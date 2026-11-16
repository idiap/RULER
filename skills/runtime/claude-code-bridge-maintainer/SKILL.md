---
name: claude-code-bridge-maintainer
description: Maintain RULER compatibility with Claude Code by keeping CLAUDE.md, .claude/skills wrappers, bridge docs, workflow routes, hooks, and validation commands synchronized. Use when making the framework runnable or inspectable in Claude Code.
---

# Claude Code Bridge Maintainer

Keep Claude Code support explicit and validated.

## Procedure

1. Update `CLAUDE.md` when setup, commands, or guardrails change.
2. Update `.claude/skills/*/SKILL.md` when Claude Code should expose a new slash-invoked workflow.
3. Keep `.claude/skills` as wrappers over canonical RULER commands and repo-local `skills/`.
4. Update `docs/guides/claude_code.md` with any user-facing workflow change.
5. Run `uv run ruler validate claude-code`.
6. Run `uv run ruler validate skills`, `uv run ruler validate hooks`, and targeted tests after bridge changes.

## Gates

- Every Claude Code skill must have `SKILL.md` frontmatter with a matching `name`.
- Every Claude Code skill must mention at least one `uv run ruler` command.
- `CLAUDE.md` must include setup, validation, and `.claude/skills` discovery notes.
