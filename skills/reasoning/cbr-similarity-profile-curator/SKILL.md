---
name: cbr-similarity-profile-curator
description: Curate versioned deterministic CBR similarity profiles with hard compatibility, transparent weights, and proxy controls.
---

# CBR Similarity Profile Curator

## Input contracts

- domain and case kind, `FeatureRegistry`, reviewed `CBRCaseRecord` examples, access policy

## Output artifacts

- content-addressed `SimilarityProfile`, weight-normalization report, protected-field audit, and mandatory excluded contrast specification

## Procedure

Declare hard filters first, then comparator and missing-value policy per feature. Require weights to sum to one, bounded pool/top-k, temporal and release compatibility, diversity, and a contrast-only near-match.

## Prohibited inferences

- Never use protected or sensitive attributes—or correlated proxy fields—to rank candidates.
- Never tune a profile against the query's desired disposition or hide a zero-contribution feature.
- Never permit embeddings to determine eligibility or final rank.

## Files owned

- `skills/reasoning/cbr-similarity-profile-curator/SKILL.md`
- `data/use_cases/cbr/profiles/*.yaml`

## Validation

`uv run ruler validate cbr`; `uv run ruler validate skills`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`
