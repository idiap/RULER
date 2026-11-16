# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic descriptive statistics for the KB and processed source corpus."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ruler.ingestion.contracts import canonical_sha256
from ruler.io import read_yaml, write_text, write_yaml
from ruler.paths import BUILD_DIR, DATA_DIR, KB_DIR, KB_FORMALIZED_REAL_DIR, REPO_ROOT

KB_STATISTICS_DIR = BUILD_DIR / "kb_statistics"
ONBOARDING_POINTER = KB_DIR / "releases" / "product_onboarding" / "active_batch_01.yaml"
ONBOARDING_POINTER_DIR = KB_DIR / "releases" / "product_onboarding" / "active_batches"


def _records(path: Path) -> list[dict[str, Any]]:
    """Return list-shaped YAML records while tolerating an absent optional artifact."""
    if not path.exists():
        return []
    payload = read_yaml(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return value
    return []


def _logic_statements(path: Path) -> tuple[str, ...]:
    """Parse complete Prolog/ASP statements after removing comments and directives."""
    if not path.exists():
        return ()
    statements: list[str] = []
    buffer: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("%", "#show", "#program")):
            continue
        buffer.append(line)
        if line.endswith("."):
            statements.append(" ".join(buffer))
            buffer = []
    return tuple(statements)


def _statistics_context(context: dict[str, Any]) -> tuple[Path, Path, Path, Path, Path]:
    root_value = context.get("repository_root")
    if root_value is None:
        return (
            REPO_ROOT,
            KB_FORMALIZED_REAL_DIR,
            DATA_DIR,
            ONBOARDING_POINTER,
            ONBOARDING_POINTER_DIR,
        )
    root = Path(root_value)
    release = root / "kb/releases/product_onboarding"
    return (
        root,
        root / "kb/formalized/real",
        root / "data",
        release / "active_batch_01.yaml",
        release / "active_batches",
    )


def _scan_state(paths: list[Path], accumulated: dict, prior: dict) -> dict:
    return {
        "paths": [str(path) for path in paths],
        "cursor": 0,
        "has_more": bool(paths),
        "accumulated": accumulated,
        "prior": prior,
    }


def _scan_advance(state: dict) -> dict:
    state["cursor"] += 1
    state["has_more"] = state["cursor"] < len(state["paths"])
    return state


def prepare_statistics_targets(context: dict[str, Any]) -> dict:
    """Load canonical records, then discover ordered targets and initialize locals."""
    root, formalized, data, pointer, pointer_dir = _statistics_context(context)
    clauses = _records(formalized / "policy" / "policy_clauses.yaml")
    policy_rules = _records(formalized / "policy" / "policy_rules.yaml")
    candidates = _records(data / "candidates" / "extraction_candidates.yaml")
    drafts = _records(data / "candidates" / "formalization_drafts.yaml")
    corpus_root = root / "kb/corpora"
    targets = sorted(corpus_root.rglob("*.pl")) + sorted(corpus_root.rglob("*.lp"))
    target_stats: list[dict[str, Any]] = []
    nl_fr = nl_en = 0
    canonical = {
        "policy_clauses": len(clauses),
        "policy_rules": len(policy_rules),
        "candidate_records": len(candidates),
        "formalization_drafts": len(drafts),
    }
    return _scan_state(
        targets,
        {
            "target_stats": target_stats,
            "target_stats_json": json.dumps(target_stats),
            "unique_facts": [],
            "unique_rules": [],
            "nl_fr": nl_fr,
            "nl_en": nl_en,
        },
        {
            "context": context,
            "canonical_json": json.dumps(canonical),
            "canonical_kb": {
                "policy_clauses": len(clauses),
                "policy_rules": len(policy_rules),
                "candidate_records": len(candidates),
                "formalization_drafts": len(drafts),
            },
        },
    )


def scan_statistics_target(state: dict) -> dict:
    """Process exactly one discovered target, preserving per-target and global sets."""
    root, *_ = _statistics_context(state["prior"]["context"])
    path = Path(state["paths"][state["cursor"]])
    a = state["accumulated"]
    target_stats = json.loads(a["target_stats_json"])
    a["target_stats"] = target_stats
    unique_facts, unique_rules = set(a["unique_facts"]), set(a["unique_rules"])
    nl_fr, nl_en = a["nl_fr"], a["nl_en"]
    statements = _logic_statements(path)
    facts = {item for item in statements if ":-" not in item}
    rules = {item for item in statements if ":-" in item}
    text = path.read_text(encoding="utf-8")
    fr = len(re.findall(r"(?m)^%\s*NL-FR:", text))
    en = len(re.findall(r"(?m)^%\s*NL-EN:", text))
    nl_fr += fr
    nl_en += en
    unique_facts.update(facts)
    unique_rules.update(rules)
    target_stats.append(
        {
            "path": path.relative_to(root).as_posix(),
            "facts": len(facts),
            "rules": len(rules),
            "nl_fr_comments": fr,
            "nl_en_comments": en,
        }
    )
    a["target_stats_json"] = json.dumps(target_stats)
    a.update(
        unique_facts=sorted(unique_facts),
        unique_rules=sorted(unique_rules),
        nl_fr=nl_fr,
        nl_en=nl_en,
    )
    return _scan_advance(state)


