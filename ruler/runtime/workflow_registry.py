# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Canonical workflow inventory and execution-surface validation.

The YAML registry contains policy.  This module joins it to the live Click tree,
hooks, skill bindings, router declarations, and client wrappers.  It deliberately
does not execute workflows or external evaluators.
"""

from __future__ import annotations

import re
import shlex
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import click

from ruler.io import read_yaml
from ruler.paths import (
    HOOKS_FILE,
    REPO_ROOT,
    SKILL_HOOKS_FILE,
    SKILL_LIFECYCLE_FILE,
    WORKFLOW_REGISTRY_FILE,
)
from ruler.schemas import SkillHookBinding, WorkflowHook

RULER_PREFIX = ("uv", "run", "ruler")
QUALITY_COMMAND_PREFIXES = (
    ("uv", "run", "pytest"),
    ("uv", "run", "ruff"),
    ("git", "diff", "--check"),
)
CLASSIFICATIONS = {
    "public",
    "internal_stage",
    "lifecycle_gate",
    "compatibility_alias",
    "experimental",
    "deprecated",
}
EFFECT_FIELDS = (
    "local_read",
    "local_write",
    "external_read",
    "external_write",
    "network",
    "deterministic",
    "expected_duration",
    "cache_policy",
    "confirmation_required",
    "resumable",
)


def load_workflow_registry(path: Path = WORKFLOW_REGISTRY_FILE) -> dict[str, Any]:
    """Load registry policy and materialize defaults into every workflow record."""
    payload = read_yaml(path)
    defaults = payload.get("defaults", {})
    workflows: list[dict[str, Any]] = []
    for raw in payload.get("workflows", []):
        item = {**defaults, **raw}
        item.setdefault("command", f"uv run ruler workflow {item['id']}")
        item.setdefault("hook", None)
        item.setdefault("parent_workflow", None)
        item.setdefault("inputs", [])
        item.setdefault("outputs", [])
        item.setdefault("validators", [])
        item.setdefault("tools", [])
        item.setdefault("generated_evidence", [])
        workflows.append(item)
    return {**payload, "workflows": workflows}


def click_command_paths() -> dict[tuple[str, ...], click.Command]:
    """Return every live Click command path, including groups."""
    from ruler.cli import main

    found: dict[tuple[str, ...], click.Command] = {}

    def walk(command: click.Command, prefix: tuple[str, ...]) -> None:
        """Recursively index every live Click group and command by invocation path."""
        if prefix:
            found[prefix] = command
        if isinstance(command, click.Group):
            for name, child in command.commands.items():
                walk(child, (*prefix, name))

    walk(main, ())
    return found


def resolve_cli_command(command: str) -> str | None:
    """Return a stable error for an undeclared or invalid command, else ``None``."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"cannot parse command: {exc}"
    if not argv:
        return "empty command"
    if any(argv[: len(prefix)] == list(prefix) for prefix in QUALITY_COMMAND_PREFIXES):
        return None
    if tuple(argv[:3]) != RULER_PREFIX:
        return "command is outside the RULER CLI and quality-command allowlist"
    args = argv[3:]
    paths = click_command_paths()
    matched: tuple[str, ...] = ()
    for token in args:
        candidate = (*matched, token)
        if candidate in paths:
            matched = candidate
            continue
        break
    if not matched:
        return "missing CLI command target"
    selected = paths[matched]
    if isinstance(selected, click.Group) and len(matched) == len(args):
        return f"CLI target {' '.join(matched)} is a group, not an executable command"
    remaining = args[len(matched) :]
    if isinstance(selected, click.Group) and remaining:
        return f"missing CLI command target {' '.join((*matched, remaining[0]))}"
    known_options = {
        option
        for parameter in selected.params
        if isinstance(parameter, click.Option)
        for option in (*parameter.opts, *parameter.secondary_opts)
    }
    for token in remaining:
        option = token.split("=", 1)[0]
        if option.startswith("-") and option not in known_options:
            return f"unknown option {option} for CLI target {' '.join(matched)}"
    return None


