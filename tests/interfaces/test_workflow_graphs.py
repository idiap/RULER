# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for workflow graph visualization artifacts.

Workflow graphs turn hooks and skill bindings into an inspectable control map, so these
tests pin both the machine graph and the generated HTML surface.
"""

from __future__ import annotations

import json

from ruler.runtime.validation import validate_workflow_graphs
from ruler.interfaces.workflow_graphs import (
    build_workflow_graph_model,
    render_workflow_graph_html,
    write_workflow_graph_artifacts,
)


def test_workflow_graph_model_exposes_reasoning_and_reflection_stacks() -> None:
    """The graph model should include reasoning, promotion, logging, and reflection loops."""
    model = build_workflow_graph_model()

    assert model["repo"] == "ruler"
    assert model["summary"]["stacks"] >= 4
    assert model["summary"]["reflective_stacks"] >= 1
    assert "source-to-reasoner-promotion-loop" in model["stacks"]
    assert "reasoning-log-evidence-loop" in model["stacks"]
    assert model["graph"]["elements"]["nodes"]
    assert model["graph"]["elements"]["edges"]
    assert validate_workflow_graphs()


def test_workflow_graph_html_and_artifacts_are_inspectable(tmp_path) -> None:
    """The graph workflow should write JSON, layout, and an HTML explorer."""
    model = build_workflow_graph_model()
    html = render_workflow_graph_html(model)

    assert "RULER Workflow Graphs" in html
    assert "cytoscape" in html
    assert "workflow-graph-model" in html
    assert "Static Workflow Cards" in html

    paths = write_workflow_graph_artifacts(tmp_path)
    graph_payload = json.loads(paths["workflow_graphs_json"].read_text(encoding="utf-8"))

    assert paths["workflow_graphs_html"].exists()
    assert paths["workflow_layout_plan"].exists()
    assert graph_payload["summary"]["modeled_skills"] >= 4
