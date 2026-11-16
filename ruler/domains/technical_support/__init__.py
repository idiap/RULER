# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Technical-support domain pack."""

from ruler.domains.registry import DomainPackRegistry
from ruler.domains.technical_support.pack import (
    TECHNICAL_SUPPORT_DOMAIN_PACK,
    TechnicalSupportDomainPack,
)


def register_technical_support_domain(registry: DomainPackRegistry) -> TechnicalSupportDomainPack:
    registry.register(TECHNICAL_SUPPORT_DOMAIN_PACK)
    return TECHNICAL_SUPPORT_DOMAIN_PACK


__all__ = [
    "TECHNICAL_SUPPORT_DOMAIN_PACK",
    "TechnicalSupportDomainPack",
    "register_technical_support_domain",
]
