# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import json
from pathlib import Path

from ruler.interfaces.cbr_demonstrators import (
    CBRDomainDemonstrator,
    build_cbr_demonstrator_portfolio,
    validate_cbr_demonstrators,
    write_cbr_demonstrator_artifacts,
)


def test_portfolio_contains_five_complete_governed_journeys() -> None:
    portfolio = build_cbr_demonstrator_portfolio()

    assert {item.domain_id for item in portfolio.domains} == {
        "spending",
        "regulatory",
        "fiscal",
        "trade",
        "technical_support",
    }
    for journey in portfolio.domains:
        assert {item.case_role for item in journey.reviewed_precedents} == {
            "positive",
            "negative",
        }
        assert len(journey.reviewed_precedents) == 3
        assert journey.excluded_near_match.case_id not in {
            item.case_id for item in journey.reviewed_precedents
        }
        assert journey.adaptation
        assert all(item.requires_formal_verification for item in journey.adaptation)
        assert journey.counterfactuals
        assert journey.human_review_required
        assert "not proof" in journey.non_reliance_label
        assert journey.live_retrieval.request_id == f"demo-retrieve-{journey.domain_id}"


def test_writer_emits_six_standalone_safe_html_json_pairs(tmp_path: Path) -> None:
    paths = write_cbr_demonstrator_artifacts(tmp_path)

    assert len(paths) == 12
    assert all(path.exists() for path in paths.values())
    for domain_id in ("spending", "regulatory", "fiscal", "trade", "technical_support"):
        payload = json.loads(paths[f"{domain_id}_json"].read_text(encoding="utf-8"))
        CBRDomainDemonstrator.model_validate(payload)
        rendered = paths[f"{domain_id}_html"].read_text(encoding="utf-8")
        assert "Content-Security-Policy" in rendered
        assert "<main" in rendered and "<nav" in rendered and "<table" in rendered
        assert "<script" not in rendered.lower()
        assert "Historical similarity is operational evidence, not proof" in rendered
    portfolio = paths["portfolio_html"].read_text(encoding="utf-8")
    assert all(
        f"href='{domain_id}.html'" in portfolio
        for domain_id in ("spending", "regulatory", "fiscal", "trade", "technical_support")
    )


def test_renderer_escapes_stored_case_content() -> None:
    from ruler.interfaces.cbr_demonstrators import render_cbr_domain_html

    journey = (
        build_cbr_demonstrator_portfolio()
        .domains[0]
        .model_copy(update={"query_summary": "<img src=x onerror=alert(1)>"})
    )
    rendered = render_cbr_domain_html(journey)

    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "<img src=x" not in rendered


def test_validator_reports_artifact_and_boundary_evidence() -> None:
    evidence = validate_cbr_demonstrators()

    assert "domains=5" in evidence
    assert "artifact_pairs=6" in evidence
    assert "non_reliance=required" in evidence
