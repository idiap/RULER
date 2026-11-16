---
name: core-reasoning-case-builder
description: Build and validate registry-driven RULER domain reasoning cases with explicit corpus identity and source-grounded context.
---

# Core Reasoning Case Builder

1. Select a registered domain and a corpus manifest.
2. Load the case with `load_domain_reasoning_case` in
   `ruler/reasoning/reasoning_case.py`, supplying `domain_id`, `corpus_id`,
   `case_payload`, and `domain_registry`.
3. Preserve the domain pack's context validation and evidence requirements.
4. Keep solver evaluation and application recommendations in their registered
   workflows. Case loading alone does not establish a decision.
5. Reject mismatched domain identities and missing corpus identifiers.

Use `uv run ruler workflow cbr-case` for the case-based reasoning demonstrator,
then `uv run ruler validate cbr` and `uv run pytest -q tests/domains`.
