# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic recommendation-impact diffs for KB release promotion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.ingestion.contracts import canonical_sha256, stable_id


class RecommendationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    selected_feature_id: str
    runner_up_feature_ids: tuple[str, ...]
    caveats: tuple[str, ...]
    source_review_burden: tuple[str, ...]
    frontier: tuple[tuple[str, int], ...]
    counterfactual_ids: tuple[str, ...]


class ImpactExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str
    expected_changed_fields: tuple[str, ...] = ()
    rationale: str


class RecommendationImpactDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str
    baseline: RecommendationOutcome
    candidate: RecommendationOutcome
    changed_fields: tuple[str, ...]
    unexpected_changes: tuple[str, ...]
    expected_but_missing: tuple[str, ...]
    explanation_diff: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return true when observed recommendation changes exactly match expectations."""
        return not self.unexpected_changes and not self.expected_but_missing


class RecommendationImpactReport(BaseModel):
    """Automated deterministic and generative gate over golden-case diffs."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    report_id: str
    baseline_kb_release_id: str | None
    candidate_kb_release_id: str
    diffs: tuple[RecommendationImpactDiff, ...] = Field(min_length=1)
    deterministic_evidence_hashes: dict[str, str]
    generative_gate_config_sha256: str
    generative_evidence_sha256: str
    generative_verdict: Literal["pass", "fail", "uncertain"]
    optional_reviewer_metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def deterministic_and_reviewed(self) -> "RecommendationImpactReport":
        """Bind impact evidence to the candidate release without requiring human approval."""
        expected = stable_id(
            "recommendation_impact",
            {
                "baseline_kb_release_id": self.baseline_kb_release_id,
                "candidate_kb_release_id": self.candidate_kb_release_id,
                "diffs": [item.model_dump(mode="json") for item in self.diffs],
                "deterministic_evidence_hashes": self.deterministic_evidence_hashes,
                "generative_gate_config_sha256": self.generative_gate_config_sha256,
                "generative_evidence_sha256": self.generative_evidence_sha256,
                "generative_verdict": self.generative_verdict,
            },
        )
        if self.report_id != expected:
            raise ValueError("impact report ID does not match its deterministic contents")
        for name, digest in {
            **self.deterministic_evidence_hashes,
            "generative_gate_config": self.generative_gate_config_sha256,
            "generative_evidence": self.generative_evidence_sha256,
        }.items():
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise ValueError(f"{name} must use sha256:<64 hex>")
        recomputed = {
            "impact_diff": canonical_sha256([item.model_dump(mode="json") for item in self.diffs]),
            "schema": canonical_sha256(type(self).model_json_schema()),
            "provenance": canonical_sha256(
                {
                    "baseline_kb_release_id": self.baseline_kb_release_id,
                    "candidate_kb_release_id": self.candidate_kb_release_id,
                }
            ),
        }
        for name, digest in recomputed.items():
            if self.deterministic_evidence_hashes.get(name) != digest:
                raise ValueError(f"{name} deterministic evidence hash does not match report")
        return self

    def require_publishable(self, release_id: str) -> None:
        """Block publication on unexpected changes or missing automated evidence."""
        if self.candidate_kb_release_id != release_id:
            raise ValueError("impact report targets another KB release")
        failed = [item.case_id for item in self.diffs if not item.passed]
        if failed:
            raise ValueError(f"recommendation impact regressions unresolved: {failed}")
        required = {"impact_diff", "schema", "provenance"}
        if not required.issubset(self.deterministic_evidence_hashes):
            raise ValueError("recommendation impact report lacks deterministic gate evidence")
        if self.generative_verdict != "pass":
            raise ValueError("recommendation impact generative quality gate did not pass")
