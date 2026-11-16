# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Safe, standalone artifacts for the five case-based reasoning demonstrations.

The renderer deliberately distinguishes live deterministic retrieval from the reviewed
demonstration journey.  This makes ranking drift visible instead of quietly presenting
curated examples as runtime results.  Historical dispositions are always accompanied
by a non-reliance label; only the explicitly labelled scenario rule outcome describes
the current query.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from ruler.cbr.contracts import RetrievalRequest
from ruler.cbr.registry import FeatureRegistry
from ruler.cbr.service import CBRService
from ruler.contracts.common import StrictContract
from ruler.domains.cbr_catalog import DomainCBRDemo, load_all_cbr_demos
from ruler.io import write_text
from ruler.paths import BUILD_DIR

CBR_DEMONSTRATOR_DIR = BUILD_DIR / "cbr_demonstrators"

GLOBAL_NON_RELIANCE = (
    "Historical similarity is operational evidence, not proof of compliance or "
    "authorization. Current release-pinned rules and required human review control."
)
SYNTHETIC_LABEL = (
    "Demonstration data are synthetic. Public-law references are dated planning "
    "anchors, not legal or tax advice."
)


class DemonstratorFeature(StrictContract):
    feature_id: str
    value: str
    missingness: str


class DemonstratorPrecedent(StrictContract):
    case_id: str
    reviewed_rank: int = Field(ge=1)
    case_role: Literal["positive", "negative"]
    historical_disposition: str
    engine_rank: int | None = Field(default=None, ge=1)
    engine_score: float | None = Field(default=None, ge=0, le=1)
    material_differences: tuple[str, ...] = ()
    non_reliance_label: str = GLOBAL_NON_RELIANCE


class ExcludedNearMatch(StrictContract):
    case_id: str
    historical_disposition: str
    exclusion_reason: str
    engine_contrast: bool
    non_reliance_label: str = GLOBAL_NON_RELIANCE


class DemonstratorAdaptation(StrictContract):
    operation: Literal["add", "remove", "replace", "retain"]
    target: str
    requires_formal_verification: bool = True


class EngineRetrievalEvidence(StrictContract):
    request_id: str
    profile_sha256: str
    selected_case_ids: tuple[str, ...]
    excluded_contrast_case_id: str | None
    candidate_count: int = Field(ge=0)
    trace: tuple[str, ...]
    matches_reviewed_order: bool


class CBRDomainDemonstrator(StrictContract):
    schema_version: Literal["ruler-cbr-demonstrator/1"] = "ruler-cbr-demonstrator/1"
    domain_id: str
    title: str
    query_case_id: str
    query_summary: str
    query_features: tuple[DemonstratorFeature, ...]
    case_library_release_id: str
    case_library_release_sha256: str
    rule_release_id: str
    rule_release_sha256: str
    live_retrieval: EngineRetrievalEvidence
    reviewed_precedents: tuple[DemonstratorPrecedent, ...] = Field(min_length=3)
    excluded_near_match: ExcludedNearMatch
    adaptation: tuple[DemonstratorAdaptation, ...] = Field(min_length=1)
    scenario_rule_outcome: str
    rule_outcome_status: Literal["blocked_or_held", "review_required"]
    counterfactuals: tuple[str, ...] = Field(min_length=1)
    human_review_required: bool = True
    synthetic_data_label: str = SYNTHETIC_LABEL
    non_reliance_label: str = GLOBAL_NON_RELIANCE
    claim_boundary: str


class CBRDemonstratorPortfolio(StrictContract):
    schema_version: Literal["ruler-cbr-demonstrator-portfolio/1"] = (
        "ruler-cbr-demonstrator-portfolio/1"
    )
    title: str
    cycle: tuple[str, ...]
    domains: tuple[CBRDomainDemonstrator, ...] = Field(min_length=5, max_length=5)
    synthetic_data_label: str = SYNTHETIC_LABEL
    non_reliance_label: str = GLOBAL_NON_RELIANCE


