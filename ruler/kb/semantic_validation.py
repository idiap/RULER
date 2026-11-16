# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic semantic-drift and protected-mutation checks."""

from __future__ import annotations

from pydantic import Field

from ruler.contracts.common import StrictContract
from ruler.contracts.semantics import (
    SemanticBasis,
    SemanticElement,
    SemanticElementKind,
    SemanticModality,
    SemanticRole,
)

PROTECTED_DIMENSIONS = frozenset(
    {
        "actor",
        "modality",
        "polarity",
        "connective",
        "exception",
        "quantity",
        "temporal",
        "coreference",
    }
)


class SemanticMutationFinding(StrictContract):
    element_id: str
    changed_dimensions: tuple[str, ...] = Field(min_length=1)
    blocks_projection: bool = True


class SemanticMutationReport(StrictContract):
    source_basis_id: str
    candidate_basis_id: str
    findings: tuple[SemanticMutationFinding, ...]
    protected_dimensions_exercised: tuple[str, ...]
    projection_allowed: bool
    blockers: tuple[str, ...]


class GeneratedSemanticMutation(StrictContract):
    """A mechanically generated mutant and the critic evidence that killed it."""

    dimension: str
    changed_path: str
    candidate: SemanticBasis
    report: SemanticMutationReport


def compare_semantic_bases(
    source: SemanticBasis, candidate: SemanticBasis
) -> SemanticMutationReport:
    """Detect meaning-changing edits by element identity; additions never hide deletions."""

    original = {item.element_id: item for item in source.elements}
    changed = {item.element_id: item for item in candidate.elements}
    findings: list[SemanticMutationFinding] = []
    for element_id in sorted(set(original) | set(changed)):
        left, right = original.get(element_id), changed.get(element_id)
        dimensions = _changed_dimensions(left, right)
        if dimensions:
            findings.append(
                SemanticMutationFinding(element_id=element_id, changed_dimensions=dimensions)
            )
    exercised = tuple(sorted({item for finding in findings for item in finding.changed_dimensions}))
    blockers = tuple(
        f"semantic_mutation:{item.element_id}:{','.join(item.changed_dimensions)}"
        for item in findings
    )
    return SemanticMutationReport(
        source_basis_id=source.basis_id,
        candidate_basis_id=candidate.basis_id,
        findings=tuple(findings),
        protected_dimensions_exercised=exercised,
        projection_allowed=not findings,
        blockers=blockers,
    )


def require_mutation_suite_coverage(reports: tuple[SemanticMutationReport, ...]) -> None:
    """Require an executed rejecting mutation for every protected semantic dimension."""

    covered = {
        dimension
        for report in reports
        if not report.projection_allowed
        for dimension in report.protected_dimensions_exercised
    }
    if missing := PROTECTED_DIMENSIONS - covered:
        raise ValueError(f"semantic mutation suite is incomplete: {sorted(missing)}")


def generate_protected_semantic_mutants(
    basis: SemanticBasis,
) -> tuple[GeneratedSemanticMutation, ...]:
    """Generate and independently compare one real mutant per protected dimension.

    The function fails closed when the supplied basis does not contain enough semantic
    structure to exercise a dimension.  This prevents a nominal eight-item suite from
    claiming coverage with no actual actor, temporal, or coreference mutation.
    """

    entities = [item.element_id for item in basis.elements if item.kind.value == "entity"]
    generated: list[GeneratedSemanticMutation] = []
    for dimension in sorted(PROTECTED_DIMENSIONS):
        elements = list(basis.elements)
        index, mutated, changed_path = _mutate_dimension(elements, dimension, entities)
        elements[index] = mutated
        candidate = basis.model_copy(
            update={
                "basis_id": f"{basis.basis_id}:mutant:{dimension}",
                "elements": tuple(elements),
            }
        )
        report = compare_semantic_bases(basis, candidate)
        if dimension not in report.protected_dimensions_exercised:
            raise ValueError(f"generated {dimension} mutant was not detected as {dimension}")
        generated.append(
            GeneratedSemanticMutation(
                dimension=dimension,
                changed_path=changed_path,
                candidate=candidate,
                report=report,
            )
        )
    require_mutation_suite_coverage(tuple(item.report for item in generated))
    return tuple(generated)


