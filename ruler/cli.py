# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Command-line entrypoint for RULER. The CLI exposes workflow execution, artifact
generation, and validation gates so the reasoning framework can be run consistently by
humans, hooks, and external agents.
"""

from __future__ import annotations

import os
import secrets
import shlex
import subprocess
import sys
from typing import Literal
from pathlib import Path

import click
import yaml
from rich.console import Console

from ruler.source.source_corpus import (
    extract_exact_documents,
    MAX_EXACT_DOCUMENT_BYTES,
    MAX_EXACT_DOCUMENT_PAGES,
)
from ruler.runtime.api_config import load_generative_api_config
from ruler.kb.formalized_kb import write_formalized_kb_artifacts
from ruler.runtime.hooks import run_hook
from ruler.interfaces.inference_dashboard import write_inference_control_dashboard_artifacts
from ruler.interfaces.kb_visualizer import write_kb_visualizer_artifact
from ruler.io import write_yaml
from ruler.paths import BUILD_DIR
from ruler.interfaces.skill_reasoning_logs import (
    append_skill_log_guardian,
    announce_skill_log_paths,
    write_skill_reasoning_log_artifacts,
)
from ruler.runtime.validation import (
    validate_progressive_onboarding,
    validate_batch_pipeline,
    ValidationErrorGroup,
    validate_claude_code_bridge,
    validate_codex_bridge,
    validate_plugins,
    validate_cross_platform,
    validate_deterministic_skills,
    validate_resource_portfolio,
    validate_generative_api_config,
    validate_generative_kb_quality,
    validate_contracts,
    validate_deps,
    validate_formalized_kb,
    validate_formalization_completion,
    validate_formalization_coverage,
    validate_formalization_governance,
    validate_formalization_wave,
    validate_hooks,
    validate_inference_dashboard,
    validate_kb_workspace,
    validate_kb_visualizer,
    validate_mcp_server,
    validate_opencode_bridge,
    validate_skill_reasoning_logs,
    validate_skills,
    validate_translation_control,
    validate_vocabulary_predicates,
    validate_workflow_graphs,
    validate_workflow_registry,
    validate_workflow_router,
    validate_kb_statistics,
    validate_prolog_nl_comments,
    validate_cbr,
)
from ruler.kb.translation_control import write_translation_control_artifacts
from ruler.interfaces.workflow_graphs import write_workflow_graph_artifacts
from ruler.interfaces.workflow_router import (
    guide_workflow_intent,
    route_workflow_intent,
    write_workflow_router_artifacts,
)

console = Console()


def _run_validation(label: str, func, *, target: Console | None = None) -> None:
    """Internal helper for run validation in the cli workflow."""
    target = target or console
    try:
        messages = func()
    except ValidationErrorGroup as exc:
        target.print(f"[red]{label} failed[/red]")
        for error in exc.errors:
            target.print(f"  - {error}")
        raise click.Abort() from exc
    target.print(f"[green]{label} ok[/green] " + ", ".join(messages))


@click.group()
def main() -> None:
    """RULER controlled reasoning CLI."""


@main.group()
def validate() -> None:
    """Run deterministic validation gates."""


@validate.command("deps")
def validate_deps_command() -> None:
    _run_validation("deps", validate_deps)


@validate.command("contracts")
def validate_contracts_command() -> None:
    _run_validation("contracts", validate_contracts)


@validate.command("skills")
def validate_skills_command() -> None:
    _run_validation("skills", validate_skills)


@validate.command("deterministic-skills")
def validate_deterministic_skills_command() -> None:
    """Validate executable runtime skill contracts and backend evidence routes."""
    _run_validation("deterministic-skills", validate_deterministic_skills)


@validate.command("resource-portfolio")
def validate_resource_portfolio_command() -> None:
    """Execute real Z3, HiGHS, CP-SAT, verification, and explanation checks."""
    _run_validation("resource-portfolio", validate_resource_portfolio)


@validate.command("hooks")
def validate_hooks_command() -> None:
    _run_validation("hooks", validate_hooks)


@validate.command("workflow-graphs")
def validate_workflow_graphs_command() -> None:
    _run_validation("workflow-graphs", validate_workflow_graphs)


@validate.command("workflow-router")
def validate_workflow_router_command() -> None:
    _run_validation("workflow-router", validate_workflow_router)


@validate.command("workflow-registry")
def validate_workflow_registry_command() -> None:
    _run_validation("workflow-registry", validate_workflow_registry)


@validate.command("generative-kb-quality")
def validate_generative_kb_quality_command() -> None:
    _run_validation("generative-kb-quality", validate_generative_kb_quality)


@validate.command("claude-code")
def validate_claude_code_command() -> None:
    _run_validation("claude-code", validate_claude_code_bridge)


@validate.command("codex")
def validate_codex_command() -> None:
    _run_validation("codex", validate_codex_bridge)


@validate.command("plugins")
def validate_plugins_command() -> None:
    """Check Codex/Claude plugin manifests and skill coverage without writes."""
    _run_validation("plugins", validate_plugins)


@validate.command("opencode")
def validate_OpenCode_command() -> None:
    _run_validation("opencode", validate_opencode_bridge)


@validate.command("cross-platform")
def validate_cross_platform_command() -> None:
    _run_validation("cross-platform", validate_cross_platform)


@validate.command("api-config")
def validate_api_config_command() -> None:
    _run_validation("api-config", validate_generative_api_config)


@validate.command("mcp-server")
def validate_mcp_server_command() -> None:
    _run_validation("mcp-server", validate_mcp_server)


@validate.command("inference-dashboard")
def validate_inference_dashboard_command() -> None:
    _run_validation("inference-dashboard", validate_inference_dashboard)


@validate.command("kb-visualizer")
def validate_kb_visualizer_command() -> None:
    """Validate the unified, self-contained KB visualizer."""
    _run_validation("kb-visualizer", validate_kb_visualizer)


@validate.command("kb-workspace")
def validate_kb_workspace_command() -> None:
    """Validate named KB management, search, routing, API, and visual shell."""
    _run_validation("kb-workspace", validate_kb_workspace)


@validate.command("kb-statistics")
def validate_kb_statistics_command() -> None:
    """Recompute KB/document statistics and validate their internal consistency."""
    _run_validation("kb-statistics", validate_kb_statistics)


@validate.command("formalization-wave")
def validate_formalization_wave_command() -> None:
    _run_validation("formalization-wave", validate_formalization_wave)


@validate.command("formalization-coverage")
def validate_formalization_coverage_command() -> None:
    _run_validation("formalization-coverage", validate_formalization_coverage)


@validate.command("formalization-completion")
def validate_formalization_completion_command() -> None:
    _run_validation("formalization-completion", validate_formalization_completion)


@validate.command("formalization-governance")
def validate_formalization_governance_command() -> None:
    _run_validation("formalization-governance", validate_formalization_governance)


@validate.command("formalized-kb")
def validate_formalized_kb_command() -> None:
    _run_validation("formalized-kb", validate_formalized_kb)


@validate.command("translation-control")
def validate_translation_control_command() -> None:
    _run_validation("translation-control", validate_translation_control)


@validate.command("vocabulary-predicates")
def validate_vocabulary_predicates_command() -> None:
    _run_validation("vocabulary-predicates", validate_vocabulary_predicates)


@validate.command("prolog-nl-comments")
def validate_prolog_nl_comments_command() -> None:
    _run_validation("prolog-nl-comments", validate_prolog_nl_comments)


@validate.command("skill-reasoning-logs")
def validate_skill_reasoning_logs_command() -> None:
    """Validate catalogue-wide skill log contracts and actual invocation events."""
    _run_validation("skill-reasoning-logs", validate_skill_reasoning_logs)


@validate.command("cbr")
def validate_cbr_command() -> None:
    """Run deterministic CBR contracts, goldens, safety, and demo checks."""
    _run_validation("cbr", validate_cbr)


@validate.command("all")
def validate_all_command() -> None:
    """Run every offline validation without repairing or generating its inputs."""
    validators = (
        ("deps", validate_deps),
        ("contracts", validate_contracts),
        ("inference-dashboard", validate_inference_dashboard),
        ("kb-visualizer", validate_kb_visualizer),
        ("kb-workspace", validate_kb_workspace),
        ("progressive-onboarding", validate_progressive_onboarding),
        ("batch-pipeline", validate_batch_pipeline),
        ("kb-statistics", validate_kb_statistics),
        ("formalization-completion", validate_formalization_completion),
        ("formalization-coverage", validate_formalization_coverage),
        ("formalization-governance", validate_formalization_governance),
        ("formalization-wave", validate_formalization_wave),
        ("formalized-kb", validate_formalized_kb),
        ("translation-control", validate_translation_control),
        ("vocabulary-predicates", validate_vocabulary_predicates),
        ("prolog-nl-comments", validate_prolog_nl_comments),
        ("skill-reasoning-logs", validate_skill_reasoning_logs),
        ("workflow-graphs", validate_workflow_graphs),
        ("workflow-registry", validate_workflow_registry),
        ("workflow-router", validate_workflow_router),
        ("codex", validate_codex_bridge),
        ("plugins", validate_plugins),
        ("claude-code", validate_claude_code_bridge),
        ("opencode", validate_opencode_bridge),
        ("cross-platform", validate_cross_platform),
        ("api-config", validate_generative_api_config),
        ("mcp-server", validate_mcp_server),
        ("generative-kb-quality-config", validate_generative_kb_quality),
        ("skills", validate_skills),
        ("deterministic-skills", validate_deterministic_skills),
        ("resource-portfolio", validate_resource_portfolio),
        ("hooks", validate_hooks),
        ("cbr", validate_cbr),
    )
    for label, validator in validators:
        _run_validation(label, validator)
    for label, args in (
        ("pytest", ["uv", "run", "pytest", "-q"]),
        ("ruff", ["uv", "run", "ruff", "check", "."]),
        ("diff-check", ["git", "diff", "--check"]),
    ):
        result = subprocess.run(args, cwd=Path.cwd(), capture_output=True, text=True, check=False)
        if result.returncode:
            raise click.ClickException(f"{label} failed: {result.stdout}{result.stderr}")
        console.print(f"[green]{label} ok[/green]")
    console.print(
        "[yellow]live source and Codex profiles skipped[/yellow] explicit budgeted workflows only"
    )


@validate.command("tests")
def validate_tests_command() -> None:
    result = subprocess.run(
        ["uv", "run", "pytest", "-q"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout.strip():
        console.print(result.stdout.strip())
    if result.stderr.strip():
        console.print(result.stderr.strip())
    if result.returncode != 0:
        raise click.Abort()
    console.print("[green]tests ok[/green]")


@main.group()
def workflow() -> None:
    """Run reasoning workflows."""


@main.group("ingestion")
def ingestion_group() -> None:
    """Run provider-neutral, checkpointed ingestion stages."""


def _ingestion_stage_command(stage: str):
    @click.option("--provider", required=True)
    @click.option("--batch-id", required=True)
    @click.option("--select", "selectors", multiple=True)
    @click.option("--output-root", type=click.Path(path_type=Path), required=True)
    @click.option("--dry-run", is_flag=True)
    @click.option("--resume", is_flag=True)
    @click.option("--max-download-bytes", type=int, default=100_000_000, show_default=True)
    @click.option("--max-pages", type=int, default=2_000, show_default=True)
    @click.option("--max-ocr-pages", type=int, default=500, show_default=True)
    @click.option("--max-model-calls", type=int, default=0, show_default=True)
    @click.option("--max-tokens", type=int, default=0, show_default=True)
    @click.option("--max-retries", type=int, default=3, show_default=True)
    @click.option("--max-duration-seconds", type=int, default=3_600, show_default=True)
    def command(**kwargs) -> None:
        from ruler.ingestion.operations import ResourceBudget, run_stage

        output_root = kwargs.pop("output_root")
        budget = ResourceBudget(
            download_bytes=kwargs.pop("max_download_bytes"),
            pages=kwargs.pop("max_pages"),
            ocr_pages=kwargs.pop("max_ocr_pages"),
            model_calls=kwargs.pop("max_model_calls"),
            tokens=kwargs.pop("max_tokens"),
            retries=kwargs.pop("max_retries"),
            duration_seconds=kwargs.pop("max_duration_seconds"),
        )
        report = run_stage(stage, output_root=output_root, budget=budget, **kwargs)
        console.print_json(data=report.model_dump(mode="json"))

    command.__name__ = f"ingestion_{stage.replace('-', '_')}_command"
    return command


for _stage_name in (
    "plan",
    "discover",
    "fetch",
    "extract",
    "assess-completeness",
    "formalize-candidates",
    "review",
    "compile",
    "publish",
    "validate",
    "replay-impacts",
):
    ingestion_group.command(_stage_name)(_ingestion_stage_command(_stage_name))


@workflow.command("resource-portfolio-plan")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def resource_portfolio_plan_command(output_dir: Path | None) -> None:
    """Run the real deterministic construction-fleet acceptance workflow."""
    from ruler.applications.resource_portfolio.workflow import write_sample_portfolio_artifacts

    destination = write_sample_portfolio_artifacts(output_dir or BUILD_DIR / "resource_portfolio")
    console.print(f"[green]wrote verified advisory resource portfolio[/green] {destination}")


@workflow.command("resource-portfolio-demonstrator")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
@click.option("--model", default="gpt-5.4", show_default=True)
@click.option(
    "--kb-profile",
    type=click.Choice(("compact", "expanded")),
    default="compact",
    show_default=True,
    help="Size of the synthetic natural-language knowledge base.",
)
@click.option(
    "--reuse-formalization",
    is_flag=True,
    help="Resume from an already authenticated formalization.yaml receipt.",
)
def resource_portfolio_demonstrator_command(
    output_dir: Path | None,
    model: str,
    kb_profile: Literal["compact", "expanded"],
    reuse_formalization: bool,
) -> None:
    """Run the live grounded NL-to-optimization HTML demonstrator."""
    from ruler.applications.resource_portfolio.demonstrator import (
        execute_grounded_demonstrator,
    )
    from ruler.kb.generative_autoformalization import GenerativeTransportError

    try:
        destination = execute_grounded_demonstrator(
            output_dir or BUILD_DIR / "resource_portfolio_demonstrator",
            model=model,
            reuse_formalization=reuse_formalization,
            kb_profile=kb_profile,
        )
    except (OSError, ValueError, GenerativeTransportError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]wrote grounded portfolio demonstrator[/green] {destination}")


def print_reason_case_artifacts(artifacts: dict[str, Path], *, output_console=None) -> None:
    """Render the single-case completion messages for CLI and MCP callers."""
    target = output_console if output_console is not None else console
    target.print("[green]wrote reasoning case artifacts[/green]")
    for name, path in artifacts.items():
        target.print(f"{name}: {path}")


@workflow.command("workflow-graphs")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def workflow_graphs_command(output_dir: Path | None) -> None:
    artifacts = _write_workflow_graph_artifacts(output_dir=output_dir)
    console.print("[green]wrote workflow graph artifacts[/green]")
    for name, path in artifacts.items():
        console.print(f"{name}: {path}")


@workflow.command("workflow-router")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def workflow_router_command(output_dir: Path | None) -> None:
    artifacts = _write_workflow_router_artifacts(output_dir=output_dir)
    console.print("[green]wrote workflow router artifacts[/green]")
    for name, path in artifacts.items():
        console.print(f"{name}: {path}")


@workflow.command("cbr-demonstrators")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def cbr_demonstrators_command(output_dir: Path | None) -> None:
    """Build the five governed CBR demonstrators and portfolio."""
    from ruler.interfaces.cbr_demonstrators import write_cbr_demonstrator_artifacts

    paths = write_cbr_demonstrator_artifacts(output_dir)
    for name, path in paths.items():
        console.print(f"{name}: {path}")


@workflow.command("cbr-case")
def cbr_case_workflow_command() -> None:
    """Validate the governed retrieve-adapt-verify CBR workflow."""
    _run_validation("cbr-case", validate_cbr)


@workflow.command("cbr-case-library-curation")
def cbr_case_library_curation_workflow_command() -> None:
    """Validate case libraries; retention remains an explicit reviewed command."""
    from ruler.domains.cbr_catalog import load_all_cbr_demos

    demos = load_all_cbr_demos()
    console.print(
        f"[green]cbr-case-library-curation ok[/green] libraries={len(demos)} "
        "mode=read-only retention='ruler cbr retain --apply'"
    )


@workflow.command("cbr-benchmark")
@click.option("--output-dir", type=click.Path(path_type=Path, file_okay=False), default=None)
def cbr_benchmark_command(output_dir: Path | None) -> None:
    """Write deterministic retrieval, contrast, adaptation, and verification evidence."""
    from ruler.interfaces.cbr_benchmark import write_cbr_benchmark

    for name, path in write_cbr_benchmark(output_dir).items():
        console.print(f"{name}: {path}")


@workflow.command("execution-catalogue")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def execution_catalogue_command(output_dir: Path | None) -> None:
    """Generate the verified workflow, hook, tool, and skill catalogue."""
    from ruler.runtime.workflow_registry import write_execution_catalogue

    paths = write_execution_catalogue(output_dir or BUILD_DIR)
    console.print(f"[green]execution catalogue ok[/green] {paths['yaml']}")


def _describe_registered_test_workflow(workflow_id: str) -> None:
    """Describe a test boundary without invoking a separately governed runner."""
    from ruler.runtime.workflow_registry import load_workflow_registry

    item = next(
        workflow
        for workflow in load_workflow_registry()["workflows"]
        if workflow["id"] == workflow_id
    )
    console.print(
        f"[green]{workflow_id} registered[/green] "
        f"tier={item['release_tier']} network={item['network']} tools={','.join(item['tools']) or 'none'}"
    )


def _load_registered_test_validators(workflow_id: str) -> list[str]:
    """Load the authoritative ordered validators, including registry defaults."""
    from ruler.runtime.workflow_registry import load_workflow_registry

    item = next(
        workflow
        for workflow in load_workflow_registry()["workflows"]
        if workflow["id"] == workflow_id
    )
    validators = item.get("validators", [])
    if not validators:
        raise click.ClickException(f"{workflow_id} has no governed validators")
    return validators


def _execute_registered_test_validator(command: str, *, cwd=None, target=None) -> None:
    """Resolve and execute one validator; retain native failure and console behavior."""
    from ruler.runtime.workflow_registry import resolve_cli_command

    resolution_error = resolve_cli_command(command)
    if resolution_error:
        raise click.ClickException(f"invalid validator {command!r}: {resolution_error}")
    completed = subprocess.run(
        shlex.split(command),
        cwd=Path.cwd() if cwd is None else Path(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise click.ClickException(
            f"validator failed: {command}\n{completed.stdout}{completed.stderr}"
        )
    (console if target is None else target).print(f"[green]validator ok[/green] {command}")


def _complete_registered_test_workflow(workflow_id: str, validators: list[str], *, target=None):
    """Emit the native exhaustion announcement."""
    (console if target is None else target).print(
        f"[green]{workflow_id} complete[/green] validators={len(validators)}"
    )


def _run_registered_test_workflow(workflow_id: str) -> None:
    """Execute every validator declared by a governed test workflow."""
    validators = _load_registered_test_validators(workflow_id)
    for command in validators:
        _execute_registered_test_validator(command)
    _complete_registered_test_workflow(workflow_id, validators)


@workflow.command("test-deterministic")
def test_deterministic_command() -> None:
    """Execute the deterministic test workflow's governed validators."""
    _run_registered_test_workflow("test-deterministic")


