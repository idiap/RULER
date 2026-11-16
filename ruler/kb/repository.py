# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Typed immutable KB repository, coherence checks, and scoped projections."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ruler.ingestion.contracts import (
    AutomatedGateEvidence,
    FormalElementAnnotation,
    KBReleaseManifest,
    canonical_sha256,
    stable_id,
)
from ruler.schemas import SourceRecord


class ReleasedAssertion(BaseModel):
    """One canonical approved assertion indexed by an immutable KB release."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    assertion_id: str
    semantic_key: str
    assertion_kind: Literal[
        "feature",
        "clause",
        "rule",
        "definition",
        "condition",
        "exclusion",
        "exception",
        "limit",
        "precedence",
    ]
    provider: str
    product_family: str
    product_id: str
    jurisdiction: str
    customer_segments: tuple[str, ...] = ()
    option_ids: tuple[str, ...] = ()
    option_group_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    option_group_required: bool = Field(default=False, exclude_if=lambda value: not value)
    option_group_product_ids: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    dependency_only: bool = Field(default=False, exclude_if=lambda value: not value)
    effective_from: date | None = None
    effective_to: date | None = None
    dependencies: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    precedes: tuple[str, ...] = ()
    source_version_ids: tuple[str, ...] = Field(min_length=1)
    annotation_id: str
    payload: dict[str, Any]
    payload_sha256: str

    @model_validator(mode="after")
    def content_hash_matches(self) -> "ReleasedAssertion":
        """Verify assertion payload integrity and temporal interval ordering."""
        if canonical_sha256(self.payload) != self.payload_sha256:
            raise ValueError("payload_sha256 does not match assertion payload")
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from must not follow effective_to")
        if self.option_group_required and self.option_group_id is None:
            raise ValueError("option_group_required requires option_group_id")
        if self.option_group_id is not None and len(self.option_ids) != 1:
            raise ValueError("option-group assertions require exactly one option_id")
        if self.option_group_product_ids and self.option_group_id is None:
            raise ValueError("option_group_product_ids requires option_group_id")
        return self


class ProjectionRequest(BaseModel):
    """Bounded selection scope for one reasoning case."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    product_family: str
    provider: str | None = None
    product_ids: tuple[str, ...] = ()
    jurisdiction: str
    customer_segment: str | None = None
    effective_on: date
    option_ids: tuple[str, ...] = ()
    assertion_ids: tuple[str, ...] = ()

    @field_validator("product_ids", "option_ids", "assertion_ids")
    @classmethod
    def canonicalize_set_like_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Make semantically set-like request fields order/duplicate invariant."""
        return tuple(sorted(set(values)))


class ProjectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    assertion_id: str
    included: bool
    reason: str


class RuntimeProjection(BaseModel):
    """Deterministic dependency-closed subset of an immutable release."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    projection_id: str
    kb_release_id: str
    request: ProjectionRequest
    assertion_ids: tuple[str, ...]
    annotation_ids: tuple[str, ...]
    source_version_ids: tuple[str, ...]
    decisions: tuple[ProjectionDecision, ...]

    @model_validator(mode="after")
    def deterministic_identity(self) -> "RuntimeProjection":
        """Bind a runtime projection to its release, scope, and dependency closure."""
        expected = stable_id(
            "kb_projection",
            {
                "kb_release_id": self.kb_release_id,
                "request": self.request.model_dump(mode="json"),
                "assertion_ids": self.assertion_ids,
                "annotation_ids": self.annotation_ids,
                "source_version_ids": self.source_version_ids,
            },
        )
        if self.projection_id != expected:
            raise ValueError("projection_id does not match projection contents")
        return self


class CoherenceIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    assertion_ids: tuple[str, ...]
    message: str


class CoherenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kb_release_id: str
    issues: tuple[CoherenceIssue, ...]

    @property
    def coherent(self) -> bool:
        """Return true when no structural or semantic release issue remains."""
        return not self.issues


