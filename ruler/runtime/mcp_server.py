# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""PostgreSQL-backed MCP adapter exposing bounded RULER operations.

Public tools and resources execute against database-backed workspace snapshots;
the internal local adapter is restricted to disposable workers and unit tests.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from inspect import signature
from pathlib import Path
from typing import Any, Literal

from ruler.runtime.api_config import load_generative_api_config
from ruler.runtime.mcp_projects import ProjectMCPService
from ruler.runtime.generative_transport import (
    ConfiguredApiTransport,
    ConfiguredApiTransportError,
)
from ruler.interfaces.cbr_workspace import (
    cbr_case_show as _cbr_case_show,
    cbr_compare as _cbr_compare,
    cbr_library_list as _cbr_library_list,
    cbr_plan as _cbr_plan,
    cbr_retrieve as _cbr_retrieve,
)
from ruler.io import repo_relative_posix
from ruler.paths import BUILD_DIR
from ruler.interfaces.workflow_graphs import (
    build_workflow_graph_model,
    write_workflow_graph_artifacts,
)
from ruler.interfaces.workflow_router import (
    build_router_catalogue,
    guide_workflow_intent,
    route_workflow_intent,
    write_workflow_router_artifacts,
)
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog
from ruler.kb.workspace_contracts import KBInferenceRequest
from ruler.kb.workspace_experience import ReleaseSearchIndex, plan_inference
from ruler.kb.workspace_inference import KBInferenceService

from ruler.runtime.product_workflows import (
    BACKENDS,
    WORKFLOWS,
    KnowledgeInput,
    PreparedRequest,
    ProductWorkflows,
)

MCP_TOOL_NAMES = [f"ruler_{name}" for name in WORKFLOWS]

MCP_GENERATIVE_WORKFLOWS = frozenset(
    {
        "autoformalization",
        "explanation",
        "extraction",
        "profile_explanation",
        "profile_extraction",
        "profile_reasoning",
        "reflection",
        "reflective_refinement",
        "translation",
        "workflow_routing",
    }
)

KB_EXECUTION_BACKENDS = BACKENDS

VALIDATION_TOOL_NAMES = {
    "api-config": "validate_generative_api_config",
    "contracts": "validate_contracts",
    "cross-platform": "validate_cross_platform",
    "hooks": "validate_hooks",
    "mcp-server": "validate_mcp_server",
    "reasoning-core": "validate_reasoning_core",
    "reasoning-log": "validate_reasoning_log",
    "skills": "validate_skills",
    "workflow-graphs": "validate_workflow_graphs",
    "workflow-router": "validate_workflow_router",
}

WORKFLOW_WRITERS: dict[str, Callable[[], dict[str, Path]]] = {
    "workflow-graphs": write_workflow_graph_artifacts,
    "workflow-router": write_workflow_router_artifacts,
}


def mcp_manifest() -> dict[str, Any]:
    """Describe only the four product workflows and their execution boundary."""
    return {
        "name": "ruler",
        "version": "1.0.0",
        "tools": MCP_TOOL_NAMES,
        "resources": [],
        "resource_templates": ["ruler://artifacts/{digest}"],
        "persistence": {
            "backend": "postgresql",
            "migrations": "alembic",
            "filesystem_fallback": False,
        },
        "safety": {
            "arbitrary_shell": False,
            "read_only_by_default": True,
            "workflow_writes_require_allow_write": True,
            "kb_import_requires_session_plan": True,
            "kb_execution_requires_allow_execute": True,
            "kb_execution_backend_allowlist": sorted(BACKENDS),
            "generative_network_requires_allow_network": True,
        },
    }


def list_workflow_routes() -> dict[str, Any]:
    """List workflow routes for the MCP server workflow."""
    return build_router_catalogue().model_dump(mode="json")


def route_intent(intent: str, top_k: int = 3) -> dict[str, Any]:
    """Expose workflow routing as a small MCP-safe tool payload."""
    packet = route_workflow_intent(intent, top_k=top_k)
    return packet.model_dump(mode="json")


def guide_intent(
    intent: str,
    top_k: int = 3,
    allow_network: bool = False,
) -> dict[str, Any]:
    """Interpret intent and return bounded guidance without executing a workflow."""

    try:
        packet = guide_workflow_intent(
            intent,
            top_k=top_k,
            allow_network=allow_network,
        )
    except ValueError as exc:
        return {"status": "blocked", "reason": str(exc)}
    return packet.model_dump(mode="json")


