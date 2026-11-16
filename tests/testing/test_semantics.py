# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Golden, bounded-property, metamorphic, mutation, and differential tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings, strategies as st

from ruler.io import read_yaml
from ruler.paths import REPO_ROOT
from ruler.testing.semantics import (
    assert_differential_equivalence,
    bounded_benefit,
    changed_dependency_descendants,
)


def test_independently_authored_semantic_golden_cases() -> None:
    fixture = read_yaml(REPO_ROOT / "tests/fixtures/testing/semantic_cases.yaml")
    for case in fixture["cases"]:
        decision = bounded_benefit(
            conditions=case["conditions"],
            excluded=case["excluded"],
            exception_to_exclusion=case["exception_to_exclusion"],
            claimed=Decimal(case["claimed"]),
            service_fee=Decimal(case["service_fee"]),
            limit=Decimal(case["limit"]),
        )
        assert decision.eligible is case["expected_eligible"], case["id"]
        assert decision.amount == Decimal(case["expected_amount"]), case["id"]
        assert decision.trace.index("service_fee") < decision.trace.index("limit")


def test_bounded_numeric_properties_and_metamorphic_limit_rule() -> None:
    for claimed in map(Decimal, range(0, 5001, 137)):
        for service_fee in map(Decimal, (0, 100, 500)):
            low = bounded_benefit(
                conditions=[True],
                excluded=False,
                exception_to_exclusion=False,
                claimed=claimed,
                limit=Decimal(1000),
                service_fee=service_fee,
            )
            high = bounded_benefit(
                conditions=[True],
                excluded=False,
                exception_to_exclusion=False,
                claimed=claimed,
                limit=Decimal(1500),
                service_fee=service_fee,
            )
            assert Decimal(0) <= low.amount <= Decimal(1000)
            assert low.amount <= high.amount


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    claimed=st.integers(min_value=0, max_value=10_000),
    service_fee=st.integers(min_value=0, max_value=2_000),
    low_limit=st.integers(min_value=0, max_value=5_000),
    increment=st.integers(min_value=0, max_value=5_000),
)
def test_generated_limit_monotonicity(
    claimed: int, service_fee: int, low_limit: int, increment: int
) -> None:
    """Hypothesis explores and shrinks the numeric policy boundary space."""

    low = bounded_benefit(
        conditions=[True],
        excluded=False,
        exception_to_exclusion=False,
        claimed=Decimal(claimed),
        limit=Decimal(low_limit),
        service_fee=Decimal(service_fee),
    )
    high = bounded_benefit(
        conditions=[True],
        excluded=False,
        exception_to_exclusion=False,
        claimed=Decimal(claimed),
        limit=Decimal(low_limit + increment),
        service_fee=Decimal(service_fee),
    )
    assert Decimal(0) <= low.amount <= Decimal(low_limit)
    assert low.amount <= high.amount


def test_high_risk_negation_and_exception_mutants_are_killed() -> None:
    correct = bounded_benefit(
        conditions=[True],
        excluded=True,
        exception_to_exclusion=False,
        claimed=Decimal(2000),
        limit=Decimal(1000),
        service_fee=Decimal(0),
    )
    lost_exclusion = bounded_benefit(
        conditions=[True],
        excluded=False,
        exception_to_exclusion=False,
        claimed=Decimal(2000),
        limit=Decimal(1000),
        service_fee=Decimal(0),
    )
    removed_exception = bounded_benefit(
        conditions=[True],
        excluded=True,
        exception_to_exclusion=False,
        claimed=Decimal(2000),
        limit=Decimal(1000),
        service_fee=Decimal(0),
    )
    with_exception = bounded_benefit(
        conditions=[True],
        excluded=True,
        exception_to_exclusion=True,
        claimed=Decimal(2000),
        limit=Decimal(1000),
        service_fee=Decimal(0),
    )
    assert correct != lost_exclusion
    assert removed_exception != with_exception


def test_differential_target_mismatch_has_stable_target_and_case_code() -> None:
    cases = [1, 2, 3]
    assert_differential_equivalence(
        cases, lambda value: value * 2, {"asp": lambda value: value + value}
    )
    with pytest.raises(AssertionError, match=r"SEMANTIC_DIFFERENTIAL_MISMATCH:prolog:case\[1\]"):
        assert_differential_equivalence(
            cases,
            lambda value: value * 2,
            {"prolog": lambda value: value * 2 if value != 2 else 5},
        )


def test_source_drift_invalidates_exactly_dependency_descendants() -> None:
    graph = {
        "source:v1": {"span:1", "span:2"},
        "span:1": {"clause:1"},
        "clause:1": {"rule:1", "annotation:1"},
        "rule:1": {"release:1"},
        "unrelated": {"rule:other"},
    }
    assert changed_dependency_descendants(graph, {"source:v1"}) == {
        "source:v1",
        "span:1",
        "span:2",
        "clause:1",
        "rule:1",
        "annotation:1",
        "release:1",
    }
