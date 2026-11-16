# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Declarative domain-pack metadata for regulatory compliance evaluation."""

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


def _predicate(
    predicate_id: str,
    *arguments: tuple[str, str],
    role: str = "condition",
    description: str,
) -> PredicateDescriptor:
    return PredicateDescriptor.model_validate(
        dict(
            predicate_id=predicate_id,
            arguments=tuple(
                PredicateArgument(name=name, value_type=value_type)
                for name, value_type in arguments
            ),
            role=role,
            description=description,
        )
    )


class RegulatoryDomainPack:
    domain_id = "regulatory"
    schema_version = "2.0"
    document_kinds = frozenset({"regulation", "standard", "institutional_policy"})
    value_types = {
        "regulated_subject": ValueTypeDescriptor(
            type_id="regulated_subject",
            scalar_kind="entity",
            description="Actor governed by a normative instrument.",
        ),
    }
    predicates = {
        "in_scope": _predicate(
            "in_scope",
            ("subject", "regulated_subject"),
            description="The instrument applies to the subject.",
        ),
        "out_of_scope": _predicate(
            "out_of_scope",
            ("subject", "regulated_subject"),
            description="The instrument explicitly does not apply to the subject.",
        ),
        "submitted_notice": _predicate(
            "submitted_notice",
            ("subject", "regulated_subject"),
            description="The subject submitted the required notice.",
        ),
        "notice_missing": _predicate(
            "notice_missing",
            ("subject", "regulated_subject"),
            description="The required notice is explicitly recorded as missing.",
        ),
        "within_deadline": _predicate(
            "within_deadline",
            ("subject", "regulated_subject"),
            description="The regulated act occurred on or before the inclusive deadline.",
        ),
        "after_deadline": _predicate(
            "after_deadline",
            ("subject", "regulated_subject"),
            description="The regulated act is explicitly recorded after the deadline.",
        ),
        "restricted_action": _predicate(
            "restricted_action",
            ("subject", "regulated_subject"),
            description="The subject performed the action governed by a prohibition.",
        ),
        "authorized_exception": _predicate(
            "authorized_exception",
            ("subject", "regulated_subject"),
            role="exception",
            description="A higher-precedence exception is established.",
        ),
        "regulated_quantity": _predicate(
            "regulated_quantity",
            ("subject", "regulated_subject"),
            ("quantity", "integer"),
            description="Numeric quantity tested against a normative threshold.",
        ),
        "evaluation_outcome": _predicate(
            "evaluation_outcome",
            ("rule", "string"),
            ("subject", "regulated_subject"),
            ("status", "string"),
            role="effect",
            description="Release-pinned status produced for a normative rule.",
        ),
    }
    taxonomy = DomainTaxonomy(
        unit_types=(
            "scope",
            "definition",
            "obligation",
            "prohibition",
            "exception",
            "numeric_limit",
            "temporal_rule",
            "precedence",
        ),
        materiality_roles=("applicability", "compliance", "exception", "deadline", "threshold"),
    )
    translation_contracts = (
        TranslationContract(
            contract_id="regulatory_source_to_logic_v1",
            source_languages=("en",),
            target_language="en",
            required_checks=("exact_span", "modality", "numeric_temporal_boundary", "precedence"),
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


REGULATORY_DOMAIN_PACK = RegulatoryDomainPack()
