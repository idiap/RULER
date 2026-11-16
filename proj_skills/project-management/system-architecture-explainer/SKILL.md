---
name: system-architecture-explainer
description: Generate RULER systems architecture explanations for project management, planning, stakeholder alignment, and technical handoff, grounded in current source packages, workflows, KB boundaries, validation gates, and runtime adapters.
---

# System Architecture Explainer

Use this skill when producing or refreshing a systems architecture explanation for
RULER.

## Procedure

1. Read the current source layout before writing:
   - `ruler/reasoning/`
   - `ruler/kb/`
   - `ruler/source/`
   - `ruler/interfaces/`
   - `ruler/runtime/`
   - `ruler/solvers/`
   - `kb/`, `data/`, `.ruler/hooks.yaml`, `skills/SKILL_HOOKS.yaml`
2. Explain the architecture as a system of responsibilities, not as a file list.
3. Make the source-to-KB-to-reasoning-to-interface flow explicit.
4. Keep control boundaries visible:
   - source extraction is not automatic formalization;
   - candidate formalizations are not promoted KB truth;
   - advisor/customer outputs remain human-review gated;
   - MCP and CLI workflows are bounded by allowlists and validation gates.
5. Include the commands that regenerate or validate the architecture-relevant artifacts.
6. Write durable docs under `docs/`; do not edit the main `README.md` unless requested.

## Recommended Sections

- Purpose
- System Context
- Architectural Layers
- Data and Control Flow
- Knowledge-Base Boundary
- Reasoning Boundary
- Runtime and Integration Boundary
- Validation and Observability
- Extension Points

## Gates

- Do not claim external communication is automated.
- Do not show candidate-only KB artifacts as active truth.
- Do not describe source extraction as autoformalization unless a promotion gate is named.
- Do not omit validation gates when explaining a workflow boundary.
