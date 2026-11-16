# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import pytest

from ruler.applications.resource_portfolio.demonstrator_formalization import (
    load_claim_manifest,
    load_demonstrator_dossier,
)
from ruler.applications.resource_portfolio.demonstrator_synthetic_kb import (
    ExpandedSyntheticKBDossier,
    SyntheticClaimAnchor,
    build_expanded_claim_catalogue,
    generate_expanded_synthetic_kb,
    verify_expanded_claim_catalogue_consistency,
)


def test_expanded_synthetic_kb_is_deterministic_and_materially_more_complex() -> None:
    base = load_demonstrator_dossier()
    first = generate_expanded_synthetic_kb(base)
    second = generate_expanded_synthetic_kb(base)

    assert first == second
    assert first.content_sha256 == second.content_sha256
    assert first.source_text.startswith(base)
    assert first.expected_statement_count == 32
    assert len(first.claims) == 32
    # The annual base dossier now carries 36 exact schedule groundings, so use
    # an absolute materiality check rather than a ratio tied to its old size.
    assert len(first.source_text) > len(base) + 4_000
    assert {item.predicate for item in first.claims} == {
        "resource_provides",
        "activity_requires",
        "resource_eligible",
        "backup_required",
    }
    assert "if that resource provides grading capability" in first.source_text
    assert "is not eligible" in first.source_text
    assert "independently mobilizable backup" in first.source_text
    assert "pump_cascade_8in" in first.source_text
    assert first.source_text.count("dozer_talus_d8") == 2


def test_expanded_kb_digest_and_exact_claim_anchors_fail_closed() -> None:
    generated = generate_expanded_synthetic_kb(load_demonstrator_dossier())

    payload = generated.model_dump(mode="json")
    payload["content_sha256"] = "sha256:" + "0" * 64
    try:
        ExpandedSyntheticKBDossier.model_validate(payload)
    except ValueError as exc:
        assert "digest mismatch" in str(exc)
    else:
        raise AssertionError("mutated expanded KB digest was accepted")


def test_expanded_catalogue_has_43_unique_exact_natural_language_claims() -> None:
    base_source = load_demonstrator_dossier()
    expanded = generate_expanded_synthetic_kb(base_source)
    base_claims, _ = load_claim_manifest()
    combined = build_expanded_claim_catalogue(
        expanded,
        (
            SyntheticClaimAnchor(
                claim_id=item.claim_id,
                predicate=item.predicate,
                exact_text=item.exact_text,
                expected_constant_values=item.expected_constant_values,
            )
            for item in base_claims
        ),
    )

    assert len(combined) == 43
    assert len({item.claim_id for item in combined}) == 43
    assert all(expanded.source_text.count(item.exact_text) == 1 for item in combined)
    assert {
        predicate: sum(item.predicate == predicate for item in combined)
        for predicate in (
            "resource_provides",
            "activity_requires",
            "resource_eligible",
            "backup_required",
        )
    } == {
        "resource_provides": 14,
        "activity_requires": 11,
        "resource_eligible": 13,
        "backup_required": 5,
    }


def test_expanded_semantic_network_is_backed_and_nonvacuous() -> None:
    base_claims, _ = load_claim_manifest()
    expanded = generate_expanded_synthetic_kb(load_demonstrator_dossier())
    combined = build_expanded_claim_catalogue(
        expanded,
        (
            SyntheticClaimAnchor(
                claim_id=item.claim_id,
                predicate=item.predicate,
                exact_text=item.exact_text,
                expected_constant_values=item.expected_constant_values,
            )
            for item in base_claims
        ),
    )

    verify_expanded_claim_catalogue_consistency(combined)
    providers = {
        (str(item.expected_constant_values[0]), str(item.expected_constant_values[1]))
        for item in combined
        if item.predicate == "resource_provides"
    }
    assert ("pump_torrent_12in", "dewatering") in providers
    assert ("pump_cascade_8in", "dewatering") in providers
    assert ("dozer_talus_d8", "grading") in providers
    assert ("dozer_talus_d8", "material_handling") in providers


def test_expanded_semantic_audit_rejects_underbacked_and_vacuous_networks() -> None:
    base_claims, _ = load_claim_manifest()
    expanded = generate_expanded_synthetic_kb(load_demonstrator_dossier())
    combined = tuple(
        SyntheticClaimAnchor(
            claim_id=item.claim_id,
            predicate=item.predicate,
            exact_text=item.exact_text,
            expected_constant_values=item.expected_constant_values,
            expected_body_constant_values=item.expected_body_constant_values,
        )
        for item in (*base_claims, *expanded.claims)
    )

    without_cascade = tuple(
        item for item in combined if "pump_cascade_8in" not in item.expected_constant_values
    )
    with pytest.raises(ValueError, match="backup for dewatering has 1 distinct provider"):
        verify_expanded_claim_catalogue_consistency(without_cascade)

    split_talus = tuple(
        (
            item.model_copy(
                update={"expected_constant_values": ("loader_lynx_l120", "material_handling")}
            )
            if item.expected_constant_values == ("dozer_talus_d8", "material_handling")
            else item
        )
        for item in combined
    )
    with pytest.raises(ValueError, match="eligibility body is vacuous"):
        verify_expanded_claim_catalogue_consistency(split_talus)
