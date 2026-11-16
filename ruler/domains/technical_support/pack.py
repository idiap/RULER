# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Synthetic TC8 support rules with non-bypassable safety invariants."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ruler.contracts.cases import CaseContext
from ruler.domains.base import (
    DomainTaxonomy,
    PredicateArgument,
    PredicateDescriptor,
    TranslationContract,
    ValueTypeDescriptor,
)


def _p(identifier: str, role: str, description: str, *args: tuple[str, str]) -> PredicateDescriptor:
    return PredicateDescriptor.model_validate(
        dict(
            predicate_id=identifier,
            arguments=tuple(PredicateArgument(name=n, value_type=t) for n, t in args),
            role=role,
            description=description,
        )
    )


class TechnicalSupportDomainPack:
    domain_id = "technical_support"
    schema_version = "1.0"
    document_kinds = frozenset({"service_manual", "service_bulletin", "support_incident", "sla"})
    value_types = {
        "support_incident": ValueTypeDescriptor(
            type_id="support_incident",
            scalar_kind="entity",
            description="Customer support incident",
        ),
        "product_version": ValueTypeDescriptor(
            type_id="product_version",
            scalar_kind="string",
            description="Comparable semantic firmware version",
        ),
        "fault_code": ValueTypeDescriptor(
            type_id="fault_code",
            scalar_kind="string",
            description="Controlled diagnostic fault code",
        ),
        "procedure": ValueTypeDescriptor(
            type_id="procedure",
            scalar_kind="entity",
            description="Versioned diagnostic or repair procedure",
        ),
    }
    predicates = {
        "product_version": _p(
            "product_version",
            "fact",
            "Hardware and firmware compatibility identity.",
            ("incident", "support_incident"),
            ("version", "product_version"),
        ),
        "fault_code": _p(
            "fault_code",
            "fact",
            "Observed diagnostic fault code.",
            ("incident", "support_incident"),
            ("code", "fault_code"),
        ),
        "safety_interlock": _p(
            "safety_interlock",
            "constraint",
            "Safety interlock state; bypass is never an adaptation.",
            ("incident", "support_incident"),
            ("active", "boolean"),
        ),
        "procedure_applicable": _p(
            "procedure_applicable",
            "condition",
            "Procedure prerequisites match product and safety state.",
            ("incident", "support_incident"),
            ("procedure", "procedure"),
        ),
        "escalation_required": _p(
            "escalation_required",
            "effect",
            "Incident requires authorized-technician escalation.",
            ("incident", "support_incident"),
        ),
    }
    taxonomy = DomainTaxonomy(
        unit_types=("diagnostic", "procedure", "safety_invariant", "service_bulletin", "sla"),
        materiality_roles=("compatibility", "safety", "resolution", "escalation", "outcome"),
    )
    translation_contracts = (
        TranslationContract(
            contract_id="tc8_support_to_logic_v1",
            source_languages=("en",),
            target_language="en",
            required_checks=(
                "hardware_revision",
                "firmware_range",
                "safety_invariant",
                "technician_authority",
                "sla",
            ),
        ),
    )

    def load_case(self, payload: Mapping[str, Any]) -> CaseContext:
        return CaseContext(
            context_id=str(payload["context_id"]),
            domain_id=self.domain_id,
            subject_id=str(payload["subject_id"]),
            facts=dict(payload.get("facts", {})),
            attributes=dict(payload.get("attributes", {})),
        )

    def scope_matches(self, rule_scope: Mapping[str, str], context: CaseContext) -> bool:
        return all(str(context.attributes.get(key)) == value for key, value in rule_scope.items())


TECHNICAL_SUPPORT_DOMAIN_PACK = TechnicalSupportDomainPack()
