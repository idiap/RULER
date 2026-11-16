# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from pathlib import Path

from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import (
    AddKBArtifactRequest,
    CreateKnowledgeBaseRequest,
    KBArtifactRole,
    KBFormalism,
    KBInferenceRequest,
    KBPurpose,
)
from ruler.kb.workspace_experience import (
    InferenceRunStore,
    ReleaseSearchIndex,
    compare_releases,
    layered_graph,
    query_editor_model,
)
from ruler.runtime.mcp_server import (
    kb_capabilities,
    kb_execute,
    kb_list,
    kb_plan,
    kb_search,
    kb_show,
)


def _catalog(tmp_path: Path) -> KnowledgeBaseCatalog:
    (tmp_path / "kb/corpora").mkdir(parents=True)
    catalog = KnowledgeBaseCatalog(repo_root=tmp_path, managed_root=tmp_path / "kb/workspaces")
    catalog.create(
        CreateKnowledgeBaseRequest(
            kb_id="access-kb",
            name="Access",
            description="Bounded access rules.",
            domain_id="general",
            purposes=frozenset({KBPurpose.INFERENCE}),
            tags=frozenset({"demo"}),
        )
    )
    catalog.add_artifact(
        "access-kb",
        AddKBArtifactRequest(
            artifact_id="rules",
            name="Access rules",
            role=KBArtifactRole.RULES,
            formalism=KBFormalism.ASP,
            media_type="text/x-asp",
            filename="rules.lp",
            content="allowed(X) :- person(X), not blocked(X).\n",
            language="en",
            references=(),
            change_summary="Add access rules.",
        ),
    )
    return catalog


def _request() -> KBInferenceRequest:
    return KBInferenceRequest(
        request_id="run-1",
        operation="query",
        artifact_id="rules",
        query="allowed(alice)",
        contrary="-allowed(alice)",
        asserted_facts=("person(alice)",),
        backend_id="clingo-ground-query-v1",
        parameters={"allow_preview": True},
    )


def test_release_index_is_stable_filtered_pinned_and_redacted(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    one = ReleaseSearchIndex.build(catalog, "access-kb")
    two = ReleaseSearchIndex.build(catalog, "access-kb")
    assert one.index_digest == two.index_digest
    found = one.search("allowed", languages={"en"}, formalisms={"asp"}, statuses={"candidate"})
    assert found["version_id"] == "access-kb-v0002"
    assert found["hits"][0]["artifact_id"] == "rules"
    redacted = one.search("rules", visible_fields=frozenset({"metadata"}))
    assert redacted["hits"][0]["snippet"] == "[redacted]"
    assert redacted["hits"][0]["redacted_fields"] == ["content"]
    assert one.search("allowed", languages={"fr"})["hits"] == []


def test_comparison_query_model_and_digest_bound_graph(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    comparison = compare_releases(catalog, "access-kb", "access-kb")
    assert comparison["semantic_change"] is False
    assert comparison["artifacts"] == {"added": [], "removed": [], "changed": []}
    editor = query_editor_model(catalog, "access-kb")
    signature = next(row for row in editor["signatures"] if row["predicate"] == "allowed")
    assert signature["arity"] == 1
    assert signature["template"] == "allowed(<1:term>)"
    graph = layered_graph(catalog.get("access-kb"))
    assert graph["nodes"][0]["layer"] == "rule_axiom"
    assert graph["nodes"][0]["digest"].startswith("sha256:")
    assert graph["accessible_alternative"]


def test_content_addressed_run_is_idempotent_and_replayable(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    store = InferenceRunStore(tmp_path / "runs", catalog)
    first = store.execute("access-kb", _request())
    second = store.execute("access-kb", _request())
    assert first["run_id"] == second["run_id"]
    assert first["result"]["conclusion"] == "supported"
    assert first["identity"]["backend_compiler_digest"].startswith("sha256:")
    assert (
        store.get(first["run_id"])["identity"]["release_digest"]
        == catalog.get("access-kb").current_version.content_sha256
    )
    replay = store.replay(first["run_id"])
    assert replay["status"] == "replayed"
    assert replay["outcome_matches"] is True
    assert first["evidence_graph"]["edges"][-1]["relation"] == "produced_result"


def test_mcp_kb_tools_are_redacted_and_execution_is_doubly_guarded(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    assert kb_list(catalog=catalog)["count"] == 1
    shown = kb_show("access-kb", catalog=catalog)
    assert "path" not in str(shown)
    assert kb_search("access-kb", "rules", catalog=catalog)["hits"][0]["snippet"] == "[redacted]"
    assert kb_capabilities("access-kb", catalog=catalog)["executed"] is False
    plan = kb_plan("access-kb", "query", catalog=catalog)
    assert plan["executable"] is False
    assert plan["blockers"] == ["no_published_release"]
    payload = _request().model_dump(mode="json")
    assert kb_execute("access-kb", payload, catalog=catalog)["status"] == "blocked"
    payload["backend_id"] = "untrusted"
    assert (
        kb_execute("access-kb", payload, allow_execute=True, catalog=catalog)["status"] == "blocked"
    )
    payload["backend_id"] = "clingo-ground-query-v1"
    assert (
        kb_execute("access-kb", payload, allow_execute=True, catalog=catalog)["conclusion"]
        == "supported"
    )
