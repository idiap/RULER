# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Digest-closed stage graph for the deterministic formal reasoning flow."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256


class FormalStageKind(StrEnum):
    SOURCE = "source"
    SEMANTICS = "semantics"
    INTERPRETATION = "interpretation"
    PROJECTION = "projection"
    EXECUTION = "execution"
    CERTIFICATE = "certificate"
    REVIEW = "review"
    RELEASE = "release"


_ORDER = tuple(FormalStageKind)


class FormalStage(StrictContract):
    stage_id: str
    kind: FormalStageKind
    performed_by: str = Field(min_length=1)
    input_digests: tuple[str, ...]
    output_digest: str
    status: Literal["pending", "blocked", "completed"]
    blockers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def digests_are_canonical(self) -> "FormalStage":
        for value in (*self.input_digests, self.output_digest):
            validate_sha256(value)
        if self.status == "completed" and self.blockers:
            raise ValueError("completed formal stage cannot retain blockers")
        return self


class FormalHandoff(StrictContract):
    producer_stage_id: str
    consumer_stage_id: str
    artifact_digest: str

    @model_validator(mode="after")
    def digest_is_canonical(self) -> "FormalHandoff":
        validate_sha256(self.artifact_digest)
        return self


class FormalFlowRun(StrictContract):
    run_id: str
    stages: tuple[FormalStage, ...] = Field(min_length=1)
    handoffs: tuple[FormalHandoff, ...]
    release_authorized: bool = False

    @model_validator(mode="after")
    def graph_is_closed_and_ordered(self) -> "FormalFlowRun":
        ids = [item.stage_id for item in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("formal stage IDs must be unique")
        by_id = {item.stage_id: item for item in self.stages}
        output_digests = [item.output_digest for item in self.stages]
        if len(output_digests) != len(set(output_digests)):
            raise ValueError("formal stage outputs must have unique digests")
        produced: dict[str, str] = {}
        adjacency: dict[str, set[str]] = {item: set() for item in ids}
        for handoff in self.handoffs:
            if handoff.producer_stage_id not in by_id or handoff.consumer_stage_id not in by_id:
                raise ValueError("formal handoff references an unknown stage")
            producer = by_id[handoff.producer_stage_id]
            consumer = by_id[handoff.consumer_stage_id]
            if handoff.artifact_digest != producer.output_digest:
                raise ValueError("formal handoff digest does not match producer output")
            if handoff.artifact_digest not in consumer.input_digests:
                raise ValueError("formal handoff digest is absent from consumer inputs")
            prior = produced.setdefault(handoff.artifact_digest, producer.stage_id)
            if prior != producer.stage_id:
                raise ValueError("formal artifact has duplicate producers")
            if _ORDER.index(producer.kind) >= _ORDER.index(consumer.kind):
                raise ValueError("formal handoff violates stage order")
            adjacency[producer.stage_id].add(consumer.stage_id)
        if _cyclic(adjacency):
            raise ValueError("formal stage graph contains a cycle")
        if self.release_authorized:
            required = set(_ORDER)
            completed = {item.kind for item in self.stages if item.status == "completed"}
            if required - completed:
                raise ValueError("release requires every formal stage to complete")
            kinds = [item.kind for item in self.stages]
            if len(kinds) != len(required) or set(kinds) != required:
                raise ValueError("release requires exactly one stage of every formal kind")
            if any(item.blockers for item in self.stages):
                raise ValueError("release cannot be authorized with blockers")
            by_kind = {item.kind: item for item in self.stages}
            handoff_keys = {
                (item.producer_stage_id, item.consumer_stage_id, item.artifact_digest)
                for item in self.handoffs
            }
            for producer_kind, consumer_kind in zip(_ORDER, _ORDER[1:]):
                producer = by_kind[producer_kind]
                consumer = by_kind[consumer_kind]
                expected = (producer.stage_id, consumer.stage_id, producer.output_digest)
                if expected not in handoff_keys:
                    raise ValueError("release requires an unbroken adjacent-stage digest chain")
            if (
                by_kind[FormalStageKind.REVIEW].performed_by
                == by_kind[FormalStageKind.RELEASE].performed_by
            ):
                raise ValueError("review and release must have independent authorities")
        return self


def _cyclic(adjacency: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in adjacency[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in adjacency)