_TITLES = {
    "spending": "Research GPU procurement",
    "regulatory": "EU recruitment AI deployment",
    "fiscal": "Swiss VAT expense coding",
    "trade": "Swiss dual-use export",
    "technical_support": "Industrial controller E-42 support",
}

_SUMMARIES = {
    "spending": "CHF 71,800 GPU server order with one quote and missing waiver and finance approval.",
    "regulatory": "Operational CV screening in France with logging but missing oversight, notice, and input review.",
    "fiscal": "Mixed-rate Swiss travel invoice with no documented business purpose for an input-tax claim.",
    "trade": "Controller and firmware export to Turkey with classification, end-use, screening, and licence gaps.",
    "technical_support": "Revision-C controller E-42 after update, active interlock, and a stopped production line.",
}

_CASE_ROLES: dict[str, dict[str, Literal["positive", "negative"]]] = {
    "spending": {
        "spend-precedent-microscope-009": "positive",
        "spend-precedent-compute-014": "positive",
        "spend-precedent-budget-033": "negative",
    },
    "regulatory": {
        "regulatory-precedent-notice-024": "negative",
        "regulatory-precedent-oversight-019": "negative",
        "regulatory-precedent-cv-pilot-011": "positive",
    },
    "fiscal": {
        "fiscal-precedent-mixed-travel-031": "positive",
        "fiscal-precedent-conference-018": "positive",
        "fiscal-precedent-client-gift-012": "negative",
        "fiscal-precedent-wrong-rate-037": "negative",
    },
    "trade": {
        "trade-precedent-enduser-missing-028": "negative",
        "trade-precedent-unlicensed-034": "negative",
        "trade-precedent-controller-eu-015": "positive",
    },
    "technical_support": {
        "support-precedent-e42-031": "positive",
        "support-precedent-e42-038": "positive",
        "support-precedent-bypass-026": "negative",
    },
}

_EXCLUSION_REASONS = {
    "spending": "USD framework cloud service uses another currency and procurement route.",
    "regulatory": "Biometric identification belongs to a materially different use context and control regime.",
    "fiscal": "Foreign SaaS is an acquisition-tax mechanism, not a domestic mixed-rate invoice.",
    "trade": "A standard motor is not comparable to a controller with firmware and unresolved classification.",
    "technical_support": "TC6 hardware is a different product family; its remote reset is not version-compatible.",
}


