# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""CBR-specific regulatory deployment vocabulary kept additive to the proof pack."""

from ruler.domains.base import PredicateArgument, PredicateDescriptor
from ruler.domains.regulatory.pack import RegulatoryDomainPack

REGULATORY_CBR_PREDICATES = {
    "deployer_role": PredicateDescriptor(
        predicate_id="deployer_role",
        arguments=(PredicateArgument(name="subject", value_type="regulated_subject"),),
        role="fact",
        description="Subject acts as deployer for the evaluated AI use.",
    ),
    "applicable_on": PredicateDescriptor(
        predicate_id="applicable_on",
        arguments=(
            PredicateArgument(name="rule", value_type="string"),
            PredicateArgument(name="date", value_type="date"),
        ),
        role="metadata",
        description="Rule applicability resolved for the case as-of date.",
    ),
    "oversight_assigned": PredicateDescriptor(
        predicate_id="oversight_assigned",
        arguments=(PredicateArgument(name="subject", value_type="regulated_subject"),),
        role="condition",
        description="Competent trained human oversight is assigned and evidenced.",
    ),
    "logs_retained": PredicateDescriptor(
        predicate_id="logs_retained",
        arguments=(
            PredicateArgument(name="subject", value_type="regulated_subject"),
            PredicateArgument(name="months", value_type="integer"),
        ),
        role="condition",
        description="Logging and documented retention controls are enabled.",
    ),
    "affected_person_informed": PredicateDescriptor(
        predicate_id="affected_person_informed",
        arguments=(PredicateArgument(name="subject", value_type="regulated_subject"),),
        role="condition",
        description="Required affected-person information is evidenced.",
    ),
    "deployment_permitted": PredicateDescriptor(
        predicate_id="deployment_permitted",
        arguments=(PredicateArgument(name="subject", value_type="regulated_subject"),),
        role="effect",
        description="Current effective deployer-control release permits operational deployment.",
    ),
}


class RegulatoryCBRDomainPack(RegulatoryDomainPack):
    """Opt-in regulatory pack extension for deployment CBR journeys."""

    schema_version = "2.1-cbr"
    document_kinds = RegulatoryDomainPack.document_kinds | frozenset(
        {"ai_deployment_record", "conformity_evidence", "oversight_record"}
    )
    predicates = {**RegulatoryDomainPack.predicates, **REGULATORY_CBR_PREDICATES}


REGULATORY_CBR_DOMAIN_PACK = RegulatoryCBRDomainPack()

__all__ = [
    "REGULATORY_CBR_DOMAIN_PACK",
    "REGULATORY_CBR_PREDICATES",
    "RegulatoryCBRDomainPack",
]
