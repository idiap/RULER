<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Running RULER In OpenCode

RULER is runnable in OpenCode through `AGENTS.md`, project-local skills, and project-local commands.

## Entry Points

- `AGENTS.md`: repository instructions loaded by OpenCode.
- `.opencode/skills/`: OpenCode skills that wrap RULER workflows.
- `.opencode/commands/`: slash commands for validation, reasoning, and workflow graph regeneration.
- `uv run ruler validate opencode`: deterministic bridge validator.

## Setup

```bash
uv sync --extra dev
uv run ruler prepare agent-config
uv run ruler validate opencode
```

## OpenCode Skills

- `/ruler-framework-runner`
- `/ruler-validation-gates`
- `/ruler-reasoning-workflows`
- `/ruler-translation-control`
- `/ruler-opencode-bridge-maintainer`

## OpenCode Commands

- `/validate`: run bridge, skill, hook, or full validation gates.
- `/reason`: run reasoning workflows and inspect generated artifacts.
- `/graphs`: regenerate workflow router and graph artifacts.

## Boundary

The canonical RULER skill catalogue remains `skills/`. The `.opencode/skills/` directory contains OpenCode wrappers that route OpenCode to the same CLI, hooks, generated artifacts, and validators used elsewhere in the repository.

Agent instruction files and client-specific directories are ignored by Git.
`uv run ruler prepare agent-config` creates defaults from maintained project
documentation and preserves existing local customizations. Run it explicitly
before validating a fresh checkout; validation never generates these files.
