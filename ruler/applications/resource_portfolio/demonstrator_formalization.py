# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Grounded natural-language intake for the resource-portfolio demonstrator.

This module joins the production Codex transport to RULER's source-locked
autoformalization boundary. Generative candidates remain immutable lineage while
semantic defects are recycled into repair prompts. Only a candidate that passes the
automatic executable acceptance gates can become the active logical KB; it never
becomes an ``ApprovedLinearRule`` or authorizes a portfolio-optimizer constraint.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256
from ruler.domains.construction_fleet import CONSTRUCTION_FLEET_DOMAIN_PACK
from ruler.applications.resource_portfolio.demonstrator_synthetic_kb import (
    SyntheticClaimAnchor,
    build_expanded_claim_catalogue,
    generate_expanded_synthetic_kb,
)
from ruler.io import read_yaml, stable_hash, write_yaml
from ruler.kb.autoformalization_refinement import (
    ContinuousRefinementRun,
    RefinementFinding,
    build_refinement_finding,
    run_continuous_autoformalization_refinement,
)
from ruler.kb.generative_autoformalization import (
    AutoformalizationCandidate,
    AutoformalizationRequest,
    CodexExecTransport,
    GenerativeTransport,
    predicate_registry_from_domain_pack,
)
from ruler.kb.partitioned_autoformalization import (
    PartitionClaim,
    PartitionedAutoformalizationError,
    PartitionedAutoformalizationRun,
    run_partitioned_autoformalization,
)
from ruler.paths import REPO_ROOT

DEMONSTRATOR_DOSSIER_PATH = (
    REPO_ROOT
    / "data"
    / "domains"
    / "construction_fleet"
    / "demonstrator"
    / "alpine_station_expansion_dossier.md"
)
DEMONSTRATOR_CLAIMS_PATH = DEMONSTRATOR_DOSSIER_PATH.with_name("claim_manifest.yaml")
DEMONSTRATOR_PREDICATES = (
    "resource_provides",
    "activity_requires",
    "resource_eligible",
    "backup_required",
)


class FormalizationCheck(StrictContract):
    """One artifact-level deterministic validation result."""

    check_id: str
    status: Literal["passed"] = "passed"
    evidence_digest: str
    summary: str

    @model_validator(mode="after")
    def digest_is_valid(self) -> "FormalizationCheck":
        validate_sha256(self.evidence_digest)
        return self


class ExpectedClaim(StrictContract):
    """Reviewer-authored lexical anchor; not a semantic-equivalence assertion."""

    claim_id: str
    predicate: str
    exact_text: str = Field(min_length=1)
    required: bool = True
    expected_constant_values: tuple[str | int, ...] = ()
    expected_body_constant_values: tuple[tuple[str | int, ...], ...] = ()


class PlanningInputProjection(StrictContract):
    """Separate reviewed route from prose to typed optimization inputs."""

    projection_id: str
    source_sections: tuple[str, ...] = Field(min_length=1)
    approved_input_files: tuple[str, ...] = Field(min_length=1)
    authority_status: Literal["reviewer_approved"] = "reviewer_approved"
    generated_candidate_dependency: Literal[False] = False
    note: str


class ClaimCoverage(StrictContract):
    """Deterministic predicate/span overlap, explicitly weaker than equivalence."""

    claim_id: str
    predicate: str
    candidate_element_ids: tuple[str, ...] = Field(min_length=1)
    check_kind: Literal["lexical_span_predicate_overlap"] = "lexical_span_predicate_overlap"
    semantic_equivalence_established: Literal[False] = False


class SolverAuthorityBoundary(StrictContract):
    """Explicit proof that generated logic has no optimization authority."""

    candidate_digest: str
    candidate_lifecycle: Literal["candidate_uncommitted"] = "candidate_uncommitted"
    activation_status: Literal["blocked"] = "blocked"
    solver_use_permitted: Literal[False] = False
    required_authority: Literal["separately_reviewed_approved_linear_rules"] = (
        "separately_reviewed_approved_linear_rules"
    )

    @model_validator(mode="after")
    def digest_is_valid(self) -> "SolverAuthorityBoundary":
        validate_sha256(self.candidate_digest)
        return self


