# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Release binding, coherence, and dependency-closed KB projection tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from ruler.ingestion import (
    FormalElementAnnotation,
    KBReleaseManifest,
    canonical_sha256,
    stable_id,
)
from ruler.kb.repository import KnowledgeRepository, ProjectionRequest, ReleasedAssertion

NOW = datetime(2026, 8, 13, tzinfo=UTC)
SOURCE_ID = "source-version:motor-2026"
SOURCE_HASH = canonical_sha256(b"independent policy fixture")


def _assertion(
    assertion_id: str,
    *,
    semantic_key: str | None = None,
    kind: str = "rule",
    provider: str = "provider_a",
    family: str = "motor_vehicle",
    product: str = "motor-basic",
    jurisdiction: str = "CH",
    segments: tuple[str, ...] = (),
    options: tuple[str, ...] = (),
    option_group_id: str | None = None,
    option_group_required: bool = False,
    option_group_product_ids: tuple[str, ...] = (),
    dependency_only: bool = False,
    effective_from: date | None = date(2026, 1, 1),
    effective_to: date | None = date(2026, 12, 31),
    dependencies: tuple[str, ...] = (),
    contradicts: tuple[str, ...] = (),
    precedes: tuple[str, ...] = (),
    payload: dict[str, object] | None = None,
) -> ReleasedAssertion:
    content = payload or {"predicate": "covers", "object": assertion_id}
    return ReleasedAssertion(
        assertion_id=assertion_id,
        semantic_key=semantic_key or f"semantic:{assertion_id}",
        assertion_kind=kind,
        provider=provider,
        product_family=family,
        product_id=product,
        jurisdiction=jurisdiction,
        customer_segments=segments,
        option_ids=options,
        option_group_id=option_group_id,
        option_group_required=option_group_required,
        option_group_product_ids=option_group_product_ids,
        dependency_only=dependency_only,
        effective_from=effective_from,
        effective_to=effective_to,
        dependencies=dependencies,
        contradicts=contradicts,
        precedes=precedes,
        source_version_ids=(SOURCE_ID,),
        annotation_id=f"annotation:{assertion_id}",
        payload=content,
        payload_sha256=canonical_sha256(content),
    )


def _annotation(assertion: ReleasedAssertion) -> FormalElementAnnotation:
    identity = {
        "formal_element_id": assertion.assertion_id,
        "semantic_sha256": assertion.payload_sha256,
        "source_span_ids": (f"span:{assertion.assertion_id}",),
        "source_text_sha256s": (canonical_sha256(f"source:{assertion.assertion_id}"),),
        "source_language": "fr",
        "source_language_gloss": f"Règle contrôlée {assertion.assertion_id}.",
        "controlled_english": f"Controlled rule {assertion.assertion_id}.",
        "terminology_decision_ids": ("term:coverage",),
    }
    return FormalElementAnnotation(
        annotation_id=stable_id("formal_annotation", identity),
        **identity,
        review_state="approved",
        reviewer_id="reviewer:fixture",
        approved_at=NOW,
        approval_id="approval:fixture",
    )


def _with_bound_annotation(
    assertion: ReleasedAssertion,
) -> tuple[ReleasedAssertion, FormalElementAnnotation]:
    annotation = _annotation(assertion)
    return assertion.model_copy(update={"annotation_id": annotation.annotation_id}), annotation


def _release(
    assertions: list[ReleasedAssertion],
    annotations: list[FormalElementAnnotation],
) -> KBReleaseManifest:
    one = {"fixture:one": canonical_sha256("fixture")}
    payload = {
        "corpus_snapshot_id": "snapshot:fixture",
        "source_version_hashes": {SOURCE_ID: SOURCE_HASH},
        "span_hashes": one,
        "translation_hashes": one,
        "formal_record_hashes": {
            item.assertion_id: canonical_sha256(item.model_dump(mode="json")) for item in assertions
        },
        "automated_gate_hashes": {"automated_gate:fixture": canonical_sha256("gate")},
        "optional_review_hashes": {"review:fixture": canonical_sha256("review")},
        "annotation_hashes": {
            item.annotation_id: canonical_sha256(item.model_dump(mode="json"))
            for item in annotations
        },
        "executable_rule_hashes": one,
        "validator_hashes": one,
    }
    return KBReleaseManifest(
        kb_release_id=stable_id("kb_release", payload),
        **payload,
        created_at=NOW,
        release_status="published",
    )


def _repository(assertions: list[ReleasedAssertion]) -> KnowledgeRepository:
    bound = [_with_bound_annotation(item) for item in assertions]
    released = [item[0] for item in bound]
    annotations = [item[1] for item in bound]
    return KnowledgeRepository(_release(released, annotations), released, annotations)


