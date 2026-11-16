<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# RULER Workflow Graph Visualization

RULER now carries a workflow visualization pattern adapted from the Mathformer reference project. The goal is to make the controlled reasoning stack inspectable as a graph rather than as scattered hooks, skills, and generated files.

## Artifacts

Generate the report with:

```bash
uv run ruler workflow workflow-graphs
```

Outputs:

- `build/ruler/workflow_graphs/workflow_graphs.json`
- `build/ruler/workflow_graphs/workflow_graphs.html`
- `build/ruler/workflow_graphs/workflow_layout_plan.json`

Validate the graph model and HTML surface with:

```bash
uv run ruler validate workflow-graphs
```

## Model

The graph follows the portable shape:

```text
Workflow Family -> Workflow Stack -> Ordered Workflow Step -> Skill
```

Node types:

- `family`
- `workflow`
- `workflow_step`
- `skill`

Edge types:

- `family_contains_workflow`
- `workflow_entry`
- `skill_handoff`
- `stack_uses_skill`
- `workflow_reflective_loop`

## Report Surface

The HTML report contains:

- summary cards;
- a workflow selector;
- Cytoscape.js drill-down view;
- optional reusable skill overlay;
- optional reflective edge overlay;
- static fallback workflow cards;
- embedded JSON.

The JSON model is the source of truth. The HTML is an inspection surface.

## Skill and Hook Control

Workflow visualization is visible in the repo-local control plane:

- `skills/workflow/ruler-workflow-graph-modeler/SKILL.md`
- `skills/workflow/ruler-workflow-graph-html-reporter/SKILL.md`
- `skills/workflow/ruler-workflow-graph-reporter/SKILL.md`
- `.ruler/hooks.yaml` stage: `workflow-visualization`
- `skills/SKILL_HOOKS.yaml` bindings for the three graph skills

## Current Coverage

The current graph exposes:

- source-to-reasoner promotion;
- solver decision packet construction;
- synthetic substitution regression;
- advisor communication control;
- all current hook-contract stages;
- reflective edges for trace, gate, and review feedback.
