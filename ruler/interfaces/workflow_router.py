# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Generative workflow router surface. It maps user intents to bounded workflow routes,
required skills, commands, and validations for controlled agent execution.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ruler.io import load_model_list, read_yaml, stable_hash, write_text, write_yaml
from ruler.paths import BUILD_DIR, HOOKS_FILE, REPO_ROOT, SKILL_HOOKS_FILE, USE_CASES_DIR
from ruler.schemas import SkillHookBinding, WorkflowHook
from ruler.runtime.skill_inventory import discover_skill_files
from ruler.runtime.api_config import load_generative_api_config
from ruler.runtime.generative_transport import (
    ConfiguredApiTransport,
    ConfiguredApiTransportError,
)

ROUTER_FILE = USE_CASES_DIR / "workflow_router.yaml"
ROUTER_DIR = BUILD_DIR / "workflow_router"


class WorkflowRoute(BaseModel):
    """Typed workflow route artifact used by the workflow router workflow."""

    model_config = ConfigDict(extra="forbid")

    route_id: str
    title: str
    description: str
    intent_patterns: list[str] = Field(min_length=1)
    hook: str
    workflow_commands: list[str] = Field(min_length=1)
    skills: list[str] = Field(min_length=1)
    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)


class RouteCandidate(BaseModel):
    """Typed route candidate artifact used by the workflow router workflow."""

    model_config = ConfigDict(extra="forbid")

    route_id: str
    title: str
    score: int
    matched_terms: list[str]
    hook: str
    skills: list[str]
    workflow_commands: list[str]
    validation_commands: list[str]
    expected_outputs: list[str]


class RouterPacket(BaseModel):
    """Typed router packet artifact used by the workflow router workflow."""

    model_config = ConfigDict(extra="forbid")

    query: str
    selected_route_id: str
    candidates: list[RouteCandidate]
    router_notes: list[str]
    audit_hash: str


class RouterCatalogue(BaseModel):
    """Collection artifact that organizes workflow router outputs."""

    model_config = ConfigDict(extra="forbid")

    catalogue_id: str
    route_count: int
    routes: list[WorkflowRoute]
    generated_from: list[str]
    audit_hash: str


class GenerativeRouteProposal(BaseModel):
    """Schema-constrained, advisory interpretation returned by a configured model."""

    model_config = ConfigDict(extra="forbid")

    interpreted_intent: str = Field(min_length=1, max_length=1000)
    selected_route_ids: list[str] = Field(max_length=3)
    confidence: Literal["high", "medium", "low"]
    concise_guidance: list[str] = Field(min_length=1, max_length=4)
    clarification_question: str = Field(max_length=500)


