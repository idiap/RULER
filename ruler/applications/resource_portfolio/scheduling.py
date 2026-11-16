# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Exact-integer interval scheduling backed by the real OR-Tools CP-SAT solver."""

from __future__ import annotations

import time
from importlib.metadata import version
from typing import Literal

from ortools.sat.python import cp_model
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.io import stable_hash


class ScheduleTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str
    project_id: str = "unassigned_project"
    location_id: str = "unspecified_location"
    duration: int = Field(gt=0)
    earliest_start: int = Field(ge=0)
    latest_end: int = Field(gt=0)
    eligible_resource_ids: tuple[str, ...] = Field(min_length=1)
    required_capability_ids: tuple[str, ...] = ()
    allowed_location_ids: tuple[str, ...] = ()
    capacity_demands: dict[str, int] = Field(default_factory=dict)
    optional: bool = False
    origin_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def window_fits(self) -> "ScheduleTask":
        if self.earliest_start + self.duration > self.latest_end:
            raise ValueError("task duration does not fit its scheduling window")
        if any(value <= 0 for value in self.capacity_demands.values()):
            raise ValueError("capacity demands must be positive exact integers")
        return self


class SchedulePrecedence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    predecessor_id: str
    successor_id: str
    minimum_lag: int = Field(default=0, ge=0)
    origin_ref: str


class FrozenAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str
    resource_id: str
    start: int = Field(ge=0)


class SchedulingProblem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["resource-scheduling/v1"] = "resource-scheduling/v1"
    schedule_id: str
    plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    time_unit: str
    tasks: tuple[ScheduleTask, ...] = Field(min_length=1)
    precedences: tuple[SchedulePrecedence, ...] = ()
    travel_time: dict[str, int] = Field(default_factory=dict)
    resource_capability_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    resource_location_ids: dict[str, str] = Field(default_factory=dict)
    capacity_limits: dict[str, int] = Field(default_factory=dict)
    frozen_assignments: tuple[FrozenAssignment, ...] = ()

    @model_validator(mode="after")
    def closed(self) -> "SchedulingProblem":
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task IDs must be unique")
        known = set(task_ids)
        for item in self.precedences:
            if item.predecessor_id not in known or item.successor_id not in known:
                raise ValueError("precedence references an unknown task")
        for item in self.frozen_assignments:
            task = next((task for task in self.tasks if task.task_id == item.task_id), None)
            if task is None or item.resource_id not in task.eligible_resource_ids:
                raise ValueError("frozen assignment is not eligible")
        demanded_pools = {pool for task in self.tasks for pool in task.capacity_demands}
        if demanded_pools - set(self.capacity_limits):
            raise ValueError("task references an undeclared capacity pool")
        if any(value <= 0 for value in self.capacity_limits.values()):
            raise ValueError("capacity limits must be positive exact integers")
        return self

    @property
    def digest(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class ScheduledAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str
    resource_id: str
    start: int
    end: int


class ScheduleReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    backend_id: Literal["ortools_cp_sat_intervals"] = "ortools_cp_sat_intervals"
    library_version: str
    problem_digest: str
    native_status: str
    seed: int
    workers: int
    conflicts: int
    branches: int


class SchedulingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schedule_id: str
    status: Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "TIME_LIMIT", "ERROR"]
    assignments: tuple[ScheduledAssignment, ...] = ()
    unassigned_task_ids: tuple[str, ...] = ()
    objective_value: int | None = None
    runtime_seconds: float
    receipt: ScheduleReceipt