def validation_gate(name: str) -> dict[str, Any]:
    """Run a named validation gate through the MCP boundary and return structured status."""
    if name not in VALIDATION_TOOL_NAMES:
        return {
            "status": "blocked",
            "reason": f"unknown validation gate {name!r}",
            "allowed": sorted(VALIDATION_TOOL_NAMES),
        }
    from ruler.runtime import validation

    func = getattr(validation, VALIDATION_TOOL_NAMES[name])
    try:
        messages = func()
    except validation.ValidationErrorGroup as exc:
        return {"status": "fail", "gate": name, "errors": exc.errors}
    return {"status": "pass", "gate": name, "messages": messages}


def run_workflow(name: str, allow_write: bool = False) -> dict[str, Any]:
    """Run a bounded artifact workflow through the MCP boundary and report output paths."""
    if name not in WORKFLOW_WRITERS:
        return {
            "status": "blocked",
            "reason": f"unknown workflow {name!r}",
            "allowed": sorted(WORKFLOW_WRITERS),
        }
    if not allow_write:
        return {
            "status": "blocked",
            "reason": "workflow writes require allow_write=true",
            "workflow": name,
            "would_write_under": repo_relative_posix(BUILD_DIR),
        }
    paths = WORKFLOW_WRITERS[name]()
    return {
        "status": "written",
        "workflow": name,
        "artifacts": {label: repo_relative_posix(path) for label, path in sorted(paths.items())},
    }


def generative_api_config(workflow: str | None = None) -> dict[str, Any]:
    """Return a redacted view of the configured generative provider settings."""
    return load_generative_api_config().redacted_summary(workflow=workflow)


def generate_structured(
    *,
    workflow: str,
    prompt: str,
    output_schema: dict[str, Any],
    allow_network: bool = False,
) -> dict[str, Any]:
    """Run explicitly authorized structured generation through configured HTTPS APIs."""
    if workflow not in MCP_GENERATIVE_WORKFLOWS:
        return {
            "status": "blocked",
            "reason": f"unknown generative workflow {workflow!r}",
            "allowed": sorted(MCP_GENERATIVE_WORKFLOWS),
        }
    if not allow_network:
        return {
            "status": "blocked",
            "reason": "configured generation requires allow_network=true",
            "workflow": workflow,
        }
    if output_schema.get("type") != "object":
        return {"status": "blocked", "reason": "output_schema must describe an object"}
    try:
        config = load_generative_api_config()
        provider = config.selected_provider(workflow)
        transport = ConfiguredApiTransport(provider)
        result = transport.generate(prompt=prompt, output_schema=output_schema)
    except (ConfiguredApiTransportError, KeyError, OSError, ValueError) as exc:
        return {
            "status": "failed",
            "workflow": workflow,
            "reason": str(exc),
        }
    return {
        "status": "generated",
        "workflow": workflow,
        "provider": transport.provider,
        "model": transport.model,
        "result": result,
    }


def workflow_graph_resource() -> dict[str, Any]:
    """Return the generated workflow graph model as an MCP resource payload."""
    return build_workflow_graph_model()


def kb_list(*, catalog: KnowledgeBaseCatalog | None = None) -> dict[str, Any]:
    """List path-redacted knowledge bases through a read-only MCP boundary."""
    active = catalog or KnowledgeBaseCatalog()
    rows = [_kb_public(item, detail=False) for item in active.list()]
    return {"knowledge_bases": rows, "count": len(rows), "read_only": True}


def kb_show(kb_id: str, *, catalog: KnowledgeBaseCatalog | None = None) -> dict[str, Any]:
    """Show immutable KB and artifact metadata without filesystem paths or content."""
    active = catalog or KnowledgeBaseCatalog()
    return _kb_public(active.get(kb_id), detail=True)


def kb_search(
    kb_id: str,
    query: str,
    *,
    language: list[str] | None = None,
    formalism: list[str] | None = None,
    status: list[str] | None = None,
    include_content: bool = False,
    limit: int = 20,
    catalog: KnowledgeBaseCatalog | None = None,
) -> dict[str, Any]:
    """Search one release; source snippets are redacted unless explicitly requested."""
    active = catalog or KnowledgeBaseCatalog()
    index = ReleaseSearchIndex.build(active, kb_id)
    fields = frozenset({"metadata", "content"} if include_content else {"metadata"})
    return index.search(
        query,
        languages=set(language or ()),
        formalisms=set(formalism or ()),
        statuses=set(status or ()),
        visible_fields=fields,
        limit=limit,
    )


