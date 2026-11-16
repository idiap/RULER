# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Executable, candidate-only formal KB export for the portfolio demonstrator."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ruler.applications.resource_portfolio.demonstrator_formalization import (
    DemonstratorFormalizationRun,
)
from ruler.contracts.common import StrictContract, validate_sha256
from ruler.io import stable_hash, write_text
from ruler.kb.asp_compiler import CompiledASP, compile_asp
from ruler.kb.formalization_validation import validate_static_semantics
from ruler.kb.prolog_compiler import CompiledProlog, compile_prolog

ASP_FILENAME = "candidate_kb.lp"
PROLOG_FILENAME = "candidate_kb.pl"


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class CandidateFormalKBArtifact(StrictContract):
    """One executable rendering of the activation-blocked candidate IR."""

    formalism: Literal["asp", "prolog"]
    filename: Literal["candidate_kb.lp", "candidate_kb.pl"]
    media_type: Literal["text/x-asp", "text/x-prolog"]
    program_id: str
    compiler_version: str
    compiler_output_sha256: str
    content_sha256: str
    validation: Literal["compiler_validated_and_regeneration_bound"] = (
        "compiler_validated_and_regeneration_bound"
    )
    lifecycle: Literal["candidate_uncommitted"] = "candidate_uncommitted"
    activation_status: Literal["blocked"] = "blocked"
    solver_use_permitted: Literal[False] = False
    authority: Literal["none_candidate_artifact"] = "none_candidate_artifact"

    @model_validator(mode="after")
    def hashes_are_valid(self) -> "CandidateFormalKBArtifact":
        validate_sha256(self.compiler_output_sha256)
        validate_sha256(self.content_sha256)
        expected_filename = ASP_FILENAME if self.formalism == "asp" else PROLOG_FILENAME
        expected_media = "text/x-asp" if self.formalism == "asp" else "text/x-prolog"
        if self.filename != expected_filename or self.media_type != expected_media:
            raise ValueError("formal KB filename/media type does not match its formalism")
        return self


class CandidateFormalKBExport(StrictContract):
    """Content-bound receipt for both real formal-language candidate artifacts."""

    schema_version: Literal["resource-portfolio-candidate-formal-kb/v1"] = (
        "resource-portfolio-candidate-formal-kb/v1"
    )
    source_artifact_id: str
    source_artifact_sha256: str
    request_sha256: str
    candidate_sha256: str
    typed_ir_sha256: str
    static_semantics_sha256: str
    refinement_run_sha256: str
    formalization_run_sha256: str
    artifacts: tuple[CandidateFormalKBArtifact, CandidateFormalKBArtifact] = Field(
        min_length=2, max_length=2
    )
    lifecycle: Literal["candidate_uncommitted"] = "candidate_uncommitted"
    activation_status: Literal["blocked"] = "blocked"
    solver_use_permitted: Literal[False] = False
    authority: Literal["none_candidate_artifact"] = "none_candidate_artifact"
    export_sha256: str

    @model_validator(mode="after")
    def receipt_is_complete(self) -> "CandidateFormalKBExport":
        for digest in (
            self.source_artifact_sha256,
            self.request_sha256,
            self.candidate_sha256,
            self.typed_ir_sha256,
            self.static_semantics_sha256,
            self.refinement_run_sha256,
            self.formalization_run_sha256,
            self.export_sha256,
        ):
            validate_sha256(digest)
        if tuple(item.formalism for item in self.artifacts) != ("asp", "prolog"):
            raise ValueError("formal KB export must contain deterministic ASP then Prolog")
        expected = stable_hash(self.model_dump(mode="json", exclude={"export_sha256"}))
        if self.export_sha256 != expected:
            raise ValueError("formal KB export digest mismatch")
        return self


def _provenance_header(
    run: DemonstratorFormalizationRun,
    *,
    formalism: Literal["asp", "prolog"],
) -> str:
    candidate_sha256 = stable_hash(run.candidate.model_dump(mode="json"))
    request_sha256 = stable_hash(run.request.model_dump(mode="json"))
    lines = [
        "%",
        "% RULER resource-portfolio formal KB export.",
        "% lifecycle: candidate_uncommitted",
        "% activation-status: blocked",
        "% solver-use-permitted: false",
        "% authority: none_candidate_artifact",
        "% This artifact is executable for validation only; it is not promoted KB truth.",
        f"% formalism: {formalism}",
        f"% source-artifact: {run.request.artifact_id}",
        f"% source-artifact-sha256: {run.source_digest}",
        f"% request-sha256: {request_sha256}",
        f"% candidate-sha256: {candidate_sha256}",
        f"% typed-ir-sha256: {run.candidate.logical_program.sha256()}",
        f"% refinement-run-sha256: {run.refinement.run_sha256}",
        f"% formalization-run-sha256: {run.run_digest}",
    ]
    if formalism == "prolog":
        lines.append(
            "% formalism-authority: ASP-mirror semantics only; the candidate ASP has no solver authority"
        )
    return "\n".join(lines) + "\n%\n"


