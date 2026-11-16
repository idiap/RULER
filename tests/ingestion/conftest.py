# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Isolated technical-service plans for batch lifecycle regression tests."""

import pytest
from ruler.io import write_yaml


@pytest.fixture(autouse=True)
def service_batch_workspace(request, monkeypatch, tmp_path):
    if request.module.__name__.split(".")[-1] not in {
        "test_batch_pipeline",
        "test_progressive_onboarding",
    }:
        return
    import ruler.ingestion.progressive_onboarding as onboarding
    import ruler.ingestion.batch_pipeline as pipeline

    root = tmp_path / "batch-workspace"
    plan_path = root / "rollout.yaml"
    phases = []
    for phase, count in enumerate((1, 3, 6, 3, 3, 18), 1):
        labels = [f"Service {phase}-{i}" for i in range(count)]
        if phase == 1:
            labels = ["Equipment maintenance"]
        if phase == 2:
            labels[0] = "Support contract"
        phases.append(
            dict(
                phase=phase,
                products=labels,
                workbook_rows=count,
                source_dispositions={"source_ready": count},
            )
        )
    write_yaml(plan_path, {"schema_version": 1, "phases": phases})
    monkeypatch.setattr(onboarding, "ROLLOUT_PLAN_FILE", plan_path)
    monkeypatch.setattr(
        onboarding, "PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE", root / "expansion.yaml"
    )
    monkeypatch.setattr(
        onboarding, "LEGACY_REFERENCE_DOCUMENT_IDS", frozenset({"fixture-reference-document"})
    )
    plan = onboarding.build_progressive_plan()
    ids = tuple(batch.batch_id for batch in plan.batches)
    monkeypatch.setattr(onboarding, "LEGACY_BATCH_IDS", ids)
    monkeypatch.setattr(request.module, "LEGACY_BATCH_IDS", ids)
    workspace = root / "onboarding"
    artifacts = onboarding.initialize_progressive_onboarding(workspace)
    catalogue = pipeline.build_pipeline_catalogue()
    catalogue_path = workspace / "pipeline_catalogue.yaml"
    write_yaml(catalogue_path, catalogue)
    monkeypatch.setattr(pipeline, "CATALOGUE_FILE", catalogue_path)
    monkeypatch.setattr(pipeline, "ONBOARDING_PLAN_FILE", artifacts["plan"])
    monkeypatch.setattr(
        pipeline,
        "load_progress_events",
        lambda: onboarding.load_progress_events(artifacts["ledger"]),
    )
    monkeypatch.setattr(request.module, "CATALOGUE_FILE", catalogue_path, raising=False)
    # Reference-release tests use an explicit isolated fixture, never a production release.
    if request.node.name == "test_reference_backed_publication_is_final_for_later_phase_checkpoint":
        for batch in catalogue["batches"]:
            if batch["batch_id"] == "phase-03-batch-02":
                batch["reference_release"] = "reference.yaml"
        write_yaml(catalogue_path, catalogue)
        write_yaml(root / "reference.yaml", {"release_status": "published"})
        defaults = dict(onboarding.reference_release_is_published.__kwdefaults__)
        defaults.update(catalogue_path=catalogue_path, repository_root=root)
        monkeypatch.setattr(onboarding.reference_release_is_published, "__kwdefaults__", defaults)
