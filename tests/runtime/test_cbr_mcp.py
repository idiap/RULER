# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import pytest

from ruler.runtime.mcp_server import (
    MCP_TOOL_NAMES,
    cbr_compare_cases,
    cbr_list_libraries,
    cbr_plan_adaptation,
    cbr_retrieve_cases,
    cbr_show_case,
    mcp_manifest,
)

CBR_TOOLS = {
    "ruler_cbr_list_libraries",
    "ruler_cbr_show_case",
    "ruler_cbr_retrieve",
    "ruler_cbr_compare",
    "ruler_cbr_plan_adaptation",
}


def test_cbr_helpers_remain_internal_to_the_product_surface() -> None:
    assert not CBR_TOOLS.intersection(MCP_TOOL_NAMES)
    assert not CBR_TOOLS.intersection(mcp_manifest()["tools"])


def test_mcp_cbr_list_show_and_retrieve_are_bounded_and_redacted() -> None:
    libraries = cbr_list_libraries()
    assert libraries["count"] == 5
    case = cbr_show_case("spending", "spend-precedent-microscope-009")
    assert case["subject_ref"] == "[redacted]"
    assert case["party_refs"] == "[redacted]"
    assert case["evidence_digests"] == "[redacted]"
    assert all(item["value"] == "[redacted]" for item in case["feature_states"])
    assert "/Users/" not in str(case)

    result = cbr_retrieve_cases("technical_support", top_k=2)
    assert len(result["retrieved"]) == 2
    assert result["read_only"] is True
    with pytest.raises(ValueError, match="top_k"):
        cbr_retrieve_cases("technical_support", top_k=11)


def test_mcp_cbr_compare_and_plan_cannot_execute_or_retain() -> None:
    comparison = cbr_compare_cases(
        "fiscal",
        "fiscal-precedent-mixed-travel-031",
        "fiscal-precedent-conference-018",
    )
    assert comparison["values_redacted"] is True
    plan = cbr_plan_adaptation("trade", "trade-precedent-enduser-missing-028")
    assert plan["executable"] is False
    assert plan["human_review_required"] is True
    assert all(item["requires_formal_verification"] for item in plan["operations"])
    assert "retain" not in plan
    assert "outcome" not in plan
