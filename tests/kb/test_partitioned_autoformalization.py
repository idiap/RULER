# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Focused tests for scalable, deterministic candidate partitioning and merge."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

import pytest

from ruler.io import stable_hash
from ruler.kb.formalization import (
    PredicateRegistry,
    PredicateSignature,
    ValueType,
    WorldAssumption,
)
from ruler.kb.generative_autoformalization import AutoformalizationRequest
from ruler.kb.partitioned_autoformalization import (
    PartitionClaim,
    PartitionedAutoformalizationError,
    build_claim_partition_plan,
    run_partitioned_autoformalization,
)

SOURCE = "Atlas provides excavation.\nBoreas provides hauling."


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _request(source: str = SOURCE) -> AutoformalizationRequest:
    predicates = ("resource_provides", "backup_required")
    return AutoformalizationRequest(
        request_id="fleet-expanded",
        artifact_id="fleet-dossier",
        artifact_sha256=_sha(source),
        source_text=source,
        source_version="v1",
        context_id="fleet",
        domain_id="construction_fleet",
        allowed_predicates=predicates,
        predicate_registry=PredicateRegistry(
            signatures=tuple(
                PredicateSignature(
                    name=name,
                    argument_names=("resource",),
                    argument_types=(ValueType.ENTITY_ID,),
                    family="test",
                    world_assumption=WorldAssumption.OPEN,
                )
                for name in predicates
            )
        ),
    )


def _claims() -> tuple[PartitionClaim, ...]:
    return (
        PartitionClaim(
            claim_id="claim-atlas",
            predicate="resource_provides",
            exact_text="Atlas provides excavation.",
        ),
        PartitionClaim(
            claim_id="claim-boreas",
            predicate="backup_required",
            exact_text="Boreas provides hauling.",
        ),
    )


