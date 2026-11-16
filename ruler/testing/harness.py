# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Dependency-injected, fixture-rooted deterministic pipeline harness primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


class HttpResolver(Protocol):
    def get(self, url: str, *, headers: dict[str, str] | None = None) -> object:
        """Resolve a request through the injected offline transport."""
        ...


@dataclass(frozen=True)
class HarnessContext:
    """All nondeterministic or external dependencies supplied explicitly."""

    root: Path
    clock: Callable[[], datetime]
    locale: str
    timezone: str
    http: HttpResolver
    extractor: Callable[[bytes, str], object]
    model_adapter: Callable[[object], object]
    event_sink: Callable[[dict[str, object]], None]
    seed: int = 0

    def resolve(self, relative: str) -> Path:
        """Resolve a harness path and reject traversal outside the fixture root."""
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("HARNESS_PATH_ESCAPE") from exc
        return candidate


@dataclass
class IsolatedPipelineHarness:
    """Generate only in a disposable stage and validate without writes."""

    context: HarnessContext
    protected_roots: tuple[Path, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        root = self.context.root.resolve()
        for protected in self.protected_roots:
            if root == protected.resolve() or protected.resolve() in root.parents:
                raise ValueError("HARNESS_PROTECTED_ROOT")
        root.mkdir(parents=True, exist_ok=True)

    def stage(self, name: str) -> Path:
        """Create one fresh, isolated stage directory."""
        if not name or any(part in {"", ".", ".."} for part in Path(name).parts):
            raise ValueError("HARNESS_INVALID_STAGE")
        path = self.context.resolve(f"stages/{name}")
        path.mkdir(parents=True, exist_ok=False)
        return path

    @staticmethod
    def snapshot(root: Path) -> dict[str, str]:
        """Hash every file to produce a deterministic tree snapshot."""
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def validate_read_only(self, root: Path, validator: Callable[[Path], T]) -> T:
        """Run a validator and fail if it mutates any artifact."""
        before = self.snapshot(root)
        result = validator(root)
        after = self.snapshot(root)
        if before != after:
            raise RuntimeError("HARNESS_VALIDATOR_WROTE_STATE")
        return result

    def assert_reproducible(self, generator: Callable[[Path, int, int], None]) -> None:
        """Assert byte-identical output across two safe worker schedules."""
        left, right = self.stage("schedule-1"), self.stage("schedule-2")
        generator(left, self.context.seed, 1)
        generator(right, self.context.seed, 2)
        if self.snapshot(left) != self.snapshot(right):
            raise AssertionError("HARNESS_NONDETERMINISTIC_OUTPUT")

    def assert_resume_equivalent(
        self,
        uninterrupted: Callable[[Path], None],
        interrupted_then_resumed: Callable[[Path], None],
    ) -> None:
        """Assert resumed execution equals an uninterrupted run byte for byte."""
        left, right = self.stage("uninterrupted"), self.stage("resumed")
        uninterrupted(left)
        interrupted_then_resumed(right)
        if self.snapshot(left) != self.snapshot(right):
            raise AssertionError("HARNESS_RESUME_MISMATCH")


def atomic_write(path: Path, payload: bytes) -> None:
    """Commit bytes atomically without leaving a partial canonical file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def canonical_json_bytes(payload: object) -> bytes:
    """Serialize JSON with stable ordering and no presentation-only whitespace."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def clone_fixture_tree(source: Path, target: Path) -> None:
    """Copy fixture input while rejecting a pre-existing destination."""
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target, symlinks=True)
