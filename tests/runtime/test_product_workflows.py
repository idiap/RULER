# SPDX-FileCopyrightText: 2026 Idiap Research Institute
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Product lifecycle tests using real release gates and a real ASP solver."""

import asyncio
from datetime import UTC, datetime
import json

import pytest

from ruler.cli import _domain_registry
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import KBInferenceRequest
from ruler.persistence.workspace import PostgresMCPRuntime
from ruler.runtime.mcp_projects import ProjectMCPService
from ruler.runtime.mcp_server import _create_mcp_server, create_mcp_server
from ruler.runtime.product_workflows import KnowledgeInput, PreparedRequest, ProductWorkflows


@pytest.fixture
def product(tmp_path):
    return ProductWorkflows(
        ProjectMCPService(_domain_registry, KnowledgeBaseCatalog(repo_root=tmp_path))
    )


def knowledge(product, action, **kwargs):
    return product.prepare_knowledge(KnowledgeInput(action=action, **kwargs), allow_write=True)


def create_draft(product):
    knowledge(
        product,
        "create",
        definition={
            "kb_id": "product-kb",
            "name": "Product KB",
            "description": "Reviewed product rules",
            "domain_id": "regulatory",
            "purposes": ["inference"],
        },
    )
    knowledge(
        product,
        "add_artifact",
        kb_id="product-kb",
        artifact={
            "artifact_id": "rules",
            "name": "Rules",
            "role": "rules",
            "formalism": "asp",
            "media_type": "text/plain",
            "filename": "rules.lp",
            "content": "eligible(X) :- qualified(X).",
            "change_summary": "Initial formal rules",
        },
    )


def publish(product):
    digest = product.catalog.get("product-kb").current_version.content_sha256
    for target, kind in (
        ("candidate", "validation"),
        ("reviewed", "review"),
        ("published", "publication_approval"),
    ):
        knowledge(
            product,
            "transition",
            kb_id="product-kb",
            target=target,
            evidence=[
                {
                    "evidence_id": kind,
                    "kind": kind,
                    "subject_sha256": digest,
                    "actor_id": "test-reviewer",
                    "successful": True,
                    "recorded_at": datetime.now(UTC),
                    "details": "Reviewed fixture for lifecycle acceptance.",
                }
            ],
        )


def request():
    return KBInferenceRequest(
        request_id="customer-query",
        operation="query",
        backend_id="clingo-ground-query-v1",
        artifact_id="rules",
        query="eligible(alice)",
        asserted_facts=("qualified(alice)",),
    )


def test_real_end_to_end_with_release_evidence_and_restart(product):
    create_draft(product)
    with pytest.raises(LookupError):
        product.prepare_request("product-kb", request())
    publish(product)
    prepared = PreparedRequest.model_validate(
        product.prepare_request("product-kb", request())["prepared"]
    )
    assert product.execute_reasoning(prepared)["status"] == "blocked"
    result = product.execute_reasoning(prepared, allow_execute=True)
    assert result["status"] == "completed"
    assert result["result"]["target_support"] == "proved"
    restarted = ProductWorkflows(ProjectMCPService(_domain_registry, product.catalog))
    record = restarted.retrieve_results(result["run_id"])["record"]
    assert record["prepared"] == prepared.model_dump(mode="json")
    assert record["result"] == result["result"]


def test_publication_cannot_skip_review_or_use_wrong_digest(product):
    create_draft(product)
    with pytest.raises(ValueError):
        knowledge(product, "transition", kb_id="product-kb", target="published")
    with pytest.raises(ValueError):
        knowledge(
            product,
            "transition",
            kb_id="product-kb",
            target="candidate",
            evidence=[
                {
                    "evidence_id": "wrong",
                    "kind": "validation",
                    "subject_sha256": "sha256:" + "0" * 64,
                    "actor_id": "reviewer",
                    "successful": True,
                    "recorded_at": datetime.now(UTC),
                    "details": "Wrong source",
                }
            ],
        )


def test_tampered_request_preview_and_backend_are_rejected(product):
    create_draft(product)
    publish(product)
    for changes in (
        {"backend_id": "arbitrary"},
        {"parameters": {"allow_preview": True}},
        {"version_id": "stale"},
    ):
        with pytest.raises(ValueError):
            product.prepare_request("product-kb", request().model_copy(update=changes))
    prepared = product.prepare_request("product-kb", request())["prepared"]
    prepared["content_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="differs"):
        product.execute_reasoning(PreparedRequest.model_validate(prepared), allow_execute=True)
    assert not (product.catalog.repo_root / "build/ruler/product_runs").exists()


def test_retrieval_rejects_paths_tampering_and_foreign_workspaces(product, tmp_path):
    create_draft(product)
    publish(product)
    prepared = PreparedRequest.model_validate(
        product.prepare_request("product-kb", request())["prepared"]
    )
    run = product.execute_reasoning(prepared, allow_execute=True)["run_id"]
    other = ProductWorkflows(
        ProjectMCPService(_domain_registry, KnowledgeBaseCatalog(repo_root=tmp_path / "other"))
    )
    with pytest.raises(FileNotFoundError):
        other.retrieve_results(run)
    with pytest.raises(ValueError, match="identifier"):
        product.retrieve_results("../../secret")
    path = product.catalog.repo_root / "build/ruler/product_runs" / f"{run}.json"
    envelope = json.loads(path.read_text())
    envelope["record"]["result"]["target_support"] = "fabricated"
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match="digest"):
        product.retrieve_results(run)


def test_four_tools_only_and_no_developer_escape_hatches(product):
    async def check():
        expected = {
            "ruler_prepare_knowledge",
            "ruler_prepare_request",
            "ruler_execute_reasoning",
            "ruler_retrieve_results",
        }
        for server in (_create_mcp_server(project_service=product.projects), create_mcp_server()):
            assert {t.name for t in await server.list_tools()} == expected
            assert await server.list_resources() == []
        server = _create_mcp_server(project_service=product.projects)
        with pytest.raises(Exception, match="Unknown tool"):
            await server.call_tool(
                "ruler_run_workflow", {"workflow": "run-gates", "allow_write": True}
            )

    asyncio.run(check())
    for operation in (
        "ruler_run_workflow",
        "list_agent_assets",
        "read_agent_asset",
        "workflow_router_resource",
    ):
        with pytest.raises(ValueError, match="not a product"):
            PostgresMCPRuntime().invoke(operation, {})


def test_mutations_are_blocked_before_work_and_worker_accepts_json(product):
    for action in ("create", "apply_import", "transition", "batch_stage", "add_artifact"):
        assert product.prepare_knowledge(KnowledgeInput(action=action))["status"] == "blocked"
    assert not product.catalog.managed_root.exists()
    operations = {}
    _create_mcp_server(project_service=product.projects, operations=operations)
    assert (
        operations["ruler_prepare_knowledge"](input={"action": "apply_import", "plan_id": "none"})[
            "status"
        ]
        == "blocked"
    )
    assert (
        operations["ruler_prepare_knowledge"](input={"action": "shell", "command": "echo unsafe"})[
            "status"
        ]
        == "blocked"
    )


def test_batch_executes_only_one_native_stage_after_authorization(product, monkeypatch):
    from ruler.ingestion import batch_pipeline

    calls = []
    monkeypatch.setattr(
        batch_pipeline,
        "run_batch_stage",
        lambda batch, stage: calls.append((batch, stage.value)) or {"status": "advanced"},
    )
    input = KnowledgeInput(action="batch_stage", batch_id="registered-batch", stage="formalized")
    assert product.prepare_knowledge(input, allow_write=True)["status"] == "blocked"
    assert calls == []
    assert (
        product.prepare_knowledge(input, allow_write=True, allow_network=True)["status"]
        == "advanced"
    )
    assert calls == [("registered-batch", "formalized")]


def test_new_unpublished_revision_invalidates_prepared_requests(product):
    create_draft(product)
    publish(product)
    prepared = PreparedRequest.model_validate(
        product.prepare_request("product-kb", request())["prepared"]
    )
    knowledge(
        product,
        "add_artifact",
        kb_id="product-kb",
        artifact={
            "artifact_id": "new-facts",
            "name": "New facts",
            "role": "facts",
            "formalism": "asp",
            "media_type": "text/plain",
            "filename": "new.lp",
            "content": "qualified(bob).",
            "change_summary": "Unreviewed revision",
        },
    )
    with pytest.raises(ValueError):
        product.execute_reasoning(prepared, allow_execute=True)