class KnowledgeRepository:
    """Read-only index over one published, hash-pinned KB release."""

    def __init__(
        self,
        release: KBReleaseManifest,
        assertions: list[ReleasedAssertion],
        annotations: list[FormalElementAnnotation],
        source_records: list[SourceRecord] | None = None,
        automated_gates: list[AutomatedGateEvidence] | None = None,
    ) -> None:
        if release.release_status != "published":
            raise ValueError("reasoning repositories require a published release")
        self.release = release
        self.assertions = {item.assertion_id: item for item in assertions}
        self.annotations = {item.annotation_id: item for item in annotations}
        self.source_records = {item.source_id: item for item in (source_records or [])}
        self.automated_gates = {item.gate_evidence_id: item for item in (automated_gates or [])}
        if len(self.assertions) != len(assertions):
            raise ValueError("duplicate assertion IDs")
        if len(self.annotations) != len(annotations):
            raise ValueError("duplicate annotation IDs")
        if source_records is not None and len(self.source_records) != len(source_records):
            raise ValueError("duplicate source record IDs")
        if automated_gates is not None and len(self.automated_gates) != len(automated_gates):
            raise ValueError("duplicate automated gate IDs")
        self._validate_release_bindings()

    def _validate_release_bindings(self) -> None:
        missing_assertions = set(self.release.formal_record_hashes) - self.assertions.keys()
        if missing_assertions:
            raise ValueError(f"release assertions not loaded: {sorted(missing_assertions)}")
        missing_annotations = set(self.release.annotation_hashes) - self.annotations.keys()
        if missing_annotations:
            raise ValueError(f"release annotations not loaded: {sorted(missing_annotations)}")
        for assertion in self.assertions.values():
            expected = self.release.formal_record_hashes.get(assertion.assertion_id)
            if expected is None:
                raise ValueError(f"assertion absent from release: {assertion.assertion_id}")
            if expected != canonical_sha256(assertion.model_dump(mode="json")):
                raise ValueError(f"release assertion hash mismatch: {assertion.assertion_id}")
            if assertion.annotation_id not in self.annotations:
                raise ValueError(f"assertion lacks annotation: {assertion.assertion_id}")
            if assertion.annotation_id not in self.release.annotation_hashes:
                raise ValueError(f"annotation absent from release: {assertion.annotation_id}")
            annotation = self.annotations[assertion.annotation_id]
            expected_annotation_hash = self.release.annotation_hashes[assertion.annotation_id]
            if expected_annotation_hash != canonical_sha256(annotation.model_dump(mode="json")):
                raise ValueError(f"release annotation hash mismatch: {assertion.annotation_id}")
            if annotation.formal_element_id != assertion.assertion_id:
                raise ValueError(f"annotation targets another assertion: {assertion.assertion_id}")
            if annotation.semantic_sha256 != assertion.payload_sha256:
                raise ValueError(f"annotation semantic hash mismatch: {assertion.assertion_id}")
            for source_id in assertion.source_version_ids:
                if source_id not in self.release.source_version_hashes:
                    raise ValueError(f"source absent from release: {source_id}")
        if self.source_records:
            missing_sources = set(self.release.source_version_hashes) - self.source_records.keys()
            if missing_sources:
                raise ValueError(f"release source records not loaded: {sorted(missing_sources)}")
            for source_id, source in self.source_records.items():
                expected = self.release.source_version_hashes.get(source_id)
                if expected is None:
                    raise ValueError(f"source record absent from release: {source_id}")
                if source.raw_sha256 != expected:
                    raise ValueError(f"release source hash mismatch: {source_id}")
        if self.automated_gates:
            missing_gates = set(self.release.automated_gate_hashes) - self.automated_gates.keys()
            if missing_gates:
                raise ValueError(f"release automated gates not loaded: {sorted(missing_gates)}")
            for gate_id, gate in self.automated_gates.items():
                expected = self.release.automated_gate_hashes.get(gate_id)
                if expected != canonical_sha256(gate.model_dump(mode="json")):
                    raise ValueError(f"release automated gate hash mismatch: {gate_id}")
                assertion = self.assertions.get(gate.formal_element_id)
                if assertion is None or gate.semantic_sha256 != assertion.payload_sha256:
                    raise ValueError(f"automated gate targets different semantics: {gate_id}")
                if not gate.passed:
                    raise ValueError(f"automated gate did not pass: {gate_id}")

    def require_coherent(self) -> CoherenceReport:
        """Return the report or reject a release that is unsafe for runtime use."""
        report = self.coherence_report()
        if report.issues:
            summary = "; ".join(
                f"{item.code}:{','.join(item.assertion_ids)}" for item in report.issues
            )
            raise ValueError(f"incoherent KB release: {summary}")
        return report

    def coherence_report(self) -> CoherenceReport:
        """Detect duplicates, dangling links, cycles, contradictions, and edition overlap."""
        issues: list[CoherenceIssue] = []
        by_semantic_key: dict[str, list[str]] = defaultdict(list)
        for assertion in self.assertions.values():
            by_semantic_key[assertion.semantic_key].append(assertion.assertion_id)
            for dependency in assertion.dependencies:
                if dependency not in self.assertions:
                    issues.append(
                        CoherenceIssue(
                            code="KB_DANGLING_DEPENDENCY",
                            assertion_ids=(assertion.assertion_id,),
                            message=f"unknown dependency {dependency}",
                        )
                    )
            for target in (*assertion.contradicts, *assertion.precedes):
                if target not in self.assertions:
                    issues.append(
                        CoherenceIssue(
                            code="KB_DANGLING_RELATION",
                            assertion_ids=(assertion.assertion_id,),
                            message=f"unknown related assertion {target}",
                        )
                    )
        for key, ids in by_semantic_key.items():
            if len(ids) > 1:
                issues.append(
                    CoherenceIssue(
                        code="KB_DUPLICATE_SEMANTIC_KEY",
                        assertion_ids=tuple(sorted(ids)),
                        message=f"duplicate canonical semantic key {key}",
                    )
                )
        contradiction_pairs = {
            tuple(sorted((assertion.assertion_id, target_id)))
            for assertion in self.assertions.values()
            for target_id in assertion.contradicts
            if target_id in self.assertions and target_id != assertion.assertion_id
        }
        for left_id, right_id in sorted(contradiction_pairs):
            assertion = self.assertions[left_id]
            target = self.assertions[right_id]
            resolved = right_id in assertion.precedes or left_id in target.precedes
            if not resolved and _scopes_overlap(assertion, target):
                issues.append(
                    CoherenceIssue(
                        code="KB_UNRESOLVED_CONTRADICTION",
                        assertion_ids=(left_id, right_id),
                        message="overlapping contradictory assertions lack precedence",
                    )
                )
        issues.extend(_dependency_cycle_issues(self.assertions))
        return CoherenceReport(
            kb_release_id=self.release.kb_release_id,
            issues=tuple(sorted(issues, key=lambda item: (item.code, item.assertion_ids))),
        )

    def project(self, request: ProjectionRequest) -> RuntimeProjection:
        """Select matching roots, then include their complete dependency closure."""

        roots: set[str] = set(request.assertion_ids)
        unknown_roots = roots - self.assertions.keys()
        if unknown_roots:
            raise ValueError(f"unknown requested assertions: {sorted(unknown_roots)}")
        dependency_only_roots = sorted(
            assertion_id for assertion_id in roots if self.assertions[assertion_id].dependency_only
        )
        if dependency_only_roots:
            raise ValueError(
                "dependency-only assertions cannot be requested explicitly: "
                f"{dependency_only_roots}"
            )
        self._validate_option_groups(request)
        for assertion in self.assertions.values():
            if _matches_request(assertion, request):
                roots.add(assertion.assertion_id)

        included: set[str] = set()
        queue = deque(sorted(roots))
        while queue:
            assertion_id = queue.popleft()
            if assertion_id in included:
                continue
            included.add(assertion_id)
            assertion = self.assertions[assertion_id]
            for dependency in assertion.dependencies:
                if dependency not in self.assertions:
                    raise ValueError(f"projection has dangling dependency {dependency}")
                queue.append(dependency)

        assertion_ids = tuple(sorted(included))
        annotation_ids = tuple(sorted({self.assertions[item].annotation_id for item in included}))
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for item in included
                    for source_id in self.assertions[item].source_version_ids
                }
            )
        )
        decisions = tuple(
            ProjectionDecision(
                assertion_id=assertion_id,
                included=assertion_id in included,
                reason=(
                    "scope_match"
                    if assertion_id in roots
                    else "dependency" if assertion_id in included else "outside_scope"
                ),
            )
            for assertion_id in sorted(self.assertions)
        )
        identity_payload = {
            "kb_release_id": self.release.kb_release_id,
            "request": request.model_dump(mode="json"),
            "assertion_ids": assertion_ids,
            "annotation_ids": annotation_ids,
            "source_version_ids": source_ids,
        }
        return RuntimeProjection(
            projection_id=stable_id("kb_projection", identity_payload),
            kb_release_id=self.release.kb_release_id,
            request=request,
            assertion_ids=assertion_ids,
            annotation_ids=annotation_ids,
            source_version_ids=source_ids,
            decisions=decisions,
        )

    def _validate_option_groups(self, request: ProjectionRequest) -> None:
        """Enforce exclusive option groups that are relevant to the request scope."""
        groups: dict[str, dict[str, Any]] = {}
        for assertion in self.assertions.values():
            if assertion.option_group_id is None or not _matches_option_group_scope(
                assertion, request
            ):
                continue
            group = groups.setdefault(
                assertion.option_group_id,
                {"members": set(), "required": False},
            )
            group["members"].update(assertion.option_ids)
            group["required"] = group["required"] or assertion.option_group_required

        for group_id, group in sorted(groups.items()):
            selected = sorted(set(request.option_ids) & group["members"])
            if len(selected) > 1:
                raise ValueError(
                    f"option group {group_id} is mutually exclusive; selected: {selected}"
                )
            if group["required"] and not selected:
                raise ValueError(f"option group {group_id} requires exactly one selection")