def _declared_commands() -> list[tuple[str, str]]:
    declared: list[tuple[str, str]] = []
    hooks = [WorkflowHook.model_validate(item) for item in read_yaml(HOOKS_FILE).get("hooks", [])]
    for hook in hooks:
        declared.extend((f"hook:{hook.hook}/{item.name}", item.command) for item in hook.commands)
    for route in read_yaml(REPO_ROOT / "data/use_cases/workflow_router.yaml"):
        for field in ("workflow_commands", "validation_commands"):
            declared.extend(
                (f"route:{route['route_id']}/{field}", item) for item in route.get(field, [])
            )
    registry = load_workflow_registry()
    declared.extend((f"registry:{item['id']}", item["command"]) for item in registry["workflows"])
    for item in registry.get("workflows", []):
        declared.extend((f"registry:{item['id']}/validator", value) for value in item["validators"])

    documentation = [REPO_ROOT / "AGENTS.md"]
    documentation.extend((REPO_ROOT / ".opencode").rglob("*.md"))
    documentation.extend((REPO_ROOT / ".claude" / "skills").rglob("*.md"))
    command_pattern = re.compile(r"(?:uv run (?:ruler|pytest|ruff)|git diff --check)[^\n`]*")
    for path in documentation:
        for match in command_pattern.findall(path.read_text(encoding="utf-8")):
            command = match.strip()
            if "..." not in command:
                declared.append((f"documentation:{path.relative_to(REPO_ROOT)}", command))
    return declared


def _skill_inventory_errors() -> tuple[list[str], dict[str, list[str]]]:
    errors: list[str] = []
    grouped: dict[str, list[str]] = defaultdict(list)
    lifecycle = read_yaml(SKILL_LIFECYCLE_FILE).get("roots", [])
    configured = {item["path"]: item for item in lifecycle}
    for required in ("skills", "proj_skills", ".opencode/skills", ".claude/skills"):
        if required not in configured:
            errors.append(f"unclassified skill root: {required}")
            continue
        root = REPO_ROOT / required
        for path in root.rglob("SKILL.md"):
            grouped[configured[required]["classification"]].append(str(path.relative_to(REPO_ROOT)))
    bindings = [SkillHookBinding.model_validate(item) for item in read_yaml(SKILL_HOOKS_FILE)]
    binding_counts = Counter(item.skill for item in bindings)
    runtime_names = {Path(path).parent.name for path in grouped.get("runtime", [])}
    for name in sorted(runtime_names):
        count = binding_counts[name]
        if count != 1:
            errors.append(f"runtime skill {name}: expected exactly one binding, found {count}")
    for name in sorted(set(binding_counts) - runtime_names):
        errors.append(f"skill binding references missing runtime skill: {name}")
    return errors, grouped


