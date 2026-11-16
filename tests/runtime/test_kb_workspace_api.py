# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from pathlib import Path

from fastapi.testclient import TestClient

from ruler.interfaces.kb_workspace import create_kb_workspace_app
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import CreateKnowledgeBaseRequest
from ruler.kb.workspace_governance import AccessGrant, AccessPolicy, KBRole

TOKEN = "test-workspace-token-123456"


def _client(tmp_path: Path) -> TestClient:
    (tmp_path / "kb/corpora").mkdir(parents=True)
    catalog = KnowledgeBaseCatalog(repo_root=tmp_path, managed_root=tmp_path / "kb/workspaces")
    return TestClient(create_kb_workspace_app(token=TOKEN, catalog=catalog))


def _headers(**extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", **extra}


def test_every_workspace_and_artifact_route_requires_authentication(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 401
    assert client.get("/api/kbs").status_code == 401
    assert client.get("/api/search?q=test").status_code == 401
    assert client.get("/api/kbs/unknown/artifacts/a").status_code == 401
    response = client.get("/", params={"token": TOKEN})
    assert response.status_code == 200
    assert "Knowledge Base Workspace" in response.text
    assert "Content-Security-Policy" in response.headers


def test_create_add_search_inspect_graph_and_infer_end_to_end(tmp_path: Path) -> None:
    client = _client(tmp_path)
    create_payload = {
        "kb_id": "access-kb",
        "name": "Access KB",
        "description": "Rules governing a bounded access example.",
        "domain_id": "general",
        "purposes": ["inference", "verification"],
        "tags": ["demo"],
    }
    missing_confirmation = client.post("/api/kbs", headers=_headers(), json=create_payload)
    assert missing_confirmation.status_code == 409
    created = client.post(
        "/api/kbs",
        headers=_headers(**{"X-KB-Confirm": "create:access-kb"}),
        json=create_payload,
    )
    assert created.status_code == 200
    assert created.json()["current_version_id"] == "access-kb-v0001"
    etag = client.get("/api/kbs/access-kb", headers=_headers()).headers["etag"]

    artifact_payload = {
        "artifact_id": "access-rules",
        "name": "<img src=x onerror=alert(1)>",
        "role": "rules",
        "formalism": "asp",
        "media_type": "text/x-asp",
        "filename": "access.lp",
        "content": "allowed(X) :- person(X), not blocked(X).\n",
        "language": "en",
        "references": [],
        "change_summary": "Add executable access rules.",
    }
    added = client.post(
        "/api/kbs/access-kb/artifacts",
        headers=_headers(
            **{
                "X-KB-Confirm": "add:access-kb:access-rules",
                "If-Match": etag,
                "Idempotency-Key": "add-access-rules-v1",
            }
        ),
        json=artifact_payload,
    )
    assert added.status_code == 200
    assert added.json()["current_version_id"] == "access-kb-v0002"
    assert "path" not in str(added.json())
    replayed = client.post(
        "/api/kbs/access-kb/artifacts",
        headers=_headers(
            **{
                "X-KB-Confirm": "add:access-kb:access-rules",
                "If-Match": etag,
                "Idempotency-Key": "add-access-rules-v1",
            }
        ),
        json=artifact_payload,
    )
    assert replayed.status_code == 200
    assert replayed.headers["idempotent-replay"] == "true"

    search = client.get(
        "/api/search", params={"q": "allowed person", "kb_id": "access-kb"}, headers=_headers()
    )
    assert search.status_code == 200
    assert search.json()["hits"][0]["artifact_id"] == "access-rules"

    graph = client.get("/api/kbs/access-kb/graph", headers=_headers()).json()
    assert graph["nodes"][0]["formalism"] == "asp"
    preview = client.get("/api/kbs/access-kb/artifacts/access-rules", headers=_headers()).json()
    assert "allowed(X)" in preview["preview"]
    assert "path" not in str(preview)

    inference = client.post(
        "/api/kbs/access-kb/infer",
        headers=_headers(),
        json={
            "request_id": "api-run",
            "operation": "query",
            "artifact_id": "access-rules",
            "query": "allowed(alice)",
            "contrary": "-allowed(alice)",
            "asserted_facts": ["person(alice)"],
            "parameters": {"allow_preview": True},
        },
    )
    assert inference.status_code == 200
    assert inference.json()["conclusion"] == "supported"
    assert "NON-RELIANCE PREVIEW" in inference.json()["claim_boundary"]

    stale = client.patch(
        "/api/kbs/access-kb",
        headers=_headers(
            **{
                "X-KB-Confirm": "update:access-kb",
                "If-Match": etag,
                "Idempotency-Key": "stale-update",
            }
        ),
        json={"name": "Stale"},
    )
    assert stale.status_code == 412


def test_visual_shell_does_not_embed_stored_content_or_paths(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/", params={"token": TOKEN})
    assert response.status_code == 200
    assert "innerHTML" not in response.text
    assert "/Users/" not in response.text
    assert "textContent" in response.text


def test_workspace_access_policy_hides_unauthorized_kbs_and_execution(tmp_path: Path) -> None:
    (tmp_path / "kb/corpora").mkdir(parents=True)
    catalog = KnowledgeBaseCatalog(repo_root=tmp_path, managed_root=tmp_path / "kb/workspaces")
    catalog.create(
        CreateKnowledgeBaseRequest(
            kb_id="reader-kb",
            name="Reader KB",
            description="Visible metadata with restricted execution.",
            domain_id="general",
            purposes=frozenset({"verification"}),
        )
    )
    policy = AccessPolicy(
        (AccessGrant(principal_id="reader", kb_id="reader-kb", roles=frozenset({KBRole.READER})),)
    )
    client = TestClient(
        create_kb_workspace_app(
            token=TOKEN, catalog=catalog, access_policy=policy, principal_id="reader"
        )
    )
    assert client.get("/api/kbs", headers=_headers()).json()["count"] == 1
    denied = client.post(
        "/api/kbs/reader-kb/infer",
        headers=_headers(),
        json={"request_id": "denied", "operation": "verify"},
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "knowledge base is unavailable"