def _matches_request(assertion: ReleasedAssertion, request: ProjectionRequest) -> bool:
    if assertion.dependency_only:
        return False
    scope_matches = (
        _matches_option_group_scope(assertion, request)
        if assertion.option_group_id is not None
        else _matches_base_scope(assertion, request)
    )
    if not scope_matches:
        return False
    if assertion.option_ids and not set(assertion.option_ids).issubset(request.option_ids):
        return False
    return True


def _matches_base_scope(assertion: ReleasedAssertion, request: ProjectionRequest) -> bool:
    """Match request scope without considering option selection."""
    if assertion.product_family != request.product_family:
        return False
    if assertion.jurisdiction != request.jurisdiction:
        return False
    if request.provider and assertion.provider != request.provider:
        return False
    if request.product_ids and assertion.product_id not in request.product_ids:
        return False
    if request.customer_segment and assertion.customer_segments:
        if request.customer_segment not in assertion.customer_segments:
            return False
    if assertion.effective_from and request.effective_on < assertion.effective_from:
        return False
    if assertion.effective_to and request.effective_on > assertion.effective_to:
        return False
    return True


def _matches_option_group_scope(assertion: ReleasedAssertion, request: ProjectionRequest) -> bool:
    """Match group scope using declared product aliases when they are available."""
    if not _matches_base_scope(assertion, request.model_copy(update={"product_ids": ()})):
        return False
    product_ids = assertion.option_group_product_ids or (assertion.product_id,)
    return not request.product_ids or bool(set(product_ids) & set(request.product_ids))


