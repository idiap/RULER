---
name: informalization-visualization-agent
description: Generate controlled advisor cards, compliance notes, and visualization specs from RULER traces only. Use when translating formal reasoning traces into human-readable explanations, causal chains, or dashboard-ready visual specs without adding unsupported claims.
---

# Informalization Visualization Agent

Explain from the trace; do not invent.

## Procedure

1. Run the registered domain workflow or load an existing validated trace; for the
   machine portfolio use `uv run ruler workflow resource-portfolio-demonstrator`.
2. Generate advisor-facing text from trace facts, source clauses, rules fired, solver runs, and uncertainty flags.
3. Generate visuals as specs such as Mermaid, Vega-Lite, or ECharts with trace references.
4. Include human validation controls in every advisor or client-facing output.
5. Preserve uncertainty and blockers.

## Gates

- Do not add product claims absent from the trace.
- Do not remove uncertainty flags or human-review banners.
- Client-facing text remains draft-only until advisor validation is logged.
