<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Controlled Source-to-English Translation Skills

RULER has a controlled translation skill chain for moving source-language text into English without losing provenance, terminology, limits, exclusions, or review state.

## Skill Chain

1. `source-text-intake-segmenter`: create stable source units with anchors and blocking issues.
2. `translation-terminology-curator`: define controlled bilingual terms and untranslated labels.
3. `controlled-english-translator`: translate aligned units into English with preserved values and notes.
4. `translation-fidelity-validator`: compare English units against source text, glossary, and policy-risk fields.
5. `translation-review-orchestrator`: coordinate promotion into extraction, formalization, or reasoning workflows.
6. `autoformalization-translation-aligner`: connect controlled English units to formalizable units and drafts.
7. `vocabulary-predicate-harmonizer`: map stable bilingual vocabulary to approved predicate candidates.
8. `bilingual-prolog-commentator`: keep Prolog mirror rules readable in source French and controlled English.

## Hook

Use the `translation-control` hook as the workflow checkpoint.

```bash
uv run ruler workflow translation-control
uv run ruler validate translation-control
uv run ruler validate vocabulary-predicates
uv run ruler validate prolog-nl-comments
uv run ruler hook run translation-control
```

The workflow writes:

- `build/ruler/translation_control/source_fr_units.yaml`
- `build/ruler/translation_control/controlled_english_units.yaml`
- `build/ruler/translation_control/glossary.yaml`
- `build/ruler/translation_control/vocabulary_predicate_map.yaml`
- `build/ruler/translation_control/alignment_report.yaml`

## Promotion Rule

Only translated units with `pass` status, or reviewed `warn` status with copied caveats, may enter downstream extraction candidates or formalization drafts. `needs_human_review` and `fail` remain blocked.
