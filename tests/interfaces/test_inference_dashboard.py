# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from ruler.interfaces.inference_dashboard import (
    build_inference_control_dashboard,
    write_inference_control_dashboard_artifacts,
    validate_inference_control_dashboard,
)


def test_dashboard_exposes_canonical_domains_without_inventing_runs(tmp_path):
    dashboard = build_inference_control_dashboard()
    assert {"legal", "regulatory", "technical_support"} <= {
        item.branch for item in dashboard.domains
    }
    assert dashboard.summary.assertions == len(dashboard.assertions)
    artifacts = write_inference_control_dashboard_artifacts(tmp_path)
    html = artifacts["html"].read_text()
    assert "Logic explorer" in html
    assert "/Users/" not in html
    assert validate_inference_control_dashboard()
