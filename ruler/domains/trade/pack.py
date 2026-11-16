# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Fail-closed Swiss export-control representations."""

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


class TradeDomainPack:
    domain_id = "trade"
    schema_version = "1.0"
    document_kinds = frozenset(
        {"controlled_list_metadata", "export_review", "licence_record", "screening_evidence"}
    )
    value_types = {
        "shipment": ValueTypeDescriptor(
            type_id="shipment",
            scalar_kind="entity",
            description="Tangible or intangible export transaction",
        ),
        "classification_state": ValueTypeDescriptor(
            type_id="classification_state",
            scalar_kind="string",
            description="reviewed classification state",
        ),
        "freshness_state": ValueTypeDescriptor(
            type_id="freshness_state",
            scalar_kind="string",
            description="fresh, stale, or unknown screening state",
        ),
    }
    predicates = {
        "classification_status": _p(
            "classification_status",
            "fact",
            "Reviewed goods or technology classification.",
            ("shipment", "shipment"),
            ("status", "classification_state"),
        ),
        "listed_good": _p(
            "listed_good",
            "condition",
            "Product or technology is covered by a controlled-list release.",
            ("shipment", "shipment"),
        ),
        "end_user_known": _p(
            "end_user_known",
            "condition",
            "Ultimate end user is verified by evidence.",
            ("shipment", "shipment"),
        ),
        "screening_freshness": _p(
            "screening_freshness",
            "condition",
            "Sanctions screening freshness at release time.",
            ("shipment", "shipment"),
            ("status", "freshness_state"),
        ),
        "licence_required": _p(
            "licence_required",
            "effect",
            "Current rules require an export licence.",
            ("shipment", "shipment"),
        ),
        "shipment_releasable": _p(
            "shipment_releasable",
            "effect",
            "Human export-control review permits shipment.",
            ("shipment", "shipment"),
        ),
    }
    taxonomy = DomainTaxonomy(
        unit_types=(
            "classification",
            "controlled_list",
            "catch_all",
            "licensing",
            "screening",
            "technology_transfer",
        ),
        materiality_roles=("scope", "authorization", "evidence", "freshness", "shipment_hold"),
    )
    translation_contracts = (
        TranslationContract(
            contract_id="swiss_export_control_to_logic_v1",
            source_languages=("de", "fr", "it", "en"),
            target_language="en",
            required_checks=(
                "as_of_date",
                "classification",
                "end_use",
                "screening_freshness",
                "human_release",
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


TRADE_DOMAIN_PACK = TradeDomainPack()
