# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Safety and audit tests for the dry-run-first artifact migration service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ruler.kb.artifact_migration import (
    apply_artifact_migration,
    plan_artifact_migration,
)


def _legacy_release(tmp_path: Path, payload: object) -> tuple[Path, Path]:
    source = tmp_path / "kb/formalized/real/policy/rules.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    manifest = tmp_path / "kb/manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "kb_id": "legacy-v1",
                "entries": [
                    {
                        "kb_path": "kb/formalized/real/policy/rules.yaml",
                        "artifact_id": "legacy-rule-set",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest, source


def test_migration_defaults_to_a_no_write_dry_run_and_reports_deltas(tmp_path: Path) -> None:
    manifest, source = _legacy_release(tmp_path, [{"policy_id": "p-1", "clause": "Must file."}])
    original = source.read_bytes()

    plan = plan_artifact_migration(
        manifest,
        release_name="regulatory-2026",
        rename_fields={"policy_id": "document_id", "clause": "normative_unit"},
        repo_root=tmp_path,
    )

    assert plan.mode == "dry-run"
    assert not (tmp_path / plan.destination_namespace).exists()
    assert source.read_bytes() == original
    artifact = plan.artifacts[0]
    assert artifact.hash_changed and artifact.id_changed
    assert {item.source_field: item.occurrences for item in artifact.field_mappings} == {
        "clause": 1,
        "policy_id": 1,
    }
    assert artifact.ambiguities == ()
    assert artifact.losses == ()


def test_apply_publishes_new_namespace_without_mutating_or_overwriting_v1(
    tmp_path: Path,
) -> None:
    manifest, source = _legacy_release(tmp_path, {"policy_id": "p-1"})
    original = source.read_bytes()
    plan = plan_artifact_migration(
        manifest,
        release_name="release-1",
        rename_fields={"policy_id": "document_id"},
        repo_root=tmp_path,
    )

    applied = apply_artifact_migration(plan, repo_root=tmp_path)

    destination = tmp_path / applied.destination_namespace
    assert applied.mode == "applied"
    assert source.read_bytes() == original
    assert (destination / "migration-report.json").is_file()
    report = json.loads((destination / "migration-report.json").read_text(encoding="utf-8"))
    assert report["source_manifest_sha256"] == plan.source_manifest_sha256
    migrated = tmp_path / applied.artifacts[0].target_path
    assert yaml.safe_load(migrated.read_text(encoding="utf-8")) == {"document_id": "p-1"}

    with pytest.raises(FileExistsError, match="immutable v2 release"):
        apply_artifact_migration(plan, repo_root=tmp_path)


def test_loss_and_ambiguity_require_explicit_acceptance(tmp_path: Path) -> None:
    manifest, _ = _legacy_release(
        tmp_path, {"policy_id": "old", "document_id": "already-v2", "discard": "value"}
    )
    plan = plan_artifact_migration(
        manifest,
        release_name="reviewed",
        rename_fields={"policy_id": "document_id"},
        drop_fields=("discard",),
        repo_root=tmp_path,
    )

    assert plan.requires_review
    assert plan.artifacts[0].ambiguities
    assert plan.artifacts[0].losses
    with pytest.raises(ValueError, match="ambiguities"):
        apply_artifact_migration(plan, repo_root=tmp_path)
    with pytest.raises(ValueError, match="losses"):
        apply_artifact_migration(plan, repo_root=tmp_path, accept_ambiguities=True)

    applied = apply_artifact_migration(
        plan, repo_root=tmp_path, accept_ambiguities=True, accept_losses=True
    )
    migrated = yaml.safe_load(
        (tmp_path / applied.artifacts[0].target_path).read_text(encoding="utf-8")
    )
    assert migrated == {"document_id": "already-v2"}


def test_apply_refuses_source_drift_after_dry_run(tmp_path: Path) -> None:
    manifest, source = _legacy_release(tmp_path, {"policy_id": "p-1"})
    plan = plan_artifact_migration(manifest, release_name="stale", repo_root=tmp_path)
    source.write_text("policy_id: changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source artifact changed"):
        apply_artifact_migration(plan, repo_root=tmp_path)
    assert not (tmp_path / plan.destination_namespace).exists()
