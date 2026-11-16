# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Exercise actual MCP schemas and the import trust boundary."""

import asyncio
import hashlib

import pytest
import yaml

from ruler.domains.regulatory.pack import RegulatoryDomainPack
from ruler.domains.registry import DomainPackRegistry
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.runtime import mcp_projects
from ruler.runtime.mcp_projects import ProjectMCPService
from ruler.runtime.mcp_server import MCP_TOOL_NAMES, _create_mcp_server, kb_execute, kb_show


@pytest.fixture
def service(tmp_path):
    corpus = tmp_path / "kb/corpora/test-corpus"
    corpus.mkdir(parents=True)
    source = corpus / "source.txt"
    source.write_text("The subject must submit notice.\n")
    manifest = {
        "schema_version": "2.0",
        "domain_id": "regulatory",
        "corpus_id": "test-corpus",
        "description": "A reviewed source corpus.",
        "artifacts": [
            {
                "artifact_id": "source-v1",
                "document_id": "source",
                "document_version": "1",
                "status": "approved",
                "path": "kb/corpora/test-corpus/source.txt",
                "sha256": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
                "language": "en",
                "category": "source_evidence",
                "artifact_type": "normative_document",
                "role": "Requirement source",
                "references": [],
            }
        ],
    }
    (corpus / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    registry = DomainPackRegistry()
    registry.register(RegulatoryDomainPack())
    return ProjectMCPService(lambda: registry, KnowledgeBaseCatalog(repo_root=tmp_path))


def test_project_discovery_validation_and_actual_tool_schemas(service):
    server = _create_mcp_server(project_service=service)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == set(MCP_TOOL_NAMES)
    assert "input" in tools["ruler_prepare_knowledge"].inputSchema["properties"]
    assert "ruler_project_inspect" not in tools
    assert service.validate("regulatory")["status"] == "pass"
    assert service.list_projects()["projects"][0]["project_id"] == "regulatory"
    assert service.inspect("regulatory")["predicates"]["in_scope"]["world_assumption"] == "open"
    result = asyncio.run(
        server.call_tool(
            "ruler_prepare_knowledge", {"input": {"action": "inspect", "project_id": "missing"}}
        )
    )
    assert "blocked" in str(result)


def test_read_only_plan_then_exact_draft_import_and_replay_block(service):
    catalog = service.catalog
    plan = service.plan_import("regulatory", "test-corpus")
    assert not catalog.managed_root.exists()
    assert plan["kb_id"] == "test-corpus-import"
    assert plan["publication_inherited"] is False
    assert str(catalog.repo_root) not in str(plan)
    assert service.apply_import(plan["plan_id"])["status"] == "blocked"
    result = service.apply_import(plan["plan_id"], allow_write=True)
    assert result["status"] == "imported"
    kb = catalog.get(result["kb_id"])
    assert kb.lifecycle == kb.current_version.status == "draft"
    assert kb.source_kind == "managed"
    artifact = kb.current_version.artifacts[0]
    assert artifact.status == "approved"
    assert catalog.artifact_path(artifact).read_text() == "The subject must submit notice.\n"
    assert catalog.releases(kb.kb_id) == ()
    assert kb_show(kb.kb_id, catalog=catalog)["project_id"] == "regulatory"
    assert service.apply_import(plan["plan_id"], allow_write=True)["status"] == "blocked"
    with pytest.raises(ValueError, match="already exists"):
        service.plan_import("regulatory", "test-corpus")
    request = {
        "request_id": "check",
        "operation": "query",
        "artifact_id": artifact.artifact_id,
        "backend_id": "clingo-ground-query-v1",
        "query": "ok",
    }
    assert kb_execute(kb.kb_id, request, allow_execute=True, catalog=catalog)["status"] == "blocked"


def test_plan_expiration_unknown_id_and_server_session_isolation(service):
    now = [0.0]
    service.clock = lambda: now[0]
    plan = service.plan_import("regulatory", "test-corpus", "custom-kb")
    other = ProjectMCPService(service.registry, service.catalog)
    assert other.apply_import(plan["plan_id"], True)["status"] == "blocked"
    assert service.apply_import("unknown", True)["status"] == "blocked"
    now[0] += mcp_projects.PLAN_TTL_SECONDS
    assert service.apply_import(plan["plan_id"], True)["status"] == "blocked"
    assert not service.catalog.managed_root.exists()


def test_tampered_bytes_and_stale_manifest_never_import(service):
    plan = service.plan_import("regulatory", "test-corpus")
    corpus = service.catalog.repo_root / "kb/corpora/test-corpus"
    (corpus / "source.txt").write_text("Changed evidence.")
    with pytest.raises(ValueError, match="digest mismatch"):
        service.apply_import(plan["plan_id"], True)
    manifest_path = corpus / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["artifacts"][0]["sha256"] = (
        "sha256:" + hashlib.sha256((corpus / "source.txt").read_bytes()).hexdigest()
    )
    manifest_path.write_text(yaml.safe_dump(manifest))
    assert service.apply_import(plan["plan_id"], True)["status"] == "blocked"
    assert not service.catalog.managed_root.exists()


def test_changed_project_definition_blocks_an_existing_plan(service):
    plan = service.plan_import("regulatory", "test-corpus")
    service.registry().get("regulatory").schema_version = "changed"
    assert service.apply_import(plan["plan_id"], True)["status"] == "blocked"


@pytest.mark.parametrize(
    "corpus_id", ["../test-corpus", "/tmp/source", "test-corpus/manifest.yaml"]
)
def test_import_does_not_accept_paths(service, corpus_id):
    with pytest.raises(ValueError, match="identifier"):
        service.plan_import("regulatory", corpus_id)


def test_wrong_project_unsafe_target_and_size_limits(service, monkeypatch):
    with pytest.raises(ValueError, match="unknown project"):
        service.plan_import("other", "test-corpus")
    with pytest.raises(ValueError):
        service.plan_import("regulatory", "test-corpus", "../escape")
    monkeypatch.setattr(mcp_projects, "MAX_IMPORT_BYTES", 1)
    with pytest.raises(ValueError, match="byte limit"):
        service.plan_import("regulatory", "test-corpus")


def test_plan_payload_cannot_change_the_pinned_import(service, monkeypatch):
    plan = service.plan_import("regulatory", "test-corpus")
    plan["artifacts"][0]["sha256"] = "sha256:" + "0" * 64
    assert service.apply_import(plan["plan_id"], True)["status"] == "imported"
    monkeypatch.setattr(mcp_projects, "MAX_PLANS", 1)
    service.plan_import("regulatory", "test-corpus", "another-copy")
    with pytest.raises(ValueError, match="too many pending"):
        service.plan_import("regulatory", "test-corpus", "third-copy")


def test_import_preserves_references_and_binary_bytes(service):
    corpus = service.catalog.repo_root / "kb/corpora/test-corpus"
    manifest_path = corpus / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    content = b"\x00\xff\x01binary evidence"
    (corpus / "attachment.bin").write_bytes(content)
    manifest["artifacts"].append(
        {
            **manifest["artifacts"][0],
            "artifact_id": "attachment-v1",
            "document_id": "attachment",
            "path": "kb/corpora/test-corpus/attachment.bin",
            "references": ["source-v1"],
            "status": "candidate",
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
        }
    )
    manifest_path.write_text(yaml.safe_dump(manifest))
    plan = service.plan_import("regulatory", "test-corpus")
    imported = service.apply_import(plan["plan_id"], True)
    attachment = service.catalog.get(imported["kb_id"]).current_version.artifacts[1]
    assert attachment.references == ("source-v1",)
    assert attachment.status == "candidate"
    assert service.catalog.artifact_path(attachment).read_bytes() == content


def test_symlinked_artifacts_cannot_escape_the_corpus(service):
    root = service.catalog.repo_root
    artifact = root / "kb/corpora/test-corpus/source.txt"
    outside = root / "outside.txt"
    outside.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        service.plan_import("regulatory", "test-corpus")


def test_failed_import_rolls_back_and_keeps_source_unchanged(service, monkeypatch):
    plan = service.plan_import("regulatory", "test-corpus")
    source = service.catalog.get("test-corpus")

    def fail(_):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(service.catalog, "_write", fail)
    with pytest.raises(OSError):
        service.apply_import(plan["plan_id"], True)
    assert not (service.catalog.managed_root / plan["kb_id"]).exists()
    assert service.catalog.get("test-corpus") == source


def test_mcp_tools_apply_authorization_and_project_response_keys(service):
    server = _create_mcp_server(project_service=service)

    async def call():
        _, plan = await server.call_tool(
            "ruler_prepare_knowledge",
            {
                "input": {
                    "action": "plan_import",
                    "project_id": "regulatory",
                    "corpus_id": "test-corpus",
                },
            },
        )
        args = {"input": {"action": "apply_import", "plan_id": plan["plan_id"]}}
        _, blocked = await server.call_tool("ruler_prepare_knowledge", args)
        assert blocked["status"] == "blocked"
        _, applied = await server.call_tool(
            "ruler_prepare_knowledge", {**args, "allow_write": True}
        )
        assert applied["status"] == "imported"
        assert "domain_id" not in applied

    asyncio.run(call())
