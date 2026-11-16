---
name: cross-platform-runtime-guardian
description: Keep RULER runnable on macOS, Linux, and Windows by maintaining Python-based setup paths, shell-independent hook execution, repo-relative artifact identifiers, cross-platform docs, and portability validators. Use when changing setup scripts, hooks, CLI commands, generated paths, or platform support.
---

# Cross-Platform Runtime Guardian

Keep RULER portable across macOS, Linux, and Windows.

## Procedure

1. Prefer `uv run ruler ...` for framework commands.
2. Prefer `uv run python ...` for local scripts.
3. Keep required setup in Python when possible.
4. Avoid mandatory POSIX-only tools in docs, hooks, and validators.
5. Keep machine-readable artifact identifiers repo-relative with forward slashes.
6. Run `uv run ruler validate cross-platform`.
7. Run targeted tests and `uv run ruler validate all` after platform-sensitive changes.

## Gates

- `scripts/install_hooks.py` must exist as the cross-platform hook installer.
- `ruler/runtime/hooks.py` must not use `shell=True`.
- Hook commands in `.ruler/hooks.yaml` must parse into `uv run ...` argument lists.
- `README.md` and `docs/guides/cross_platform.md` must document Windows-compatible setup.
