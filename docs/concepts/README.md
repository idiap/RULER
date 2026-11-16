<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Concepts

Understand the project model, terminology, and evidence boundaries. This section is for readers learning or using RULER.

RULER turns rigorously stated natural-language sources into formal knowledge
bases, checked decisions, and traceable explanations. It combines generative
interpretation with deterministic validation and logic or optimization backends.
The result retains source evidence, accepted facts and rules, assumptions, solver
outputs, counterfactuals, and grounded explanations.

- **Formal KB releases:** manage source-grounded facts and rules with immutable identities and explicit scope.
- **Controlled autoformalization:** propose, validate, execute, and review formal statements before acceptance.
- **Solver-backed decisions:** use declared logic, optimization, or scheduling capabilities for the computed result.
- **Case-based reasoning:** retrieve governed precedents, then verify the current case against current rules.
- **Separate authority:** generative interpretation and explanation cannot promote rules or replace formal inference; unknown remains distinct from false.

## Read next

- [Trust and assurance](../concepts/trust-and-assurance.md) — Source, formal, historical, generative, and human authority.
- [System architecture](../architecture/system_architecture.md) — Knowledge representation and release-pinned evaluation.
- [Case-based reasoning](../guides/cbr_demonstrators.md) — Retrieve, adapt, verify, and retain reviewed cases.

Return to the [documentation index](../README.md) or consult the
[documentation map](../reference/documentation-map.md) for the complete retained collections.
