# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Authenticated, read-only CBR workspace and bounded application helpers."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from ruler.cbr.contracts import OutcomeObservation, RetrievalRequest
from ruler.cbr.registry import FeatureRegistry
from ruler.cbr.service import CBRService
from ruler.cbr.store import OutcomeStore
from ruler.domains.cbr_catalog import (
    DomainCBRDemo,
    evaluate_cbr_demo,
    load_all_cbr_demos,
    load_cbr_demo,
)
from ruler.interfaces.cbr_demonstrators import (
    build_cbr_demonstrator_portfolio,
    build_cbr_domain_demonstrator,
    render_cbr_domain_html,
    render_cbr_portfolio_html,
)

MAX_CBR_TOP_K = 10
MAX_CBR_ID_LENGTH = 120


class CBRRetrievePayload(BaseModel):
    """A bounded request over a canonical synthetic demonstration query."""

    model_config = ConfigDict(extra="forbid")
    domain_id: str = Field(min_length=1, max_length=40)
    top_k: int = Field(default=3, ge=1, le=MAX_CBR_TOP_K)


class CBRPlanPayload(BaseModel):
    """Select one reviewed precedent for a non-executable adaptation preview."""

    model_config = ConfigDict(extra="forbid")
    domain_id: str = Field(min_length=1, max_length=40)
    source_case_id: str = Field(min_length=1, max_length=MAX_CBR_ID_LENGTH)


