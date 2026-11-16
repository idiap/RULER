# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Declarative, hash-bound manifests for isolated knowledge-base corpora.

The models in this module are independent of application-specific vocabularies.  They are the
filesystem trust boundary for corpus artifacts: paths stay in their declared corpus,
content hashes are current, identifiers are unique, and references cannot silently
reach into another corpus.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ruler.io import read_yaml
from ruler.paths import KB_CORPORA_DIR, REPO_ROOT

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=1, max_length=128),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ArtifactStatus = Literal["candidate", "reviewed", "approved", "active", "retired", "rejected"]


class CorpusArtifact(BaseModel):
    """One immutable file declared by a corpus manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: Identifier
    document_id: Identifier
    document_version: str = Field(min_length=1, max_length=128)
    status: ArtifactStatus
    path: str = Field(min_length=1)
    sha256: Sha256
    language: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9-]{0,34}$")
    category: Identifier
    artifact_type: Identifier
    role: str = Field(min_length=1)
    references: tuple[str, ...] = ()
    legacy_mirrors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def paths_are_portable(self) -> "CorpusArtifact":
        _validate_relative_path(self.path, "path")
        for mirror in self.legacy_mirrors:
            _validate_relative_path(mirror, "legacy mirror")
        return self


class CorpusManifest(BaseModel):
    """Versioned declaration for one domain corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    domain_id: Identifier
    corpus_id: Identifier
    description: str = Field(min_length=1)
    artifacts: tuple[CorpusArtifact, ...]

    @model_validator(mode="after")
    def identifiers_and_references_are_local(self) -> "CorpusManifest":
        ids = [item.artifact_id for item in self.artifacts]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate artifact IDs: {duplicates}")
        local_ids = set(ids)
        for artifact in self.artifacts:
            for reference in artifact.references:
                if reference.startswith("shared:"):
                    _validate_reference_id(reference.removeprefix("shared:"), reference)
                    continue
                if ":" in reference:
                    raise ValueError(
                        f"{artifact.artifact_id}: cross-corpus reference is forbidden: {reference}"
                    )
                _validate_reference_id(reference, reference)
                if reference not in local_ids:
                    raise ValueError(
                        f"{artifact.artifact_id}: unknown local artifact reference {reference}"
                    )
        return self


def load_corpus_manifest(path: Path) -> CorpusManifest:
    """Load one strict corpus manifest without trusting any paths it contains."""

    return CorpusManifest.model_validate(read_yaml(path))


def corpus_manifest_json_schema() -> dict[str, object]:
    """Return the versioned JSON Schema for tooling and domain-pack authors."""

    return CorpusManifest.model_json_schema()


def validate_corpus_manifest(
    manifest: CorpusManifest,
    *,
    repo_root: Path = REPO_ROOT,
    verify_legacy_mirrors: bool = True,
) -> list[str]:
    """Validate containment and on-disk integrity, returning an audit summary.

    Canonical artifacts must be under ``kb/corpora/<corpus-id>``.  Shared
    references are declarations, not paths; a caller can validate a shared manifest
    separately.  Legacy mirrors may live elsewhere in the repository for one
    deprecation cycle, but must be byte-identical when present.
    """

    errors: list[str] = []
    corpus_root = repo_root / "kb" / "corpora" / manifest.corpus_id
    for artifact in manifest.artifacts:
        try:
            target = _contained_path(repo_root, corpus_root, artifact.path)
        except ValueError as exc:
            errors.append(f"{artifact.artifact_id}: {exc}")
            continue
        if not target.is_file():
            errors.append(f"{artifact.artifact_id}: artifact missing: {artifact.path}")
            continue
        actual = sha256_file(target)
        if actual != artifact.sha256:
            errors.append(
                f"{artifact.artifact_id}: stale hash: declared {artifact.sha256}, actual {actual}"
            )
        if verify_legacy_mirrors:
            for mirror_path in artifact.legacy_mirrors:
                try:
                    mirror = _contained_path(repo_root, repo_root, mirror_path)
                except ValueError as exc:
                    errors.append(f"{artifact.artifact_id}: {exc}")
                    continue
                if not mirror.is_file():
                    errors.append(f"{artifact.artifact_id}: legacy mirror missing: {mirror_path}")
                elif sha256_file(mirror) != actual:
                    errors.append(
                        f"{artifact.artifact_id}: legacy mirror hash mismatch: {mirror_path}"
                    )
    if errors:
        raise ValueError("invalid corpus manifest:\n" + "\n".join(errors))
    return [
        f"domain_id={manifest.domain_id}",
        f"corpus_id={manifest.corpus_id}",
        f"artifacts={len(manifest.artifacts)}",
    ]


def validate_corpus_manifests(
    manifests: Iterable[CorpusManifest],
    *,
    repo_root: Path = REPO_ROOT,
    verify_files: bool = True,
) -> list[str]:
    """Validate a manifest set and reject IDs reused by different corpora."""

    manifest_list = list(manifests)
    corpus_ids = [item.corpus_id for item in manifest_list]
    duplicate_corpora = sorted({item for item in corpus_ids if corpus_ids.count(item) > 1})
    if duplicate_corpora:
        raise ValueError(f"duplicate corpus IDs: {duplicate_corpora}")
    owners: dict[str, str] = {}
    for manifest in manifest_list:
        for artifact in manifest.artifacts:
            owner = owners.setdefault(artifact.artifact_id, manifest.corpus_id)
            if owner != manifest.corpus_id:
                raise ValueError(
                    f"duplicate artifact ID {artifact.artifact_id!r} across corpora "
                    f"{owner!r} and {manifest.corpus_id!r}"
                )
    if verify_files:
        for manifest in manifest_list:
            validate_corpus_manifest(manifest, repo_root=repo_root)
    return [f"corpora={len(manifest_list)}", f"artifacts={len(owners)}"]


def discover_corpus_manifests(*, repo_root: Path = REPO_ROOT) -> tuple[Path, ...]:
    """Discover manifests only at the declarative corpus boundary."""

    root = repo_root / KB_CORPORA_DIR.relative_to(REPO_ROOT)
    if not root.exists():
        return ()
    return tuple(sorted(root.glob("*/manifest.yaml")))


def sha256_file(path: Path) -> str:
    """Return the canonical labelled SHA-256 of a file."""

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_relative_path(value: str, label: str) -> None:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or "\\" in value or ".." in pure.parts or "." in pure.parts:
        raise ValueError(f"{label} must be a normalized repository-relative POSIX path: {value!r}")


def _contained_path(repo_root: Path, allowed_root: Path, value: str) -> Path:
    _validate_relative_path(value, "artifact path")
    root = repo_root.resolve()
    allowed = allowed_root.resolve()
    target = (root / value).resolve()
    try:
        target.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"path escapes declared root {allowed}: {value}") from exc
    return target


def _validate_reference_id(value: str, original: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise ValueError(f"invalid artifact reference {original!r}")


__all__ = [
    "ArtifactStatus",
    "CorpusArtifact",
    "CorpusManifest",
    "corpus_manifest_json_schema",
    "discover_corpus_manifests",
    "load_corpus_manifest",
    "sha256_file",
    "validate_corpus_manifest",
    "validate_corpus_manifests",
]
