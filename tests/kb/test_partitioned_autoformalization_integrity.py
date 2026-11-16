# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Adversarial integrity checks for partitioned autoformalization and merge."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

import pytest

import ruler.kb.partitioned_autoformalization as partitioning
from ruler.kb.formalization import (
    PredicateRegistry,
    PredicateSignature,
    ValueType,
    WorldAssumption,
)
from ruler.kb.generative_autoformalization import AutoformalizationRequest
from ruler.io import stable_hash
from ruler.kb.partitioned_autoformalization import (
    PartitionClaim,
    PartitionedAutoformalizationRun,
    PartitionedAutoformalizationError,
    build_claim_partition_plan,
    run_partitioned_autoformalization,
)

CLAIM_ALPHA = "Excavator alpha provides digging."
CLAIM_BETA = "Excavator beta provides digging."
SOURCE = CLAIM_ALPHA + "\n\n" + CLAIM_BETA


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _request() -> AutoformalizationRequest:
    return AutoformalizationRequest(
        request_id="partition-integrity-1",
        artifact_id="synthetic:partition-integrity",
        artifact_sha256=_sha(SOURCE),
        source_text=SOURCE,
        source_version="v1",
        context_id="partition-integrity",
        domain_id="construction_fleet",
        allowed_predicates=("resource_provides",),
        predicate_registry=PredicateRegistry(
            signatures=(
                PredicateSignature(
                    name="resource_provides",
                    argument_names=("resource",),
                    argument_types=(ValueType.ENTITY_ID,),
                    family="capability",
                    world_assumption=WorldAssumption.OPEN,
                ),
            )
        ),
    )


def _claims() -> tuple[PartitionClaim, ...]:
    return (
        PartitionClaim(
            claim_id="claim-alpha",
            predicate="resource_provides",
            exact_text=CLAIM_ALPHA,
        ),
        PartitionClaim(
            claim_id="claim-beta",
            predicate="resource_provides",
            exact_text=CLAIM_BETA,
        ),
    )


