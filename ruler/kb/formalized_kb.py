# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-neutral inventory of canonical corpus artifacts."""

from dataclasses import dataclass
from pathlib import Path
from ruler.io import write_yaml
from ruler.paths import KB_DIR
from ruler.kb.corpus_manifest import (
    discover_corpus_manifests,
    load_corpus_manifest,
    validate_corpus_manifests,
)

KB_MANIFEST = KB_DIR / "manifest.yaml"


@dataclass(frozen=True)
class KBFileSpec:
    kb_path: str
    category: str
    artifact_type: str
    language: str
    role: str
    legacy_paths: tuple[str, ...] = ()
    branch: str = "neutral"


def load_formalized_kb_specs(path: Path = KB_MANIFEST) -> tuple[KBFileSpec, ...]:
    """Read authoritative corpus declarations instead of fixed application defaults."""
    return tuple(
        KBFileSpec(
            artifact.path,
            artifact.category,
            artifact.artifact_type,
            artifact.language,
            artifact.role,
            tuple(artifact.legacy_mirrors),
            manifest.domain_id,
        )
        for source in discover_corpus_manifests()
        for manifest in [load_corpus_manifest(source)]
        for artifact in manifest.artifacts
    )


KB_FILE_SPECS = load_formalized_kb_specs()


def validate_formalized_kb_artifacts() -> list[str]:
    """Check canonical artifact hashes and cross-corpus identities without writing."""
    manifests = [load_corpus_manifest(p) for p in discover_corpus_manifests()]
    if not manifests:
        raise ValueError("no corpus manifests found")
    return validate_corpus_manifests(manifests)


def write_formalized_kb_artifacts() -> dict[str, Path]:
    """Build a presentation inventory without rewriting canonical source evidence."""
    validate_formalized_kb_artifacts()
    entries = []
    for path in discover_corpus_manifests():
        manifest = load_corpus_manifest(path)
        for artifact in manifest.artifacts:
            entries.append(
                dict(
                    kb_path=artifact.path,
                    branch=manifest.domain_id,
                    category=artifact.category,
                    artifact_type=artifact.artifact_type,
                    language=(
                        {"asp_program": "asp", "prolog_program": "prolog"}.get(
                            artifact.artifact_type, artifact.language
                        )
                    ),
                    role=artifact.role,
                    legacy_paths=list(artifact.legacy_mirrors),
                    kb_sha256=artifact.sha256,
                )
            )
    write_yaml(
        KB_MANIFEST,
        dict(
            kb_id="ruler_formalized_kb",
            description="Canonical domain corpus inventory",
            entries=entries,
        ),
    )
    return {"manifest": KB_MANIFEST}
