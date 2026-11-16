# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Persistence and immutable release construction for controlled ingestion."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from ruler.ingestion.contracts import (
    CorpusSnapshot,
    IngestionBundle,
    KBReleaseManifest,
    canonical_sha256,
    ingestion_json_schemas,
    stable_id,
    validate_ingestion_bundle,
)


def write_contract_schemas(output_dir: Path) -> dict[str, Path]:
    """Persist each versioned JSON Schema and a hash-verifiable catalogue."""
    paths: dict[str, Path] = {}
    entries: dict[str, str] = {}
    for name, schema in ingestion_json_schemas().items():
        path = output_dir / "v1" / f"{name}.schema.json"
        payload = _json_bytes(schema)
        _atomic_replace(path, payload)
        paths[name] = path
        entries[name] = canonical_sha256(payload)
    catalogue = {
        "contract_version": "1.0",
        "schemas": entries,
        "catalogue_sha256": canonical_sha256(entries),
    }
    catalogue_path = output_dir / "v1" / "catalogue.json"
    _atomic_replace(catalogue_path, _json_bytes(catalogue))
    paths["catalogue"] = catalogue_path
    return paths


def build_corpus_snapshot(
    bundle: IngestionBundle, *, created_at: datetime | None = None
) -> CorpusSnapshot:
    """Pin all source versions in a bundle into a deterministic snapshot."""
    pairs = sorted((item.source_version_id, item.raw_sha256) for item in bundle.source_versions)
    return CorpusSnapshot(
        corpus_snapshot_id=stable_id("corpus_snapshot", pairs),
        source_version_ids=tuple(item[0] for item in pairs),
        source_version_sha256s=tuple(item[1] for item in pairs),
        created_at=created_at or datetime.now(UTC),
    )


def build_kb_release(
    bundle: IngestionBundle,
    snapshot: CorpusSnapshot,
    *,
    span_payloads: dict[str, Any],
    translation_payloads: dict[str, Any],
    formal_record_payloads: dict[str, Any],
    validator_payloads: dict[str, Any],
    created_at: datetime | None = None,
) -> KBReleaseManifest:
    """Build a release only from hash-bound automated gates and validated annotations."""
    validation_bundle = bundle.model_copy(update={"snapshots": (*bundle.snapshots, snapshot)})
    errors = validate_ingestion_bundle(validation_bundle)
    if errors:
        raise ValueError("invalid ingestion bundle:\n" + "\n".join(errors))

    passed_gates = {item.candidate_id: item for item in bundle.automated_gates if item.passed}
    candidates = {item.candidate_id: item for item in bundle.candidates}
    approved_elements = {
        candidates[candidate_id].formal_element_id for candidate_id in passed_gates
    }
    annotations = {
        item.annotation_id: item
        for item in bundle.annotations
        if item.review_state in {"validated", "approved"}
        and item.formal_element_id in approved_elements
    }
    compiled = [
        item
        for item in bundle.compiled_artifacts
        if set(item.formal_element_ids).issubset(approved_elements)
        and set(item.annotation_ids).issubset(annotations)
    ]
    if not approved_elements or not compiled:
        raise ValueError("a KB release requires automatically gated, annotated, compiled elements")

    source_hashes = dict(
        zip(snapshot.source_version_ids, snapshot.source_version_sha256s, strict=True)
    )
    automated_gate_hashes = {
        item.gate_evidence_id: canonical_sha256(item.model_dump(mode="json"))
        for item in passed_gates.values()
    }
    optional_review_hashes = {
        item.approval_id: canonical_sha256(item.model_dump(mode="json"))
        for item in bundle.approvals
    }
    annotation_hashes = {
        item_id: canonical_sha256(item.model_dump(mode="json"))
        for item_id, item in annotations.items()
    }
    executable_hashes = {item.compiled_artifact_id: item.payload_sha256 for item in compiled}
    validator_hashes = _hash_payloads(validator_payloads)
    available_evidence_hashes = set(validator_hashes.values())
    for gate in passed_gates.values():
        required_evidence_hashes = {
            *gate.deterministic_evidence_hashes.values(),
            gate.generative_gate_config_sha256,
            gate.generative_evidence_sha256,
        }
        missing = required_evidence_hashes - available_evidence_hashes
        if missing:
            raise ValueError(
                f"{gate.gate_evidence_id}: automated evidence payloads are not release-pinned: "
                f"{sorted(missing)}"
            )
    hash_payload = {
        "corpus_snapshot_id": snapshot.corpus_snapshot_id,
        "source_version_hashes": source_hashes,
        "span_hashes": _hash_payloads(span_payloads),
        "translation_hashes": _hash_payloads(translation_payloads),
        "formal_record_hashes": _hash_payloads(formal_record_payloads),
        "automated_gate_hashes": automated_gate_hashes,
        "optional_review_hashes": optional_review_hashes,
        "annotation_hashes": annotation_hashes,
        "executable_rule_hashes": executable_hashes,
        "validator_hashes": validator_hashes,
    }
    return KBReleaseManifest(
        kb_release_id=stable_id("kb_release", hash_payload),
        **hash_payload,
        created_at=created_at or snapshot.created_at,
    )


def publish_kb_release(release: KBReleaseManifest, release_root: Path) -> Path:
    """Persist a manifest once at its content-derived path; never overwrite it."""
    path = release_root / release.kb_release_id.replace(":", "_") / "manifest.json"
    payload = _json_bytes(release.model_dump(mode="json"))
    if path.exists():
        existing = validate_published_release(path)
        existing_content = existing.model_dump(mode="json", exclude={"created_at"})
        requested_content = release.model_dump(mode="json", exclude={"created_at"})
        if existing_content != requested_content:
            raise ValueError(f"immutable release collision at {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(f"immutable release collision at {path}")
    finally:
        temporary_path.unlink(missing_ok=True)
    return path


def validate_published_release(path: Path) -> KBReleaseManifest:
    """Reload a persisted manifest and recompute its deterministic identity."""
    release = KBReleaseManifest.model_validate_json(path.read_text(encoding="utf-8"))
    # Model validation recomputes all hash formats and the release identity.
    return release


def _hash_payloads(payloads: dict[str, Any]) -> dict[str, str]:
    return {key: canonical_sha256(value) for key, value in sorted(payloads.items())}


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)
