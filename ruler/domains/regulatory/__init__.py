# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Small redistribution-safe regulatory proof domain."""

from ruler.domains.regulatory.proof import (
    REGULATORY_RELEASE_ID,
    build_regulatory_program,
    regulatory_expected_rules,
    regulatory_registry,
)
from ruler.domains.regulatory.pack import REGULATORY_DOMAIN_PACK, RegulatoryDomainPack

__all__ = [
    "REGULATORY_RELEASE_ID",
    "REGULATORY_DOMAIN_PACK",
    "RegulatoryDomainPack",
    "build_regulatory_program",
    "regulatory_expected_rules",
    "regulatory_registry",
]
