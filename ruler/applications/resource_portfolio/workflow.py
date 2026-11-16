# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Bounded, artifact-closed resource-portfolio reference workflow.

This composition root executes the real Z3, HiGHS and CP-SAT implementations.
It is intentionally file-oriented so the CLI can remain a thin adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field, field_validator

from ruler.applications.resource_portfolio.compiler import (
    CompilationReport,
    CompilationRequest,
    compile_rules,
)
from ruler.applications.resource_portfolio import contracts as portfolio_contracts
from ruler.applications.resource_portfolio.evidence import (
    EvidenceNormalizationResult,
    StateReconstructionResult,
    normalize_operational_events,
    reconstruct_state_intervals,
)
from ruler.applications.resource_portfolio.explanations import (
    ExplanationCounterfactual,
    ExplanationDriver,
    PortfolioExplanation,
    PortfolioExplanationEvidence,
    build_deterministic_explanation,
    explanation_evidence_digest,
)
from ruler.applications.resource_portfolio.optimization import VerifiedPlan, optimize_portfolio
from ruler.applications.resource_portfolio.profiles import build_conditional_profiles
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    CounterfactualRun,
    ScenarioSet,
    StressReport,
    calculate_cvar,
    run_counterfactual,
    stress_test,
)
from ruler.applications.resource_portfolio.scheduling import (
    SchedulingProblem,
    SchedulingResult,
    solve_schedule,
    verify_schedule_result,
)
from ruler.applications.resource_portfolio.snapshot import build_immutable_snapshot
from ruler.contracts.common import StrictContract, validate_sha256
from ruler.ingestion.contracts import canonical_sha256, stable_id
from ruler.io import read_yaml, stable_hash, write_yaml
from ruler.paths import REPO_ROOT
from ruler.optimization.verification import verify_result

INPUT_FILENAMES = (
    "evidence.yaml",
    "compile.yaml",
    "model.yaml",
    "schedule.yaml",
    "stress.yaml",
    "explanation.yaml",
)
SAMPLE_INPUT_DIR = REPO_ROOT / "data" / "domains" / "construction_fleet" / "tests"
REQUIRED_ARTIFACT_TYPES = frozenset(
    {
        "operational_evidence",
        "immutable_planning_snapshot",
        "compilation_report",
        "verified_plan",
        "scheduling_result",
        "stress_report",
        "counterfactual_run",
        "deterministic_explanation",
        "human_review_gate",
    }
)


class WorkflowLimits(StrictContract):
    max_variables: int = Field(default=100, ge=1, le=10_000)
    max_constraints: int = Field(default=500, ge=1, le=50_000)
    max_schedule_tasks: int = Field(default=100, ge=1, le=10_000)
    max_scenarios: int = Field(default=10, ge=1, le=1_000)
    max_solver_seconds: float = Field(default=30.0, gt=0, le=3_600)


class WorkflowArtifact(StrictContract):
    artifact_type: str
    relative_path: str
    payload_sha256: str
    semantic_sha256: str

    _hashes = field_validator("payload_sha256", "semantic_sha256")(validate_sha256)

    @field_validator("relative_path")
    @classmethod
    def local_artifact_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise ValueError("workflow artifact paths must be local filenames")
        return value


class ResourcePortfolioWorkflowRun(StrictContract):
    schema_version: Literal["resource-portfolio-workflow/v1"] = "resource-portfolio-workflow/v1"
    run_id: str
    input_digests: dict[str, str]
    artifacts: tuple[WorkflowArtifact, ...] = Field(min_length=9)
    solver_backends: tuple[str, ...]
    status: Literal["pending_review"] = "pending_review"
    advisory_only: Literal[True] = True
    externally_authorized: Literal[False] = False
    run_digest: str

    _digest = field_validator("run_digest")(validate_sha256)


