# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Inspectable, source-grounded visualizer for uncommitted formalization candidates.

This is the candidate counterpart of :mod:`ruler.interfaces.kb_visualizer`.  It
uses the same path-free, self-contained artifact pattern, but deliberately does
not present generated rules as published knowledge.  The adapter verifies the
source spans and compiles every displayed rule through RULER's ASP compiler.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from ruler.contracts.common import StrictContract
from ruler.io import stable_hash, write_text
from ruler.kb.asp_compiler import compile_asp
from ruler.kb.generative_autoformalization import (
    AutoformalizationCandidate,
    AutoformalizationRequest,
    _formalization_unit_manifest,
    _generation_schema,
)


class CandidateSpanView(StrictContract):
    span_id: str
    exact_text: str
    start_char: int
    end_char: int
    artifact_sha256: str
    verification: Literal["exact_source_match"] = "exact_source_match"


class CandidateElementView(StrictContract):
    element_id: str
    kind: str
    predicate: str
    modality: str
    polarity: str
    connective: str
    source_span_ids: tuple[str, ...]
    formalization_unit_ids: tuple[str, ...]
    value: str | int | float | None = None
    unit: str | None = None


class CandidateRuleView(StrictContract):
    statement_id: str
    modality: str
    deontic_operator: str | None = None
    compiled_asp: str
    head_predicate: str | None = None
    body_predicates: tuple[str, ...]
    source_element_ids: tuple[str, ...]
    source_span_ids: tuple[str, ...]


class CandidateGraphEdge(StrictContract):
    source_id: str
    target_id: str
    relation: Literal["grounds", "supports", "requires", "concludes", "projects_to"]


