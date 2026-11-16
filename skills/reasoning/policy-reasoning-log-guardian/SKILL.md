---
name: policy-reasoning-log-guardian
description: Generate, validate, and interpret RULER reasoning logs in both machine-processable JSONL/JSON/YAML and human-readable Markdown/HTML. Use when reasoning traces, audit timelines, process logs, evidence-flow explanations, or customer-facing reasoning readouts are requested.
---

# Policy Reasoning Log Guardian

Use this skill to keep RULER reasoning logs explicit, inspectable, and automation-ready.

## Workflow

3. Inspect machine artifacts in `build/ruler/reasoning_logs/latest.jsonl`, `latest.json`, and `latest.yaml`.
4. Inspect human artifacts in `build/ruler/reasoning_logs/latest.md` and `latest.html`.
5. Generate catalogue-wide contracts with `uv run ruler workflow skill-reasoning-logs`.
6. Validate one profile per canonical skill and invocation-backed events with `uv run ruler validate skill-reasoning-logs`.

Catalogue profiles describe expected observability and are not evidence that a skill ran.
Only `build/ruler/skill_reasoning_logs/actual_events.jsonl` records real invocations.
Never infer execution from shared hook membership. Keep all explanations at artifact
level and exclude hidden chain-of-thought and secrets.

## Guardrails

- Logs describe artifact-level process evidence: source lineage, gate status, solver backend, selected artifacts, and decision impact.
- Human-facing logs should be reasoning-focused, not repetitive: group raw events into a small number of foci with the question answered, reasoning move, decision relevance, evidence basis, and artifact references.
- Do not present hidden chain-of-thought as a log. Human readouts must summarize observable workflow state.
- Every event needs artifact identifiers, gate status, event type, and decision impact.
- Prefer JSONL for downstream machines and Markdown/HTML for human review.
- If a log entry points to a missing artifact, treat that as a validation failure or routing issue.

## Expected Event Types

- `extraction`: candidate pool and source lineage became available.
- `formalization`: controlled units or drafts were built and gated.
- `solver`: MaxSMT or equivalent decision optimization ran.
- `package_solver`: bounded package context was produced for advisor review.
