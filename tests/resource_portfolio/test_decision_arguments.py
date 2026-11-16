# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ruler.applications.resource_portfolio.argumentation import (
    AuthorityBoundaryCertificate,
    build_decision_argument_certificate,
    validate_decision_argument_certificate,
)
from ruler.applications.resource_portfolio.compiler import (
    CompilationRequest,
    compile_rules,
)
from ruler.applications.resource_portfolio.demonstrator import _demonstrator_inputs
from ruler.applications.resource_portfolio.optimization import optimize_portfolio
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    run_counterfactual,
)
from ruler.applications.resource_portfolio.workflow import build_evidence_snapshot
from ruler.io import stable_hash
from ruler.optimization.contracts import (
    LinearConstraint,
    LinearExpression,
    LinearObjective,
    LinearTerm,
    OptimizationProblem,
    OptimizationVariable,
)

SHA = "sha256:" + "a" * 64


def _binary_problem(
    *,
    problem_id: str = "argument-test",
    constraints: tuple[LinearConstraint, ...],
    costs: tuple[int, int] = (3, 5),
) -> OptimizationProblem:
    return OptimizationProblem(
        problem_id=problem_id,
        snapshot_digest=SHA,
        variables=tuple(
            OptimizationVariable(
                variable_id=name,
                domain="binary",
                lower_bound=0,
                upper_bound=1,
                unit="unit",
                origin_refs=(f"resource:{name}",),
            )
            for name in ("x", "y")
        ),
        constraints=constraints,
        objectives=(
            LinearObjective(
                objective_id="cost",
                expression=LinearExpression(
                    terms=tuple(
                        LinearTerm(variable_id=name, coefficient=cost)
                        for name, cost in zip(("x", "y"), costs, strict=True)
                    )
                ),
                sense="minimize",
                unit="CHF",
                component="lifecycle",
                origin_refs=("reviewed:cost",),
            ),
        ),
    )


def _minimum(name: str, variable: str, rhs: int = 1) -> LinearConstraint:
    return LinearConstraint(
        constraint_id=name,
        expression=LinearExpression(terms=(LinearTerm(variable_id=variable, coefficient=1),)),
        sense=">=",
        rhs=rhs,
        unit="unit",
        origin_refs=(f"reviewed:{name}",),
    )


def _choice() -> LinearConstraint:
    return LinearConstraint(
        constraint_id="choose_one",
        expression=LinearExpression(
            terms=(
                LinearTerm(variable_id="x", coefficient=1),
                LinearTerm(variable_id="y", coefficient=1),
            )
        ),
        sense=">=",
        rhs=1,
        unit="unit",
        origin_refs=("reviewed:choice",),
    )


def test_unique_feasible_is_proved_by_infeasible_same_model_nogood() -> None:
    problem = _binary_problem(constraints=(_minimum("require_x", "x"), _minimum("require_y", "y")))
    plan = optimize_portfolio(problem)

    certificate = build_decision_argument_certificate(
        problem,
        plan,
        candidate_kb_digest="sha256:" + "b" * 64,
        seed=7,
    )

    assert certificate.decision_class == "unique_feasible"
    assert certificate.same_model_alternative.alternative_assignment is None
    assert all(item.feasibility_forced for item in certificate.variable_forcedness)
    assert {item.role for item in certificate.constraint_roles} == {"cost_decisive"}
    assert certificate.authority.candidate_kb_solver_authority is False
    assert certificate.authority.reviewed_model_solver_authority is True
    validate_decision_argument_certificate(problem, plan, certificate)

    repeated = build_decision_argument_certificate(
        problem,
        plan,
        candidate_kb_digest="sha256:" + "b" * 64,
        seed=7,
    )
    assert repeated.certificate_sha256 == certificate.certificate_sha256


def test_cost_preferred_uses_a_distinct_optimum_under_the_same_reviewed_model() -> None:
    problem = _binary_problem(constraints=(_choice(),))
    plan = optimize_portfolio(problem)
    certificate = build_decision_argument_certificate(problem, plan, seed=11)

    alternative = certificate.same_model_alternative
    assert certificate.decision_class == "cost_preferred"
    assert certificate.selected_assignment == {"x": Decimal("1.0"), "y": Decimal("0.0")}
    assert alternative.alternative_assignment == {"x": Decimal("0.0"), "y": Decimal("1.0")}
    assert alternative.alternative_objective_value == Decimal(5)
    assert alternative.objective_gap == Decimal(2)
    assert alternative.probe.reference_model_digest == problem.digest
    assert alternative.probe.probe_model_digest != problem.digest
    assert not any(item.feasibility_forced for item in certificate.variable_forcedness)


def test_tied_optima_are_not_misreported_as_cost_preferred() -> None:
    problem = _binary_problem(constraints=(_choice(),), costs=(3, 3))
    plan = optimize_portfolio(problem)
    certificate = build_decision_argument_certificate(problem, plan)

    assert certificate.decision_class == "multiple_optima"
    assert certificate.same_model_alternative.objective_gap == 0


def test_binding_redundant_constraints_are_not_called_decisive() -> None:
    problem = _binary_problem(
        constraints=(
            _minimum("require_x_a", "x"),
            _minimum("require_x_b", "x"),
            _minimum("require_y", "y"),
        )
    )
    plan = optimize_portfolio(problem)
    certificate = build_decision_argument_certificate(problem, plan)
    roles = {item.constraint_id: item for item in certificate.constraint_roles}

    assert roles["require_x_a"].binding_at_selected_point
    assert roles["require_x_a"].role == "redundant_at_optimum"
    assert roles["require_x_b"].role == "redundant_at_optimum"
    assert roles["require_y"].role == "cost_decisive"


