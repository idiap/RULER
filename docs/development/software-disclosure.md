<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Idiap software disclosure

`main` is the source-only disclosure branch. Its tracked tree excludes `data/`,
`kb/`, and `refs/`, including third-party provider documents, extracted text, and
bundled evidence and derivatives whose redistribution licenses are unknown.
The same scope also excludes synthetic fixtures stored inside those bundles.
The canonical application `skills/` catalogue remains part of the source tree.

`development` retains the complete evidence bundles and the project SD and agent
files: `.idiap-sd/`, `.claude/`, `.opencode/`, `AGENTS.md`, and `CLAUDE.md`.
These paths are ignored on `main`. Local copies remain available after the branch
split, but fresh source-only checkouts must restore inputs before corpus-dependent
workflows or tests can run. Personal caches and runtime workspaces remain ignored
on both branches.

Historical commits still contain evidence. Removing paths from the current `main`
tree does not purge Git history or other branches. A repository-wide disclosure
must account for that history and for the intentionally complete `development`
branch. No history rewriting or remote publication is performed by this setup.

There is no retained disclosure archive or generated disclosure snapshot.
`check.sh` audits attribution and LFS metadata without requiring an archive.
Its REUSE check uses a temporary copy of the source scope and removes that copy
when the check finishes. Downloaded evidence is preserved byte-for-byte and is
never relicensed by the SD helper.

## Prepare a checkout

For complete local development, use the `development` branch. To run complete
checks from a `main` checkout, restore the evidence and SD support as local inputs
from the development revision you intend to validate:

```sh
git restore --source=development --worktree -- data kb refs .idiap-sd
uv sync --extra dev --locked
npm --prefix codex-app-workbench ci
uv run playwright install chromium
uv run ruler prepare agent-config
uv run ruler prepare checks
./check.sh
```

`git restore --worktree` leaves the source-only index unchanged. The restored
paths are ignored on `main`; do not force-add them there. If only a remote
`development` branch exists, fetch it and use `origin/development` as the restore
source. Agent setup generates missing defaults from maintained public project
documentation and preserves existing local instructions. Validators remain
read-only and require their inputs to be prepared first.

SWI-Prolog (`swipl`) and Git LFS are required for the complete gate. On Linux,
use `uv run playwright install --with-deps chromium`. LFS tracking for the large
recorded evidence stays on `development`; history is not rewritten.

CI runs project tests, frontend checks, static checks, and complete RULER validation
independently of local SD tooling. On `main`, its evidence setup restores only
`data/`, `kb/`, and `refs/` from a pinned development commit into the ignored working
tree. Push that development commit together with the source-only branch before
expecting remote CI to fetch it. The input revision is recorded in
`.github/actions/development-evidence/action.yml`; update it deliberately when
updating evidence. Deployment consumes the passing quality run's validated inputs.

CI rejects tracked evidence and agent/SD files before restoring its local inputs.
Transfer source changes between branches selectively; a full development merge
must preserve the source-only path policy on `main`.

## Local SD checks

```sh
uv run python .idiap-sd/idiap_sd.py check --metadata-only
uv run python .idiap-sd/idiap_sd.py reuse
```

The complete `check.sh` additionally runs Python tests, Ruff, Black, Pyright,
Vulture, both frontend suites, RULER validation, and whitespace checks. Every
required check runs and contributes to the exit status. Missing SD support or
project evidence is an error, never a silently skipped check.

Pyright checks application and executable tooling code. Pytest covers test
fixtures that deliberately exercise invalid inputs. Vulture's configured ignored
names cover framework-required callback arguments.

## Copyright and contributor attribution

Comment-capable source files carry copyright, contributor, and current-license
SPDX headers. `REUSE.toml` uses file-type patterns for formats without comments
and `SKILL.md` definitions. Ordinary Markdown, shell scripts, and other
comment-capable sources use their own headers, with no directory-wide manifest
annotations. Hash-locked YAML fixtures retain their bytes and use adjacent
`.license` notices instead.

André Freitas is the sole contributor outside the areas attributed to Danilo.
Danilo Gusicuma is the sole contributor credited for the MCP server, project
services and worker; PostgreSQL persistence, schema, migrations and deployment
initialization; the four product workflow adapters; workflow registry and
execution-surface validation; and plugin packaging. These scopes include their
associated tests and dedicated MCP/plugin documentation. Headers and scoped
manifest entries record the corresponding attribution; do not restore deleted
components solely to add attribution.

The Idiap license permits non-commercial research and educational use only. Its text
is in `LICENSE` and `LICENSES/LicenseRef-Idiap-Research-Education.txt`.

Plugin distributions derive their own `REUSE.toml` from the plugin-packaging
metadata with scoped paths so attribution remains correct after files are relocated.

Run `uv run reuse lint` to validate license coverage. Local disclosure helpers
must preserve copyright, contributor, and license headers and keep their
attribution consistent with `REUSE.toml`. When restoring historical headers, use the current declared license
rather than reintroducing superseded license identifiers.
