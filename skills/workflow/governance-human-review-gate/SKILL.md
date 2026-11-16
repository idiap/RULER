---
name: governance-human-review-gate
description: Enforce RULER governance boundaries for human review, no-send controls, audit logging, stale sources, and workflow hook validation. Use when recommendations, explanations, policy changes, or customer-status changes may affect advisor or client actions.
---

# Governance Human Review Gate

Keep the controlled reasoning layer auditable and human-gated.

## Procedure

1. Run `uv run ruler validate all`.
2. Check `.ruler/hooks.yaml` when adding a new workflow stage.
3. Check `skills/SKILL_HOOKS.yaml` when adding or changing a skill.
4. Ensure generated recommendations require human validation.
5. Ensure outbound communication remains blocked until explicit advisor validation exists.

## Gates

- Active dispute, cancellation-in-progress, and closed/deceased states are absolute blockers.
- Material policy changes require human review before reusing old explanations.
- Workflow hooks must stay visible and deterministic.
