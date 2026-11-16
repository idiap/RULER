# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Bounded concurrency, publication-race, and regression-budget tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from ruler.ingestion import AppendOnlySourceStore, SourceVersion, canonical_sha256, stable_id
from ruler.testing.semantics import bounded_benefit, changed_dependency_descendants


def _version(payload: bytes) -> SourceVersion:
    raw_hash = canonical_sha256(payload)
    task_id = "source_task:concurrency-fixture"
    return SourceVersion(
        source_version_id=stable_id(
            "source_version",
            {"source_task_id": task_id, "raw_sha256": raw_hash},
        ),
        source_task_id=task_id,
        raw_sha256=raw_hash,
        byte_length=len(payload),
        retrieved_at=datetime(2026, 8, 13, tzinfo=UTC),
        submitted_url="https://fixture.invalid/policy.pdf",
        final_url="https://fixture.invalid/policy.pdf",
        http_status=200,
        content_type="application/pdf",
    )


def test_concurrent_duplicate_workers_commit_one_canonical_source(tmp_path: Path) -> None:
    store = AppendOnlySourceStore(tmp_path)
    payload = b"immutable policy bytes"
    version = _version(payload)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: store.put(payload, version), range(32)))
    assert sum(result.created for result in results) == 1
    assert len({result.path for result in results}) == 1
    assert store.read(version) == payload
    assert not list(tmp_path.rglob("tmp*"))


def test_scale_primitives_remain_linear_and_do_not_truncate_semantics() -> None:
    count = 20_000
    graph = {f"node:{index}": {f"node:{index + 1}"} for index in range(count - 1)}
    started = perf_counter()
    closure = changed_dependency_descendants(graph, {"node:0"})
    elapsed = perf_counter() - started
    assert len(closure) == count
    assert elapsed < 2.0

    decisions = [
        bounded_benefit(
            conditions=[True],
            excluded=False,
            exception_to_exclusion=False,
            claimed=index,
            service_fee=0,
            limit=1000,
        )
        for index in range(2_272)
    ]
    assert len(decisions) == 2_272
    assert decisions[-1].amount == 1000
