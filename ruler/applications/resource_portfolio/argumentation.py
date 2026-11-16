# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Replayable proof certificates for resource-portfolio decision arguments.

This module establishes the formal facts from which an explanation may be rendered.
It does not generate prose.  In particular, it keeps an alternative under the same
reviewed model distinct from a sensitivity run that changes policy assumptions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from ruler.applications.resource_portfolio.optimization import VerifiedPlan
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    CounterfactualRun,
    apply_counterfactual,
)
from ruler.contracts.common import StrictContract
from ruler.io import stable_hash
from ruler.optimization.contracts import (
    LinearConstraint,
    LinearExpression,
    LinearTerm,
    OptimizationProblem,
    OptimizationResult,
    OptimizationStatus,
)
from ruler.optimization.highs import solve_highs
from ruler.optimization.verification import VerificationReport, verify_result

DecisionClass = Literal["unique_feasible", "cost_preferred", "multiple_optima"]
ProbeKind = Literal["same_model_nogood", "variable_opposite", "constraint_ablation"]
ConstraintRole = Literal[
    "cost_decisive",
    "optimal_set_restricting",
    "redundant_at_optimum",
    "unresolved",
]


class ProbeCertificate(StrictContract):
    """One real HiGHS probe over a deterministic transformation of the base model."""

    probe_id: str
    kind: ProbeKind
    reference_model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    probe_model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result: OptimizationResult
    verification: VerificationReport | None = None

    @model_validator(mode="after")
    def result_is_bound(self) -> "ProbeCertificate":
        if self.result.model_digest != self.probe_model_digest:
            raise ValueError("probe result is not bound to its probe model")
        feasible = self.result.status in {
            OptimizationStatus.OPTIMAL,
            OptimizationStatus.FEASIBLE,
        }
        if feasible != (self.verification is not None):
            raise ValueError("feasible probe results require independent verification")
        if self.verification is not None and (
            not self.verification.verified
            or self.verification.model_digest != self.probe_model_digest
            or self.verification.result_semantic_digest != self.result.semantic_digest
        ):
            raise ValueError("probe verification does not authenticate its result")
        return self


class SameModelAlternativeCertificate(StrictContract):
    """The next optimum after excluding exactly the selected binary assignment."""

    method: Literal["binary_nogood_resolve/v1"] = "binary_nogood_resolve/v1"
    decision_class: DecisionClass
    probe: ProbeCertificate
    alternative_assignment: dict[str, Decimal] | None
    alternative_objective_value: Decimal | None
    objective_gap: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def classification_matches_probe(self) -> "SameModelAlternativeCertificate":
        if self.probe.kind != "same_model_nogood":
            raise ValueError("same-model alternative requires a no-good probe")
        if self.decision_class == "unique_feasible":
            if self.probe.result.status != OptimizationStatus.INFEASIBLE:
                raise ValueError("unique_feasible requires an infeasible no-good probe")
            if any(
                value is not None
                for value in (
                    self.alternative_assignment,
                    self.alternative_objective_value,
                    self.objective_gap,
                )
            ):
                raise ValueError("unique_feasible cannot contain an alternative")
        else:
            if self.probe.result.status != OptimizationStatus.OPTIMAL:
                raise ValueError("an alternative classification requires an optimal probe")
            if (
                self.alternative_assignment is None
                or self.alternative_objective_value is None
                or self.objective_gap is None
            ):
                raise ValueError("alternative result and objective gap are required")
            if self.decision_class == "cost_preferred" and self.objective_gap <= 0:
                raise ValueError("cost_preferred requires a strictly positive objective gap")
            if self.decision_class == "multiple_optima" and self.objective_gap != 0:
                raise ValueError("multiple_optima requires a zero objective gap")
        return self


