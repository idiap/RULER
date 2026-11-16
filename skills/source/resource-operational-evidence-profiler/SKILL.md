---
name: resource-operational-evidence-profiler
description: Normalize resource events, reconstruct non-overlapping states, estimate provenance-bound profiles and latent demand, and build immutable planning snapshots.
---

# Resource Operational Evidence Profiler

Run the canonical evidence workflow through `uv run ruler portfolio build-snapshot`.
Use only declared units, mappings, validity intervals, and source identities. Preserve
raw events and corrections, deduplicate by stable identity, expose unresolved gaps as
`UNKNOWN`, and record every fallback used by a profile. Historical delivery is not
complete demand when supply-constraint evidence exists.

This skill is deterministic. Do not use a model to map evidence, estimate values, or
close missing safety facts.

## Validation

`uv run ruler validate resource-portfolio`
