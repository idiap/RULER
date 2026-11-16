# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Append-only, content-addressed storage for immutable source versions."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from ruler.ingestion.contracts import SourceVersion, canonical_sha256


@dataclass(frozen=True)
class StoreResult:
    path: Path
    created: bool


class AppendOnlySourceStore:
    """Store raw bytes by digest and immutable version metadata by version ID."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, payload: bytes, version: SourceVersion) -> StoreResult:
        """Persist bytes and metadata; identical content is a deterministic no-op."""
        actual_hash = canonical_sha256(payload)
        if actual_hash != version.raw_sha256:
            raise ValueError("source bytes do not match SourceVersion.raw_sha256")
        if len(payload) != version.byte_length:
            raise ValueError("source bytes do not match SourceVersion.byte_length")

        digest = actual_hash.removeprefix("sha256:")
        raw_path = self.root / "objects" / "sha256" / digest[:2] / digest
        metadata_path = self.root / "versions" / f"{_safe_id(version.source_version_id)}.json"
        created = self._write_once(raw_path, payload)
        encoded_metadata = (
            json.dumps(
                version.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        self._write_once(metadata_path, encoded_metadata)
        return StoreResult(path=raw_path, created=created)

    def read(self, version: SourceVersion) -> bytes:
        """Load immutable bytes and recompute their hash before returning them."""
        digest = version.raw_sha256.removeprefix("sha256:")
        path = self.root / "objects" / "sha256" / digest[:2] / digest
        payload = path.read_bytes()
        if canonical_sha256(payload) != version.raw_sha256:
            raise ValueError("stored source object failed hash verification")
        return payload

    @staticmethod
    def _write_once(path: Path, payload: bytes) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(f"append-only collision at {path}")
            return False
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ValueError(f"append-only collision at {path}")
            temporary_path.unlink()
            return False
        temporary_path.unlink()
        return True


def _safe_id(value: str) -> str:
    return value.replace(":", "_").replace("/", "_")
