---
name: source-text-intake-segmenter
description: Segment source-language documents into stable, cited translation units before translation to English. Use when ingesting non-English policy, product, legal, or customer-facing text that needs controlled translation, alignment, provenance, or reviewable unit IDs.
---

# Source Text Intake Segmenter

Create stable source units before any English rendering.

## Procedure

1. Identify source language, document ID, version, page/row/section anchors, and extraction method.
2. Split text into minimal translation units that preserve legal or policy meaning.
3. Assign stable IDs such as `srcdoc_section_003_sentence_002`.
4. Preserve original text verbatim for every unit.
5. Capture neighboring context when a sentence depends on a title, table header, footnote, exception, or definition.
6. Flag OCR noise, ambiguous abbreviations, formatting loss, and unresolved references before translation.

## Output Contract

Each unit should expose:

- `unit_id`
- `source_language`
- `source_document_id`
- `source_anchor`
- `source_text`
- `context_before`
- `context_after`
- `layout_notes`
- `blocking_issues`

## Gates

- Never translate before source-unit IDs exist.
- Do not merge clauses, exclusions, limits, or exceptions if separate translation decisions may be needed.
- Keep source text immutable after segmentation; corrections should create a new source-unit version.