def build_cbr_domain_demonstrator(demo: DomainCBRDemo) -> CBRDomainDemonstrator:
    """Build one honest journey from the canonical data and the live CBR service."""
    registry = FeatureRegistry(domain_id=demo.domain_id, definitions=demo.feature_definitions)
    service = CBRService(
        registry=registry,
        profile=demo.similarity_profile,
        cases=demo.library.cases,
    )
    authorized_fields = frozenset(item.feature_id for item in demo.feature_definitions)
    request = RetrievalRequest(
        request_id=f"demo-retrieve-{demo.domain_id}",
        query_case=demo.query,
        case_library_release_id=demo.library.release_id,
        case_library_release_sha256=demo.query.case_library_release_sha256,
        similarity_profile_sha256=demo.similarity_profile.sha256(),
        rule_release_id=demo.query.rule_release_id,
        rule_release_sha256=demo.query.rule_release_sha256,
        top_k=3,
        authorized_fields=authorized_fields,
    )
    result = service.retrieve(request)
    live_by_id = {item.case_id: item for item in result.retrieved}
    cases = {item.case_id: item for item in demo.library.cases}
    dispositions = {
        key: item.disposition.decision
        for key, item in cases.items()
        if item.disposition is not None
    }
    precedents = tuple(
        DemonstratorPrecedent(
            case_id=case_id,
            reviewed_rank=rank,
            case_role=_CASE_ROLES[demo.domain_id][case_id],
            historical_disposition=dispositions[case_id],
            engine_rank=live_by_id[case_id].rank if case_id in live_by_id else None,
            engine_score=live_by_id[case_id].score if case_id in live_by_id else None,
            material_differences=(
                live_by_id[case_id].material_differences if case_id in live_by_id else ()
            ),
        )
        for rank, case_id in enumerate(demo.expected.retrieval_order, start=1)
    )
    excluded_id = demo.expected.excluded_case_id
    actual_contrast = result.excluded_contrast.case_id if result.excluded_contrast else None
    return CBRDomainDemonstrator(
        domain_id=demo.domain_id,
        title=_TITLES[demo.domain_id],
        query_case_id=demo.query.case_id,
        query_summary=_SUMMARIES[demo.domain_id],
        query_features=tuple(
            DemonstratorFeature(
                feature_id=feature.feature_id,
                value=(
                    json.dumps(feature.value.value, ensure_ascii=False)
                    if feature.value is not None
                    else "unknown"
                ),
                missingness=feature.missingness.value,
            )
            for feature in demo.query.features
        ),
        case_library_release_id=demo.library.release_id,
        case_library_release_sha256=demo.query.case_library_release_sha256,
        rule_release_id=demo.query.rule_release_id,
        rule_release_sha256=demo.query.rule_release_sha256,
        live_retrieval=EngineRetrievalEvidence(
            request_id=result.request_id,
            profile_sha256=result.profile_sha256,
            selected_case_ids=tuple(item.case_id for item in result.retrieved),
            excluded_contrast_case_id=actual_contrast,
            candidate_count=result.candidate_count,
            trace=result.trace,
            matches_reviewed_order=(
                tuple(item.case_id for item in result.retrieved) == demo.expected.retrieval_order
                and actual_contrast == excluded_id
            ),
        ),
        reviewed_precedents=precedents,
        excluded_near_match=ExcludedNearMatch(
            case_id=excluded_id,
            historical_disposition=dispositions[excluded_id],
            exclusion_reason=_EXCLUSION_REASONS[demo.domain_id],
            engine_contrast=actual_contrast == excluded_id,
        ),
        adaptation=tuple(
            DemonstratorAdaptation.model_validate(dict(operation=operation, target=target))
            for operation, target in (
                item.split(":", maxsplit=1) for item in demo.expected.adaptation_operations
            )
        ),
        scenario_rule_outcome=demo.expected.rule_outcome,
        rule_outcome_status=(
            "blocked_or_held"
            if any(
                token in demo.expected.rule_outcome
                for token in ("block", "hold", "stop", "keep_interlock")
            )
            else "review_required"
        ),
        counterfactuals=demo.expected.counterfactuals,
        claim_boundary=demo.claim_boundary,
    )


def build_cbr_demonstrator_portfolio() -> CBRDemonstratorPortfolio:
    """Build the stable five-domain comparison portfolio."""
    return CBRDemonstratorPortfolio(
        title="Case-based reasoning: five governed journeys",
        cycle=(
            "typed_case_intake",
            "hard_filter_and_retrieve",
            "contrast_and_explain",
            "adapt_without_copying_approval",
            "verify_against_current_rules",
            "human_review",
        ),
        domains=tuple(build_cbr_domain_demonstrator(item) for item in load_all_cbr_demos()),
    )


