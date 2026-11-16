# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Digest-preserving legacy adapters and safe KB package import/export."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ruler.contracts.common import StrictContract, validate_sha256
from ruler.kb.workspace_contracts import (
    KBArtifactRef,
    KBFormalism,
    KBPurpose,
    KBVersion,
    KnowledgeBase,
)
from ruler.kb.workspace_governance import KBDependency, ReleaseEnvelope

PACKAGE_SCHEMA = "ruler.kb-package/v1"
MAX_PACKAGE_BYTES = 100_000_000
MAX_PACKAGE_MEMBERS = 10_000


class PackageObject(StrictContract):
    artifact: KBArtifactRef
    object_path: str

    @model_validator(mode="after")
    def safe_content_address(self) -> "PackageObject":
        digest = validate_sha256(self.artifact.sha256).removeprefix("sha256:")
        expected = f"objects/sha256/{digest}"
        if self.object_path != expected:
            raise ValueError("object path must be derived from the artifact digest")
        return self


class PackageAttestationRef(StrictContract):
    kind: Literal["signature", "attestation"]
    uri: str = Field(min_length=1, max_length=1000)
    sha256: str | None = None

    @field_validator("sha256")
    @classmethod
    def optional_digest(cls, value: str | None) -> str | None:
        return validate_sha256(value) if value is not None else None


class KBPackageManifest(StrictContract):
    schema_id: Literal["ruler.kb-package/v1"] = PACKAGE_SCHEMA
    kb: KnowledgeBase
    release: ReleaseEnvelope | None = None
    objects: tuple[PackageObject, ...]
    dependencies: tuple[KBDependency, ...] = ()
    schema_refs: tuple[str, ...] = ()
    attestations: tuple[PackageAttestationRef, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def package_is_consistent(self) -> "KBPackageManifest":
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.release and (
            self.release.kb_id != self.kb.kb_id
            or self.release.version_id not in {item.version_id for item in self.kb.versions}
        ):
            raise ValueError("release does not identify a packaged KB version")
        packaged = {item.artifact.artifact_id: item.artifact.sha256 for item in self.objects}
        current = {item.artifact_id: item.sha256 for item in self.kb.current_version.artifacts}
        if packaged != current:
            raise ValueError("package objects must exactly cover current-version artifacts")
        if len({item.object_path for item in self.objects}) != len(self.objects):
            # Same bytes can legitimately serve multiple artifacts.  The manifest remains
            # unambiguous, so duplicate object paths are allowed only for the same digest.
            paths: dict[str, str] = {}
            for item in self.objects:
                previous = paths.setdefault(item.object_path, item.artifact.sha256)
                if previous != item.artifact.sha256:
                    raise ValueError("one package object path has conflicting digests")
        return self


class ImportIssue(StrictContract):
    code: str
    message: str
    blocking: bool = True


class ImportPlan(StrictContract):
    kb_id: str | None
    safe_to_import: bool
    issues: tuple[ImportIssue, ...] = ()
    object_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    representational_losses: tuple[str, ...] = ()
    schema_migrations: tuple[str, ...] = ()


def export_package(
    kb: KnowledgeBase,
    destination: Path,
    *,
    read_artifact: Callable[[KBArtifactRef], bytes],
    release: ReleaseEnvelope | None = None,
    dependencies: Sequence[KBDependency] = (),
    schema_refs: Sequence[str] = (),
    attestations: Sequence[PackageAttestationRef] = (),
) -> KBPackageManifest:
    """Write a deterministic package without changing any source artifact."""

    objects: list[PackageObject] = []
    payloads: dict[str, bytes] = {}
    for artifact in kb.current_version.artifacts:
        payload = read_artifact(artifact)
        actual = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual != artifact.sha256:
            raise ValueError(f"artifact digest mismatch during export: {artifact.artifact_id}")
        object_path = f"objects/sha256/{actual.removeprefix('sha256:')}"
        objects.append(PackageObject(artifact=artifact, object_path=object_path))
        payloads[object_path] = payload
    manifest = KBPackageManifest(
        kb=kb,
        release=release,
        objects=tuple(objects),
        dependencies=tuple(dependencies),
        schema_refs=tuple(schema_refs),
        attestations=tuple(attestations),
        created_at=datetime.now(UTC),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"package already exists: {destination}")
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
        )
        for name, payload in sorted(payloads.items()):
            archive.writestr(name, payload)
    return manifest


