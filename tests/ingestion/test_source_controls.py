# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

import pytest

from ruler.ingestion import LayoutAwareChunk, OCRQualityState, PageExtractionQuality
from ruler.ingestion.contracts import canonical_sha256, stable_id
from ruler.ingestion.source_controls import (
    ConditionalRequestMetadata,
    DependencyEdge,
    FailureCategory,
    FetchCheckpoint,
    FetchFailure,
    RetryPolicy,
    classify_fetch_failure,
    invalidation_closure,
    is_stale,
    retry_call,
    write_fetch_checkpoint,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def test_conditional_headers_and_failure_taxonomy() -> None:
    metadata = ConditionalRequestMetadata(
        etag='"v1"', last_modified="Wed, 12 Aug 2026 10:00:00 GMT"
    )
    assert metadata.headers() == {
        "If-None-Match": '"v1"',
        "If-Modified-Since": "Wed, 12 Aug 2026 10:00:00 GMT",
    }
    limited = classify_fetch_failure(
        HTTPError("https://example.test", 429, "limited", {"Retry-After": "3"}, None)
    )
    missing = classify_fetch_failure(HTTPError("https://example.test", 404, "missing", {}, None))
    network = classify_fetch_failure(URLError("offline"))
    assert (limited.category, limited.transient, limited.retry_after_seconds) == (
        FailureCategory.RATE_LIMITED,
        True,
        3,
    )
    assert missing.transient is False
    assert network.category == FailureCategory.TRANSIENT_NETWORK


def test_retry_only_retries_transient_failures_with_deterministic_delays() -> None:
    calls = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise URLError("temporary")
        return "ok"

    result, attempts = retry_call(
        operation,
        RetryPolicy(maximum_attempts=3),
        seed="source:1",
        sleep=delays.append,
    )
    assert (result, attempts, len(delays)) == ("ok", 3, 2)
    with pytest.raises(HTTPError):
        retry_call(
            lambda: (_ for _ in ()).throw(
                HTTPError("https://example.test", 404, "missing", {}, None)
            ),
            RetryPolicy(maximum_attempts=3),
            seed="source:1",
            sleep=delays.append,
        )


def test_checkpoints_are_append_only_and_resumable(tmp_path) -> None:
    checkpoint = FetchCheckpoint(
        checkpoint_id="checkpoint:1",
        source_task_id="source:1",
        attempt=1,
        state="failed",
        updated_at=NOW,
        failure=FetchFailure(
            category=FailureCategory.TRANSIENT_NETWORK,
            code="timeout",
            message="timed out",
            transient=True,
        ),
    )
    path = tmp_path / "checkpoint.json"
    assert write_fetch_checkpoint(path, checkpoint) is True
    assert write_fetch_checkpoint(path, checkpoint) is False


def test_invalidation_is_exact_transitive_closure() -> None:
    edges = (
        DependencyEdge(
            source_artifact_id="version:1", dependent_artifact_id="span:1", dependency_kind="span"
        ),
        DependencyEdge(
            source_artifact_id="span:1",
            dependent_artifact_id="rule:1",
            dependency_kind="formalization",
        ),
        DependencyEdge(
            source_artifact_id="version:other",
            dependent_artifact_id="rule:other",
            dependency_kind="formalization",
        ),
    )
    record = invalidation_closure("version:1", edges, created_at=NOW)
    assert record.invalidated_artifact_ids == ("rule:1", "span:1")
    assert "rule:other" not in record.invalidated_artifact_ids
    assert is_stale(NOW, timedelta(days=30), NOW + timedelta(days=31))


def test_layout_chunk_identity_and_page_ocr_quality_are_typed() -> None:
    coordinates = {
        "source_version_id": "version:1",
        "structural_element_ids": ("element:1",),
        "page_start": 2,
        "page_end": 2,
        "bounding_boxes": ((1.0, 2.0, 3.0, 4.0),),
        "character_offsets": (10, 30),
        "heading_ancestry": ("Coverage",),
        "table_lineage": (),
    }
    chunk = LayoutAwareChunk(
        chunk_id=stable_id("layout_chunk", coordinates),
        **coordinates,
        neighboring_context_ids=("element:0", "element:2"),
        raw_text_sha256=canonical_sha256("raw"),
        cleaned_text_sha256=canonical_sha256("cleaned"),
    )
    quality = PageExtractionQuality(
        page=2,
        native_text_characters=0,
        extracted_text_sha256=canonical_sha256(""),
        quality=0.1,
        ocr_state=OCRQualityState.REQUIRED,
        warnings=("native_text_missing",),
    )
    assert chunk.page_start == quality.page
    assert quality.ocr_state == OCRQualityState.REQUIRED
