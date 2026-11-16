<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Running RULER In Claude Code

The four product workflow skills are also available as the `ruler` plugin:
`claude --plugin-dir /path/to/ruler`, or install `ruler@ruler` from its marketplace.
Plugin skills use `/ruler:<skill-name>`. See the [plugin guide](plugins.md) for
installation and building a skills-only distribution. The local wrappers below
remain available for repository development.

RULER is runnable in Claude Code through repo-local project memory and skills.

## Entry Points

- `CLAUDE.md`: project-level context loaded by Claude Code.
- `.claude/skills/`: Claude Code skills that become slash-invoked project workflows.
- `uv run ruler validate claude-code`: deterministic bridge validator.

## Setup

```bash
uv sync --extra dev
uv run ruler prepare agent-config
uv run ruler validate claude-code
```

## Claude Code Skills

- `/ruler-framework-runner`
- `/ruler-validation-gates`
- `/ruler-reasoning-workflows`
- `/ruler-translation-control`
- `/ruler-claude-bridge-maintainer`

## Recommended Claude Code Workflow

1. Ask Claude Code to use one of the project skills above.
2. Keep execution inside `uv run ruler ...` commands.
3. Inspect generated artifacts under `build/ruler/`.
4. Validate with the narrow relevant command and `uv run ruler validate claude-code`.

## Boundary

The canonical RULER skill catalogue remains `skills/`. The `.claude/skills/` directory contains Claude Code wrappers that route Claude to the same CLI, hooks, generated artifacts, and validators used elsewhere in the repository.

Agent instruction files and client-specific directories are ignored by Git.
`uv run ruler prepare agent-config` creates defaults from maintained project
documentation and preserves existing local customizations. Run it explicitly
before validating a fresh checkout; validation never generates these files.
