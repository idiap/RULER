---
name: formalized-kb-curator
description: Index canonical RULER corpus artifacts and validate their immutable content hashes.
---

# Formalized KB Curator

Use `kb/corpora/*/manifest.yaml` as the authoritative artifact declarations.
Each corpus supplies its domain, evidence, formal programs, and content hashes.

1. Run `uv run ruler workflow formalized-kb` to refresh `kb/manifest.yaml`.
2. Run `uv run ruler validate formalized-kb` to check corpus identities and hashes.
3. Keep evidence, candidate assertions, and released programs distinct.
4. Use `uv run ruler workflow kb-visualizer` to inspect the indexed artifacts.

Inventory generation must not rewrite canonical source evidence or manufacture
missing releases. Review changes to corpus manifests with the affected domain.
