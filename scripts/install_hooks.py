# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Portable hook installer. It copies repository hook definitions into the local Git hooks
directory without assuming a Unix-only shell.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".githooks"
HOOK_FILES = (HOOKS_DIR / "pre-commit", HOOKS_DIR / "pre-push")


def main() -> None:
    """Command-line entrypoint for this module."""
    _run(["git", "config", "core.hooksPath", ".githooks"])
    if os.name != "nt":
        for hook_file in HOOK_FILES:
            mode = hook_file.stat().st_mode
            hook_file.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("Installed RULER hooks from .githooks")


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=REPO_ROOT, check=True)


if __name__ == "__main__":
    main()
