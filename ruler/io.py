# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Shared repository I/O helpers. The helpers standardize YAML serialization, artifact
writing, stable hashing, and portable path rendering across generated reasoning
artifacts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

from ruler.paths import BUILD_DIR
from ruler.paths import REPO_ROOT

T = TypeVar("T", bound=BaseModel)


class _NoAliasDumper(yaml.SafeDumper):
    """YAML dumper variant that expands repeated objects instead of emitting aliases."""

    def ignore_aliases(self, data: Any) -> bool:
        """Disable YAML anchors so generated artifacts stay simple to review."""
        return True


def read_yaml(path: Path) -> Any:
    """Read a UTF-8 YAML artifact into native Python data."""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def write_yaml(path: Path, payload: Any) -> None:
    """Write a UTF-8 YAML artifact, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.dump(payload, handle, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True)


def write_text(path: Path, content: str) -> None:
    """Write a UTF-8 text artifact, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def stable_hash(payload: Any) -> str:
    """Hash structured payloads deterministically for audit IDs and manifests."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_model_list(path: Path, model: type[T]) -> list[T]:
    """Load a YAML list and validate every item with the supplied Pydantic model."""
    payload = read_yaml(path)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a YAML list")
    return [model.model_validate(item) for item in payload]


def load_model(path: Path, model: type[T]) -> T:
    """Load one YAML mapping and validate it with the supplied Pydantic model."""
    return model.model_validate(read_yaml(path))


def artifact_path(name: str) -> Path:
    """Return the build-directory path for a named generated artifact."""
    return BUILD_DIR / name


def repo_relative_posix(path: Path) -> str:
    """Render a path relative to the repository using portable POSIX separators."""
    try:
        relative = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        relative = path
    return relative.as_posix()
