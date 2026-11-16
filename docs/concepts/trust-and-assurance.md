<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Trust and assurance model

Ruler separates five kinds of evidence so that convenience never becomes authority.

| Layer | What it can establish | What it cannot establish |
|---|---|---|
| Source evidence | What a pinned document span or structured source contains | That an interpretation or formalization is correct |
| Formal KB release | Reviewed rules, axioms, facts, constraints, and explicit scope | Facts absent from the release or applicability outside its scope/date |
| Solver evaluation | Consequences of declared facts and formal rules | Legal advice, causal truth, missing evidence, or permission to act |
| Historical case | Comparable operational experience and observed outcomes | Current compliance, approval, licensing, deductibility, or safety |
| Generative component | Candidate extraction, normalization, translation, and explanation | Promotion, authoritative inference, or autonomous external action |

## Core invariants

- Unknown, false, redacted, and not-applicable are distinct values.
- Every authoritative inference is pinned to an immutable rule release and evidence.
- Hard eligibility and safety constraints run before optimization or recommendation.
- Target support and contrary support are evaluated separately.
- Historical approvals and dispositions are never transferred to a current case.
- Adapted precedent patterns are re-evaluated against current rules.
- Mutation requires explicit permission, confirmation, concurrency control, and audit.
- User-facing explanations expose artifact-level traces, never hidden chain-of-thought.

## Lifecycle

```text
source -> extracted candidate -> formalization draft -> reviewed artifact
       -> candidate release -> published immutable release -> evaluation/replay
```

Promotion is explicit. Candidate rules are useful for review but are not active truth.
Published artifacts are corrected through a new release or supersession, not overwrite.

## CBR decision boundary

```text
current case -> hard filters -> deterministic similarities/differences
             -> typed adaptation -> current-rule verification
             -> human disposition -> independently reviewed observed outcome
```

A high similarity score cannot fill a missing approval, tax fact, regulatory control,
classification, licence, source document, or safe operating condition. An outcome is
retained separately from the decision that preceded it, with an independent reviewer
and an explicit causal-claim boundary.

## Public-law and external-source boundary

The demonstration regulatory, fiscal, and trade corpora include dated discovery
metadata and reviewer-gated rules. Their manifests state when exact official snapshots,
effective-date analysis, fresh external evidence, or expert review is still required.
They must not be presented as legal, tax, or export-control advice.
