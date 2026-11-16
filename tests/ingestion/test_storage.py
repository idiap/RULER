# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ruler.ingestion import AppendOnlySourceStore, SourceVersion, canonical_sha256, stable_id


def _version(payload: bytes) -> SourceVersion:
    task_id = "source_task:test"
    raw_hash = canonical_sha256(payload)
    return SourceVersion(
        source_version_id=stable_id(
            "source_version", {"source_task_id": task_id, "raw_sha256": raw_hash}
        ),
        source_task_id=task_id,
        raw_sha256=raw_hash,
        byte_length=len(payload),
        retrieved_at=datetime(2026, 8, 13, tzinfo=UTC),
        submitted_url="https://example.test/policy",
        final_url="https://example.test/policy.pdf",
        http_status=200,
        content_type="application/pdf",
    )


def test_same_bytes_are_a_noop_and_changed_bytes_create_a_version(tmp_path) -> None:
    store = AppendOnlySourceStore(tmp_path)
    first = _version(b"version one")
    first_result = store.put(b"version one", first)
    repeated_result = store.put(b"version one", first)
    second = _version(b"version two")
    second_result = store.put(b"version two", second)

    assert first_result.created is True
    assert repeated_result.created is False
    assert second_result.created is True
    assert first_result.path != second_result.path
    assert store.read(first) == b"version one"
    assert store.read(second) == b"version two"


def test_store_recomputes_bytes_and_length(tmp_path) -> None:
    store = AppendOnlySourceStore(tmp_path)
    version = _version(b"expected")
    with pytest.raises(ValueError, match="raw_sha256"):
        store.put(b"different", version)
    with pytest.raises(ValueError, match="byte_length"):
        store.put(
            b"expected!", version.model_copy(update={"raw_sha256": canonical_sha256(b"expected!")})
        )
