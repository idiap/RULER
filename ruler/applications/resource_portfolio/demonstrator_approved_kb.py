# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic, automatic acceptance of demonstrator formal knowledge bases.

The assessment surface is a structured critic for continuous refinement.  The export
surface is deliberately stricter: it writes an accepted release only after every
logical statement passes every applicable executable gate.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import clingo
from pydantic import Field, model_validator

from ruler.applications.resource_portfolio.demonstrator_formalization import (
    DemonstratorFormalizationRun,
)
from ruler.kb.autoformalization_refinement import RefinementFinding, build_refinement_finding
from ruler.contracts.common import StrictContract, validate_sha256
from ruler.ingestion.contracts import canonical_sha256
from ruler.io import stable_hash, write_text, write_yaml
from ruler.kb.asp_compiler import CompiledASP, compile_asp
from ruler.kb.formalization_release import (
    FormalLogicRelease,
    FormalReviewDecision,
    ValidatorEvidence,
    build_formal_logic_release,
)
from ruler.kb.formalization_validation import IssueSeverity, validate_static_semantics
from ruler.kb.formalization import PredicateRegistry, ValueType
from ruler.kb.generative_autoformalization import (
    AutoformalizationCandidate,
    AutoformalizationRequest,
)
from ruler.kb.logical_ir import Atom, Constant, LogicalProgram
from ruler.kb.prolog_compiler import (
    CompiledProlog,
    ConclusionExpectation,
    compile_prolog,
    crosscheck_asp_prolog,
)

ACCEPTED_ASP_FILENAME = "accepted_kb.lp"
ACCEPTED_PROLOG_FILENAME = "accepted_kb.pl"
FORMAL_LOGIC_RELEASE_FILENAME = "formal_logic_release.yaml"
ACCEPTANCE_RECEIPT_FILENAME = "accepted_kb_manifest.yaml"

_GATES = (
    "static_semantics",
    "asp_compile_execute",
    "prolog_compile_load",
    "asp_prolog_crosscheck",
)
_VALIDATOR_VERSIONS = {
    "static_semantics": "ruler-static-semantics/1",
    "asp_compile_execute": "ruler-clingo-execution/1",
    "prolog_compile_load": "ruler-swi-load/1",
    "asp_prolog_crosscheck": "ruler-asp-prolog-crosscheck/1",
}


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class FormalKBAcceptanceFinding(StrictContract):
    """One deterministic critic finding suitable for a refinement retry."""

    gate_id: Literal[
        "static_semantics",
        "asp_compile_execute",
        "prolog_compile_load",
        "asp_prolog_crosscheck",
    ]
    code: str
    statement_ids: tuple[str, ...] = Field(min_length=1)
    message: str


class StatementAcceptanceAssessment(StrictContract):
    """Complete gate result for one logical statement."""

    statement_id: str
    passed_gate_ids: tuple[str, ...]
    finding_codes: tuple[str, ...] = ()
    accepted: bool

    @model_validator(mode="after")
    def status_matches_gates(self) -> "StatementAcceptanceAssessment":
        if self.accepted != (self.passed_gate_ids == _GATES and not self.finding_codes):
            raise ValueError("statement acceptance status does not match its gate evidence")
        return self


class FormalKBAcceptanceAssessment(StrictContract):
    """Non-throwing, hash-bound validation result consumed by refinement."""

    schema_version: Literal["resource-portfolio-formal-kb-assessment/v1"] = (
        "resource-portfolio-formal-kb-assessment/v1"
    )
    formalization_run_sha256: str
    ir_sha256: str
    statements: tuple[StatementAcceptanceAssessment, ...] = Field(min_length=1)
    findings: tuple[FormalKBAcceptanceFinding, ...] = ()
    promotable: bool
    assessment_sha256: str

    @model_validator(mode="after")
    def assessment_is_closed(self) -> "FormalKBAcceptanceAssessment":
        validate_sha256(self.formalization_run_sha256)
        validate_sha256(self.ir_sha256)
        validate_sha256(self.assessment_sha256)
        ids = tuple(item.statement_id for item in self.statements)
        if len(set(ids)) != len(ids):
            raise ValueError("acceptance assessment statement IDs must be unique")
        if self.promotable != (
            not self.findings and all(item.accepted for item in self.statements)
        ):
            raise ValueError("promotable status does not match statement validation")
        expected = stable_hash(self.model_dump(mode="json", exclude={"assessment_sha256"}))
        if self.assessment_sha256 != expected:
            raise ValueError("acceptance assessment digest mismatch")
        return self

    def require_promotable(self) -> None:
        if not self.promotable:
            codes = ", ".join(item.code for item in self.findings)
            raise ValueError(f"formal KB acceptance failed: {codes or 'incomplete validation'}")