def validate_workflow_registry(path: Path = WORKFLOW_REGISTRY_FILE) -> list[str]:
    """Validate command resolution, classifications, effects, and reachability."""
    payload = load_workflow_registry(path)
    errors: list[str] = []
    workflows = payload.get("workflows", [])
    ids = [item["id"] for item in workflows]
    for duplicate, count in Counter(ids).items():
        if count > 1:
            errors.append(f"duplicate workflow id: {duplicate}")
    workflow_ids = set(ids)
    live_workflows = {
        path[1] for path in click_command_paths() if len(path) == 2 and path[0] == "workflow"
    }
    for missing in sorted(live_workflows - workflow_ids):
        errors.append(f"unclassified CLI workflow: {missing}")
    for missing in sorted(workflow_ids - live_workflows):
        errors.append(f"registry workflow has no CLI command: {missing}")
    live_ingestion = {
        command_path[1]
        for command_path in click_command_paths()
        if len(command_path) == 2 and command_path[0] == "ingestion"
    }
    declared_ingestion = set(payload.get("ingestion_operations", []))
    for missing in sorted(live_ingestion - declared_ingestion):
        errors.append(f"unclassified ingestion operation: {missing}")
    for missing in sorted(declared_ingestion - live_ingestion):
        errors.append(f"ingestion operation has no CLI command: {missing}")
    for operation in sorted(declared_ingestion):
        command_error = resolve_cli_command(
            f"uv run ruler ingestion {operation} --provider sample --batch-id audit "
            "--output-root build/ruler/ingestion --dry-run"
        )
        if command_error:
            errors.append(f"ingestion operation {operation}: {command_error}")

    command_surfaces = payload.get("command_surfaces", [])
    surface_ids = [item.get("id") for item in command_surfaces]
    for duplicate, count in Counter(surface_ids).items():
        if count > 1:
            errors.append(f"duplicate command surface id: {duplicate}")
    for item in command_surfaces:
        surface_id = item.get("id", "<missing>")
        if item.get("classification") not in CLASSIFICATIONS:
            errors.append(
                f"command surface {surface_id}: invalid classification "
                f"{item.get('classification')!r}"
            )
        for field in (
            "local_read",
            "local_write",
            "external_read",
            "external_write",
            "network",
            "deterministic",
            "confirmation_required",
        ):
            if not isinstance(item.get(field), bool):
                errors.append(f"command surface {surface_id}: undeclared boolean effect {field}")
        command_error = resolve_cli_command(str(item.get("command", "")))
        if command_error:
            errors.append(f"command surface {surface_id}: {command_error}")

    hooks = [WorkflowHook.model_validate(item) for item in read_yaml(HOOKS_FILE).get("hooks", [])]
    hook_ids = [item.hook for item in hooks]
    for duplicate, count in Counter(hook_ids).items():
        if count > 1:
            errors.append(f"duplicate hook id: {duplicate}")
    hook_set = set(hook_ids)
    hook_policies = {item["id"]: item for item in payload.get("hook_policies", [])}
    for missing in sorted(hook_set - hook_policies.keys()):
        errors.append(f"hook without reachability policy: {missing}")
    for missing in sorted(hook_policies.keys() - hook_set):
        errors.append(f"hook policy references missing hook: {missing}")

    tools = {item["id"]: item for item in payload.get("external_tools", [])}
    for item in workflows:
        workflow_id = item["id"]
        if item.get("classification") not in CLASSIFICATIONS:
            errors.append(f"{workflow_id}: invalid classification {item.get('classification')!r}")
        for field in EFFECT_FIELDS:
            if field not in item:
                errors.append(f"{workflow_id}: undeclared effect {field}")
        if item.get("router_visibility") == "public" and item.get("classification") != "public":
            errors.append(f"{workflow_id}: router-visible workflow must be public")
        if (
            item.get("classification") != "public"
            and not item.get("hook")
            and not item.get("parent_workflow")
        ):
            errors.append(f"{workflow_id}: internal workflow has no hook or parent")
        if item.get("hook") and item["hook"] not in hook_set:
            errors.append(f"{workflow_id}: unknown hook {item['hook']}")
        if item.get("parent_workflow") and item["parent_workflow"] not in workflow_ids:
            errors.append(f"{workflow_id}: unknown parent workflow {item['parent_workflow']}")
        for tool in item.get("tools", []):
            if tool not in tools:
                errors.append(f"{workflow_id}: unknown external tool {tool}")
        command_error = resolve_cli_command(item["command"])
        if command_error:
            errors.append(f"{workflow_id}: {command_error}")

    for tool_id, tool in tools.items():
        if Path(tool.get("executable", "")).is_absolute():
            errors.append(f"external tool {tool_id}: executable must not be machine-specific")
        overlap = set(tool.get("allowed_options", [])) & set(tool.get("forbidden_options", []))
        if overlap:
            errors.append(
                f"external tool {tool_id}: allowed and forbidden options overlap: {sorted(overlap)}"
            )

    for origin, command in _declared_commands():
        command_error = resolve_cli_command(command)
        if command_error:
            errors.append(f"{origin}: {command_error}: {command}")

    skill_errors, grouped = _skill_inventory_errors()
    errors.extend(skill_errors)
    if errors:
        from ruler.runtime.validation import ValidationErrorGroup

        raise ValidationErrorGroup("workflow-registry", errors)
    return [
        f"workflows={len(workflows)}",
        f"hooks={len(hooks)}",
        f"commands={len(_declared_commands())}",
        f"runtime_skills={len(grouped.get('runtime', []))}",
        f"project_skills={len(grouped.get('project_only', []))}",
        f"client_wrappers={len(grouped.get('client_wrapper', []))}",
        f"ingestion_operations={len(declared_ingestion)}",
        f"command_surfaces={len(command_surfaces)}",
    ]