def verify_schedule_result(problem: SchedulingProblem, result: SchedulingResult) -> tuple[str, ...]:
    """Independently check a returned schedule without trusting CP-SAT telemetry."""
    violations: list[str] = []
    if result.schedule_id != problem.schedule_id:
        violations.append("schedule_id")
    if result.status not in {"OPTIMAL", "FEASIBLE"}:
        return tuple(violations)
    tasks = {item.task_id: item for item in problem.tasks}
    assignments = {item.task_id: item for item in result.assignments}
    if len(assignments) != len(result.assignments):
        violations.append("duplicate_task_assignment")
    unknown = set(assignments) - set(tasks)
    if unknown:
        violations.append("unknown_task")
    for task_id, assignment in assignments.items():
        if task_id not in tasks:
            continue
        task = tasks[task_id]
        if assignment.resource_id not in task.eligible_resource_ids:
            violations.append(f"ineligible_resource:{task_id}")
        if assignment.start < task.earliest_start or assignment.end > task.latest_end:
            violations.append(f"window:{task_id}")
        if assignment.end - assignment.start != task.duration:
            violations.append(f"duration:{task_id}")
        capabilities = set(problem.resource_capability_ids.get(assignment.resource_id, ()))
        if set(task.required_capability_ids) - capabilities:
            violations.append(f"capability:{task_id}")
        location = problem.resource_location_ids.get(assignment.resource_id)
        if task.allowed_location_ids and location not in task.allowed_location_ids:
            violations.append(f"location:{task_id}")
    required = {item.task_id for item in problem.tasks if not item.optional}
    if missing := required - set(assignments):
        violations.extend(f"missing_required:{item}" for item in sorted(missing))
    expected_unassigned = set(tasks) - set(assignments)
    if set(result.unassigned_task_ids) != expected_unassigned:
        violations.append("unassigned_task_ids")
    for frozen in problem.frozen_assignments:
        assigned = assignments.get(frozen.task_id)
        if assigned is None or (assigned.resource_id, assigned.start) != (
            frozen.resource_id,
            frozen.start,
        ):
            violations.append(f"frozen:{frozen.task_id}")
    for precedence in problem.precedences:
        before = assignments.get(precedence.predecessor_id)
        after = assignments.get(precedence.successor_id)
        if before and after and after.start < before.end + precedence.minimum_lag:
            violations.append(f"precedence:{precedence.predecessor_id}:{precedence.successor_id}")
    by_resource: dict[str, list[ScheduledAssignment]] = {}
    for assignment in assignments.values():
        by_resource.setdefault(assignment.resource_id, []).append(assignment)
    for resource_id, items in by_resource.items():
        ordered = sorted(items, key=lambda item: (item.start, item.task_id))
        for before, after in zip(ordered, ordered[1:]):
            if after.start < before.end + _travel(problem, before.task_id, after.task_id):
                violations.append(f"overlap_or_travel:{resource_id}")
    if assignments:
        start = min(item.start for item in assignments.values())
        end = max(item.end for item in assignments.values())
        for pool_id, limit in problem.capacity_limits.items():
            for instant in range(start, end):
                demand = sum(
                    tasks[item.task_id].capacity_demands.get(pool_id, 0)
                    for item in assignments.values()
                    if item.start <= instant < item.end and item.task_id in tasks
                )
                if demand > limit:
                    violations.append(f"capacity:{pool_id}:{instant}")
    return tuple(sorted(set(violations)))


def _travel(problem: SchedulingProblem, before: str, after: str) -> int:
    return problem.travel_time.get(f"{before}->{after}", 0)