@workflow.command("test-generative-smoke")
def test_generative_smoke_command() -> None:
    """Execute bounded, unmocked Codex autoformalization smoke tests."""
    completed = _run_generative_smoke_pytest()
    if _generative_smoke_failed(completed):
        _raise_generative_smoke_failure(completed)
    _print_generative_smoke_success(completed)


def _run_generative_smoke_pytest(*, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Launch the native test collection once with the inherited profile."""
    environment = dict(os.environ)
    environment["RULER_RUN_LIVE_CODEX_AUTOFORMALIZATION"] = "1"
    return subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/generative/test_autoformalization_live.py",
            "-s",
        ],
        cwd=Path.cwd() if cwd is None else cwd,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _generative_smoke_failed(completed: subprocess.CompletedProcess) -> bool:
    return bool(completed.returncode)


def _raise_generative_smoke_failure(completed: subprocess.CompletedProcess) -> None:
    raise click.ClickException(
        f"live generative smoke tests failed\n{completed.stdout}{completed.stderr}"
    )


def _print_generative_smoke_success(
    completed: subprocess.CompletedProcess, *, target: Console | None = None
) -> None:
    target = console if target is None else target
    target.print(completed.stdout.strip())
    target.print("[green]test-generative-smoke complete[/green] transport=codex-exec")


@workflow.command("test-generative-local")
def test_generative_local_command() -> None:
    """Execute the network-free deterministic autoformalization profile."""

    _run_local_autoformalization_profile()


def _run_local_autoformalization_profile(
    *, cwd: Path | None = None, environment: dict | None = None, target=None
) -> None:
    """Run source integrity, parser, compiler, solver, profile, and mutation checks."""

    target = console if target is None else target
    completed = _run_local_autoformalization_pytest(cwd=cwd, environment=environment)
    if _local_autoformalization_failed(completed.returncode):
        _raise_local_autoformalization_failure(completed)
    _print_local_autoformalization_success(completed.stdout, target=target)


def _run_local_autoformalization_pytest(
    *, cwd: Path | None = None, environment: dict | None = None
) -> subprocess.CompletedProcess:
    """Wait for the single native local pytest process, preserving its context."""
    return subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/testing/test_autoformalization_case_corpus.py",
            "tests/testing/test_autoformalization_profiles.py",
            "tests/kb/test_generative_autoformalization.py",
        ],
        cwd=Path.cwd() if cwd is None else cwd,
        capture_output=True,
        text=True,
        check=False,
        **({"env": environment} if environment is not None else {}),
    )


def _local_autoformalization_failed(code: int) -> bool:
    """Use native return-code truthiness, including signal termination."""
    return bool(code)


def _raise_local_autoformalization_failure(completed: subprocess.CompletedProcess) -> None:
    raise click.ClickException(
        f"local generative profile failed\n{completed.stdout}{completed.stderr}"
    )


def _print_local_autoformalization_success(stdout: str, *, target=None) -> None:
    target = console if target is None else target
    target.print(stdout.strip())
    target.print("[green]test-generative-local complete[/green] network=false")


@workflow.command("test-generative-pr")
def test_generative_pr_command() -> None:
    """Execute the advisory three-style pull-request profile."""

    _run_live_autoformalization_profile("pr", repetitions=1)


@workflow.command("test-generative-integration")
def test_generative_integration_command() -> None:
    """Execute all five cases with one independent critic per case."""

    _run_local_autoformalization_profile()
    _run_live_autoformalization_profile("integration", repetitions=1)


@workflow.command("test-generative-release")
def test_generative_release_command() -> None:
    """Execute the unmocked multi-run generative release profile."""
    _run_local_autoformalization_profile()
    _run_live_autoformalization_profile("release", repetitions=3)


@workflow.command("test-generative-drift")
def test_generative_drift_command() -> None:
    """Execute the unmocked repeated generative drift profile."""
    _run_local_autoformalization_profile()
    _run_live_autoformalization_profile("drift", repetitions=2)


def _initialize_autoformalization_profile(profile: str, *, environment: dict | None = None) -> dict:
    """Capture the source process environment once for the repetition range."""
    environment = dict(os.environ if environment is None else environment)
    environment["RULER_RUN_LIVE_CODEX_AUTOFORMALIZATION"] = "1"
    environment["RULER_AUTOFORMALIZATION_PROFILE"] = profile
    environment["RULER_AUTOFORMALIZATION_REPETITION"] = "1"
    return {"repetition": 1, "environment": environment}


def _execute_autoformalization_repetition(
    profile: str, *, repetitions: int, state: dict, cwd: Path | None = None, target=None
) -> None:
    """Execute one fresh native pytest process and preserve its failure boundary."""
    target = console if target is None else target
    repetition = state["repetition"]
    completed = subprocess.run(
        ["uv", "run", "pytest", "-q", "tests/generative/test_autoformalization_live.py", "-s"],
        cwd=Path.cwd() if cwd is None else cwd,
        capture_output=True,
        text=True,
        check=False,
        env=state["environment"],
    )
    if completed.returncode:
        raise click.ClickException(
            f"{profile} generative tests failed at repetition {repetition}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    target.print(completed.stdout.strip())
    target.print(
        f"[green]generative {profile} repetition ok[/green] "
        f"repetition={repetition}/{repetitions} execution=fresh"
    )


def _advance_autoformalization_profile(state: dict, *, repetitions: int) -> tuple[dict, bool]:
    """Advance the native range cursor only after success, without aggregation."""
    if state["repetition"] == repetitions:
        return state, True
    environment = dict(state["environment"])
    repetition = state["repetition"] + 1
    environment["RULER_AUTOFORMALIZATION_REPETITION"] = str(repetition)
    return {"repetition": repetition, "environment": environment}, False


def _complete_autoformalization_profile(profile: str, *, repetitions: int, target=None) -> None:
    target = console if target is None else target
    target.print(
        f"[green]test-generative-{profile} complete[/green] "
        f"transport=codex-exec execution=fresh repetitions={repetitions}"
    )


def _run_live_autoformalization_profile(profile: str, *, repetitions: int) -> None:
    """Run explicit provider tests; never substitute cached output for a live profile."""
    # Preserve the empty-range behavior for callers other than the release callback.
    if repetitions > 0:
        state = _initialize_autoformalization_profile(profile)
        for _ in range(repetitions):
            _execute_autoformalization_repetition(profile, repetitions=repetitions, state=state)
            state, _done = _advance_autoformalization_profile(state, repetitions=repetitions)
    _complete_autoformalization_profile(profile, repetitions=repetitions)


@workflow.command("generative-kb-quality")
@click.option("--profile", required=True)
@click.option("--case-id", default=None)
@click.option("--model", default=None)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
@click.option("--dry-run", is_flag=True, default=False)
def generative_kb_quality_command(
    profile: str,
    case_id: str | None,
    model: str | None,
    output_dir: Path | None,
    dry_run: bool,
) -> None:
    """Run a bounded profile or one selected Codex quality assessment."""
    from ruler.runtime.generative_quality import (
        QUALITY_BUILD_DIR,
        load_quality_catalogue,
        resolve_quality_consensus,
        run_quality_case,
        write_consensus_bundle,
    )

    catalogue = load_quality_catalogue()
    if profile not in catalogue.profiles:
        raise click.ClickException(f"unknown profile: {profile}")
    selected_profile = catalogue.profiles[profile]
    selected_cases = [case_id] if case_id else selected_profile.case_ids
    selected_model = model or catalogue.allowed_models[0]
    unresolved = False
    for selected_case in selected_cases:
        attempts = 1 if dry_run or not selected_profile.blocking else selected_profile.max_calls
        results = [
            run_quality_case(
                selected_case,
                profile_name=profile,
                model=selected_model,
                output_dir=output_dir or QUALITY_BUILD_DIR,
                dry_run=dry_run,
                attempt=attempt + 1,
            )
            for attempt in range(attempts)
        ]
        if dry_run:
            status = results[0].status
        elif attempts > 1:
            status = resolve_quality_consensus(results).status
            consensus_path = write_consensus_bundle(
                results, output_dir=output_dir or QUALITY_BUILD_DIR
            )
            console.print(f"consensus: {consensus_path}")
        else:
            status = results[0].status
        console.print(
            f"[green]generative KB quality result[/green] case={selected_case} status={status}"
        )
        unresolved = unresolved or status != "pass"
    if selected_profile.blocking and unresolved and not dry_run:
        raise click.ClickException("blocking generative profile has unresolved results")


@workflow.command("calibrate-generative-judge")
@click.option("--model", required=True)
@click.option("--codex-version", required=True)
@click.option(
    "--judge-config",
    type=click.Path(path_type=Path, file_okay=True, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--results",
    type=click.Path(path_type=Path, file_okay=True, dir_okay=False, exists=True),
    default=None,
)
@click.option("--execute", is_flag=True, help="Explicitly execute the allowlisted Codex runner.")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def calibrate_generative_judge_command(
    model: str,
    codex_version: str,
    judge_config: Path,
    results: Path | None,
    execute: bool,
    output_dir: Path | None,
) -> None:
    """Execute or deterministically recalculate blind judge calibration."""
    from ruler.io import read_yaml
    from ruler.runtime.generative_calibration import (
        CALIBRATION_BUILD_DIR,
        load_and_calculate_calibration,
        run_calibration_suite,
    )

    if execute == (results is not None):
        raise click.ClickException("choose exactly one of --execute or --results")
    config = read_yaml(judge_config)
    if not isinstance(config, dict):
        raise click.ClickException("judge config must be a YAML/JSON mapping")
    destination = output_dir or CALIBRATION_BUILD_DIR
    if execute:
        certification = run_calibration_suite(
            model=model,
            codex_version=codex_version,
            judge_config=config,
            output_dir=destination,
        )
    else:
        assert results is not None  # The exclusive CLI options are checked above.
        certification = load_and_calculate_calibration(
            results,
            model=model,
            codex_version=codex_version,
            judge_config=config,
            output_dir=destination,
        )
    console.print(
        f"[green]generative judge calibration calculated[/green] "
        f"certification={certification.certification_id} calibrated={certification.calibrated}"
    )
    if not certification.calibrated:
        raise click.ClickException(
            f"judge remains advisory: {list(certification.threshold_failures)}"
        )


@workflow.command("inference-dashboard")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def inference_dashboard_command(output_dir: Path | None) -> None:
    artifacts = _write_inference_dashboard_artifacts(output_dir=output_dir)
    print_inference_dashboard_paths(artifacts)


def print_inference_dashboard_paths(artifacts: dict[str, Path], *, target=None) -> None:
    """Keep CLI and MCP path reporting on the same source-owned console path."""
    output = target if target is not None else console
    output.print("[green]wrote inference control dashboard artifacts[/green]")
    for name, path in artifacts.items():
        output.print(f"{name}: {path}")


@workflow.command("kb-visualizer")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def kb_visualizer_command(output_dir: Path | None) -> None:
    """Build the consolidated logical KB visualizer without internal locations."""
    write_kb_visualizer_artifact(output_dir=output_dir)
    console.print("[green]wrote consolidated logical KB visualizer[/green]")


@workflow.command("progressive-product-onboarding")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def progressive_product_onboarding_command(output_dir: Path | None) -> None:
    """Prepare small ordered batches and seed their append-only progress ledger."""
    from ruler.ingestion.onboarding_workflow import (
        initialize_onboarding,
        catalogue_onboarding,
        announce_onboarding,
    )

    artifacts = initialize_onboarding(output_dir)
    if output_dir is None:
        artifacts = catalogue_onboarding(artifacts)
    announce_onboarding(artifacts, console)


@workflow.command("product-batch-pipeline")
@click.option("--batch-id", required=True)
@click.option(
    "--stage",
    required=True,
    type=click.Choice(
        [
            "status",
            "planned",
            "sources-ready",
            "extracted",
            "completeness-verified",
            "formalized",
            "deterministic-verified",
            "generative-verified",
            "coherence-verified",
            "published",
            "revision",
            "source-revision",
            "scope-revision",
        ]
    ),
)
@click.option("--model", default=None, help="Allowlisted model for generative-verified only.")
@click.option("--dry-run", is_flag=True, help="Report readiness without changing progress.")
def product_batch_pipeline_command(
    batch_id: str, stage: str, model: str | None, dry_run: bool
) -> None:
    """Run one legal stage of the portable progressive KB construction pipeline."""
    from ruler.ingestion.batch_pipeline import PipelineStage, run_batch_stage

    try:
        result = run_batch_stage(batch_id, PipelineStage(stage), model=model, dry_run=dry_run)
    except (OSError, TypeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=result)


@workflow.command("onboarding-checkpoint")
@click.option("--batch-id", required=True)
@click.option(
    "--stage",
    required=True,
    type=click.Choice(
        [
            "planned",
            "sources_ready",
            "extracted",
            "completeness_verified",
            "formalized",
            "deterministic_verified",
            "generative_verified",
            "coherence_verified",
            "published",
            "blocked",
        ]
    ),
)
@click.option("--evidence-id", multiple=True)
@click.option("--note", required=True)
def onboarding_checkpoint_command(
    batch_id: str, stage: str, evidence_id: tuple[str, ...], note: str
) -> None:
    """Append one evidence-bound legal progress transition for a bounded batch."""
    from ruler.ingestion.progressive_onboarding import (
        OnboardingStage,
        append_progress_checkpoint,
    )

    event = append_progress_checkpoint(
        batch_id, OnboardingStage(stage), evidence_ids=evidence_id, note=note
    )
    console.print_json(data=event.model_dump(mode="json"))


@workflow.command("kb-statistics")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def kb_statistics_command(output_dir: Path | None) -> None:
    """Generate descriptive statistics without changing source or KB truth."""
    from ruler.kb.statistics import KB_STATISTICS_DIR, write_kb_statistics

    artifacts = write_kb_statistics(output_dir or KB_STATISTICS_DIR)
    console.print("[green]wrote KB and document statistics[/green]")
    for name, path in artifacts.items():
        console.print(f"{name}: {path}")


def print_priority_policy_sample_summary(manifest: dict) -> None:
    """Validate the fetch-only boundary and print the native summary."""
    if manifest.get("mode") != "bounded_fetch_only_no_extraction_no_formalization_no_publication":
        raise click.ClickException("sample crawl returned an unsafe execution mode")
    summary = manifest.get("summary", {})
    if any(summary.get(field) != 0 for field in ("extracted", "formalized", "published")):
        raise click.ClickException("sample crawl crossed its fetch-only boundary")
    console.print("[green]bounded fetch-only sample complete[/green]")
    for key, value in summary.items():
        console.print(f"{key}: {value}")


@workflow.command("formalized-kb")
def formalized_kb_command() -> None:
    artifacts = _write_formalized_kb_artifacts()
    console.print("[green]wrote formalized KB artifacts[/green]")
    for name, path in artifacts.items():
        console.print(f"{name}: {path}")


@workflow.command("translation-control")
def translation_control_command() -> None:
    artifacts = write_translation_control_artifacts()
    console.print("[green]wrote translation-control artifacts[/green]")
    for name, path in artifacts.items():
        console.print(f"{name}: {path}")


def formalization_wave_write_step() -> dict[str, Path]:
    """Write the native coverage artifacts before any validation."""
    from ruler.kb.formalization_artifacts import write_formalization_coverage_artifacts

    return write_formalization_coverage_artifacts()


def formalization_wave_validation_step(stage: str) -> list[str]:
    """Run a single native gate and retain the CLI's observable messages."""
    validators = {
        "wave": validate_formalization_wave,
        "coverage": validate_formalization_coverage,
        "completion": validate_formalization_completion,
        "governance": validate_formalization_governance,
    }
    messages = validators[stage]()
    for message in messages:
        console.print(f"[green]formalization-{stage} ok[/green] {message}")
    return messages


@workflow.command("formalization-wave")
def formalization_wave_command() -> None:
    """Build honest coverage artifacts and validate canonical wave evidence."""
    formalization_wave_write_step()
    formalization_wave_validation_step("wave")
    formalization_wave_validation_step("coverage")
    formalization_wave_validation_step("completion")
    formalization_wave_validation_step("governance")


@workflow.command("skill-reasoning-logs")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def skill_reasoning_logs_command(output_dir: Path | None) -> None:
    """Write one observability profile per skill and preserve actual events."""
    artifacts = write_skill_reasoning_log_artifacts(output_dir=output_dir)
    append_skill_log_guardian(artifacts, output_dir=output_dir)
    artifacts = write_skill_reasoning_log_artifacts(output_dir=output_dir)
    announce_skill_log_paths(artifacts, console)


def announce_run_gates(artifacts: dict[str, Path], *, target: Console | None = None) -> None:
    """Shared final success announcement, only reached after validation."""
    (target or console).print(f"[green]wrote gate artifacts[/green] {artifacts['gates']}")


@main.group("route")
def route_group() -> None:
    """Route natural-language workflow intents to known skills and commands."""


@route_group.command("query")
@click.argument("intent", nargs=-1)
@click.option("--top-k", type=int, default=3, show_default=True)
def route_query_command(intent: tuple[str, ...], top_k: int) -> None:
    query = " ".join(intent).strip()
    if not query:
        raise click.UsageError("provide an intent, e.g. ruler route query customer demo")
    packet = route_workflow_intent(query, top_k=top_k)
    console.print(f"[green]selected route[/green] {packet.selected_route_id}")
    for candidate in packet.candidates:
        console.print(f"\n[bold]{candidate.title}[/bold] score={candidate.score}")
        console.print(f"hook: {candidate.hook}")
        console.print("skills: " + ", ".join(candidate.skills))
        console.print("commands:")
        for command in candidate.workflow_commands:
            console.print(f"  - {command}")
        if candidate.validation_commands:
            console.print("validation:")
            for command in candidate.validation_commands:
                console.print(f"  - {command}")


@route_group.command("guide")
@click.argument("intent", nargs=-1)
@click.option("--top-k", type=click.IntRange(1, 10), default=3, show_default=True)
@click.option(
    "--allow-network",
    is_flag=True,
    help="Allow the configured provider to interpret intent; never executes a workflow.",
)
def route_guide_command(intent: tuple[str, ...], top_k: int, allow_network: bool) -> None:
    """Interpret intent and return advisory guidance over registered workflows."""

    query = " ".join(intent).strip()
    if not query:
        raise click.UsageError("provide an intent, e.g. ruler route guide compare options")
    packet = guide_workflow_intent(query, top_k=top_k, allow_network=allow_network)
    console.print(f"[green]orchestrator status[/green] {packet.status}")
    console.print(f"interpreted intent: {packet.interpreted_intent}")
    console.print("selected routes: " + (", ".join(packet.selected_route_ids) or "none"))
    for item in packet.guidance:
        console.print(f"  - {item}")
    if packet.clarification_question:
        console.print(f"clarification: {packet.clarification_question}")
    for route in packet.routes:
        console.print(f"\n[bold]{route.title}[/bold] ({route.route_id})")
        console.print(route.description)
        console.print("skills: " + ", ".join(route.skills))
        console.print("canonical commands:")
        for command in route.workflow_commands:
            console.print(f"  - {command}")
    console.print("[dim]Advisory only: no workflow was executed and no artifact was written.[/dim]")


@route_group.command("catalogue")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
)
def route_catalogue_command(output_dir: Path | None) -> None:
    artifacts = _write_workflow_router_artifacts(output_dir=output_dir)
    console.print("[green]wrote workflow router catalogue[/green]")
    for name, path in artifacts.items():
        console.print(f"{name}: {path}")


