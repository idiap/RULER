# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Construction-fleet domain vocabulary and mapping implementation."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from ruler.applications.resource_portfolio.contracts import CoreStateRole, DecisionType, Quantity
from ruler.contracts.cases import CaseContext
from ruler.domains.base import (
    DomainTaxonomy,
    PredicateArgument,
    PredicateDescriptor,
    TranslationContract,
    ValueTypeDescriptor,
)
from ruler.domains.construction_fleet.contracts import ConstructionFleetManifest
from ruler.io import read_yaml
from ruler.paths import REPO_ROOT

_DATA_ROOT = REPO_ROOT / "data" / "domains" / "construction_fleet"


def load_domain_manifest(path: Path | None = None) -> ConstructionFleetManifest:
    """Load and strictly validate the reviewer-authored domain manifest."""
    selected = path or (_DATA_ROOT / "manifest.yaml")
    return ConstructionFleetManifest.model_validate(read_yaml(selected))


class ConstructionFleetDomainPack:
    """Executable construction specialization without leaking into neutral code."""

    domain_id = "construction_fleet"
    schema_version = "1.0"
    document_kinds = frozenset(
        {"fleet_master_data", "telematics_event", "work_plan", "service_record", "rental_offer"}
    )
    value_types = {
        "resource": ValueTypeDescriptor(
            type_id="resource",
            scalar_kind="entity",
            description="Individually identified fleet resource",
        ),
        "capability": ValueTypeDescriptor(
            type_id="capability",
            scalar_kind="entity",
            description="Fleet-delivered operational capability",
        ),
        "work_unit": ValueTypeDescriptor(
            type_id="work_unit",
            scalar_kind="entity",
            description="Construction work package or project phase",
        ),
        "quantity": ValueTypeDescriptor(
            type_id="quantity",
            scalar_kind="decimal",
            description="Unit-bearing planning quantity",
            unit_dimension="domain_declared",
        ),
    }
    predicates = {
        "resource_provides": PredicateDescriptor(
            predicate_id="resource_provides",
            arguments=(
                PredicateArgument(name="resource", value_type="resource"),
                PredicateArgument(name="capability", value_type="capability"),
            ),
            role="fact",
            description="A configured resource provides a capability.",
            world_assumption="closed",
        ),
        "activity_requires": PredicateDescriptor(
            predicate_id="activity_requires",
            arguments=(
                PredicateArgument(name="work_unit", value_type="work_unit"),
                PredicateArgument(name="capability", value_type="capability"),
                PredicateArgument(name="amount", value_type="quantity", unit="productive_hour"),
            ),
            role="constraint",
            description="A work unit requires a unit-bearing amount of capability.",
        ),
        "resource_eligible": PredicateDescriptor(
            predicate_id="resource_eligible",
            arguments=(
                PredicateArgument(name="resource", value_type="resource"),
                PredicateArgument(name="work_unit", value_type="work_unit"),
            ),
            role="effect",
            description="A resource is eligible for assignment to a work unit.",
            world_assumption="closed",
        ),
        "backup_required": PredicateDescriptor(
            predicate_id="backup_required",
            arguments=(
                PredicateArgument(name="work_unit", value_type="work_unit"),
                PredicateArgument(name="capability", value_type="capability"),
            ),
            role="constraint",
            description="A work unit requires independently mobilizable backup capability.",
        ),
    }
    taxonomy = DomainTaxonomy(
        unit_types=(
            "classification",
            "eligibility",
            "requirement",
            "hard_policy",
            "soft_preference",
        ),
        materiality_roles=("safety", "capacity", "service", "cost", "resilience", "approval"),
    )
    translation_contracts = (
        TranslationContract(
            contract_id="construction_fleet_source_to_ir_v1",
            source_languages=("en", "fr", "de"),
            target_language="typed_resource_rule_ir",
            required_checks=(
                "entity_resolution",
                "numeric_unit_time",
                "scope",
                "exception",
                "authority",
            ),
        ),
    )

    def __init__(self, manifest_path: Path | None = None) -> None:
        self.manifest = load_domain_manifest(manifest_path)
        self._state_map = {
            item.source_state: item.core_role for item in self.manifest.state_mappings
        }
        aliases = read_yaml(_DATA_ROOT / "mappings" / "source_states.yaml")
        if not isinstance(aliases, dict):
            raise ValueError("source state mapping must be a mapping")
        unknown_targets = sorted(set(aliases.values()) - set(self._state_map))
        if unknown_targets:
            raise ValueError(
                f"source state mapping has unknown targets: {', '.join(unknown_targets)}"
            )
        self._source_aliases = {str(key).upper(): str(value) for key, value in aliases.items()}

    def load_case(self, payload: Mapping[str, Any]) -> CaseContext:
        """Project a construction planning case into the neutral case surface."""
        context_id = str(payload.get("context_id", "")).strip()
        if not context_id:
            raise ValueError("construction fleet case requires context_id")
        return CaseContext(
            context_id=context_id,
            domain_id=self.domain_id,
            subject_id=str(payload.get("resource_id")) if payload.get("resource_id") else None,
            facts=dict(payload.get("facts", {})),
            event_facts=tuple(payload.get("event_facts", ())),
            parties={
                str(key): str(value) for key, value in dict(payload.get("parties", {})).items()
            },
            attributes=dict(payload.get("attributes", {})),
        )

    def scope_matches(self, rule_scope: Mapping[str, str], context: CaseContext) -> bool:
        return all(
            key == "domain_id"
            and value == context.domain_id
            or str(context.attributes.get(key)) == value
            for key, value in rule_scope.items()
        )

    def map_source_state(self, source_state: str) -> CoreStateRole:
        """Map a source state fail-closed; unknown values remain explicitly UNKNOWN."""
        normalized = source_state.strip().upper()
        normalized = self._source_aliases.get(normalized, normalized)
        return self._state_map.get(normalized, CoreStateRole.UNKNOWN)

    def convert_quantity(self, quantity: Quantity, target_unit: str) -> Quantity:
        """Convert through the manifest's dimension and scale declarations."""
        try:
            source_dimension = self.manifest.units[quantity.unit]
            target_dimension = self.manifest.units[target_unit]
        except KeyError as error:
            raise ValueError(f"unknown construction-fleet unit: {error.args[0]}") from error
        if source_dimension != target_dimension:
            raise ValueError(f"cannot convert {source_dimension} to {target_dimension}")
        scales = {
            "minute": Decimal("0.01666666666666666666666666667"),
            "hour": Decimal("1"),
            "day": Decimal("24"),
            "week": Decimal("168"),
            "productive_hour": Decimal("1"),
            "CHF": Decimal("1"),
            "m3": Decimal("1"),
            "litre": Decimal("1"),
            "unit": Decimal("1"),
            "ratio": Decimal("1"),
        }
        if quantity.unit not in scales or target_unit not in scales:
            if quantity.unit == target_unit:
                return quantity
            raise ValueError("unit has no declared conversion scale")
        return Quantity(
            value=quantity.value * scales[quantity.unit] / scales[target_unit], unit=target_unit
        )

    def validate_action(self, action: DecisionType | str) -> DecisionType:
        parsed = action if isinstance(action, DecisionType) else DecisionType(action)
        if parsed.value not in self.manifest.actions:
            raise ValueError(f"action {parsed.value} is not enabled by the domain pack")
        return parsed

    def explanation_label(self, identifier: str) -> str:
        return self.manifest.explanation_labels.get(
            identifier, identifier.replace("_", " ").title()
        )


CONSTRUCTION_FLEET_DOMAIN_PACK = ConstructionFleetDomainPack()

__all__ = ["CONSTRUCTION_FLEET_DOMAIN_PACK", "ConstructionFleetDomainPack", "load_domain_manifest"]
