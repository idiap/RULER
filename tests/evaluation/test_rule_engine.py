# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-neutral rule engine boundaries."""

from __future__ import annotations

import pytest

from ruler.kb.formalization import (
    PredicateRegistry,
    PredicateSignature,
    SourceSpanRef,
    ValueType,
    WorldAssumption,
)
from ruler.kb.logical_ir import (
    Atom,
    Constant,
    IRStatement,
    LogicalExpression,
    LogicalProgram,
    Modality,
    ShowDirective,
    Variable,
)
from ruler.kb.rule_engine import (
    RuleEngine,
    RuleEngineError,
    RuleModuleDescriptor,
    run_rule_scenario,
)

SPAN = SourceSpanRef(
    document_id="doc",
    source_version="v1",
    section_id="one",
    span_id="span-one",
    span_sha256="sha256:" + "1" * 64,
)


def _registry() -> PredicateRegistry:
    def signature(name: str) -> PredicateSignature:
        return PredicateSignature(
            name=name,
            argument_names=("subject",),
            argument_types=(ValueType.SUBJECT,),
            family="test",
            world_assumption=WorldAssumption.OPEN,
            units=(None,),
            value_domains=(None,),
        )

    return PredicateRegistry(signatures=(signature("input_fact"), signature("derived_fact")))


def test_engine_executes_any_registry_validated_logical_program() -> None:
    subject = Variable(name="Subject", value_type=ValueType.SUBJECT)
    program = LogicalProgram(
        program_id="generic",
        version="1",
        statements=(
            IRStatement(
                statement_id="derive",
                modality=Modality.IMPLICATION,
                head=Atom(predicate="derived_fact", arguments=(subject,)),
                body=LogicalExpression.from_atom(
                    Atom(predicate="input_fact", arguments=(subject,))
                ),
                source_assertion_ids=("assertion",),
                provenance=(SPAN,),
            ),
        ),
        show=(ShowDirective(predicate="derived_fact", arity=1),),
    )
    fact = Atom(
        predicate="input_fact",
        arguments=(Constant(value_type=ValueType.SUBJECT, value="subject-a"),),
    )
    result = run_rule_scenario(program, (fact,), registry=_registry())
    assert result.atoms == frozenset({'derived_fact("subject-a")'})


def test_engine_rejects_undeclared_output_and_ambiguous_projection() -> None:
    hidden = RuleEngine(
        RuleModuleDescriptor(
            module_id="bad-output",
            source="invented(a). #show invented/1.",
            shown_predicates=frozenset({"approved"}),
        )
    )
    with pytest.raises(RuleEngineError, match="undeclared shown predicates"):
        hidden.run_source()

    ambiguous = RuleEngine(
        RuleModuleDescriptor(
            module_id="ambiguous",
            source="1 { selected(a); selected(b) } 1. #show selected/1.",
            shown_predicates=frozenset({"selected"}),
        )
    )
    with pytest.raises(RuleEngineError, match="ambiguous shown answer sets"):
        ambiguous.run_source()


def test_typed_facts_fail_closed_on_unknown_predicate() -> None:
    engine = RuleEngine(
        RuleModuleDescriptor(
            module_id="empty",
            source="#show derived_fact/1.",
            shown_predicates=frozenset({"derived_fact"}),
        )
    )
    unknown = Atom(
        predicate="invented",
        arguments=(Constant(value_type=ValueType.SUBJECT, value="subject-a"),),
    )
    with pytest.raises(ValueError, match="undeclared or unapproved predicate"):
        engine.run_atoms((unknown,), registry=_registry())