@main.group()
def config() -> None:
    """Inspect RULER runtime configuration."""


@config.command("generative")
@click.option("--workflow", default=None, help="Optional workflow name, e.g. extraction.")
def config_generative_command(workflow: str | None) -> None:
    summary = load_generative_api_config().redacted_summary(workflow=workflow)
    console.print(yaml.safe_dump(summary, sort_keys=False))


@main.group()
def prepare() -> None:
    """Generate explicit prerequisites before running read-only validation gates."""


@prepare.command("agent-config")
def prepare_agent_config_command() -> None:
    """Create missing ignored agent defaults without replacing local settings."""
    from ruler.runtime.agent_setup import prepare_agent_config

    created = prepare_agent_config()
    console.print(f"[green]Agent configuration prepared[/green] files_created={len(created)}")


@prepare.command("plugins")
@click.option("--refresh-manifests", is_flag=True, help="Update tracked plugin declarations first.")
def prepare_plugins_command(refresh_manifests: bool) -> None:
    """Build the skills-only plugin marketplace under build/ruler/plugins."""
    from ruler.runtime.plugins import prepare_plugin_package, refresh_plugin_manifests

    try:
        if refresh_manifests:
            refresh_plugin_manifests()
        destination = prepare_plugin_package()
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from None
    console.print(f"[green]RULER plugin marketplace prepared[/green] {destination}")