class VariableForcednessCertificate(StrictContract):
    variable_id: str
    selected_value: Decimal
    tested_value: Decimal
    feasibility_forced: bool
    probe: ProbeCertificate

    @model_validator(mode="after")
    def forcedness_matches_probe(self) -> "VariableForcednessCertificate":
        if self.probe.kind != "variable_opposite":
            raise ValueError("variable forcedness requires an opposite-value probe")
        if self.probe.result.status not in {
            OptimizationStatus.OPTIMAL,
            OptimizationStatus.INFEASIBLE,
        }:
            raise ValueError("variable forcedness requires an optimal or infeasible probe")
        expected = self.probe.result.status == OptimizationStatus.INFEASIBLE
        if self.feasibility_forced != expected:
            raise ValueError("variable forcedness contradicts its probe")
        return self


class ConstraintRoleCertificate(StrictContract):
    constraint_id: str
    binding_at_selected_point: bool
    role: ConstraintRole
    assignment_changed: bool
    objective_delta: Decimal | None
    probe: ProbeCertificate

    @model_validator(mode="after")
    def role_matches_probe(self) -> "ConstraintRoleCertificate":
        if self.probe.kind != "constraint_ablation":
            raise ValueError("constraint role requires an ablation probe")
        if self.role == "cost_decisive" and (
            not self.assignment_changed or self.objective_delta is None or self.objective_delta >= 0
        ):
            raise ValueError("cost_decisive requires a cheaper changed ablation optimum")
        if self.role == "optimal_set_restricting" and (
            not self.assignment_changed or self.objective_delta != 0
        ):
            raise ValueError("optimal_set_restricting requires a tied changed optimum")
        if self.role == "redundant_at_optimum" and (
            self.assignment_changed or self.objective_delta != 0
        ):
            raise ValueError("redundant_at_optimum requires an unchanged optimum")
        if self.role == "unresolved" and self.objective_delta is not None:
            raise ValueError("unresolved constraint roles cannot assert an objective delta")
        return self


class PolicySensitivityCertificate(StrictContract):
    """A changed-policy comparison, explicitly not a same-model alternative."""

    comparison_kind: Literal["policy_sensitivity"] = "policy_sensitivity"
    changes: tuple[CounterfactualChange, ...] = Field(min_length=1)
    run: CounterfactualRun
    verification: VerificationReport
    changed_assignments: dict[str, tuple[Decimal, Decimal]]
    objective_delta: Decimal
    objective_unit: str


class AuthorityBoundaryCertificate(StrictContract):
    """Keep generated knowledge separate from the reviewed optimization model."""

    candidate_kb_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_kb_solver_authority: Literal[False] = False
    reviewed_model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewed_model_solver_authority: Literal[True] = True
    reviewed_constraint_ids: tuple[str, ...]
    reviewed_origin_refs: tuple[str, ...]


class DecisionArgumentCertificate(StrictContract):
    """Complete formal substrate for a logically valid decision argument."""

    schema_version: Literal["resource-decision-argument-certificate/v1"] = (
        "resource-decision-argument-certificate/v1"
    )
    problem_id: str
    decision_class: DecisionClass
    base_model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    base_result_semantic_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    objective_id: str
    objective_sense: Literal["minimize", "maximize"]
    objective_unit: str
    selected_assignment: dict[str, Decimal]
    selected_objective_value: Decimal
    same_model_alternative: SameModelAlternativeCertificate
    variable_forcedness: tuple[VariableForcednessCertificate, ...]
    constraint_roles: tuple[ConstraintRoleCertificate, ...]
    policy_sensitivity: PolicySensitivityCertificate | None
    authority: AuthorityBoundaryCertificate
    certificate_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def content_digest_closes(self) -> "DecisionArgumentCertificate":
        expected = stable_hash(self.model_dump(mode="json", exclude={"certificate_sha256"}))
        if self.certificate_sha256 != expected:
            raise ValueError("certificate_sha256 does not authenticate the certificate")
        if self.decision_class != self.same_model_alternative.decision_class:
            raise ValueError("decision class contradicts the same-model probe")
        return self


