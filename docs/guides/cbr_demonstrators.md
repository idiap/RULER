<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Case-based reasoning demonstrators

The CBR demonstrator builder produces six dependency-free HTML/JSON pairs: one for
each realistic domain journey and one portfolio comparison. The artifacts are designed
for local review, demonstrations, and audit evidence; they do not execute actions.

## Journeys

| Domain | Current case | Formal boundary |
|---|---|---|
| Spending | CHF 71,800 GPU procurement | approval and quote requirements cannot be copied from precedent |
| Regulatory | operational recruitment AI in France | current effective rules, oversight, and notice control deployment |
| Fiscal | Swiss mixed-rate travel invoice | business-purpose evidence controls the input-tax conclusion |
| Trade | controller and firmware export to Turkey | classification, screening, and licence review control shipment |
| Technical support | revision-C controller E-42 | safety interlock and version-compatible procedures control recovery |

Every journey shows the typed query, positive and negative precedents, a deliberately
excluded near-match, typed adaptation operations, the reviewed scenario rule outcome,
counterfactuals, release pins, and non-reliance labels.

## Honest retrieval presentation

Each artifact keeps two layers separate:

1. **Live deterministic retrieval** is produced by `CBRService.retrieve` with the
   canonical feature registry and similarity profile. It includes the request identity,
   selected case IDs, candidate count, trace, and whether the result exactly matches the
   reviewed demonstration.
2. **Reviewed demonstration precedents** define the golden educational journey. Their
   historical dispositions are labelled as experience, never as current authorization.

This distinction makes ranking drift and abstention reviewable. The renderer never
silently promotes a curated case into a live engine result.

## Generate and validate

CLI usage:

```bash
uv run ruler cbr libraries
uv run ruler cbr retrieve spending
uv run ruler cbr compare spending \
  spend-precedent-microscope-009 spend-precedent-compute-014
uv run ruler cbr adapt spending spend-precedent-microscope-009
uv run ruler cbr verify spending
uv run ruler workflow cbr-demonstrators
uv run ruler workflow cbr-benchmark
uv run ruler validate cbr
```

`ruler cbr retain OUTCOME.json` validates without writing. Add `--apply` only after
independent review. The HTTP retention endpoint additionally requires confirmation,
ETag, and idempotency headers.

Programmatic generation:

```python
from pathlib import Path

from ruler.interfaces.cbr_demonstrators import (
    validate_cbr_demonstrators,
    write_cbr_demonstrator_artifacts,
)

paths = write_cbr_demonstrator_artifacts(Path("build/cbr_demonstrators"))
evidence = validate_cbr_demonstrators()
```

The writer returns twelve named paths: HTML and JSON for five domains, plus
`portfolio.html` and `portfolio.json`.

## Authenticated workspace API

The KB workspace mounts a bearer-only CBR surface. Query-string tokens are rejected
for these routes.

```text
GET  /cases
GET  /cases/{domain_id}
GET  /api/cbr/libraries
GET  /api/cbr/libraries/{domain_id}
GET  /api/cbr/cases/{domain_id}/{case_id}
POST /api/cbr/retrieve
GET  /api/cbr/compare
POST /api/cbr/plan
POST /api/cbr/verify
GET  /api/cbr/runs/{sha256_run_id}
GET  /api/cbr/outcomes
POST /api/cbr/outcomes
```

Retrieval is limited to ten results and the canonical immutable libraries. Verification
creates a content-addressed replay record and never executes the proposed action.
Outcome retention is the sole mutating CBR API: it requires `X-CBR-Confirm:
retain:{outcome_id}`, a current collection `If-Match` value, an `Idempotency-Key`, a
known case, `review_state=reviewed`, and a reviewer different from the original
proposer. `GET /api/cbr/outcomes` supplies the current ETag and redacts source details.

MCP exposes exactly five CBR tools—list libraries, show a redacted case, retrieve,
compare, and plan adaptation. MCP has no verification, outcome-retention, case-editing,
or library-publishing operation.

## Safety and accessibility

- All case-derived HTML is escaped.
- Pages contain no JavaScript or external resources and carry a restrictive content
  security policy.
- Semantic headings, landmarks, captions, scoped table headings, skip links, visible
  focus, and a mobile layout are provided.
- Synthetic facts, source limitations, human-review requirements, and non-reliance
  boundaries are shown on every domain page.
- An outcome from a prior case never supplies a missing approval, licence, tax fact,
  regulatory control, or safe technical procedure.