@prepare.command("checks")
@click.pass_context
def prepare_checks_command(ctx: click.Context) -> None:
    """Build offline check artifacts from repository evidence; never fetch sources."""
    from ruler.runtime.check_prerequisites import (
        CHECK_WORKFLOWS,
        CHECK_WORKFLOW_OPTIONS,
        check_native_prerequisites,
    )

    try:
        check_native_prerequisites()
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from None
    ctx.invoke(prepare_agent_config_command)
    for name in CHECK_WORKFLOWS:
        console.print(f"[green]preparing[/green] {name}")
        ctx.invoke(workflow.commands[name], **CHECK_WORKFLOW_OPTIONS.get(name, {}))
    console.print("[green]Check prerequisites prepared from local evidence.[/green]")


@main.group()
def database() -> None:
    """Manage the PostgreSQL persistence used by MCP."""


@database.command("upgrade")
def database_upgrade_command() -> None:
    """Apply Alembic migrations to the configured PostgreSQL database."""
    from ruler.persistence.database import upgrade_database

    try:
        upgrade_database()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    except Exception:
        raise click.ClickException("PostgreSQL migration failed; check database access") from None
    console.print("PostgreSQL migrations applied.")


@database.command("import-workspace")
@click.option(
    "--source", type=click.Path(exists=True, file_okay=False, path_type=Path), default="."
)
@click.option("--workspace", default=None, help="Defaults to RULER_MCP_WORKSPACE or default.")
def database_import_workspace_command(source: Path, workspace: str | None) -> None:
    """Copy existing local data into a new PostgreSQL workspace atomically."""
    from ruler.persistence.workspace import PostgresWorkspace

    store = None
    try:
        store = PostgresWorkspace(workspace_id=workspace)
        count = store.import_workspace(source)
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        if store is not None:
            store.engine.dispose()
    console.print(f"Imported {count} artifacts into PostgreSQL.")


@database.command("prepare-deployment")
@click.option(
    "--source", type=click.Path(exists=True, file_okay=False, path_type=Path), default="."
)
@click.option(
    "--preprovisioned-runtime",
    is_flag=True,
    help="Shared instance: require existing restricted logins; never create/rotate roles.",
)
def database_prepare_deployment_command(source: Path, preprovisioned_runtime: bool) -> None:
    """Migrate, seed a missing workspace, and grant the separate runtime user access."""
    from ruler.persistence.deployment import prepare_deployment

    if not os.environ.get("RULER_RUNTIME_DATABASE_URL"):
        raise click.ClickException("RULER_RUNTIME_DATABASE_URL is required")
    try:
        prepare_deployment(source, provision_runtime_role=not preprovisioned_runtime)
    except Exception:
        raise click.ClickException("Deployment preparation failed; check database access") from None
    console.print("Database deployment prepared; existing workspace data preserved.")


@main.group()
def serve() -> None:
    """Run long-lived RULER service entrypoints."""


@serve.command("mcp")
@click.option("--transport", type=click.Choice(["stdio", "streamable-http"]), default="stdio")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", envvar="PORT", default=8080, type=click.IntRange(1024, 65535))
def serve_mcp_command(transport: Literal["stdio", "streamable-http"], host: str, port: int) -> None:
    from ruler.runtime.mcp_server import main as mcp_main

    mcp_main(transport=transport, host=host, port=port)