def build_decision_argument_certificate(
    problem: OptimizationProblem,
    plan: VerifiedPlan,
    *,
    policy_counterfactual: CounterfactualRun | None = None,
    policy_changes: tuple[CounterfactualChange, ...] = (),
    candidate_kb_digest: str | None = None,
    seed: int = 0,
) -> DecisionArgumentCertificate:
    """Build a certificate using real deterministic HiGHS probes.

    Version 1 deliberately supports binary, single-objective decision models.  It
    fails closed for domains where a linear no-good cut cannot prove the next point.
    """

    objective = _validate_base(problem, plan)
    selected = dict(plan.result.assignments)
    base_value = plan.verification.objective_values[objective.objective_id]

    nogood_problem = _with_constraint(problem, _binary_nogood(problem, selected))
    nogood_probe = _solve_probe(
        nogood_problem,
        probe_id="same-model-next-best",
        kind="same_model_nogood",
        reference_model_digest=problem.digest,
        seed=seed,
    )
    alternative = _classify_alternative(
        nogood_probe,
        base_value=base_value,
        objective_id=objective.objective_id,
        objective_sense=objective.sense,
    )

    forcedness = tuple(
        _variable_forcedness(problem, variable.variable_id, selected[variable.variable_id], seed)
        for variable in problem.variables
    )
    roles = tuple(
        _constraint_role(
            problem,
            plan,
            constraint.constraint_id,
            base_value,
            objective.objective_id,
            objective.sense,
            seed,
        )
        for constraint in problem.constraints
    )
    sensitivity = _policy_sensitivity(
        problem,
        plan,
        policy_counterfactual,
        policy_changes,
        objective.objective_id,
        objective.unit,
    )
    origins = tuple(sorted({origin for item in problem.constraints for origin in item.origin_refs}))
    authority = AuthorityBoundaryCertificate(
        candidate_kb_digest=candidate_kb_digest,
        reviewed_model_digest=problem.digest,
        reviewed_constraint_ids=tuple(item.constraint_id for item in problem.constraints),
        reviewed_origin_refs=origins,
    )
    payload = {
        "problem_id": problem.problem_id,
        "decision_class": alternative.decision_class,
        "base_model_digest": problem.digest,
        "base_result_semantic_digest": plan.result.semantic_digest,
        "objective_id": objective.objective_id,
        "objective_sense": objective.sense,
        "objective_unit": objective.unit,
        "selected_assignment": selected,
        "selected_objective_value": base_value,
        "same_model_alternative": alternative,
        "variable_forcedness": forcedness,
        "constraint_roles": roles,
        "policy_sensitivity": sensitivity,
        "authority": authority,
    }
    unsigned = DecisionArgumentCertificate.model_construct(
        **payload,
        certificate_sha256="sha256:" + "0" * 64,
    )
    certificate = DecisionArgumentCertificate(
        **payload,
        certificate_sha256=stable_hash(
            unsigned.model_dump(mode="json", exclude={"certificate_sha256"})
        ),
    )
    validate_decision_argument_certificate(problem, plan, certificate, replay_solves=False)
    return certificate


