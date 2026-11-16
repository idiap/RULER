# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the organized formalized-KB layout.

The KB manifest is the bridge between legacy rule locations and the curated
`kb/formalized/...` tree, so these tests pin paths, hashes, and executable surfaces.
"""

from __future__ import annotations

from ruler.kb.formalized_kb import KB_FILE_SPECS, KB_MANIFEST, write_formalized_kb_artifacts
from ruler.io import read_yaml
from ruler.runtime.validation import validate_formalized_kb


def test_inventory_preserves_canonical_corpus_hashes():
    from ruler.kb.corpus_manifest import sha256_file
    from ruler.paths import REPO_ROOT

    artifacts = write_formalized_kb_artifacts()
    assert artifacts["manifest"].exists()
    manifest = read_yaml(KB_MANIFEST)
    assert len(manifest["entries"]) == len(KB_FILE_SPECS)
    assert {"legal", "regulatory", "technical_support"} <= {
        e["branch"] for e in manifest["entries"]
    }
    for entry in manifest["entries"]:
        assert entry["kb_path"].startswith("kb/corpora/")
        assert entry["kb_sha256"] == sha256_file(REPO_ROOT / entry["kb_path"])
    assert validate_formalized_kb()
