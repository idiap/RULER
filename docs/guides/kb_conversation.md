<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Conversational knowledge-base interface

The authenticated KB workspace includes an **Ask KB** tab for exploring a selected
knowledge base in natural language. It can summarize scope, explain artifacts and
relationships, answer grounded questions, and translate an explicit request into a
bounded formal inference.

## Start the interface

```bash
uv run ruler serve kb-workspace
```

Open the one-time loopback URL, select a knowledge base, and choose **Ask KB**. The
composer reports whether `codex exec` is available. Press Enter to send or Shift+Enter
for a new line. The server uses the existing Codex authentication and does not persist
conversation transcripts.

## Grounding model

Each turn is pinned to the selected KB's current immutable version. Its bounded snapshot
contains KB metadata, path-free artifact metadata, relevant excerpts selected by the
deterministic search layer, exact inference capabilities, and at most 12 history turns.

Codex returns source IDs rather than free-form citations. The server discards invented
IDs and resolves accepted citations against its own snapshot. Changing KBs clears the
browser-side history.

## Codex execution boundary

The adapter invokes:

```text
codex exec --ephemeral --ignore-user-config --skip-git-repo-check \
  --ignore-rules --disable shell_tool --disable web_search_request \
  --disable apps --disable browser_use --disable skill_search \
  --sandbox read-only --output-schema ... --output-last-message ... -C TEMP_DIR -
```

The temporary directory contains only the response schema. Shell, web, browser, app,
skill, hook, image, computer-use, and multi-agent features are disabled, so Codex cannot
browse the repository or external systems through this interface. The bounded snapshot
is supplied on standard input. Artifact text is marked as untrusted data so embedded
instructions are not treated as agent instructions. The process has a 120-second limit,
and only two requests may run concurrently.

## Formal inference

Codex does not establish a formal conclusion. If the user explicitly asks for inference,
checks **Allow bounded formal inference**, and has execute permission, Codex may propose a
request using an advertised artifact/backend pair. The server validates it as a
`KBInferenceRequest`, pins it to the current version, executes it through
`KBInferenceService`, and returns the formal result separately from the chat answer.

Draft inference remains release-governed. A permitted preview is labelled
**NON-RELIANCE PREVIEW**; otherwise execution may be blocked until the release carries
the required evidence.

## HTTP API

```bash
curl -X POST \
  -H "Authorization: Bearer $RULER_TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8766/api/kbs/regulatory-proof/chat \
  -d '{
    "message": "What rules and evidence are represented here?",
    "history": [],
    "allow_inference": false
  }'
```

Use `GET /api/chat/status` to inspect availability and isolation properties.
Authentication, KB visibility, search, source-read, and execute permissions are enforced
before a snapshot is built or an inference is run. Backend failure returns `503`;
concurrency saturation returns `429`.

Conversational answers are grounded explanations, not independent legal, fiscal,
regulatory, or technical determinations. The cited artifacts, formal result, human review,
and release evidence gates remain authoritative.