def _mutate_dimension(
    elements: list[SemanticElement], dimension: str, entities: list[str]
) -> tuple[int, SemanticElement, str]:
    if dimension == "actor":
        for index, element in enumerate(elements):
            for role_index, role in enumerate(element.roles):
                replacements = [item for item in entities if item != role.element_id]
                if role.role == "actor" and replacements:
                    roles = list(element.roles)
                    roles[role_index] = SemanticRole(role="actor", element_id=replacements[0])
                    return (
                        index,
                        element.model_copy(update={"roles": tuple(roles)}),
                        f"elements[{index}].roles[{role_index}].element_id",
                    )
    elif dimension == "modality":
        for index, element in enumerate(elements):
            if element.kind.value == "proposition":
                replacement = (
                    SemanticModality.PERMITTED
                    if element.modality != SemanticModality.PERMITTED
                    else SemanticModality.OBLIGATORY
                )
                return (
                    index,
                    element.model_copy(update={"modality": replacement}),
                    f"elements[{index}].modality",
                )
    elif dimension == "polarity":
        for index, element in enumerate(elements):
            replacement = "negative" if element.polarity == "positive" else "positive"
            return (
                index,
                element.model_copy(update={"polarity": replacement}),
                f"elements[{index}].polarity",
            )
    elif dimension == "connective":
        for index, element in enumerate(elements):
            if element.connective in {"and", "or"}:
                replacement = "or" if element.connective == "and" else "and"
                return (
                    index,
                    element.model_copy(update={"connective": replacement}),
                    f"elements[{index}].connective",
                )
    elif dimension == "exception":
        for index, element in enumerate(elements):
            if element.kind.value == "exception":
                return (
                    index,
                    element.model_copy(update={"kind": SemanticElementKind.PROPOSITION}),
                    f"elements[{index}].kind",
                )
    elif dimension == "quantity":
        for index, element in enumerate(elements):
            if element.kind.value == "quantity":
                value = (
                    element.value + 1
                    if isinstance(element.value, (int, float))
                    else f"{element.value}-mutated"
                )
                return (
                    index,
                    element.model_copy(update={"value": value}),
                    f"elements[{index}].value",
                )
    elif dimension == "temporal":
        for index, element in enumerate(elements):
            if element.kind.value == "temporal_relation":
                assert element.temporal is not None
                if element.temporal.amount is not None:
                    temporal = element.temporal.model_copy(
                        update={"amount": element.temporal.amount + 1}
                    )
                    return (
                        index,
                        element.model_copy(update={"temporal": temporal}),
                        f"elements[{index}].temporal.amount",
                    )
                temporal = element.temporal.model_copy(
                    update={"end_inclusive": not element.temporal.end_inclusive}
                )
                return (
                    index,
                    element.model_copy(update={"temporal": temporal}),
                    f"elements[{index}].temporal.end_inclusive",
                )
    elif dimension == "coreference":
        for index, element in enumerate(elements):
            if element.kind.value == "coreference":
                for role_index, role in enumerate(element.roles):
                    replacements = [item for item in entities if item != role.element_id]
                    if role.role == "antecedent" and replacements:
                        roles = list(element.roles)
                        roles[role_index] = SemanticRole(
                            role="antecedent", element_id=replacements[0]
                        )
                        return (
                            index,
                            element.model_copy(update={"roles": tuple(roles)}),
                            f"elements[{index}].roles[{role_index}].element_id",
                        )
                return (
                    index,
                    element.model_copy(update={"kind": SemanticElementKind.RELATION}),
                    f"elements[{index}].kind",
                )
    raise ValueError(f"semantic basis cannot exercise protected dimension: {dimension}")


def _changed_dimensions(
    left: SemanticElement | None, right: SemanticElement | None
) -> tuple[str, ...]:
    if left is None or right is None:
        remaining = left or right
        return (
            ("exception",)
            if remaining is not None and remaining.kind.value == "exception"
            else ("actor",)
        )
    dimensions: set[str] = set()
    left_roles = {(item.role, item.element_id) for item in left.roles}
    right_roles = {(item.role, item.element_id) for item in right.roles}
    if left_roles != right_roles:
        dimensions.add("actor")
        if any(role == "antecedent" for role, _ in left_roles | right_roles):
            dimensions.add("coreference")
    if left.modality != right.modality:
        dimensions.add("modality")
    if left.polarity != right.polarity:
        dimensions.add("polarity")
    if left.connective != right.connective:
        dimensions.add("connective")
    if left.kind != right.kind and "exception" in {left.kind.value, right.kind.value}:
        dimensions.add("exception")
    if (left.value, left.unit) != (right.value, right.unit):
        dimensions.add("quantity")
    if left.kind.value == "temporal_relation" and left != right:
        dimensions.add("temporal")
    if left.kind.value == "coreference" and left != right:
        dimensions.add("coreference")
    if left.source_span_ids != right.source_span_ids:
        dimensions.add("actor")
    return tuple(sorted(dimensions))