class AcceptedFormalKBArtifact(StrictContract):
    """One executable, accepted formal-language artifact."""

    formalism: Literal["asp", "prolog"]
    filename: Literal["accepted_kb.lp", "accepted_kb.pl"]
    media_type: Literal["text/x-asp", "text/x-prolog"]
    program_id: str
    compiler_version: str
    compiler_output_sha256: str
    content_sha256: str
    lifecycle: Literal["accepted"] = "accepted"
    activation_status: Literal["active"] = "active"
    acceptance_status: Literal["accepted"] = "accepted"
    solver_use_permitted: Literal[True] = True
    portfolio_optimization_authority: Literal[False] = False

    @model_validator(mode="after")
    def artifact_is_consistent(self) -> "AcceptedFormalKBArtifact":
        validate_sha256(self.compiler_output_sha256)
        validate_sha256(self.content_sha256)
        expected = (
            (ACCEPTED_ASP_FILENAME, "text/x-asp")
            if self.formalism == "asp"
            else (ACCEPTED_PROLOG_FILENAME, "text/x-prolog")
        )
        if (self.filename, self.media_type) != expected:
            raise ValueError("accepted formal KB filename/media type mismatch")
        return self


class AcceptedFormalKBReceipt(StrictContract):
    """Immutable receipt for automatic acceptance and its formal release."""

    schema_version: Literal["resource-portfolio-accepted-formal-kb/v1"] = (
        "resource-portfolio-accepted-formal-kb/v1"
    )
    source_artifact_id: str
    source_artifact_sha256: str
    formalization_run_sha256: str
    ir_sha256: str
    approved_statement_ids: tuple[str, ...] = Field(min_length=1)
    accepted_claim_ids: tuple[str, ...] = Field(min_length=1)
    accepted_claim_count: int = Field(ge=1)
    statement_assessments: tuple[StatementAcceptanceAssessment, ...] = Field(min_length=1)
    validator_evidence: tuple[ValidatorEvidence, ...] = Field(min_length=4, max_length=4)
    automatic_review_decision: FormalReviewDecision
    formal_logic_release: FormalLogicRelease
    formal_logic_release_sha256: str
    artifacts: tuple[AcceptedFormalKBArtifact, AcceptedFormalKBArtifact]
    lifecycle: Literal["accepted"] = "accepted"
    activation_status: Literal["active"] = "active"
    acceptance_status: Literal["accepted"] = "accepted"
    solver_use_permitted: Literal[True] = True
    portfolio_optimization_authority: Literal[False] = False
    authority: Literal["automatic_deterministic_validation"] = "automatic_deterministic_validation"
    receipt_sha256: str

    @model_validator(mode="after")
    def receipt_is_complete(self) -> "AcceptedFormalKBReceipt":
        for digest in (
            self.source_artifact_sha256,
            self.formalization_run_sha256,
            self.ir_sha256,
            self.formal_logic_release_sha256,
            self.receipt_sha256,
        ):
            validate_sha256(digest)
        assessed = tuple(item.statement_id for item in self.statement_assessments)
        if assessed != self.approved_statement_ids or not all(
            item.accepted for item in self.statement_assessments
        ):
            raise ValueError("approved statement IDs must exactly cover passing assessments")
        if self.accepted_claim_count != len(self.accepted_claim_ids) or len(
            set(self.accepted_claim_ids)
        ) != len(self.accepted_claim_ids):
            raise ValueError("accepted claim count must identify unique accepted claims")
        decision = self.automatic_review_decision
        if (
            decision.decision != "approved"
            or decision.logical_unit_ids != self.approved_statement_ids
        ):
            raise ValueError("automatic approval must exactly cover every accepted statement")
        if tuple(item.validator_id for item in self.validator_evidence) != _GATES:
            raise ValueError("accepted receipt requires every validator in deterministic order")
        if any(
            not item.passed or item.evaluated_ir_sha256 != self.ir_sha256
            for item in self.validator_evidence
        ):
            raise ValueError("accepted receipt requires current passing validator evidence")
        if self.formal_logic_release.ir_sha256 != self.ir_sha256:
            raise ValueError("formal release is stale for the accepted IR")
        if self.formal_logic_release_sha256 != canonical_sha256(
            self.formal_logic_release.model_dump(mode="json")
        ):
            raise ValueError("formal logic release digest mismatch")
        if tuple(item.formalism for item in self.artifacts) != ("asp", "prolog"):
            raise ValueError("accepted artifacts must be deterministic ASP then Prolog")
        expected = stable_hash(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("formal KB acceptance receipt digest mismatch")
        return self


def _program_for_statement(program: LogicalProgram, statement_id: str) -> LogicalProgram:
    statement = next(item for item in program.statements if item.statement_id == statement_id)
    return program.model_copy(update={"statements": (statement,), "show": ()})


def _execute_asp(asp: CompiledASP) -> None:
    control = clingo.Control(["--warn=none", "--models=1"])
    control.add("base", [], asp.text)
    control.ground([("base", [])])
    result = control.solve()
    if not result.satisfiable:
        raise ValueError("compiled ASP is unsatisfiable")


def _load_prolog(prolog: CompiledProlog) -> None:
    executable = shutil.which("swipl")
    if executable is None:
        raise RuntimeError("Prolog executable is unavailable: swipl")
    with TemporaryDirectory(prefix="ruler-accepted-prolog-") as temporary:
        path = Path(temporary) / ACCEPTED_PROLOG_FILENAME
        path.write_text(prolog.text, encoding="utf-8")
        completed = subprocess.run(
            [executable, "-q", "-s", str(path), "-g", "true", "-t", "halt"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise RuntimeError(f"Prolog load validation failed: {detail}")


def _constant_from_symbol(symbol: clingo.Symbol, value_type: ValueType) -> Constant:
    if symbol.type == clingo.SymbolType.Number:
        value: str | int | bool | date = symbol.number
    elif symbol.type == clingo.SymbolType.String:
        value = symbol.string
    elif symbol.type == clingo.SymbolType.Function and not symbol.arguments:
        if value_type == ValueType.BOOLEAN and symbol.name in {"true", "false"}:
            value = symbol.name == "true"
        else:
            value = symbol.name
    else:
        raise ValueError(f"unsupported grounded ASP term: {symbol}")
    if value_type == ValueType.DATE and isinstance(value, str):
        value = date.fromisoformat(value)
    return Constant(value_type=value_type, value=value)


def _ground_crosscheck_expectations(
    program: LogicalProgram, registry: PredicateRegistry
) -> tuple[ConclusionExpectation, ...]:
    """Enumerate the full finite grounding surface and its ASP truth values."""

    asp = compile_asp(program, registry)
    control = clingo.Control(["--warn=none", "--models=1"])
    control.add("base", [], asp.text)
    control.ground([("base", [])])
    models: list[set[clingo.Symbol]] = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            models.append(set(model.symbols(atoms=True)))
    if len(models) != 1:
        raise ValueError("accepted ASP must have exactly one deterministic model")
    truth = models[0]
    expectations: list[ConclusionExpectation] = []
    for symbolic_atom in control.symbolic_atoms:
        symbol = symbolic_atom.symbol
        signature = registry.require(symbol.name)
        if len(symbol.arguments) != signature.arity:
            raise ValueError(f"grounded arity mismatch for {symbol.name}")
        atom = Atom(
            predicate=symbol.name,
            arguments=tuple(
                _constant_from_symbol(argument, expected_type)
                for argument, expected_type in zip(
                    symbol.arguments, signature.argument_types, strict=True
                )
            ),
            classical_negation=symbol.negative,
        )
        expectations.append(
            ConclusionExpectation(
                expectation_id=f"ground:{len(expectations):06d}:{symbol}",
                atom=atom,
                expected=symbol in truth,
            )
        )
    if not expectations:
        raise ValueError("accepted programs require a finite grounded cross-check surface")
    return tuple(expectations)


def _finding(
    gate_id: str, code: str, statement_ids: tuple[str, ...], error: Exception | str
) -> FormalKBAcceptanceFinding:
    return FormalKBAcceptanceFinding.model_validate(
        dict(
            gate_id=gate_id,
            code=code,
            statement_ids=statement_ids,
            message=str(error),
        )
    )


def _assess_program(
    program: LogicalProgram,
    registry: PredicateRegistry,
    *,
    formalization_digest: str,
) -> FormalKBAcceptanceAssessment:
    statement_ids = tuple(sorted(item.statement_id for item in program.statements))
    passed: dict[str, list[str]] = {statement_id: [] for statement_id in statement_ids}
    findings: list[FormalKBAcceptanceFinding] = []

    semantic_report = validate_static_semantics(program, registry)
    static_failures: set[str] = set()
    for issue in semantic_report.issues:
        if issue.severity != IssueSeverity.ERROR:
            continue
        affected = issue.statement_ids or statement_ids
        static_failures.update(affected)
        findings.append(_finding("static_semantics", issue.code, affected, issue.message))
    for statement_id in statement_ids:
        if statement_id not in static_failures:
            passed[statement_id].append("static_semantics")

    # Validate each unit independently so refinement receives precise failure ownership.
    for statement_id in statement_ids:
        if statement_id in static_failures:
            continue
        unit = _program_for_statement(program, statement_id)
        try:
            unit_asp = compile_asp(unit, registry)
            _execute_asp(unit_asp)
            passed[statement_id].append("asp_compile_execute")
        except Exception as exc:  # compiler/backend failures are critic evidence
            findings.append(
                _finding("asp_compile_execute", "asp_validation_failed", (statement_id,), exc)
            )
            continue
        try:
            unit_prolog = compile_prolog(unit, registry)
            _load_prolog(unit_prolog)
            passed[statement_id].append("prolog_compile_load")
        except Exception as exc:
            findings.append(
                _finding("prolog_compile_load", "prolog_validation_failed", (statement_id,), exc)
            )
            continue

    # Whole-program closure catches interactions which isolated statement checks cannot.
    if not findings:
        try:
            asp = compile_asp(program, registry)
            _execute_asp(asp)
        except Exception as exc:
            findings.append(
                _finding("asp_compile_execute", "program_asp_validation_failed", statement_ids, exc)
            )
        try:
            prolog = compile_prolog(program, registry)
            _load_prolog(prolog)
        except Exception as exc:
            findings.append(
                _finding(
                    "prolog_compile_load", "program_prolog_validation_failed", statement_ids, exc
                )
            )
        try:
            expectations = _ground_crosscheck_expectations(program, registry)
            crosscheck_asp_prolog(program, expectations, registry).require_equivalent()
            for statement_id in statement_ids:
                passed[statement_id].append("asp_prolog_crosscheck")
        except Exception as exc:
            findings.append(
                _finding("asp_prolog_crosscheck", "program_backend_divergence", statement_ids, exc)
            )

    assessments = tuple(
        StatementAcceptanceAssessment(
            statement_id=statement_id,
            passed_gate_ids=tuple(passed[statement_id]),
            finding_codes=tuple(
                item.code for item in findings if statement_id in item.statement_ids
            ),
            accepted=tuple(passed[statement_id]) == _GATES
            and not any(statement_id in item.statement_ids for item in findings),
        )
        for statement_id in statement_ids
    )
    payload = {
        "formalization_run_sha256": formalization_digest,
        "ir_sha256": program.sha256(),
        "statements": assessments,
        "findings": tuple(findings),
        "promotable": not findings and all(item.accepted for item in assessments),
    }
    serialized = {
        "schema_version": "resource-portfolio-formal-kb-assessment/v1",
        **{
            key: (
                [item.model_dump(mode="json") for item in value]
                if key in {"statements", "findings"}
                else value
            )
            for key, value in payload.items()
        },
    }
    return FormalKBAcceptanceAssessment(**payload, assessment_sha256=stable_hash(serialized))


def assess_formal_kb_acceptance(run: DemonstratorFormalizationRun) -> FormalKBAcceptanceAssessment:
    """Return complete statement-scoped findings without prematurely stopping refinement."""

    return _assess_program(
        run.candidate.logical_program,
        run.request.predicate_registry,
        formalization_digest=run.run_digest,
    )


def candidate_acceptance_findings(
    request: AutoformalizationRequest,
    candidate: AutoformalizationCandidate,
) -> tuple[RefinementFinding, ...]:
    """Adapt executable acceptance defects into deterministic repair-loop findings."""

    digest = stable_hash(
        {
            "request": request.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
        }
    )
    assessment = _assess_program(
        candidate.logical_program,
        request.predicate_registry,
        formalization_digest=digest,
    )
    return tuple(
        build_refinement_finding(
            origin="deterministic",
            stage="semantics",
            severity="blocker",
            code=f"acceptance_{finding.code}",
            summary=finding.message[:600],
            repair_instruction=(
                "Repair the referenced logical units so the executable acceptance "
                f"gate {finding.gate_id} passes, then regenerate the complete candidate."
            ),
            statement_ids=finding.statement_ids,
            evidence=finding.model_dump(mode="json"),
        )
        for finding in assessment.findings
    )


def _accepted_header(
    run: DemonstratorFormalizationRun,
    release: FormalLogicRelease,
    *,
    formalism: Literal["asp", "prolog"],
) -> str:
    return (
        "\n".join(
            (
                "%",
                "% RULER accepted resource-portfolio formal knowledge base.",
                "% lifecycle: accepted",
                "% activation-status: active",
                "% acceptance-status: accepted",
                "% solver-use-permitted: true",
                "% portfolio-optimization-authority: false",
                "% authority: automatic_deterministic_validation",
                f"% formalism: {formalism}",
                f"% source-artifact: {run.request.artifact_id}",
                f"% source-artifact-sha256: {run.source_digest}",
                f"% typed-ir-sha256: {run.candidate.logical_program.sha256()}",
                f"% formalization-run-sha256: {run.run_digest}",
                f"% formal-logic-release: {release.release_id}",
                "%",
            )
        )
        + "\n"
    )


def _commented_program_text(
    run: DemonstratorFormalizationRun,
    compiled_text: str,
) -> str:
    """Attach authenticated natural-language comments to every compiled statement."""

    spans = {
        span.span_id: " ".join(span.exact_text.split())
        for span in run.candidate.semantic_basis.spans
    }
    rendered = compiled_text
    for statement in run.candidate.logical_program.statements:
        marker = f"% statement: {statement.statement_id}"
        if rendered.count(marker) != 1:
            raise ValueError(
                f"compiled KB does not identify statement exactly once: {statement.statement_id}"
            )
        source_span_ids = tuple(reference.span_id for reference in statement.provenance)
        missing = tuple(span_id for span_id in source_span_ids if span_id not in spans)
        if missing:
            raise ValueError(
                f"compiled KB statement has unavailable source spans: {statement.statement_id}"
            )
        source_text = " | ".join(spans[span_id] for span_id in source_span_ids)
        statement_kind = "fact" if statement.modality.value == "fact" else "rule"
        comments = f"% formal-kind: {statement_kind}\n% natural-language: {source_text}"
        rendered = rendered.replace(marker, f"{marker}\n{comments}", 1)
    return rendered


def build_approved_formal_kb_export(
    run: DemonstratorFormalizationRun,
) -> tuple[AcceptedFormalKBReceipt, FormalLogicRelease, dict[str, str]]:
    """Build a fully validated accepted release; unresolved findings fail closed."""

    assessment = assess_formal_kb_acceptance(run)
    assessment.require_promotable()
    program = run.candidate.logical_program
    registry = run.request.predicate_registry
    expected_claims = tuple(sorted(run.expected_claim_coverage, key=lambda item: item.claim_id))
    if run.kb_profile == "expanded" and (
        len(expected_claims) != 43 or len(program.statements) != 43
    ):
        raise ValueError("expanded accepted KB requires exact 43-claim/43-statement closure")
    expected_elements = {
        element_id for claim in expected_claims for element_id in claim.candidate_element_ids
    }
    for claim in expected_claims:
        if not any(
            set(statement.source_assertion_ids) & set(claim.candidate_element_ids)
            for statement in program.statements
        ):
            raise ValueError(f"accepted claim has no approved logical statement: {claim.claim_id}")
    for statement in program.statements:
        if not set(statement.source_assertion_ids) & expected_elements:
            raise ValueError(
                f"approved statement is outside expected claim closure: {statement.statement_id}"
            )
    asp = compile_asp(program, registry)
    prolog = compile_prolog(program, registry)
    validators = tuple(
        ValidatorEvidence.create(
            validator_id=gate,
            validator_version=_VALIDATOR_VERSIONS[gate],
            evaluated_ir_sha256=program.sha256(),
            passed=True,
        )
        for gate in _GATES
    )
    statement_ids = tuple(item.statement_id for item in assessment.statements)
    decision = FormalReviewDecision.create(
        decision_id="automatic-deterministic-acceptance:v1",
        reviewer_id="accountable-agent:ruler-formal-kb-validator",
        decision="approved",
        logical_unit_ids=statement_ids,
        rationale=(
            "Every logical unit passed static semantics, Clingo execution, "
            "SWI-Prolog loading, and the applicable ASP/Prolog cross-check."
        ),
        # A logical epoch keeps identical inputs byte-for-byte reproducible.  This is
        # evidence ordering metadata, not a claim about wall-clock execution time.
        decided_at=datetime(1970, 1, 1, tzinfo=UTC),
    )
    source_versions = {
        reference.source_version
        for statement in program.statements
        for reference in statement.provenance
    }
    release = build_formal_logic_release(
        program,
        asp,
        prolog,
        source_version_hashes={version: run.source_digest for version in source_versions},
        validators=validators,
        review_decisions=(decision,),
    )
    texts = {
        ACCEPTED_ASP_FILENAME: _accepted_header(run, release, formalism="asp")
        + _commented_program_text(run, asp.text),
        ACCEPTED_PROLOG_FILENAME: _accepted_header(run, release, formalism="prolog")
        + _commented_program_text(run, prolog.text),
    }
    artifacts = (
        AcceptedFormalKBArtifact(
            formalism="asp",
            filename=ACCEPTED_ASP_FILENAME,
            media_type="text/x-asp",
            program_id=asp.program_id,
            compiler_version=asp.compiler_version,
            compiler_output_sha256=asp.sha256,
            content_sha256=_sha256_text(texts[ACCEPTED_ASP_FILENAME]),
        ),
        AcceptedFormalKBArtifact(
            formalism="prolog",
            filename=ACCEPTED_PROLOG_FILENAME,
            media_type="text/x-prolog",
            program_id=prolog.program_id,
            compiler_version=prolog.compiler_version,
            compiler_output_sha256=prolog.sha256,
            content_sha256=_sha256_text(texts[ACCEPTED_PROLOG_FILENAME]),
        ),
    )
    payload = {
        "source_artifact_id": run.request.artifact_id,
        "source_artifact_sha256": run.source_digest,
        "formalization_run_sha256": run.run_digest,
        "ir_sha256": program.sha256(),
        "approved_statement_ids": statement_ids,
        "accepted_claim_ids": tuple(item.claim_id for item in expected_claims),
        "accepted_claim_count": len(expected_claims),
        "statement_assessments": assessment.statements,
        "validator_evidence": validators,
        "automatic_review_decision": decision,
        "formal_logic_release": release,
        "formal_logic_release_sha256": canonical_sha256(release.model_dump(mode="json")),
        "artifacts": artifacts,
    }
    serialized = {
        "schema_version": "resource-portfolio-accepted-formal-kb/v1",
        **{
            key: (
                [item.model_dump(mode="json") for item in value]
                if key in {"statement_assessments", "validator_evidence", "artifacts"}
                else value.model_dump(mode="json")
                if hasattr(value, "model_dump")
                else value
            )
            for key, value in payload.items()
        },
        "lifecycle": "accepted",
        "activation_status": "active",
        "acceptance_status": "accepted",
        "solver_use_permitted": True,
        "portfolio_optimization_authority": False,
        "authority": "automatic_deterministic_validation",
    }
    receipt = AcceptedFormalKBReceipt(**payload, receipt_sha256=stable_hash(serialized))
    return receipt, release, texts


def write_approved_formal_kb(
    run: DemonstratorFormalizationRun, output_dir: Path
) -> AcceptedFormalKBReceipt:
    """Write accepted executable artifacts, release, and receipt, then reverify."""

    receipt, release, texts = build_approved_formal_kb_export(run)
    for artifact in receipt.artifacts:
        write_text(output_dir / artifact.filename, texts[artifact.filename])
    write_yaml(output_dir / FORMAL_LOGIC_RELEASE_FILENAME, release.model_dump(mode="json"))
    write_yaml(output_dir / ACCEPTANCE_RECEIPT_FILENAME, receipt.model_dump(mode="json"))
    verify_approved_formal_kb(run, output_dir, receipt)
    return receipt


def verify_approved_formal_kb(
    run: DemonstratorFormalizationRun,
    output_dir: Path,
    receipt: AcceptedFormalKBReceipt,
) -> None:
    """Require byte-identical regeneration and immutable release/receipt closure."""

    expected, release, texts = build_approved_formal_kb_export(run)
    if receipt != expected:
        raise ValueError("accepted formal KB receipt differs from deterministic regeneration")
    for artifact in receipt.artifacts:
        path = output_dir / artifact.filename
        if not path.is_file() or path.read_text(encoding="utf-8") != texts[artifact.filename]:
            raise ValueError(f"accepted formal KB artifact differs from IR: {artifact.filename}")
        if _sha256_text(path.read_text(encoding="utf-8")) != artifact.content_sha256:
            raise ValueError(f"accepted formal KB artifact digest mismatch: {artifact.filename}")
    # YAML comments and whitespace do not affect parsed models, but they do affect an
    # immutable release artifact.  Regenerate through the canonical writer and compare
    # exact UTF-8 text so even semantically inert edits are detected.
    metadata = {
        FORMAL_LOGIC_RELEASE_FILENAME: release.model_dump(mode="json"),
        ACCEPTANCE_RECEIPT_FILENAME: expected.model_dump(mode="json"),
    }
    with TemporaryDirectory(prefix="ruler-accepted-metadata-") as temporary:
        expected_dir = Path(temporary)
        for filename, payload in metadata.items():
            expected_path = expected_dir / filename
            write_yaml(expected_path, payload)
            observed_path = output_dir / filename
            if (
                not observed_path.is_file()
                or observed_path.read_bytes() != expected_path.read_bytes()
            ):
                raise ValueError(
                    f"accepted formal KB metadata differs from regeneration: {filename}"
                )


__all__ = [
    "ACCEPTANCE_RECEIPT_FILENAME",
    "ACCEPTED_ASP_FILENAME",
    "ACCEPTED_PROLOG_FILENAME",
    "FORMAL_LOGIC_RELEASE_FILENAME",
    "AcceptedFormalKBArtifact",
    "AcceptedFormalKBReceipt",
    "FormalKBAcceptanceAssessment",
    "FormalKBAcceptanceFinding",
    "StatementAcceptanceAssessment",
    "assess_formal_kb_acceptance",
    "build_approved_formal_kb_export",
    "candidate_acceptance_findings",
    "verify_approved_formal_kb",
    "write_approved_formal_kb",
]
