# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import hashlib
import os

import pytest

from ruler.applications.resource_portfolio.demonstrator_formalization import (
    DEMONSTRATOR_DOSSIER_PATH,
    DEMONSTRATOR_PREDICATES,
    ExpectedClaim,
    SolverAuthorityBoundary,
    build_demonstrator_request,
    load_claim_manifest,
    load_demonstrator_dossier,
    run_demonstrator_autoformalization,
)
from ruler.io import stable_hash
from ruler.kb.generative_autoformalization import _generation_schema
from ruler.kb.partitioned_autoformalization import (
    PartitionClaim,
    build_claim_partition_plan,
)
from ruler.applications.resource_portfolio.demonstrator_synthetic_kb import (
    SyntheticClaimAnchor,
    build_expanded_claim_catalogue,
    generate_expanded_synthetic_kb,
)


def test_realistic_dossier_builds_a_closed_source_locked_request() -> None:
    source = load_demonstrator_dossier()
    request = build_demonstrator_request(source_text=source)

    assert "This dossier is entirely synthetic" in source
    assert "The owned 35-tonne excavator called Atlas" in source
    assert "requires independently mobilizable backup" in source
    assert "Only separately reviewed rules marked approved" in source
    assert request.allowed_predicates == DEMONSTRATOR_PREDICATES
    assert {item.name for item in request.predicate_registry.signatures} == set(
        DEMONSTRATOR_PREDICATES
    )
    assert request.artifact_sha256 == "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert DEMONSTRATOR_DOSSIER_PATH.is_file()
    claims, planning_projection = load_claim_manifest()
    assert {item.predicate for item in claims} >= {
        "resource_provides",
        "activity_requires",
        "resource_eligible",
        "backup_required",
    }
    assert planning_projection.generated_candidate_dependency is False
    assert set(planning_projection.approved_input_files) >= {"model.yaml", "schedule.yaml"}


def test_solver_authority_boundary_is_fail_closed_and_digest_bound() -> None:
    digest = stable_hash({"candidate": "example"})
    boundary = SolverAuthorityBoundary(candidate_digest=digest)

    assert boundary.candidate_lifecycle == "candidate_uncommitted"
    assert boundary.activation_status == "blocked"
    assert boundary.solver_use_permitted is False
    with pytest.raises(ValueError, match="hash must use sha256"):
        SolverAuthorityBoundary(candidate_digest="not-a-digest")


def test_live_output_schema_requires_every_declared_object_property() -> None:
    request = build_demonstrator_request(source_text=load_demonstrator_dossier())
    schema = _generation_schema(request)

    def assert_strict_objects(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                assert value.get("required") == list(properties)
            for child in value.values():
                assert_strict_objects(child)
        elif isinstance(value, list):
            for child in value:
                assert_strict_objects(child)

    assert_strict_objects(schema)


def test_expanded_claims_form_four_deterministic_semantic_partitions() -> None:
    base_source = load_demonstrator_dossier()
    base_claims, _ = load_claim_manifest()
    expanded = generate_expanded_synthetic_kb(base_source)
    catalogue = build_expanded_claim_catalogue(
        expanded,
        (
            SyntheticClaimAnchor(
                claim_id=item.claim_id,
                predicate=item.predicate,
                exact_text=item.exact_text,
                expected_constant_values=item.expected_constant_values,
            )
            for item in base_claims
        ),
    )
    claims = tuple(
        ExpectedClaim(
            claim_id=item.claim_id,
            predicate=item.predicate,
            exact_text=item.exact_text,
            expected_constant_values=item.expected_constant_values,
        )
        for item in catalogue
    )
    request = build_demonstrator_request(
        source_text=expanded.source_text,
        request_id="expanded-partition-plan-test",
        source_version="synthetic-expanded-dossier-2026-09-04",
        max_output_tokens=16_000,
    )
    plan = build_claim_partition_plan(
        request,
        tuple(
            PartitionClaim(
                claim_id=item.claim_id,
                predicate=item.predicate,
                exact_text=item.exact_text,
            )
            for item in claims
        ),
        max_claims_per_partition=16,
    )

    assert len(plan.claim_ids) == 43
    assert [(item.predicate, len(item.claim_ids)) for item in plan.partitions] == [
        ("resource_provides", 14),
        ("activity_requires", 11),
        ("resource_eligible", 13),
        ("backup_required", 5),
    ]
    assert [item.partition_id for item in plan.partitions] == [
        "partition-001",
        "partition-002",
        "partition-003",
        "partition-004",
    ]
    assert all(
        "Formalize every assigned claim exactly once" in item.guidance[1]
        for item in plan.partitions
    )
    assert max(item.source_character_count for item in plan.partitions) < len(expanded.source_text)


@pytest.mark.skipif(
    os.environ.get("RULER_RUN_LIVE_PORTFOLIO_DEMONSTRATOR") != "1",
    reason="explicit unmocked Codex demonstrator execution",
)
def test_live_demonstrator_uses_real_transport_and_stays_blocked() -> None:
    run = run_demonstrator_autoformalization(model=os.environ.get("RULER_CODEX_MODEL", "gpt-5.4"))

    assert run.candidate.receipt.provider == "codex-exec"
    assert run.candidate.projection.activation_status == "blocked"
    assert run.solver_authority.solver_use_permitted is False
    assert len(run.checks) >= 5
    assert run.refinement.terminal_status == "converged"
    assert len(run.refinement.iterations) in {1, 2, 3}
    assert all(item.critic_receipt is not None for item in run.refinement.iterations)
    assert run.refinement.iterations[-1].critic_verdict == "pass"
