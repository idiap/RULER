# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Workflow graph artifact builder. It models workflow stacks, hook steps, skills,
reflective edges, and HTML visualization data for the RULER control system.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import html
import json
import re
from pathlib import Path
from typing import Any

from ruler.io import read_yaml, write_text
from ruler.paths import BUILD_DIR, HOOKS_FILE, SKILL_HOOKS_FILE
from ruler.schemas import SkillHookBinding, WorkflowHook
from ruler.runtime.skill_inventory import discover_skill_files, repo_relative_skill_path

WORKFLOW_GRAPH_DIR = BUILD_DIR / "workflow_graphs"


@dataclass(frozen=True)
class WorkflowStep:
    """Typed workflow step artifact used by the workflow graphs workflow."""

    skill: str
    role: str
    posture: str
    output: str
    description: str
    trigger: str


@dataclass(frozen=True)
class WorkflowStack:
    """Typed workflow stack artifact used by the workflow graphs workflow."""

    stack_id: str
    label: str
    family: str
    description: str
    trigger: str
    artifact_entrypoints: tuple[str, ...]
    steps: tuple[WorkflowStep, ...]
    reflective_edges: tuple[dict[str, str], ...] = ()


def select_workflow_graph_directory(output_dir: Path | None = None) -> Path:
    """Select the native destination without creating it."""
    return output_dir or WORKFLOW_GRAPH_DIR


def write_workflow_graph_artifacts(output_dir: Path | None = None) -> dict[str, Path]:
    """Write workflow graph artifacts for the workflow graphs workflow."""
    base = select_workflow_graph_directory(output_dir)
    model = build_workflow_graph_model()
    layout = build_workflow_layout_plan(model)
    html_report = render_workflow_graph_html(model)
    return persist_workflow_graph_artifacts(base, model, layout, html_report)


def persist_workflow_graph_artifacts(
    base: Path, model: dict[str, Any], layout: dict[str, Any], html_report: str
) -> dict[str, Path]:
    """Write in native order; an exception leaves earlier writes intact."""
    base.mkdir(parents=True, exist_ok=True)
    paths = {
        "workflow_graphs_json": base / "workflow_graphs.json",
        "workflow_graphs_html": base / "workflow_graphs.html",
        "workflow_layout_plan": base / "workflow_layout_plan.json",
    }
    write_text(paths["workflow_graphs_json"], json.dumps(model, ensure_ascii=False, indent=2))
    write_text(paths["workflow_graphs_html"], html_report)
    write_text(paths["workflow_layout_plan"], json.dumps(layout, ensure_ascii=False, indent=2))
    return paths


def build_workflow_graph_model() -> dict[str, Any]:
    """Build the model using the same steps exposed by the MCP bindings.

    The native traversal remains finite-input driven and has no contract cap.
    """
    state = prepare_workflow_graph_state()
    while state["cursor"] < len(state["stacks"]):
        expand_workflow_graph_stack(state)
    return finish_workflow_graph_model(state)


def prepare_workflow_graph_state() -> dict[str, Any]:
    """Load native inputs, retain stacks, and seed the graph's carried state."""
    skills = _skill_inventory()
    bindings = _load_skill_bindings()
    hooks = _load_workflow_hooks()
    stacks = _workflow_stacks(skills, bindings, hooks)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    families = sorted({stack.family for stack in stacks})
    skill_use_counter: Counter[str] = Counter()
    role_counter: Counter[str] = Counter()
    stack_payloads: dict[str, Any] = {}

    for family in families:
        family_id = _family_id(family)
        nodes.append(
            {
                "data": {
                    "id": family_id,
                    "label": family,
                    "node_type": "family",
                    "family": family,
                    "description": f"Workflow family for {family}.",
                }
            }
        )

    return {
        "skills": skills,
        "stacks": stacks,
        "families": families,
        "nodes": nodes,
        "edges": edges,
        "skill_use_counter": skill_use_counter,
        "role_counter": role_counter,
        "stack_payloads": stack_payloads,
        "cursor": 0,
    }


