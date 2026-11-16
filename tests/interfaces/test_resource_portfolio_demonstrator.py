# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ruler.applications.resource_portfolio.workflow import (
    execute_resource_portfolio_workflow,
)
from ruler.applications.resource_portfolio.argumentation import (
    build_decision_argument_certificate,
)
from ruler.applications.resource_portfolio.compiler import CompilationReport
from ruler.applications.resource_portfolio.demonstrator import (
    _demonstrator_inputs,
    _write_inputs,
)
from ruler.applications.resource_portfolio.explanation_records import (
    CoverageExclusion,
    ScenarioCoverageDeclaration,
    build_cost_objective_explanation,
    build_scenario_envelope_explanation,
)
from ruler.applications.resource_portfolio.optimization import VerifiedPlan
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    CounterfactualRun,
    ScenarioSet,
    StressReport,
)
from ruler.interfaces.resource_portfolio_demonstrator import (
    _load_accepted_kb_texts,
    render_resource_portfolio_demonstrator_html,
    write_resource_portfolio_demonstrator_report,
)
from ruler.paths import REPO_ROOT
from ruler.io import read_yaml, stable_hash

FIXTURES = REPO_ROOT / "data" / "domains" / "construction_fleet" / "tests"


def _dossier() -> dict[str, object]:
    return {
        "title": "AlpineBuild weekly fleet decision",
        "scenario_id": "alpinebuild_week_37",
        "synthetic": True,
        "narrative_sections": [
            {
                "section_id": "facts-1",
                "title": "Available fleet",
                "kind": "facts",
                "text": "Excavator EX-104 is ready at Rivergate.",
            },
            {
                "section_id": "rules-1",
                "title": "Capacity policy",
                "kind": "rules",
                "text": "At least two excavation units must be available. <script>alert(1)</script>",
            },
        ],
    }


def _formalization(
    artifact_dir: Path | None = None,
    model: dict[str, object] | None = None,
) -> dict[str, object]:
    candidate = {
        "request_id": "request:alpinebuild_week_37",
        "lifecycle": "candidate_uncommitted",
        "logical_program": {
            "program_id": "program:alpinebuild_week_37",
            "version": "1",
            "statements": [{"statement_id": "statement-1"}],
        },
        "projection": {
            "target_formalism": "asp",
            "activation_status": "blocked",
            "activation_blockers": [{"blocker_id": "review-required"}],
            "dimensions": [{"dimension": "quantities", "disposition": "represented"}],
        },
        "receipt": {
            "provider": "codex-exec",
            "model": "configured-model",
            "attempts": 2,
            "response_sha256": "sha256:" + "a" * 64,
        },
    }
    value: dict[str, object] = {
        "candidate": candidate,
        "refinement": {
            "attempts": 2,
            "events": ["schema correction", "deterministic validation passed"],
        },
        "grounding": {
            "source_spans_authenticated": True,
            "predicate_registry_closed": True,
        },
        "candidate_visualization": {
            "visualizer_id": "candidate-kb:test",
            "title": "Test candidate rules",
            "lifecycle": "candidate_uncommitted",
            "publication_status": "not_published",
            "solver_authority": "blocked",
            "boundary_notice": "Review-only test candidate.",
            "request_id": candidate["request_id"],
            "artifact_id": "synthetic:test",
            "source_version": "v1",
            "source_text": "Test source",
            "source_artifact_sha256": "sha256:" + "b" * 64,
            "target_formalism": "asp",
            "candidate_digest": stable_hash(candidate),
            "program_digest": "sha256:" + "c" * 64,
            "summary": {
                "source_characters": 11,
                "exact_spans": 1,
                "semantic_elements": 1,
                "rules": 1,
                "facts": 1,
                "dependencies": 0,
                "activation_blockers": 1,
            },
            "spans": [
                {
                    "span_id": "span-1",
                    "exact_text": "Test source",
                    "start_char": 0,
                    "end_char": 11,
                    "artifact_sha256": "sha256:" + "b" * 64,
                    "verification": "exact_source_match",
                }
            ],
            "elements": [
                {
                    "element_id": "element-1",
                    "kind": "proposition",
                    "predicate": "resource_provides",
                    "modality": "asserted",
                    "polarity": "positive",
                    "connective": "none",
                    "source_span_ids": ["span-1"],
                    "formalization_unit_ids": ["statement-1"],
                }
            ],
            "rules": [
                {
                    "statement_id": "statement-1",
                    "modality": "fact",
                    "compiled_asp": "resource_provides(test).",
                    "head_predicate": "resource_provides",
                    "body_predicates": [],
                    "source_element_ids": ["element-1"],
                    "source_span_ids": ["span-1"],
                }
            ],
            "graph_edges": [
                {
                    "source_id": "span-1",
                    "target_id": "element-1",
                    "relation": "grounds",
                }
            ],
            "projection_dimensions": [],
            "activation_blockers": [],
            "uncertainties": [],
            "audit_hash": "sha256:" + "d" * 64,
        },
    }
    if artifact_dir is not None:
        compilation = CompilationReport.model_validate(
            read_yaml(artifact_dir / "compilation.yaml")["payload"]
        )
        plan = VerifiedPlan.model_validate(read_yaml(artifact_dir / "plan.yaml")["payload"])
        counterfactual = CounterfactualRun.model_validate(
            read_yaml(artifact_dir / "counterfactual.yaml")["payload"]
        )
        model = model or read_yaml(FIXTURES / "model.yaml")
        changes = tuple(
            CounterfactualChange.model_validate(item) for item in model["counterfactual"]["changes"]
        )
        argument = build_decision_argument_certificate(
            compilation.problem,
            plan,
            policy_counterfactual=counterfactual,
            policy_changes=changes,
            candidate_kb_digest=stable_hash(candidate),
            seed=int(model["seed"]),
        )
        value["decision_argument"] = argument.model_dump(mode="json")
        stress_payload = dict(read_yaml(artifact_dir / "stress.yaml")["payload"])
        scenario_set = ScenarioSet.model_validate(stress_payload.pop("scenario_set"))
        stress = StressReport.model_validate(stress_payload)
        value["scenario_envelope_explanation"] = build_scenario_envelope_explanation(
            compilation.problem,
            scenario_set,
            stress,
            ScenarioCoverageDeclaration(
                coverage_id="test-envelope",
                planning_horizon="annual test horizon",
                investigated_question="Does the assignment change?",
                exclusions=(
                    CoverageExclusion(
                        dimension="weather",
                        reason="not represented",
                        origin_refs=("review:test",),
                    ),
                ),
                origin_refs=("review:test",),
            ),
            certificate=argument,
        ).model_dump(mode="json")
        value["cost_objective_explanation"] = build_cost_objective_explanation(
            compilation.problem,
            plan,
            objective_id=compilation.problem.objectives[0].objective_id,
            time_basis="annual test horizon",
            time_basis_origin_refs=("review:test",),
            certificate=argument,
        ).model_dump(mode="json")
    return value


