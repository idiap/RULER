# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Compatibility adapters from existing RULER artifacts to controlled contracts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ruler.ingestion.contracts import (
    CatalogueRow,
    FormalizationCandidate,
    NullMeaning,
    SourceRegistryEntry,
    SourceVersion,
    TranslationUnit,
    WorkbookCell,
    WorkbookIntake,
    WorkbookSheetSignature,
    canonical_sha256,
    stable_id,
)


def adapt_workbook_catalogue(
    workbook_path: Path, *, ingested_at: datetime | None = None
) -> tuple[WorkbookIntake, tuple[CatalogueRow, ...]]:
    """Adapt the legacy workbook into reversible intake and row contracts."""
    workbook_bytes = workbook_path.read_bytes()
    workbook_hash = canonical_sha256(workbook_bytes)
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    signatures = tuple(_sheet_signature(sheet) for sheet in workbook.worksheets)
    intake_payload = {
        "workbook_sha256": workbook_hash,
        "sheet_signatures": [item.model_dump(mode="json") for item in signatures],
    }
    intake = WorkbookIntake(
        intake_run_id=stable_id("workbook_intake", intake_payload),
        workbook_sha256=workbook_hash,
        sheet_signatures=signatures,
        accepted_rows=sum(
            1
            for row in workbook["Produits"].iter_rows(min_row=4, values_only=True)
            if any(value is not None and str(value).strip() for value in row)
        ),
        warning_rows=0,
        quarantined_rows=0,
        schema_decision="accepted",
        ingested_at=ingested_at or datetime.now(UTC),
    )
    rows = tuple(
        _catalogue_row(intake.intake_run_id, row_number, values)
        for row_number, values in (
            (number, row)
            for number, row in enumerate(
                workbook["Produits"].iter_rows(min_row=4, values_only=True), start=4
            )
            if any(value is not None and str(value).strip() for value in row)
        )
    )
    return intake, rows


def adapt_legacy_source_manifests(
    link_manifest: dict[str, Any],
    extraction_manifest: dict[str, Any],
    *,
    catalogue_rows: tuple[CatalogueRow, ...] = (),
) -> tuple[tuple[SourceRegistryEntry, ...], tuple[SourceVersion, ...]]:
    """Join legacy link/extraction views without mutating either source manifest."""
    links = {item["document_id"]: item for item in link_manifest.get("selected_documents", [])}
    row_id_by_coordinate = {
        (item.sheet_name, item.row_number): item.row_id for item in catalogue_rows
    }
    registry: list[SourceRegistryEntry] = []
    versions: list[SourceVersion] = []
    for document in extraction_manifest.get("documents", []):
        if document.get("status") != "extracted" or not document.get("raw_sha256"):
            continue
        linked = links.get(document["document_id"], {})
        canonical_url = str(document["fetch_url"])
        retrieval_url = str(document.get("retrieval_url") or canonical_url)
        provider = str(document.get("organization") or "unknown")
        task_identity = {"provider_id": provider, "canonical_url": canonical_url}
        if "retrieval_url" in document:
            task_identity["retrieval_url"] = retrieval_url
        task_id = stable_id("source_task", task_identity)
        raw_hash = str(document["raw_sha256"])
        version_id = stable_id(
            "source_version", {"source_task_id": task_id, "raw_sha256": raw_hash}
        )
        supplied_task_id = document.get("source_task_id")
        if supplied_task_id is not None and supplied_task_id != task_id:
            raise ValueError(
                f"{document['document_id']}: extraction source_task_id does not match URLs"
            )
        supplied_version_id = document.get("source_version_id")
        if supplied_version_id is not None and supplied_version_id != version_id:
            raise ValueError(
                f"{document['document_id']}: extraction source_version_id does not match content"
            )
        row_refs = tuple(str(value) for value in document.get("row_refs", []))
        registry.append(
            SourceRegistryEntry(
                source_task_id=task_id,
                provider_id=provider,
                catalogue_row_ids=tuple(
                    _catalogue_row_id_from_ref(value, row_id_by_coordinate) for value in row_refs
                ),
                product_ids=tuple(
                    sorted({stable_id("product", value) for value in document.get("products", [])})
                ),
                submitted_urls=(str(linked.get("submitted_url") or canonical_url),),
                canonical_url=canonical_url,
                retrieval_url=retrieval_url if "retrieval_url" in document else None,
                document_ids=(str(document["document_id"]),),
                source_version_ids=(version_id,),
                extraction_artifact_ids=tuple(
                    stable_id("extraction_artifact", item)
                    for item in document.get("extracted_artifacts", [])
                ),
            )
        )
        versions.append(
            SourceVersion(
                source_version_id=version_id,
                source_task_id=task_id,
                raw_sha256=raw_hash,
                byte_length=int(document.get("raw_bytes") or 0),
                retrieved_at=_manifest_datetime(extraction_manifest.get("created_at")),
                submitted_url=str(linked.get("submitted_url") or canonical_url),
                final_url=retrieval_url,
                http_status=200,
                content_type=str(document.get("content_type") or "application/octet-stream"),
            )
        )
    return tuple(sorted(registry, key=lambda item: item.source_task_id)), tuple(
        sorted(versions, key=lambda item: item.source_version_id)
    )


