# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-owned declarations for comparable CBR features."""

from __future__ import annotations

from ruler.cbr.contracts import CBRCaseRecord, FeatureDefinition, SimilarityProfile


class FeatureRegistry:
    def __init__(self, *, domain_id: str, definitions: tuple[FeatureDefinition, ...]) -> None:
        self.domain_id = domain_id
        self._definitions = {item.feature_id: item for item in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("feature definitions must have unique IDs")

    def require(self, feature_id: str) -> FeatureDefinition:
        try:
            return self._definitions[feature_id]
        except KeyError as exc:
            raise ValueError(f"undeclared feature: {feature_id}") from exc

    def validate_case(self, case: CBRCaseRecord) -> None:
        if case.domain_id != self.domain_id:
            raise ValueError(f"case domain {case.domain_id!r} does not match {self.domain_id!r}")
        for feature in case.features:
            definition = self.require(feature.feature_id)
            if feature.comparison_policy != definition.comparison_policy:
                raise ValueError(f"{feature.feature_id}: comparison policy differs from registry")
            if feature.value and feature.value.value_type != definition.value_type:
                raise ValueError(
                    f"{feature.feature_id}: expected value type {definition.value_type}"
                )

    def validate_profile(self, profile: SimilarityProfile) -> None:
        if profile.domain_id != self.domain_id:
            raise ValueError("profile domain does not match registry")
        for weight in profile.feature_weights:
            definition = self.require(weight.feature_id)
            if definition.comparison_policy.value == "non_comparable":
                raise ValueError(f"{weight.feature_id}: non-comparable features cannot be ranked")
            if definition.sensitivity == "restricted":
                raise ValueError(
                    f"{weight.feature_id}: restricted features cannot become ranking proxies"
                )

    @property
    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))