class ExpandedRefinementRun(StrictContract):
    """Demonstrator receipt for four refined partitions and deterministic merge.

    The compatibility properties expose the same final-candidate surface used by the
    compact workflow while the complete partition and merge evidence stays available
    through ``partitioned_run``.
    """

    protocol_version: Literal["resource-portfolio-expanded-refinement/v1"] = (
        "resource-portfolio-expanded-refinement/v1"
    )
    request_sha256: str
    source_artifact_sha256: str
    expected_claim_count: Literal[43] = 43
    expected_partition_count: Literal[4] = 4
    partitioned_run: PartitionedAutoformalizationRun
    terminal_status: Literal["converged"] = "converged"
    final_candidate: AutoformalizationCandidate
    final_candidate_sha256: str
    candidate_lifecycle: Literal["candidate_uncommitted"] = "candidate_uncommitted"
    activation_status: Literal["blocked"] = "blocked"
    solver_use_permitted: Literal[False] = False
    run_sha256: str

    @property
    def partitions(self) -> tuple[object, ...]:
        """Expose partition receipts for report and caller compatibility."""

        return self.partitioned_run.partition_receipts

    @property
    def iterations(self) -> tuple[object, ...]:
        """Expose all child refinement iterations in deterministic partition order."""

        return tuple(
            iteration
            for receipt in self.partitioned_run.partition_receipts
            for iteration in receipt.refinement_run.iterations
        )

    @model_validator(mode="after")
    def receipt_is_cross_bound(self) -> "ExpandedRefinementRun":
        for value in (
            self.request_sha256,
            self.source_artifact_sha256,
            self.final_candidate_sha256,
            self.run_sha256,
        ):
            validate_sha256(value)
        if self.request_sha256 != self.partitioned_run.plan.request_sha256:
            raise ValueError("expanded refinement request digest mismatch")
        if self.source_artifact_sha256 != self.partitioned_run.plan.source_artifact_sha256:
            raise ValueError("expanded refinement source digest mismatch")
        if len(self.partitioned_run.plan.claim_ids) != self.expected_claim_count:
            raise ValueError("expanded refinement must cover exactly 43 claims")
        if len(self.partitioned_run.plan.partitions) != self.expected_partition_count:
            raise ValueError("expanded refinement must execute exactly four partitions")
        expected_families = {
            "resource_provides": (14,),
            "activity_requires": (11,),
            "resource_eligible": (13,),
            "backup_required": (5,),
        }
        observed_families: dict[str, list[int]] = {predicate: [] for predicate in expected_families}
        for partition in self.partitioned_run.plan.partitions:
            if partition.predicate not in observed_families:
                raise ValueError("expanded refinement contains an unexpected predicate family")
            observed_families[partition.predicate].append(len(partition.claim_ids))
        if {key: tuple(value) for key, value in observed_families.items()} != expected_families:
            raise ValueError("expanded refinement partition shape is not deterministic")
        candidate_digest = stable_hash(self.final_candidate.model_dump(mode="json"))
        if self.final_candidate_sha256 != candidate_digest:
            raise ValueError("expanded refinement final candidate digest mismatch")
        if self.final_candidate != self.partitioned_run.candidate:
            raise ValueError("expanded refinement does not expose the merged candidate")
        if self.final_candidate.lifecycle != self.candidate_lifecycle:
            raise ValueError("expanded refinement crossed the candidate lifecycle boundary")
        if self.final_candidate.projection.activation_status != self.activation_status:
            raise ValueError("expanded refinement crossed the activation boundary")
        expected = stable_hash(self.model_dump(mode="json", exclude={"run_sha256"}))
        if self.run_sha256 != expected:
            raise ValueError("expanded refinement run digest mismatch")
        return self


def _expanded_refinement_run(
    request: AutoformalizationRequest,
    run: PartitionedAutoformalizationRun,
) -> ExpandedRefinementRun:
    candidate_digest = stable_hash(run.candidate.model_dump(mode="json"))
    payload = {
        "protocol_version": "resource-portfolio-expanded-refinement/v1",
        "request_sha256": stable_hash(request.model_dump(mode="json")),
        "source_artifact_sha256": request.artifact_sha256,
        "expected_claim_count": 43,
        "expected_partition_count": 4,
        "partitioned_run": run,
        "terminal_status": "converged",
        "final_candidate": run.candidate,
        "final_candidate_sha256": candidate_digest,
        "candidate_lifecycle": "candidate_uncommitted",
        "activation_status": "blocked",
        "solver_use_permitted": False,
    }
    serialized = {
        key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        for key, value in payload.items()
    }
    return ExpandedRefinementRun(**payload, run_sha256=stable_hash(serialized))