class OrchestratorReceipt(BaseModel):
    """Artifact-level provenance for a route interpretation, without model reasoning."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["deterministic", "generative"]
    provider: str | None = None
    model: str | None = None
    schema_validated: bool
    catalogue_hash: str
    response_hash: str | None = None
    selected_route_ids: list[str] = Field(default_factory=list)
    selected_skill_ids: list[str] = Field(default_factory=list)
    skills_executed: bool = False
    authority: Literal["advisory"] = "advisory"


class GuidedRoutePacket(BaseModel):
    """Safe orchestrator response combining interpretation with canonical routes."""

    model_config = ConfigDict(extra="forbid")

    query: str
    status: Literal["deterministic_only", "guided", "unavailable"]
    interpreted_intent: str
    confidence: Literal["high", "medium", "low", "not_generated"]
    selected_route_ids: list[str]
    routes: list[WorkflowRoute]
    deterministic_candidates: list[RouteCandidate]
    guidance: list[str]
    clarification_question: str
    receipt: OrchestratorReceipt
    router_notes: list[str]
    audit_hash: str


class _StructuredGenerator(Protocol):
    provider: str
    model: str

    def generate(
        self, *, prompt: str, output_schema: Mapping[str, object]
    ) -> Mapping[str, object]: ...


def load_workflow_routes() -> list[WorkflowRoute]:
    """Load workflow routes for the workflow router workflow."""
    return load_model_list(ROUTER_FILE, WorkflowRoute)


def route_workflow_intent(query: str, top_k: int = 3) -> RouterPacket:
    """Route workflow intent for the workflow router workflow."""
    routes = load_workflow_routes()
    scored = sorted(
        (_score_route(query, route) for route in routes),
        key=lambda item: (item.score, len(item.matched_terms), item.route_id),
        reverse=True,
    )
    candidates = [candidate for candidate in scored if candidate.score > 0][:top_k]
    selected = candidates[0] if candidates else None
    packet = RouterPacket(
        query=query,
        selected_route_id=selected.route_id if selected else "none",
        candidates=candidates,
        router_notes=[
            "Router is advisory: execute only known commands and keep hook validators authoritative.",
            "Low or zero scores should be treated as a request for human route review.",
        ],
        audit_hash="sha256:pending",
    )
    return packet.model_copy(
        update={"audit_hash": stable_hash(packet.model_dump(mode="json", exclude={"audit_hash"}))}
    )


def guide_workflow_intent(
    query: str,
    *,
    top_k: int = 3,
    allow_network: bool = False,
    env: Mapping[str, str] | None = None,
    generator: _StructuredGenerator | None = None,
) -> GuidedRoutePacket:
    """Interpret prose and guide it to registered workflows without executing them.

    Offline operation returns the deterministic router result. Generative guidance is
    attempted only with explicit network authorization (or an injected, schema-aware
    generator used by tests/embedded callers). Model-selected identifiers are checked
    against the trusted catalogue and all executable metadata comes from that catalogue.
    """

    if not query.strip() or len(query) > 16_000:
        raise ValueError("query must contain 1 to 16000 characters")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10")
    deterministic = route_workflow_intent(query, top_k=top_k)
    catalogue = build_router_catalogue()
    route_by_id = {route.route_id: route for route in catalogue.routes}
    fallback_ids = (
        [deterministic.selected_route_id] if deterministic.selected_route_id in route_by_id else []
    )
    if generator is None and not allow_network:
        return _guided_packet(
            query=query,
            status="deterministic_only",
            interpreted_intent=query,
            selected_route_ids=fallback_ids,
            route_by_id=route_by_id,
            deterministic=deterministic,
            guidance=[
                "Review the canonical workflow, skills, inputs, outputs, and validation gates below.",
                "Enable configured network generation explicitly for semantic interpretation and disambiguation.",
            ],
            clarification_question=(
                "Which RULER outcome should this request produce?" if not fallback_ids else ""
            ),
            receipt=OrchestratorReceipt(
                mode="deterministic",
                schema_validated=False,
                catalogue_hash=catalogue.audit_hash,
            ),
            confidence="not_generated",
        )

    try:
        if generator is None:
            config = load_generative_api_config(env=env)
            generator = ConfiguredApiTransport(
                config.selected_provider("workflow_routing"), env=env
            )
        schema = _proposal_schema(sorted(route_by_id))
        raw = generator.generate(
            prompt=_orchestrator_prompt(query, catalogue.routes, deterministic),
            output_schema=schema,
        )
        proposal = GenerativeRouteProposal.model_validate(raw)
        unknown = sorted(set(proposal.selected_route_ids).difference(route_by_id))
        if unknown:
            raise ValueError(f"provider selected unknown route identifiers: {', '.join(unknown)}")
    except (ConfiguredApiTransportError, KeyError, OSError, ValueError) as exc:
        return _guided_packet(
            query=query,
            status="unavailable",
            interpreted_intent=query,
            selected_route_ids=fallback_ids,
            route_by_id=route_by_id,
            deterministic=deterministic,
            guidance=[
                "Generative interpretation was unavailable; use the deterministic candidate only after reviewing it.",
                f"Fail-closed reason: {exc}",
            ],
            clarification_question=(
                "Which RULER outcome should this request produce?" if not fallback_ids else ""
            ),
            receipt=OrchestratorReceipt(
                mode="deterministic",
                schema_validated=False,
                catalogue_hash=catalogue.audit_hash,
            ),
            confidence="not_generated",
        )

    response_hash = stable_hash(proposal.model_dump(mode="json"))
    return _guided_packet(
        query=query,
        status="guided",
        interpreted_intent=proposal.interpreted_intent,
        selected_route_ids=proposal.selected_route_ids,
        route_by_id=route_by_id,
        deterministic=deterministic,
        guidance=proposal.concise_guidance,
        clarification_question=proposal.clarification_question,
        receipt=OrchestratorReceipt(
            mode="generative",
            provider=generator.provider,
            model=generator.model,
            schema_validated=True,
            catalogue_hash=catalogue.audit_hash,
            response_hash=response_hash,
        ),
        confidence=proposal.confidence,
    )


def build_router_catalogue() -> RouterCatalogue:
    """Build router catalogue for the workflow router workflow."""
    routes = load_workflow_routes()
    catalogue = RouterCatalogue(
        catalogue_id="ruler_workflow_router_catalogue",
        route_count=len(routes),
        routes=routes,
        generated_from=[
            str(ROUTER_FILE.relative_to(REPO_ROOT)),
            str(HOOKS_FILE.relative_to(REPO_ROOT)),
            str(SKILL_HOOKS_FILE.relative_to(REPO_ROOT)),
        ],
        audit_hash="sha256:pending",
    )
    return catalogue.model_copy(
        update={
            "audit_hash": stable_hash(catalogue.model_dump(mode="json", exclude={"audit_hash"}))
        }
    )


def write_workflow_router_artifacts(output_dir: Path | None = None) -> dict[str, Path]:
    """Write workflow router artifacts for the workflow router workflow."""
    base = output_dir or ROUTER_DIR
    base.mkdir(parents=True, exist_ok=True)
    catalogue = build_router_catalogue()
    sample_packets = [
        route_workflow_intent("build realistic customer demonstrators"),
        route_workflow_intent("run semantic preservation and gates"),
        route_workflow_intent("create a human intelligible reasoning log"),
        route_workflow_intent("show inference counts in a dynamic interface"),
        route_workflow_intent("translate policy text to english with fidelity checks"),
        route_workflow_intent("make the framework runnable in Claude Code"),
        route_workflow_intent("make the framework runnable in OpenCode"),
        route_workflow_intent("make the framework cross platform"),
        route_workflow_intent("run the framework as an MCP server"),
        route_workflow_intent("visualize the workflow graph"),
    ]
    paths = {
        "json": base / "workflow_router.json",
        "yaml": base / "workflow_router.yaml",
        "markdown": base / "workflow_router.md",
        "html": base / "workflow_router.html",
        "sample_packets": base / "sample_route_packets.yaml",
    }
    write_text(
        paths["json"], json.dumps(catalogue.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    write_yaml(paths["yaml"], catalogue.model_dump(mode="json"))
    write_text(paths["markdown"], render_router_markdown(catalogue))
    write_text(paths["html"], render_router_html(catalogue))
    write_yaml(
        paths["sample_packets"], [packet.model_dump(mode="json") for packet in sample_packets]
    )
    return paths


def validate_workflow_router() -> list[str]:
    """Validate workflow router for the workflow router workflow."""
    routes = load_workflow_routes()
    errors: list[str] = []
    hooks = _hook_ids()
    skills = _skill_names()
    bindings = _skill_bindings()
    route_ids: set[str] = set()
    for route in routes:
        if route.route_id in route_ids:
            errors.append(f"{route.route_id}: duplicate route")
        route_ids.add(route.route_id)
        if route.hook not in hooks:
            errors.append(f"{route.route_id}: unknown hook {route.hook}")
        for skill in route.skills:
            if skill not in skills:
                errors.append(f"{route.route_id}: unknown skill {skill}")
            elif route.hook not in bindings.get(skill, set()):
                errors.append(f"{route.route_id}: skill {skill} is not bound to hook {route.hook}")
        for command in [*route.workflow_commands, *route.validation_commands]:
            if not command.startswith("uv run ruler "):
                errors.append(f"{route.route_id}: command must use ruler CLI: {command}")
        for required_input in route.required_inputs:
            if not (REPO_ROOT / required_input).exists():
                errors.append(f"{route.route_id}: missing required input {required_input}")
        if not route.expected_outputs:
            errors.append(f"{route.route_id}: expected_outputs must not be empty")
    sample = {
        "dynamic inference interface": "inference_control_dashboard",
        "number of facts and rules": "inference_control_dashboard",
        "translate policy text to english": "controlled_translation",
        "harmonize vocabulary into predicates": "controlled_translation",
        "bilingual Prolog comments": "controlled_translation",
        "runnable in Claude Code": "claude_code_bridge",
        "runnable in OpenCode": "opencode_bridge",
        "cross platform": "cross_platform_runtime",
        "MCP server": "mcp_server_runtime",
        "generative API config": "mcp_server_runtime",
        "workflow graph visualization": "workflow_visualization",
        "full validation": "full_validation",
    }
    for query, expected in sample.items():
        packet = route_workflow_intent(query)
        if packet.selected_route_id != expected:
            errors.append(f"{query!r}: expected {expected}, got {packet.selected_route_id}")
    guided = guide_workflow_intent("translate policy text to english")
    if guided.status != "deterministic_only":
        errors.append("offline orchestrator must remain deterministic_only")
    if guided.receipt.skills_executed:
        errors.append("orchestrator receipt must not claim selected skills executed")
    if guided.receipt.authority != "advisory":
        errors.append("orchestrator receipt must remain advisory")
    if errors:
        from ruler.runtime.validation import ValidationErrorGroup

        raise ValidationErrorGroup("workflow-router", errors)
    return [f"routes={len(routes)}"]


def render_router_markdown(catalogue: RouterCatalogue) -> str:
    """Render router markdown for the workflow router workflow."""
    lines = [
        "# RULER Workflow Router",
        "",
        "A bounded generative-facing interface over known hooks, skills, commands, and artifacts.",
        "",
        "## Routes",
        "",
    ]
    for route in catalogue.routes:
        lines.extend(
            [
                f"### {route.title}",
                "",
                route.description,
                "",
                f"- Route: `{route.route_id}`",
                f"- Hook: `{route.hook}`",
                f"- Skills: {', '.join(f'`{skill}`' for skill in route.skills)}",
                f"- Commands: {', '.join(f'`{command}`' for command in route.workflow_commands)}",
                "",
            ]
        )
    return "\n".join(lines)


def render_router_html(catalogue: RouterCatalogue) -> str:
    """Render router HTML for the workflow router workflow."""
    cards = "\n".join(_route_html(route) for route in catalogue.routes)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RULER Workflow Router</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f8fa; color: #17202a; }}
    header {{ background: #fff; border-bottom: 1px solid #dde3ea; padding: 28px; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; display: grid; gap: 14px; }}
    article {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 18px; }}
    code {{ background: #eef2f6; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>RULER Workflow Router</h1>
    <p>Bounded interface from user intent to known workflow hooks, skills, commands, and evidence artifacts.</p>
  </header>
  <main>{cards}</main>
</body>
</html>
"""


