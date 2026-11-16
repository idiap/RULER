# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Capability-truthful adapters for managed multi-formalism knowledge bases.

Each adapter reports only what its executable and evidence actually establish. Optional
external tools fail as unavailable, and compiler/elaborator success is never promoted
to a domain theorem.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from ruler.kb.workspace_inference import InferenceAdapter

from ruler.applications.decision_support.ranking import (
    DecisionSupportRequest,
    rank_candidate_options,
)
from ruler.evaluation.contracts import EvaluationRequest
from ruler.evaluation.pipeline import EvaluationPipeline
from ruler.kb.asp_compiler import compile_asp
from ruler.kb.formalization import PredicateRegistry
from ruler.kb.logical_ir import Atom, ExpressionKind, LogicalExpression, LogicalProgram
from ruler.kb.optimization import NeutralOptimizationArtifact
from ruler.kb.prolog_compiler import ConclusionExpectation, crosscheck_asp_prolog
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import (
    KBArtifactRef,
    KBFormalism,
    KBInferenceRequest,
    KBInferenceResult,
    KnowledgeBase,
)
from ruler.solvers.maxsmt import solve_maxsmt_feature_choice


def _payload(catalog: KnowledgeBaseCatalog, artifact: KBArtifactRef) -> Any:
    return yaml.safe_load(catalog.artifact_path(artifact).read_text(encoding="utf-8"))


def _base(
    kb: KnowledgeBase,
    artifact: KBArtifactRef,
    request: KBInferenceRequest,
    backend_id: str,
    **changes: Any,
) -> KBInferenceResult:
    values: dict[str, Any] = {
        "request_id": request.request_id,
        "kb_id": kb.kb_id,
        "version_id": kb.current_version_id,
        "operation": request.operation,
        "backend_id": backend_id,
        "status": "completed",
        "conclusion": "underdetermined",
        "summary": "Backend operation completed within its declared boundary.",
        "complete": True,
        "evidence": (artifact.artifact_id, artifact.sha256),
        "claim_boundary": "Backend completion alone establishes no domain conclusion.",
    }
    values.update(changes)
    return KBInferenceResult(**values)


def _unavailable(
    kb: KnowledgeBase,
    artifact: KBArtifactRef,
    request: KBInferenceRequest,
    backend_id: str,
    executable: str,
) -> KBInferenceResult:
    return _base(
        kb,
        artifact,
        request,
        backend_id,
        status="blocked",
        complete=False,
        summary=f"Optional executable is unavailable: {executable}.",
        blockers=(f"backend_unavailable:{executable}",),
        result={"execution": "unavailable"},
        claim_boundary="Unavailable execution establishes neither support nor non-support.",
    )


def _logical_envelope(payload: Any) -> tuple[LogicalProgram, PredicateRegistry]:
    if not isinstance(payload, dict) or "program" not in payload or "registry" not in payload:
        raise ValueError("logical IR artifact requires program and registry objects")
    return (
        LogicalProgram.model_validate(payload["program"]),
        PredicateRegistry.model_validate(payload["registry"]),
    )


def _is_logical_envelope(payload: Any) -> bool:
    try:
        _logical_envelope(payload)
    except (TypeError, ValueError):
        return False
    return True


class LogicalIRValidationAdapter:
    backend_id = "logical-ir-asp-validation-v1"
    formalisms = frozenset({KBFormalism.LOGICAL_IR})
    operations = frozenset({"verify"})

    def can_execute(self, *, artifact, catalog) -> bool:
        return _is_logical_envelope(_payload(catalog, artifact))

    def execute(self, *, kb, artifact, request, catalog):
        program, registry = _logical_envelope(_payload(catalog, artifact))
        compiled = compile_asp(program, registry)
        return _base(
            kb,
            artifact,
            request,
            self.backend_id,
            summary="Typed Logical IR and declared show boundaries compiled and grounded successfully.",
            evidence=(artifact.artifact_id, artifact.sha256, compiled.sha256),
            result={"validation": "encoding_checked", "program_id": program.program_id},
            claim_boundary="Compilation checks declared predicates, types, lowering, and grounding; it is not proof of a queried proposition.",
        )