class DemonstratorFormalizationRun(StrictContract):
    """Complete source, candidate, validation, and authority-boundary artifact."""

    schema_version: Literal["resource-portfolio-formalization-demo/v2"] = (
        "resource-portfolio-formalization-demo/v2"
    )
    kb_profile: Literal["compact", "expanded"] = "compact"
    dossier_path: str
    source_text: str
    source_digest: str
    request: AutoformalizationRequest
    candidate: AutoformalizationCandidate
    checks: tuple[FormalizationCheck, ...] = Field(min_length=5)
    expected_claim_coverage: tuple[ClaimCoverage, ...] = Field(min_length=1)
    planning_input_projection: PlanningInputProjection
    refinement: ContinuousRefinementRun | ExpandedRefinementRun
    solver_authority: SolverAuthorityBoundary
    run_digest: str

    @model_validator(mode="after")
    def cross_bind_artifacts(self) -> "DemonstratorFormalizationRun":
        for value in (self.source_digest, self.run_digest):
            validate_sha256(value)
        if self.source_digest != self.request.artifact_sha256:
            raise ValueError("source digest is not bound to the formalization request")
        if self.source_text != self.request.source_text:
            raise ValueError("source text differs from the submitted dossier")
        if self.kb_profile == "expanded" and not isinstance(self.refinement, ExpandedRefinementRun):
            raise ValueError("expanded profile requires the partitioned refinement receipt")
        if self.kb_profile == "compact" and isinstance(self.refinement, ExpandedRefinementRun):
            raise ValueError("compact profile cannot carry an expanded refinement receipt")
        if self.kb_profile == "expanded" and len(self.expected_claim_coverage) != 43:
            raise ValueError("expanded profile must retain coverage for all 43 claims")
        candidate_digest = stable_hash(self.candidate.model_dump(mode="json"))
        if candidate_digest != self.refinement.final_candidate_sha256:
            raise ValueError("refinement receipt is not bound to candidate")
        if self.refinement.terminal_status != "converged":
            raise ValueError("demonstrator requires a converged refinement run")
        if candidate_digest != self.solver_authority.candidate_digest:
            raise ValueError("solver boundary is not bound to candidate")
        expected = _formalization_run_digest(
            source_digest=self.source_digest,
            request=self.request,
            candidate=self.candidate,
            checks=self.checks,
            expected_claim_coverage=self.expected_claim_coverage,
            planning_input_projection=self.planning_input_projection,
            refinement=self.refinement,
            solver_authority=self.solver_authority,
        )
        if self.run_digest != expected:
            raise ValueError("formalization run digest mismatch")
        return self


class DemonstratorRefinementError(ValueError):
    """A fail-closed refinement run that callers can persist for diagnosis."""

    def __init__(
        self,
        refinement: ContinuousRefinementRun | ExpandedRefinementRun,
        request: AutoformalizationRequest,
        kb_profile: Literal["compact", "expanded"],
    ) -> None:
        self.refinement = refinement
        self.request = request
        self.kb_profile = kb_profile
        super().__init__(
            f"autoformalization refinement did not converge: {refinement.terminal_status}"
        )


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_demonstrator_dossier(path: Path = DEMONSTRATOR_DOSSIER_PATH) -> str:
    """Read the versioned synthetic dossier used by the demonstrator."""

    source = path.read_text(encoding="utf-8")
    if not source.strip():
        raise ValueError("demonstrator dossier is empty")
    return source


def load_claim_manifest(
    path: Path = DEMONSTRATOR_CLAIMS_PATH,
) -> tuple[tuple[ExpectedClaim, ...], PlanningInputProjection]:
    """Load reviewer-authored claim anchors and the separate planning projection."""

    payload = read_yaml(path)
    if not isinstance(payload, dict):
        raise ValueError("demonstrator claim manifest must be a mapping")
    claims = tuple(ExpectedClaim.model_validate(item) for item in payload["expected_claims"])
    projection = PlanningInputProjection.model_validate(payload["planning_input_projection"])
    if len({item.claim_id for item in claims}) != len(claims):
        raise ValueError("expected claim identifiers must be unique")
    return claims, projection


