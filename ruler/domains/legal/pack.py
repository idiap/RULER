# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Declarative legal interpretation domain pack."""

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
    predicate_id: str, *arguments: tuple[str, str], role: str = "condition", description: str
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


class LegalDomainPack:
    domain_id = "legal"
    schema_version = "1.0"
    document_kinds = frozenset(
        {"constitution", "statute", "regulation", "judgment", "legal_commentary", "contract"}
    )
    value_types = {
        "legal_actor": ValueTypeDescriptor(
            type_id="legal_actor",
            scalar_kind="entity",
            description="Party, court, authority, or other legally relevant actor.",
        ),
        "legal_authority": ValueTypeDescriptor(
            type_id="legal_authority",
            scalar_kind="entity",
            description="Versioned authority with jurisdiction, rank, and binding posture.",
        ),
        "legal_claim": ValueTypeDescriptor(
            type_id="legal_claim",
            scalar_kind="entity",
            description="Atomic candidate legal proposition.",
        ),
        "legal_concept": ValueTypeDescriptor(
            type_id="legal_concept",
            scalar_kind="entity",
            description="Source-grounded concept sense subject to boundary review.",
        ),
    }
    predicates = {
        "authority_applies": _predicate(
            "authority_applies",
            ("authority", "legal_authority"),
            ("actor", "legal_actor"),
            description="Authority applies after jurisdictional, temporal, and scope review.",
        ),
        "supports_claim": _predicate(
            "supports_claim",
            ("authority", "legal_authority"),
            ("claim", "legal_claim"),
            description="A source-bound authority supports a candidate claim.",
        ),
        "defeats_claim": _predicate(
            "defeats_claim",
            ("defeater", "legal_claim"),
            ("claim", "legal_claim"),
            role="exception",
            description="A live exception or counterargument defeats support for a claim.",
        ),
        "distinguishes_precedent": _predicate(
            "distinguishes_precedent",
            ("claim", "legal_claim"),
            ("authority", "legal_authority"),
            role="exception",
            description="A reviewed material distinction limits a precedent analogy.",
        ),
        "burden_discharged": _predicate(
            "burden_discharged",
            ("actor", "legal_actor"),
            ("claim", "legal_claim"),
            description="Evidence meets the declared burden and standard for an issue.",
        ),
        "concept_instance": _predicate(
            "concept_instance",
            ("concept", "legal_concept"),
            ("claim", "legal_claim"),
            description="A source-grounded instance falls within a reviewed concept reading.",
        ),
        "candidate_conclusion": _predicate(
            "candidate_conclusion",
            ("claim", "legal_claim"),
            role="effect",
            description="A bounded candidate conclusion, never a final legal determination.",
        ),
    }
    taxonomy = DomainTaxonomy(
        unit_types=(
            "source_expression",
            "authority",
            "material_fact",
            "normative_position",
            "holding",
            "interpretation",
            "warrant",
            "defeater",
            "burden",
            "remedy",
            "proof_obligation",
        ),
        materiality_roles=(
            "jurisdiction",
            "authority_hierarchy",
            "temporal_validity",
            "applicability",
            "interpretation",
            "fact_application",
            "defeasibility",
            "burden",
            "remedy",
            "assurance",
        ),
    )
    translation_contracts = (
        TranslationContract(
            contract_id="legal_source_to_candidate_semantics_v1",
            source_languages=("de", "fr", "it", "rm", "en"),
            target_language="en",
            required_checks=(
                "exact_span",
                "source_version",
                "jurisdiction",
                "authority_rank",
                "modality",
                "concept_sense",
                "translation_variance",
                "defeaters",
                "candidate_commitment",
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


LEGAL_DOMAIN_PACK = LegalDomainPack()