def validate_decision_argument_certificate(
    problem: OptimizationProblem,
    plan: VerifiedPlan,
    certificate: DecisionArgumentCertificate,
    *,
    replay_solves: bool = True,
) -> None:
    """Replay deterministic transformations, arithmetic, and optionally every solve."""

    expected_digest = stable_hash(
        certificate.model_dump(mode="json", exclude={"certificate_sha256"})
    )
    if certificate.certificate_sha256 != expected_digest:
        raise ValueError("certificate_sha256 does not authenticate the certificate")
    objective = _validate_base(problem, plan)
    base_value = plan.verification.objective_values[objective.objective_id]
    if (
        certificate.problem_id != problem.problem_id
        or certificate.base_model_digest != problem.digest
        or certificate.base_result_semantic_digest != plan.result.semantic_digest
        or certificate.selected_assignment != plan.result.assignments
        or certificate.selected_objective_value != base_value
        or certificate.objective_id != objective.objective_id
        or certificate.objective_sense != objective.sense
        or certificate.objective_unit != objective.unit
    ):
        raise ValueError("certificate is not bound to the verified base decision")
    if certificate.authority.reviewed_model_digest != problem.digest:
        raise ValueError("authority certificate is not bound to the reviewed model")
    expected_constraint_ids = tuple(item.constraint_id for item in problem.constraints)
    if certificate.authority.reviewed_constraint_ids != expected_constraint_ids:
        raise ValueError("authority certificate does not name the reviewed constraints")
    expected_origins = tuple(
        sorted({origin for item in problem.constraints for origin in item.origin_refs})
    )
    if certificate.authority.reviewed_origin_refs != expected_origins:
        raise ValueError("authority certificate does not name reviewed origins exactly")

    nogood_problem = _with_constraint(problem, _binary_nogood(problem, plan.result.assignments))
    _validate_probe(
        certificate.same_model_alternative.probe,
        nogood_problem,
        reference_model_digest=problem.digest,
        replay_solves=replay_solves,
    )
    expected_alternative = _classify_alternative(
        certificate.same_model_alternative.probe,
        base_value=base_value,
        objective_id=objective.objective_id,
        objective_sense=objective.sense,
    )
    if certificate.same_model_alternative != expected_alternative:
        raise ValueError("same-model alternative classification or arithmetic is invalid")

    forced_by_id = {item.variable_id: item for item in certificate.variable_forcedness}
    if set(forced_by_id) != {item.variable_id for item in problem.variables}:
        raise ValueError("variable forcedness coverage is incomplete")
    for variable in problem.variables:
        item = forced_by_id[variable.variable_id]
        expected_constraint = _opposite_constraint(
            variable.variable_id, plan.result.assignments[variable.variable_id]
        )
        probe_problem = _with_constraint(problem, expected_constraint)
        _validate_probe(
            item.probe,
            probe_problem,
            reference_model_digest=problem.digest,
            replay_solves=replay_solves,
        )
        expected = VariableForcednessCertificate(
            variable_id=variable.variable_id,
            selected_value=plan.result.assignments[variable.variable_id],
            tested_value=Decimal(1) - plan.result.assignments[variable.variable_id],
            feasibility_forced=item.probe.result.status == OptimizationStatus.INFEASIBLE,
            probe=item.probe,
        )
        if item != expected:
            raise ValueError(f"invalid forcedness certificate for {variable.variable_id}")

    roles_by_id = {item.constraint_id: item for item in certificate.constraint_roles}
    if set(roles_by_id) != set(expected_constraint_ids):
        raise ValueError("constraint-role coverage is incomplete")
    for constraint in problem.constraints:
        item = roles_by_id[constraint.constraint_id]
        probe_problem = _without_constraint(problem, constraint.constraint_id)
        _validate_probe(
            item.probe,
            probe_problem,
            reference_model_digest=problem.digest,
            replay_solves=replay_solves,
        )
        expected = _constraint_role_from_probe(
            plan,
            constraint.constraint_id,
            item.probe,
            base_value,
            objective.objective_id,
            objective.sense,
        )
        if item != expected:
            raise ValueError(f"invalid role certificate for {constraint.constraint_id}")

    _validate_policy_sensitivity(
        problem,
        plan,
        certificate.policy_sensitivity,
        objective.objective_id,
        objective.unit,
        replay_solves=replay_solves,
    )


