# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Project vocabulary and session-bound corpus import plans for MCP.

The public project identifier maps to the existing domain-pack contract. Persisted
schemas and immutable evidence identities retain their original field names.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from threading import Lock
from typing import Any

from ruler.domains.base import validate_domain_pack
from ruler.domains.registry import DomainPackRegistry
from ruler.kb.corpus_manifest import load_corpus_manifest, validate_corpus_manifest
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import CreateKnowledgeBaseRequest, KnowledgeBase

MAX_IMPORT_BYTES = 20_000_000
MAX_IMPORT_ARTIFACTS = 256
PLAN_TTL_SECONDS = 900
MAX_PLANS = 128


def project_fields(value: Any) -> Any:
    """Translate structured MCP keys without rewriting evidence text or identifiers."""
    if isinstance(value, dict):
        return {
            {"domain_id": "project_id", "domains": "projects", "domain_ids": "project_ids"}.get(
                key, key
            ): project_fields(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [project_fields(item) for item in value]
    return value


class ProjectMCPService:
    """Bounded operations over registered local packs, never caller-supplied paths."""

    def __init__(
        self,
        registry: Callable[[], DomainPackRegistry],
        catalog: KnowledgeBaseCatalog | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry
        self.catalog = catalog or KnowledgeBaseCatalog()
        self.clock = clock
        self._plans: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()

    def restore_plans(self, plans: dict[str, Any]) -> None:
        """Restore this session's database-backed plans inside a disposable worker."""
        self._plans = {
            key: (expiry, payload)
            for key, (expiry, payload) in plans.items()
            if expiry > self.clock()
        }

    def snapshot_plans(self) -> dict[str, Any]:
        """Export bounded plans for the surrounding PostgreSQL transaction."""
        return {
            key: [expiry, payload]
            for key, (expiry, payload) in self._plans.items()
            if expiry > self.clock()
        }

    def list_projects(self) -> dict[str, Any]:
        projects = [self.inspect(key) for key in self.registry().registered_ids()]
        return {"projects": projects, "count": len(projects), "read_only": True}

    def inspect(self, project_id: str) -> dict[str, Any]:
        try:
            pack = self.registry().get(project_id)
        except LookupError:
            raise ValueError("unknown project identifier") from None
        validate_domain_pack(pack)
        return {
            "project_id": pack.domain_id,
            "schema_version": pack.schema_version,
            "document_kinds": sorted(pack.document_kinds),
            "value_types": {
                key: value.model_dump(mode="json")
                for key, value in sorted(pack.value_types.items())
            },
            "predicates": {
                key: value.model_dump(mode="json") for key, value in sorted(pack.predicates.items())
            },
            "taxonomy": pack.taxonomy.model_dump(mode="json"),
            "translation_contracts": [
                item.model_dump(mode="json") for item in pack.translation_contracts
            ],
        }

    def validate(self, project_id: str) -> dict[str, Any]:
        self.inspect(project_id)
        return {
            "status": "pass",
            "project_id": project_id,
            "read_only": True,
            "checks": ["pack_protocol", "identifiers", "predicate_value_types"],
            "claim_boundary": "Pack declarations only; not corpus or semantic validation.",
        }

    def _snapshot(
        self, project_id: str, corpus_id: str, kb_id: str
    ) -> tuple[dict[str, Any], KnowledgeBase, dict[str, bytes]]:
        project = self.inspect(project_id)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", corpus_id):
            raise ValueError("invalid corpus identifier")
        root = self.catalog.repo_root
        corpus_root = root / "kb" / "corpora" / corpus_id
        path = corpus_root / "manifest.yaml"
        # Resolve before reading, including the manifest itself and symlinked parents.
        if not path.resolve().is_relative_to(root / "kb" / "corpora"):
            raise ValueError("corpus manifest escapes the corpus catalogue")
        if path.stat().st_size > 1_000_000:
            raise ValueError("corpus manifest exceeds size limit")
        manifest_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = load_corpus_manifest(path)
        if manifest.corpus_id != corpus_id or manifest.domain_id != project_id:
            raise ValueError("corpus does not belong to the selected project")
        if not manifest.artifacts or len(manifest.artifacts) > MAX_IMPORT_ARTIFACTS:
            raise ValueError("corpus artifact count is outside import limits")
        payloads: dict[str, bytes] = {}
        total = 0
        for artifact in manifest.artifacts:
            source_path = (root / artifact.path).resolve()
            if not source_path.is_relative_to(corpus_root):
                raise ValueError("corpus artifact escapes its namespace")
            total += source_path.stat().st_size
            if total > MAX_IMPORT_BYTES:
                raise ValueError("corpus exceeds import byte limit")
            with source_path.open("rb") as handle:
                payload = handle.read(MAX_IMPORT_BYTES + 1)
            if len(payload) != source_path.stat().st_size or len(payload) > MAX_IMPORT_BYTES:
                raise ValueError("corpus changed or exceeds import limits")
            if "sha256:" + hashlib.sha256(payload).hexdigest() != artifact.sha256:
                raise ValueError("corpus artifact digest mismatch")
            payloads[artifact.artifact_id] = payload
        try:
            validate_corpus_manifest(manifest, repo_root=root)
        except ValueError:
            raise ValueError("corpus integrity validation failed") from None
        source = self.catalog.get(corpus_id)
        if source.source_kind != "corpus_adapter":
            raise ValueError("source must be a registered corpus")
        CreateKnowledgeBaseRequest(
            kb_id=kb_id,
            name=source.name,
            description=source.description,
            domain_id=project_id,
            purposes=source.purposes,
        )
        if any(kb.kb_id == kb_id for kb in self.catalog.list()):
            raise ValueError("import target already exists")
        if (self.catalog.managed_root / kb_id).exists():
            raise ValueError("import target already exists")
        plan = {
            "project_id": project_id,
            "corpus_id": corpus_id,
            "kb_id": kb_id,
            "manifest_sha256": manifest_digest,
            "source_version_id": source.current_version_id,
            "source_content_sha256": source.current_version.content_sha256,
            "project_sha256": "sha256:"
            + hashlib.sha256(json.dumps(project, sort_keys=True).encode()).hexdigest(),
            "artifact_count": len(payloads),
            "total_bytes": total,
            "artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "sha256": item.sha256,
                    "status": item.status,
                    "references": list(item.references),
                }
                for item in source.current_version.artifacts
            ],
            "target_status": "draft",
            "publication_inherited": False,
        }
        return plan, source, payloads

    def plan_import(
        self, project_id: str, corpus_id: str, kb_id: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            plan, _, _ = self._snapshot(
                project_id,
                corpus_id,
                kb_id if kb_id is not None else re.sub(r"[._]", "-", corpus_id[:56]) + "-import",
            )
            now = self.clock()
            self._plans = {key: item for key, item in self._plans.items() if item[0] > now}
            if len(self._plans) >= MAX_PLANS:
                raise ValueError("too many pending import plans")
            plan_id = secrets.token_urlsafe(24)
            # Keep the stored plan independent of the returned mutable JSON payload.
            self._plans[plan_id] = (now + PLAN_TTL_SECONDS, json.loads(json.dumps(plan)))
            return {
                "status": "planned",
                "plan_id": plan_id,
                **plan,
                "expires_in_seconds": PLAN_TTL_SECONDS,
                "read_only": True,
                "apply_requires_allow_write": True,
            }

    def apply_import(self, plan_id: str, allow_write: bool = False) -> dict[str, Any]:
        if not allow_write:
            return {"status": "blocked", "reason": "import requires allow_write=true"}
        with self._lock:
            stored = self._plans.get(plan_id)
            if stored is None or stored[0] <= self.clock():
                self._plans.pop(plan_id, None)
                return {"status": "blocked", "reason": "unknown or expired import plan"}
            _, expected = stored
            actual, source, payloads = self._snapshot(
                expected["project_id"], expected["corpus_id"], expected["kb_id"]
            )
            if actual != expected:
                return {"status": "blocked", "reason": "import plan is stale; create a new plan"}
            kb = self.catalog.import_corpus_snapshot(source, expected["kb_id"], payloads)
            del self._plans[plan_id]
            return {
                "status": "imported",
                "project_id": kb.domain_id,
                "kb_id": kb.kb_id,
                "version_id": kb.current_version_id,
                "content_sha256": kb.current_version.content_sha256,
                "source_content_sha256": expected["source_content_sha256"],
                "lifecycle": "draft",
                "publication_inherited": False,
            }
