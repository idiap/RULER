# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Release-pinned search, comparison, query, run, and graph experience services.

These services deliberately sit above :mod:`workspace_catalog`: they never mutate a
knowledge base and every derived object identifies the immutable version and content
digests from which it was produced.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable

from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import (
    KBArtifactRef,
    KBFormalism,
    KBInferenceRequest,
    KBInferenceResult,
    KBVersion,
    KnowledgeBase,
)
from ruler.kb.workspace_inference import KBInferenceService

_TOKEN = re.compile(r"[\w:-]+", re.UNICODE)
_PREDICATE = re.compile(r"(?<![#\w])(-?[a-z][a-z0-9_]*)\s*(?:\(([^()]*)\))?")
_REDACTED = "[redacted]"


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ReleaseSearchIndex:
    """Deterministic in-memory index over exactly one immutable KB version."""

    def __init__(
        self, catalog: KnowledgeBaseCatalog, kb: KnowledgeBase, version: KBVersion
    ) -> None:
        self.catalog = catalog
        self.kb = kb
        self.version = version
        self.documents = tuple(self._documents())
        self.index_digest = canonical_digest(
            {
                "kb": kb.kb_id,
                "version": version.version_id,
                "content": version.content_sha256,
                "documents": self.documents,
            }
        )

    @classmethod
    def build(
        cls, catalog: KnowledgeBaseCatalog, kb_id: str, version_id: str | None = None
    ) -> "ReleaseSearchIndex":
        kb = catalog.get(kb_id)
        selected = version_id or kb.current_version_id
        try:
            version = next(item for item in kb.versions if item.version_id == selected)
        except StopIteration as exc:
            raise LookupError(f"unknown version {selected!r} in {kb_id!r}") from exc
        return cls(catalog, kb, version)

    def _documents(self) -> Iterable[dict[str, Any]]:
        yield {
            "artifact_id": None,
            "name": self.kb.name,
            "role": None,
            "formalism": None,
            "language": "und",
            "status": self.version.status,
            "metadata": " ".join(
                (
                    self.kb.kb_id,
                    self.kb.name,
                    self.kb.description,
                    self.kb.domain_id,
                    *sorted(self.kb.tags),
                )
            ),
            "content": "",
        }
        for artifact in sorted(self.version.artifacts, key=lambda item: item.artifact_id):
            content = ""
            if artifact.size_bytes <= 1_000_000:
                try:
                    content = self.catalog.artifact_path(artifact).read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    pass
            yield {
                "artifact_id": artifact.artifact_id,
                "name": artifact.name,
                "role": artifact.role.value,
                "formalism": artifact.formalism.value,
                "language": artifact.language,
                "status": artifact.status,
                "metadata": f"{artifact.artifact_id} {artifact.name} {artifact.role.value} {artifact.formalism.value}",
                "content": content,
            }

    def search(
        self,
        query: str,
        *,
        languages: set[str] | None = None,
        formalisms: set[str] | None = None,
        statuses: set[str] | None = None,
        visible_fields: frozenset[str] = frozenset({"metadata", "content"}),
        limit: int = 50,
    ) -> dict[str, Any]:
        terms = tuple(token.casefold() for token in _TOKEN.findall(query))
        if not terms:
            raise ValueError("search query must contain a searchable term")
        if not 1 <= limit <= 200:
            raise ValueError("search limit must be between 1 and 200")
        unknown = set(visible_fields) - {"metadata", "content"}
        if unknown:
            raise ValueError(f"unknown visible fields: {sorted(unknown)}")
        hits = []
        for doc in self.documents:
            if languages and doc["language"] not in languages:
                continue
            if formalisms and doc["formalism"] not in formalisms:
                continue
            if statuses and doc["status"] not in statuses:
                continue
            searchable = " ".join(str(doc[field]) for field in sorted(visible_fields)).casefold()
            score = sum(searchable.count(term) for term in terms)
            if not score:
                continue
            snippet = _snippet(searchable, terms) if "content" in visible_fields else _REDACTED
            hits.append(
                {
                    "kb_id": self.kb.kb_id,
                    "version_id": self.version.version_id,
                    "artifact_id": doc["artifact_id"],
                    "name": doc["name"],
                    "role": doc["role"],
                    "formalism": doc["formalism"],
                    "language": doc["language"],
                    "status": doc["status"],
                    "score": score,
                    "snippet": snippet,
                    "redacted_fields": sorted({"metadata", "content"} - set(visible_fields)),
                }
            )
        hits.sort(key=lambda row: (-row["score"], row["artifact_id"] or ""))
        return {
            "query": query,
            "kb_id": self.kb.kb_id,
            "version_id": self.version.version_id,
            "release_digest": self.version.content_sha256,
            "index_digest": self.index_digest,
            "hits": hits[:limit],
        }


