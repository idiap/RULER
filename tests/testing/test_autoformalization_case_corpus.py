# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Integrity and leakage tests for realistic autoformalization cases."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from ruler.testing.autoformalization_cases import (
    build_producer_input,
    load_autoformalization_case_catalogue,
    load_autoformalization_oracle,
    stage_producer_input,
)


def test_realistic_case_corpus_is_hash_locked_and_style_diverse() -> None:
    catalogue = load_autoformalization_case_catalogue()

    assert catalogue.fixture_id == "realistic-autoformalization-cases-v1"
    assert {case.domain_id for case in catalogue.cases} == {
        "legal",
        "regulatory",
        "spending",
    }
    assert len({case.source_style for case in catalogue.cases}) == len(catalogue.cases) == 4
    assert all(
        set(case.required_behavioral_perspectives)
        == {"positive", "negative", "counterfactual", "exception", "boundary", "conflict"}
        for case in catalogue.cases
    )


def test_producer_payload_contains_exact_sources_but_no_hidden_oracle() -> None:
    catalogue = load_autoformalization_case_catalogue()

    for case in catalogue.cases:
        oracle = load_autoformalization_oracle(case)
        payload = build_producer_input(case)
        serialized = json.dumps(payload, ensure_ascii=False)

        assert set(payload) == set(catalogue.producer_input_policy.include_fields)
        assert "oracle" not in payload
        assert "expected_disposition" not in serialized
        assert case.oracle.path not in serialized
        assert all(source["content"] for source in payload["sources"])
        assert oracle.case_id == case.case_id


def test_oracles_cover_fail_closed_semantics_and_behavior() -> None:
    catalogue = load_autoformalization_case_catalogue()
    oracles = [load_autoformalization_oracle(case) for case in catalogue.cases]
    covered_mutations = {item for oracle in oracles for item in oracle.required_mutations}

    assert {
        "actor",
        "modality",
        "polarity",
        "connective",
        "exception",
        "quantity",
        "temporal",
        "coreference",
        "precedence",
        "source_link",
    } <= covered_mutations
    ambiguity = next(item for item in oracles if item.case_id == "coreference_open_texture")
    assert ambiguity.expected_disposition == "blocked_ambiguity"
    assert any("unresolved" in item for item in ambiguity.semantic_invariants)
    assert all(len(oracle.behavioral_cases) >= 4 for oracle in oracles)


def test_staged_producer_directory_is_read_only_and_contains_no_oracle_signal() -> None:
    catalogue = load_autoformalization_case_catalogue()

    for case in catalogue.cases:
        oracle = load_autoformalization_oracle(case)
        with stage_producer_input(case) as staged:
            stage_mode = stat.S_IMODE(staged.root.stat().st_mode)
            payload_mode = stat.S_IMODE(staged.payload_path.stat().st_mode)
            serialized = staged.payload_path.read_text(encoding="utf-8")
            lowered = serialized.casefold()
            public_payload = json.dumps(build_producer_input(case), ensure_ascii=False).casefold()

            assert stage_mode == 0o555
            assert payload_mode == 0o444
            assert tuple(staged.root.iterdir()) == (staged.payload_path,)
            assert case.oracle.path not in serialized
            assert case.oracle.sha256 not in serialized
            assert oracle.expected_disposition not in serialized
            assert json.loads(serialized) == build_producer_input(case)
            for hidden in (
                *oracle.semantic_invariants,
                *oracle.forbidden_claims,
                *(item["expected"] for item in oracle.behavioral_cases),
            ):
                # An oracle may intentionally use a public vocabulary symbol as its
                # expected label.  Such a token is not leakage; only hidden material
                # absent from the allowlisted payload must be absent from the stage.
                if hidden.casefold() not in public_payload:
                    assert hidden.casefold() not in lowered


def test_source_digest_drift_fails_before_a_producer_can_run(tmp_path: Path) -> None:
    catalogue = load_autoformalization_case_catalogue()
    case = catalogue.cases[0]
    source = case.sources[0]
    copied = tmp_path / "changed.txt"
    copied.write_text("substituted source bytes", encoding="utf-8")
    changed_source = source.model_copy(update={"path": copied.name})
    changed_case = case.model_copy(update={"sources": (changed_source,)})

    with pytest.raises(ValueError, match="source digest mismatch"):
        build_producer_input(changed_case, root=tmp_path)


def test_fixture_paths_cannot_escape_the_declared_root(tmp_path: Path) -> None:
    catalogue = load_autoformalization_case_catalogue()
    case = catalogue.cases[0]
    escaped = case.sources[0].model_copy(update={"path": "../outside.txt"})
    escaped_case = case.model_copy(update={"sources": (escaped,)})

    with pytest.raises(ValueError, match="escapes repository root"):
        build_producer_input(escaped_case, root=tmp_path)
