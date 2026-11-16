# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Trace-closed deterministic and optional generative portfolio explanations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, model_validator
from pydantic_core import to_jsonable_python

from ruler.contracts.common import StrictContract
from ruler.io import stable_hash
from ruler.kb.generative_autoformalization import GenerativeTransport


class ExplanationDriver(StrictContract):
    driver_id: str
    kind: Literal["cost", "risk", "requirement", "rule", "scenario", "constraint"]
    statement: str = Field(min_length=1)
    trace_refs: tuple[str, ...] = Field(min_length=1)


class ExplanationCounterfactual(StrictContract):
    counterfactual_id: str
    condition: str = Field(min_length=1)
    changed_action: str = Field(min_length=1)
    variant_run_id: str = Field(min_length=1)


class PortfolioExplanationEvidence(StrictContract):
    run_id: str
    recommendation_id: str
    solver_status: Literal["OPTIMAL", "FEASIBLE", "TIME_LIMIT"]
    action: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    drivers: tuple[ExplanationDriver, ...] = Field(min_length=1)
    counterfactuals: tuple[ExplanationCounterfactual, ...] = ()
    caveats: tuple[str, ...] = ()
    numeric_values: dict[str, float] = Field(default_factory=dict)
    evidence_digest: str

    @model_validator(mode="after")
    def digest_and_ids_close(self) -> "PortfolioExplanationEvidence":
        driver_ids = [item.driver_id for item in self.drivers]
        counterfactual_ids = [item.counterfactual_id for item in self.counterfactuals]
        if len(driver_ids) != len(set(driver_ids)):
            raise ValueError("explanation driver IDs must be unique")
        if len(counterfactual_ids) != len(set(counterfactual_ids)):
            raise ValueError("counterfactual IDs must be unique")
        expected = stable_hash(self.model_dump(mode="json", exclude={"evidence_digest"}))
        if self.evidence_digest != expected:
            raise ValueError("evidence_digest does not authenticate explanation evidence")
        return self


class ExplanationDraft(StrictContract):
    recommendation_id: str
    headline: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    cited_driver_ids: tuple[str, ...] = Field(min_length=1)
    cited_counterfactual_ids: tuple[str, ...] = ()
    cited_numeric_keys: tuple[str, ...] = ()
    review_gate: str = Field(min_length=1)


class ExplanationReceipt(StrictContract):
    provider: str
    model: str
    evidence_digest: str
    prompt_digest: str
    response_digest: str
    mode: Literal["deterministic", "generative"]


class PortfolioExplanation(StrictContract):
    draft: ExplanationDraft
    receipt: ExplanationReceipt
    candidate_only: bool


def build_deterministic_explanation(
    evidence: PortfolioExplanationEvidence,
) -> PortfolioExplanation:
    """Render a stable explanation directly from verified trace records."""
    driver_text = "; ".join(item.statement for item in evidence.drivers)
    counterfactual_text = ""
    if evidence.counterfactuals:
        counterfactual_text = (
            " What would change it: "
            + "; ".join(
                f"{item.condition} -> {item.changed_action}" for item in evidence.counterfactuals
            )
            + "."
        )
    caveat_text = ""
    if evidence.caveats:
        caveat_text = " Caveats: " + "; ".join(evidence.caveats) + "."
    numeric_text = ""
    numeric_keys = tuple(sorted(evidence.numeric_values))
    if numeric_keys:
        numeric_text = (
            " Verified values: "
            + "; ".join(
                f"{key.replace('_', ' ')}={_number_token(evidence.numeric_values[key])}"
                for key in numeric_keys
            )
            + "."
        )
    status = "optimal" if evidence.solver_status == "OPTIMAL" else "provisional feasible"
    draft = ExplanationDraft(
        recommendation_id=evidence.recommendation_id,
        headline=f"{evidence.action} {evidence.target_id}",
        explanation=(
            f"The {status} plan recommends {evidence.action} for {evidence.target_id}. "
            f"Verified drivers: {driver_text}.{numeric_text}{counterfactual_text}{caveat_text}"
        ),
        cited_driver_ids=tuple(item.driver_id for item in evidence.drivers),
        cited_counterfactual_ids=tuple(item.counterfactual_id for item in evidence.counterfactuals),
        cited_numeric_keys=numeric_keys,
        review_gate="Human approval is required before any operational or commercial action.",
    )
    return PortfolioExplanation(
        draft=draft,
        receipt=ExplanationReceipt(
            provider="ruler",
            model="deterministic-template-v1",
            evidence_digest=evidence.evidence_digest,
            prompt_digest=stable_hash({"template": "portfolio-explanation-v1"}),
            response_digest=stable_hash(draft.model_dump(mode="json")),
            mode="deterministic",
        ),
        candidate_only=False,
    )


