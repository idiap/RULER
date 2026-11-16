# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Spending and procurement domain pack."""

from ruler.domains.registry import DomainPackRegistry
from ruler.domains.spending.pack import SPENDING_DOMAIN_PACK, SpendingDomainPack


def register_spending_domain(registry: DomainPackRegistry) -> SpendingDomainPack:
    registry.register(SPENDING_DOMAIN_PACK)
    return SPENDING_DOMAIN_PACK


__all__ = ["SPENDING_DOMAIN_PACK", "SpendingDomainPack", "register_spending_domain"]
