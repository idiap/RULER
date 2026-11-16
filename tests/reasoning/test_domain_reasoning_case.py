# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from collections.abc import Mapping
from typing import Any

import pytest

from ruler.contracts.cases import CaseContext
from ruler.domains.base import DomainTaxonomy
from ruler.domains.registry import DomainRegistry
from ruler.reasoning.reasoning_case import load_reasoning_case


class RegulatoryPack:
    domain_id = "regulatory"
    schema_version = "2.0"
    document_kinds = frozenset({"regulation"})
    value_types = {}
    predicates = {}
    taxonomy = DomainTaxonomy(unit_types=("provision",), materiality_roles=("compliance_impact",))
    translation_contracts = ()

    def load_case(self, payload: Mapping[str, Any]) -> CaseContext:
        return CaseContext.model_validate({**payload, "domain_id": self.domain_id})

    def scope_matches(self, rule_scope: Mapping[str, str], context: CaseContext) -> bool:
        return all(str(context.attributes.get(key)) == value for key, value in rule_scope.items())


def test_neutral_domain_case_loads_through_registry_without_retired_application_objects() -> None:
    registry = DomainRegistry()
    registry.register(RegulatoryPack())
    case = load_reasoning_case(
        domain_id="regulatory",
        corpus_id="workplace_safety",
        case_payload={
            "context_id": "inspection-1",
            "subject_id": "operator-1",
            "facts": {"employee_count": 50},
        },
        domain_registry=registry,
    )
    assert case.domain_id == "regulatory"
    assert case.corpus_id == "workplace_safety"
    assert case.context.facts["employee_count"] == 50
    assert not hasattr(case, "customer_context")
    assert not hasattr(case, "candidate_features")


def test_neutral_case_rejects_partial_or_conflicting_dispatch() -> None:
    registry = DomainRegistry()
    registry.register(RegulatoryPack())
    with pytest.raises(ValueError, match="required together"):
        load_reasoning_case(domain_id="regulatory", corpus_id="c")
    with pytest.raises(ValueError, match="cannot be combined"):
        load_reasoning_case(
            "provider_a",
            domain_id="regulatory",
            corpus_id="c",
            case_payload={"context_id": "x"},
            domain_registry=registry,
        )


def test_unknown_neutral_domain_fails_with_registered_inventory() -> None:
    registry = DomainRegistry()
    registry.register(RegulatoryPack())
    with pytest.raises(LookupError, match="registered domains: regulatory"):
        load_reasoning_case(
            domain_id="unknown",
            corpus_id="c",
            case_payload={"context_id": "x"},
            domain_registry=registry,
        )
