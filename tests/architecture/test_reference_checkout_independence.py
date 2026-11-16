# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Regression checks for independence from local upstream comparison checkouts."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_CHECKOUT_NAMES = ("ref", "ref_legal")
EXECUTABLE_SURFACES = (
    "ruler",
    "scripts",
    "skills",
    "proj_skills",
    "tests",
    ".claude",
    ".opencode",
    ".ruler",
    ".github",
    "config",
)
PROJECT_CONTROL_FILES = (
    "pyproject.toml",
    "uv.lock",
    "AGENTS.md",
    "CLAUDE.md",
)
TEXT_SUFFIXES = {".json", ".md", ".py", ".sh", ".toml", ".yaml", ".yml"}


def test_reference_checkouts_are_absent_and_ignored() -> None:
    """A clean clone must contain everything needed to run RULER."""

    ignore_lines = {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }

    for checkout_name in REFERENCE_CHECKOUT_NAMES:
        assert not (
            REPOSITORY_ROOT / checkout_name
        ).exists(), f"local comparison checkout {checkout_name!r} must be removed"
        assert f"/{checkout_name}/" in ignore_lines


def test_executable_surfaces_do_not_reference_comparison_checkouts() -> None:
    """Runtime code, client bridges, skills, and CI must not reach outside the repo."""

    forbidden_fragments = tuple(
        fragment
        for checkout_name in REFERENCE_CHECKOUT_NAMES
        for fragment in (f"{checkout_name}/", f"{checkout_name}\\\\")
    )
    violations: list[str] = []

    for surface_name in EXECUTABLE_SURFACES:
        surface = REPOSITORY_ROOT / surface_name
        if not surface.exists():
            continue
        for path in surface.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(fragment in text for fragment in forbidden_fragments):
                violations.append(path.relative_to(REPOSITORY_ROOT).as_posix())

    for file_name in PROJECT_CONTROL_FILES:
        path = REPOSITORY_ROOT / file_name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(fragment in text for fragment in forbidden_fragments):
            violations.append(path.relative_to(REPOSITORY_ROOT).as_posix())

    assert violations == [], f"comparison-checkout references found: {sorted(violations)}"
