# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Typed, prose-free logical intermediate representation for policy knowledge."""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.kb.formalization import SourceSpanRef, ValueType


class Variable(BaseModel):
    """Typed logical variable. Upper-case names map safely to ASP variables."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["variable"] = "variable"
    name: str = Field(pattern=r"^[A-Z][A-Za-z0-9_]*$")
    value_type: ValueType


class Constant(BaseModel):
    """Typed atomic constant; source prose cannot be inserted as an expression."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["constant"] = "constant"
    value_type: ValueType
    value: str | int | bool | date

    @model_validator(mode="before")
    @classmethod
    def parse_typed_date(cls, data: Any) -> Any:
        """Preserve date typing across canonical JSON round trips."""
        if isinstance(data, dict) and data.get("value_type") in {ValueType.DATE, "date"}:
            value = data.get("value")
            if isinstance(value, str):
                data = {**data, "value": date.fromisoformat(value)}
        return data

    @model_validator(mode="after")
    def value_matches_type(self) -> "Constant":
        integer_types = {ValueType.MONEY, ValueType.PERCENTAGE, ValueType.DURATION, ValueType.COUNT}
        if self.value_type in integer_types and (
            not isinstance(self.value, int) or isinstance(self.value, bool)
        ):
            raise ValueError(f"{self.value_type.value} constants require an integer value")
        if self.value_type == ValueType.BOOLEAN and not isinstance(self.value, bool):
            raise ValueError("boolean constants require a bool value")
        if self.value_type == ValueType.DATE and not isinstance(self.value, date):
            raise ValueError("date constants require a date value")
        if self.value_type not in integer_types | {ValueType.BOOLEAN, ValueType.DATE}:
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError(f"{self.value_type.value} constants require a non-empty string")
        return self


Term = Variable | Constant


class ArithmeticTerm(BaseModel):
    """Typed binary arithmetic over variables and numeric constants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["arithmetic"] = "arithmetic"
    operator: Literal["+", "-", "*", "/"]
    left: Term
    right: Term
    value_type: Literal[ValueType.MONEY, ValueType.PERCENTAGE, ValueType.DURATION, ValueType.COUNT]

    @model_validator(mode="after")
    def operand_types_match(self) -> "ArithmeticTerm":
        if self.left.value_type != self.value_type or self.right.value_type != self.value_type:
            raise ValueError("arithmetic operands must match the declared numeric value_type")
        return self


Scalar = Term | ArithmeticTerm


class Atom(BaseModel):
    """Predicate application resolved against the separate vocabulary registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    predicate: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    arguments: tuple[Term, ...]
    classical_negation: bool = False

    def key(self) -> str:
        """Stable structural identity used for provenance and contradiction checks."""
        return self.model_dump_json(exclude={"classical_negation"})


class ExpressionKind(StrEnum):
    """Closed expression variants supported by the IR."""

    ATOM = "atom"
    NEGATION = "negation"
    CONJUNCTION = "conjunction"
    DISJUNCTION = "disjunction"
    COMPARISON = "comparison"
    AGGREGATION = "aggregation"
    TEMPORAL = "temporal"
    EXCEPTION = "exception"
    PRIORITY = "priority"


class Comparison(BaseModel):
    """Typed arithmetic/comparison relation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operator: Literal["=", "!=", "<", "<=", ">", ">="]
    left: Scalar
    right: Scalar

    @model_validator(mode="after")
    def operands_are_comparable(self) -> "Comparison":
        if self.left.value_type != self.right.value_type:
            raise ValueError("comparison operands must have the same value_type")
        return self


class Aggregation(BaseModel):
    """ASP-style aggregate with typed result and optional comparison bound."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operator: Literal["count", "sum", "min", "max"]
    variable: Variable
    atom: Atom
    comparison: Literal["=", "!=", "<", "<=", ">", ">="]
    bound: Constant

    @model_validator(mode="after")
    def aggregate_is_typed(self) -> "Aggregation":
        if self.operator == "count" and self.bound.value_type != ValueType.COUNT:
            raise ValueError("count aggregate bounds must have count type")
        if self.operator != "count" and self.variable.value_type != self.bound.value_type:
            raise ValueError("aggregate variable and bound types must match")
        return self


