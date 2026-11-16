# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations


import pytest

from ruler.ingestion.adapters import (
    adapt_legacy_source_manifests,
    adapt_priority_candidates,
)
from ruler.ingestion.contracts import stable_id


def test_legacy_source_adapter_preserves_urls_rows_and_versions() -> None:
    link = {
        "selected_documents": [
            {
                "document_id": "document-1",
                "fetch_url": "https://example.test/policy.pdf",
                "submitted_url": "https://example.test/policy.pdf?utm_source=workbook",
            }
        ]
    }
    extraction = {
        "created_at": "2026-08-13T00:00:00+00:00",
        "documents": [
            {
                "document_id": "document-1",
                "organization": "provider",
                "fetch_url": "https://example.test/policy.pdf",
                "status": "extracted",
                "raw_sha256": "sha256:" + "a" * 64,
                "raw_bytes": 42,
                "content_type": "application/pdf",
                "row_refs": ["refs/catalogue.xlsx#Produits!4"],
                "products": ["Motor"],
                "extracted_artifacts": [{"kind": "text", "path": "text.txt"}],
            }
        ],
    }
    registry, versions = adapt_legacy_source_manifests(link, extraction)

    assert len(registry) == len(versions) == 1
    assert registry[0].submitted_urls == ("https://example.test/policy.pdf?utm_source=workbook",)
    assert registry[0].source_version_ids == (versions[0].source_version_id,)
    assert versions[0].raw_sha256 == "sha256:" + "a" * 64
    assert registry[0].retrieval_url is None
    assert versions[0].final_url == "https://example.test/policy.pdf"


def test_source_adapter_preserves_governed_retrieval_url_provenance() -> None:
    canonical_url = "https://provider.example/versioned/policy.pdf"
    retrieval_url = "https://provider.example/current/policy.pdf?lang=fr"
    raw_hash = "sha256:" + "d" * 64
    task_id = stable_id(
        "source_task",
        {
            "provider_id": "provider",
            "canonical_url": canonical_url,
            "retrieval_url": retrieval_url,
        },
    )
    version_id = stable_id("source_version", {"source_task_id": task_id, "raw_sha256": raw_hash})
    link = {
        "selected_documents": [
            {
                "document_id": "document-1",
                "submitted_url": canonical_url,
            }
        ]
    }
    extraction = {
        "documents": [
            {
                "document_id": "document-1",
                "organization": "provider",
                "fetch_url": canonical_url,
                "retrieval_url": retrieval_url,
                "status": "extracted",
                "raw_sha256": raw_hash,
                "raw_bytes": 42,
                "content_type": "application/pdf",
                "row_refs": ["refs/catalogue.xlsx#Produits!4"],
                "source_task_id": task_id,
                "source_version_id": version_id,
            }
        ]
    }

    registry, versions = adapt_legacy_source_manifests(link, extraction)

    assert registry[0].source_task_id == task_id
    assert registry[0].retrieval_url == retrieval_url
    assert registry[0].canonical_url == canonical_url
    assert versions[0].source_version_id == version_id
    assert versions[0].submitted_url == canonical_url
    assert versions[0].final_url == retrieval_url


def test_source_adapter_rejects_mismatched_extraction_identity() -> None:
    extraction = {
        "documents": [
            {
                "document_id": "document-1",
                "organization": "provider",
                "fetch_url": "https://provider.example/versioned/policy.pdf",
                "retrieval_url": "https://provider.example/current/policy.pdf",
                "status": "extracted",
                "raw_sha256": "sha256:" + "e" * 64,
                "raw_bytes": 42,
                "content_type": "application/pdf",
                "row_refs": ["refs/catalogue.xlsx#Produits!4"],
                "source_task_id": "source_task:" + "0" * 64,
            }
        ]
    }

    with pytest.raises(ValueError, match="source_task_id does not match URLs"):
        adapt_legacy_source_manifests({}, extraction)


def test_priority_adapter_never_infers_review_or_approval() -> None:
    link = {"selected_documents": [{"document_id": "document-1"}]}
    extraction = {
        "created_at": "2026-08-13T00:00:00+00:00",
        "documents": [
            {
                "document_id": "document-1",
                "organization": "provider",
                "fetch_url": "https://example.test/policy.pdf",
                "status": "extracted",
                "raw_sha256": "sha256:" + "b" * 64,
                "raw_bytes": 42,
                "content_type": "application/pdf",
                "row_refs": ["refs/catalogue.xlsx#Produits!4"],
            }
        ],
    }
    registry, versions = adapt_legacy_source_manifests(link, extraction)
    text_hash = "sha256:" + "c" * 64
    spans = [
        {
            "span_id": "span:1",
            "element_id": "element:1",
            "source_id": "document-1",
            "text_sha256": text_hash,
            "language": "fr",
        }
    ]
    translations = [
        {
            "translation_id": "translation:1",
            "element_id": "element:1",
            "controlled_statement": "The policy covers the loss.",
            "predicate_candidates": ["covers/2"],
        }
    ]
    drafts = [
        {
            "draft_id": "draft:1",
            "element_id": "element:1",
            "target_id": "rule:1",
            "draft_payload": {"predicate": "covers", "subject": "loss"},
        }
    ]
    units, candidates = adapt_priority_candidates(spans, translations, drafts, registry, versions)

    assert units[0].review_state == "draft"
    assert candidates[0].state == "formalization_candidate"
    assert candidates[0].source_version_id == versions[0].source_version_id
