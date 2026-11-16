# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for complete, honest formalization accounting artifacts."""

from __future__ import annotations

from ruler.kb.formalization_artifacts import (
    build_formalization_coverage_artifacts,
    validate_formalization_coverage,
    write_formalization_coverage_artifacts,
)
from ruler.kb.formalization_wave import REQUIRED_SKILL_SEQUENCE


def test_coverage_accounts_for_every_published_assertion_and_wave() -> None:
    artifacts = build_formalization_coverage_artifacts()
    inventory = artifacts["inventory"]
    coverage = artifacts["coverage"]
    wave_plan = artifacts["wave_plan"]

    expected = inventory["expected_assertion_count"]
    assert expected == len(inventory["items"])
    assert coverage["totals"]["source_assertions"] == expected
    assert coverage["totals"]["unresolved_units"] == expected
    assert sum(wave["assertion_count"] for wave in wave_plan["waves"]) == expected
    assert all(
        wave["required_skill_sequence"] == list(REQUIRED_SKILL_SEQUENCE)
        for wave in wave_plan["waves"]
    )
    assert artifacts["completion"]["promotion_blocked"] is True


def test_coverage_writer_emits_inventory_metrics_plan_and_report(tmp_path) -> None:
    paths = write_formalization_coverage_artifacts(tmp_path)

    assert set(paths) == {"inventory", "coverage", "wave_plan", "report"}
    report = paths["report"].read_text(encoding="utf-8")
    expected = build_formalization_coverage_artifacts()["inventory"]["expected_assertion_count"]
    assert f"Published assertions: {expected}" in report
    assert "Promotion blocked: true" in report
    assert validate_formalization_coverage()[-1] == "skills=reused"
