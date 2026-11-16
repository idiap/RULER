# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Isolation, deterministic scheduling, read-only, and recovery tests."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path

import pytest

from ruler.testing.harness import (
    HarnessContext,
    IsolatedPipelineHarness,
    atomic_write,
    canonical_json_bytes,
)
from ruler.testing.offline_http import OfflineHttpResolver


def _harness(tmp_path: Path) -> IsolatedPipelineHarness:
    context = HarnessContext(
        root=tmp_path / "isolated",
        clock=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        locale="fr_CH",
        timezone="Europe/Zurich",
        http=OfflineHttpResolver({}),
        extractor=lambda body, mime: {"size": len(body), "mime": mime},
        model_adapter=lambda value: value,
        event_sink=lambda event: None,
        seed=73,
    )
    return IsolatedPipelineHarness(context)


def test_validator_is_detected_if_it_writes(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    stage = harness.stage("candidate")
    (stage / "artifact.json").write_bytes(b"{}")

    def bad_validator(root: Path) -> None:
        (root / "artifact.json").write_bytes(b'{"repaired":true}')

    with pytest.raises(RuntimeError, match="HARNESS_VALIDATOR_WROTE_STATE"):
        harness.validate_read_only(stage, bad_validator)


def test_two_worker_schedules_produce_identical_semantic_bytes(tmp_path: Path) -> None:
    harness = _harness(tmp_path)

    def generate(root: Path, seed: int, workers: int) -> None:
        records = [{"id": value, "seed": seed} for value in range(4)]
        traversal = list(reversed(records)) if workers == 2 else records
        for record in traversal:
            atomic_write(root / f"{record['id']}.json", canonical_json_bytes(record))

    harness.assert_reproducible(generate)


def test_interrupted_and_resumed_output_matches(tmp_path: Path) -> None:
    harness = _harness(tmp_path)

    def full(root: Path) -> None:
        for index in range(3):
            atomic_write(root / f"{index}.txt", str(index).encode())

    def resumed(root: Path) -> None:
        atomic_write(root / "0.txt", b"0")
        for index in range(1, 3):
            atomic_write(root / f"{index}.txt", str(index).encode())

    harness.assert_resume_equivalent(full, resumed)


def test_failed_atomic_commit_preserves_previous_canonical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "release.json"
    target.write_bytes(b"previous")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated disk failure"):
        atomic_write(target, b"candidate")
    assert target.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".release.json.tmp-*"))


def test_harness_rejects_protected_or_escaping_root(tmp_path: Path) -> None:
    context = HarnessContext(
        root=tmp_path / "repo" / "build",
        clock=lambda: datetime.now(UTC),
        locale="C",
        timezone="UTC",
        http=OfflineHttpResolver({}),
        extractor=lambda body, mime: None,
        model_adapter=lambda value: value,
        event_sink=lambda event: None,
    )
    with pytest.raises(ValueError, match="HARNESS_PROTECTED_ROOT"):
        IsolatedPipelineHarness(context, protected_roots=(tmp_path / "repo",))
    safe = _harness(tmp_path)
    with pytest.raises(ValueError, match="HARNESS_PATH_ESCAPE"):
        safe.context.resolve("../../outside")
