---
name: ruler-prepare-request
description: Validate a structured product reasoning request and pin it to a published RULER knowledge release.
---

Use the connected RULER MCP server, started from a prepared checkout with `uv run ruler serve mcp`. The plugin supplies instructions, not a runtime, database, evidence, or credentials. If the four product tools are unavailable, report the missing connection; do not substitute demonstration workflows.

Call `ruler_prepare_request` with `kb_id` and a typed `request`: `request_id`, `operation`, an advertised `backend_id`, and applicable `artifact_id`, `query`, `contrary`, `asserted_facts`, and `parameters`.
Inspect KB capabilities through `ruler_prepare_knowledge` first. This boundary accepts structured inputs; translate and review natural-language intent before submitting it. Do not substitute synthetic profiles or demonstration cases. Unsupported capabilities, draft knowledge and preview execution remain blocked.
Pass the returned `prepared` object unchanged to execution. Request preparation is read-only and does not run a solver.