def _validate_base(problem: OptimizationProblem, plan: VerifiedPlan):
    if len(problem.objectives) != 1:
        raise ValueError("decision argument certificates currently require one objective")
    if any(item.domain != "binary" for item in problem.variables):
        raise ValueError("decision argument certificates currently require binary variables")
    if any(not item.hard for item in problem.constraints):
        raise ValueError("decision argument certificates currently require hard constraints")
    if problem.objectives[0].sense != "minimize":
        raise ValueError("cost-preference certificates require a minimizing objective")
    if plan.result.status != OptimizationStatus.OPTIMAL:
        raise ValueError("decision argument certificate requires a proven optimal base plan")
    replay = verify_result(problem, plan.result)
    if not replay.verified or replay != plan.verification:
        raise ValueError("base plan failed independent replay")
    if any(value not in {Decimal(0), Decimal(1)} for value in plan.result.assignments.values()):
        raise ValueError("base assignment is not binary")
    return problem.objectives[0]


def _binary_nogood(
    problem: OptimizationProblem, assignment: dict[str, Decimal]
) -> LinearConstraint:
    ones = [item.variable_id for item in problem.variables if assignment[item.variable_id] == 1]
    terms = tuple(
        LinearTerm(
            variable_id=item.variable_id,
            coefficient=Decimal(-1) if assignment[item.variable_id] == 1 else Decimal(1),
        )
        for item in problem.variables
    )
    return LinearConstraint(
        constraint_id=_reserved_id(problem, "argument_probe:nogood"),
        expression=LinearExpression(terms=terms, constant=Decimal(len(ones))),
        sense=">=",
        rhs=Decimal(1),
        unit="unit",
        origin_refs=("decision_argument:same_model_nogood",),
    )


def _opposite_constraint(variable_id: str, selected: Decimal) -> LinearConstraint:
    return LinearConstraint(
        constraint_id=f"argument_probe:opposite:{variable_id}",
        expression=LinearExpression(
            terms=(LinearTerm(variable_id=variable_id, coefficient=Decimal(1)),)
        ),
        sense="=",
        rhs=Decimal(1) - selected,
        unit="unit",
        origin_refs=("decision_argument:variable_forcedness",),
    )


def _with_constraint(
    problem: OptimizationProblem, constraint: LinearConstraint
) -> OptimizationProblem:
    if constraint.constraint_id in {item.constraint_id for item in problem.constraints}:
        raise ValueError(f"probe constraint ID collides: {constraint.constraint_id}")
    return OptimizationProblem.model_validate(
        {
            **problem.model_dump(mode="python"),
            "constraints": (*problem.constraints, constraint),
        }
    )


def _without_constraint(problem: OptimizationProblem, constraint_id: str) -> OptimizationProblem:
    return OptimizationProblem.model_validate(
        {
            **problem.model_dump(mode="python"),
            "constraints": tuple(
                item for item in problem.constraints if item.constraint_id != constraint_id
            ),
        }
    )


def _reserved_id(problem: OptimizationProblem, value: str) -> str:
    if value in {item.constraint_id for item in problem.constraints}:
        raise ValueError(f"reviewed model uses reserved probe ID {value}")
    return value


def _solve_probe(
    problem: OptimizationProblem,
    *,
    probe_id: str,
    kind: ProbeKind,
    reference_model_digest: str,
    seed: int,
) -> ProbeCertificate:
    result = _semantic_result(solve_highs(problem, seed=seed, threads=1))
    verification = (
        verify_result(problem, result)
        if result.status in {OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE}
        else None
    )
    return ProbeCertificate(
        probe_id=probe_id,
        kind=kind,
        reference_model_digest=reference_model_digest,
        probe_model_digest=problem.digest,
        result=result,
        verification=verification,
    )


def _validate_probe(
    probe: ProbeCertificate,
    problem: OptimizationProblem,
    *,
    reference_model_digest: str,
    replay_solves: bool,
) -> None:
    if probe.reference_model_digest != reference_model_digest:
        raise ValueError(f"probe {probe.probe_id} names the wrong reference model")
    if probe.reference_model_digest == probe.probe_model_digest:
        raise ValueError("probe transformation did not change the model")
    if probe.probe_model_digest != problem.digest:
        raise ValueError(f"probe {probe.probe_id} is not bound to its transformation")
    if probe.result.status in {OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE}:
        replayed_verification = verify_result(problem, probe.result)
        if probe.verification != replayed_verification or not replayed_verification.verified:
            raise ValueError(f"probe {probe.probe_id} failed independent verification")
    if replay_solves:
        replayed = solve_highs(
            problem,
            seed=probe.result.receipt.seed,
            threads=probe.result.receipt.threads,
        )
        if replayed.semantic_digest != probe.result.semantic_digest:
            raise ValueError(f"probe {probe.probe_id} solver replay diverged")


