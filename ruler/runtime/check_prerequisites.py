# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Explicit offline preparation, kept separate from read-only validation gates."""

from pathlib import Path
import shutil


CHECK_WORKFLOWS = (
    "formalized-kb",
    "translation-control",
    "progressive-product-onboarding",
    "inference-dashboard",
    "skill-reasoning-logs",
    "workflow-graphs",
    "workflow-router",
)

CHECK_WORKFLOW_OPTIONS: dict[str, dict] = {}


def check_native_prerequisites() -> None:
    """Fail before writing artifacts when a required solver/browser is missing."""
    if shutil.which("swipl") is None:
        raise RuntimeError("SWI-Prolog is required; install it and put swipl on PATH")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            raise RuntimeError("Chromium is required; run uv run playwright install chromium")