@serve.command("kb-workspace")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8766, show_default=True, type=click.IntRange(1024, 65535))
def serve_kb_workspace_command(host: str, port: int) -> None:
    """Serve the authenticated visual KB workspace on a loopback address."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise click.ClickException("KB workspace currently permits loopback binding only")
    import uvicorn

    from ruler.interfaces.kb_workspace import create_kb_workspace_app

    token = secrets.token_urlsafe(32)
    console.print(f"[green]KB workspace[/green] http://{host}:{port}/?token={token}")
    uvicorn.run(create_kb_workspace_app(token=token), host=host, port=port)


@main.group("cbr")
def cbr_group() -> None:
    """Retrieve, compare, adapt, and verify governed precedent cases."""


@cbr_group.command("libraries")
def cbr_libraries_command() -> None:
    from ruler.interfaces.cbr_cases import cbr_portfolio

    console.print_json(data=cbr_portfolio())


@cbr_group.command("show-case")
@click.argument("domain_id")
@click.argument("case_id")
def cbr_show_case_command(domain_id: str, case_id: str) -> None:
    from ruler.interfaces.cbr_cases import show_cbr_case

    try:
        console.print_json(data=show_cbr_case(domain_id, case_id))
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc


@cbr_group.command("retrieve")
@click.argument("domain_id")
@click.option("--query-file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--top-k", type=click.IntRange(1, 10), default=3, show_default=True)
def cbr_retrieve_command(domain_id: str, query_file: Path | None, top_k: int) -> None:
    from pydantic import ValidationError
    from ruler.cbr.contracts import CBRCaseRecord
    from ruler.interfaces.cbr_cases import retrieve_cbr_cases

    try:
        query = None
        if query_file is not None:
            if query_file.stat().st_size > 1_000_000:
                raise click.ClickException("query file exceeds the 1 MB limit")
            query = CBRCaseRecord.model_validate_json(query_file.read_text(encoding="utf-8"))
        console.print_json(data=retrieve_cbr_cases(domain_id, query=query, top_k=top_k))
    except (LookupError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc


@cbr_group.command("compare")
@click.argument("domain_id")
@click.argument("left_case_id")
@click.argument("right_case_id")
def cbr_compare_command(domain_id: str, left_case_id: str, right_case_id: str) -> None:
    from ruler.interfaces.cbr_cases import compare_cbr_cases

    try:
        console.print_json(data=compare_cbr_cases(domain_id, left_case_id, right_case_id))
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc


@cbr_group.command("adapt")
@click.argument("domain_id")
@click.argument("source_case_id")
def cbr_adapt_command(domain_id: str, source_case_id: str) -> None:
    from ruler.interfaces.cbr_cases import suggest_cbr_adaptation

    try:
        console.print_json(data=suggest_cbr_adaptation(domain_id, source_case_id))
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc


@cbr_group.command("verify")
@click.argument("domain_id")
def cbr_verify_command(domain_id: str) -> None:
    from ruler.interfaces.cbr_cases import verify_cbr_demo

    try:
        console.print_json(data=verify_cbr_demo(domain_id))
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc


@cbr_group.command("retain")
@click.argument("outcome_file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--apply", "apply_change", is_flag=True, help="Persist an independently reviewed outcome."
)
def cbr_retain_command(outcome_file: Path, apply_change: bool) -> None:
    """Validate an outcome in dry-run mode unless --apply is explicit."""
    from pydantic import ValidationError
    from ruler.cbr.contracts import OutcomeObservation
    from ruler.interfaces.cbr_cases import retain_cbr_outcome

    try:
        if outcome_file.stat().st_size > 1_000_000:
            raise click.ClickException("outcome file exceeds the 1 MB limit")
        outcome = OutcomeObservation.model_validate_json(outcome_file.read_text(encoding="utf-8"))
        if not apply_change:
            console.print_json(data={"status": "dry_run", "outcome_id": outcome.outcome_id})
            return
        digest = retain_cbr_outcome(outcome, root=BUILD_DIR / "cbr" / "outcomes")
        console.print_json(
            data={"status": "retained", "outcome_id": outcome.outcome_id, "sha256": digest}
        )
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.group("domains")
def domains_group() -> None:
    """Inspect installed rigorous-document domain packs."""


def _domain_registry():
    """Build the fail-closed built-in domain registry without global mutation."""
    from ruler.domains.fiscal import FISCAL_DOMAIN_PACK
    from ruler.domains.legal import LEGAL_DOMAIN_PACK
    from ruler.domains.regulatory import REGULATORY_DOMAIN_PACK
    from ruler.domains.registry import DomainPackRegistry
    from ruler.domains.spending import SPENDING_DOMAIN_PACK
    from ruler.domains.technical_support import TECHNICAL_SUPPORT_DOMAIN_PACK
    from ruler.domains.trade import TRADE_DOMAIN_PACK
    from ruler.domains.construction_fleet import CONSTRUCTION_FLEET_DOMAIN_PACK

    registry = DomainPackRegistry()
    registry.register(CONSTRUCTION_FLEET_DOMAIN_PACK)
    registry.register(FISCAL_DOMAIN_PACK)
    registry.register(LEGAL_DOMAIN_PACK)
    registry.register(REGULATORY_DOMAIN_PACK)
    registry.register(SPENDING_DOMAIN_PACK)
    registry.register(TECHNICAL_SUPPORT_DOMAIN_PACK)
    registry.register(TRADE_DOMAIN_PACK)
    return registry


@main.group("portfolio")
def portfolio_group() -> None:
    """Execute typed resource-portfolio evidence, solver, and explanation stages."""


def _portfolio_payload(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise click.ClickException(str(exc)) from exc


def _portfolio_write(output_dir: Path, name: str, payload: object) -> Path:
    destination = output_dir / name
    write_yaml(destination, payload)
    return destination


@portfolio_group.command("build-snapshot")
@click.argument("input_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_build_snapshot_command(input_path: Path, output_dir: Path) -> None:
    """Normalize typed observations and freeze a digest-closed planning snapshot."""
    from pydantic import ValidationError
    from ruler.applications.resource_portfolio.workflow import build_evidence_snapshot

    try:
        payload = _portfolio_payload(input_path)
        if not isinstance(payload, dict):
            raise ValueError("snapshot input must be a mapping")
        normalized, states, profiles, snapshot = build_evidence_snapshot(payload)
        _portfolio_write(output_dir, "normalized_events.yaml", normalized.model_dump(mode="json"))
        _portfolio_write(output_dir, "state_intervals.yaml", states.model_dump(mode="json"))
        _portfolio_write(
            output_dir, "profiles.yaml", [item.model_dump(mode="json") for item in profiles]
        )
        destination = _portfolio_write(
            output_dir, "snapshot.yaml", snapshot.model_dump(mode="json")
        )
    except (KeyError, OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "snapshot_id": snapshot.snapshot_id,
            "digest": snapshot.content_sha256,
            "output": str(destination),
        }
    )


@portfolio_group.command("generate-rule-candidates")
@click.argument("source_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--artifact-id", required=True)
@click.option("--source-version", required=True)
@click.option("--context-id", required=True)
@click.option("--domain-id", default="construction_fleet", show_default=True)
@click.option("--allowed-predicate", "allowed_predicates", multiple=True, required=True)
@click.option("--request-id", required=True)
@click.option("--target-formalism", type=click.Choice(["asp", "prolog"]), default="asp")
@click.option("--model", default="gpt-5.4", show_default=True)
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_generate_rule_candidates_command(
    source_path: Path,
    artifact_id: str,
    source_version: str,
    context_id: str,
    domain_id: str,
    allowed_predicates: tuple[str, ...],
    request_id: str,
    target_formalism: str,
    model: str,
    output_dir: Path,
) -> None:
    """Invoke the real bounded provider and emit inactive rule candidates."""
    import hashlib
    from pydantic import ValidationError
    from ruler.kb.generative_autoformalization import (
        AutoformalizationRequest,
        CodexExecTransport,
        GenerativeTransportError,
        generate_autoformalization_candidate,
        predicate_registry_from_domain_pack,
    )

    try:
        source_text = source_path.read_text(encoding="utf-8")
        pack = _domain_registry().get(domain_id)
        request = AutoformalizationRequest.model_validate(
            dict(
                request_id=request_id,
                artifact_id=artifact_id,
                artifact_sha256="sha256:" + hashlib.sha256(source_text.encode()).hexdigest(),
                source_text=source_text,
                source_version=source_version,
                context_id=context_id,
                domain_id=domain_id,
                allowed_predicates=allowed_predicates,
                predicate_registry=predicate_registry_from_domain_pack(pack, allowed_predicates),
                target_formalism=target_formalism,
            )
        )
        candidate = generate_autoformalization_candidate(request, CodexExecTransport(model=model))
        destination = _portfolio_write(
            output_dir, "rule_candidates.yaml", candidate.model_dump(mode="json")
        )
    except (OSError, ValueError, ValidationError, GenerativeTransportError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "lifecycle": candidate.lifecycle,
            "activation_status": candidate.projection.activation_status,
            "output": str(destination),
        }
    )


@portfolio_group.command("generate-synthetic")
@click.argument("config_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--seed", required=True, type=int, help="Deterministic generation seed.")
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
@click.option(
    "--generate-only",
    is_flag=True,
    help="Validate and write inputs without executing the workflow.",
)
def portfolio_generate_synthetic_command(
    config_path: Path, seed: int, output_dir: Path, generate_only: bool
) -> None:
    """Generate a synthetic case and, by default, execute all real backends."""
    from pydantic import ValidationError
    from ruler.applications.resource_portfolio.compiler import CompilationRequest, compile_rules
    from ruler.applications.resource_portfolio.synthetic import (
        load_synthetic_config,
        verify_synthetic_portfolio_inputs,
        write_synthetic_portfolio_inputs,
    )
    from ruler.applications.resource_portfolio.workflow import execute_resource_portfolio_workflow
    from ruler.io import stable_hash

    try:
        config = load_synthetic_config(config_path).model_copy(update={"seed": seed})
        manifest = write_synthetic_portfolio_inputs(config, output_dir)
        verify_synthetic_portfolio_inputs(output_dir)
        outcome: dict[str, object] = {
            "schema_version": "resource-portfolio-synthetic-test/v1",
            "dataset_id": manifest.dataset_id,
            "seed": seed,
            "input_manifest_digest": manifest.content_sha256,
            "model_variant": manifest.model_variant,
            "synthetic": True,
            "advisory_only": True,
        }
        if not generate_only and manifest.expected_compilation_status == "sat":
            run = execute_resource_portfolio_workflow(output_dir, output_dir / "workflow_run")
            outcome.update(status="passed", workflow_run_digest=run.run_digest)
        elif not generate_only:
            request = CompilationRequest.model_validate(
                _portfolio_payload(output_dir / "compile.yaml")
            )
            try:
                compile_rules(request)
            except ValueError as exc:
                if "unsatisfiable" not in str(exc):
                    raise
                infeasibility = {
                    "schema_version": "resource-portfolio-infeasibility-receipt/v1",
                    "backend_id": "z3",
                    "status": "unsat",
                    "expected": True,
                    "problem_id": request.problem_id,
                    "request_digest": stable_hash(request.model_dump(mode="json")),
                    "input_manifest_digest": manifest.content_sha256,
                    "diagnostic": str(exc),
                }
                infeasibility["content_sha256"] = stable_hash(infeasibility)
                _portfolio_write(output_dir, "infeasibility.yaml", infeasibility)
                outcome.update(
                    status="expected_infeasible",
                    diagnostic=str(exc),
                    infeasibility_receipt_digest=infeasibility["content_sha256"],
                )
            else:
                raise ValueError("synthetic infeasible case unexpectedly compiled as satisfiable")
        else:
            outcome.update(status="generated")
        outcome["content_sha256"] = stable_hash(outcome)
        destination = _portfolio_write(output_dir, "synthetic_test.yaml", outcome)
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "status": outcome["status"],
            "manifest": manifest.content_sha256,
            "output": str(destination),
        }
    )


@portfolio_group.command("compile")
@click.argument("request_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_compile_command(request_path: Path, output_dir: Path) -> None:
    """Compile approved linear rules and prove hard feasibility with Z3."""
    from pydantic import ValidationError
    from ruler.applications.resource_portfolio.compiler import CompilationRequest, compile_rules

    try:
        report = compile_rules(CompilationRequest.model_validate(_portfolio_payload(request_path)))
        destination = _portfolio_write(
            output_dir, "compilation.yaml", report.model_dump(mode="json")
        )
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "status": report.z3_status,
            "output": str(destination),
            "model_digest": report.problem.digest,
        }
    )


@portfolio_group.command("optimize")
@click.argument("model_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--backend", type=click.Choice(["highs"]), default="highs", show_default=True)
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_optimize_command(model_path: Path, backend: str, output_dir: Path) -> None:
    """Solve a bounded linear portfolio model with Pyomo and HiGHS."""
    from pydantic import ValidationError
    from ruler.applications.resource_portfolio.optimization import optimize_portfolio
    from ruler.optimization import OptimizationProblem

    try:
        problem = OptimizationProblem.model_validate(_portfolio_payload(model_path))
        plan = optimize_portfolio(problem)
        destination = _portfolio_write(
            output_dir, "verified_plan.yaml", plan.model_dump(mode="json")
        )
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "status": str(plan.result.status),
            "verified": plan.verification.verified,
            "backend": backend,
            "output": str(destination),
        }
    )


@portfolio_group.command("verify-plan")
@click.argument("model_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.argument("result_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_verify_plan_command(model_path: Path, result_path: Path, output_dir: Path) -> None:
    """Independently evaluate a solver result against the typed model."""
    from pydantic import ValidationError
    from ruler.optimization import OptimizationProblem, OptimizationResult
    from ruler.optimization.verification import verify_result

    try:
        problem = OptimizationProblem.model_validate(_portfolio_payload(model_path))
        payload = _portfolio_payload(result_path)
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        report = verify_result(problem, OptimizationResult.model_validate(payload))
        destination = _portfolio_write(
            output_dir, "verification.yaml", report.model_dump(mode="json")
        )
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data={"verified": report.verified, "output": str(destination)})


@portfolio_group.command("schedule")
@click.argument("problem_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_schedule_command(problem_path: Path, output_dir: Path) -> None:
    """Solve an exact-integer interval schedule with OR-Tools CP-SAT."""
    from pydantic import ValidationError
    from ruler.applications.resource_portfolio.scheduling import SchedulingProblem, solve_schedule

    try:
        result = solve_schedule(SchedulingProblem.model_validate(_portfolio_payload(problem_path)))
        destination = _portfolio_write(output_dir, "schedule.yaml", result.model_dump(mode="json"))
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data={"status": result.status, "output": str(destination)})


@portfolio_group.command("stress")
@click.argument("request_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_stress_command(request_path: Path, output_dir: Path) -> None:
    """Execute typed counterfactual changes through a fresh HiGHS solve."""
    from pydantic import ValidationError
    from ruler.applications.resource_portfolio.robustness import (
        CounterfactualChange,
        run_counterfactual,
    )
    from ruler.optimization import OptimizationProblem

    try:
        payload = _portfolio_payload(request_path)
        if not isinstance(payload, dict):
            raise ValueError("stress request must be a mapping")
        problem = OptimizationProblem.model_validate(payload["problem"])
        changes = tuple(CounterfactualChange.model_validate(item) for item in payload["changes"])
        run = run_counterfactual(
            problem, changes, run_id=str(payload["run_id"]), seed=int(payload.get("seed", 0))
        )
        destination = _portfolio_write(output_dir, "stress.yaml", run.model_dump(mode="json"))
    except (KeyError, OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "status": str(run.result.status),
            "output": str(destination),
            "variant_model_digest": run.variant_model_digest,
        }
    )


@portfolio_group.command("explain")
@click.argument("evidence_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--generative-draft", is_flag=True, help="Use the configured bounded Codex provider.")
@click.option("--model", default="gpt-5.4", show_default=True)
@click.option(
    "--output", "output_dir", required=True, type=click.Path(path_type=Path, file_okay=False)
)
def portfolio_explain_command(
    evidence_path: Path, generative_draft: bool, model: str, output_dir: Path
) -> None:
    """Render trace-closed prose deterministically or through an explicit model call."""
    from pydantic import ValidationError
    from ruler.applications.resource_portfolio.explanations import (
        PortfolioExplanationEvidence,
        build_deterministic_explanation,
        generate_explanation,
    )
    from ruler.kb.generative_autoformalization import CodexExecTransport, GenerativeTransportError

    try:
        evidence = PortfolioExplanationEvidence.model_validate(_portfolio_payload(evidence_path))
        explanation = (
            generate_explanation(evidence, CodexExecTransport(model=model))
            if generative_draft
            else build_deterministic_explanation(evidence)
        )
        destination = _portfolio_write(
            output_dir, "explanation.yaml", explanation.model_dump(mode="json")
        )
    except (OSError, ValueError, ValidationError, GenerativeTransportError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "mode": explanation.receipt.mode,
            "candidate_only": explanation.candidate_only,
            "output": str(destination),
        }
    )


@domains_group.command("list")
def domains_list_command() -> None:
    """List validated built-in domain packs."""
    registry = _domain_registry()
    for domain_id in registry.registered_ids():
        pack = registry.get(domain_id)
        console.print(
            f"[green]{domain_id}[/green] schema={pack.schema_version} "
            f"documents={','.join(sorted(pack.document_kinds))}"
        )


@domains_group.command("inspect")
@click.argument("domain_id")
def domains_inspect_command(domain_id: str) -> None:
    """Print a redaction-safe domain capability summary."""
    try:
        pack = _domain_registry().get(domain_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "domain_id": pack.domain_id,
            "schema_version": pack.schema_version,
            "document_kinds": sorted(pack.document_kinds),
            "unit_types": list(pack.taxonomy.unit_types),
            "materiality_roles": list(pack.taxonomy.materiality_roles),
            "predicates": sorted(pack.predicates),
            "translation_contracts": [
                item.model_dump(mode="json") for item in pack.translation_contracts
            ],
        }
    )


@main.group("legal")
def legal_group() -> None:
    """Validate source-bound candidate legal reasoning artifacts."""


@main.group("semantic")
def semantic_group() -> None:
    """Validate source-bound semantic bases and projections."""


@main.group("autoformalize")
def autoformalize_group() -> None:
    """Generate source-locked, uncommitted formalization candidates."""


@autoformalize_group.command("generate")
@click.argument("source_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--artifact-id", required=True, help="Stable identifier for the source artifact.")
@click.option("--source-version", required=True, help="Pinned source revision identifier.")
@click.option("--context-id", required=True, help="Semantic context identifier.")
@click.option("--domain-id", required=True, help="Bound domain vocabulary identifier.")
@click.option(
    "--allowed-predicate",
    "allowed_predicates",
    multiple=True,
    required=True,
    help="Predicate name permitted in candidate IR; repeat for the closed vocabulary.",
)
@click.option("--request-id", required=True, help="Unique generation request identifier.")
@click.option("--target-formalism", type=click.Choice(["asp", "prolog"]), default="asp")
@click.option("--model", default="gpt-5.4", show_default=True)
@click.option("--output", "output_path", required=True, type=click.Path(path_type=Path))
def autoformalize_generate_command(
    source_path: Path,
    artifact_id: str,
    source_version: str,
    context_id: str,
    domain_id: str,
    allowed_predicates: tuple[str, ...],
    request_id: str,
    target_formalism: str,
    model: str,
    output_path: Path,
) -> None:
    """Invoke Codex explicitly and write a blocked candidate, never active rules."""
    import hashlib

    from pydantic import ValidationError

    from ruler.kb.generative_autoformalization import (
        AutoformalizationRequest,
        CodexExecTransport,
        GenerativeTransportError,
        generate_autoformalization_candidate,
        predicate_registry_from_domain_pack,
    )

    try:
        source_text = source_path.read_text(encoding="utf-8")
        pack = _domain_registry().get(domain_id)
        predicate_registry = predicate_registry_from_domain_pack(pack, allowed_predicates)
        request = AutoformalizationRequest.model_validate(
            dict(
                request_id=request_id,
                artifact_id=artifact_id,
                artifact_sha256="sha256:" + hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                source_text=source_text,
                source_version=source_version,
                context_id=context_id,
                domain_id=domain_id,
                allowed_predicates=allowed_predicates,
                predicate_registry=predicate_registry,
                target_formalism=target_formalism,
            )
        )
        candidate = generate_autoformalization_candidate(request, CodexExecTransport(model=model))
        write_yaml(output_path, candidate.model_dump(mode="json"))
    except (OSError, ValueError, ValidationError, GenerativeTransportError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "request_id": candidate.request_id,
            "lifecycle": candidate.lifecycle,
            "activation_status": candidate.projection.activation_status,
            "output": str(output_path),
        }
    )


@semantic_group.command("validate")
@click.argument("basis_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--artifact",
    "artifact_bindings",
    multiple=True,
    metavar="ID=PATH",
    help="Bind a semantic source artifact ID to exact local bytes; repeat as needed.",
)
def semantic_validate_command(basis_path: Path, artifact_bindings: tuple[str, ...]) -> None:
    """Validate a semantic basis and authenticate all of its source spans."""
    from pydantic import ValidationError

    from ruler.contracts.semantics import SemanticBasis

    try:
        basis = SemanticBasis.model_validate(yaml.safe_load(basis_path.read_text(encoding="utf-8")))
        artifacts: dict[str, bytes] = {}
        for binding in artifact_bindings:
            artifact_id, separator, raw_path = binding.partition("=")
            if not separator or not artifact_id or not raw_path:
                raise ValueError("--artifact must use ID=PATH")
            artifacts[artifact_id] = Path(raw_path).read_bytes()
        basis.verify_source_artifacts(artifacts)
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "basis_id": basis.basis_id,
            "source_bound": True,
            "spans": len(basis.spans),
            "elements": len(basis.elements),
            "commitment_status": basis.commitment_status,
        }
    )


@main.group("arguments")
def arguments_group() -> None:
    """Evaluate finite source-bound structured argument frameworks."""


@main.group("formal-flow")
def formal_flow_group() -> None:
    """Validate digest-closed formal reasoning stage graphs."""


@formal_flow_group.command("validate")
@click.argument("flow_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
def formal_flow_validate_command(flow_path: Path) -> None:
    """Validate ordered handoffs and independent review/release authority."""
    from pydantic import ValidationError

    from ruler.assurance.formal_flow import FormalFlowRun

    try:
        flow = FormalFlowRun.model_validate(yaml.safe_load(flow_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "run_id": flow.run_id,
            "stage_count": len(flow.stages),
            "handoff_count": len(flow.handoffs),
            "release_authorized": flow.release_authorized,
            "status": "valid",
        }
    )


@arguments_group.command("evaluate")
@click.argument("framework_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--target", required=True, help="Exact target conclusion identifier.")
@click.option("--max-arguments", type=click.IntRange(1, 24), default=18, show_default=True)
def arguments_evaluate_command(framework_path: Path, target: str, max_arguments: int) -> None:
    """Evaluate grounded/preferred/stable semantics and cross-check with Clingo."""
    from pydantic import ValidationError

    from ruler.assurance.argumentation import ArgumentFramework, evaluate_argument_framework

    try:
        framework = ArgumentFramework.model_validate(
            yaml.safe_load(framework_path.read_text(encoding="utf-8"))
        )
        result = evaluate_argument_framework(framework, target, max_arguments=max_arguments)
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=result.model_dump(mode="json"))


@legal_group.command("validate-packet")
@click.argument("packet_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
    help="Authenticate packet spans against this corpus manifest and repository bytes.",
)
@click.option(
    "--repo-root",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path.cwd,
    show_default="current directory",
)
def legal_validate_packet_command(
    packet_path: Path, manifest_path: Path | None, repo_root: Path
) -> None:
    """Validate reference closure and report evidence-only assurance."""
    from pydantic import ValidationError

    from ruler.domains.legal import (
        LegalReasoningPacket,
        assess_legal_packet,
        verify_legal_packet_evidence,
    )
    from ruler.kb.corpus_manifest import CorpusManifest

    try:
        payload = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
        packet = LegalReasoningPacket.model_validate(payload)
        evidence = None
        if manifest_path is not None:
            manifest = CorpusManifest.model_validate(
                yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            )
            evidence = verify_legal_packet_evidence(packet, manifest, repo_root=repo_root)
        report = assess_legal_packet(packet, evidence)
    except (OSError, ValueError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    result = {"assurance": report.model_dump(mode="json")}
    if evidence is not None:
        result["evidence_verification"] = evidence.model_dump(mode="json")
    console.print_json(data=result)


@main.group("kb")
def kb_group() -> None:
    """Manage, search, inspect, and query named formal knowledge bases."""


@kb_group.command("list")
def kb_list_command() -> None:
    """List adapted and locally managed knowledge bases."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog

    for kb in KnowledgeBaseCatalog().list():
        console.print(
            f"[green]{kb.kb_id}[/green] name={kb.name!r} domain={kb.domain_id} "
            f"revision={kb.current_version_id} artifacts={len(kb.current_version.artifacts)} "
            f"formalisms={','.join(sorted(item.value for item in kb.formalisms)) or 'none'} "
            f"access={kb.access_mode}"
        )


