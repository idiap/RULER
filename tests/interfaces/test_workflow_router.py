# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the generative workflow router.

The router is the natural-language interface to workflow commands and skills, so tests
pin representative intents to stable route identifiers.
"""

from __future__ import annotations

from ruler.interfaces.workflow_graphs import build_workflow_graph_model
from ruler.interfaces.workflow_router import (
    build_router_catalogue,
    guide_workflow_intent,
    route_workflow_intent,
    validate_workflow_router,
    write_workflow_router_artifacts,
)


class _Generator:
    provider = "test-provider"
    model = "test-model"

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.schema: dict[str, object] = {}

    def generate(self, *, prompt: str, output_schema: dict[str, object]) -> dict[str, object]:
        assert "Registered routes" in prompt
        self.schema = output_schema
        return self.result


def test_workflow_router_routes_plain_intents_to_known_workflows() -> None:
    """Plain user intents should resolve to the correct workflow route."""
    assert (
        route_workflow_intent("build an attractive dynamic inference interface").selected_route_id
        == "inference_control_dashboard"
    )
    assert (
        route_workflow_intent("show number of facts and rules").selected_route_id
        == "inference_control_dashboard"
    )
    assert (
        route_workflow_intent("translate policy text to english").selected_route_id
        == "controlled_translation"
    )
    assert (
        route_workflow_intent("harmonize vocabulary into predicates").selected_route_id
        == "controlled_translation"
    )
    assert (
        route_workflow_intent("make this runnable in Claude Code").selected_route_id
        == "claude_code_bridge"
    )
    assert (
        route_workflow_intent("make this runnable in OpenCode").selected_route_id
        == "opencode_bridge"
    )
    assert (
        route_workflow_intent("make this project cross platform").selected_route_id
        == "cross_platform_runtime"
    )
    assert (
        route_workflow_intent("run this as an MCP server").selected_route_id == "mcp_server_runtime"
    )
    assert (
        route_workflow_intent("configure generative API params").selected_route_id
        == "mcp_server_runtime"
    )
    assert (
        route_workflow_intent("visualize workflow graph").selected_route_id
        == "workflow_visualization"
    )
    assert (
        route_workflow_intent("run the full validation gate").selected_route_id == "full_validation"
    )


def test_workflow_router_catalogue_is_bounded_to_manifest() -> None:
    """The route catalogue should stay bounded and CLI-backed."""
    catalogue = build_router_catalogue()

    assert catalogue.route_count == 10
    assert catalogue.audit_hash.startswith("sha256:")
    assert all(route.workflow_commands for route in catalogue.routes)
    assert all(
        command.startswith("uv run ruler ")
        for route in catalogue.routes
        for command in route.workflow_commands
    )
    assert validate_workflow_router() == ["routes=10"]


def test_workflow_router_artifacts_and_graph_stack(tmp_path) -> None:
    """Router artifacts should be written and represented in the workflow graph."""
    paths = write_workflow_router_artifacts(tmp_path)
    model = build_workflow_graph_model()

    assert paths["json"].exists()
    assert paths["yaml"].exists()
    assert paths["markdown"].exists()
    assert paths["html"].exists()
    assert paths["sample_packets"].exists()
    assert "generative-workflow-router-loop" in model["stacks"]
    assert "ruler-generative-workflow-router" in model["skill_inventory"]["modeled"]


def test_orchestrator_is_offline_safe_and_does_not_execute_skills() -> None:
    packet = guide_workflow_intent("translate policy text to english")

    assert packet.status == "deterministic_only"
    assert packet.selected_route_ids == ["controlled_translation"]
    assert packet.receipt.mode == "deterministic"
    assert packet.receipt.skills_executed is False
    assert packet.receipt.selected_skill_ids == sorted(packet.routes[0].skills)
    assert "has not executed" in packet.router_notes[0]


def test_orchestrator_constrains_generation_to_canonical_route_metadata() -> None:
    generator = _Generator(
        {
            "interpreted_intent": "Compare business products using the governed workflow.",
            "selected_route_ids": ["controlled_translation"],
            "confidence": "high",
            "concise_guidance": ["Collect the required customer and provider inputs."],
            "clarification_question": "",
        }
    )

    packet = guide_workflow_intent(
        "Which workflow compares our commercial alternatives?",
        generator=generator,
    )

    assert packet.status == "guided"
    assert packet.receipt.provider == "test-provider"
    assert packet.receipt.schema_validated is True
    assert packet.receipt.skills_executed is False
    assert packet.routes[0].workflow_commands
    enum = generator.schema["properties"]["selected_route_ids"]["items"]["enum"]
    assert "controlled_translation" in enum


def test_orchestrator_rejects_an_invented_generated_route() -> None:
    generator = _Generator(
        {
            "interpreted_intent": "Run an invented operation.",
            "selected_route_ids": ["arbitrary_shell"],
            "confidence": "high",
            "concise_guidance": ["Run it."],
            "clarification_question": "",
        }
    )

    packet = guide_workflow_intent("do an unknown thing", generator=generator)

    assert packet.status == "unavailable"
    assert "arbitrary_shell" not in packet.selected_route_ids
    assert packet.receipt.authority == "advisory"
    assert packet.receipt.skills_executed is False
