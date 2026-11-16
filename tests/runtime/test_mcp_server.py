# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the MCP server facade.

The MCP layer exposes bounded, named RULER operations while keeping arbitrary shell
execution and workflow writes behind explicit controls.
"""

from __future__ import annotations

from ruler.runtime.mcp_server import (
    MCP_TOOL_NAMES,
    generative_api_config,
    generate_structured,
    guide_intent,
    mcp_manifest,
    route_intent,
    run_workflow,
    validation_gate,
)
from ruler.runtime.validation import validate_mcp_server


def test_mcp_manifest_is_bounded_and_read_safe_by_default() -> None:
    """The manifest should advertise only the intended safe tool surface."""
    manifest = mcp_manifest()

    assert manifest["tools"] == MCP_TOOL_NAMES
    assert manifest["safety"]["arbitrary_shell"] is False
    assert manifest["safety"]["read_only_by_default"] is True
    assert manifest["safety"]["workflow_writes_require_allow_write"] is True
    assert len(manifest["tools"]) == 4
    assert "ruler_run_workflow" not in manifest["tools"]


def test_mcp_route_validation_and_config_tools() -> None:
    """MCP tools should route, validate, and report config without writing by default."""
    assert (
        route_intent("run the framework as an mcp server")["selected_route_id"]
        == "mcp_server_runtime"
    )
    assert (
        route_intent("translate policy text to english")["selected_route_id"]
        == "controlled_translation"
    )
    assert validation_gate("api-config")["status"] == "pass"
    assert validation_gate("contracts")["status"] == "pass"
    assert run_workflow("workflow-router")["status"] == "blocked"
    assert generative_api_config()["provider"]["api_key_present"] is False
    assert validate_mcp_server() == [f"tools={len(MCP_TOOL_NAMES)}", "resources=0"]


def test_mcp_configured_generation_is_network_gated() -> None:
    result = generate_structured(
        workflow="explanation",
        prompt="Return a short explanation.",
        output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )

    assert result == {
        "status": "blocked",
        "reason": "configured generation requires allow_network=true",
        "workflow": "explanation",
    }


def test_mcp_orchestrator_is_advisory_and_offline_safe() -> None:
    result = guide_intent("translate source text into controlled English")

    assert result["status"] == "deterministic_only"
    assert result["selected_route_ids"] == ["controlled_translation"]
    assert result["receipt"]["skills_executed"] is False
    assert result["receipt"]["authority"] == "advisory"
