# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import hashlib

import pytest

from ruler.contracts.semantics import (
    SemanticBasis,
    SemanticElement,
    SemanticRole,
    SemanticSourceSpan,
)
from ruler.kb.semantic_validation import compare_semantic_bases, require_mutation_suite_coverage


def _basis(element: SemanticElement, basis_id: str = "base") -> SemanticBasis:
    text = "A must act unless B objects."
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    return SemanticBasis(
        basis_id=basis_id,
        context_id="case",
        spans=(
            SemanticSourceSpan(
                span_id="s",
                artifact_id="source",
                artifact_sha256=digest,
                exact_text=text,
                start_char=0,
                end_char=len(text),
            ),
        ),
        elements=(
            SemanticElement(
                element_id="actor-a", kind="entity", predicate="actor_a", source_span_ids=("s",)
            ),
            SemanticElement(
                element_id="actor-b", kind="entity", predicate="actor_b", source_span_ids=("s",)
            ),
            element,
        ),
    )


def test_actor_modality_and_connective_drift_block_projection() -> None:
    original = SemanticElement(
        element_id="rule",
        kind="proposition",
        predicate="must_act",
        roles=(SemanticRole(role="actor", element_id="actor-a"),),
        modality="obligatory",
        connective="unless",
        source_span_ids=("s",),
    )
    mutated = original.model_copy(
        update={
            "roles": (SemanticRole(role="actor", element_id="actor-b"),),
            "modality": "permitted",
            "connective": "and",
        }
    )
    report = compare_semantic_bases(_basis(original), _basis(mutated, "mutated"))
    assert not report.projection_allowed
    assert set(report.protected_dimensions_exercised) == {"actor", "connective", "modality"}


def test_mutation_suite_cannot_self_attest_without_all_dimensions() -> None:
    original = SemanticElement(
        element_id="rule",
        kind="proposition",
        predicate="must_act",
        modality="obligatory",
        source_span_ids=("s",),
    )
    mutated = original.model_copy(update={"modality": "permitted"})
    report = compare_semantic_bases(_basis(original), _basis(mutated, "mutated"))
    with pytest.raises(ValueError, match="incomplete"):
        require_mutation_suite_coverage((report,))
