# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for grounded Codex conversation over named knowledge bases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ruler.interfaces.kb_conversation import (
    CodexExecClient,
    KBConversationRequest,
    KBConversationService,
)
from ruler.interfaces.kb_workspace import create_kb_workspace_app
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import AddKBArtifactRequest, CreateKnowledgeBaseRequest

TOKEN = "test-workspace-token-123456"


class RecordingConversationClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.prompts: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        return self.response


def _catalog(tmp_path: Path) -> KnowledgeBaseCatalog:
    (tmp_path / "kb/corpora").mkdir(parents=True)
    catalog = KnowledgeBaseCatalog(repo_root=tmp_path, managed_root=tmp_path / "kb/workspaces")
    catalog.create(
        CreateKnowledgeBaseRequest(
            kb_id="access-kb",
            name="Access KB",
            description="A bounded access-control knowledge base.",
            domain_id="general",
            purposes=frozenset({"inference", "exploration"}),
        )
    )
    catalog.add_artifact(
        "access-kb",
        AddKBArtifactRequest(
            artifact_id="access-rules",
            name="Access rules",
            role="rules",
            formalism="asp",
            media_type="text/x-asp",
            filename="access.lp",
            content="allowed(X) :- person(X), not blocked(X).\n",
            references=(),
            change_summary="Add access rules.",
        ),
    )
    return catalog


def _draft(**updates: Any) -> dict[str, Any]:
    value = {
        "answer": "The KB contains one ASP rule artifact.",
        "source_ids": ["kb:metadata", "artifact:access-rules:content", "invented"],
        "suggested_questions": ["Which inference operations are available?"],
        "inference_request": None,
    }
    value.update(updates)
    return value


def test_service_builds_path_free_grounding_and_verifies_citations(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    client = RecordingConversationClient(_draft())
    response = KBConversationService(catalog, client=client).converse(
        "access-kb",
        KBConversationRequest(message="What access rules are present?"),
        include_source_content=True,
        may_execute=True,
    )

    assert response.version_id == "access-kb-v0002"
    assert [item.source_id for item in response.citations] == [
        "kb:metadata",
        "artifact:access-rules:content",
    ]
    assert response.persisted is False
    prompt = client.prompts[0]
    assert "BEGIN UNTRUSTED KB SNAPSHOT" in prompt
    assert "allowed(X)" in prompt
    assert str(tmp_path) not in prompt
    assert "kb/workspaces" not in prompt


def test_chat_api_is_authenticated_and_can_delegate_bounded_inference(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    client = RecordingConversationClient(
        _draft(
            answer="I ran the requested bounded preview.",
            inference_request={
                "operation": "query",
                "artifact_id": "access-rules",
                "query": "allowed(alice)",
                "contrary": "-allowed(alice)",
                "asserted_facts": ["person(alice)"],
                "parameters": {"allow_preview": True},
                "backend_id": "clingo-ground-query-v1",
                "max_models": 100,
            },
        )
    )
    api = TestClient(
        create_kb_workspace_app(token=TOKEN, catalog=catalog, conversation_client=client)
    )

    assert api.get("/api/chat/status").status_code == 401
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert api.get("/api/chat/status", headers=headers).json()["available"] is True
    result = api.post(
        "/api/kbs/access-kb/chat",
        headers=headers,
        json={"message": "Is Alice allowed if she is a person?", "allow_inference": True},
    )

    assert result.status_code == 200
    payload = result.json()
    assert payload["backend"] == "codex-exec"
    assert payload["inference_result"]["conclusion"] == "supported"
    assert payload["inference_result"]["version_id"] == "access-kb-v0002"
    assert "NON-RELIANCE PREVIEW" in payload["inference_result"]["claim_boundary"]


def test_codex_exec_uses_ephemeral_isolated_read_only_directory(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    monkeypatch.setattr("ruler.interfaces.kb_conversation.shutil.which", lambda _: "/bin/codex")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["prompt"] = kwargs["input"]
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps(_draft()), encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("ruler.interfaces.kb_conversation.subprocess.run", fake_run)
    result = CodexExecClient(executable="codex").complete("bounded prompt")

    command = captured["command"]
    assert result["answer"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "shell_tool" in command
    assert "web_search_request" in command
    assert "skill_search" in command
    assert str(tmp_path) not in " ".join(command)
    assert captured["prompt"] == "bounded prompt"