class PrologCrosscheckAdapter:
    backend_id = "swi-prolog-horn-crosscheck-v1"
    formalisms = frozenset({KBFormalism.LOGICAL_IR})
    operations = frozenset({"crosscheck"})

    def can_execute(self, *, artifact, catalog) -> bool:
        return _is_logical_envelope(_payload(catalog, artifact))

    def execute(self, *, kb, artifact, request, catalog):
        if shutil.which("swipl") is None:
            return _unavailable(kb, artifact, request, self.backend_id, "swipl")
        program, registry = _logical_envelope(_payload(catalog, artifact))
        for statement in program.statements:
            if statement.body is not None:
                _assert_horn_overlap(statement.body)
        raw_expectations = request.parameters.get("expectations")
        if not isinstance(raw_expectations, list) or not raw_expectations:
            raise ValueError("Prolog crosscheck requires a non-empty parameters.expectations list")
        expectations = tuple(
            ConclusionExpectation.model_validate(item) for item in raw_expectations
        )
        if request.query is not None and request.query not in {
            item.expectation_id for item in expectations
        }:
            raise ValueError("crosscheck query must name one declared expectation_id")
        report = crosscheck_asp_prolog(program, expectations, registry)
        report.require_equivalent()
        selected = (
            next(item for item in report.checks if item.expectation_id == request.query)
            if request.query is not None
            else None
        )
        return _base(
            kb,
            artifact,
            request,
            self.backend_id,
            conclusion=(
                "supported"
                if selected and selected.asp_observed
                else "refuted" if selected else "underdetermined"
            ),
            target_support=(
                "proved"
                if selected and selected.asp_observed
                else "not_proved" if selected else "unknown"
            ),
            summary="ASP and SWI-Prolog agreed on every declared Horn-overlap expectation.",
            evidence=(artifact.artifact_id, artifact.sha256),
            result={
                "execution": "completed",
                "authority": "crosscheck_only",
                "equivalent": report.equivalent,
                "checks": [item.model_dump(mode="json") for item in report.checks],
            },
            claim_boundary="Prolog is only a Horn-overlap cross-check; ASP/default-negation or stable-model conclusions cannot be established here.",
        )


def _assert_horn_overlap(expression: LogicalExpression) -> None:
    unsupported = {
        ExpressionKind.NEGATION,
        ExpressionKind.DISJUNCTION,
        ExpressionKind.AGGREGATION,
        ExpressionKind.EXCEPTION,
        ExpressionKind.PRIORITY,
        ExpressionKind.TEMPORAL,
    }
    if expression.kind in unsupported:
        raise ValueError(
            f"{expression.kind.value} is outside the positive Horn Prolog cross-check boundary"
        )
    for operand in expression.operands:
        _assert_horn_overlap(operand)


