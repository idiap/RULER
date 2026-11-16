# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the project summary stats reporter.

The reporter is a project-management skill script, not runtime reasoning code.
These checks keep the generated communication artifact honest enough for reuse:
it must produce JSON and HTML, count visible project structures, and include the
qualitative solver/workflow surfaces requested by the project.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "proj_skills"
    / "project-management"
    / "project-summary-stats-reporter"
    / "scripts"
    / "render_project_summary_stats.py"
)


def test_project_summary_stats_reporter_generates_html_and_json(tmp_path: Path) -> None:
    """The stats reporter should produce a self-contained report from repo evidence."""
    subprocess.run(
        ["uv", "run", "python", str(SCRIPT), "--output-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
    )

    json_path = tmp_path / "project_summary_stats.json"
    html_path = tmp_path / "project_summary_stats.html"
    assert json_path.exists()
    assert html_path.exists()

    report = json.loads(json_path.read_text(encoding="utf-8"))
    metrics = report["headline_metrics"]
    assert metrics["total_skills"] >= 60
    assert metrics["prompt_like_artifacts"] >= metrics["total_skills"]
    assert metrics["python_classes"] > 0
    assert metrics["python_functions"] > 0
    assert metrics["python_methods"] > 0
    assert metrics["test_cases"] >= 100
    assert metrics["python_loc"] > 1000
    assert metrics["workflow_routes"] >= 10
    assert metrics["registered_workflows"] >= metrics["workflow_routes"]
    assert metrics["workflow_hooks"] >= 20
    assert 0 < metrics["runtime_agent_configs"] <= metrics["runtime_skills"]
    # A newly replaced canonical plan may legitimately begin with no completed
    # items; the reporter must describe the repository evidence without
    # inventing historical completions.
    assert metrics["todo_completed"] >= 0
    assert metrics["todo_total"] >= metrics["todo_completed"]
    assert metrics["unique_documents"] > 0
    assert metrics["solver_families"] >= 3

    assert "runtime_by_theme" in report["skill_breakdown"]
    assert "project_by_theme" in report["skill_breakdown"]
    assert report["skill_inventory"]["runtime_clusters"]
    assert report["skill_inventory"]["project_clusters"]
    runtime_skill_names = {
        skill["name"]
        for cluster in report["skill_inventory"]["runtime_clusters"]
        for skill in cluster["skills"]
    }
    project_skill_names = {
        skill["name"]
        for cluster in report["skill_inventory"]["project_clusters"]
        for skill in cluster["skills"]
    }
    assert "core-reasoning-case-builder" in runtime_skill_names
    assert "project-summary-stats-reporter" in project_skill_names
    assert all(
        skill["description"]
        for cluster in report["skill_inventory"]["runtime_clusters"]
        for skill in cluster["skills"]
    )
    assert report["functionality_breakdown"]
    assert report["workflows"]
    assert report["execution_surfaces"]["ingestion_operations"] >= 10
    assert isinstance(report["delivery_status"]["todos"]["latest_completed"], list)
    assert report["delivery_status"]["onboarding"]["planned_batches"] == 0
    assert report["delivery_status"]["extraction"]["executed_batch_extractions"] == 0
    assert report["architecture_compliance_analysis"]["available"] is True
    assert report["architecture_compliance_analysis"]["not_legal_advice"] is True
    assert len(report["architecture_compliance_analysis"]["criteria"]) >= 12
    assert "designed_strength" in report["architecture_compliance_analysis"]["status_counts"]
    assert any("Z3" in solver["name"] for solver in report["solvers"])
    assert any("clingo" in solver["name"] for solver in report["solvers"])

    html = html_path.read_text(encoding="utf-8")
    assert "RULER Project Summary Stats" in html
    assert "Embedded Machine-Readable JSON" in html
    assert "Code Metrics By Key Functionality" in html
    assert "Delivery, TODO, and Extraction Status" in html
    assert "Latest Completed TODOs" in html
    assert "Progressive Onboarding Batches" in html
    assert "Skills By Cluster" in html
    assert "Runtime Skill Clusters" in html
    assert "Project Skill Clusters" in html
    assert "Underlying Solvers" in html
    assert "EU AI Act and GDPR Architecture Analysis" in html
    assert "RAG + LLM Contrast" in html
