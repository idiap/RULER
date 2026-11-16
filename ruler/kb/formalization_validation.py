# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Named static semantic validators for typed logical programs."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ruler.kb.formalization import (
    LOGIC_STATES,
    FormalizationInventory,
    PredicateRegistry,
)
from ruler.kb.logical_ir import (
    ArithmeticTerm,
    Atom,
    Constant,
    ExpressionKind,
    IRStatement,
    LogicalExpression,
    LogicalProgram,
    Modality,
    Variable,
)


class IssueSeverity(StrEnum):
    """Static semantic issue severity."""

    ERROR = "error"
    WARNING = "warning"


class SemanticIssue(BaseModel):
    """One stable, named validation finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validator: str
    code: str
    severity: IssueSeverity
    statement_ids: tuple[str, ...] = ()
    message: str


class SemanticValidationReport(BaseModel):
    """Complete static report; any error blocks compilation/promotion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    program_id: str
    issues: tuple[SemanticIssue, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == IssueSeverity.ERROR for issue in self.issues)

    def require_valid(self) -> None:
        """Fail closed with deterministic issue codes."""
        errors = [issue.code for issue in self.issues if issue.severity == IssueSeverity.ERROR]
        if errors:
            raise ValueError("static semantic validation failed: " + ", ".join(errors))


def validate_static_semantics(
    program: LogicalProgram,
    registry: PredicateRegistry | None = None,
    *,
    inventory: FormalizationInventory | None = None,
) -> SemanticValidationReport:
    """Run every named static checker and return findings in stable order."""
    vocabulary = registry or PredicateRegistry()
    issues = [
        *_validate_predicates(program, vocabulary),
        *_validate_variable_safety(program),
        *_validate_contradictory_facts(program),
        *_validate_dependency_cycles(program),
        *_validate_unreachable_rules(program),
        *_validate_grounding(program),
        *_validate_orphan_clauses(program, inventory),
    ]
    issues.sort(key=lambda item: (item.validator, item.code, item.statement_ids, item.message))
    return SemanticValidationReport(program_id=program.program_id, issues=tuple(issues))


def _validate_predicates(
    program: LogicalProgram,
    registry: PredicateRegistry,
) -> list[SemanticIssue]:
    issues: list[SemanticIssue] = []
    declarations = {
        signature.name: signature for signature in registry.signatures if signature.approved
    }
    for statement in program.statements:
        for atom in _statement_atoms(statement):
            signature = declarations.get(atom.predicate)
            if signature is None:
                issues.append(
                    _issue(
                        "predicate_declaration", "undeclared_predicate", statement, atom.predicate
                    )
                )
                continue
            if len(atom.arguments) != signature.arity:
                issues.append(
                    _issue(
                        "predicate_arity",
                        "arity_error",
                        statement,
                        f"{atom.predicate} expects {signature.arity}, got {len(atom.arguments)}",
                    )
                )
                continue
            for index, (argument, expected) in enumerate(
                zip(atom.arguments, signature.argument_types, strict=True)
            ):
                if argument.value_type != expected:
                    issues.append(
                        _issue(
                            "predicate_type",
                            "type_error",
                            statement,
                            f"{atom.predicate} argument {index + 1} expects {expected.value}, "
                            f"got {argument.value_type.value}",
                        )
                    )
                domain = signature.value_domains[index] if signature.value_domains else None
                if domain and isinstance(argument, Constant) and str(argument.value) not in domain:
                    issues.append(
                        _issue(
                            "predicate_value_domain",
                            "value_domain_error",
                            statement,
                            f"{atom.predicate} argument {index + 1} value "
                            f"{argument.value!r} is outside {domain}",
                        )
                    )
    for directive in program.show:
        signature = declarations.get(directive.predicate)
        if signature is None:
            issues.append(
                SemanticIssue(
                    validator="predicate_declaration",
                    code="undeclared_predicate",
                    severity=IssueSeverity.ERROR,
                    message=f"show directive uses {directive.predicate}",
                )
            )
        elif directive.arity != signature.arity:
            issues.append(
                SemanticIssue(
                    validator="predicate_arity",
                    code="arity_error",
                    severity=IssueSeverity.ERROR,
                    message=f"show directive {directive.predicate}/{directive.arity} has wrong arity",
                )
            )
    return issues


