---
name: policy-layout-section-scout
description: Map policy PDF layout into a section inventory before extraction. Use when a policy document needs selective layout analysis, Docling/PDF heading discovery, page-aware section scouting, table/list detection, or decisions about which sections are worth extracting.
---

# Policy Layout Section Scout

Use this before extracting clauses from a policy PDF.

## Procedure

1. Load the latest extracted layout surfaces:
   - `data/extracted/*docling.md`
   - `data/extracted/extraction_segments.yaml`
   - `data/extracted/extraction_quality_report.yaml`
2. Build a section inventory from headings, page estimates, and neighboring sections.
3. Preserve layout signals that change legal meaning:
   - heading hierarchy
   - tables
   - numbered subclauses
   - bullet exclusions
   - benefit amount rows
   - continuation across pages
4. Tag each section with a candidate reasoning role:
   - `scope`
   - `coverage_grant`
   - `limit`
   - `exclusion`
   - `exception_to_exclusion`
   - `duty`
   - `definition`
   - `parameter`
5. Mark sections as `promote_now`, `extract_next`, `index_only`, or `defer`.

## Output Contract

Write or update a section-plan artifact such as `data/extracted/policy_layout_extraction_plan.yaml` with:

- `source_id`
- `layout_source`
- `section`
- `title`
- `priority`
- `reasoning_role`
- `layout_requirements`
- `start_marker`
- `end_marker`
- `promotion_gate`

## Gates

- Do not extract isolated benefit amounts without the coverage condition that activates them.
- Do not promote exclusions without their parent coverage family.
- Do not promote a section if the Docling heading is missing and no fallback start/end marker exists.
- Keep indexed-but-deferred sections visible so later product-feature generalization can reuse them.