class TemporalInterval(BaseModel):
    """Explicit interval preserving open/closed boundary semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Term
    start: Constant
    end: Constant
    start_inclusive: bool = True
    end_inclusive: bool = True

    @model_validator(mode="after")
    def dates_and_order_are_valid(self) -> "TemporalInterval":
        if self.start.value_type != ValueType.DATE or self.end.value_type != ValueType.DATE:
            raise ValueError("temporal interval endpoints must be dates")
        if not isinstance(self.start.value, date) or not isinstance(self.end.value, date):
            raise ValueError("temporal interval endpoint values must be dates")
        if self.start.value > self.end.value:
            raise ValueError("temporal interval start must not follow end")
        return self


class LogicalExpression(BaseModel):
    """Recursive tagged expression tree with no source-text or note fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ExpressionKind
    atom: Atom | None = None
    operands: tuple["LogicalExpression", ...] = ()
    comparison: Comparison | None = None
    aggregation: Aggregation | None = None
    temporal: TemporalInterval | None = None
    exception_target: Atom | None = None
    priority: int | None = None

    @model_validator(mode="after")
    def shape_matches_kind(self) -> "LogicalExpression":
        fields = {
            "atom": self.atom,
            "comparison": self.comparison,
            "aggregation": self.aggregation,
            "temporal": self.temporal,
            "exception_target": self.exception_target,
            "priority": self.priority,
        }
        expected: dict[ExpressionKind, set[str]] = {
            ExpressionKind.ATOM: {"atom"},
            ExpressionKind.NEGATION: set(),
            ExpressionKind.CONJUNCTION: set(),
            ExpressionKind.DISJUNCTION: set(),
            ExpressionKind.COMPARISON: {"comparison"},
            ExpressionKind.AGGREGATION: {"aggregation"},
            ExpressionKind.TEMPORAL: {"temporal"},
            ExpressionKind.EXCEPTION: {"exception_target"},
            ExpressionKind.PRIORITY: {"priority"},
        }
        populated = {name for name, value in fields.items() if value is not None}
        if populated != expected[self.kind]:
            raise ValueError(
                f"{self.kind.value} expression requires {sorted(expected[self.kind])}, "
                f"got {sorted(populated)}"
            )
        operand_counts = {
            ExpressionKind.ATOM: 0,
            ExpressionKind.NEGATION: 1,
            ExpressionKind.CONJUNCTION: 2,
            ExpressionKind.DISJUNCTION: 2,
            ExpressionKind.COMPARISON: 0,
            ExpressionKind.AGGREGATION: 0,
            ExpressionKind.TEMPORAL: 0,
            ExpressionKind.EXCEPTION: 1,
            ExpressionKind.PRIORITY: 1,
        }
        minimum = operand_counts[self.kind]
        if len(self.operands) < minimum or (
            self.kind == ExpressionKind.NEGATION and len(self.operands) != 1
        ):
            raise ValueError(f"{self.kind.value} expression has invalid operand count")
        if (
            self.kind
            not in {
                ExpressionKind.NEGATION,
                ExpressionKind.CONJUNCTION,
                ExpressionKind.DISJUNCTION,
                ExpressionKind.EXCEPTION,
                ExpressionKind.PRIORITY,
            }
            and self.operands
        ):
            raise ValueError(f"{self.kind.value} expression cannot contain operands")
        return self

    @classmethod
    def from_atom(cls, atom: Atom) -> "LogicalExpression":
        return cls(kind=ExpressionKind.ATOM, atom=atom)

    @classmethod
    def all_of(cls, *operands: "LogicalExpression") -> "LogicalExpression":
        return cls(kind=ExpressionKind.CONJUNCTION, operands=operands)


class Modality(StrEnum):
    """Operational modality retained from normalized policy propositions."""

    FACT = "fact"
    DEFINITION = "definition"
    IMPLICATION = "implication"
    CONSTRAINT = "constraint"
    EXCLUSION = "exclusion"
    EXCEPTION = "exception"
    PRECEDENCE_RULE = "precedence_rule"
    LIMIT = "limit"
    TEMPORAL_RULE = "temporal_rule"
    UNKNOWN = "unknown"


class DeonticOperator(StrEnum):
    """Source-level normative force, kept distinct from executable rule shape."""

    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"
    DEFINITION = "definition"
    EXCEPTION = "exception"
    COUNTER_EXCEPTION = "counter_exception"


class IRStatement(BaseModel):
    """One fact, implication, or constraint with exact source evidence."""

    model_config = ConfigDict(extra="forbid")

    statement_id: str
    modality: Modality
    deontic_operator: DeonticOperator | None = None
    head: Atom | None
    body: LogicalExpression | None = None
    source_assertion_ids: tuple[str, ...]
    provenance: tuple[SourceSpanRef, ...]

    @model_validator(mode="after")
    def statement_shape_is_executable(self) -> "IRStatement":
        if not self.source_assertion_ids or not self.provenance:
            raise ValueError("logical statements require assertion and exact-span provenance")
        if self.modality == Modality.FACT and (self.head is None or self.body is not None):
            raise ValueError("facts require a head and no body")
        if self.modality == Modality.CONSTRAINT and self.head is not None:
            raise ValueError("constraints must not have a head")
        if self.modality == Modality.UNKNOWN:
            raise ValueError("unknown modality cannot enter executable IR")
        if self.modality != Modality.FACT and self.body is None:
            raise ValueError("non-fact statements require a body")
        return self


class ShowDirective(BaseModel):
    """Declared predicate output emitted as an ASP show directive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    predicate: str
    arity: int = Field(ge=0)


class LogicalProgram(BaseModel):
    """Deterministically serializable executable module."""

    model_config = ConfigDict(extra="forbid")

    program_id: str
    version: str
    statements: tuple[IRStatement, ...]
    show: tuple[ShowDirective, ...] = ()
    entrypoint_predicates: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ids_are_unique(self) -> "LogicalProgram":
        ids = [statement.statement_id for statement in self.statements]
        if len(ids) != len(set(ids)):
            raise ValueError("statement_id values must be unique within a program")
        return self

    def canonical_json(self) -> str:
        """Stable round-trip representation independent of incidental whitespace."""
        return self.model_dump_json(exclude_none=True)

    def sha256(self) -> str:
        """Content identity of the typed IR."""
        return "sha256:" + hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