def compare_releases(
    catalog: KnowledgeBaseCatalog,
    left_kb_id: str,
    right_kb_id: str,
    *,
    left_version_id: str | None = None,
    right_version_id: str | None = None,
) -> dict[str, Any]:
    left = ReleaseSearchIndex.build(catalog, left_kb_id, left_version_id)
    right = ReleaseSearchIndex.build(catalog, right_kb_id, right_version_id)
    left_artifacts = {item.artifact_id: item for item in left.version.artifacts}
    right_artifacts = {item.artifact_id: item for item in right.version.artifacts}
    common = sorted(left_artifacts.keys() & right_artifacts.keys())
    changed = [
        key
        for key in common
        if _semantic_artifact(left_artifacts[key]) != _semantic_artifact(right_artifacts[key])
    ]
    left_predicates = _release_predicates(left)
    right_predicates = _release_predicates(right)
    report = {
        "left": _release_ref(left),
        "right": _release_ref(right),
        "artifacts": {
            "added": sorted(right_artifacts.keys() - left_artifacts.keys()),
            "removed": sorted(left_artifacts.keys() - right_artifacts.keys()),
            "changed": changed,
        },
        "predicates": {
            "added": sorted(right_predicates - left_predicates),
            "removed": sorted(left_predicates - right_predicates),
        },
        "source_coverage": {
            "left": _source_coverage(left.version),
            "right": _source_coverage(right.version),
        },
        "projection_losses": {"left": _projection_losses(left), "right": _projection_losses(right)},
        "query_outcomes": {"status": "not_compared", "reason": "no replay set supplied"},
    }
    report["semantic_change"] = any(
        (report["artifacts"][key] for key in ("added", "removed", "changed"))
    ) or bool(report["predicates"]["added"] or report["predicates"]["removed"])
    report["comparison_digest"] = canonical_digest(report)
    return report


def query_editor_model(
    catalog: KnowledgeBaseCatalog, kb_id: str, version_id: str | None = None
) -> dict[str, Any]:
    index = ReleaseSearchIndex.build(catalog, kb_id, version_id)
    signatures: dict[tuple[str, int], dict[str, Any]] = {}
    for artifact in index.version.artifacts:
        if artifact.formalism not in {KBFormalism.ASP, KBFormalism.PROLOG}:
            continue
        try:
            content = catalog.artifact_path(artifact).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, args in _PREDICATE.findall(_strip_comments(content, artifact.formalism)):
            arity = 0 if not args.strip() else len(args.split(","))
            key = (name.removeprefix("-"), arity)
            signatures.setdefault(
                key,
                {
                    "predicate": key[0],
                    "arity": arity,
                    "argument_types": ["term"] * arity,
                    "artifacts": set(),
                },
            )["artifacts"].add(artifact.artifact_id)
    rows = []
    for row in signatures.values():
        row["artifacts"] = sorted(row["artifacts"])
        row["template"] = row["predicate"] + (
            "(" + ", ".join(f"<{i + 1}:term>" for i in range(row["arity"])) + ")"
            if row["arity"]
            else ""
        )
        rows.append(row)
    rows.sort(key=lambda row: (row["predicate"], row["arity"]))
    return {
        "kb_id": kb_id,
        "version_id": index.version.version_id,
        "release_digest": index.version.content_sha256,
        "raw_solver_syntax_required": False,
        "signatures": rows,
    }


