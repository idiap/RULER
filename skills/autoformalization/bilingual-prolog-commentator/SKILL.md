---
name: bilingual-prolog-commentator
description: Maintain adjacent French and English natural-language comments for each RULER Prolog mirror rule so executable predicates remain reviewable from source-language policy text.
---

# Bilingual Prolog Commentator

Use this skill when editing `rules/*.pl` mirrors.

## Procedure

1. For every Prolog rule head, add an adjacent `% NL-FR:` comment that preserves the source-language policy meaning.
2. Add an adjacent `% NL-EN:` comment with the controlled English rendering used by autoformalization.
3. Keep comments close to the rule head they explain.
4. Do not let comments introduce customer-facing claims that are absent from the source span.
5. After editing comments or predicates, run the Prolog comment and policy-rule gates.

## Gates

```bash
uv run ruler validate prolog-nl-comments
uv run ruler validate formalized-kb
```
