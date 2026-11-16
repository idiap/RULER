# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Workflow hook runner. It loads hook definitions and executes configured commands with
argument-list subprocess calls so validation and artifact generation can be controlled
outside the CLI.
"""

from __future__ import annotations

import shlex
import subprocess

from ruler.io import read_yaml
from ruler.paths import HOOKS_FILE, REPO_ROOT
from ruler.schemas import WorkflowHook


def load_hooks() -> dict[str, WorkflowHook]:
    """Load hooks for the hooks workflow."""
    payload = read_yaml(HOOKS_FILE)
    hooks = [WorkflowHook.model_validate(item) for item in payload.get("hooks", [])]
    return {hook.hook: hook for hook in hooks}


def run_hook(hook_name: str) -> list[str]:
    """Run hook for the hooks workflow."""
    hooks = load_hooks()
    if hook_name not in hooks:
        known = ", ".join(sorted(hooks))
        raise ValueError(f"unknown hook {hook_name}; known hooks: {known}")

    messages: list[str] = []
    for command in hooks[hook_name].commands:
        command_args = shlex.split(command.command)
        result = subprocess.run(
            command_args,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.stdout.strip():
            messages.append(result.stdout.strip())
        if result.stderr.strip():
            messages.append(result.stderr.strip())
        if result.returncode != 0 and command.required:
            raise RuntimeError(
                f"hook {hook_name} command {command.name} failed with exit {result.returncode}"
            )
    return messages
