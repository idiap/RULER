<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Running RULER in Codex

Install the four product workflow skills as the `ruler` plugin using the
[plugin guide](plugins.md). Both direct repository loading and a generated,
flat skills-only distribution are available; the runtime checkout stays separate
from the installed plugin cache.

Codex reads `AGENTS.md` at the repository root and uses the canonical skills in
`skills/`. Both surfaces invoke the installed RULER CLI, so agent execution has
the same contracts and validators as direct terminal use.

## Setup

```bash
uv sync --extra dev --locked
uv run ruler prepare agent-config
uv run ruler validate codex
```

Ask Codex to run a named workflow or use a canonical skill. Keep execution at
the `uv run ruler ...` boundary and validate meaningful changes with the narrow
gate for that workflow.

The bridge itself is checked with:

```bash
uv run ruler validate codex
uv run ruler validate cross-platform
```

Agent instruction files and client-specific directories are ignored by Git.
`uv run ruler prepare agent-config` creates defaults from maintained project
documentation and preserves existing local customizations. Run it explicitly
before validating a fresh checkout; validation never generates these files.