def build_demonstrator_request(
    *,
    source_text: str,
    request_id: str = "alpine-station-expansion-autoformalization-v1",
    source_version: str = "synthetic-dossier-2026-09-03",
    max_output_tokens: int = 12_000,
) -> AutoformalizationRequest:
    """Build the closed-vocabulary request consumed by the production generator."""

    registry = predicate_registry_from_domain_pack(
        CONSTRUCTION_FLEET_DOMAIN_PACK, DEMONSTRATOR_PREDICATES
    )
    return AutoformalizationRequest(
        request_id=request_id,
        artifact_id="synthetic:alpine-station-expansion-dossier",
        artifact_sha256=_sha256_text(source_text),
        source_text=source_text,
        source_version=source_version,
        context_id="alpine_station_expansion_earthworks",
        domain_id="construction_fleet",
        allowed_predicates=DEMONSTRATOR_PREDICATES,
        predicate_registry=registry,
        target_formalism="asp",
        max_output_tokens=max_output_tokens,
        guidance=(
            "Formalize only capability, requirement, eligibility, and backup statements that fit the reviewed predicate signatures.",
            "Treat costs, dates, locations, weather, maintenance, and commercial terms as context outside this closed predicate vocabulary; do not invent predicates for them.",
            "Use the exact snake_case identifiers printed in parentheses as entity constants.",
            "Keep quantities exactly as written and record any unsupported unit semantics as uncertainty.",
            "For independently mobilizable backup, keep backup_required/2 for the core claim, preserve the qualifier in the semantic element, and explicitly disclose that the closed predicate is an activation-blocked abstraction rather than silently dropping or omitting the qualifier.",
        ),
    )


def _validate_candidate(
    request: AutoformalizationRequest, candidate: AutoformalizationCandidate
) -> tuple[FormalizationCheck, ...]:
    """Repeat the material handoff checks and emit concise evidence receipts."""

    if candidate.request_id != request.request_id:
        raise ValueError("candidate request identity mismatch")
    if candidate.lifecycle != "candidate_uncommitted":
        raise ValueError("generated candidate crossed the review boundary")
    if candidate.projection.activation_status != "blocked":
        raise ValueError("generated candidate is not activation-blocked")

    candidate.semantic_basis.verify_source_artifacts(
        {request.artifact_id: request.source_text.encode("utf-8")}
    )
    source_span_payload = [item.model_dump(mode="json") for item in candidate.semantic_basis.spans]

    used_predicates = {element.predicate for element in candidate.semantic_basis.elements}
    if not used_predicates <= set(request.allowed_predicates):
        raise ValueError("candidate uses a predicate outside the closed registry")

    program_digest = candidate.logical_program.sha256()
    if candidate.projection.program_digest != program_digest:
        raise ValueError("projection is not bound to typed logical program")
    if candidate.receipt.source_artifact_sha256 != request.artifact_sha256:
        raise ValueError("generation receipt is not bound to dossier")
    if candidate.receipt.request_sha256 != stable_hash(request.model_dump(mode="json")):
        raise ValueError("generation receipt is not bound to request")

    checks = (
        (
            "source_spans_authenticated",
            source_span_payload,
            "Every cited span resolves to exact dossier bytes.",
        ),
        (
            "closed_predicate_registry",
            sorted(used_predicates),
            "Every semantic predicate belongs to the reviewed domain registry.",
        ),
        (
            "typed_ir_validated",
            candidate.logical_program.model_dump(mode="json"),
            "The candidate materializes as typed logical IR.",
        ),
        (
            "projection_cross_bound",
            candidate.projection.model_dump(mode="json"),
            "The semantic projection digest identifies the typed program.",
        ),
        (
            "activation_blocked",
            {
                "lifecycle": candidate.lifecycle,
                "activation_status": candidate.projection.activation_status,
            },
            "The candidate remains uncommitted and blocked from execution.",
        ),
        (
            "provider_receipt_bound",
            candidate.receipt.model_dump(mode="json"),
            "The provider or deterministic-merge receipt is bound to source, request, schema, prompt, and response.",
        ),
    )
    return tuple(
        FormalizationCheck(
            check_id=check_id,
            evidence_digest=stable_hash(payload),
            summary=summary,
        )
        for check_id, payload, summary in checks
    )