def kb_capabilities(kb_id: str, *, catalog: KnowledgeBaseCatalog | None = None) -> dict[str, Any]:
    """Report declared inference routes without executing them."""
    active = catalog or KnowledgeBaseCatalog()
    kb = active.get(kb_id)
    return {
        "kb_id": kb_id,
        "version_id": kb.current_version_id,
        "capabilities": KBInferenceService(active).capabilities(kb_id),
        "executed": False,
    }


def kb_plan(
    kb_id: str, operation: str, *, catalog: KnowledgeBaseCatalog | None = None
) -> dict[str, Any]:
    """Plan an inference using capability declarations only."""
    return plan_inference(catalog or KnowledgeBaseCatalog(), kb_id, operation)


def kb_execute(
    kb_id: str,
    request: dict[str, Any],
    *,
    allow_execute: bool = False,
    catalog: KnowledgeBaseCatalog | None = None,
) -> dict[str, Any]:
    """Execute only an explicitly selected allowlisted backend; never mutate a KB."""
    backend_id = request.get("backend_id")
    if not allow_execute:
        return {
            "status": "blocked",
            "reason": "KB execution requires allow_execute=true",
            "allowed_backends": sorted(KB_EXECUTION_BACKENDS),
        }
    if backend_id not in KB_EXECUTION_BACKENDS:
        return {
            "status": "blocked",
            "reason": "backend is not explicitly allowlisted",
            "allowed_backends": sorted(KB_EXECUTION_BACKENDS),
        }
    active = catalog or KnowledgeBaseCatalog()
    result = KBInferenceService(active).execute(kb_id, KBInferenceRequest.model_validate(request))
    return result.model_dump(mode="json")


def cbr_list_libraries() -> dict[str, Any]:
    """List immutable demonstration case libraries without local paths."""
    return _cbr_library_list()


def cbr_show_case(domain_id: str, case_id: str) -> dict[str, Any]:
    """Show one case with subject, evidence, party, and feature values redacted."""
    return _cbr_case_show(domain_id, case_id)


def cbr_retrieve_cases(domain_id: str, top_k: int = 3) -> dict[str, Any]:
    """Retrieve a bounded top-k from one canonical, immutable demonstration library."""
    return _cbr_retrieve(domain_id, top_k=top_k)


def cbr_compare_cases(domain_id: str, left_case_id: str, right_case_id: str) -> dict[str, Any]:
    """Compare cases using contribution evidence while keeping feature values redacted."""
    return _cbr_compare(domain_id, left_case_id, right_case_id)


def cbr_plan_adaptation(domain_id: str, source_case_id: str) -> dict[str, Any]:
    """Plan a non-executable adaptation; no MCP function can verify, retain, or mutate."""
    return _cbr_plan(domain_id, source_case_id)


def _kb_public(kb, *, detail: bool) -> dict[str, Any]:
    payload = {
        "kb_id": kb.kb_id,
        "name": kb.name,
        "description": kb.description,
        "project_id": kb.domain_id,
        "purposes": sorted(item.value for item in kb.purposes),
        "tags": sorted(kb.tags),
        "access_mode": kb.access_mode,
        "lifecycle": kb.lifecycle,
        "current_version_id": kb.current_version_id,
        "formalisms": sorted(item.value for item in kb.formalisms),
    }
    if detail:
        payload["versions"] = [
            {
                "version_id": version.version_id,
                "revision": version.revision,
                "status": version.status,
                "content_sha256": version.content_sha256,
                "artifacts": [
                    item.model_dump(mode="json", exclude={"path"}) for item in version.artifacts
                ],
            }
            for version in kb.versions
        ]
    return payload


def create_mcp_server(*, runtime=None, http_settings: dict | None = None):
    """Register database operations and the caller-supplied, session-local CBR context."""
    from ruler.persistence.workspace import PostgresMCPRuntime

    active = runtime or PostgresMCPRuntime()
    # Remote clients must not share import-plan authorization. The SDK session
    # object is stable across HTTP requests and is never supplied by a tool caller.
    from weakref import WeakKeyDictionary

    sessions = WeakKeyDictionary()

    def current_runtime():
        if http_settings is None:
            return active
        session = mcp.get_context().session
        if session not in sessions:
            sessions[session] = PostgresMCPRuntime(active.store, timeout=480)
        return sessions[session]

    def dispatch(operation, arguments):
        return current_runtime().invoke(operation, arguments)

    mcp = _create_mcp_server(dispatch=dispatch, server_settings=http_settings)

    @mcp.resource("ruler://artifacts/{digest}")
    def artifact_resource(digest: str) -> dict[str, Any]:
        """Read exact artifact bytes from this workspace's PostgreSQL objects."""
        return current_runtime().store.artifact(digest)

    return mcp


