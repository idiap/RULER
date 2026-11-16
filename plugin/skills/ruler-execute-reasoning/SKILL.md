---
name: ruler-execute-reasoning
description: Run a prepared RULER product request against its published KB and persist checked results.
---

Use the connected RULER MCP server, started from a prepared checkout with `uv run ruler serve mcp`. The plugin supplies instructions, not a runtime, database, evidence, or credentials. If the four product tools are unavailable, report the missing connection; do not substitute demonstration workflows.

Call `ruler_execute_reasoning` with the exact `prepared` object returned by request preparation and `allow_execute=true` when execution and result storage are authorized.
Execution revalidates release version and content digest. If knowledge changed, prepare the request again. Do not override release pins, preview restrictions or backend allowlists.
A completed response contains `run_id` and the native structured result. Preserve its conclusion, evidence, blockers and claim boundary. A blocked, unsupported or failed result is not a successful decision and has no completed run to retrieve.