def _validate_variable_safety(program: LogicalProgram) -> list[SemanticIssue]:
    issues: list[SemanticIssue] = []
    for statement in program.statements:
        positive: set[str] = set()
        restricted: set[str] = set()
        if statement.body:
            _classify_variables(statement.body, positive, restricted, negated=False)
        head_variables = _atom_variables(statement.head) if statement.head else set()
        unsafe = (head_variables | restricted) - positive
        if statement.modality == Modality.FACT:
            unsafe |= head_variables
        if unsafe:
            issues.append(
                _issue(
                    "variable_safety",
                    "unsafe_variable",
                    statement,
                    "variables lack a positive body binding: " + ", ".join(sorted(unsafe)),
                )
            )
    return issues


def _classify_variables(
    expression: LogicalExpression,
    positive: set[str],
    restricted: set[str],
    *,
    negated: bool,
) -> None:
    if expression.kind == ExpressionKind.ATOM and expression.atom:
        target = restricted if negated else positive
        target.update(_atom_variables(expression.atom))
    elif expression.kind == ExpressionKind.NEGATION:
        _classify_variables(expression.operands[0], positive, restricted, negated=True)
    elif expression.kind in {ExpressionKind.CONJUNCTION, ExpressionKind.DISJUNCTION}:
        for operand in expression.operands:
            _classify_variables(operand, positive, restricted, negated=negated)
    elif expression.kind == ExpressionKind.COMPARISON and expression.comparison:
        restricted.update(_scalar_variables(expression.comparison.left))
        restricted.update(_scalar_variables(expression.comparison.right))
    elif expression.kind == ExpressionKind.AGGREGATION and expression.aggregation:
        # Aggregate-local variables are bound by the aggregate's atom.
        positive.update(_atom_variables(expression.aggregation.atom))
        restricted.add(expression.aggregation.variable.name)
    elif expression.kind in {ExpressionKind.EXCEPTION, ExpressionKind.PRIORITY}:
        for operand in expression.operands:
            _classify_variables(operand, positive, restricted, negated=negated)
        if expression.exception_target:
            restricted.update(_atom_variables(expression.exception_target))


def _validate_contradictory_facts(program: LogicalProgram) -> list[SemanticIssue]:
    facts: dict[str, dict[bool, list[str]]] = defaultdict(lambda: defaultdict(list))
    for statement in program.statements:
        if statement.modality == Modality.FACT and statement.head:
            facts[statement.head.key()][statement.head.classical_negation].append(
                statement.statement_id
            )
    issues = []
    for polarities in facts.values():
        if polarities[False] and polarities[True]:
            ids = tuple(sorted(polarities[False] + polarities[True]))
            issues.append(
                SemanticIssue(
                    validator="fact_consistency",
                    code="contradictory_fact",
                    severity=IssueSeverity.ERROR,
                    statement_ids=ids,
                    message="the same ground atom is asserted positively and negatively",
                )
            )
    return issues


def _validate_dependency_cycles(program: LogicalProgram) -> list[SemanticIssue]:
    graph: dict[str, set[str]] = defaultdict(set)
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)
    for statement in program.statements:
        if not statement.head or not statement.body:
            continue
        for atom in _expression_atoms(statement.body):
            graph[statement.head.predicate].add(atom.predicate)
            owners[(statement.head.predicate, atom.predicate)].append(statement.statement_id)
    issues: list[SemanticIssue] = []
    for component in _strongly_connected_components(graph):
        if len(component) > 1 or any(node in graph[node] for node in component):
            ids = {
                statement_id
                for source in component
                for target in graph[source] & component
                for statement_id in owners[(source, target)]
            }
            issues.append(
                SemanticIssue(
                    validator="dependency_acyclicity",
                    code="dependency_cycle",
                    severity=IssueSeverity.ERROR,
                    statement_ids=tuple(sorted(ids)),
                    message="predicate dependency cycle: " + " -> ".join(sorted(component)),
                )
            )
    return issues