def _request(**updates: object) -> ProjectionRequest:
    values = {
        "product_family": "motor_vehicle",
        "provider": "provider_a",
        "product_ids": ("motor-basic",),
        "jurisdiction": "CH",
        "customer_segment": "private",
        "effective_on": date(2026, 6, 1),
        "option_ids": (),
    }
    values.update(updates)
    return ProjectionRequest(**values)


def test_repository_requires_published_hash_complete_release() -> None:
    assertion, annotation = _with_bound_annotation(_assertion("rule:one"))
    release = _release([assertion], [annotation])
    KnowledgeRepository(release, [assertion], [annotation])
    with pytest.raises(ValueError, match="published release"):
        KnowledgeRepository(
            release.model_copy(update={"release_status": "built"}), [assertion], [annotation]
        )
    with pytest.raises(ValueError, match="release assertions not loaded"):
        KnowledgeRepository(release, [], [annotation])


def test_assertion_and_annotation_hash_or_semantic_drift_is_rejected() -> None:
    assertion, annotation = _with_bound_annotation(_assertion("rule:one"))
    release = _release([assertion], [annotation])
    drifted = assertion.model_copy(update={"semantic_key": "semantic:changed"})
    with pytest.raises(ValueError, match="release assertion hash mismatch"):
        KnowledgeRepository(release, [drifted], [annotation])
    changed_annotation = annotation.model_copy(
        update={"controlled_english": "Changed after release."}
    )
    with pytest.raises(ValueError, match="release annotation hash mismatch"):
        KnowledgeRepository(release, [assertion], [changed_annotation])
    mismatched_semantics = annotation.model_copy(
        update={"semantic_sha256": canonical_sha256("other")}
    )
    altered_release = _release([assertion], [mismatched_semantics])
    with pytest.raises(ValueError, match="annotation semantic hash mismatch"):
        KnowledgeRepository(altered_release, [assertion], [mismatched_semantics])


def test_released_assertion_recomputes_payload_hash_and_temporal_order() -> None:
    with pytest.raises(ValidationError, match="payload_sha256"):
        _assertion("rule:bad").model_copy(
            update={"payload_sha256": canonical_sha256("bad")}, deep=True
        ).__class__.model_validate(
            {
                **_assertion("rule:bad").model_dump(mode="python"),
                "payload_sha256": canonical_sha256("bad"),
            }
        )
    with pytest.raises(ValidationError, match="effective_from"):
        _assertion("rule:bad-date", effective_from=date(2027, 1, 1), effective_to=date(2026, 1, 1))


def test_coherence_detects_duplicates_dangling_edges_cycles_and_unresolved_contradictions() -> None:
    assertions = [
        _assertion(
            "rule:a", semantic_key="duplicate", dependencies=("rule:b",), contradicts=("rule:c",)
        ),
        _assertion("rule:b", semantic_key="duplicate", dependencies=("rule:a",)),
        _assertion("rule:c", contradicts=("rule:a",)),
        _assertion("rule:d", dependencies=("rule:missing",), precedes=("rule:missing-relation",)),
    ]
    report = _repository(assertions).coherence_report()
    codes = {issue.code for issue in report.issues}
    assert codes == {
        "KB_DANGLING_DEPENDENCY",
        "KB_DANGLING_RELATION",
        "KB_DEPENDENCY_CYCLE",
        "KB_DUPLICATE_SEMANTIC_KEY",
        "KB_UNRESOLVED_CONTRADICTION",
    }
    assert report.coherent is False


def test_precedence_resolves_contradiction_regardless_of_relation_direction() -> None:
    left = _assertion("rule:a", contradicts=("rule:z",), precedes=("rule:z",))
    right = _assertion("rule:z", contradicts=("rule:a",))
    assert _repository([left, right]).coherence_report().coherent
    # Previously a one-sided contradiction declared by the lexically larger ID was skipped.
    high_only = _assertion("rule:z", contradicts=("rule:a",))
    codes = {
        issue.code
        for issue in _repository([_assertion("rule:a"), high_only]).coherence_report().issues
    }
    assert "KB_UNRESOLVED_CONTRADICTION" in codes


def test_projection_is_dependency_closed_deterministic_and_excludes_irrelevant_policies() -> None:
    definition = _assertion(
        "definition:vehicle",
        kind="definition",
        provider="shared",
        family="definitions",
        product="shared",
    )
    root = _assertion("rule:motor", dependencies=("definition:vehicle",))
    irrelevant = _assertion("rule:home", family="household", product="home", provider="other")
    repository = _repository([definition, root, irrelevant])
    first = repository.project(_request())
    second = repository.project(_request(product_ids=("motor-basic", "motor-basic")))
    assert first.assertion_ids == ("definition:vehicle", "rule:motor")
    assert second.projection_id == first.projection_id
    assert "rule:home" not in first.assertion_ids
    reasons = {item.assertion_id: item.reason for item in first.decisions}
    assert reasons == {
        "definition:vehicle": "dependency",
        "rule:home": "outside_scope",
        "rule:motor": "scope_match",
    }


