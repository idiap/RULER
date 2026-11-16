# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Atomic, resumable operational boundary for provider-neutral ingestion stages."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, ConfigDict, Field

from ruler.ingestion.contracts import canonical_sha256, stable_id

OPERATIONAL_STAGES = (
    "plan",
    "discover",
    "fetch",
    "extract",
    "assess-completeness",
    "formalize-candidates",
    "review",
    "compile",
    "publish",
    "validate",
    "replay-impacts",
)


class ResourceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_bytes: int = Field(default=100_000_000, ge=0)
    pages: int = Field(default=2_000, ge=0)
    ocr_pages: int = Field(default=500, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    retries: int = Field(default=3, ge=0)
    concurrency: int = Field(default=4, ge=1)
    per_host_per_minute: int = Field(default=30, ge=1)
    duration_seconds: int = Field(default=3_600, ge=1)


class ResourceUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_bytes: int = 0
    pages: int = 0
    ocr_pages: int = 0
    model_calls: int = 0
    tokens: int = 0
    retries: int = 0


class StageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    run_id: str
    stage: str
    provider: str
    batch_id: str
    status: str
    attempt: int
    dry_run: bool
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    selectors: tuple[str, ...]
    output_root: str
    checkpoint: str
    usage: ResourceUsage
    budget: ResourceBudget
    counts: dict[str, int]
    artifact_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    failure: dict[str, str] | None = None


@dataclass
class AtomicRun:
    """Stage privately and expose a checkpoint only after all artifacts commit."""

    output_root: Path
    run_id: str
    stage: str
    _staged: list[tuple[Path, bytes]] = field(default_factory=list)

    @property
    def stage_root(self) -> Path:
        """Return the private directory for this run and lifecycle stage."""
        return self.output_root / "runs" / self.run_id / self.stage

    def stage_bytes(self, relative: Path, payload: bytes) -> None:
        """Queue an artifact while preventing paths from escaping the stage root."""
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("artifact path must stay inside the stage root")
        self._staged.append((relative, payload))

    def commit(self, report: StageReport) -> bool:
        """Atomically expose staged artifacts and return false for an exact no-op."""
        manifest = (json.dumps(report.model_dump(mode="json"), sort_keys=True) + "\n").encode()
        checkpoint = self.output_root / report.checkpoint
        if checkpoint.exists() and checkpoint.read_bytes() == manifest:
            return False
        for relative, payload in self._staged:
            _atomic_write(self.stage_root / relative, payload)
        _atomic_write(checkpoint, manifest)
        return True


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def enforce_budget(usage: ResourceUsage, budget: ResourceBudget) -> None:
    """Stop a stage before partial publication when any declared resource cap is exceeded."""
    for name in ("download_bytes", "pages", "ocr_pages", "model_calls", "tokens", "retries"):
        if getattr(usage, name) > getattr(budget, name):
            raise RuntimeError(f"budget_exceeded:{name}")


def run_stage(
    stage: str,
    *,
    provider: str,
    batch_id: str,
    selectors: tuple[str, ...] = (),
    output_root: Path,
    dry_run: bool = False,
    resume: bool = False,
    budget: ResourceBudget | None = None,
    usage: ResourceUsage | None = None,
) -> StageReport:
    """Create one controlled stage checkpoint without implicit cross-stage writes."""
    if stage not in OPERATIONAL_STAGES:
        raise ValueError(f"unknown ingestion operation: {stage}")
    budget = budget or ResourceBudget()
    identity = {"provider": provider, "batch": batch_id, "stage": stage, "selectors": selectors}
    run_id = stable_id("run", identity).split(":", 1)[1][:20]
    checkpoint = Path("checkpoints") / run_id / f"{stage}.json"
    checkpoint_path = output_root / checkpoint
    if resume and checkpoint_path.exists():
        return StageReport.model_validate_json(checkpoint_path.read_text(encoding="utf-8"))
    started = datetime.now(UTC)
    before = time.monotonic()
    usage = usage or ResourceUsage()
    try:
        enforce_budget(usage, budget)
    except RuntimeError as exc:
        completed = datetime.now(UTC)
        report = StageReport(
            run_id=run_id,
            stage=stage,
            provider=provider,
            batch_id=batch_id,
            status="blocked",
            attempt=1,
            dry_run=dry_run,
            started_at=started,
            completed_at=completed,
            duration_ms=int((time.monotonic() - before) * 1000),
            selectors=selectors,
            output_root=str(output_root),
            checkpoint=checkpoint.as_posix(),
            usage=usage,
            budget=budget,
            counts={"changed": 0, "unchanged": 0, "blocked": 1},
            artifact_ids=(),
            warnings=(),
            failure={
                "category": "resource_budget",
                "code": str(exc),
                "remediation": "resume with an explicitly reviewed larger budget",
            },
        )
        if not dry_run:
            AtomicRun(output_root, run_id, stage).commit(report)
        return report
    artifact_id = stable_id("artifact", identity)
    report = StageReport(
        run_id=run_id,
        stage=stage,
        provider=provider,
        batch_id=batch_id,
        status="planned" if dry_run else "completed",
        attempt=1,
        dry_run=dry_run,
        started_at=started,
        completed_at=datetime.now(UTC),
        duration_ms=int((time.monotonic() - before) * 1000),
        selectors=selectors,
        output_root=str(output_root),
        checkpoint=checkpoint.as_posix(),
        usage=usage,
        budget=budget,
        counts={"changed": 0, "unchanged": 0, "blocked": 0},
        artifact_ids=() if dry_run else (artifact_id,),
        warnings=(),
    )
    if not dry_run:
        transaction = AtomicRun(output_root, run_id, stage)
        payload = {"artifact_id": artifact_id, "content_hash": canonical_sha256(identity)}
        transaction.stage_bytes(
            Path("stage_manifest.json"), (json.dumps(payload, sort_keys=True) + "\n").encode()
        )
        transaction.commit(report)
    return report
