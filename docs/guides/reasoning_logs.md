<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# RULER Reasoning Logs

RULER emits reasoning logs as paired human and machine artifacts.

## Commands

```bash
uv run ruler workflow skill-reasoning-logs
uv run ruler validate skill-reasoning-logs
```

## Catalogue-wide skill logs

The skill reasoning-log workflow emits one normalized profile for each canonical
skill in JSONL, JSON, YAML, and Markdown. Each profile states the skill's
plain-language purpose, mode, stages, observable inputs/actions/evidence/outputs,
decision impact, declared validation boundary, executable backends, and limitations.
Each profile also states whether its mode comes from an executable binding or from
description-based inference for a workflow-composed skill.

Capability coverage and execution coverage are intentionally separate:

- `profiles.jsonl` contains exactly one observability contract per canonical skill;
- `actual_events.jsonl` contains only invocation-backed events and can therefore be empty;
- `manifest.yaml` reports both profile coverage and the number of skills with actual events.

Actual events carry a canonical skill identifier, workflow and invocation identifiers,
a monotonic sequence, status (including blocked and failed states), public
question/move/outcome/impact fields, and typed content-addressed artifact evidence.
These are inspectable execution facts, not reconstructed deliberation. Shared hook
membership is never counted as evidence that a skill ran, and secrets and hidden
chain-of-thought are excluded by schema and validation.
