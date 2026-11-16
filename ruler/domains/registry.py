# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Fail-closed registry for domain packs."""

from __future__ import annotations

from ruler.domains.base import DomainPack, validate_domain_pack


class DomainPackRegistry:
    def __init__(self) -> None:
        self._packs: dict[str, DomainPack] = {}

    def register(self, pack: DomainPack) -> None:
        validate_domain_pack(pack)
        if pack.domain_id in self._packs:
            raise ValueError(f"domain pack already registered: {pack.domain_id}")
        self._packs[pack.domain_id] = pack

    def get(self, domain_id: str) -> DomainPack:
        try:
            return self._packs[domain_id]
        except KeyError as error:
            available = ", ".join(sorted(self._packs)) or "none"
            raise LookupError(
                f"unknown domain pack {domain_id!r}; registered domains: {available}"
            ) from error

    def registered_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._packs))


# Short canonical name for application composition roots. The longer export remains stable.
DomainRegistry = DomainPackRegistry
