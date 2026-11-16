# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for cross-platform runtime assumptions.

The suite protects path normalization and hook execution from macOS-only or
shell-specific behavior so the framework can run on Linux and Windows too.
"""

from __future__ import annotations

import subprocess

from ruler.runtime.cross_platform import CROSS_PLATFORM_DOC, HOOK_INSTALLER
from ruler.runtime.hooks import run_hook
from ruler.paths import REPO_ROOT
from ruler.runtime.validation import validate_cross_platform


def test_cross_platform_validator_passes() -> None:
    """The named gate should summarize all supported platforms."""
    assert validate_cross_platform() == ["platforms=macos-linux-windows"]


def test_python_hook_installer_and_docs_exist() -> None:
    """Hook setup should be documented through a portable Python entrypoint."""
    assert HOOK_INSTALLER.exists()
    assert CROSS_PLATFORM_DOC.exists()
    assert "uv run python scripts/install_hooks.py" in CROSS_PLATFORM_DOC.read_text(
        encoding="utf-8"
    )


def test_hook_runner_uses_argument_lists(monkeypatch) -> None:
    """Hook execution should avoid shell parsing so commands work cross-platform."""
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    messages = run_hook("cross-platform")

    assert messages == ["ok", "ok", "ok"]
    assert isinstance(captured["args"], list)
    assert captured["kwargs"]["cwd"] == REPO_ROOT
    assert "shell" not in captured["kwargs"]