class VampireAdapter:
    backend_id = "vampire-tptp-bounded-v1"
    formalisms = frozenset({KBFormalism.TPTP})
    operations = frozenset({"verify", "consistency"})

    def execute(self, *, kb, artifact, request, catalog):
        executable = shutil.which("vampire")
        if executable is None:
            return _unavailable(kb, artifact, request, self.backend_id, "vampire")
        timeout = min(int(request.parameters.get("timeout_seconds", 10)), 30)
        source = catalog.artifact_path(artifact)
        target = request.query
        if request.operation == "verify":
            if not target or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", target):
                raise ValueError("Vampire verify requires a safe conjecture name in query")
            source_text = source.read_text(encoding="utf-8")
            declaration = re.compile(
                rf"(?:fof|tff|thf)\s*\(\s*{re.escape(target)}\s*,\s*conjecture\s*,",
                re.IGNORECASE,
            )
            if not declaration.search(source_text):
                raise ValueError(f"requested conjecture is not declared: {target}")
        try:
            completed = subprocess.run(
                [executable, "--mode", "casc", "--time_limit", str(timeout), str(source)],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout + 2,
            )
        except subprocess.TimeoutExpired:
            return _base(
                kb,
                artifact,
                request,
                self.backend_id,
                status="blocked",
                complete=False,
                summary="Vampire exceeded the bounded execution time.",
                blockers=("backend_timeout",),
                result={"execution": "timeout"},
                claim_boundary="A timeout establishes neither support nor non-support.",
            )
        output = completed.stdout + completed.stderr
        status_line = next((line for line in output.splitlines() if "SZS status" in line), "")
        if completed.returncode not in {0, 1} or not status_line:
            raise RuntimeError(
                "Vampire did not return a recognized SZS result: " f"exit={completed.returncode}"
            )
        theorem = any(word in status_line for word in ("Theorem", "Unsatisfiable"))
        digest = "sha256:" + hashlib.sha256(output.encode()).hexdigest()
        return _base(
            kb,
            artifact,
            request,
            self.backend_id,
            conclusion=(
                "supported" if theorem and request.operation == "verify" else "underdetermined"
            ),
            target_support="proved" if theorem and request.operation == "verify" else "unknown",
            summary=f"Vampire completed with {status_line.strip() or 'no recognized SZS status'}.",
            evidence=(artifact.artifact_id, artifact.sha256, digest),
            result={
                "execution": "completed",
                "target": target,
                "szs_status": status_line.strip(),
                "proof_object": "unverified",
            },
            claim_boundary="SZS status is relative to the selected TPTP encoding; emitted TSTP is unverified evidence until independently checked.",
        )