def _compile_candidate(
    run: DemonstratorFormalizationRun,
) -> tuple[CompiledASP, CompiledProlog]:
    """Lower the final refined typed IR through the canonical compilers."""

    if run.candidate.lifecycle != "candidate_uncommitted":
        raise ValueError("only an uncommitted candidate may be exported")
    if run.candidate.projection.activation_status != "blocked":
        raise ValueError("formal KB export requires an activation-blocked candidate")
    if run.solver_authority.solver_use_permitted:
        raise ValueError("formal KB export cannot grant solver authority")
    program = run.candidate.logical_program
    registry = run.request.predicate_registry
    validate_static_semantics(program, registry).require_valid()
    return compile_asp(program, registry), compile_prolog(program, registry)


def build_candidate_formal_kb_export(
    run: DemonstratorFormalizationRun,
) -> tuple[CandidateFormalKBExport, dict[str, str]]:
    """Compile the final candidate and return its typed receipt and exact file texts."""

    asp, prolog = _compile_candidate(run)
    semantic_report = validate_static_semantics(
        run.candidate.logical_program, run.request.predicate_registry
    )
    semantic_report.require_valid()
    texts = {
        ASP_FILENAME: _provenance_header(run, formalism="asp") + asp.text,
        PROLOG_FILENAME: _provenance_header(run, formalism="prolog") + prolog.text,
    }
    artifacts = (
        CandidateFormalKBArtifact(
            formalism="asp",
            filename=ASP_FILENAME,
            media_type="text/x-asp",
            program_id=asp.program_id,
            compiler_version=asp.compiler_version,
            compiler_output_sha256=asp.sha256,
            content_sha256=_sha256_text(texts[ASP_FILENAME]),
        ),
        CandidateFormalKBArtifact(
            formalism="prolog",
            filename=PROLOG_FILENAME,
            media_type="text/x-prolog",
            program_id=prolog.program_id,
            compiler_version=prolog.compiler_version,
            compiler_output_sha256=prolog.sha256,
            content_sha256=_sha256_text(texts[PROLOG_FILENAME]),
        ),
    )
    payload = {
        "source_artifact_id": run.request.artifact_id,
        "source_artifact_sha256": run.source_digest,
        "request_sha256": stable_hash(run.request.model_dump(mode="json")),
        "candidate_sha256": stable_hash(run.candidate.model_dump(mode="json")),
        "typed_ir_sha256": run.candidate.logical_program.sha256(),
        "static_semantics_sha256": stable_hash(semantic_report.model_dump(mode="json")),
        "refinement_run_sha256": run.refinement.run_sha256,
        "formalization_run_sha256": run.run_digest,
        "artifacts": artifacts,
    }
    serialized = {
        key: [item.model_dump(mode="json") for item in value] if key == "artifacts" else value
        for key, value in payload.items()
    }
    # Defaults are part of the contract and therefore part of its stable identity.
    serialized.update(
        {
            "schema_version": "resource-portfolio-candidate-formal-kb/v1",
            "lifecycle": "candidate_uncommitted",
            "activation_status": "blocked",
            "solver_use_permitted": False,
            "authority": "none_candidate_artifact",
        }
    )
    receipt = CandidateFormalKBExport(
        **payload,
        export_sha256=stable_hash(serialized),
    )
    return receipt, texts


def write_candidate_formal_kb(
    run: DemonstratorFormalizationRun,
    output_dir: Path,
) -> CandidateFormalKBExport:
    """Write executable ASP/Prolog candidates and verify their exact disk bytes."""

    receipt, texts = build_candidate_formal_kb_export(run)
    for artifact in receipt.artifacts:
        write_text(output_dir / artifact.filename, texts[artifact.filename])
    verify_candidate_formal_kb(run, output_dir, receipt)
    return receipt


def verify_candidate_formal_kb(
    run: DemonstratorFormalizationRun,
    output_dir: Path,
    receipt: CandidateFormalKBExport,
) -> None:
    """Recompile from typed IR and require byte-identical, digest-bound artifacts."""

    expected_receipt, expected_texts = build_candidate_formal_kb_export(run)
    if receipt != expected_receipt:
        raise ValueError("formal KB receipt differs from deterministic recompilation")
    for artifact in receipt.artifacts:
        path = output_dir / artifact.filename
        if not path.is_file():
            raise ValueError(f"missing formal KB artifact: {artifact.filename}")
        observed = path.read_text(encoding="utf-8")
        if observed != expected_texts[artifact.filename]:
            raise ValueError(f"formal KB artifact differs from typed IR: {artifact.filename}")
        if _sha256_text(observed) != artifact.content_sha256:
            raise ValueError(f"formal KB artifact digest mismatch: {artifact.filename}")


__all__ = [
    "ASP_FILENAME",
    "PROLOG_FILENAME",
    "CandidateFormalKBArtifact",
    "CandidateFormalKBExport",
    "build_candidate_formal_kb_export",
    "verify_candidate_formal_kb",
    "write_candidate_formal_kb",
]
