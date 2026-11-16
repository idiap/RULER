# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Repository-wide formalization inventory and honest coverage artifacts.

The builder assigns every published assertion to a provider/product-family wave while
leaving its reviewed formalization state untouched. It never promotes source records,
controlled text, or metadata projections into solver truth.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ruler.io import stable_hash, write_text, write_yaml
from ruler.kb.formalization import (
    FormalizationInventory,
    FormalizationState,
    build_coverage_report,
    load_active_onboarding_inventory,
)
from ruler.kb.formalization_wave import REQUIRED_SKILL_SEQUENCE
from ruler.paths import BUILD_DIR

FORMALIZATION_COVERAGE_DIR = BUILD_DIR / "formalization_coverage"


def build_formalization_wave_plan(
    inventory: FormalizationInventory,
) -> dict[str, Any]:
    """Group the complete inventory into small skill-governed provider/family waves."""
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in inventory.items:
        grouped[(item.provider, item.product_family)].append(item.assertion_id)

    waves: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for (provider, family), assertion_ids in sorted(grouped.items()):
        ids = sorted(assertion_ids)
        duplicate = assigned.intersection(ids)
        if duplicate:
            raise ValueError(f"assertions assigned to multiple waves: {sorted(duplicate)}")
        assigned.update(ids)
        slug = _slug(f"{provider}-{family}")
        waves.append(
            {
                "wave_id": f"formalization-wave:{slug}",
                "provider": provider,
                "product_family": family,
                "assertion_count": len(ids),
                "assertion_ids": ids,
                "required_skill_sequence": list(REQUIRED_SKILL_SEQUENCE),
                "owning_skill": "policy-autoformalization-orchestrator",
                "review_skill": "policy-source-formalization-drift-guard",
                "publication_skill": "formalized-kb-curator",
                "promotion_policy": "candidate_only_until_all_required_gates_pass",
            }
        )

    expected = {item.assertion_id for item in inventory.items}
    if assigned != expected:
        missing = sorted(expected - assigned)
        raise ValueError(f"wave plan omits assertions: {missing[:10]}")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "inventory_id": inventory.inventory_id,
        "assertion_count": len(expected),
        "wave_count": len(waves),
        "required_skill_sequence": list(REQUIRED_SKILL_SEQUENCE),
        "waves": waves,
    }
    payload["audit_hash"] = stable_hash(payload)
    return payload


def build_formalization_coverage_artifacts() -> dict[str, Any]:
    """Build inventory, reconciled metrics, wave ownership, and completion status."""
    inventory = load_active_onboarding_inventory()
    coverage = build_coverage_report(inventory)
    wave_plan = build_formalization_wave_plan(inventory)
    terminal = sum(
        item.state
        in {
            FormalizationState.VALIDATED,
            FormalizationState.REJECTED,
            FormalizationState.NON_FORMALIZABLE,
        }
        for item in inventory.items
    )
    completion = {
        "inventory_closed": terminal == len(inventory.items),
        "terminal_assertions": terminal,
        "unresolved_assertions": coverage.totals.unresolved_units,
        "formalizable_validated": (
            coverage.totals.validated_assertions == coverage.totals.formalizable_assertions
        ),
        "promotion_blocked": not inventory.items or coverage.totals.unresolved_units > 0,
        "reason": (
            "no assertions configured"
            if not inventory.items
            else "all formalizable assertions validated"
            if coverage.totals.unresolved_units == 0
            else "reviewed logical overlays and behavioral evidence are still required"
        ),
    }
    return {
        "inventory": inventory.model_dump(mode="json"),
        "coverage": coverage.model_dump(mode="json"),
        "wave_plan": wave_plan,
        "completion": completion,
    }


def write_formalization_coverage_artifacts(
    output_dir: Path = FORMALIZATION_COVERAGE_DIR,
) -> dict[str, Path]:
    """Write machine-readable inventory plus a compact honest coverage report."""
    artifacts = build_formalization_coverage_artifacts()
    inventory_path = output_dir / "inventory.yaml"
    coverage_path = output_dir / "coverage.yaml"
    wave_plan_path = output_dir / "wave_plan.yaml"
    report_path = output_dir / "coverage.md"
    write_yaml(inventory_path, artifacts["inventory"])
    write_yaml(
        coverage_path, {"coverage": artifacts["coverage"], "completion": artifacts["completion"]}
    )
    write_yaml(wave_plan_path, artifacts["wave_plan"])
    totals = artifacts["coverage"]["totals"]
    completion = artifacts["completion"]
    write_text(
        report_path,
        "# Formalization coverage\n\n"
        f"- Published assertions: {totals['source_assertions']}\n"
        f"- Formalizable assertions: {totals['formalizable_assertions']}\n"
        f"- Validated assertions: {totals['validated_assertions']}\n"
        f"- Unresolved assertions: {totals['unresolved_units']}\n"
        f"- Provider/product-family waves: {artifacts['wave_plan']['wave_count']}\n"
        f"- Inventory closed: {str(completion['inventory_closed']).lower()}\n"
        f"- Promotion blocked: {str(completion['promotion_blocked']).lower()}\n\n"
        "Source approval is not logical formalization. Unresolved records remain outside "
        "solver truth until their skill-governed wave passes review and behavioral gates.\n",
    )
    return {
        "inventory": inventory_path,
        "coverage": coverage_path,
        "wave_plan": wave_plan_path,
        "report": report_path,
    }


def validate_formalization_coverage() -> list[str]:
    """Validate complete accounting without pretending unresolved work is complete."""
    artifacts = build_formalization_coverage_artifacts()
    inventory = artifacts["inventory"]
    coverage = artifacts["coverage"]
    wave_plan = artifacts["wave_plan"]
    assertion_ids = {item["assertion_id"] for item in inventory["items"]}
    planned_ids = {
        assertion_id for wave in wave_plan["waves"] for assertion_id in wave["assertion_ids"]
    }
    if len(assertion_ids) != inventory["expected_assertion_count"]:
        raise ValueError("formalization inventory total does not reconcile")
    if assertion_ids != planned_ids:
        raise ValueError("formalization wave plan does not cover the complete inventory")
    if any(
        item.get("metadata_projection") and item["state"] != "source_only"
        for item in inventory["items"]
    ):
        raise ValueError("metadata projections are counted as formalized logic")
    if coverage["totals"]["source_assertions"] != len(assertion_ids):
        raise ValueError("coverage denominator differs from inventory")
    expected_skills = list(REQUIRED_SKILL_SEQUENCE)
    if any(wave["required_skill_sequence"] != expected_skills for wave in wave_plan["waves"]):
        raise ValueError("a formalization wave skips or reorders canonical skills")
    return [
        f"assertions={len(assertion_ids)}",
        f"waves={wave_plan['wave_count']}",
        f"validated={coverage['totals']['validated_assertions']}",
        f"unresolved={coverage['totals']['unresolved_units']}",
        "metadata_projections=excluded",
        "skills=reused",
    ]


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "unknown"
