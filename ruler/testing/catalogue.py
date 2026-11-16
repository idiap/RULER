# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Versioned test-catalogue contracts and coverage validation.

The catalogue is intentionally independent of pytest collection.  It describes
which policy/control risk a case owns; pytest remains the executable mechanism.
That separation prevents line coverage from being mistaken for semantic coverage.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ruler.io import read_yaml
from ruler.paths import REPO_ROOT

CATALOGUE_FILE = REPO_ROOT / "tests" / "catalogue.yaml"
CASE_ID = re.compile(r"^TC-[A-Z0-9]+-[0-9]{3}$")
CONTROL_ID = re.compile(r"^(?:TST|ING|CAT|SRC|EXT|FOR|KB|OPS|ROL|WF)-[0-9]{3}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class FixtureRef(BaseModel):
    """A fixture whose bytes are independently committed and hash-locked."""

    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str
    oracle_authorship: Literal["independent", "source_evidence"]

    @field_validator("sha256")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        """Require an explicit lowercase SHA-256 digest for every fixture."""
        if not SHA256.fullmatch(value):
            raise ValueError("must use sha256:<64 lowercase hex> form")
        return value


class TestCaseRecord(BaseModel):
    """One stable deterministic or generative test/evaluation case."""

    model_config = ConfigDict(extra="forbid")
    case_id: str
    title: str
    owner: str
    controls: list[str] = Field(min_length=1)
    risk_class: Literal["critical", "high", "medium", "low"]
    lifecycle_stage: str
    engine: Literal["deterministic", "generative"]
    oracle_type: Literal["exact", "invariant", "differential", "rubric"]
    fixtures: list[FixtureRef] = Field(default_factory=list)
    expected_assertions: list[str] = Field(min_length=1)
    output_schema: str
    timeout_seconds: int = Field(gt=0, le=3600)
    retries: int = Field(ge=0, le=3)
    budget: str
    cache_policy: Literal["disabled", "exact-input-digest"]
    run_profiles: list[Literal["local", "pr", "integration", "release", "scheduled"]]
    retention_days: int = Field(gt=0)
    blocking_tier: Literal["advisory", "pr", "integration", "release"]
    coverage_modes: list[Literal["positive", "negative", "boundary", "stale_drift", "recovery"]]
    expires_on: str | None = None

    @field_validator("case_id")
    @classmethod
    def valid_case_id(cls, value: str) -> str:
        """Keep test identifiers stable and machine-indexable."""
        if not CASE_ID.fullmatch(value):
            raise ValueError("must match TC-<AREA>-NNN")
        return value

    @field_validator("controls")
    @classmethod
    def valid_controls(cls, values: list[str]) -> list[str]:
        """Reject test cases mapped to malformed or undeclared control families."""
        unknown = [value for value in values if not CONTROL_ID.fullmatch(value)]
        if unknown:
            raise ValueError(f"invalid control IDs: {unknown}")
        return values


class TestCatalogue(BaseModel):
    """Root versioned catalogue with explicit P0 coverage requirements."""

    model_config = ConfigDict(extra="forbid")
    catalogue_id: str
    version: str
    owners: list[str] = Field(min_length=1)
    known_controls: list[str] = Field(min_length=1)
    required_p0_controls: list[str] = Field(min_length=1)
    required_semantic_categories: list[str] = Field(min_length=1)
    cases: list[TestCaseRecord] = Field(min_length=1)


class CatalogueIssue(BaseModel):
    """Stable machine-readable catalogue validation finding."""

    model_config = ConfigDict(extra="forbid")
    code: str
    path: str
    message: str


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def validate_catalogue_payload(payload: object, *, root: Path = REPO_ROOT) -> list[CatalogueIssue]:
    """Validate catalogue structure, references, hashes, ownership, and P0 coverage."""
    try:
        catalogue = TestCatalogue.model_validate(payload)
    except ValidationError as exc:
        return [
            CatalogueIssue(
                code="TESTCAT_SCHEMA_INVALID",
                path=".".join(str(part) for part in error["loc"]),
                message=error["msg"],
            )
            for error in exc.errors()
        ]

    issues: list[CatalogueIssue] = []
    known_controls = set(catalogue.known_controls)
    for control in catalogue.required_p0_controls:
        if control not in known_controls:
            issues.append(
                CatalogueIssue(
                    code="TESTCAT_UNKNOWN_CONTROL", path="required_p0_controls", message=control
                )
            )
    case_ids: set[str] = set()
    referenced_fixture_paths: set[str] = set()
    for index, case in enumerate(catalogue.cases):
        prefix = f"cases[{index}]"
        if case.case_id in case_ids:
            issues.append(
                CatalogueIssue(
                    code="TESTCAT_DUPLICATE_CASE", path=f"{prefix}.case_id", message=case.case_id
                )
            )
        case_ids.add(case.case_id)
        if case.owner not in catalogue.owners:
            issues.append(
                CatalogueIssue(
                    code="TESTCAT_UNKNOWN_OWNER", path=f"{prefix}.owner", message=case.owner
                )
            )
        for control in case.controls:
            if control not in known_controls:
                issues.append(
                    CatalogueIssue(
                        code="TESTCAT_UNKNOWN_CONTROL", path=f"{prefix}.controls", message=control
                    )
                )
        if case.engine == "generative" and case.oracle_type != "rubric":
            issues.append(
                CatalogueIssue(
                    code="TESTCAT_ENGINE_ORACLE_MISMATCH",
                    path=f"{prefix}.oracle_type",
                    message="generative cases require rubric oracle",
                )
            )
        for fixture_index, fixture in enumerate(case.fixtures):
            referenced_fixture_paths.add(fixture.path)
            fixture_path = (root / fixture.path).resolve()
            try:
                fixture_path.relative_to(root.resolve())
            except ValueError:
                issues.append(
                    CatalogueIssue(
                        code="TESTCAT_FIXTURE_ESCAPE",
                        path=f"{prefix}.fixtures[{fixture_index}].path",
                        message=fixture.path,
                    )
                )
                continue
            if not fixture_path.is_file():
                issues.append(
                    CatalogueIssue(
                        code="TESTCAT_FIXTURE_MISSING",
                        path=f"{prefix}.fixtures[{fixture_index}].path",
                        message=fixture.path,
                    )
                )
            elif _hash_file(fixture_path) != fixture.sha256:
                issues.append(
                    CatalogueIssue(
                        code="TESTCAT_FIXTURE_HASH_MISMATCH",
                        path=f"{prefix}.fixtures[{fixture_index}].sha256",
                        message=fixture.path,
                    )
                )

    managed_fixture_root = root / "tests" / "fixtures" / "testing"
    if managed_fixture_root.exists():
        for fixture_path in managed_fixture_root.rglob("*"):
            # Paired REUSE sidecars describe fixture attribution, not test inputs.
            # Orphan sidecars still require accounting, as do all fixture bytes.
            if fixture_path.suffix == ".license" and Path(str(fixture_path)[:-8]).is_file():
                continue
            if fixture_path.is_file():
                relative = fixture_path.relative_to(root).as_posix()
                if relative not in referenced_fixture_paths:
                    issues.append(
                        CatalogueIssue(
                            code="TESTCAT_FIXTURE_UNACCOUNTED",
                            path="cases.fixtures",
                            message=relative,
                        )
                    )

    covered = {control for case in catalogue.cases for control in case.controls}
    for control in catalogue.required_p0_controls:
        if control not in covered:
            issues.append(
                CatalogueIssue(
                    code="TESTCAT_P0_UNCOVERED", path="required_p0_controls", message=control
                )
            )
    for control in catalogue.required_p0_controls:
        modes = {
            mode
            for case in catalogue.cases
            if control in case.controls
            for mode in case.coverage_modes
        }
        required = {"positive", "negative", "boundary"}
        if not required.issubset(modes):
            issues.append(
                CatalogueIssue(
                    code="TESTCAT_COVERAGE_MODE_MISSING",
                    path="required_p0_controls",
                    message=f"{control}: {sorted(required - modes)}",
                )
            )
    for category in catalogue.required_semantic_categories:
        if not any(
            category in assertion
            for case in catalogue.cases
            for assertion in case.expected_assertions
        ):
            issues.append(
                CatalogueIssue(
                    code="TESTCAT_SEMANTIC_CATEGORY_UNCOVERED",
                    path="required_semantic_categories",
                    message=category,
                )
            )
    return issues


def validate_test_catalogue(path: Path = CATALOGUE_FILE) -> list[str]:
    """Validate the checked-in catalogue, raising with stable issue codes."""
    issues = validate_catalogue_payload(read_yaml(path))
    if issues:
        rendered = "; ".join(f"{issue.code} {issue.path}: {issue.message}" for issue in issues)
        raise ValueError(rendered)
    catalogue = TestCatalogue.model_validate(read_yaml(path))
    return [
        f"catalogue={catalogue.catalogue_id}@{catalogue.version}",
        f"cases={len(catalogue.cases)}",
    ]


def build_coverage_matrix(path: Path = CATALOGUE_FILE) -> list[dict[str, object]]:
    """Return deterministic control-to-case coverage rows for reports/CI."""
    catalogue = TestCatalogue.model_validate(read_yaml(path))
    rows: list[dict[str, object]] = []
    for control in sorted({value for case in catalogue.cases for value in case.controls}):
        cases = [case for case in catalogue.cases if control in case.controls]
        rows.append(
            {
                "control_id": control,
                "case_ids": sorted(case.case_id for case in cases),
                "engines": sorted({case.engine for case in cases}),
                "coverage_modes": sorted({mode for case in cases for mode in case.coverage_modes}),
                "blocking_tiers": sorted({case.blocking_tier for case in cases}),
            }
        )
    return rows
