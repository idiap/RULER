# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Trade-control domain pack."""

from ruler.domains.registry import DomainPackRegistry
from ruler.domains.trade.pack import TRADE_DOMAIN_PACK, TradeDomainPack


def register_trade_domain(registry: DomainPackRegistry) -> TradeDomainPack:
    registry.register(TRADE_DOMAIN_PACK)
    return TRADE_DOMAIN_PACK


__all__ = ["TRADE_DOMAIN_PACK", "TradeDomainPack", "register_trade_domain"]