def write_cbr_demonstrator_artifacts(
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write five standalone domain pairs plus the cross-domain portfolio pair."""
    base = output_dir or CBR_DEMONSTRATOR_DIR
    base.mkdir(parents=True, exist_ok=True)
    portfolio = build_cbr_demonstrator_portfolio()
    paths: dict[str, Path] = {}
    for journey in portfolio.domains:
        json_path = base / f"{journey.domain_id}.json"
        html_path = base / f"{journey.domain_id}.html"
        write_text(json_path, journey.model_dump_json(indent=2))
        write_text(html_path, render_cbr_domain_html(journey))
        paths[f"{journey.domain_id}_json"] = json_path
        paths[f"{journey.domain_id}_html"] = html_path
    portfolio_json = base / "portfolio.json"
    portfolio_html = base / "portfolio.html"
    write_text(portfolio_json, portfolio.model_dump_json(indent=2))
    write_text(portfolio_html, render_cbr_portfolio_html(portfolio))
    paths["portfolio_json"] = portfolio_json
    paths["portfolio_html"] = portfolio_html
    return paths


def validate_cbr_demonstrators() -> list[str]:
    """Validate completeness, non-reliance boundaries, safe HTML, and JSON round trips."""
    errors: list[str] = []
    portfolio = build_cbr_demonstrator_portfolio()
    if {item.domain_id for item in portfolio.domains} != set(_TITLES):
        errors.append("portfolio does not contain each required domain exactly once")
    for journey in portfolio.domains:
        roles = {item.case_role for item in journey.reviewed_precedents}
        if roles != {"positive", "negative"}:
            errors.append(f"{journey.domain_id}: retrieved set needs positive and negative cases")
        if len({item.case_id for item in journey.reviewed_precedents}) != 3:
            errors.append(f"{journey.domain_id}: expected three distinct precedents")
        if journey.excluded_near_match.case_id in {
            item.case_id for item in journey.reviewed_precedents
        }:
            errors.append(f"{journey.domain_id}: excluded case appears in reviewed top-k")
        if not all(item.requires_formal_verification for item in journey.adaptation):
            errors.append(f"{journey.domain_id}: unverified adaptation operation")
        labels = [
            journey.non_reliance_label,
            journey.excluded_near_match.non_reliance_label,
            *(item.non_reliance_label for item in journey.reviewed_precedents),
        ]
        if any("not proof" not in label for label in labels):
            errors.append(f"{journey.domain_id}: incomplete non-reliance label")
        rendered = render_cbr_domain_html(journey)
        if "<script" in rendered.lower() or "javascript:" in rendered.lower():
            errors.append(f"{journey.domain_id}: unsafe executable HTML")
        if "<main" not in rendered or "<nav" not in rendered or "<table" not in rendered:
            errors.append(f"{journey.domain_id}: accessible semantic structure is incomplete")
        try:
            CBRDomainDemonstrator.model_validate_json(journey.model_dump_json())
        except ValueError as exc:
            errors.append(f"{journey.domain_id}: JSON round trip failed: {exc}")
    if errors:
        from ruler.runtime.validation import ValidationErrorGroup

        raise ValidationErrorGroup("cbr-demonstrators", errors)
    exact = sum(item.live_retrieval.matches_reviewed_order for item in portfolio.domains)
    return [
        f"domains={len(portfolio.domains)}",
        "artifact_pairs=6",
        f"live_golden_matches={exact}/{len(portfolio.domains)}",
        "non_reliance=required",
    ]


def render_cbr_domain_html(journey: CBRDomainDemonstrator) -> str:
    """Render one accessible, dependency-free domain journey."""
    e = html.escape
    features = "".join(
        f"<tr><th scope='row'>{e(item.feature_id)}</th><td>{e(item.value)}</td>"
        f"<td>{e(item.missingness)}</td></tr>"
        for item in journey.query_features
    )
    precedents = "".join(
        "<article class='precedent'>"
        f"<h3>#{item.reviewed_rank} {e(item.case_id)}</h3>"
        f"<p><span class='badge {e(item.case_role)}'>{e(item.case_role)}</span> "
        f"Historical disposition: <code>{e(item.historical_disposition)}</code></p>"
        f"<p>Live engine: {e(_engine_position(item))}</p>"
        f"<p class='boundary'>{e(item.non_reliance_label)}</p>"
        "</article>"
        for item in journey.reviewed_precedents
    )
    operations = "".join(
        f"<li><strong>{e(item.operation)}</strong> <code>{e(item.target)}</code> "
        "<span class='badge review'>formal verification required</span></li>"
        for item in journey.adaptation
    )
    counterfactuals = "".join(f"<li>{e(item)}</li>" for item in journey.counterfactuals)
    live_ids = ", ".join(journey.live_retrieval.selected_case_ids) or "none (abstained)"
    drift = (
        "matches the reviewed demonstration"
        if journey.live_retrieval.matches_reviewed_order
        else "differs from the reviewed demonstration; inspect before release"
    )
    body = f"""
<a class='skip' href='#main'>Skip to journey</a>
<header><p class='eyebrow'>RULER · governed CBR demonstration</p><h1>{e(journey.title)}</h1>
<p>{e(journey.query_summary)}</p><p class='warning'><strong>Synthetic:</strong> {e(journey.synthetic_data_label)}</p></header>
<nav aria-label='Journey stages'><ol><li><a href='#intake'>Intake</a></li><li><a href='#retrieve'>Retrieve</a></li><li><a href='#adapt'>Adapt</a></li><li><a href='#verify'>Verify</a></li></ol></nav>
<main id='main'>
<section id='intake'><h2>1. Typed case intake</h2><p>Query <code>{e(journey.query_case_id)}</code></p>
<table><caption>Observed and explicitly unknown query features</caption><thead><tr><th scope='col'>Feature</th><th scope='col'>Value</th><th scope='col'>Missingness</th></tr></thead><tbody>{features}</tbody></table></section>
<section id='retrieve'><h2>2. Retrieve and contrast</h2><div class='engine'><h3>Live deterministic retrieval</h3>
<p>Selected: <code>{e(live_ids)}</code>. Result {e(drift)}.</p><p>Request <code>{e(journey.live_retrieval.request_id)}</code>; candidates {journey.live_retrieval.candidate_count}.</p></div>
<h3>Reviewed demonstration precedents</h3><p>These reviewed examples define the intended journey and are not silently represented as live ranks.</p>{precedents}
<aside><h3>Excluded near-match: {e(journey.excluded_near_match.case_id)}</h3><p>{e(journey.excluded_near_match.exclusion_reason)}</p>
<p>Historical disposition: <code>{e(journey.excluded_near_match.historical_disposition)}</code></p><p class='boundary'>{e(journey.excluded_near_match.non_reliance_label)}</p></aside></section>
<section id='adapt'><h2>3. Proposed adaptation</h2><p>Operations transfer evidence patterns or diagnostics—not approvals, licences, tax facts, or outcomes.</p><ul>{operations}</ul></section>
<section id='verify'><h2>4. Current-rule verification</h2><p class='outcome'><strong>Scenario rule outcome:</strong> <code>{e(journey.scenario_rule_outcome)}</code></p>
<p>This is the reviewed scenario expectation, pinned to <code>{e(journey.rule_release_id)}</code>; human review remains required.</p>
<h3>Counterfactuals for reviewer exploration</h3><ul>{counterfactuals}</ul></section>
<section aria-labelledby='boundary'><h2 id='boundary'>Non-reliance boundary</h2><p class='boundary'>{e(journey.non_reliance_label)}</p><p>{e(journey.claim_boundary)}</p></section>
</main>"""
    return _document(journey.title, body)


def render_cbr_portfolio_html(
    portfolio: CBRDemonstratorPortfolio, *, domain_href_prefix: str | None = None
) -> str:
    """Render a compact comparison of the same governed cycle across five domains."""
    e = html.escape

    def href(domain_id: str) -> str:
        return (
            f"{domain_href_prefix}{domain_id}"
            if domain_href_prefix is not None
            else f"{domain_id}.html"
        )

    rows = "".join(
        "<tr>"
        f"<th scope='row'><a href='{e(href(item.domain_id), quote=True)}'>{e(item.title)}</a></th>"
        f"<td>{e(item.query_summary)}</td>"
        f"<td>{e(', '.join(p.case_id for p in item.reviewed_precedents if p.case_role == 'positive'))}</td>"
        f"<td>{e(', '.join(p.case_id for p in item.reviewed_precedents if p.case_role == 'negative'))}</td>"
        f"<td>{e(item.excluded_near_match.case_id)}</td>"
        f"<td><code>{e(item.scenario_rule_outcome)}</code></td>"
        "</tr>"
        for item in portfolio.domains
    )
    cycle = "".join(f"<li>{e(item.replace('_', ' '))}</li>" for item in portfolio.cycle)
    body = f"""
<a class='skip' href='#main'>Skip to comparison</a>
<header><p class='eyebrow'>RULER · CBR portfolio</p><h1>{e(portfolio.title)}</h1>
<p class='warning'><strong>Synthetic:</strong> {e(portfolio.synthetic_data_label)}</p></header>
<nav aria-label='Portfolio'><a href='#cycle'>Shared cycle</a> · <a href='#comparison'>Domain comparison</a></nav>
<main id='main'><section id='cycle'><h2>One controlled cycle</h2><ol>{cycle}</ol>
<p class='boundary'>{e(portfolio.non_reliance_label)}</p></section>
<section id='comparison'><h2>Five realistic journeys</h2><div class='table-scroll' tabindex='0' aria-label='Scrollable domain comparison'>
<table><caption>How the same CBR controls apply across five domains</caption><thead><tr><th scope='col'>Journey</th><th scope='col'>Current case</th><th scope='col'>Positive precedents</th><th scope='col'>Negative precedents</th><th scope='col'>Excluded near-match</th><th scope='col'>Current-rule outcome</th></tr></thead><tbody>{rows}</tbody></table></div></section></main>"""
    return _document(portfolio.title, body)


def _engine_position(item: DemonstratorPrecedent) -> str:
    if item.engine_rank is None:
        return "not selected in the live top-k"
    assert item.engine_score is not None
    return f"rank {item.engine_rank}, score {item.engine_score:.3f}"


def _document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>{html.escape(title)}</title><style>
:root{{--ink:#17202a;--muted:#53606d;--paper:#f5f7f8;--card:#fff;--line:#cbd5df;--accent:#175c70;--warning:#fff4ce;--danger:#ffe8e8;--positive:#dff4e5}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}}header,nav,main{{max-width:1160px;margin:auto;padding:1rem 1.5rem}}header{{padding-top:2.5rem}}nav{{background:var(--card);border-block:1px solid var(--line)}}nav ol{{display:flex;flex-wrap:wrap;gap:1.5rem;padding-left:1.25rem}}section,aside,.precedent,.engine{{background:var(--card);border:1px solid var(--line);border-radius:.5rem;padding:1rem;margin:1rem 0}}aside{{border-left:.35rem solid #9b5b00}}h1{{font-size:clamp(2rem,5vw,3.5rem);line-height:1.1}}h2{{margin-top:.25rem}}.eyebrow{{color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:.08em}}.warning,.boundary{{background:var(--warning);padding:.75rem;border-radius:.25rem}}.outcome{{background:var(--positive);padding:1rem;border-left:.35rem solid #277944}}.badge{{display:inline-block;padding:.1rem .45rem;border-radius:1rem;font-size:.85rem;font-weight:700}}.positive{{background:var(--positive)}}.negative{{background:var(--danger)}}.review{{background:var(--warning)}}code{{overflow-wrap:anywhere}}table{{width:100%;border-collapse:collapse}}caption{{font-weight:700;text-align:left;padding:.75rem 0}}th,td{{border:1px solid var(--line);padding:.6rem;text-align:left;vertical-align:top}}thead{{background:#eaf0f3}}.table-scroll{{overflow-x:auto}}a{{color:#075b75}}a:focus-visible,.table-scroll:focus-visible{{outline:3px solid #e07600;outline-offset:3px}}.skip{{position:absolute;left:-9999px}}.skip:focus{{left:1rem;top:1rem;background:#fff;padding:.75rem;z-index:2}}@media(max-width:650px){{header,nav,main{{padding-inline:.75rem}}nav ol{{display:block}}}}
</style></head><body>{body}</body></html>"""
