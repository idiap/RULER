# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""High-risk formalization mutation evidence and completeness gate."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from ruler.kb.behavioral_validation import BehavioralCase, evaluate_behavioral_cases
from ruler.kb.formalization import PredicateRegistry
from ruler.kb.logical_ir import LogicalProgram


class MutationOperator(StrEnum):
    """Material semantic mutations that release controls must kill."""

    NEGATION = "negation"
    CONNECTIVE = "conjunction_disjunction"
    COMPARISON = "comparison_operator"
    UNIT = "unit"
    CONSTANT = "constant"
    PRECEDENCE = "precedence"
    TEMPORAL_BOUND = "temporal_bound"
    SOURCE_LINK = "source_link"


REQUIRED_MUTATION_OPERATORS = frozenset(MutationOperator)


class MutationDetectorKind(StrEnum):
    """Independent control classes allowed to kill a mutant."""

    BEHAVIORAL = "behavioral_case"
    STATIC = "static_semantics"
    IMMUTABLE_RELEASE = "immutable_release"
    SOURCE_DRIFT = "source_drift"


class MutationDetection(BaseModel):
    """Auditable evidence that one control rejected a mutant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    detector_kind: MutationDetectorKind
    evidence_id: str
    detected: bool


class MutationTrial(BaseModel):
    """One content-distinct IR mutant and its detector evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trial_id: str
    operator: MutationOperator
    original_ir_sha256: str
    mutant_ir_sha256: str
    changed_paths: tuple[str, ...]
    detections: tuple[MutationDetection, ...]

    @model_validator(mode="after")
    def mutant_is_distinct_and_detected_by_the_right_control(self) -> "MutationTrial":
        if self.original_ir_sha256 == self.mutant_ir_sha256:
            raise ValueError("mutation trials must change the IR hash")
        if not self.changed_paths:
            raise ValueError("mutation trials must record changed IR paths")
        if not self.detections:
            raise ValueError("mutation trials require detector evidence")
        return self

    @property
    def killed(self) -> bool:
        detected = {item.detector_kind for item in self.detections if item.detected}
        if self.operator == MutationOperator.SOURCE_LINK:
            return bool(
                detected
                & {MutationDetectorKind.IMMUTABLE_RELEASE, MutationDetectorKind.SOURCE_DRIFT}
            )
        return bool(detected & {MutationDetectorKind.BEHAVIORAL, MutationDetectorKind.STATIC})


