# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Verified, self-contained HTML report for the resource-portfolio demonstrator.

The renderer is intentionally downstream of artifact verification.  It does not
recalculate or embellish decisions: every displayed operational value is read from
the authenticated workflow artifacts, while source and autoformalization material is
rendered verbatim from the caller-supplied demonstration record.
"""

from __future__ import annotations

import html
import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ruler.applications.resource_portfolio import contracts as portfolio_contracts
from ruler.applications.resource_portfolio.argumentation import (
    DecisionArgumentCertificate,
    validate_decision_argument_certificate,
)
from ruler.applications.resource_portfolio.compiler import CompilationReport
from ruler.applications.resource_portfolio.explanations import PortfolioExplanation
from ruler.applications.resource_portfolio.explanation_records import (
    CostObjectiveExplanation,
    ScenarioEnvelopeExplanation,
)
from ruler.applications.resource_portfolio.demonstrator_approved_kb import (
    AcceptedFormalKBReceipt,
)
from ruler.applications.resource_portfolio.optimization import VerifiedPlan
from ruler.applications.resource_portfolio.robustness import CounterfactualRun, StressReport
from ruler.applications.resource_portfolio.scheduling import (
    SchedulingProblem,
    SchedulingResult,
)
from ruler.applications.resource_portfolio.workflow import verify_workflow_artifacts
from ruler.interfaces.autoformalization_visualizer import CandidateKBVisualization
from ruler.io import read_yaml, stable_hash, write_text
from ruler.kb.logical_ir import LogicalProgram


def render_resource_portfolio_demonstrator_html(
    dossier: Mapping[str, Any] | BaseModel,
    formalization: Mapping[str, Any] | BaseModel,
    artifact_dir: Path,
) -> str:
    """Render one report from a synthetic dossier and a verified workflow run.

    ``artifact_dir`` must be a complete output directory produced by
    :func:`execute_resource_portfolio_workflow`.  Verification is performed before
    any content is rendered, so a tampered or partial run fails closed.
    """
    dossier_data = _mapping(dossier, "dossier")
    formalization_data = _mapping(formalization, "formalization")
    title = _required_text(dossier_data, "title", "dossier")
    scenario_id = _required_text(dossier_data, "scenario_id", "dossier")
    if dossier_data.get("synthetic") is not True:
        raise ValueError("dossier.synthetic must be true for this demonstrator")
    sections = _dossier_sections(dossier_data)
    candidate, refinement, grounding = _formalization_parts(formalization_data)
    accepted_formal_kb_data = formalization_data.get("accepted_formal_kb")
    accepted_formal_kb = (
        AcceptedFormalKBReceipt.model_validate(accepted_formal_kb_data)
        if accepted_formal_kb_data is not None
        else None
    )
    generative_explanation_data = formalization_data.get("generative_explanation")

    run = verify_workflow_artifacts(artifact_dir)
    artifacts = _load_artifact_payloads(artifact_dir, run.artifacts)
    snapshot = portfolio_contracts.ImmutableSnapshot.model_validate(
        artifacts["immutable_planning_snapshot"]
    )
    compilation = CompilationReport.model_validate(artifacts["compilation_report"])
    plan = VerifiedPlan.model_validate(artifacts["verified_plan"])
    schedule_data = dict(artifacts["scheduling_result"])
    schedule_problem = SchedulingProblem.model_validate(schedule_data.pop("problem"))
    schedule = SchedulingResult.model_validate(schedule_data)
    stress_data = dict(artifacts["stress_report"])
    stress_data.pop("scenario_set")
    stress = StressReport.model_validate(stress_data)
    explanation_data = dict(artifacts["deterministic_explanation"])
    explanation_evidence = _mapping(explanation_data.pop("evidence"), "explanation.evidence")
    PortfolioExplanation.model_validate(explanation_data)
    generative_explanation = (
        PortfolioExplanation.model_validate(generative_explanation_data)
        if generative_explanation_data is not None
        else None
    )
    if generative_explanation is not None and (
        generative_explanation.receipt.mode != "generative"
        or not generative_explanation.candidate_only
        or generative_explanation.receipt.evidence_digest
        != explanation_evidence.get("evidence_digest")
    ):
        raise ValueError("generative explanation is not a trace-bound candidate")
    review = _mapping(artifacts["human_review_gate"], "review")
    argument = DecisionArgumentCertificate.model_validate(
        formalization_data.get("decision_argument")
    )
    scenario_explanation_data = formalization_data.get("scenario_envelope_explanation")
    scenario_explanation = (
        ScenarioEnvelopeExplanation.model_validate(scenario_explanation_data)
        if scenario_explanation_data is not None
        else None
    )
    cost_explanation_data = formalization_data.get("cost_objective_explanation")
    cost_explanation = (
        CostObjectiveExplanation.model_validate(cost_explanation_data)
        if cost_explanation_data is not None
        else None
    )
    validate_decision_argument_certificate(compilation.problem, plan, argument, replay_solves=False)
    if argument.authority.candidate_kb_digest != stable_hash(candidate):
        raise ValueError("decision argument is not bound to the displayed candidate KB")
    if (
        scenario_explanation is not None
        and scenario_explanation.base_model_digest != compilation.problem.digest
    ):
        raise ValueError("scenario explanation is not bound to the displayed model")
    if (
        scenario_explanation is not None
        and scenario_explanation.scenario_set_digest != stress.scenario_set_digest
    ):
        raise ValueError("scenario explanation is not bound to the displayed stress run")
    if cost_explanation is not None and cost_explanation.model_digest != compilation.problem.digest:
        raise ValueError("cost explanation is not bound to the displayed model")
    if (
        cost_explanation is not None
        and cost_explanation.result_semantic_digest != plan.result.semantic_digest
    ):
        raise ValueError("cost explanation is not bound to the displayed verified plan")

    objective_unit = compilation.problem.objectives[0].unit
    formal_kb_texts = _load_accepted_kb_texts(artifact_dir, accepted_formal_kb)
    fact_count, rule_count = _formal_statement_counts(
        candidate, formalization_data.get("candidate_visualization")
    )
    configuration_count = _diagnostic_configuration_count(argument, stress, scenario_explanation)
    e = html.escape

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Cost Optimization for Machine Portfolio</title>
  <style>{_STYLE}</style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to report</a>
  <header class="hero">
    <div class="hero-inner">
      <p class="eyebrow">RULER · grounded neuro-symbolic demonstrator</p>
      <h1>Cost Optimization for Machine Portfolio</h1>
      <p class="lede">A decision argument derived from reviewed requirements,
      independently verified optimization results, and explicit counterfactuals.</p>
      <p class="context-title">{e(title)}</p>
      <div class="badges" aria-label="Report status">
        <span class="badge synthetic">Synthetic dossier</span>
        <span class="badge verified">Argument certificate validated</span>
      </div>
      <dl class="identity">
        <div><dt>As of</dt><dd>{e(snapshot.as_of.isoformat())}</dd></div>
        <div><dt>Decision context</dt><dd>{e(scenario_id.replace('_', ' '))}</dd></div>
      </dl>
      <dl class="report-summary" aria-label="Report summary">
        <div><dt>Autoformalized facts</dt><dd>{fact_count}</dd></div>
        <div><dt>Autoformalized rules</dt><dd>{rule_count}</dd></div>
        <div><dt>Diagnostic configurations</dt><dd>{configuration_count}</dd></div>
      </dl>
    </div>
  </header>
  <main id="main">
    <nav class="report-tabs" role="tablist" aria-label="Report views">
      <button id="decision-tab" role="tab" aria-selected="true"
        aria-controls="decision-panel">Decision and trade-offs</button>
      <button id="knowledge-tab" role="tab" aria-selected="false"
        aria-controls="knowledge-panel" tabindex="-1">Accepted facts and rules</button>
    </nav>
    <div id="decision-panel" class="tab-panel" role="tabpanel"
      aria-labelledby="decision-tab">
    <section aria-labelledby="programme-heading" class="section programme-context">
      <div class="section-heading">
        <p class="eyebrow">Enterprise context</p>
        <h2 id="programme-heading">The project programme and its machine portfolio</h2>
      </div>
      {_render_enterprise_context(schedule_problem, plan)}
    </section>

    <section aria-labelledby="question-heading" class="section decision">
      <div class="section-heading">
        <p class="eyebrow">Decision question</p><h2 id="question-heading">Must the independent rock-backup policy be retained at its modeled {e(_objective_period(argument.objective_id))} cost?</h2>
      </div>
      {_render_policy_tradeoff(argument)}
      {_render_certified_conclusion(argument, compilation, review)}
    </section>

    <section aria-labelledby="cost-origin-heading" class="section">
      <div class="section-heading"><p class="eyebrow">Cost provenance</p>
      <h2 id="cost-origin-heading">Where the annual optimization cost comes from</h2></div>
      {_render_cost_origin(cost_explanation) if cost_explanation is not None else _render_cost_origin_boundary()}
    </section>

    <section aria-labelledby="reasoning-heading" class="section reasoning-context">
      <div class="section-heading">
        <p class="eyebrow">Reasoning and investigation</p>
        <h2 id="reasoning-heading">From operating commitments to a defensible fleet decision</h2>
      </div>
      {_render_reasoning_method(argument, compilation, schedule_problem, stress)}
      {_render_configuration_extent(argument, stress, scenario_explanation)}
    </section>

    <section aria-labelledby="proof-heading" class="section">
      <div class="section-heading"><p class="eyebrow">Formal derivation</p>
      <h2 id="proof-heading">What the unchanged approved model proves</h2></div>
      {_render_argument_proof(argument, compilation, plan)}
    </section>

    <section aria-labelledby="sensitivity-heading" class="section">
      <div class="section-heading"><p class="eyebrow">Changed-policy sensitivity</p>
      <h2 id="sensitivity-heading">The cost of requiring independent rock backup</h2></div>
      {_render_policy_sensitivity(argument)}
    </section>

    <section aria-labelledby="source-heading" class="section">
      <div class="section-heading"><p class="eyebrow">Natural-language evidence</p>
      <h2 id="source-heading">Decision-relevant facts and approved projection</h2></div>
      <div class="source-list">{_render_decision_sources(sections)}</div>
    </section>

    <section aria-labelledby="model-heading" class="section">
      <div class="section-heading"><p class="eyebrow">Reviewed formal model</p>
      <h2 id="model-heading">The representation that actually governed the solve</h2></div>
      {_render_constraints(plan)}
      {_render_constraint_roles(argument)}
    </section>

    <section aria-labelledby="schedule-heading" class="section">
      <div class="section-heading"><p class="eyebrow">Bounded operational check</p>
      <h2 id="schedule-heading">A feasible annual multi-project programme</h2></div>
      <p>The CP-SAT plan coordinates {len(schedule_problem.tasks)} mandatory activities
      across {len({item.project_id for item in schedule_problem.tasks})} concurrent
      programmes and shared company resources. It enforces capability eligibility,
      project sequence, selected mobilization lags, supervision and dispatch capacity,
      maintenance capacity, and frozen commitments.</p>
      {_render_schedule_scope(schedule_problem)}
      {_render_schedule(schedule, schedule_problem)}
    </section>

    <section aria-labelledby="stress-heading" class="section">
      <div class="section-heading"><p class="eyebrow">Commercial stress</p>
      <h2 id="stress-heading">Assignments stay fixed while cost exposure changes</h2></div>
      <p>Because the approved requirements force all four selections, the tested
      rental-price scenarios change the objective value, not the portfolio.</p>
      {_render_scenario_envelope(scenario_explanation) if scenario_explanation is not None else ''}
      {_render_stress(stress, objective_unit, argument.objective_id)}
    </section>

    <section aria-labelledby="review-heading" class="section method">
      <div class="section-heading"><p class="eyebrow">Decision for the reviewer</p>
      <h2 id="review-heading">Confirm or revise the backup policy</h2></div>
      <p>The model does not choose whether independent backup is worth its price; it
      proves the consequence of the approved policy. The fleet director must decide
      whether the resilience requirement justifies the certified incremental
      cost shown above.</p>
      <p class="gate"><strong>Human authorization:</strong> required from
      {e(str(review['required_role']))} before operational or commercial action.</p>
    </section>
    </div>

    <div id="knowledge-panel" class="tab-panel" role="tabpanel"
      aria-labelledby="knowledge-tab" hidden>
      <section aria-labelledby="formal-heading" class="section boundary">
        <div class="section-heading"><p class="eyebrow">Autoformalization record</p>
        <h2 id="formal-heading">An accepted, executable formal KB</h2></div>
        {_render_formalization_summary(
            candidate, refinement, grounding,
            formalization_data.get("candidate_visualization"),
            accepted_formal_kb,
            formal_kb_texts,
        )}
        {_render_generative_explanation(generative_explanation)}
      </section>
    </div>
  </main>
  <footer><p>This report describes a synthetic demonstration. Its recommendation remains
  advisory and requires review by <strong>{e(str(review['required_role']))}</strong>.</p></footer>
  <script>{_TAB_SCRIPT}</script>
</body>
</html>
"""