def _score_route(query: str, route: WorkflowRoute) -> RouteCandidate:
    """Internal helper for score route in the workflow router workflow."""
    query_terms = _terms(query)
    matched: set[str] = set()
    score = 0
    for pattern in route.intent_patterns:
        pattern_terms = _terms(pattern)
        overlap = query_terms.intersection(pattern_terms)
        if overlap:
            matched.update(overlap)
            score += len(overlap)
        if pattern.lower() in query.lower():
            score += 4
            matched.add(pattern.lower())
    title_terms = query_terms.intersection(_terms(route.title))
    if title_terms:
        matched.update(title_terms)
        score += len(title_terms)
    return RouteCandidate(
        route_id=route.route_id,
        title=route.title,
        score=score,
        matched_terms=sorted(matched),
        hook=route.hook,
        skills=route.skills,
        workflow_commands=route.workflow_commands,
        validation_commands=route.validation_commands,
        expected_outputs=route.expected_outputs,
    )


def _terms(value: str) -> set[str]:
    """Internal helper for terms in the workflow router workflow."""
    return {
        term
        for term in re.split(r"[^a-z0-9]+", value.lower())
        if len(term) >= 3 and term not in {"the", "and", "for", "with", "run"}
    }


def _proposal_schema(route_ids: list[str]) -> dict[str, object]:
    """Build a strict schema whose selectable values are the registered route IDs."""

    return {
        "type": "object",
        "properties": {
            "interpreted_intent": {"type": "string", "minLength": 1, "maxLength": 1000},
            "selected_route_ids": {
                "type": "array",
                "items": {"type": "string", "enum": route_ids},
                "maxItems": 3,
                "uniqueItems": True,
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "concise_guidance": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
                "minItems": 1,
                "maxItems": 4,
            },
            "clarification_question": {"type": "string", "maxLength": 500},
        },
        "required": [
            "interpreted_intent",
            "selected_route_ids",
            "confidence",
            "concise_guidance",
            "clarification_question",
        ],
        "additionalProperties": False,
    }


