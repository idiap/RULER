# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Fiscal compliance domain pack."""

from ruler.domains.fiscal.pack import FISCAL_DOMAIN_PACK, FiscalDomainPack
from ruler.domains.registry import DomainPackRegistry


def register_fiscal_domain(registry: DomainPackRegistry) -> FiscalDomainPack:
    registry.register(FISCAL_DOMAIN_PACK)
    return FISCAL_DOMAIN_PACK


__all__ = ["FISCAL_DOMAIN_PACK", "FiscalDomainPack", "register_fiscal_domain"]
