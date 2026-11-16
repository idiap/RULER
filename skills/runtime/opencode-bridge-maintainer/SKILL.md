---
name: opencode-bridge-maintainer
description: Maintain RULER compatibility with OpenCode by keeping AGENTS.md, .opencode/skills wrappers, .opencode/commands, bridge docs, workflow routes, hooks, and validation commands synchronized. Use when making the framework runnable or inspectable in OpenCode.
---

# OpenCode Bridge Maintainer

Keep OpenCode support explicit and validated.

## Procedure

1. Update `AGENTS.md` when setup, commands, or guardrails change.
2. Update `.opencode/skills/*/SKILL.md` when OpenCode should expose a new skill-routed workflow.
3. Update `.opencode/commands/*.md` when OpenCode should expose a slash command.
4. Keep `.opencode/skills` as wrappers over canonical RULER commands and repo-local `skills/`.
5. Update `docs/guides/opencode.md` with any user-facing workflow change.
6. Run `uv run ruler validate opencode`.
7. Run `uv run ruler validate skills`, `uv run ruler validate hooks`, and targeted tests after bridge changes.

## Gates

- Every OpenCode skill must have `SKILL.md` frontmatter with a matching `name`.
- Every OpenCode skill and command must mention at least one `uv run ruler` command.
- `AGENTS.md` must include setup, validation, `.opencode/skills`, and `.opencode/commands` discovery notes.