def _objective_value(probe: ProbeCertificate, objective_id: str) -> Decimal | None:
    return (
        probe.verification.objective_values[objective_id]
        if probe.verification is not None
        else None
    )


def _preference_gap(base_value: Decimal, alternative_value: Decimal, sense: str) -> Decimal:
    return alternative_value - base_value if sense == "minimize" else base_value - alternative_value


def _classify_alternative(
    probe: ProbeCertificate,
    *,
    base_value: Decimal,
    objective_id: str,
    objective_sense: str,
) -> SameModelAlternativeCertificate:
    if probe.result.status == OptimizationStatus.INFEASIBLE:
        return SameModelAlternativeCertificate(
            decision_class="unique_feasible",
            probe=probe,
            alternative_assignment=None,
            alternative_objective_value=None,
            objective_gap=None,
        )
    if probe.result.status != OptimizationStatus.OPTIMAL:
        raise ValueError("same-model no-good probe must prove optimality or infeasibility")
    value = _objective_value(probe, objective_id)
    assert value is not None
    gap = _preference_gap(base_value, value, objective_sense)
    if gap < 0:
        raise ValueError("same-model alternative is better than the claimed optimum")
    return SameModelAlternativeCertificate(
        decision_class="cost_preferred" if gap > 0 else "multiple_optima",
        probe=probe,
        alternative_assignment=dict(probe.result.assignments),
        alternative_objective_value=value,
        objective_gap=gap,
    )


def _variable_forcedness(
    problem: OptimizationProblem,
    variable_id: str,
    selected_value: Decimal,
    seed: int,
) -> VariableForcednessCertificate:
    tested = Decimal(1) - selected_value
    probe = _solve_probe(
        _with_constraint(problem, _opposite_constraint(variable_id, selected_value)),
        probe_id=f"opposite:{variable_id}",
        kind="variable_opposite",
        reference_model_digest=problem.digest,
        seed=seed,
    )
    return VariableForcednessCertificate(
        variable_id=variable_id,
        selected_value=selected_value,
        tested_value=tested,
        feasibility_forced=probe.result.status == OptimizationStatus.INFEASIBLE,
        probe=probe,
    )


def _constraint_role(
    problem: OptimizationProblem,
    plan: VerifiedPlan,
    constraint_id: str,
    base_value: Decimal,
    objective_id: str,
    objective_sense: str,
    seed: int,
) -> ConstraintRoleCertificate:
    probe = _solve_probe(
        _without_constraint(problem, constraint_id),
        probe_id=f"ablate:{constraint_id}",
        kind="constraint_ablation",
        reference_model_digest=problem.digest,
        seed=seed,
    )
    return _constraint_role_from_probe(
        plan, constraint_id, probe, base_value, objective_id, objective_sense
    )


