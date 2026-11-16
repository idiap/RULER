# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Operational guarantees for provider-neutral ingestion."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from ruler.cli import main
from ruler.ingestion.operations import ResourceBudget, ResourceUsage, enforce_budget, run_stage


def test_dry_run_is_machine_readable_and_writes_nothing(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        [
            "ingestion",
            "plan",
            "--provider",
            "sample",
            "--batch-id",
            "b1",
            "--output-root",
            str(tmp_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert '"status": "planned"' in result.output
    assert list(tmp_path.rglob("*")) == []


def test_stage_commit_is_atomic_and_resumable(tmp_path: Path) -> None:
    first = run_stage("discover", provider="sample", batch_id="b1", output_root=tmp_path)
    checkpoint = tmp_path / first.checkpoint
    assert checkpoint.exists()
    assert (tmp_path / "runs" / first.run_id / "discover" / "stage_manifest.json").exists()
    resumed = run_stage(
        "discover", provider="sample", batch_id="b1", output_root=tmp_path, resume=True
    )
    assert resumed == first


def test_budget_exhaustion_fails_before_commit(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="budget_exceeded:pages"):
        enforce_budget(ResourceUsage(pages=2), ResourceBudget(pages=1))
    assert list(tmp_path.iterdir()) == []
    report = run_stage(
        "extract",
        provider="sample",
        batch_id="b2",
        output_root=tmp_path,
        usage=ResourceUsage(pages=2),
        budget=ResourceBudget(pages=1),
    )
    assert report.status == "blocked"
    assert report.counts["blocked"] == 1
    assert report.artifact_ids == ()
    assert (tmp_path / report.checkpoint).exists()
