# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Synthetic internal procurement semantics for the spending demonstrator."""

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
            arguments=tuple(PredicateArgument(name=name, value_type=kind) for name, kind in args),
            role=role,
            description=description,
        )
    )


class SpendingDomainPack:
    domain_id = "spending"
    schema_version = "1.0"
    document_kinds = frozenset({"procurement_policy", "purchase_request", "approval_record"})
    value_types = {
        "money_chf": ValueTypeDescriptor(
            type_id="money_chf",
            scalar_kind="decimal",
            description="Swiss-franc amount",
            unit_dimension="currency",
        ),
        "purchase": ValueTypeDescriptor(
            type_id="purchase", scalar_kind="entity", description="Purchase request"
        ),
        "approval_kind": ValueTypeDescriptor(
            type_id="approval_kind", scalar_kind="string", description="Controlled approval kind"
        ),
    }
    predicates = {
        "budget_available": _p(
            "budget_available",
            "fact",
            "Approved budget available for the request.",
            ("request", "purchase"),
            ("amount", "money_chf"),
        ),
        "purchase_amount": _p(
            "purchase_amount",
            "fact",
            "Total non-split purchase commitment.",
            ("request", "purchase"),
            ("amount", "money_chf"),
        ),
        "quote_count": _p(
            "quote_count",
            "fact",
            "Comparable independent quotes obtained.",
            ("request", "purchase"),
            ("count", "integer"),
        ),
        "approval_present": _p(
            "approval_present",
            "condition",
            "A named approval is evidenced.",
            ("request", "purchase"),
            ("kind", "approval_kind"),
        ),
        "exception_approved": _p(
            "exception_approved",
            "exception",
            "An authorized procurement exception is evidenced.",
            ("request", "purchase"),
        ),
        "split_purchase_pattern": _p(
            "split_purchase_pattern",
            "constraint",
            "Related orders indicate prohibited threshold avoidance.",
            ("request", "purchase"),
        ),
        "purchase_releasable": _p(
            "purchase_releasable",
            "effect",
            "All current policy gates permit release.",
            ("request", "purchase"),
        ),
    }
    taxonomy = DomainTaxonomy(
        unit_types=("threshold", "approval", "exception", "budget", "conflict", "anti_splitting"),
        materiality_roles=(
            "eligibility",
            "evidence",
            "authorization",
            "financial_control",
            "audit",
        ),
    )
    translation_contracts = (
        TranslationContract(
            contract_id="spending_policy_to_logic_v1",
            source_languages=("en",),
            target_language="en",
            required_checks=(
                "amount_currency",
                "approval_authority",
                "exception_evidence",
                "anti_splitting",
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


SPENDING_DOMAIN_PACK = SpendingDomainPack()