def expand_workflow_graph_stack(state: dict[str, Any]) -> dict[str, Any]:
    """Consume exactly one retained stack, including its declared graph edges."""
    skills = state["skills"]
    stacks = state["stacks"]
    nodes = state["nodes"]
    edges = state["edges"]
    skill_use_counter = state["skill_use_counter"]
    role_counter = state["role_counter"]
    stack_payloads = state["stack_payloads"]
    stack = stacks[state["cursor"]]
    family_id = _family_id(stack.family)
    workflow_id = f"workflow:{stack.stack_id}"
    nodes.append(
        {
            "data": {
                "id": workflow_id,
                "label": stack.label,
                "node_type": "workflow",
                "family": stack.family,
                "stack": stack.label,
                "description": stack.description,
                "trigger": stack.trigger,
                "artifact_entrypoints": list(stack.artifact_entrypoints),
                "reflective": bool(stack.reflective_edges),
            }
        }
    )
    _add_edge(
        edges,
        family_id,
        workflow_id,
        "family_contains_workflow",
        "workflow_group",
        "groups workflow",
    )

    ordered_hooks: list[dict[str, Any]] = []
    previous_step_id: str | None = None
    for index, step in enumerate(stack.steps, start=1):
        step_id = f"step:{stack.stack_id}:{index:02d}"
        skill_id = f"skill:{step.skill}"
        skill_use_counter[step.skill] += 1
        role_counter[step.role] += 1
        nodes.append(
            {
                "data": {
                    "id": step_id,
                    "label": f"{index}. {_humanize(step.skill)}",
                    "node_type": "workflow_step",
                    "family": stack.family,
                    "stack": stack.label,
                    "skill": step.skill,
                    "role": step.role,
                    "execution_posture": step.posture,
                    "output_type": step.output,
                    "description": step.description,
                    "sequence_index": index,
                    "trigger": step.trigger,
                }
            }
        )
        _add_edge(
            edges,
            workflow_id if index == 1 else previous_step_id or workflow_id,
            step_id,
            "workflow_entry" if index == 1 else "skill_handoff",
            step.output,
            "starts with" if index == 1 else f"hands off {step.output}",
        )
        previous_step_id = step_id
        ordered_hooks.append(
            {
                "index": index,
                "skill": step.skill,
                "role": step.role,
                "execution_posture": step.posture,
                "output_type": step.output,
                "description": step.description,
            }
        )
        nodes.append(
            {
                "data": {
                    "id": skill_id,
                    "label": _humanize(step.skill),
                    "node_type": "skill",
                    "skill": step.skill,
                    "role": step.role,
                    "execution_posture": step.posture,
                    "output_type": step.output,
                    "description": skills.get(step.skill, {}).get("description", step.description),
                }
            }
        )
        _add_edge(
            edges,
            workflow_id,
            skill_id,
            "stack_uses_skill",
            step.output,
            f"invokes {step.output}",
        )

    step_by_skill = {
        step.skill: f"step:{stack.stack_id}:{index:02d}"
        for index, step in enumerate(stack.steps, start=1)
    }
    for feedback in stack.reflective_edges:
        source = step_by_skill[feedback["from"]]
        target = step_by_skill[feedback["to"]]
        _add_edge(
            edges,
            source,
            target,
            "workflow_reflective_loop",
            feedback["output"],
            f"returns {feedback['output']}",
        )

    stack_payloads[stack.stack_id] = {
        "label": stack.label,
        "family": stack.family,
        "description": stack.description,
        "trigger": stack.trigger,
        "artifact_entrypoints": list(stack.artifact_entrypoints),
        "reflective": bool(stack.reflective_edges),
        "ordered_hooks": ordered_hooks,
        "reflective_edges": list(stack.reflective_edges),
    }

    state["cursor"] += 1
    return state


