# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the AI Act/GDPR architecture compliance-analysis skill.

The report is not a legal opinion. The tests assert that the generated artifact
has the engineering properties the project needs: explicit criteria, source
URLs, design strategies, evidence paths, RAG+LLM contrast, residual gaps, and a
machine-readable payload.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "proj_skills"
    / "compliance"
    / "ai-act-gdpr-architecture-assessor"
    / "scripts"
    / "render_architecture_compliance_analysis.py"
)


def test_ai_act_gdpr_architecture_assessor_generates_deep_dive(tmp_path: Path) -> None:
    """The compliance assessor should generate criteria-rich JSON and HTML."""
    subprocess.run(
        ["uv", "run", "python", str(SCRIPT), "--output-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
    )

    json_path = tmp_path / "architecture_compliance_analysis.json"
    html_path = tmp_path / "architecture_compliance_analysis.html"
    assert json_path.exists()
    assert html_path.exists()

    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["not_legal_advice"] is True
    assert report["scope"]["contrast_baseline"].startswith("Pure RAG+LLM")
    assert len(report["criteria"]) >= 12

    regulations = {criterion["regulation"] for criterion in report["criteria"]}
    assert {"EU AI Act", "GDPR"}.issubset(regulations)
    assert report["status_counts"]["designed_strength"] >= 5
    assert report["status_counts"]["partially_addressed"] >= 3
    assert report["status_counts"]["requires_legal_review"] >= 1

    for criterion in report["criteria"]:
        assert criterion["source_url"].startswith("https://")
        assert criterion["ruler_design_strategies"]
        assert criterion["evidence_paths"]
        assert "RAG" in criterion["rag_llm_contrast"] or "RAG+LLM" in criterion["rag_llm_contrast"]
        assert criterion["residual_gaps"]
        assert criterion["status"] in {
            "designed_strength",
            "partially_addressed",
            "requires_legal_review",
            "action_required",
        }

    html = html_path.read_text(encoding="utf-8")
    assert "RULER AI Act and GDPR Architecture Analysis" in html
    assert "RAG + LLM Contrast" in html
    assert "Embedded Machine-Readable JSON" in html
