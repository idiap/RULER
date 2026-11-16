# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Validated declarative content supplied by the construction-fleet pack."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from ruler.applications.resource_portfolio.contracts import CoreStateRole
from ruler.contracts.common import StrictContract


class StateMapping(StrictContract):
    source_state: str
    core_role: CoreStateRole
    precedence: int = Field(ge=0)


class CapabilityDefinition(StrictContract):
    capability_id: str
    label: str
    output_unit: str


class ResourceTypeDefinition(StrictContract):
    resource_type_id: str
    label: str
    capability_ids: tuple[str, ...] = Field(min_length=1)


class SubstitutionDefinition(StrictContract):
    source_resource_type_id: str
    target_resource_type_id: str
    capability_id: str
    effectiveness_ratio: Decimal = Field(gt=0)
    required_context: dict[str, str] = Field(default_factory=dict)


class ConstructionFleetManifest(StrictContract):
    package_id: str
    domain_id: str
    schema_version: str
    vocabulary_version: str
    resource_types: tuple[ResourceTypeDefinition, ...]
    capabilities: tuple[CapabilityDefinition, ...]
    state_mappings: tuple[StateMapping, ...]
    substitutions: tuple[SubstitutionDefinition, ...] = ()
    actions: tuple[str, ...] = Field(min_length=1)
    units: dict[str, str] = Field(min_length=1)
    explanation_labels: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def references_are_closed(self) -> "ConstructionFleetManifest":
        if self.domain_id != "construction_fleet":
            raise ValueError("construction fleet manifest has the wrong domain_id")
        capability_ids = {item.capability_id for item in self.capabilities}
        resource_type_ids = {item.resource_type_id for item in self.resource_types}
        if len(capability_ids) != len(self.capabilities) or len(resource_type_ids) != len(
            self.resource_types
        ):
            raise ValueError("domain vocabulary identifiers must be unique")
        if len({item.source_state for item in self.state_mappings}) != len(self.state_mappings):
            raise ValueError("source state mappings must be unique")
        for item in self.resource_types:
            if not set(item.capability_ids) <= capability_ids:
                raise ValueError(
                    f"resource type {item.resource_type_id} refers to an unknown capability"
                )
        for item in self.capabilities:
            if item.output_unit not in self.units:
                raise ValueError(f"capability {item.capability_id} refers to an unknown unit")
        for item in self.substitutions:
            if (
                item.source_resource_type_id not in resource_type_ids
                or item.target_resource_type_id not in resource_type_ids
            ):
                raise ValueError("substitution refers to an unknown resource type")
            if item.capability_id not in capability_ids:
                raise ValueError("substitution refers to an unknown capability")
        return self


__all__ = [
    "CapabilityDefinition",
    "ConstructionFleetManifest",
    "ResourceTypeDefinition",
    "StateMapping",
    "SubstitutionDefinition",
]