class ClaimProducer:
    provider = "live-producer-boundary"
    model = "producer-model"
    timeout_seconds = 5

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, output_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        self.prompts.append(prompt)
        request_id = re.search(r"REQUEST_ID: ([^\n]+)", prompt).group(1)  # type: ignore[union-attr]
        predicate = re.search(r"This partition is limited to predicate '([^']+)'", prompt).group(
            1
        )  # type: ignore[union-attr]
        source = prompt.split("SOURCE_START\n", 1)[1].split("\nSOURCE_END", 1)[0]
        resource = "atlas" if source.startswith("Atlas") else "boreas"
        return {
            "request_id": request_id,
            "basis_id": "basis",
            "program_id": "program",
            "program_version": "v1",
            "spans": [
                {
                    "span_id": "span",
                    "section_id": "facts",
                    "exact_text": source,
                    "start_char": 0,
                    "end_char": len(source),
                }
            ],
            "elements": [
                {
                    "element_id": "element",
                    "kind": "proposition",
                    "predicate": predicate,
                    "modality": "asserted",
                    "polarity": "positive",
                    "connective": "none",
                    "value": None,
                    "unit": None,
                    "source_span_ids": ["span"],
                    "temporal": None,
                }
            ],
            "rules": [
                {
                    "statement_id": "fact",
                    "modality": "fact",
                    "head": {
                        "predicate": predicate,
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
                    "source_element_ids": ["element"],
                    "source_span_ids": ["span"],
                }
            ],
            "dimensions": [
                {
                    "dimension": "actors",
                    "disposition": "represented",
                    "explanation": "Typed resource constant.",
                    "query_affecting": True,
                    "element_ids": ["element"],
                }
            ],
            "represented_element_ids": ["element"],
            "omitted_element_ids": [],
            "symbol_mappings": [],
            "uncertainties": [],
        }


class PassingCritic:
    provider = "live-blind-critic-boundary"
    model = "critic-model"

    def generate(self, *, prompt: str, output_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        blind_id = re.search(r'"blind_case_id":\s*"([^"]+)"', prompt).group(1)  # type: ignore[union-attr]
        return {"blind_case_id": blind_id, "overall": "pass", "findings": []}


class InvalidProducer:
    provider = "failing-producer-boundary"
    model = "producer-model"

    def generate(self, *, prompt: str, output_schema: Mapping[str, Any]) -> Mapping[str, Any]:
        return {}


def test_plan_groups_predicate_families_before_fixed_size_chunking() -> None:
    source_claims: list[str] = []
    claims: list[PartitionClaim] = []
    counts = {"resource_provides": 14, "backup_required": 5}
    for predicate, count in counts.items():
        for index in range(count):
            exact = f"Unique {predicate} claim number {index}."
            source_claims.append(exact)
            claims.append(
                PartitionClaim(
                    claim_id=f"{predicate}-{index}", predicate=predicate, exact_text=exact
                )
            )
    source = "\n".join(source_claims)

    plan = build_claim_partition_plan(_request(source), tuple(claims), max_claims_per_partition=8)

    assert [item.predicate for item in plan.partitions] == [
        "resource_provides",
        "resource_provides",
        "backup_required",
    ]
    assert [len(item.claim_ids) for item in plan.partitions] == [8, 6, 5]
    assert all(item.source_character_count < len(source) for item in plan.partitions)


def test_partitioned_run_reanchors_namespaces_reparses_and_compiles_globally() -> None:
    producer = ClaimProducer()
    run = run_partitioned_autoformalization(
        _request(),
        _claims(),
        producer,
        PassingCritic(),
        max_claims_per_partition=1,
        max_workers=2,
    )

    assert run.terminal_status == "converged"
    assert len(run.partition_receipts) == 2
    assert [item.partition_id for item in run.partition_receipts] == [
        "partition-001",
        "partition-002",
    ]
    assert all(receipt.child_request.source_text != SOURCE for receipt in run.partition_receipts)
    assert all(
        receipt.refinement_run.iterations[-1].critic_verdict == "pass"
        for receipt in run.partition_receipts
    )
    assert {item.statement_id for item in run.candidate.logical_program.statements} == {
        "partition-001::fact",
        "partition-002::fact",
    }
    assert {item.start_char for item in run.candidate.semantic_basis.spans} == {
        0,
        SOURCE.index("Boreas"),
    }
    assert all(
        item.artifact_id == "fleet-dossier" and item.artifact_sha256 == _sha(SOURCE)
        for item in run.candidate.semantic_basis.spans
    )
    assert run.candidate.receipt.provider == "deterministic-partition-merge"
    assert run.merge_receipt.provider_authority == "none_deterministic_merge"
    assert run.merge_receipt.compiler == "clingo_asp"
    assert run.merge_receipt.child_run_sha256s == tuple(
        item.refinement_run.run_sha256 for item in run.partition_receipts
    )
    assert run.lifecycle == "candidate_uncommitted"
    assert run.solver_use_permitted is False


def test_duplicate_or_missing_claims_fail_before_any_provider_call() -> None:
    producer = ClaimProducer()
    duplicate = (_claims()[0], _claims()[0])
    with pytest.raises(ValueError, match="identifiers must be unique"):
        run_partitioned_autoformalization(_request(), duplicate, producer, PassingCritic())
    missing = PartitionClaim(
        claim_id="missing",
        predicate="resource_provides",
        exact_text="This sentence is absent.",
    )
    with pytest.raises(ValueError, match="missing from the source"):
        run_partitioned_autoformalization(_request(), (missing,), producer, PassingCritic())
    assert not producer.prompts


def test_nonconverged_partition_fails_closed_with_child_run_receipt() -> None:
    with pytest.raises(PartitionedAutoformalizationError) as caught:
        run_partitioned_autoformalization(
            _request(), (_claims()[0],), InvalidProducer(), PassingCritic()
        )

    assert caught.value.partition_id == "partition-001"
    assert caught.value.refinement_run is not None
    assert caught.value.refinement_run.terminal_status == "no_progress"
    assert caught.value.refinement_run.final_candidate is None


def test_plan_digest_detects_partition_assignment_tampering() -> None:
    plan = build_claim_partition_plan(_request(), _claims(), max_claims_per_partition=1)
    payload = plan.model_dump(mode="json")
    payload["partitions"][0]["claim_ids"] = ["claim-boreas"]
    # Keeping either the child assignment hash or the aggregate hash is insufficient.
    payload["plan_sha256"] = stable_hash(
        {key: value for key, value in payload.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValueError):
        type(plan).model_validate(payload)
