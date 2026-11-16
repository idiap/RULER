# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Token-protected API and visual workspace for named formal knowledge bases."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from ruler.interfaces.kb_conversation import (
    CodexExecError,
    ConversationClient,
    KBConversationRequest,
    KBConversationService,
)
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import (
    AddKBArtifactRequest,
    CreateKnowledgeBaseRequest,
    KBInferenceRequest,
    KnowledgeBase,
)
from ruler.kb.workspace_inference import KBInferenceService
from ruler.kb.workspace_governance import (
    AccessPolicy,
    InferenceQuota,
    KBPermission,
    MutationCoordinator,
    ReleaseEvidence,
    ReleaseStage,
    execution_boundary,
    kb_etag,
)
from ruler.kb.workspace_experience import (
    InferenceRunStore,
    ReleaseSearchIndex,
    compare_releases,
    layered_graph,
    query_editor_model,
)


class MetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    lifecycle: str | None = None
    tags: frozenset[str] | None = None


class ReleaseTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: ReleaseStage
    evidence: tuple[ReleaseEvidence, ...]


def create_kb_workspace_app(
    *,
    token: str,
    catalog: KnowledgeBaseCatalog | None = None,
    access_policy: AccessPolicy | None = None,
    principal_id: str = "workspace-owner",
    conversation_client: ConversationClient | None = None,
) -> FastAPI:
    """Build a local authenticated application over one catalog instance."""
    if len(token) < 16:
        raise ValueError("KB workspace token must contain at least 16 characters")
    active_catalog = catalog or KnowledgeBaseCatalog()
    inference = KBInferenceService(active_catalog)
    run_store = InferenceRunStore(
        active_catalog.managed_root / ".inference-runs", active_catalog, inference
    )
    mutations = MutationCoordinator(active_catalog.managed_root / ".audit" / "events.jsonl")
    inference_quota = InferenceQuota(4)
    conversation_quota = InferenceQuota(2)
    conversation = KBConversationService(
        active_catalog, client=conversation_client, inference=inference
    )
    app = FastAPI(title="Ruler Knowledge Base Workspace", version="1.0")

    def authorize(
        authorization: str | None = Header(default=None),
        access_token: str | None = Query(default=None, alias="token"),
    ) -> None:
        supplied = access_token
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ")
        if supplied is None or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="valid workspace token required")

    def authorize_bearer(
        authorization: str | None = Header(default=None),
    ) -> None:
        supplied = None
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ")
        if supplied is None or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="valid bearer token required")

    def require(kb_id: str, permission: KBPermission) -> None:
        if access_policy is None:
            return
        try:
            access_policy.require(principal_id, kb_id, permission)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "kb-workspace"}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authorize)])
    def index() -> str:
        return render_kb_workspace_html(token)

    @app.get("/api/kbs", dependencies=[Depends(authorize)])
    def list_kbs() -> dict[str, Any]:
        visible = active_catalog.list()
        if access_policy is not None:
            visible = access_policy.visible_kbs(principal_id, visible)
        items = [_public_kb(item, detail=False) for item in visible]
        return {"knowledge_bases": items, "count": len(items)}

    @app.post("/api/kbs", dependencies=[Depends(authorize)])
    def create_kb(
        payload: CreateKnowledgeBaseRequest,
        response: Response,
        x_kb_confirm: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _confirm(x_kb_confirm, f"create:{payload.kb_id}")
        try:
            kb = active_catalog.create(payload)
            response.headers["ETag"] = kb_etag(kb)
            return _public_kb(kb, detail=True)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/kbs/{kb_id}", dependencies=[Depends(authorize)])
    def get_kb(kb_id: str, response: Response) -> dict[str, Any]:
        require(kb_id, KBPermission.READ_METADATA)
        try:
            kb = active_catalog.get(kb_id)
            response.headers["ETag"] = kb_etag(kb)
            return _public_kb(kb, detail=True)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/kbs/{kb_id}", dependencies=[Depends(authorize)])
    def update_kb(
        kb_id: str,
        payload: MetadataUpdate,
        response: Response,
        x_kb_confirm: str | None = Header(default=None),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        _confirm(x_kb_confirm, f"update:{kb_id}")
        require(kb_id, KBPermission.EDIT)
        try:
            result = mutations.execute(
                kb_id=kb_id,
                actor_id="workspace-owner",
                action="update_metadata",
                idempotency_key=idempotency_key or "",
                request=payload.model_dump(mode="json", exclude_none=True),
                if_match=if_match or "",
                load=lambda: active_catalog.get(kb_id),
                mutate=lambda _kb: active_catalog.update_metadata(
                    kb_id, **payload.model_dump(exclude_none=True)
                ),
            )
            updated = KnowledgeBase.model_validate(result.value)
            response.headers["ETag"] = result.etag
            response.headers["Idempotent-Replay"] = str(result.replayed).lower()
            return _public_kb(updated, detail=True)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/kbs/{kb_id}/artifacts", dependencies=[Depends(authorize)])
    def add_artifact(
        kb_id: str,
        payload: AddKBArtifactRequest,
        response: Response,
        x_kb_confirm: str | None = Header(default=None),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        _confirm(x_kb_confirm, f"add:{kb_id}:{payload.artifact_id}")
        require(kb_id, KBPermission.EDIT)
        try:
            result = mutations.execute(
                kb_id=kb_id,
                actor_id="workspace-owner",
                action="add_artifact",
                idempotency_key=idempotency_key or "",
                request=payload.model_dump(mode="json"),
                if_match=if_match or "",
                load=lambda: active_catalog.get(kb_id),
                mutate=lambda _kb: active_catalog.add_artifact(kb_id, payload),
            )
            response.headers["ETag"] = result.etag
            response.headers["Idempotent-Replay"] = str(result.replayed).lower()
            return _public_kb(KnowledgeBase.model_validate(result.value), detail=True)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except (OSError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/kbs/{kb_id}/releases", dependencies=[Depends(authorize)])
    def releases(kb_id: str) -> dict[str, Any]:
        require(kb_id, KBPermission.READ_METADATA)
        try:
            values = active_catalog.releases(kb_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "kb_id": kb_id,
            "releases": [
                {
                    **item.model_dump(mode="json"),
                    "execution_boundary": execution_boundary(item).model_dump(mode="json"),
                }
                for item in values
            ],
        }

    @app.post("/api/kbs/{kb_id}/releases/transition", dependencies=[Depends(authorize)])
    def transition_release(
        kb_id: str,
        payload: ReleaseTransitionRequest,
        x_kb_confirm: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _confirm(x_kb_confirm, f"release:{kb_id}:{payload.target.value}")
        require(
            kb_id,
            (
                KBPermission.PUBLISH
                if payload.target in {ReleaseStage.PUBLISHED, ReleaseStage.RETIRED}
                else KBPermission.REVIEW
            ),
        )
        try:
            value = active_catalog.transition_release(kb_id, payload.target, payload.evidence)
            return {
                **value.model_dump(mode="json"),
                "execution_boundary": execution_boundary(value).model_dump(mode="json"),
            }
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/search", dependencies=[Depends(authorize)])
    def search(q: str, kb_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        if kb_id is not None:
            require(kb_id, KBPermission.SEARCH)
        try:
            if kb_id is not None or access_policy is None:
                hits = active_catalog.search(q, kb_id=kb_id, limit=limit)
            else:
                visible = access_policy.visible_kbs(principal_id, active_catalog.list())
                hits = tuple(
                    hit
                    for item in visible
                    for hit in active_catalog.search(q, kb_id=item.kb_id, limit=limit)
                )[:limit]
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if access_policy is None:
            public_hits = [item.model_dump(mode="json") for item in hits]
        else:
            public_hits = []
            for hit in hits:
                kb = active_catalog.get(hit.kb_id)
                artifact = next(
                    (
                        item
                        for item in kb.current_version.artifacts
                        if item.artifact_id == hit.artifact_id
                    ),
                    None,
                )
                public_hits.append(
                    access_policy.search_hit_view(principal_id, hit, artifact=artifact)
                )
        return {"query": q, "hits": public_hits}

    @app.get("/api/search/indexed", dependencies=[Depends(authorize)])
    def indexed_search(
        q: str,
        kb_id: str,
        version_id: str | None = None,
        language: list[str] = Query(default=[]),
        formalism: list[str] = Query(default=[]),
        status: list[str] = Query(default=[]),
        include_content: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        require(kb_id, KBPermission.SEARCH)
        try:
            index = ReleaseSearchIndex.build(active_catalog, kb_id, version_id)
            if access_policy is not None and not access_policy.allows(
                principal_id, kb_id, KBPermission.READ_SOURCE
            ):
                include_content = False
            fields = frozenset({"metadata", "content"} if include_content else {"metadata"})
            return index.search(
                q,
                languages=set(language),
                formalisms=set(formalism),
                statuses=set(status),
                visible_fields=fields,
                limit=limit,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/kbs/{kb_id}/compare", dependencies=[Depends(authorize)])
    def compare(
        kb_id: str,
        right_kb_id: str,
        left_version_id: str | None = None,
        right_version_id: str | None = None,
    ) -> dict[str, Any]:
        require(kb_id, KBPermission.READ_METADATA)
        require(right_kb_id, KBPermission.READ_METADATA)
        try:
            return compare_releases(
                active_catalog,
                kb_id,
                right_kb_id,
                left_version_id=left_version_id,
                right_version_id=right_version_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/kbs/{kb_id}/query-editor", dependencies=[Depends(authorize)])
    def query_editor(kb_id: str, version_id: str | None = None) -> dict[str, Any]:
        require(kb_id, KBPermission.QUERY)
        try:
            return query_editor_model(active_catalog, kb_id, version_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/kbs/{kb_id}/graph", dependencies=[Depends(authorize)])
    def graph(kb_id: str) -> dict[str, Any]:
        require(kb_id, KBPermission.READ_METADATA)
        try:
            kb = active_catalog.get(kb_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return layered_graph(kb)

    @app.get("/api/kbs/{kb_id}/artifacts/{artifact_id}", dependencies=[Depends(authorize)])
    def artifact(kb_id: str, artifact_id: str) -> dict[str, Any]:
        require(kb_id, KBPermission.READ_SOURCE)
        try:
            kb = active_catalog.get(kb_id)
            item = next(
                value for value in kb.current_version.artifacts if value.artifact_id == artifact_id
            )
            path = active_catalog.artifact_path(item)
        except (LookupError, StopIteration) as exc:
            raise HTTPException(status_code=404, detail="unknown knowledge-base artifact") from exc
        payload = path.read_bytes()
        truncated = len(payload) > 50_000
        preview = payload[:50_000].decode("utf-8", errors="replace")
        return {
            "artifact": _public_artifact(item),
            "preview": preview,
            "preview_truncated": truncated,
        }

    @app.get("/api/kbs/{kb_id}/capabilities", dependencies=[Depends(authorize)])
    def capabilities(kb_id: str) -> dict[str, Any]:
        require(kb_id, KBPermission.READ_METADATA)
        try:
            return {"kb_id": kb_id, "capabilities": inference.capabilities(kb_id)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/chat/status", dependencies=[Depends(authorize)])
    def chat_status() -> dict[str, Any]:
        """Report whether the isolated Codex conversational backend is available."""
        return conversation.status()

    @app.post("/api/kbs/{kb_id}/chat", dependencies=[Depends(authorize)])
    def chat(kb_id: str, payload: KBConversationRequest) -> dict[str, Any]:
        """Answer against one pinned KB snapshot and optionally run formal inference."""
        require(kb_id, KBPermission.SEARCH)
        include_source_content = access_policy is None or access_policy.allows(
            principal_id, kb_id, KBPermission.READ_SOURCE
        )
        may_execute = access_policy is None or access_policy.allows(
            principal_id, kb_id, KBPermission.EXECUTE
        )
        try:
            with conversation_quota.reserve():
                return conversation.converse(
                    kb_id,
                    payload,
                    include_source_content=include_source_content,
                    may_execute=may_execute,
                ).model_dump(mode="json")
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CodexExecError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    @app.post("/api/kbs/{kb_id}/infer", dependencies=[Depends(authorize)])
    def infer(kb_id: str, payload: KBInferenceRequest) -> dict[str, Any]:
        require(kb_id, KBPermission.EXECUTE)
        try:
            with inference_quota.reserve():
                return inference.execute(kb_id, payload).model_dump(mode="json")
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    @app.post("/api/kbs/{kb_id}/runs", dependencies=[Depends(authorize)])
    def create_run(kb_id: str, payload: KBInferenceRequest) -> dict[str, Any]:
        require(kb_id, KBPermission.EXECUTE)
        try:
            with inference_quota.reserve():
                return run_store.execute(kb_id, payload)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}", dependencies=[Depends(authorize)])
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            value = run_store.get(run_id)
            require(value["kb_id"], KBPermission.QUERY)
            return value
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/replay", dependencies=[Depends(authorize)])
    def replay_run(run_id: str) -> dict[str, Any]:
        try:
            prior = run_store.get(run_id)
            require(prior["kb_id"], KBPermission.EXECUTE)
            with inference_quota.reserve():
                return run_store.replay(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    from ruler.interfaces.cbr_workspace import create_cbr_workspace_router

    app.include_router(
        create_cbr_workspace_router(
            authorize_bearer, outcome_root=active_catalog.managed_root / ".cbr"
        )
    )

    return app


def _confirm(supplied: str | None, expected: str) -> None:
    if supplied != expected:
        raise HTTPException(status_code=409, detail=f"write requires X-KB-Confirm: {expected}")


def _public_artifact(item) -> dict[str, Any]:
    return item.model_dump(mode="json", exclude={"path"})


def _public_kb(kb: KnowledgeBase, *, detail: bool) -> dict[str, Any]:
    current = kb.current_version
    base = {
        "kb_id": kb.kb_id,
        "name": kb.name,
        "description": kb.description,
        "domain_id": kb.domain_id,
        "purposes": sorted(item.value for item in kb.purposes),
        "tags": sorted(kb.tags),
        "owner": kb.owner,
        "access_mode": kb.access_mode,
        "lifecycle": kb.lifecycle,
        "source_kind": kb.source_kind,
        "current_version_id": kb.current_version_id,
        "revision_count": len(kb.versions),
        "artifact_count": len(current.artifacts),
        "formalisms": sorted(item.value for item in kb.formalisms),
        "roles": sorted({item.role.value for item in current.artifacts}),
    }
    if detail:
        base["versions"] = [
            {
                "version_id": version.version_id,
                "revision": version.revision,
                "status": version.status,
                "parent_version_id": version.parent_version_id,
                "created_at": version.created_at.isoformat(),
                "content_sha256": version.content_sha256,
                "change_summary": version.change_summary,
                "artifacts": [_public_artifact(item) for item in version.artifacts],
            }
            for version in kb.versions
        ]
    return base


def render_kb_workspace_html(token: str) -> str:
    """Return the dynamic three-pane KB portfolio and inference workspace."""
    safe_token = token.replace("\\", "\\\\").replace("'", "\\'")
    return _HTML.replace("__TOKEN__", safe_token)


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ruler · Knowledge Base Workspace</title>
<style>
:root{--ink:#17211b;--muted:#667169;--paper:#f5f5ef;--panel:#fff;--line:#dfe2d9;--green:#1f6b4f;--lime:#d9f266;--blue:#4169a1;--amber:#b87519;--red:#a13a3a}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 Inter,ui-sans-serif,system-ui}button,input,select,textarea{font:inherit}:focus-visible{outline:3px solid var(--blue);outline-offset:2px}.skip{position:fixed;left:8px;top:-80px;background:white;color:var(--ink);padding:10px;z-index:20}.skip:focus{top:8px}header{height:72px;padding:15px 24px;display:flex;align-items:center;gap:16px;border-bottom:1px solid var(--line);background:#17211b;color:white}.mark{width:38px;height:38px;border-radius:12px;background:var(--lime);color:#17211b;display:grid;place-items:center;font-weight:900}.brand h1{font-size:17px;margin:0}.brand div{color:#b8c1ba;font-size:12px}.status{margin-left:auto;color:#d9f266}.layout{display:grid;grid-template-columns:290px minmax(460px,1fr) 360px;height:calc(100vh - 72px)}aside,main{overflow:auto}.left{border-right:1px solid var(--line);padding:18px}.right{border-left:1px solid var(--line);padding:18px;background:#fafaf6}main{padding:22px}.eyebrow{font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:var(--muted);font-weight:800}.toolbar{display:flex;gap:8px;margin:12px 0}.toolbar input,.field{width:100%;border:1px solid var(--line);background:white;border-radius:9px;padding:9px}.kb-card{width:100%;text-align:left;border:1px solid var(--line);border-radius:12px;background:white;padding:13px;margin:7px 0;cursor:pointer}.kb-card.active{border-color:var(--green);box-shadow:0 0 0 2px #1f6b4f20}.kb-card strong{display:block}.meta{font-size:11px;color:var(--muted);margin-top:5px}.tag{display:inline-block;padding:2px 7px;border-radius:10px;background:#edf0e9;margin:4px 3px 0 0;font-size:10px}.hero{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}.hero h2{font-size:30px;line-height:1.1;margin:5px 0}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:22px 0}.metric{background:white;border:1px solid var(--line);border-radius:12px;padding:13px}.metric b{display:block;font-size:21px}.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:16px}.tabs button{border:0;background:none;padding:10px 13px;cursor:pointer}.tabs button.active{color:var(--green);border-bottom:3px solid var(--green);font-weight:700}.pane{display:none}.pane.active{display:block}.artifact{display:grid;grid-template-columns:1fr auto auto;gap:10px;background:white;border:1px solid var(--line);padding:11px;border-radius:10px;margin:7px 0;cursor:pointer}.badge{font-size:10px;padding:3px 7px;border-radius:10px;background:#edf0e9}.btn{border:0;border-radius:9px;padding:9px 12px;background:var(--green);color:white;cursor:pointer}.btn.secondary{background:#e9ece5;color:var(--ink)}.btn:disabled{opacity:.55;cursor:not-allowed}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#17211b;color:#dce6de;padding:13px;border-radius:10px;max-height:420px;overflow:auto}.empty{padding:25px;border:1px dashed #bfc5bb;border-radius:12px;color:var(--muted);text-align:center}.search-hit{padding:11px;border-bottom:1px solid var(--line)}.graph{position:relative;min-height:380px;background:white;border:1px solid var(--line);border-radius:14px;overflow:auto;padding:30px}.node{display:inline-flex;vertical-align:top;width:170px;min-height:90px;margin:12px;padding:12px;border-radius:12px;border:1px solid var(--line);background:#fff;box-shadow:0 3px 10px #0000000b}.node.rules{border-top:4px solid var(--green)}.node.source{border-top:4px solid var(--blue)}.node.interpretation{border-top:4px solid var(--amber)}label{display:block;font-size:11px;font-weight:700;margin:10px 0 4px}textarea{min-height:90px;resize:vertical}.notice{padding:10px;border-left:4px solid var(--amber);background:#fff8e8;margin:10px 0}.chat-log{display:flex;flex-direction:column;gap:12px;min-height:240px;max-height:55vh;overflow:auto;padding:4px}.message{max-width:88%;padding:12px 14px;border-radius:14px;background:white;border:1px solid var(--line);white-space:pre-wrap}.message.user{align-self:flex-end;background:#e7f1eb;border-color:#b8d2c5}.message.assistant{align-self:flex-start}.citations{margin-top:9px;padding-top:8px;border-top:1px solid var(--line)}.citation{display:block;border:0;background:none;color:var(--blue);padding:3px 0;text-align:left;cursor:pointer}.chat-compose{border-top:1px solid var(--line);margin-top:14px;padding-top:12px}.chat-actions{display:flex;align-items:center;gap:10px}.chat-actions label{margin:0;font-weight:500}.suggestions{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.suggestion{border:1px solid var(--line);background:white;border-radius:14px;padding:5px 9px;cursor:pointer}.danger{color:var(--red)}dialog{border:0;border-radius:14px;padding:22px;max-width:480px;box-shadow:0 20px 70px #0004}dialog::backdrop{background:#17211b99}@media(max-width:1050px){.layout{grid-template-columns:240px 1fr}.right{display:none}}@media(max-width:700px){.layout{display:block;height:auto}.left{border:0}.metric-grid{grid-template-columns:repeat(2,1fr)}.tabs{overflow-x:auto}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style></head><body><a href="#main" class="skip">Skip to workspace</a><header><div class="mark" aria-hidden="true">R</div><div class="brand"><h1>Knowledge Base Workspace</h1><div>Formal knowledge · evidence · inference</div></div><div class="status" id="status" aria-live="polite">Connecting…</div></header>
<div class="layout"><aside class="left"><div class="eyebrow">Portfolio</div><div class="toolbar"><input id="filter" placeholder="Filter knowledge bases"><button class="btn" id="newKb">+</button></div><div id="kbList"></div></aside>
<main id="main" tabindex="-1"><div id="empty" class="empty">Choose a knowledge base from the portfolio.</div><div id="workspace" hidden><div class="hero"><div><div class="eyebrow" id="domain"></div><h2 id="title"></h2><p id="description"></p><div id="tags"></div></div><span class="badge" id="access"></span></div><div class="metric-grid"><div class="metric"><b id="artifactCount">0</b>Artifacts</div><div class="metric"><b id="revisionCount">0</b>Revisions</div><div class="metric"><b id="formalismCount">0</b>Formalisms</div><div class="metric"><b id="capabilityCount">0</b>Inference routes</div></div>
	<div class="tabs"><button data-tab="overview" class="active">Artifacts</button><button data-tab="chat">Ask KB</button><button data-tab="search">Search</button><button data-tab="graph">Graph</button><button data-tab="infer">Infer</button><button data-tab="versions">Versions</button></div>
	<section id="overview" class="pane active"><div id="artifacts"></div></section><section id="chat" class="pane"><div class="notice">Answers are generated by isolated <code>codex exec</code> from the selected immutable KB revision. Citations are verified by the workspace; formal conclusions come only from registered inference backends.</div><div id="chatLog" class="chat-log" aria-live="polite"><div class="message assistant">Ask what this knowledge base contains, how its rules relate, or request a bounded formal inference.</div></div><div id="chatSuggestions" class="suggestions"></div><div class="chat-compose"><label for="chatInput">Message</label><textarea id="chatInput" class="field" placeholder="What rules, facts, and evidence are represented in this knowledge base?"></textarea><div class="chat-actions"><button class="btn" id="sendChat">Ask KB</button><label><input type="checkbox" id="allowChatInference"> Allow bounded formal inference</label><span id="chatBackend" class="meta">Checking Codex…</span></div></div></section><section id="search" class="pane"><div class="toolbar"><input id="searchInput" aria-label="Search this knowledge base" placeholder="Search names, rules, facts and source text"><button class="btn" id="searchBtn">Search</button></div><div id="searchResults" aria-live="polite"></div></section><section id="graph" class="pane"><div class="graph" id="graphView" role="list" aria-label="Artifact dependency graph; each card includes its layer and dependency count"></div></section>
<section id="infer" class="pane"><div class="notice">Inference is pinned to the active immutable revision. Backend results describe only the selected formal encoding.</div><label for="operation">Operation</label><select id="operation" class="field"><option>query</option><option>verify</option><option>evaluate</option><option>assess</option></select><label for="inferArtifact">Artifact</label><select id="inferArtifact" class="field"></select><label for="query">Target ground atom</label><input id="query" class="field" placeholder="eligible(subject_a)"><label for="contrary">Explicit contrary (optional)</label><input id="contrary" class="field" placeholder="ineligible(subject_a)"><label for="facts">Scenario facts, one ground atom per line</label><textarea id="facts" class="field" placeholder="in_scope(subject_a)"></textarea><button class="btn" id="runInference">Run bounded inference</button><button class="btn secondary" id="replayInference" disabled>Replay pinned run</button><pre id="inferenceResult" aria-live="polite">No run yet.</pre></section><section id="versions" class="pane"><div id="versionList"></div></section></div></main>
<aside class="right"><div class="eyebrow">Inspector</div><h3 id="inspectorTitle">Nothing selected</h3><div id="inspectorMeta" class="meta"></div><pre id="preview">Select an artifact to inspect its bounded preview.</pre></aside></div>
<dialog id="createDialog"><form method="dialog"><h2>Create knowledge base</h2><label>ID</label><input class="field" id="createId" placeholder="my-policy-kb"><label>Name</label><input class="field" id="createName"><label>Description</label><textarea class="field" id="createDescription"></textarea><label>Domain</label><input class="field" id="createDomain" value="general"><label>Purposes (comma-separated)</label><input class="field" id="createPurposes" value="inference,exploration"><div class="toolbar"><button value="cancel" class="btn secondary">Cancel</button><button value="default" class="btn" id="createSubmit">Create</button></div><div id="createError" class="danger"></div></form></dialog>
<script>
const TOKEN='__TOKEN__';const headers={'Authorization':'Bearer '+TOKEN};let portfolio=[],selected=null,detail=null,capabilities=[],lastRun=null,chatHistory=[];
const $=id=>document.getElementById(id);async function api(path,options={}){options.headers={...headers,...(options.headers||{})};const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw new Error(data.detail||r.statusText);return data}function clear(el){while(el.firstChild)el.removeChild(el.firstChild)}function text(tag,value,cls){const e=document.createElement(tag);e.textContent=value;if(cls)e.className=cls;return e}
async function load(){const [data,chatStatus]=await Promise.all([api('/api/kbs'),api('/api/chat/status')]);portfolio=data.knowledge_bases;$('status').textContent=data.count+' knowledge bases · secured';$('chatBackend').textContent=chatStatus.available?'Codex ready · isolated':'Codex unavailable';$('sendChat').disabled=!chatStatus.available;renderList();if(portfolio.length)selectKb(portfolio[0].kb_id)}function renderList(){const q=$('filter').value.toLowerCase();clear($('kbList'));portfolio.filter(k=>[k.name,k.kb_id,k.domain_id,...k.formalisms].join(' ').toLowerCase().includes(q)).forEach(k=>{const b=text('button','', 'kb-card'+(selected===k.kb_id?' active':''));b.append(text('strong',k.name));b.append(text('div',k.domain_id+' · '+k.artifact_count+' artifacts','meta'));k.formalisms.forEach(x=>b.append(text('span',x,'tag')));b.onclick=()=>selectKb(k.kb_id);$('kbList').append(b)})}
async function selectKb(id){selected=id;chatHistory=[];resetChat();[detail,capabilities]=await Promise.all([api('/api/kbs/'+id),api('/api/kbs/'+id+'/capabilities').then(x=>x.capabilities)]);$('empty').hidden=true;$('workspace').hidden=false;$('title').textContent=detail.name;$('description').textContent=detail.description;$('domain').textContent=detail.domain_id+' · '+detail.lifecycle;$('access').textContent=detail.access_mode;$('artifactCount').textContent=detail.artifact_count;$('revisionCount').textContent=detail.revision_count;$('formalismCount').textContent=detail.formalisms.length;$('capabilityCount').textContent=capabilities.length;clear($('tags'));detail.tags.forEach(x=>$('tags').append(text('span',x,'tag')));renderArtifacts();renderVersions();renderGraph();renderList()}
function current(){return detail.versions.find(v=>v.version_id===detail.current_version_id)}function renderArtifacts(){clear($('artifacts'));clear($('inferArtifact'));const items=current().artifacts;if(!items.length)$('artifacts').append(text('div','This KB is empty. Add artifacts through the API or CLI to create a new revision.','empty'));items.forEach(a=>{const row=text('div','', 'artifact');row.append(text('strong',a.name));row.append(text('span',a.role,'badge'));row.append(text('span',a.formalism,'badge'));row.onclick=()=>inspect(a);$('artifacts').append(row);const o=text('option',a.name+' · '+a.formalism);o.value=a.artifact_id;$('inferArtifact').append(o)})}async function inspect(a){$('inspectorTitle').textContent=a.name;$('inspectorMeta').textContent=a.role+' · '+a.formalism+' · '+a.status+' · '+a.sha256;const d=await api('/api/kbs/'+selected+'/artifacts/'+a.artifact_id);$('preview').textContent=d.preview+(d.preview_truncated?'\n\n[preview truncated]':'')}
function renderVersions(){clear($('versionList'));detail.versions.slice().reverse().forEach(v=>{const e=text('div','', 'artifact');e.append(text('strong',v.version_id));e.append(text('span',v.status,'badge'));e.append(text('span',v.artifacts.length+' artifacts','badge'));e.title=v.change_summary;$('versionList').append(e)})}async function renderGraph(){const g=await api('/api/kbs/'+selected+'/graph');clear($('graphView'));if(!g.nodes.length)$('graphView').append(text('div','No artifacts to graph.','empty'));g.nodes.forEach(n=>{const e=text('div','', 'node '+n.role);e.setAttribute('role','listitem');e.tabIndex=0;e.append(text('strong',n.label));e.append(text('div',n.layer+' · '+n.formalism,'meta'));const incoming=g.edges.filter(x=>x.target===n.id).length;e.append(text('div',incoming+' dependencies','meta'));$('graphView').append(e)})}
function resetChat(){clear($('chatLog'));$('chatLog').append(text('div','Ask what this knowledge base contains, how its rules relate, or request a bounded formal inference.','message assistant'));clear($('chatSuggestions'))}function addMessage(role,content,citations=[],inferenceResult=null){const box=text('div',content,'message '+role);if(citations.length){const list=text('div','', 'citations');list.append(text('strong','Grounding'));citations.forEach(c=>{const b=text('button','↳ '+c.label,'citation');b.title=c.excerpt;if(c.artifact_id)b.onclick=()=>{const a=current().artifacts.find(x=>x.artifact_id===c.artifact_id);if(a)inspect(a)};list.append(b)});box.append(list)}if(inferenceResult){const p=text('pre',JSON.stringify(inferenceResult,null,2));box.append(p)}$('chatLog').append(box);$('chatLog').scrollTop=$('chatLog').scrollHeight}function renderSuggestions(items){clear($('chatSuggestions'));items.forEach(value=>{const b=text('button',value,'suggestion');b.onclick=()=>{$('chatInput').value=value;$('chatInput').focus()};$('chatSuggestions').append(b)})}async function sendChat(){const message=$('chatInput').value.trim();if(!message||!selected)return;const prior=chatHistory.slice(-12);addMessage('user',message);chatHistory.push({role:'user',content:message});$('chatInput').value='';$('sendChat').disabled=true;$('chatBackend').textContent='Codex is reading the pinned KB snapshot…';try{const d=await api('/api/kbs/'+selected+'/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,history:prior,allow_inference:$('allowChatInference').checked})});addMessage('assistant',d.answer,d.citations,d.inference_result);chatHistory.push({role:'assistant',content:d.answer});chatHistory=chatHistory.slice(-12);renderSuggestions(d.suggested_questions);$('chatBackend').textContent='Grounded in '+d.version_id}catch(e){addMessage('assistant','Unable to answer: '+e.message);$('chatBackend').textContent='Codex request failed'}finally{$('sendChat').disabled=false}}
$('filter').oninput=renderList;document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tabs button,.pane').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(b.dataset.tab).classList.add('active')});$('searchBtn').onclick=async()=>{const d=await api('/api/search?q='+encodeURIComponent($('searchInput').value)+'&kb_id='+encodeURIComponent(selected));clear($('searchResults'));d.hits.forEach(h=>{const e=text('div','', 'search-hit');e.append(text('strong',h.artifact_name||h.kb_name));e.append(text('div',h.snippet));e.append(text('div',(h.formalism||'metadata')+' · score '+h.score,'meta'));$('searchResults').append(e)})};
$('runInference').onclick=async()=>{const body={request_id:'ui-'+Date.now(),operation:$('operation').value,artifact_id:$('inferArtifact').value||null,query:$('query').value||null,contrary:$('contrary').value||null,asserted_facts:$('facts').value.split(/\n/).map(x=>x.trim()).filter(Boolean),parameters:{},max_models:100};try{const d=await api('/api/kbs/'+selected+'/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});lastRun=d.run_id;$('replayInference').disabled=false;$('inferenceResult').textContent=JSON.stringify(d,null,2)}catch(e){$('inferenceResult').textContent=e.message}};$('replayInference').onclick=async()=>{if(!lastRun)return;try{const d=await api('/api/runs/'+lastRun+'/replay',{method:'POST'});$('inferenceResult').textContent=JSON.stringify(d,null,2)}catch(e){$('inferenceResult').textContent=e.message}};
$('sendChat').onclick=sendChat;$('chatInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat()}};
$('newKb').onclick=()=>$('createDialog').showModal();$('createSubmit').onclick=async e=>{e.preventDefault();const id=$('createId').value;const body={kb_id:id,name:$('createName').value,description:$('createDescription').value,domain_id:$('createDomain').value,purposes:$('createPurposes').value.split(',').map(x=>x.trim()),tags:[]};try{await api('/api/kbs',{method:'POST',headers:{'Content-Type':'application/json','X-KB-Confirm':'create:'+id},body:JSON.stringify(body)});$('createDialog').close();await load();await selectKb(id)}catch(err){$('createError').textContent=err.message}};document.addEventListener('keydown',e=>{if(e.key==='/'&&document.activeElement.tagName!=='INPUT'&&document.activeElement.tagName!=='TEXTAREA'){e.preventDefault();$('filter').focus()}if(e.key==='Escape'&&$('createDialog').open)$('createDialog').close()});load().catch(e=>$('status').textContent='Error: '+e.message);
</script></body></html>"""


__all__ = ["create_kb_workspace_app", "render_kb_workspace_html"]
