# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""KB statistics count canonical and derived layers without conflating them."""

from pathlib import Path

from ruler.io import read_yaml
from ruler.kb.statistics import (
    build_kb_statistics,
    validate_kb_statistics,
    write_kb_statistics,
)


def test_statistics_expose_canonical_logic_commentary_and_document_layers() -> None:
    statistics = build_kb_statistics()

    assert statistics["canonical_kb"]["policy_clauses"] == 0
    assert statistics["canonical_kb"]["policy_rules"] == 0
    assert statistics["compiled_logic"]["unique_facts_across_targets"] >= 0
    assert statistics["compiled_logic"]["unique_rules_across_targets"] > 0
    assert (
        statistics["compiled_logic"]["nl_fr_comments"]
        == statistics["compiled_logic"]["nl_en_comments"]
    )
    onboarding = statistics["released_onboarding"]
    assert onboarding["features"] == sum(item["features"] for item in onboarding["batches"])
    assert onboarding["clauses"] == sum(item["clauses"] for item in onboarding["batches"])
    assert onboarding["rules"] == sum(item["rules"] for item in onboarding["batches"])
    assert onboarding["compiled_facts"] == sum(
        item["compiled_facts"] for item in onboarding["batches"]
    )
    assert onboarding["compiled_rules"] == sum(
        item["compiled_rules"] for item in onboarding["batches"]
    )
    assert onboarding["batches"] == []
    assert statistics["documents"]["unique_documents"] > 0


def test_written_statistics_are_hash_bound_and_recomputable(tmp_path: Path) -> None:
    artifacts = write_kb_statistics(tmp_path)
    payload = read_yaml(artifacts["yaml"])

    assert payload["snapshot_hash"].startswith("sha256:")
    assert (
        artifacts["markdown"].read_text(encoding="utf-8").startswith("# KB and document statistics")
    )
    assert validate_kb_statistics(artifacts["yaml"])
