---
name: ruler-workflow-graph-modeler
description: Build the typed RULER workflow graph model from hooks, skill bindings, reasoning stacks, and reflective edges. Use when workflow structure needs JSON inspection or visualization.
---

# RULER Workflow Graph Modeler

Convert RULER workflow contracts into a typed graph model.

## Model

Use:

- `family`
- `workflow`
- `workflow_step`
- `skill`

Edges:

- `family_contains_workflow`
- `workflow_entry`
- `skill_handoff`
- `stack_uses_skill`
- `workflow_reflective_loop`

## Procedure

1. Read `.ruler/hooks.yaml`.
2. Read `skills/SKILL_HOOKS.yaml`.
3. Preserve ordered workflow steps separately from reusable skill nodes.
4. Mark critic, guard, trace, and governance feedback as reflective edges.
5. Keep `workflow_graphs.json` as the source of truth for downstream reports.

## Commands

```bash
uv run ruler workflow workflow-graphs
uv run ruler validate workflow-graphs
```

## Gates

- The graph must contain family, workflow, workflow-step, and skill nodes.
- The graph must expose at least one reflective stack.
- JSON must remain deterministic and inspectable.
