# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Immutable on-disk representation of a published reasoning repository."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, model_validator

from ruler.ingestion.contracts import (
    AutomatedGateEvidence,
    FormalElementAnnotation,
    KBReleaseManifest,
)
from ruler.kb.repository import KnowledgeRepository, ReleasedAssertion
from ruler.schemas import SourceRecord

if TYPE_CHECKING:
    from ruler.reasoning.impact_regression import RecommendationImpactReport


class PublishedRepositoryBundle(BaseModel):
    """All records needed to replay a published release without live data."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    release: KBReleaseManifest
    assertions: tuple[ReleasedAssertion, ...]
    annotations: tuple[FormalElementAnnotation, ...]
    automated_gates: tuple[AutomatedGateEvidence, ...]
    source_records: tuple[SourceRecord, ...]
    impact_report: dict[str, Any]

    @model_validator(mode="after")
    def release_is_complete_and_published(self) -> "PublishedRepositoryBundle":
        """Revalidate source, gate, coherence, and impact evidence before loading truth."""
        source_ids = {item.source_id for item in self.source_records}
        expected_source_ids = set(self.release.source_version_hashes)
        if source_ids != expected_source_ids:
            raise ValueError(
                "published repository source records differ from release: "
                f"missing={sorted(expected_source_ids - source_ids)}, "
                f"extra={sorted(source_ids - expected_source_ids)}"
            )
        gate_ids = {item.gate_evidence_id for item in self.automated_gates}
        expected_gate_ids = set(self.release.automated_gate_hashes)
        if gate_ids != expected_gate_ids:
            raise ValueError("published repository automated gates differ from release")
        repository = KnowledgeRepository(
            self.release,
            list(self.assertions),
            list(self.annotations),
            source_records=list(self.source_records),
            automated_gates=list(self.automated_gates),
        )
        repository.require_coherent()
        from ruler.reasoning.impact_regression import RecommendationImpactReport

        RecommendationImpactReport.model_validate(self.impact_report).require_publishable(
            self.release.kb_release_id
        )
        return self

    def repository(self) -> KnowledgeRepository:
        """Construct the read-only repository after bundle-level validation succeeds."""
        return KnowledgeRepository(
            self.release,
            list(self.assertions),
            list(self.annotations),
            source_records=list(self.source_records),
            automated_gates=list(self.automated_gates),
        )


def publish_repository_bundle(
    repository: KnowledgeRepository,
    release_root: Path,
    *,
    impact_report: RecommendationImpactReport,
) -> Path:
    """Write a repository once at its content-derived release path."""

    repository.require_coherent()
    impact_report.require_publishable(repository.release.kb_release_id)
    bundle = PublishedRepositoryBundle(
        release=repository.release,
        assertions=tuple(
            sorted(repository.assertions.values(), key=lambda item: item.assertion_id)
        ),
        annotations=tuple(
            sorted(repository.annotations.values(), key=lambda item: item.annotation_id)
        ),
        automated_gates=tuple(
            sorted(repository.automated_gates.values(), key=lambda item: item.gate_evidence_id)
        ),
        source_records=tuple(
            sorted(repository.source_records.values(), key=lambda item: item.source_id)
        ),
        impact_report=impact_report.model_dump(mode="json"),
    )
    path = release_root / repository.release.kb_release_id.replace(":", "_") / "repository.json"
    payload = (
        json.dumps(
            bundle.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"immutable repository collision at {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(f"immutable repository collision at {path}")
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_repository_bundle(path: Path) -> KnowledgeRepository:
    """Load and hash-validate a published repository bundle."""

    bundle_path = path / "repository.json" if path.is_dir() else path
    bundle = PublishedRepositoryBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    return bundle.repository()
