# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic, inspectable CBR hard filtering and retrieval."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from ruler.cbr.contracts import (
    CBRCaseRecord,
    CaseFeature,
    ComparisonPolicy,
    ExclusionReason,
    FeatureContribution,
    FeatureDefinition,
    HardFilter,
    Missingness,
    RetrievalRequest,
    RetrievalResult,
    RetrievedCase,
    SimilarityProfile,
)
from ruler.cbr.registry import FeatureRegistry


def _raw(feature: CaseFeature) -> Any:
    return feature.value.value if feature.value else None


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    quarter = re.fullmatch(r"(\d{4})-Q([1-4])", text)
    if quarter:
        return date(int(quarter.group(1)), (int(quarter.group(2)) - 1) * 3 + 1, 1)
    month = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if month:
        return date(int(month.group(1)), int(month.group(2)), 1)
    return date.fromisoformat(text)


def _set(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("set comparator requires a sequence")
    return {str(item) for item in value}


def _version(value: Any) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value))
    if not parts:
        raise ValueError("version comparator requires numeric version components")
    return tuple(int(item) for item in parts)


def _taxonomy_distance(left: str, right: str, parents: dict[str, str | None]) -> float:
    def ancestry(item: str) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        while item not in seen:
            result.append(item)
            seen.add(item)
            parent = parents.get(item)
            if parent is None:
                break
            item = parent
        return result

    a, b = ancestry(left), ancestry(right)
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    distance = min(a.index(item) + b.index(item) for item in shared)
    return 1 / (1 + distance)


def compare_features(
    query: CaseFeature, candidate: CaseFeature, definition: FeatureDefinition
) -> tuple[float, str]:
    """Compare two observed features using their registry-declared policy."""
    if query.missingness != Missingness.OBSERVED or candidate.missingness != Missingness.OBSERVED:
        raise ValueError("only observed features can be compared")
    assert query.value is not None and candidate.value is not None
    if query.value.value_type != candidate.value.value_type:
        raise ValueError("comparison requires matching typed-value declarations")
    if query.value.unit != candidate.value.unit:
        raise ValueError("comparison requires matching units")
    left, right = _raw(query), _raw(candidate)
    policy = definition.comparison_policy
    if policy == ComparisonPolicy.CATEGORICAL:
        similarity = float(left == right)
    elif policy == ComparisonPolicy.ORDINAL:
        try:
            distance = abs(
                definition.ordinal_values.index(str(left))
                - definition.ordinal_values.index(str(right))
            )
        except ValueError as exc:
            raise ValueError(f"{definition.feature_id}: value outside ordinal vocabulary") from exc
        similarity = 1 - distance / max(1, len(definition.ordinal_values) - 1)
    elif policy == ComparisonPolicy.NUMERIC_RANGE:
        assert definition.numeric_range is not None
        if (
            isinstance(left, bool)
            or isinstance(right, bool)
            or not isinstance(left, (int, float))
            or not isinstance(right, (int, float))
        ):
            raise ValueError("numeric range comparator requires numeric non-boolean values")
        span = definition.numeric_range[1] - definition.numeric_range[0]
        similarity = max(0.0, 1 - abs(float(left) - float(right)) / span)
    elif policy == ComparisonPolicy.SET:
        a, b = _set(left), _set(right)
        similarity = len(a & b) / len(a | b) if a | b else 1.0
    elif policy == ComparisonPolicy.TEMPORAL:
        days = abs((_as_date(left) - _as_date(right)).days)
        similarity = 1 / (1 + days / 30)
    elif policy == ComparisonPolicy.TAXONOMY:
        similarity = _taxonomy_distance(str(left), str(right), definition.taxonomy_parents)
    elif policy == ComparisonPolicy.VERSION:
        a, b = _version(left), _version(right)
        if a[0] != b[0]:
            similarity = 0.0
        else:
            length = max(len(a), len(b))
            padded_a, padded_b = a + (0,) * (length - len(a)), b + (0,) * (length - len(b))
            similarity = 1 / (1 + sum(abs(x - y) for x, y in zip(padded_a[1:], padded_b[1:])))
    else:
        raise ValueError(f"{definition.feature_id}: feature is not comparable")
    similarity = min(1.0, max(0.0, similarity))
    return similarity, f"{policy.value}: similarity={similarity:.6f}"


