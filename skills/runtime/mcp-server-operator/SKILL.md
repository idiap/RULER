---
name: mcp-server-operator
description: Maintain the RULER MCP server, allowlisted MCP tools/resources, read-only defaults, product workflow boundaries, and validation gates.
---

# MCP Server Operator

Use this skill when RULER needs to run through a Model Context Protocol client or when the MCP tool/resource contract changes.

## Responsibilities

- Keep `ruler/runtime/mcp_server.py` bounded to explicit resources and allowlisted tools.
- Keep workflow artifact writes blocked unless `allow_write=true`.
- Keep validation gates routed through named RULER validators, not arbitrary shell commands.
- Expose only prepare-knowledge, prepare-request, execute-reasoning and retrieve-results. Keep developer operations and provider configuration internal.
- Preserve release evidence gates, published KB pins, session-bound import plans and PostgreSQL artifact ownership.
- Update `docs/guides/mcp_server.md`, `.ruler/hooks.yaml`, `skills/SKILL_HOOKS.yaml`, and `data/use_cases/workflow_router.yaml` together when MCP behavior changes.

## Required Checks

```bash
uv run ruler validate api-config
uv run ruler validate mcp-server
uv run ruler validate skills
uv run ruler validate hooks
uv run ruler validate workflow-router
```
