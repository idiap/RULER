# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ruler.interfaces.kb_workspace import create_kb_workspace_app
from ruler.kb.workspace_catalog import KnowledgeBaseCatalog

TOKEN = "cbr-workspace-token-123456"


def _client(tmp_path: Path) -> TestClient:
    (tmp_path / "kb/corpora").mkdir(parents=True)
    catalog = KnowledgeBaseCatalog(repo_root=tmp_path, managed_root=tmp_path / "kb/workspaces")
    return TestClient(create_kb_workspace_app(token=TOKEN, catalog=catalog))


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_cbr_routes_require_bearer_and_render_accessible_safe_html(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/cases").status_code == 401
    assert client.get("/cases", params={"token": TOKEN}).status_code == 401
    response = client.get("/cases", headers=_headers())
    assert response.status_code == 200
    assert "<main" in response.text and "<nav" in response.text and "<table" in response.text
    assert "<script" not in response.text.lower()
    assert "Content-Security-Policy" in response.headers
    domain = client.get("/cases/technical_support", headers=_headers())
    assert domain.status_code == 200
    assert "Industrial controller E-42 support" in domain.text


def test_cbr_read_only_api_retrieves_compares_plans_and_redacts(tmp_path: Path) -> None:
    client = _client(tmp_path)

    libraries = client.get("/api/cbr/libraries", headers=_headers()).json()
    assert libraries["count"] == 5
    assert libraries["read_only"] is True
    shown = client.get("/api/cbr/libraries/spending", headers=_headers()).json()
    assert shown["case_count"] >= 6
    case = client.get(
        "/api/cbr/cases/spending/spend-precedent-microscope-009", headers=_headers()
    ).json()
    assert case["subject_ref"] == "[redacted]"
    assert all(item["value"] == "[redacted]" for item in case["feature_states"])
    assert "/Users/" not in str(case)

    retrieval = client.post(
        "/api/cbr/retrieve",
        headers=_headers(),
        json={"domain_id": "spending", "top_k": 2},
    )
    assert retrieval.status_code == 200
    assert len(retrieval.json()["retrieved"]) == 2
    assert retrieval.json()["read_only"] is True

    comparison = client.get(
        "/api/cbr/compare",
        headers=_headers(),
        params={
            "domain_id": "spending",
            "left_case_id": "spend-precedent-microscope-009",
            "right_case_id": "spend-precedent-compute-014",
        },
    )
    assert comparison.status_code == 200
    assert comparison.json()["values_redacted"] is True
    plan = client.post(
        "/api/cbr/plan",
        headers=_headers(),
        json={
            "domain_id": "spending",
            "source_case_id": "spend-precedent-microscope-009",
        },
    )
    assert plan.status_code == 200
    assert plan.json()["executable"] is False
    assert all(item["requires_formal_verification"] for item in plan.json()["operations"])


def test_cbr_api_has_uniform_not_found_and_bounded_inputs(tmp_path: Path) -> None:
    client = _client(tmp_path)

    unknown_domain = client.get("/api/cbr/libraries/unknown", headers=_headers())
    unknown_case = client.get("/api/cbr/cases/spending/unknown", headers=_headers())
    assert unknown_domain.status_code == unknown_case.status_code == 404
    assert unknown_domain.json()["detail"] == unknown_case.json()["detail"]
    oversized = client.post(
        "/api/cbr/retrieve",
        headers=_headers(),
        json={"domain_id": "spending", "top_k": 11},
    )
    assert oversized.status_code == 422
    extra = client.post(
        "/api/cbr/retrieve",
        headers=_headers(),
        json={"domain_id": "spending", "top_k": 3, "retain": True},
    )
    assert extra.status_code == 422


def test_cbr_verification_run_is_content_bound_and_replayable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    request = {
        "domain_id": "trade",
        "source_case_id": "trade-precedent-enduser-missing-028",
    }

    verified = client.post("/api/cbr/verify", headers=_headers(), json=request)
    assert verified.status_code == 200
    assert verified.json()["evaluation"]["action"] == ("stop_shipment_and_escalate_export_control")
    assert verified.json()["executed_action"] is False
    run_id = verified.json()["run_id"]
    replay = client.get(f"/api/cbr/runs/{run_id}", headers=_headers())
    assert replay.status_code == 200
    assert replay.json()["result_sha256"] == run_id
    assert replay.json()["evaluation"] == verified.json()["evaluation"]
    assert replay.json()["replayed"] is True


def test_reviewed_outcome_retention_requires_confirmation_etag_and_idempotency(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    initial = client.get("/api/cbr/outcomes", headers=_headers())
    etag = initial.headers["etag"]
    payload = {
        "outcome_id": "support-observation-001",
        "case_id": "support-current-controller-001",
        "observed_at": datetime(2026, 8, 30, 15, tzinfo=UTC).isoformat(),
        "source_ref": "ticket:SYNTHETIC-42",
        "reviewer_id": "support-reviewer",
        "original_proposer_id": "cbr-automation",
        "status": "success",
        "customer_confirmed": True,
        "causal_claim_boundary": "Observed after intervention; no isolated causal claim.",
        "visibility": "internal",
        "retention_policy_id": "synthetic-demo-7y",
        "review_state": "reviewed",
    }
    missing_confirmation = client.post("/api/cbr/outcomes", headers=_headers(), json=payload)
    assert missing_confirmation.status_code == 409
    write_headers = {
        **_headers(),
        "X-CBR-Confirm": "retain:support-observation-001",
        "If-Match": etag,
        "Idempotency-Key": "retain-support-observation-001",
    }
    retained = client.post("/api/cbr/outcomes", headers=write_headers, json=payload)
    assert retained.status_code == 200
    assert retained.json()["immutable"] is True
    assert retained.headers["idempotent-replay"] == "false"

    replay = client.post("/api/cbr/outcomes", headers=write_headers, json=payload)
    assert replay.status_code == 200
    assert replay.headers["idempotent-replay"] == "true"

    stale_payload = {
        **payload,
        "outcome_id": "support-observation-002",
        "observed_at": datetime(2026, 8, 30, 16, tzinfo=UTC).isoformat(),
    }
    stale = client.post(
        "/api/cbr/outcomes",
        headers={
            **_headers(),
            "X-CBR-Confirm": "retain:support-observation-002",
            "If-Match": etag,
            "Idempotency-Key": "retain-support-observation-002",
        },
        json=stale_payload,
    )
    assert stale.status_code == 412

    listed = client.get(
        "/api/cbr/outcomes",
        params={"case_id": "support-current-controller-001"},
        headers=_headers(),
    )
    assert listed.json()["outcomes"][0]["source_ref"] == "[redacted]"
    assert "ticket:SYNTHETIC-42" not in listed.text


def test_outcome_reviewer_must_be_independent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = {
        "outcome_id": "bad-review",
        "case_id": "support-current-controller-001",
        "observed_at": datetime(2026, 8, 30, 15, tzinfo=UTC).isoformat(),
        "source_ref": "ticket:redacted",
        "reviewer_id": "same-actor",
        "original_proposer_id": "same-actor",
        "status": "success",
        "causal_claim_boundary": "No causal inference.",
        "visibility": "internal",
        "retention_policy_id": "synthetic-demo-7y",
    }
    response = client.post(
        "/api/cbr/outcomes",
        headers={
            **_headers(),
            "X-CBR-Confirm": "retain:bad-review",
            "If-Match": client.get("/api/cbr/outcomes", headers=_headers()).headers["etag"],
            "Idempotency-Key": "bad-review",
        },
        json=payload,
    )
    assert response.status_code == 422