def _constraint_role_from_probe(
    plan: VerifiedPlan,
    constraint_id: str,
    probe: ProbeCertificate,
    base_value: Decimal,
    objective_id: str,
    objective_sense: str,
) -> ConstraintRoleCertificate:
    check = next(
        item for item in plan.verification.constraint_checks if item.constraint_id == constraint_id
    )
    binding = check.lhs == check.rhs
    if probe.result.status != OptimizationStatus.OPTIMAL:
        return ConstraintRoleCertificate(
            constraint_id=constraint_id,
            binding_at_selected_point=binding,
            role="unresolved",
            assignment_changed=False,
            objective_delta=None,
            probe=probe,
        )
    value = _objective_value(probe, objective_id)
    assert value is not None
    changed = probe.result.assignments != plan.result.assignments
    delta = value - base_value if objective_sense == "minimize" else base_value - value
    if delta > 0:
        raise ValueError("constraint ablation cannot worsen a proven single-objective optimum")
    role: ConstraintRole
    if changed and delta < 0:
        role = "cost_decisive"
    elif changed:
        role = "optimal_set_restricting"
    else:
        role = "redundant_at_optimum"
    return ConstraintRoleCertificate(
        constraint_id=constraint_id,
        binding_at_selected_point=binding,
        role=role,
        assignment_changed=changed,
        objective_delta=delta,
        probe=probe,
    )


def _policy_sensitivity(
    problem: OptimizationProblem,
    plan: VerifiedPlan,
    run: CounterfactualRun | None,
    changes: tuple[CounterfactualChange, ...],
    objective_id: str,
    objective_unit: str,
) -> PolicySensitivityCertificate | None:
    if run is None:
        if changes:
            raise ValueError("policy changes require an executed counterfactual run")
        return None
    if not changes:
        raise ValueError("policy counterfactual requires its exact changes")
    variant = apply_counterfactual(problem, changes)
    run = run.model_copy(update={"result": _semantic_result(run.result)})
    if (
        run.base_model_digest != problem.digest
        or run.variant_model_digest == problem.digest
        or run.variant_model_digest != variant.digest
        or run.transformation_digest
        != stable_hash([item.model_dump(mode="json") for item in changes])
        or run.result.model_digest != variant.digest
        or run.result.status != OptimizationStatus.OPTIMAL
    ):
        raise ValueError("policy counterfactual is not bound to its declared transformation")
    verification = verify_result(variant, run.result)
    if not verification.verified:
        raise ValueError("policy counterfactual failed independent verification")
    base_value = plan.verification.objective_values[objective_id]
    variant_value = verification.objective_values[objective_id]
    changes_by_variable = {
        variable_id: (plan.result.assignments[variable_id], value)
        for variable_id, value in run.result.assignments.items()
        if plan.result.assignments[variable_id] != value
    }
    return PolicySensitivityCertificate(
        changes=changes,
        run=run,
        verification=verification,
        changed_assignments=changes_by_variable,
        objective_delta=variant_value - base_value,
        objective_unit=objective_unit,
    )


def _semantic_result(result: OptimizationResult) -> OptimizationResult:
    """Remove non-semantic wall-clock telemetry from a certificate-embedded result."""

    return result.model_copy(update={"runtime_seconds": 0.0})


def _validate_policy_sensitivity(
    problem: OptimizationProblem,
    plan: VerifiedPlan,
    sensitivity: PolicySensitivityCertificate | None,
    objective_id: str,
    objective_unit: str,
    *,
    replay_solves: bool,
) -> None:
    if sensitivity is None:
        return
    expected = _policy_sensitivity(
        problem,
        plan,
        sensitivity.run,
        sensitivity.changes,
        objective_id,
        objective_unit,
    )
    if sensitivity != expected:
        raise ValueError("policy sensitivity arithmetic or binding is invalid")
    if replay_solves:
        variant = apply_counterfactual(problem, sensitivity.changes)
        replayed = solve_highs(
            variant,
            seed=sensitivity.run.result.receipt.seed,
            threads=sensitivity.run.result.receipt.threads,
        )
        if replayed.semantic_digest != sensitivity.run.result.semantic_digest:
            raise ValueError("policy sensitivity solver replay diverged")


__all__ = [
    "AuthorityBoundaryCertificate",
    "ConstraintRoleCertificate",
    "DecisionArgumentCertificate",
    "PolicySensitivityCertificate",
    "ProbeCertificate",
    "SameModelAlternativeCertificate",
    "VariableForcednessCertificate",
    "build_decision_argument_certificate",
    "validate_decision_argument_certificate",
]