def evaluate_hard_filters(
    query: CBRCaseRecord,
    candidate: CBRCaseRecord,
    filters: tuple[HardFilter, ...],
    *,
    authorized_fields: frozenset[str],
    weighted_fields: frozenset[str],
) -> tuple[tuple[str, ...], tuple[ExclusionReason, ...]]:
    matched: list[str] = []
    excluded: list[ExclusionReason] = []
    for item in filters:
        ok, code, explanation = True, "matched", "compatible"
        if item.kind == "case_kind":
            ok = query.case_kind == candidate.case_kind
            code, explanation = "case_kind_mismatch", "candidate has another case kind"
        elif item.kind == "domain":
            ok = query.domain_id == candidate.domain_id
            code, explanation = "domain_mismatch", "candidate belongs to another domain"
        elif item.kind == "jurisdiction":
            ok = bool(set(query.jurisdictions) & set(candidate.jurisdictions))
            code, explanation = "jurisdiction_mismatch", "no shared jurisdiction"
        elif item.kind == "rule_release":
            ok = (
                query.rule_release_id == candidate.rule_release_id
                and query.rule_release_sha256 == candidate.rule_release_sha256
            )
            code, explanation = "rule_release_mismatch", "candidate used another rule release"
        elif item.kind == "temporal":
            age = (query.as_of_date - candidate.as_of_date).days
            ok = age >= 0 and (item.max_age_days is None or age <= item.max_age_days)
            code = "future_or_stale_case"
            explanation = "candidate is future-dated or outside the configured lookback"
        elif item.kind == "access":
            ok = weighted_fields <= authorized_fields
            code, explanation = "field_access_denied", "ranking would require an unauthorized field"
        elif item.kind == "feature":
            assert item.feature_id is not None
            query_feature = query.feature_map().get(item.feature_id)
            candidate_feature = candidate.feature_map().get(item.feature_id)
            ok = bool(
                query_feature
                and candidate_feature
                and query_feature.missingness == Missingness.OBSERVED
                and candidate_feature.missingness == Missingness.OBSERVED
                and _raw(query_feature) == _raw(candidate_feature)
            )
            code = "hard_feature_mismatch"
            explanation = f"candidate differs on required feature {item.feature_id}"
        if ok:
            matched.append(item.filter_id)
        elif item.required:
            excluded.append(
                ExclusionReason(filter_id=item.filter_id, code=code, explanation=explanation)
            )
    return tuple(matched), tuple(excluded)


