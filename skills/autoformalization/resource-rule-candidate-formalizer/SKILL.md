---
name: resource-rule-candidate-formalizer
description: Generate source-locked resource-rule candidates and keep them inactive until deterministic semantic, compiler, solver, and human-review gates pass.
---

# Resource Rule Candidate Formalizer

Invoke `uv run ruler portfolio generate-rule-candidates` only for bounded,
source-grounded autoformalization. Use the construction or other registered domain
pack to close the allowed vocabulary. Preserve exact spans, actors, modality,
exceptions, quantities, units, scope, and effective time.

Generated rules are always `candidate_uncommitted`. Run deterministic schema,
vocabulary, Clingo behavior, Z3 conflict/boundary, and feasible-space checks before
review. A model response or model self-review cannot promote a rule.

## Validation

`uv run ruler validate resource-portfolio`; explicit unmocked generation uses the
repository generative integration/release profile.
