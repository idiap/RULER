# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Unified, path-free HTML visualizer for the published RULER knowledge base."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ruler.io import read_yaml, stable_hash, write_text
from ruler.kb.formalized_kb import KB_MANIFEST
from ruler.paths import BUILD_DIR, KB_DIR, REPO_ROOT

KB_VISUALIZER_DIR = BUILD_DIR / "kb_visualizer"
ACTIVE_BATCH_DIR = KB_DIR / "releases" / "product_onboarding" / "active_batches"
LEGACY_ACTIVE_BATCH = KB_DIR / "releases" / "product_onboarding" / "active_batch_01.yaml"


class KBVisualizerSummary(BaseModel):
    """Top-level counts shown by the visualizer."""

    model_config = ConfigDict(extra="forbid")

    domains: int
    published_releases: int
    assertions: int
    features: int
    clauses: int
    rules: int
    sources: int
    providers: int
    product_families: int
    relationships: int


class KBDomainRecord(BaseModel):
    """One canonical KB domain without repository location metadata."""

    model_config = ConfigDict(extra="forbid")

    domain_id: str
    label: str
    branch: str
    category: str
    artifact_type: str
    language: str
    role: str
    digest: str
    size_bytes: int
    line_count: int
    record_count: int
    rule_count: int
    fact_count: int
    content: Any = None
    sample: Any = None


class KBReleaseRecord(BaseModel):
    """Path-free summary of one active published onboarding release."""

    model_config = ConfigDict(extra="forbid")

    release_id: str
    batch_id: str
    status: str
    created_at: str | None = None
    corpus_snapshot_id: str | None = None
    projection_id: str | None = None
    features: int
    clauses: int
    rules: int
    sources: int
    annotations: int
    automated_gates: int
    validators: int
    digest: str


class KBAssertionRecord(BaseModel):
    """Unified assertion, annotation, and grounding record."""

    model_config = ConfigDict(extra="forbid")

    assertion_id: str
    label: str
    kind: str
    provider: str
    product_family: str
    product: str
    jurisdiction: str
    batch_id: str
    release_id: str
    review_state: str
    source_language: str
    source_gloss: str
    controlled_english: str
    source_ids: list[str]
    span_ids: list[str]
    dependencies: list[str]
    contradicts: list[str]
    precedes: list[str]
    related_assertions: list[str]
    digest: str
    details: dict[str, Any] = Field(default_factory=dict)


