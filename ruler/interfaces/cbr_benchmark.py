# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic, non-ML benchmark evidence for the five CBR journeys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ruler.domains.cbr_catalog import load_all_cbr_demos
from ruler.interfaces.cbr_cases import retrieve_cbr_cases, suggest_cbr_adaptation, verify_cbr_demo
from ruler.paths import BUILD_DIR


def build_cbr_benchmark() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for demo in load_all_cbr_demos():
        first = retrieve_cbr_cases(demo.domain_id, top_k=3)["result"]
        second = retrieve_cbr_cases(demo.domain_id, top_k=3)["result"]
        order = [item["case_id"] for item in first["retrieved"]]
        contrast = first.get("excluded_contrast") or {}
        adaptation = suggest_cbr_adaptation(demo.domain_id, order[0])
        evaluation = verify_cbr_demo(demo.domain_id)
        rows.append(
            {
                "domain_id": demo.domain_id,
                "hard_filter_precision": (
                    1.0
                    if all(item["eligibility"] == "usable" for item in first["retrieved"])
                    else 0.0
                ),
                "top_k_stable": first["retrieved"] == second["retrieved"],
                "golden_order_match": order == list(demo.expected.retrieval_order),
                "contrast_quality": contrast.get("case_id") == demo.expected.excluded_case_id
                and contrast.get("eligibility") == "contrast_only",
                "adaptation_valid": adaptation["human_review_required"]
                and adaptation["adapted_case"].get("disposition") is None,
                "abstention_or_gate": bool(
                    evaluation["blockers"]
                    or evaluation["unknowns"]
                    or evaluation["human_review_required"]
                ),
                "verification_match": evaluation["action"] == demo.expected.rule_outcome,
            }
        )
    metrics = {
        key: sum(bool(row[key]) for row in rows) / len(rows)
        for key in (
            "hard_filter_precision",
            "top_k_stable",
            "golden_order_match",
            "contrast_quality",
            "adaptation_valid",
            "abstention_or_gate",
            "verification_match",
        )
    }
    return {
        "schema_version": "ruler-cbr-benchmark/1",
        "domain_count": len(rows),
        "metrics": metrics,
        "domains": rows,
        "claim_boundary": "Synthetic deterministic checks measure fixture behavior, not legal, fiscal, trade, procurement, or safety correctness in production.",
    }


def write_cbr_benchmark(output_dir: Path | None = None) -> dict[str, Path]:
    target = output_dir or BUILD_DIR / "cbr" / "benchmark"
    target.mkdir(parents=True, exist_ok=True)
    report = build_cbr_benchmark()
    json_path = target / "benchmark.json"
    markdown_path = target / "benchmark.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# CBR deterministic benchmark",
        "",
        report["claim_boundary"],
        "",
        "| Domain | Golden | Stable | Contrast | Adaptation | Verification |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["domains"]:
        values = [
            "pass" if row[key] else "fail"
            for key in (
                "golden_order_match",
                "top_k_stable",
                "contrast_quality",
                "adaptation_valid",
                "verification_match",
            )
        ]
        lines.append(f"| {row['domain_id']} | " + " | ".join(values) + " |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


__all__ = ["build_cbr_benchmark", "write_cbr_benchmark"]