def test_report_renders_values_from_real_verified_solver_artifacts(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    input_dir = tmp_path / "inputs"
    payloads = _demonstrator_inputs()
    _write_inputs(payloads, input_dir)
    execute_resource_portfolio_workflow(input_dir, artifact_dir)

    rendered = render_resource_portfolio_demonstrator_html(
        _dossier(), _formalization(artifact_dir, payloads["model.yaml"]), artifact_dir
    )

    assert "<!doctype html>" in rendered
    assert "AlpineBuild weekly fleet decision" in rendered
    assert "<title>Cost Optimization for Machine Portfolio</title>" in rendered
    assert "<h1>Cost Optimization for Machine Portfolio</h1>" in rendered
    assert 'role="tablist"' in rendered
    assert 'aria-controls="decision-panel"' in rendered
    assert 'aria-controls="knowledge-panel"' in rendered
    assert "Decision and trade-offs" in rendered
    assert "Accepted facts and rules" in rendered
    assert "Autoformalized facts</dt><dd>1" in rendered
    assert "Autoformalized rules</dt><dd>0" in rendered
    assert "Diagnostic configurations</dt><dd>13" in rendered
    assert "1102400.0 CHF" in rendered
    assert "retain_atlas" in rendered
    assert "Rock Bench Cut" in rendered
    assert "The project programme and its machine portfolio" in rendered
    assert "Projects, work types, and eligible machine pool" in rendered
    assert "From operating commitments to a defensible fleet decision" in rendered
    assert "Where the cost optimization" in rendered
    assert "unchanged approved model" in rendered
    assert "rental-price stress scenarios" in rendered
    assert "annual multi-project programme" in rendered
    assert "36 activities scheduled" in rendered
    assert "North Logistics Park" in rendered
    assert "Rivergate Flood Defence" in rendered
    assert "Valais Wind Access" in rendered
    assert "Lakeview Hospital Enabling" in rendered
    assert "Central Fleet Support" in rendered
    assert "Planning day 47" in rendered
    assert 'id="policy-cost-title"' in rendered
    assert "Increment attributed to the independent-backup policy" in rendered
    assert 'id="schedule-chart-title"' in rendered
    assert (
        'aria-label="Annual Gantt chart of 36 scheduled activities across 6 projects"' in rendered
    )
    assert 'id="stress-chart-title"' in rendered
    assert "Annual cost exposure by rental-rate" in rendered
    assert "quoted_rate" in rendered and "rental_scarcity" in rendered
    assert "Certified conclusion" in rendered
    assert "What the unchanged approved model proves" in rendered
    assert "same-model" in rendered
    assert "different policy model, not a runner-up" in rendered
    assert "changes from" in rendered
    assert "did not govern" in rendered
    assert "variable" in rendered and "constraint" in rendered
    assert "accepted, executable formal KB" in rendered
    assert "cannot silently create portfolio constraints" in rendered
    assert 'href="accepted_rules.html"' not in rendered
    assert 'href="synthetic_dossier.md"' not in rendered
    assert 'href="accepted_kb.lp"' not in rendered
    assert 'href="accepted_kb.pl"' not in rendered
    assert "linked technical explorer" not in rendered
    assert "grid-template-columns" not in rendered
    assert "Source-commented accepted facts and rules" in rendered
    assert "% Fact: statement-1" in rendered
    assert "% Source: Test source" in rendered
    assert "resource_provides(test)." in rendered
    assert "The decision is a two-option" in rendered
    assert "A decision tree would imply sequential" in rendered
    assert "13 diagnostic configurations were executed" in rendered
    assert "Solver outcomes" in rendered
    assert "OPTIMAL: 3" in rendered
    assert "finite, declared investigation rather than an exhaustive search" in rendered
    assert "Parameter Stress</th><td>3" in rendered
    assert "Same Model Exclusion</th><td>1" in rendered
    assert "Variable Forcedness</th><td>4" in rendered
    assert "Constraint Ablation</th><td>4" in rendered
    assert "Policy Sensitivity</th><td>1" in rendered
    assert "base portfolio solve" in rendered and "annual CP-SAT schedule" in rendered
    assert "HiGHS" in rendered
    assert "Z3" in rendered
    assert "What was actually investigated" in rendered
    assert "Outside this experiment" in rendered
    assert "Where the annual optimization cost comes from" in rendered
    assert "bounded annual working-day model" in rendered
    assert "grid-template-columns" not in rendered
    assert "sha256:" not in rendered
    assert "Verified workflow manifest" not in rendered
    assert "Refinement record" not in rendered
    assert "Grounding checks" not in rendered
    assert "candidate_uncommitted" not in rendered
    assert "codex-exec / configured-model" not in rendered
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered

    output_path = tmp_path / "report" / "index.html"
    assert (
        write_resource_portfolio_demonstrator_report(
            _dossier(),
            _formalization(artifact_dir, payloads["model.yaml"]),
            artifact_dir,
            output_path,
        )
        == output_path
    )
    assert output_path.read_text(encoding="utf-8") == rendered


def test_report_requires_synthetic_source_and_candidate_boundary(tmp_path: Path) -> None:
    dossier = _dossier()
    dossier["synthetic"] = False
    with pytest.raises(ValueError, match="synthetic must be true"):
        render_resource_portfolio_demonstrator_html(
            dossier, _formalization(), tmp_path / "not-read"
        )

    formalization = _formalization()
    candidate = formalization["candidate"]
    assert isinstance(candidate, dict)
    candidate["lifecycle"] = "active"
    with pytest.raises(ValueError, match="candidate_uncommitted"):
        render_resource_portfolio_demonstrator_html(
            _dossier(), formalization, tmp_path / "not-read"
        )


def test_embedded_kb_text_must_match_accepted_content_digest(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    accepted = "% accepted\nresource_provides(test).\n"
    (tmp_path / "accepted_kb.lp").write_text(accepted, encoding="utf-8")
    artifact = SimpleNamespace(
        filename="accepted_kb.lp",
        formalism="asp",
        content_sha256="sha256:" + hashlib.sha256(accepted.encode()).hexdigest(),
    )
    receipt = SimpleNamespace(artifacts=(artifact,))

    assert _load_accepted_kb_texts(workflow_dir, receipt) == {"asp": accepted}

    (tmp_path / "accepted_kb.lp").write_text("% tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        _load_accepted_kb_texts(workflow_dir, receipt)
