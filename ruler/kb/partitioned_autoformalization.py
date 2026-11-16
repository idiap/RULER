# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic partitioning and merging for large autoformalization requests.

Each partition receives a compact source made only from one predicate family's exact
claim anchors. Generated spans are uniquely re-anchored into the complete source.
Every partition executes the normal producer/deterministic-critic/blind-critic loop.
Only converged, source-grounded candidates are namespaced and reparsed as one complete
candidate; the deterministic merge never impersonates a model provider.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from collections.abc import Callable, Iterable
from typing import Any, Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256
from ruler.io import stable_hash
from ruler.kb.asp_compiler import compile_asp
from ruler.kb.autoformalization_refinement import (
    ContinuousRefinementRun,
    RefinementFinding,
    build_refinement_finding,
    run_continuous_autoformalization_refinement,
)
from ruler.kb.generative_autoformalization import (
    AutoformalizationCandidate,
    AutoformalizationRequest,
    GenerativeTransport,
    parse_autoformalization_candidate,
)
from ruler.kb.logical_ir import Atom, Constant, ExpressionKind, LogicalExpression, Variable
from ruler.kb.prolog_compiler import compile_prolog

PARTITION_PROTOCOL_VERSION = "claim-partitioned-autoformalization-v1"


class PartitionClaim(StrictContract):
    """Reviewer-authored exact source anchor assigned to one predicate family."""

    claim_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")
    predicate: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    exact_text: str = Field(min_length=1)
    expected_constant_values: tuple[str | int, ...] = ()
    expected_body_constant_values: tuple[tuple[str | int, ...], ...] = ()
    required: Literal[True] = True


class ClaimPartition(StrictContract):
    """One deterministic claim-family work unit over the complete source."""

    partition_id: str = Field(pattern=r"^partition-[0-9]{3}$")
    ordinal: int = Field(ge=1)
    predicate: str
    claim_ids: tuple[str, ...] = Field(min_length=1)
    guidance: tuple[str, ...] = Field(min_length=1)
    partition_source_sha256: str
    source_character_count: int = Field(ge=1)
    assignment_sha256: str

    @model_validator(mode="after")
    def assignment_is_bound(self) -> "ClaimPartition":
        validate_sha256(self.assignment_sha256)
        validate_sha256(self.partition_source_sha256)
        expected = stable_hash(
            {
                "partition_id": self.partition_id,
                "ordinal": self.ordinal,
                "predicate": self.predicate,
                "claim_ids": self.claim_ids,
                "guidance": self.guidance,
                "partition_source_sha256": self.partition_source_sha256,
                "source_character_count": self.source_character_count,
            }
        )
        if self.assignment_sha256 != expected:
            raise ValueError("partition assignment digest mismatch")
        return self


