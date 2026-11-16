<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Cross-Platform RULER

RULER is intended to run on macOS, Linux, and Windows through the same Python and `uv` command surface.

## Setup

```bash
uv sync --extra dev
uv run python scripts/install_hooks.py
uv run ruler validate cross-platform
```

The Python hook installer works across platforms. The shell wrapper `scripts/install_hooks.sh` remains available for POSIX environments.

## Command Rules

- Prefer `uv run ruler ...` commands.
- Prefer `uv run python ...` for local Python scripts.
- Avoid relying on `./script.sh`, `chmod`, `sed`, `grep`, `find`, `cp`, or `rsync` in documented required workflows.
- Keep generated artifact identifiers repo-relative and use forward slashes in machine-readable logs.

## Hooks

Git hook files in `.githooks/` remain POSIX shell files because Git executes hooks through its own hook mechanism. Install them with:

```bash
uv run python scripts/install_hooks.py
```

The RULER hook runner executes configured hook commands as parsed argument lists instead of through a platform shell.

## Validation

The complete gate needs SWI-Prolog on `PATH` and the Chromium version matching the
locked Playwright package. Install SWI-Prolog using `brew install swi-prolog` on
macOS, `sudo apt-get install swi-prolog-nox` on Ubuntu, or the official Windows
installer at <https://www.swi-prolog.org/download/stable>. On Windows, include the
installation's `bin` directory in `PATH`. Verify it with `swipl --version`.

```bash
uv run playwright install chromium
uv run ruler prepare checks
```

On Linux CI, use `uv run playwright install --with-deps chromium`. Rerun browser
installation after upgrading Playwright. Preparation regenerates local reports,
reasoning evidence, and demonstrations in dependency order. The source-readiness
report preserves the recorded extraction manifest and its original dates; it does
not claim a new download, publish a release, or invoke a live generative provider.
Run preparation after a fresh checkout or deleting `build/ruler`.

```bash
uv run ruler validate cross-platform
uv run ruler validate all
uv run pytest -q
```

The cross-platform validator checks setup documentation, hook command portability, shell-independent hook execution, and repo-relative reasoning-log artifact IDs.
