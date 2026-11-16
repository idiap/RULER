# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Documentation navigation and public-surface drift checks."""

from __future__ import annotations

import re
from pathlib import Path

from ruler.runtime.mcp_server import MCP_TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def test_documentation_index_links_to_core_user_and_maintainer_guides() -> None:
    index = (REPO_ROOT / "docs/README.md").read_text(encoding="utf-8")
    for relative in (
        "getting-started.md",
        "architecture/system_architecture.md",
        "concepts/trust-and-assurance.md",
        "reference/cli.md",
        "reference/http-api.md",
        "development/contributing.md",
        "operations/release-checklist.md",
    ):
        assert f"]({relative})" in index


def test_internal_markdown_links_resolve() -> None:
    errors: list[str] = []
    documents = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").rglob("*.md"))]
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            clean = target.split("#", 1)[0]
            if not clean or "://" in clean or clean.startswith("mailto:"):
                continue
            path = (document.parent / clean).resolve()
            if not path.exists():
                errors.append(f"{document.relative_to(REPO_ROOT)} -> {target}")
    assert not errors, "broken documentation links:\n" + "\n".join(errors)


def test_mcp_guide_names_the_complete_live_tool_surface() -> None:
    guide = (REPO_ROOT / "docs/guides/mcp_server.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in guide for name in MCP_TOOL_NAMES)
    assert "arbitrary shell" in guide.lower()
    assert "no case editing" in guide.lower()


def test_http_reference_covers_every_declared_workspace_route() -> None:
    reference = (REPO_ROOT / "docs/reference/http-api.md").read_text(encoding="utf-8")
    for route in (
        "/api/kbs",
        "/api/kbs/{kb_id}/infer",
        "/api/runs/{run_id}/replay",
        "/api/cbr/retrieve",
        "/api/cbr/verify",
        "/api/cbr/outcomes",
    ):
        assert route in reference
    for control in (
        "Authorization: Bearer",
        "X-KB-Confirm",
        "X-CBR-Confirm",
        "If-Match",
        "Idempotency-Key",
    ):
        assert control in reference