def _scopes_overlap(left: ReleasedAssertion, right: ReleasedAssertion) -> bool:
    if (left.provider, left.product_family, left.product_id, left.jurisdiction) != (
        right.provider,
        right.product_family,
        right.product_id,
        right.jurisdiction,
    ):
        return False
    left_start = left.effective_from or date.min
    left_end = left.effective_to or date.max
    right_start = right.effective_from or date.min
    right_end = right.effective_to or date.max
    return left_start <= right_end and right_start <= left_end


def _dependency_cycle_issues(
    assertions: dict[str, ReleasedAssertion],
) -> list[CoherenceIssue]:
    visiting: set[str] = set()
    visited: set[str] = set()
    issues: list[CoherenceIssue] = []

    def visit(assertion_id: str, path: tuple[str, ...]) -> None:
        """Depth-first walk used to report dependency cycles with their exact path."""
        if assertion_id in visiting:
            start = path.index(assertion_id)
            cycle = path[start:] + (assertion_id,)
            issues.append(
                CoherenceIssue(
                    code="KB_DEPENDENCY_CYCLE",
                    assertion_ids=cycle,
                    message="dependency cycle prevents a finite projection closure",
                )
            )
            return
        if assertion_id in visited:
            return
        visiting.add(assertion_id)
        assertion = assertions[assertion_id]
        for dependency in assertion.dependencies:
            if dependency in assertions:
                visit(dependency, path + (assertion_id,))
        visiting.remove(assertion_id)
        visited.add(assertion_id)

    for assertion_id in sorted(assertions):
        visit(assertion_id, ())
    return issues
