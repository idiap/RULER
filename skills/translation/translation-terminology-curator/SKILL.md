---
name: translation-terminology-curator
description: Build and maintain controlled bilingual terminology for source-language to English translation. Use when domain terms, provider product labels, legal terms, clause labels, abbreviations, or recurring phrases need consistent English equivalents.
---

# Translation Terminology Curator

Keep translation choices consistent and reviewable.

## Procedure

1. Extract candidate terms from source units before translating long passages.
2. Separate product labels, policy terms, legal terms, customer-facing phrasing, abbreviations, and named entities.
3. Choose one preferred English rendering per term.
4. Keep literal alternatives when the preferred term may hide source-language nuance.
5. Mark terms that should remain untranslated.
6. Link repeated terms to canonical concepts and senses in `tests/fixtures/translation/`.
7. Map formalizable vocabulary to candidate predicates in `build/ruler/translation_control/vocabulary_predicate_map.yaml`.
8. Record reviewer decisions and unresolved terminology questions.

## Output Contract

Each glossary entry should expose:

- `term_id`
- `source_language`
- `source_term`
- `preferred_english`
- `literal_english`
- `domain`
- `usage_note`
- `do_not_translate`
- `review_status`
- `source_span_ids`

## Predicate Contract

Every glossary term used in executable reasoning should either map to an approved predicate or be explicitly held out of formalization. Check `tests/fixtures/translation/approved_predicates.yaml` before inventing a new predicate.

## Vocabulary Contract


## Gates

- Do not normalize away provider-specific product names.
- Do not translate legal terms as broad paraphrases without a literal note.
- Use the glossary for every repeated term unless a unit-specific exception is documented.
- Run `uv run ruler validate vocabulary-predicates`.
