# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Focused isolation and integrity tests for declarative corpus manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ruler.kb.corpus_manifest import (
    CorpusManifest,
    corpus_manifest_json_schema,
    discover_corpus_manifests,
    load_corpus_manifest,
    validate_corpus_manifest,
    validate_corpus_manifests,
)


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _payload(corpus_id: str, path: str, content: bytes = b"rule.\n") -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "domain_id": "regulatory",
        "corpus_id": corpus_id,
        "description": "A focused test corpus.",
        "artifacts": [
            {
                "artifact_id": "rule-1",
                "document_id": "document-1",
                "document_version": "2026-01",
                "status": "active",
                "path": path,
                "sha256": _sha(content),
                "language": "en",
                "category": "rules",
                "artifact_type": "asp-program",
                "role": "Executable test rule.",
                "references": [],
                "legacy_mirrors": [],
            }
        ],
    }


def test_load_and_validate_isolated_corpus(tmp_path: Path) -> None:
    content = b"rule.\n"
    artifact = tmp_path / "kb/corpora/regulations/rules/main.lp"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    manifest_path = tmp_path / "kb/corpora/regulations/manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(_payload("regulations", "kb/corpora/regulations/rules/main.lp")),
        encoding="utf-8",
    )

    manifest = load_corpus_manifest(manifest_path)

    assert validate_corpus_manifest(manifest, repo_root=tmp_path) == [
        "domain_id=regulatory",
        "corpus_id=regulations",
        "artifacts=1",
    ]
    assert discover_corpus_manifests(repo_root=tmp_path) == (manifest_path,)
    assert corpus_manifest_json_schema()["properties"]["schema_version"]["const"] == "2.0"


def test_manifest_rejects_duplicate_and_cross_corpus_ids() -> None:
    payload = _payload("alpha", "kb/corpora/alpha/a.lp")
    payload["artifacts"] = [*payload["artifacts"], dict(payload["artifacts"][0])]
    with pytest.raises(ValidationError, match="duplicate artifact IDs"):
        CorpusManifest.model_validate(payload)

    first = CorpusManifest.model_validate(_payload("alpha", "kb/corpora/alpha/a.lp"))
    second = CorpusManifest.model_validate(_payload("beta", "kb/corpora/beta/b.lp"))
    with pytest.raises(ValueError, match="duplicate artifact ID.*across corpora"):
        validate_corpus_manifests([first, second], verify_files=False)


def test_manifest_rejects_traversal_cross_corpus_reference_and_stale_hash(
    tmp_path: Path,
) -> None:
    traversal = _payload("alpha", "kb/corpora/alpha/../beta/rule.lp")
    with pytest.raises(ValidationError, match="normalized repository-relative"):
        CorpusManifest.model_validate(traversal)

    cross_reference = _payload("alpha", "kb/corpora/alpha/rule.lp")
    cross_reference["artifacts"][0]["references"] = ["beta:rule-2"]
    with pytest.raises(ValidationError, match="cross-corpus reference"):
        CorpusManifest.model_validate(cross_reference)

    artifact = tmp_path / "kb/corpora/alpha/rule.lp"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("changed.\n", encoding="utf-8")
    manifest = CorpusManifest.model_validate(
        _payload("alpha", "kb/corpora/alpha/rule.lp", b"original.\n")
    )
    with pytest.raises(ValueError, match="stale hash"):
        validate_corpus_manifest(manifest, repo_root=tmp_path)


def test_manifest_rejects_path_into_another_corpus(tmp_path: Path) -> None:
    artifact = tmp_path / "kb/corpora/beta/rule.lp"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"rule.\n")
    manifest = CorpusManifest.model_validate(_payload("alpha", "kb/corpora/beta/rule.lp"))
    with pytest.raises(ValueError, match="path escapes declared root"):
        validate_corpus_manifest(manifest, repo_root=tmp_path)
