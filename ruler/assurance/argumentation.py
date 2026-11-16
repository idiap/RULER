# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Finite, source-bound structured argumentation with an ASP cross-check.

This is the domain-neutral part of the Legal Reasoner argumentation flow.  It keeps
support distinct from attack, requires evidence for preferences, computes complete
Dung semantics, and can compare the reference evaluator with an independently
executed clingo projection.
"""

from __future__ import annotations

from enum import StrEnum

import clingo
from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract


class ArgumentRelationKind(StrEnum):
    SUPPORT = "support"
    REBUTTAL = "rebuttal"
    UNDERCUT = "undercut"
    PREMISE_UNDERMINE = "premise_undermine"
    DISTINCTION = "distinction"
    AUTHORITY_CHALLENGE = "authority_challenge"
    DECLARED_PREFERENCE = "declared_preference"


class ArgumentConclusionStatus(StrEnum):
    WARRANTED = "argumentatively_warranted"
    DEFENSIBLE = "defensible"
    CONTROVERSIAL = "controversial"
    UNWARRANTED = "unwarranted"
    UNDECIDED = "undecided"


class StructuredArgument(StrictContract):
    argument_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
    conclusion: str = Field(min_length=1)
    contrary: str = Field(min_length=1)
    premise_ids: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    context_id: str = Field(min_length=1)
    assumptions: tuple[str, ...] = ()
    candidate_status: str = "candidate_uncommitted"
    review_state: str = "pending"

    @model_validator(mode="after")
    def conclusion_is_oriented(self) -> "StructuredArgument":
        if self.conclusion == self.contrary:
            raise ValueError("argument conclusion and contrary must differ")
        return self


class ArgumentRelation(StrictContract):
    relation_id: str
    source_argument_id: str
    target_argument_id: str
    kind: ArgumentRelationKind
    legal_basis_refs: tuple[str, ...] = ()
    policy_revision: str | None = None

    @model_validator(mode="after")
    def preference_is_grounded(self) -> "ArgumentRelation":
        if self.kind == ArgumentRelationKind.DECLARED_PREFERENCE and (
            not self.legal_basis_refs or not self.policy_revision
        ):
            raise ValueError("argument preference requires legal basis and policy revision")
        return self


class ArgumentFramework(StrictContract):
    framework_id: str
    context_id: str
    arguments: tuple[StructuredArgument, ...] = Field(min_length=1)
    relations: tuple[ArgumentRelation, ...] = ()
    finite_assumption: str = Field(min_length=1)

    @model_validator(mode="after")
    def graph_is_closed(self) -> "ArgumentFramework":
        ids = [item.argument_id for item in self.arguments]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate structured argument ID")
        known = set(ids)
        if any(item.context_id != self.context_id for item in self.arguments):
            raise ValueError("argument framework mixes contexts")
        for relation in self.relations:
            if relation.source_argument_id not in known or relation.target_argument_id not in known:
                raise ValueError("argument relation references an unknown argument")
        return self


class ArgumentationEvaluation(StrictContract):
    framework_id: str
    semantics_profile: str = "dung-grounded-preferred-stable-v1"
    grounded_extension: tuple[str, ...]
    preferred_extensions: tuple[tuple[str, ...], ...]
    stable_extensions: tuple[tuple[str, ...], ...]
    enumeration_complete: bool
    accepted: tuple[str, ...]
    rejected: tuple[str, ...]
    undecided: tuple[str, ...]
    effective_attacks: tuple[tuple[str, str], ...]
    preference_applications: tuple[tuple[str, str, tuple[str, ...]], ...]
    target_status: ArgumentConclusionStatus
    backend_equivalent: bool | None = None
    blockers: tuple[str, ...] = ()


_ATTACKS = frozenset(
    {
        ArgumentRelationKind.REBUTTAL,
        ArgumentRelationKind.UNDERCUT,
        ArgumentRelationKind.PREMISE_UNDERMINE,
        ArgumentRelationKind.DISTINCTION,
        ArgumentRelationKind.AUTHORITY_CHALLENGE,
    }
)


def evaluate_argument_framework(
    framework: ArgumentFramework,
    target: str,
    *,
    include_stable: bool = True,
    max_arguments: int = 18,
    crosscheck_asp: bool = True,
) -> ArgumentationEvaluation:
    """Evaluate grounded/preferred/stable semantics without collapsing undecided claims."""

    ids = tuple(sorted(item.argument_id for item in framework.arguments))
    attacks, applications = _effective_attacks(framework)
    grounded: set[str] = set()
    while True:
        defended = {
            item
            for item in ids
            if all(
                any((defender, attacker) in attacks for defender in grounded)
                for attacker in _attackers(item, attacks)
            )
        }
        if defended == grounded:
            break
        grounded = defended
    rejected = {target_id for source, target_id in attacks if source in grounded}
    undecided = set(ids) - grounded - rejected

    preferred: tuple[tuple[str, ...], ...] = ()
    stable: tuple[tuple[str, ...], ...] = ()
    complete = len(ids) <= max_arguments
    blockers: list[str] = []
    if complete:
        admissible: list[frozenset[str]] = []
        stable_sets: list[tuple[str, ...]] = []
        for mask in range(1 << len(ids)):
            candidate = frozenset(item for index, item in enumerate(ids) if mask & (1 << index))
            if any(left in candidate and right in candidate for left, right in attacks):
                continue
            if not all(
                all(
                    any((defender, attacker) in attacks for defender in candidate)
                    for attacker in _attackers(item, attacks)
                )
                for item in candidate
            ):
                continue
            admissible.append(candidate)
            outside = set(ids) - candidate
            if include_stable and all(
                any((member, item) in attacks for member in candidate) for item in outside
            ):
                stable_sets.append(tuple(sorted(candidate)))
        preferred = tuple(
            sorted(
                tuple(sorted(item))
                for item in admissible
                if not any(item < other for other in admissible)
            )
        )
        stable = tuple(sorted(set(stable_sets)))
    else:
        blockers.append("argument_enumeration_budget_exceeded")

    support = {item.argument_id for item in framework.arguments if item.conclusion == target}
    contrary = {item.argument_id for item in framework.arguments if item.contrary == target}
    if support & grounded and not contrary & grounded:
        status = ArgumentConclusionStatus.WARRANTED
    elif support & grounded and contrary & grounded:
        status = ArgumentConclusionStatus.CONTROVERSIAL
    elif preferred and any(support & set(extension) for extension in preferred):
        status = (
            ArgumentConclusionStatus.CONTROVERSIAL
            if any(contrary & set(extension) for extension in preferred)
            else ArgumentConclusionStatus.DEFENSIBLE
        )
    elif support & undecided:
        status = ArgumentConclusionStatus.UNDECIDED
    else:
        status = ArgumentConclusionStatus.UNWARRANTED

    equivalent: bool | None = None
    if crosscheck_asp and complete:
        asp_preferred, asp_stable = _evaluate_with_clingo(ids, attacks, include_stable)
        equivalent = asp_preferred == preferred and (not include_stable or asp_stable == stable)
        if not equivalent:
            blockers.append("argumentation_backend_divergence")
    return ArgumentationEvaluation(
        framework_id=framework.framework_id,
        grounded_extension=tuple(sorted(grounded)),
        preferred_extensions=preferred,
        stable_extensions=stable,
        enumeration_complete=complete,
        accepted=tuple(sorted(grounded)),
        rejected=tuple(sorted(rejected)),
        undecided=tuple(sorted(undecided)),
        effective_attacks=tuple(sorted(attacks)),
        preference_applications=applications,
        target_status=status,
        backend_equivalent=equivalent,
        blockers=tuple(blockers),
    )


def _effective_attacks(
    framework: ArgumentFramework,
) -> tuple[set[tuple[str, str]], tuple[tuple[str, str, tuple[str, ...]], ...]]:
    preferences = {
        (item.source_argument_id, item.target_argument_id): item
        for item in framework.relations
        if item.kind == ArgumentRelationKind.DECLARED_PREFERENCE
    }
    attacks: set[tuple[str, str]] = set()
    applications: list[tuple[str, str, tuple[str, ...]]] = []
    for relation in framework.relations:
        if relation.kind not in _ATTACKS:
            continue
        preference = preferences.get((relation.target_argument_id, relation.source_argument_id))
        if preference:
            applications.append(
                (
                    relation.target_argument_id,
                    relation.source_argument_id,
                    preference.legal_basis_refs,
                )
            )
        else:
            attacks.add((relation.source_argument_id, relation.target_argument_id))
    return attacks, tuple(sorted(applications))


def _attackers(argument_id: str, attacks: set[tuple[str, str]]) -> set[str]:
    return {source for source, target in attacks if target == argument_id}


def _evaluate_with_clingo(
    ids: tuple[str, ...], attacks: set[tuple[str, str]], include_stable: bool
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Independently enumerate maximal admissible and stable sets with ASP."""

    index = {argument_id: f"a{position}" for position, argument_id in enumerate(ids)}
    reverse = {value: key for key, value in index.items()}
    facts = [
        *(f"arg({index[item]})." for item in ids),
        *(f"attack({index[left]},{index[right]})." for left, right in attacks),
    ]
    base = "\n".join(facts) + """
{in(X)} :- arg(X).
:- in(X), in(Y), attack(X,Y).
defeats_attacker(X,A) :- in(X), attack(X,A).
undefended(X) :- in(X), attack(A,X), not defeats_attacker(_,A).
:- undefended(X).
#show in/1.
"""
    control = clingo.Control(["--warn=none", "--models=0"])
    control.add("base", [], base)
    control.ground([("base", [])])
    admissible: list[frozenset[str]] = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            admissible.append(
                frozenset(reverse[str(symbol.arguments[0])] for symbol in model.symbols(shown=True))
            )
    preferred = tuple(
        sorted(
            tuple(sorted(item))
            for item in admissible
            if not any(item < other for other in admissible)
        )
    )
    stable = tuple(
        sorted(
            tuple(sorted(candidate))
            for candidate in admissible
            if include_stable
            and all(
                any((member, outside) in attacks for member in candidate)
                for outside in set(ids) - candidate
            )
        )
    )
    return preferred, stable