def finish_workflow_graph_model(state: dict[str, Any]) -> dict[str, Any]:
    """Deduplicate nodes and assemble native model metadata and counts."""
    skills = state["skills"]
    stacks = state["stacks"]
    families = state["families"]
    nodes = state["nodes"]
    edges = state["edges"]
    skill_use_counter = state["skill_use_counter"]
    role_counter = state["role_counter"]
    stack_payloads = state["stack_payloads"]
    unique_nodes = {node["data"]["id"]: node for node in nodes}
    available_skills = sorted(skills)
    modeled_skills = sorted(skill_use_counter)
    unmodeled_skills = sorted(set(available_skills) - set(modeled_skills))
    summary = {
        "stacks": len(stacks),
        "total_hooks": sum(len(stack.steps) for stack in stacks),
        "modeled_skills": len(modeled_skills),
        "available_skills": len(available_skills),
        "unmodeled_skills": len(unmodeled_skills),
        "shared_skills": sum(1 for count in skill_use_counter.values() if count > 1),
        "reflective_stacks": sum(1 for stack in stacks if stack.reflective_edges),
        "families": len(families),
    }
    return {
        "repo": "ruler",
        "source_documents": [
            ".ruler/hooks.yaml",
            "skills/SKILL_HOOKS.yaml",
            "docs/guides/workflow_graph_visualization.md",
            "docs/guides/reasoning_logs.md",
            "kb/manifest.yaml",
        ],
        "summary": summary,
        "families": {
            family: [stack.stack_id for stack in stacks if stack.family == family]
            for family in families
        },
        "skill_inventory": {
            "total": len(available_skills),
            "modeled": modeled_skills,
            "unmodeled": unmodeled_skills,
            "note": "The graph models workflow-facing skills and hook stacks, not every possible future skill.",
        },
        "shared_skills": [
            {"skill": skill, "use_count": count}
            for skill, count in sorted(skill_use_counter.items())
            if count > 1
        ],
        "reflection_role_counts": dict(role_counter),
        "graph": {
            "library_recommendation": "Cytoscape.js",
            "library_reason": "RULER workflow stacks are typed ordered graphs with hierarchy, reuse, and reflective feedback.",
            "layout_strategy": {
                "drilldown": "preset workflow -> ordered skill steps, with optional reflection edges",
                "overview": "family -> workflow containment plus shared skill reuse",
            },
            "edge_semantics": {
                "family_contains_workflow": "Family contains workflow.",
                "workflow_entry": "Workflow starts at first step.",
                "skill_handoff": "One skill output feeds another.",
                "stack_uses_skill": "Workflow invokes reusable skill.",
                "workflow_reflective_loop": "Critic, guard, or trace returns evidence to an earlier step.",
            },
            "views": {
                "drilldown": "Click one workflow to inspect ordered steps and reflective loops.",
                "static_cards": "Read workflow stack cards without JavaScript.",
            },
            "elements": {"nodes": list(unique_nodes.values()), "edges": edges},
        },
        "stacks": stack_payloads,
    }


def build_workflow_layout_plan(model: dict[str, Any]) -> dict[str, Any]:
    """Build workflow layout plan for the workflow graphs workflow."""
    edge_type_counts = Counter(
        edge["data"]["edge_type"] for edge in model["graph"]["elements"]["edges"]
    )
    stack_layouts = {}
    for stack_id, stack in model["stacks"].items():
        positions = {f"workflow:{stack_id}": {"x": -280, "y": 0}}
        for hook in stack["ordered_hooks"]:
            index = int(hook["index"])
            positions[f"step:{stack_id}:{index:02d}"] = {"x": (index - 1) * 300, "y": 0}
            positions[f"skill:{hook['skill']}"] = {"x": (index - 1) * 300, "y": 180}
        stack_layouts[stack_id] = {
            "positions": positions,
            "lanes": {
                "workflow": "left anchor",
                "steps": "main horizontal reasoning/control lane",
                "skills": "lower reusable capability lane",
                "reflection": "upper optional feedback lane",
            },
        }
    return {
        "repo": model["repo"],
        "source_graph": "build/ruler/workflow_graphs/workflow_graphs.json",
        "layout_principle": "Temporal control order first, reusable skill identity second, reflective feedback third.",
        "pressure": {
            "edge_type_counts": dict(edge_type_counts),
            "drilldown_default_edge_count": edge_type_counts["workflow_entry"]
            + edge_type_counts["skill_handoff"],
        },
        "views": {
            "drilldown": {
                "purpose": "inspect one selected RULER workflow as an ordered control trace",
                "default_nodes": ["workflow", "workflow_step"],
                "default_edges": ["workflow_entry", "skill_handoff"],
                "stack_layouts": stack_layouts,
                "optional_overlays": ["reflective edges", "reusable skill nodes"],
            }
        },
        "recommendations": [
            "Keep one workflow selected by default; full cross-stack views are secondary.",
            "Make reflection opt-in so gate feedback does not obscure the main reasoning lane.",
            "Use static cards as the durable fallback and JSON as the source of truth.",
        ],
    }


