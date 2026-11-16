# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the extraction-only source corpus layer.

The source-corpus workflow may crawl and extract documents, but it must not
autoformalize or silently drop failed source links.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ruler.ingestion import stable_id
from ruler.source import source_corpus


def _write_exact_document_manifest(
    path: Path,
    document: dict[str, object],
) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "manifest_id": "retrieval_url_test",
                "mode": "bounded_exact_document_extraction_only",
                "documents": [document],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class _SampleResponse:
    status = 200
    headers = {"content-type": "application/pdf", "etag": '"sample"'}

    def __init__(self, url: str) -> None:
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit: int) -> bytes:
        return b"%PDF-1.4 bounded sample"

    def geturl(self) -> str:
        return self._url


def test_exact_document_retrieval_url_controls_transport_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    canonical_url = "https://provider.example/conditions/policy.html"
    retrieval_url = "https://cdn.example/current/policy.html"
    document_id = source_corpus._document_id(canonical_url)
    manifest_path = tmp_path / "exact.yaml"
    _write_exact_document_manifest(
        manifest_path,
        {
            "document_id": document_id,
            "organization": "official_provider",
            "fetch_url": canonical_url,
            "retrieval_url": retrieval_url,
        },
    )
    _manifest, documents = source_corpus._load_exact_document_manifest(manifest_path)
    entry = documents[0]
    downloaded_urls: list[str] = []
    html_base_urls: list[str] = []
    versions: list[object] = []

    def fake_download(
        url: str,
        raw_dir: Path,
        **_options: object,
    ) -> tuple[Path, str]:
        downloaded_urls.append(url)
        raw_path = raw_dir / "source.html"
        raw_path.write_text('<a href="policy.pdf">Policy</a>', encoding="utf-8")
        return raw_path, "text/html"

    def fake_extract_html(
        _raw_path: Path,
        _extracted_dir: Path,
        base_url: str,
    ) -> tuple[list[dict[str, str]], list[str]]:
        html_base_urls.append(base_url)
        return [], []

    class CapturingStore:
        def __init__(self, root: Path) -> None:
            self.root = root

        def put(self, _payload: bytes, version: object) -> SimpleNamespace:
            versions.append(version)
            return SimpleNamespace(path=self.root / "captured")

    monkeypatch.setattr(source_corpus, "SOURCE_RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(source_corpus, "SOURCE_EXTRACTED_DIR", tmp_path / "extracted")
    monkeypatch.setattr(source_corpus, "_download_bytes", fake_download)
    monkeypatch.setattr(source_corpus, "_extract_html_artifacts", fake_extract_html)
    monkeypatch.setattr(source_corpus, "AppendOnlySourceStore", CapturingStore)
    monkeypatch.setattr(source_corpus, "repo_relative_posix", lambda path: str(path))

    retrieved = source_corpus._download_and_extract_entry(entry, force=True)
    canonical_only = source_corpus._download_and_extract_entry(
        {key: value for key, value in entry.items() if key != "retrieval_url"},
        force=True,
    )

    assert retrieved["status"] == "extracted"
    assert canonical_only["status"] == "extracted"
    assert downloaded_urls == [retrieval_url, canonical_url]
    assert html_base_urls == [retrieval_url, canonical_url]
    assert versions[0].submitted_url == canonical_url
    assert versions[0].final_url == retrieval_url
    assert versions[1].submitted_url == canonical_url
    assert versions[1].final_url == canonical_url
    expected_retrieval_task_id = stable_id(
        "source_task",
        {
            "provider_id": "official_provider",
            "canonical_url": canonical_url,
            "retrieval_url": retrieval_url,
        },
    )
    expected_canonical_task_id = stable_id(
        "source_task",
        {
            "provider_id": "official_provider",
            "canonical_url": canonical_url,
        },
    )
    assert retrieved["source_task_id"] == expected_retrieval_task_id
    assert canonical_only["source_task_id"] == expected_canonical_task_id
    assert retrieved["source_task_id"] != canonical_only["source_task_id"]


@pytest.mark.parametrize(
    "retrieval_url",
    [
        "ftp://cdn.example/policy.pdf",
        "https://user:password@cdn.example/policy.pdf",
        "https://cdn.example/policy.pdf?token=do-not-record",
        "http://localhost/policy.pdf",
        "http://127.0.0.1/policy.pdf",
    ],
)
def test_exact_document_manifest_rejects_unsafe_retrieval_urls(
    retrieval_url: str,
    tmp_path: Path,
) -> None:
    canonical_url = "https://provider.example/conditions/policy.pdf"
    manifest_path = tmp_path / "unsafe.yaml"
    _write_exact_document_manifest(
        manifest_path,
        {
            "document_id": source_corpus._document_id(canonical_url),
            "organization": "official_provider",
            "fetch_url": canonical_url,
            "retrieval_url": retrieval_url,
        },
    )

    with pytest.raises(ValueError) as error:
        source_corpus._load_exact_document_manifest(manifest_path)

    assert "do-not-record" not in str(error.value)


def test_cached_extraction_reuses_existing_source_version_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_task_id = stable_id("source_task", {"provider_id": "provider"})
    raw_sha256 = "sha256:" + "a" * 64
    version_id = stable_id(
        "source_version",
        {"source_task_id": source_task_id, "raw_sha256": raw_sha256},
    )
    existing = source_corpus.SourceVersion(
        source_version_id=version_id,
        source_task_id=source_task_id,
        raw_sha256=raw_sha256,
        byte_length=12,
        retrieved_at=source_corpus.datetime.fromisoformat(source_corpus.SOURCE_CORPUS_TIMESTAMP),
        submitted_url="https://provider.example/policy",
        final_url="https://provider.example/policy",
        http_status=200,
        content_type="text/html; charset=utf-8",
    )
    candidate = existing.model_copy(update={"content_type": "text/html"})
    monkeypatch.setattr(source_corpus, "SOURCE_RAW_DIR", tmp_path)
    metadata_path = (
        tmp_path / "_content_addressed" / "versions" / f"{version_id.replace(':', '_')}.json"
    )
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(existing.model_dump_json(), encoding="utf-8")

    reused = source_corpus._preserve_existing_source_version_metadata(candidate)

    assert reused == existing
    assert reused.content_type == "text/html; charset=utf-8"
