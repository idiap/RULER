# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from ruler.ingestion.batch_pipeline import DocumentBatchPaths, DocumentBatchPipelineSpec
from ruler.ingestion.contracts import (
    CorpusRecord,
    DocumentSourceRegistryEntry,
    EntityAssociation,
    IngestionBundle,
    stable_id,
    validate_ingestion_bundle,
)
from ruler.ingestion.record_registry import RecordParserRegistry


def _document_task(*, record_ids: tuple[str, ...] = ()) -> DocumentSourceRegistryEntry:
    identity: dict[str, Any] = {
        "domain_id": "regulatory",
        "corpus_id": "workplace_safety",
        "canonical_url": "https://authority.example/safety.pdf",
        "publisher_id": "safety_authority",
    }
    return DocumentSourceRegistryEntry(
        source_task_id=stable_id("source_task", identity),
        domain_id="regulatory",
        corpus_id="workplace_safety",
        publisher_id="safety_authority",
        canonical_url=identity["canonical_url"],
        submitted_urls=(identity["canonical_url"],),
        corpus_record_ids=record_ids,
        document_ids=("safety-regulation",),
    )


def test_document_only_corpus_needs_no_workbook_product_or_entity() -> None:
    bundle = IngestionBundle(document_source_registry=(_document_task(),))
    assert bundle.workbook_intakes == ()
    assert bundle.catalogue_rows == ()
    assert bundle.entity_associations == ()
    assert validate_ingestion_bundle(bundle) == []


def test_neutral_records_validate_domain_scoped_entity_associations() -> None:
    association_identity = {
        "domain_id": "regulatory",
        "entity_kind": "regulated_operator",
        "entity_id": "operator-1",
        "role": "subject",
    }
    association = EntityAssociation(
        association_id=stable_id("entity_association", association_identity),
        **association_identity,
    )
    record_identity = {
        "domain_id": "regulatory",
        "corpus_id": "workplace_safety",
        "record_type": "document",
        "external_id": "safety-regulation",
    }
    record = CorpusRecord(
        record_id=stable_id("corpus_record", record_identity),
        **record_identity,
        entity_association_ids=(association.association_id,),
    )
    bundle = IngestionBundle(
        entity_associations=(association,),
        corpus_records=(record,),
        document_source_registry=(_document_task(record_ids=(record.record_id,)),),
    )
    assert validate_ingestion_bundle(bundle) == []


class ProvisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provision_id: str
    text: str


def test_record_parser_registry_is_versioned_and_fail_closed() -> None:
    registry = RecordParserRegistry()
    registry.register(
        domain_id="regulatory",
        record_type="provision",
        schema_version="2.0",
        parser=ProvisionRecord.model_validate,
    )
    parsed = registry.parse(
        domain_id="regulatory",
        record_type="provision",
        schema_version="2.0",
        payload={"provision_id": "p1", "text": "An operator shall keep records."},
    )
    assert parsed.provision_id == "p1"
    with pytest.raises(LookupError, match="unknown record parser"):
        registry.parse(
            domain_id="regulatory", record_type="provision", schema_version="3.0", payload={}
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        registry.parse(
            domain_id="regulatory",
            record_type="provision",
            schema_version="2.0",
            payload={"provision_id": "p1", "text": "x", "provider": "fake"},
        )


def test_document_batch_contract_has_no_product_labels() -> None:
    spec = DocumentBatchPipelineSpec(
        batch_id="regulatory-wave-1",
        sequence=1,
        domain_id="regulatory",
        corpus_id="workplace_safety",
        planned_document_ids=("safety-regulation",),
        quality_case_id="regulatory-fidelity",
        record_parser_types=("provision",),
        paths=DocumentBatchPaths(
            source_manifest="kb/corpora/workplace_safety/sources.yaml",
            extraction_manifest="kb/corpora/workplace_safety/extraction.yaml",
            span_specs="kb/corpora/workplace_safety/spans.yaml",
            formal_elements="kb/corpora/workplace_safety/formal.yaml",
            output_root="build/workplace_safety",
        ),
    )
    assert spec.schema_version == 2
    assert "product_labels" not in spec.model_dump()
