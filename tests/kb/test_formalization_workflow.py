# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Cross-domain tests for corpus-neutral formalization orchestration."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from ruler.domains.regulatory.pack import REGULATORY_DOMAIN_PACK
from ruler.kb.formalization import SourceSpanRef, ValueType
from ruler.kb.formalization_release import FormalReviewDecision, ValidatorEvidence
from ruler.kb.formalization_workflow import (
    FormalizationDocument,
    FormalizationSpan,
    FormalizationUnit,
    FormalizationWorkflowConfig,
    FormalizationWorkflowRequest,
    run_formalization_workflow,
)
from ruler.kb.logical_ir import Atom, Constant, IRStatement, Modality


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _statement(
    unit_id: str,
    span: FormalizationSpan,
    predicate: str,
    arguments: tuple[Constant, ...],
    *,
    span_hash: str | None = None,
) -> IRStatement:
    return IRStatement(
        statement_id=unit_id,
        modality=Modality.FACT,
        head=Atom(predicate=predicate, arguments=arguments),
        source_assertion_ids=(f"assertion:{unit_id}",),
        provenance=(
            SourceSpanRef(
                document_id=span.document_id,
                source_version=span.source_version,
                section_id=span.section_id,
                span_id=span.span_id,
                span_sha256=span_hash or span.span_sha256,
            ),
        ),
    )


def _request(
    *,
    domain_id: str,
    corpus_id: str,
    document_kind: str,
    source_language: str,
    target_language: str,
    unit_type: str,
    materiality: str,
    predicate: str,
    arguments: tuple[Constant, ...],
    mixed_states: bool = False,
) -> FormalizationWorkflowRequest:
    source_version = f"{corpus_id}/1"
    texts = [
        "Approved exact provision.",
        "Candidate provision.",
        "Rejected provision.",
        "Stale provision.",
    ]
    source_text = "\n".join(texts)
    spans = tuple(
        FormalizationSpan(
            span_id=f"span-{index}",
            document_id=f"document-{corpus_id}",
            source_version=source_version,
            section_id=f"section-{index}",
            text=text,
            start_char=source_text.index(text),
            end_char=source_text.index(text) + len(text),
            span_sha256=_hash(text),
        )
        for index, text in enumerate(texts, start=1)
    )
    states = ("approved", "candidate", "rejected", "stale") if mixed_states else ("approved",)
    units = []
    for index, state in enumerate(states):
        span = spans[index]
        unit_id = f"unit-{state}"
        units.append(
            FormalizationUnit(
                unit_id=unit_id,
                span_id=span.span_id,
                unit_type=unit_type,
                materiality_role=materiality,
                state=state,
                controlled_text=f"Controlled {state} unit.",
                predicate_candidates=(predicate,),
                statement=_statement(
                    unit_id,
                    span,
                    predicate,
                    arguments,
                    span_hash=("sha256:" + "0" * 64) if state == "stale" else None,
                ),
                rationale=(
                    (f"Unit is intentionally {state}.") if state in {"rejected", "stale"} else None
                ),
            )
        )
    return FormalizationWorkflowRequest(
        config=FormalizationWorkflowConfig(
            domain_id=domain_id,
            corpus_id=corpus_id,
            source_language=source_language,
            target_language=target_language,
            program_id=f"program-{corpus_id}",
            program_version="1",
        ),
        documents=(
            FormalizationDocument(
                document_id=f"document-{corpus_id}",
                document_kind=document_kind,
                source_version=source_version,
                source_sha256=_hash(source_text),
                source_text=source_text,
                language=source_language,
            ),
        ),
        spans=spans,
        units=tuple(units),
    )


def test_document_digest_and_span_offsets_authenticate_actual_source_bytes() -> None:
    request = _request(
        domain_id="regulatory",
        corpus_id="byte-identity",
        document_kind="regulation",
        source_language="en",
        target_language="en",
        unit_type="scope",
        materiality="applicability",
        predicate="in_scope",
        arguments=(Constant(value_type=ValueType.SUBJECT, value="operator-1"),),
    )
    document = request.documents[0]

    with pytest.raises(ValueError, match="authenticate supplied document bytes"):
        FormalizationDocument.model_validate(
            {**document.model_dump(), "source_text": document.source_text + " altered"}
        )

    span = request.spans[0]
    shifted = span.model_copy(
        update={"start_char": span.start_char + 1, "end_char": span.end_char + 1}
    )
    with pytest.raises(ValueError, match="exact text does not match authenticated"):
        run_formalization_workflow(
            REGULATORY_DOMAIN_PACK, request.model_copy(update={"spans": (shifted,)})
        )