class InferenceRunStore:
    """Content-addressed durable results; replay never silently overwrites evidence."""

    def __init__(
        self, root: Path, catalog: KnowledgeBaseCatalog, service: KBInferenceService | None = None
    ) -> None:
        self.root = root.resolve()
        self.catalog = catalog
        self.service = service or KBInferenceService(catalog)

    def execute(self, kb_id: str, request: KBInferenceRequest) -> dict[str, Any]:
        kb = self.catalog.get(kb_id)
        release = self.catalog.execution_release(
            kb_id, allow_preview=request.parameters.get("allow_preview") is True
        )
        selected = kb.model_copy(update={"current_version_id": release.version_id})
        identity = self._identity(selected, request)
        run_id = canonical_digest(identity).removeprefix("sha256:")
        path = self.root / run_id[:2] / f"{run_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        result = self.service.execute(kb_id, request)
        payload = {
            "run_id": run_id,
            "identity": identity,
            "result": result.model_dump(mode="json"),
            "evidence_graph": result_graph(selected, request, result),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), default=str)
            temp = Path(handle.name)
        temp.replace(path)
        return payload

    def get(self, run_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9]{64}", run_id):
            raise LookupError("invalid inference run ID")
        path = self.root / run_id[:2] / f"{run_id}.json"
        if not path.is_file():
            raise LookupError(f"unknown inference run {run_id!r}")
        return json.loads(path.read_text(encoding="utf-8"))

    def replay(self, run_id: str) -> dict[str, Any]:
        prior = self.get(run_id)
        request = KBInferenceRequest.model_validate(prior["identity"]["request"])
        kb_id = prior["identity"]["kb_id"]
        releases = self.catalog.releases(kb_id)
        if not any(
            item.version_id == prior["identity"]["version_id"]
            and item.content_sha256 == prior["identity"]["release_digest"]
            for item in releases
        ):
            return {
                "status": "blocked",
                "run_id": run_id,
                "reason": "pinned release is no longer active",
            }
        fresh = self.service.execute(kb_id, request).model_dump(mode="json")
        return {
            "status": "replayed",
            "run_id": run_id,
            "outcome_matches": _outcome(fresh) == _outcome(prior["result"]),
            "result": fresh,
        }

    def _identity(self, kb: KnowledgeBase, request: KBInferenceRequest) -> dict[str, Any]:
        capabilities = self.service.capabilities(kb.kb_id)
        return {
            "kb_id": kb.kb_id,
            "version_id": kb.current_version_id,
            "release_digest": kb.current_version.content_sha256,
            "formalization_digest": canonical_digest(
                [item.sha256 for item in kb.current_version.artifacts]
            ),
            "request": request.model_dump(mode="json"),
            "request_digest": canonical_digest(request.model_dump(mode="json")),
            "backend_compiler_digest": canonical_digest(capabilities),
            "resource_policy_digest": canonical_digest({"max_models": request.max_models}),
        }


def layered_graph(kb: KnowledgeBase) -> dict[str, Any]:
    nodes = []
    for artifact in kb.current_version.artifacts:
        nodes.append(
            {
                "id": artifact.artifact_id,
                "label": artifact.name,
                "layer": _layer(artifact),
                "role": artifact.role.value,
                "formalism": artifact.formalism.value,
                "digest": artifact.sha256,
            }
        )
    edges = []
    known = {item.artifact_id: item for item in kb.current_version.artifacts}
    for artifact in kb.current_version.artifacts:
        for reference in artifact.references:
            source = known[reference]
            relation = _relation(source, artifact)
            edges.append(
                {
                    "source": reference,
                    "target": artifact.artifact_id,
                    "relation": relation,
                    "semantic": relation != "presentation_link",
                    "source_digest": source.sha256,
                    "target_digest": artifact.sha256,
                }
            )
    return {
        "kb_id": kb.kb_id,
        "version_id": kb.current_version_id,
        "release_digest": kb.current_version.content_sha256,
        "nodes": nodes,
        "edges": edges,
        "accessible_alternative": [
            {"artifact": node["label"], "layer": node["layer"]} for node in nodes
        ],
    }


def result_graph(
    kb: KnowledgeBase, request: KBInferenceRequest, result: KBInferenceResult
) -> dict[str, Any]:
    base = layered_graph(kb)
    query_id = "query:" + canonical_digest(request.model_dump(mode="json"))[7:19]
    result_id = "result:" + canonical_digest(result.model_dump(mode="json"))[7:19]
    base["nodes"].extend(
        [
            {
                "id": query_id,
                "label": request.query or request.operation,
                "layer": "query",
                "digest": canonical_digest(request.model_dump(mode="json")),
            },
            {
                "id": result_id,
                "label": result.conclusion,
                "layer": "result",
                "digest": canonical_digest(result.model_dump(mode="json")),
            },
        ]
    )
    if request.artifact_id:
        artifact = next(
            (
                item
                for item in kb.current_version.artifacts
                if item.artifact_id == request.artifact_id
            ),
            None,
        )
        if artifact:
            base["edges"].append(
                {
                    "source": artifact.artifact_id,
                    "target": query_id,
                    "relation": "queried_formalization",
                    "semantic": True,
                    "source_digest": artifact.sha256,
                    "target_digest": base["nodes"][-2]["digest"],
                }
            )
    base["edges"].append(
        {
            "source": query_id,
            "target": result_id,
            "relation": "produced_result",
            "semantic": True,
            "source_digest": base["nodes"][-2]["digest"],
            "target_digest": base["nodes"][-1]["digest"],
        }
    )
    return base