def test_changed_policy_is_separate_and_uses_exact_decimal_delta() -> None:
    problem = _binary_problem(constraints=(_minimum("require_x", "x"), _minimum("require_y", "y")))
    plan = optimize_portfolio(problem)
    changes = (CounterfactualChange(kind="constraint_rhs", target_id="require_x", value=0),)
    run = run_counterfactual(problem, changes, run_id="relax-x", seed=5)
    certificate = build_decision_argument_certificate(
        problem,
        plan,
        policy_counterfactual=run,
        policy_changes=changes,
        seed=5,
    )

    assert certificate.decision_class == "unique_feasible"
    assert certificate.policy_sensitivity is not None
    assert certificate.policy_sensitivity.comparison_kind == "policy_sensitivity"
    assert certificate.policy_sensitivity.changed_assignments == {
        "x": (Decimal("1.0"), Decimal("0.0"))
    }
    assert certificate.policy_sensitivity.objective_delta == Decimal(-3)
    assert certificate.policy_sensitivity.objective_unit == "CHF"


def test_validator_rejects_tampered_classification_and_policy_delta() -> None:
    problem = _binary_problem(constraints=(_minimum("require_x", "x"), _minimum("require_y", "y")))
    plan = optimize_portfolio(problem)
    changes = (CounterfactualChange(kind="constraint_rhs", target_id="require_x", value=0),)
    certificate = build_decision_argument_certificate(
        problem,
        plan,
        policy_counterfactual=run_counterfactual(problem, changes, run_id="relax-x"),
        policy_changes=changes,
    )

    tampered_alternative = certificate.same_model_alternative.model_copy(
        update={"decision_class": "cost_preferred"}
    )
    tampered = certificate.model_copy(
        update={
            "decision_class": "cost_preferred",
            "same_model_alternative": tampered_alternative,
        }
    )
    tampered = tampered.model_copy(
        update={
            "certificate_sha256": stable_hash(
                tampered.model_dump(mode="json", exclude={"certificate_sha256"})
            )
        }
    )
    with pytest.raises(ValueError, match="same-model|classification"):
        validate_decision_argument_certificate(problem, plan, tampered, replay_solves=False)

    assert certificate.policy_sensitivity is not None
    wrong_delta = certificate.policy_sensitivity.model_copy(update={"objective_delta": Decimal(3)})
    tampered = certificate.model_copy(update={"policy_sensitivity": wrong_delta})
    tampered = tampered.model_copy(
        update={
            "certificate_sha256": stable_hash(
                tampered.model_dump(mode="json", exclude={"certificate_sha256"})
            )
        }
    )
    with pytest.raises(ValueError, match="policy sensitivity"):
        validate_decision_argument_certificate(problem, plan, tampered, replay_solves=False)


def test_counterfactual_transformation_mismatch_fails_closed() -> None:
    problem = _binary_problem(constraints=(_minimum("require_x", "x"), _minimum("require_y", "y")))
    plan = optimize_portfolio(problem)
    executed = (CounterfactualChange(kind="constraint_rhs", target_id="require_x", value=0),)
    mislabeled = (CounterfactualChange(kind="constraint_rhs", target_id="require_y", value=0),)
    run = run_counterfactual(problem, executed, run_id="relax-x")

    with pytest.raises(ValueError, match="declared transformation"):
        build_decision_argument_certificate(
            problem,
            plan,
            policy_counterfactual=run,
            policy_changes=mislabeled,
        )


def test_authority_contract_cannot_promote_candidate_kb() -> None:
    with pytest.raises(ValidationError):
        AuthorityBoundaryCertificate(
            candidate_kb_digest="sha256:" + "b" * 64,
            candidate_kb_solver_authority=True,
            reviewed_model_digest=SHA,
            reviewed_constraint_ids=(),
            reviewed_origin_refs=(),
        )


def test_nonbinary_models_fail_instead_of_fabricating_a_runner_up() -> None:
    base = _binary_problem(constraints=(_choice(),))
    problem = base.model_copy(
        update={
            "variables": (
                base.variables[0].model_copy(update={"domain": "continuous"}),
                base.variables[1],
            )
        }
    )
    plan = optimize_portfolio(problem)
    with pytest.raises(ValueError, match="binary variables"):
        build_decision_argument_certificate(problem, plan)


def test_current_demonstrator_economics_identify_backup_policy_cost() -> None:
    inputs = _demonstrator_inputs()
    _, _, _, snapshot = build_evidence_snapshot(inputs["evidence.yaml"])
    compilation_payload = deepcopy(inputs["compile.yaml"])
    compilation_payload["snapshot_digest"] = snapshot.content_sha256
    problem = compile_rules(CompilationRequest.model_validate(compilation_payload)).problem
    plan = optimize_portfolio(problem, seed=20260903)
    changes = tuple(
        CounterfactualChange.model_validate(item)
        for item in inputs["model.yaml"]["counterfactual"]["changes"]
    )
    counterfactual = run_counterfactual(
        problem,
        changes,
        run_id="current-demonstrator-backup-relaxation",
        seed=20260903,
    )

    certificate = build_decision_argument_certificate(
        problem,
        plan,
        policy_counterfactual=counterfactual,
        policy_changes=changes,
        seed=20260903,
    )

    assert certificate.decision_class == "unique_feasible"
    assert certificate.selected_objective_value == Decimal(1102400)
    sensitivity = certificate.policy_sensitivity
    assert sensitivity is not None
    assert sensitivity.verification.objective_values["verified_annual_cost"] == Decimal(743600)
    assert sensitivity.changed_assignments == {"reserve_ibex": (Decimal(1), Decimal(0))}
    assert sensitivity.objective_delta == Decimal(-358800)