def test_regulatory_workflow_blocks_candidate_rejected_and_stale_units_from_release() -> None:
    subject = Constant(value_type=ValueType.SUBJECT, value="operator-1")
    request = _request(
        domain_id="regulatory",
        corpus_id="regulatory-proof",
        document_kind="regulation",
        source_language="en",
        target_language="en",
        unit_type="scope",
        materiality="applicability",
        predicate="in_scope",
        arguments=(subject,),
        mixed_states=True,
    )
    preview = run_formalization_workflow(REGULATORY_DOMAIN_PACK, request)

    assert preview.active_unit_ids == ("unit-approved",)
    assert preview.blocked_unit_ids == ("unit-candidate", "unit-rejected", "unit-stale")
    assert preview.active_program is not None
    assert {item.statement_id for item in preview.active_program.statements} == {"unit-approved"}
    stale = next(item for item in preview.dispositions if item.unit_id == "unit-stale")
    assert set(stale.reasons) == {"lifecycle_stale", "source_span_stale"}
    assert preview.release is None

    validator = ValidatorEvidence.create(
        validator_id="formal-semantics",
        validator_version="1",
        evaluated_ir_sha256=preview.active_program.sha256(),
        passed=True,
    )
    decision = FormalReviewDecision.create(
        decision_id="review:regulatory-proof",
        reviewer_id="reviewer:test",
        decision="approved",
        logical_unit_ids=("unit-approved",),
        rationale="The exact provision and typed fact were reviewed.",
        decided_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
    )
    released = run_formalization_workflow(
        REGULATORY_DOMAIN_PACK,
        request,
        validators=(validator,),
        review_decisions=(decision,),
    )

    assert released.release is not None
    assert released.release.program_id == request.config.program_id
    assert set(released.release.review_decision_hashes) == {"review:regulatory-proof"}
    assert not set(released.blocked_unit_ids) & set(released.release.review_decision_hashes)


def test_domain_pack_controls_language_taxonomy_and_executable_predicates() -> None:
    subject = Constant(value_type=ValueType.SUBJECT, value="operator-1")
    request = _request(
        domain_id="regulatory",
        corpus_id="bad-profile",
        document_kind="regulation",
        source_language="en",
        target_language="fr",
        unit_type="scope",
        materiality="applicability",
        predicate="in_scope",
        arguments=(subject,),
    )
    with pytest.raises(ValueError, match="translation contract"):
        run_formalization_workflow(REGULATORY_DOMAIN_PACK, request)

    invalid_unit = request.units[0].model_copy(
        update={"unit_type": "unsupported_unit", "predicate_candidates": ("invented",)}
    )
    valid_language = request.model_copy(
        update={
            "config": request.config.model_copy(update={"target_language": "en"}),
            "units": (invalid_unit,),
        }
    )
    with pytest.raises(ValueError, match="unknown domain unit type"):
        run_formalization_workflow(REGULATORY_DOMAIN_PACK, valid_language)


def test_all_candidate_request_has_no_active_projection_or_release() -> None:
    request = _request(
        domain_id="regulatory",
        corpus_id="candidate-only",
        document_kind="regulation",
        source_language="en",
        target_language="en",
        unit_type="scope",
        materiality="applicability",
        predicate="in_scope",
        arguments=(Constant(value_type=ValueType.SUBJECT, value="operator-1"),),
    )
    candidate = request.units[0].model_copy(update={"state": "candidate"})
    request = request.model_copy(update={"units": (candidate,)})

    result = run_formalization_workflow(REGULATORY_DOMAIN_PACK, request)

    assert result.active_program is None
    assert result.release is None
    assert result.blocked_unit_ids == (candidate.unit_id,)
