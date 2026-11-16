# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for bounded, manifest-driven exact-document extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from ruler.cli import main
from ruler.source import source_corpus


def _write_manifest(path: Path, documents: list[dict[str, object]]) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "manifest_id": "phase_04_exact_sources",
                "mode": "bounded_exact_document_extraction_only",
                "documents": documents,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_exact_document_extraction_processes_only_manifest_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_manifest = tmp_path / "exact.yaml"
    output_manifest = tmp_path / "extracted.yaml"
    first_url = "https://provider.example/policy-a.pdf?utm_source=catalogue"
    second_url = "https://provider.example/policy-b.pdf"
    first_id = source_corpus._document_id("https://provider.example/policy-a.pdf")
    second_id = source_corpus._document_id(second_url)
    _write_manifest(
        input_manifest,
        [
            {
                "document_id": first_id,
                "organization": "official_provider",
                "fetch_url": first_url,
                "row_refs": ["refs/products.xlsx#Produits!1"],
            },
            {
                "document_id": second_id,
                "organization": "official_provider",
                "fetch_url": second_url,
            },
        ],
    )
    calls: list[dict[str, object]] = []

    def fake_extract(entry: dict[str, object], **limits: object) -> dict[str, object]:
        calls.append({"entry": entry, **limits})
        return {
            **entry,
            "status": "extracted",
            "content_kind": "pdf",
            "raw_sha256": f"sha256:{str(entry['document_id'])[-1] * 64}",
            "extracted_artifacts": [
                {"kind": "section_index", "path": f"sections/{entry['document_id']}.yaml"}
            ],
            "discovered_document_urls": ["https://provider.example/not-enqueued.pdf"],
            "autoformalized": False,
        }

    monkeypatch.setattr(source_corpus, "_download_and_extract_entry", fake_extract)

    first = source_corpus.extract_exact_documents(
        input_manifest,
        output_manifest=output_manifest,
        max_download_bytes=1024,
        max_pdf_pages=20,
    )
    second = source_corpus.extract_exact_documents(
        input_manifest,
        output_manifest=output_manifest,
        max_download_bytes=1024,
        max_pdf_pages=20,
    )

    assert len(calls) == 4
    assert [call["entry"]["document_id"] for call in calls[:2]] == [
        first_id,
        second_id,
    ]
    assert calls[0]["entry"]["fetch_url"] == "https://provider.example/policy-a.pdf"
    assert all(call["max_download_bytes"] == 1024 for call in calls)
    assert all(call["max_pdf_pages"] == 20 for call in calls)
    assert first == second
    assert first["summary"] == {
        "selected_documents": 2,
        "documents_extracted": 2,
        "documents_failed": 0,
        "pdf_documents": 2,
        "html_documents": 0,
        "discovered_documents_enqueued": 0,
        "autoformalization_outputs_written": 0,
        "published_outputs_written": 0,
    }
    assert yaml.safe_load(output_manifest.read_text(encoding="utf-8")) == first


def test_exact_document_manifest_rejects_scope_and_secrets_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_manifest = tmp_path / "unsafe.yaml"
    _write_manifest(
        input_manifest,
        [
            {
                "document_id": source_corpus._document_id(
                    "https://provider.example/policy.pdf?api_key=do-not-record"
                ),
                "organization": "official_provider",
                "fetch_url": "https://provider.example/policy.pdf?api_key=do-not-record",
            }
        ],
    )
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(source_corpus, "_download_and_extract_entry", fail_if_called)

    with pytest.raises(ValueError, match="sensitive query field") as error:
        source_corpus.extract_exact_documents(input_manifest)

    assert called is False
    assert "do-not-record" not in str(error.value)


def test_exact_document_cli_forwards_bounded_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_manifest = tmp_path / "exact.yaml"
    output_manifest = tmp_path / "result.yaml"
    _write_manifest(input_manifest, [])
    seen: dict[str, object] = {}

    def fake_extract(path: Path, **options: object) -> dict[str, object]:
        seen.update({"manifest_path": path, **options})
        return {
            "summary": {
                "selected_documents": 1,
                "documents_extracted": 1,
                "documents_failed": 0,
            }
        }

    monkeypatch.setattr("ruler.cli.extract_exact_documents", fake_extract)
    result = CliRunner().invoke(
        main,
        [
            "sources",
            "extract-documents",
            "--manifest",
            str(input_manifest),
            "--output-manifest",
            str(output_manifest),
            "--max-download-bytes",
            "4096",
            "--max-pdf-pages",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen == {
        "manifest_path": input_manifest,
        "output_manifest": output_manifest,
        "force": False,
        "max_download_bytes": 4096,
        "max_pdf_pages": 30,
    }
    assert "bounded exact-document extraction complete" in result.output
