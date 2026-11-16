# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Repository validation control plane. It aggregates dependency, skill, hook, source,
solver, KB, bridge, and reasoning checks into explicit gates for development and
automation.
"""

from __future__ import annotations

import importlib
import hashlib
import re
from pathlib import Path

from ruler.runtime.api_config import (
    GEN_API_CONFIG_FILE,
    validate_generative_api_config as _validate_generative_api_config,
)
from ruler.runtime.claude_code import (
    REQUIRED_CLAUDE_SKILLS,
    validate_claude_code_bridge as _validate_claude_code_bridge,
)
from ruler.runtime.codex import validate_codex_bridge as _validate_codex_bridge
from ruler.runtime.cross_platform import (
    validate_cross_platform_support as _validate_cross_platform,
)
from ruler.kb.formalized_kb import validate_formalized_kb_artifacts
from ruler.kb.formalization_completion import (
    validate_formalization_completion as _validate_formalization_completion,
)
from ruler.kb.formalization_wave import validate_formalization_wave_configuration
from ruler.kb.formalization_artifacts import (
    validate_formalization_coverage as _validate_formalization_coverage,
)
from ruler.interfaces.inference_dashboard import (
    validate_inference_control_dashboard as _validate_inference_dashboard,
)
from ruler.interfaces.kb_visualizer import validate_kb_visualizer as _validate_kb_visualizer
from ruler.io import load_model_list, read_yaml
from ruler.runtime.opencode import (
    REQUIRED_OPENCODE_COMMANDS,
    REQUIRED_OPENCODE_SKILLS,
    validate_opencode_bridge as _validate_opencode_bridge,
)
from ruler.interfaces.skill_reasoning_logs import validate_skill_reasoning_log_artifacts
from ruler.paths import (
    HOOKS_FILE,
    REFERENCE_DIR,
    REPO_ROOT,
    SKILL_HOOKS_FILE,
    SKILLS_DIR,
)
from ruler.schemas import (
    SkillHookBinding,
    WorkflowHook,
)
from ruler.runtime.skill_inventory import SKILL_GROUPS, discover_skill_files
from ruler.kb.translation_control import (
    AUTOFORMALIZATION_ALIGNMENT_FILE,
    VOCABULARY_PREDICATE_MAP_FILE,
    validate_translation_control_artifacts,
)
from ruler.interfaces.workflow_graphs import (
    build_workflow_graph_model,
    render_workflow_graph_html,
    validate_workflow_graph_model,
)
from ruler.interfaces.workflow_router import (
    validate_workflow_router as _validate_workflow_router,
)
from ruler.interfaces.cbr_demonstrators import validate_cbr_demonstrators


class ValidationErrorGroup(Exception):
    """Typed validation error group artifact used by the validation workflow."""

    def __init__(self, label: str, errors: list[str]) -> None:
        self.label = label
        self.errors = errors
        super().__init__(f"{label}: {len(errors)} validation error(s)")


def _raise(label: str, errors: list[str]) -> None:
    if errors:
        raise ValidationErrorGroup(label, errors)


def validate_deps() -> list[str]:
    """Validate deps for the validation workflow."""
    modules = [
        "alembic",
        "click",
        "clingo",
        "docling",
        "fastapi",
        "mcp",
        "ortools",
        "pydantic",
        "pg8000",
        "pypdf",
        "rdflib",
        "sqlalchemy",
        "yaml",
        "uvicorn",
        "z3",
    ]
    errors: list[str] = []
    for module in modules:
        try:
            importlib.import_module(module)
        except ImportError as exc:
            errors.append(f"missing Python dependency {module}: {exc}")
    _raise("deps", errors)
    return [f"imported {module}" for module in modules]


def validate_kb_workspace() -> list[str]:
    """Validate named-KB discovery, integrity, routing, redaction, and visual shell."""
    from fastapi.testclient import TestClient

    from ruler.interfaces.kb_workspace import create_kb_workspace_app
    from ruler.kb.corpus_manifest import (
        validate_corpus_manifests,
        load_corpus_manifest,
        discover_corpus_manifests,
    )
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_contracts import KBInferenceRequest
    from ruler.kb.workspace_inference import KBInferenceService

    errors: list[str] = []
    manifests = [load_corpus_manifest(path) for path in discover_corpus_manifests()]
    try:
        validate_corpus_manifests(manifests)
    except ValueError as exc:
        errors.append(str(exc))
    catalog = KnowledgeBaseCatalog()
    items = catalog.list()
    expected = {"regulatory-proof", "legal-sr101-art36"}
    missing = expected - {item.kb_id for item in items}
    if missing:
        errors.append(f"workspace is missing adapted corpora: {sorted(missing)}")
    for kb in items:
        for artifact in kb.current_version.artifacts:
            try:
                catalog.artifact_path(artifact)
            except ValueError as exc:
                errors.append(str(exc))
    inference = KBInferenceService(catalog)
    registered_backends = {item.backend_id for item in inference.adapters}
    required_backends = {
        "logical-ir-asp-validation-v1",
        "swi-prolog-horn-crosscheck-v1",
        "vampire-tptp-bounded-v1",
        "lean4-elaboration-v1",
        "logical-ir-compliance-v1",
        "deterministic-hard-gated-ranking-v1",
        "z3-typed-maxsmt-v1",
    }
    if missing_backends := required_backends - registered_backends:
        errors.append(f"workspace is missing formalism adapters: {sorted(missing_backends)}")
    route_count = sum(len(inference.capabilities(item.kb_id)) for item in items)
    if not inference.capabilities("regulatory-proof"):
        errors.append("regulatory proof KB has no executable inference route")
    if not inference.capabilities("legal-sr101-art36"):
        errors.append("legal KB has no assurance route")
    probe = inference.execute(
        "regulatory-proof",
        KBInferenceRequest(
            request_id="workspace-backend-probe",
            operation="verify",
            artifact_id="regulatory-proof-asp-v1",
            query='evaluation_outcome("rg_notice_obligation",alice,"satisfied")',
            contrary='evaluation_outcome("rg_notice_obligation",alice,"violated")',
            asserted_facts=(
                "in_scope(alice)",
                "submitted_notice(alice)",
                "within_deadline(alice)",
            ),
        ),
    )
    if probe.status != "completed" or probe.conclusion != "supported":
        errors.append(
            "regulatory proof executable backend probe failed: "
            f"status={probe.status}, conclusion={probe.conclusion}"
        )
    app = create_kb_workspace_app(token="validation-workspace-token-1234", catalog=catalog)
    client = TestClient(app)
    if client.get("/api/kbs").status_code != 401:
        errors.append("KB workspace list is accessible without authentication")
    if client.get("/api/chat/status").status_code != 401:
        errors.append("KB conversation status is accessible without authentication")
    response = client.get(
        "/api/kbs", headers={"Authorization": "Bearer validation-workspace-token-1234"}
    )
    if response.status_code != 200:
        errors.append("authenticated KB workspace list failed")
    elif "/Users/" in response.text or '"path"' in response.text:
        errors.append("KB workspace public catalogue leaks filesystem paths")
    detail = client.get(
        "/api/kbs/regulatory-proof",
        headers={"Authorization": "Bearer validation-workspace-token-1234"},
    )
    if detail.status_code != 200 or "etag" not in detail.headers:
        errors.append("KB workspace detail lacks optimistic-concurrency ETag")
    releases = client.get(
        "/api/kbs/regulatory-proof/releases",
        headers={"Authorization": "Bearer validation-workspace-token-1234"},
    )
    if releases.status_code != 200 or not releases.json().get("releases"):
        errors.append("KB workspace has no published release envelope")
    html = client.get("/", params={"token": "validation-workspace-token-1234"})
    if html.status_code != 200 or "Knowledge Base Workspace" not in html.text:
        errors.append("KB visual workspace shell is unavailable")
    elif "Ask KB" not in html.text or "codex exec" not in html.text:
        errors.append("KB conversational workspace shell is unavailable")
    chat_status = client.get(
        "/api/chat/status",
        headers={"Authorization": "Bearer validation-workspace-token-1234"},
    )
    if chat_status.status_code != 200 or chat_status.json().get("backend") != "codex-exec":
        errors.append("KB conversational backend status is unavailable")
    _raise("kb-workspace", errors)
    return [
        f"knowledge_bases={len(items)}",
        f"inference_routes={route_count}",
        f"registered_backends={len(registered_backends)}",
        "backend_probe=regulatory-proof-supported",
        "releases=governed",
        "authentication=required",
        "paths=redacted",
        "conversation=codex-exec-isolated",
    ]


def validate_contracts() -> list[str]:
    """Validate registered corpus contracts, identities, and exact artifact hashes."""
    from ruler.kb.corpus_manifest import (
        discover_corpus_manifests,
        load_corpus_manifest,
        validate_corpus_manifests,
    )

    manifests = [load_corpus_manifest(path) for path in discover_corpus_manifests()]
    if not manifests:
        raise ValidationErrorGroup("contracts", ["no corpus manifests found"])
    try:
        return validate_corpus_manifests(manifests)
    except (ValueError, OSError) as exc:
        raise ValidationErrorGroup("contracts", [str(exc)]) from exc


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Internal helper for read frontmatter in the validation workflow."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter must end with ---")
    frontmatter = read_yaml_from_text(content[4:end])
    if not isinstance(frontmatter, dict):
        raise ValueError("frontmatter must be a mapping")
    return frontmatter


def read_yaml_from_text(content: str) -> object:
    """Read YAML from text for the validation workflow."""
    import yaml

    return yaml.safe_load(content)


def validate_skills() -> list[str]:
    """Validate skills for the validation workflow."""
    errors: list[str] = []
    direct_skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    if direct_skill_files:
        errors.append(
            "skills must live under one thematic subfolder: "
            + ", ".join(str(path.relative_to(REPO_ROOT)) for path in direct_skill_files)
        )
    unknown_group_dirs = sorted(
        path.name
        for path in SKILLS_DIR.iterdir()
        if path.is_dir() and path.name not in SKILL_GROUPS
    )
    if unknown_group_dirs:
        errors.append(f"unknown skill theme folders: {unknown_group_dirs}")
    skill_inventory = discover_skill_files()
    name_pattern = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    bindings = load_model_list(SKILL_HOOKS_FILE, SkillHookBinding)
    bound_skills = {binding.skill for binding in bindings}

    for skill_name, skill in sorted(skill_inventory.items()):
        if not name_pattern.match(skill_name):
            errors.append(f"{skill_name}: invalid skill directory name")
        if skill.path.parent.name != skill_name:
            errors.append(f"{skill_name}: skill folder name must match frontmatter name")
        try:
            frontmatter = _read_frontmatter(skill.path)
        except ValueError as exc:
            errors.append(f"{skill_name}: {exc}")
            continue
        if frontmatter.get("name") != skill_name:
            errors.append(f"{skill_name}: frontmatter name must match directory")
        if not frontmatter.get("description"):
            errors.append(f"{skill_name}: missing description")
        if skill_name not in bound_skills:
            errors.append(f"{skill_name}: missing SKILL_HOOKS binding")

    missing_dirs = sorted(bound_skills - set(skill_inventory))
    if missing_dirs:
        errors.append(f"SKILL_HOOKS references missing skill dirs: {missing_dirs}")

    transfer = read_yaml(REFERENCE_DIR / "upstream_skill_transfer.yaml")
    transferred = transfer.get("skills", []) if isinstance(transfer, dict) else []
    if not isinstance(transferred, list) or not all(isinstance(item, str) for item in transferred):
        errors.append("upstream skill transfer manifest must contain a string skills list")
    else:
        canonical = sorted(transferred)
        digest = "sha256:" + hashlib.sha256(("\n".join(canonical) + "\n").encode()).hexdigest()
        if transfer.get("inventory_sha256") != digest:
            errors.append("upstream skill transfer manifest inventory digest mismatch")
        if missing_transfers := sorted(set(canonical) - set(skill_inventory)):
            errors.append(f"upstream skills missing after transfer: {missing_transfers}")

    _raise("skills", errors)
    return [f"skills={len(skill_inventory)}", f"bindings={len(bindings)}"]


def validate_deterministic_skills() -> list[str]:
    """Validate executable contracts for solver-backed and generative runtime skills."""
    from ruler.runtime.workflow_registry import resolve_cli_command

    errors: list[str] = []
    known_backends = {
        "codex-exec",
        "codex-exec-optional",
        "decimal-independent-verifier",
        "logical-ir-asp-validation-v1",
        "ortools-cp-sat",
        "pyomo-highs",
        "ruler-evidence-sweep-v1",
        "scipy-optimize",
        "swi-prolog-horn-crosscheck-v1",
        "z3",
    }
    bindings = load_model_list(SKILL_HOOKS_FILE, SkillHookBinding)
    governed = [
        binding
        for binding in bindings
        if binding.execution_mode is not None or binding.skill.startswith("resource-")
    ]
    for binding in governed:
        prefix = binding.skill
        if binding.execution_mode is None:
            errors.append(f"{prefix}: missing execution_mode")
        for field in (
            "execution_commands",
            "implementation_refs",
            "backend_ids",
            "fixture_paths",
            "evidence_outputs",
        ):
            if not getattr(binding, field):
                errors.append(f"{prefix}: missing executable skill contract field {field}")
        for command in binding.execution_commands:
            resolution_error = resolve_cli_command(command)
            if resolution_error:
                errors.append(f"{prefix}: invalid execution command: {resolution_error}")
        for value in (*binding.implementation_refs, *binding.fixture_paths):
            path = REPO_ROOT / value
            if not path.exists():
                errors.append(f"{prefix}: declared executable evidence path is missing: {value}")
        if len(binding.backend_ids) != len(set(binding.backend_ids)):
            errors.append(f"{prefix}: duplicate backend IDs")
        if unknown := sorted(set(binding.backend_ids) - known_backends):
            errors.append(f"{prefix}: unknown or unverified backend IDs: {unknown}")
        if len(binding.evidence_outputs) != len(set(binding.evidence_outputs)):
            errors.append(f"{prefix}: duplicate evidence output paths")
        if any(
            Path(value).is_absolute() or ".." in Path(value).parts
            for value in binding.evidence_outputs
        ):
            errors.append(f"{prefix}: evidence outputs must be safe relative paths")
        if binding.execution_mode == "generative" and "codex-exec" not in binding.backend_ids:
            errors.append(f"{prefix}: generative skill must declare the real codex-exec backend")

    _raise("deterministic-skills", errors)
    return [f"executable_skills={len(governed)}"]


def validate_resource_portfolio() -> list[str]:
    """Execute the solver-backed acceptance case and check advisory boundaries."""
    from tempfile import TemporaryDirectory
    from ruler.applications.resource_portfolio.compiler import CompilationRequest, compile_rules
    from ruler.applications.resource_portfolio.synthetic import (
        SyntheticPortfolioConfig,
        generate_synthetic_portfolio_inputs,
        write_synthetic_portfolio_inputs,
    )
    from ruler.applications.resource_portfolio.workflow import (
        SAMPLE_INPUT_DIR,
        execute_resource_portfolio_workflow,
    )

    errors: list[str] = []
    with TemporaryDirectory(prefix="ruler-resource-validation-") as temporary:
        output = Path(temporary)
        execute_resource_portfolio_workflow(SAMPLE_INPUT_DIR, output)
        compilation = read_yaml(output / "compilation.yaml")["payload"]
        plan = read_yaml(output / "plan.yaml")["payload"]
        schedule = read_yaml(output / "schedule.yaml")["payload"]
        explanation = read_yaml(output / "explanation.yaml")["payload"]
        if compilation["z3_status"] != "sat":
            errors.append("approved-rule compilation was not satisfiable")
        if plan["result"]["status"] != "OPTIMAL":
            errors.append(
                f"HiGHS did not prove the acceptance case optimal: {plan['result']['status']}"
            )
        if not plan["verification"]["verified"]:
            errors.append("independent plan verification failed")
        if schedule["status"] not in {"OPTIMAL", "FEASIBLE"}:
            errors.append(f"CP-SAT schedule has no incumbent: {schedule['status']}")
        if explanation["receipt"]["mode"] != "deterministic":
            errors.append("offline acceptance explanation must be deterministic")
        if not plan["advisory_only"] or plan["review_status"] != "pending":
            errors.append("portfolio output crossed the pending human-review boundary")
    with TemporaryDirectory(prefix="ruler-synthetic-validation-") as temporary:
        root = Path(temporary)
        synthetic_config = SyntheticPortfolioConfig.model_validate(
            dict(
                seed=2718,
                resource_count=2,
                event_days=1,
                events_per_resource_per_day=2,
                tasks_per_resource=1,
                scenario_count=2,
                anomaly_rate="0.25",
                duplicate_rate="0.25",
                correction_rate="0.25",
            )
        )
        manifest = write_synthetic_portfolio_inputs(synthetic_config, root / "inputs")
        synthetic_run = execute_resource_portfolio_workflow(root / "inputs", root / "workflow")
        if (
            synthetic_run.status != "pending_review"
            or manifest.expected_compilation_status != "sat"
        ):
            errors.append("synthetic feasible acceptance case did not complete safely")
        infeasible_payloads, infeasible_manifest = generate_synthetic_portfolio_inputs(
            synthetic_config.model_copy(update={"model_variant": "infeasible"})
        )
        try:
            compile_rules(CompilationRequest.model_validate(infeasible_payloads["compile.yaml"]))
        except ValueError as exc:
            if "unsatisfiable" not in str(exc):
                errors.append(f"synthetic infeasibility produced an unexpected failure: {exc}")
        else:
            errors.append("synthetic infeasible acceptance case was not rejected")
    _raise("resource-portfolio", errors)
    return [
        f"model={plan['result']['model_digest']}",
        f"solver={plan['result']['receipt']['backend_id']}",
        f"schedule={schedule['receipt']['backend_id']}",
        f"synthetic={infeasible_manifest.expected_compilation_status}",
        "review=pending",
    ]


def validate_hooks() -> list[str]:
    """Validate hooks for the validation workflow."""
    errors: list[str] = []
    payload = read_yaml(HOOKS_FILE)
    hooks = [WorkflowHook.model_validate(item) for item in payload.get("hooks", [])]
    hook_ids = [hook.hook for hook in hooks]
    stages = set(hook_ids)
    bindings = load_model_list(SKILL_HOOKS_FILE, SkillHookBinding)

    duplicate_hooks = sorted(name for name in set(hook_ids) if hook_ids.count(name) > 1)
    if duplicate_hooks:
        errors.append(f"duplicate hook IDs: {duplicate_hooks}")
    binding_names = [binding.skill for binding in bindings]
    duplicate_bindings = sorted(
        name for name in set(binding_names) if binding_names.count(name) > 1
    )
    if duplicate_bindings:
        errors.append(f"duplicate skill bindings: {duplicate_bindings}")

    for hook in hooks:
        if not hook.commands:
            errors.append(f"{hook.hook}: must define at least one command")
        command_names = [command.name for command in hook.commands]
        duplicate_commands = sorted(
            name for name in set(command_names) if command_names.count(name) > 1
        )
        if duplicate_commands:
            errors.append(f"{hook.hook}: duplicate command names {duplicate_commands}")
        for command in hook.commands:
            if not command.command.startswith("uv run ruler "):
                errors.append(f"{hook.hook}/{command.name}: command must go through ruler CLI")
            else:
                from ruler.runtime.workflow_registry import resolve_cli_command

                resolution_error = resolve_cli_command(command.command)
                if resolution_error:
                    errors.append(f"{hook.hook}/{command.name}: {resolution_error}")

    for binding in bindings:
        if not binding.stages:
            errors.append(f"{binding.skill}: binding must declare at least one stage")
        if not binding.validation_commands:
            errors.append(f"{binding.skill}: binding must declare validation commands")
        for stage in binding.stages:
            if stage not in stages:
                errors.append(f"{binding.skill}: unknown hook stage {stage}")
        for required_input in binding.required_inputs:
            if not (REPO_ROOT / required_input).exists():
                errors.append(f"{binding.skill}: missing required input {required_input}")
        for validation_command in binding.validation_commands:
            from ruler.runtime.workflow_registry import resolve_cli_command

            resolution_error = resolve_cli_command(validation_command)
            if resolution_error:
                errors.append(
                    f"{binding.skill}: invalid validation command: {resolution_error}: "
                    f"{validation_command}"
                )

    bound_stages = {stage for binding in bindings for stage in binding.stages}
    unbound_hooks = sorted(stages - bound_stages)
    if unbound_hooks:
        errors.append(f"hooks without bound skills: {unbound_hooks}")

    _raise("hooks", errors)
    return [f"workflow_hooks={len(hooks)}", f"skill_bindings={len(bindings)}"]


def validate_workflow_registry() -> list[str]:
    """Validate the canonical workflow registry against every execution surface."""
    from ruler.runtime.workflow_registry import validate_workflow_registry as validate

    return validate()


def validate_generative_kb_quality() -> list[str]:
    """Validate generative-quality controls without making a model call."""
    from ruler.runtime.generative_quality import validate_quality_configuration

    errors = validate_quality_configuration()
    _raise("generative-kb-quality", errors)
    return ["catalogue=valid", "runner=read-only"]


def validate_workflow_graphs() -> list[str]:
    """Validate workflow graphs for the validation workflow."""
    errors: list[str] = []
    try:
        model = build_workflow_graph_model()
        messages = validate_workflow_graph_model(model)
    except Exception as exc:
        raise ValidationErrorGroup("workflow-graphs", [str(exc)]) from exc
    html_report = render_workflow_graph_html(model)
    required_fragments = [
        "RULER Workflow Graphs",
        "cytoscape",
        "workflow-graph-model",
        "Static Workflow Cards",
    ]
    for fragment in required_fragments:
        if fragment not in html_report:
            errors.append(f"HTML report missing {fragment!r}")
    if not model["stacks"]:
        errors.append("workflow model has no stacks")
    if not model["graph"]["elements"]["nodes"]:
        errors.append("workflow model has no nodes")
    if not model["graph"]["elements"]["edges"]:
        errors.append("workflow model has no edges")
    _raise("workflow-graphs", errors)
    return messages


def validate_workflow_router() -> list[str]:
    """Validate workflow router for the validation workflow."""
    return _validate_workflow_router()


def validate_cbr() -> list[str]:
    """Validate the five CBR packs against live deterministic golden journeys."""
    from ruler.interfaces.cbr_cases import (
        retrieve_cbr_cases,
        suggest_cbr_adaptation,
        verify_cbr_demo,
    )
    from ruler.domains.cbr_catalog import load_all_cbr_demos

    errors: list[str] = []
    demos = load_all_cbr_demos()
    for demo in demos:
        try:
            retrieval = retrieve_cbr_cases(demo.domain_id, top_k=3)
            result = retrieval["result"]
            actual = tuple(item["case_id"] for item in result["retrieved"])
            if actual != demo.expected.retrieval_order:
                errors.append(
                    f"{demo.domain_id}: retrieval {actual!r} != {demo.expected.retrieval_order!r}"
                )
            contrast = result.get("excluded_contrast")
            contrast_id = contrast.get("case_id") if contrast else None
            if contrast_id != demo.expected.excluded_case_id:
                errors.append(
                    f"{demo.domain_id}: contrast {contrast_id!r} != {demo.expected.excluded_case_id!r}"
                )
            adaptation = suggest_cbr_adaptation(demo.domain_id, actual[0])
            if not adaptation["human_review_required"]:
                errors.append(f"{demo.domain_id}: adaptation bypassed human review")
            if adaptation["adapted_case"].get("disposition") is not None:
                errors.append(f"{demo.domain_id}: precedent disposition leaked into adaptation")
            evaluation = verify_cbr_demo(demo.domain_id)
            if evaluation.get("action") != demo.expected.rule_outcome:
                errors.append(f"{demo.domain_id}: live rule outcome differs from golden fixture")
        except Exception as exc:
            errors.append(f"{demo.domain_id}: {exc}")
    try:
        evidence = validate_cbr_demonstrators()
    except Exception as exc:
        errors.append(f"demonstrators: {exc}")
        evidence = []
    _raise("cbr", errors)
    return [f"domains={len(demos)}", "goldens=5/5", *evidence]


def validate_claude_code_bridge() -> list[str]:
    """Validate Claude Code bridge for the validation workflow."""
    errors = _validate_claude_code_bridge()
    _raise("claude-code", errors)
    return [f"claude_skills={len(REQUIRED_CLAUDE_SKILLS)}"]


def validate_plugins() -> list[str]:
    """Check both plugin hosts against the four product workflows without writes."""
    from ruler.runtime.plugins import validate_plugin_catalogue

    _raise("plugins", validate_plugin_catalogue())
    return ["codex=product", "claude=product", "workflows=4", "marketplace=ruler"]


def validate_codex_bridge() -> list[str]:
    """Validate the Codex repository instruction and skill surface."""
    errors = _validate_codex_bridge()
    _raise("codex", errors)
    return ["instructions=AGENTS.md", "skills=canonical"]


def validate_opencode_bridge() -> list[str]:
    """Validate OpenCode bridge for the validation workflow."""
    errors = _validate_opencode_bridge()
    _raise("OpenCode", errors)
    return [
        f"opencode_skills={len(REQUIRED_OPENCODE_SKILLS)}",
        f"opencode_commands={len(REQUIRED_OPENCODE_COMMANDS)}",
    ]


def validate_cross_platform() -> list[str]:
    """Validate cross platform for the validation workflow."""
    errors = _validate_cross_platform()
    _raise("cross-platform", errors)
    return ["platforms=macos-linux-windows"]


def validate_generative_api_config() -> list[str]:
    """Validate generative API config for the validation workflow."""
    errors = _validate_generative_api_config()
    if not GEN_API_CONFIG_FILE.exists():
        errors.append("missing data/reference/generative_api_config.yaml")
    _raise("api-config", errors)
    from ruler.runtime.api_config import load_generative_api_config

    config = load_generative_api_config()
    return [
        f"providers={len(config.providers)}",
        f"default_provider={config.default_provider}",
        "secrets=redacted",
    ]


def validate_mcp_server() -> list[str]:
    """Check the actual product allowlist and default write/execution guards."""
    import asyncio
    from ruler.runtime.mcp_server import (
        MCP_TOOL_NAMES,
        _create_mcp_server,
        create_mcp_server,
        mcp_manifest,
    )

    errors = []
    expected = {
        "ruler_prepare_knowledge",
        "ruler_prepare_request",
        "ruler_execute_reasoning",
        "ruler_retrieve_results",
    }
    manifest = mcp_manifest()

    async def check():
        for server in (_create_mcp_server(), create_mcp_server()):
            names = {tool.name for tool in await server.list_tools()}
            if names != expected:
                errors.append("MCP must expose exactly the four product workflows")
            if await server.list_resources():
                errors.append("MCP must not advertise developer resources")
        local = _create_mcp_server()
        _, blocked = await local.call_tool(
            "ruler_prepare_knowledge", {"input": {"action": "apply_import", "plan_id": "missing"}}
        )
        if blocked.get("status") != "blocked":
            errors.append("knowledge mutations require explicit write authorization")

    asyncio.run(check())
    if set(MCP_TOOL_NAMES) != expected or set(manifest["tools"]) != expected:
        errors.append("manifest and product tools differ")
    if manifest["persistence"] != {
        "backend": "postgresql",
        "migrations": "alembic",
        "filesystem_fallback": False,
    }:
        errors.append("MCP requires PostgreSQL without filesystem fallback")
    if manifest["resource_templates"] != ["ruler://artifacts/{digest}"]:
        errors.append("only workspace artifact resources are supported")
    _raise("mcp-server", errors)
    return ["tools=4", "resources=0"]


def validate_inference_dashboard() -> list[str]:
    """Validate inference dashboard for the validation workflow."""
    return _validate_inference_dashboard()


def validate_kb_visualizer() -> list[str]:
    """Validate the unified, path-free KB visualizer."""
    return _validate_kb_visualizer()


def validate_formalization_wave() -> list[str]:
    """Validate reusable wave contracts and the concrete vNext evidence bundle."""
    try:
        return validate_formalization_wave_configuration()
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationErrorGroup("formalization-wave", [str(exc)]) from exc


def validate_formalization_coverage() -> list[str]:
    """Validate exact inventory accounting and canonical skill-wave ownership."""
    try:
        return _validate_formalization_coverage()
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationErrorGroup("formalization-coverage", [str(exc)]) from exc


def validate_formalization_completion() -> list[str]:
    """Validate reviewed overlays and exact completion-gate accounting."""
    try:
        return _validate_formalization_completion()
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationErrorGroup("formalization-completion", [str(exc)]) from exc


def validate_formalization_governance() -> list[str]:
    """Validate compiler, behavioral, mutation, and immutable-release contracts."""
    from ruler.kb.asp_compiler import COMPILER_VERSION
    from ruler.kb.behavioral_validation import MANDATORY_CASE_KINDS
    from ruler.kb.formalization_mutation import REQUIRED_MUTATION_OPERATORS
    from ruler.kb.formalization_release import FormalLogicRelease
    from ruler.kb.prolog_compiler import PROLOG_COMPILER_VERSION

    errors: list[str] = []
    if len(MANDATORY_CASE_KINDS) != 6:
        errors.append("behavioral gate must retain six case perspectives")
    if len(REQUIRED_MUTATION_OPERATORS) != 8:
        errors.append("mutation gate must retain eight high-risk operators")
    release_fields = set(FormalLogicRelease.model_fields)
    required_release_fields = {
        "source_version_hashes",
        "span_hashes",
        "ir_sha256",
        "compiler_hashes",
        "generated_program_hashes",
        "validator_hashes",
        "review_decision_hashes",
    }
    missing = sorted(required_release_fields - release_fields)
    if missing:
        errors.append("immutable release contract missing: " + ", ".join(missing))
    if not COMPILER_VERSION or not PROLOG_COMPILER_VERSION:
        errors.append("formal compiler versions must be explicit")
    if errors:
        raise ValidationErrorGroup("formalization-governance", errors)
    return [
        f"asp_compiler={COMPILER_VERSION}",
        f"prolog_compiler={PROLOG_COMPILER_VERSION}",
        f"behavioral_kinds={len(MANDATORY_CASE_KINDS)}",
        f"mutation_operators={len(REQUIRED_MUTATION_OPERATORS)}",
        "immutable_release=bound",
    ]


def validate_kb_statistics() -> list[str]:
    """Recompute descriptive KB statistics without writing generated artifacts."""
    from ruler.kb.statistics import validate_kb_statistics as validate_statistics

    try:
        return validate_statistics()
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationErrorGroup("kb-statistics", [str(exc)]) from exc


def validate_formalized_kb() -> list[str]:
    """Validate formalized KB for the validation workflow."""
    try:
        return validate_formalized_kb_artifacts()
    except ValueError as exc:
        raise ValidationErrorGroup("formalized-kb", [str(exc)]) from exc


def validate_translation_control() -> list[str]:
    """Validate translation control for the validation workflow."""
    errors = validate_translation_control_artifacts()
    _raise("translation-control", errors)
    report = read_yaml(AUTOFORMALIZATION_ALIGNMENT_FILE)
    checks = report.get("checks", []) if isinstance(report, dict) else []
    failing = [check for check in checks if check.get("status") != "pass"]
    if failing:
        raise ValidationErrorGroup(
            "translation-control",
            [
                f"{check.get('span_id')}: alignment status {check.get('status')}"
                for check in failing
            ],
        )
    return [
        f"translation_units={report.get('translation_unit_count', 0)}",
        f"glossary_terms={report.get('glossary_term_count', 0)}",
        f"predicate_mappings={report.get('predicate_mapping_count', 0)}",
    ]


def validate_vocabulary_predicates() -> list[str]:
    """Validate vocabulary predicates for the validation workflow."""
    errors: list[str] = []
    payload = read_yaml(VOCABULARY_PREDICATE_MAP_FILE)
    approved_payload = read_yaml(REPO_ROOT / "tests/fixtures/translation/approved_predicates.yaml")
    approved = set(approved_payload.get("approved_predicates", []))
    if not isinstance(payload, list) or not payload:
        raise ValidationErrorGroup("vocabulary-predicates", ["vocabulary predicate map is empty"])
    for item in payload:
        predicate = str(item.get("predicate", ""))
        predicate_name = predicate.split("(", 1)[0].split("/", 1)[0]
        if predicate_name not in approved:
            errors.append(f"{item.get('term_id')}: predicate {predicate_name} is not approved")
        if not item.get("preferred_english"):
            errors.append(f"{item.get('term_id')}: missing preferred English")
        if not item.get("source_term"):
            errors.append(f"{item.get('term_id')}: missing source term")
    _raise("vocabulary-predicates", errors)
    return [f"vocabulary_predicates={len(payload)}"]


def validate_prolog_nl_comments() -> list[str]:
    """Require explanatory statement anchors in canonical generated logic."""
    from ruler.kb.corpus_manifest import discover_corpus_manifests, load_corpus_manifest

    errors: list[str] = []
    count = 0
    for path in discover_corpus_manifests():
        for artifact in load_corpus_manifest(path).artifacts:
            if artifact.artifact_type not in {"asp_program", "prolog_program"}:
                continue
            text = (REPO_ROOT / artifact.path).read_text()
            count += 1
            if "% generated by ruler-ir-" in text and "% statement:" not in text:
                errors.append(f"{artifact.artifact_id}: generated logic lacks statement anchors")
    _raise("prolog-nl-comments", errors)
    return [f"compiled_targets={count}", "statement_anchors=checked"]


def validate_skill_reasoning_logs() -> list[str]:
    """Validate catalogue profiles separately from real skill invocation events."""
    errors = validate_skill_reasoning_log_artifacts()
    _raise("skill-reasoning-logs", errors)
    profiles = discover_skill_files()
    return [f"profiles={len(profiles)}", "one_per_skill=yes", "execution=event_backed"]


def _is_prolog_rule_head(line: str) -> bool:
    """Internal helper for is Prolog rule head in the validation workflow."""
    if (
        not line
        or line.startswith("%")
        or line.startswith(("source_clause", "operational_predicate_source"))
    ):
        return False
    if line.endswith(".") and ":-" not in line:
        return "(" in line and ")" in line
    return line.endswith(":-")


def validate_progressive_onboarding() -> list[str]:
    """Validate bounded batches and their append-only evidence checkpoints."""
    from ruler.ingestion.progressive_onboarding import (
        validate_progressive_onboarding as validate_artifacts,
    )

    try:
        return validate_artifacts()
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationErrorGroup("progressive-onboarding", [str(exc)]) from exc


def validate_batch_pipeline() -> list[str]:
    """Validate the portable per-batch construction catalogue and stage contract."""
    from ruler.ingestion.batch_pipeline import validate_batch_pipeline as validate_artifacts

    try:
        return validate_artifacts()
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationErrorGroup("batch-pipeline", [str(exc)]) from exc
