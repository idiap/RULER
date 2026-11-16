# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral regulatory snapshot rendering and injection resistance."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError
import pytest

from ruler.domains.regulatory import (
    REGULATORY_RELEASE_ID,
    build_regulatory_program,
    regulatory_expected_rules,
    regulatory_registry,
)
from ruler.evaluation import EvaluationRequest, evaluate_request
from ruler.interfaces.neutral_evaluation import (
    ConsequenceNode,
    DocumentNode,
    EvidenceNode,
    NeutralEvaluationSnapshot,
    NormativeUnitNode,
    RuleNode,
    render_neutral_evaluation,
)
from ruler.kb.formalization import ValueType
from ruler.kb.logical_ir import Atom, Constant


def _regulatory_snapshot(*, title: str = "Regulatory proof") -> NeutralEvaluationSnapshot:
    subject = Constant(value_type=ValueType.SUBJECT, value="operator-a")
    packet = evaluate_request(
        build_regulatory_program(),
        regulatory_registry(),
        EvaluationRequest(
            request_id="snapshot-request",
            case_id="snapshot-case",
            release_id=REGULATORY_RELEASE_ID,
            facts=(
                Atom(predicate="in_scope", arguments=(subject,)),
                Atom(predicate="submitted_notice", arguments=(subject,)),
                Atom(predicate="within_deadline", arguments=(subject,)),
            ),
            expected_rules=regulatory_expected_rules(),
        ),
    )
    consequence = next(
        item for item in packet.consequences if item.rule_id == "rg_notice_obligation"
    )
    evidence = tuple(
        EvidenceNode(
            evidence_id=item.span_id,
            source_id=item.document_id,
            source_version=item.source_version,
            section=item.section_id,
            span_sha256=item.span_sha256,
            locator=item.span_id,
        )
        for item in consequence.evidence
    )
    return NeutralEvaluationSnapshot(
        snapshot_id="snapshot:regulatory",
        domain_id="regulatory",
        corpus_id="regulatory-proof",
        release_id=packet.release_id,
        documents=(
            DocumentNode(
                document_id="regulatory_proof_instrument",
                title=title,
                document_kind="regulation",
                issuing_authority="Local proof authority",
                units=(
                    NormativeUnitNode(
                        unit_id="unit:RG-3",
                        title="Notice obligation",
                        modality="obligation",
                        rules=(
                            RuleNode(
                                rule_id=consequence.rule_id,
                                modality=consequence.modality,
                                consequence="Submit notice within the deadline",
                                outcomes=(
                                    ConsequenceNode(
                                        consequence_id="consequence:notice",
                                        status=consequence.status.value,
                                        effect="Notice duty is satisfied",
                                        evidence=evidence,
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def test_regulatory_snapshot_renders_complete_neutral_hierarchy() -> None:
    snapshot = _regulatory_snapshot()
    rendered = render_neutral_evaluation(snapshot)
    for marker in (
        'class="document"',
        'class="unit"',
        'class="rule"',
        'class="consequence"',
        "Exact evidence",
        REGULATORY_RELEASE_ID,
    ):
        assert marker in rendered
    assert "provider" not in rendered.lower()
    assert "customer" not in rendered.lower()


def test_snapshot_renderer_escapes_markup_and_script_breakout() -> None:
    attack = '</script><script data-attack="yes">alert(1)</script>'
    rendered = render_neutral_evaluation(_regulatory_snapshot(title=attack))
    assert attack not in rendered
    assert '<script data-attack="yes">' not in rendered
    assert "&lt;/script&gt;" in rendered
    assert "default-src 'none'" in rendered
    payload = re.search(
        r'<script id="evaluation-snapshot" type="application/json">(.*?)</script>',
        rendered,
        re.DOTALL,
    )
    assert payload is not None
    decoded = json.loads(payload.group(1))
    assert decoded["documents"][0]["title"] == attack


def test_consequences_cannot_render_without_exact_evidence() -> None:
    with pytest.raises(ValidationError):
        ConsequenceNode(
            consequence_id="unsafe",
            status="satisfied",
            effect="unsupported",
            evidence=(),
        )


def test_snapshot_rejects_evidence_from_a_different_document() -> None:
    snapshot = _regulatory_snapshot()
    document = snapshot.documents[0]
    unit = document.units[0]
    rule = unit.rules[0]
    outcome = rule.outcomes[0]
    foreign = outcome.evidence[0].model_copy(update={"source_id": "other-document"})
    bad_outcome = outcome.model_copy(update={"evidence": (foreign,)})
    bad_rule = rule.model_copy(update={"outcomes": (bad_outcome,)})
    bad_unit = unit.model_copy(update={"rules": (bad_rule,)})
    bad_document = document.model_copy(update={"units": (bad_unit,)})
    with pytest.raises(ValidationError, match="outside document"):
        NeutralEvaluationSnapshot.model_validate(
            snapshot.model_copy(update={"documents": (bad_document,)}).model_dump()
        )