def _verify_expected_claim_coverage(
    request: AutoformalizationRequest,
    candidate: AutoformalizationCandidate,
    claims: tuple[ExpectedClaim, ...],
) -> tuple[ClaimCoverage, ...]:
    """Check source-span/predicate overlap without asserting semantic equivalence."""

    spans = {item.span_id: item for item in candidate.semantic_basis.spans}
    coverage: list[ClaimCoverage] = []
    for claim in claims:
        first = request.source_text.find(claim.exact_text)
        if first < 0:
            raise ValueError(f"expected claim {claim.claim_id} is absent from dossier")
        if request.source_text.find(claim.exact_text, first + 1) >= 0:
            raise ValueError(f"expected claim {claim.claim_id} is not a unique source anchor")
        end = first + len(claim.exact_text)
        element_ids = tuple(
            element.element_id
            for element in candidate.semantic_basis.elements
            if element.predicate == claim.predicate
            and any(
                spans[span_id].start_char == first
                and spans[span_id].end_char == end
                and spans[span_id].exact_text == claim.exact_text
                for span_id in element.source_span_ids
            )
        )
        if claim.required and not element_ids:
            raise ValueError(
                f"required expected claim {claim.claim_id} lacks predicate/span coverage"
            )
        if element_ids and claim.expected_constant_values:
            observed_argument_tuples: set[tuple[str | int | None, ...]] = set()
            for statement in candidate.logical_program.statements:
                if not set(statement.source_assertion_ids).intersection(element_ids):
                    continue
                atoms = [statement.head] if statement.head is not None else []
                pending = [statement.body] if statement.body is not None else []
                while pending:
                    expression = pending.pop()
                    if expression.atom is not None:
                        atoms.append(expression.atom)
                    pending.extend(expression.operands)
                for atom in atoms:
                    if atom.predicate != claim.predicate:
                        continue
                    observed_argument_tuples.add(
                        tuple(
                            value
                            for argument in atom.arguments
                            if (value := getattr(argument, "value", None)) is not None
                        )
                    )
            if claim.expected_constant_values not in observed_argument_tuples:
                raise ValueError(
                    f"expected claim {claim.claim_id} lacks its positional typed constants"
                )
        if element_ids and claim.expected_body_constant_values:
            observed_body_tuples: set[tuple[str | int, ...]] = set()
            for statement in candidate.logical_program.statements:
                if not set(statement.source_assertion_ids).intersection(element_ids):
                    continue
                pending = [statement.body] if statement.body is not None else []
                while pending:
                    expression = pending.pop()
                    if expression.atom is not None:
                        observed_body_tuples.add(
                            tuple(
                                value
                                for argument in expression.atom.arguments
                                if (value := getattr(argument, "value", None)) is not None
                            )
                        )
                    pending.extend(reversed(expression.operands))
            missing_body = set(claim.expected_body_constant_values) - observed_body_tuples
            if missing_body:
                raise ValueError(
                    f"expected claim {claim.claim_id} lacks body constants "
                    f"{sorted(missing_body)}"
                )
        if element_ids:
            coverage.append(
                ClaimCoverage(
                    claim_id=claim.claim_id,
                    predicate=claim.predicate,
                    candidate_element_ids=element_ids,
                )
            )
    return tuple(coverage)


def _formalization_run_digest(
    *,
    source_digest: str,
    request: AutoformalizationRequest,
    candidate: AutoformalizationCandidate,
    checks: tuple[FormalizationCheck, ...],
    expected_claim_coverage: tuple[ClaimCoverage, ...],
    planning_input_projection: PlanningInputProjection,
    refinement: ContinuousRefinementRun | ExpandedRefinementRun,
    solver_authority: SolverAuthorityBoundary,
) -> str:
    return stable_hash(
        {
            "source_digest": source_digest,
            "request": request.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "checks": [item.model_dump(mode="json") for item in checks],
            "expected_claim_coverage": [
                item.model_dump(mode="json") for item in expected_claim_coverage
            ],
            "planning_input_projection": planning_input_projection.model_dump(mode="json"),
            "refinement": refinement.model_dump(mode="json"),
            "solver_authority": solver_authority.model_dump(mode="json"),
        }
    )