class KBSourceRecord(BaseModel):
    """Consolidated source identity and its semantic coverage."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    provider: str
    document_ids: list[str]
    product_ids: list[str]
    batches: list[str]
    assertion_ids: list[str]
    web_url: str | None = None
    digest: str


class KBRelationship(BaseModel):
    """Semantic graph edge rendered by the relationship inspector."""

    model_config = ConfigDict(extra="forbid")

    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    label: str


class KBVisualization(BaseModel):
    """Complete payload embedded in the standalone visualizer."""

    model_config = ConfigDict(extra="forbid")

    visualizer_id: str
    summary: KBVisualizerSummary
    assertion_kind_counts: dict[str, int]
    provider_counts: dict[str, int]
    product_family_counts: dict[str, int]
    review_state_counts: dict[str, int]
    domains: list[KBDomainRecord]
    releases: list[KBReleaseRecord]
    assertions: list[KBAssertionRecord]
    sources: list[KBSourceRecord]
    relationships: list[KBRelationship]
    audit_hash: str


def build_kb_visualization(repository_root: Path | None = None) -> KBVisualization:
    """Join canonical domains and published onboarding releases into one safe model."""
    domains = _build_domains(repository_root)
    releases: list[KBReleaseRecord] = []
    assertions: list[KBAssertionRecord] = []
    source_accumulator: dict[str, dict[str, Any]] = {}
    relationships: list[KBRelationship] = []

    for pointer in _active_release_pointers(repository_root):
        release, batch_assertions, batch_sources, batch_relationships = _load_release(
            pointer, repository_root
        )
        releases.append(release)
        assertions.extend(batch_assertions)
        relationships.extend(batch_relationships)
        _merge_sources(source_accumulator, batch_sources)

    assertions = _deduplicate_assertions(assertions)
    sources = _finalize_sources(source_accumulator, assertions)
    relationships = _deduplicate_relationships(relationships)
    kind_counts = dict(sorted(Counter(item.kind for item in assertions).items()))
    provider_counts = dict(sorted(Counter(item.provider for item in assertions).items()))
    family_counts = dict(sorted(Counter(item.product_family for item in assertions).items()))
    review_counts = dict(sorted(Counter(item.review_state for item in assertions).items()))
    summary = KBVisualizerSummary(
        domains=len(domains),
        published_releases=sum(item.status == "published" for item in releases),
        assertions=len(assertions),
        features=kind_counts.get("feature", 0),
        clauses=kind_counts.get("clause", 0),
        rules=kind_counts.get("rule", 0),
        sources=len(sources),
        providers=len({item.provider for item in assertions if item.provider != "Unknown"}),
        product_families=len(
            {item.product_family for item in assertions if item.product_family != "unknown"}
        ),
        relationships=len(relationships),
    )
    model = KBVisualization(
        visualizer_id="ruler_unified_kb_visualizer",
        summary=summary,
        assertion_kind_counts=kind_counts,
        provider_counts=provider_counts,
        product_family_counts=family_counts,
        review_state_counts=review_counts,
        domains=domains,
        releases=sorted(releases, key=lambda item: item.batch_id),
        assertions=sorted(
            assertions, key=lambda item: (item.provider, item.product_family, item.label)
        ),
        sources=sources,
        relationships=relationships,
        audit_hash="sha256:pending",
    )
    return model.model_copy(
        update={"audit_hash": stable_hash(model.model_dump(mode="json", exclude={"audit_hash"}))}
    )


def write_kb_visualizer_artifact(output_dir: Path | None = None) -> dict[str, Path]:
    """Write one self-contained HTML artifact; no companion files are required."""
    target = prepare_kb_visualizer_target(output_dir)
    return persist_kb_visualizer_html(target, render_kb_visualizer_html(build_kb_visualization()))


def prepare_kb_visualizer_target(output_dir: Path | None = None) -> Path:
    """Select and create the native destination before reading model inputs."""
    base = output_dir or KB_VISUALIZER_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / "index.html"


def persist_kb_visualizer_html(target: Path, html: str) -> dict[str, Path]:
    """Write the single native artifact and return its locator."""
    write_text(target, html)
    return {"html": target}


def validate_kb_visualizer() -> list[str]:
    """Validate genuine-logic, evidence separation, coverage, and redaction."""
    model = build_kb_visualization()
    errors: list[str] = []
    programs = _logical_programs(model)
    modules, evidence, coverage_gaps, _dependency_edges = _executable_program_modules(
        programs, model.assertions
    )
    if not model.domains:
        errors.append("canonical domain inventory is empty")
    if not programs:
        errors.append("no logical representations are visible")
    if any(not isinstance(item.content, str) or not item.content for item in programs):
        errors.append("logical representation content is empty")
    logical_clauses = [
        clause
        for module in modules
        for family in module["family_nodes"]
        for clause in family["assertions"]
    ]
    logical_source = "\n".join(str(item["logic"]) for item in logical_clauses)
    if any(f"{predicate}(" in logical_source for predicate in _PROVENANCE_PREDICATES):
        errors.append("provenance metadata is presented as domain logic")
    if "attribute(" in logical_source or "assertion_kind(" in logical_source:
        errors.append("generic record projections are presented as domain logic")
    mapped_assertions = {
        assertion_id for item in evidence for assertion_id in item["assertion_ids"]
    }
    if len(mapped_assertions) + len(coverage_gaps) != model.summary.assertions:
        errors.append("compiled assertion and coverage-gap inventory does not reconcile")
    serialized = json.dumps(model.model_dump(mode="json"), ensure_ascii=False)
    for forbidden in _forbidden_path_fragments():
        if forbidden in serialized:
            errors.append(f"embedded payload exposes forbidden location fragment {forbidden!r}")
    if re.search(r'"[^"\n]*(?:path|file)[^"\n]*"\s*:', serialized, re.IGNORECASE):
        errors.append("embedded payload exposes a path/file field")
    report = render_kb_visualizer_html(model)
    required = [
        "Logic explorer",
        "logic-visualizer-data",
        "Source evidence",
        "Coverage gaps",
        "providerFilter",
        "productFamilyFilter",
        "dependency_edges",
        "renderPrograms",
        "programSearch",
    ]
    for fragment in required:
        if fragment not in report:
            errors.append(f"HTML visualizer missing {fragment!r}")
    for forbidden in _forbidden_path_fragments():
        if forbidden in report:
            errors.append(f"HTML visualizer exposes forbidden location fragment {forbidden!r}")
    if "<script src=" in report or "<link rel=" in report:
        errors.append("visualizer is not self-contained")
    if errors:
        from ruler.runtime.validation import ValidationErrorGroup

        raise ValidationErrorGroup("kb-visualizer", errors)
    return [
        f"programs={len(programs)}",
        f"inventory_assertions={model.summary.assertions}",
        f"rules={sum(int(item['rule_count']) for item in modules)}",
        f"facts={sum(int(item['fact_count']) for item in modules)}",
        "path_metadata=absent",
        "artifact=self_contained_html",
    ]


def _render_logical_kb_visualizer_html(model: KBVisualization) -> str:
    """Render only genuine ASP and Prolog clauses as dependency-free HTML."""
    programs = _logical_programs(model)
    representations, evidence, coverage_gaps, dependency_edges = _executable_program_modules(
        programs, model.assertions
    )
    logical_clauses = sum(int(item["clause_count"]) for item in representations)
    payload_model = {
        "visualizer_id": "ruler_logical_representation_visualizer",
        "summary": {
            "programs": len(representations),
            "logical_clauses": logical_clauses,
            "rules": sum(int(item["rule_count"]) for item in representations),
            "facts": sum(int(item["fact_count"]) for item in representations),
            "constraints": sum(int(item["constraint_count"]) for item in representations),
            "directives": sum(int(item["directive_count"]) for item in representations),
            "evidence_parts": len(evidence),
            "compiled_assertions": len(model.assertions) - len(coverage_gaps),
            "coverage_gaps": len(coverage_gaps),
            "inventory_assertions": len(model.assertions),
        },
        "representations": representations,
        "evidence": evidence,
        "coverage_gaps": coverage_gaps,
        "dependency_edges": dependency_edges,
    }
    payload_model["audit_hash"] = stable_hash(payload_model)
    payload = _json_script_payload(payload_model)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RULER Logical Representations</title>
  <style>
    :root {{ --bg:#071018; --panel:#0d1924; --line:#23394a; --text:#e9f2f7; --muted:#91a7b7; --cyan:#62d9e8; --violet:#b9a4ff; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; color:var(--text); background:radial-gradient(circle at 10% 0,rgba(98,217,232,.11),transparent 32%),var(--bg); font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
    button,input,select {{ font:inherit; }} button {{ cursor:pointer; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:end; padding:22px 26px; border-bottom:1px solid var(--line); background:rgba(7,16,24,.95); }}
    h1 {{ margin:0; font-size:27px; letter-spacing:-.03em; }} h2 {{ margin:0; font-size:20px; }}
    .eyebrow {{ color:var(--cyan); font-size:11px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }}
    .muted {{ color:var(--muted); }} .subtitle {{ margin:4px 0 0; color:var(--muted); }}
    .metrics {{ display:flex; gap:8px; }} .metric {{ min-width:100px; padding:10px 13px; border:1px solid var(--line); border-radius:9px; background:var(--panel); }} .metric strong {{ display:block; font-size:21px; }} .metric span {{ color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.08em; }}
    main {{ padding:20px 24px 36px; }} .toolbar {{ display:grid; grid-template-columns:minmax(260px,2fr) minmax(220px,1.25fr) auto; gap:9px; margin-bottom:12px; }}
    input,select {{ width:100%; padding:11px 12px; color:var(--text); border:1px solid var(--line); border-radius:8px; background:#07111a; outline:none; }} input:focus,select:focus {{ border-color:var(--cyan); }}
    .filters {{ position:relative; }} .filters>summary {{ min-width:110px; padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:#07111a; cursor:pointer; text-align:center; }} .filters[open]>summary {{ border-color:var(--cyan); }} .filter-menu {{ position:absolute; z-index:2; right:0; width:min(520px,80vw); display:grid; grid-template-columns:1fr 1fr; gap:9px; margin-top:7px; padding:10px; border:1px solid var(--line); border-radius:9px; background:#07111a; box-shadow:0 14px 32px rgba(0,0,0,.35); }}
    .layout {{ display:grid; grid-template-columns:minmax(340px,.68fr) minmax(520px,1.32fr); gap:12px; min-height:720px; }}
    .panel {{ min-width:0; padding:15px; border:1px solid var(--line); border-radius:10px; background:linear-gradient(160deg,rgba(18,35,49,.94),rgba(10,23,33,.96)); }}
    .panel-head {{ display:flex; justify-content:space-between; gap:12px; align-items:start; margin-bottom:12px; }} .list {{ max-height:750px; overflow:auto; }}
    .tree {{ max-height:750px; overflow:auto; }} .family {{ margin-bottom:8px; border:1px solid var(--line); border-radius:8px; background:#08151f; }} .family summary {{ padding:9px 10px; cursor:pointer; color:var(--cyan); font-weight:700; }} .assertion {{ width:calc(100% - 14px); margin:0 7px 7px; padding:8px 9px; color:var(--text); border:1px solid var(--line); border-radius:7px; background:#091722; text-align:left; }} .assertion:hover,.assertion.active {{ border-color:var(--cyan); background:#102535; }} .assertion small {{ display:block; margin-top:3px; color:var(--muted); }}
    .badge {{ display:inline-flex; padding:3px 7px; border:1px solid rgba(185,164,255,.35); border-radius:999px; color:var(--violet); font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }}
    .detail-title {{ margin:3px 0 5px; font-size:23px; }} .detail-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:14px 0; }} .detail-cell {{ padding:9px; border:1px solid var(--line); border-radius:8px; background:#08151f; }} .detail-cell span {{ display:block; color:var(--muted); font-size:10px; text-transform:uppercase; }} .detail-cell strong {{ display:block; margin-top:3px; overflow-wrap:anywhere; }}
    .document-parts {{ display:grid; gap:8px; margin:10px 0 16px; }} .document-part {{ padding:11px; border:1px solid var(--line); border-left:3px solid var(--cyan); border-radius:8px; background:#08151f; }} .document-part dl {{ display:grid; grid-template-columns:105px 1fr; gap:5px 9px; margin:0; }} .document-part dt {{ color:var(--muted); font-size:10px; text-transform:uppercase; }} .document-part dd {{ margin:0; overflow-wrap:anywhere; }} .source-gloss {{ margin-top:9px; padding-top:9px; border-top:1px solid var(--line); color:#cfe2ee; }}
    .technical,.coverage-section {{ margin-top:14px; border:1px solid var(--line); border-radius:10px; background:var(--panel); }} .technical>summary,.coverage-section>summary {{ display:flex; justify-content:space-between; gap:12px; padding:12px 14px; cursor:pointer; font-weight:700; }} .coverage-section>summary {{ font-size:17px; }} .coverage-section>summary span {{ color:var(--muted); font-size:13px; font-weight:400; }} .technical-body,.coverage-body {{ padding:0 14px 14px; }}
    .gap-layout {{ display:grid; grid-template-columns:minmax(330px,.8fr) minmax(440px,1.2fr); gap:12px; }} .gap-card {{ width:100%; margin-bottom:7px; padding:10px; color:var(--text); border:1px solid var(--line); border-radius:8px; background:#091722; text-align:left; }} .gap-card:hover,.gap-card.active {{ border-color:var(--cyan); }} .separate {{ margin-top:12px; padding:12px; border:1px dashed var(--violet); border-radius:8px; background:#0a1420; }} .dependency {{ padding:7px 0; border-bottom:1px solid var(--line); color:var(--muted); }}
    pre {{ max-height:610px; overflow:auto; margin:10px 0 0; padding:14px; color:#cfe2ee; border:1px solid var(--line); border-radius:8px; background:#050d13; white-space:pre; font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .empty {{ display:grid; place-items:center; min-height:240px; color:var(--muted); text-align:center; }}
    @media(max-width:900px) {{ header {{ align-items:start; flex-direction:column; }} .layout,.gap-layout {{ grid-template-columns:1fr; }} .detail-grid {{ grid-template-columns:repeat(2,1fr); }} .toolbar {{ grid-template-columns:1fr 1fr; }} }}
    @media(max-width:560px) {{ main,header {{ padding:16px; }} .toolbar {{ grid-template-columns:1fr; }} .metrics {{ flex-wrap:wrap; }} }}
  </style>
</head>
<body>
  <header>
    <div><div class="eyebrow">RULER / Formal logic</div><h1>Logic explorer</h1><p class="subtitle">Browse compiled logic with its source evidence and coverage in one continuous view.</p></div>
    <div id="metrics" class="metrics"></div>
  </header>
  <main>
    <div class="toolbar">
      <input id="programSearch" type="search" placeholder="Search program, predicate, or compiled clause" autocomplete="off">
      <select id="programFilter" aria-label="Logic program"></select>
      <details class="filters"><summary>Filters</summary><div class="filter-menu"><select id="providerFilter"></select><select id="productFamilyFilter"></select></div></details>
    </div>
    <div class="layout">
      <section class="panel"><div class="panel-head"><div><h2>Compiled clauses</h2><div id="hierarchyCount" class="muted"></div></div></div><div id="hierarchyTree" class="tree"><div class="empty">Select a logic program.</div></div></section>
      <section class="panel" id="programDetail"><div class="empty">Select a compiled clause.</div></section>
    </div>
    <details class="coverage-section">
      <summary>Coverage gaps <span>Published records without an exact compiled-clause link</span></summary>
      <div class="coverage-body"><div class="gap-layout"><section class="panel"><p class="muted">These records remain explicitly unformalized or blocked.</p><input id="gapSearch" type="search" placeholder="Search gaps" autocomplete="off"><div id="gapList" class="list"></div></section><section id="gapDetail" class="panel"><div class="empty">Select a coverage gap.</div></section></div></div>
    </details>
  </main>
  <script id="logic-visualizer-data" type="application/json">{payload}</script>
  <script>
    const data=JSON.parse(document.getElementById('logic-visualizer-data').textContent);
    const state={{query:'',selectedModule:null,selectedClause:null,filters:{{}},gapQuery:''}};
    const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
    const title=value=>String(value??'').replaceAll('_',' ').replaceAll('-',' ').replace(/\\b\\w/g,c=>c.toUpperCase());
    const cell=(label,value)=>`<div class="detail-cell"><span>${{esc(label)}}</span><strong>${{esc(value)}}</strong></div>`;
    const allClauses=()=>data.representations.flatMap(module=>module.family_nodes.flatMap(family=>family.assertions.map(clause=>({{...clause,module_id:module.program_id,module_label:module.label,formalism:module.formalism}}))));
    const clauseById=new Map(allClauses().map(item=>[item.clause_id,item])); const evidenceById=new Map(data.evidence.map(item=>[item.evidence_id,item]));
    document.getElementById('metrics').innerHTML=[['Logic clauses',data.summary.logical_clauses],['Coverage gaps',data.summary.coverage_gaps]].map(([label,value])=>`<div class="metric"><strong>${{value.toLocaleString()}}</strong><span>${{label}}</span></div>`).join('');
    const programFilter=document.getElementById('programFilter');
    programFilter.innerHTML=data.representations.map(item=>`<option value="${{esc(item.program_id)}}">${{esc(item.label)}} (${{esc(title(item.formalism))}})</option>`).join('');
    programFilter.addEventListener('change',event=>{{state.selectedModule=event.target.value;state.selectedClause=null;renderPrograms();}});
    document.getElementById('programSearch').addEventListener('input',event=>{{state.query=event.target.value.trim().toLowerCase();renderPrograms();}});
    const filterSpecs=[['providerFilter','providers','Provider'],['productFamilyFilter','product_families','Product family']];
    function valuesFor(field) {{ return [...new Set(allClauses().flatMap(item=>Array.isArray(item[field])?item[field]:[item[field]]).filter(Boolean))].sort(); }}
    filterSpecs.forEach(([id,field,label])=>{{const select=document.getElementById(id);select.innerHTML=`<option value="all">All ${{esc(label.toLowerCase())}}s</option>`+valuesFor(field).map(value=>`<option value="${{esc(value)}}">${{esc(title(value))}}</option>`).join('');select.addEventListener('change',event=>{{state.filters[field]=event.target.value;renderPrograms();}});}});
    function clauseMatches(item) {{ const text=[item.label,item.logic,item.predicate,item.providers.join(' '),item.product_families.join(' ')].join(' ').toLowerCase(); return (!state.query||text.includes(state.query))&&filterSpecs.every(([,field])=>{{const wanted=state.filters[field]||'all',actual=Array.isArray(item[field])?item[field]:[item[field]];return wanted==='all'||actual.includes(wanted);}}); }}
    function visibleFamilies(module) {{ if(!module)return[];return module.family_nodes.map(family=>({{...family,assertions:family.assertions.filter(clauseMatches)}})).filter(family=>family.assertions.length); }}
    function filteredPrograms() {{ return data.representations.filter(item=>visibleFamilies(item).length); }}
    function renderPrograms() {{ const items=filteredPrograms();if((!state.selectedModule||!items.some(item=>item.program_id===state.selectedModule))&&items.length){{state.selectedModule=items[0].program_id;state.selectedClause=null;}}else if(!items.length){{state.selectedModule=null;state.selectedClause=null;}}programFilter.value=state.selectedModule||'';renderHierarchy(); }}
    function currentModule() {{ return data.representations.find(item=>item.program_id===state.selectedModule); }}
    function renderHierarchy() {{ const families=visibleFamilies(currentModule()),clauses=families.flatMap(family=>family.assertions);if((!state.selectedClause||!clauses.some(item=>item.clause_id===state.selectedClause))&&clauses.length)state.selectedClause=clauses[0].clause_id;document.getElementById('hierarchyCount').textContent=`${{families.length}} predicates · ${{clauses.length}} clauses`;document.getElementById('hierarchyTree').innerHTML=families.length?families.map(family=>`<details class="family" ${{family.assertions.some(item=>item.clause_id===state.selectedClause)?'open':''}}><summary>${{esc(family.label)}} · ${{family.assertions.length}}</summary>${{family.assertions.map(item=>`<button class="assertion ${{state.selectedClause===item.clause_id?'active':''}}" data-id="${{esc(item.clause_id)}}"><strong>${{esc(item.label)}}</strong><small>${{esc(title(item.kind))}} · ${{esc(item.modality.map(title).join(', '))}}</small></button>`).join('')}}</details>`).join(''):'<div class="empty">No matching compiled clauses.</div>';document.querySelectorAll('.assertion').forEach(button=>button.addEventListener('click',()=>selectClause(button.dataset.id)));if(!clauses.length)renderClauseDetail(null);else renderClauseDetail(clauseById.get(state.selectedClause)); }}
    function selectClause(id,rerender=true) {{ const item=clauseById.get(id);if(!item)return;state.selectedModule=item.module_id;state.selectedClause=id;if(rerender)renderPrograms();else renderClauseDetail(item); }}
    function evidenceCard(part) {{ return `<div class="document-part"><dl><dt>Provider</dt><dd>${{esc(part.provider)}}</dd><dt>Document</dt><dd>${{esc(part.document_id||'—')}}</dd><dt>Edition</dt><dd>${{esc(part.edition||'—')}}</dd><dt>Section</dt><dd>${{esc(part.section||'—')}}</dd><dt>Spans</dt><dd>${{esc((part.span_ids||[]).join(', ')||'—')}}</dd><dt>Language</dt><dd>${{esc(title(part.source_language))}}</dd><dt>Review</dt><dd>${{esc(title(part.review_state))}}</dd></dl>${{part.source_excerpt?`<div class="source-gloss"><strong>Source excerpt</strong><br>${{esc(part.source_excerpt)}}</div>`:''}}${{part.controlled_english?`<div class="source-gloss"><strong>Controlled English</strong><br>${{esc(part.controlled_english)}}</div>`:''}}</div>`; }}
    function renderClauseDetail(item) {{ const target=document.getElementById('programDetail');if(!item){{target.innerHTML='<div class="empty">Select a compiled clause.</div>';return;}}const parts=item.evidence_ids.map(id=>evidenceById.get(id)).filter(Boolean),edges=data.dependency_edges.filter(edge=>edge.source_id===item.clause_id||edge.target_id===item.clause_id);target.innerHTML=`<span class="badge">${{esc(title(item.kind))}}</span><div class="detail-title">${{esc(item.predicate)}}</div><div class="detail-grid">${{cell('Modality',item.modality.map(title).join(', '))}}${{cell('State',item.formalization_states.map(title).join(', '))}}${{cell('Provider',item.providers.join(', '))}}${{cell('Product family',item.product_families.map(title).join(', '))}}</div><h3>Compiled logical clause</h3><pre>${{esc(item.logic)}}</pre><div class="separate"><h3>Source evidence — separate from logic</h3>${{parts.length?parts.map(evidenceCard).join(''):'<div class="muted">No exact source mapping is encoded.</div>'}}</div><details class="technical"><summary>Technical dependencies</summary><div class="technical-body">${{edges.length?edges.map(edge=>`<div class="dependency">${{esc(edge.source_id)}} → ${{esc(edge.target_id)}} · ${{esc(title(edge.relation))}}</div>`).join(''):'<div class="muted">No predicate dependencies.</div>'}}</div></details>`; }}
    document.getElementById('gapSearch').addEventListener('input',event=>{{state.gapQuery=event.target.value.trim().toLowerCase();renderGaps();}});
    function renderGaps() {{ const gaps=data.coverage_gaps.filter(item=>!state.gapQuery||[item.label,item.provider,item.product_family,item.modality,item.formalization_state,item.source_document].join(' ').toLowerCase().includes(state.gapQuery));document.getElementById('gapList').innerHTML=gaps.map(item=>`<button class="gap-card" data-id="${{esc(item.assertion_id)}}"><strong>${{esc(item.label)}}</strong><div class="muted">${{esc(title(item.formalization_state))}} · ${{esc(item.provider)}} · ${{esc(title(item.product_family))}}</div></button>`).join('')||'<div class="empty">No coverage gaps match.</div>';document.querySelectorAll('.gap-card').forEach(button=>button.addEventListener('click',()=>renderGapDetail(data.coverage_gaps.find(item=>item.assertion_id===button.dataset.id)))); }}
    function renderGapDetail(item) {{ if(!item)return;document.getElementById('gapDetail').innerHTML=`<span class="badge">Coverage gap</span><div class="detail-title">${{esc(item.label)}}</div><div class="detail-grid">${{cell('State',title(item.formalization_state))}}${{cell('Provider',item.provider)}}${{cell('Product family',title(item.product_family))}}${{cell('Modality',title(item.modality))}}${{cell('Review',title(item.review_status))}}${{cell('Source document',item.source_document)}}</div><div class="separate"><strong>Why this is not in the logic tree</strong><div>${{esc(item.reason)}}</div></div>`; }}
    renderPrograms();renderGaps();
  </script>
</body>
</html>
"""


