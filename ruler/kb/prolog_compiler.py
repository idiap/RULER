# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic Prolog mirrors and ASP/Prolog conclusion cross-checking.

ASP remains authoritative. The Prolog output is a verified operational mirror for the
Horn-compatible IR subset; unsupported semantics fail closed instead of being weakened.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory

import clingo
from pydantic import BaseModel, ConfigDict

from ruler.kb.asp_compiler import compile_asp, render_asp_atom
from ruler.kb.formalization import PredicateRegistry
from ruler.kb.logical_ir import (
    Aggregation,
    ArithmeticTerm,
    Atom,
    Comparison,
    Constant,
    ExpressionKind,
    IRStatement,
    LogicalExpression,
    LogicalProgram,
    Modality,
    Scalar,
    Term,
    Variable,
)

PROLOG_COMPILER_VERSION = "ruler-ir-prolog-mirror/1"


@dataclass(frozen=True)
class CompiledProlog:
    """Stable Prolog mirror and its content identity."""

    program_id: str
    compiler_version: str
    authority: str
    text: str
    sha256: str


class PrologCompilationError(ValueError):
    """Raised for IR constructs without semantics-preserving Prolog lowering."""


class ConclusionExpectation(BaseModel):
    """One ground expected conclusion shared by ASP and Prolog checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expectation_id: str
    atom: Atom
    expected: bool

    def model_post_init(self, __context: object) -> None:
        if any(isinstance(argument, Variable) for argument in self.atom.arguments):
            raise ValueError("conclusion expectations must be ground")


class EpistemicStatus(StrEnum):
    """Four-valued result for an open-world ground query.

    ``false`` means that the explicit classical contrary was derived; mere absence of
    the queried atom is ``unknown``.  ``both`` makes inconsistency visible rather than
    silently allowing one polarity to win.
    """

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"
    BOTH = "both"


class EpistemicExpectation(BaseModel):
    """A ground query with an explicit open-world expected status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expectation_id: str
    atom: Atom
    expected: EpistemicStatus

    def model_post_init(self, __context: object) -> None:
        if self.atom.classical_negation:
            raise ValueError("epistemic queries name the positive atom; status carries polarity")
        if any(isinstance(argument, Variable) for argument in self.atom.arguments):
            raise ValueError("epistemic expectations must be ground")


