# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Digest-bound projections from semantic IR to executable formalisms."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256


class ProjectionDimension(StrictContract):
    dimension: Literal[
        "actors",
        "modality",
        "polarity",
        "connectives",
        "exceptions",
        "quantities",
        "temporal",
        "coreference",
        "attribution",
    ]
    disposition: Literal[
        "represented", "approximated", "omitted", "unsupported", "ambiguous", "open_texture"
    ]
    explanation: str = Field(min_length=1)
    query_affecting: bool
    element_ids: tuple[str, ...] = ()


class ActivationBlocker(StrictContract):
    """A typed reason why lossy semantics cannot enter an active knowledge base."""

    blocker_id: str = Field(min_length=1)
    category: Literal["omitted", "approximated", "unsupported", "ambiguous", "open_texture"]
    dimension: str = Field(min_length=1)
    affected_element_ids: tuple[str, ...] = ()
    explanation: str = Field(min_length=1)


class SemanticProjection(StrictContract):
    projection_id: str
    target_formalism: Literal["asp", "prolog", "tptp", "lean4"]
    source_artifact_digests: tuple[str, ...] = Field(min_length=1)
    semantic_basis_digest: str
    formalization_units_digest: str
    program_digest: str
    query_id: str
    represented_element_ids: tuple[str, ...] = Field(min_length=1)
    omitted_element_ids: tuple[str, ...] = ()
    symbol_mapping: dict[str, str]
    dimensions: tuple[ProjectionDimension, ...] = Field(min_length=1)
    activation_blockers: tuple[ActivationBlocker, ...] = ()
    activation_status: Literal["active", "blocked"]

    @model_validator(mode="after")
    def projection_is_complete_and_safe(self) -> "SemanticProjection":
        for value in (
            *self.source_artifact_digests,
            self.semantic_basis_digest,
            self.formalization_units_digest,
            self.program_digest,
        ):
            validate_sha256(value)
        represented = set(self.represented_element_ids)
        omitted = set(self.omitted_element_ids)
        if represented & omitted:
            raise ValueError("semantic element cannot be both represented and omitted")
        if set(self.symbol_mapping) != represented:
            raise ValueError("symbol mapping must cover every represented element exactly")
        if len(set(self.symbol_mapping.values())) != len(self.symbol_mapping):
            raise ValueError("engine symbol mapping must be bijective")
        unsafe = any(
            item.query_affecting and item.disposition != "represented" for item in self.dimensions
        )
        if (unsafe or omitted) and self.activation_status != "blocked":
            raise ValueError("lossy or incomplete projection must block execution")
        required = {
            (item.dimension, item.disposition)
            for item in self.dimensions
            if item.query_affecting and item.disposition != "represented"
        }
        actual = {(item.dimension, item.category) for item in self.activation_blockers}
        if missing := required - actual:
            raise ValueError(
                f"query-affecting semantic loss lacks typed blockers: {sorted(missing)}"
            )
        if omitted and not any(item.category == "omitted" for item in self.activation_blockers):
            raise ValueError("omitted semantic elements require an omitted activation blocker")
        if len({item.blocker_id for item in self.activation_blockers}) != len(
            self.activation_blockers
        ):
            raise ValueError("activation blocker identifiers must be unique")
        return self
