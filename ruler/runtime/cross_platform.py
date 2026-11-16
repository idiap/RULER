# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Cross-platform guardrails for repository execution. The checks keep hooks, artifact
identifiers, and setup instructions portable across macOS, Linux, and Windows-oriented
shells.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from ruler.io import read_yaml
from ruler.paths import CODE_ROOT, HOOKS_FILE, REPO_ROOT
from ruler.interfaces.skill_reasoning_logs import build_skill_reasoning_profiles
from ruler.schemas import WorkflowHook

CROSS_PLATFORM_DOC = REPO_ROOT / "docs" / "guides" / "cross_platform.md"
HOOK_INSTALLER = REPO_ROOT / "scripts" / "install_hooks.py"
README = REPO_ROOT / "README.md"
HOOK_RUNNER = CODE_ROOT / "ruler" / "runtime" / "hooks.py"


def validate_cross_platform_support() -> list[str]:
    """Validate cross platform support for the cross platform workflow."""
    errors: list[str] = []
    if not HOOK_INSTALLER.exists():
        errors.append("missing scripts/install_hooks.py")
    if not CROSS_PLATFORM_DOC.exists():
        errors.append("missing docs/guides/cross_platform.md")
    errors.extend(_validate_readme())
    errors.extend(_validate_hook_runner())
    errors.extend(_validate_hook_commands())
    errors.extend(_validate_reasoning_artifact_ids())
    return errors


def _validate_readme() -> list[str]:
    """Internal helper for validate readme in the cross platform workflow."""
    if not README.exists():
        return ["missing README.md"]
    content = README.read_text(encoding="utf-8")
    errors: list[str] = []
    for fragment in [
        "uv run python scripts/install_hooks.py",
        "macOS, Linux, and Windows",
        "uv run ruler validate cross-platform",
    ]:
        if fragment not in content:
            errors.append(f"README.md missing {fragment!r}")
    return errors


def _validate_hook_runner() -> list[str]:
    """Internal helper for validate hook runner in the cross platform workflow."""
    if not HOOK_RUNNER.exists():
        return ["missing ruler/runtime/hooks.py"]
    content = HOOK_RUNNER.read_text(encoding="utf-8")
    errors: list[str] = []
    if "shell=True" in content:
        errors.append("ruler/runtime/hooks.py must not use shell=True")
    if "shlex.split" not in content:
        errors.append("ruler/runtime/hooks.py should parse hook commands without a platform shell")
    return errors


def _validate_hook_commands() -> list[str]:
    """Internal helper for validate hook commands in the cross platform workflow."""
    payload = read_yaml(HOOKS_FILE)
    hooks = [WorkflowHook.model_validate(item) for item in payload.get("hooks", [])]
    errors: list[str] = []
    for hook in hooks:
        for command in hook.commands:
            try:
                parts = shlex.split(command.command)
            except ValueError as exc:
                errors.append(f"{hook.hook}/{command.name}: command is not shell-portable: {exc}")
                continue
            if not parts:
                errors.append(f"{hook.hook}/{command.name}: empty command")
                continue
            if parts[:2] != ["uv", "run"]:
                errors.append(f"{hook.hook}/{command.name}: command must start with 'uv run'")
            if command.command.startswith("./"):
                errors.append(
                    f"{hook.hook}/{command.name}: command must not require ./ shell syntax"
                )
    return errors


def _validate_reasoning_artifact_ids() -> list[str]:
    """Skill identifiers must remain portable across host platforms."""
    return [
        f"absolute skill identifier: {p.skill_id}"
        for p in build_skill_reasoning_profiles()
        if _looks_absolute(p.skill_id)
    ]


def _looks_absolute(value: str) -> bool:
    """Internal helper for looks absolute in the cross platform workflow."""
    if value.startswith("/"):
        return True
    if len(value) >= 3 and value[1] == ":" and value[2] in {"/", "\\"}:
        return True
    return Path(value).is_absolute()