def build_execution_catalogue() -> dict[str, Any]:
    """Build the complete human/machine-facing registry view."""
    payload = load_workflow_registry()
    hooks = {
        item.hook: item
        for item in (
            WorkflowHook.model_validate(raw) for raw in read_yaml(HOOKS_FILE).get("hooks", [])
        )
    }
    bindings = [SkillHookBinding.model_validate(item) for item in read_yaml(SKILL_HOOKS_FILE)]
    skills_by_hook: dict[str, list[str]] = defaultdict(list)
    for binding in bindings:
        for stage in binding.stages:
            skills_by_hook[stage].append(binding.skill)
    rows = []
    for workflow in payload["workflows"]:
        hook = workflow.get("hook")
        effective_inputs = set(workflow["inputs"])
        effective_outputs = set(workflow["outputs"])
        for binding in bindings:
            if hook in binding.stages:
                effective_inputs.update(binding.required_inputs)
                effective_outputs.update(binding.required_outputs)
        rows.append(
            {
                **workflow,
                "skills": sorted(skills_by_hook.get(hook, [])),
                "inputs": sorted(effective_inputs),
                "outputs": sorted(effective_outputs),
                "hook_commands": [item.command for item in hooks[hook].commands] if hook else [],
            }
        )
    _, skill_inventory = _skill_inventory_errors()
    return {
        "version": payload["version"],
        "workflows": rows,
        "hooks": payload.get("hook_policies", []),
        "external_tools": payload.get("external_tools", []),
        "ingestion_operations": payload.get("ingestion_operations", []),
        "skill_inventory": dict(skill_inventory),
        "drift": [],
    }


def render_execution_catalogue(catalogue: dict[str, Any]) -> str:
    """Render a compact Markdown catalogue from the canonical model."""
    lines = [
        "# Workflow execution catalogue",
        "",
        "Generated from `.ruler/workflows.yaml` and verified against the live Click tree.",
        "",
        "| Workflow | Class | Command | Hook | Router | Effects |",
        "|---|---|---|---|---|---|",
    ]
    for item in catalogue["workflows"]:
        effects = (
            ", ".join(
                name
                for name in ("local_write", "external_read", "external_write", "network")
                if item[name]
            )
            or "read-only"
        )
        lines.append(
            f"| `{item['id']}` | {item['classification']} | `{item['command']}` | "
            f"{item.get('hook') or '-'} | {item['router_visibility']} | {effects} |"
        )
    for title, key in (
        ("Runtime skills", "runtime"),
        ("Project-only skills", "project_only"),
        ("Client wrappers", "client_wrapper"),
    ):
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- `{path}`" for path in catalogue["skill_inventory"].get(key, []))
    lines.extend(["", "## Drift", "", "No unexplained drift.", ""])
    return "\n".join(lines)


def write_execution_catalogue(output_dir: Path) -> dict[str, Path]:
    """Write deterministic YAML and Markdown views of the execution registry."""
    from ruler.io import write_text, write_yaml

    output_dir.mkdir(parents=True, exist_ok=True)
    catalogue = build_execution_catalogue()
    yaml_path = output_dir / "workflow_execution_catalogue.yaml"
    markdown_path = output_dir / "workflow_execution_catalogue.md"
    write_yaml(yaml_path, catalogue)
    write_text(markdown_path, render_execution_catalogue(catalogue))
    return {"yaml": yaml_path, "markdown": markdown_path}
