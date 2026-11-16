---
name: cbr-demonstration-artifact-builder
description: Build safe accessible CBR HTML and JSON demonstrations from five replayable decision packets.
---

# CBR Demonstration Artifact Builder

## Input contracts

- five validated `CBRDecisionPacket` artifacts, retrieval/adaptation/verification traces, replay identifiers, visibility policy

## Output artifacts

- one self-contained HTML/JSON demonstrator per domain and a portfolio comparison with accessible tabular alternatives and replay links

## Procedure

Render current rules, historical evidence, proposed adaptation, verified disposition, and later observation as distinct layers. Escape all stored content, redact unauthorized fields, label synthetic materials, and include loading/empty/error presentations.

## Prohibited inferences

- Never render a precedent as authority, merge proposal with verification, imply legal/tax/export/support reliance, reveal hidden fields, or embed executable stored content.

## Files owned

- `skills/demonstrators/cbr-demonstration-artifact-builder/SKILL.md`
- CBR outputs under `build/ruler/cbr/demonstrators/`

## Validation

`uv run ruler validate cbr`; `uv run ruler validate skills`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`
