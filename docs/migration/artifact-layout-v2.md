<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Artifact layout v2 migration

The v2 knowledge-base layout is corpus-oriented and domain-neutral:

```text
kb/
  corpora/<corpus-id>/manifest.yaml
  shared/
  releases/v2/<release-id>/
```

Each corpus manifest declares its domain and corpus identifiers and, for every artifact, its
document/version, lifecycle status, language, canonical path, SHA-256, local/shared references,
and temporary v1 compatibility mirrors. Canonical paths are contained under the declared corpus;
cross-corpus references are rejected rather than resolved implicitly.

## Migration contract

`ruler.kb.artifact_migration.plan_artifact_migration` is always a dry run. It reports field
mappings, ambiguity and loss, source and target hashes, and source and target IDs without writing
files. `apply_artifact_migration` revalidates the manifest and source hashes, requires explicit
acceptance of ambiguity or loss, and atomically publishes only to a fresh
`kb/releases/v2/<release-id>/` namespace. It never edits `kb/formalized/`, legacy mirrors, or an
existing release.

The generated `migration-report.json` is sufficient to audit the transformation while the v1
source remains the rollback path.

## Deprecation schedule

| Compatibility surface | Available through | Removal target |
|---|---:|---:|
| `kb/formalized/{real,synthetic}/` reads | 0.x | 2.0 |
| `kb/manifest.yaml` legacy `entries` inventory | 0.x | 2.0 |
| `rules/` and `data/` compatibility mirrors | 0.x | 2.0 |
| v1 skill aliases | 1.x | 2.0 |

Published v1 artifacts and releases are immutable and are retained after compatibility readers
are removed. Removal means ending the legacy read/command surface, never deleting historical
evidence.