def solve_schedule(
    problem: SchedulingProblem,
    *,
    time_limit_seconds: float | None = None,
    seed: int = 0,
) -> SchedulingResult:
    """Schedule optional assignments and resource no-overlap with CP-SAT.

    Pairwise ordering constraints incorporate declared task-to-task travel time
    whenever two tasks use the same resource.
    """
    model = cp_model.CpModel()
    starts = {
        task.task_id: model.new_int_var(
            task.earliest_start, task.latest_end - task.duration, f"start__{task.task_id}"
        )
        for task in problem.tasks
    }
    ends = {
        task.task_id: model.new_int_var(
            task.earliest_start + task.duration, task.latest_end, f"end__{task.task_id}"
        )
        for task in problem.tasks
    }
    present: dict[tuple[str, str], cp_model.IntVar] = {}
    choices_by_task: dict[str, list[cp_model.IntVar]] = {}
    task_selected: dict[str, cp_model.IntVar] = {}
    task_intervals: dict[str, cp_model.IntervalVar] = {}
    intervals_by_resource: dict[str, list] = {}
    for task in problem.tasks:
        model.add(ends[task.task_id] == starts[task.task_id] + task.duration)
        choices = []
        for resource_id in task.eligible_resource_ids:
            selected = model.new_bool_var(f"assigned__{task.task_id}__{resource_id}")
            interval = model.new_optional_interval_var(
                starts[task.task_id],
                task.duration,
                ends[task.task_id],
                selected,
                f"interval__{task.task_id}__{resource_id}",
            )
            present[(task.task_id, resource_id)] = selected
            intervals_by_resource.setdefault(resource_id, []).append(interval)
            choices.append(selected)
            resource_capabilities = set(problem.resource_capability_ids.get(resource_id, ()))
            if set(task.required_capability_ids) - resource_capabilities:
                model.add(selected == 0)
            resource_location = problem.resource_location_ids.get(resource_id)
            if task.allowed_location_ids and resource_location not in task.allowed_location_ids:
                model.add(selected == 0)
        choices_by_task[task.task_id] = choices
        if task.optional:
            selected = model.new_bool_var(f"selected__{task.task_id}")
            model.add(selected == sum(choices))
            task_intervals[task.task_id] = model.new_optional_interval_var(
                starts[task.task_id],
                task.duration,
                ends[task.task_id],
                selected,
                f"capacity_interval__{task.task_id}",
            )
        else:
            selected = model.new_constant(1)
            model.add(sum(choices) == 1)
            task_intervals[task.task_id] = model.new_interval_var(
                starts[task.task_id],
                task.duration,
                ends[task.task_id],
                f"capacity_interval__{task.task_id}",
            )
        task_selected[task.task_id] = selected
    for intervals in intervals_by_resource.values():
        model.add_no_overlap(intervals)
    for pool_id, limit in problem.capacity_limits.items():
        pool_tasks = [task for task in problem.tasks if pool_id in task.capacity_demands]
        if pool_tasks:
            model.add_cumulative(
                [task_intervals[task.task_id] for task in pool_tasks],
                [task.capacity_demands[pool_id] for task in pool_tasks],
                limit,
            )
    # NoOverlap prevents collision; these disjunctions add asymmetric movement lag.
    for resource_id in intervals_by_resource:
        eligible = [task for task in problem.tasks if resource_id in task.eligible_resource_ids]
        for left_index, left in enumerate(eligible):
            for right in eligible[left_index + 1 :]:
                left_first = model.new_bool_var(
                    f"order__{left.task_id}__{right.task_id}__{resource_id}"
                )
                both = [present[(left.task_id, resource_id)], present[(right.task_id, resource_id)]]
                model.add(
                    starts[right.task_id]
                    >= ends[left.task_id] + _travel(problem, left.task_id, right.task_id)
                ).only_enforce_if([*both, left_first])
                model.add(
                    starts[left.task_id]
                    >= ends[right.task_id] + _travel(problem, right.task_id, left.task_id)
                ).only_enforce_if([*both, left_first.negated()])
    for precedence in problem.precedences:
        relation = model.add(
            starts[precedence.successor_id]
            >= ends[precedence.predecessor_id] + precedence.minimum_lag
        )
        enforcement = []
        predecessor = next(
            task for task in problem.tasks if task.task_id == precedence.predecessor_id
        )
        successor = next(task for task in problem.tasks if task.task_id == precedence.successor_id)
        if predecessor.optional:
            enforcement.append(task_selected[predecessor.task_id])
        if successor.optional:
            enforcement.append(task_selected[successor.task_id])
        if enforcement:
            relation.only_enforce_if(enforcement)
    for frozen in problem.frozen_assignments:
        model.add(present[(frozen.task_id, frozen.resource_id)] == 1)
        model.add(starts[frozen.task_id] == frozen.start)
    optional_presence = [task_selected[task.task_id] for task in problem.tasks if task.optional]
    makespan = model.new_int_var(0, max(task.latest_end for task in problem.tasks), "makespan")
    model.add_max_equality(makespan, list(ends.values()))
    # Missing an optional task dominates makespan minimization.
    horizon = max(task.latest_end for task in problem.tasks)
    model.minimize(makespan + horizon * (len(optional_presence) - sum(optional_presence)))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    if time_limit_seconds is not None:
        solver.parameters.max_time_in_seconds = time_limit_seconds
    start_time = time.monotonic()
    native = solver.solve(model)
    runtime = time.monotonic() - start_time
    native_name = solver.status_name(native)
    status = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "TIME_LIMIT" if time_limit_seconds is not None else "ERROR",
    }.get(native, "ERROR")
    assignments: list[ScheduledAssignment] = []
    unassigned: list[str] = []
    if native in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        for task in problem.tasks:
            selected = next(
                (
                    resource_id
                    for resource_id in task.eligible_resource_ids
                    if solver.boolean_value(present[(task.task_id, resource_id)])
                ),
                None,
            )
            if selected is None:
                unassigned.append(task.task_id)
            else:
                assignments.append(
                    ScheduledAssignment(
                        task_id=task.task_id,
                        resource_id=selected,
                        start=solver.value(starts[task.task_id]),
                        end=solver.value(ends[task.task_id]),
                    )
                )
    receipt = ScheduleReceipt(
        library_version=version("ortools"),
        problem_digest=problem.digest,
        native_status=native_name,
        seed=seed,
        workers=1,
        conflicts=solver.num_conflicts,
        branches=solver.num_branches,
    )
    return SchedulingResult.model_validate(
        dict(
            schedule_id=problem.schedule_id,
            status=status,
            assignments=tuple(sorted(assignments, key=lambda item: item.task_id)),
            unassigned_task_ids=tuple(sorted(unassigned)),
            objective_value=(
                int(round(solver.objective_value))
                if native in {cp_model.OPTIMAL, cp_model.FEASIBLE}
                else None
            ),
            runtime_seconds=runtime,
            receipt=receipt,
        )
    )
