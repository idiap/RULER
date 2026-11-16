# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""End-user command contract for governed case-based reasoning."""

from __future__ import annotations

from click.testing import CliRunner

from ruler.cli import main


def test_cbr_cli_lists_retrieves_compares_adapts_and_verifies() -> None:
    runner = CliRunner()
    for arguments, marker in (
        (["cbr", "libraries"], '"count": 5'),
        (["cbr", "retrieve", "spending"], '"query_case_id"'),
        (
            [
                "cbr",
                "compare",
                "spending",
                "spend-precedent-microscope-009",
                "spend-precedent-compute-014",
            ],
            '"contributions"',
        ),
        (
            ["cbr", "adapt", "spending", "spend-precedent-microscope-009"],
            '"human_review_required": true',
        ),
        (["cbr", "verify", "spending"], '"action": "hold_order"'),
    ):
        result = runner.invoke(main, arguments)
        assert result.exit_code == 0, result.output
        assert marker in result.output


def test_cbr_cli_uniformly_rejects_unknown_cases() -> None:
    result = CliRunner().invoke(main, ["cbr", "show-case", "spending", "../secret"])
    assert result.exit_code != 0
    assert "case is unavailable" in result.output
    assert "Traceback" not in result.output
