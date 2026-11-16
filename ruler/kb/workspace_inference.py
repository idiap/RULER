# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Unified, capability-truthful inference over named KB artifacts."""

from __future__ import annotations

import re
from typing import Protocol, TypedDict

import clingo
import yaml

from ruler.domains.legal import LegalReasoningPacket, assess_legal_packet
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import (
    KBArtifactRef,
    KBFormalism,
    KBInferenceRequest,
    KBInferenceResult,
    KnowledgeBase,
)
from ruler.kb.workspace_governance import execution_boundary

_GROUND_TERM = r'(?:[a-z][a-z0-9_]*|-?[0-9]+|"[A-Za-z0-9_.: -]{1,128}")'
_GROUND_ATOM = re.compile(rf"^-?[a-z][a-z0-9_]*(?:\({_GROUND_TERM}(?:,{_GROUND_TERM})*\))?$")
_UNSAFE_ASP = re.compile(r"#\s*(?:include|script)|@")


class InferenceAdapter(Protocol):
    backend_id: str
    formalisms: frozenset[KBFormalism]
    operations: frozenset[str]

    def execute(
        self,
        *,
        kb: KnowledgeBase,
        artifact: KBArtifactRef,
        request: KBInferenceRequest,
        catalog: KnowledgeBaseCatalog,
    ) -> KBInferenceResult: ...


class AdapterCapability(TypedDict):
    artifact_id: str
    formalism: str
    backend_id: str
    operations: list[str]


class KBInferenceService:
    def __init__(
        self,
        catalog: KnowledgeBaseCatalog,
        adapters: tuple[InferenceAdapter, ...] | None = None,
    ) -> None:
        self.catalog = catalog
        if adapters is None:
            # Keep the protocol and the concrete adapters decoupled while exposing the
            # full formalism registry through the default service.
            from ruler.kb.formalism_adapters import default_formalism_adapters

            configured = (
                AspQueryAdapter(),
                LegalAssuranceAdapter(),
                *default_formalism_adapters(),
            )
        else:
            configured = adapters
        ids = [item.backend_id for item in configured]
        if len(ids) != len(set(ids)):
            raise ValueError("inference adapter IDs must be unique")
        self.adapters = configured

    def capabilities(self, kb_id: str) -> tuple[AdapterCapability, ...]:
        kb = self.catalog.get(kb_id)
        rows: list[AdapterCapability] = []
        for artifact in kb.current_version.artifacts:
            for adapter in self.adapters:
                if artifact.formalism in adapter.formalisms and self._can_execute(
                    adapter, artifact
                ):
                    rows.append(
                        {
                            "artifact_id": artifact.artifact_id,
                            "formalism": artifact.formalism.value,
                            "backend_id": adapter.backend_id,
                            "operations": sorted(adapter.operations),
                        }
                    )
        return tuple(rows)

    def execute(self, kb_id: str, request: KBInferenceRequest) -> KBInferenceResult:
        kb = self.catalog.get(kb_id)
        allow_preview = request.parameters.get("allow_preview") is True
        try:
            release = self.catalog.execution_release(kb_id, allow_preview=allow_preview)
        except LookupError as exc:
            return _blocked(kb, request, "release-governance", str(exc))
        version = next(item for item in kb.versions if item.version_id == release.version_id)
        if request.version_id is not None and request.version_id != release.version_id:
            return _blocked(
                kb, request, "catalog", "requested version is not the active immutable version"
            )
        selected_kb = kb.model_copy(update={"current_version_id": version.version_id})
        boundary = execution_boundary(release)
        candidates = list(version.artifacts)
        if request.artifact_id:
            candidates = [item for item in candidates if item.artifact_id == request.artifact_id]
            if not candidates:
                return _blocked(
                    kb,
                    request,
                    "catalog",
                    "requested artifact is not present in the pinned version",
                )
        for artifact in candidates:
            for adapter in self.adapters:
                if (
                    artifact.formalism in adapter.formalisms
                    and self._can_execute(adapter, artifact)
                    and request.operation in adapter.operations
                    and (request.backend_id is None or request.backend_id == adapter.backend_id)
                ):
                    try:
                        result = adapter.execute(
                            kb=selected_kb, artifact=artifact, request=request, catalog=self.catalog
                        )
                        if boundary.preview:
                            result = result.model_copy(
                                update={
                                    "claim_boundary": f"{boundary.warning}. {result.claim_boundary}",
                                    "result": {
                                        **result.result,
                                        "release_boundary": boundary.model_dump(mode="json"),
                                    },
                                }
                            )
                        return result
                    except (OSError, ValueError, RuntimeError) as exc:
                        return KBInferenceResult(
                            request_id=request.request_id,
                            kb_id=kb.kb_id,
                            version_id=version.version_id,
                            operation=request.operation,
                            backend_id=adapter.backend_id,
                            status="error",
                            conclusion="underdetermined",
                            summary="The selected backend rejected or could not execute the request.",
                            blockers=(str(exc),),
                            claim_boundary="Backend failure establishes no support, contrary support, or domain conclusion.",
                        )
        return KBInferenceResult(
            request_id=request.request_id,
            kb_id=kb.kb_id,
            version_id=version.version_id,
            operation=request.operation,
            backend_id=request.backend_id or "none",
            status="unsupported",
            conclusion="not_applicable",
            summary="No artifact/backend pair declares this operation and formalism.",
            blockers=("capability_not_registered",),
            claim_boundary="Artifact presence does not imply executable inference capability.",
        )

    def _can_execute(self, adapter: InferenceAdapter, artifact: KBArtifactRef) -> bool:
        """Reject schema-incompatible artifact/backend pairs before advertising them."""
        checker = getattr(adapter, "can_execute", None)
        if checker is None:
            return True
        try:
            return bool(checker(artifact=artifact, catalog=self.catalog))
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            return False