def write_resource_portfolio_demonstrator_report(
    dossier: Mapping[str, Any] | BaseModel,
    formalization: Mapping[str, Any] | BaseModel,
    artifact_dir: Path,
    output_path: Path,
) -> Path:
    """Verify the run, write its standalone HTML report, and return the path."""
    rendered = render_resource_portfolio_demonstrator_html(dossier, formalization, artifact_dir)
    write_text(output_path, rendered)
    return output_path


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(value)


def _required_text(value: Mapping[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{label}.{key} must be non-blank text")
    return result


def _dossier_sections(dossier: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_sections = dossier.get("narrative_sections")
    if raw_sections is None:
        source = _required_text(dossier, "source_text", "dossier")
        return _markdown_source_sections(source)
    if not isinstance(raw_sections, Sequence) or isinstance(raw_sections, (str, bytes)):
        raise ValueError("dossier.narrative_sections must be a list")
    sections: list[dict[str, str]] = []
    for index, raw in enumerate(raw_sections, start=1):
        if isinstance(raw, str):
            if not raw.strip():
                raise ValueError("dossier narrative section text must be non-blank")
            sections.append(
                {
                    "section_id": str(index),
                    "title": f"Section {index}",
                    "kind": "source",
                    "text": raw,
                }
            )
            continue
        item = _mapping(raw, f"dossier.narrative_sections[{index - 1}]")
        text = _required_text(item, "text", "dossier narrative section")
        sections.append(
            {
                "section_id": str(item.get("section_id", item.get("id", index))),
                "title": str(item.get("title", item.get("kind", f"Section {index}"))),
                "kind": str(item.get("kind", "source")),
                "text": text,
            }
        )
    if not sections:
        raise ValueError("dossier narrative sections cannot be empty")
    return sections


def _markdown_source_sections(source: str) -> list[dict[str, str]]:
    """Split the demonstrator's Markdown headings without interpreting inline HTML."""
    sections: list[dict[str, str]] = []
    title = "Source text"
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            sections.append(
                {
                    "section_id": f"source-{len(sections) + 1}",
                    "title": title,
                    "kind": "source section",
                    "text": text,
                }
            )

    for line in source.splitlines():
        if line.startswith("## "):
            flush()
            title = line[3:].strip()
            body = []
        elif line.startswith("# ") and not sections and not body:
            continue
        else:
            body.append(line)
    flush()
    if not sections:
        sections.append(
            {
                "section_id": "source-1",
                "title": "Source text",
                "kind": "source section",
                "text": source,
            }
        )
    return sections


def _formalization_parts(
    formalization: Mapping[str, Any],
) -> tuple[dict[str, Any], Any, Any]:
    candidate = _mapping(formalization.get("candidate", formalization), "candidate")
    _required_text(candidate, "request_id", "candidate")
    if candidate.get("lifecycle") != "candidate_uncommitted":
        raise ValueError("formalization candidate must remain candidate_uncommitted")
    for key in ("logical_program", "projection", "receipt"):
        if not isinstance(candidate.get(key), Mapping):
            raise ValueError(f"candidate.{key} must be a mapping")
    refinement = formalization.get("refinement", formalization.get("refinement_events"))
    grounding = formalization.get("grounding", formalization.get("grounding_checks"))
    if refinement is None or grounding is None:
        raise ValueError("formalization requires refinement and grounding metadata")
    grounding_record = {
        "deterministic_checks": formalization.get("checks", ()),
        "claim_coverage": formalization.get("expected_claim_coverage", ()),
        "solver_authority": formalization.get("solver_authority", {}),
        "planning_input_projection": formalization.get("planning_input_projection", {}),
        "reviewed_source_bindings": grounding,
    }
    return candidate, refinement, grounding_record


def _load_artifact_payloads(artifact_dir: Path, artifacts: Sequence[Any]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for artifact in artifacts:
        envelope = read_yaml(artifact_dir / artifact.relative_path)
        payloads[artifact.artifact_type] = envelope["payload"]
    return payloads


def _load_accepted_kb_texts(
    artifact_dir: Path, receipt: AcceptedFormalKBReceipt | None
) -> dict[str, str]:
    """Load only digest-authenticated KB bytes for inline, standalone rendering."""

    if receipt is None:
        return {}
    texts: dict[str, str] = {}
    for artifact in receipt.artifacts:
        paths = (
            artifact_dir / artifact.filename,
            artifact_dir.parent / artifact.filename,
        )
        path = next((item for item in paths if item.is_file()), None)
        if path is None:
            raise ValueError(f"accepted formal KB artifact is missing: {artifact.filename}")
        value = path.read_text(encoding="utf-8")
        digest = "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
        if digest != artifact.content_sha256:
            raise ValueError(f"accepted formal KB artifact digest mismatch: {artifact.filename}")
        texts[artifact.formalism] = value
    return texts


def _formal_statement_counts(
    candidate: Mapping[str, Any], candidate_visualization: Any
) -> tuple[int, int]:
    """Count executable facts and rules without guessing from rendered source text."""

    program = _mapping(candidate["logical_program"], "candidate.logical_program")
    statements = program.get("statements", ())
    modalities = [str(item.get("modality", "")) for item in statements if isinstance(item, Mapping)]
    if modalities and all(modalities):
        facts = sum(value == "fact" for value in modalities)
        return facts, len(modalities) - facts
    visualization = CandidateKBVisualization.model_validate(candidate_visualization)
    facts = sum(str(item.modality) == "fact" for item in visualization.rules)
    return facts, len(visualization.rules) - facts


def _diagnostic_configuration_count(
    argument: DecisionArgumentCertificate,
    stress: StressReport,
    explanation: ScenarioEnvelopeExplanation | None,
) -> int:
    """Return the exact number of authenticated diagnostic re-solves."""

    if explanation is not None:
        return sum(item.run_count for item in explanation.executed_analysis_classes)
    return (
        len(stress.outcomes)
        + 1
        + len(argument.variable_forcedness)
        + len(argument.constraint_roles)
        + (1 if argument.policy_sensitivity is not None else 0)
    )


def _render_configuration_extent(
    argument: DecisionArgumentCertificate,
    stress: StressReport,
    explanation: ScenarioEnvelopeExplanation | None,
) -> str:
    """Communicate finite experiment coverage from validated execution records."""

    if explanation is not None:
        rows = "".join(
            "<tr>"
            f"<th scope='row'>{html.escape(_human_identifier(item.analysis_kind))}</th>"
            f"<td>{item.run_count}</td>"
            "<td>"
            + html.escape(
                ", ".join(f"{status}: {count}" for status, count in item.statuses.items())
            )
            + "</td>"
            f"<td>{'changed model' if item.changes_approved_model else 'unchanged model'}</td>"
            "</tr>"
            for item in explanation.executed_analysis_classes
        )
    else:
        fallback = (
            ("Parameter stress", len(stress.outcomes), "changed model"),
            ("Same model exclusion", 1, "unchanged model"),
            ("Variable forcedness", len(argument.variable_forcedness), "unchanged model"),
            ("Constraint ablation", len(argument.constraint_roles), "changed model"),
            (
                "Policy sensitivity",
                1 if argument.policy_sensitivity is not None else 0,
                "changed model",
            ),
        )
        rows = "".join(
            f"<tr><th scope='row'>{label}</th><td>{count}</td>"
            f"<td>recorded in solver artifacts</td><td>{model}</td></tr>"
            for label, count, model in fallback
        )
    total = _diagnostic_configuration_count(argument, stress, explanation)
    return f"""
      <article class="configuration-extent">
        <h3>{total} diagnostic configurations were executed</h3>
        <p>This is a finite, declared investigation rather than an exhaustive search
        over every possible market or operating condition. Each count below comes
        from an authenticated solver result. The verified base portfolio solve and
        annual CP-SAT schedule are separate foundation runs and are not padded into
        this diagnostic total.</p>
        <table><caption>Executed diagnostic configurations</caption>
          <thead><tr><th scope="col">Analysis</th><th scope="col">Runs</th>
          <th scope="col">Solver outcomes</th>
          <th scope="col">Model relationship</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </article>
    """


def _render_source_section(section: Mapping[str, str]) -> str:
    e = html.escape
    paragraphs = "".join(
        f"<p>{e(part.strip())}</p>" for part in section["text"].split("\n\n") if part.strip()
    )
    return f"""<article class="source-card">
      <h3>{e(section['title'])}</h3>{paragraphs}</article>"""


def _render_decision_sources(sections: Sequence[Mapping[str, str]]) -> str:
    wanted = {
        "Work facts and requirements",
        "Commercial and scheduling observations",
        "Decision policy",
        "Reviewer-approved planning projection",
    }
    chosen = [dict(item) for item in sections if item["title"] in wanted]
    for item in chosen:
        if item["title"] == "Reviewer-approved planning projection":
            paragraphs = [
                paragraph
                for paragraph in item["text"].split("\n\n")
                if not paragraph.startswith("The mandatory activity ")
            ]
            item["text"] = "\n\n".join(paragraphs)
    return "".join(_render_source_section(item) for item in chosen or sections[:3])


def _render_enterprise_context(problem: SchedulingProblem, plan: VerifiedPlan) -> str:
    """Describe the programme-to-machine relationship from scheduling artifacts."""

    tasks_by_project: dict[str, list[Any]] = {}
    for task in problem.tasks:
        tasks_by_project.setdefault(task.project_id, []).append(task)
    rows = []
    for project_id, tasks in sorted(tasks_by_project.items()):
        capabilities = sorted(
            {capability for task in tasks for capability in task.required_capability_ids}
        )
        eligible_resources = sorted(
            {resource for task in tasks for resource in task.eligible_resource_ids}
        )
        activity_names = [_human_identifier(task.task_id) for task in tasks]
        rows.append(
            "<tr>"
            f"<th scope='row'>{html.escape(_human_identifier(project_id))}</th>"
            f"<td>{len(tasks)} activities: {html.escape(', '.join(activity_names))}</td>"
            f"<td>{html.escape(', '.join(_human_identifier(item) for item in capabilities))}</td>"
            f"<td>{html.escape(', '.join(_human_identifier(item) for item in eligible_resources))}</td>"
            "</tr>"
        )
    selected = [
        _human_variable(variable_id)
        for variable_id, value in sorted(plan.result.assignments.items())
        if value != 0
    ]
    scheduled_resources = {
        resource for task in problem.tasks for resource in task.eligible_resource_ids
    }
    return f"""
      <p>The annual programme contains <strong>{len(tasks_by_project)} projects</strong>
      with <strong>{len(problem.tasks)} mandatory activities</strong>. Their work spans
      {len({capability for task in problem.tasks for capability in task.required_capability_ids})}
      declared capability classes and can draw on {len(scheduled_resources)} eligible
      company or rental resources.</p>
      <p>The planning problem has two linked layers. The portfolio model determines
      whether to {html.escape(', '.join(selected))} under the approved capacity and
      backup rules. The scheduling model is bound to that verified plan and tests
      whether dated project activities can be assigned to eligible machinery without
      violating project sequence, shared-capacity, travel, or frozen-commitment rules.
      Its wider eligible resource pool supports delivery of the enterprise programme;
      it does not add decision variables to the {len(plan.result.assignments)}-item
      commercial portfolio.</p>
      <table><caption>Projects, work types, and eligible machine pool</caption>
        <thead><tr><th scope="col">Project</th><th scope="col">Planned work</th>
        <th scope="col">Required capabilities</th><th scope="col">Eligible resources</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    """


def _render_reasoning_method(
    argument: DecisionArgumentCertificate,
    compilation: CompilationReport,
    schedule: SchedulingProblem,
    stress: StressReport,
) -> str:
    """Explain the reasoning layers and investigated scenario classes."""

    objective = compilation.problem.objectives[0]
    decision_terms = len(objective.expression.terms)
    policy_variant = (
        "one changed-policy re-solve"
        if argument.policy_sensitivity
        else "no changed-policy re-solve"
    )
    return f"""
      <p>The central question is not simply which machine is cheapest. The company
      must preserve hard operational capabilities across several projects, respect an
      independent-backup policy, test whether the resulting fleet can support the
      annual programme, and expose the cost of changing that policy.</p>
      <ol class="reasoning-steps">
        <li><strong>Ground and delimit the problem.</strong> Natural-language facts and
        rules are autoformalized as a review candidate. Only the separately reviewed
        optimization projection receives solver authority.</li>
        <li><strong>Compile and prove the base-policy result.</strong> Z3 first checks
        satisfiability of the approved hard symbolic projection. HiGHS then minimizes
        its {html.escape(_objective_period(objective.objective_id))} cost expression over
        {decision_terms} retain-or-reserve terms. Independent arithmetic and constraint
        replay verify the returned assignment.</li>
        <li><strong>Test the argument, not just the answer.</strong> Opposite-value,
        no-good, and constraint-ablation re-solves distinguish a feasibility-forced
        portfolio from a cost-preferred portfolio and identify what each rule changes.</li>
        <li><strong>Test operational realization.</strong> CP-SAT assigns the annual
        activity set in {html.escape(schedule.time_unit.replace('_', ' '))} units while
        enforcing resource eligibility, precedence, travel, capacity, and frozen work.</li>
        <li><strong>Separate scenario meanings.</strong> The analysis includes the
        unchanged approved model, its same-model alternative test, {policy_variant},
        and {len(stress.outcomes)} rental-price stress scenarios. A policy variant is
        never presented as a runner-up from the base model.</li>
      </ol>
      <article class="boundary-note"><p><strong>Where the cost optimization comes
      from:</strong> each reviewed retain-or-reserve variable has an attributable cost
      coefficient, plus any unavoidable constant cost. The schedule establishes
      operational feasibility; it does not invent those prices or silently add
      scheduling activity costs to the commercial objective.</p></article>
    """


def _objective_period(objective_id: str) -> str:
    lowered = objective_id.lower()
    for period in ("annual", "monthly", "weekly", "daily"):
        if period in lowered:
            return period
    return "modeled"


def _render_certified_conclusion(
    argument: DecisionArgumentCertificate,
    compilation: CompilationReport,
    review: Mapping[str, Any],
) -> str:
    selected = [
        _human_variable(variable_id)
        for variable_id, value in sorted(argument.selected_assignment.items())
        if value == 1
    ]
    if argument.decision_class == "unique_feasible":
        finding = (
            "The approved requirements force one feasible portfolio: "
            + ", ".join(selected)
            + ". The objective evaluates that forced point; it does not choose it "
            "over another feasible base-policy portfolio."
        )
    elif argument.decision_class == "cost_preferred":
        finding = (
            "The approved model admits another feasible portfolio, but the verified "
            "objective prefers this selection by "
            f"{argument.same_model_alternative.objective_gap} {argument.objective_unit}."
        )
    else:
        finding = (
            "The approved model has multiple equally optimal portfolios. This is one "
            "verified optimum and must not be presented as uniquely preferred."
        )
    return f"""<article class="decision-point">
      <span class="label">Certified conclusion · {html.escape(argument.decision_class)}</span>
      <h3>{html.escape(finding)}</h3>
      <p>The verified {html.escape(_objective_period(argument.objective_id))} cost is
      <strong>{html.escape(_quantity(argument.selected_objective_value, argument.objective_unit))}</strong>.</p>
      {_render_cost_equation(argument, compilation)}
      <p class="gate"><strong>Status:</strong> advisory, pending authorization by
      {html.escape(str(review['required_role']))}.</p>
    </article>"""


def _render_cost_equation(
    argument: DecisionArgumentCertificate, compilation: CompilationReport
) -> str:
    objective = compilation.problem.objectives[0]
    parts = []
    if objective.expression.constant:
        parts.append(str(objective.expression.constant))
    parts.extend(
        str(term.coefficient)
        for term in objective.expression.terms
        if argument.selected_assignment[term.variable_id] == 1
    )
    return (
        "<p><strong>Cost decomposition:</strong> <code>"
        + html.escape(" + ".join(parts))
        + " = "
        + html.escape(str(argument.selected_objective_value))
        + f" {html.escape(argument.objective_unit)}</code>.</p>"
    )


def _render_cost_origin(record: CostObjectiveExplanation) -> str:
    rows = []
    for term in record.terms:
        rows.append(
            "<tr>"
            f"<th scope='row'><code>{html.escape(term.variable_id)}</code></th>"
            f"<td>{html.escape(_quantity(term.coefficient, record.objective_unit))}</td>"
            f"<td>{html.escape(str(term.selected_value))}</td>"
            f"<td>{html.escape(_quantity(term.contribution, record.objective_unit))}</td>"
            f"<td><code>{html.escape(term.grounding_span_id or 'not grounded')}</code></td>"
            "</tr>"
        )
    contrast_rows = []
    for contrast in record.contrasts:
        label = (
            "Changed-policy sensitivity"
            if contrast.changes_approved_model
            else "Same-model alternative"
        )
        contrast_rows.append(
            "<tr>"
            f"<th scope='row'>{label}</th>"
            f"<td>{'yes' if contrast.available else 'no'}</td>"
            f"<td>{html.escape(_quantity(contrast.compared_objective_value, record.objective_unit))}</td>"
            f"<td>{html.escape(_quantity(contrast.selected_minus_compared, record.objective_unit))}</td>"
            "</tr>"
        )
    return f"""
      <p>This is a <strong>{html.escape(record.time_basis)}</strong> objective reconstructed
      from the reviewed constant and variable coefficients. The independent verifier
      closes the arithmetic at <strong>{html.escape(_quantity(record.verified_objective_value, record.objective_unit))}</strong>;
      grounding is <strong>{'complete' if record.grounding_complete else 'incomplete'}</strong>.</p>
      <table><caption>Selected-term contribution to the verified objective</caption>
        <thead><tr><th scope="col">Decision variable</th><th scope="col">Annual coefficient</th>
        <th scope="col">Selected value</th><th scope="col">Contribution</th><th scope="col">Grounded span</th></tr></thead>
        <tbody><tr><th scope="row">Unavoidable constant</th>
        <td>{html.escape(_quantity(record.constant.constant, record.objective_unit))}</td><td>1</td>
        <td>{html.escape(_quantity(record.constant.contribution, record.objective_unit))}</td>
        <td><code>{html.escape(record.constant.grounding_span_id or 'not grounded')}</code></td></tr>
        {''.join(rows)}</tbody>
      </table>
      <table><caption>Do not conflate the two cost comparisons</caption>
        <thead><tr><th scope="col">Comparison</th><th scope="col">Available</th>
        <th scope="col">Compared cost</th><th scope="col">Selected minus compared</th></tr></thead>
        <tbody>{''.join(contrast_rows)}</tbody>
      </table>
    """


def _render_policy_tradeoff(argument: DecisionArgumentCertificate) -> str:
    """Show the one policy choice as an argument map, not a branching decision tree."""

    sensitivity = argument.policy_sensitivity
    if sensitivity is None:
        return ""
    base = argument.selected_objective_value
    variant = sensitivity.verification.objective_values[argument.objective_id]
    delta = sensitivity.objective_delta
    return f"""<figure class="tradeoff-map" aria-labelledby="tradeoff-map-title">
      <figcaption id="tradeoff-map-title"><strong>The decision is a two-option
      policy trade-off</strong><br><small>A decision tree would imply sequential
      branches. Here, management chooses between two explicit policy definitions.</small></figcaption>
      <article class="tradeoff-option retained">
        <span class="label">Option A · approved policy</span>
        <h3>Retain independent rock backup</h3>
        <p>Preserves the modeled resilience requirement. The verified portfolio costs
        <strong>{html.escape(_quantity(base, argument.objective_unit))}</strong>.</p>
      </article>
      <p class="tradeoff-versus" aria-hidden="true">versus</p>
      <article class="tradeoff-option relaxed">
        <span class="label">Option B · changed policy</span>
        <h3>Relax independent rock backup</h3>
        <p>Removes that modeled protection. The re-solved portfolio costs
        <strong>{html.escape(_quantity(variant, argument.objective_unit))}</strong>,
        changing modeled cost by
        <strong>{html.escape(_quantity(delta, argument.objective_unit))}</strong>.</p>
      </article>
      <p class="tradeoff-question"><strong>Management judgment:</strong> is the
      retained resilience worth the certified incremental modeled cost?</p>
    </figure>"""


def _render_cost_origin_boundary() -> str:
    return (
        "<p>The objective coefficients are the reviewed commercial inputs shown in "
        "the formal derivation. No separate digest-closed cost-provenance record was "
        "supplied to this renderer.</p>"
    )


def _render_scenario_envelope(record: ScenarioEnvelopeExplanation) -> str:
    ranges = ", ".join(
        f"{_human_identifier(item.parameter_id)}: "
        f"{', '.join(str(value) for value in item.tested_values)}×"
        for item in record.tested_parameters
    )
    classes = "".join(
        "<li><strong>"
        + html.escape(_human_identifier(item.analysis_kind))
        + f":</strong> {item.run_count} executed re-solve(s); "
        + (
            "changes the approved model"
            if item.changes_approved_model
            else "keeps the approved model unchanged"
        )
        + ".</li>"
        for item in record.executed_analysis_classes
    )
    exclusions = "".join(
        f"<li><strong>{html.escape(item.dimension.capitalize())}:</strong> "
        f"{html.escape(item.reason)}</li>"
        for item in record.exclusions
    )
    stability = (
        "The assignment was stable across every solved scenario."
        if record.assignment_stable_across_tested_scenarios
        else f"The solved scenarios produced {record.distinct_assignment_count} distinct assignments."
    )
    return f"""
      <article class="boundary-note">
        <h3>What was actually investigated</h3>
        <p>{html.escape(record.investigated_question)} The finite envelope contains
        <strong>{record.scenario_count} price cases</strong> over {html.escape(ranges)}.
        {html.escape(stability)}</p>
        <ul>{classes}</ul>
        <h4>Outside this experiment</h4><ul>{exclusions}</ul>
      </article>
    """


def _render_argument_proof(
    argument: DecisionArgumentCertificate,
    compilation: CompilationReport,
    plan: VerifiedPlan,
) -> str:
    forced = "".join(
        f"<li><code>{html.escape(item.variable_id)}</code> = {item.selected_value}: "
        "the opposite value makes the approved model infeasible.</li>"
        for item in argument.variable_forcedness
        if item.feasibility_forced
    )
    alternative = argument.same_model_alternative
    if alternative.decision_class == "unique_feasible":
        comparison = (
            "A no-good re-solve excluded the complete selected assignment and proved "
            "the remaining approved model infeasible. There is therefore no same-model "
            "runner-up."
        )
    else:
        comparison = (
            "A no-good re-solve found a distinct same-model assignment at "
            f"{alternative.alternative_objective_value} {argument.objective_unit}, "
            f"with objective gap {alternative.objective_gap} {argument.objective_unit}."
        )
    return f"""
      <p>{html.escape(comparison)}</p>
      <h3>Variable forcedness</h3><ul class="evidence-list">{forced}</ul>
      <p>Each statement above comes from a real opposite-value HiGHS re-solve. The
      selected point and its cost were independently replayed against the
      {len(compilation.problem.constraints)} hard constraints.</p>
      {_render_assignments(plan)}
    """


def _render_policy_sensitivity(argument: DecisionArgumentCertificate) -> str:
    sensitivity = argument.policy_sensitivity
    if sensitivity is None:
        return "<p>No changed-policy sensitivity is certified.</p>"
    objective_id = argument.objective_id
    changed = (
        ", ".join(
            f"{_human_variable(variable_id)} changes from {before} to {after}"
            for variable_id, (before, after) in sorted(sensitivity.changed_assignments.items())
        )
        or "the selected variables do not change"
    )
    variant_value = sensitivity.verification.objective_values[objective_id]
    delta = sensitivity.objective_delta
    direction = "decrease" if delta < 0 else "increase"
    change_text = "; ".join(
        f"{item.kind} {item.target_id} to {item.value}" for item in sensitivity.changes
    )
    return f"""{_render_policy_cost_chart(argument)}
    <article class="boundary-note">
      <p><strong>This is a different policy model, not a runner-up.</strong> The tested
      transformation changes {html.escape(change_text)}. The re-solve gives
      <strong>{html.escape(_quantity(variant_value, argument.objective_unit))}</strong>;
      {html.escape(changed)}.</p>
      <p>Relative to the approved base policy, that is a certified cost {direction} of
      <strong>{html.escape(_quantity(abs(delta), argument.objective_unit))}</strong>.
      The practical review question is whether independent backup justifies that
      incremental cost.</p>
    </article>"""


def _render_policy_cost_chart(argument: DecisionArgumentCertificate) -> str:
    sensitivity = argument.policy_sensitivity
    if sensitivity is None:
        return ""
    base = argument.selected_objective_value
    variant = sensitivity.verification.objective_values[argument.objective_id]
    maximum = max(abs(base), abs(variant), 1)
    base_width = float(abs(base) * 100 / maximum)
    variant_width = float(abs(variant) * 100 / maximum)
    delta = abs(sensitivity.objective_delta)
    return f"""<figure class="chart" aria-labelledby="policy-cost-title">
      <figcaption id="policy-cost-title"><strong>{html.escape(_objective_period(argument.objective_id).title())} modeled cost under the two
      policy definitions</strong><br><small>These bars compare different models; the
      relaxed-policy result is not a base-policy alternative.</small></figcaption>
      {_bar_row("Approved backup policy", base, argument.objective_unit, base_width, "base")}
      {_bar_row("Backup requirement relaxed", variant, argument.objective_unit, variant_width, "variant")}
      <p class="chart-callout">Increment attributed to the independent-backup policy:
      <strong>{html.escape(_quantity(delta, argument.objective_unit))}</strong></p>
    </figure>"""


def _bar_row(label: str, value: Any, unit: str, width: float, tone: str) -> str:
    return f"""<div class="bar-row">
      <span class="bar-label">{html.escape(label)}</span>
      <span class="bar-track" aria-hidden="true"><i class="{tone}" style="width:{width:.3f}%"></i></span>
      <strong>{html.escape(_quantity(value, unit))}</strong>
    </div>"""


def _render_constraint_roles(argument: DecisionArgumentCertificate) -> str:
    rows = "".join(
        "<tr>"
        f"<th scope='row'><code>{html.escape(item.constraint_id)}</code></th>"
        f"<td>{'yes' if item.binding_at_selected_point else 'no'}</td>"
        f"<td>{html.escape(item.role.replace('_', ' '))}</td>"
        f"<td>{html.escape(_quantity(item.objective_delta, argument.objective_unit))}</td>"
        "</tr>"
        for item in argument.constraint_roles
    )
    return f"""<table><caption>Ablation-tested constraint roles</caption>
      <thead><tr><th>Constraint</th><th>Binding</th><th>Certified role</th><th>Cost change if removed</th></tr></thead>
      <tbody>{rows}</tbody></table>
      <p><em>Binding</em> reports equality at the selected point. The role is derived
      separately by removing the constraint and re-solving; equality alone is not
      treated as causal evidence.</p>"""


def _render_formalization_summary(
    candidate: Mapping[str, Any],
    refinement: Any,
    grounding: Any,
    candidate_visualization: Any,
    formal_kb: AcceptedFormalKBReceipt | None,
    formal_kb_texts: Mapping[str, str],
) -> str:
    program = _mapping(candidate["logical_program"], "candidate.logical_program")
    projection = _mapping(candidate["projection"], "candidate.projection")
    visualization = CandidateKBVisualization.model_validate(candidate_visualization)
    if visualization.candidate_digest != stable_hash(candidate):
        raise ValueError("candidate visualization is not bound to displayed candidate")
    if (
        formal_kb is not None
        and formal_kb.ir_sha256 != LogicalProgram.model_validate(program).sha256()
    ):
        raise ValueError("accepted formal KB is not bound to displayed typed IR")
    refinement_record = _mapping(refinement, "refinement")
    partitioned = refinement_record.get("partitioned_run")
    partitions = (
        len(partitioned.get("partition_receipts", ())) if isinstance(partitioned, Mapping) else 1
    )
    dispositions = sorted(
        {
            str(item.get("disposition", ""))
            for item in projection.get("dimensions", ())
            if isinstance(item, Mapping)
        }
    )
    blockers = len(projection.get("activation_blockers", ()))
    return f"""
      <article class="boundary-note"><p>The generative/refinement loop produced
      {len(program.get('statements', ()))} source-linked formalized statements across
      {partitions} semantic partition(s). Deterministic checks then validated its
      schema, exact spans, vocabulary, typing, and compilation.</p>
      <p><strong>Authority boundary:</strong> activation remains
      <code>{html.escape(str(projection.get('activation_status', 'blocked')))}</code>
      with {blockers} blocker(s) in its immutable pre-acceptance lineage. Projection
      dispositions include {html.escape(', '.join(dispositions) or 'not recorded')}.
      The complete candidate was automatically validated and promoted into an accepted
      executable KB. It did not govern the portfolio solve: its logical-runtime
      authority remains separate from the reviewer-approved optimization model and it
      cannot silently create portfolio constraints.</p>
      {_render_candidate_visualization(candidate, candidate_visualization)}
      {_render_formal_kb_embeds(
          candidate, visualization, formal_kb, formal_kb_texts
      )}</article>
    """


def _render_formal_kb_embeds(
    candidate: Mapping[str, Any],
    visualization: CandidateKBVisualization,
    formal_kb: AcceptedFormalKBReceipt | None,
    formal_kb_texts: Mapping[str, str],
) -> str:
    if formal_kb is None:
        return _render_commented_statements(visualization)
    facts, rules = _formal_statement_counts(candidate, visualization)
    code_blocks = "".join(
        f"<details><summary>Complete accepted {html.escape(formalism.upper())} KB "
        f"(embedded)</summary><pre><code>{html.escape(text)}</code></pre></details>"
        for formalism, text in (
            ("asp", formal_kb_texts["asp"]),
            ("prolog", formal_kb_texts["prolog"]),
        )
    )
    return f"""
      <p><strong>Backend-native formal KBs:</strong> all {facts} facts and {rules}
      rules passed the automated semantic and executable gates. The accepted KB is
      active for standalone Clingo ASP and SWI-Prolog reasoning; portfolio-optimization
      authority remains explicitly false.</p>
      {_render_commented_statements(visualization)}
      <div class="embedded-kb">{code_blocks}</div>
    """


def _render_commented_statements(
    visualization: CandidateKBVisualization,
) -> str:
    """Render accepted logical units with human-readable, source-grounded comments."""

    spans = {item.span_id: item.exact_text for item in visualization.spans}
    blocks = []
    for rule in visualization.rules:
        kind = "Fact" if str(rule.modality) == "fact" else "Rule"
        sources = [spans[item] for item in rule.source_span_ids if item in spans]
        source_lines = [
            line.strip() for source in sources for line in source.splitlines() if line.strip()
        ]
        comments = "\n".join(f"% Source: {line}" for line in source_lines) or (
            "% Source: authenticated source span recorded in the acceptance lineage"
        )
        blocks.append(f"% {kind}: {rule.statement_id}\n{comments}\n{rule.compiled_asp}")
    return f"""<section class="commented-rules" aria-labelledby="commented-rules-heading">
      <h3 id="commented-rules-heading">Source-commented accepted facts and rules</h3>
      <p>Comments identify the logical-unit kind and reproduce its authenticated
      natural-language grounding. Executable syntax is shown unchanged beneath it.</p>
      <pre><code>{html.escape(chr(10).join(blocks))}</code></pre>
    </section>"""


def _human_variable(variable_id: str) -> str:
    names = {
        "retain_atlas": "retain Atlas",
        "retain_brenta": "retain Brenta",
        "retain_cervo": "retain Cervo",
        "reserve_ibex": "reserve Ibex",
    }
    return names.get(variable_id, variable_id.replace("_", " "))


def _render_formalization(
    candidate: Mapping[str, Any],
    refinement: Any,
    grounding: Any,
    candidate_visualization: Any = None,
) -> str:
    program = _mapping(candidate["logical_program"], "candidate.logical_program")
    projection = _mapping(candidate["projection"], "candidate.projection")
    statements = program.get("statements", [])
    dimensions = projection.get("dimensions", [])
    dimension_dispositions: dict[str, set[str]] = {}
    for raw_dimension in dimensions:
        item = _mapping(raw_dimension, "projection dimension")
        dimension_dispositions.setdefault(str(item.get("dimension", "")), set()).add(
            str(item.get("disposition", ""))
        )
    dimension_summaries = (
        {
            "dimension": dimension,
            "disposition": " / ".join(
                value
                for value in ("represented", "approximated", "omitted")
                if value in dispositions
            ),
        }
        for dimension, dispositions in dimension_dispositions.items()
    )
    refinement_record = _mapping(refinement, "refinement")
    partitioned = refinement_record.get("partitioned_run")
    if isinstance(partitioned, Mapping):
        receipts = partitioned.get("partition_receipts", ())
        passes = sum(
            len(item.get("refinement_run", {}).get("iterations", ()))
            for item in receipts
            if isinstance(item, Mapping)
        )
        refinement_sentence = (
            f"{len(receipts)} semantic partitions converged in {passes} refinement " "pass(es)."
        )
    else:
        passes = len(refinement_record.get("iterations", ()))
        refinement_sentence = f"The candidate converged in {passes} refinement pass(es)."
    grounding_record = _mapping(grounding, "grounding")
    check_count = len(grounding_record.get("deterministic_checks", ()))
    claim_count = len(grounding_record.get("claim_coverage", ()))
    return f"""
      <p>The refinement process produced {len(statements)} typed intermediate
      statement(s) for {html.escape(str(projection.get('target_formalism', 'the target logic')))}.
      {html.escape(refinement_sentence)} Exact source spans, predicate closure, typing,
      and all {claim_count} expected claims passed {check_count} deterministic checks
      before the representation below was accepted as a review candidate.</p>
      <div class="dimension-list" aria-label="Semantic projection dimensions">
        {''.join(_render_dimension(item) for item in dimension_summaries)}
      </div>
      {_render_candidate_visualization(candidate, candidate_visualization)}
    """


def _render_candidate_visualization(candidate: Mapping[str, Any], value: Any) -> str:
    """Embed a compact verified graph summary without external dependencies."""

    if value is None:
        return ""
    visualization = CandidateKBVisualization.model_validate(value)
    expected = stable_hash(candidate)
    if visualization.candidate_digest != expected:
        raise ValueError("candidate visualization is not bound to displayed candidate")
    e = html.escape
    rule_rows = "".join(
        "<tr>"
        f"<th scope='row'><code>{e(rule.statement_id)}</code></th>"
        f"<td><code>{e(rule.compiled_asp)}</code></td>"
        f"<td>{len(rule.source_span_ids)} exact source span(s) verified</td>"
        f"<td>{e(', '.join(rule.body_predicates) or 'fact')}</td>"
        "</tr>"
        for rule in visualization.rules
    )
    return f"""
      <article class="candidate-viz">
        <div class="candidate-viz-heading">
          <div><span class="label">Embedded KB visualization</span>
          <h3>Autoformalized rule and grounding graph</h3></div>
        </div>
        <p class="gate"><strong>Interpretation boundary:</strong> these source-linked
        rules were automatically accepted for the logical runtime after all gates
        passed, but cannot directly control the portfolio optimizer.</p>
        <p>Each row follows the formal path from an exact natural-language span to a
        semantic element, a typed rule, and its predicate dependencies. Opaque span
        and element identifiers remain visible in this embedded record.</p>
        <div class="formal-flow">
          <table><caption>Compiler-validated accepted rules</caption>
            <thead><tr><th scope="col">Rule</th><th scope="col">ASP</th>
            <th scope="col">Grounding</th><th scope="col">Depends on</th></tr></thead>
            <tbody>{rule_rows}</tbody></table></div>
        <p>{visualization.summary['exact_spans']} exact spans ·
        {visualization.summary['semantic_elements']} semantic elements ·
        {visualization.summary['rules']} compiler-validated rules.</p>
      </article>
    """


def _render_dimension(value: Any) -> str:
    item = _mapping(value, "projection dimension")
    e = html.escape
    return (
        f"<span class='dimension'><b>{e(str(item.get('dimension', '')))}</b>"
        f"<small>{e(str(item.get('disposition', '')))}</small></span>"
    )


def _render_assignments(plan: VerifiedPlan) -> str:
    rows = "".join(
        f"<tr><th scope='row'><code>{html.escape(variable_id)}</code></th>"
        f"<td>{html.escape(str(value))}</td>"
        f"<td>{'selected' if value != 0 else 'not selected'}</td></tr>"
        for variable_id, value in sorted(plan.result.assignments.items())
    )
    return f"""<table><caption>Verified decision variables</caption>
      <thead><tr><th scope="col">Variable</th><th scope="col">Value</th><th scope="col">Decision</th></tr></thead>
      <tbody>{rows}</tbody></table>"""


def _render_decision_point(
    plan: VerifiedPlan,
    counterfactual: CounterfactualRun,
    evidence: Mapping[str, Any],
    unit: str,
) -> str:
    """Explain the choice, its decisive formal boundary, and its sensitivity."""

    selected = [
        f"{variable_id} = {value}"
        for variable_id, value in sorted(plan.result.assignments.items())
        if value != 0
    ]
    active = [
        item.constraint_id
        for item in plan.verification.constraint_checks
        if item.satisfied and item.lhs == item.rhs
    ]
    drivers = [
        str(item.get("statement", "")).strip()
        for item in evidence.get("drivers", ())
        if isinstance(item, Mapping) and str(item.get("statement", "")).strip()
    ]
    counterfactuals = [
        item for item in evidence.get("counterfactuals", ()) if isinstance(item, Mapping)
    ]
    choice = ", ".join(selected) if selected else "No non-zero decision variables"
    boundaries = ", ".join(active) if active else "No equality boundary was active"
    driver_items = "".join(f"<li>{html.escape(item)}</li>" for item in drivers)
    changed_assignments = [
        (variable_id, plan.result.assignments.get(variable_id), value)
        for variable_id, value in sorted(counterfactual.result.assignments.items())
        if plan.result.assignments.get(variable_id) != value
    ]
    changes = (
        ", ".join(
            f"{variable_id} changes from {before} to {after}"
            for variable_id, before, after in changed_assignments
        )
        or "the selected variables do not change"
    )
    condition = (
        str(counterfactuals[0].get("condition", "")).strip()
        if counterfactuals
        else "The tested policy change"
    )
    difference_text = "an unavailable amount"
    direction = "different"
    if (
        plan.result.objective_value is not None
        and counterfactual.result.objective_value is not None
    ):
        difference = plan.result.objective_value - counterfactual.result.objective_value
        percentage = (
            abs(difference * 100 / plan.result.objective_value)
            if plan.result.objective_value != 0
            else None
        )
        percentage_text = f" ({percentage:.1f}%)" if percentage is not None else ""
        difference_text = f"{abs(difference)} {unit}{percentage_text}"
        direction = "less" if difference > 0 else "more"
    return f"""<article class="decision-point">
      <span class="label">Explanatory decision point</span>
      <h3>Why this is the optimum</h3>
      <h4>Optimal choice</h4>
      <p><strong>{html.escape(choice)}</strong>, with verified objective
      <strong>{html.escape(_quantity(plan.result.objective_value, unit))}</strong>.</p>
      <h4>Decisive constraints</h4>
      <p>The chosen point lies on the active formal boundary:
      <code>{html.escape(boundaries)}</code>.</p>
      <ul>{driver_items}</ul>
      <h4>Trade-off and sensitivity</h4>
      <p><strong>{html.escape(condition)}</strong>. The executed alternative solves to
      <strong>{html.escape(_quantity(counterfactual.result.objective_value, unit))}</strong>:
      {html.escape(changes)}, making it {html.escape(difference_text)} {direction}.
      This contrast identifies the policy's marginal effect on the selected point.</p>
    </article>"""


def _render_constraints(plan: VerifiedPlan) -> str:
    rows = "".join(
        f"<tr><th scope='row'><code>{html.escape(item.constraint_id)}</code></th>"
        f"<td>{html.escape(str(item.lhs))} {html.escape(item.sense)} {html.escape(str(item.rhs))}</td>"
        f"<td>{'satisfied' if item.satisfied else 'violated'}</td></tr>"
        for item in plan.verification.constraint_checks
    )
    return f"""<table><caption>Independent constraint replay</caption>
      <thead><tr><th scope="col">Constraint</th><th scope="col">Check</th><th scope="col">Result</th></tr></thead>
      <tbody>{rows}</tbody></table>"""


def _render_schedule(schedule: SchedulingResult, problem: SchedulingProblem) -> str:
    if not schedule.assignments:
        return "<p>No schedule assignments were emitted.</p>"
    tasks = {item.task_id: item for item in problem.tasks}
    assignments_by_project: dict[str, list[Any]] = {}
    for assignment in schedule.assignments:
        assignments_by_project.setdefault(tasks[assignment.task_id].project_id, []).append(
            assignment
        )
    project_sections = []
    for project_id, assignments in sorted(assignments_by_project.items()):
        rows = "".join(
            "<tr>"
            f"<th scope='row'>{html.escape(_human_identifier(item.task_id))}</th>"
            f"<td>{html.escape(_human_identifier(tasks[item.task_id].location_id))}</td>"
            f"<td>{html.escape(_human_identifier(item.resource_id))}</td>"
            f"<td>{html.escape(_schedule_clock(item.start, problem))}</td>"
            f"<td>{html.escape(_schedule_clock(item.end, problem, end_boundary=True))}</td>"
            f"<td>{html.escape(_duration_label(tasks[item.task_id].duration, problem))}</td>"
            "</tr>"
            for item in sorted(assignments, key=lambda value: (value.start, value.task_id))
        )
        project_sections.append(
            f"<h3>{html.escape(_human_identifier(project_id))}</h3>"
            "<table><thead><tr><th>Activity</th><th>Site</th><th>Assigned resource</th>"
            "<th>Start</th><th>Finish</th><th>Duration</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    resource_count = len({item.resource_id for item in schedule.assignments})
    horizon = max(item.end for item in schedule.assignments)
    return f"""<p><strong>{len(schedule.assignments)} activities scheduled</strong> ·
      {len(assignments_by_project)} projects · {resource_count} dispatched resources ·
      programme makespan {html.escape(_duration_label(horizon, problem))}.</p>
      {_render_schedule_gantt(schedule, problem)}
      {''.join(project_sections)}"""


def _render_schedule_gantt(schedule: SchedulingResult, problem: SchedulingProblem) -> str:
    tasks = {item.task_id: item for item in problem.tasks}
    ordered = sorted(
        schedule.assignments,
        key=lambda item: (tasks[item.task_id].project_id, item.start, item.task_id),
    )
    left = 255
    plot_width = 720
    row_height = 27
    top = 58
    height = top + len(ordered) * row_height + 34
    projects = sorted({tasks[item.task_id].project_id for item in ordered})
    colors = ("#0d6b4d", "#7b5e20", "#245f73", "#8b4a57", "#5c4b8a", "#8a5b2d", "#376f5c")
    palette = {project: colors[index % len(colors)] for index, project in enumerate(projects)}
    horizon = max(
        max((item.latest_end for item in problem.tasks), default=1),
        max((item.end for item in ordered), default=1),
    )
    annual = _is_annual_schedule(problem)
    period_labels = ("Q1", "Q2", "Q3", "Q4") if annual else ("Mon", "Tue", "Wed", "Thu", "Fri")
    bands = []
    for period, label in enumerate(period_labels):
        x = left + period * plot_width / len(period_labels)
        bands.append(
            f'<rect x="{x:.2f}" y="36" width="{plot_width / len(period_labels):.2f}" '
            f'height="{height - 58}" fill="{"#f3f7f4" if period % 2 == 0 else "#e8f0ec"}"/>'
            f'<text x="{x + plot_width / (2 * len(period_labels)):.2f}" y="27" text-anchor="middle" '
            f'class="gantt-day">{label}</text>'
            f'<line x1="{x:.2f}" y1="36" x2="{x:.2f}" y2="{height - 22}" '
            'class="gantt-grid"/>'
        )
    bands.append(
        f'<line x1="{left + plot_width:.2f}" y1="36" '
        f'x2="{left + plot_width:.2f}" y2="{height - 22}" class="gantt-grid"/>'
    )
    rows = []
    previous_project = None
    for index, assignment in enumerate(ordered):
        task = tasks[assignment.task_id]
        y = top + index * row_height
        project_changed = task.project_id != previous_project
        if project_changed and index:
            rows.append(
                f'<line x1="8" y1="{y - 6}" x2="{left + plot_width}" '
                f'y2="{y - 6}" class="gantt-project-rule"/>'
            )
        label = _human_identifier(assignment.task_id)
        if len(label) > 32:
            label = label[:29] + "…"
        x = left + float(assignment.start) * plot_width / horizon
        width = max(4.0, float(assignment.end - assignment.start) * plot_width / horizon)
        color = palette.get(task.project_id, "#4f6b63")
        rows.append(
            f'<text x="8" y="{y + 15}" class="gantt-task">{html.escape(label)}</text>'
            f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="19" rx="4" '
            f'fill="{color}" tabindex="0"><title>{html.escape(_human_identifier(task.project_id))}: '
            f"{html.escape(_human_identifier(assignment.task_id))}; "
            f"{html.escape(_human_identifier(assignment.resource_id))}; "
            f"{html.escape(_schedule_clock(assignment.start, problem))}–"
            f"{html.escape(_schedule_clock(assignment.end, problem, end_boundary=True))}</title></rect>"
        )
        previous_project = task.project_id
    legend = "".join(
        f'<span><i style="background:{color}"></i>{html.escape(_human_identifier(project))}</span>'
        for project, color in palette.items()
    )
    return f"""<figure class="chart gantt" aria-labelledby="schedule-chart-title">
      <figcaption id="schedule-chart-title"><strong>{'Annual programme by planning quarter' if annual else 'Regional programme by productive shift'}</strong><br><small>Hover or focus a bar for its project, resource, and exact
      scheduled interval.</small></figcaption>
      <div class="chart-scroll"><svg viewBox="0 0 1000 {height}" role="img"
      aria-label="{'Annual ' if annual else ''}Gantt chart of {len(ordered)} scheduled activities across {len(projects)} projects">
        {''.join(bands)}{''.join(rows)}
      </svg></div><div class="chart-legend">{legend}</div>
    </figure>"""


def _is_annual_schedule(problem: SchedulingProblem) -> bool:
    unit = problem.time_unit.lower()
    return "day" in unit or max((task.latest_end for task in problem.tasks), default=0) > 60


def _render_schedule_scope(problem: SchedulingProblem) -> str:
    if _is_annual_schedule(problem):
        horizon = max(task.latest_end for task in problem.tasks)
        return (
            "<p>This is a bounded annual working-day model spanning up to "
            f"{horizon} {html.escape(problem.time_unit.replace('_', ' '))} units. "
            "It establishes resource-feasible sequencing at planning-day resolution; "
            "it does not claim intraday dispatch precision or model undeclared weather "
            "and permitting disruptions.</p>"
        )
    return (
        "<p>This is a bounded productive-hour model. It establishes resource-feasible "
        "sequencing at shift-hour resolution and does not claim annual coverage or "
        "model undeclared weather and permitting disruptions.</p>"
    )


def _schedule_clock(value: int, problem: SchedulingProblem, *, end_boundary: bool = False) -> str:
    if _is_annual_schedule(problem):
        day = value if end_boundary and value > 0 else value + 1
        return f"Planning day {day}"
    return _productive_clock(value, end_boundary=end_boundary)


def _duration_label(value: int, problem: SchedulingProblem) -> str:
    if _is_annual_schedule(problem):
        unit = "working day" if value == 1 else "working days"
        return f"{value} {unit}"
    unit = problem.time_unit.replace("productive_", "productive ").replace("_", " ")
    if value != 1 and not unit.endswith("s"):
        unit += "s"
    return f"{value} {unit}"


def _productive_clock(hour: int, *, end_boundary: bool = False) -> str:
    days = ("Mon", "Tue", "Wed", "Thu", "Fri")
    if hour == 60:
        return "Fri 18:00"
    if end_boundary and hour > 0 and hour % 12 == 0:
        return f"{days[hour // 12 - 1]} 18:00"
    day = hour // 12
    shift_hour = 6 + hour % 12
    return f"{days[day]} {shift_hour:02d}:00"


def _human_identifier(value: str) -> str:
    return value.replace("_", " ").title()


def _render_stress(stress: StressReport, unit: str, objective_id: str) -> str:
    objective_values = [
        item.result.objective_value
        for item in stress.outcomes
        if item.result.objective_value is not None
    ]
    maximum = max((abs(value) for value in objective_values), default=1)
    scenario_chart = "".join(
        _bar_row(
            _human_identifier(item.scenario_id),
            item.result.objective_value,
            unit,
            (
                float(abs(item.result.objective_value) * 100 / maximum)
                if item.result.objective_value is not None
                else 0
            ),
            "scenario",
        )
        for item in stress.outcomes
    )
    rows = "".join(
        f"<tr><th scope='row'><code>{html.escape(item.scenario_id)}</code></th>"
        f"<td>{html.escape(str(item.probability))}</td>"
        f"<td>{html.escape(item.result.status.value)}</td>"
        f"<td>{html.escape(_quantity(item.result.objective_value, unit))}</td></tr>"
        for item in stress.outcomes
    )
    risk = stress.risk
    risk_metrics = ""
    if risk is not None:
        risk_metrics = f"""<div class="metric-grid compact">
          {_metric("Expected", _quantity(risk.expected_loss, unit), "Scenario-weighted")}
          {_metric("VaR", _quantity(risk.value_at_risk, unit), f"alpha {risk.alpha}")}
          {_metric("CVaR", _quantity(risk.conditional_value_at_risk, unit), f"alpha {risk.alpha}")}
        </div>"""
    return f"""<figure class="chart" aria-labelledby="stress-chart-title">
      <figcaption id="stress-chart-title"><strong>{html.escape(_objective_period(objective_id).title())} cost exposure by rental-rate
      scenario</strong></figcaption>{scenario_chart}</figure>
      {risk_metrics}<table><caption>Executed scenario outcomes</caption>
      <thead><tr><th scope="col">Scenario</th><th scope="col">Probability</th><th scope="col">Status</th><th scope="col">Objective</th></tr></thead>
      <tbody>{rows}</tbody></table>"""


def _render_explanation_evidence(evidence: Mapping[str, Any]) -> str:
    drivers = evidence.get("drivers", [])
    counterfactuals = evidence.get("counterfactuals", [])
    caveats = evidence.get("caveats", [])
    driver_html = "".join(
        f"<li><strong>{html.escape(str(item.get('statement', '')))}</strong></li>"
        for item in drivers
        if isinstance(item, Mapping)
    )
    counterfactual_html = "".join(
        f"<li><strong>{html.escape(str(item.get('condition', '')))}</strong> → "
        f"{html.escape(str(item.get('changed_action', '')))}</li>"
        for item in counterfactuals
        if isinstance(item, Mapping)
    )
    caveat_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in caveats)
    return f"""<div class="explanation-elements">
      <article><span class="label">Verified drivers</span><ul class="evidence-list">{driver_html}</ul></article>
      <article><span class="label">Executed counterfactuals</span><ul class="evidence-list">{counterfactual_html}</ul></article>
    </div><div class="caveats"><strong>Caveats</strong><ul>{caveat_html}</ul></div>"""


def _render_generative_explanation(
    explanation: PortfolioExplanation | None,
) -> str:
    if explanation is None:
        return ""
    return f"""<article class="recommendation candidate-explanation">
      <div><span class="label">Generative explanation candidate · review only</span>
      <h3>{html.escape(explanation.draft.headline)}</h3></div>
      <p>{html.escape(explanation.draft.explanation)}</p>
      <p>The wording is generative; every factual claim must remain within the
      deterministic evidence displayed in this report.</p></article>"""


def _metric(label: str, value: str, detail: str) -> str:
    return (
        f"<article class='metric'><span>{html.escape(label)}</span>"
        f"<strong>{html.escape(value)}</strong><small>{html.escape(detail)}</small></article>"
    )


def _quantity(value: Any, unit: str) -> str:
    return "not available" if value is None else f"{value} {unit}"


_STYLE = """
:root { --ink:#14231f; --muted:#597069; --paper:#f4f7f3; --card:#fff;
  --line:#d6e1db; --green:#0d6b4d; --green-soft:#dff4ea; --amber:#8b5b06;
  --amber-soft:#fff0c9; --blue:#245f73; --navy:#123742; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55
  ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.skip-link { position:absolute; left:-9999px; top:8px; background:#fff; padding:10px; z-index:10; }
.skip-link:focus { left:8px; }
.hero { color:#f7fffb; background:linear-gradient(125deg,#0d2f2b 0%,#164c47 55%,#245f73 100%);
  border-bottom:5px solid #63c19c; }
.hero-inner, main, footer p { max-width:900px; margin:auto; }
.hero-inner { padding:62px 28px 42px; }
h1 { max-width:900px; margin:.15em 0; font:700 clamp(2.35rem,6vw,4.8rem)/1.03 Georgia,serif; }
h2 { margin:.1em 0 .7em; font:700 clamp(1.7rem,3vw,2.6rem)/1.15 Georgia,serif; }
h3 { margin:.3em 0; }
.eyebrow,.label { display:block; font-size:.75rem; font-weight:800; letter-spacing:.12em;
  text-transform:uppercase; color:var(--green); }
.hero .eyebrow { color:#89d8b8; }.lede { max-width:800px; color:#dcece6; font-size:1.12rem; }
.badges { display:flex; flex-wrap:wrap; gap:8px; margin:24px 0; }
.badge { border-radius:99px; padding:6px 11px; font-size:.78rem; font-weight:750; color:#173c34; }
.synthetic { background:#dce9f0; }.verified { background:#a9e3c8; }.pending { background:#ffd978; }
.identity { margin:20px 0 0; }
.identity div { border-top:1px solid #528078; padding-top:10px; min-width:0; }
dt { font-size:.75rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
.identity dt { color:#b6d6cc; }.identity dd { margin:3px 0 12px; overflow-wrap:anywhere; }
.context-title { margin:18px 0 0; color:#bfe1d5; font-weight:700; }
.report-summary { margin:24px 0 0; }
.report-summary div { border-top:1px solid #528078; padding:10px 0; }
.report-summary dt { color:#b6d6cc; }.report-summary dd { margin:2px 0 0;
  color:white; font:700 1.45rem/1.2 Georgia,serif; }
main { padding:18px 28px 70px; }.section { padding:44px 0; border-bottom:1px solid var(--line); }
.report-tabs { position:sticky; top:0; z-index:4; display:flex; gap:8px; padding:12px 0;
  background:var(--paper); border-bottom:1px solid var(--line); }
.report-tabs button { border:1px solid var(--line); border-radius:99px; padding:10px 15px;
  background:white; color:var(--navy); font:inherit; font-weight:800; cursor:pointer; }
.report-tabs button[aria-selected="true"] { background:var(--navy); color:white; border-color:var(--navy); }
.report-tabs button:focus-visible { outline:3px solid #63c19c; outline-offset:2px; }
.tab-panel[hidden] { display:none; }
.section-heading { max-width:780px; }.metric-list,.metric-grid { margin:12px 0; }
.metric,.recommendation,.source-card,.boundary-note,.decision-point,.explanation-elements article { background:var(--card);
  border:1px solid var(--line); border-radius:14px; padding:18px; box-shadow:0 6px 22px #18362a0a; }
.metric { margin:10px 0; }
.metric span,.metric small { display:block; color:var(--muted); }.metric strong { display:block; margin:.18em 0;
  font:700 1.45rem/1.2 Georgia,serif; overflow-wrap:anywhere; }
.decision-point { margin:18px 0; border-left:6px solid var(--green); }
.decision-point h4 { margin:1.2em 0 .2em; color:var(--navy); }
.recommendation { margin-top:14px; border-left:5px solid var(--green); }
.recommendation .gate { padding-top:12px; border-top:1px solid var(--line); color:var(--amber); }
.pipeline { padding:0; list-style:none; }
.pipeline li { position:relative; display:flex; gap:10px; align-items:center; padding:14px 9px; background:#edf3f0; border-radius:9px; }
.pipeline b { display:grid; place-items:center; width:28px; height:28px; flex:none; border-radius:50%; background:var(--green); color:white; }
.pipeline li + li,.source-card + .source-card,.explanation-elements article + article { margin-top:10px; }
.pipeline small,.evidence-list small { display:block; color:var(--muted); }
.source-card { white-space:normal; }
code { font: .88em ui-monospace,SFMono-Regular,Consolas,monospace; overflow-wrap:anywhere; }
.boundary { border-top:5px solid var(--amber); }.boundary-note { background:var(--amber-soft); }
.dimension-list { display:flex; flex-wrap:wrap; gap:8px; }
.dimension { background:#e6eff2; color:var(--navy); border-radius:7px; padding:6px 9px; }
.dimension b,.dimension small { display:block; }.candidate-viz { margin:18px 0; padding:18px;
  border:1px solid var(--line); border-left:5px solid var(--blue); border-radius:14px; background:#f8fbfa; }
.candidate-viz-heading { display:flex; justify-content:space-between; gap:18px; align-items:start; }
.explorer-link { display:inline-block; padding:9px 12px; border-radius:8px; background:var(--navy);
  color:white; text-decoration:none; font-weight:750; white-space:nowrap; }
.graph-flow { max-height:360px; overflow:auto; }.graph-flow ol { padding-left:1.4em; }
.graph-flow li { margin:.45em 0; }.candidate-viz table { font-size:.84rem; }
details { margin-top:12px; }summary { cursor:pointer; font-weight:700; color:var(--blue); }
pre { max-height:440px; overflow:auto; padding:14px; border-radius:8px; background:#102723; color:#dcf7eb;
  font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace; white-space:pre-wrap; overflow-wrap:anywhere; }
table { width:100%; border-collapse:collapse; background:var(--card); }caption { text-align:left; padding:0 0 9px; font-weight:800; }
th,td { border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; }thead { background:#eaf1ed; }
.chart { margin:22px 0; padding:18px; border:1px solid var(--line); border-radius:14px;
  background:var(--card); box-shadow:0 6px 22px #18362a0a; }
.configuration-extent,.tradeoff-map { margin:22px 0; padding:18px; border:1px solid var(--line);
  border-radius:14px; background:var(--card); box-shadow:0 6px 22px #18362a0a; }
.tradeoff-map figcaption { margin-bottom:16px; }.tradeoff-map figcaption small { color:var(--muted); }
.tradeoff-option { padding:16px; border:1px solid var(--line); border-left:5px solid var(--green);
  border-radius:10px; background:#f8fbfa; }
.tradeoff-option.relaxed { border-left-color:var(--blue); }.tradeoff-versus { margin:8px 0;
  color:var(--muted); font-weight:800; text-align:center; text-transform:uppercase; font-size:.75rem; }
.tradeoff-question { margin:16px 0 0; padding:12px; background:var(--green-soft); border-radius:8px; }
.commented-rules { margin-top:20px; }.embedded-kb { margin-top:18px; }
.chart figcaption { margin-bottom:16px; color:var(--navy); }.chart figcaption strong { font-size:1.08rem; }
.chart figcaption small { color:var(--muted); }.bar-row { margin:13px 0; }
.bar-label { display:block; margin-bottom:4px; font-weight:700; }.bar-row > strong { display:block; margin-top:3px; }
.bar-track { display:block; height:22px; overflow:hidden; border-radius:5px; background:#e2ebe6; }
.bar-track i { display:block; height:100%; min-width:3px; border-radius:5px; background:var(--green); }
.bar-track i.variant { background:var(--blue); }.bar-track i.scenario { background:#4b7e6e; }
.chart-callout { margin:16px 0 0; padding:12px; border-left:4px solid var(--green); background:var(--green-soft); }
.chart-scroll { overflow-x:auto; }.gantt svg { display:block; width:100%; min-width:820px; height:auto; }
.gantt-day { fill:var(--navy); font:700 13px ui-sans-serif,sans-serif; }
.gantt-task { fill:var(--ink); font:12px ui-sans-serif,sans-serif; }
.gantt-grid { stroke:#b9c9c1; stroke-width:1; }.gantt-project-rule { stroke:#789087; stroke-width:1.25; }
.chart-legend { display:flex; flex-wrap:wrap; gap:8px 18px; margin-top:12px; font-size:.82rem; color:var(--muted); }
.chart-legend span { white-space:nowrap; }.chart-legend i { display:inline-block; width:11px; height:11px;
  margin-right:5px; border-radius:2px; vertical-align:-1px; }
.timeline { list-style:none; padding:0; }.timeline li { margin:16px 0; }
.timeline small { display:block; color:var(--muted); }.track { position:relative; height:30px; background:#dfe9e4; border-radius:7px; overflow:hidden; }
.track { display:block; margin-top:6px; }
.track i { position:absolute; top:0; bottom:0; background:linear-gradient(90deg,var(--green),#40a982); border-radius:5px; }
.evidence-list li { margin:0 0 12px; }.caveats { margin-top:14px; padding:15px 18px; background:var(--amber-soft); border-radius:10px; }
footer { background:#102d29; color:#d7e8e2; padding:28px; }
@media (max-width:800px) { .candidate-viz-heading { flex-direction:column; }
  h1 { font-size:2.6rem; }.hero-inner { padding-top:45px; } }
@media print { body { background:white; }.hero { background:#153f39 !important; print-color-adjust:exact; }
  .report-tabs { display:none; }.tab-panel[hidden] { display:block; }
  .section { break-inside:avoid; }.source-card { break-inside:avoid; }details:not([open]) { display:none; } }
"""


_TAB_SCRIPT = """
(() => {
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  const activate = (tab) => {
    tabs.forEach((item) => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
    });
    tab.focus();
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activate(tab));
    tab.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      activate(tabs[(index + offset + tabs.length) % tabs.length]);
    });
  });
})();
"""


__all__ = [
    "render_resource_portfolio_demonstrator_html",
    "write_resource_portfolio_demonstrator_report",
]