def _without_telemetry(value: Any) -> Any:
    """Remove wall-clock fields while retaining solver termination evidence."""
    if isinstance(value, dict):
        return {
            key: _without_telemetry(item)
            for key, item in value.items()
            if key not in {"runtime_seconds"}
        }
    if isinstance(value, list):
        return [_without_telemetry(item) for item in value]
    return value


def _artifact_envelope(artifact_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    return {
        "schema_version": "resource-portfolio-artifact/v1",
        "artifact_type": artifact_type,
        "payload": normalized,
        "payload_sha256": stable_hash(normalized),
        "semantic_sha256": stable_hash(_without_telemetry(normalized)),
    }


def _run_digest_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Authenticate replay-stable semantics, excluding measured telemetry hashes."""
    normalized = dict(payload)
    normalized["artifacts"] = [
        {
            "artifact_type": item["artifact_type"],
            "relative_path": item["relative_path"],
            "semantic_sha256": item["semantic_sha256"],
        }
        for item in normalized["artifacts"]
    ]
    return normalized


def _write_artifact(
    output_dir: Path,
    filename: str,
    artifact_type: str,
    payload: Mapping[str, Any],
) -> WorkflowArtifact:
    envelope = _artifact_envelope(artifact_type, payload)
    write_yaml(output_dir / filename, envelope)
    return WorkflowArtifact(
        artifact_type=artifact_type,
        relative_path=filename,
        payload_sha256=envelope["payload_sha256"],
        semantic_sha256=envelope["semantic_sha256"],
    )


def _load_inputs(input_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    payloads: dict[str, Any] = {}
    digests: dict[str, str] = {}
    for filename in INPUT_FILENAMES:
        path = input_dir / filename
        if not path.is_file():
            raise ValueError(f"missing workflow input {filename}")
        payload = read_yaml(path)
        if not isinstance(payload, dict):
            raise ValueError(f"workflow input {filename} must be a mapping")
        payloads[filename] = payload
        digests[filename] = canonical_sha256(path.read_bytes())
    return payloads, digests


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def build_evidence_snapshot(
    payload: Mapping[str, Any],
) -> tuple[
    EvidenceNormalizationResult,
    StateReconstructionResult,
    tuple[portfolio_contracts.Profile, ...],
    portfolio_contracts.ImmutableSnapshot,
]:
    """Execute the typed evidence path and freeze the exact solver snapshot."""
    collection_types = {
        "unit_definitions": portfolio_contracts.UnitDefinition,
        "resources": portfolio_contracts.Resource,
        "resource_types": portfolio_contracts.ResourceType,
        "capabilities": portfolio_contracts.Capability,
        "configurations": portfolio_contracts.Configuration,
        "locations": portfolio_contracts.Location,
        "work_units": portfolio_contracts.WorkUnit,
        "activities": portfolio_contracts.Activity,
        "requirements": portfolio_contracts.Requirement,
        "events": portfolio_contracts.OperationalEvent,
        "external_offers": portfolio_contracts.ExternalSupplyOffer,
        "profiles": portfolio_contracts.Profile,
        "rules": portfolio_contracts.Rule,
        "scenarios": portfolio_contracts.Scenario,
    }
    values = {
        name: tuple(model.model_validate(item) for item in payload.get(name, ()))
        for name, model in collection_types.items()
    }
    normalization = payload.get("normalization", {})
    if not isinstance(normalization, Mapping):
        raise ValueError("evidence normalization settings must be a mapping")
    conversions = {
        str(source): (str(config["target_unit"]), str(config["factor"]))
        for source, config in normalization.get("unit_conversions", {}).items()
    }
    normalized = normalize_operational_events(
        values.pop("events"),
        identity_maps=normalization.get("identity_maps", {}),
        state_map=normalization.get("state_map", {}),
        unit_conversions=conversions,
        split_boundaries=tuple(
            _datetime(item) for item in normalization.get("split_boundaries", ())
        ),
    )
    as_of = _datetime(payload["as_of"])
    scope_start = _datetime(payload["scope_start"])
    scope_end = _datetime(payload["scope_end"])
    reconstructed = reconstruct_state_intervals(
        normalized.canonical_events,
        scope_start=scope_start,
        scope_end=scope_end,
        as_of=as_of,
        resource_ids=(item.resource_id for item in values["resources"]),
    )
    profile_validity = portfolio_contracts.TimeInterval.model_validate(payload["profile_validity"])
    generated_profiles = build_conditional_profiles(
        normalized.active_events,
        reconstructed.intervals,
        as_of=as_of,
        validity=profile_validity,
        context_dimensions=tuple(payload.get("profile_context_dimensions", ())),
        minimum_exact_support=int(payload.get("minimum_exact_profile_support", 3)),
    )
    values["profiles"] = (*values["profiles"], *generated_profiles)
    snapshot = build_immutable_snapshot(
        domain_id=str(payload["domain_id"]),
        domain_package_id=str(payload["domain_package_id"]),
        as_of=as_of,
        created_at=_datetime(payload["created_at"]),
        currency_unit=str(payload["currency_unit"]),
        watermarks={key: _datetime(value) for key, value in payload["watermarks"].items()},
        input_artifact_digests=payload.get("input_artifact_digests"),
        events=normalized.canonical_events,
        state_intervals=reconstructed.intervals,
        safety_critical_capability_ids=payload.get("safety_critical_capability_ids", ()),
        **values,
    )
    return normalized, reconstructed, generated_profiles, snapshot


def _enforce_limits(
    compilation: CompilationRequest,
    schedule: SchedulingProblem,
    scenarios: ScenarioSet,
    limits: WorkflowLimits,
    time_limit_seconds: float,
) -> None:
    if len(compilation.variables) > limits.max_variables:
        raise ValueError("workflow variable limit exceeded")
    if len(compilation.rules) + len(compilation.axioms) > limits.max_constraints:
        raise ValueError("workflow constraint limit exceeded")
    if len(schedule.tasks) > limits.max_schedule_tasks:
        raise ValueError("workflow schedule task limit exceeded")
    if len(scenarios.scenarios) > limits.max_scenarios:
        raise ValueError("workflow scenario limit exceeded")
    if time_limit_seconds > limits.max_solver_seconds:
        raise ValueError("workflow solver time limit exceeded")


def _assert_success(
    compilation: CompilationReport,
    plan: VerifiedPlan,
    scheduling_problem: SchedulingProblem,
    schedule: SchedulingResult,
    stress: StressReport,
    counterfactual: CounterfactualRun,
) -> None:
    if compilation.z3_status != "sat":
        raise ValueError("Z3 compilation did not establish satisfiability")
    if plan.result.status not in {"OPTIMAL", "FEASIBLE"} or not plan.verification.verified:
        raise ValueError("HiGHS plan has no independently verified incumbent")
    if plan.result.receipt.model_digest != compilation.problem.digest:
        raise ValueError("HiGHS receipt is not bound to the compiled model")
    if schedule.status not in {"OPTIMAL", "FEASIBLE"}:
        raise ValueError("CP-SAT did not produce a usable schedule")
    if schedule.receipt.problem_digest != scheduling_problem.digest:
        raise ValueError("CP-SAT receipt is not bound to the scheduling problem")
    if any(outcome.result.status not in {"OPTIMAL", "FEASIBLE"} for outcome in stress.outcomes):
        raise ValueError("stress run contains a scenario without a feasible incumbent")
    if stress.risk is None:
        raise ValueError("stress run did not calculate risk")
    if any(
        outcome.result.receipt.model_digest != outcome.variant_model_digest
        for outcome in stress.outcomes
    ):
        raise ValueError("stress receipt is not bound to its scenario model")
    if counterfactual.base_model_digest == counterfactual.variant_model_digest:
        raise ValueError("counterfactual did not change the model")
    if counterfactual.result.status not in {"OPTIMAL", "FEASIBLE"}:
        raise ValueError("counterfactual did not produce a feasible result")
    if counterfactual.result.receipt.model_digest != counterfactual.variant_model_digest:
        raise ValueError("counterfactual receipt is not bound to its variant model")


def portfolio_load(
    input_dir: Path, output_dir: Path, limits: WorkflowLimits | None = None
) -> dict[str, Any]:
    """Shared native load step; exceptions propagate without retry."""
    selected_limits = limits or WorkflowLimits()
    inputs, input_digests = _load_inputs(input_dir)
    run_id = stable_id("resource_portfolio_run", input_digests)

    return {
        "selected_limits": selected_limits,
        "inputs": inputs,
        "input_digests": input_digests,
        "run_id": run_id,
        "output_dir": output_dir,
    }


def portfolio_freeze(context: dict[str, Any]):
    """Shared native freeze step; exceptions propagate without retry."""
    inputs = context["inputs"]
    normalized, reconstructed, generated_profiles, snapshot = build_evidence_snapshot(
        inputs["evidence.yaml"]
    )
    return {
        **context,
        "normalized": normalized,
        "reconstructed": reconstructed,
        "generated_profiles": generated_profiles,
        "snapshot": snapshot,
    }


def portfolio_compile(context: dict[str, Any]):
    """Shared native compile step; exceptions propagate without retry."""
    inputs = context["inputs"]
    snapshot = context["snapshot"]
    compilation_payload = dict(inputs["compile.yaml"])
    compilation_payload["snapshot_digest"] = snapshot.content_sha256
    compilation_request = CompilationRequest.model_validate(compilation_payload)
    compilation = compile_rules(compilation_request)  # real Z3 execution
    if compilation.problem.snapshot_digest != snapshot.content_sha256:
        raise ValueError("compiled model is not bound to the freshly built snapshot")

    return {**context, "compilation_request": compilation_request, "compilation": compilation}


def portfolio_configure(context: dict[str, Any]):
    """Shared native configure step; exceptions propagate without retry."""
    inputs = context["inputs"]
    compilation = context["compilation"]
    compilation_request = context["compilation_request"]
    selected_limits = context["selected_limits"]
    model_config = inputs["model.yaml"]
    time_limit_seconds = float(model_config.get("time_limit_seconds", 30.0))
    seed = int(model_config.get("seed", 0))
    threads = int(model_config.get("threads", 1))
    if threads != 1:
        raise ValueError("reference workflow requires a deterministic single solver thread")

    schedule_payload = dict(inputs["schedule.yaml"])
    schedule_payload["plan_digest"] = compilation.problem.digest
    scheduling_problem = SchedulingProblem.model_validate(schedule_payload)
    scenario_set = ScenarioSet.model_validate(inputs["stress.yaml"])
    _enforce_limits(
        compilation_request,
        scheduling_problem,
        scenario_set,
        selected_limits,
        time_limit_seconds,
    )

    return {
        **context,
        "model_config": model_config,
        "time_limit_seconds": time_limit_seconds,
        "seed": seed,
        "threads": threads,
        "scheduling_problem": scheduling_problem,
        "scenario_set": scenario_set,
    }


def portfolio_optimize(context: dict[str, Any]):
    """Shared native optimize step; exceptions propagate without retry."""
    compilation = context["compilation"]
    time_limit_seconds = context["time_limit_seconds"]
    seed = context["seed"]
    threads = context["threads"]
    plan = optimize_portfolio(
        compilation.problem,
        time_limit_seconds=time_limit_seconds,
        seed=seed,
        threads=threads,
    )  # real Pyomo + HiGHS execution and independent arithmetic verification
    return plan


def portfolio_schedule(context: dict[str, Any]):
    """Shared native schedule step; exceptions propagate without retry."""
    scheduling_problem = context["scheduling_problem"]
    time_limit_seconds = context["time_limit_seconds"]
    seed = context["seed"]
    schedule = solve_schedule(
        scheduling_problem,
        time_limit_seconds=time_limit_seconds,
        seed=seed,
    )  # real CP-SAT execution
    return schedule


def portfolio_counterfactual(context: dict[str, Any]):
    """Shared native counterfactual step; exceptions propagate without retry."""
    model_config = context["model_config"]
    compilation = context["compilation"]
    run_id = context["run_id"]
    seed = context["seed"]
    counterfactual_payload = model_config.get("counterfactual")
    if not isinstance(counterfactual_payload, dict):
        raise ValueError("model input requires one bounded counterfactual")
    changes = tuple(
        CounterfactualChange.model_validate(item)
        for item in counterfactual_payload.get("changes", ())
    )
    if not changes:
        raise ValueError("counterfactual changes cannot be empty")
    counterfactual = run_counterfactual(
        compilation.problem,
        changes,
        run_id=f"{run_id}:counterfactual",
        seed=seed,
    )
    return counterfactual


def portfolio_explain(
    context: dict[str, Any],
    plan: VerifiedPlan,
    schedule: SchedulingResult,
    stress: StressReport,
    counterfactual: CounterfactualRun,
) -> dict[str, Any]:
    """Shared native explain step; exceptions propagate without retry."""
    inputs = context["inputs"]
    model_config = context["model_config"]
    run_id = context["run_id"]
    compilation = context["compilation"]
    scheduling_problem = context["scheduling_problem"]
    counterfactual_payload = model_config["counterfactual"]
    _assert_success(
        compilation,
        plan,
        scheduling_problem,
        schedule,
        stress,
        counterfactual,
    )

    explanation_input = inputs["explanation.yaml"]
    drivers = tuple(
        ExplanationDriver.model_validate(item) for item in explanation_input.get("drivers", ())
    )
    constraint_refs = {
        f"constraint:{item.constraint_id}" for item in compilation.problem.constraints
    }
    cited_refs = {reference for driver in drivers for reference in driver.trace_refs}
    if not drivers or not cited_refs <= constraint_refs:
        raise ValueError("explanation drivers are not closed over compiled constraints")
    explanation_counterfactual = ExplanationCounterfactual(
        counterfactual_id=str(counterfactual_payload["counterfactual_id"]),
        condition=str(counterfactual_payload["condition"]),
        changed_action=str(counterfactual_payload["changed_action"]),
        variant_run_id=counterfactual.run_id,
    )
    evidence_payload = {
        "run_id": run_id,
        "recommendation_id": str(explanation_input["recommendation_id"]),
        "solver_status": plan.result.status.value,
        "action": str(explanation_input["action"]),
        "target_id": str(explanation_input["target_id"]),
        "drivers": drivers,
        "counterfactuals": (explanation_counterfactual,),
        "caveats": tuple(explanation_input.get("caveats", ())),
        "numeric_values": {
            **{
                f"assignment_{variable_id}": float(value)
                for variable_id, value in sorted(plan.result.assignments.items())
            },
            **(
                {"objective_value": float(plan.result.objective_value)}
                if plan.result.objective_value is not None
                else {}
            ),
        },
    }
    explanation_evidence = PortfolioExplanationEvidence(
        **evidence_payload,
        evidence_digest=explanation_evidence_digest(evidence_payload),
    )
    explanation = build_deterministic_explanation(explanation_evidence)

    return {
        **context,
        "explanation": explanation,
        "explanation_evidence": explanation_evidence,
        "explanation_input": explanation_input,
        "plan": plan,
        "schedule": schedule,
        "stress": stress,
        "counterfactual": counterfactual,
    }


def portfolio_write_replay(context: dict[str, Any]):
    """Shared native write replay step; exceptions propagate without retry."""
    output_dir = context["output_dir"]
    generated_profiles = context["generated_profiles"]
    normalized = context["normalized"]
    reconstructed = context["reconstructed"]
    snapshot = context["snapshot"]
    compilation = context["compilation"]
    plan = context["plan"]
    schedule = context["schedule"]
    scheduling_problem = context["scheduling_problem"]
    stress = context["stress"]
    scenario_set = context["scenario_set"]
    counterfactual = context["counterfactual"]
    explanation = context["explanation"]
    explanation_evidence = context["explanation_evidence"]
    run_id = context["run_id"]
    input_digests = context["input_digests"]
    explanation_input = context["explanation_input"]
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_backends = sorted(
        ({"deterministic_empirical_statistics"} if generated_profiles else set())
        | (
            {"scipy.optimize.minimize:L-BFGS-B"}
            if any(
                item.profile_type == portfolio_contracts.ProfileType.RELIABILITY
                for item in generated_profiles
            )
            else set()
        )
    )
    artifacts = (
        _write_artifact(
            output_dir,
            "evidence.yaml",
            "operational_evidence",
            {
                "normalization": normalized.model_dump(mode="json"),
                "state_reconstruction": reconstructed.model_dump(mode="json"),
                "profiles": [item.model_dump(mode="json") for item in generated_profiles],
                "profile_backends": profile_backends,
            },
        ),
        _write_artifact(
            output_dir,
            "snapshot.yaml",
            "immutable_planning_snapshot",
            snapshot.model_dump(mode="json"),
        ),
        _write_artifact(
            output_dir,
            "compilation.yaml",
            "compilation_report",
            compilation.model_dump(mode="json"),
        ),
        _write_artifact(output_dir, "plan.yaml", "verified_plan", plan.model_dump(mode="json")),
        _write_artifact(
            output_dir,
            "schedule.yaml",
            "scheduling_result",
            {
                **schedule.model_dump(mode="json"),
                "problem": scheduling_problem.model_dump(mode="json"),
            },
        ),
        _write_artifact(
            output_dir,
            "stress.yaml",
            "stress_report",
            {
                **stress.model_dump(mode="json"),
                "scenario_set": scenario_set.model_dump(mode="json"),
            },
        ),
        _write_artifact(
            output_dir,
            "counterfactual.yaml",
            "counterfactual_run",
            counterfactual.model_dump(mode="json"),
        ),
        _write_artifact(
            output_dir,
            "explanation.yaml",
            "deterministic_explanation",
            {
                **explanation.model_dump(mode="json"),
                "evidence": explanation_evidence.model_dump(mode="json"),
            },
        ),
        _write_artifact(
            output_dir,
            "review.yaml",
            "human_review_gate",
            {
                "run_id": run_id,
                "state": "pending_review",
                "advisory_only": True,
                "externally_authorized": False,
                "required_role": str(explanation_input["required_reviewer_role"]),
            },
        ),
    )
    run_payload = {
        "schema_version": "resource-portfolio-workflow/v1",
        "run_id": run_id,
        "input_digests": input_digests,
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
        "solver_backends": (
            *(("scipy_weibull_mle",) if any("scipy" in item for item in profile_backends) else ()),
            "z3",
            "pyomo_highs",
            "ortools_cp_sat_intervals",
        ),
        "status": "pending_review",
        "advisory_only": True,
        "externally_authorized": False,
    }
    run = ResourcePortfolioWorkflowRun(
        **run_payload,
        run_digest=stable_hash(_run_digest_payload(run_payload)),
    )
    write_yaml(output_dir / "workflow_run.yaml", run.model_dump(mode="json"))
    verify_workflow_artifacts(output_dir)
    return run


def execute_resource_portfolio_workflow(
    input_dir: Path,
    output_dir: Path,
    *,
    limits: WorkflowLimits | None = None,
) -> ResourcePortfolioWorkflowRun:
    """Execute the same ordered steps exposed by the workflow tools."""
    context = portfolio_load(input_dir, output_dir, limits)
    context = portfolio_freeze(context)
    context = portfolio_compile(context)
    context = portfolio_configure(context)
    plan = portfolio_optimize(context)
    schedule = portfolio_schedule(context)
    stress = stress_test(context["compilation"].problem, context["scenario_set"])
    counterfactual = portfolio_counterfactual(context)
    context = portfolio_explain(context, plan, schedule, stress, counterfactual)
    return portfolio_write_replay(context)


def verify_workflow_artifacts(output_dir: Path) -> ResourcePortfolioWorkflowRun:
    """Replay all artifact and run digests without invoking a solver."""
    run = ResourcePortfolioWorkflowRun.model_validate(read_yaml(output_dir / "workflow_run.yaml"))
    run_payload = run.model_dump(mode="json", exclude={"run_digest"})
    if run.run_digest != stable_hash(_run_digest_payload(run_payload)):
        raise ValueError("workflow run digest mismatch")
    for digest in run.input_digests.values():
        validate_sha256(digest)
    artifact_types = {item.artifact_type for item in run.artifacts}
    artifact_paths = {item.relative_path for item in run.artifacts}
    if (
        artifact_types != REQUIRED_ARTIFACT_TYPES
        or len(run.artifacts) != len(REQUIRED_ARTIFACT_TYPES)
        or len(artifact_paths) != len(run.artifacts)
    ):
        raise ValueError("workflow manifest does not contain each required artifact exactly once")
    payloads: dict[str, Any] = {}
    for artifact in run.artifacts:
        envelope = read_yaml(output_dir / artifact.relative_path)
        if (
            not isinstance(envelope, dict)
            or envelope.get("artifact_type") != artifact.artifact_type
        ):
            raise ValueError(f"invalid artifact envelope: {artifact.relative_path}")
        payload = envelope.get("payload")
        if envelope.get("payload_sha256") != stable_hash(payload):
            raise ValueError(f"artifact payload digest mismatch: {artifact.relative_path}")
        if envelope.get("semantic_sha256") != stable_hash(_without_telemetry(payload)):
            raise ValueError(f"artifact semantic digest mismatch: {artifact.relative_path}")
        if artifact.payload_sha256 != envelope["payload_sha256"]:
            raise ValueError(f"run manifest payload digest mismatch: {artifact.relative_path}")
        if artifact.semantic_sha256 != envelope["semantic_sha256"]:
            raise ValueError(f"run manifest semantic digest mismatch: {artifact.relative_path}")
        payloads[artifact.artifact_type] = payload
    snapshot = portfolio_contracts.ImmutableSnapshot.model_validate(
        payloads["immutable_planning_snapshot"]
    )
    compilation = CompilationReport.model_validate(payloads["compilation_report"])
    if compilation.problem.snapshot_digest != snapshot.content_sha256:
        raise ValueError("compiled model is not bound to the emitted planning snapshot")
    plan = VerifiedPlan.model_validate(payloads["verified_plan"])
    if (
        plan.result.model_digest != compilation.problem.digest
        or plan.result.receipt.model_digest != compilation.problem.digest
    ):
        raise ValueError("plan is not bound to the compiled model")
    replayed_verification = verify_result(compilation.problem, plan.result)
    if not plan.verification.verified or not replayed_verification.verified:
        raise ValueError("emitted plan failed independent verification")
    schedule_payload = dict(payloads["scheduling_result"])
    scheduling_problem = SchedulingProblem.model_validate(schedule_payload.pop("problem"))
    schedule = SchedulingResult.model_validate(schedule_payload)
    if scheduling_problem.plan_digest != compilation.problem.digest:
        raise ValueError("scheduling problem is not bound to the compiled model")
    if schedule.receipt.problem_digest != scheduling_problem.digest:
        raise ValueError("schedule receipt is not bound to the scheduling problem")
    if violations := verify_schedule_result(scheduling_problem, schedule):
        raise ValueError(f"schedule failed independent verification: {violations}")
    counterfactual = CounterfactualRun.model_validate(payloads["counterfactual_run"])
    if (
        counterfactual.base_model_digest != compilation.problem.digest
        or counterfactual.result.model_digest != counterfactual.variant_model_digest
        or counterfactual.result.receipt.model_digest != counterfactual.variant_model_digest
    ):
        raise ValueError("counterfactual is not bound to the compiled or variant model")
    stress_payload = dict(payloads["stress_report"])
    scenario_set = ScenarioSet.model_validate(stress_payload.pop("scenario_set"))
    stress = StressReport.model_validate(stress_payload)
    if stress.base_model_digest != compilation.problem.digest or any(
        outcome.result.model_digest != outcome.variant_model_digest
        or outcome.result.receipt.model_digest != outcome.variant_model_digest
        for outcome in stress.outcomes
    ):
        raise ValueError("stress scenario result is not bound to its variant model")
    if stress.scenario_set_digest != scenario_set.digest:
        raise ValueError("stress report is not bound to its scenario set")
    outcomes = {item.scenario_id: item for item in stress.outcomes}
    if set(outcomes) != {item.scenario_id for item in scenario_set.scenarios} or any(
        outcomes[item.scenario_id].probability != item.probability
        for item in scenario_set.scenarios
    ):
        raise ValueError("stress outcomes do not match the scenario set")
    losses = {
        item.scenario_id: item.result.objective_value
        for item in stress.outcomes
        if item.result.objective_value is not None
    }
    expected_risk = calculate_cvar(losses, scenario_set.scenarios, Decimal("0.95"))
    if stress.risk != expected_risk:
        raise ValueError("stress risk does not replay from scenario outcomes")
    explanation_payload = dict(payloads["deterministic_explanation"])
    explanation_evidence = PortfolioExplanationEvidence.model_validate(
        explanation_payload.pop("evidence")
    )
    explanation = PortfolioExplanation.model_validate(explanation_payload)
    if explanation.receipt.evidence_digest != explanation_evidence.evidence_digest:
        raise ValueError("explanation evidence digest is not bound to its verified evidence")
    if explanation.receipt.response_digest != stable_hash(
        explanation.draft.model_dump(mode="json")
    ):
        raise ValueError("explanation response digest does not authenticate its draft")
    if explanation.receipt.mode == "generative" and not explanation.candidate_only:
        raise ValueError("generative explanation cannot cross the candidate-only boundary")
    review = payloads["human_review_gate"]
    if review != {
        "run_id": run.run_id,
        "state": "pending_review",
        "advisory_only": True,
        "externally_authorized": False,
        "required_role": review.get("required_role"),
    } or not review.get("required_role"):
        raise ValueError("review gate must remain advisory, unauthorized, and pending")
    return run


def run_sample_portfolio() -> ResourcePortfolioWorkflowRun:
    """Execute the packaged reviewer-authored sample without retaining artifacts."""
    with TemporaryDirectory(prefix="ruler-resource-portfolio-") as temporary:
        return execute_resource_portfolio_workflow(SAMPLE_INPUT_DIR, Path(temporary))


def write_sample_portfolio_artifacts(output_dir: Path) -> Path:
    """Execute the packaged sample and return its verified run-manifest path."""
    execute_resource_portfolio_workflow(SAMPLE_INPUT_DIR, output_dir)
    return output_dir / "workflow_run.yaml"


__all__ = [
    "ResourcePortfolioWorkflowRun",
    "WorkflowArtifact",
    "WorkflowLimits",
    "build_evidence_snapshot",
    "execute_resource_portfolio_workflow",
    "run_sample_portfolio",
    "verify_workflow_artifacts",
    "write_sample_portfolio_artifacts",
]
