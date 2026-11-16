<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Development

Change the project and run the relevant checks. This section is for maintainers and operators.

Use [AGENTS.md](../../AGENTS.md) and [contributing](contributing.md).
Start with checks appropriate to the changed surface. Before the complete gate,
install SWI-Prolog and prepare the required browser and reports:

```bash
uv run playwright install chromium
uv run ruler prepare checks
uv run ruler validate all
```

On Linux CI, use `uv run playwright install --with-deps chromium`.
Preparation uses recorded local evidence. Validators must not generate or repair
their inputs. The full offline gate includes tests, Ruff, and whitespace checks;
live acquisition and generative evaluations remain separate operations.

## Read next

- [Documentation maintenance](documentation.md) — Shared structure, preservation, and review rules.

- [Contributing](../development/contributing.md) — Design rules, focused checks, and extension process.
- [Agent instructions](../../AGENTS.md) — Canonical commands and repository guardrails.
- [Release checklist](../operations/release-checklist.md) — Required evidence and offline gate.
- [Software disclosure](../development/software-disclosure.md) — Branch and evidence setup.

Return to the [documentation index](../README.md) or consult the
[documentation map](../reference/documentation-map.md) for the complete retained collections.