class CandidateKBVisualization(StrictContract):
    """Path-free browser contract for one generated candidate."""

    visualizer_id: str
    title: str
    lifecycle: Literal["candidate_uncommitted"] = "candidate_uncommitted"
    publication_status: Literal["not_published"] = "not_published"
    solver_authority: Literal["blocked"] = "blocked"
    boundary_notice: str
    request_id: str
    artifact_id: str
    source_version: str
    source_text: str
    source_artifact_sha256: str
    target_formalism: str
    candidate_digest: str
    program_digest: str
    summary: dict[str, int]
    spans: tuple[CandidateSpanView, ...]
    elements: tuple[CandidateElementView, ...]
    rules: tuple[CandidateRuleView, ...]
    graph_edges: tuple[CandidateGraphEdge, ...]
    projection_dimensions: tuple[dict[str, object], ...]
    activation_blockers: tuple[dict[str, object], ...]
    uncertainties: tuple[str, ...]
    audit_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def build_autoformalization_visualization(
    request: AutoformalizationRequest,
    candidate: AutoformalizationCandidate,
    *,
    title: str = "Autoformalized rule candidate",
) -> CandidateKBVisualization:
    """Verify and adapt a generated candidate into an inspectable graph model."""

    if request.target_formalism != "asp":
        raise ValueError(
            "candidate visualizer currently requires target_formalism='asp' because "
            "every displayed rule is compiler-validated ASP"
        )
    if candidate.request_id != request.request_id:
        raise ValueError("candidate request_id does not match the source request")
    if candidate.receipt.source_artifact_sha256 != request.artifact_sha256:
        raise ValueError("candidate receipt is not bound to the source artifact")
    if candidate.receipt.request_sha256 != stable_hash(request.model_dump(mode="json")):
        raise ValueError("candidate receipt is not bound to the complete request")
    if candidate.receipt.schema_sha256 != stable_hash(_generation_schema(request)):
        raise ValueError("candidate receipt is not bound to the request output schema")
    if candidate.lifecycle != "candidate_uncommitted":
        raise ValueError("visualization accepts only uncommitted candidates")
    if candidate.semantic_basis.commitment_status != "candidate_uncommitted":
        raise ValueError("semantic basis crossed the candidate commitment boundary")
    if candidate.projection.activation_status != "blocked":
        raise ValueError("candidate projection is not activation-blocked")
    candidate.semantic_basis.verify_source_artifacts(
        {request.artifact_id: request.source_text.encode("utf-8")}
    )
    _verify_projection_and_provenance(request, candidate)
    # Compile the complete program as well as each rule shown below.  This preserves
    # whole-program compiler grounding even when a browser focuses on one statement.
    compile_asp(candidate.logical_program, request.predicate_registry)

    spans = tuple(
        CandidateSpanView(
            span_id=span.span_id,
            exact_text=span.exact_text,
            start_char=span.start_char,
            end_char=span.end_char,
            artifact_sha256=span.artifact_sha256,
        )
        for span in candidate.semantic_basis.spans
    )
    elements = tuple(
        CandidateElementView(
            element_id=element.element_id,
            kind=element.kind.value,
            predicate=element.predicate,
            modality=element.modality.value,
            polarity=element.polarity,
            connective=element.connective,
            source_span_ids=element.source_span_ids,
            formalization_unit_ids=element.formalization_unit_ids,
            value=element.value,
            unit=element.unit,
        )
        for element in candidate.semantic_basis.elements
    )
    rules = tuple(
        CandidateRuleView(
            statement_id=statement.statement_id,
            modality=statement.modality.value,
            deontic_operator=(
                statement.deontic_operator.value if statement.deontic_operator else None
            ),
            compiled_asp=_compiled_statement(request, candidate, statement.statement_id),
            head_predicate=statement.head.predicate if statement.head else None,
            body_predicates=tuple(sorted(_expression_predicates(statement.body))),
            source_element_ids=statement.source_assertion_ids,
            source_span_ids=tuple(item.span_id for item in statement.provenance),
        )
        for statement in candidate.logical_program.statements
    )
    edges = _candidate_edges(elements, rules)
    raw: dict[str, object] = {
        "visualizer_id": f"candidate-kb:{candidate.logical_program.program_id}",
        "title": title,
        "lifecycle": "candidate_uncommitted",
        "publication_status": "not_published",
        "solver_authority": "blocked",
        "boundary_notice": (
            "Generated rules are review-only candidates. They are not published KB truth "
            "and cannot authorize solver constraints until separately reviewed and promoted."
        ),
        "request_id": request.request_id,
        "artifact_id": request.artifact_id,
        "source_version": request.source_version,
        "source_text": request.source_text,
        "source_artifact_sha256": request.artifact_sha256,
        "target_formalism": request.target_formalism,
        "candidate_digest": stable_hash(candidate.model_dump(mode="json")),
        "program_digest": candidate.logical_program.sha256(),
        "summary": {
            "source_characters": len(request.source_text),
            "exact_spans": len(spans),
            "semantic_elements": len(elements),
            "rules": len(rules),
            "facts": sum(item.modality == "fact" for item in rules),
            "dependencies": sum(item.relation == "requires" for item in edges),
            "activation_blockers": len(candidate.projection.activation_blockers),
        },
        "spans": spans,
        "elements": elements,
        "rules": rules,
        "graph_edges": edges,
        "projection_dimensions": tuple(
            item.model_dump(mode="json") for item in candidate.projection.dimensions
        ),
        "activation_blockers": tuple(
            item.model_dump(mode="json") for item in candidate.projection.activation_blockers
        ),
        "uncertainties": candidate.uncertainties,
    }
    return CandidateKBVisualization.model_validate({**raw, "audit_hash": stable_hash(raw)})


def _verify_projection_and_provenance(
    request: AutoformalizationRequest,
    candidate: AutoformalizationCandidate,
) -> None:
    basis = candidate.semantic_basis
    program = candidate.logical_program
    projection = candidate.projection
    basis_digest = stable_hash(basis.model_dump(mode="json"))
    units = _formalization_unit_manifest(basis, program)
    units_digest = stable_hash({"semantic_basis_digest": basis_digest, "units": units})
    expected = {
        "source_artifact_digests": (request.artifact_sha256,),
        "semantic_basis_digest": basis_digest,
        "formalization_units_digest": units_digest,
        "program_digest": program.sha256(),
        "target_formalism": request.target_formalism,
    }
    for field, value in expected.items():
        if getattr(projection, field) != value:
            raise ValueError(f"candidate projection has stale or foreign {field}")

    spans = {item.span_id: item for item in basis.spans}
    elements = {item.element_id: item for item in basis.elements}
    represented = set(projection.represented_element_ids)
    for statement in program.statements:
        element_ids = set(statement.source_assertion_ids)
        if unknown := element_ids - represented:
            raise ValueError(
                f"{statement.statement_id}: logical rule cites unrepresented elements "
                f"{sorted(unknown)}"
            )
        expected_spans = {
            span_id
            for element_id in element_ids
            for span_id in elements[element_id].source_span_ids
        }
        provenance = {item.span_id: item for item in statement.provenance}
        if set(provenance) != expected_spans:
            raise ValueError(f"{statement.statement_id}: logical provenance is not exact")
        for span_id, item in provenance.items():
            span = spans[span_id]
            if (
                item.document_id != request.artifact_id
                or item.source_version != request.source_version
                or item.span_sha256
                != "sha256:" + hashlib.sha256(span.exact_text.encode("utf-8")).hexdigest()
            ):
                raise ValueError(
                    f"{statement.statement_id}: logical provenance is stale or foreign"
                )


