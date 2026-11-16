# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the consolidated, path-free logical KB visualizer."""

from __future__ import annotations

import json
import re
from typing import Any

from ruler.interfaces.kb_visualizer import (
    build_kb_visualization,
    validate_kb_visualizer,
    write_kb_visualizer_artifact,
)


def test_kb_visualizer_unifies_published_kb_surfaces() -> None:
    """All active releases, assertion kinds, sources, and relations should be joined."""
    visualizer = build_kb_visualization()

    assert {"legal", "regulatory", "technical_support"} <= {
        item.branch for item in visualizer.domains
    }
    assert visualizer.summary.assertions == len(visualizer.assertions)
    assert visualizer.summary.published_releases == len(visualizer.releases)
    formal_programs = [item for item in visualizer.domains if item.language in {"asp", "prolog"}]
    assert len(formal_programs) >= 1
    assert all(
        isinstance(item.content, str) and len(item.content.splitlines()) > 10
        for item in formal_programs
    )
    assert len({item.label for item in formal_programs}) == len(formal_programs)
    asp_programs = [item for item in formal_programs if item.language == "asp"]
    assert all("#show" in item.content for item in asp_programs)


def test_kb_visualizer_payload_contains_no_file_locations() -> None:
    """The browser contract must not carry local or repository location metadata."""
    payload = build_kb_visualization().model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "/Users/" not in serialized
    assert "kb/formalized/" not in serialized
    assert "data/operations/" not in serialized
    assert "build/ruler/" not in serialized
    assert not _keys_matching(payload, re.compile(r"path|file", re.IGNORECASE))


def test_kb_visualizer_writes_one_self_contained_html_artifact(tmp_path) -> None:
    """The artifact separates compiled logic, evidence mappings, and gaps."""
    artifacts = write_kb_visualizer_artifact(tmp_path)

    assert set(artifacts) == {"html"}
    assert [item.name for item in tmp_path.iterdir()] == ["index.html"]
    report = artifacts["html"].read_text(encoding="utf-8")
    assert "Logic explorer" in report
    assert "Source evidence" in report
    assert "Coverage gaps" in report
    assert "programFilter" in report
    assert "providerFilter" in report
    assert "productFamilyFilter" in report
    assert "formalismFilter" not in report
    assert "programList" not in report
    assert "predicateFilter" not in report
    assert "modalityFilter" not in report
    assert "formalizationStateFilter" not in report
    assert "sourceDocumentFilter" not in report
    assert "reviewStatusFilter" not in report
    assert "Compiled clauses" in report
    assert '<details class="filters">' in report
    assert "Technical dependencies" in report
    assert "coverage-section" in report
    assert "evidenceView" not in report
    assert "renderEvidence" not in report
    assert "view-button" not in report
    assert "showView" not in report
    assert '<details class="family" open>' not in report
    assert "family.assertions.some(item=>item.clause_id===state.selectedClause)" in report
    assert "else renderClauseDetail(clauseById.get(state.selectedClause))" in report
    assert "dependency_edges" in report
    assert "JSON.stringify" not in report
    assert "Published releases" not in report
    assert "Evidence relationships" not in report
    assert "<script src=" not in report
    assert "<link rel=" not in report
    assert "/Users/" not in report
    assert "kb/formalized/" not in report

    match = re.search(
        r'<script id="logic-visualizer-data" type="application/json">(.*?)</script>',
        report,
        re.DOTALL,
    )
    assert match is not None
    embedded = json.loads(match.group(1))
    assert embedded["summary"]["programs"] >= 1
    assert embedded["summary"]["logical_clauses"] > 0
    assert embedded["summary"]["coverage_gaps"] == len(build_kb_visualization().assertions)
    assert embedded["summary"]["inventory_assertions"] == len(build_kb_visualization().assertions)
    assert (
        embedded["summary"]["compiled_assertions"] + embedded["summary"]["coverage_gaps"]
        == embedded["summary"]["inventory_assertions"]
    )
    assert {item["formalism"] for item in embedded["representations"]} == {
        item.language
        for item in build_kb_visualization().domains
        if item.language in {"asp", "prolog"}
    }
    assert not ({"assertions", "releases", "sources", "relationships", "domains"} & embedded.keys())
    clauses = [
        clause
        for module in embedded["representations"]
        for family in module["family_nodes"]
        for clause in family["assertions"]
    ]
    clause_ids = {item["clause_id"] for item in clauses}
    evidence_ids = {item["evidence_id"] for item in embedded["evidence"]}
    assert len(clauses) == embedded["summary"]["logical_clauses"]
    assert {item["kind"] for item in clauses} <= {"fact", "rule", "constraint", "directive"}
    assert all(item["logic"].strip() for item in clauses)
    canonical_programs = {
        item.domain_id: str(item.content)
        for item in build_kb_visualization().domains
        if item.language in {"asp", "prolog"}
    }
    assert all(
        clause["logic"] in canonical_programs[module["program_id"]]
        for module in embedded["representations"]
        for family in module["family_nodes"]
        for clause in family["assertions"]
    )
    assert all(set(item["evidence_ids"]) <= evidence_ids for item in clauses)
    assert all(set(item["logical_clause_ids"]) <= clause_ids for item in embedded["evidence"])
    assert all("content" not in module for module in embedded["representations"])
    logical_source = "\n".join(item["logic"] for item in clauses)
    assert "attribute(" not in logical_source
    assert "assertion_kind(" not in logical_source
    assert "source_clause(" not in logical_source
    assert "operational_predicate_source(" not in logical_source
    assert all(item["formalization_state"] != "validated" for item in embedded["coverage_gaps"])
    assert not _keys_matching(embedded, re.compile(r"path|file", re.IGNORECASE))
    assert validate_kb_visualizer()[-1] == "artifact=self_contained_html"


def _keys_matching(value: Any, pattern: re.Pattern[str]) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if pattern.search(str(key)):
                matches.append(str(key))
            matches.extend(_keys_matching(child, pattern))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_keys_matching(child, pattern))
    return matches
