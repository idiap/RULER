# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Contract and mutation tests for the versioned test catalogue."""

from __future__ import annotations

from copy import deepcopy
import shutil

from ruler.io import read_yaml
from ruler.testing.catalogue import (
    CATALOGUE_FILE,
    build_coverage_matrix,
    validate_catalogue_payload,
    validate_test_catalogue,
)


def test_checked_in_catalogue_is_complete_and_hash_locked() -> None:
    messages = validate_test_catalogue()
    assert "cases=9" in messages
    matrix = build_coverage_matrix()
    assert {row["control_id"] for row in matrix} >= {
        "TST-007",
        "TST-008",
        "TST-009",
        "TST-010",
        "TST-011",
        "TST-012",
        "TST-013",
        "TST-020",
        "TST-014",
        "TST-015",
        "TST-016",
        "TST-017",
        "TST-018",
        "TST-019",
    }


def _mutated_payload() -> dict[str, object]:
    return deepcopy(read_yaml(CATALOGUE_FILE))


def test_catalogue_rejects_duplicate_case_ids() -> None:
    payload = _mutated_payload()
    payload["cases"].append(deepcopy(payload["cases"][0]))
    codes = {issue.code for issue in validate_catalogue_payload(payload)}
    assert "TESTCAT_DUPLICATE_CASE" in codes


def test_catalogue_rejects_unknown_owner_and_self_generated_oracle() -> None:
    payload = _mutated_payload()
    payload["cases"][0]["owner"] = "nobody"
    issues = validate_catalogue_payload(payload)
    assert any(issue.code == "TESTCAT_UNKNOWN_OWNER" for issue in issues)

    payload = _mutated_payload()
    payload["cases"][2]["fixtures"][0]["oracle_authorship"] = "production"
    issues = validate_catalogue_payload(payload)
    assert any(issue.code == "TESTCAT_SCHEMA_INVALID" for issue in issues)


def test_catalogue_rejects_fixture_drift_and_uncovered_p0() -> None:
    payload = _mutated_payload()
    payload["cases"][2]["fixtures"][0]["sha256"] = "sha256:" + "0" * 64
    payload["required_p0_controls"].append("WF-999")
    codes = {issue.code for issue in validate_catalogue_payload(payload)}
    assert {
        "TESTCAT_FIXTURE_HASH_MISMATCH",
        "TESTCAT_P0_UNCOVERED",
        "TESTCAT_UNKNOWN_CONTROL",
    } <= codes


def test_catalogue_distinguishes_paired_license_metadata_from_unregistered_inputs(tmp_path) -> None:
    root = CATALOGUE_FILE.parents[1]
    shutil.copytree(root / "tests" / "fixtures", tmp_path / "tests" / "fixtures")
    payload = _mutated_payload()
    for case in payload["cases"]:
        for fixture in case["fixtures"]:
            relative = fixture["path"]
            destination = tmp_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, destination)
    assert not validate_catalogue_payload(payload, root=tmp_path)
    managed = tmp_path / "tests" / "fixtures" / "testing"
    (managed / "unregistered.yaml").write_text("case: unregistered\n")
    (managed / "orphan.yaml.license").write_text("unpaired attribution\n")
    issues = validate_catalogue_payload(payload, root=tmp_path)
    unaccounted = {issue.message for issue in issues if issue.code == "TESTCAT_FIXTURE_UNACCOUNTED"}
    assert unaccounted == {
        "tests/fixtures/testing/unregistered.yaml",
        "tests/fixtures/testing/orphan.yaml.license",
    }
