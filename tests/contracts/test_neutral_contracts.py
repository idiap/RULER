# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ruler.contracts import (
    AuthoritativeSource,
    CaseContext,
    EvaluationRequest,
    EvidenceGrounding,
    EvidenceSpan,
    FormalRule,
    NormativeUnit,
)
from ruler.contracts.common import NormativeModality, ReviewStatus
from ruler.contracts.rules import RuleValidation

HASH = "sha256:" + "a" * 64


def test_regulatory_models_require_no_retired_application_placeholders() -> None:
    source = AuthoritativeSource(
        source_id="reg-1",
        uri="https://authority.example/regulation",
        document_kind="regulation",
        issuing_authority="Example Authority",
        language="en",
        content_sha256=HASH,
        extraction_quality=1.0,
    )
    span = EvidenceSpan(
        span_id="span-1",
        source_id=source.source_id,
        source_version="2026-01",
        text_sha256=HASH,
        page_start=1,
        page_end=1,
        character_start=10,
        character_end=40,
    )
    unit = NormativeUnit(
        unit_id="article-1",
        source_id=source.source_id,
        modality="obligation",
        subject="operator",
        evidence_span_ids=(span.span_id,),
        review_status="approved",
        language="en",
    )
    assert unit.modality is NormativeModality.OBLIGATION
    assert AuthoritativeSource.model_validate_json(source.model_dump_json()) == source


def test_contracts_forbid_extra_fields_and_inexact_provenance() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        CaseContext(context_id="c", domain_id="regulatory", provider="fake")
    with pytest.raises(ValidationError, match="exact page"):
        EvidenceSpan(span_id="s", source_id="d", source_version="v", text_sha256=HASH)
    with pytest.raises(ValidationError, match="64 lowercase"):
        AuthoritativeSource(
            source_id="d",
            uri="x",
            document_kind="regulation",
            language="en",
            content_sha256="sha256:abc",
            extraction_quality=1,
        )


def test_approved_rule_requires_grounding_compilation_and_fidelity() -> None:
    grounding = EvidenceGrounding(
        grounding_id="g",
        normative_unit_ids=("u",),
        evidence_span_ids=("s",),
        entailment_reviewed=True,
        reviewed_by="reviewer",
    )
    validation = RuleValidation(
        schema_valid=True,
        compiles=True,
        symbolic_consistent=True,
        source_entails_rule=True,
        rule_entails_source=True,
        reviewed_by="reviewer",
        review_status=ReviewStatus.APPROVED,
    )
    with pytest.raises(ValidationError, match="compiled target"):
        FormalRule(
            rule_id="r",
            rule_version="2",
            modality="obligation",
            consequence="record(x)",
            grounding=grounding,
            validation=validation,
        )


def test_evaluation_request_domain_must_match_case() -> None:
    with pytest.raises(ValidationError, match="domain_id must match"):
        EvaluationRequest(
            request_id="q",
            requested_at=datetime.now(UTC),
            requested_by="tester",
            domain_id="regulatory",
            corpus_id="c",
            release_id="r",
            context=CaseContext(context_id="ctx", domain_id="retired_application"),
        )