@kb_group.command("show")
@click.argument("kb_id")
def kb_show_command(kb_id: str) -> None:
    """Inspect one KB without exposing filesystem locations."""
    from ruler.interfaces.kb_workspace import _public_kb
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog

    try:
        payload = _public_kb(KnowledgeBaseCatalog().get(kb_id), detail=True)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=payload)


@kb_group.command("search")
@click.argument("query")
@click.option("--kb", "kb_id", default=None, help="Restrict search to one KB ID.")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, 200))
def kb_search_command(query: str, kb_id: str | None, limit: int) -> None:
    """Search KB names, artifact metadata, rules, facts, and source text."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog

    try:
        hits = KnowledgeBaseCatalog().search(query, kb_id=kb_id, limit=limit)
    except (LookupError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={"query": query, "hits": [item.model_dump(mode="json") for item in hits]}
    )


@kb_group.command("rename")
@click.argument("kb_id")
@click.argument("name")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Apply the metadata change; otherwise show a dry-run plan.",
)
def kb_rename_command(kb_id: str, name: str, apply_changes: bool) -> None:
    """Rename a managed KB without changing its immutable identity or revision digest."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog

    catalog = KnowledgeBaseCatalog()
    try:
        current = catalog.get(kb_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if not apply_changes:
        console.print_json(
            data={
                "status": "dry_run",
                "operation": "rename",
                "kb_id": kb_id,
                "from": current.name,
                "to": name,
            }
        )
        return
    try:
        updated = catalog.update_metadata(kb_id, name=name)
    except (OSError, PermissionError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "status": "renamed",
            "kb_id": kb_id,
            "name": updated.name,
            "version_id": updated.current_version_id,
            "version_sha256": updated.current_version.content_sha256,
        }
    )


