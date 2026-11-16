# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Fail-closed capability router for semantics-preserving backend selection."""

from __future__ import annotations

from ruler.assurance.contracts import BackendProfile, ProjectionPolicy, ReasoningQuery


class BackendRouter:
    def __init__(self, profiles: tuple[BackendProfile, ...]) -> None:
        ids = [item.backend_id for item in profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("backend profile IDs must be unique")
        self._profiles = {item.backend_id: item for item in profiles}

    def route(
        self,
        query: ReasoningQuery,
        policies: tuple[ProjectionPolicy, ...],
    ) -> tuple[BackendProfile, ...]:
        policy_by_backend, eligible = self.initialize_scan(policies)
        for profile in self._profiles.values():
            self.scan_profile(query, profile, policy_by_backend, eligible)
        return self.finish_route(query, eligible)

    @staticmethod
    def initialize_scan(
        policies: tuple[ProjectionPolicy, ...],
    ) -> tuple[dict[str, ProjectionPolicy], list[BackendProfile]]:
        """Build the last-policy-wins index before traversing any profiles."""
        policy_by_backend = {item.target_backend_id: item for item in policies}
        return policy_by_backend, []

    @staticmethod
    def scan_profile(
        query: ReasoningQuery,
        profile: BackendProfile,
        policy_by_backend: dict[str, ProjectionPolicy],
        eligible: list[BackendProfile],
    ) -> None:
        """Consume one profile, preserving the native eligibility check order."""
        policy = policy_by_backend.get(profile.backend_id)
        if (
            profile.native_execution != "unavailable"
            and query.required_capabilities.issubset(profile.capabilities)
            and policy is not None
            and policy.executable
        ):
            eligible.append(profile)

    @staticmethod
    def finish_route(
        query: ReasoningQuery, eligible: list[BackendProfile]
    ) -> tuple[BackendProfile, ...]:
        """Fail closed on no match, otherwise return profiles in backend ID order."""
        if not eligible:
            raise LookupError(
                f"no semantics-preserving backend for query {query.query_id!r}; "
                "missing capability, executable profile, or non-lossy projection policy"
            )
        return tuple(sorted(eligible, key=lambda item: item.backend_id))
