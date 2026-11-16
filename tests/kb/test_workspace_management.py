# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from pathlib import Path

import pytest
from pydantic import ValidationError

from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import (
    AddKBArtifactRequest,
    CreateKnowledgeBaseRequest,
    KBInferenceRequest,
)
from ruler.kb.workspace_inference import KBInferenceService


def _catalog(tmp_path: Path) -> KnowledgeBaseCatalog:
    (tmp_path / "kb/corpora").mkdir(parents=True)
    return KnowledgeBaseCatalog(repo_root=tmp_path, managed_root=tmp_path / "kb/workspaces")


def _create(catalog: KnowledgeBaseCatalog, kb_id: str = "test-kb"):
    return catalog.create(
        CreateKnowledgeBaseRequest(
            kb_id=kb_id,
            name="Test Rules",
            description="A bounded test knowledge base.",
            domain_id="general",
            purposes=frozenset({"inference", "verification"}),
            tags=frozenset({"test"}),
        )
    )


def _asp_artifact(
    content: str = "allowed(X) :- person(X), not blocked(X).\n",
) -> AddKBArtifactRequest:
    return AddKBArtifactRequest(
        artifact_id="access-rules",
        name="Access rules",
        role="rules",
        formalism="asp",
        media_type="text/x-asp",
        filename="access.lp",
        content=content,
        language="en",
        change_summary="Add the initial executable access policy.",
    )


def test_managed_kb_create_rename_version_search_and_reload(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    created = _create(catalog)
    assert created.current_version.revision == 1
    assert not created.current_version.artifacts

    renamed = catalog.update_metadata("test-kb", name="Renamed Rules")
    assert renamed.name == "Renamed Rules"
    assert renamed.current_version.content_sha256 == created.current_version.content_sha256

    updated = catalog.add_artifact("test-kb", _asp_artifact())
    assert updated.current_version.revision == 2
    assert updated.current_version.parent_version_id == created.current_version_id
    assert updated.versions[0].artifacts == ()
    assert updated.current_version.artifacts[0].sha256.startswith("sha256:")

    reloaded = KnowledgeBaseCatalog(
        repo_root=tmp_path, managed_root=tmp_path / "kb/workspaces"
    ).get("test-kb")
    assert reloaded.current_version.content_sha256 == updated.current_version.content_sha256
    hits = catalog.search("allowed person", kb_id="test-kb")
    assert [(item.kb_id, item.artifact_id) for item in hits] == [("test-kb", "access-rules")]


def test_read_only_adapters_and_immutable_artifact_collisions_fail(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _create(catalog)
    catalog.add_artifact("test-kb", _asp_artifact())
    with pytest.raises(ValueError, match="already exists"):
        catalog.add_artifact("test-kb", _asp_artifact())

    with pytest.raises(ValidationError, match="filename"):
        AddKBArtifactRequest(
            artifact_id="bad",
            name="Bad",
            role="rules",
            formalism="asp",
            media_type="text/plain",
            filename="../escape.lp",
            content="fact.",
            change_summary="Attempt traversal.",
        )


def test_asp_inference_reports_skeptical_support_and_rejects_injection(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _create(catalog)
    catalog.add_artifact("test-kb", _asp_artifact())
    service = KBInferenceService(catalog)
    result = service.execute(
        "test-kb",
        KBInferenceRequest(
            request_id="supported",
            operation="verify",
            artifact_id="access-rules",
            query="allowed(alice)",
            contrary="-allowed(alice)",
            asserted_facts=("person(alice)",),
            parameters={"allow_preview": True},
        ),
    )
    assert result.status == "completed"
    assert result.conclusion == "supported"
    assert result.target_support == "proved"
    assert result.contrary_support == "not_proved"
    assert result.complete

    injection = service.execute(
        "test-kb",
        KBInferenceRequest(
            request_id="injection",
            operation="query",
            query="allowed(alice). evil",
            parameters={"allow_preview": True},
        ),
    )
    assert injection.status == "error"
    assert injection.conclusion == "underdetermined"


def test_model_bound_blocks_instead_of_sampling_a_conclusion(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _create(catalog)
    catalog.add_artifact("test-kb", _asp_artifact("{pick(a)}.\n{pick(b)}.\n"))
    result = KBInferenceService(catalog).execute(
        "test-kb",
        KBInferenceRequest(
            request_id="bounded",
            operation="query",
            query="pick(a)",
            max_models=2,
            parameters={"allow_preview": True},
        ),
    )
    assert result.status == "blocked"
    assert not result.complete
    assert result.blockers == ("model_enumeration_incomplete",)


def test_existing_corpora_are_exposed_as_three_read_only_named_kbs() -> None:
    items = KnowledgeBaseCatalog().list()
    assert {item.kb_id for item in items}.issuperset({"regulatory-proof", "legal-sr101-art36"})
    adapted = [item for item in items if item.source_kind == "corpus_adapter"]
    assert adapted and all(item.access_mode == "read_only" for item in adapted)
    assert all(item.current_version.content_sha256.startswith("sha256:") for item in adapted)


def test_regulatory_corpus_supports_source_grounded_compliance_query() -> None:
    catalog = KnowledgeBaseCatalog()
    result = KBInferenceService(catalog).execute(
        "regulatory-proof",
        KBInferenceRequest(
            request_id="regulatory-boundary",
            operation="verify",
            artifact_id="regulatory-proof-asp-v1",
            query='evaluation_outcome("rg_notice_obligation",alice,"satisfied")',
            contrary='evaluation_outcome("rg_notice_obligation",alice,"violated")',
            asserted_facts=(
                "in_scope(alice)",
                "submitted_notice(alice)",
                "within_deadline(alice)",
            ),
        ),
    )
    assert result.status == "completed"
    assert result.conclusion == "supported"
    assert result.evidence[0] == "regulatory-proof-asp-v1"
