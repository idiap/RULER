#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Audit neutral-core imports and public schema terminology."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_TREES = (
    REPO_ROOT / "ruler" / "contracts",
    REPO_ROOT / "ruler" / "domains" / "base.py",
    REPO_ROOT / "ruler" / "domains" / "registry.py",
)
FORBIDDEN_IMPORT_PREFIXES = tuple(
    f"ruler.domains.{path.name}"
    for path in (REPO_ROOT / "ruler/domains").iterdir()
    if path.is_dir() and not path.name.startswith("_")
)
APPLICATION_FIELD_TERMS = {
    "product",
    "product_family",
    "coverage",
    "coverage_scope",
    "customer",
    "client",
    "vehicle",
    "advisor",
}
# Intentional debt is explicit rather than silently accepted. Neutral v2 contracts start clean.
PUBLIC_CORE_TERM_ALLOWLIST: dict[str, set[str]] = {}


def _python_files(path: Path) -> list[Path]:
    return sorted(path.rglob("*.py")) if path.is_dir() else [path]


def audit() -> list[str]:
    errors: list[str] = []
    for root in CORE_TREES:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(REPO_ROOT).as_posix()
            for node in ast.walk(tree):
                imported: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = (node.module,)
                for module in imported:
                    if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        errors.append(
                            f"{relative}:{getattr(node, 'lineno', 0)}: forbidden core import {module}"
                        )
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    field = node.target.id
                    if (
                        field in APPLICATION_FIELD_TERMS
                        and field not in PUBLIC_CORE_TERM_ALLOWLIST.get(relative, set())
                    ):
                        errors.append(
                            f"{relative}:{node.lineno}: application field {field!r} in public neutral contract"
                        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    errors = audit()
    if errors:
        print("\n".join(errors))
        return 1
    print("domain coupling audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
