---
name: cbr-case-retriever
description: Retrieve deterministic authorized precedents with decomposed similarity and a materially excluded near-match.
---

# CBR Case Retriever

## Input contracts

- `RetrievalRequest`, published case-library release, digest-matched `SimilarityProfile`, authorized field set

## Output artifacts

- ordered `RetrievedCase` top-k, excluded contrast, hard-filter ledger, contribution decomposition, and redaction ledger

## Procedure

Apply access, temporal, release, jurisdiction, and case-kind filters before scoring. Score only declared features, use stable case-id tie-breaking and diversity, and include one useful excluded contrast.

## Prohibited inferences

- Never score an unauthorized or hard-incompatible case.
- Never claim that a precedent disposition or outcome applies to the query.
- Never reveal hidden candidates through counts, snippets, graph edges, or rank gaps.

## Files owned

- `skills/reasoning/cbr-case-retriever/SKILL.md`
- retrieval packets under `build/ruler/cbr/retrieval/`

## Validation

`uv run ruler validate cbr`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `uv run ruler validate skills`
