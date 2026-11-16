<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Add a corpus

Each v2 corpus is isolated under `kb/corpora/<corpus-id>/` and declared by
`kb/corpora/<corpus-id>/manifest.yaml`.

The strict manifest requires:

- schema version, domain ID, corpus ID, and description;
- stable artifact and document IDs;
- document version, review status, language, category, and artifact type;
- repository-contained POSIX paths and current SHA-256 hashes;
- local or explicitly shared references;
- optional byte-identical legacy mirrors during a deprecation cycle.

Cross-corpus references and path/symlink escapes fail closed. Published source artifacts should
be copied into the corpus namespace; do not point a v2 canonical artifact at mutable external
state.

Validate with:

```bash
uv run ruler corpora list
uv run ruler corpora validate --manifest kb/corpora/<corpus-id>/manifest.yaml
uv run ruler corpora schema
```

For legacy data, plan an immutable migration first:

```bash
uv run ruler migrate artifacts \
  --manifest kb/manifest.yaml \
  --release-name <new-release>
```

The command is dry-run by default. `--apply` writes only to a fresh
`kb/releases/v2/<release-name>/` namespace and never overwrites a v1 or existing v2 release.
