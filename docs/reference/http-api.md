<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# HTTP API reference

The local HTTP API is provided by the KB workspace:

```bash
uv run ruler serve kb-workspace
```

It binds only to loopback. The command prints an ephemeral token and local URL.

## Authentication and response controls

- KB visual and API routes accept `Authorization: Bearer TOKEN`; the printed visual
  URL may bootstrap the root workspace with `?token=TOKEN`.
- Every CBR route, including `/cases`, requires the bearer header. Query-string tokens
  are rejected on that surface.
- Responses use `Cache-Control: no-store`, a restrictive content security policy,
  `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`.
- Unknown and unauthorized objects use bounded, uniform errors. Filesystem paths and
  sensitive case/source fields are not returned.

Example:

```bash
curl -H "Authorization: Bearer $RULER_TOKEN" \
  http://127.0.0.1:8766/api/kbs
```

## Knowledge-base routes

| Method and path | Purpose |
|---|---|
| `GET /health` | Unauthenticated process health |
| `GET /` | Visual KB workspace |
| `GET /api/kbs` | List visible KBs |
| `POST /api/kbs` | Create a managed KB |
| `GET/PATCH /api/kbs/{kb_id}` | Inspect or update metadata |
| `POST /api/kbs/{kb_id}/artifacts` | Add an artifact as a new immutable revision |
| `GET /api/kbs/{kb_id}/releases` | List release envelopes and execution boundaries |
| `POST /api/kbs/{kb_id}/releases/transition` | Apply an evidence-gated lifecycle transition |
| `GET /api/search` | Search visible KB metadata and content |
| `GET /api/search/indexed` | Search a pinned release with field/formalism filters |
| `GET /api/kbs/{kb_id}/compare` | Compare two selected KB releases |
| `GET /api/kbs/{kb_id}/query-editor` | Return typed query templates |
| `GET /api/kbs/{kb_id}/graph` | Return the layered dependency/provenance graph |
| `GET /api/kbs/{kb_id}/artifacts/{artifact_id}` | Return a bounded authorized preview |
| `GET /api/kbs/{kb_id}/capabilities` | List truthful backend/operation routes |
| `GET /api/chat/status` | Report isolated `codex exec` availability and controls |
| `POST /api/kbs/{kb_id}/chat` | Ask grounded questions and optionally delegate formal inference |
| `POST /api/kbs/{kb_id}/infer` | Run bounded inference |
| `POST /api/kbs/{kb_id}/runs` | Run inference and retain a content-addressed record |
| `GET /api/runs/{run_id}` | Read a retained run |
| `POST /api/runs/{run_id}/replay` | Replay against its pinned inputs |

KB metadata and artifact mutations use an exact `X-KB-Confirm` value. Updates and
artifact additions also require the current `If-Match` ETag and an `Idempotency-Key`.
Stale mutations fail with `412`; a safe repeat returns the prior result with
`Idempotent-Replay: true`. Optional RBAC separates metadata read, source read, search,
query, execute, edit, review, publish, and administrative permissions.

Chat accepts an 8,000-character message, at most 12 bounded history turns, and an
`allow_inference` flag. It runs `codex exec` in an ephemeral, isolated, read-only
directory against a path-free snapshot of the current immutable version. The server
resolves returned citation IDs. Formal inference requires both request opt-in and execute
permission. See the [conversational interface guide](../guides/kb_conversation.md).

## CBR routes

| Method and path | Purpose |
|---|---|
| `GET /cases` | Accessible portfolio view |
| `GET /cases/{domain_id}` | One domain journey |
| `GET /api/cbr/libraries` | List case-library releases |
| `GET /api/cbr/libraries/{domain_id}` | Inspect a library manifest |
| `GET /api/cbr/cases/{domain_id}/{case_id}` | Read a redacted reviewed case |
| `POST /api/cbr/retrieve` | Deterministic bounded retrieval |
| `GET /api/cbr/compare` | Explain pairwise feature contributions |
| `POST /api/cbr/plan` | Build a non-executable adaptation preview |
| `POST /api/cbr/verify` | Verify the preview and retain a content-addressed run |
| `GET /api/cbr/runs/{run_id}` | Replay-safe verification record lookup |
| `GET /api/cbr/outcomes` | List redacted outcomes and return collection ETag |
| `POST /api/cbr/outcomes` | Retain one independently reviewed outcome |

Retrieval payload:

```json
{"domain_id": "spending", "top_k": 3}
```

Plan and verification payload:

```json
{
  "domain_id": "spending",
  "source_case_id": "spend-precedent-microscope-009"
}
```

Outcome retention requires all of:

- a strict `OutcomeObservation` body with `review_state: "reviewed"`;
- a known case ID;
- different `reviewer_id` and `original_proposer_id`;
- `X-CBR-Confirm: retain:OUTCOME_ID`;
- the collection ETag from `GET /api/cbr/outcomes` in `If-Match`;
- a non-empty `Idempotency-Key`.

The API never exposes CBR retention or verification as an MCP mutation.

## Limits and status codes

- CBR `top_k` is bounded to 10.
- Case and domain identifiers are length-bounded.
- Artifact previews are capped at 50,000 bytes and identify truncation.
- Concurrent inference is quota-controlled; saturation returns `429`.
- `401`: missing/invalid token; `404`: unavailable resource; `409`: confirmation or
  immutable-state conflict; `412`: stale ETag; `422`: malformed/bounded-input failure;
  `428`: required concurrency/idempotency header missing.

The FastAPI application is the schema authority. For embedded use, construct it with
`ruler.interfaces.kb_workspace.create_kb_workspace_app` and inspect its generated
OpenAPI schema.