@kb_group.command("capabilities")
@click.argument("kb_id")
def kb_capabilities_command(kb_id: str) -> None:
    """List truthful artifact/backend operation routes for one KB."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_inference import KBInferenceService

    try:
        rows = KBInferenceService(KnowledgeBaseCatalog()).capabilities(kb_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data={"kb_id": kb_id, "capabilities": rows})


@kb_group.command("create")
@click.option("--id", "kb_id", required=True)
@click.option("--name", required=True)
@click.option("--description", required=True)
@click.option("--domain", "domain_id", required=True)
@click.option("--purpose", "purposes", multiple=True, required=True)
@click.option("--tag", "tags", multiple=True)
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Create the local KB; otherwise show a dry-run plan.",
)
def kb_create_command(
    kb_id: str,
    name: str,
    description: str,
    domain_id: str,
    purposes: tuple[str, ...],
    tags: tuple[str, ...],
    apply_changes: bool,
) -> None:
    """Create an empty managed KB with an immutable first revision."""
    from pydantic import ValidationError

    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_contracts import CreateKnowledgeBaseRequest

    try:
        request = CreateKnowledgeBaseRequest.model_validate(
            dict(
                kb_id=kb_id,
                name=name,
                description=description,
                domain_id=domain_id,
                purposes=frozenset(purposes),
                tags=frozenset(tags),
            )
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    if not apply_changes:
        console.print_json(
            data={
                "status": "dry_run",
                "operation": "create",
                "request": request.model_dump(mode="json"),
            }
        )
        return
    try:
        kb = KnowledgeBaseCatalog().create(request)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={"status": "created", "kb_id": kb.kb_id, "version_id": kb.current_version_id}
    )


@kb_group.command("add-artifact")
@click.argument("kb_id")
@click.option("--id", "artifact_id", required=True)
@click.option("--name", required=True)
@click.option("--role", required=True)
@click.option("--formalism", required=True)
@click.option("--media-type", required=True)
@click.option(
    "--file",
    "source_file",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option("--language", default="und", show_default=True)
@click.option("--reference", "references", multiple=True)
@click.option("--summary", "change_summary", required=True)
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Publish a new local revision; otherwise show a dry-run plan.",
)
def kb_add_artifact_command(
    kb_id: str,
    artifact_id: str,
    name: str,
    role: str,
    formalism: str,
    media_type: str,
    source_file: Path,
    language: str,
    references: tuple[str, ...],
    change_summary: str,
    apply_changes: bool,
) -> None:
    """Copy one text artifact into a new immutable managed-KB revision."""
    from pydantic import ValidationError

    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_contracts import AddKBArtifactRequest

    try:
        content = source_file.read_text(encoding="utf-8")
        request = AddKBArtifactRequest.model_validate(
            dict(
                artifact_id=artifact_id,
                name=name,
                role=role,
                formalism=formalism,
                media_type=media_type,
                filename=source_file.name,
                content=content,
                language=language,
                references=references,
                change_summary=change_summary,
            )
        )
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not apply_changes:
        console.print_json(
            data={
                "status": "dry_run",
                "operation": "add_artifact",
                "kb_id": kb_id,
                "artifact": request.model_dump(mode="json", exclude={"content"}),
                "content_bytes": len(content.encode()),
            }
        )
        return
    try:
        kb = KnowledgeBaseCatalog().add_artifact(kb_id, request)
    except (LookupError, OSError, PermissionError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={"status": "created_revision", "kb_id": kb.kb_id, "version_id": kb.current_version_id}
    )


@kb_group.command("infer")
@click.argument("kb_id")
@click.option("--operation", default="query", show_default=True)
@click.option("--artifact", "artifact_id", default=None)
@click.option("--query", "query_atom", default=None)
@click.option("--contrary", default=None)
@click.option("--fact", "facts", multiple=True)
@click.option("--backend", "backend_id", default=None)
@click.option("--max-models", default=100, show_default=True, type=click.IntRange(1, 1000))
def kb_infer_command(
    kb_id: str,
    operation: str,
    artifact_id: str | None,
    query_atom: str | None,
    contrary: str | None,
    facts: tuple[str, ...],
    backend_id: str | None,
    max_models: int,
) -> None:
    """Run a capability-routed inference against the active immutable revision."""
    from pydantic import ValidationError

    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_contracts import KBInferenceRequest
    from ruler.kb.workspace_inference import KBInferenceService

    try:
        request = KBInferenceRequest.model_validate(
            dict(
                request_id=f"cli-{secrets.token_hex(8)}",
                operation=operation,
                artifact_id=artifact_id,
                query=query_atom,
                contrary=contrary,
                asserted_facts=facts,
                backend_id=backend_id,
                max_models=max_models,
            )
        )
        result = KBInferenceService(KnowledgeBaseCatalog()).execute(kb_id, request)
    except (LookupError, ValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=result.model_dump(mode="json"))
    if result.status in {"error", "blocked", "unsupported"}:
        raise click.exceptions.Exit(2)


@kb_group.command("releases")
@click.argument("kb_id")
def kb_releases_command(kb_id: str) -> None:
    """List immutable release envelopes and their reliance boundaries."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_governance import execution_boundary

    try:
        releases = KnowledgeBaseCatalog().releases(kb_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "kb_id": kb_id,
            "releases": [
                {
                    **item.model_dump(mode="json"),
                    "execution_boundary": execution_boundary(item).model_dump(mode="json"),
                }
                for item in releases
            ],
        }
    )