class LeanAdapter:
    backend_id = "lean4-elaboration-v1"
    formalisms = frozenset({KBFormalism.LEAN4})
    operations = frozenset({"elaborate", "verify"})

    def execute(self, *, kb, artifact, request, catalog):
        executable = shutil.which("lean")
        if executable is None:
            return _unavailable(kb, artifact, request, self.backend_id, "lean")
        source = catalog.artifact_path(artifact)
        target = request.query
        if request.operation == "verify":
            if not target or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", target):
                raise ValueError("Lean verify requires a safe declaration name in query")
            source_text = source.read_text(encoding="utf-8")
            declaration = re.compile(
                rf"^\s*(?:theorem|lemma)\s+{re.escape(target)}(?:\s|:)", re.MULTILINE
            )
            if not declaration.search(source_text):
                raise ValueError(f"requested Lean theorem is not declared: {target}")
        timeout = min(int(request.parameters.get("timeout_seconds", 20)), 60)
        try:
            completed = subprocess.run(
                [executable, str(source)],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _base(
                kb,
                artifact,
                request,
                self.backend_id,
                status="blocked",
                complete=False,
                summary="Lean exceeded the bounded execution time.",
                blockers=("backend_timeout",),
                result={"execution": "timeout", "target": target},
                claim_boundary="A timeout establishes neither theorem support nor non-support.",
            )
        checked = completed.returncode == 0
        return _base(
            kb,
            artifact,
            request,
            self.backend_id,
            status="completed" if checked else "error",
            complete=checked,
            summary=(
                "Lean artifact elaborated successfully."
                if checked
                else "Lean rejected the artifact."
            ),
            blockers=() if checked else ("lean_elaboration_failed",),
            result={
                "execution": "completed",
                "encoding_checked": checked,
                "target": target,
                "theorem_evidence": "not_reconstructed",
            },
            claim_boundary="Elaboration checks the visible Lean encoding and axioms; independent theorem reconstruction and domain review remain distinct.",
        )


class StructuredComplianceAdapter:
    backend_id = "logical-ir-compliance-v1"
    formalisms = frozenset({KBFormalism.SEMANTIC_IR, KBFormalism.STRUCTURED_DATA})
    operations = frozenset({"evaluate", "counterfactual"})

    def can_execute(self, *, artifact, catalog) -> bool:
        payload = _payload(catalog, artifact)
        if not _is_logical_envelope(payload) or not isinstance(payload, dict):
            return False
        try:
            EvaluationRequest.model_validate(payload.get("request"))
        except (TypeError, ValueError):
            return False
        return True

    def execute(self, *, kb, artifact, request, catalog):
        payload = _payload(catalog, artifact)
        if not isinstance(payload, dict):
            raise ValueError("compliance artifact must be a mapping")
        program, registry = _logical_envelope(payload)
        evaluation = EvaluationRequest.model_validate(payload.get("request"))
        pipeline = EvaluationPipeline(program, registry)
        if request.operation == "evaluate":
            result = pipeline.evaluate(evaluation)
        else:
            intervention = request.parameters.get("intervention")
            if not isinstance(intervention, dict) or set(intervention) != {"operation", "facts"}:
                raise ValueError("counterfactual requires explicit operation and facts")
            operation = intervention["operation"]
            if operation not in {"add", "remove", "replace"}:
                raise ValueError("intervention operation must be add, remove, or replace")
            changed = tuple(Atom.model_validate(item) for item in intervention["facts"])
            facts = list(evaluation.facts)
            if operation == "replace":
                facts = list(changed)
            elif operation == "add":
                facts.extend(changed)
            else:
                remove = {item.key() for item in changed}
                facts = [item for item in facts if item.key() not in remove]
            result = pipeline.counterfactual(
                evaluation,
                probe_id=str(request.parameters.get("probe_id", request.request_id)),
                facts=tuple(facts),
            )
        return _base(
            kb,
            artifact,
            request,
            self.backend_id,
            summary="Open-world compliance evaluation completed with explicit unknown outcomes.",
            result=result.model_dump(mode="json"),
            claim_boundary="Missing outcomes remain unknown; counterfactual results are relative to the explicit fact intervention and pinned rule release.",
        )


class DeterministicRecommendationAdapter:
    backend_id = "deterministic-hard-gated-ranking-v1"
    formalisms = frozenset({KBFormalism.STRUCTURED_DATA})
    operations = frozenset({"recommend"})

    def can_execute(self, *, artifact, catalog) -> bool:
        try:
            DecisionSupportRequest.model_validate(_payload(catalog, artifact))
        except (TypeError, ValueError):
            return False
        return True

    def execute(self, *, kb, artifact, request, catalog):
        decision = DecisionSupportRequest.model_validate(_payload(catalog, artifact))
        result = rank_candidate_options(decision)
        return _base(
            kb,
            artifact,
            request,
            self.backend_id,
            conclusion="supported" if result.status == "ranked" else "not_applicable",
            summary=f"Deterministic hard-gated ranking status: {result.status}.",
            result=result.model_dump(mode="json"),
            claim_boundary="Ranking cannot change hard eligibility, invent grounding, or authorize action; selected options retain their source trace references.",
        )


class MaxSMTOptimizationAdapter:
    backend_id = "z3-typed-maxsmt-v1"
    formalisms = frozenset({KBFormalism.OPTIMIZATION_MODEL})
    operations = frozenset({"optimize"})

    def can_execute(self, *, artifact, catalog) -> bool:
        try:
            NeutralOptimizationArtifact.model_validate(_payload(catalog, artifact))
        except (TypeError, ValueError):
            return False
        return True

    def execute(self, *, kb, artifact, request, catalog):
        envelope = NeutralOptimizationArtifact.model_validate(_payload(catalog, artifact))
        result = solve_maxsmt_feature_choice(
            envelope.problem, top_k=min(int(request.parameters.get("top_k", 3)), 20)
        )
        return _base(
            kb,
            artifact,
            request,
            self.backend_id,
            conclusion=(
                "supported" if result.status in {"optimal", "feasible"} else "not_applicable"
            ),
            summary=f"Typed MaxSMT optimization status: {result.status}.",
            result=result.model_dump(mode="json"),
            claim_boundary=envelope.profile.claim_boundary,
        )


def default_formalism_adapters() -> tuple[InferenceAdapter, ...]:
    return (
        LogicalIRValidationAdapter(),
        PrologCrosscheckAdapter(),
        VampireAdapter(),
        LeanAdapter(),
        StructuredComplianceAdapter(),
        DeterministicRecommendationAdapter(),
        MaxSMTOptimizationAdapter(),
    )