def _create_mcp_server(
    *, project_service=None, dispatch=None, operations=None, server_settings=None
):
    """Register the exact product surface, also used inside isolated workers."""
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    from pydantic import ValidationError
    from ruler.cli import _domain_registry

    mcp = FastMCP("ruler", **(server_settings or {}))
    service = ProductWorkflows(project_service or ProjectMCPService(_domain_registry))

    def tool(*, read_only=False):
        def register(func):
            @wraps(func)
            def local(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except ValidationError:
                    return {
                        "status": "blocked",
                        "reason": "product input or evidence schema is invalid",
                    }
                except (ValueError, LookupError):
                    return {
                        "status": "blocked",
                        "reason": "invalid input, unsupported operation, or unmet release gate",
                    }
                except OSError:
                    return {"status": "blocked", "reason": "product workspace data is unavailable"}

            if operations is not None:
                operations[func.__name__] = local

            @wraps(func)
            def invoke(*args, **kwargs):
                if dispatch is None:
                    return local(*args, **kwargs)
                bound = signature(func).bind(*args, **kwargs)
                bound.apply_defaults()
                # FastMCP parses schemas; the isolated worker receives plain JSON.
                from pydantic import BaseModel

                arguments = {
                    key: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
                    for key, value in bound.arguments.items()
                }
                return dispatch(func.__name__, arguments)

            return mcp.tool(
                annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=False)
            )(invoke)

        return register

    @tool()
    def ruler_prepare_knowledge(
        input: KnowledgeInput,
        allow_write: bool = False,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        """Discover projects/KBs; prepare and release knowledge using guarded actions.

        Imports create drafts. Publication requires native hash-bound validation,
        review and approval evidence. Batch stages use registered native inputs.
        """
        return service.prepare_knowledge(
            KnowledgeInput.model_validate(input),
            allow_write=allow_write,
            allow_network=allow_network,
        )

    @tool(read_only=True)
    def ruler_prepare_request(kb_id: str, request: KBInferenceRequest) -> dict[str, Any]:
        """Validate structured facts/query and bind them to published knowledge.

        Use prepare_knowledge/inspect to discover supported artifact/backend pairs.
        Natural language must be formalized and reviewed before this boundary.
        """
        return service.prepare_request(kb_id, KBInferenceRequest.model_validate(request))

    @tool()
    def ruler_execute_reasoning(
        prepared: PreparedRequest, allow_execute: bool = False
    ) -> dict[str, Any]:
        """Execute a prepared request and persist the checked result under a run ID."""
        return service.execute_reasoning(
            PreparedRequest.model_validate(prepared), allow_execute=allow_execute
        )

    @tool(read_only=True)
    def ruler_retrieve_results(run_id: str) -> dict[str, Any]:
        """Retrieve a completed run's structured result, release pin and evidence."""
        return service.retrieve_results(run_id)

    return mcp


def create_mcp_http_app(server):
    """Serve request/response MCP without a billable, idle server event stream."""
    from starlette.responses import Response

    application = server.streamable_http_app()

    async def app(scope, receive, send):
        # Streamable HTTP explicitly allows 405 when no standalone SSE listener
        # is offered. RULER has no unsolicited notifications or resumable events.
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and scope["path"] == server.settings.streamable_http_path
        ):
            await Response(status_code=405, headers={"Allow": "POST, DELETE"})(scope, receive, send)
        else:
            await application(scope, receive, send)

    return app


def main(
    *,
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Command-line entrypoint for this module."""
    from ruler.persistence.workspace import PostgresMCPRuntime

    import os

    from mcp.server.transport_security import TransportSecuritySettings

    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("unsupported MCP transport")
    settings = None
    if transport == "streamable-http":
        hosts = [
            item.strip()
            for item in os.environ.get("RULER_MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*").split(
                ","
            )
            if item.strip()
        ]
        settings = {
            "host": host,
            "port": port,
            "json_response": True,
            "stateless_http": False,
            "transport_security": TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                # Browser origins are rejected by default. Native MCP clients
                # do not send Origin; configure authentication at the hosting boundary.
                allowed_origins=[],
            ),
        }
    runtime = PostgresMCPRuntime(timeout=480 if settings else 600)
    runtime.store.check_ready()
    server = create_mcp_server(runtime=runtime, http_settings=settings)
    if settings:
        from starlette.responses import PlainTextResponse

        @server.custom_route("/healthz", methods=["GET"])
        async def healthz(request):
            return PlainTextResponse("ok")

        import uvicorn

        uvicorn.run(create_mcp_http_app(server), host=host, port=port)
        return
    server.run(transport=transport)