def test_projection_filters_provider_segment_date_and_required_options() -> None:
    assertions = [
        _assertion("rule:base", segments=("private",)),
        _assertion("rule:business", segments=("business",)),
        _assertion("rule:option", options=("assistance-top",)),
        _assertion(
            "rule:expired", effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31)
        ),
        _assertion("rule:future", effective_from=date(2027, 1, 1), effective_to=None),
        _assertion("rule:other-provider", provider="provider_b"),
    ]
    repository = _repository(assertions)
    without_option = repository.project(_request())
    assert without_option.assertion_ids == ("rule:base",)
    with_option = repository.project(_request(option_ids=("assistance-top",)))
    assert with_option.assertion_ids == ("rule:base", "rule:option")


def test_projection_request_set_fields_are_order_and_duplicate_invariant() -> None:
    repository = _repository(
        [
            _assertion("rule:one", options=("a",)),
            _assertion("rule:two", options=("b",)),
        ]
    )
    left = repository.project(_request(option_ids=("b", "a", "a")))
    right = repository.project(_request(option_ids=("a", "b")))
    assert left.request.option_ids == ("a", "b")
    assert left.projection_id == right.projection_id
    assert left.model_dump(mode="json") == right.model_dump(mode="json")


def test_required_exclusive_option_group_selects_exactly_one_and_closes_dependencies() -> None:
    group_id = "service-variant"
    dependencies = [
        _assertion(
            f"clause:capability-{name}",
            options=(f"capability:{name}",),
            dependency_only=True,
        )
        for name in ("partial", "collision", "parked")
    ]
    members = [
        _assertion(
            f"clause:variant-{index}",
            options=(f"variant-{index}",),
            option_group_id=group_id,
            option_group_required=True,
            dependencies=(dependencies[index - 1].assertion_id,) if index <= 3 else (),
        )
        for index in range(1, 5)
    ]
    repository = _repository([*dependencies, *members])

    with pytest.raises(ValueError, match="requires exactly one selection"):
        repository.project(_request())
    with pytest.raises(ValueError, match="mutually exclusive"):
        repository.project(_request(option_ids=("variant-1", "variant-2")))

    projection = repository.project(_request(option_ids=("variant-1", "capability:collision")))
    assert projection.assertion_ids == ("clause:capability-partial", "clause:variant-1")
    reasons = {item.assertion_id: item.reason for item in projection.decisions}
    assert reasons["clause:capability-partial"] == "dependency"
    assert reasons["clause:capability-collision"] == "outside_scope"

    with pytest.raises(ValueError, match="dependency-only assertions cannot be requested"):
        repository.project(
            _request(assertion_ids=("clause:capability-partial",), option_ids=("variant-1",))
        )


@pytest.mark.parametrize("product_id", ["motor_vehicle", "Véhicule à moteur"])
def test_option_group_declared_product_aliases_enforce_required_selection(
    product_id: str,
) -> None:
    repository = _repository(
        [
            _assertion(
                "clause:variant",
                options=("variant",),
                option_group_id="service-variant",
                option_group_required=True,
                option_group_product_ids=("motor_vehicle", "Véhicule à moteur"),
            )
        ]
    )

    with pytest.raises(ValueError, match="requires exactly one selection"):
        repository.project(_request(product_ids=(product_id,)))
    assert repository.project(
        _request(product_ids=(product_id,), option_ids=("variant",))
    ).assertion_ids == ("clause:variant",)


def test_required_option_groups_outside_product_provider_or_family_do_not_constrain_request() -> (
    None
):
    repository = _repository(
        [
            _assertion("rule:motor-base"),
            _assertion(
                "rule:home-option",
                options=("home-variant",),
                option_group_id="home-variant-group",
                option_group_required=True,
                option_group_product_ids=("home",),
            ),
            _assertion(
                "rule:other-provider-option",
                provider="other",
                options=("other-provider-variant",),
                option_group_id="other-provider-group",
                option_group_required=True,
            ),
            _assertion(
                "rule:other-family-option",
                family="household",
                product="motor-basic",
                options=("other-family-variant",),
                option_group_id="other-family-group",
                option_group_required=True,
            ),
        ]
    )

    assert repository.project(_request()).assertion_ids == ("rule:motor-base",)


def test_default_option_group_metadata_is_omitted_from_release_serialization() -> None:
    payload = _assertion("rule:legacy").model_dump(mode="json")
    assert "option_group_id" not in payload
    assert "option_group_required" not in payload
    assert "option_group_product_ids" not in payload
    assert "dependency_only" not in payload