class AutoformalizationPartitionPlan(StrictContract):
    """Content-addressed, total partition of exact source claims."""

    protocol_version: Literal["claim-partitioned-autoformalization-v1"] = PARTITION_PROTOCOL_VERSION
    source_artifact_sha256: str
    request_sha256: str
    claim_sha256: str
    max_claims_per_partition: int = Field(ge=1, le=64)
    claim_ids: tuple[str, ...] = Field(min_length=1)
    partitions: tuple[ClaimPartition, ...] = Field(min_length=1)
    plan_sha256: str

    @model_validator(mode="after")
    def plan_is_total_and_content_addressed(self) -> "AutoformalizationPartitionPlan":
        for value in (
            self.source_artifact_sha256,
            self.request_sha256,
            self.claim_sha256,
            self.plan_sha256,
        ):
            validate_sha256(value)
        assigned = [claim for part in self.partitions for claim in part.claim_ids]
        if len(assigned) != len(set(assigned)):
            raise ValueError("a claim cannot be assigned to multiple partitions")
        if set(assigned) != set(self.claim_ids) or len(assigned) != len(self.claim_ids):
            raise ValueError("partition plan must assign every claim exactly once")
        if tuple(item.ordinal for item in self.partitions) != tuple(
            range(1, len(self.partitions) + 1)
        ):
            raise ValueError("partition ordinals must be contiguous")
        expected = stable_hash(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("plan_sha256 must identify the complete partition plan")
        return self


class PartitionExecutionReceipt(StrictContract):
    """Typed binding from a plan assignment to its complete refinement run."""

    partition_id: str
    predicate: str
    claim_ids: tuple[str, ...] = Field(min_length=1)
    child_request: AutoformalizationRequest
    child_request_sha256: str
    refinement_run: ContinuousRefinementRun
    refinement_run_sha256: str
    candidate_sha256: str
    producer_provider: str
    critic_provider: str
    terminal_status: Literal["converged"] = "converged"

    @model_validator(mode="after")
    def receipt_is_cross_bound(self) -> "PartitionExecutionReceipt":
        for value in (
            self.child_request_sha256,
            self.refinement_run_sha256,
            self.candidate_sha256,
        ):
            validate_sha256(value)
        if self.child_request_sha256 != stable_hash(self.child_request.model_dump(mode="json")):
            raise ValueError("child request digest mismatch")
        if self.refinement_run_sha256 != self.refinement_run.run_sha256:
            raise ValueError("partition receipt does not bind the refinement run")
        if self.refinement_run.terminal_status != "converged":
            raise ValueError("only converged partitions can enter a merge receipt")
        if self.refinement_run.request_sha256 != self.child_request_sha256:
            raise ValueError("refinement run is not bound to the child request")
        if self.refinement_run.source_artifact_sha256 != self.child_request.artifact_sha256:
            raise ValueError("refinement run is not bound to the child source")
        candidate = self.refinement_run.final_candidate
        if candidate is None or self.candidate_sha256 != stable_hash(
            candidate.model_dump(mode="json")
        ):
            raise ValueError("partition candidate digest mismatch")
        if candidate.request_id != self.child_request.request_id:
            raise ValueError("partition candidate request identity mismatch")
        if candidate.receipt.request_sha256 != self.child_request_sha256:
            raise ValueError("partition candidate receipt is not bound to child request")
        if candidate.receipt.source_artifact_sha256 != self.child_request.artifact_sha256:
            raise ValueError("partition candidate receipt is not bound to child source")
        if self.producer_provider != candidate.receipt.provider:
            raise ValueError("partition producer provider mismatch")
        critic_receipts = [
            item.critic_receipt
            for item in self.refinement_run.iterations
            if item.critic_receipt is not None
        ]
        if not critic_receipts or critic_receipts[-1].provider != self.critic_provider:
            raise ValueError("partition critic provider mismatch")
        return self


class DeterministicMergeReceipt(StrictContract):
    """Evidence that aggregation was deterministic and had no provider authority."""

    merge_engine: Literal["ruler_deterministic_candidate_merge_v1"] = (
        "ruler_deterministic_candidate_merge_v1"
    )
    provider_authority: Literal["none_deterministic_merge"] = "none_deterministic_merge"
    plan_sha256: str
    child_run_sha256s: tuple[str, ...] = Field(min_length=1)
    namespace_map_sha256: str
    merged_draft_sha256: str
    final_candidate_sha256: str
    compiler: Literal["clingo_asp", "prolog"]
    compiler_version: str
    compiled_program_sha256: str
    merge_sha256: str

    @model_validator(mode="after")
    def merge_is_content_addressed(self) -> "DeterministicMergeReceipt":
        for value in (
            self.plan_sha256,
            *self.child_run_sha256s,
            self.namespace_map_sha256,
            self.merged_draft_sha256,
            self.final_candidate_sha256,
            self.compiled_program_sha256,
            self.merge_sha256,
        ):
            validate_sha256(value)
        expected = stable_hash(self.model_dump(mode="json", exclude={"merge_sha256"}))
        if self.merge_sha256 != expected:
            raise ValueError("merge_sha256 must identify the complete merge receipt")
        return self


class PartitionedAutoformalizationRun(StrictContract):
    """Successful end-to-end partition execution and globally validated candidate."""

    protocol_version: Literal["claim-partitioned-autoformalization-v1"] = PARTITION_PROTOCOL_VERSION
    request: AutoformalizationRequest
    claims: tuple[PartitionClaim, ...] = Field(min_length=1)
    plan: AutoformalizationPartitionPlan
    partition_receipts: tuple[PartitionExecutionReceipt, ...] = Field(min_length=1)
    candidate: AutoformalizationCandidate
    merge_receipt: DeterministicMergeReceipt
    terminal_status: Literal["converged"] = "converged"
    lifecycle: Literal["candidate_uncommitted"] = "candidate_uncommitted"
    activation_status: Literal["blocked"] = "blocked"
    solver_use_permitted: Literal[False] = False
    run_sha256: str

    @model_validator(mode="after")
    def run_is_total_and_bound(self) -> "PartitionedAutoformalizationRun":
        validate_sha256(self.run_sha256)
        if tuple(item.partition_id for item in self.partition_receipts) != tuple(
            item.partition_id for item in self.plan.partitions
        ):
            raise ValueError("partition receipts do not exactly follow the plan")
        if self.merge_receipt.plan_sha256 != self.plan.plan_sha256:
            raise ValueError("merge receipt is not bound to the plan")
        child_runs = tuple(item.refinement_run_sha256 for item in self.partition_receipts)
        if self.merge_receipt.child_run_sha256s != child_runs:
            raise ValueError("merge receipt does not bind every child run in order")
        candidate_sha256 = stable_hash(self.candidate.model_dump(mode="json"))
        if self.merge_receipt.final_candidate_sha256 != candidate_sha256:
            raise ValueError("merge receipt is not bound to the final candidate")
        if self.candidate.lifecycle != self.lifecycle:
            raise ValueError("merged candidate crossed the lifecycle boundary")
        if self.candidate.projection.activation_status != self.activation_status:
            raise ValueError("merged candidate crossed the activation boundary")
        _verify_run_evidence(self)
        expected = stable_hash(self.model_dump(mode="json", exclude={"run_sha256"}))
        if self.run_sha256 != expected:
            raise ValueError("run_sha256 must identify the complete partitioned run")
        return self


class PartitionedAutoformalizationError(ValueError):
    """A partition failed closed before deterministic aggregation."""

    def __init__(
        self,
        message: str,
        *,
        partition_id: str | None = None,
        refinement_run: ContinuousRefinementRun | None = None,
        completed_receipts: tuple[PartitionExecutionReceipt, ...] = (),
    ) -> None:
        super().__init__(message)
        self.partition_id = partition_id
        self.refinement_run = refinement_run
        self.completed_receipts = completed_receipts


def build_claim_partition_plan(
    request: AutoformalizationRequest,
    claims: tuple[PartitionClaim, ...],
    *,
    max_claims_per_partition: int = 8,
) -> AutoformalizationPartitionPlan:
    """Partition claims by reviewed predicate order and then fixed-size chunks."""

    if not 1 <= max_claims_per_partition <= 64:
        raise ValueError("max_claims_per_partition must be between 1 and 64")
    if not claims:
        raise ValueError("partitioned autoformalization requires at least one claim")
    claim_ids = [item.claim_id for item in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("partition claim identifiers must be unique")
    anchors: list[tuple[int, PartitionClaim]] = []
    allowed = set(request.allowed_predicates)
    for claim in claims:
        if claim.predicate not in allowed:
            raise ValueError(f"claim {claim.claim_id} uses an unreviewed predicate")
        start = request.source_text.find(claim.exact_text)
        if start < 0:
            raise ValueError(f"claim {claim.claim_id} is missing from the source")
        if request.source_text.find(claim.exact_text, start + 1) >= 0:
            raise ValueError(f"claim {claim.claim_id} source anchor is not unique")
        anchors.append((start, claim))

    by_predicate: dict[str, list[tuple[int, PartitionClaim]]] = {
        predicate: [] for predicate in request.allowed_predicates
    }
    for anchor in anchors:
        by_predicate[anchor[1].predicate].append(anchor)
    partitions: list[ClaimPartition] = []
    for predicate in request.allowed_predicates:
        ordered = [item for _, item in sorted(by_predicate[predicate], key=lambda pair: pair[0])]
        for offset in range(0, len(ordered), max_claims_per_partition):
            chunk = ordered[offset : offset + max_claims_per_partition]
            ordinal = len(partitions) + 1
            partition_id = f"partition-{ordinal:03d}"
            claim_list = ", ".join(item.claim_id for item in chunk)
            guidance = (
                f"This partition is limited to predicate {predicate!r}.",
                f"Formalize every assigned claim exactly once: {claim_list}.",
                "Use only the exact assigned claim text as semantic source spans; ignore all other source statements in this partition.",
            )
            partition_source = _partition_source(tuple(chunk))
            assignment = {
                "partition_id": partition_id,
                "ordinal": ordinal,
                "predicate": predicate,
                "claim_ids": tuple(item.claim_id for item in chunk),
                "guidance": guidance,
                "partition_source_sha256": _sha256_text(partition_source),
                "source_character_count": len(partition_source),
            }
            partitions.append(
                ClaimPartition(**assignment, assignment_sha256=stable_hash(assignment))
            )
    payload = {
        "protocol_version": PARTITION_PROTOCOL_VERSION,
        "source_artifact_sha256": request.artifact_sha256,
        "request_sha256": stable_hash(request.model_dump(mode="json")),
        "claim_sha256": stable_hash([item.model_dump(mode="json") for item in claims]),
        "max_claims_per_partition": max_claims_per_partition,
        "claim_ids": tuple(claim_ids),
        "partitions": tuple(partitions),
    }
    serialized = {
        **payload,
        "partitions": [item.model_dump(mode="json") for item in partitions],
    }
    return AutoformalizationPartitionPlan(**payload, plan_sha256=stable_hash(serialized))


def run_partitioned_autoformalization(
    request: AutoformalizationRequest,
    claims: tuple[PartitionClaim, ...],
    producer_transport: GenerativeTransport,
    critic_transport: GenerativeTransport,
    *,
    max_claims_per_partition: int = 8,
    maximum_iterations: int = 3,
    max_workers: int = 1,
    additional_deterministic_critic: (
        Callable[
            [AutoformalizationRequest, AutoformalizationCandidate],
            Iterable[RefinementFinding],
        ]
        | None
    ) = None,
) -> PartitionedAutoformalizationRun:
    """Execute every claim partition and merge only globally valid candidates."""

    plan = build_claim_partition_plan(
        request, claims, max_claims_per_partition=max_claims_per_partition
    )
    if not 1 <= max_workers <= 16:
        raise ValueError("max_workers must be between 1 and 16")
    claims_by_id = {item.claim_id: item for item in claims}

    def execute(
        partition: ClaimPartition,
    ) -> tuple[PartitionExecutionReceipt, AutoformalizationCandidate]:
        assigned = tuple(claims_by_id[item] for item in partition.claim_ids)
        child_request = _child_request(request, partition, assigned)

        def deterministic_critic(
            candidate: AutoformalizationCandidate,
        ) -> tuple[RefinementFinding, ...]:
            additional = (
                tuple(additional_deterministic_critic(child_request, candidate))
                if additional_deterministic_critic is not None
                else ()
            )
            return _claim_partition_findings(candidate, assigned) + additional

        refinement = run_continuous_autoformalization_refinement(
            child_request,
            producer_transport,
            deterministic_critic=deterministic_critic,
            critic_transport=critic_transport,
            maximum_iterations=maximum_iterations,
        )
        if refinement.terminal_status != "converged" or refinement.final_candidate is None:
            raise PartitionedAutoformalizationError(
                f"partition {partition.partition_id} did not converge",
                partition_id=partition.partition_id,
                refinement_run=refinement,
            )
        candidate = refinement.final_candidate
        _assert_partition_claims(candidate, assigned)
        receipt = PartitionExecutionReceipt(
            partition_id=partition.partition_id,
            predicate=partition.predicate,
            claim_ids=partition.claim_ids,
            child_request=child_request,
            child_request_sha256=stable_hash(child_request.model_dump(mode="json")),
            refinement_run=refinement,
            refinement_run_sha256=refinement.run_sha256,
            candidate_sha256=stable_hash(candidate.model_dump(mode="json")),
            producer_provider=candidate.receipt.provider,
            critic_provider=critic_transport.provider,
        )
        return receipt, candidate

    results: dict[str, tuple[PartitionExecutionReceipt, AutoformalizationCandidate]] = {}
    failures: list[PartitionedAutoformalizationError] = []
    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures: dict[
        Future[tuple[PartitionExecutionReceipt, AutoformalizationCandidate]],
        ClaimPartition,
    ] = {executor.submit(execute, partition): partition for partition in plan.partitions}
    done, pending = wait(futures, return_when=FIRST_EXCEPTION)
    if any(future.exception() is not None for future in done):
        for future in pending:
            future.cancel()
    executor.shutdown(wait=True, cancel_futures=True)
    for future, partition in futures.items():
        if future.cancelled() or not future.done():
            continue
        try:
            results[partition.partition_id] = future.result()
        except PartitionedAutoformalizationError as exc:
            failures.append(exc)
        except Exception as exc:
            failures.append(
                PartitionedAutoformalizationError(
                    f"partition {partition.partition_id} execution failed closed: "
                    f"{exc.__class__.__name__}",
                    partition_id=partition.partition_id,
                )
            )
    if failures:
        completed = tuple(
            results[item.partition_id][0]
            for item in plan.partitions
            if item.partition_id in results
        )
        failure = min(
            failures,
            key=lambda item: next(
                part.ordinal for part in plan.partitions if part.partition_id == item.partition_id
            ),
        )
        raise PartitionedAutoformalizationError(
            str(failure),
            partition_id=failure.partition_id,
            refinement_run=failure.refinement_run,
            completed_receipts=completed,
        ) from failure
    if len(results) != len(plan.partitions):
        raise PartitionedAutoformalizationError(
            "partition execution was cancelled before complete evidence was collected",
            completed_receipts=tuple(
                results[item.partition_id][0]
                for item in plan.partitions
                if item.partition_id in results
            ),
        )
    receipts = [results[item.partition_id][0] for item in plan.partitions]
    candidates = [(item, results[item.partition_id][1]) for item in plan.partitions]

    merged_draft, namespace_map = _merged_draft(request, candidates)
    merge_prompt = f"deterministic merge of partition plan {plan.plan_sha256}; no provider invoked"
    merged = parse_autoformalization_candidate(
        request,
        merged_draft,
        provider="deterministic-partition-merge",
        model="not-applicable",
        prompt=merge_prompt,
        attempts=1,
        timeout_seconds=1,
    )
    _assert_global_claims(merged, claims)
    if request.target_formalism == "asp":
        compiled = compile_asp(merged.logical_program, request.predicate_registry)
        compiler = "clingo_asp"
    else:
        compiled = compile_prolog(merged.logical_program, request.predicate_registry)
        compiler = "prolog"
    merge_payload = {
        "merge_engine": "ruler_deterministic_candidate_merge_v1",
        "provider_authority": "none_deterministic_merge",
        "plan_sha256": plan.plan_sha256,
        "child_run_sha256s": tuple(item.refinement_run_sha256 for item in receipts),
        "namespace_map_sha256": stable_hash(namespace_map),
        "merged_draft_sha256": stable_hash(merged_draft),
        "final_candidate_sha256": stable_hash(merged.model_dump(mode="json")),
        "compiler": compiler,
        "compiler_version": compiled.compiler_version,
        "compiled_program_sha256": compiled.sha256,
    }
    merge_receipt = DeterministicMergeReceipt(
        **merge_payload, merge_sha256=stable_hash(merge_payload)
    )
    run_payload = {
        "protocol_version": PARTITION_PROTOCOL_VERSION,
        "request": request,
        "claims": claims,
        "plan": plan,
        "partition_receipts": tuple(receipts),
        "candidate": merged,
        "merge_receipt": merge_receipt,
        "terminal_status": "converged",
        "lifecycle": "candidate_uncommitted",
        "activation_status": "blocked",
        "solver_use_permitted": False,
    }
    serialized = {
        "protocol_version": PARTITION_PROTOCOL_VERSION,
        "request": request.model_dump(mode="json"),
        "claims": [item.model_dump(mode="json") for item in claims],
        "plan": plan.model_dump(mode="json"),
        "partition_receipts": [item.model_dump(mode="json") for item in receipts],
        "candidate": merged.model_dump(mode="json"),
        "merge_receipt": merge_receipt.model_dump(mode="json"),
        "terminal_status": "converged",
        "lifecycle": "candidate_uncommitted",
        "activation_status": "blocked",
        "solver_use_permitted": False,
    }
    return PartitionedAutoformalizationRun(**run_payload, run_sha256=stable_hash(serialized))


def verify_partitioned_autoformalization_run(
    run: PartitionedAutoformalizationRun,
) -> None:
    """Recompute partition, merge, source, and compiler evidence from run contents."""

    _verify_run_evidence(run)


def _child_request(
    request: AutoformalizationRequest,
    partition: ClaimPartition,
    claims: tuple[PartitionClaim, ...],
) -> AutoformalizationRequest:
    source_text = _partition_source(claims)
    payload = request.model_dump(mode="json")
    payload.update(
        {
            "request_id": f"{request.request_id}:{partition.partition_id}",
            "artifact_id": f"{request.artifact_id}#{partition.partition_id}",
            "artifact_sha256": _sha256_text(source_text),
            "source_text": source_text,
            "guidance": tuple(request.guidance)
            + partition.guidance
            + tuple(f"ASSIGNED_CLAIM {item.claim_id}: {item.exact_text}" for item in claims),
        }
    )
    return AutoformalizationRequest.model_validate(payload)


def _verify_run_evidence(run: PartitionedAutoformalizationRun) -> None:
    expected_plan = build_claim_partition_plan(
        run.request,
        run.claims,
        max_claims_per_partition=run.plan.max_claims_per_partition,
    )
    if run.plan != expected_plan:
        raise ValueError("partition plan does not match the bound request and claims")
    claims_by_id = {item.claim_id: item for item in run.claims}
    child_candidates: list[tuple[ClaimPartition, AutoformalizationCandidate]] = []
    for partition, receipt in zip(run.plan.partitions, run.partition_receipts, strict=True):
        assigned = tuple(claims_by_id[item] for item in partition.claim_ids)
        if receipt.predicate != partition.predicate or receipt.claim_ids != partition.claim_ids:
            raise ValueError("partition receipt assignment metadata mismatch")
        expected_request = _child_request(run.request, partition, assigned)
        if receipt.child_request != expected_request:
            raise ValueError("partition child request does not match its assignment")
        candidate = receipt.refinement_run.final_candidate
        assert candidate is not None
        _assert_partition_claims(candidate, assigned)
        child_candidates.append((partition, candidate))
    merged_draft, namespace_map = _merged_draft(run.request, child_candidates)
    if run.merge_receipt.namespace_map_sha256 != stable_hash(namespace_map):
        raise ValueError("merge namespace evidence mismatch")
    if run.merge_receipt.merged_draft_sha256 != stable_hash(merged_draft):
        raise ValueError("merged draft evidence mismatch")
    expected_candidate = parse_autoformalization_candidate(
        run.request,
        merged_draft,
        provider="deterministic-partition-merge",
        model="not-applicable",
        prompt=(
            f"deterministic merge of partition plan {run.plan.plan_sha256}; " "no provider invoked"
        ),
        attempts=1,
        timeout_seconds=1,
    )
    if run.candidate != expected_candidate:
        raise ValueError("merged candidate is not the deterministic child aggregation")
    _assert_global_claims(run.candidate, run.claims)
    if run.request.target_formalism == "asp":
        compiled = compile_asp(run.candidate.logical_program, run.request.predicate_registry)
        expected_compiler = "clingo_asp"
    else:
        compiled = compile_prolog(run.candidate.logical_program, run.request.predicate_registry)
        expected_compiler = "prolog"
    if (
        run.merge_receipt.compiler != expected_compiler
        or run.merge_receipt.compiler_version != compiled.compiler_version
        or run.merge_receipt.compiled_program_sha256 != compiled.sha256
    ):
        raise ValueError("global compiler evidence mismatch")


def _claim_partition_findings(
    candidate: AutoformalizationCandidate,
    claims: tuple[PartitionClaim, ...],
) -> tuple[RefinementFinding, ...]:
    try:
        _assert_partition_claims(candidate, claims)
    except ValueError as exc:
        return (
            build_refinement_finding(
                origin="deterministic",
                stage="coverage",
                severity="blocker",
                code="partition_claim_coverage_invalid",
                summary=" ".join(str(exc).split())[:600],
                repair_instruction=(
                    "Formalize every assigned exact claim and no unassigned source span."
                ),
                evidence={
                    "claims": [item.model_dump(mode="json") for item in claims],
                    "candidate": stable_hash(candidate.model_dump(mode="json")),
                    "error": " ".join(str(exc).split())[:600],
                },
            ),
        )
    return ()


def _assert_partition_claims(
    candidate: AutoformalizationCandidate, claims: tuple[PartitionClaim, ...]
) -> None:
    spans = {item.span_id: item for item in candidate.semantic_basis.spans}
    matched: dict[str, set[str]] = {item.claim_id: set() for item in claims}
    for element in candidate.semantic_basis.elements:
        source_compatible = [
            claim
            for claim in claims
            if any(
                spans[span_id].exact_text == claim.exact_text for span_id in element.source_span_ids
            )
        ]
        if not source_compatible:
            raise ValueError(f"element {element.element_id} is outside the assigned exact claims")
        for claim in source_compatible:
            if claim.predicate == element.predicate:
                matched[claim.claim_id].add(element.element_id)
    missing = [claim_id for claim_id, element_ids in matched.items() if not element_ids]
    if missing:
        raise ValueError(f"assigned claims lack predicate/span coverage: {sorted(missing)}")
    for claim in claims:
        linked_elements = matched[claim.claim_id]
        linked_statements = tuple(
            statement
            for statement in candidate.logical_program.statements
            if set(statement.source_assertion_ids).intersection(linked_elements)
        )
        if claim.expected_constant_values:
            observed_heads = {
                tuple(
                    value
                    for argument in statement.head.arguments
                    if (value := getattr(argument, "value", None)) is not None
                )
                for statement in linked_statements
                if statement.head is not None and statement.head.predicate == claim.predicate
            }
            if claim.expected_constant_values not in observed_heads:
                raise ValueError(
                    f"claim {claim.claim_id} lacks head constants "
                    f"{claim.expected_constant_values}"
                )
        if claim.expected_body_constant_values:
            observed_bodies: set[tuple[str | int, ...]] = set()
            for statement in linked_statements:
                pending = [statement.body] if statement.body is not None else []
                while pending:
                    expression = pending.pop()
                    if expression.atom is not None:
                        observed_bodies.add(
                            tuple(
                                value
                                for argument in expression.atom.arguments
                                if (value := getattr(argument, "value", None)) is not None
                            )
                        )
                    pending.extend(reversed(expression.operands))
            missing_body = set(claim.expected_body_constant_values) - observed_bodies
            if missing_body:
                raise ValueError(
                    f"claim {claim.claim_id} lacks body constants {sorted(missing_body)}"
                )


def _assert_global_claims(
    candidate: AutoformalizationCandidate, claims: tuple[PartitionClaim, ...]
) -> None:
    _assert_partition_claims(candidate, claims)
    statement_ids = [item.statement_id for item in candidate.logical_program.statements]
    element_ids = [item.element_id for item in candidate.semantic_basis.elements]
    span_ids = [item.span_id for item in candidate.semantic_basis.spans]
    for label, identifiers in (
        ("statement", statement_ids),
        ("element", element_ids),
        ("span", span_ids),
    ):
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"merged {label} identifiers are not unique")


def _merged_draft(
    request: AutoformalizationRequest,
    candidates: list[tuple[ClaimPartition, AutoformalizationCandidate]],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    spans: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    dimensions: list[dict[str, Any]] = []
    uncertainties: list[str] = []
    namespace_map: dict[str, dict[str, str]] = {}
    for partition, candidate in candidates:
        prefix = partition.partition_id + "::"
        span_map = {item.span_id: prefix + item.span_id for item in candidate.semantic_basis.spans}
        element_map = {
            item.element_id: prefix + item.element_id for item in candidate.semantic_basis.elements
        }
        statement_map = {
            item.statement_id: prefix + item.statement_id
            for item in candidate.logical_program.statements
        }
        namespace_map[partition.partition_id] = {
            **{f"span:{key}": value for key, value in span_map.items()},
            **{f"element:{key}": value for key, value in element_map.items()},
            **{f"statement:{key}": value for key, value in statement_map.items()},
        }
        section_by_span = {
            provenance.span_id: provenance.section_id
            for statement in candidate.logical_program.statements
            for provenance in statement.provenance
        }
        for item in candidate.semantic_basis.spans:
            global_start = request.source_text.find(item.exact_text)
            if global_start < 0 or request.source_text.find(item.exact_text, global_start + 1) >= 0:
                raise PartitionedAutoformalizationError(
                    f"partition span {item.span_id} cannot be uniquely re-anchored"
                )
            spans.append(
                {
                    "span_id": span_map[item.span_id],
                    "section_id": section_by_span[item.span_id],
                    "exact_text": item.exact_text,
                    "start_char": global_start,
                    "end_char": global_start + len(item.exact_text),
                }
            )
        for item in candidate.semantic_basis.elements:
            elements.append(
                {
                    "element_id": element_map[item.element_id],
                    "kind": item.kind.value,
                    "predicate": item.predicate,
                    "modality": item.modality.value,
                    "polarity": item.polarity,
                    "connective": item.connective,
                    "value": item.value,
                    "unit": item.unit,
                    "source_span_ids": [span_map[value] for value in item.source_span_ids],
                    "temporal": (item.temporal.model_dump(mode="json") if item.temporal else None),
                }
            )
        for statement in candidate.logical_program.statements:
            body_connective, body_atoms = _generated_body(
                statement.body, request.predicate_registry.signatures
            )
            rules.append(
                {
                    "statement_id": statement_map[statement.statement_id],
                    "modality": statement.modality.value,
                    "head": _generated_atom(request, statement.head),
                    "body_connective": body_connective,
                    "body_atoms": body_atoms,
                    "source_element_ids": [
                        element_map[value] for value in statement.source_assertion_ids
                    ],
                    "source_span_ids": [span_map[item.span_id] for item in statement.provenance],
                }
            )
        for item in candidate.projection.dimensions:
            dimensions.append(
                {
                    **item.model_dump(mode="json"),
                    "element_ids": [element_map[value] for value in item.element_ids],
                }
            )
        uncertainties.extend(
            f"[{partition.partition_id}] {item}" for item in candidate.uncertainties
        )
    raw = {
        "request_id": request.request_id,
        "basis_id": f"partition-merge:{request.request_id}",
        "program_id": f"partition-merge:{request.request_id}",
        "program_version": "candidate-merged-v1",
        "spans": spans,
        "elements": elements,
        "rules": rules,
        "dimensions": dimensions,
        "represented_element_ids": [item for rule in rules for item in rule["source_element_ids"]],
        "omitted_element_ids": [],
        "symbol_mappings": [],
        "uncertainties": uncertainties,
    }
    represented = set(raw["represented_element_ids"])
    raw["represented_element_ids"] = sorted(represented)
    raw["omitted_element_ids"] = sorted({item["element_id"] for item in elements} - represented)
    return raw, namespace_map


def _generated_body(
    expression: LogicalExpression | None,
    registry: tuple[Any, ...],
) -> tuple[str, list[dict[str, Any]]]:
    if expression is None:
        return "atom", []
    if expression.kind == ExpressionKind.ATOM:
        assert expression.atom is not None
        return "atom", [_generated_atom_untyped(expression.atom, registry=registry)]
    if expression.kind not in {ExpressionKind.CONJUNCTION, ExpressionKind.DISJUNCTION}:
        raise PartitionedAutoformalizationError(
            f"cannot merge unsupported expression kind {expression.kind.value}"
        )
    if any(item.kind != ExpressionKind.ATOM or item.atom is None for item in expression.operands):
        raise PartitionedAutoformalizationError(
            "partition merge requires flat atom conjunctions or disjunctions"
        )
    return expression.kind.value, [
        _generated_atom_untyped(item.atom, registry=registry)
        for item in expression.operands
        if item.atom
    ]


def _generated_atom(request: AutoformalizationRequest, atom: Atom | None) -> dict[str, Any] | None:
    if atom is None:
        return None
    return _generated_atom_untyped(atom, registry=request.predicate_registry.signatures)


def _generated_atom_untyped(
    atom: Atom,
    registry: tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    signatures = {item.name: item for item in registry or ()}
    signature = signatures.get(atom.predicate)
    if signature is None:
        # Body atoms are guaranteed to share the request registry at parse time. Roles
        # are reconstructed from value types only when this private helper lacks it.
        roles = tuple(
            argument.value_type.value.removesuffix("_id") or f"argument_{index + 1}"
            for index, argument in enumerate(atom.arguments)
        )
        units = tuple(None for _ in atom.arguments)
    else:
        roles = signature.argument_names
        units = signature.units or tuple(None for _ in atom.arguments)
    return {
        "predicate": atom.predicate,
        "arguments": [
            {
                "kind": "variable" if isinstance(argument, Variable) else "constant",
                "role": role,
                "value_type": argument.value_type.value,
                "name": argument.name if isinstance(argument, Variable) else None,
                "value": argument.value if isinstance(argument, Constant) else None,
                "unit": unit,
            }
            for argument, role, unit in zip(atom.arguments, roles, units, strict=True)
        ],
        "classical_negation": atom.classical_negation,
    }


def _partition_source(claims: tuple[PartitionClaim, ...]) -> str:
    """Join exact claim sentences without labels that could contaminate extraction."""

    return "\n\n".join(item.exact_text for item in claims)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "AutoformalizationPartitionPlan",
    "ClaimPartition",
    "DeterministicMergeReceipt",
    "PARTITION_PROTOCOL_VERSION",
    "PartitionClaim",
    "PartitionExecutionReceipt",
    "PartitionedAutoformalizationError",
    "PartitionedAutoformalizationRun",
    "build_claim_partition_plan",
    "run_partitioned_autoformalization",
    "verify_partitioned_autoformalization_run",
]
