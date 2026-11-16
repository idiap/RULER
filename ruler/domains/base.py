# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-pack extension contracts used by the neutral core."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from ruler.contracts.cases import CaseContext
from ruler.contracts.common import StrictContract

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class ValueTypeDescriptor(StrictContract):
    type_id: str
    scalar_kind: Literal["boolean", "integer", "decimal", "string", "date", "datetime", "entity"]
    description: str
    unit_dimension: str | None = None


class PredicateArgument(StrictContract):
    name: str
    value_type: str
    unit: str | None = None


class PredicateDescriptor(StrictContract):
    predicate_id: str
    arguments: tuple[PredicateArgument, ...]
    role: Literal["fact", "condition", "effect", "exception", "constraint", "metadata"]
    description: str
    world_assumption: Literal["open", "closed"] = "open"

    @model_validator(mode="after")
    def signature_is_valid(self) -> "PredicateDescriptor":
        if not _IDENTIFIER.fullmatch(self.predicate_id):
            raise ValueError("predicate_id must be lower_snake_case")
        names = [argument.name for argument in self.arguments]
        if len(names) != len(set(names)):
            raise ValueError("predicate argument names must be unique")
        return self


class TranslationContract(StrictContract):
    contract_id: str
    source_languages: tuple[str, ...] = Field(min_length=1)
    target_language: str
    required_checks: tuple[str, ...] = Field(min_length=1)


class DomainTaxonomy(StrictContract):
    unit_types: tuple[str, ...] = Field(min_length=1)
    materiality_roles: tuple[str, ...] = Field(min_length=1)


@runtime_checkable
class DomainPack(Protocol):
    """Minimal behavior a domain contributes without reversing dependencies."""

    @property
    def domain_id(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    @property
    def document_kinds(self) -> frozenset[str]: ...

    @property
    def value_types(self) -> Mapping[str, ValueTypeDescriptor]: ...

    @property
    def predicates(self) -> Mapping[str, PredicateDescriptor]: ...

    @property
    def taxonomy(self) -> DomainTaxonomy: ...

    @property
    def translation_contracts(self) -> tuple[TranslationContract, ...]: ...

    def load_case(self, payload: Mapping[str, Any]) -> CaseContext: ...

    def scope_matches(self, rule_scope: Mapping[str, str], context: CaseContext) -> bool: ...


def validate_domain_pack(pack: DomainPack) -> None:
    """Validate extension declarations before a pack can affect compilation."""
    if not isinstance(pack, DomainPack):
        raise TypeError("domain pack does not implement the DomainPack protocol")
    if not _IDENTIFIER.fullmatch(pack.domain_id):
        raise ValueError("domain_id must be lower_snake_case")
    if not pack.schema_version.strip() or not pack.document_kinds:
        raise ValueError("domain packs require schema_version and document kinds")
    if set(pack.value_types) != {item.type_id for item in pack.value_types.values()}:
        raise ValueError("value type registry keys must match descriptor identifiers")
    if set(pack.predicates) != {item.predicate_id for item in pack.predicates.values()}:
        raise ValueError("predicate registry keys must match descriptor identifiers")
    known_types = {"boolean", "integer", "decimal", "string", "date", "datetime", "entity"}
    known_types.update(pack.value_types)
    unknown = sorted(
        {
            argument.value_type
            for predicate in pack.predicates.values()
            for argument in predicate.arguments
            if argument.value_type not in known_types
        }
    )
    if unknown:
        raise ValueError(f"predicate registry refers to unknown value types: {', '.join(unknown)}")
