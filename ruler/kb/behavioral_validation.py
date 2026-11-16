# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Solver-backed behavioral cases and complete rule-family coverage gates."""

from __future__ import annotations

from enum import StrEnum

import clingo
from pydantic import BaseModel, ConfigDict, model_validator

from ruler.kb.asp_compiler import compile_asp, render_asp_atom
from ruler.kb.formalization import PredicateRegistry
from ruler.kb.logical_ir import Atom, LogicalProgram, Variable


class BehavioralCaseKind(StrEnum):
    """Mandatory behavioral perspectives for every rule family."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    COUNTERFACTUAL = "counterfactual"
    EXCEPTION = "exception"
    BOUNDARY = "boundary"
    CONFLICT = "conflict"


MANDATORY_CASE_KINDS = frozenset(BehavioralCaseKind)


class BehavioralCase(BaseModel):
    """Ground solver fixture linked to the logical units it exercises."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    kind: BehavioralCaseKind
    rule_family: str
    statement_ids: tuple[str, ...]
    given: tuple[Atom, ...] = ()
    expected_conclusions: tuple[Atom, ...] = ()
    expected_absences: tuple[Atom, ...] = ()
    expected_satisfiable: bool = True

    @model_validator(mode="after")
    def case_is_ground_and_linked(self) -> "BehavioralCase":
        if not self.statement_ids:
            raise ValueError("behavioral cases must link to at least one logical unit")
        atoms = self.given + self.expected_conclusions + self.expected_absences
        if any(isinstance(argument, Variable) for atom in atoms for argument in atom.arguments):
            raise ValueError("behavioral cases must use ground atoms")
        positive = {atom.key() for atom in self.expected_conclusions}
        negative = {atom.key() for atom in self.expected_absences}
        if positive & negative:
            raise ValueError("a conclusion cannot be both expected and absent")
        if self.kind == BehavioralCaseKind.POSITIVE and not self.expected_conclusions:
            raise ValueError("positive cases require an expected conclusion")
        if (
            self.kind
            in {
                BehavioralCaseKind.NEGATIVE,
                BehavioralCaseKind.COUNTERFACTUAL,
                BehavioralCaseKind.EXCEPTION,
            }
            and not self.expected_absences
        ):
            raise ValueError(f"{self.kind.value} cases require an expected absence")
        if self.kind == BehavioralCaseKind.BOUNDARY and not any(
            isinstance(argument.value, int)
            for atom in self.given
            for argument in atom.arguments
            if not isinstance(argument, Variable)
        ):
            raise ValueError("boundary cases require a typed numeric input")
        polarities: dict[str, set[bool]] = {}
        for atom in self.given:
            polarities.setdefault(atom.key(), set()).add(atom.classical_negation)
        has_explicit_conflict = any(values == {False, True} for values in polarities.values())
        if (
            self.kind == BehavioralCaseKind.CONFLICT
            and self.expected_satisfiable
            and not has_explicit_conflict
        ):
            raise ValueError("conflict cases require opposing facts or expected unsatisfiability")
        return self


class BehavioralCaseResult(BaseModel):
    """Cautious-consequence outcome for one case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    satisfiable: bool
    expected_satisfiable: bool
    missing_conclusions: tuple[str, ...] = ()
    unexpected_conclusions: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.satisfiable == self.expected_satisfiable
            and not self.missing_conclusions
            and not self.unexpected_conclusions
        )


class BehavioralCoverageReport(BaseModel):
    """Execution results plus rule-family and statement-level coverage gaps."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    program_id: str
    results: tuple[BehavioralCaseResult, ...]
    uncovered_rule_families: tuple[str, ...]
    incomplete_rule_families: tuple[str, ...]
    uncovered_statement_ids: tuple[str, ...]
    material_rules_without_negative_case: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            bool(self.results)
            and all(result.passed for result in self.results)
            and not self.uncovered_rule_families
            and not self.incomplete_rule_families
            and not self.uncovered_statement_ids
            and not self.material_rules_without_negative_case
        )

    def require_passed(self) -> None:
        if not self.passed:
            raise ValueError("behavioral coverage gate failed")


def evaluate_behavioral_cases(
    program: LogicalProgram,
    cases: tuple[BehavioralCase, ...],
    *,
    validated_statement_ids: frozenset[str],
    material_statement_ids: frozenset[str],
    required_rule_families: frozenset[str],
    registry: PredicateRegistry | None = None,
) -> BehavioralCoverageReport:
    """Execute cases and require six perspectives per declared rule family."""
    vocabulary = registry or PredicateRegistry()
    compiled = compile_asp(program, vocabulary)
    results = tuple(_evaluate_case(compiled.text, case, vocabulary) for case in cases)
    by_family: dict[str, set[BehavioralCaseKind]] = {}
    exercised: set[str] = set()
    negative_exercised: set[str] = set()
    for case in cases:
        by_family.setdefault(case.rule_family, set()).add(case.kind)
        exercised.update(case.statement_ids)
        if case.kind == BehavioralCaseKind.NEGATIVE:
            negative_exercised.update(case.statement_ids)
    uncovered_families = required_rule_families - set(by_family)
    incomplete_families = {
        family
        for family in required_rule_families & set(by_family)
        if by_family[family] != MANDATORY_CASE_KINDS
    }
    return BehavioralCoverageReport(
        program_id=program.program_id,
        results=results,
        uncovered_rule_families=tuple(sorted(uncovered_families)),
        incomplete_rule_families=tuple(sorted(incomplete_families)),
        uncovered_statement_ids=tuple(sorted(validated_statement_ids - exercised)),
        material_rules_without_negative_case=tuple(
            sorted(material_statement_ids - negative_exercised)
        ),
    )


def _evaluate_case(
    base_program: str,
    case: BehavioralCase,
    registry: PredicateRegistry,
) -> BehavioralCaseResult:
    additions = "\n".join(f"{render_asp_atom(atom, registry)}." for atom in case.given)
    control = clingo.Control(["--warn=none"])
    control.add("base", [], base_program + additions + "\n")
    control.ground([("base", [])])
    models: list[set[str]] = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            models.append({str(symbol) for symbol in model.symbols(atoms=True)})
    satisfiable = bool(models)
    cautious = set.intersection(*models) if models else set()
    possible = set.union(*models) if models else set()
    expected = {render_asp_atom(atom, registry) for atom in case.expected_conclusions}
    absent = {render_asp_atom(atom, registry) for atom in case.expected_absences}
    return BehavioralCaseResult(
        case_id=case.case_id,
        satisfiable=satisfiable,
        expected_satisfiable=case.expected_satisfiable,
        missing_conclusions=(
            tuple(sorted(expected - cautious)) if satisfiable else tuple(sorted(expected))
        ),
        unexpected_conclusions=tuple(sorted(absent & possible)),
    )