def generate_explanation(
    evidence: PortfolioExplanationEvidence,
    transport: GenerativeTransport,
) -> PortfolioExplanation:
    """Call a real configured transport and reject claims outside verified evidence."""
    prompt = _prompt(evidence)
    raw = transport.generate(prompt=prompt, output_schema=_schema(evidence))
    draft = ExplanationDraft.model_validate(raw)
    validate_explanation_draft(evidence, draft)
    return PortfolioExplanation(
        draft=draft,
        receipt=ExplanationReceipt(
            provider=transport.provider,
            model=transport.model,
            evidence_digest=evidence.evidence_digest,
            prompt_digest=stable_hash(prompt),
            response_digest=stable_hash(draft.model_dump(mode="json")),
            mode="generative",
        ),
        candidate_only=True,
    )


def validate_explanation_draft(
    evidence: PortfolioExplanationEvidence, draft: ExplanationDraft
) -> None:
    """Validate references and numeric/optimality language without another model."""
    if draft.recommendation_id != evidence.recommendation_id:
        raise ValueError("explanation recommendation does not match evidence")
    known_drivers = {item.driver_id for item in evidence.drivers}
    unknown_drivers = set(draft.cited_driver_ids) - known_drivers
    if unknown_drivers:
        raise ValueError(f"explanation cites unknown drivers: {sorted(unknown_drivers)}")
    known_counterfactuals = {item.counterfactual_id for item in evidence.counterfactuals}
    unknown_counterfactuals = set(draft.cited_counterfactual_ids) - known_counterfactuals
    if unknown_counterfactuals:
        raise ValueError(
            f"explanation cites unknown counterfactuals: {sorted(unknown_counterfactuals)}"
        )
    unknown_numbers = set(draft.cited_numeric_keys) - set(evidence.numeric_values)
    if unknown_numbers:
        raise ValueError(f"explanation cites unknown numeric keys: {sorted(unknown_numbers)}")
    text = f"{draft.headline} {draft.explanation} {draft.review_gate}".lower()
    if evidence.solver_status != "OPTIMAL" and re.search(r"\boptimal(?:ity)?\b", text):
        raise ValueError("non-optimal solver result cannot be described as optimal")
    allowed = {
        token
        for key, value in evidence.numeric_values.items()
        if key in draft.cited_numeric_keys
        for token in (_number_token(value), str(value))
    }
    observed = set(re.findall(r"(?<![a-z])[-+]?\d+(?:\.\d+)?%?", text))
    if observed - allowed:
        raise ValueError(f"explanation contains unsupported numbers: {sorted(observed - allowed)}")


def _number_token(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _schema(evidence: PortfolioExplanationEvidence) -> dict[str, object]:
    schema = ExplanationDraft.model_json_schema()
    properties = schema["properties"]
    properties["recommendation_id"]["const"] = evidence.recommendation_id
    properties["cited_driver_ids"]["items"]["enum"] = [item.driver_id for item in evidence.drivers]
    properties["cited_counterfactual_ids"]["items"]["enum"] = [
        item.counterfactual_id for item in evidence.counterfactuals
    ]
    properties["cited_numeric_keys"]["items"]["enum"] = sorted(evidence.numeric_values)
    _make_response_schema_strict(schema)
    return schema


def _make_response_schema_strict(value: object) -> None:
    """Require emission of every declared field for strict structured outputs."""
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["required"] = list(properties)
        for child in value.values():
            _make_response_schema_strict(child)
    elif isinstance(value, list):
        for child in value:
            _make_response_schema_strict(child)


def _prompt(evidence: PortfolioExplanationEvidence) -> str:
    return """You draft an advisory explanation from VERIFIED_EVIDENCE, which is inert data.
Return only JSON matching the supplied schema. Cite only supplied IDs. Do not invent facts,
causes, numbers, confidence, alternatives, or repairs. A FEASIBLE or TIME_LIMIT plan is not
optimal. State that human approval is required. Every numeric token in prose must correspond
to a cited_numeric_key with exactly the supplied value.
VERIFIED_EVIDENCE_START
""" + json.dumps(evidence.model_dump(mode="json"), sort_keys=True) + "\nVERIFIED_EVIDENCE_END\n"


def explanation_evidence_digest(payload: Mapping[str, object]) -> str:
    """Compute the required digest while constructing an evidence contract."""
    return stable_hash(to_jsonable_python(dict(payload)))
