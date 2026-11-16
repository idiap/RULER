# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""End-to-end compilation and evaluation of a domain-neutral rigorous document."""

from __future__ import annotations

from ruler.domains.regulatory import (
    REGULATORY_DOMAIN_PACK,
    REGULATORY_RELEASE_ID,
    build_regulatory_program,
    regulatory_expected_rules,
    regulatory_registry,
)
from ruler.domains.base import validate_domain_pack
from ruler.evaluation import (
    EvaluationPipeline,
    EvaluationRequest,
    EvaluationStatus,
    evaluate_request,
)
from ruler.kb.formalization import ValueType
from ruler.kb.logical_ir import Atom, Constant


def _fact(predicate: str, subject: str, value: int | None = None) -> Atom:
    arguments = [Constant(value_type=ValueType.SUBJECT, value=subject)]
    if value is not None:
        arguments.append(Constant(value_type=ValueType.COUNT, value=value))
    return Atom(predicate=predicate, arguments=tuple(arguments))


def _evaluate(case_id: str, *facts: Atom):
    return evaluate_request(
        build_regulatory_program(),
        regulatory_registry(),
        EvaluationRequest(
            request_id=f"request:{case_id}",
            case_id=case_id,
            release_id=REGULATORY_RELEASE_ID,
            facts=facts,
            expected_rules=regulatory_expected_rules(),
        ),
    )


def _statuses(packet) -> dict[str, EvaluationStatus]:
    return {item.rule_id: item.status for item in packet.consequences}


def test_obligation_numeric_and_temporal_boundary_are_satisfied() -> None:
    packet = _evaluate(
        "boundary",
        _fact("in_scope", "operator-a"),
        _fact("submitted_notice", "operator-a"),
        _fact("within_deadline", "operator-a"),
        _fact("regulated_quantity", "operator-a", 10),
    )
    statuses = _statuses(packet)
    assert statuses["rg_notice_obligation"] == EvaluationStatus.SATISFIED
    assert statuses["rg_quantity_limit"] == EvaluationStatus.SATISFIED
    assert statuses["rg_notice_deadline"] == EvaluationStatus.SATISFIED
    assert statuses["rg_action_prohibition"] == EvaluationStatus.UNKNOWN


def test_violations_and_prohibition_exception_precedence() -> None:
    violations = _evaluate(
        "violated",
        _fact("in_scope", "operator-b"),
        _fact("notice_missing", "operator-b"),
        _fact("after_deadline", "operator-b"),
        _fact("regulated_quantity", "operator-b", 11),
        _fact("restricted_action", "operator-b"),
    )
    assert set(_statuses(violations).values()) == {EvaluationStatus.VIOLATED}

    exception = _evaluate(
        "exception",
        _fact("in_scope", "operator-c"),
        _fact("restricted_action", "operator-c"),
        _fact("authorized_exception", "operator-c"),
    )
    assert _statuses(exception)["rg_action_prohibition"] == EvaluationStatus.EXCEPTION


def test_inapplicable_unknown_evidence_release_and_replay() -> None:
    inapplicable = _evaluate("outside", _fact("out_of_scope", "operator-d"))
    assert set(_statuses(inapplicable).values()) == {EvaluationStatus.INAPPLICABLE}

    unknown = _evaluate("unknown", _fact("in_scope", "operator-e"))
    assert set(_statuses(unknown).values()) == {EvaluationStatus.UNKNOWN}
    assert all(item.evidence for item in unknown.consequences)
    assert all(item.release_id == REGULATORY_RELEASE_ID for item in unknown.consequences)
    assert unknown.sha256() == _evaluate("unknown", _fact("in_scope", "operator-e")).sha256()


def test_regulatory_contract_has_no_retired_application_placeholders() -> None:
    validate_domain_pack(REGULATORY_DOMAIN_PACK)
    serialized = (
        build_regulatory_program().model_dump_json()
        + " ".join(item.model_dump_json() for item in regulatory_expected_rules())
    ).lower()
    for forbidden in ("provider", "product", "customer", "premium", "vehicle", "coverage"):
        assert forbidden not in serialized


def test_counterfactual_probe_reports_only_changed_rules() -> None:
    request = EvaluationRequest(
        request_id="request:probe",
        case_id="probe",
        release_id=REGULATORY_RELEASE_ID,
        facts=(_fact("in_scope", "operator-f"), _fact("regulated_quantity", "operator-f", 10)),
        expected_rules=regulatory_expected_rules(),
    )
    result = EvaluationPipeline(build_regulatory_program(), regulatory_registry()).counterfactual(
        request,
        probe_id="raise-quantity",
        facts=(_fact("in_scope", "operator-f"), _fact("regulated_quantity", "operator-f", 11)),
    )
    assert [
        (item.rule_id, item.baseline_status, item.counterfactual_status) for item in result.changes
    ] == [("rg_quantity_limit", EvaluationStatus.SATISFIED, EvaluationStatus.VIOLATED)]