class CBRWorkspaceStore:
    """Content-bound verification runs and idempotent immutable outcome retention."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.outcomes = OutcomeStore(root)
        self._lock = threading.Lock()

    def verify(self, payload: CBRPlanPayload) -> dict[str, Any]:
        plan = cbr_plan(payload.domain_id, payload.source_case_id)
        evaluation = evaluate_cbr_demo(payload.domain_id).model_dump(mode="json")
        body = {
            "domain_id": payload.domain_id,
            "query_case_id": plan["query_case_id"],
            "source_case_id": payload.source_case_id,
            "rule_release_id": plan["rule_release_id"],
            "rule_release_sha256": plan["rule_release_sha256"],
            "adaptation": plan,
            "evaluation": evaluation,
            "human_review_required": True,
            "executed_action": False,
        }
        encoded = _canonical(body)
        run_id = "sha256:" + hashlib.sha256(encoded).hexdigest()
        record = {"run_id": run_id, "result_sha256": run_id, **body}
        path = self._run_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != serialized:
                raise ValueError("verification run content-address collision") from None
        return record

    def get_run(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise LookupError("CBR run unavailable") from exc
        body = {
            key: value for key, value in record.items() if key not in {"run_id", "result_sha256"}
        }
        actual = "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()
        if actual != run_id or record.get("result_sha256") != run_id:
            raise ValueError("stored verification run digest mismatch")
        return {**record, "replayed": True}

    def outcomes_etag(self) -> str:
        directory = self.root / "outcomes"
        rows = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                if path.is_file() and not path.is_symlink():
                    rows.append((path.name, hashlib.sha256(path.read_bytes()).hexdigest()))
        digest = hashlib.sha256(_canonical(rows)).hexdigest()
        return f'"sha256:{digest}"'

    def retain_outcome(
        self,
        outcome: OutcomeObservation,
        *,
        if_match: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], str, bool]:
        if not idempotency_key or len(idempotency_key) > 160:
            raise ValueError("Idempotency-Key must contain 1 to 160 characters")
        request_sha = (
            "sha256:"
            + hashlib.sha256(outcome.model_dump_json(exclude_none=True).encode()).hexdigest()
        )
        key_sha = hashlib.sha256(idempotency_key.encode()).hexdigest()
        receipt_path = self.root / "idempotency" / f"{key_sha}.json"
        with self._lock:
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt["request_sha256"] != request_sha:
                    raise RuntimeError("idempotency key was already used for another request")
                return receipt["response"], receipt["etag"], True
            current = self.outcomes_etag()
            if if_match != current:
                raise RuntimeError("stale outcome collection ETag")
            if outcome.review_state != "reviewed":
                raise ValueError("outcome retention requires review_state=reviewed")
            if not _known_case(outcome.case_id):
                raise LookupError("CBR resource unavailable")
            self.outcomes.retain(outcome)
            updated = self.outcomes_etag()
            response = {
                "outcome_id": outcome.outcome_id,
                "case_id": outcome.case_id,
                "status": "retained",
                "immutable": True,
                "reviewed": True,
            }
            receipt = {
                "request_sha256": request_sha,
                "etag": updated,
                "response": response,
            }
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            with receipt_path.open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
            return response, updated, False

    def list_outcomes(self, case_id: str | None = None) -> tuple[OutcomeObservation, ...]:
        directory = self.root / "outcomes"
        if not directory.exists():
            return ()
        values = tuple(
            OutcomeObservation.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
            if path.is_file() and not path.is_symlink()
        )
        return tuple(item for item in values if case_id is None or item.case_id == case_id)

    def _run_path(self, run_id: str) -> Path:
        if (
            not run_id.startswith("sha256:")
            or len(run_id) != 71
            or not all(character in "0123456789abcdef" for character in run_id[7:])
        ):
            raise ValueError("invalid CBR run identifier")
        return self.root / "runs" / f"{run_id[7:]}.json"


def cbr_library_list() -> dict[str, Any]:
    """List release-pinned case libraries without subject or filesystem identifiers."""
    libraries = [_public_library(item) for item in load_all_cbr_demos()]
    return {"libraries": libraries, "count": len(libraries), "read_only": True}


def cbr_library_show(domain_id: str) -> dict[str, Any]:
    """Show one library manifest as bounded public metadata."""
    return _public_library(_demo(domain_id), detail=True)


def cbr_case_show(domain_id: str, case_id: str) -> dict[str, Any]:
    """Show one reviewed case with identity and provenance fields redacted."""
    demo = _demo(domain_id)
    case = _case(demo, case_id)
    return _public_case(case)


def cbr_retrieve(domain_id: str, *, top_k: int = 3) -> dict[str, Any]:
    """Run deterministic retrieval over one immutable demonstration library."""
    if not 1 <= top_k <= MAX_CBR_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_CBR_TOP_K}")
    demo = _demo(domain_id)
    service = _service(demo)
    result = service.retrieve(
        RetrievalRequest(
            request_id=f"workspace-retrieve-{demo.domain_id}",
            query_case=demo.query,
            case_library_release_id=demo.library.release_id,
            case_library_release_sha256=demo.query.case_library_release_sha256,
            similarity_profile_sha256=demo.similarity_profile.sha256(),
            rule_release_id=demo.query.rule_release_id,
            rule_release_sha256=demo.query.rule_release_sha256,
            top_k=top_k,
            authorized_fields=frozenset(item.feature_id for item in demo.feature_definitions),
            maximum_candidates=50,
        )
    )
    return {
        **result.model_dump(mode="json"),
        "domain_id": demo.domain_id,
        "query_case_id": demo.query.case_id,
        "read_only": True,
        "non_reliance": (
            "Similarity ranks historical experience; it does not prove the current "
            "case is compliant, approved, licensed, deductible, or safe."
        ),
    }


def cbr_compare(domain_id: str, left_case_id: str, right_case_id: str) -> dict[str, Any]:
    """Compare two reviewed cases without exposing raw values or subject identities."""
    _bounded_id(left_case_id)
    _bounded_id(right_case_id)
    demo = _demo(domain_id)
    service = _service(demo)
    _case(demo, left_case_id)
    _case(demo, right_case_id)
    contributions = service.compare(left_case_id, right_case_id)
    return {
        "domain_id": domain_id,
        "left_case_id": left_case_id,
        "right_case_id": right_case_id,
        "contributions": [item.model_dump(mode="json") for item in contributions],
        "read_only": True,
        "values_redacted": True,
    }


def cbr_plan(domain_id: str, source_case_id: str) -> dict[str, Any]:
    """Return a typed, non-executable adaptation preview from a reviewed source."""
    _bounded_id(source_case_id)
    demo = _demo(domain_id)
    _case(demo, source_case_id)
    if source_case_id not in demo.expected.retrieval_order:
        raise ValueError("source case is not in the reviewed demonstration retrieval set")
    return {
        "status": "planned",
        "domain_id": demo.domain_id,
        "query_case_id": demo.query.case_id,
        "source_case_id": source_case_id,
        "rule_release_id": demo.query.rule_release_id,
        "rule_release_sha256": demo.query.rule_release_sha256,
        "operations": [
            {
                "operation": operation,
                "target": target,
                "requires_formal_verification": True,
            }
            for operation, target in (
                item.split(":", maxsplit=1) for item in demo.expected.adaptation_operations
            )
        ],
        "proposed_action": None,
        "executable": False,
        "human_review_required": True,
        "non_reliance": "The plan transfers evidence patterns, never a precedent disposition.",
    }


def create_cbr_workspace_router(
    authorize_bearer: Callable[..., Any], *, outcome_root: Path
) -> APIRouter:
    """Build CBR routes under the owning workspace's bearer dependency."""
    router = APIRouter(dependencies=[Depends(authorize_bearer)])
    store = CBRWorkspaceStore(outcome_root)

    @router.get("/cases", response_class=HTMLResponse)
    def cases_workspace() -> str:
        return render_cbr_portfolio_html(
            build_cbr_demonstrator_portfolio(), domain_href_prefix="/cases/"
        )

    @router.get("/cases/{domain_id}", response_class=HTMLResponse)
    def domain_workspace(domain_id: str) -> str:
        try:
            return render_cbr_domain_html(build_cbr_domain_demonstrator(_demo(domain_id)))
        except LookupError as exc:
            raise _not_found() from exc

    @router.get("/api/cbr/libraries")
    def libraries() -> dict[str, Any]:
        return cbr_library_list()

    @router.get("/api/cbr/libraries/{domain_id}")
    def library(domain_id: str) -> dict[str, Any]:
        try:
            return cbr_library_show(domain_id)
        except LookupError as exc:
            raise _not_found() from exc

    @router.get("/api/cbr/cases/{domain_id}/{case_id}")
    def show_case(domain_id: str, case_id: str) -> dict[str, Any]:
        try:
            return cbr_case_show(domain_id, case_id)
        except (LookupError, ValueError) as exc:
            raise _not_found() from exc

    @router.post("/api/cbr/retrieve")
    def retrieve(payload: CBRRetrievePayload) -> dict[str, Any]:
        try:
            return cbr_retrieve(payload.domain_id, top_k=payload.top_k)
        except LookupError as exc:
            raise _not_found() from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/cbr/compare")
    def compare(
        domain_id: str = Query(min_length=1, max_length=40),
        left_case_id: str = Query(min_length=1, max_length=MAX_CBR_ID_LENGTH),
        right_case_id: str = Query(min_length=1, max_length=MAX_CBR_ID_LENGTH),
    ) -> dict[str, Any]:
        try:
            return cbr_compare(domain_id, left_case_id, right_case_id)
        except (LookupError, ValueError, KeyError) as exc:
            raise _not_found() from exc

    @router.post("/api/cbr/plan")
    def plan(payload: CBRPlanPayload) -> dict[str, Any]:
        try:
            return cbr_plan(payload.domain_id, payload.source_case_id)
        except LookupError as exc:
            raise _not_found() from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/cbr/verify")
    def verify(payload: CBRPlanPayload) -> dict[str, Any]:
        try:
            return store.verify(payload)
        except LookupError as exc:
            raise _not_found() from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/cbr/runs/{run_id}")
    def replay(run_id: str) -> dict[str, Any]:
        try:
            return store.get_run(run_id)
        except LookupError as exc:
            raise _not_found() from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/cbr/outcomes")
    def outcomes(
        response: Response,
        case_id: str | None = Query(default=None, min_length=1, max_length=MAX_CBR_ID_LENGTH),
    ) -> dict[str, Any]:
        response.headers["ETag"] = store.outcomes_etag()
        return {
            "outcomes": [
                {
                    "outcome_id": item.outcome_id,
                    "case_id": item.case_id,
                    "observed_at": item.observed_at.isoformat(),
                    "status": item.status,
                    "review_state": item.review_state,
                    "source_ref": "[redacted]",
                    "visibility": item.visibility,
                    "immutable": True,
                }
                for item in store.list_outcomes(case_id)
            ],
            "read_only_view": True,
        }

    @router.post("/api/cbr/outcomes")
    def retain_outcome(
        payload: OutcomeObservation,
        response: Response,
        x_cbr_confirm: str | None = Header(default=None, alias="X-CBR-Confirm"),
        if_match: str | None = Header(default=None, alias="If-Match"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        expected = f"retain:{payload.outcome_id}"
        if x_cbr_confirm != expected:
            raise HTTPException(
                status_code=409,
                detail=f"retention requires X-CBR-Confirm: {expected}",
            )
        if if_match is None:
            raise HTTPException(status_code=428, detail="outcome retention requires If-Match")
        if idempotency_key is None:
            raise HTTPException(
                status_code=428, detail="outcome retention requires Idempotency-Key"
            )
        try:
            value, etag, replayed = store.retain_outcome(
                payload, if_match=if_match, idempotency_key=idempotency_key
            )
            response.headers["ETag"] = etag
            response.headers["Idempotent-Replay"] = str(replayed).lower()
            return value
        except LookupError as exc:
            raise _not_found() from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def _demo(domain_id: str) -> DomainCBRDemo:
    if not domain_id or len(domain_id) > 40:
        raise LookupError("CBR resource unavailable")
    return load_cbr_demo(domain_id)


def _service(demo: DomainCBRDemo) -> CBRService:
    return CBRService(
        registry=FeatureRegistry(domain_id=demo.domain_id, definitions=demo.feature_definitions),
        profile=demo.similarity_profile,
        cases=demo.library.cases,
    )


def _case(demo: DomainCBRDemo, case_id: str):
    _bounded_id(case_id)
    try:
        return next(item for item in demo.library.cases if item.case_id == case_id)
    except StopIteration as exc:
        raise LookupError("CBR resource unavailable") from exc


def _bounded_id(value: str) -> None:
    if not value or len(value) > MAX_CBR_ID_LENGTH:
        raise ValueError("case identifier is outside allowed bounds")


def _public_library(demo: DomainCBRDemo, *, detail: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "domain_id": demo.domain_id,
        "library_id": demo.library.library_id,
        "release_id": demo.library.release_id,
        "case_count": len(demo.library.cases),
        "profile_id": demo.similarity_profile.profile_id,
        "profile_sha256": demo.library.profile_sha256,
        "rule_dependencies": [item.model_dump(mode="json") for item in demo.library.dependencies],
        "read_only": True,
    }
    if detail:
        payload["cases"] = [
            {
                "case_id": item.case_id,
                "case_kind": item.case_kind,
                "as_of_date": item.as_of_date.isoformat(),
                "review_state": item.review_state.value,
                "historical_disposition": (item.disposition.decision if item.disposition else None),
                "subject_ref": "[redacted]",
            }
            for item in demo.library.cases
        ]
    return payload


def _public_case(case) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "case_kind": case.case_kind,
        "domain_id": case.domain_id,
        "as_of_date": case.as_of_date.isoformat(),
        "jurisdictions": list(case.jurisdictions),
        "rule_release_id": case.rule_release_id,
        "rule_release_sha256": case.rule_release_sha256,
        "case_library_release_id": case.case_library_release_id,
        "review_state": case.review_state.value,
        "feature_states": [
            {
                "feature_id": item.feature_id,
                "missingness": item.missingness.value,
                "comparison_policy": item.comparison_policy.value,
                "value": "[redacted]",
            }
            for item in case.features
        ],
        "historical_disposition": case.disposition.decision if case.disposition else None,
        "subject_ref": "[redacted]",
        "party_refs": "[redacted]",
        "evidence_digests": "[redacted]",
        "read_only": True,
        "non_reliance": "A historical disposition is not a current-rule conclusion.",
    }


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="CBR resource unavailable")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _known_case(case_id: str) -> bool:
    return any(
        case_id == demo.query.case_id or any(item.case_id == case_id for item in demo.library.cases)
        for demo in load_all_cbr_demos()
    )


__all__ = [
    "CBRPlanPayload",
    "CBRRetrievePayload",
    "CBRWorkspaceStore",
    "cbr_case_show",
    "cbr_compare",
    "cbr_library_list",
    "cbr_library_show",
    "cbr_plan",
    "cbr_retrieve",
    "create_cbr_workspace_router",
]
