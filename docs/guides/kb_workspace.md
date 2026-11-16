<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Knowledge Base Workspace

The Ruler KB Workspace is the end-user control surface for multiple named formal
knowledge bases. A knowledge base is not the same as a corpus: a corpus is a
hash-bound artifact inventory, while a KB adds a stable human-facing identity,
metadata, purposes, immutable revisions, formalism declarations, search, and
capability-routed inference.

## Start the visual workspace

```bash
uv run ruler validate kb-workspace
uv run ruler serve kb-workspace
```

The command creates an ephemeral access token, binds only to loopback, and prints the
authenticated local URL. The workspace provides:

- a portfolio of named KBs with domain, lifecycle, formalism and access filters;
- artifact and bounded-content inspection;
- lexical search over authorized metadata and textual artifacts;
- a dependency graph built from explicit artifact references;
- immutable revision history;
- evidence-gated draft, candidate, reviewed, published, and retired releases;
- truthful inference capabilities per artifact;
- typed query templates, release comparison, layered provenance graphs, and durable replay;
- ASP, Logical IR, Prolog cross-check, TPTP/Vampire, Lean, compliance,
  recommendation, optimization, and legal-assurance adapters.

All API and artifact routes require the token. Public payloads expose opaque IDs and
digests, never filesystem locations. Stored labels and source text are rendered with
DOM `textContent`, not executable HTML.

## CLI management

Existing corpora are automatically exposed as read-only KBs:

```bash
uv run ruler kb list
uv run ruler kb show regulatory-proof
uv run ruler kb search proportionality --kb legal-sr101-art36
uv run ruler kb capabilities regulatory-proof
uv run ruler kb releases regulatory-proof
uv run ruler kb compare regulatory-proof legal-sr101-art36
uv run ruler kb query-editor regulatory-proof
```

Create a managed KB. Mutations are dry-run unless `--apply` is present:

```bash
uv run ruler kb create \
  --id access-policy \
  --name "Access policy" \
  --description "Rules for controlled facility access." \
  --domain regulatory \
  --purpose compliance \
  --purpose verification

uv run ruler kb create ... --apply
uv run ruler kb rename access-policy "Facility access" --apply
```

Add a text artifact. This copies the content into the managed KB and publishes a new
immutable revision; it never mutates a prior revision:

```bash
uv run ruler kb add-artifact access-policy \
  --id access-rules \
  --name "Facility access rules" \
  --role rules \
  --formalism asp \
  --media-type text/x-asp \
  --file ./access.lp \
  --summary "Add reviewed access policy projection." \
  --apply
```

Run a bounded query against the active immutable revision:

```bash
uv run ruler kb infer regulatory-proof \
  --operation verify \
  --artifact regulatory-proof-asp-v1 \
  --query 'evaluation_outcome("rg_notice_obligation",alice,"satisfied")' \
  --contrary 'evaluation_outcome("rg_notice_obligation",alice,"violated")' \
  --fact 'in_scope(alice)' \
  --fact 'submitted_notice(alice)' \
  --fact 'within_deadline(alice)'
```

ASP requests accept only safe ground atoms. Model enumeration is bounded. If the
bound is exceeded, the result is blocked rather than inferred from a partial sample.
Target and explicit contrary support remain separate, and missing support is never
reported as domain falsity. Legal packets route only to assurance classification and
remain unfit for legal reliance.

Ordinary inference selects a published release. Managed drafts require an explicit
`parameters.allow_preview=true` request and return a visible non-reliance boundary.
Release transitions require digest-bound evidence in sequence:

```bash
uv run ruler kb release-transition access-policy candidate \
  --evidence ./validation-evidence.yaml --apply
```

Portable packages preserve artifact digests and are collision/traversal checked:

```bash
uv run ruler kb package-export regulatory-proof ./regulatory.kbpkg --apply
uv run ruler kb package-inspect ./regulatory.kbpkg
uv run ruler kb package-import ./regulatory.kbpkg       # dry-run
```

## Storage and revision behavior

Managed state lives under `kb/workspaces/<kb-id>/`:

```text
kb/workspaces/<kb-id>/kb.yaml
kb/workspaces/<kb-id>/artifacts/<artifact-id>/<filename>
kb/workspaces/.releases/<kb-id>/<release-id>.json
kb/workspaces/.inference-runs/<run-id>.json
kb/workspaces/.audit/events.jsonl
```

The KB ID is immutable. Display metadata can change without altering revision
digests. Adding content creates the next contiguous revision and binds every artifact
by SHA-256. Existing corpus manifests remain authoritative and are adapted read-only;
they are not copied or rewritten.

## API boundary

The authenticated application provides:

- `GET/POST /api/kbs`
- `GET/PATCH /api/kbs/{kb_id}`
- `POST /api/kbs/{kb_id}/artifacts`
- `GET /api/search`
- `GET /api/search/indexed`
- `GET/POST /api/kbs/{kb_id}/releases[/transition]`
- `GET /api/kbs/{kb_id}/compare`
- `GET /api/kbs/{kb_id}/query-editor`
- `GET /api/kbs/{kb_id}/graph`
- `GET /api/kbs/{kb_id}/artifacts/{artifact_id}`
- `GET /api/kbs/{kb_id}/capabilities`
- `POST /api/kbs/{kb_id}/infer`
- `POST /api/kbs/{kb_id}/runs`
- `GET/POST /api/runs/{run_id}[/replay]`

Metadata and artifact mutations require exact `X-KB-Confirm`, `If-Match`, and
`Idempotency-Key` headers. ETags, per-KB locks, idempotent replay, and append-only
audit prevent stale or duplicate divergent revisions. Optional RBAC separates reader,
reasoner, editor, reviewer, publisher, and administrator permissions with field-level
source redaction. Intake, previews, runs, solver resources, and concurrency are bounded.
