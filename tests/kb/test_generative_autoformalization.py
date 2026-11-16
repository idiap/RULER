# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Contract and opt-in live tests for source-locked autoformalization."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from ruler.kb.formalization import PredicateRegistry, PredicateSignature, ValueType, WorldAssumption
from ruler.kb.generative_autoformalization import (
    AutoformalizationDraft,
    AutoformalizationRequest,
    CodexExecTransport,
    parse_autoformalization_candidate,
)
from ruler.kb.logical_ir import Atom, Constant, IRStatement, Modality
from ruler.kb.prolog_compiler import ConclusionExpectation, crosscheck_asp_prolog

SOURCE = (
    "If the customer reports the outage within 48 hours and provides a diagnostic log, "
    "the provider must issue a service credit up to CHF 2,500. "
    "However, no reimbursement is due when the vehicle was left unlocked."
)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request() -> AutoformalizationRequest:
    allowed = (
        "theft_reported_within_48_hours",
        "replacement_cost_reimbursable",
        "vehicle_left_unlocked",
    )
    return AutoformalizationRequest(
        request_id="request-theft-001",
        artifact_id="policy-theft-2026",
        artifact_sha256=_sha(SOURCE),
        source_text=SOURCE,
        source_version="2026-04-01",
        context_id="motor-theft-benefit",
        domain_id="technical_support",
        allowed_predicates=allowed,
        predicate_registry=PredicateRegistry(
            signatures=tuple(
                PredicateSignature(
                    name=name,
                    argument_names=("claim",),
                    argument_types=(ValueType.CLAIM_ID,),
                    family="autoformalization-test",
                    world_assumption=WorldAssumption.OPEN,
                )
                for name in allowed
            )
        ),
        target_formalism="asp",
    )


def _draft() -> dict:
    first = SOURCE.index("If")
    first_end = SOURCE.index(". ") + 1
    exception_start = SOURCE.index("However")
    span_one = SOURCE[first:first_end]
    span_two = SOURCE[exception_start:]
    variable_claim = {"kind": "variable", "name": "Claim", "value_type": "claim_id"}
    return {
        "request_id": "request-theft-001",
        "semantic_basis": {
            "basis_id": "basis-theft-001",
            "context_id": "motor-theft-benefit",
            "spans": [
                {
                    "span_id": "span-grant",
                    "artifact_id": "policy-theft-2026",
                    "artifact_sha256": _sha(SOURCE),
                    "exact_text": span_one,
                    "start_char": first,
                    "end_char": first_end,
                },
                {
                    "span_id": "span-exception",
                    "artifact_id": "policy-theft-2026",
                    "artifact_sha256": _sha(SOURCE),
                    "exact_text": span_two,
                    "start_char": exception_start,
                    "end_char": len(SOURCE),
                },
            ],
            "elements": [
                {
                    "element_id": "e-report-timely",
                    "kind": "proposition",
                    "predicate": "theft_reported_within_48_hours",
                    "source_span_ids": ["span-grant"],
                },
                {
                    "element_id": "e-reimburse",
                    "kind": "proposition",
                    "predicate": "replacement_cost_reimbursable",
                    "modality": "obligatory",
                    "source_span_ids": ["span-grant"],
                },
                {
                    "element_id": "e-unlocked-exception",
                    "kind": "exception",
                    "predicate": "vehicle_left_unlocked",
                    "polarity": "negative",
                    "connective": "unless",
                    "source_span_ids": ["span-exception"],
                },
            ],
            "commitment_status": "candidate_uncommitted",
        },
        "logical_program": {
            "program_id": "candidate-theft-001",
            "version": "candidate-1",
            "statements": [
                {
                    "statement_id": "rule-reimburse",
                    "modality": "implication",
                    "head": {
                        "predicate": "replacement_cost_reimbursable",
                        "arguments": [variable_claim],
                    },
                    "body": {
                        "kind": "atom",
                        "atom": {
                            "predicate": "theft_reported_within_48_hours",
                            "arguments": [variable_claim],
                        },
                    },
                    "source_assertion_ids": ["e-report-timely", "e-reimburse"],
                    "provenance": [
                        {
                            "document_id": "policy-theft-2026",
                            "source_version": "2026-04-01",
                            "section_id": "theft-benefit",
                            "span_id": "span-grant",
                            "span_sha256": _sha(span_one),
                        }
                    ],
                },
                {
                    "statement_id": "rule-unlocked-exception",
                    "modality": "exclusion",
                    "head": {
                        "predicate": "replacement_cost_reimbursable",
                        "arguments": [variable_claim],
                        "classical_negation": True,
                    },
                    "body": {
                        "kind": "atom",
                        "atom": {
                            "predicate": "vehicle_left_unlocked",
                            "arguments": [variable_claim],
                        },
                    },
                    "source_assertion_ids": ["e-unlocked-exception"],
                    "provenance": [
                        {
                            "document_id": "policy-theft-2026",
                            "source_version": "2026-04-01",
                            "section_id": "theft-benefit",
                            "span_id": "span-exception",
                            "span_sha256": _sha(span_two),
                        }
                    ],
                },
            ],
            "show": [{"predicate": "replacement_cost_reimbursable", "arity": 1}],
            "entrypoint_predicates": ["replacement_cost_reimbursable"],
        },
        "dimensions": [
            {
                "dimension": dimension,
                "disposition": "represented",
                "explanation": "Represented explicitly in candidate IR.",
                "query_affecting": True,
            }
            for dimension in ("actors", "modality", "polarity", "connectives", "exceptions")
        ],
        "represented_element_ids": ["e-report-timely", "e-reimburse", "e-unlocked-exception"],
        "symbol_mapping": {
            "e-report-timely": "theft_reported_within_48_hours/1",
            "e-reimburse": "replacement_cost_reimbursable/1",
            "e-unlocked-exception": "vehicle_left_unlocked/1",
        },
        "uncertainties": [
            "The source does not define what qualifies as reasonable replacement costs."
        ],
    }