def _validate_unreachable_rules(program: LogicalProgram) -> list[SemanticIssue]:
    roots = set(program.entrypoint_predicates) | {directive.predicate for directive in program.show}
    if not roots:
        return []
    dependencies: dict[str, set[str]] = defaultdict(set)
    statements_by_head: dict[str, list[str]] = defaultdict(list)
    for statement in program.statements:
        if statement.head and statement.body:
            statements_by_head[statement.head.predicate].append(statement.statement_id)
            dependencies[statement.head.predicate].update(
                atom.predicate for atom in _expression_atoms(statement.body)
            )
    reachable = set(roots)
    pending = list(roots)
    while pending:
        current = pending.pop()
        for dependency in dependencies[current] - reachable:
            reachable.add(dependency)
            pending.append(dependency)
    issues = []
    for predicate in sorted(set(statements_by_head) - reachable):
        issues.append(
            SemanticIssue(
                validator="rule_reachability",
                code="unreachable_rule",
                severity=IssueSeverity.ERROR,
                statement_ids=tuple(sorted(statements_by_head[predicate])),
                message=f"{predicate} is not reachable from a declared entrypoint",
            )
        )
    return issues


def _validate_grounding(program: LogicalProgram) -> list[SemanticIssue]:
    issues = []
    for statement in program.statements:
        if any(ref.span_id.startswith("assertion_payload:") for ref in statement.provenance):
            issues.append(
                _issue(
                    "source_grounding",
                    "missing_grounding",
                    statement,
                    "statement uses assertion-level fallback instead of an exact document span",
                )
            )
    return issues


def _validate_orphan_clauses(
    program: LogicalProgram,
    inventory: FormalizationInventory | None,
) -> list[SemanticIssue]:
    if inventory is None:
        return []
    statement_ids = {statement.statement_id for statement in program.statements}
    inventory_ids = {item.assertion_id for item in inventory.items}
    issues: list[SemanticIssue] = []
    for item in inventory.items:
        if item.state in LOGIC_STATES:
            missing = set(item.logical_unit_ids) - statement_ids
            if missing:
                issues.append(
                    SemanticIssue(
                        validator="clause_linkage",
                        code="orphan_clause",
                        severity=IssueSeverity.ERROR,
                        statement_ids=tuple(sorted(missing)),
                        message=f"{item.assertion_id} points to absent logical units",
                    )
                )
    for statement in program.statements:
        unknown = set(statement.source_assertion_ids) - inventory_ids
        if unknown:
            issues.append(
                _issue(
                    "clause_linkage",
                    "orphan_clause",
                    statement,
                    "statement references unknown assertions: " + ", ".join(sorted(unknown)),
                )
            )
    return issues


def _statement_atoms(statement: IRStatement) -> list[Atom]:
    atoms = [statement.head] if statement.head else []
    if statement.body:
        atoms.extend(_expression_atoms(statement.body))
    return atoms


def _expression_atoms(expression: LogicalExpression) -> list[Atom]:
    atoms: list[Atom] = []
    if expression.atom:
        atoms.append(expression.atom)
    if expression.aggregation:
        atoms.append(expression.aggregation.atom)
    if expression.exception_target:
        atoms.append(expression.exception_target)
    for operand in expression.operands:
        atoms.extend(_expression_atoms(operand))
    return atoms


def _atom_variables(atom: Atom | None) -> set[str]:
    if atom is None:
        return set()
    return {argument.name for argument in atom.arguments if isinstance(argument, Variable)}


def _scalar_variables(scalar: object) -> set[str]:
    if isinstance(scalar, Variable):
        return {scalar.name}
    if isinstance(scalar, ArithmeticTerm):
        return _scalar_variables(scalar.left) | _scalar_variables(scalar.right)
    return set()


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[set[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: set[str] = set()
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.add(target)
                if target == node:
                    break
            components.append(component)

    nodes = set(graph) | {target for targets in graph.values() for target in targets}
    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return components


def _issue(validator: str, code: str, statement: IRStatement, message: str) -> SemanticIssue:
    return SemanticIssue(
        validator=validator,
        code=code,
        severity=IssueSeverity.ERROR,
        statement_ids=(statement.statement_id,),
        message=message,
    )
