# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

# Lunar AI

"""Render RULER project summary statistics as JSON and self-contained HTML.

The script is intentionally repo-local and deterministic: it scans source files,
skills, tests, workflow routing, and formalized artifacts without relying on
external services. The resulting report is meant for project communication and
release-readiness discussions, not for build tooling.
"""

from __future__ import annotations

import argparse
import ast
import html
import importlib.util
import json
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".lp", ".pl"}
CODE_SUFFIXES = {".py"}
ARTIFACT_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".md", ".lp", ".pl"}


@dataclass
class PythonMetrics:
    files: int = 0
    classes: int = 0
    functions: int = 0
    methods: int = 0
    test_cases: int = 0
    loc: int = 0


class PythonAstCounter(ast.NodeVisitor):
    """Count Python declarations while distinguishing top-level functions and methods."""

    def __init__(self, is_test_file: bool) -> None:
        self.is_test_file = is_test_file
        self.class_stack: list[str] = []
        self.classes = 0
        self.functions = 0
        self.methods = 0
        self.test_cases = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.classes += 1
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.class_stack:
            self.methods += 1
        else:
            self.functions += 1
        if self.is_test_file and node.name.startswith("test_"):
            self.test_cases += 1
        self.generic_visit(node)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to build/ruler/project_summary_stats under --root.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    output_dir = args.output_dir or root / "build" / "ruler" / "project_summary_stats"
    report = build_report(root)
    write_report(report, output_dir)

    print(f"json: {output_dir / 'project_summary_stats.json'}")
    print(f"html: {output_dir / 'project_summary_stats.html'}")


def _default_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_report(root: Path) -> dict[str, Any]:
    pyproject = _load_pyproject(root)
    all_files = list(_iter_repo_files(root))
    python_files = [path for path in all_files if path.suffix == ".py"]
    prompt_files = _prompt_files(all_files)
    runtime_skills = sorted((root / "skills").glob("**/SKILL.md"))
    project_skills = sorted((root / "proj_skills").glob("**/SKILL.md"))
    workflow_routes = _load_workflow_routes(root)
    execution_surfaces = _execution_surface_summary(root)
    delivery_status = _delivery_status(root)

    python_by_group = _python_metrics_by_group(root, python_files)
    total_python = _sum_python_metrics(python_by_group.values())
    functionality = _functionality_breakdown(root, all_files, python_by_group)
    solvers = _solver_summary(root, pyproject)
    compliance_analysis = _build_architecture_compliance_analysis(root)

    report = {
        "report_id": "ruler_project_summary_stats",
        "generated_from": str(root),
        "definitions": {
            "skills": "Files named SKILL.md under skills/ and proj_skills/.",
            "prompts": "Prompt-like control artifacts: SKILL.md, AGENTS.md, CLAUDE.md, and files with prompt in the filename.",
            "classes_functions_methods": "Python AST declarations. Methods are functions nested in classes.",
            "test_cases": "Python AST functions or methods beginning with test_ under tests/.",
            "lines_of_code": "Nonblank, noncomment Python lines; artifact lines are counted separately.",
        },
        "headline_metrics": {
            "runtime_skills": len(runtime_skills),
            "project_skills": len(project_skills),
            "total_skills": len(runtime_skills) + len(project_skills),
            "prompt_like_artifacts": len(prompt_files),
            "python_files": total_python.files,
            "python_classes": total_python.classes,
            "python_functions": total_python.functions,
            "python_methods": total_python.methods,
            "test_cases": total_python.test_cases,
            "python_loc": total_python.loc,
            "workflow_routes": len(workflow_routes),
            "registered_workflows": execution_surfaces["registered_workflows"],
            "workflow_hooks": execution_surfaces["workflow_hooks"],
            "runtime_agent_configs": execution_surfaces["runtime_agent_configs"],
            "todo_completed": delivery_status["todos"]["completed"],
            "todo_total": delivery_status["todos"]["total"],
            "unique_documents": delivery_status["extraction"]["unique_documents"],
            "solver_families": len(solvers),
        },
        "skill_breakdown": {
            "runtime_by_theme": _skill_theme_counts(root / "skills", runtime_skills),
            "project_by_theme": _skill_theme_counts(root / "proj_skills", project_skills),
        },
        "skill_inventory": {
            "runtime_clusters": _skill_inventory_by_cluster(root, root / "skills", runtime_skills),
            "project_clusters": _skill_inventory_by_cluster(
                root, root / "proj_skills", project_skills
            ),
        },
        "prompt_breakdown": _prompt_breakdown(root, prompt_files),
        "python_breakdown": {
            group: vars(metrics) for group, metrics in sorted(python_by_group.items())
        },
        "functionality_breakdown": functionality,
        "solvers": solvers,
        "workflows": workflow_routes,
        "execution_surfaces": execution_surfaces,
        "delivery_status": delivery_status,
        "architecture_compliance_analysis": compliance_analysis,
        "qualitative_summary": _qualitative_summary(functionality, solvers, workflow_routes),
        "evidence_paths": _evidence_paths(root),
    }
    return report


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "project_summary_stats.json"
    html_path = output_dir / "project_summary_stats.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")


