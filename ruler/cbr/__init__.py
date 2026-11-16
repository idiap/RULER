# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Transparent, rule-gated case-based reasoning."""

from ruler.cbr.contracts import *  # noqa: F403
from ruler.cbr.registry import FeatureRegistry
from ruler.cbr.service import CBRService

__all__ = ["CBRService", "FeatureRegistry"]
