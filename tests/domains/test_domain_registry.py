# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from collections.abc import Mapping
from typing import Any

import pytest

from ruler.contracts.cases import CaseContext
from ruler.domains.base import (
    DomainTaxonomy,
    PredicateArgument,
    PredicateDescriptor,
    ValueTypeDescriptor,
)
from ruler.domains.registry import DomainPackRegistry


class InvalidPack:
    domain_id = "bad"
    schema_version = "2"
    document_kinds = frozenset({"document"})
    value_types: Mapping[str, ValueTypeDescriptor] = {}
    predicates = {
        "broken": PredicateDescriptor(
            predicate_id="broken",
            arguments=(PredicateArgument(name="x", value_type="not_registered"),),
            role="fact",
            description="broken",
        )
    }
    taxonomy = DomainTaxonomy(unit_types=("unit",), materiality_roles=("material",))
    translation_contracts = ()

    def load_case(self, payload: Mapping[str, Any]) -> CaseContext:
        return CaseContext.model_validate(payload)

    def scope_matches(self, rule_scope: Mapping[str, str], context: CaseContext) -> bool:
        return True


def test_invalid_predicate_registration_fails_before_use() -> None:
    with pytest.raises(ValueError, match="unknown value types"):
        DomainPackRegistry().register(InvalidPack())
