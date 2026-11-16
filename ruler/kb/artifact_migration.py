# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Auditable, dry-run-first migration of v1 KB artifacts into v2 releases."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path, PurePosixPath
from tempfile import mkdtemp
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.ingestion.contracts import canonical_sha256, stable_id
from ruler.io import read_yaml
from ruler.kb.corpus_manifest import sha256_file
from ruler.paths import REPO_ROOT


class FieldMigration(BaseModel):
    """An explicit structured-field conversion rule and its observed impact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_field: str = Field(min_length=1)
    target_field: str | None = None
    occurrences: int = Field(ge=0)
    outcome: Literal["renamed", "unchanged", "dropped", "ambiguous"]
    note: str | None = None


class MigratedArtifact(BaseModel):
    """Hash and identifier delta for one planned artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_artifact_id: str
    target_artifact_id: str
    source_path: str
    target_path: str
    source_sha256: str
    target_sha256: str
    hash_changed: bool
    id_changed: bool
    field_mappings: tuple[FieldMigration, ...] = ()
    ambiguities: tuple[str, ...] = ()
    losses: tuple[str, ...] = ()


class ArtifactMigrationPlan(BaseModel):
    """Complete replayable migration report; plans are dry-run records by default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    migration_id: str
    source_manifest: str
    source_manifest_sha256: str
    destination_namespace: str
    mode: Literal["dry-run", "applied"] = "dry-run"
    rename_fields: dict[str, str] = Field(default_factory=dict)
    drop_fields: tuple[str, ...] = ()
    artifacts: tuple[MigratedArtifact, ...]

    @model_validator(mode="after")
    def destination_is_v2_release(self) -> "ArtifactMigrationPlan":
        path = PurePosixPath(self.destination_namespace)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("migration destination must be repository-relative")
        if path.parts[:3] != ("kb", "releases", "v2") or len(path.parts) != 4:
            raise ValueError("migration destination must be kb/releases/v2/<release-id>")
        return self

    @property
    def requires_review(self) -> bool:
        """Whether applying the plan requires explicit ambiguity/loss acceptance."""

        return any(item.ambiguities or item.losses for item in self.artifacts)


def plan_artifact_migration(
    source_manifest: Path,
    *,
    release_name: str,
    rename_fields: dict[str, str] | None = None,
    drop_fields: tuple[str, ...] = (),
    repo_root: Path = REPO_ROOT,
) -> ArtifactMigrationPlan:
    """Plan a v1-to-v2 copy without writing anything.

    Both the legacy ``entries`` inventory and v2 ``artifacts`` manifests are
    accepted.  Structured YAML/JSON fields are transformed recursively; rule and
    text artifacts are copied byte-for-byte.
    """

    _validate_release_name(release_name)
    manifest_path = _repo_file(repo_root, source_manifest)
    manifest_payload = read_yaml(manifest_path)
    if not isinstance(manifest_payload, dict):
        raise ValueError("source manifest must contain a mapping")
    raw_entries = manifest_payload.get("artifacts", manifest_payload.get("entries"))
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("source manifest must contain a non-empty artifacts or entries list")

    renames = dict(sorted((rename_fields or {}).items()))
    if set(renames) & set(drop_fields):
        raise ValueError("a field cannot be both renamed and dropped")
    destination = f"kb/releases/v2/{release_name}"
    destination_path = repo_root / destination
    if destination_path.exists():
        raise FileExistsError(f"v2 release namespace already exists: {destination}")

    results: list[MigratedArtifact] = []
    source_paths: set[str] = set()
    target_paths: set[str] = set()
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"manifest entry {index} must be a mapping")
        source_value = raw_entry.get("path", raw_entry.get("kb_path"))
        if not isinstance(source_value, str):
            raise ValueError(f"manifest entry {index} has no path/kb_path")
        source_path = _repo_file(repo_root, Path(source_value))
        source_rel = source_path.relative_to(repo_root.resolve()).as_posix()
        if source_rel in source_paths:
            raise ValueError(f"duplicate source path in migration manifest: {source_rel}")
        source_paths.add(source_rel)
        source_id = str(raw_entry.get("artifact_id") or stable_id("v1_artifact", source_rel))
        payload, field_reports, ambiguities, losses = _transform_file(
            source_path, renames=renames, drops=set(drop_fields)
        )
        target_hash = canonical_sha256(payload)
        target_id = stable_id("artifact", {"sha256": target_hash, "source_id": source_id})
        suffix = "".join(source_path.suffixes) or ".bin"
        safe_id = target_id.replace(":", "_")
        target_rel = f"{destination}/artifacts/{safe_id}{suffix}"
        if target_rel in target_paths:
            raise ValueError(f"duplicate target path planned: {target_rel}")
        target_paths.add(target_rel)
        source_hash = sha256_file(source_path)
        results.append(
            MigratedArtifact(
                source_artifact_id=source_id,
                target_artifact_id=target_id,
                source_path=source_rel,
                target_path=target_rel,
                source_sha256=source_hash,
                target_sha256=target_hash,
                hash_changed=source_hash != target_hash,
                id_changed=source_id != target_id,
                field_mappings=field_reports,
                ambiguities=ambiguities,
                losses=losses,
            )
        )

    identity_payload = {
        "source_manifest_sha256": sha256_file(manifest_path),
        "destination_namespace": destination,
        "rename_fields": renames,
        "drop_fields": sorted(drop_fields),
        "artifacts": [item.model_dump(mode="json") for item in results],
    }
    return ArtifactMigrationPlan(
        migration_id=stable_id("artifact_migration", identity_payload),
        source_manifest=manifest_path.relative_to(repo_root.resolve()).as_posix(),
        source_manifest_sha256=identity_payload["source_manifest_sha256"],
        destination_namespace=destination,
        rename_fields=renames,
        drop_fields=tuple(sorted(drop_fields)),
        artifacts=tuple(results),
    )


def apply_artifact_migration(
    plan: ArtifactMigrationPlan,
    *,
    repo_root: Path = REPO_ROOT,
    accept_ambiguities: bool = False,
    accept_losses: bool = False,
) -> ArtifactMigrationPlan:
    """Apply a reviewed plan once to a fresh v2 namespace.

    The source manifest and every source hash are rechecked immediately before
    writing.  The destination directory is assembled off to the side and renamed
    into place, so neither v1 nor a previously published v2 release is overwritten.
    """

    if plan.mode != "dry-run":
        raise ValueError("only a dry-run plan can be applied")
    if any(item.ambiguities for item in plan.artifacts) and not accept_ambiguities:
        raise ValueError("migration contains ambiguities; explicit acceptance is required")
    if any(item.losses for item in plan.artifacts) and not accept_losses:
        raise ValueError("migration contains losses; explicit acceptance is required")

    source_manifest = _repo_file(repo_root, Path(plan.source_manifest))
    if sha256_file(source_manifest) != plan.source_manifest_sha256:
        raise ValueError("source manifest changed after the dry run")
    destination = (repo_root / plan.destination_namespace).resolve()
    _require_contained(repo_root.resolve(), destination)
    if destination.exists():
        raise FileExistsError(f"immutable v2 release already exists: {plan.destination_namespace}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for item in plan.artifacts:
            source = _repo_file(repo_root, Path(item.source_path))
            if sha256_file(source) != item.source_sha256:
                raise ValueError(f"source artifact changed after dry run: {item.source_path}")
            payload, reports, ambiguities, losses = _transform_file(
                source, renames=plan.rename_fields, drops=set(plan.drop_fields)
            )
            if canonical_sha256(payload) != item.target_sha256:
                raise ValueError(f"migration output drifted after dry run: {item.source_path}")
            if (
                tuple(reports) != item.field_mappings
                or ambiguities != item.ambiguities
                or losses != item.losses
            ):
                raise ValueError(f"migration audit drifted after dry run: {item.source_path}")
            relative = Path(item.target_path).relative_to(plan.destination_namespace)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        applied = plan.model_copy(update={"mode": "applied"})
        report = temporary / "migration-report.json"
        report.write_text(
            json.dumps(applied.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.rename(temporary, destination)
        return applied
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _transform_file(
    path: Path, *, renames: dict[str, str], drops: set[str]
) -> tuple[bytes, tuple[FieldMigration, ...], tuple[str, ...], tuple[str, ...]]:
    suffix = path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        return path.read_bytes(), (), (), ()
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
    else:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    counts = {key: 0 for key in (*renames, *drops)}
    ambiguities: list[str] = []
    losses: list[str] = []

    def visit(item: Any, location: str) -> Any:
        if isinstance(item, list):
            return [visit(value, f"{location}[{index}]") for index, value in enumerate(item)]
        if not isinstance(item, dict):
            return item
        result: dict[Any, Any] = {}
        for key, value in item.items():
            field = str(key)
            current = f"{location}.{field}" if location else field
            if field in drops:
                counts[field] += 1
                losses.append(f"dropped {current}")
                continue
            target = renames.get(field, field)
            if field in renames:
                counts[field] += 1
                if target in item and target != field:
                    ambiguities.append(f"{current} maps to existing field {target!r}")
                    continue
            if target in result and target != field:
                ambiguities.append(f"{current} maps to existing field {target!r}")
                continue
            result[target] = visit(value, current)
        return result

    transformed = visit(value, "")
    reports = []
    for source, target in renames.items():
        outcome: Literal["renamed", "unchanged", "dropped", "ambiguous"]
        outcome = (
            "ambiguous" if any(f"field {target!r}" in item for item in ambiguities) else "renamed"
        )
        reports.append(
            FieldMigration(
                source_field=source,
                target_field=target,
                occurrences=counts[source],
                outcome=outcome,
            )
        )
    for source in sorted(drops):
        reports.append(
            FieldMigration(
                source_field=source,
                occurrences=counts[source],
                outcome="dropped",
                note="lossy field removal",
            )
        )
    if suffix == ".json":
        payload = (
            json.dumps(transformed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    else:
        payload = yaml.safe_dump(
            transformed, sort_keys=False, allow_unicode=True, default_flow_style=False
        ).encode("utf-8")
    return payload, tuple(reports), tuple(ambiguities), tuple(losses)


def _repo_file(repo_root: Path, value: Path) -> Path:
    root = repo_root.resolve()
    target = (value if value.is_absolute() else root / value).resolve()
    _require_contained(root, target)
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def _require_contained(root: Path, target: Path) -> None:
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository: {target}") from exc


def _validate_release_name(value: str) -> None:
    if not value or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in value):
        raise ValueError(
            "release name must contain only lowercase letters, digits, '.', '_' or '-'"
        )


__all__ = [
    "ArtifactMigrationPlan",
    "FieldMigration",
    "MigratedArtifact",
    "apply_artifact_migration",
    "plan_artifact_migration",
]
