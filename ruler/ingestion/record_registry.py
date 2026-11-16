# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Registry-driven parsing of domain-owned ingestion records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class RecordParser(Protocol):
    """Parser supplied by a domain pack for one versioned record type."""

    def __call__(self, payload: Mapping[str, Any]) -> BaseModel: ...


class RecordParserRegistry:
    """Fail-closed parser lookup keyed by domain, record type, and schema version."""

    def __init__(self) -> None:
        self._parsers: dict[tuple[str, str, str], RecordParser] = {}

    def register(
        self,
        *,
        domain_id: str,
        record_type: str,
        schema_version: str,
        parser: RecordParser,
    ) -> None:
        if not all(value.strip() for value in (domain_id, record_type, schema_version)):
            raise ValueError("parser coordinates must not be blank")
        if not callable(parser):
            raise TypeError("record parser must be callable")
        key = (domain_id, record_type, schema_version)
        if key in self._parsers:
            raise ValueError(f"record parser already registered: {key}")
        self._parsers[key] = parser

    def parse(
        self,
        *,
        domain_id: str,
        record_type: str,
        schema_version: str,
        payload: Mapping[str, Any],
    ) -> BaseModel:
        key = (domain_id, record_type, schema_version)
        try:
            parser = self._parsers[key]
        except KeyError as error:
            raise LookupError(f"unknown record parser: {key}") from error
        result = parser(payload)
        if not isinstance(result, BaseModel):
            raise TypeError(f"record parser {key} returned a non-model value")
        return result

    def registered_keys(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(sorted(self._parsers))
