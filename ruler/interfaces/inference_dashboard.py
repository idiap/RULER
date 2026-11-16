# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-neutral knowledge and inference inventory dashboard."""

from pathlib import Path
from ruler.interfaces.kb_visualizer import (
    build_kb_visualization,
    validate_kb_visualizer,
    write_kb_visualizer_artifact,
)
from ruler.paths import BUILD_DIR


def build_inference_control_dashboard():
    """Inspect registered domain knowledge, without manufacturing reasoning runs."""
    return build_kb_visualization()


def write_inference_control_dashboard_artifacts(output_dir: Path | None = None) -> dict[str, Path]:
    """Render the shared domain-neutral knowledge dashboard."""
    return write_kb_visualizer_artifact(output_dir or BUILD_DIR / "inference_dashboard")


def validate_inference_control_dashboard() -> list[str]:
    """Validate the same catalog, evidence, and rendering used by the dashboard."""
    return validate_kb_visualizer()