def adapt_priority_candidates(
    spans: list[dict[str, Any]],
    translations: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    source_registry: tuple[SourceRegistryEntry, ...],
    source_versions: tuple[SourceVersion, ...],
) -> tuple[tuple[TranslationUnit, ...], tuple[FormalizationCandidate, ...]]:
    """Adapt current candidate-only priority artifacts; never infer approval."""
    span_by_element = {item["element_id"]: item for item in spans}
    translation_by_element = {item["element_id"]: item for item in translations}
    versions_by_id = {item.source_version_id: item for item in source_versions}
    version_by_document = {
        document_id: versions_by_id[version_id]
        for entry in source_registry
        for document_id in entry.document_ids
        for version_id in entry.source_version_ids
        if version_id in versions_by_id
    }
    controlled_units: list[TranslationUnit] = []
    candidates: list[FormalizationCandidate] = []
    for draft in drafts:
        span = span_by_element[draft["element_id"]]
        translation = translation_by_element[draft["element_id"]]
        try:
            version = version_by_document[str(span["source_id"])]
        except KeyError as error:
            raise ValueError(
                f"no source registry version for span source {span['source_id']}"
            ) from error
        statement = str(translation["controlled_statement"])
        unit = TranslationUnit(
            translation_unit_id=str(translation["translation_id"]),
            structural_element_ids=(str(span["span_id"]),),
            source_language=str(span.get("language") or "und"),
            source_text_sha256=str(span["text_sha256"]),
            controlled_english=statement,
            controlled_english_sha256=canonical_sha256(statement),
            terminology_decision_ids=tuple(sorted(translation.get("predicate_candidates", []))),
            review_state="draft",
        )
        semantic_payload = dict(draft["draft_payload"])
        semantic_hash = canonical_sha256(semantic_payload)
        binding = {
            "source_version_id": version.source_version_id,
            "source_span_ids": (str(span["span_id"]),),
            "source_text_sha256s": (str(span["text_sha256"]),),
            "formal_element_id": str(draft["target_id"]),
            "semantic_sha256": semantic_hash,
        }
        controlled_units.append(unit)
        candidates.append(
            FormalizationCandidate(
                candidate_id=stable_id("formalization_candidate", binding),
                **binding,
                translation_unit_ids=(unit.translation_unit_id,),
                semantic_payload=semantic_payload,
                state="formalization_candidate",
            )
        )
    return tuple(controlled_units), tuple(candidates)


def _sheet_signature(sheet: Any) -> WorkbookSheetSignature:
    header_rows = [
        list(row)
        for row in sheet.iter_rows(min_row=1, max_row=min(3, sheet.max_row), values_only=True)
    ]
    return WorkbookSheetSignature(
        name=sheet.title,
        row_count=sheet.max_row,
        column_count=sheet.max_column,
        header_sha256=canonical_sha256(header_rows),
    )


def _catalogue_row(intake_id: str, row_number: int, values: tuple[Any, ...]) -> CatalogueRow:
    def value(index: int) -> Any:
        """Read an optional workbook column without losing an out-of-range null."""
        return values[index] if index < len(values) else None

    cells = tuple(
        WorkbookCell(
            coordinate=f"Produits!{_column_name(index + 1)}{row_number}",
            original_value=cell,
            normalized_value=cell if cell is not None and str(cell).strip() else None,
            null_meaning=(
                NullMeaning.VALUE
                if cell is not None and str(cell).strip()
                else NullMeaning.GENUINELY_EMPTY
            ),
        )
        for index, cell in enumerate(values)
    )
    identity = {"intake_run_id": intake_id, "sheet_name": "Produits", "row_number": row_number}
    source_value = value(14)
    return CatalogueRow(
        row_id=stable_id("catalogue_row", identity),
        intake_run_id=intake_id,
        sheet_name="Produits",
        row_number=row_number,
        client_segment_id=stable_id("client_segment", value(1)),
        provider_id=stable_id("provider", value(2)),
        branch_id=stable_id("branch", value(3)),
        product_id=stable_id("product", value(4)),
        feature_id=stable_id(
            "feature", {"product": value(4), "coverage": value(6), "label": value(7)}
        ),
        source_reference_ids=(stable_id("source_reference", source_value),) if source_value else (),
        cells=cells,
    )


def _legacy_row_id(row_ref: str) -> str:
    match = re.search(r"#([^!]+)!(\d+)$", row_ref)
    return stable_id("legacy_catalogue_row", match.groups() if match else row_ref)


def _catalogue_row_id_from_ref(
    row_ref: str, row_id_by_coordinate: dict[tuple[str, int], str]
) -> str:
    match = re.search(r"#([^!]+)!(\d+)$", row_ref)
    if match:
        coordinate = (match.group(1), int(match.group(2)))
        if coordinate in row_id_by_coordinate:
            return row_id_by_coordinate[coordinate]
    return _legacy_row_id(row_ref)


def _manifest_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        return datetime.fromisoformat(str(value))
    return datetime.now(UTC)


def _column_name(number: int) -> str:
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(65 + remainder) + output
    return output