def render_workflow_graph_html(model: dict[str, Any]) -> str:
    """Render workflow graph HTML for the workflow graphs workflow."""
    embedded = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RULER Workflow Graphs</title>
  <script defer src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
  <style>
    :root {{ --ink: #18212f; --muted: #5f6b7a; --line: #d8dee9; --paper: #fff; --blue: #234f8f; --green: #2f7d4f; --gold: #bd8429; }}
    body {{ margin: 0; font: 15px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: #f7f9fc; }}
    main {{ max-width: 1240px; margin: 0 auto; padding: 34px 24px 70px; }}
    h1 {{ margin: 0 0 8px; color: var(--blue); font-size: 34px; border-left: 8px solid var(--green); padding-left: 16px; }}
    h2 {{ margin-top: 30px; color: var(--blue); border-top: 1px solid var(--line); padding-top: 18px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 24px 0; }}
    .card, .workflow-card, #details, .toolbar {{ background: var(--paper); border: 1px solid var(--line); border-radius: 8px; }}
    .card {{ padding: 14px 16px; }}
    .card strong {{ display: block; color: var(--green); font-size: 28px; }}
    .card span, .muted {{ color: var(--muted); }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 10px 12px; margin: 14px 0; }}
    .toolbar label {{ font-weight: 650; color: var(--blue); }}
    select {{ border: 1px solid var(--line); border-radius: 6px; padding: 7px 9px; min-width: min(100%, 420px); background: #fff; }}
    #cy {{ height: 620px; border: 1px solid var(--line); background: #fff; border-radius: 8px; }}
    #details {{ margin-top: 14px; border-left: 5px solid var(--green); padding: 14px 16px; min-height: 86px; }}
    .workflow-card {{ margin: 12px 0; padding: 12px 14px; }}
    .workflow-card summary {{ cursor: pointer; font-weight: 700; color: var(--blue); }}
    .workflow-card em {{ color: var(--muted); font-style: normal; margin-left: 8px; }}
    code {{ background: #f6f8fa; border: 1px solid #e5e7eb; border-radius: 4px; padding: 0.1rem 0.25rem; }}
    dt {{ font-weight: 700; margin-top: 8px; }}
    dd {{ margin-left: 0; color: var(--muted); }}
  </style>
</head>
<body>
<main>
  <h1>RULER Workflow Graphs</h1>
  <p class="muted">A portable workflow explorer for extraction, policy formalization, solver reasoning, recommendation safety, and reflective controls.</p>
  <section class="cards">{_summary_cards(model["summary"])}</section>
  <h2>Graph Explorer</h2>
  <p class="muted">Select a workflow to inspect ordered steps. Reflection edges are optional so the primary control path remains readable.</p>
  <div class="toolbar">
    <label for="workflow-select">Workflow</label>
    <select id="workflow-select"></select>
    <label><input id="show-labels" type="checkbox" checked> labels</label>
    <label><input id="show-reflection" type="checkbox"> reflection</label>
    <label><input id="show-skills" type="checkbox"> reusable skills</label>
  </div>
  <p id="view-note" class="muted"></p>
  <div id="cy"></div>
  <section id="details">Click a workflow, step, skill, or edge to inspect metadata.</section>
  <h2>Static Workflow Cards</h2>
  {_workflow_cards(model)}
  <h2>JSON Model</h2>
  <p class="muted">The JSON model is embedded below and also emitted as <code>workflow_graphs.json</code>.</p>
  <script type="application/json" id="workflow-graph-model">{embedded}</script>
</main>
<script>
window.addEventListener('DOMContentLoaded', () => {{
  const model = JSON.parse(document.getElementById('workflow-graph-model').textContent);
  const allElements = [...model.graph.elements.nodes, ...model.graph.elements.edges];
  const details = document.getElementById('details');
  const workflowSelect = document.getElementById('workflow-select');
  const labelToggle = document.getElementById('show-labels');
  const reflectionToggle = document.getElementById('show-reflection');
  const skillToggle = document.getElementById('show-skills');
  const viewNote = document.getElementById('view-note');
  Object.entries(model.stacks).forEach(([stackId, stack]) => {{
    const option = document.createElement('option');
    option.value = stackId;
    option.textContent = stack.label;
    workflowSelect.appendChild(option);
  }});
  const cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: allElements,
    style: [
      {{ selector: 'node', style: {{ label: 'data(label)', 'font-size': 11, 'text-wrap': 'wrap', 'text-max-width': 150, 'background-color': '#dbeafe', 'border-width': 1, 'border-color': '#94a3b8', width: 38, height: 38 }} }},
      {{ selector: 'node[node_type = "workflow"]', style: {{ 'background-color': '#2f7d4f', color: '#17412a', width: 50, height: 50 }} }},
      {{ selector: 'node[node_type = "workflow_step"]', style: {{ 'background-color': '#f6d58b', color: '#4a3511', shape: 'round-rectangle', width: 120, height: 48, 'text-max-width': 112 }} }},
      {{ selector: 'node[node_type = "skill"]', style: {{ 'background-color': '#e9d5ff', color: '#4c1d95', shape: 'hexagon' }} }},
      {{ selector: 'edge', style: {{ width: 1.4, label: '', 'font-size': 8, 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'line-color': '#94a3b8', 'target-arrow-color': '#94a3b8' }} }},
      {{ selector: 'edge[edge_type = "workflow_reflective_loop"]', style: {{ 'line-style': 'dashed', 'line-color': '#bd8429', 'target-arrow-color': '#bd8429', width: 2.2 }} }}
    ],
    layout: {{ name: 'cose', nodeRepulsion: 26000, idealEdgeLength: 180, padding: 70 }}
  }});
  function showDetails(evt) {{
    const d = evt.target.data();
    const rows = Object.entries(d).filter(([k]) => !['id', 'source', 'target'].includes(k)).map(([k, v]) => `<dt>${{k}}</dt><dd>${{Array.isArray(v) ? v.join('<br>') : v}}</dd>`).join('');
    details.innerHTML = `<h3>${{d.label || d.id}}</h3><dl>${{rows}}</dl>`;
  }}
  cy.on('tap', 'node, edge', showDetails);
  function currentStack() {{ return model.stacks[workflowSelect.value]; }}
  function selectedIds() {{
    const stackId = workflowSelect.value;
    const stack = currentStack();
    const ids = new Set([`workflow:${{stackId}}`]);
    cy.nodes().forEach(node => {{
      const d = node.data();
      if (d.node_type === 'workflow_step' && d.stack === stack.label) ids.add(d.id);
      if (skillToggle.checked && d.node_type === 'skill') {{
        const used = stack.ordered_hooks.some(h => h.skill === d.skill);
        if (used) ids.add(d.id);
      }}
    }});
    return ids;
  }}
  function render() {{
    const ids = selectedIds();
    const edgeTypes = new Set(['workflow_entry', 'skill_handoff']);
    if (skillToggle.checked) edgeTypes.add('stack_uses_skill');
    if (reflectionToggle.checked) edgeTypes.add('workflow_reflective_loop');
    cy.elements().hide();
    cy.nodes().forEach(node => {{ if (ids.has(node.id())) node.show(); }});
    cy.edges().forEach(edge => {{ if (edgeTypes.has(edge.data('edge_type')) && ids.has(edge.source().id()) && ids.has(edge.target().id())) edge.show(); }});
    const visibleSteps = cy.nodes('[node_type = "workflow_step"]:visible').sort((a, b) => (a.data('sequence_index') || 0) - (b.data('sequence_index') || 0));
    visibleSteps.forEach((node, order) => node.position({{x: 145 + order * 220, y: 180}}));
    cy.nodes('[node_type = "workflow"]:visible').positions(() => ({{x: 55, y: 180}}));
    cy.nodes('[node_type = "skill"]:visible').forEach((node, index) => node.position({{x: 145 + index * 220, y: 370}}));
    cy.nodes().style('label', labelToggle.checked ? 'data(label)' : '');
    cy.edges().style('label', '');
    if (labelToggle.checked) cy.edges('[edge_type = "workflow_reflective_loop"]').style('label', 'data(label)');
    viewNote.textContent = `Showing ${{currentStack().label}}. JSON remains the source of truth; this view is an inspection surface.`;
    cy.fit(cy.elements(':visible'), 50);
  }}
  workflowSelect.addEventListener('change', render);
  labelToggle.addEventListener('change', render);
  reflectionToggle.addEventListener('change', render);
  skillToggle.addEventListener('change', render);
  render();
}});
</script>
</body>
</html>
"""


def validate_workflow_graph_model(model: dict[str, Any] | None = None) -> list[str]:
    """Validate workflow graph model for the workflow graphs workflow."""
    model = model or build_workflow_graph_model()
    errors: list[str] = []
    summary = model.get("summary", {})
    if summary.get("stacks", 0) < 4:
        errors.append("workflow graph should expose at least four stacks")
    if summary.get("total_hooks", 0) < 12:
        errors.append("workflow graph should expose at least twelve workflow hooks")
    nodes = model["graph"]["elements"]["nodes"]
    edges = model["graph"]["elements"]["edges"]
    node_types = {node["data"].get("node_type") for node in nodes}
    edge_types = {edge["data"].get("edge_type") for edge in edges}
    for required in {"family", "workflow", "workflow_step", "skill"}:
        if required not in node_types:
            errors.append(f"missing node type {required}")
    for required in {
        "family_contains_workflow",
        "workflow_entry",
        "skill_handoff",
        "stack_uses_skill",
    }:
        if required not in edge_types:
            errors.append(f"missing edge type {required}")
    if summary.get("reflective_stacks", 0) < 1:
        errors.append("workflow graph should expose at least one reflective stack")
    if errors:
        raise ValueError("; ".join(errors))
    return [
        f"workflow_stacks={summary['stacks']}",
        f"workflow_hooks={summary['total_hooks']}",
        f"modeled_skills={summary['modeled_skills']}",
        f"reflective_stacks={summary['reflective_stacks']}",
    ]


def _workflow_stacks(
    skills: dict[str, dict[str, str]],
    bindings: list[SkillHookBinding],
    hooks: list[WorkflowHook],
) -> tuple[WorkflowStack, ...]:
    """Internal helper for workflow stacks in the workflow graphs workflow."""
    stacks = [
        *_manual_reasoning_stacks(skills),
        *_stage_stacks(skills, bindings, hooks),
    ]
    seen: set[str] = set()
    unique: list[WorkflowStack] = []
    for stack in stacks:
        if stack.stack_id in seen or not stack.steps:
            continue
        seen.add(stack.stack_id)
        unique.append(stack)
    return tuple(unique)


def _manual_reasoning_stacks(skills: dict[str, dict[str, str]]) -> tuple[WorkflowStack, ...]:
    """Internal helper for manual reasoning stacks in the workflow graphs workflow."""
    return (
        _stack(
            stack_id="source-to-reasoner-promotion-loop",
            label="Source To Reasoner Promotion Loop",
            family="Extraction And Promotion",
            description="Turns PDF/workbook evidence into candidates, promotion ledger entries, and reasoner-eligible records.",
            trigger="source ingestion or candidate promotion changes",
            artifact_entrypoints=(
                "data/extracted/extraction_quality_report.yaml",
                "data/candidates/extraction_candidates.yaml",
                "data/candidates/promotion_ledger.yaml",
            ),
            skill_names=(
                "source-integrity-curator",
                "policy-clause-formalizer",
                "feature-grounding-validator",
                "core-reasoning-case-builder",
            ),
            skills=skills,
            reflective_edges=(
                {
                    "from": "feature-grounding-validator",
                    "to": "policy-clause-formalizer",
                    "output": "finding",
                },
                {
                    "from": "core-reasoning-case-builder",
                    "to": "source-integrity-curator",
                    "output": "gate_decision",
                },
            ),
        ),
        _stack(
            stack_id="advisor-communication-control-loop",
            label="Advisor Communication Control Loop",
            family="Recommendation Safety",
            description="Turns controlled reasoning outputs into advisor-visible artifacts while preserving no-send and human-validation gates.",
            trigger="advisor card or value-case artifact generation",
            artifact_entrypoints=(
                "build/ruler/advisor_card.yaml",
                "build/ruler/value_case.yaml",
                "build/ruler/value_case_demo.html",
            ),
            skill_names=(
                "recommendation-trace-guardian",
                "informalization-visualization-agent",
                "governance-human-review-gate",
            ),
            skills=skills,
            reflective_edges=(
                {
                    "from": "governance-human-review-gate",
                    "to": "informalization-visualization-agent",
                    "output": "gate_decision",
                },
            ),
        ),
        _stack(
            stack_id="customer-demonstrator-evidence-loop",
            label="Customer Demonstrator Evidence Loop",
            family="Demonstration And Evidence",
            description="Builds attractive customer demonstrations from live use cases, decision packets, caveats, and control proof.",
            trigger="customer demonstrator catalogue generation",
            artifact_entrypoints=(
                "data/use_cases/customer_demonstrators.yaml",
                "build/ruler/customer_demonstrators/customer_demonstrators.json",
                "build/ruler/customer_demonstrators/customer_demonstrators.html",
            ),
            skill_names=(
                "customer-demonstrator-scenario-curator",
                "customer-demonstrator-artifact-builder",
                "customer-demonstrator-control-auditor",
            ),
            skills=skills,
            reflective_edges=(
                {
                    "from": "customer-demonstrator-control-auditor",
                    "to": "customer-demonstrator-scenario-curator",
                    "output": "finding",
                },
                {
                    "from": "customer-demonstrator-control-auditor",
                    "to": "customer-demonstrator-artifact-builder",
                    "output": "gate_decision",
                },
            ),
        ),
        _stack(
            stack_id="generative-workflow-router-loop",
            label="Generative Workflow Router Loop",
            family="Workflow Routing",
            description="Maps prose user intent to bounded RULER hooks, skills, commands, artifacts, and validators.",
            trigger="natural-language workflow request or route catalogue regeneration",
            artifact_entrypoints=(
                "data/use_cases/workflow_router.yaml",
                "build/ruler/workflow_router/workflow_router.yaml",
                "build/ruler/workflow_router/sample_route_packets.yaml",
            ),
            skill_names=(
                "ruler-generative-workflow-router",
                "ruler-workflow-graph-modeler",
                "ruler-workflow-graph-reporter",
            ),
            skills=skills,
            reflective_edges=(
                {
                    "from": "ruler-workflow-graph-reporter",
                    "to": "ruler-generative-workflow-router",
                    "output": "routing_gap",
                },
            ),
        ),
        _stack(
            stack_id="reasoning-log-evidence-loop",
            label="Reasoning Log Evidence Loop",
            family="Observability And Logs",
            description="Turns bounded reasoning events into JSONL/JSON/YAML streams and Markdown/HTML review surfaces.",
            trigger="reasoning log generation, audit review, or process-trace request",
            artifact_entrypoints=(
                "build/ruler/reasoning_logs/latest.jsonl",
                "build/ruler/reasoning_logs/latest.md",
                "build/ruler/reasoning_logs/latest.html",
            ),
            skill_names=(
                "policy-reasoning-log-guardian",
                "ruler-generative-workflow-router",
                "ruler-workflow-graph-reporter",
            ),
            skills=skills,
            reflective_edges=(
                {
                    "from": "policy-reasoning-log-guardian",
                    "to": "ruler-generative-workflow-router",
                    "output": "routing_gap",
                },
                {
                    "from": "ruler-workflow-graph-reporter",
                    "to": "policy-reasoning-log-guardian",
                    "output": "missing_artifact",
                },
            ),
        ),
    )


def _stage_stacks(
    skills: dict[str, dict[str, str]],
    bindings: list[SkillHookBinding],
    hooks: list[WorkflowHook],
) -> list[WorkflowStack]:
    """Internal helper for stage stacks in the workflow graphs workflow."""
    bindings_by_stage: dict[str, list[SkillHookBinding]] = defaultdict(list)
    for binding in bindings:
        for stage in binding.stages:
            bindings_by_stage[stage].append(binding)
    stacks: list[WorkflowStack] = []
    for hook in hooks:
        stage_bindings = bindings_by_stage.get(hook.hook, [])
        if not stage_bindings:
            continue
        skill_names = tuple(binding.skill for binding in stage_bindings)
        stacks.append(
            _stack(
                stack_id=f"hook-{hook.hook}",
                label=f"Hook: {_humanize(hook.hook)}",
                family="Hook Contracts",
                description=hook.description,
                trigger=f"uv run ruler hook run {hook.hook}",
                artifact_entrypoints=tuple(command.command for command in hook.commands),
                skill_names=skill_names,
                skills=skills,
                reflective_edges=(),
            )
        )
    return stacks


def _stack(
    *,
    stack_id: str,
    label: str,
    family: str,
    description: str,
    trigger: str,
    artifact_entrypoints: tuple[str, ...],
    skill_names: tuple[str, ...],
    skills: dict[str, dict[str, str]],
    reflective_edges: tuple[dict[str, str], ...],
) -> WorkflowStack:
    """Internal helper for stack in the workflow graphs workflow."""
    steps = tuple(
        WorkflowStep(
            skill=skill_name,
            role=_role_for_skill(skill_name),
            posture=_posture_for_skill(skill_name),
            output=_output_for_role(_role_for_skill(skill_name)),
            description=skills.get(skill_name, {}).get(
                "description", f"Run {_humanize(skill_name)}."
            ),
            trigger=trigger,
        )
        for skill_name in skill_names
    )
    return WorkflowStack(
        stack_id=stack_id,
        label=label,
        family=family,
        description=description,
        trigger=trigger,
        artifact_entrypoints=artifact_entrypoints,
        steps=steps,
        reflective_edges=reflective_edges,
    )


def _load_workflow_hooks() -> list[WorkflowHook]:
    payload = read_yaml(HOOKS_FILE)
    return [WorkflowHook.model_validate(item) for item in payload.get("hooks", [])]


def _load_skill_bindings() -> list[SkillHookBinding]:
    payload = read_yaml(SKILL_HOOKS_FILE)
    return [SkillHookBinding.model_validate(item) for item in payload]


def _skill_inventory() -> dict[str, dict[str, str]]:
    """Internal helper for skill inventory in the workflow graphs workflow."""
    inventory: dict[str, dict[str, str]] = {}
    for name, skill in sorted(discover_skill_files().items()):
        inventory[name] = {
            "path": repo_relative_skill_path(skill),
            "description": skill.description,
            "group": skill.group,
        }
    return inventory


def _role_for_skill(skill: str) -> str:
    """Internal helper for role for skill in the workflow graphs workflow."""
    if any(term in skill for term in ("orchestrator", "workflow", "builder")):
        return "orchestrator"
    if any(term in skill for term in ("guardian", "gate", "validator", "auditor", "curator")):
        return "guard"
    if any(term in skill for term in ("analyst", "critic", "review")):
        return "critic"
    if any(term in skill for term in ("ranker", "solver")):
        return "solver"
    if any(term in skill for term in ("formalizer", "designer", "agent")):
        return "writer"
    return "agent"


def _output_for_role(role: str) -> str:
    """Internal helper for output for role in the workflow graphs workflow."""
    return {
        "orchestrator": "workflow_context",
        "guard": "gate_decision",
        "critic": "finding",
        "solver": "solver_trace",
        "writer": "report_artifact",
        "agent": "workflow_update",
    }[role]


def _posture_for_skill(skill: str) -> str:
    if any(term in skill for term in ("designer", "formalizer", "agent", "analyst")):
        return "both"
    return "deterministic"


def _family_id(family: str) -> str:
    return "family:" + re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


def _edge_id(source: str, target: str, edge_type: str) -> str:
    return f"edge:{edge_type}:{source}:{target}".replace(" ", "-")


def _add_edge(
    edges: list[dict[str, Any]],
    source: str,
    target: str,
    edge_type: str,
    output: str,
    label: str,
) -> None:
    """Internal helper for add edge in the workflow graphs workflow."""
    edges.append(
        {
            "data": {
                "id": _edge_id(source, target, edge_type),
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "output_type": output,
                "label": label,
            }
        }
    )


def _humanize(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


def _summary_cards(summary: dict[str, Any]) -> str:
    """Internal helper for summary cards in the workflow graphs workflow."""
    labels = {
        "stacks": "Workflow Stacks",
        "total_hooks": "Total Steps",
        "modeled_skills": "Modeled Skills",
        "available_skills": "Available Skills",
        "unmodeled_skills": "Unmodeled Skills",
        "shared_skills": "Shared Skills",
        "reflective_stacks": "Reflective Stacks",
        "families": "Workflow Families",
    }
    return "\n".join(
        f'<article class="card"><strong>{html.escape(str(value))}</strong><span>{html.escape(labels[key])}</span></article>'
        for key, value in summary.items()
    )


def _workflow_cards(model: dict[str, Any]) -> str:
    """Internal helper for workflow cards in the workflow graphs workflow."""
    cards = []
    for stack in model["stacks"].values():
        hooks = "\n".join(
            f"<li><b>{hook['index']}. {html.escape(_humanize(hook['skill']))}</b> <span>{html.escape(hook['role'])} / {html.escape(hook['execution_posture'])}</span><p>{html.escape(hook['description'])}</p></li>"
            for hook in stack["ordered_hooks"]
        )
        loops = (
            "\n".join(
                f"<li>{html.escape(edge['from'])} returns {html.escape(edge['output'])} to {html.escape(edge['to'])}</li>"
                for edge in stack["reflective_edges"]
            )
            or "<li>No reflective edge declared.</li>"
        )
        cards.append(f"""
<details class="workflow-card">
  <summary>{html.escape(stack["label"])} <em>{html.escape(stack["family"])}</em></summary>
  <p>{html.escape(stack["description"])}</p>
  <h4>Ordered Steps</h4>
  <ol>{hooks}</ol>
  <h4>Reflective Loops</h4>
  <ul>{loops}</ul>
</details>
""")
    return "\n".join(cards)
