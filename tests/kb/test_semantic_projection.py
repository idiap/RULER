# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import hashlib
from datetime import date

import pytest
from pydantic import ValidationError

from ruler.contracts.semantics import (
    SemanticBasis,
    SemanticElement,
    SemanticSourceSpan,
    SemanticTemporalConstraint,
)
from ruler.kb.semantic_projection import ProjectionDimension, SemanticProjection


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def test_semantic_basis_verifies_exact_source_bytes_not_a_self_hash() -> None:
    source = b"The operator shall notify the authority."
    text = source.decode()
    basis = SemanticBasis(
        basis_id="basis-1",
        context_id="case-1",
        spans=(
            SemanticSourceSpan(
                span_id="s1",
                artifact_id="law",
                artifact_sha256=_digest(source),
                exact_text=text,
                start_char=0,
                end_char=len(text),
            ),
        ),
        elements=(
            SemanticElement(
                element_id="e1",
                kind="proposition",
                predicate="notify_authority",
                source_span_ids=("s1",),
            ),
        ),
    )
    basis.verify_source_artifacts({"law": source})
    with pytest.raises(ValueError, match="digest mismatch"):
        basis.verify_source_artifacts({"law": b"A substituted provision."})


def test_semantic_basis_requires_bidirectional_unit_links() -> None:
    source = b"The operator shall notify the authority."
    basis = SemanticBasis(
        basis_id="basis-linked",
        context_id="case-linked",
        spans=(
            SemanticSourceSpan(
                span_id="s1",
                artifact_id="law",
                artifact_sha256=_digest(source),
                exact_text=source.decode(),
                start_char=0,
                end_char=len(source.decode()),
            ),
        ),
        elements=(
            SemanticElement(
                element_id="e1",
                kind="proposition",
                predicate="notify_authority",
                source_span_ids=("s1",),
                formalization_unit_ids=("unit-1",),
            ),
        ),
    )
    basis.verify_logical_units({"unit-1": ("e1",)})
    with pytest.raises(ValueError, match="unknown formalization units"):
        basis.verify_logical_units({"unit-2": ("e1",)})


def test_typed_temporal_semantics_preserve_units_boundaries_and_version_precedence() -> None:
    deadline = SemanticTemporalConstraint(
        kind="relative_deadline",
        anchor_event="notice_received",
        amount=5,
        unit="business_days",
        comparison="before_or_on",
    )
    window = SemanticTemporalConstraint(
        kind="rolling_window",
        anchor_event="purchase_time",
        amount=48,
        unit="hours",
        comparison="after_or_on",
        start_inclusive=False,
        end_inclusive=True,
    )
    version = SemanticTemporalConstraint(
        kind="effective_version",
        effective_from=date(2026, 7, 1),
        effective_until=date(2026, 12, 31),
        start_inclusive=True,
        end_inclusive=False,
        version_id="amendment-2026-07",
        precedence_rank=20,
    )

    assert deadline.unit == "business_days"
    assert deadline.comparison == "before_or_on"
    assert (window.start_inclusive, window.end_inclusive) == (False, True)
    assert version.precedence_rank == 20
    with pytest.raises(ValidationError, match="explicit boundary inclusivity"):
        SemanticTemporalConstraint(
            kind="rolling_window",
            anchor_event="purchase_time",
            amount=30,
            unit="calendar_days",
            comparison="before",
        )


def test_deontic_distinctions_survive_basis_to_logical_unit_links() -> None:
    source = b"Definition. Must. Must not. May. Unless. But not when restored."
    span = SemanticSourceSpan(
        span_id="s-deontic",
        artifact_id="rules",
        artifact_sha256=_digest(source),
        exact_text=source.decode(),
        start_char=0,
        end_char=len(source.decode()),
    )
    specifications = (
        ("definition", "proposition", "defined", "definition"),
        ("duty", "proposition", "obligatory", "obligation"),
        ("ban", "proposition", "prohibited", "prohibition"),
        ("leave", "proposition", "permitted", "permission"),
        ("exception", "exception", "asserted", "exception"),
        ("restoration", "counter_exception", "asserted", "counter_exception"),
    )
    elements = tuple(
        SemanticElement(
            element_id=element_id,
            kind=kind,
            predicate=f"rule_{element_id}",
            modality=modality,
            source_span_ids=(span.span_id,),
            formalization_unit_ids=(f"unit-{element_id}",),
        )
        for element_id, kind, modality, _operator in specifications
    )
    basis = SemanticBasis(
        basis_id="basis-deontic", context_id="deontic-case", spans=(span,), elements=elements
    )
    links = {f"unit-{element_id}": (element_id,) for element_id, *_ in specifications}
    operators = {
        f"unit-{element_id}": operator for element_id, _kind, _modality, operator in specifications
    }
    basis.verify_logical_units(links, operators)

    operators["unit-leave"] = "obligation"
    with pytest.raises(ValueError, match="does not preserve leave as permission"):
        basis.verify_logical_units(links, operators)


def test_query_affecting_projection_loss_blocks_activation() -> None:
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValidationError, match="must block"):
        SemanticProjection(
            projection_id="p1",
            target_formalism="asp",
            source_artifact_digests=(digest,),
            semantic_basis_digest=digest,
            formalization_units_digest=digest,
            program_digest=digest,
            query_id="q1",
            represented_element_ids=("e1",),
            symbol_mapping={"e1": "p_e1"},
            dimensions=(
                ProjectionDimension(
                    dimension="exceptions",
                    disposition="omitted",
                    explanation="not supported",
                    query_affecting=True,
                ),
            ),
            activation_status="active",
        )


def test_symbol_mapping_must_be_bijective_and_total() -> None:
    digest = "sha256:" + "b" * 64
    with pytest.raises(ValidationError, match="cover every represented"):
        SemanticProjection(
            projection_id="p1",
            target_formalism="tptp",
            source_artifact_digests=(digest,),
            semantic_basis_digest=digest,
            formalization_units_digest=digest,
            program_digest=digest,
            query_id="q1",
            represented_element_ids=("e1", "e2"),
            symbol_mapping={"e1": "p1"},
            dimensions=(
                ProjectionDimension(
                    dimension="actors",
                    disposition="represented",
                    explanation="typed symbols",
                    query_affecting=True,
                ),
            ),
            activation_status="active",
        )


@pytest.mark.parametrize(
    "disposition",
    ["omitted", "approximated", "unsupported", "ambiguous", "open_texture"],
)
def test_each_loss_category_requires_its_own_activation_blocker(disposition: str) -> None:
    digest = "sha256:" + "c" * 64
    with pytest.raises(ValidationError, match="lacks typed blockers"):
        SemanticProjection(
            projection_id="p-loss",
            target_formalism="asp",
            source_artifact_digests=(digest,),
            semantic_basis_digest=digest,
            formalization_units_digest=digest,
            program_digest=digest,
            query_id="q-loss",
            represented_element_ids=("e1",),
            symbol_mapping={"e1": "p/1#e1"},
            dimensions=(
                ProjectionDimension(
                    dimension="temporal",
                    disposition=disposition,
                    explanation="The source meaning cannot safely be projected.",
                    query_affecting=True,
                    element_ids=("e1",),
                ),
            ),
            activation_status="blocked",
        )
