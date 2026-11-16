---
name: ruler-workflow-graph-reporter
description: Orchestrate RULER workflow visualization generation across typed graph JSON, layout plan, HTML explorer, hooks, skills, and validation.
---

# RULER Workflow Graph Reporter

Own the end-to-end workflow visualization pipeline.

## Pipeline

```text
hooks + skill bindings + reasoning stacks
  -> typed workflow graph JSON
  -> layout plan
  -> HTML explorer
  -> workflow graph validation
```

## Procedure

1. Generate artifacts with `uv run ruler workflow workflow-graphs`.
2. Validate them with `uv run ruler validate workflow-graphs`.
3. Keep graph generation deterministic.
4. Keep reflective loops visible as typed feedback edges.
5. Keep workflow cards available as a static fallback.

## Outputs

- `build/ruler/workflow_graphs/workflow_graphs.json`
- `build/ruler/workflow_graphs/workflow_graphs.html`
- `build/ruler/workflow_graphs/workflow_layout_plan.json`

## Gates

- Graph summary counts must be nonzero.
- Skill/hook validation must still pass.
- Workflow visualization must not replace deterministic validation gates.