class MutationGateReport(BaseModel):
    """Completeness and survival report for all high-risk operators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trials: tuple[MutationTrial, ...]
    missing_operators: tuple[MutationOperator, ...]
    surviving_trial_ids: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return bool(self.trials) and not self.missing_operators and not self.surviving_trial_ids

    def require_passed(self) -> None:
        if not self.passed:
            raise ValueError("formalization mutation gate failed")


def mutation_trial(
    trial_id: str,
    operator: MutationOperator,
    original: LogicalProgram,
    mutant: LogicalProgram,
    detections: tuple[MutationDetection, ...],
) -> MutationTrial:
    """Bind detector evidence to the exact original and mutant IR revisions."""
    original_data = original.model_dump(mode="json")
    mutant_data = mutant.model_dump(mode="json")
    changed_paths = tuple(sorted(_changed_paths(original_data, mutant_data)))
    if not _operator_change_is_present(operator, original_data, mutant_data, changed_paths):
        raise ValueError(f"mutant does not implement the declared {operator.value} mutation")
    return MutationTrial(
        trial_id=trial_id,
        operator=operator,
        original_ir_sha256=original.sha256(),
        mutant_ir_sha256=mutant.sha256(),
        changed_paths=changed_paths,
        detections=detections,
    )


def evaluate_mutation_gate(trials: tuple[MutationTrial, ...]) -> MutationGateReport:
    """Require every high-risk operator and reject every surviving mutant."""
    covered = {trial.operator for trial in trials}
    missing = tuple(sorted(REQUIRED_MUTATION_OPERATORS - covered, key=lambda item: item.value))
    surviving = tuple(sorted(trial.trial_id for trial in trials if not trial.killed))
    return MutationGateReport(
        trials=trials,
        missing_operators=missing,
        surviving_trial_ids=surviving,
    )


def detect_behavioral_regression(
    original: LogicalProgram,
    mutant: LogicalProgram,
    cases: tuple[BehavioralCase, ...],
    *,
    registry: PredicateRegistry | None = None,
) -> MutationDetection:
    """Execute the same ground cases and report whether only the mutant regressed."""

    statement_ids = frozenset(item.statement_id for item in original.statements)
    families = frozenset(item.rule_family for item in cases)
    baseline = evaluate_behavioral_cases(
        original,
        cases,
        validated_statement_ids=statement_ids,
        material_statement_ids=frozenset(),
        required_rule_families=families,
        registry=registry,
    )
    changed = evaluate_behavioral_cases(
        mutant,
        cases,
        validated_statement_ids=frozenset(item.statement_id for item in mutant.statements),
        material_statement_ids=frozenset(),
        required_rule_families=families,
        registry=registry,
    )
    baseline_passed = all(item.passed for item in baseline.results)
    failed_ids = tuple(item.case_id for item in changed.results if not item.passed)
    evidence = ",".join(failed_ids) if failed_ids else "none"
    return MutationDetection(
        detector_kind=MutationDetectorKind.BEHAVIORAL,
        evidence_id=f"executed:{original.sha256()}:{mutant.sha256()}:{evidence}",
        detected=baseline_passed and bool(failed_ids),
    )


def detect_source_link_drift(original: LogicalProgram, mutant: LogicalProgram) -> MutationDetection:
    """Recompute exact provenance paths instead of accepting model self-criticism."""

    paths = tuple(
        sorted(
            path
            for path in _changed_paths(
                original.model_dump(mode="json"), mutant.model_dump(mode="json")
            )
            if ".provenance" in path
        )
    )
    return MutationDetection(
        detector_kind=MutationDetectorKind.SOURCE_DRIFT,
        evidence_id="source-paths:" + (",".join(paths) if paths else "none"),
        detected=bool(paths),
    )


def detect_static_reference_drift(
    operator: MutationOperator,
    original: LogicalProgram,
    mutant: LogicalProgram,
) -> MutationDetection:
    """Detect a declared mutation against the independently accepted reference IR."""

    original_data = original.model_dump(mode="json")
    mutant_data = mutant.model_dump(mode="json")
    paths = tuple(sorted(_changed_paths(original_data, mutant_data)))
    detected = _operator_change_is_present(operator, original_data, mutant_data, paths)
    return MutationDetection(
        detector_kind=(
            MutationDetectorKind.SOURCE_DRIFT
            if operator == MutationOperator.SOURCE_LINK
            else MutationDetectorKind.STATIC
        ),
        evidence_id=(
            f"reference-ir:{original.sha256()}:{operator.value}:"
            + (",".join(paths) if paths else "none")
        ),
        detected=detected,
    )


def _changed_paths(original: object, mutant: object, prefix: str = "$") -> set[str]:
    if type(original) is not type(mutant):
        return {prefix}
    if isinstance(original, dict) and isinstance(mutant, dict):
        paths: set[str] = set()
        for key in set(original) | set(mutant):
            path = f"{prefix}.{key}"
            if key not in original or key not in mutant:
                paths.add(path)
            else:
                paths.update(_changed_paths(original[key], mutant[key], path))
        return paths
    if isinstance(original, list) and isinstance(mutant, list):
        paths = set()
        for index in range(max(len(original), len(mutant))):
            path = f"{prefix}[{index}]"
            if index >= len(original) or index >= len(mutant):
                paths.add(path)
            else:
                paths.update(_changed_paths(original[index], mutant[index], path))
        return paths
    return set() if original == mutant else {prefix}


def _operator_change_is_present(
    operator: MutationOperator,
    original: dict[str, object],
    mutant: dict[str, object],
    paths: tuple[str, ...],
) -> bool:
    if operator == MutationOperator.NEGATION:
        return _body_kind_transition(original, mutant, {"negation"})
    if operator == MutationOperator.CONNECTIVE:
        return _body_kind_transition(original, mutant, {"conjunction", "disjunction"})
    if operator == MutationOperator.COMPARISON:
        return any(".comparison.operator" in path for path in paths)
    if operator == MutationOperator.UNIT:
        return any(path.endswith(".value_type") for path in paths)
    if operator == MutationOperator.CONSTANT:
        return any(path.endswith(".value") for path in paths)
    if operator == MutationOperator.PRECEDENCE:
        return _predicate_arguments_changed(original, mutant, "takes_precedence")
    if operator == MutationOperator.TEMPORAL_BOUND:
        return any(".temporal." in path for path in paths)
    if operator == MutationOperator.SOURCE_LINK:
        return any(".provenance" in path for path in paths)
    return False


def _body_kind_transition(
    original: dict[str, object],
    mutant: dict[str, object],
    required_kinds: set[str],
) -> bool:
    original_statements = original.get("statements", [])
    mutant_statements = mutant.get("statements", [])
    if not isinstance(original_statements, list) or not isinstance(mutant_statements, list):
        return False
    for before, after in zip(original_statements, mutant_statements, strict=False):
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        before_body = before.get("body")
        after_body = after.get("body")
        if not isinstance(before_body, dict) or not isinstance(after_body, dict):
            continue
        before_kind = before_body.get("kind")
        after_kind = after_body.get("kind")
        if before_kind != after_kind and {str(before_kind), str(after_kind)} >= required_kinds:
            return True
    return False


def _predicate_arguments_changed(
    original: dict[str, object],
    mutant: dict[str, object],
    predicate: str,
) -> bool:
    before = _predicate_arguments(original, predicate)
    after = _predicate_arguments(mutant, predicate)
    return bool(before and after and before != after)


def _predicate_arguments(payload: object, predicate: str) -> list[object] | None:
    if isinstance(payload, dict):
        if payload.get("predicate") == predicate and isinstance(payload.get("arguments"), list):
            return payload["arguments"]
        for value in payload.values():
            found = _predicate_arguments(value, predicate)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _predicate_arguments(value, predicate)
            if found is not None:
                return found
    return None