def plan_inference(catalog: KnowledgeBaseCatalog, kb_id: str, operation: str) -> dict[str, Any]:
    service = KBInferenceService(catalog)
    routes = [row for row in service.capabilities(kb_id) if operation in row["operations"]]
    kb = catalog.get(kb_id)
    try:
        release = catalog.execution_release(kb_id)
    except LookupError:
        release = None
    return {
        "kb_id": kb_id,
        "version_id": kb.current_version_id,
        "operation": operation,
        "executable": bool(routes) and release is not None,
        "routes": routes,
        "release_id": release.release_id if release else None,
        "blockers": [] if release else ["no_published_release"],
        "claim_boundary": "Planning reports declared capability and release eligibility; it does not execute or establish a conclusion.",
    }


def _snippet(content: str, terms: tuple[str, ...]) -> str:
    positions = [content.find(term) for term in terms if term in content]
    start = max(0, min(positions) - 80) if positions else 0
    return " ".join(content[start : start + 320].split())


def _semantic_artifact(item: KBArtifactRef) -> tuple[Any, ...]:
    return (
        item.role,
        item.formalism,
        item.media_type,
        item.sha256,
        item.language,
        item.status,
        item.references,
    )


def _release_predicates(index: ReleaseSearchIndex) -> set[str]:
    result = set()
    for doc in index.documents:
        if doc["formalism"] in {"asp", "prolog"}:
            result.update(
                f"{name.removeprefix('-')}/{0 if not args.strip() else len(args.split(','))}"
                for name, args in _PREDICATE.findall(
                    _strip_comments(doc["content"], KBFormalism(doc["formalism"]))
                )
            )
    return result


def _strip_comments(content: str, formalism: KBFormalism) -> str:
    marker = "%" if formalism == KBFormalism.PROLOG else "%"
    return "\n".join(line.split(marker, 1)[0] for line in content.splitlines())


def _release_ref(index: ReleaseSearchIndex) -> dict[str, str]:
    return {
        "kb_id": index.kb.kb_id,
        "version_id": index.version.version_id,
        "release_digest": index.version.content_sha256,
    }


def _source_coverage(version: KBVersion) -> dict[str, int]:
    sources = {item.artifact_id for item in version.artifacts if item.role.value == "source"}
    referenced = {ref for item in version.artifacts for ref in item.references if ref in sources}
    return {
        "source_count": len(sources),
        "referenced_source_count": len(referenced),
        "unreferenced_source_count": len(sources - referenced),
    }


def _projection_losses(index: ReleaseSearchIndex) -> list[str]:
    return sorted(
        doc["artifact_id"]
        for doc in index.documents
        if doc["artifact_id"] and "projection_loss" in doc["content"].casefold()
    )


def _outcome(result: dict[str, Any]) -> tuple[Any, ...]:
    return (
        result.get("status"),
        result.get("conclusion"),
        result.get("target_support"),
        result.get("contrary_support"),
        result.get("complete"),
        result.get("model_count"),
    )


def _layer(artifact: KBArtifactRef) -> str:
    return {
        "source": "source",
        "interpretation": "claim",
        "facts": "unit_claim",
        "rules": "rule_axiom",
        "axioms": "rule_axiom",
        "model": "projection",
        "query": "query",
        "evidence": "result",
    }.get(artifact.role.value, "unit_claim")


def _relation(source: KBArtifactRef, target: KBArtifactRef) -> str:
    if source.role.value == "source" and target.role.value in {"facts", "interpretation"}:
        return "derived_from_source"
    if target.role.value in {"rules", "axioms", "model"}:
        return "semantic_dependency"
    if target.role.value == "evidence":
        return "evidence_for"
    return "presentation_link"


__all__ = [
    "InferenceRunStore",
    "ReleaseSearchIndex",
    "canonical_digest",
    "compare_releases",
    "layered_graph",
    "plan_inference",
    "query_editor_model",
    "result_graph",
]
