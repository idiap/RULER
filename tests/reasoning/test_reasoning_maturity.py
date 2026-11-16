# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the mature reasoning closure layer.

This suite checks that solver flips, ASP-backed policy effects, package selection,
trace-locked explanations, candidate guardrails, and translation vocabulary alignment
remain visible in packets and validators.
"""

from __future__ import annotations

from ruler.kb.translation_control import (
    build_autoformalization_alignment_report,
    build_translation_glossary,
    build_vocabulary_predicate_map,
)


def test_translation_vocabulary_alignment_feeds_predicates() -> None:
    """Controlled translation terms should align to predicate candidates."""
    report = build_autoformalization_alignment_report()
    glossary = build_translation_glossary()
    predicate_map = build_vocabulary_predicate_map()

    assert report["translation_unit_count"] == 1
    assert all(check["status"] == "pass" for check in report["checks"])
    assert {entry.term_id for entry in glossary}
    assert {"power_disconnected_before_panel_removal/1"}.issubset(
        {entry.predicate for entry in predicate_map}
    )
