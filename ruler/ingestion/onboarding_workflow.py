# SPDX-FileCopyrightText: 2026 Idiap Research Institute
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Shared steps of the planning-only Click onboarding command."""

from pathlib import Path
from rich.console import Console


def initialize_onboarding(output_dir: Path | None) -> dict[str, Path]:
    from ruler.ingestion.progressive_onboarding import (
        ONBOARDING_ROOT,
        initialize_progressive_onboarding,
    )

    return initialize_progressive_onboarding(output_dir or ONBOARDING_ROOT)


def catalogue_onboarding(artifacts: dict[str, Path]) -> dict[str, Path]:
    from ruler.ingestion.batch_pipeline import write_pipeline_catalogue

    artifacts.update(write_pipeline_catalogue())
    return artifacts


def announce_onboarding(artifacts: dict[str, Path], console: Console) -> None:
    console.print("[green]prepared progressive product onboarding[/green]")
    for name, path in artifacts.items():
        console.print(f"{name}: {path}")