class CollisionProducer:
    """Return valid children that intentionally reuse every local identifier."""

    provider = "scripted-producer"
    model = "scripted-producer-model"
    timeout_seconds = 5

    def generate(self, *, prompt: str, output_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        request_id = re.search(r"^REQUEST_ID: (.+)$", prompt, re.MULTILINE)
        source = re.search(r"SOURCE_START\n(.*?)\nSOURCE_END", prompt, re.DOTALL)
        assert request_id is not None and source is not None
        exact_text = source.group(1)
        resource = "excavator_alpha" if "alpha" in exact_text else "excavator_beta"
        return {
            "request_id": request_id.group(1),
            "basis_id": "shared-basis",
            "program_id": "shared-program",
            "program_version": "candidate-v1",
            "spans": [
                {
                    "span_id": "shared-span",
                    "section_id": "claims",
                    "exact_text": exact_text,
                    "start_char": 0,
                    "end_char": len(exact_text),
                }
            ],
            "elements": [
                {
                    "element_id": "shared-element",
                    "kind": "proposition",
                    "predicate": "resource_provides",
                    "modality": "asserted",
                    "polarity": "positive",
                    "connective": "none",
                    "value": None,
                    "unit": None,
                    "source_span_ids": ["shared-span"],
                    "temporal": None,
                }
            ],
            "rules": [
                {
                    "statement_id": "shared-rule",
                    "modality": "fact",
                    "head": {
                        "predicate": "resource_provides",
                        "arguments": [
                            {
                                "kind": "constant",
                                "role": "resource",
                                "value_type": "entity_id",
                                "name": None,
                                "value": resource,
                                "unit": None,
                            }
                        ],
                        "classical_negation": False,
                    },
                    "body_connective": "atom",
                    "body_atoms": [],
                    "source_element_ids": ["shared-element"],
                    "source_span_ids": ["shared-span"],
                }
            ],
            "dimensions": [
                {
                    "dimension": "actors",
                    "disposition": "represented",
                    "explanation": "The named resource is represented.",
                    "query_affecting": True,
                    "element_ids": ["shared-element"],
                }
            ],
            "represented_element_ids": ["shared-element"],
            "omitted_element_ids": [],
            "symbol_mappings": [],
            "uncertainties": [],
        }


class PassingCritic:
    provider = "scripted-critic"
    model = "scripted-critic-model"

    def generate(self, *, prompt: str, output_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        case = re.search(r'"blind_case_id":\s*"([^"]+)"', prompt)
        assert case is not None
        return {"blind_case_id": case.group(1), "overall": "pass", "findings": []}


class InvalidProducer:
    provider = "invalid-producer"
    model = "invalid-producer-model"

    def generate(self, *, prompt: str, output_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"not": "a candidate"}


def _run():
    return run_partitioned_autoformalization(
        _request(),
        _claims(),
        CollisionProducer(),
        PassingCritic(),
        max_claims_per_partition=1,
        maximum_iterations=2,
    )


def _rehash_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["run_sha256"] = stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )
    return payload


def test_cross_partition_identifier_collisions_are_namespaced() -> None:
    run = _run()

    assert len(run.partition_receipts) == 2
    statement_ids = [item.statement_id for item in run.candidate.logical_program.statements]
    element_ids = [item.element_id for item in run.candidate.semantic_basis.elements]
    span_ids = [item.span_id for item in run.candidate.semantic_basis.spans]
    assert len(statement_ids) == len(set(statement_ids)) == 2
    assert len(element_ids) == len(set(element_ids)) == 2
    assert len(span_ids) == len(set(span_ids)) == 2
    assert all(item.startswith("partition-") for item in statement_ids + element_ids + span_ids)


def test_plan_rejects_duplicate_and_missing_claims() -> None:
    duplicate = (_claims()[0], _claims()[0])
    with pytest.raises(ValueError, match="identifiers must be unique"):
        build_claim_partition_plan(_request(), duplicate)

    missing = PartitionClaim(
        claim_id="claim-missing",
        predicate="resource_provides",
        exact_text="A claim absent from the authenticated source.",
    )
    with pytest.raises(ValueError, match="missing from the source"):
        build_claim_partition_plan(_request(), (missing,))


@pytest.mark.parametrize("claim_mutation", ["missing", "duplicate"])
def test_run_rejects_missing_or_duplicate_bound_claims(claim_mutation: str) -> None:
    payload = _run().model_dump(mode="json")
    if claim_mutation == "missing":
        payload["claims"] = payload["claims"][:1]
    else:
        payload["claims"] = [payload["claims"][0], payload["claims"][0]]
    _rehash_run_payload(payload)

    with pytest.raises(
        ValueError,
        match="partition plan does not match|partition claim identifiers must be unique",
    ):
        PartitionedAutoformalizationRun.model_validate(payload)


def test_nonconverged_child_fails_closed_with_refinement_evidence() -> None:
    with pytest.raises(PartitionedAutoformalizationError) as caught:
        run_partitioned_autoformalization(
            _request(),
            _claims(),
            InvalidProducer(),
            PassingCritic(),
            max_claims_per_partition=1,
            maximum_iterations=2,
        )

    assert caught.value.partition_id == "partition-001"
    assert caught.value.refinement_run is not None
    assert caught.value.refinement_run.terminal_status == "no_progress"
    assert caught.value.refinement_run.final_candidate is None


def test_merge_and_verifier_compile_the_complete_program(monkeypatch) -> None:
    original = partitioning.compile_asp
    compiled_statement_counts: list[int] = []

    def recording_compile(program, registry):
        compiled_statement_counts.append(len(program.statements))
        return original(program, registry)

    monkeypatch.setattr(partitioning, "compile_asp", recording_compile)
    run = _run()

    assert len(run.candidate.logical_program.statements) == 2
    assert compiled_statement_counts
    assert set(compiled_statement_counts) == {2}
    assert run.merge_receipt.compiler == "clingo_asp"
    assert run.merge_receipt.compiled_program_sha256.startswith("sha256:")


def test_run_rejects_rehashed_source_and_request_digest_mismatch() -> None:
    payload = _run().model_dump(mode="json")
    plan = payload["plan"]
    plan["source_artifact_sha256"] = _sha("foreign source")
    plan["request_sha256"] = stable_hash({"foreign": "request"})
    plan["plan_sha256"] = stable_hash(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    merge = payload["merge_receipt"]
    merge["plan_sha256"] = plan["plan_sha256"]
    merge["merge_sha256"] = stable_hash(
        {key: value for key, value in merge.items() if key != "merge_sha256"}
    )
    _rehash_run_payload(payload)

    with pytest.raises(ValueError, match="partition plan does not match"):
        PartitionedAutoformalizationRun.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("request_sha256", stable_hash({"foreign": "child request"}), "child request"),
        ("source_artifact_sha256", _sha("foreign child source"), "child source"),
    ],
)
def test_run_rejects_child_refinement_digest_mismatch(
    field: str, replacement: str, message: str
) -> None:
    payload = _run().model_dump(mode="json")
    receipt = payload["partition_receipts"][0]
    refinement = receipt["refinement_run"]
    refinement[field] = replacement
    refinement["run_sha256"] = stable_hash(
        {key: value for key, value in refinement.items() if key != "run_sha256"}
    )
    receipt["refinement_run_sha256"] = refinement["run_sha256"]
    merge = payload["merge_receipt"]
    merge["child_run_sha256s"][0] = refinement["run_sha256"]
    merge["merge_sha256"] = stable_hash(
        {key: value for key, value in merge.items() if key != "merge_sha256"}
    )
    _rehash_run_payload(payload)

    with pytest.raises(ValueError, match=message):
        PartitionedAutoformalizationRun.model_validate(payload)


def test_run_rejects_forged_partition_assignment_metadata() -> None:
    payload = _run().model_dump(mode="json")
    receipt = payload["partition_receipts"][0]
    receipt["predicate"] = "forged_predicate"
    receipt["claim_ids"] = ["forged-claim"]
    _rehash_run_payload(payload)

    with pytest.raises(ValueError, match="assignment metadata mismatch"):
        PartitionedAutoformalizationRun.model_validate(payload)


def test_run_rejects_internally_rehashed_merge_receipt_forgery() -> None:
    payload = _run().model_dump(mode="json")
    merge = payload["merge_receipt"]
    merge["compiled_program_sha256"] = "sha256:" + "0" * 64
    merge["merge_sha256"] = stable_hash(
        {key: value for key, value in merge.items() if key != "merge_sha256"}
    )
    _rehash_run_payload(payload)

    with pytest.raises(ValueError, match="global compiler evidence mismatch"):
        PartitionedAutoformalizationRun.model_validate(payload)
