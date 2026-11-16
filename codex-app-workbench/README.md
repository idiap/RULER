<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Codex App Workbench

A small TypeScript repository for experimenting with the Codex SDK and every app
currently installed in your Codex environment.

It has two deliberately separate surfaces:

- `@openai/codex-sdk` starts, continues, and resumes Codex threads.
- `codex app-server` discovers installed/available apps dynamically. No Gmail,
  Calendar, Slack, Drive, Sites, or future app is hard-coded into the program.

The generic RPC explorer is read-only. Mutating app calls need a purpose-built
approval flow before they can be added.

## Requirements

- Node.js 18 or later
- A current `codex` CLI installation and authenticated Codex session
- Installed apps enabled in your ChatGPT/Codex workspace

For API-key automation, set `CODEX_API_KEY` only in the invoking shell. Do not
commit it or put it in repository-controlled scripts.

## Setup

```bash
npm install
npm run check
npm test
```

## Explore all your apps

```bash
# Exact enabled/callable state for installed apps
npm run apps

# Paginated catalog of apps available to this account/workspace
npm run app-catalog

# Build a read-only daily briefing from relevant callable apps
npm run brief

# Inspect another stable read-only app-server method
npm run build --silent
node dist/src/cli.js rpc mcpServerStatus/list '{"detail":"toolsAndAuthOnly"}'
```

Because discovery uses `app/installed` and `app/list`, a newly installed app
appears without a code change.

## Run Codex workflows

```bash
npm run chat -- "Inspect this repository and propose three useful app-powered workflows"
npm run chat -- "Use my available apps to prepare a concise daily briefing"
npm run chat -- --resume <thread-id> "Turn the selected idea into an implementation plan"
```

Codex decides which configured tools are relevant inside its governed runtime.
This workbench does not copy OAuth tokens into prompts or configuration files.
The briefing prompt requests read-only behavior, while actual enforcement remains
with each app's permissions and Codex approval policy; inspect any approval before
accepting it.

## Track the exact local protocol

App-server evolves with the Codex CLI. Generate types from the installed binary
after an upgrade:

```bash
npm run schemas
```

Generated schemas are intentionally ignored because they are version-specific.

## Architecture

```text
CLI
├── chat ─────────────── @openai/codex-sdk ── Codex thread
└── apps / safe rpc ─── codex app-server ─── installed app registry
                                             ├── Gmail
                                             ├── Google Calendar
                                             ├── Slack
                                             └── any other enabled app
```

## Security posture

- App inventory is queried locally from the authenticated Codex runtime.
- The repository stores no app tokens and logs no connector payloads.
- Raw RPC access is allowlisted to read-only methods.
- Sensitive writes should use explicit, operation-specific confirmation rather
  than adding `mcpServer/tool/call` to the generic explorer.

## Publish to GitHub

From this directory, after choosing the visibility you want:

```bash
git init
git add .
git commit -m "Initial Codex App Workbench"
gh repo create codex-app-workbench --private --source=. --remote=origin --push
```

Replace `--private` with `--public` only if you intend to publish the source.

## Official references

- [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)
- [Codex app-server](https://learn.chatgpt.com/docs/app-server)
- [MCP and Connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