class EpistemicConclusionCheck(BaseModel):
    """Observed four-valued status from both independently executed backends."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expectation_id: str
    expected: EpistemicStatus
    asp_observed: EpistemicStatus
    prolog_observed: EpistemicStatus

    @property
    def passed(self) -> bool:
        return self.asp_observed == self.prolog_observed == self.expected


class EpistemicCrosscheckReport(BaseModel):
    """ASP/SWI differential report that does not collapse unknown into false."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    program_id: str
    checks: tuple[EpistemicConclusionCheck, ...]

    @property
    def equivalent(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def require_equivalent(self) -> None:
        if not self.equivalent:
            failed = [check.expectation_id for check in self.checks if not check.passed]
            raise ValueError(
                "ASP/Prolog epistemic divergence: " + ", ".join(failed or ["no checks"])
            )


class ConclusionCheck(BaseModel):
    """Observed conclusion in both formalism backends."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expectation_id: str
    expected: bool
    asp_observed: bool
    prolog_observed: bool

    @property
    def passed(self) -> bool:
        return self.asp_observed == self.prolog_observed == self.expected


class MirrorCrosscheckReport(BaseModel):
    """Equivalence report over the explicitly declared expected overlap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    program_id: str
    asp_authoritative: bool = True
    checks: tuple[ConclusionCheck, ...]

    @property
    def equivalent(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def require_equivalent(self) -> None:
        if not self.equivalent:
            failed = [check.expectation_id for check in self.checks if not check.passed]
            raise ValueError("ASP/Prolog mirror divergence: " + ", ".join(failed or ["no checks"]))


def compile_prolog(
    program: LogicalProgram,
    registry: PredicateRegistry | None = None,
) -> CompiledProlog:
    """Compile the approved Horn-compatible IR subset to a deterministic mirror."""
    vocabulary = registry or PredicateRegistry()
    lines = [
        f"% generated by {PROLOG_COMPILER_VERSION}",
        "% authority: ASP",
        f"% program: {program.program_id}",
        ":- use_module(library(aggregate)).",
    ]
    # SWI raises on an entirely undefined predicate whereas ASP treats it as absent.
    # Declaring both polarities makes the Prolog mirror preserve the same open-world
    # query boundary without asserting either one.
    for signature in sorted(vocabulary.signatures, key=lambda item: item.name):
        lines.append(f":- dynamic {signature.name}/{signature.arity}.")
        lines.append(f":- dynamic explicitly_not_{signature.name}/{signature.arity}.")
    for statement in sorted(program.statements, key=lambda item: item.statement_id):
        lines.extend(_compile_statement(statement, vocabulary))
    text = "\n".join(lines) + "\n"
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return CompiledProlog(
        program_id=program.program_id,
        compiler_version=PROLOG_COMPILER_VERSION,
        authority="asp",
        text=text,
        sha256=digest,
    )


def crosscheck_asp_prolog(
    program: LogicalProgram,
    expectations: tuple[ConclusionExpectation, ...],
    registry: PredicateRegistry | None = None,
    *,
    prolog_executable: str = "swipl",
) -> MirrorCrosscheckReport:
    """Run expected ground conclusions through clingo and the generated SWI mirror."""
    if not expectations:
        raise ValueError("mirror cross-check requires at least one expected conclusion")
    executable = shutil.which(prolog_executable)
    if executable is None:
        raise RuntimeError(f"Prolog executable is unavailable: {prolog_executable}")
    vocabulary = registry or PredicateRegistry()
    asp = compile_asp(program, vocabulary)
    prolog = compile_prolog(program, vocabulary)
    asp_symbols = _asp_conclusions(asp.text)
    checks: list[ConclusionCheck] = []
    with TemporaryDirectory(prefix="ruler-prolog-crosscheck-") as temporary:
        path = Path(temporary) / "mirror.pl"
        path.write_text(prolog.text, encoding="utf-8")
        for expectation in expectations:
            asp_atom = render_asp_atom(expectation.atom, vocabulary)
            asp_observed = asp_atom in asp_symbols
            query = _render_atom(expectation.atom, vocabulary)
            completed = subprocess.run(
                [executable, "-q", "-s", str(path), "-g", query, "-t", "halt"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if completed.returncode not in {0, 1}:
                raise RuntimeError(
                    f"Prolog mirror execution failed for {expectation.expectation_id}: "
                    f"{completed.stderr.strip()}"
                )
            checks.append(
                ConclusionCheck(
                    expectation_id=expectation.expectation_id,
                    expected=expectation.expected,
                    asp_observed=asp_observed,
                    prolog_observed=completed.returncode == 0,
                )
            )
    return MirrorCrosscheckReport(program_id=program.program_id, checks=tuple(checks))


def crosscheck_asp_prolog_epistemic(
    program: LogicalProgram,
    expectations: tuple[EpistemicExpectation, ...],
    registry: PredicateRegistry | None = None,
    *,
    prolog_executable: str = "swipl",
) -> EpistemicCrosscheckReport:
    """Execute positive and explicit-negative queries in real Clingo and SWI-Prolog."""

    if not expectations:
        raise ValueError("epistemic cross-check requires at least one expected conclusion")
    executable = shutil.which(prolog_executable)
    if executable is None:
        raise RuntimeError(f"Prolog executable is unavailable: {prolog_executable}")
    vocabulary = registry or PredicateRegistry()
    asp = compile_asp(program, vocabulary)
    prolog = compile_prolog(program, vocabulary)
    asp_symbols = _asp_conclusions(asp.text)
    checks: list[EpistemicConclusionCheck] = []
    with TemporaryDirectory(prefix="ruler-prolog-epistemic-") as temporary:
        path = Path(temporary) / "mirror.pl"
        path.write_text(prolog.text, encoding="utf-8")
        for expectation in expectations:
            contrary = expectation.atom.model_copy(update={"classical_negation": True})
            asp_status = _status(
                render_asp_atom(expectation.atom, vocabulary) in asp_symbols,
                render_asp_atom(contrary, vocabulary) in asp_symbols,
            )
            positive = _run_prolog_query(
                executable, path, _render_atom(expectation.atom, vocabulary)
            )
            negative = _run_prolog_query(executable, path, _render_atom(contrary, vocabulary))
            checks.append(
                EpistemicConclusionCheck(
                    expectation_id=expectation.expectation_id,
                    expected=expectation.expected,
                    asp_observed=asp_status,
                    prolog_observed=_status(positive, negative),
                )
            )
    return EpistemicCrosscheckReport(program_id=program.program_id, checks=tuple(checks))


def _run_prolog_query(executable: str, path: Path, query: str) -> bool:
    completed = subprocess.run(
        [executable, "-q", "-s", str(path), "-g", query, "-t", "halt"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(f"Prolog mirror execution failed: {completed.stderr.strip()}")
    return completed.returncode == 0


def _status(positive: bool, negative: bool) -> EpistemicStatus:
    if positive and negative:
        return EpistemicStatus.BOTH
    if positive:
        return EpistemicStatus.TRUE
    if negative:
        return EpistemicStatus.FALSE
    return EpistemicStatus.UNKNOWN


def _asp_conclusions(text: str) -> set[str]:
    control = clingo.Control(["--warn=none"])
    control.add("base", [], text)
    control.ground([("base", [])])
    symbols: set[str] = set()
    with control.solve(yield_=True) as handle:
        for model in handle:
            symbols.update(str(symbol) for symbol in model.symbols(atoms=True))
    return symbols


def _compile_statement(statement: IRStatement, registry: PredicateRegistry) -> list[str]:
    lines = [f"% statement: {statement.statement_id}"]
    head = _render_atom(statement.head, registry) if statement.head else None
    if statement.modality == Modality.FACT:
        lines.append(f"{head}.")
        return lines
    if statement.body is None:
        raise PrologCompilationError(f"statement {statement.statement_id} has no body")
    body = _render_expression(statement.body, registry)
    if head:
        lines.append(f"{head} :- {body}.")
    else:
        identifier = _quote(statement.statement_id)
        lines.append(f"policy_violation({identifier}) :- {body}.")
    return lines


def _render_expression(expression: LogicalExpression, registry: PredicateRegistry) -> str:
    if expression.kind == ExpressionKind.ATOM:
        return _render_atom(_required(expression.atom, "atom"), registry)
    if expression.kind == ExpressionKind.NEGATION:
        operand = expression.operands[0]
        if operand.kind != ExpressionKind.ATOM:
            raise PrologCompilationError("negation mirror currently requires an atom operand")
        return f"\\+ {_render_atom(_required(operand.atom, 'negated atom'), registry)}"
    if expression.kind == ExpressionKind.CONJUNCTION:
        return ", ".join(_render_expression(item, registry) for item in expression.operands)
    if expression.kind == ExpressionKind.DISJUNCTION:
        return (
            "("
            + " ; ".join(_render_expression(item, registry) for item in expression.operands)
            + ")"
        )
    if expression.kind == ExpressionKind.COMPARISON:
        return _render_comparison(_required(expression.comparison, "comparison"))
    if expression.kind == ExpressionKind.AGGREGATION:
        return _render_aggregation(_required(expression.aggregation, "aggregation"), registry)
    if expression.kind == ExpressionKind.EXCEPTION:
        body = _render_expression(expression.operands[0], registry)
        target = _render_atom(_required(expression.exception_target, "exception target"), registry)
        return f"{body}, \\+ {target}"
    if expression.kind in {ExpressionKind.TEMPORAL, ExpressionKind.PRIORITY}:
        raise PrologCompilationError(
            f"{expression.kind.value} must be normalized to declared predicates before mirroring"
        )
    raise PrologCompilationError(f"unsupported expression: {expression.kind.value}")


def _render_atom(atom: Atom, registry: PredicateRegistry) -> str:
    signature = registry.require(atom.predicate)
    if len(atom.arguments) != signature.arity:
        raise PrologCompilationError(
            f"arity mismatch for {atom.predicate}: expected {signature.arity}, got {len(atom.arguments)}"
        )
    for index, (argument, expected) in enumerate(
        zip(atom.arguments, signature.argument_types, strict=True)
    ):
        if argument.value_type != expected:
            raise PrologCompilationError(
                f"type mismatch for {atom.predicate} argument {index + 1}: "
                f"expected {expected.value}, got {argument.value_type.value}"
            )
        domain = signature.value_domains[index] if signature.value_domains else None
        if domain and isinstance(argument, Constant) and str(argument.value) not in domain:
            raise PrologCompilationError(
                f"value-domain mismatch for {atom.predicate} argument {index + 1}"
            )
    name = f"explicitly_not_{atom.predicate}" if atom.classical_negation else atom.predicate
    return f"{name}({','.join(_render_term(item) for item in atom.arguments)})"


def _render_comparison(comparison: Comparison) -> str:
    operators = {"=": "=", "!=": "\\=", "<": "<", "<=": "=<", ">": ">", ">=": ">="}
    return (
        f"{_render_scalar(comparison.left)} {operators[comparison.operator]} "
        f"{_render_scalar(comparison.right)}"
    )


def _render_aggregation(aggregation: Aggregation, registry: PredicateRegistry) -> str:
    atom = _render_atom(aggregation.atom, registry)
    variable = _render_term(aggregation.variable)
    bound = _render_term(aggregation.bound)
    comparison = {"=": "=", "!=": "\\=", "<": "<", "<=": "=<", ">": ">", ">=": ">="}[
        aggregation.comparison
    ]
    if aggregation.operator == "count":
        return f"aggregate_all(count, {atom}, Result), Result {comparison} {bound}"
    operation = aggregation.operator
    return f"aggregate_all({operation}({variable}), {atom}, Result), Result {comparison} {bound}"


def _render_scalar(value: Scalar) -> str:
    if isinstance(value, ArithmeticTerm):
        return f"({_render_term(value.left)} {value.operator} {_render_term(value.right)})"
    return _render_term(value)


def _render_term(term: Term) -> str:
    if isinstance(term, Variable):
        return term.name
    value = term.value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, date):
        value = value.isoformat()
    return _quote(str(value))


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _required[T](value: T | None, label: str) -> T:
    if value is None:
        raise PrologCompilationError(f"missing {label}")
    return value
