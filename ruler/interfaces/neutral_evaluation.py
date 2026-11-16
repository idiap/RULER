# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-neutral document-to-evidence snapshot and dependency-free HTML renderer."""

from __future__ import annotations

import html
import json

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256
from pydantic import field_validator


class EvidenceNode(StrictContract):
    evidence_id: str
    source_id: str
    source_version: str
    section: str
    span_sha256: str
    locator: str

    _hash_is_canonical = field_validator("span_sha256")(validate_sha256)


class ConsequenceNode(StrictContract):
    consequence_id: str
    status: str
    effect: str
    evidence: tuple[EvidenceNode, ...] = Field(min_length=1)


class RuleNode(StrictContract):
    rule_id: str
    modality: str
    consequence: str
    outcomes: tuple[ConsequenceNode, ...] = ()


class NormativeUnitNode(StrictContract):
    unit_id: str
    title: str
    modality: str
    rules: tuple[RuleNode, ...] = Field(min_length=1)


class DocumentNode(StrictContract):
    document_id: str
    title: str
    document_kind: str
    issuing_authority: str | None = None
    units: tuple[NormativeUnitNode, ...] = Field(min_length=1)


class NeutralEvaluationSnapshot(StrictContract):
    """Nested projection: document → unit → rule → consequence → exact evidence."""

    snapshot_id: str
    domain_id: str
    corpus_id: str
    release_id: str
    documents: tuple[DocumentNode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> "NeutralEvaluationSnapshot":
        collections = {
            "document": [item.document_id for item in self.documents],
            "unit": [unit.unit_id for document in self.documents for unit in document.units],
            "rule": [
                rule.rule_id
                for document in self.documents
                for unit in document.units
                for rule in unit.rules
            ],
            "consequence": [
                outcome.consequence_id
                for document in self.documents
                for unit in document.units
                for rule in unit.rules
                for outcome in rule.outcomes
            ],
        }
        for label, identifiers in collections.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {label} identifiers in neutral snapshot")
        for document in self.documents:
            for unit in document.units:
                for rule in unit.rules:
                    for outcome in rule.outcomes:
                        wrong_sources = sorted(
                            {
                                item.source_id
                                for item in outcome.evidence
                                if item.source_id != document.document_id
                            }
                        )
                        if wrong_sources:
                            raise ValueError(
                                f"evidence for {outcome.consequence_id} is outside document "
                                f"{document.document_id}: {', '.join(wrong_sources)}"
                            )
        return self


def render_neutral_evaluation(snapshot: NeutralEvaluationSnapshot) -> str:
    """Render a standalone escaped view with inert, safely embedded snapshot JSON."""
    documents = "".join(_render_document(item) for item in snapshot.documents)
    data = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    safe_data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Rule evaluation · {html.escape(snapshot.domain_id)}</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:auto;padding:2rem;color:#18202a}}
article,section{{border:1px solid #d6dce3;border-radius:8px;padding:1rem;margin:1rem 0}}
.meta{{color:#53606e}} code{{overflow-wrap:anywhere}} .status{{font-weight:700}}
</style></head><body>
<header><h1>Rule evaluation</h1><p class="meta">Domain {html.escape(snapshot.domain_id)} ·
corpus {html.escape(snapshot.corpus_id)} · release <code>{html.escape(snapshot.release_id)}</code></p></header>
{documents}
<script id="evaluation-snapshot" type="application/json">{safe_data}</script>
</body></html>"""


def _render_document(document: DocumentNode) -> str:
    units = "".join(_render_unit(item) for item in document.units)
    authority = (
        f" · {html.escape(document.issuing_authority)}" if document.issuing_authority else ""
    )
    return f"""<article class="document"><h2>{html.escape(document.title)}</h2>
<p class="meta">{html.escape(document.document_kind)}{authority} ·
<code>{html.escape(document.document_id)}</code></p>{units}</article>"""


def _render_unit(unit: NormativeUnitNode) -> str:
    rules = "".join(_render_rule(item) for item in unit.rules)
    return f"""<section class="unit"><h3>{html.escape(unit.title)}</h3>
<p class="meta">Unit <code>{html.escape(unit.unit_id)}</code> · {html.escape(unit.modality)}</p>
{rules}</section>"""


def _render_rule(rule: RuleNode) -> str:
    outcomes = "".join(_render_outcome(item) for item in rule.outcomes)
    empty = '<p class="meta">No consequence emitted (open-world unknown).</p>'
    return f"""<section class="rule"><h4>Rule <code>{html.escape(rule.rule_id)}</code></h4>
<p><strong>{html.escape(rule.modality)}</strong> · {html.escape(rule.consequence)}</p>
{outcomes or empty}</section>"""


def _render_outcome(outcome: ConsequenceNode) -> str:
    evidence = "".join(
        f"<li><code>{html.escape(item.evidence_id)}</code> · {html.escape(item.section)} · "
        f"{html.escape(item.locator)} · <code>{html.escape(item.span_sha256)}</code></li>"
        for item in outcome.evidence
    )
    return f"""<section class="consequence"><p><span class="status">{html.escape(outcome.status)}</span>
· {html.escape(outcome.effect)}</p><p class="meta"><code>{html.escape(outcome.consequence_id)}</code></p>
<details><summary>Exact evidence</summary><ul>{evidence}</ul></details></section>"""
