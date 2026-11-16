---
name: controlled-english-translator
description: Translate source-language units into controlled English while preserving meaning, caveats, exclusions, limits, and source alignment. Use when producing English translations from segmented non-English policy, product, legal, or customer-facing text.
---

# Controlled English Translator

Translate source units into English without breaking alignment or legal meaning.

## Procedure

1. Translate one source unit at a time using the stable `unit_id`.
2. Apply the controlled glossary before choosing phrasing.
3. Preserve modality: must, may, can, shall, excluded, limited, conditional, optional.
4. Preserve numbers, dates, currency, time windows, locations, thresholds, and exception scopes exactly.
5. Preserve vocabulary-normalization governed terms so `tests/fixtures/translation/catalogue.yaml` can link concepts and senses.
6. Keep source-order when it carries legal or policy interpretation.
7. Emit a translator note when English needs clarification, not silent smoothing.

## Output Contract

Each translated unit should expose:

- `unit_id`
- `source_language`
- `english_text`
- `terminology_entry_ids`
- `preserved_values`
- `translation_notes`
- `confidence`
- `needs_human_review`

## Gates

- Do not introduce recommendations or customer value claims during translation.
- Do not infer missing policy meaning from adjacent clauses unless explicitly marked as context.
- If a word-for-word rendering and fluent rendering differ materially, keep the fluent English plus a literal note.
