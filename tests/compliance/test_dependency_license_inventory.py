# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Dependency-management and license-inventory regression tests."""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "proj_skills"
    / "compliance"
    / "dependency-license-inventory"
    / "scripts"
    / "generate_licenses_md.py"
)


def _inventory_module() -> dict[str, object]:
    return runpy.run_path(str(SCRIPT), run_name="dependency_license_inventory")


def test_all_declared_python_dependency_sections_are_managed() -> None:
    module = _inventory_module()
    dependencies = module["load_direct_dependencies"]()  # type: ignore[operator]

    assert dependencies["click"] == "direct runtime"
    assert dependencies["playwright"] == "direct dev"
    assert dependencies["hypothesis"] == "direct dev"
    assert dependencies["jsonschema"] == "direct runtime"
    assert dependencies["packaging"] == "direct dev"
    assert (ROOT / "uv.lock").is_file()


def test_npm_lock_inventory_covers_runtime_dev_and_platform_packages() -> None:
    module = _inventory_module()
    rows = module["build_npm_rows"]()  # type: ignore[operator]
    by_name = {row.name: row for row in rows}

    assert by_name["@openai/codex-sdk"].scope == "direct runtime"
    assert by_name["typescript"].scope == "direct dev"
    assert by_name["@esbuild/win32-x64"].scope == "transitive"
    assert all(row.version != "UNKNOWN" for row in rows)
    assert all(row.license != "UNKNOWN" for row in rows)


def test_committed_inventory_matches_locked_dependency_metadata() -> None:
    module = _inventory_module()
    rows = [*module["build_rows"](), *module["build_npm_rows"]()]  # type: ignore[operator]
    rows = sorted(rows, key=module["row_sort_key"])  # type: ignore[arg-type]
    rendered = module["render_document"](rows)  # type: ignore[operator]

    assert (ROOT / "docs" / "governance" / "LICENSES.md").read_text() == rendered
    assert "| Node | @openai/codex-sdk |" in rendered
    assert "| Python | clingo |" in rendered
    assert "Packages with unknown license metadata: 0" in rendered
