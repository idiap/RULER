---
name: ruler-prepare-knowledge
description: Prepare and publish project knowledge for product reasoning, including guarded corpus imports and native batch stages.
---

Use the connected RULER MCP server, started from a prepared checkout with `uv run ruler serve mcp`. The plugin supplies instructions, not a runtime, database, evidence, or credentials. If the four product tools are unavailable, report the missing connection; do not substitute demonstration workflows.

Call `ruler_prepare_knowledge` with an `input.action`:
- `discover` lists registered projects and KBs; `inspect` shows a project or KB, its release evidence and supported backends.
- `plan_import` takes `project_id`, `corpus_id` and optional `kb_id`. `apply_import` takes its `plan_id` in the same MCP session and requires `allow_write=true`. Imports remain drafts.
- `create` takes a native KB `definition` (including the registered `domain_id`); `add_artifact` takes `kb_id` and a typed `artifact`. Both require `allow_write=true`.
- `transition` takes `kb_id`, `target` and existing hash-bound `evidence`, with `allow_write=true`. Preserve native draft → candidate → reviewed → published gates. Do not invent review or publication evidence.
- `batch_status` and `batch_stage` take a registered `batch_id`; execution also takes `stage`, `allow_write=true` and `allow_network=true`. Follow the native next-stage response. Missing prepared batch inputs remain blockers.
Raw documents and candidate artifacts are not executable knowledge. Formalization and required review must finish before preparing a reasoning request. The current native batch pipeline uses prepared project inputs; it is not an arbitrary document-to-KB service.
