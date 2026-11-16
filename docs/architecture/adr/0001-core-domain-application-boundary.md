<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# ADR 0001: Core, domain, and application boundary

- Status: accepted
- Date: 2026-08-30

## Decision

The package remains branded **RULER** and keeps the `ruler` Python package and CLI. Ruler
is the repository/generalization initiative, not a second runtime brand. The canonical neutral
document type is **NormativeUnit**. “Provision” is a valid domain label, but would incorrectly
exclude definitions, table rows, requirements, and cross-references.

The dependency direction is:

```text
applications/demonstrators -> domain packs -> neutral contracts/core
compatibility adapters ----> domain packs + neutral contracts + frozen v1 schemas
neutral contracts/core -X-> concrete domain packs
```

Core owns content identity, sources, evidence spans, formalization lifecycle, typed logic,
compilation, releases, evaluation envelopes, runtime controls, and registries. A domain pack
owns its document kinds, metadata, taxonomy, predicates, value types, translations, validators,
case loader, scope matcher, and optional projections. Applications own candidate selection,
optimization, recommendations, and human-facing reports.

Published v1 schemas and hashes remain immutable. V2 is additive. A compatibility adapter must
retain original payloads and report ambiguity or loss; it may not silently re-hash v1 records.

## Existing module classification

Every current `ruler` module is covered by exactly one row below. More-specific rows take
precedence over directory rows.

| Module or module family | Layer | Migration note |
|---|---|---|
| `contracts.*`, `io`, `paths` | core | Neutral public contracts and infrastructure. |
| `ingestion.*`, `source.*` | core (legacy debt) | Product catalogue vocabulary is to move into packs. |
| `domains.base`, `domains.registry` | core extension boundary | These modules never import a concrete pack. |
| `interfaces.*` | demonstrator | Labels and cards may consume pack projections, never define semantics. |
| `compat.*`, `schemas` | compatibility | `schemas` is the frozen v1 export surface. |
| `testing.*` | core test support | Domain fixtures remain outside this package. |
| package `__init__` modules | same layer as their package | They only expose that package’s public API. |

No module is renamed by this ADR. The classification records debt without changing published
paths or artifact identity.

## Public v2 names

`AuthoritativeSource`, `EvidenceSpan`, `NormativeUnit`, `FormalRule`, `EvidenceGrounding`,
`CaseContext`, `RuleConsequence`, `EvaluationRequest`, and `EvaluationPacket` are canonical.
Application-specific vocabulary belongs in domain packs; authoritative documents use
`issuing_authority` or `publisher`.

## Enforcement

`scripts/audit_domain_coupling.py` parses imports and annotated public fields. It rejects concrete domain imports and application fields in core contracts. Any
temporary exception must be an exact file/field entry in `PUBLIC_CORE_TERM_ALLOWLIST`; the empty
initial allowlist is intentional. Architecture tests run the audit in CI.