@kb_group.command("release-transition")
@click.argument("kb_id")
@click.argument("target", type=click.Choice(["candidate", "reviewed", "published", "retired"]))
@click.option(
    "--evidence",
    "evidence_path",
    required=True,
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option("--apply", "apply_changes", is_flag=True)
def kb_release_transition_command(
    kb_id: str, target: str, evidence_path: Path, apply_changes: bool
) -> None:
    """Advance one managed release using digest-bound validation/review evidence."""
    from pydantic import TypeAdapter, ValidationError

    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_governance import ReleaseEvidence, ReleaseStage

    try:
        raw = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
        evidence = TypeAdapter(tuple[ReleaseEvidence, ...]).validate_python(raw)
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not apply_changes:
        console.print_json(
            data={
                "status": "dry_run",
                "kb_id": kb_id,
                "target": target,
                "evidence_count": len(evidence),
            }
        )
        return
    try:
        release = KnowledgeBaseCatalog().transition_release(kb_id, ReleaseStage(target), evidence)
    except (LookupError, PermissionError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=release.model_dump(mode="json"))


@kb_group.command("compare")
@click.argument("left_kb_id")
@click.argument("right_kb_id")
@click.option("--left-version", default=None)
@click.option("--right-version", default=None)
def kb_compare_command(
    left_kb_id: str, right_kb_id: str, left_version: str | None, right_version: str | None
) -> None:
    """Compare two pinned KB releases structurally and semantically."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_experience import compare_releases

    try:
        result = compare_releases(
            KnowledgeBaseCatalog(),
            left_kb_id,
            right_kb_id,
            left_version_id=left_version,
            right_version_id=right_version,
        )
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=result)


@kb_group.command("query-editor")
@click.argument("kb_id")
@click.option("--version", "version_id", default=None)
def kb_query_editor_command(kb_id: str, version_id: str | None) -> None:
    """Show typed query templates and declared predicate signatures."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_experience import query_editor_model

    try:
        result = query_editor_model(KnowledgeBaseCatalog(), kb_id, version_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=result)


@kb_group.command("package-inspect")
@click.argument("package", type=click.Path(path_type=Path, exists=True, dir_okay=False))
def kb_package_inspect_command(package: Path) -> None:
    """Dry-run a portable KB package without writing it."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_packages import inspect_package

    manifest, plan = inspect_package(
        package, existing_kb_ids=[item.kb_id for item in KnowledgeBaseCatalog().list()]
    )
    console.print_json(
        data={
            "manifest": manifest.model_dump(mode="json") if manifest else None,
            "plan": plan.model_dump(mode="json"),
        }
    )


@kb_group.command("package-export")
@click.argument("kb_id")
@click.argument("destination", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--apply", "apply_changes", is_flag=True)
def kb_package_export_command(kb_id: str, destination: Path, apply_changes: bool) -> None:
    """Export a deterministic digest-preserving KB package."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_packages import export_package

    catalog = KnowledgeBaseCatalog()
    try:
        kb = catalog.get(kb_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if not apply_changes:
        console.print_json(
            data={
                "status": "dry_run",
                "kb_id": kb_id,
                "destination": str(destination),
                "objects": len(kb.current_version.artifacts),
            }
        )
        return
    try:
        manifest = export_package(
            kb, destination, read_artifact=lambda item: catalog.artifact_path(item).read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=manifest.model_dump(mode="json"))


@kb_group.command("package-import")
@click.argument("package", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--apply", "apply_changes", is_flag=True)
def kb_package_import_command(package: Path, apply_changes: bool) -> None:
    """Validate and stage a portable package without overwriting catalogue data."""
    from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
    from ruler.kb.workspace_packages import import_package, inspect_package

    catalog = KnowledgeBaseCatalog()
    existing = [item.kb_id for item in catalog.list()]
    manifest, plan = inspect_package(package, existing_kb_ids=existing)
    if not apply_changes:
        console.print_json(
            data={
                "status": "dry_run",
                "manifest": manifest.model_dump(mode="json") if manifest else None,
                "plan": plan.model_dump(mode="json"),
            }
        )
        return
    try:
        imported, applied_plan = import_package(
            package, catalog.managed_root / ".imports", existing_kb_ids=existing
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(
        data={
            "status": "staged",
            "kb_id": imported.kb.kb_id,
            "plan": applied_plan.model_dump(mode="json"),
            "note": "Package is staged for governed review; catalogue publication is a separate release action.",
        }
    )


@main.group("corpora")
def corpora_group() -> None:
    """Inspect and validate declarative corpus manifests."""


@corpora_group.command("list")
def corpora_list_command() -> None:
    from ruler.kb.corpus_manifest import discover_corpus_manifests, load_corpus_manifest

    paths = discover_corpus_manifests()
    if not paths:
        console.print("[yellow]no v2 corpus manifests discovered[/yellow]")
        return
    for path in paths:
        manifest = load_corpus_manifest(path)
        console.print(
            f"[green]{manifest.corpus_id}[/green] domain={manifest.domain_id} "
            f"artifacts={len(manifest.artifacts)} path={path}"
        )


@corpora_group.command("validate")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=False),
    default=None,
    help="Validate one manifest; omitted validates every discovered v2 corpus.",
)
def corpora_validate_command(manifest_path: Path | None) -> None:
    from ruler.kb.corpus_manifest import (
        discover_corpus_manifests,
        load_corpus_manifest,
        validate_corpus_manifests,
    )

    paths = (manifest_path,) if manifest_path else discover_corpus_manifests()
    if not paths:
        raise click.ClickException("no v2 corpus manifests discovered")
    try:
        messages = validate_corpus_manifests([load_corpus_manifest(path) for path in paths])
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[green]corpora ok[/green] " + ", ".join(messages))


@corpora_group.command("schema")
def corpora_schema_command() -> None:
    """Emit the machine-readable corpus manifest JSON Schema."""
    from ruler.kb.corpus_manifest import corpus_manifest_json_schema

    console.print_json(data=corpus_manifest_json_schema())


@main.group("evaluate")
def evaluate_group() -> None:
    """Evaluate release-pinned cases independently of recommendation/ranking."""


@evaluate_group.command("regulatory-proof")
@click.option(
    "--case",
    "case_id",
    required=True,
    help="Case identifier from data/regulatory/proof/evaluation_cases.yaml.",
)
def evaluate_regulatory_proof_command(case_id: str) -> None:
    """Run the domain-neutral proof corpus through the generic rule evaluator."""
    from ruler.domains.regulatory import (
        REGULATORY_RELEASE_ID,
        build_regulatory_program,
        regulatory_expected_rules,
        regulatory_registry,
    )
    from ruler.evaluation import EvaluationRequest, evaluate_request
    from ruler.io import read_yaml
    from ruler.kb.formalization import ValueType
    from ruler.kb.logical_ir import Atom, Constant
    from ruler.paths import REPO_ROOT

    cases = read_yaml(REPO_ROOT / "data" / "regulatory" / "proof" / "evaluation_cases.yaml")
    selected = next((item for item in cases if item["case_id"] == case_id), None)
    if selected is None:
        available = ", ".join(sorted(item["case_id"] for item in cases))
        raise click.ClickException(
            f"unknown regulatory proof case {case_id!r}; available: {available}"
        )
    facts = []
    for predicate, entries in selected.get("facts", {}).items():
        for entry in entries:
            values = entry if isinstance(entry, list) else [entry]
            arguments = []
            for index, value in enumerate(values):
                value_type = (
                    ValueType.COUNT if index > 0 and isinstance(value, int) else ValueType.SUBJECT
                )
                arguments.append(Constant(value_type=value_type, value=value))
            facts.append(Atom(predicate=predicate, arguments=tuple(arguments)))
    packet = evaluate_request(
        build_regulatory_program(),
        regulatory_registry(),
        EvaluationRequest(
            request_id=f"request:{case_id}",
            case_id=case_id,
            release_id=REGULATORY_RELEASE_ID,
            facts=tuple(facts),
            expected_rules=regulatory_expected_rules(),
        ),
    )
    console.print_json(data=packet.model_dump(mode="json"))


@main.group("migrate")
def migrate_group() -> None:
    """Plan or explicitly publish immutable v2 artifact migrations."""


@migrate_group.command("artifacts")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=False),
    required=True,
)
@click.option("--release-name", required=True)
@click.option("--rename", "renames", multiple=True, help="Field mapping OLD=NEW; repeatable.")
@click.option("--drop", "drops", multiple=True, help="Lossy field removal; repeatable.")
@click.option("--apply", "apply_changes", is_flag=True, help="Publish the reviewed plan.")
@click.option("--accept-ambiguities", is_flag=True)
@click.option("--accept-losses", is_flag=True)
def migrate_artifacts_command(
    manifest_path: Path,
    release_name: str,
    renames: tuple[str, ...],
    drops: tuple[str, ...],
    apply_changes: bool,
    accept_ambiguities: bool,
    accept_losses: bool,
) -> None:
    """Dry-run by default; apply writes only to a fresh immutable v2 namespace."""
    from ruler.kb.artifact_migration import (
        apply_artifact_migration,
        plan_artifact_migration,
    )

    mappings: dict[str, str] = {}
    for mapping in renames:
        if "=" not in mapping:
            raise click.UsageError("--rename values must use OLD=NEW")
        source, target = mapping.split("=", 1)
        if not source or not target:
            raise click.UsageError("--rename values require non-empty OLD and NEW fields")
        mappings[source] = target
    try:
        plan = plan_artifact_migration(
            manifest_path,
            release_name=release_name,
            rename_fields=mappings,
            drop_fields=drops,
        )
        result = (
            apply_artifact_migration(
                plan,
                accept_ambiguities=accept_ambiguities,
                accept_losses=accept_losses,
            )
            if apply_changes
            else plan
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=result.model_dump(mode="json"))


@main.group()
def sources() -> None:
    """Ingest source documents and product workbooks."""


@main.group("hook")
def hook_group() -> None:
    """Run configured workflow hooks."""


@hook_group.command("run")
@click.argument("hook_name")
def hook_run_command(hook_name: str) -> None:
    try:
        messages = run_hook(hook_name)
    except Exception as exc:
        console.print(f"[red]hook {hook_name} failed:[/red] {exc}")
        sys.exit(1)
    for message in messages:
        console.print(message)
    console.print(f"[green]hook {hook_name} ok[/green]")


def _write_workflow_graph_artifacts(output_dir: Path | None = None) -> dict[str, Path]:
    return write_workflow_graph_artifacts(output_dir=output_dir)


def _write_workflow_router_artifacts(output_dir: Path | None = None) -> dict[str, Path]:
    return write_workflow_router_artifacts(output_dir=output_dir)


def _write_inference_dashboard_artifacts(output_dir: Path | None = None) -> dict[str, Path]:
    return write_inference_control_dashboard_artifacts(output_dir=output_dir)


def _write_formalized_kb_artifacts() -> dict[str, Path]:
    return write_formalized_kb_artifacts()


if __name__ == "__main__":
    main()


@validate.command("progressive-onboarding")
def validate_progressive_onboarding_command() -> None:
    """Validate the progressive batch plan and append-only progress ledger."""
    _run_validation("progressive-onboarding", validate_progressive_onboarding)


@validate.command("batch-pipeline")
def validate_batch_pipeline_command() -> None:
    """Validate portable batch definitions, ordering, paths, and execution limits."""
    _run_validation("batch-pipeline", validate_batch_pipeline)


@sources.command("extract-documents")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=False),
    required=True,
    help="Bounded YAML manifest listing one to three exact public documents.",
)
@click.option(
    "--output-manifest",
    type=click.Path(path_type=Path, file_okay=True, dir_okay=False),
    default=None,
    help="Extraction manifest path; defaults beside the input manifest.",
)
@click.option("--force", is_flag=True, help="Re-download existing raw files.")
@click.option(
    "--max-download-bytes",
    type=click.IntRange(min=1, max=MAX_EXACT_DOCUMENT_BYTES),
    default=MAX_EXACT_DOCUMENT_BYTES,
    show_default=True,
)
@click.option(
    "--max-pdf-pages",
    type=click.IntRange(min=1, max=MAX_EXACT_DOCUMENT_PAGES),
    default=MAX_EXACT_DOCUMENT_PAGES,
    show_default=True,
)
def extract_documents_command(
    manifest_path: Path,
    output_manifest: Path | None,
    force: bool,
    max_download_bytes: int,
    max_pdf_pages: int,
) -> None:
    """Download and extract only exact documents explicitly listed in a manifest."""
    try:
        manifest = extract_exact_documents(
            manifest_path,
            output_manifest=output_manifest,
            force=force,
            max_download_bytes=max_download_bytes,
            max_pdf_pages=max_pdf_pages,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[green]bounded exact-document extraction complete[/green]")
    for key, value in manifest["summary"].items():
        console.print(f"{key}: {value}")
    if manifest["summary"]["documents_failed"]:
        raise click.ClickException(
            "one or more exact documents failed; inspect the preserved extraction manifest"
        )