def _iter_repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        files.append(path)
    return files


def _load_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _load_workflow_routes(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "use_cases" / "workflow_router.yaml"
    if not path.exists():
        return []
    routes = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [
        {
            "route_id": route.get("route_id"),
            "title": route.get("title"),
            "hook": route.get("hook"),
            "skills": route.get("skills", []),
            "validation_commands": route.get("validation_commands", []),
        }
        for route in routes
    ]


def _execution_surface_summary(root: Path) -> dict[str, int]:
    """Count declared agent, workflow, hook, and client execution surfaces."""
    workflow_path = root / ".ruler" / "workflows.yaml"
    hook_path = root / ".ruler" / "hooks.yaml"
    workflows = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    hooks = yaml.safe_load(hook_path.read_text(encoding="utf-8")) or {}
    return {
        "registered_workflows": len(workflows.get("workflows", [])),
        "workflow_hooks": len(hooks.get("hooks", [])),
        "ingestion_operations": len(workflows.get("ingestion_operations", [])),
        "external_tools": len(workflows.get("external_tools", [])),
        "runtime_agent_configs": len(list((root / "skills").glob("**/agents/openai.yaml"))),
        "project_agent_configs": len(list((root / "proj_skills").glob("**/agents/openai.yaml"))),
        "opencode_wrappers": len(list((root / ".opencode" / "skills").glob("*/SKILL.md"))),
        "claude_wrappers": len(list((root / ".claude" / "skills").glob("*/SKILL.md"))),
    }


def _delivery_status(root: Path) -> dict[str, Any]:
    """Summarize optional TODO progress and current extraction evidence."""
    todo_path = root / "to-do.md"
    todo_available = todo_path.is_file()
    todo_text = todo_path.read_text(encoding="utf-8") if todo_available else ""
    completed_titles = [
        " ".join(match.split())
        for match in re.findall(r"^- \[x\] \*\*(.+?)\*\*", todo_text, re.MULTILINE | re.DOTALL)
    ]
    completed = len(re.findall(r"^- \[x\]", todo_text, re.MULTILINE))
    opened = len(re.findall(r"^- \[ \]", todo_text, re.MULTILINE))

    plan_path = root / "data" / "operations" / "progressive_onboarding" / "plan.yaml"
    ledger_path = root / "data" / "operations" / "progressive_onboarding" / "progress_ledger.jsonl"
    batch_root = root / "data" / "operations" / "progressive_onboarding" / "batches"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    latest: dict[str, dict[str, Any]] = {}
    event_count = 0
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            latest[event["batch_id"]] = event
            event_count += 1

    batch_rows: list[dict[str, Any]] = []
    for batch in plan.get("batches", []):
        batch_id = batch["batch_id"]
        batch_dir = batch_root / batch_id
        event = latest.get(batch_id, {})
        extraction_path = batch_dir / "input" / "extraction_manifest.yaml"
        extraction_payload = (
            yaml.safe_load(extraction_path.read_text(encoding="utf-8")) or {}
            if extraction_path.exists()
            else {}
        )
        extraction_summary = extraction_payload.get("summary", {})
        batch_rows.append(
            {
                "batch_id": batch_id,
                "products": batch.get("product_labels", []),
                "stage": event.get("stage", "not_started"),
                "documents": int(extraction_summary.get("selected_documents", 0)),
                "extracted": int(extraction_summary.get("documents_extracted", 0)),
                "failed": int(extraction_summary.get("documents_failed", 0)),
                "spans": _yaml_sequence_count(batch_dir / "output" / "spans.yaml"),
                "assertions": _yaml_sequence_count(batch_dir / "output" / "assertions.yaml"),
                "note": event.get("note", "No execution evidence recorded."),
            }
        )

    document_records: list[dict[str, Any]] = []
    for manifest_path in sorted((root / "kb/corpora").glob("*/manifest.yaml")):
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        for artifact in payload.get("artifacts", []):
            if artifact.get("category") == "source_evidence":
                document_records.append(
                    {
                        "document_id": artifact["document_id"],
                        "raw_sha256": artifact["sha256"],
                        "status": "extracted",
                    }
                )
    unique_documents = {
        item.get("raw_sha256") or item.get("source_version_id") or item.get("document_id")
        for item in document_records
        if item.get("raw_sha256") or item.get("source_version_id") or item.get("document_id")
    }
    executed = [row for row in batch_rows if row["stage"] != "not_started"]
    return {
        "todos": {
            "available": todo_available,
            "completed": completed,
            "open": opened,
            "total": completed + opened,
            "completion_percent": (
                round(100 * completed / (completed + opened)) if completed + opened else 0
            ),
            "latest_completed": completed_titles[-10:],
            "remaining": (
                [
                    "Resolve the complete canonical source and discovery backlog.",
                    "Expand onboarding by recommendation impact and source readiness.",
                    "Advance every remaining batch independently through all quality gates.",
                ]
                if todo_available
                else []
            ),
        },
        "onboarding": {
            "planned_batches": len(batch_rows),
            "published_batches": sum(row["stage"] == "published" for row in batch_rows),
            "active_batches": sum(
                row["stage"] not in {"published", "not_started"} for row in batch_rows
            ),
            "not_started_batches": sum(row["stage"] == "not_started" for row in batch_rows),
            "ledger_events": event_count,
            "batches": batch_rows,
        },
        "extraction": {
            "manifest_records": len(document_records),
            "unique_documents": len(unique_documents),
            "extracted_records": sum(
                item.get("status") == "extracted" for item in document_records
            ),
            "failed_records": sum(item.get("status") == "failed" for item in document_records),
            "executed_batch_documents": sum(row["documents"] for row in executed),
            "executed_batch_extractions": sum(row["extracted"] for row in executed),
            "executed_batch_spans": sum(row["spans"] for row in executed),
            "executed_batch_assertions": sum(row["assertions"] for row in executed),
        },
    }


def _yaml_sequence_count(path: Path) -> int:
    """Count root-level YAML sequence records when a batch artifact exists."""
    if not path.exists():
        return 0
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return len(payload) if isinstance(payload, list) else 0


def _prompt_files(files: list[Path]) -> list[Path]:
    prompt_files: list[Path] = []
    for path in files:
        name = path.name.lower()
        if path.name in {"SKILL.md", "AGENTS.md", "CLAUDE.md"} or "prompt" in name:
            prompt_files.append(path)
    return sorted(prompt_files)


def _prompt_breakdown(root: Path, prompt_files: list[Path]) -> dict[str, Any]:
    by_kind: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for path in prompt_files:
        rel = path.relative_to(root)
        if rel.name == "SKILL.md" and rel.parts[0] == "skills":
            kind = "runtime_skill_prompts"
        elif rel.name == "SKILL.md" and rel.parts[0] == "proj_skills":
            kind = "project_skill_prompts"
        elif rel.name in {"AGENTS.md", "CLAUDE.md"}:
            kind = "agent_bridge_prompts"
        else:
            kind = "named_prompt_files"
        by_kind[kind] += 1
        if len(examples[kind]) < 8:
            examples[kind].append(str(rel))
    return {
        "by_kind": dict(sorted(by_kind.items())),
        "examples": dict(sorted(examples.items())),
    }


def _skill_theme_counts(root: Path, skill_files: list[Path]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in skill_files:
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        theme = rel.parts[0] if len(rel.parts) > 1 else "root"
        counts[theme] += 1
    return dict(sorted(counts.items()))


def _skill_inventory_by_cluster(
    repo_root: Path,
    skill_root: Path,
    skill_files: list[Path],
) -> list[dict[str, Any]]:
    clusters: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in skill_files:
        try:
            rel = path.relative_to(skill_root)
        except ValueError:
            continue
        cluster = rel.parts[0] if len(rel.parts) > 1 else "root"
        metadata = _read_skill_metadata(path)
        name = metadata.get("name") or path.parent.name
        description = metadata.get("description") or _fallback_skill_description(path)
        clusters[cluster].append(
            {
                "name": name,
                "description": description,
                "path": str(path.relative_to(repo_root)),
            }
        )

    return [
        {
            "cluster": cluster,
            "label": _group_label(cluster),
            "count": len(entries),
            "skills": sorted(entries, key=lambda item: item["name"]),
        }
        for cluster, entries in sorted(clusters.items())
    ]


def _read_skill_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    raw = yaml.safe_load(parts[1]) or {}
    return {
        str(key): str(value).strip()
        for key, value in raw.items()
        if value is not None and str(value).strip()
    }


def _fallback_skill_description(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "---", "<!--", "-->")):
            continue
        if stripped.startswith(("SPDX-", "name:")):
            continue
        return stripped[:240]
    return "No description provided."


def _python_metrics_by_group(root: Path, python_files: list[Path]) -> dict[str, PythonMetrics]:
    groups: dict[str, PythonMetrics] = defaultdict(PythonMetrics)
    for path in python_files:
        rel = path.relative_to(root)
        group = _functionality_group(rel)
        metrics = groups[group]
        metrics.files += 1
        metrics.loc += _python_loc(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        counter = PythonAstCounter(is_test_file=rel.parts[0] == "tests")
        counter.visit(tree)
        metrics.classes += counter.classes
        metrics.functions += counter.functions
        metrics.methods += counter.methods
        metrics.test_cases += counter.test_cases
    return dict(groups)


def _python_loc(path: Path) -> int:
    loc = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            loc += 1
    return loc


def _sum_python_metrics(metrics_list: Any) -> PythonMetrics:
    total = PythonMetrics()
    for metrics in metrics_list:
        total.files += metrics.files
        total.classes += metrics.classes
        total.functions += metrics.functions
        total.methods += metrics.methods
        total.test_cases += metrics.test_cases
        total.loc += metrics.loc
    return total


def _functionality_group(rel: Path) -> str:
    parts = list(rel.parts)
    if not parts:
        return "."
    if parts[0] == "ruler" and len(parts) > 1:
        return f"ruler/{parts[1]}"
    if parts[0] == "tests" and len(parts) > 1:
        return f"tests/{parts[1]}"
    if parts[0] in {"skills", "proj_skills"} and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _functionality_breakdown(
    root: Path,
    all_files: list[Path],
    python_by_group: dict[str, PythonMetrics],
) -> list[dict[str, Any]]:
    grouped_files: dict[str, list[Path]] = defaultdict(list)
    for path in all_files:
        rel = path.relative_to(root)
        grouped_files[_functionality_group(rel)].append(path)

    rows: list[dict[str, Any]] = []
    for group, paths in sorted(grouped_files.items()):
        text_lines = sum(_line_count(path) for path in paths if path.suffix in TEXT_SUFFIXES)
        artifact_lines = sum(
            _line_count(path) for path in paths if path.suffix in ARTIFACT_SUFFIXES
        )
        py = python_by_group.get(group, PythonMetrics())
        rows.append(
            {
                "group": group,
                "label": _group_label(group),
                "role": _group_role(group),
                "files": len(paths),
                "python_files": py.files,
                "python_loc": py.loc,
                "classes": py.classes,
                "functions": py.functions,
                "methods": py.methods,
                "test_cases": py.test_cases,
                "artifact_lines": artifact_lines,
                "text_lines": text_lines,
            }
        )
    return rows


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except UnicodeDecodeError:
        return 0


def _group_label(group: str) -> str:
    return group.replace("_", " ").replace("/", " / ").title()


def _group_role(group: str) -> str:
    roles = {
        "ruler/reasoning": "Core inference, eligibility, policy effects, package ranking, counterfactuals, and decision packets.",
        "ruler/solvers": "Solver backends for hard and soft constraint ranking.",
        "ruler/kb": "Formalized KB loading, priority promotion, translation control, and vocabulary normalization.",
        "ruler/source": "Source ingestion, workbook sampling, provider-document maps, and extraction corpora.",
        "ruler/interfaces": "HTML, JSON, YAML, and markdown interfaces for dashboards, logs, demonstrators, and workflow explorers.",
        "ruler/runtime": "Hooks, validators, API configuration, MCP server, and coding-agent bridges.",
        "tests/reasoning": "Reasoning, solver, and maturity regression tests.",
        "tests/kb": "KB integrity, customer profile, and autoformalization tests.",
        "tests/interfaces": "Dashboard, router, graph, and report rendering tests.",
        "tests/runtime": "Runtime bridge, MCP, API config, and platform tests.",
        "tests/source": "Source ingestion and workbook sampling tests.",
        "skills/reasoning": "Runtime reasoning skills bound to hook and workflow controls.",
        "skills/autoformalization": "Runtime source-to-formalization and vocabulary skills.",
        "skills/source": "Runtime source-management and freshness skills.",
        "skills/workflow": "Workflow orchestration skills.",
        "skills/demonstrators": "Customer-facing demonstrator skills.",
        "proj_skills/project-management": "Project communication, reporting, architecture, and planning skills.",
        "proj_skills/communication": "External-facing explanation and report-building skills.",
        "proj_skills/customer-profile": "Out-of-core customer profile abstraction and reporting skills.",
        "proj_skills/compliance": "Dependency and license reporting skills.",
        "kb": "Formalized and draft knowledge bases.",
        "data": "Example inputs, source manifests, extracted text, and reference artifacts.",
        "docs": "Architecture, reasoning, communication, and project narrative documents.",
    }
    return roles.get(group, "Repository support artifacts or generated-adjacent project content.")


def _solver_summary(root: Path, pyproject: dict[str, Any]) -> list[dict[str, Any]]:
    deps = set(pyproject.get("project", {}).get("dependencies", []))
    dep_text = "\n".join(deps).lower()
    asp_files = sorted((root / "kb" / "formalized" / "real" / "rules" / "asp").glob("*.lp"))
    prolog_files = sorted((root / "kb" / "formalized" / "real" / "rules" / "prolog").glob("*.pl"))
    solvers: list[dict[str, Any]] = []
    if "z3-solver" in dep_text or (root / "ruler" / "solvers" / "maxsmt.py").exists():
        solvers.append(
            {
                "name": "Z3 Optimize / MaxSMT",
                "role": "Primary hard-before-soft feature ranking backend.",
                "evidence": ["pyproject.toml", "ruler/solvers/maxsmt.py"],
            }
        )
    if "ortools" in dep_text:
        solvers.append(
            {
                "name": "OR-Tools CP-SAT / package optimization",
                "role": "Package-configuration and cross-check substrate for combinatorial choices.",
                "evidence": ["pyproject.toml", "ruler/reasoning/package_solver.py"],
            }
        )
    if "clingo" in dep_text or asp_files:
        solvers.append(
            {
                "name": "clingo / ASP policy rules",
                "role": "Executable logic-program layer for policy-rule validation and promoted rule checks.",
                "evidence": [
                    "pyproject.toml",
                    *[str(path.relative_to(root)) for path in asp_files[:4]],
                ],
            }
        )
    if prolog_files:
        solvers.append(
            {
                "name": "Prolog-style review mirrors",
                "role": "Readable bilingual rule mirrors for advisor/reviewer inspection; not the primary executable backend.",
                "evidence": [str(path.relative_to(root)) for path in prolog_files[:4]],
            }
        )
    return solvers


def _qualitative_summary(
    functionality: list[dict[str, Any]],
    solvers: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
) -> dict[str, Any]:
    top_groups = sorted(
        functionality,
        key=lambda row: (row["python_loc"], row["artifact_lines"], row["files"]),
        reverse=True,
    )[:8]
    return {
        "architecture_claim": "RULER is a controlled neuro-symbolic reasoning framework: extraction and vocabulary control feed formalized KB artifacts, which drive rule activation, solver-backed tradeoff ranking, audit logs, and customer-facing explanations.",
        "solver_claim": "The solver layer separates hard blockers from soft preferences and exposes traces that can be rendered in dashboards and reports.",
        "workflow_claim": f"The workflow router exposes {len(workflows)} named routes spanning source ingestion, translation, KB promotion, reasoning, dashboards, runtime bridges, and business-customer comparison.",
        "largest_functionality_groups": [
            {
                "group": row["group"],
                "role": row["role"],
                "python_loc": row["python_loc"],
                "artifact_lines": row["artifact_lines"],
            }
            for row in top_groups
        ],
        "solver_names": [solver["name"] for solver in solvers],
    }


def _evidence_paths(root: Path) -> list[str]:
    candidates = [
        "pyproject.toml",
        "ruler/",
        "ruler/solvers/maxsmt.py",
        "ruler/reasoning/",
        "ruler/kb/",
        "ruler/source/",
        "ruler/interfaces/",
        "ruler/runtime/",
        "skills/",
        "proj_skills/",
        "tests/",
        "data/use_cases/workflow_router.yaml",
        ".ruler/hooks.yaml",
        "skills/SKILL_HOOKS.yaml",
        "kb/",
    ]
    return [path for path in candidates if (root / path).exists()]


def _build_architecture_compliance_analysis(root: Path) -> dict[str, Any]:
    script_path = (
        root
        / "proj_skills"
        / "compliance"
        / "ai-act-gdpr-architecture-assessor"
        / "scripts"
        / "render_architecture_compliance_analysis.py"
    )
    if not script_path.exists():
        return {
            "available": False,
            "summary": "AI Act/GDPR architecture analysis skill is not present.",
            "criteria": [],
            "status_counts": {},
        }

    spec = importlib.util.spec_from_file_location("ruler_architecture_compliance", script_path)
    if spec is None or spec.loader is None:
        return {
            "available": False,
            "summary": "AI Act/GDPR architecture analysis could not be loaded.",
            "criteria": [],
            "status_counts": {},
        }
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    analysis = module.build_analysis(root)
    return {
        "available": True,
        "status": analysis["status"],
        "not_legal_advice": analysis["not_legal_advice"],
        "status_counts": analysis["status_counts"],
        "criteria": analysis["criteria"],
        "rag_llm_contrast_summary": analysis["rag_llm_contrast_summary"],
        "recommended_next_actions": analysis["recommended_next_actions"],
        "source_catalog": analysis["source_catalog"],
        "report_paths": {
            "json": "build/ruler/architecture_compliance/architecture_compliance_analysis.json",
            "html": "build/ruler/architecture_compliance/architecture_compliance_analysis.html",
        },
    }


def render_html(report: dict[str, Any]) -> str:
    metrics = report["headline_metrics"]
    delivery = report["delivery_status"]
    todos = delivery["todos"]
    todo_completion_summary = (
        f"{todos['completed']} of {todos['total']} canonical TODOs are complete "
        f"({todos['completion_percent']}%)."
        if todos["available"]
        else "TODO progress is unavailable; no TODO source is present."
    )
    todo_remaining_summary = (
        f"{todos['open']} canonical TODOs remain open."
        if todos["available"]
        else "Remaining TODOs are unavailable; no TODO source is present."
    )
    onboarding = delivery["onboarding"]
    extraction = delivery["extraction"]
    execution = report["execution_surfaces"]
    functionality_rows = "\n".join(
        _render_functionality_row(row) for row in report["functionality_breakdown"]
    )
    workflow_rows = "\n".join(_render_workflow_row(row) for row in report["workflows"])
    solver_cards = "\n".join(_render_solver_card(row) for row in report["solvers"])
    runtime_skills = _render_count_list(report["skill_breakdown"]["runtime_by_theme"])
    project_skills = _render_count_list(report["skill_breakdown"]["project_by_theme"])
    runtime_skill_inventory = _render_skill_inventory(report["skill_inventory"]["runtime_clusters"])
    project_skill_inventory = _render_skill_inventory(report["skill_inventory"]["project_clusters"])
    prompt_breakdown = _render_count_list(report["prompt_breakdown"]["by_kind"])
    compliance = report["architecture_compliance_analysis"]
    compliance_cards = "\n".join(
        _render_compliance_card(item) for item in compliance.get("criteria", [])
    )
    compliance_status = _render_count_list(compliance.get("status_counts", {}))
    compliance_contrast = "".join(
        f"<li>{html.escape(item)}</li>" for item in compliance.get("rag_llm_contrast_summary", [])
    )
    compliance_actions = "".join(
        f"<li>{html.escape(item)}</li>" for item in compliance.get("recommended_next_actions", [])
    )
    payload = html.escape(json.dumps(report, indent=2, sort_keys=True))
    max_loc = max((row["python_loc"] for row in report["functionality_breakdown"]), default=1)
    completed_todos = "".join(
        f"<li>{html.escape(title)}</li>" for title in todos["latest_completed"]
    )
    remaining_todos = "".join(f"<li>{html.escape(title)}</li>" for title in todos["remaining"])
    onboarding_rows = "\n".join(_render_onboarding_row(row) for row in onboarding["batches"])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RULER Project Summary Stats</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #071018;
      --panel: #0d1722;
      --panel-2: #111f2d;
      --text: #edf6ff;
      --muted: #9fb0c2;
      --line: #233447;
      --accent: #56d6a9;
      --accent-2: #6aa8ff;
      --warn: #ffd166;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 32px 20px 56px; }}
    header {{ display: grid; gap: 12px; margin-bottom: 24px; }}
    h1, h2, h3 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 34px; }}
    h2 {{ font-size: 20px; margin-top: 28px; margin-bottom: 12px; }}
    h3 {{ font-size: 15px; }}
    p {{ margin: 0; color: var(--muted); max-width: 980px; }}
    .grid {{ display: grid; gap: 14px; }}
    .metrics {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric strong {{ display: block; font-size: 28px; color: var(--accent); }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; margin-top: 4px; }}
    .two {{ grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
    .solver-grid {{ grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); }}
    ul {{ margin: 10px 0 0; padding-left: 18px; color: var(--muted); }}
    li strong {{ color: var(--text); }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 8px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ color: #cfe4f8; background: var(--panel-2); font-size: 12px; text-transform: uppercase; }}
    td {{ color: var(--muted); font-size: 13px; }}
    td:first-child, .name {{ color: var(--text); font-weight: 650; }}
    .bar {{ height: 8px; border-radius: 99px; background: #1c2c3a; overflow: hidden; min-width: 90px; }}
    .bar > span {{ display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }}
    .small {{ font-size: 12px; color: var(--muted); }}
    .pill {{ display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; color: var(--muted); margin: 2px; }}
    .status {{ display: inline-block; border-radius: 999px; padding: 3px 8px; font-size: 11px; font-weight: 750; text-transform: uppercase; }}
    .status-published {{ color: #071018; background: var(--accent); }}
    .status-active {{ color: #071018; background: var(--warn); }}
    .status-muted {{ color: var(--muted); background: #182633; }}
    details {{ margin-top: 18px; }}
    summary {{ cursor: pointer; color: var(--accent); }}
    pre {{
      max-height: 420px;
      overflow: auto;
      padding: 14px;
      background: #050b11;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: #c9e5ff;
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>RULER Project Summary Stats</h1>
    <p>{html.escape(report["qualitative_summary"]["architecture_claim"])}</p>
  </header>

  <section class="grid metrics">
    {_metric("Skills", metrics["total_skills"], "runtime + project")}
    {_metric("Agents", metrics["runtime_agent_configs"], "runtime OpenAI configs")}
    {_metric("Prompt Artifacts", metrics["prompt_like_artifacts"], "definition disclosed")}
    {_metric("Python LOC", metrics["python_loc"], "nonblank noncomment")}
    {_metric("Classes", metrics["python_classes"], "AST counted")}
    {_metric("Functions", metrics["python_functions"], "top-level")}
    {_metric("Methods", metrics["python_methods"], "inside classes")}
    {_metric("Test Cases", metrics["test_cases"], "pytest-style")}
    {_metric("Workflows", metrics["registered_workflows"], "canonical registry")}
    {_metric("Hooks", metrics["workflow_hooks"], "lifecycle bindings")}
    {_metric("TODOs", metrics["todo_completed"], f"of {metrics['todo_total']} complete") if todos["available"] else ""}
    {_metric("Documents", metrics["unique_documents"], "content/version unique")}
  </section>

  <section>
    <h2>Delivery, TODO, and Extraction Status</h2>
    <div class="grid two">
      <div class="card">
        <h3>Latest Completed TODOs</h3>
        <p>{todo_completion_summary}</p>
        <ul>{completed_todos}</ul>
      </div>
      <div class="card">
        <h3>Remaining Work</h3>
        <p>{todo_remaining_summary}</p>
        <ul>{remaining_todos}</ul>
      </div>
      <div class="card">
        <h3>Extraction Snapshot</h3>
        <ul>
          <li><strong>{extraction["unique_documents"]}</strong> unique documents across <strong>{extraction["manifest_records"]}</strong> manifest records.</li>
          <li><strong>{extraction["extracted_records"]}</strong> extracted and <strong>{extraction["failed_records"]}</strong> failed records.</li>
          <li><strong>{extraction["executed_batch_documents"]}</strong> bounded batch documents; <strong>{extraction["executed_batch_extractions"]}</strong> extracted.</li>
          <li><strong>{extraction["executed_batch_spans"]}</strong> source spans and <strong>{extraction["executed_batch_assertions"]}</strong> formal assertions in executed batches.</li>
        </ul>
      </div>
      <div class="card">
        <h3>Execution Surfaces</h3>
        <ul>
          <li><strong>{execution["registered_workflows"]}</strong> registered workflows and <strong>{execution["workflow_hooks"]}</strong> hooks.</li>
          <li><strong>{execution["runtime_agent_configs"]}</strong> runtime and <strong>{execution["project_agent_configs"]}</strong> project agent configurations.</li>
          <li><strong>{execution["ingestion_operations"]}</strong> controlled ingestion operations.</li>
          <li><strong>{execution["opencode_wrappers"]}</strong> OpenCode and <strong>{execution["claude_wrappers"]}</strong> Claude wrappers.</li>
        </ul>
      </div>
    </div>
    <h3 style="margin-top:18px">Progressive Onboarding Batches</h3>
    <p>{onboarding["published_batches"]} published, {onboarding["active_batches"]} active, {onboarding["not_started_batches"]} not started; {onboarding["ledger_events"]} append-only checkpoint events.</p>
    <table style="margin-top:10px">
      <thead><tr><th>Batch</th><th>Products</th><th>Stage</th><th>Docs</th><th>Extracted</th><th>Spans</th><th>Assertions</th><th>Latest note</th></tr></thead>
      <tbody>{onboarding_rows}</tbody>
    </table>
  </section>

  <section class="grid two">
    <div class="card">
      <h2>Skill Breakdown</h2>
      <h3>Runtime skills</h3>
      {runtime_skills}
      <h3>Project skills</h3>
      {project_skills}
    </div>
    <div class="card">
      <h2>Prompt-Like Artifacts</h2>
      <p>Prompts are counted as skill instructions, coding-agent bridge files, and explicitly named prompt files.</p>
      {prompt_breakdown}
    </div>
  </section>

  <section>
    <h2>Skills By Cluster</h2>
    <p>Each cluster lists the visible skill name and its concise declared purpose from the skill frontmatter.</p>
    <div class="grid two">
      <div class="card">
        <h3>Runtime Skill Clusters</h3>
        {runtime_skill_inventory}
      </div>
      <div class="card">
        <h3>Project Skill Clusters</h3>
        {project_skill_inventory}
      </div>
    </div>
  </section>

  <section>
    <h2>Underlying Solvers</h2>
    <div class="grid solver-grid">{solver_cards}</div>
  </section>

  <section>
    <h2>Code Metrics By Key Functionality</h2>
    <table data-max-loc="{max_loc}">
      <thead>
        <tr>
          <th>Functionality</th>
          <th>Role</th>
          <th>Files</th>
          <th>Python LOC</th>
          <th>Classes</th>
          <th>Functions</th>
          <th>Methods</th>
          <th>Tests</th>
          <th>LOC Share</th>
        </tr>
      </thead>
      <tbody>{functionality_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Main Workflows</h2>
    <table>
      <thead>
        <tr>
          <th>Route</th>
          <th>Hook</th>
          <th>Skills</th>
          <th>Validation</th>
        </tr>
      </thead>
      <tbody>{workflow_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>EU AI Act and GDPR Architecture Analysis</h2>
    <div class="grid two">
      <div class="card">
        <h3>Status Counts</h3>
        {compliance_status}
        <p class="small">Engineering readiness analysis only; not legal advice.</p>
      </div>
      <div class="card">
        <h3>RAG + LLM Contrast</h3>
        <ul>{compliance_contrast}</ul>
      </div>
    </div>
    <div class="grid two">
      <div class="card">
        <h3>Recommended Next Actions</h3>
        <ul>{compliance_actions}</ul>
      </div>
      <div class="card">
        <h3>Generated Compliance Report</h3>
        <p>Detailed HTML/JSON artifacts are generated by the project compliance skill.</p>
        <div>
          <span class="pill">{html.escape(compliance.get("report_paths", {}).get("html", "n/a"))}</span>
          <span class="pill">{html.escape(compliance.get("report_paths", {}).get("json", "n/a"))}</span>
        </div>
      </div>
    </div>
    <div>{compliance_cards}</div>
  </section>

  <section class="grid two">
    <div class="card">
      <h2>Qualitative Functionalities</h2>
      <ul>
        <li><strong>Source and extraction:</strong> source PDFs, manifests, Docling/pypdf outputs, workbook sampling, and freshness controls.</li>
        <li><strong>Representation:</strong> controlled vocabulary, bilingual comments, formalized KB entries, and customer-profile abstractions.</li>
        <li><strong>Reasoning:</strong> fact activation, policy effects, hard constraints, soft objectives, MaxSMT ranking, package solving, and counterfactual checks.</li>
        <li><strong>Interfaces:</strong> inference dashboard, workflow graphs, reasoning logs, customer demonstrators, and customer-facing reports.</li>
        <li><strong>Runtime:</strong> hooks, validation commands, MCP server, API config, Claude Code bridge, and OpenCode bridge.</li>
      </ul>
    </div>
    <div class="card">
      <h2>Evidence Paths</h2>
      <div>{"".join(f'<span class="pill">{html.escape(path)}</span>' for path in report["evidence_paths"])}</div>
    </div>
  </section>

  <details>
    <summary>Embedded Machine-Readable JSON</summary>
    <pre id="report-json">{payload}</pre>
  </details>
</main>
</body>
</html>
"""


def _metric(label: str, value: int, sublabel: str) -> str:
    return (
        '<div class="card metric">'
        f"<strong>{value:,}</strong>"
        f"<span>{html.escape(label)}<br>{html.escape(sublabel)}</span>"
        "</div>"
    )


def _render_count_list(counts: dict[str, int]) -> str:
    if not counts:
        return '<p class="small">No entries found.</p>'
    items = "\n".join(
        f"<li><strong>{html.escape(_group_label(name))}</strong>: {count}</li>"
        for name, count in sorted(counts.items())
    )
    return f"<ul>{items}</ul>"


def _render_skill_inventory(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return '<p class="small">No skills found.</p>'
    return "\n".join(_render_skill_cluster(cluster) for cluster in clusters)


def _render_skill_cluster(cluster: dict[str, Any]) -> str:
    rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(skill["name"])}</td>
          <td>{html.escape(skill["description"])}</td>
        </tr>"""
        for skill in cluster["skills"]
    )
    return f"""
      <details class="skill-cluster">
        <summary>{html.escape(cluster["label"])} ({cluster["count"]})</summary>
        <table>
          <thead>
            <tr>
              <th>Skill</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </details>"""


def _render_solver_card(solver: dict[str, Any]) -> str:
    evidence = "".join(
        f'<span class="pill">{html.escape(path)}</span>' for path in solver["evidence"]
    )
    return (
        '<div class="card">'
        f"<h3>{html.escape(solver['name'])}</h3>"
        f"<p>{html.escape(solver['role'])}</p>"
        f"<div>{evidence}</div>"
        "</div>"
    )


def _render_functionality_row(row: dict[str, Any]) -> str:
    width = min(100, max(2, row["python_loc"] // 10))
    return f"""
        <tr>
          <td>{html.escape(row["label"])}</td>
          <td>{html.escape(row["role"])}</td>
          <td>{row["files"]}</td>
          <td>{row["python_loc"]}</td>
          <td>{row["classes"]}</td>
          <td>{row["functions"]}</td>
          <td>{row["methods"]}</td>
          <td>{row["test_cases"]}</td>
          <td><div class="bar"><span style="width:{width}%"></span></div></td>
        </tr>"""


def _render_workflow_row(route: dict[str, Any]) -> str:
    skills = ", ".join(route.get("skills", [])[:6])
    validation = ", ".join(route.get("validation_commands", [])[:3])
    return f"""
        <tr>
          <td>{html.escape(str(route.get("title") or route.get("route_id")))}</td>
          <td>{html.escape(str(route.get("hook") or ""))}</td>
          <td>{html.escape(skills)}</td>
          <td>{html.escape(validation)}</td>
        </tr>"""


def _render_onboarding_row(row: dict[str, Any]) -> str:
    """Render one evidence-backed progressive-onboarding batch summary."""
    stage = row["stage"]
    if stage == "published":
        status_class = "status-published"
    elif stage == "not_started":
        status_class = "status-muted"
    else:
        status_class = "status-active"
    return f"""
        <tr>
          <td>{html.escape(row["batch_id"])}</td>
          <td>{html.escape(", ".join(row["products"]))}</td>
          <td><span class="status {status_class}">{html.escape(stage.replace("_", " "))}</span></td>
          <td>{row["documents"]}</td>
          <td>{row["extracted"]}</td>
          <td>{row["spans"]}</td>
          <td>{row["assertions"]}</td>
          <td>{html.escape(row["note"])}</td>
        </tr>"""


def _render_compliance_card(item: dict[str, Any]) -> str:
    evidence = "".join(
        f'<span class="pill">{html.escape(path)}</span>'
        for path in item.get("evidence_paths", [])[:5]
    )
    return f"""
      <div class="card">
        <h3>{html.escape(item.get("criterion", ""))}</h3>
        <p><strong>{html.escape(item.get("regulation", ""))}</strong> -
        {html.escape(item.get("status", ""))}</p>
        <p>{html.escape(item.get("regulatory_expectation", ""))}</p>
        <p class="small">RAG + LLM contrast: {html.escape(item.get("rag_llm_contrast", ""))}</p>
        <div>{evidence}</div>
      </div>"""


if __name__ == "__main__":
    main()