def _orchestrator_prompt(
    query: str,
    routes: list[WorkflowRoute],
    deterministic: RouterPacket,
) -> str:
    route_summary = [
        {
            "route_id": route.route_id,
            "title": route.title,
            "description": route.description,
            "intent_patterns": route.intent_patterns,
        }
        for route in routes
    ]
    candidate_ids = [candidate.route_id for candidate in deterministic.candidates]
    return (
        "Interpret the user's requested outcome and recommend up to three routes from the "
        "registered RULER catalogue. Return only the requested structured object. Do not "
        "invent route identifiers, commands, inputs, outputs, facts, or capabilities. "
        "Do not provide chain-of-thought. Guidance must briefly explain the proposed next "
        "workflow steps without claiming they have run. If essential information is missing, "
        "use an empty selected_route_ids list and ask one concise clarification question.\n\n"
        f"User request:\n{query}\n\n"
        f"Deterministic candidate IDs:\n{json.dumps(candidate_ids)}\n\n"
        f"Registered routes:\n{json.dumps(route_summary, ensure_ascii=False)}"
    )


def _guided_packet(
    *,
    query: str,
    status: Literal["deterministic_only", "guided", "unavailable"],
    interpreted_intent: str,
    selected_route_ids: list[str],
    route_by_id: dict[str, WorkflowRoute],
    deterministic: RouterPacket,
    guidance: list[str],
    clarification_question: str,
    receipt: OrchestratorReceipt,
    confidence: Literal["high", "medium", "low", "not_generated"],
) -> GuidedRoutePacket:
    selected_skills = sorted(
        {skill for route_id in selected_route_ids for skill in route_by_id[route_id].skills}
    )
    receipt = receipt.model_copy(
        update={
            "selected_route_ids": selected_route_ids,
            "selected_skill_ids": selected_skills,
            "skills_executed": False,
        }
    )
    packet = GuidedRoutePacket(
        query=query,
        status=status,
        interpreted_intent=interpreted_intent,
        confidence=confidence,
        selected_route_ids=selected_route_ids,
        routes=[route_by_id[route_id] for route_id in selected_route_ids],
        deterministic_candidates=deterministic.candidates,
        guidance=guidance,
        clarification_question=clarification_question,
        receipt=receipt,
        router_notes=[
            "This packet is advisory and has not executed a workflow or written an artifact.",
            "Only canonical route metadata is executable; generated prose has no execution authority.",
            "A caller must separately authorize any allowlisted workflow write or external action.",
        ],
        audit_hash="sha256:pending",
    )
    return packet.model_copy(
        update={"audit_hash": stable_hash(packet.model_dump(mode="json", exclude={"audit_hash"}))}
    )


def _hook_ids() -> set[str]:
    """Internal helper for hook ids in the workflow router workflow."""
    return {
        WorkflowHook.model_validate(item).hook for item in read_yaml(HOOKS_FILE).get("hooks", [])
    }


def _skill_names() -> set[str]:
    return set(discover_skill_files())


def _skill_bindings() -> dict[str, set[str]]:
    bindings = load_model_list(SKILL_HOOKS_FILE, SkillHookBinding)
    return {binding.skill: set(binding.stages) for binding in bindings}


def _route_html(route: WorkflowRoute) -> str:
    """Internal helper for route html in the workflow router workflow."""
    skills = ", ".join(f"<code>{html.escape(skill)}</code>" for skill in route.skills)
    commands = "".join(
        f"<li><code>{html.escape(command)}</code></li>" for command in route.workflow_commands
    )
    return f"""<article>
  <h2>{html.escape(route.title)}</h2>
  <p>{html.escape(route.description)}</p>
  <p><strong>Route:</strong> <code>{html.escape(route.route_id)}</code> <strong>Hook:</strong> <code>{html.escape(route.hook)}</code></p>
  <p><strong>Skills:</strong> {skills}</p>
  <ul>{commands}</ul>
</article>"""