def render_kb_visualizer_html(model: KBVisualization) -> str:
    """Render consolidated logical KB modules only."""
    return _render_logical_kb_visualizer_html(model)


def _render_unified_kb_visualizer_html(model: KBVisualization) -> str:
    """Render all KB surfaces, including complete formal representations."""
    payload = _json_script_payload(model.model_dump(mode="json"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RULER Unified Knowledge Base</title>
  <style>
    :root {{ --bg:#071018; --panel:#0d1924; --panel2:#122331; --line:#23394a; --text:#e9f2f7; --muted:#91a7b7; --cyan:#62d9e8; --green:#6ee7b7; --amber:#f7c66b; --red:#fb7185; --violet:#b9a4ff; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; color:var(--text); background:radial-gradient(circle at 10% 0,rgba(98,217,232,.11),transparent 32%),var(--bg); font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
    button,input,select {{ font:inherit; }} button {{ cursor:pointer; }}
    header {{ position:sticky; top:0; z-index:20; display:grid; grid-template-columns:minmax(260px,1fr) minmax(300px,620px); gap:24px; align-items:center; padding:20px 26px; border-bottom:1px solid var(--line); background:rgba(7,16,24,.94); backdrop-filter:blur(18px); }}
    h1 {{ margin:0; font-size:25px; letter-spacing:-.03em; }} h2 {{ margin:0 0 12px; font-size:18px; }} h3 {{ margin:0; font-size:14px; }}
    .eyebrow {{ color:var(--cyan); font-size:11px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }}
    .subtitle,.muted {{ color:var(--muted); }} .subtitle {{ margin:4px 0 0; }}
    .search {{ width:100%; padding:12px 14px; color:var(--text); border:1px solid var(--line); border-radius:9px; background:#07111a; outline:none; }} .search:focus {{ border-color:var(--cyan); box-shadow:0 0 0 3px rgba(98,217,232,.1); }}
    .shell {{ display:grid; grid-template-columns:225px minmax(0,1fr); min-height:calc(100vh - 95px); }}
    nav {{ position:sticky; top:95px; height:calc(100vh - 95px); padding:18px 14px; border-right:1px solid var(--line); background:rgba(9,20,30,.8); }}
    .nav-btn {{ display:flex; width:100%; justify-content:space-between; align-items:center; margin-bottom:7px; padding:10px 11px; color:var(--muted); border:1px solid transparent; border-radius:8px; background:transparent; text-align:left; }} .nav-btn.active {{ color:var(--text); border-color:var(--line); background:var(--panel2); }} .nav-btn span:last-child {{ color:var(--cyan); font-size:11px; }}
    .privacy {{ position:absolute; left:14px; right:14px; bottom:18px; padding:11px; color:var(--muted); border:1px solid var(--line); border-radius:8px; font-size:11px; }}
    main {{ min-width:0; padding:22px 24px 44px; }} .view {{ display:none; }} .view.active {{ display:block; }}
    .metric-grid {{ display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); gap:10px; margin-bottom:20px; }}
    .metric,.panel {{ border:1px solid var(--line); border-radius:10px; background:linear-gradient(160deg,rgba(18,35,49,.94),rgba(10,23,33,.96)); box-shadow:0 16px 40px rgba(0,0,0,.18); }}
    .metric {{ padding:14px; }} .metric strong {{ display:block; font-size:27px; line-height:1; }} .metric span {{ display:block; margin-top:7px; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em; }}
    .panel {{ padding:16px; min-width:0; }} .panel-head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:14px; }}
    .overview-grid {{ display:grid; grid-template-columns:1.05fr .95fr; gap:12px; }}
    .bars {{ display:grid; gap:9px; }} .bar-row {{ display:grid; grid-template-columns:minmax(110px,190px) 1fr 48px; align-items:center; gap:10px; }} .bar-track {{ height:8px; overflow:hidden; border-radius:99px; background:#07111a; }} .bar-fill {{ height:100%; border-radius:99px; background:linear-gradient(90deg,var(--cyan),var(--green)); }} .bar-count {{ color:var(--muted); text-align:right; font-variant-numeric:tabular-nums; }}
    .chip-grid {{ display:flex; flex-wrap:wrap; gap:7px; }} .chip {{ padding:6px 9px; border:1px solid var(--line); border-radius:999px; color:var(--muted); background:#0a1721; }} .chip strong {{ color:var(--text); }}
    .toolbar {{ display:grid; grid-template-columns:minmax(220px,1fr) repeat(3,minmax(130px,190px)); gap:9px; margin-bottom:12px; }}
    select {{ width:100%; padding:10px 11px; color:var(--text); border:1px solid var(--line); border-radius:8px; background:#07111a; }}
    .records-layout {{ display:grid; grid-template-columns:minmax(330px,.9fr) minmax(380px,1.1fr); gap:12px; min-height:650px; }}
    .formal-layout {{ display:grid; grid-template-columns:minmax(300px,.72fr) minmax(460px,1.28fr); gap:12px; min-height:650px; }}
    .formal-list {{ max-height:720px; overflow:auto; padding-right:3px; }}
    .formal-records {{ display:grid; gap:8px; margin-top:10px; }} .formal-records details {{ border:1px solid var(--line); border-radius:8px; background:#08151f; }} .formal-records summary {{ padding:10px 12px; cursor:pointer; color:var(--cyan); font-weight:700; }} .formal-fields {{ width:100%; }} .formal-fields td:first-child {{ width:190px; color:var(--muted); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; }} .formal-fields pre {{ max-height:220px; }}
    .record-list {{ max-height:690px; overflow:auto; padding-right:3px; }} .record {{ width:100%; margin-bottom:7px; padding:11px; color:var(--text); border:1px solid var(--line); border-radius:8px; background:#091722; text-align:left; }} .record:hover,.record.active {{ border-color:var(--cyan); background:#102535; }}
    .record-top {{ display:flex; justify-content:space-between; gap:10px; }} .record-meta {{ margin-top:5px; color:var(--muted); font-size:12px; }}
    .badge {{ display:inline-flex; align-items:center; padding:3px 7px; border:1px solid rgba(98,217,232,.3); border-radius:999px; color:var(--cyan); font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }} .badge.feature {{ color:var(--green); border-color:rgba(110,231,183,.3); }} .badge.rule {{ color:var(--violet); border-color:rgba(185,164,255,.3); }} .badge.source {{ color:var(--amber); border-color:rgba(247,198,107,.3); }}
    .detail {{ min-height:620px; }} .detail-title {{ font-size:22px; margin:2px 0 6px; }} .detail-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin:14px 0; }} .detail-cell {{ padding:10px; border:1px solid var(--line); border-radius:8px; background:#08151f; }} .detail-cell span {{ display:block; color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.08em; }} .detail-cell strong {{ display:block; margin-top:3px; overflow-wrap:anywhere; }}
    .statement {{ margin:12px 0; padding:13px; border-left:3px solid var(--cyan); border-radius:0 8px 8px 0; background:#07131c; }} .statement.original {{ border-color:var(--violet); }}
    pre {{ max-height:320px; overflow:auto; margin:8px 0 0; padding:12px; color:#cfe2ee; border:1px solid var(--line); border-radius:8px; background:#050d13; white-space:pre-wrap; word-break:break-word; font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    pre.formal-source {{ max-height:610px; white-space:pre; word-break:normal; }}
    .graph-layout {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr); gap:12px; }} .graph {{ min-height:600px; overflow:auto; position:relative; }} svg {{ width:100%; min-width:700px; min-height:570px; }} .edge {{ stroke:#365468; stroke-width:1.5; }} .edge.active {{ stroke:var(--cyan); stroke-width:2.4; }} .node {{ cursor:pointer; }} .node circle {{ fill:#10283a; stroke:#4f748c; stroke-width:1.5; }} .node.assertion circle {{ fill:#12382f; stroke:#5fc69f; }} .node.release circle {{ fill:#2a2348; stroke:#a58dea; }} .node text {{ fill:var(--text); font-size:11px; }}
    .relation-list {{ display:grid; gap:7px; max-height:480px; overflow:auto; }} .relation {{ padding:9px; border:1px solid var(--line); border-radius:7px; background:#08151f; font-size:12px; }}
    table {{ width:100%; border-collapse:collapse; }} th,td {{ padding:10px; border-bottom:1px solid var(--line); text-align:left; }} th {{ color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.08em; }} td {{ vertical-align:top; }}
    .empty {{ display:grid; place-items:center; min-height:220px; color:var(--muted); text-align:center; }}
    @media(max-width:1050px) {{ header {{ grid-template-columns:1fr; }} .shell {{ grid-template-columns:1fr; }} nav {{ position:static; height:auto; display:flex; gap:7px; overflow:auto; border-right:0; border-bottom:1px solid var(--line); }} .nav-btn {{ min-width:150px; margin:0; }} .privacy {{ display:none; }} .metric-grid {{ grid-template-columns:repeat(3,1fr); }} .records-layout,.formal-layout,.overview-grid,.graph-layout {{ grid-template-columns:1fr; }} }}
    @media(max-width:650px) {{ header,main {{ padding:16px; }} .metric-grid {{ grid-template-columns:repeat(2,1fr); }} .toolbar {{ grid-template-columns:1fr; }} .records-layout {{ grid-template-columns:1fr; }} .detail-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <header>
    <div><div class="eyebrow">RULER / Controlled knowledge</div><h1>Unified Knowledge Base</h1><p class="subtitle">Published assertions, evidence, canonical domains, and releases in one inspectable surface.</p></div>
    <input id="globalSearch" class="search" type="search" placeholder="Search providers, products, clauses, features, sources, or releases" autocomplete="off">
  </header>
  <div class="shell">
    <nav aria-label="Knowledge base views">
      <button class="nav-btn active" data-view="overview"><span>Overview</span><span>01</span></button>
      <button class="nav-btn" data-view="formal"><span>Formal KBs</span><span>02</span></button>
      <button class="nav-btn" data-view="records"><span>Unified records</span><span>03</span></button>
      <button class="nav-btn" data-view="relationships"><span>Relationships</span><span>04</span></button>
      <button class="nav-btn" data-view="releases"><span>Published releases</span><span>05</span></button>
      <div class="privacy">No internal filenames or directories are included. The visualizer carries semantic IDs, controlled text, and audit digests only.</div>
    </nav>
    <main>
      <section id="overview" class="view active">
        <div id="summaryMetrics" class="metric-grid"></div>
        <div class="overview-grid">
          <article class="panel"><div class="panel-head"><div><h2>Published knowledge</h2><div class="muted">Assertions by formal kind</div></div></div><div id="kindBars" class="bars"></div></article>
          <article class="panel"><div class="panel-head"><div><h2>Review state</h2><div class="muted">Annotation states across active releases</div></div></div><div id="reviewBars" class="bars"></div></article>
          <article class="panel"><div class="panel-head"><div><h2>Providers</h2><div class="muted">Formal assertions grouped by provider</div></div></div><div id="providerChips" class="chip-grid"></div></article>
          <article class="panel"><div class="panel-head"><div><h2>Product families</h2><div class="muted">Coverage breadth in the published KB</div></div></div><div id="familyChips" class="chip-grid"></div></article>
        </div>
      </section>
      <section id="formal" class="view">
        <div class="toolbar">
          <input id="formalSearch" class="search" type="search" placeholder="Search formal programs, policies, predicates, and evidence">
          <select id="formalBranch"><option value="all">All branches</option></select>
          <select id="formalCategory"><option value="all">All categories</option></select>
          <select id="formalLanguage"><option value="all">All languages</option></select>
        </div>
        <div class="formal-layout">
          <article class="panel"><div class="panel-head"><div><h2>Formal knowledge bases</h2><div id="formalCount" class="muted"></div></div></div><div id="formalList" class="formal-list"></div></article>
          <article class="panel detail" id="formalDetail"><div class="empty">Select a formal knowledge base to inspect its complete content.</div></article>
        </div>
      </section>
      <section id="records" class="view">
        <div class="toolbar">
          <input id="recordSearch" class="search" type="search" placeholder="Filter unified records">
          <select id="recordType"><option value="all">All record types</option><option value="assertion">Assertions</option><option value="source">Sources</option><option value="domain">Canonical domains</option><option value="release">Releases</option></select>
          <select id="providerFilter"><option value="all">All providers</option></select>
          <select id="familyFilter"><option value="all">All product families</option></select>
        </div>
        <div class="records-layout">
          <article class="panel"><div class="panel-head"><div><h2>Knowledge records</h2><div id="recordCount" class="muted"></div></div></div><div id="recordList" class="record-list"></div></article>
          <article class="panel detail" id="recordDetail"><div class="empty">Select a record to inspect its controlled content and evidence.</div></article>
        </div>
      </section>
      <section id="relationships" class="view">
        <div class="panel-head"><div><h2>Evidence relationships</h2><div class="muted">Select an assertion to inspect its source → assertion → release chain and formal links.</div></div><select id="graphAssertion" style="max-width:430px"></select></div>
        <div class="graph-layout">
          <article class="panel graph"><svg id="relationshipGraph" viewBox="0 0 900 570" role="img" aria-label="Evidence relationship graph"></svg></article>
          <article class="panel"><h2>Relationship inspector</h2><div id="relationshipDetail" class="relation-list"></div></article>
        </div>
      </section>
      <section id="releases" class="view">
        <article class="panel"><div class="panel-head"><div><h2>Published releases</h2><div class="muted">Active immutable batches and their validated contents.</div></div></div><div style="overflow:auto"><table><thead><tr><th>Batch</th><th>Status</th><th>Features</th><th>Clauses</th><th>Rules</th><th>Sources</th><th>Gates</th><th>Created</th></tr></thead><tbody id="releaseRows"></tbody></table></div></article>
      </section>
    </main>
  </div>
  <script id="kb-visualizer-data" type="application/json">{payload}</script>
  <script>
    const data = JSON.parse(document.getElementById('kb-visualizer-data').textContent);
    const state = {{view:'overview', query:'', type:'all', provider:'all', family:'all', selected:null, formalQuery:'', formalBranch:'all', formalCategory:'all', formalLanguage:'all', selectedFormal:null}};
    const byId = new Map();
    const records = [
      ...data.assertions.map(x => ({{...x, record_type:'assertion', id:x.assertion_id, search:[x.label,x.provider,x.product_family,x.product,x.controlled_english,x.source_gloss,x.kind,x.batch_id].join(' ').toLowerCase()}})),
      ...data.sources.map(x => ({{...x, record_type:'source', id:x.source_id, label:x.document_ids[0] || x.source_id, product_family:'', search:[x.source_id,x.provider,...x.document_ids,...x.product_ids,...x.batches].join(' ').toLowerCase()}})),
      ...data.domains.map(x => ({{...x, record_type:'domain', id:x.domain_id, provider:'', product_family:'', search:[x.label,x.branch,x.category,x.artifact_type,x.language,x.role].join(' ').toLowerCase()}})),
      ...data.releases.map(x => ({{...x, record_type:'release', id:x.release_id, label:x.batch_id, provider:'', product_family:'', search:[x.release_id,x.batch_id,x.status,x.created_at || ''].join(' ').toLowerCase()}}))
    ];
    records.forEach(x => byId.set(x.id,x));
    const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
    const title = value => String(value ?? 'Unknown').replaceAll('_',' ').replaceAll('-',' ').replace(/\\b\\w/g,c=>c.toUpperCase());
    const shortId = value => {{ const raw=String(value ?? ''); const parts=raw.split(':'); const tail=parts.at(-1); return tail.length>22 ? `${{parts[0]}}:${{tail.slice(0,12)}}…` : raw; }};
    const badge = (value,extra='') => `<span class="badge ${{esc(extra)}}">${{esc(title(value))}}</span>`;
    const metric = (value,label) => `<div class="metric"><strong>${{Number(value).toLocaleString()}}</strong><span>${{esc(label)}}</span></div>`;

    document.querySelectorAll('.nav-btn').forEach(button => button.addEventListener('click',() => showView(button.dataset.view)));
    function showView(view) {{ state.view=view; document.querySelectorAll('.nav-btn').forEach(x=>x.classList.toggle('active',x.dataset.view===view)); document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===view)); if(view==='relationships') renderRelationshipGraph(); if(view==='formal') renderFormalKBs(); }}

    document.getElementById('globalSearch').addEventListener('input', event => {{ state.query=event.target.value.trim().toLowerCase(); document.getElementById('recordSearch').value=event.target.value; showView('records'); renderRecordList(); }});
    document.getElementById('recordSearch').addEventListener('input', event => {{ state.query=event.target.value.trim().toLowerCase(); document.getElementById('globalSearch').value=event.target.value; renderRecordList(); }});
    for (const [id,key] of [['recordType','type'],['providerFilter','provider'],['familyFilter','family']]) document.getElementById(id).addEventListener('change',event=>{{state[key]=event.target.value;renderRecordList();}});

    function renderOverview() {{
      const s=data.summary;
      document.getElementById('summaryMetrics').innerHTML=[metric(s.domains,'Formal KBs'),metric(s.assertions,'Published assertions'),metric(s.sources,'Grounding sources'),metric(s.published_releases,'Active releases'),metric(s.providers,'Providers'),metric(s.product_families,'Product families')].join('');
      renderBars('kindBars',data.assertion_kind_counts); renderBars('reviewBars',data.review_state_counts);
      renderChips('providerChips',data.provider_counts); renderChips('familyChips',data.product_family_counts);
    }}
    function renderBars(id,counts) {{ const rows=Object.entries(counts).sort((a,b)=>b[1]-a[1]); const max=Math.max(1,...rows.map(x=>x[1])); document.getElementById(id).innerHTML=rows.map(([name,count])=>`<div class="bar-row"><span>${{esc(title(name))}}</span><div class="bar-track"><div class="bar-fill" style="width:${{100*count/max}}%"></div></div><span class="bar-count">${{count.toLocaleString()}}</span></div>`).join(''); }}
    function renderChips(id,counts) {{ document.getElementById(id).innerHTML=Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([name,count])=>`<button class="chip" data-filter="${{esc(name)}}">${{esc(title(name))}} <strong>${{count}}</strong></button>`).join(''); document.getElementById(id).querySelectorAll('.chip').forEach(x=>x.addEventListener('click',()=>{{ const provider=id==='providerChips'; state[provider?'provider':'family']=x.dataset.filter; document.getElementById(provider?'providerFilter':'familyFilter').value=x.dataset.filter; showView('records'); renderRecordList(); }})); }}

    function fillFilters() {{
      const providers=[...new Set(data.assertions.map(x=>x.provider))].sort(); const families=[...new Set(data.assertions.map(x=>x.product_family))].sort();
      document.getElementById('providerFilter').innerHTML='<option value="all">All providers</option>'+providers.map(x=>`<option value="${{esc(x)}}">${{esc(title(x))}}</option>`).join('');
      document.getElementById('familyFilter').innerHTML='<option value="all">All product families</option>'+families.map(x=>`<option value="${{esc(x)}}">${{esc(title(x))}}</option>`).join('');
    }}
    function fillFormalFilters() {{
      for (const [id,key,label] of [['formalBranch','branch','branches'],['formalCategory','category','categories'],['formalLanguage','language','languages']]) {{
        const values=[...new Set(data.domains.map(x=>x[key]))].sort();
        document.getElementById(id).innerHTML=`<option value="all">All ${{label}}</option>`+values.map(x=>`<option value="${{esc(x)}}">${{esc(title(x))}}</option>`).join('');
        document.getElementById(id).addEventListener('change',event=>{{state[id]=event.target.value;renderFormalKBs();}});
      }}
      document.getElementById('formalSearch').addEventListener('input',event=>{{state.formalQuery=event.target.value.trim().toLowerCase();renderFormalKBs();}});
    }}
    function formalDomains() {{ return data.domains.filter(x => (state.formalBranch==='all'||x.branch===state.formalBranch) && (state.formalCategory==='all'||x.category===state.formalCategory) && (state.formalLanguage==='all'||x.language===state.formalLanguage) && (!state.formalQuery||[x.label,x.role,x.category,x.artifact_type,x.language,typeof x.content==='string'?x.content:JSON.stringify(x.content)].join(' ').toLowerCase().includes(state.formalQuery))); }}
    function renderFormalKBs() {{
      const items=formalDomains(); document.getElementById('formalCount').textContent=`${{items.length}} canonical domains · complete sanitized content`;
      document.getElementById('formalList').innerHTML=items.length?items.map(x=>`<button class="record ${{state.selectedFormal===x.domain_id?'active':''}}" data-id="${{esc(x.domain_id)}}"><div class="record-top"><strong>${{esc(x.label)}}</strong>${{badge(x.language,x.language)}}</div><div class="record-meta">${{esc(title(x.category))}} · ${{x.rule_count}} rules · ${{x.fact_count}} facts</div></button>`).join(''):'<div class="empty">No formal knowledge bases match the filters.</div>';
      document.getElementById('formalList').querySelectorAll('.record').forEach(x=>x.addEventListener('click',()=>selectFormalKB(x.dataset.id)));
      if((!state.selectedFormal||!items.some(x=>x.domain_id===state.selectedFormal))&&items.length) selectFormalKB(items[0].domain_id,false);
    }}
    function selectFormalKB(id,rerender=true) {{ state.selectedFormal=id; if(rerender)renderFormalKBs(); renderFormalDetail(data.domains.find(x=>x.domain_id===id)); }}
    function renderFormalDetail(record) {{
      const target=document.getElementById('formalDetail'); if(!record){{target.innerHTML='<div class="empty">Select a formal knowledge base.</div>';return;}}
      const isProgram=typeof record.content==='string';
      target.innerHTML=`${{badge(record.language,record.language)}}<div class="detail-title">${{esc(record.label)}}</div><p>${{esc(record.role)}}</p><div class="detail-grid">${{cell('Branch',title(record.branch))}}${{cell('Category',title(record.category))}}${{cell('Formalism',title(record.language))}}${{cell('Records',record.record_count)}}${{cell('Facts',record.fact_count)}}${{cell('Rules',record.rule_count)}}</div><h3>${{isProgram?'Complete formal program':'Complete structured knowledge'}}</h3>${{isProgram?`<pre class="formal-source">${{esc(record.content||'No formal content available.')}}</pre>`:renderStructuredKnowledge(record.content)}}`;
    }}
    function renderStructuredKnowledge(content) {{
      let items=Array.isArray(content)?content:null;
      if(!items&&content&&typeof content==='object') items=Object.values(content).find(value=>Array.isArray(value));
      if(!items) items=[content];
      return `<div class="formal-records">${{items.map((item,index)=>{{
        const semanticId=item&&typeof item==='object'?(item.rule_id||item.clause_id||item.predicate_id||item.unit_id||item.span_id||item.assertion_id||item.id||item.name):null;
        const fields=item&&typeof item==='object'&&!Array.isArray(item)?Object.entries(item):[['value',item]];
        return `<details ${{index===0?'open':''}}><summary>${{esc(semanticId||`Record ${{index+1}}`)}}</summary><table class="formal-fields"><tbody>${{fields.map(([key,value])=>`<tr><td>${{esc(title(key))}}</td><td>${{value!==null&&typeof value==='object'?`<pre>${{esc(JSON.stringify(value,null,2))}}</pre>`:esc(value)}}</td></tr>`).join('')}}</tbody></table></details>`;
      }}).join('')}}</div>`;
    }}
    function filteredRecords() {{ return records.filter(x => (state.type==='all'||x.record_type===state.type) && (state.provider==='all'||x.provider===state.provider) && (state.family==='all'||x.product_family===state.family) && (!state.query||x.search.includes(state.query))); }}
    function renderRecordList() {{
      const items=filteredRecords(); document.getElementById('recordCount').textContent=`${{items.length.toLocaleString()}} matching records`;
      document.getElementById('recordList').innerHTML=items.length ? items.map(x=>`<button class="record ${{state.selected===x.id?'active':''}}" data-id="${{esc(x.id)}}"><div class="record-top"><strong>${{esc(x.label)}}</strong>${{badge(x.record_type,x.kind||x.record_type)}}</div><div class="record-meta">${{esc(x.provider||title(x.category||x.status||''))}}${{x.product_family?' · '+esc(title(x.product_family)):''}}</div></button>`).join('') : '<div class="empty">No records match the current filters.</div>';
      document.getElementById('recordList').querySelectorAll('.record').forEach(x=>x.addEventListener('click',()=>selectRecord(x.dataset.id)));
      if(!state.selected && items.length) selectRecord(items[0].id,false);
    }}
    function selectRecord(id,rerender=true) {{ state.selected=id; if(rerender) renderRecordList(); renderRecordDetail(byId.get(id)); if(byId.get(id)?.record_type==='assertion') {{ document.getElementById('graphAssertion').value=id; }} }}
    const cell=(label,value)=>`<div class="detail-cell"><span>${{esc(label)}}</span><strong>${{esc(value||'—')}}</strong></div>`;
    function renderRecordDetail(record) {{
      const target=document.getElementById('recordDetail'); if(!record) {{target.innerHTML='<div class="empty">Select a record.</div>';return;}}
      if(record.record_type==='assertion') target.innerHTML=`${{badge(record.kind,record.kind)}}<div class="detail-title">${{esc(record.label)}}</div><div class="muted">${{esc(shortId(record.assertion_id))}}</div><div class="detail-grid">${{cell('Provider',title(record.provider))}}${{cell('Product family',title(record.product_family))}}${{cell('Product',record.product)}}${{cell('Review state',title(record.review_state))}}${{cell('Batch',record.batch_id)}}${{cell('Jurisdiction',record.jurisdiction)}}</div><div class="statement"><strong>Controlled English</strong><div>${{esc(record.controlled_english||'No controlled-English annotation supplied.')}}</div></div><div class="statement original"><strong>Source-language gloss</strong><div>${{esc(record.source_gloss||'No source-language gloss supplied.')}}</div></div><h3>Formal details</h3><pre>${{esc(JSON.stringify(record.details,null,2))}}</pre>`;
      else if(record.record_type==='source') target.innerHTML=`${{badge('source','source')}}<div class="detail-title">${{esc(record.label)}}</div><div class="muted">${{esc(shortId(record.source_id))}}</div><div class="detail-grid">${{cell('Provider',title(record.provider))}}${{cell('Assertions',record.assertion_ids.length)}}${{cell('Batches',record.batches.length)}}${{cell('Documents',record.document_ids.length)}}</div><h3>Grounded assertions</h3><pre>${{esc(record.assertion_ids.map(shortId).join('\\n')||'None')}}</pre>${{record.web_url?`<div class="statement"><strong>Public source</strong><div><a style="color:var(--cyan)" href="${{esc(record.web_url)}}" target="_blank" rel="noopener">Open publisher source</a></div></div>`:''}}`;
      else if(record.record_type==='domain') target.innerHTML=`${{badge('domain')}}<div class="detail-title">${{esc(record.label)}}</div><p>${{esc(record.role)}}</p><div class="detail-grid">${{cell('Branch',title(record.branch))}}${{cell('Category',title(record.category))}}${{cell('Language',title(record.language))}}${{cell('Records',record.record_count)}}${{cell('Facts',record.fact_count)}}${{cell('Rules',record.rule_count)}}</div><div class="statement"><strong>Canonical formal KB</strong><div>Open the Formal KBs view to inspect the complete content.</div></div>`;
      else target.innerHTML=`${{badge('release','release')}}<div class="detail-title">${{esc(record.batch_id)}}</div><div class="muted">${{esc(shortId(record.release_id))}}</div><div class="detail-grid">${{cell('Status',title(record.status))}}${{cell('Created',record.created_at)}}${{cell('Features',record.features)}}${{cell('Clauses',record.clauses)}}${{cell('Rules',record.rules)}}${{cell('Automated gates',record.automated_gates)}}</div>`;
    }}

    function fillGraphAssertions() {{ const select=document.getElementById('graphAssertion'); select.innerHTML=data.assertions.map(x=>`<option value="${{esc(x.assertion_id)}}">${{esc(x.label)}} · ${{esc(title(x.provider))}}</option>`).join(''); select.addEventListener('change',renderRelationshipGraph); }}
    function renderRelationshipGraph() {{
      const id=document.getElementById('graphAssertion').value || data.assertions[0]?.assertion_id; const assertion=data.assertions.find(x=>x.assertion_id===id); const svg=document.getElementById('relationshipGraph'); const detail=document.getElementById('relationshipDetail'); if(!assertion){{svg.innerHTML='';detail.innerHTML='<div class="empty">No assertion selected.</div>';return;}}
      const edges=data.relationships.filter(x=>x.source_id===id||x.target_id===id); const relatedIds=[...new Set(edges.flatMap(x=>[x.source_id,x.target_id]).filter(x=>x!==id))].slice(0,12); const nodes=[{{id,type:'assertion',label:assertion.label,x:450,y:285}},...relatedIds.map((rid,index)=>{{const angle=(2*Math.PI*index)/Math.max(relatedIds.length,1)-Math.PI/2; const rec=byId.get(rid); return {{id:rid,type:rec?.record_type||'relation',label:rec?.label||shortId(rid),x:450+290*Math.cos(angle),y:285+210*Math.sin(angle)}};}})]; const nodeMap=new Map(nodes.map(x=>[x.id,x]));
      svg.innerHTML=`<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#4f748c"/></marker></defs>`+edges.filter(x=>nodeMap.has(x.source_id)&&nodeMap.has(x.target_id)).map(e=>{{const a=nodeMap.get(e.source_id),b=nodeMap.get(e.target_id);return `<line class="edge active" x1="${{a.x}}" y1="${{a.y}}" x2="${{b.x}}" y2="${{b.y}}" marker-end="url(#arrow)"/>`;}}).join('')+nodes.map(n=>`<g class="node ${{esc(n.type)}}" data-id="${{esc(n.id)}}" transform="translate(${{n.x}},${{n.y}})"><circle r="${{n.id===id?34:25}}"></circle><text text-anchor="middle" y="${{n.id===id?52:42}}">${{esc(n.label.length>34?n.label.slice(0,32)+'…':n.label)}}</text></g>`).join('');
      svg.querySelectorAll('.node').forEach(x=>x.addEventListener('click',()=>{{const rec=byId.get(x.dataset.id);if(rec){{showView('records');selectRecord(rec.id);}}}}));
      detail.innerHTML=`<div class="statement"><strong>${{esc(assertion.label)}}</strong><div>${{esc(assertion.controlled_english)}}</div></div>`+(edges.length?edges.map(e=>`<div class="relation">${{badge(e.relation_type)}}<div style="margin-top:5px">${{esc(e.label)}}</div><div class="muted">${{esc(shortId(e.source_id))}} → ${{esc(shortId(e.target_id))}}</div></div>`).join(''):'<div class="empty">No direct relationships.</div>');
    }}
    function renderReleases() {{ document.getElementById('releaseRows').innerHTML=data.releases.map(x=>`<tr><td><strong>${{esc(x.batch_id)}}</strong><div class="muted">${{esc(shortId(x.release_id))}}</div></td><td>${{badge(x.status,'release')}}</td><td>${{x.features}}</td><td>${{x.clauses}}</td><td>${{x.rules}}</td><td>${{x.sources}}</td><td>${{x.automated_gates}}</td><td>${{esc((x.created_at||'').replace('T',' ').replace('Z',' UTC'))}}</td></tr>`).join(''); }}

    renderOverview(); fillFilters(); fillFormalFilters(); fillGraphAssertions(); renderFormalKBs(); renderRecordList(); renderReleases(); renderRelationshipGraph();
  </script>
</body>
</html>
"""


def _build_domains(repository_root: Path | None = None) -> list[KBDomainRecord]:
    root = repository_root if repository_root is not None else REPO_ROOT
    manifest = read_yaml(root / "kb/manifest.yaml" if repository_root is not None else KB_MANIFEST)
    domains: list[KBDomainRecord] = []
    for index, entry in enumerate(manifest.get("entries", []), start=1):
        internal_location = str(entry.get("kb_path", ""))
        target = root / internal_location
        text = ""
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        lines = text.splitlines()
        statements = [
            line.strip()
            for line in lines
            if line.strip()
            and not line.lstrip().startswith(("%", "#"))
            and not _looks_like_internal_location(line.strip())
        ]
        parsed: Any = None
        if target.suffix.lower() in {".yaml", ".yml"}:
            try:
                parsed = _sanitize_payload(read_yaml(target))
            except Exception:
                parsed = None
        sample = parsed[:2] if isinstance(parsed, list) else parsed
        if sample in ({}, [], None):
            sample = statements[:10]
        content = parsed if parsed not in ({}, [], None) else _sanitize_formal_source(text)
        artifact_type = str(entry.get("artifact_type", "knowledge_artifact"))
        digest = str(entry.get("kb_sha256", ""))
        domains.append(
            KBDomainRecord(
                domain_id=f"domain:{artifact_type}:{index}",
                label=_domain_label(entry),
                branch=str(entry.get("branch", "unknown")),
                category=str(entry.get("category", "unknown")),
                artifact_type=artifact_type,
                language=str(entry.get("language", "unknown")),
                role=str(entry.get("role", "")),
                digest=digest,
                size_bytes=len(text.encode("utf-8")),
                line_count=len(lines),
                record_count=_record_count(parsed),
                rule_count=sum(":-" in line for line in statements),
                fact_count=sum(line.endswith(".") and ":-" not in line for line in statements),
                content=content,
                sample=sample,
            )
        )
    return domains


def _active_release_pointers(repository_root: Path | None = None) -> list[dict[str, Any]]:
    release_root = (
        repository_root / "kb/releases/product_onboarding" if repository_root is not None else None
    )
    active_dir = release_root / "active_batches" if release_root is not None else ACTIVE_BATCH_DIR
    legacy = (
        release_root / "active_batch_01.yaml" if release_root is not None else LEGACY_ACTIVE_BATCH
    )
    locations = ([legacy] if legacy.exists() else []) + (
        sorted(active_dir.glob("*.yaml")) if active_dir.exists() else []
    )
    pointers: dict[str, dict[str, Any]] = {}
    for location in locations:
        pointer = dict(read_yaml(location))
        pointer.setdefault("batch_id", Path(str(pointer["assertions"])).parent.name)
        pointers[str(pointer["batch_id"])] = pointer
    return [pointers[key] for key in sorted(pointers)]


def _load_release(
    pointer: dict[str, Any],
    repository_root: Path | None = None,
) -> tuple[KBReleaseRecord, list[KBAssertionRecord], list[dict[str, Any]], list[KBRelationship]]:
    root = repository_root if repository_root is not None else REPO_ROOT
    batch_id = str(pointer["batch_id"])
    release_id = str(pointer["kb_release_id"])
    release_manifest = _read_json_internal(str(pointer["manifest"]), root)
    raw_assertions = _records(read_yaml(root / str(pointer["assertions"])))
    raw_annotations = _records(read_yaml(root / str(pointer["annotations"])))
    annotation_map = {str(item.get("formal_element_id")): item for item in raw_annotations}
    batch_root = root / "data" / "operations" / "progressive_onboarding" / "batches" / batch_id
    source_location = batch_root / "output" / "source_registry.yaml"
    raw_sources = _records(read_yaml(source_location)) if source_location.exists() else []
    assertion_records: list[KBAssertionRecord] = []
    relations: list[KBRelationship] = []
    for raw in raw_assertions:
        record = _build_assertion(
            raw, annotation_map.get(str(raw.get("assertion_id")), {}), batch_id, release_id
        )
        assertion_records.append(record)
        relations.append(
            _relation(
                record.assertion_id, release_id, "published_in", "Published in active release"
            )
        )
        for source_id in record.source_ids:
            relations.append(
                _relation(source_id, record.assertion_id, "grounds", "Source grounds assertion")
            )
        for dependency in record.dependencies:
            relations.append(
                _relation(record.assertion_id, dependency, "depends_on", "Depends on assertion")
            )
        for target in record.contradicts:
            relations.append(
                _relation(record.assertion_id, target, "contradicts", "Contradicts assertion")
            )
        for target in record.precedes:
            relations.append(
                _relation(
                    record.assertion_id, target, "precedes", "Takes precedence over assertion"
                )
            )
        for target in record.related_assertions:
            relations.append(
                _relation(record.assertion_id, target, "policy_evidence", "Linked policy evidence")
            )
    release = KBReleaseRecord(
        release_id=release_id,
        batch_id=batch_id,
        status=str(release_manifest.get("release_status", "unknown")),
        created_at=release_manifest.get("created_at"),
        corpus_snapshot_id=release_manifest.get("corpus_snapshot_id"),
        projection_id=pointer.get("projection_id"),
        features=sum(item.kind == "feature" for item in assertion_records),
        clauses=sum(item.kind == "clause" for item in assertion_records),
        rules=sum(item.kind == "rule" for item in assertion_records),
        sources=len(release_manifest.get("source_version_hashes", {})),
        annotations=len(release_manifest.get("annotation_hashes", {})),
        automated_gates=len(release_manifest.get("automated_gate_hashes", {})),
        validators=len(release_manifest.get("validator_hashes", {})),
        digest=stable_hash(release_manifest),
    )
    return release, assertion_records, raw_sources, relations


def _build_assertion(
    raw: dict[str, Any], annotation: dict[str, Any], batch_id: str, release_id: str
) -> KBAssertionRecord:
    assertion_id = str(raw.get("assertion_id", "unknown_assertion"))
    details = _sanitize_payload(raw.get("payload", {}))
    if not isinstance(details, dict):
        details = {"value": details}
    record = (
        raw.get("payload", {}).get("record", {}) if isinstance(raw.get("payload"), dict) else {}
    )
    product = str(raw.get("product_id") or record.get("product") or "Unknown")
    labels = record.get("labels", {}) if isinstance(record, dict) else {}
    label = str(
        labels.get("offer_document")
        or labels.get("admin")
        or record.get("title")
        or product
        or assertion_id
    )
    related = []
    grounding = record.get("policy_grounding", {}) if isinstance(record, dict) else {}
    if isinstance(grounding, dict):
        related.extend(str(item) for item in grounding.get("clauses", []))
    related.extend(str(item) for item in record.get("policy_evidence_refs", []) if item)
    return KBAssertionRecord(
        assertion_id=assertion_id,
        label=label,
        kind=str(raw.get("assertion_kind", "unknown")),
        provider=str(raw.get("provider") or record.get("provider") or "Unknown"),
        product_family=str(raw.get("product_family") or record.get("product_family") or "unknown"),
        product=product,
        jurisdiction=str(raw.get("jurisdiction", "unknown")),
        batch_id=batch_id,
        release_id=release_id,
        review_state=str(annotation.get("review_state", "unannotated")),
        source_language=str(annotation.get("source_language", "unknown")),
        source_gloss=str(annotation.get("source_language_gloss", "")),
        controlled_english=str(annotation.get("controlled_english", "")),
        source_ids=[str(item) for item in raw.get("source_version_ids", [])],
        span_ids=[str(item) for item in annotation.get("source_span_ids", [])],
        dependencies=[str(item) for item in raw.get("dependencies", [])],
        contradicts=[str(item) for item in raw.get("contradicts", [])],
        precedes=[str(item) for item in raw.get("precedes", [])],
        related_assertions=sorted(set(related)),
        digest=str(raw.get("payload_sha256", "")),
        details=details,
    )


def _merge_sources(accumulator: dict[str, dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    for source in sources:
        for source_id in source.get("source_version_ids", []):
            key = str(source_id)
            item = accumulator.setdefault(
                key,
                {
                    "source_id": key,
                    "providers": set(),
                    "document_ids": set(),
                    "product_ids": set(),
                    "batches": set(),
                    "web_urls": set(),
                },
            )
            item["providers"].add(str(source.get("provider_id", "Unknown")))
            item["document_ids"].update(str(value) for value in source.get("document_ids", []))
            item["product_ids"].update(str(value) for value in source.get("product_ids", []))
            canonical_url = source.get("canonical_url")
            if canonical_url:
                item["web_urls"].add(str(canonical_url))
            source_task = str(source.get("source_task_id", ""))
            if source_task:
                item["batches"].add(source_task)


def _finalize_sources(
    accumulator: dict[str, dict[str, Any]], assertions: list[KBAssertionRecord]
) -> list[KBSourceRecord]:
    assertion_map: dict[str, list[str]] = defaultdict(list)
    batch_map: dict[str, set[str]] = defaultdict(set)
    for assertion in assertions:
        for source_id in assertion.source_ids:
            assertion_map[source_id].append(assertion.assertion_id)
            batch_map[source_id].add(assertion.batch_id)
    records: list[KBSourceRecord] = []
    for source_id in sorted(set(accumulator) | set(assertion_map)):
        item = accumulator.get(source_id, {})
        providers = sorted(item.get("providers", {"Unknown"}))
        urls = sorted(item.get("web_urls", set()))
        payload = {
            "source_id": source_id,
            "provider": providers[0] if providers else "Unknown",
            "document_ids": sorted(item.get("document_ids", set())),
            "product_ids": sorted(item.get("product_ids", set())),
            "batches": sorted(batch_map.get(source_id, set())),
            "assertion_ids": sorted(set(assertion_map.get(source_id, []))),
            "web_url": urls[0] if urls else None,
        }
        records.append(KBSourceRecord(**payload, digest=stable_hash(payload)))
    return records


def _deduplicate_assertions(assertions: list[KBAssertionRecord]) -> list[KBAssertionRecord]:
    unique: dict[str, KBAssertionRecord] = {}
    for assertion in assertions:
        unique[assertion.assertion_id] = assertion
    return list(unique.values())


def _deduplicate_relationships(relationships: list[KBRelationship]) -> list[KBRelationship]:
    unique = {item.relation_id: item for item in relationships}
    return sorted(unique.values(), key=lambda item: item.relation_id)


def _relation(source_id: str, target_id: str, relation_type: str, label: str) -> KBRelationship:
    identity = {"source_id": source_id, "target_id": target_id, "relation_type": relation_type}
    return KBRelationship(
        relation_id=f"relation:{stable_hash(identity).removeprefix('sha256:')[:24]}",
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        label=label,
    )


def _sanitize_payload(value: Any) -> Any:
    """Remove repository-location metadata while retaining semantic content."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if (
                "path" in lowered
                or "file" in lowered
                or lowered
                in {
                    "manifest",
                    "manifests",
                    "compiled",
                    "compiled_targets",
                    "legacy_locations",
                    "seeded_from",
                }
            ):
                continue
            sanitized = _sanitize_payload(child)
            if sanitized is not None:
                result[str(key)] = sanitized
        return result
    if isinstance(value, list):
        return [item for child in value if (item := _sanitize_payload(child)) is not None]
    if isinstance(value, str) and _looks_like_internal_location(value):
        return None
    return value


def _looks_like_internal_location(value: str) -> bool:
    stripped = value.strip().replace("\\", "/")
    if stripped.startswith(("http://", "https://")):
        return False
    prefixes = (
        "/Users/",
        "kb/",
        "data/",
        "build/",
        "rules/",
        "docs/",
        "ruler/",
        ".opencode/",
        ".claude/",
    )
    return stripped.startswith(prefixes) or bool(re.match(r"^[A-Za-z]:/", stripped))


def _forbidden_path_fragments() -> tuple[str, ...]:
    return (
        "/Users/",
        "kb/formalized/",
        "data/operations/",
        "data/sources/",
        "build/ruler/",
        "\\Users\\",
    )


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _record_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return len(payload)
    return 0


def _logical_programs(model: KBVisualization) -> list[KBDomainRecord]:
    """Return each canonical compiled ASP or Prolog program exactly once."""
    return [
        item
        for item in model.domains
        if item.language in {"asp", "prolog"} and isinstance(item.content, str)
    ]


def _executable_program_modules(
    programs: list[KBDomainRecord], assertions: list[KBAssertionRecord]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """Build logic, evidence, gap, and dependency views from compiled programs."""
    assertion_lookup = _assertion_lookup(assertions)
    modules: list[dict[str, Any]] = []
    evidence_by_id: dict[str, dict[str, Any]] = {}
    compiled_assertion_ids: set[str] = set()
    dependency_edges: list[dict[str, str]] = []
    for program in programs:
        statements = _logic_statements(str(program.content))
        source_links = _program_source_links(statements)
        entity_comments = _program_entity_comments(statements)
        predicate_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        rule_count = 0
        fact_count = 0
        constraint_count = 0
        directive_count = 0
        for index, (statement, comments) in enumerate(statements, start=1):
            predicate = _statement_predicate(statement)
            if predicate in _PROVENANCE_PREDICATES:
                continue
            kind = _statement_kind(statement)
            rule_count += int(kind == "rule")
            fact_count += int(kind == "fact")
            constraint_count += int(kind == "constraint")
            directive_count += int(kind == "directive")
            clause_ids = _statement_source_clause_ids(statement, predicate, source_links)
            subject = _statement_subject(statement)
            if subject in assertion_lookup and subject not in clause_ids:
                clause_ids.append(subject)
            effective_comments = comments or entity_comments.get(_statement_subject(statement), [])
            matched_assertions = _matching_assertions(clause_ids, assertion_lookup)
            compiled_assertion_ids.update(item.assertion_id for item in matched_assertions)
            document_parts = _logic_document_parts(
                clause_ids, effective_comments, matched_assertions
            )
            clause_id = f"{program.domain_id}:statement:{index}"
            evidence_ids: list[str] = []
            for part in document_parts:
                evidence = _evidence_record(part)
                evidence_id = str(evidence["evidence_id"])
                evidence_ids.append(evidence_id)
                current = evidence_by_id.setdefault(evidence_id, evidence)
                current["logical_clause_ids"] = sorted({*current["logical_clause_ids"], clause_id})
                current["assertion_ids"] = sorted(
                    {
                        *current["assertion_ids"],
                        *(item.assertion_id for item in matched_assertions),
                    }
                )
            providers = sorted(
                {
                    *(item.provider for item in matched_assertions if item.provider),
                    *(
                        str(part.get("provider"))
                        for part in document_parts
                        if part.get("provider") not in {None, "", "unknown"}
                    ),
                }
            )
            if not providers:
                providers = [_source_provider(clause_ids, effective_comments, program.label)]
            product_families = sorted(
                {item.product_family for item in matched_assertions if item.product_family}
            )
            if not product_families:
                product_families = _statement_product_families(statement, program.label)
            modalities = sorted(
                {
                    str(item.details.get("record", {}).get("modality", item.kind))
                    for item in matched_assertions
                }
            ) or [_statement_modality(statement, kind)]
            reviews = sorted(
                {
                    *(item.review_state for item in matched_assertions),
                    *(
                        str(part.get("review_state"))
                        for part in document_parts
                        if part.get("review_state") not in {None, "", "unmapped"}
                    ),
                }
            ) or ["unmapped"]
            states = sorted(
                {_assertion_formalization_state(item, True) for item in matched_assertions}
            )
            if not states:
                states = ["compiled"]
            dependencies = _statement_dependencies(statement, predicate)
            predicate_groups[predicate].append(
                {
                    "clause_id": clause_id,
                    "label": statement.splitlines()[0][:100],
                    "kind": kind,
                    "modality": modalities,
                    "predicate": predicate,
                    "logic": statement,
                    "providers": providers,
                    "product_families": product_families,
                    "formalization_states": states,
                    "review_statuses": reviews,
                    "source_documents": sorted(
                        {
                            str(part.get("document_id", ""))
                            for part in document_parts
                            if part.get("document_id")
                        }
                    )
                    or ["unmapped"],
                    "evidence_ids": evidence_ids,
                    "dependencies": dependencies,
                }
            )
            dependency_edges.extend(
                {
                    "source_id": f"predicate:{dependency}",
                    "target_id": clause_id,
                    "relation": "condition_for",
                }
                for dependency in dependencies
            )
            if kind in {"rule", "fact"}:
                dependency_edges.append(
                    {
                        "source_id": clause_id,
                        "target_id": f"predicate:{predicate}",
                        "relation": "concludes",
                    }
                )
        family_nodes = [
            {
                "family_id": predicate,
                "label": predicate,
                "assertion_count": len(predicate_groups[predicate]),
                "assertions": predicate_groups[predicate],
            }
            for predicate in sorted(predicate_groups)
        ]
        modules.append(
            {
                "program_id": program.domain_id,
                "label": program.label,
                "formalism": program.language,
                "representation_kind": "executable_program",
                "branch": program.branch,
                "role": program.role,
                "clause_count": sum(len(item["assertions"]) for item in family_nodes),
                "families": [item["family_id"] for item in family_nodes],
                "family_nodes": family_nodes,
                "rule_count": rule_count,
                "fact_count": fact_count,
                "constraint_count": constraint_count,
                "directive_count": directive_count,
                "digest": program.digest,
            }
        )
    gaps = [
        _coverage_gap(item)
        for item in assertions
        if item.assertion_id not in compiled_assertion_ids
    ]
    unique_edges = {stable_hash(item): item for item in dependency_edges}
    return (
        modules,
        sorted(evidence_by_id.values(), key=lambda item: str(item["evidence_id"])),
        sorted(gaps, key=lambda item: (str(item["provider"]), str(item["label"]))),
        sorted(
            unique_edges.values(),
            key=lambda item: (item["source_id"], item["target_id"]),
        ),
    )


_PROVENANCE_PREDICATES = {
    "cross_reference_label",
    "operational_predicate_source",
    "source_clause",
}


def _logic_statements(program: str) -> list[tuple[str, list[str]]]:
    """Split the repository's line-oriented ASP/Prolog programs into clauses."""
    statements: list[tuple[str, list[str]]] = []
    pending_comments: list[str] = []
    buffer: list[str] = []
    for line in program.splitlines():
        stripped = line.strip()
        if stripped.startswith("%") and not buffer:
            pending_comments.append(stripped.removeprefix("%").strip())
            continue
        if not stripped:
            continue
        buffer.append(line)
        if stripped.endswith(".") or stripped.startswith("#show"):
            statements.append(("\n".join(buffer).strip(), pending_comments))
            buffer = []
            pending_comments = []
    if buffer:
        statements.append(("\n".join(buffer).strip(), pending_comments))
    return statements


def _statement_predicate(statement: str) -> str:
    if statement.lstrip().startswith("#"):
        return "directives"
    match = re.match(r"\s*([a-z][A-Za-z0-9_]*)\s*(?:\(|\.)", statement)
    return match.group(1) if match else "other"


def _program_source_links(
    statements: list[tuple[str, list[str]]],
) -> dict[str, set[str]]:
    links: dict[str, set[str]] = defaultdict(set)
    for statement, _comments in statements:
        source_match = re.fullmatch(
            r"source_clause\(\s*([^,]+),\s*([^)]+)\)\.", statement, re.DOTALL
        )
        if source_match:
            links[source_match.group(1).strip().strip('"')].add(
                source_match.group(2).strip().strip('"')
            )
        operational_match = re.fullmatch(
            r'operational_predicate_source\(\s*"([^"/]+)[^"]*",\s*([^)]+)\)\.',
            statement,
            re.DOTALL,
        )
        if operational_match:
            links[operational_match.group(1)].add(operational_match.group(2).strip().strip('"'))
    return links


def _statement_source_clause_ids(
    statement: str, predicate: str, source_links: dict[str, set[str]]
) -> list[str]:
    clause_ids = set(source_links.get(predicate, set()))
    for rule_id in re.findall(r"\b(rule_[a-zA-Z0-9_]+)\b", statement):
        clause_ids.update(source_links.get(rule_id, set()))
    if predicate == "source_clause":
        match = re.fullmatch(r"source_clause\(\s*[^,]+,\s*([^)]+)\)\.", statement, re.DOTALL)
        if match:
            clause_ids.add(match.group(1).strip().strip('"'))
    return sorted(clause_ids)


def _logic_document_parts(
    clause_ids: list[str],
    comments: list[str],
    assertions: list[KBAssertionRecord],
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for assertion in assertions:
        parts.extend(_assertion_document_parts(assertion))
    matched_ids = {
        value
        for part in parts
        for key in ("assertion_ids", "source_ids", "span_ids")
        for value in part.get(key, [])
    }
    for clause_id in clause_ids:
        if clause_id not in matched_ids:
            parts.append(_empty_document_part(clause_id))
    annotation = next(
        (
            item.removeprefix("Annotation-ID:").strip()
            for item in comments
            if item.startswith("Annotation-ID:")
        ),
        "",
    )
    source_text = next(
        (item.removeprefix("NL-FR:").strip() for item in comments if item.startswith("NL-FR:")),
        next(
            (
                item.removeprefix("Source FR:").strip()
                for item in comments
                if item.startswith("Source FR:")
            ),
            "",
        ),
    )
    controlled_english = next(
        (item.removeprefix("NL-EN:").strip() for item in comments if item.startswith("NL-EN:")),
        next(
            (
                item.removeprefix("Controlled EN:").strip()
                for item in comments
                if item.startswith("Controlled EN:")
            ),
            "",
        ),
    )
    source_section = next(
        (
            item.removeprefix("Source section:").strip()
            for item in comments
            if item.startswith("Source section:")
        ),
        "",
    )
    document_id, _, span_id = source_section.partition(" / ")
    if annotation or source_text or controlled_english or source_section:
        parts.append(
            {
                "assertion_ids": [],
                "source_ids": [annotation] if annotation else [],
                "span_ids": [span_id] if span_id else [],
                "provider": _comment_provider(comments),
                "document_id": document_id,
                "edition": "unknown",
                "section": source_section or source_text,
                "source_language": "fr" if source_text else "unknown",
                "review_state": "reviewed" if annotation else "unmapped",
                "source_excerpt": source_text,
                "controlled_english": controlled_english,
            }
        )
    unique = {stable_hash(part): part for part in parts}
    return list(unique.values())


def _assertion_document_parts(assertion: KBAssertionRecord) -> list[dict[str, Any]]:
    """Map an assertion to semantic document sections and source spans."""
    record = assertion.details.get("record", {})
    anchor = record.get("source_anchor", {}) if isinstance(record, dict) else {}
    if not isinstance(anchor, dict):
        anchor = {}
    source_ids = list(dict.fromkeys([*assertion.source_ids, str(anchor.get("source_id", ""))]))
    source_ids = [item for item in source_ids if item]
    span_ids = list(dict.fromkeys([*assertion.span_ids, str(anchor.get("span", ""))]))
    span_ids = [item for item in span_ids if item]
    if not source_ids and not span_ids and not anchor.get("section"):
        return []
    return [
        {
            "assertion_ids": [assertion.assertion_id],
            "source_ids": source_ids,
            "span_ids": span_ids,
            "provider": assertion.provider,
            "document_id": str(anchor.get("source_id", ""))
            or (source_ids[0] if source_ids else ""),
            "edition": str(record.get("edition", "unknown")),
            "section": str(anchor.get("section", "")),
            "source_language": assertion.source_language,
            "review_state": assertion.review_state,
            "source_excerpt": assertion.source_gloss,
            "controlled_english": assertion.controlled_english,
        }
    ]


def _assertion_lookup(
    assertions: list[KBAssertionRecord],
) -> dict[str, list[KBAssertionRecord]]:
    """Index assertions by every stable semantic source identity they carry."""
    result: dict[str, list[KBAssertionRecord]] = defaultdict(list)
    for assertion in assertions:
        record = assertion.details.get("record", {})
        anchor = record.get("source_anchor", {}) if isinstance(record, dict) else {}
        keys = {
            assertion.assertion_id,
            *assertion.source_ids,
            *assertion.span_ids,
            str(record.get("clause_id", "")),
            str(record.get("rule_id", "")),
        }
        if isinstance(anchor, dict):
            keys.update({str(anchor.get("source_id", "")), str(anchor.get("span", ""))})
        for key in keys - {""}:
            result[key].append(assertion)
    return result


def _matching_assertions(
    clause_ids: list[str], lookup: dict[str, list[KBAssertionRecord]]
) -> list[KBAssertionRecord]:
    matched = {
        assertion.assertion_id: assertion
        for clause_id in clause_ids
        for assertion in lookup.get(clause_id, [])
    }
    return list(matched.values())


def _statement_kind(statement: str) -> str:
    stripped = statement.lstrip()
    if stripped.startswith("#"):
        return "directive"
    if stripped.startswith(":-"):
        return "constraint"
    return "rule" if ":-" in statement else "fact"


def _statement_modality(statement: str, kind: str) -> str:
    predicate = _statement_predicate(statement)
    if kind == "constraint":
        return "constraint"
    if "excluded" in predicate or predicate.startswith("excludes"):
        return "exclusion"
    if "exception" in predicate:
        return "exception"
    if "limit" in predicate or "duration" in predicate:
        return "limit"
    if kind == "directive":
        return "solver_directive"
    return "implication" if kind == "rule" else "fact"


def _statement_dependencies(statement: str, head_predicate: str) -> list[str]:
    if ":-" not in statement:
        return []
    body = statement.split(":-", 1)[1]
    predicates = set(re.findall(r"\b([a-z][A-Za-z0-9_]*)\s*\(", body))
    return sorted(predicates - {"not", head_predicate})


def _statement_subject(statement: str) -> str:
    match = re.match(r"\s*[a-z][A-Za-z0-9_]*\s*\(\s*([^,\s)]+)", statement)
    return match.group(1).strip('"') if match else ""


def _program_entity_comments(
    statements: list[tuple[str, list[str]]],
) -> dict[str, list[str]]:
    """Carry source comments to compiled facts sharing the same subject term."""
    return {
        subject: comments
        for statement, comments in statements
        if comments and (subject := _statement_subject(statement))
    }


def _comment_provider(comments: list[str]) -> str:
    for comment in comments:
        match = re.search(r"\(([A-Z][A-Za-z -]+)\)\.?$", comment)
        if match:
            return match.group(1).strip()
        match = re.match(r"(?:Controlled EN: )?([A-Z][A-Za-z]+)\s", comment)
        if match and match.group(1) not in {"Annotation", "Source", "The", "Under"}:
            return match.group(1)
    return "unknown"


def _source_provider(clause_ids: list[str], comments: list[str], program_label: str) -> str:
    provider = _comment_provider(comments)
    if provider != "unknown":
        return provider
    return "unmapped"


def _statement_product_families(statement: str, program_label: str) -> list[str]:
    if _statement_predicate(statement) == "feature_record":
        match = re.match(r"feature_record\(\s*[^,]+,\s*[^,]+,\s*([^,\s)]+)", statement)
        if match:
            return [match.group(1)]
    match = re.search(r"product_family\([^,]+,\s*([^,\s)]+)", statement)
    if match:
        return [match.group(1)]
    label = program_label.lower()
    if "vehicle" in label or "motor" in label or "negligence" in label:
        return ["motor_vehicle"]
    return ["unmapped"]


def _empty_document_part(clause_id: str) -> dict[str, Any]:
    return {
        "assertion_ids": [],
        "source_ids": [clause_id],
        "span_ids": [],
        "provider": "unknown",
        "document_id": clause_id,
        "edition": "unknown",
        "section": "",
        "source_language": "unknown",
        "review_state": "unmapped",
        "source_excerpt": "",
        "controlled_english": "",
    }


def _evidence_record(part: dict[str, Any]) -> dict[str, Any]:
    identity = {
        "document_id": part.get("document_id", ""),
        "section": part.get("section", ""),
        "span_ids": part.get("span_ids", []),
    }
    return {
        "evidence_id": "evidence:" + stable_hash(identity).removeprefix("sha256:")[:24],
        **part,
        "logical_clause_ids": [],
        "assertion_ids": list(part.get("assertion_ids", [])),
    }


def _assertion_formalization_state(assertion: KBAssertionRecord, compiled: bool) -> str:
    """Classify logic state without equating record approval with formalization."""
    if compiled:
        return "validated" if assertion.review_state == "validated" else "compiled"
    record = assertion.details.get("record", {})
    status = str(record.get("formalization_status", "")) if isinstance(record, dict) else ""
    normalized = status.lower().replace("-", "_")
    if normalized in {"rejected", "non_formalizable"}:
        return normalized
    if any(token in normalized for token in ("hold", "block", "review", "candidate", "draft")):
        return "review_required"
    return "normalized"


def _coverage_gap(assertion: KBAssertionRecord) -> dict[str, Any]:
    record = assertion.details.get("record", {})
    anchor = record.get("source_anchor", {}) if isinstance(record, dict) else {}
    document_id = str(anchor.get("source_id", "")) if isinstance(anchor, dict) else ""
    modality = (
        str(record.get("modality", assertion.kind)) if isinstance(record, dict) else assertion.kind
    )
    state = _assertion_formalization_state(assertion, False)
    return {
        "assertion_id": assertion.assertion_id,
        "label": assertion.label,
        "kind": assertion.kind,
        "provider": assertion.provider,
        "product_family": assertion.product_family,
        "modality": modality,
        "formalization_state": state,
        "source_document": document_id
        or (assertion.source_ids[0] if assertion.source_ids else "unknown"),
        "span_ids": assertion.span_ids,
        "review_status": assertion.review_state,
        "reason": (
            "Awaiting formalization review"
            if state == "review_required"
            else "No compiled logical clause is linked to this published assertion"
        ),
    }


def _read_json_internal(location: str, root: Path = REPO_ROOT) -> dict[str, Any]:
    return json.loads((root / location).read_text(encoding="utf-8"))


def _display_label(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[_-]+", value) if part)


def _domain_label(entry: dict[str, Any]) -> str:
    """Return a useful semantic title without exposing an internal filename."""
    artifact_type = str(entry.get("artifact_type", "knowledge_artifact"))
    role = str(entry.get("role", "")).strip().removesuffix(".")
    if artifact_type in {"asp_program", "prolog_program", "product_feature_prolog_facts"} and role:
        role = re.sub(
            r"^(?:Executable clingo policy program for|Prolog-style mirror for)\s+", "", role
        )
        return (
            f"{role[0].upper() + role[1:]} ({_display_label(str(entry.get('language', 'logic')))})"
        )
    return _display_label(artifact_type)


def _sanitize_formal_source(text: str) -> str:
    """Retain complete logic source while dropping repository-location metadata."""
    safe_lines = []
    for line in text.splitlines():
        normalized = line.replace("\\", "/")
        if any(
            fragment.replace("\\", "/") in normalized for fragment in _forbidden_path_fragments()
        ):
            continue
        safe_lines.append(line)
    return "\n".join(safe_lines).strip()


def _json_script_payload(payload: dict[str, Any]) -> str:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
