<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Architecture

Understand components, data flow, contracts, and extension points. This section is for readers learning or using RULER.

```text
source evidence → semantic basis → candidate facts and rules → acceptance gates
                → immutable formal KB → inference / optimization
                → decision packet, counterfactuals, and grounded explanation
```

`ruler/` implements the canonical CLI, typed contracts, ingestion, KB management,
reasoning, interfaces, and runtime adapters. `kb/` holds declarative knowledge;
`skills/` holds runtime skills; `proj_skills/` holds maintenance skills.
Agent bridges and MCP invoke the same CLI and contracts.

Read the [system architecture](system_architecture.md),
[trust model](../concepts/trust-and-assurance.md), and
[repository walkthrough](directory_structure_walkthrough.md).

## Read next

- [Current system architecture](../architecture/system_architecture.md) — Components, trust boundaries, and extension points.
- [Architecture diagrams](../architecture/system_architecture_diagrams.md) — Component and data-flow diagrams.
- [Directory walkthrough](../architecture/directory_structure_walkthrough.md) — Source, tests, inputs, and outputs.
- [Core/domain/application ADR](../architecture/adr/0001-core-domain-application-boundary.md) — Domain-neutral core boundary.
- Initial MVP slice — Retained first-slice design; current overview takes precedence.

Return to the [documentation index](../README.md) or consult the
[documentation map](../reference/documentation-map.md) for the complete retained collections.