class AspQueryAdapter:
    backend_id = "clingo-ground-query-v1"
    formalisms = frozenset({KBFormalism.ASP})
    operations = frozenset({"query", "verify", "evaluate"})

    def execute(
        self,
        *,
        kb: KnowledgeBase,
        artifact: KBArtifactRef,
        request: KBInferenceRequest,
        catalog: KnowledgeBaseCatalog,
    ) -> KBInferenceResult:
        if not request.query:
            raise ValueError("ASP inference requires a ground query atom")
        target = _parse_ground_atom(request.query)
        contrary = _parse_ground_atom(request.contrary) if request.contrary else None
        facts = tuple(_parse_ground_atom(item) for item in request.asserted_facts)
        source = catalog.artifact_path(artifact).read_text(encoding="utf-8")
        if _UNSAFE_ASP.search(source):
            raise ValueError(
                "ASP module uses a prohibited include, script, or external function directive"
            )
        control = clingo.Control(["--warn=none", "--models=0"])
        control.add("base", [], source)
        if facts:
            control.add("scenario", [], "\n".join(f"{item}." for item in request.asserted_facts))
        control.ground([("base", []), ("scenario", [])] if facts else [("base", [])])
        model_count = 0
        target_hits = 0
        contrary_hits = 0
        truncated = False
        with control.solve(yield_=True) as handle:
            for model in handle:
                model_count += 1
                if model.contains(target):
                    target_hits += 1
                if contrary is not None and model.contains(contrary):
                    contrary_hits += 1
                if model_count > request.max_models:
                    truncated = True
                    handle.cancel()
                    break
        if model_count == 0:
            return KBInferenceResult(
                request_id=request.request_id,
                kb_id=kb.kb_id,
                version_id=kb.current_version_id,
                operation=request.operation,
                backend_id=self.backend_id,
                status="completed",
                conclusion="conflict",
                summary="The ASP scenario is inconsistent and has no stable model.",
                target_support="unknown",
                contrary_support="unknown",
                complete=True,
                model_count=0,
                evidence=(artifact.artifact_id, artifact.sha256),
                blockers=("no_stable_model",),
                claim_boundary="Inconsistency is relative to the selected ASP module and asserted scenario facts.",
            )
        if truncated:
            return KBInferenceResult(
                request_id=request.request_id,
                kb_id=kb.kb_id,
                version_id=kb.current_version_id,
                operation=request.operation,
                backend_id=self.backend_id,
                status="blocked",
                conclusion="underdetermined",
                summary="Model enumeration exceeded the declared bound.",
                model_count=model_count,
                evidence=(artifact.artifact_id, artifact.sha256),
                blockers=("model_enumeration_incomplete",),
                claim_boundary="A bounded partial model sample cannot establish skeptical support or non-support.",
            )
        target_support = (
            "proved"
            if target_hits == model_count
            else "not_proved" if target_hits == 0 else "unknown"
        )
        contrary_support = (
            "unknown"
            if contrary is None
            else (
                "proved"
                if contrary_hits == model_count
                else "not_proved" if contrary_hits == 0 else "unknown"
            )
        )
        conclusion = _conclusion(target_support, contrary_support)
        return KBInferenceResult.model_validate(
            dict(
                request_id=request.request_id,
                kb_id=kb.kb_id,
                version_id=kb.current_version_id,
                operation=request.operation,
                backend_id=self.backend_id,
                status="completed",
                conclusion=conclusion,
                summary=f"Evaluated {model_count} complete stable model(s); target occurred in {target_hits}.",
                target_support=target_support,
                contrary_support=contrary_support,
                complete=True,
                model_count=model_count,
                evidence=(artifact.artifact_id, artifact.sha256),
                result={
                    "target": request.query,
                    "contrary": request.contrary,
                    "target_model_count": target_hits,
                    "contrary_model_count": contrary_hits if contrary is not None else None,
                    "asserted_fact_count": len(facts),
                },
                claim_boundary="Support is skeptical stable-model support within the selected digest-bound ASP encoding; absence is not domain falsity.",
            )
        )


