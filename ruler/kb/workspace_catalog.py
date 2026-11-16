# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Filesystem-backed catalog for named managed KBs and read-only corpus adapters."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from ruler.kb.corpus_manifest import discover_corpus_manifests, load_corpus_manifest
from ruler.kb.workspace_contracts import (
    AddKBArtifactRequest,
    CreateKnowledgeBaseRequest,
    KBArtifactRef,
    KBArtifactRole,
    KBFormalism,
    KBPurpose,
    KBSearchHit,
    KBVersion,
    KnowledgeBase,
    utc_now,
)
from ruler.kb.workspace_governance import (
    EvidenceKind,
    ReleaseEnvelope,
    ReleaseEvidence,
    ReleaseLifecycle,
    ReleaseRepository,
    ReleaseStage,
)
from ruler.paths import KB_DIR, REPO_ROOT

KB_WORKSPACES_DIR = KB_DIR / "workspaces"


class KnowledgeBaseCatalog:
    """One safe catalog spanning adapted corpora and locally managed KBs."""

    def __init__(self, *, repo_root: Path = REPO_ROOT, managed_root: Path | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.managed_root = (managed_root or (self.repo_root / "kb" / "workspaces")).resolve()
        _require_within(self.managed_root, self.repo_root)
        self.release_repository = ReleaseRepository(self.managed_root / ".releases")

    def list(self) -> tuple[KnowledgeBase, ...]:
        items = {item.kb_id: item for item in self._adapted_corpora()}
        for item in self._managed():
            if item.kb_id in items:
                raise ValueError(f"managed KB shadows adapted corpus: {item.kb_id}")
            items[item.kb_id] = item
        return tuple(sorted(items.values(), key=lambda item: (item.name.casefold(), item.kb_id)))

    def get(self, kb_id: str) -> KnowledgeBase:
        try:
            return next(item for item in self.list() if item.kb_id == kb_id)
        except StopIteration as exc:
            raise LookupError(f"unknown knowledge base {kb_id!r}") from exc

    def create(self, request: CreateKnowledgeBaseRequest) -> KnowledgeBase:
        if any(item.kb_id == request.kb_id for item in self.list()):
            raise ValueError(f"knowledge base already exists: {request.kb_id}")
        created = utc_now()
        version = _make_version(
            kb_id=request.kb_id,
            revision=1,
            artifacts=(),
            created_at=created,
            change_summary="Initial empty knowledge base.",
        )
        kb = KnowledgeBase(
            kb_id=request.kb_id,
            name=request.name,
            description=request.description,
            domain_id=request.domain_id,
            purposes=request.purposes,
            tags=request.tags,
            access_mode="local_owner",
            lifecycle="draft",
            current_version_id=version.version_id,
            versions=(version,),
            source_kind="managed",
        )
        self._write(kb)
        self.release_repository.put(ReleaseLifecycle.draft(kb))
        return kb

    def import_corpus_snapshot(
        self, source: KnowledgeBase, kb_id: str, payloads: Mapping[str, bytes]
    ) -> KnowledgeBase:
        """Copy an authenticated corpus into a new draft; never inherit publication.

        The catalog entry is written last, so incomplete imports are not discoverable.
        Release evidence is created by the normal explicit transition operation.
        """
        request = CreateKnowledgeBaseRequest(
            kb_id=kb_id,
            name=source.name,
            description=source.description,
            domain_id=source.domain_id,
            purposes=source.purposes,
        )
        if source.source_kind != "corpus_adapter":
            raise ValueError("only corpus snapshots can be imported")
        if any(item.kb_id == kb_id for item in self.list()):
            raise ValueError("import target already exists")
        if set(payloads) != {item.artifact_id for item in source.current_version.artifacts}:
            raise ValueError("import payloads must exactly cover the source snapshot")
        target = self.managed_root / request.kb_id
        _require_within(target.resolve(), self.managed_root)
        artifacts = []
        for item in source.current_version.artifacts:
            content = payloads[item.artifact_id]
            if "sha256:" + hashlib.sha256(content).hexdigest() != item.sha256:
                raise ValueError(f"import digest mismatch: {item.artifact_id}")
            destination = target / "artifacts" / item.artifact_id / Path(item.path).name
            artifacts.append(
                item.model_copy(
                    update={
                        "path": destination.relative_to(self.repo_root).as_posix(),
                        "size_bytes": len(content),
                    }
                )
            )
        version = _make_version(
            kb_id=kb_id,
            revision=1,
            artifacts=tuple(artifacts),
            created_at=utc_now(),
            change_summary=f"Imported corpus snapshot {source.current_version.content_sha256}.",
        )
        kb = KnowledgeBase(
            kb_id=kb_id,
            name=request.name,
            description=request.description,
            domain_id=source.domain_id,
            purposes=source.purposes,
            tags=frozenset(
                {
                    f"source-corpus:{source.kb_id}",
                    f"source-version:{source.current_version.content_sha256}",
                }
            ),
            access_mode="local_owner",
            lifecycle="draft",
            source_kind="managed",
            current_version_id=version.version_id,
            versions=(version,),
        )
        self.managed_root.mkdir(parents=True, exist_ok=True)
        # Exclusive reservation prevents overwrites, including concurrent imports.
        target.mkdir()
        try:
            for artifact in kb.current_version.artifacts:
                destination = self.repo_root / artifact.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                _atomic_create(destination, payloads[artifact.artifact_id])
            self._write(kb)
        except Exception:
            shutil.rmtree(target)
            raise
        return kb

    def update_metadata(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        lifecycle: str | None = None,
        tags: frozenset[str] | None = None,
    ) -> KnowledgeBase:
        kb = self.get(kb_id)
        self._require_managed(kb)
        updated = kb.model_copy(
            update={
                "name": name if name is not None else kb.name,
                "description": description if description is not None else kb.description,
                "lifecycle": lifecycle if lifecycle is not None else kb.lifecycle,
                "tags": tags if tags is not None else kb.tags,
            }
        )
        updated = KnowledgeBase.model_validate(updated.model_dump(mode="json"))
        self._write(updated)
        return updated

    def releases(self, kb_id: str) -> tuple[ReleaseEnvelope, ...]:
        """Return immutable release envelopes, adapting published corpus versions."""
        kb = self.get(kb_id)
        stored = self.release_repository.list(kb_id)
        if stored:
            return stored
        if kb.source_kind == "managed":
            return ()
        version = kb.current_version
        evidence = tuple(
            ReleaseEvidence(
                evidence_id=f"adapter-{kind.value}",
                kind=kind,
                subject_sha256=version.content_sha256,
                actor_id="corpus-manifest-adapter",
                successful=True,
                recorded_at=version.created_at,
                details="Inherited from the validated, hash-bound read-only corpus manifest.",
            )
            for kind in (
                EvidenceKind.VALIDATION,
                EvidenceKind.REVIEW,
                EvidenceKind.PUBLICATION_APPROVAL,
            )
        )
        return (
            ReleaseEnvelope(
                release_id=f"{version.version_id}.published",
                kb_id=kb.kb_id,
                version_id=version.version_id,
                content_sha256=version.content_sha256,
                stage=ReleaseStage.PUBLISHED,
                evidence=evidence,
                created_at=version.created_at,
            ),
        )

    def transition_release(
        self,
        kb_id: str,
        target: ReleaseStage,
        evidence: Sequence[ReleaseEvidence],
    ) -> ReleaseEnvelope:
        kb = self.get(kb_id)
        self._require_managed(kb)
        candidates = [
            item for item in self.releases(kb_id) if item.version_id == kb.current_version_id
        ]
        if not candidates:
            current = ReleaseLifecycle.draft(kb)
            self.release_repository.put(current)
        else:
            current = candidates[-1]
        transitioned = ReleaseLifecycle.transition(current, target, evidence=evidence)
        self.release_repository.put(transitioned)
        return transitioned

    def execution_release(self, kb_id: str, *, allow_preview: bool = False) -> ReleaseEnvelope:
        return ReleaseLifecycle.execution_release(self.releases(kb_id), allow_preview=allow_preview)

    def add_artifact(self, kb_id: str, request: AddKBArtifactRequest) -> KnowledgeBase:
        kb = self.get(kb_id)
        self._require_managed(kb)
        current = kb.current_version
        if request.artifact_id in {item.artifact_id for item in current.artifacts}:
            raise ValueError(f"artifact already exists in current version: {request.artifact_id}")
        if unknown := set(request.references) - {item.artifact_id for item in current.artifacts}:
            raise ValueError(f"unknown artifact references: {sorted(unknown)}")
        encoded = request.content.encode("utf-8")
        artifact_path = (
            self.managed_root / kb_id / "artifacts" / request.artifact_id / request.filename
        )
        _require_within(artifact_path.resolve(), (self.managed_root / kb_id).resolve())
        if artifact_path.exists():
            raise ValueError(f"immutable artifact path already exists: {request.artifact_id}")
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_create(artifact_path, encoded)
        relative = artifact_path.relative_to(self.repo_root).as_posix()
        artifact = KBArtifactRef(
            artifact_id=request.artifact_id,
            name=request.name,
            role=request.role,
            formalism=request.formalism,
            media_type=request.media_type,
            path=relative,
            sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
            language=request.language,
            references=request.references,
            size_bytes=len(encoded),
        )
        revision = len(kb.versions) + 1
        version = _make_version(
            kb_id=kb_id,
            revision=revision,
            artifacts=(*current.artifacts, artifact),
            created_at=utc_now(),
            change_summary=request.change_summary,
            parent_version_id=current.version_id,
        )
        updated = kb.model_copy(
            update={
                "current_version_id": version.version_id,
                "versions": (*kb.versions, version),
                "lifecycle": "active",
            }
        )
        updated = KnowledgeBase.model_validate(updated.model_dump(mode="json"))
        self._write(updated)
        self.release_repository.put(ReleaseLifecycle.draft(updated))
        return updated

    def search(
        self,
        query: str,
        *,
        kb_id: str | None = None,
        limit: int = 50,
    ) -> tuple[KBSearchHit, ...]:
        terms = tuple(item for item in query.casefold().split() if item)
        if not terms:
            raise ValueError("search query must not be blank")
        if limit < 1 or limit > 200:
            raise ValueError("search limit must be between 1 and 200")
        kbs = (self.get(kb_id),) if kb_id else self.list()
        hits: list[KBSearchHit] = []
        for kb in kbs:
            metadata = f"{kb.kb_id} {kb.name} {kb.description} {kb.domain_id} {' '.join(kb.tags)}"
            score = _score(metadata, terms)
            if score:
                hits.append(
                    KBSearchHit(
                        kb_id=kb.kb_id,
                        kb_name=kb.name,
                        artifact_id=None,
                        artifact_name=None,
                        role=None,
                        formalism=None,
                        score=score,
                        snippet=_snippet(metadata, terms),
                        version_id=kb.current_version_id,
                    )
                )
            for artifact in kb.current_version.artifacts:
                content = self._artifact_text(artifact)
                searchable = f"{artifact.artifact_id} {artifact.name} {artifact.role} {artifact.formalism} {content}"
                score = _score(searchable, terms)
                if score:
                    hits.append(
                        KBSearchHit(
                            kb_id=kb.kb_id,
                            kb_name=kb.name,
                            artifact_id=artifact.artifact_id,
                            artifact_name=artifact.name,
                            role=artifact.role,
                            formalism=artifact.formalism,
                            score=score,
                            snippet=_snippet(searchable, terms),
                            version_id=kb.current_version_id,
                        )
                    )
        return tuple(
            sorted(hits, key=lambda item: (-item.score, item.kb_name, item.artifact_id or ""))[
                :limit
            ]
        )

    def artifact_path(self, artifact: KBArtifactRef) -> Path:
        path = (self.repo_root / artifact.path).resolve()
        _require_within(path, self.repo_root)
        if not path.is_file():
            raise ValueError(f"artifact is missing: {artifact.artifact_id}")
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != artifact.sha256:
            raise ValueError(f"artifact digest mismatch: {artifact.artifact_id}")
        return path

    def _artifact_text(self, artifact: KBArtifactRef) -> str:
        if artifact.size_bytes > 1_000_000:
            return ""
        try:
            return self.artifact_path(artifact).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ""

    def _managed(self) -> tuple[KnowledgeBase, ...]:
        if not self.managed_root.exists():
            return ()
        items = []
        for path in sorted(self.managed_root.glob("*/kb.yaml")):
            _require_within(path.resolve(), self.managed_root)
            items.append(
                KnowledgeBase.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            )
        return tuple(items)

    def _adapted_corpora(self) -> tuple[KnowledgeBase, ...]:
        items = []
        for path in discover_corpus_manifests(repo_root=self.repo_root):
            manifest = load_corpus_manifest(path)
            artifacts = tuple(
                KBArtifactRef.model_validate(
                    dict(
                        artifact_id=item.artifact_id,
                        name=item.document_id,
                        role=_role(item.category, item.artifact_type),
                        formalism=_formalism(item.path, item.artifact_type),
                        media_type=_media_type(item.path),
                        path=item.path,
                        sha256=item.sha256,
                        language=item.language,
                        status=_status(item.status),
                        references=item.references,
                        size_bytes=(self.repo_root / item.path).stat().st_size,
                    )
                )
                for item in manifest.artifacts
            )
            created = datetime(1970, 1, 1, tzinfo=UTC)
            version = _make_version(
                kb_id=manifest.corpus_id,
                revision=1,
                artifacts=artifacts,
                created_at=created,
                change_summary="Read-only adapter over the hash-bound corpus manifest.",
                status=(
                    "published"
                    if all(item.status in {"active", "approved"} for item in manifest.artifacts)
                    else "candidate"
                ),
            )
            items.append(
                KnowledgeBase(
                    kb_id=manifest.corpus_id,
                    name=manifest.corpus_id.replace("-", " ").title(),
                    description=manifest.description,
                    domain_id=manifest.domain_id,
                    purposes=_purposes(manifest.domain_id, artifacts),
                    tags=frozenset({"corpus", manifest.domain_id}),
                    access_mode="read_only",
                    lifecycle="active",
                    current_version_id=version.version_id,
                    versions=(version,),
                    source_kind="corpus_adapter",
                )
            )
        return tuple(items)

    def _require_managed(self, kb: KnowledgeBase) -> None:
        if kb.source_kind != "managed" or kb.access_mode != "local_owner":
            raise PermissionError(f"knowledge base is read-only: {kb.kb_id}")

    def _write(self, kb: KnowledgeBase) -> None:
        target = self.managed_root / kb.kb_id / "kb.yaml"
        _require_within(target.resolve(), self.managed_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(
            kb.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ).encode()
        _atomic_replace(target, payload)


def _make_version(
    *,
    kb_id: str,
    revision: int,
    artifacts: tuple[KBArtifactRef, ...],
    created_at: datetime,
    change_summary: str,
    parent_version_id: str | None = None,
    status: str = "draft",
) -> KBVersion:
    version_id = f"{kb_id}-v{revision:04d}"
    content = {
        "version_id": version_id,
        "revision": revision,
        "parent_version_id": parent_version_id,
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
    }
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return KBVersion.model_validate(
        dict(
            version_id=version_id,
            revision=revision,
            status=status,
            parent_version_id=parent_version_id,
            artifacts=artifacts,
            created_at=created_at,
            content_sha256=digest,
            change_summary=change_summary,
        )
    )


def _formalism(path: str, artifact_type: str) -> KBFormalism:
    suffix = Path(path).suffix.lower()
    if suffix == ".lp" or "asp" in artifact_type:
        return KBFormalism.ASP
    if suffix == ".pl" or "prolog" in artifact_type:
        return KBFormalism.PROLOG
    if suffix in {".lean"}:
        return KBFormalism.LEAN4
    if suffix in {".p", ".tptp"}:
        return KBFormalism.TPTP
    if "legal_reasoning" in artifact_type or "interpretation" in artifact_type:
        return KBFormalism.LEGAL_ARGUMENT
    if "source" in artifact_type or "document" in artifact_type or "provision" in artifact_type:
        return KBFormalism.SOURCE_DOCUMENT
    return KBFormalism.STRUCTURED_DATA


def _role(category: str, artifact_type: str) -> KBArtifactRole:
    text = f"{category} {artifact_type}".lower()
    for needle, role in (
        ("source", KBArtifactRole.SOURCE),
        ("evidence", KBArtifactRole.EVIDENCE),
        ("rule", KBArtifactRole.RULES),
        ("axiom", KBArtifactRole.AXIOMS),
        ("constraint", KBArtifactRole.CONSTRAINTS),
        ("interpret", KBArtifactRole.INTERPRETATION),
        ("fact", KBArtifactRole.FACTS),
    ):
        if needle in text:
            return role
    return KBArtifactRole.MODEL


def _purposes(domain_id: str, artifacts: tuple[KBArtifactRef, ...]) -> frozenset[KBPurpose]:
    values = {KBPurpose.EXPLORATION, KBPurpose.INFERENCE}
    if domain_id in {"regulatory", "legal"}:
        values.add(KBPurpose.COMPLIANCE)
        values.add(KBPurpose.VERIFICATION)
    if domain_id == "legal":
        values.add(KBPurpose.INTERPRETATION)
    if any(item.formalism == KBFormalism.OPTIMIZATION_MODEL for item in artifacts):
        values.add(KBPurpose.OPTIMIZATION)
    return frozenset(values)


def _status(value: str) -> str:
    return (
        value
        if value in {"candidate", "reviewed", "approved", "active", "retired"}
        else "candidate"
    )


def _media_type(path: str) -> str:
    return {
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".json": "application/json",
        ".lp": "text/x-asp",
        ".pl": "text/x-prolog",
        ".txt": "text/plain",
        ".lean": "text/x-lean",
        ".p": "text/x-tptp",
    }.get(Path(path).suffix.lower(), "application/octet-stream")


def _score(text: str, terms: tuple[str, ...]) -> int:
    lowered = text.casefold()
    if not all(term in lowered for term in terms):
        return 0
    return sum(lowered.count(term) for term in terms)


def _snippet(text: str, terms: tuple[str, ...]) -> str:
    compact = " ".join(text.split())
    lowered = compact.casefold()
    index = min((lowered.find(term) for term in terms if term in lowered), default=0)
    start = max(0, index - 100)
    end = min(len(compact), start + 420)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end] + suffix


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes knowledge-base root: {path}") from exc


def _atomic_create(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_replace(path: Path, payload: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)
