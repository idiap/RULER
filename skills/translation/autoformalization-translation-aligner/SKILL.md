---
name: autoformalization-translation-aligner
description: Align extracted source-language policy spans with controlled English translation units before formalization drafts are promoted into RULER reasoner artifacts.
---

# Autoformalization Translation Aligner

Use this skill when extracted PDF spans need controlled English counterparts before becoming formalizable units, policy clauses, or rule drafts.

## Procedure

1. Run `uv run ruler workflow translation-control`.
2. Inspect `build/ruler/translation_control/source_fr_units.yaml` for source span anchors and source-language text.
3. Inspect `build/ruler/translation_control/controlled_english_units.yaml` for controlled English statements and semantic constraints.
4. Ensure `build/ruler/translation_control/alignment_report.yaml` marks every source span as `pass`.

## Gates

```bash
uv run ruler validate translation-control
```