def test_realistic_candidate_is_source_bound_typed_and_always_blocked() -> None:
    request = _request()
    candidate = parse_autoformalization_candidate(
        request, _draft(), provider="direct-contract-input", model="not-invoked"
    )

    assert candidate.lifecycle == "candidate_uncommitted"
    assert candidate.projection.activation_status == "blocked"
    assert candidate.projection.formalization_units_digest.startswith("sha256:")
    assert all(element.formalization_unit_ids for element in candidate.semantic_basis.elements)
    assert {
        statement.statement_id: (
            statement.deontic_operator.value if statement.deontic_operator else None
        )
        for statement in candidate.logical_program.statements
    } == {
        "rule-reimburse": "obligation",
        "rule-unlocked-exception": "exception",
    }
    assert candidate.projection.semantic_basis_digest.startswith("sha256:")
    assert candidate.projection.program_digest == candidate.logical_program.sha256()
    assert candidate.logical_program.statements[1].head.classical_negation is True
    assert "reasonable replacement costs" in candidate.uncertainties[0]
    assert candidate.receipt.request_sha256.startswith("sha256:")
    assert candidate.receipt.source_artifact_sha256 == request.artifact_sha256
    assert candidate.receipt.schema_sha256.startswith("sha256:")
    assert candidate.receipt.token_budget == request.max_output_tokens
    assert candidate.receipt.terminal_status == "completed"


def test_digest_chain_binds_source_basis_units_and_logical_statements() -> None:
    baseline = parse_autoformalization_candidate(
        _request(), _draft(), provider="direct-contract-input", model="not-invoked"
    )
    basis_mutation = _draft()
    basis_mutation["semantic_basis"]["elements"][0]["value"] = "within-48-hours"
    changed_basis = parse_autoformalization_candidate(
        _request(), basis_mutation, provider="direct-contract-input", model="not-invoked"
    )
    assert (
        changed_basis.projection.semantic_basis_digest != baseline.projection.semantic_basis_digest
    )
    assert (
        changed_basis.projection.formalization_units_digest
        != baseline.projection.formalization_units_digest
    )
    assert changed_basis.projection.program_digest == baseline.projection.program_digest

    program_mutation = _draft()
    for statement in program_mutation["logical_program"]["statements"]:
        statement["head"]["arguments"][0]["name"] = "Matter"
        statement["body"]["atom"]["arguments"][0]["name"] = "Matter"
    changed_program = parse_autoformalization_candidate(
        _request(), program_mutation, provider="direct-contract-input", model="not-invoked"
    )
    assert (
        changed_program.projection.semantic_basis_digest
        == baseline.projection.semantic_basis_digest
    )
    assert changed_program.projection.program_digest != baseline.projection.program_digest
    assert (
        changed_program.projection.formalization_units_digest
        != baseline.projection.formalization_units_digest
    )


def test_materializer_preserves_typed_business_day_deadline() -> None:
    raw = _draft()
    raw["semantic_basis"]["elements"][0].update(
        {
            "kind": "temporal_relation",
            "temporal": {
                "kind": "relative_deadline",
                "anchor_event": "theft_discovered",
                "amount": 2,
                "unit": "business_days",
                "comparison": "before_or_on",
            },
        }
    )
    candidate = parse_autoformalization_candidate(
        _request(), raw, provider="direct-contract-input", model="not-invoked"
    )

    temporal = candidate.semantic_basis.elements[0].temporal
    assert temporal is not None
    assert (temporal.amount, temporal.unit, temporal.comparison) == (
        2,
        "business_days",
        "before_or_on",
    )