def inspect_package(
    package: Path,
    *,
    existing_kb_ids: Sequence[str] = (),
    available_releases: Mapping[str, str] | None = None,
    supported_schema: str = PACKAGE_SCHEMA,
) -> tuple[KBPackageManifest | None, ImportPlan]:
    """Dry-run a package, including traversal, digest, collision, and dependency checks."""

    issues: list[ImportIssue] = []
    losses: list[str] = []
    migrations: list[str] = []
    total = 0
    manifest: KBPackageManifest | None = None
    try:
        if package.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError("compressed package exceeds size limit")
        with zipfile.ZipFile(package) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_PACKAGE_MEMBERS:
                raise ValueError("package has too many members")
            names: set[str] = set()
            for info in infos:
                _safe_member(info.filename)
                if info.filename in names:
                    raise ValueError(f"duplicate archive member: {info.filename}")
                names.add(info.filename)
                total += info.file_size
                if total > MAX_PACKAGE_BYTES:
                    raise ValueError("expanded package exceeds size limit")
            if "manifest.json" not in names:
                raise ValueError("package lacks manifest.json")
            raw = archive.read("manifest.json")
            manifest_data = json.loads(raw)
            incoming_schema = manifest_data.get("schema_id")
            if incoming_schema != supported_schema:
                migrations.append(f"{incoming_schema or 'unknown'} -> {supported_schema}")
                raise ValueError(f"unsupported package schema: {incoming_schema!r}")
            manifest = KBPackageManifest.model_validate(manifest_data)
            if manifest.kb.kb_id in set(existing_kb_ids):
                issues.append(
                    ImportIssue(code="kb_collision", message="knowledge-base ID already exists")
                )
            expected = {item.object_path for item in manifest.objects} | {"manifest.json"}
            unexpected = names - expected
            if unexpected:
                issues.append(
                    ImportIssue(
                        code="unexpected_members",
                        message=f"unexpected package members: {sorted(unexpected)}",
                    )
                )
            for item in manifest.objects:
                if item.object_path not in names:
                    issues.append(
                        ImportIssue(
                            code="missing_object",
                            message=f"missing object for {item.artifact.artifact_id}",
                        )
                    )
                    continue
                payload = archive.read(item.object_path)
                actual = "sha256:" + hashlib.sha256(payload).hexdigest()
                if actual != item.artifact.sha256:
                    issues.append(
                        ImportIssue(
                            code="digest_mismatch",
                            message=f"digest mismatch for {item.artifact.artifact_id}",
                        )
                    )
            available = available_releases or {}
            for dependency in manifest.dependencies:
                if available.get(dependency.source_release_id) != dependency.source_release_sha256:
                    issues.append(
                        ImportIssue(
                            code="missing_dependency",
                            message=f"dependency is unavailable: {dependency.dependency_id}",
                        )
                    )
            known_formalisms = {item.value for item in KBFormalism}
            for item in manifest.objects:
                if item.artifact.formalism.value not in known_formalisms:
                    losses.append(f"unsupported formalism: {item.artifact.formalism}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        issues.append(ImportIssue(code="invalid_package", message=str(exc)))
    return manifest, ImportPlan(
        kb_id=manifest.kb.kb_id if manifest else None,
        safe_to_import=not any(item.blocking for item in issues),
        issues=tuple(issues),
        object_count=len(manifest.objects) if manifest else 0,
        total_bytes=total,
        representational_losses=tuple(losses),
        schema_migrations=tuple(migrations),
    )


def import_package(
    package: Path,
    destination_root: Path,
    *,
    existing_kb_ids: Sequence[str] = (),
    available_releases: Mapping[str, str] | None = None,
) -> tuple[KBPackageManifest, ImportPlan]:
    """Import validated objects beneath a new KB directory; never overwrite."""

    manifest, plan = inspect_package(
        package,
        existing_kb_ids=existing_kb_ids,
        available_releases=available_releases,
    )
    if manifest is None or not plan.safe_to_import:
        raise ValueError("package import blocked by dry-run report")
    destination_root.mkdir(parents=True, exist_ok=True)
    root = destination_root.resolve()
    target = (root / manifest.kb.kb_id).resolve()
    _within(target, root)
    if target.exists():
        raise FileExistsError(f"import target already exists: {manifest.kb.kb_id}")
    staging = Path(tempfile.mkdtemp(prefix=f".{manifest.kb.kb_id}.import-", dir=root)).resolve()
    _within(staging, root)
    try:
        with zipfile.ZipFile(package) as archive:
            for item in manifest.objects:
                payload = archive.read(item.object_path)
                output = (staging / item.object_path).resolve()
                _within(output, staging)
                output.parent.mkdir(parents=True, exist_ok=True)
                _exclusive_write(output, payload)
            _exclusive_write(
                staging / "manifest.json",
                json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True).encode()
                + b"\n",
            )
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest, plan


class LegacyReleaseBundle(StrictContract):
    """Lossless input to the one-way read-only legacy adapter."""

    kb_id: str
    name: str
    description: str
    domain_id: str
    purposes: frozenset[KBPurpose]
    version: KBVersion
    original_release_sha256: str

    @field_validator("original_release_sha256")
    @classmethod
    def release_digest(cls, value: str) -> str:
        return validate_sha256(value)


def adapt_legacy_release(bundle: LegacyReleaseBundle) -> KnowledgeBase:
    """Expose a legacy formal release without rewriting artifacts or digests."""

    return KnowledgeBase(
        kb_id=bundle.kb_id,
        name=bundle.name,
        description=bundle.description,
        domain_id=bundle.domain_id,
        purposes=bundle.purposes,
        tags=frozenset({"legacy", f"original-release:{bundle.original_release_sha256}"}),
        access_mode="read_only",
        lifecycle="active",
        current_version_id=bundle.version.version_id,
        versions=(bundle.version,),
        source_kind="release_adapter",
    )


def _safe_member(name: str) -> None:
    path = PurePosixPath(name)
    if not name or name.startswith(("/", "\\")) or "\\" in name or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"unsafe archive member: {name!r}")


def _within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("package path escapes import root") from exc


def _exclusive_write(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
