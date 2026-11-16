# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Typed Swiss VAT facts and evidence-dependent input-tax semantics."""

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


class FiscalDomainPack:
    domain_id = "fiscal"
    schema_version = "1.0"
    document_kinds = frozenset(
        {"tax_rate_schedule", "vat_invoice", "expense_evidence", "tax_review"}
    )
    value_types = {
        "vat_transaction": ValueTypeDescriptor(
            type_id="vat_transaction",
            scalar_kind="entity",
            description="VAT transaction or expense line",
        ),
        "tax_rate_percent": ValueTypeDescriptor(
            type_id="tax_rate_percent",
            scalar_kind="decimal",
            description="VAT rate percentage",
            unit_dimension="percent",
        ),
        "expense_category": ValueTypeDescriptor(
            type_id="expense_category",
            scalar_kind="string",
            description="Controlled VAT expense category",
        ),
        "input_tax_state": ValueTypeDescriptor(
            type_id="input_tax_state",
            scalar_kind="string",
            description="eligible, blocked, or unknown input-tax state",
        ),
    }
    predicates = {
        "tax_jurisdiction": _p(
            "tax_jurisdiction",
            "fact",
            "Jurisdiction governing the transaction.",
            ("transaction", "vat_transaction"),
            ("jurisdiction", "string"),
        ),
        "tax_rate": _p(
            "tax_rate",
            "fact",
            "Effective VAT rate for a classified line and date.",
            ("transaction", "vat_transaction"),
            ("rate", "tax_rate_percent"),
            ("effective_on", "date"),
        ),
        "expense_category": _p(
            "expense_category",
            "fact",
            "Reviewed line-level expense classification.",
            ("transaction", "vat_transaction"),
            ("category", "expense_category"),
        ),
        "business_purpose_evidenced": _p(
            "business_purpose_evidenced",
            "condition",
            "Business purpose has documentary support.",
            ("transaction", "vat_transaction"),
        ),
        "input_tax_status": _p(
            "input_tax_status",
            "effect",
            "Evidence-dependent input-tax conclusion.",
            ("transaction", "vat_transaction"),
            ("status", "input_tax_state"),
        ),
    }
    taxonomy = DomainTaxonomy(
        unit_types=("rate", "classification", "evidence", "deductibility", "rounding"),
        materiality_roles=("tax_calculation", "eligibility", "evidence", "temporal_applicability"),
    )
    translation_contracts = (
        TranslationContract(
            contract_id="swiss_vat_to_logic_v1",
            source_languages=("de", "fr", "it", "en"),
            target_language="en",
            required_checks=(
                "official_source",
                "effective_date",
                "line_classification",
                "rounding",
                "review_gate",
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


FISCAL_DOMAIN_PACK = FiscalDomainPack()
