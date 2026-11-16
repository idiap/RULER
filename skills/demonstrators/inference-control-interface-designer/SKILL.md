---
name: inference-control-interface-designer
description: Design, generate, and validate the RULER inference-control dashboard that surfaces facts, rules, constraints, effects, counterfactuals, solver backends, and advisor gates from live reasoning use cases.
---

# Inference Control Interface Designer

Use this skill when a RULER interface should show how the reasoner works rather than only showing the final recommendation.

## Procedure

1. Run `uv run ruler workflow inference-dashboard`.
2. Inspect `build/ruler/inference_control_dashboard/inference_control_dashboard.json` for machine-readable counts.
3. Inspect `build/ruler/inference_control_dashboard/inference_control_dashboard.html` for the dynamic control cockpit.
4. Run `uv run ruler workflow kb-visualizer` when the request is to inspect the complete knowledge base rather than a single inference case.
5. Keep the interface grounded in live use-case packets or published KB releases: activated facts, policy assertions, source evidence, solver constraints, counterfactuals, and advisor controls.
6. Do not show hidden chain-of-thought; show artifact-level inference traces and explicit counts.
7. Do not expose local or repository file locations in the KB visualizer payload.

## Gates

```bash
uv run ruler validate inference-dashboard
uv run ruler validate kb-visualizer
```
