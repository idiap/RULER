# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic expansion of the grounded fleet dossier for KB-scale demonstrations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract
from ruler.io import stable_hash


class SyntheticClaimAnchor(StrictContract):
    """One exact reviewer-authored anchor generated with the synthetic prose."""

    claim_id: str
    predicate: Literal[
        "resource_provides", "activity_requires", "resource_eligible", "backup_required"
    ]
    exact_text: str = Field(min_length=1)
    expected_constant_values: tuple[str | int, ...] = ()
    expected_body_constant_values: tuple[tuple[str | int, ...], ...] = ()


class ExpandedSyntheticKBDossier(StrictContract):
    """Content-addressed expanded dossier and its deterministic coverage oracle."""

    profile: Literal["expanded"] = "expanded"
    seed: int
    source_text: str
    claims: tuple[SyntheticClaimAnchor, ...] = Field(min_length=1)
    expected_statement_count: int = Field(ge=1)
    content_sha256: str

    @model_validator(mode="after")
    def content_is_cross_bound(self) -> "ExpandedSyntheticKBDossier":
        if len({item.claim_id for item in self.claims}) != len(self.claims):
            raise ValueError("synthetic claim identifiers must be unique")
        for claim in self.claims:
            if self.source_text.count(claim.exact_text) != 1:
                raise ValueError(f"claim {claim.claim_id} must identify one exact source span")
        expected = stable_hash(self.model_dump(mode="json", exclude={"content_sha256"}))
        if self.content_sha256 != expected:
            raise ValueError("expanded synthetic KB digest mismatch")
        return self


_RESOURCES = (
    ("Granite", "excavator_granite_42t", "rock_excavation"),
    ("Moraine", "excavator_moraine_30t", "standard_excavation"),
    ("Talus", "dozer_talus_d8", "grading"),
    ("Nimbus", "crane_nimbus_90t", "lifting"),
    ("Torrent", "pump_torrent_12in", "dewatering"),
    ("Talus attachment", "dozer_talus_d8", "material_handling"),
    ("Ridge", "truck_ridge_adt", "haulage"),
    ("Cascade", "pump_cascade_8in", "dewatering"),
    ("Boreal", "drill_boreal_dth", "drilling"),
    ("Reserve", "rental_reserve_crane", "lifting"),
)

_WORK = (
    ("portal_cut", "rock_excavation", 30),
    ("foundation_pads", "standard_excavation", 20),
    ("drainage_wells", "dewatering", 16),
    ("crane_erection", "lifting", 10),
    ("access_road", "grading", 14),
    ("material_stockpile", "material_handling", 18),
    ("anchor_drilling", "drilling", 22),
    ("north_spoil_removal", "haulage", 32),
)

_BACKUPS = (
    ("portal_cut", "rock_excavation"),
    ("drainage_wells", "dewatering"),
    ("crane_erection", "lifting"),
    ("north_spoil_removal", "haulage"),
)


