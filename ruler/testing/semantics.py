# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Small deterministic semantic oracles for mutation/metamorphic testing."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BenefitDecision:
    eligible: bool
    amount: Decimal
    trace: tuple[str, ...]


def bounded_benefit(
    *,
    conditions: Iterable[bool],
    excluded: bool,
    exception_to_exclusion: bool,
    claimed: Decimal,
    limit: Decimal,
    service_fee: Decimal,
) -> BenefitDecision:
    """Independent executable oracle: service_fee precedes the policy limit."""
    eligible = all(conditions) and (not excluded or exception_to_exclusion)
    amount = min(max(claimed - service_fee, Decimal(0)), limit) if eligible else Decimal(0)
    trace = ("conditions", "exclusion_exception", "service_fee", "limit")
    return BenefitDecision(eligible, amount, trace)


def assert_differential_equivalence(
    cases: Iterable[object],
    canonical: Callable[[object], object],
    targets: dict[str, Callable[[object], object]],
) -> None:
    """Compare every compiled target against an independently authored oracle."""
    for index, case in enumerate(cases):
        expected = canonical(case)
        for name, target in targets.items():
            actual = target(case)
            if actual != expected:
                raise AssertionError(f"SEMANTIC_DIFFERENTIAL_MISMATCH:{name}:case[{index}]")


def changed_dependency_descendants(graph: dict[str, set[str]], changed: set[str]) -> set[str]:
    """Compute the exact transitive invalidation closure."""
    invalidated = set(changed)
    frontier = list(changed)
    while frontier:
        node = frontier.pop()
        for descendant in graph.get(node, set()):
            if descendant not in invalidated:
                invalidated.add(descendant)
                frontier.append(descendant)
    return invalidated
