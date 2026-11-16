---
name: ruler-retrieve-results
description: Retrieve a completed RULER run with its result, release pin and auditable evidence.
---

Use the connected RULER MCP server, started from a prepared checkout with `uv run ruler serve mcp`. The plugin supplies instructions, not a runtime, database, evidence, or credentials. If the four product tools are unavailable, report the missing connection; do not substitute demonstration workflows.

Call `ruler_retrieve_results` with the `run_id` returned by successful execution. The service validates the stored evidence digest and returns the prepared request and native result.
Use workspace artifact resources from returned `persistent_artifacts` when exact stored bytes are needed. Never request local file paths or another workspace's artifacts. Preserve release identifiers, evidence and claim boundaries when presenting results; do not claim a report or approval that the result does not contain.