def prepare_statistics_documents(state: dict) -> dict:
    """Retain target locals and discover sorted extraction manifests."""
    root, _, data, _, _ = _statistics_context(state["prior"]["context"])
    prior = {**state["prior"], "targets": state["paths"], **state["accumulated"]}
    paths = sorted((root / "kb/corpora").glob("*/manifest.yaml"))
    return _scan_state(paths, {"document_records": []}, prior)


def scan_statistics_document(state: dict) -> dict:
    """Append every document from one manifest in native order."""
    path = Path(state["paths"][state["cursor"]])
    document_records = state["accumulated"]["document_records"]
    payload = read_yaml(path)
    for artifact in payload.get("artifacts", []) if isinstance(payload, dict) else []:
        if artifact.get("category") == "source_evidence":
            document_records.append(
                {
                    "manifest": path.name,
                    "document_id": artifact["document_id"],
                    "raw_sha256": artifact["sha256"],
                    "status": "extracted",
                }
            )
    return _scan_advance(state)


def prepare_statistics_batches(state: dict) -> dict:
    """Deduplicate document identities, initialize release defaults, discover pointers."""
    _, _, _, pointer, pointer_dir = _statistics_context(state["prior"]["context"])
    document_records = state["accumulated"]["document_records"]
    unique_documents = {
        item.get("raw_sha256") or item.get("source_version_id") or item.get("document_id")
        for item in document_records
        if item.get("raw_sha256") or item.get("source_version_id") or item.get("document_id")
    }
    released_onboarding: dict[str, Any] = {
        "active_release_id": None,
        "active_release_ids": [],
        "batches": [],
        "features": 0,
        "clauses": 0,
        "rules": 0,
        "compiled_facts": 0,
        "compiled_rules": 0,
    }
    pointer_paths = ([pointer] if pointer.exists() else []) + sorted(
        pointer_dir.glob("*.yaml") if pointer_dir.exists() else []
    )
    batch_statistics = []
    prior = {
        **state["prior"],
        "document_records": document_records,
        "unique_documents": list(unique_documents),
    }
    return _scan_state(
        pointer_paths,
        {
            "released_onboarding": released_onboarding,
            "released_onboarding_json": json.dumps(released_onboarding),
            "batch_statistics": batch_statistics,
            "batch_statistics_json": json.dumps(batch_statistics),
        },
        prior,
    )


def scan_statistics_batch(state: dict) -> dict:
    """Count assertions and complete compiled statements for exactly one pointer."""
    root, *_ = _statistics_context(state["prior"]["context"])
    pointer_path = Path(state["paths"][state["cursor"]])
    batch_statistics = json.loads(state["accumulated"]["batch_statistics_json"])
    pointer = read_yaml(pointer_path)
    assertions = _records(root / pointer["assertions"])
    statements = _logic_statements(root / pointer["compiled"])
    batch_statistics.append(
        {
            "batch_id": pointer.get("batch_id", pointer_path.stem),
            "active_release_id": pointer["kb_release_id"],
            "features": sum(item.get("assertion_kind") == "feature" for item in assertions),
            "clauses": sum(item.get("assertion_kind") == "clause" for item in assertions),
            "rules": sum(item.get("assertion_kind") == "rule" for item in assertions),
            "compiled_facts": sum(":-" not in item for item in statements),
            "compiled_rules": sum(":-" in item for item in statements),
        }
    )
    state["accumulated"]["batch_statistics"] = batch_statistics
    state["accumulated"]["batch_statistics_json"] = json.dumps(batch_statistics)
    return _scan_advance(state)


def finish_statistics_snapshot(state: dict) -> dict:
    """Aggregate release locals, construct schema version two, and hash the empty-hash payload."""
    p = state["prior"]
    targets, target_stats = p["targets"], json.loads(p["target_stats_json"])
    unique_facts, unique_rules = p["unique_facts"], p["unique_rules"]
    nl_fr, nl_en = p["nl_fr"], p["nl_en"]
    document_records, unique_documents = p["document_records"], p["unique_documents"]
    batch_statistics = json.loads(state["accumulated"]["batch_statistics_json"])
    released_onboarding = json.loads(state["accumulated"]["released_onboarding_json"])
    if batch_statistics:
        released_onboarding = {
            "active_release_id": batch_statistics[-1]["active_release_id"],
            "active_release_ids": [item["active_release_id"] for item in batch_statistics],
            "batches": batch_statistics,
            "features": sum(item["features"] for item in batch_statistics),
            "clauses": sum(item["clauses"] for item in batch_statistics),
            "rules": sum(item["rules"] for item in batch_statistics),
            "compiled_facts": sum(item["compiled_facts"] for item in batch_statistics),
            "compiled_rules": sum(item["compiled_rules"] for item in batch_statistics),
        }
    payload = {
        "schema_version": 2,
        "snapshot_hash": "",
        "canonical_kb": json.loads(p["canonical_json"]),
        "compiled_logic": {
            "targets": len(targets),
            "unique_facts_across_targets": len(unique_facts),
            "unique_rules_across_targets": len(unique_rules),
            "nl_fr_comments": nl_fr,
            "nl_en_comments": nl_en,
            "by_target": target_stats,
            "note": "Counts are per canonical compiled target in domain corpora.",
        },
        "released_onboarding": released_onboarding,
        "documents": {
            "manifest_records": len(document_records),
            "unique_documents": len(unique_documents),
            "extracted": sum(item.get("status") == "extracted" for item in document_records),
            "failed": sum(item.get("status") == "failed" for item in document_records),
            "pdf": sum(item.get("content_kind") == "pdf" for item in document_records),
            "html": sum(item.get("content_kind") == "html" for item in document_records),
            "note": "Manifest records include repeated references to the same content; unique_documents deduplicates them by hash, version ID, or document ID.",
        },
    }
    payload["snapshot_hash"] = canonical_sha256(payload)
    return payload