def test_omitted_open_texture_is_retained_as_a_typed_activation_blocker() -> None:
    raw = _draft()
    raw["semantic_basis"]["elements"].append(
        {
            "element_id": "e-reasonable",
            "kind": "proposition",
            "predicate": "replacement_cost_reimbursable",
            "modality": "open",
            "source_span_ids": ["span-grant"],
        }
    )
    raw["omitted_element_ids"] = ["e-reasonable"]
    raw["dimensions"].append(
        {
            "dimension": "quantities",
            "disposition": "open_texture",
            "explanation": "Reasonableness has no supplied operational definition.",
            "query_affecting": True,
            "element_ids": ["e-reasonable"],
        }
    )
    candidate = parse_autoformalization_candidate(
        _request(), raw, provider="direct-contract-input", model="not-invoked"
    )

    assert candidate.projection.activation_status == "blocked"
    assert {item.category for item in candidate.projection.activation_blockers} == {
        "open_texture",
        "omitted",
    }
    assert candidate.semantic_basis.elements[-1].formalization_unit_ids == (
        "unit:omitted:e-reasonable",
    )


def test_candidate_compiles_and_executes_real_symbolic_rules() -> None:
    candidate = parse_autoformalization_candidate(
        _request(), _draft(), provider="direct-contract-input", model="not-invoked"
    )
    registry = PredicateRegistry(
        signatures=tuple(
            PredicateSignature(
                name=name,
                argument_names=("claim",),
                argument_types=(ValueType.CLAIM_ID,),
                family="autoformalization-test",
                world_assumption=WorldAssumption.OPEN,
            )
            for name in _request().allowed_predicates
        )
    )
    claim = Constant(value_type=ValueType.CLAIM_ID, value="claim-1")
    scenario_fact = IRStatement(
        statement_id="scenario-theft-reported",
        modality=Modality.FACT,
        head=Atom(predicate="theft_reported_within_48_hours", arguments=(claim,)),
        source_assertion_ids=("e-report-timely",),
        provenance=candidate.logical_program.statements[0].provenance,
    )
    program = candidate.logical_program.model_copy(
        update={"statements": (*candidate.logical_program.statements, scenario_fact)}
    )
    report = crosscheck_asp_prolog(
        program,
        (
            ConclusionExpectation(
                expectation_id="timely-theft-is-reimbursable",
                atom=Atom(predicate="replacement_cost_reimbursable", arguments=(claim,)),
                expected=True,
            ),
        ),
        registry,
    )

    assert report.equivalent
    assert report.checks[0].asp_observed is True
    assert report.checks[0].prolog_observed is True


def test_parser_rejects_model_citation_with_correct_text_at_wrong_offset() -> None:
    raw = _draft()
    raw["semantic_basis"]["spans"][0]["start_char"] += 1
    raw["semantic_basis"]["spans"][0]["end_char"] += 1

    with pytest.raises(ValueError, match="exact text does not match"):
        parse_autoformalization_candidate(
            _request(), raw, provider="direct-contract-input", model="not-invoked"
        )


def test_parser_rejects_logic_that_skips_its_semantic_evidence() -> None:
    raw = _draft()
    raw["logical_program"]["statements"][0]["source_assertion_ids"] = ["e-report-timely"]

    with pytest.raises(ValueError, match="exactly cover every represented"):
        parse_autoformalization_candidate(
            _request(), raw, provider="direct-contract-input", model="not-invoked"
        )


def test_parser_rejects_predicate_outside_bound_domain_vocabulary() -> None:
    raw = _draft()
    raw["logical_program"]["statements"][0]["head"]["predicate"] = "invented_approval"

    with pytest.raises(ValueError, match="outside the domain vocabulary"):
        parse_autoformalization_candidate(
            _request(), raw, provider="direct-contract-input", model="not-invoked"
        )


def test_codex_command_is_shell_free_ephemeral_and_tool_disabled(tmp_path: Path) -> None:
    transport = CodexExecTransport(model="gpt-test")
    command = transport.command(
        root=tmp_path,
        schema_path=tmp_path / "schema.json",
        output_path=tmp_path / "candidate.json",
    )

    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "shell_tool" in command
    assert command[-1] == "-"
    assert not any(token in command for token in ("sh", "bash", "zsh"))


def test_model_output_schema_is_strict_and_has_no_approval_field() -> None:
    schema = AutoformalizationDraft.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "lifecycle" not in schema["properties"]
    with pytest.raises(ValidationError):
        AutoformalizationDraft.model_validate({**_draft(), "approved": True})