class LegalAssuranceAdapter:
    backend_id = "legal-packet-assurance-v1"
    formalisms = frozenset({KBFormalism.LEGAL_ARGUMENT})
    operations = frozenset({"assess", "verify"})

    def execute(
        self,
        *,
        kb: KnowledgeBase,
        artifact: KBArtifactRef,
        request: KBInferenceRequest,
        catalog: KnowledgeBaseCatalog,
    ) -> KBInferenceResult:
        payload = yaml.safe_load(catalog.artifact_path(artifact).read_text(encoding="utf-8"))
        packet = LegalReasoningPacket.model_validate(payload)
        report = assess_legal_packet(packet)
        return KBInferenceResult(
            request_id=request.request_id,
            kb_id=kb.kb_id,
            version_id=kb.current_version_id,
            operation=request.operation,
            backend_id=self.backend_id,
            status="completed",
            conclusion="underdetermined",
            summary=f"Legal packet assurance status: {report.status}.",
            complete=True,
            evidence=(artifact.artifact_id, artifact.sha256),
            blockers=report.blockers,
            result=report.model_dump(mode="json"),
            claim_boundary=report.claim_boundary,
        )


def _parse_ground_atom(value: str | None) -> clingo.Symbol:
    if value is None or not _GROUND_ATOM.fullmatch(value):
        raise ValueError(f"expected a safe ground atom, got {value!r}")
    symbol = clingo.parse_term(value)
    if symbol.type != clingo.SymbolType.Function:
        raise ValueError("query must parse as a ground function atom")
    return symbol


def _conclusion(target: str, contrary: str) -> str:
    if target == "proved" and contrary == "proved":
        return "conflict"
    if target == "proved":
        return "supported"
    if contrary == "proved":
        return "refuted"
    return "underdetermined"


def _blocked(
    kb: KnowledgeBase,
    request: KBInferenceRequest,
    backend_id: str,
    reason: str,
) -> KBInferenceResult:
    return KBInferenceResult(
        request_id=request.request_id,
        kb_id=kb.kb_id,
        version_id=kb.current_version_id,
        operation=request.operation,
        backend_id=backend_id,
        status="blocked",
        conclusion="underdetermined",
        summary=reason,
        blockers=(reason,),
        claim_boundary="A blocked request establishes no inference result.",
    )