def render_autoformalization_visualizer_html(
    model: CandidateKBVisualization, *, accepted: bool = False
) -> str:
    """Render a self-contained lineage or accepted-KB explorer offline."""

    payload = _json_script_payload(model.model_dump(mode="json"))
    rendered = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html_text(model.title)} · RULER</title>
  <style>
    :root {{ --bg:#071018; --panel:#0d1b27; --line:#294052; --text:#eaf3f7; --muted:#97acb9; --cyan:#63d5e3; --green:#70d7aa; --amber:#fac86c; --red:#fb7185; --violet:#b9a4ff; }}
    * {{ box-sizing:border-box }} body {{ margin:0; color:var(--text); background:radial-gradient(circle at 10% 0,rgba(99,213,227,.12),transparent 34%),var(--bg); font:14px/1.5 Inter,ui-sans-serif,system-ui,sans-serif }}
    header {{ padding:22px 26px; border-bottom:1px solid var(--line); background:#08131ddd }} h1,h2,h3,p {{ margin-top:0 }} h1 {{ margin-bottom:5px }}
    .eyebrow {{ color:var(--cyan); font-size:11px; font-weight:800; letter-spacing:.13em; text-transform:uppercase }} .boundary {{ margin-top:14px; padding:12px 14px; border:1px solid var(--red); border-radius:9px; background:#351421; color:#ffd9df; font-weight:700 }}
    main {{ max-width:1440px; margin:auto; padding:20px 24px 44px }} .metrics {{ display:grid; grid-template-columns:repeat(6,minmax(105px,1fr)); gap:9px; margin-bottom:14px }} .metric,.panel {{ border:1px solid var(--line); border-radius:10px; background:linear-gradient(150deg,#102331,#0a1721) }} .metric {{ padding:12px }} .metric strong {{ display:block; font-size:24px }} .metric span,.muted {{ color:var(--muted) }} .metric span {{ font-size:10px; text-transform:uppercase; letter-spacing:.08em }}
    .tabs {{ display:flex; flex-wrap:wrap; gap:7px; margin:14px 0 }} button {{ padding:9px 12px; color:var(--muted); border:1px solid var(--line); border-radius:8px; background:#0a1721; cursor:pointer }} button.active {{ color:var(--text); border-color:var(--cyan) }} .view {{ display:none }} .view.active {{ display:block }}
    .two {{ display:grid; grid-template-columns:minmax(320px,.8fr) minmax(450px,1.2fr); gap:12px }} .panel {{ padding:15px; min-width:0 }} .list {{ display:grid; gap:8px; max-height:670px; overflow:auto }} .record {{ width:100%; text-align:left }} .record strong {{ display:block; color:var(--text) }} .record small {{ color:var(--muted) }} .record.active {{ background:#123043 }}
    .badge {{ display:inline-block; margin:0 5px 5px 0; padding:3px 7px; border:1px solid #397084; border-radius:99px; color:var(--cyan); font-size:10px; text-transform:uppercase }} .badge.blocked {{ color:var(--red); border-color:var(--red) }}
    pre,.source {{ padding:12px; overflow:auto; border:1px solid var(--line); border-radius:8px; background:#050d13; white-space:pre-wrap; word-break:break-word; font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace }} mark {{ color:#051014; background:var(--amber); border-radius:2px }}
    svg {{ width:100%; min-width:850px; height:620px }} .graph-wrap {{ overflow:auto }} .edge {{ stroke:#456275; stroke-width:1.3 }} .node rect {{ fill:#10283a; stroke:#52778e; rx:8 }} .node text {{ fill:var(--text); font-size:10px }} .node.span rect {{ stroke:var(--amber) }} .node.element rect {{ stroke:var(--green) }} .node.rule rect {{ stroke:var(--violet) }} .node.predicate rect {{ stroke:var(--cyan) }}
    table {{ width:100%; border-collapse:collapse }} th,td {{ padding:9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top }} th {{ color:var(--muted); font-size:10px; text-transform:uppercase }}
    @media(max-width:900px) {{ .metrics {{ grid-template-columns:repeat(3,1fr) }} .two {{ grid-template-columns:1fr }} main,header {{ padding:16px }} }}
  </style>
</head>
<body>
  <header><div class="eyebrow">RULER / Candidate knowledge explorer</div><h1>{_html_text(model.title)}</h1><p class="muted">Exact source spans → semantic elements → typed logical rules → predicate dependencies</p><div class="boundary">CANDIDATE · UNCOMMITTED · SOLVER AUTHORITY BLOCKED — {_html_text(model.boundary_notice)}</div></header>
  <main>
    <div id="metrics" class="metrics"></div>
    <div class="tabs"><button class="active" data-view="graph">Grounding graph</button><button data-view="rules">Rules &amp; evidence</button><button data-view="source">Source spans</button><button data-view="projection">Projection review</button></div>
    <section id="graph" class="view active"><article class="panel graph-wrap"><h2>Autoformalized rule graph</h2><p class="muted">Amber: source spans · green: semantic elements · violet: candidate rules · cyan: predicates</p><svg id="graphSvg" viewBox="0 0 1100 620" role="img" aria-label="Candidate rule grounding graph"></svg></article></section>
    <section id="rules" class="view"><div class="two"><article class="panel"><h2>Candidate rules</h2><div id="ruleList" class="list"></div></article><article id="ruleDetail" class="panel"></article></div></section>
    <section id="source" class="view"><div class="two"><article class="panel"><h2>Natural-language dossier</h2><div id="sourceText" class="source"></div></article><article class="panel"><h2>Authenticated spans</h2><div id="spanList" class="list"></div></article></div></section>
    <section id="projection" class="view"><div class="two"><article class="panel"><h2>Semantic dimensions</h2><div id="dimensions"></div></article><article class="panel"><h2>Activation boundary</h2><div id="blockers"></div><h3>Uncertainties</h3><div id="uncertainties"></div></article></div></section>
  </main>
  <script id="candidate-kb-data" type="application/json">{payload}</script>
  <script>
    const data=JSON.parse(document.getElementById('candidate-kb-data').textContent); let selected=data.rules[0]?.statement_id;
    const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
    const title=v=>String(v??'').replaceAll('_',' ').replace(/\\b\\w/g,c=>c.toUpperCase()); const badge=(v,c='')=>`<span class="badge ${{c}}">${{esc(title(v))}}</span>`;
    document.getElementById('metrics').innerHTML=Object.entries(data.summary).map(([k,v])=>`<div class="metric"><strong>${{v}}</strong><span>${{esc(title(k))}}</span></div>`).join('');
    document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===b.dataset.view));}});
    function renderRules(){{const list=document.getElementById('ruleList');list.innerHTML=data.rules.map(r=>`<button class="record ${{r.statement_id===selected?'active':''}}" data-id="${{esc(r.statement_id)}}"><strong>${{esc(r.statement_id)}}</strong><small>${{esc(title(r.modality))}} · ${{esc(r.head_predicate||'constraint')}}</small></button>`).join('');list.querySelectorAll('button').forEach(b=>b.onclick=()=>{{selected=b.dataset.id;renderRules();}});const r=data.rules.find(x=>x.statement_id===selected);const d=document.getElementById('ruleDetail');if(!r){{d.innerHTML='<p>No candidate rules.</p>';return}}const spans=r.source_span_ids.map(id=>data.spans.find(s=>s.span_id===id)).filter(Boolean);d.innerHTML=`${{badge('candidate','blocked')}}${{badge(r.modality)}}${{r.deontic_operator?badge(r.deontic_operator):''}}<h2>${{esc(r.statement_id)}}</h2><h3>Compiler-validated ASP</h3><pre>${{esc(r.compiled_asp)}}</pre><h3>Exact source evidence</h3>${{spans.map(s=>`<div class="source"><strong>${{esc(s.span_id)}}</strong> [${{s.start_char}}, ${{s.end_char}})<br>${{esc(s.exact_text)}}</div>`).join('')}}<h3>Semantic support</h3><p>${{r.source_element_ids.map(x=>badge(x)).join('')}}</p>`;}}
    function highlightedSource(){{let out='',cursor=0;[...data.spans].sort((a,b)=>a.start_char-b.start_char).forEach(s=>{{if(s.start_char<cursor)return;out+=esc(data.source_text.slice(cursor,s.start_char));out+=`<mark title="${{esc(s.span_id)}}">${{esc(data.source_text.slice(s.start_char,s.end_char))}}</mark>`;cursor=s.end_char;}});return out+esc(data.source_text.slice(cursor));}}
    document.getElementById('sourceText').innerHTML=highlightedSource();document.getElementById('spanList').innerHTML=data.spans.map(s=>`<div class="source"><strong>${{esc(s.span_id)}}</strong> ${{badge(s.verification)}}<br><span class="muted">characters ${{s.start_char}}–${{s.end_char}}</span><br>${{esc(s.exact_text)}}</div>`).join('');
    document.getElementById('dimensions').innerHTML=`<table><thead><tr><th>Dimension</th><th>Disposition</th><th>Query affecting</th><th>Explanation</th></tr></thead><tbody>${{data.projection_dimensions.map(x=>`<tr><td>${{esc(title(x.dimension))}}</td><td>${{badge(x.disposition)}}</td><td>${{x.query_affecting?'yes':'no'}}</td><td>${{esc(x.explanation)}}</td></tr>`).join('')}}</tbody></table>`;
    document.getElementById('blockers').innerHTML=data.activation_blockers.length?data.activation_blockers.map(x=>`<div class="source">${{badge(x.category,'blocked')}}<strong>${{esc(x.dimension)}}</strong><br>${{esc(x.explanation)}}</div>`).join(''):'<div class="boundary">Activation remains blocked because lifecycle is candidate_uncommitted, even when no semantic-loss blocker is present.</div>';document.getElementById('uncertainties').innerHTML=data.uncertainties.length?`<ul>${{data.uncertainties.map(x=>`<li>${{esc(x)}}</li>`).join('')}}</ul>`:'<p class="muted">No generator-reported uncertainties.</p>';
    function renderGraph(){{const nodes=[];data.spans.forEach((x,i)=>nodes.push({{id:x.span_id,type:'span',label:x.span_id,x:105,y:50+i*52}}));data.elements.forEach((x,i)=>nodes.push({{id:x.element_id,type:'element',label:x.predicate,x:375,y:40+i*46}}));data.rules.forEach((x,i)=>nodes.push({{id:x.statement_id,type:'rule',label:x.statement_id,x:685,y:70+i*70}}));const ps=[...new Set([...data.elements.map(e=>e.predicate),...data.rules.flatMap(r=>[r.head_predicate,...r.body_predicates])].filter(Boolean))];ps.forEach((x,i)=>nodes.push({{id:'predicate:'+x,type:'predicate',label:x,x:965,y:70+i*60}}));const by=new Map(nodes.map(n=>[n.id,n]));const edges=data.graph_edges.filter(e=>by.has(e.source_id)&&by.has(e.target_id));const svg=document.getElementById('graphSvg');const height=Math.max(620,...nodes.map(n=>n.y+40));svg.setAttribute('viewBox',`0 0 1100 ${{height}}`);svg.style.height=height+'px';svg.innerHTML='<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#54768a"/></marker></defs>'+edges.map(e=>{{const a=by.get(e.source_id),b=by.get(e.target_id);return `<line class="edge" x1="${{a.x+90}}" y1="${{a.y}}" x2="${{b.x-90}}" y2="${{b.y}}" marker-end="url(#arrow)"><title>${{esc(e.relation)}}</title></line>`;}}).join('')+nodes.map(n=>`<g class="node ${{n.type}}"><rect x="${{n.x-90}}" y="${{n.y-17}}" width="180" height="34"></rect><text x="${{n.x}}" y="${{n.y+4}}" text-anchor="middle">${{esc(n.label.length>25?n.label.slice(0,23)+'…':n.label)}}</text><title>${{esc(n.id)}}</title></g>`).join('');}}
    renderRules();renderGraph();
  </script>
</body></html>"""
    if not accepted:
        return rendered
    replacements = {
        _html_text(model.boundary_notice): (
            "Every source-linked statement passed automatic acceptance; this active "
            "logical KB remains non-authoritative for portfolio optimization."
        ),
        "RULER / Candidate knowledge explorer": "RULER / Accepted knowledge explorer",
        "CANDIDATE · UNCOMMITTED · SOLVER AUTHORITY BLOCKED": (
            "ACCEPTED · ACTIVE · LOGICAL-RUNTIME AUTHORITY"
        ),
        "violet: candidate rules": "violet: accepted rules",
        'aria-label="Candidate rule grounding graph"': (
            'aria-label="Accepted rule grounding graph"'
        ),
        "<h2>Candidate rules</h2>": "<h2>Accepted rules</h2>",
        "No candidate rules.": "No accepted rules.",
        "badge('candidate','blocked')": "badge('accepted')",
        (
            "Activation remains blocked because lifecycle is candidate_uncommitted, "
            "even when no semantic-loss blocker is present."
        ): (
            "The immutable generation lineage remained blocked until every automatic "
            "acceptance gate passed; the released logical KB is active."
        ),
    }
    for old, new in replacements.items():
        rendered = rendered.replace(old, new)
    return rendered


def write_autoformalization_visualizer_artifact(
    request: AutoformalizationRequest,
    candidate: AutoformalizationCandidate,
    output_path: Path,
    *,
    title: str = "Autoformalized rule candidate",
    accepted: bool = False,
) -> Path:
    """Write one self-contained lineage or accepted-KB visualization."""

    model = build_autoformalization_visualization(request, candidate, title=title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(
        output_path,
        render_autoformalization_visualizer_html(model, accepted=accepted),
    )
    return output_path


def _compiled_statement(request, candidate, statement_id: str) -> str:
    statement = next(
        item for item in candidate.logical_program.statements if item.statement_id == statement_id
    )
    single = candidate.logical_program.model_copy(
        update={"statements": (statement,), "show": (), "entrypoint_predicates": ()}
    )
    compiled = compile_asp(single, request.predicate_registry)
    return "\n".join(
        line for line in compiled.text.splitlines() if line and not line.startswith("%")
    )


def _expression_predicates(expression) -> set[str]:
    if expression is None:
        return set()
    values = {expression.atom.predicate} if expression.atom is not None else set()
    if expression.aggregation is not None:
        values.add(expression.aggregation.atom.predicate)
    if expression.exception_target is not None:
        values.add(expression.exception_target.predicate)
    for operand in expression.operands:
        values.update(_expression_predicates(operand))
    return values


def _candidate_edges(elements, rules) -> tuple[CandidateGraphEdge, ...]:
    edges: dict[str, CandidateGraphEdge] = {}
    for element in elements:
        for span_id in element.source_span_ids:
            edge = CandidateGraphEdge(
                source_id=span_id, target_id=element.element_id, relation="grounds"
            )
            edges[stable_hash(edge.model_dump(mode="json"))] = edge
    for rule in rules:
        for element_id in rule.source_element_ids:
            edge = CandidateGraphEdge(
                source_id=element_id, target_id=rule.statement_id, relation="supports"
            )
            edges[stable_hash(edge.model_dump(mode="json"))] = edge
        for predicate in rule.body_predicates:
            edge = CandidateGraphEdge(
                source_id=f"predicate:{predicate}",
                target_id=rule.statement_id,
                relation="requires",
            )
            edges[stable_hash(edge.model_dump(mode="json"))] = edge
        if rule.head_predicate:
            edge = CandidateGraphEdge(
                source_id=rule.statement_id,
                target_id=f"predicate:{rule.head_predicate}",
                relation="concludes",
            )
            edges[stable_hash(edge.model_dump(mode="json"))] = edge
    for element in elements:
        edge = CandidateGraphEdge(
            source_id=element.element_id,
            target_id=f"predicate:{element.predicate}",
            relation="projects_to",
        )
        edges[stable_hash(edge.model_dump(mode="json"))] = edge
    return tuple(sorted(edges.values(), key=lambda x: (x.source_id, x.target_id, x.relation)))


def _json_script_payload(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _html_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )
