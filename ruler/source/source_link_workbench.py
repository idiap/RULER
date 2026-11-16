# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Editable source-link workbench for managed extraction.

The KB demo needs a small operational surface where advisors or developers can add
policy/product links, keep the list editable, and trigger extraction without
promoting claims into the formal KB. This module is the shared core behind the live
web demo and the MCP tool: it stores link metadata in `data/sources/manifests/`,
downloads/extracts one URL into the managed source corpus, and records the result as
extraction-only evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from ruler.io import read_yaml, stable_hash, write_yaml
from ruler.paths import SOURCE_MANIFEST_DIR
from ruler.source.source_corpus import (
    _canonical_url,
    _document_id,
    _organization_id,
    _source_kind_from_url,
)

SOURCE_LINK_WORKBENCH_FILE = SOURCE_MANIFEST_DIR / "live_demo_source_links.yaml"
SOURCE_LINK_EXTRACTION_MANIFEST = SOURCE_MANIFEST_DIR / "live_demo_source_link_extractions.yaml"


def load_source_link_workbench() -> dict[str, Any]:
    """Load the editable source-link list, starting with an empty workspace."""
    if SOURCE_LINK_WORKBENCH_FILE.exists():
        return read_yaml(SOURCE_LINK_WORKBENCH_FILE)
    payload = _source_link_payload(_default_source_links(), source="empty_workspace")
    write_yaml(SOURCE_LINK_WORKBENCH_FILE, payload)
    return payload


def save_source_link_workbench(links: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist a normalized editable source-link list."""
    payload = _source_link_payload(_normalize_links(links), source="live_demo_edit")
    write_yaml(SOURCE_LINK_WORKBENCH_FILE, payload)
    return payload


def _default_source_links() -> list[dict[str, Any]]:
    """Start with no sources; callers supply the documents for their domain."""
    return []


def _source_link_payload(links: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    """Wrap links with stable metadata for UI and MCP clients."""
    payload = {
        "link_set_id": "live_demo_source_links_2026_07_02",
        "updated_at": datetime.now(UTC).isoformat(),
        "source": source,
        "mode": "editable_extraction_only_no_autoformalization",
        "line_format": "Provider | product_family | URL",
        "links": links,
    }
    return payload | {"audit_hash": stable_hash(payload)}


def _normalize_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize editable link rows into a deduplicated structured list."""
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in links:
        url = _canonical_url(str(raw.get("url", "")).strip())
        if not url or url in seen:
            continue
        provider = str(raw.get("provider") or _provider_from_url(url)).strip()
        product_family = str(raw.get("product_family") or "user_added_source").strip()
        product_label = str(
            raw.get("product_label") or product_family.replace("_", " ").title()
        ).strip()
        normalized.append(
            {
                "provider": provider,
                "product_family": product_family,
                "product_label": product_label,
                "url": url,
                "case_fit": str(raw.get("case_fit", "user_added_pending_review")),
                "status": str(raw.get("status", "editable")),
                "editable": True,
            }
        )
        seen.add(url)
    return normalized


def _link_for_url(
    canonical_url: str,
    *,
    provider: str | None,
    product_family: str | None,
) -> dict[str, Any]:
    """Find a saved link by URL or create a normalized ad hoc link."""
    workbench = load_source_link_workbench()
    for link in workbench.get("links", []):
        if _canonical_url(str(link.get("url", ""))) == canonical_url:
            if provider:
                link["provider"] = provider
            if product_family:
                link["product_family"] = product_family
                link["product_label"] = product_family.replace("_", " ").title()
            return _normalize_links([link])[0]
    return _normalize_links(
        [
            {
                "provider": provider or _provider_from_url(canonical_url),
                "product_family": product_family or "user_added_source",
                "url": canonical_url,
                "status": "new",
            }
        ]
    )[0]


def _download_entry_from_link(link: dict[str, Any]) -> dict[str, Any]:
    """Convert one editable link into the generic source-corpus extraction entry."""
    provider = str(link["provider"])
    product_family = str(link["product_family"])
    url = str(link["url"])
    return {
        "document_id": _document_id(url),
        "organization": _organization_id([provider]),
        "provider": provider,
        "product_family": product_family,
        "fit_kind": link.get("case_fit", "user_added_pending_review"),
        "fetch_url": url,
        "source_kind": _source_kind_from_url(url),
        "seed": False,
        "discovered_from": "live_demo_source_link_workbench",
        "row_count": 0,
        "row_refs": [],
        "products": [product_family],
        "coverages": [],
        "normalized_concepts": [],
        "value_dimensions": [],
        "policy_buckets": ["user_added_source"],
        "relevance_score": 0,
        "selection_reasons": ["added_from_editable_kb_source_link_panel"],
    }


def _record_extraction(result: dict[str, Any]) -> None:
    """Append/update the extraction manifest for workbench-triggered links."""
    if SOURCE_LINK_EXTRACTION_MANIFEST.exists():
        manifest = read_yaml(SOURCE_LINK_EXTRACTION_MANIFEST)
    else:
        manifest = {
            "manifest_id": "live_demo_source_link_extractions_2026_07_02",
            "mode": "extraction_only_no_autoformalization",
            "extractions": [],
        }
    records = [
        record
        for record in manifest.get("extractions", [])
        if record.get("fetch_url") != result.get("fetch_url")
    ]
    records.append(result)
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    manifest["extractions"] = sorted(records, key=lambda item: item.get("fetch_url", ""))
    manifest["summary"] = {
        "links": len(manifest["extractions"]),
        "extracted": sum(
            1 for item in manifest["extractions"] if item.get("status") == "extracted"
        ),
        "failed": sum(1 for item in manifest["extractions"] if item.get("status") == "failed"),
    }
    write_yaml(SOURCE_LINK_EXTRACTION_MANIFEST, manifest | {"audit_hash": stable_hash(manifest)})


def _mark_link_extracted(link: dict[str, Any], result: dict[str, Any]) -> None:
    """Update the editable list status after an extraction attempt."""
    workbench = load_source_link_workbench()
    updated = []
    for item in workbench.get("links", []):
        if _canonical_url(str(item.get("url", ""))) == link["url"]:
            updated.append(
                {
                    **item,
                    "status": result.get("status", "unknown"),
                    "raw_path": result.get("raw_path"),
                    "extracted_artifacts": result.get("extracted_artifacts", []),
                }
            )
        else:
            updated.append(item)
    if not any(_canonical_url(str(item.get("url", ""))) == link["url"] for item in updated):
        updated.append(
            {
                **link,
                "status": result.get("status", "unknown"),
                "raw_path": result.get("raw_path"),
                "extracted_artifacts": result.get("extracted_artifacts", []),
            }
        )
    save_source_link_workbench(updated)


def _provider_from_url(url: str) -> str:
    """Infer a provider-ish display label from a URL host."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host:
        return "Unknown provider"
    return host.split(".")[0].replace("-", " ").title()


def extraction_result_paths(result: dict[str, Any]) -> dict[str, Any]:
    """Return short paths for extracted artifacts suitable for UI/MCP responses."""
    return {
        "raw_path": result.get("raw_path"),
        "extracted_artifacts": [
            {
                **artifact,
                "display_path": str(artifact["path"]),
            }
            for artifact in result.get("extracted_artifacts", [])
            if artifact.get("path")
        ],
    }
