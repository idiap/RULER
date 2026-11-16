---
name: ruler-workflow-graph-html-reporter
description: Render RULER workflow graph JSON into an HTML explorer with summary cards, Cytoscape drill-down, optional reflection edges, and static workflow cards.
---

# RULER Workflow Graph HTML Reporter

Render workflow graph artifacts for human inspection.

## Report Surfaces

- summary cards;
- workflow selector;
- ordered workflow drill-down;
- optional reusable-skill overlay;
- optional reflective edge overlay;
- static fallback workflow cards;
- embedded JSON model.

## Procedure

1. Use `ruler.interfaces.workflow_graphs.render_workflow_graph_html`.
2. Keep the visual surface utilitarian and readable.
3. Treat the HTML as an inspection surface, not as the source of truth.
4. Keep `workflow_graphs.json` as the canonical data model.

## Commands

```bash
uv run ruler workflow workflow-graphs
uv run ruler validate workflow-graphs
```

## Gates

- HTML must include the embedded JSON model.
- HTML must include static workflow cards for non-JavaScript inspection.
- Reflection edges must be visible but opt-in.