def generate_expanded_synthetic_kb(
    base_source: str,
    *,
    seed: int = 20260904,
) -> ExpandedSyntheticKBDossier:
    """Append a deterministic, realistic rule network to the compact base dossier."""

    claims: list[SyntheticClaimAnchor] = []
    capability_sentences: list[str] = []
    for label, resource_id, capability_id in _RESOURCES:
        sentence = (
            f"The additional synthetic resource {label} ({resource_id}) provides "
            f"{capability_id.replace('_', ' ')} capability ({capability_id})."
        )
        capability_sentences.append(sentence)
        claims.append(
            SyntheticClaimAnchor(
                claim_id=f"expanded_capability_{resource_id}_{capability_id}",
                predicate="resource_provides",
                exact_text=sentence,
                expected_constant_values=(resource_id, capability_id),
            )
        )

    requirement_sentences: list[str] = []
    eligibility_sentences: list[str] = []
    for work_id, capability_id, amount in _WORK:
        requirement = (
            f"The expanded work package {work_id.replace('_', ' ')} ({work_id}) requires "
            f"{amount} productive hours of {capability_id.replace('_', ' ')} capability "
            f"({capability_id})."
        )
        eligibility = (
            f"A resource is eligible for expanded work package {work_id.replace('_', ' ')} "
            f"({work_id}) if that resource provides {capability_id.replace('_', ' ')} "
            f"capability ({capability_id})."
        )
        requirement_sentences.append(requirement)
        eligibility_sentences.append(eligibility)
        claims.extend(
            (
                SyntheticClaimAnchor(
                    claim_id=f"expanded_requirement_{work_id}",
                    predicate="activity_requires",
                    exact_text=requirement,
                    expected_constant_values=(work_id, capability_id, amount),
                ),
                SyntheticClaimAnchor(
                    claim_id=f"expanded_eligibility_{work_id}",
                    predicate="resource_eligible",
                    exact_text=eligibility,
                    expected_constant_values=(work_id,),
                    expected_body_constant_values=((capability_id,),),
                ),
            )
        )

    backup_sentences: list[str] = []
    for work_id, capability_id in _BACKUPS:
        sentence = (
            f"The expanded work package {work_id.replace('_', ' ')} ({work_id}) requires "
            f"independently mobilizable backup for {capability_id.replace('_', ' ')} "
            f"capability ({capability_id})."
        )
        backup_sentences.append(sentence)
        claims.append(
            SyntheticClaimAnchor(
                claim_id=f"expanded_backup_{work_id}",
                predicate="backup_required",
                exact_text=sentence,
                expected_constant_values=(work_id, capability_id),
            )
        )

    conjunctive = (
        "A resource is eligible for the integrated portal finishing package "
        "(portal_finishing) if that resource provides grading capability (grading) and "
        "material handling capability (material_handling)."
    )
    negative = (
        "A resource is not eligible for the precision crane erection package "
        "(precision_crane_erection) if that resource provides haulage capability "
        "(haulage)."
    )
    claims.extend(
        (
            SyntheticClaimAnchor(
                claim_id="expanded_eligibility_portal_finishing_conjunction",
                predicate="resource_eligible",
                exact_text=conjunctive,
                expected_constant_values=("portal_finishing",),
                expected_body_constant_values=(
                    ("grading",),
                    ("material_handling",),
                ),
            ),
            SyntheticClaimAnchor(
                claim_id="expanded_ineligibility_precision_crane",
                predicate="resource_eligible",
                exact_text=negative,
                expected_constant_values=("precision_crane_erection",),
                expected_body_constant_values=(("haulage",),),
            ),
        )
    )

    expansion = "\n\n".join(
        (
            "## Expanded synthetic KB profile\n\n"
            "The following versioned records enlarge the candidate knowledge graph. They "
            "remain synthetic and do not extend the separately reviewed optimization projection.",
            "### Additional resource capability facts\n\n" + "\n\n".join(capability_sentences),
            "### Additional quantitative requirements\n\n" + "\n\n".join(requirement_sentences),
            "### Additional backup policies\n\n" + "\n\n".join(backup_sentences),
            "### Interacting eligibility rules\n\n"
            + "\n\n".join((*eligibility_sentences, conjunctive, negative)),
            "### Explicit projection limits\n\n"
            "Independently mobilizable, precision, certification, access-window, and "
            "weather-recourse qualifiers must remain visible in the semantic basis or "
            "uncertainties whenever the closed four-predicate vocabulary cannot encode them. "
            "Such loss remains activation-blocking and must never be converted into new predicates.",
        )
    )
    payload = {
        "profile": "expanded",
        "seed": seed,
        "source_text": base_source.rstrip() + "\n\n" + expansion + "\n",
        "claims": tuple(claims),
        "expected_statement_count": len(claims),
    }
    serialized = {
        **payload,
        "claims": [item.model_dump(mode="json") for item in claims],
    }
    return ExpandedSyntheticKBDossier(
        **payload,
        content_sha256=stable_hash(serialized),
    )


def build_expanded_claim_catalogue(
    dossier: ExpandedSyntheticKBDossier,
    base_claims: Iterable[SyntheticClaimAnchor],
) -> tuple[SyntheticClaimAnchor, ...]:
    """Combine compact and expanded exact claims with fail-closed identity checks."""

    combined = (*tuple(base_claims), *dossier.claims)
    identifiers = [item.claim_id for item in combined]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("combined synthetic claim identifiers must be unique")
    for claim in combined:
        if dossier.source_text.count(claim.exact_text) != 1:
            raise ValueError(f"combined claim {claim.claim_id} must identify one exact source span")
    verify_expanded_claim_catalogue_consistency(combined)
    return combined


def verify_expanded_claim_catalogue_consistency(
    claims: Iterable[SyntheticClaimAnchor],
) -> None:
    """Reject capability gaps, under-backed policies, and vacuous expanded rules."""

    catalogue = tuple(claims)
    providers: dict[str, set[str]] = {}
    for claim in catalogue:
        if claim.predicate != "resource_provides":
            continue
        resource_id, capability_id = claim.expected_constant_values
        providers.setdefault(str(capability_id), set()).add(str(resource_id))

    issues: list[str] = []
    for claim in catalogue:
        values = claim.expected_constant_values
        if claim.predicate == "activity_requires":
            capability_id = str(values[1])
            if not providers.get(capability_id):
                issues.append(f"{claim.claim_id}: no provider for {capability_id}")
        elif claim.predicate == "backup_required":
            capability_id = str(values[1])
            provider_count = len(providers.get(capability_id, set()))
            if provider_count < 2:
                issues.append(
                    f"{claim.claim_id}: backup for {capability_id} has "
                    f"{provider_count} distinct provider(s)"
                )
        elif (
            claim.predicate == "resource_eligible"
            and claim.claim_id.startswith("expanded_")
            and claim.expected_body_constant_values
        ):
            required_capabilities = tuple(
                str(value) for group in claim.expected_body_constant_values for value in group
            )
            matching = set(providers.get(required_capabilities[0], set()))
            for capability_id in required_capabilities[1:]:
                matching.intersection_update(providers.get(capability_id, set()))
            if not matching:
                issues.append(
                    f"{claim.claim_id}: eligibility body is vacuous for " f"{required_capabilities}"
                )

    if issues:
        raise ValueError("expanded synthetic KB is semantically inconsistent: " + "; ".join(issues))


__all__ = [
    "ExpandedSyntheticKBDossier",
    "SyntheticClaimAnchor",
    "build_expanded_claim_catalogue",
    "generate_expanded_synthetic_kb",
    "verify_expanded_claim_catalogue_consistency",
]