def run_demonstrator_autoformalization(
    *,
    dossier_path: Path = DEMONSTRATOR_DOSSIER_PATH,
    transport: GenerativeTransport | None = None,
    model: str = "gpt-5.4",
    maximum_attempts: int | None = None,
    allow_non_codex_transport: bool = False,
    critic_transport: GenerativeTransport | None = None,
    kb_profile: Literal["compact", "expanded"] = "compact",
) -> DemonstratorFormalizationRun:
    """Refine continuously until every automatic executable KB gate passes.

    ``maximum_attempts`` bounds one refinement round, not the overall semantic repair
    process. A no-progress or iteration-limit result starts a fresh round carrying
    the typed findings forward. Provider failures remain explicit infrastructure
    failures because another semantic prompt cannot repair an unavailable provider.
    """

    iteration_limit = maximum_attempts or 3
    base_source = load_demonstrator_dossier(dossier_path)
    base_claims, planning_projection = load_claim_manifest()
    if kb_profile == "expanded":
        expanded = generate_expanded_synthetic_kb(base_source)
        source_text = expanded.source_text
        catalogue = build_expanded_claim_catalogue(
            expanded,
            (
                SyntheticClaimAnchor.model_validate(
                    dict(
                        claim_id=item.claim_id,
                        predicate=item.predicate,
                        exact_text=item.exact_text,
                        expected_constant_values=item.expected_constant_values,
                        expected_body_constant_values=item.expected_body_constant_values,
                    )
                )
                for item in base_claims
            ),
        )
        claims = tuple(
            ExpectedClaim(
                claim_id=item.claim_id,
                predicate=item.predicate,
                exact_text=item.exact_text,
                expected_constant_values=item.expected_constant_values,
                expected_body_constant_values=item.expected_body_constant_values,
            )
            for item in catalogue
        )
        request = build_demonstrator_request(
            source_text=source_text,
            request_id="alpine-station-expanded-autoformalization-v1",
            source_version="synthetic-expanded-dossier-2026-09-04",
            max_output_tokens=16_000,
        )
        dossier_identity = "generated:expanded-synthetic-kb:20260904"
    else:
        source_text = base_source
        claims = base_claims
        request = build_demonstrator_request(source_text=source_text)
        try:
            dossier_identity = dossier_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("demonstrator dossier must be stored inside the repository") from exc
    production_transport = transport or CodexExecTransport(model=model, timeout_seconds=600)
    if production_transport.provider != "codex-exec" and not allow_non_codex_transport:
        raise ValueError("demonstrator requires the real codex-exec transport")
    independent_critic = critic_transport or production_transport
    if independent_critic.provider != "codex-exec" and not allow_non_codex_transport:
        raise ValueError("demonstrator requires the real codex-exec critic transport")

    # Imported lazily because the acceptance module consumes the completed run model
    # when it builds a release, while this boundary needs only its candidate critic.
    from ruler.applications.resource_portfolio.demonstrator_approved_kb import (
        candidate_acceptance_findings,
    )

    def claim_critic(item: AutoformalizationCandidate) -> tuple[RefinementFinding, ...]:
        findings: tuple[RefinementFinding, ...] = ()
        try:
            _verify_expected_claim_coverage(request, item, claims)
        except ValueError as exc:
            summary = " ".join(str(exc).split())
            findings = (
                build_refinement_finding(
                    origin="deterministic",
                    stage="coverage",
                    severity="blocker",
                    code="reviewed_claim_coverage_failed",
                    summary=summary,
                    repair_instruction=(
                        "Restore the missing exact source-span and positional typed-constant "
                        "coverage without adding predicates outside the reviewed registry."
                    ),
                    evidence={
                        "request_sha256": stable_hash(request.model_dump(mode="json")),
                        "candidate_sha256": stable_hash(item.model_dump(mode="json")),
                        "failure": summary,
                    },
                ),
            )
        return findings + candidate_acceptance_findings(request, item)

    def continue_after_semantic_findings(
        current_request: AutoformalizationRequest,
        refinement_run: ContinuousRefinementRun,
        round_number: int,
    ) -> AutoformalizationRequest:
        final_iteration = refinement_run.iterations[-1]
        findings = final_iteration.deterministic_findings + final_iteration.generative_findings
        repairs = tuple(
            f"Automatic refinement finding {item.code}: {item.repair_instruction}"
            for item in findings
        ) or (
            "Regenerate the complete formalization with a materially different "
            "logical representation that satisfies every deterministic gate.",
        )
        return current_request.model_copy(
            update={
                "guidance": current_request.guidance
                + (f"Continuous semantic refinement round {round_number + 1}.",)
                + repairs
            }
        )

    refinement_round = 1
    while True:
        if kb_profile == "expanded":
            partition_claims = tuple(
                PartitionClaim(
                    claim_id=item.claim_id,
                    predicate=item.predicate,
                    exact_text=item.exact_text,
                    expected_constant_values=item.expected_constant_values,
                    expected_body_constant_values=item.expected_body_constant_values,
                )
                for item in claims
            )
            try:
                partitioned = run_partitioned_autoformalization(
                    request,
                    partition_claims,
                    production_transport,
                    independent_critic,
                    max_claims_per_partition=16,
                    maximum_iterations=iteration_limit,
                    max_workers=2,
                    additional_deterministic_critic=candidate_acceptance_findings,
                )
            except PartitionedAutoformalizationError as exc:
                if exc.refinement_run is None:
                    raise ValueError(f"partitioned autoformalization failed: {exc}") from exc
                if exc.refinement_run.terminal_status == "provider_error":
                    raise DemonstratorRefinementError(
                        exc.refinement_run, request, kb_profile
                    ) from exc
                request = continue_after_semantic_findings(
                    request, exc.refinement_run, refinement_round
                )
                refinement_round += 1
                continue
            refinement = _expanded_refinement_run(request, partitioned)
            global_findings = candidate_acceptance_findings(request, partitioned.candidate)
            if global_findings:
                # A merged-only defect is expressed as new source-locked guidance and
                # the complete partition set is regenerated. Partial promotion is
                # never exposed.
                request = request.model_copy(
                    update={
                        "guidance": request.guidance
                        + (f"Continuous semantic refinement round {refinement_round + 1}.",)
                        + tuple(
                            f"Automatic merged-KB finding {item.code}: "
                            f"{item.repair_instruction}"
                            for item in global_findings
                        )
                    }
                )
                refinement_round += 1
                continue
        else:
            compact_refinement = run_continuous_autoformalization_refinement(
                request,
                production_transport,
                deterministic_critic=claim_critic,
                critic_transport=independent_critic,
                maximum_iterations=iteration_limit,
            )
            if compact_refinement.terminal_status == "provider_error":
                raise DemonstratorRefinementError(compact_refinement, request, kb_profile)
            if (
                compact_refinement.terminal_status != "converged"
                or compact_refinement.final_candidate is None
            ):
                request = continue_after_semantic_findings(
                    request, compact_refinement, refinement_round
                )
                refinement_round += 1
                continue
            refinement = compact_refinement
        break

    candidate = refinement.final_candidate
    if candidate is None:
        raise ValueError("converged refinement did not expose a final candidate")
    checks = _validate_candidate(request, candidate)
    expected_claim_coverage = _verify_expected_claim_coverage(request, candidate, claims)
    if kb_profile == "compact" and candidate.receipt.provider != production_transport.provider:
        raise ValueError("candidate provider receipt does not identify invoked transport")
    candidate_digest = stable_hash(candidate.model_dump(mode="json"))
    solver_authority = SolverAuthorityBoundary(candidate_digest=candidate_digest)
    run_digest = _formalization_run_digest(
        source_digest=request.artifact_sha256,
        request=request,
        candidate=candidate,
        checks=checks,
        expected_claim_coverage=expected_claim_coverage,
        planning_input_projection=planning_projection,
        refinement=refinement,
        solver_authority=solver_authority,
    )
    return DemonstratorFormalizationRun(
        kb_profile=kb_profile,
        dossier_path=dossier_identity,
        source_text=source_text,
        source_digest=request.artifact_sha256,
        request=request,
        candidate=candidate,
        checks=checks,
        expected_claim_coverage=expected_claim_coverage,
        planning_input_projection=planning_projection,
        refinement=refinement,
        solver_authority=solver_authority,
        run_digest=run_digest,
    )


def write_formalization_run(run: DemonstratorFormalizationRun, output_path: Path) -> None:
    """Persist the fully cross-bound artifact for downstream reporting."""

    write_yaml(output_path, run.model_dump(mode="json"))


__all__ = [
    "DEMONSTRATOR_DOSSIER_PATH",
    "DEMONSTRATOR_CLAIMS_PATH",
    "DEMONSTRATOR_PREDICATES",
    "DemonstratorFormalizationRun",
    "DemonstratorRefinementError",
    "ExpandedRefinementRun",
    "FormalizationCheck",
    "ExpectedClaim",
    "ClaimCoverage",
    "PlanningInputProjection",
    "ContinuousRefinementRun",
    "SolverAuthorityBoundary",
    "build_demonstrator_request",
    "load_demonstrator_dossier",
    "load_claim_manifest",
    "run_demonstrator_autoformalization",
    "write_formalization_run",
]