def build_kb_statistics() -> dict[str, Any]:
    """Measure canonical records using the same finite phases exposed to MCP."""
    state = prepare_statistics_targets({})
    for advance, prepare in (
        (scan_statistics_target, prepare_statistics_documents),
        (scan_statistics_document, prepare_statistics_batches),
        (scan_statistics_batch, None),
    ):
        while state["has_more"]:
            state = advance(state)
        if prepare is not None:
            state = prepare(state)
    return finish_statistics_snapshot(state)


def write_statistics_yaml(payload: dict[str, Any], output_dir: Path) -> Path:
    """Write the first native artifact."""
    yaml_path = output_dir / "kb_statistics.yaml"
    write_yaml(yaml_path, payload)
    return yaml_path


def write_statistics_markdown(payload: dict[str, Any], output_dir: Path) -> Path:
    """Write the second native artifact using the source-owned rendering."""
    markdown_path = output_dir / "kb_statistics.md"
    canonical = payload["canonical_kb"]
    logic = payload["compiled_logic"]
    documents = payload["documents"]
    onboarding = payload["released_onboarding"]
    write_text(
        markdown_path,
        "# KB and document statistics\n\n"
        f"Snapshot: `{payload['snapshot_hash']}`\n\n"
        f"- Canonical policy clauses: {canonical['policy_clauses']}\n"
        f"- Canonical policy rules: {canonical['policy_rules']}\n"
        f"- Candidate records: {canonical['candidate_records']}\n"
        f"- Formalization drafts: {canonical['formalization_drafts']}\n"
        f"- Compiled targets: {logic['targets']}\n"
        f"- Unique compiled facts: {logic['unique_facts_across_targets']}\n"
        f"- Unique compiled rules: {logic['unique_rules_across_targets']}\n"
        f"- Active onboarding release: {onboarding['active_release_id']}\n"
        f"- Released onboarding features / clauses / rules: {onboarding['features']} / {onboarding['clauses']} / {onboarding['rules']}\n"
        f"- Released onboarding compiled facts / rules: {onboarding['compiled_facts']} / {onboarding['compiled_rules']}\n"
        f"- NL-FR / NL-EN comments: {logic['nl_fr_comments']} / {logic['nl_en_comments']}\n"
        f"- Document manifest records: {documents['manifest_records']}\n"
        f"- Unique documents: {documents['unique_documents']}\n"
        f"- Extracted / failed: {documents['extracted']} / {documents['failed']}\n",
    )
    return markdown_path


def write_kb_statistics(output_dir: Path = KB_STATISTICS_DIR) -> dict[str, Path]:
    """Write YAML then Markdown; uncaught errors retain any preceding writes."""
    payload = build_kb_statistics()
    yaml_path = write_statistics_yaml(payload, output_dir)
    markdown_path = write_statistics_markdown(payload, output_dir)
    return {"yaml": yaml_path, "markdown": markdown_path}


def validate_kb_statistics(path: Path | None = None) -> list[str]:
    """Recompute a statistics snapshot and reject stale or internally inconsistent output."""
    expected = build_kb_statistics()
    if path is not None:
        actual = read_yaml(path)
        if actual != expected:
            raise ValueError("KB statistics artifact is stale")
    logic = expected["compiled_logic"]
    if logic["nl_fr_comments"] != logic["nl_en_comments"]:
        raise ValueError("compiled bilingual commentary counts differ")
    return [
        f"clauses={expected['canonical_kb']['policy_clauses']}",
        f"rules={expected['canonical_kb']['policy_rules']}",
        f"facts={logic['unique_facts_across_targets']}",
        f"compiled_rules={logic['unique_rules_across_targets']}",
        f"onboarding_features={expected['released_onboarding']['features']}",
        f"onboarding_clauses={expected['released_onboarding']['clauses']}",
        f"onboarding_rules={expected['released_onboarding']['rules']}",
        f"documents={expected['documents']['unique_documents']}",
    ]