class CaseRetriever:
    """Retrieve stable top-k precedents; hard-incompatible cases never receive a score."""

    def __init__(self, registry: FeatureRegistry, profile: SimilarityProfile) -> None:
        registry.validate_profile(profile)
        self.registry = registry
        self.profile = profile

    def _score(
        self, query: CBRCaseRecord, candidate: CBRCaseRecord
    ) -> tuple[float, tuple[FeatureContribution, ...], tuple[str, ...], float]:
        query_features, candidate_features = query.feature_map(), candidate.feature_map()
        contributions: list[FeatureContribution] = []
        differences: list[str] = []
        weighted_ids = {item.feature_id for item in self.profile.feature_weights}
        weighted_features = [item for item in candidate.features if item.feature_id in weighted_ids]
        completeness = sum(
            item.missingness == Missingness.OBSERVED for item in weighted_features
        ) / max(1, len(weighted_ids))
        score = 0.0
        for weighted in self.profile.feature_weights:
            definition = self.registry.require(weighted.feature_id)
            q = query_features.get(weighted.feature_id)
            c = candidate_features.get(weighted.feature_id)
            q_missing = q.missingness if q else Missingness.UNKNOWN
            c_missing = c.missingness if c else Missingness.UNKNOWN
            if q_missing != Missingness.OBSERVED or c_missing != Missingness.OBSERVED:
                if definition.missing_behavior == "exclude":
                    raise ValueError(f"required comparison feature missing: {weighted.feature_id}")
                contribution = (
                    weighted.weight * self.profile.missing_penalty
                    if definition.missing_behavior == "penalize"
                    else 0.0
                )
                similarity = (
                    self.profile.missing_penalty
                    if definition.missing_behavior == "penalize"
                    else None
                )
                explanation = f"missing handled as {definition.missing_behavior}; query={q_missing.value}, candidate={c_missing.value}"
                differences.append(f"{weighted.feature_id}: {q_missing.value}/{c_missing.value}")
            else:
                assert q is not None and c is not None
                similarity, explanation = compare_features(q, c, definition)
                contribution = weighted.weight * similarity
                if not math.isclose(similarity, 1.0):
                    differences.append(
                        f"{weighted.feature_id}: material similarity {similarity:.3f}"
                    )
            score += contribution
            contributions.append(
                FeatureContribution(
                    feature_id=weighted.feature_id,
                    similarity=similarity,
                    weighted_contribution=contribution,
                    query_missingness=q_missing,
                    candidate_missingness=c_missing,
                    explanation=explanation,
                )
            )
        return score, tuple(contributions), tuple(differences), completeness

    def retrieve(
        self, request: RetrievalRequest, candidates: tuple[CBRCaseRecord, ...]
    ) -> RetrievalResult:
        if request.similarity_profile_sha256 != self.profile.sha256():
            raise ValueError("request does not pin this similarity profile")
        if (
            request.query_case.domain_id != self.profile.domain_id
            or request.query_case.case_kind != self.profile.case_kind
        ):
            raise ValueError("query case does not match the profile domain and case kind")
        if (
            request.query_case.rule_release_id != request.rule_release_id
            or request.query_case.rule_release_sha256 != request.rule_release_sha256
        ):
            raise ValueError("query case and retrieval request pin different rule releases")
        if request.case_library_release_id != request.query_case.case_library_release_id:
            raise ValueError("query does not pin the requested case-library release")
        if request.case_library_release_sha256 != request.query_case.case_library_release_sha256:
            raise ValueError("query and request pin different case-library release digests")
        self.registry.validate_case(request.query_case)
        limit = min(request.maximum_candidates, self.profile.maximum_candidate_pool)
        weighted = frozenset(item.feature_id for item in self.profile.feature_weights)
        usable: list[
            tuple[
                CBRCaseRecord,
                float,
                tuple[FeatureContribution, ...],
                tuple[str, ...],
                tuple[str, ...],
            ]
        ] = []
        excluded: list[tuple[float, RetrievedCase]] = []
        considered = sorted(candidates, key=lambda item: item.case_id)[:limit]
        for candidate in considered:
            self.registry.validate_case(candidate)
            if candidate.case_id == request.query_case.case_id:
                continue
            matched, mismatched = evaluate_hard_filters(
                request.query_case,
                candidate,
                self.profile.hard_filters,
                authorized_fields=request.authorized_fields,
                weighted_fields=weighted,
            )
            if (
                candidate.case_library_release_id != request.case_library_release_id
                or candidate.case_library_release_sha256 != request.case_library_release_sha256
            ):
                mismatched += (
                    ExclusionReason(
                        filter_id="case_library_release",
                        code="case_library_release_mismatch",
                        explanation="candidate is outside the pinned case-library release",
                    ),
                )
            try:
                score, contributions, differences, completeness = self._score(
                    request.query_case, candidate
                )
            except ValueError as exc:
                mismatched += (
                    ExclusionReason(
                        filter_id="feature_completeness",
                        code="required_feature_missing",
                        explanation=str(exc),
                    ),
                )
                score, contributions, differences, completeness = 0.0, (), (), 0.0
            if completeness < self.profile.minimum_evidence_completeness:
                mismatched += (
                    ExclusionReason(
                        filter_id="evidence_completeness",
                        code="insufficient_evidence",
                        explanation="candidate evidence completeness is below the profile threshold",
                    ),
                )
            redacted = (
                tuple(sorted(weighted - request.authorized_fields))
                if request.authorized_fields
                else ()
            )
            if mismatched:
                excluded.append(
                    (
                        score,
                        RetrievedCase(
                            case_id=candidate.case_id,
                            score=0,
                            contributions=contributions,
                            matched_hard_filters=matched,
                            mismatched_hard_filters=mismatched,
                            material_differences=differences,
                            redacted_fields=redacted,
                            eligibility="excluded",
                        ),
                    )
                )
            else:
                usable.append((candidate, score, contributions, differences, matched))
        usable.sort(key=lambda item: (-item[1], item[0].case_id))
        selected: list[RetrievedCase] = []
        diversity_counts: dict[str, int] = {}
        top_k = min(request.top_k, self.profile.maximum_top_k)
        diversity_feature = self.profile.diversity.feature_id
        for candidate, score, contributions, differences, matched in usable:
            if diversity_feature:
                feature = candidate.feature_map().get(diversity_feature)
                key = repr(_raw(feature)) if feature else "<missing>"
                if diversity_counts.get(key, 0) >= self.profile.diversity.max_per_value:
                    continue
                diversity_counts[key] = diversity_counts.get(key, 0) + 1
            selected.append(
                RetrievedCase(
                    case_id=candidate.case_id,
                    rank=len(selected) + 1,
                    score=min(1.0, score),
                    contributions=contributions,
                    matched_hard_filters=matched,
                    material_differences=differences,
                    eligibility="usable",
                )
            )
            if len(selected) == top_k:
                break
        excluded.sort(key=lambda item: (-item[0], item[1].case_id))
        contrast = (
            excluded[0][1].model_copy(update={"eligibility": "contrast_only"})
            if excluded and self.profile.require_contrast
            else None
        )
        return RetrievalResult(
            request_id=request.request_id,
            profile_sha256=self.profile.sha256(),
            retrieved=tuple(selected),
            excluded_contrast=contrast,
            candidate_count=len(considered),
            trace=(
                f"hard_filters={len(self.profile.hard_filters)}",
                f"scored_eligible={len(usable)}",
                f"selected={len(selected)}",
            ),
        )


def compare_cases(
    query: CBRCaseRecord,
    candidate: CBRCaseRecord,
    registry: FeatureRegistry,
    profile: SimilarityProfile,
) -> tuple[FeatureContribution, ...]:
    retriever = CaseRetriever(registry, profile)
    return retriever._score(query, candidate)[1]
