# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Contract tests for the CBR skill catalogue and governed workflow plans."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from ruler.cbr.workflow import (
    CBRWorkflowRequest,
    CBRWorkflowStage,
    CaseLibraryCurationRequest,
    LibraryAction,
    build_cbr_workflow,
    execute_cbr_workflow,
)
from ruler.paths import REPO_ROOT
from ruler.runtime.skill_inventory import discover_skill_files

SHA = "sha256:" + "a" * 64
SHARED_SKILLS = {
    "cbr-case-intake-normalizer",
    "cbr-similarity-profile-curator",
    "cbr-case-retriever",
    "cbr-retrieval-auditor",
    "cbr-adaptation-planner",
    "cbr-formal-verification-gate",
    "cbr-outcome-retention-curator",
    "cbr-demonstration-artifact-builder",
}
DOMAIN_SKILLS = {
    "spending-procurement-case-specialist",
    "regulatory-deployment-case-specialist",
    "fiscal-vat-case-specialist",
    "trade-export-control-case-specialist",
    "technical-support-case-specialist",
}
WORKFLOW_SKILLS = {"cbr-case-workflow-orchestrator", "cbr-case-library-curator"}


def request(**overrides: object) -> CBRWorkflowRequest:
    payload: dict[str, object] = {
        "case_id": "query-1",
        "domain_id": "spending",
        "case_library_release_id": "cases-v1",
        "case_library_release_sha256": SHA,
        "rule_release_id": "rules-v1",
        "rule_release_sha256": SHA,
        "similarity_profile_sha256": SHA,
        "authorized_fields": frozenset({"amount", "approval"}),
    }
    payload.update(overrides)
    return CBRWorkflowRequest.model_validate(payload)


def test_all_cbr_skills_are_discoverable_and_have_explicit_boundaries() -> None:
    inventory = discover_skill_files()
    expected = SHARED_SKILLS | DOMAIN_SKILLS | WORKFLOW_SKILLS
    assert expected <= set(inventory)
    for name in expected:
        text = inventory[name].path.read_text(encoding="utf-8")
        assert "## Input contracts" in text
        assert "## Output artifacts" in text
        assert "## Prohibited inferences" in text
        assert "## Files owned" in text
        assert "## Validation" in text
        assert "uv run ruler validate cbr" in text


def test_workflow_manifest_declares_gate_order_and_separate_retention() -> None:
    payload = yaml.safe_load(
        (REPO_ROOT / "data/use_cases/cbr_workflows.yaml").read_text(encoding="utf-8")
    )
    case_workflow = payload["workflows"][0]
    assert [step["id"] for step in case_workflow["stages"]] == [
        "intake",
        "retrieve",
        "audit",
        "adapt",
        "verify",
        "review",
        "retain",
    ]
    assert all(not item["mutation"] for item in case_workflow["stages"][:-1])
    assert case_workflow["stages"][-1] == {
        "id": "retain",
        "skill": "cbr-outcome-retention-curator",
        "mutation": True,
        "confirmation_required": True,
        "separately_invoked": True,
    }


def test_decision_workflow_is_read_only_by_default() -> None:
    plan = build_cbr_workflow(request())
    assert tuple(step.stage for step in plan.steps) == (
        CBRWorkflowStage.INTAKE,
        CBRWorkflowStage.RETRIEVE,
        CBRWorkflowStage.AUDIT,
        CBRWorkflowStage.ADAPT,
        CBRWorkflowStage.VERIFY,
        CBRWorkflowStage.REVIEW,
    )
    assert not any(step.mutates_case_library for step in plan.steps)
    assert "spending-procurement-case-specialist" in plan.steps[0].skill


@pytest.mark.parametrize(
    ("domain_id", "specialist"),
    [
        ("spending", "spending-procurement-case-specialist"),
        ("regulatory", "regulatory-deployment-case-specialist"),
        ("fiscal", "fiscal-vat-case-specialist"),
        ("trade", "trade-export-control-case-specialist"),
        ("technical_support", "technical-support-case-specialist"),
    ],
)
def test_each_demo_domain_is_routed_through_its_specialist(domain_id: str, specialist: str) -> None:
    plan = build_cbr_workflow(request(domain_id=domain_id))
    assert plan.steps[0].skill == f"cbr-case-intake-normalizer+{specialist}"
    assert plan.steps[4].skill == "cbr-formal-verification-gate"


def test_retention_requires_distinct_confirmation_and_reviewer() -> None:
    with pytest.raises(ValidationError, match="separately confirmed"):
        request(retain_observation=True)
    with pytest.raises(ValidationError, match="reviewer"):
        request(retain_observation=True, retention_confirmed=True)
    plan = build_cbr_workflow(
        request(
            retain_observation=True,
            retention_confirmed=True,
            reviewer_ref="reviewer-2",
        )
    )
    assert plan.steps[-1].stage == CBRWorkflowStage.RETAIN
    assert plan.steps[-1].mutates_case_library
    assert plan.steps[-1].confirmation_required


def test_unknown_domain_is_rejected_before_workflow_execution() -> None:
    with pytest.raises(ValueError, match="unsupported CBR domain"):
        build_cbr_workflow(request(domain_id="retired_application"))


def test_orchestrator_calls_every_gate_in_order() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            def call(payload: tuple[str, ...]) -> tuple[str, ...]:
                self.calls.append(name)
                return (*payload, name)

            return call

    service = Recorder()
    artifacts = execute_cbr_workflow(build_cbr_workflow(request()), service, ())
    assert service.calls == ["intake", "retrieve", "audit", "adapt", "verify", "review"]
    assert artifacts[-1][1] == tuple(service.calls)


def test_case_library_publication_requires_deidentification_review_and_confirmation() -> None:
    with pytest.raises(ValidationError, match="de-identification"):
        CaseLibraryCurationRequest(
            library_id="lib",
            actions=(LibraryAction.IMPORT, LibraryAction.PUBLISH),
            source_authorized=True,
            independent_reviewer_ref="reviewer-2",
            publication_confirmed=True,
        )
    valid = CaseLibraryCurationRequest(
        library_id="lib",
        actions=(
            LibraryAction.IMPORT,
            LibraryAction.DEIDENTIFY,
            LibraryAction.REVIEW,
            LibraryAction.PUBLISH,
        ),
        source_authorized=True,
        independent_reviewer_ref="reviewer-2",
        publication_confirmed=True,
    )
    assert valid.actions[-1] == LibraryAction.PUBLISH


def test_case_library_retirement_is_separately_confirmed() -> None:
    with pytest.raises(ValidationError, match="retirement requires"):
        CaseLibraryCurationRequest(
            library_id="lib",
            actions=(LibraryAction.RETIRE,),
            source_authorized=True,
        )
