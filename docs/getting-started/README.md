<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Getting started

Install the environment and complete a first example. This section is for readers learning or using RULER.

Use Python 3.12 or newer, Git, and `uv`. From the repository root:

```bash
uv sync --extra dev
uv run ruler validate deps
uv run ruler --help
```

SWI-Prolog is a separate system executable required by workflows that declare Prolog
acceptance checks. The complete gate also requires browser and report preparation;
follow [getting started](README.md) before running it.
For agent skill discovery, see the [plugin guide](../guides/plugins.md).

## Read next

- [Installation and first use](../getting-started.md) — Install, prepare checks, choose an interface, and inspect outputs.
- [Plugin setup](../guides/plugins.md) — Canonical skills in supported agent clients.
- [Cross-platform operation](../guides/cross_platform.md) — Portable execution and system dependencies.

Return to the [documentation index](../README.md) or consult the
[documentation map](../reference/documentation-map.md) for the complete retained collections.
