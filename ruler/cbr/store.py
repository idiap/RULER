# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Content-addressed decision replay and immutable reviewed outcome retention."""

from __future__ import annotations

import json
from pathlib import Path

from ruler.cbr.contracts import (
    CBRCaseRecord,
    CBRDecisionPacket,
    OutcomeObservation,
    ReleaseDrift,
)


class DecisionPacketStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, packet: CBRDecisionPacket) -> str:
        digest = packet.sha256()
        path = self.root / "decisions" / f"{digest.removeprefix('sha256:')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = packet.model_dump_json(indent=2, exclude_none=True)
        if path.is_symlink():
            raise ValueError("decision path must not be a symbolic link")
        if path.exists() and path.read_text() != payload:
            raise ValueError("content-address collision")
        if not path.exists():
            try:
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(payload)
            except FileExistsError:
                if path.read_text(encoding="utf-8") != payload:
                    raise ValueError("content-address collision") from None
        return digest

    def get(self, digest: str) -> CBRDecisionPacket:
        if not digest.startswith("sha256:") or "/" in digest or ".." in digest:
            raise ValueError("invalid decision digest")
        path = self.root / "decisions" / f"{digest.removeprefix('sha256:')}.json"
        packet = CBRDecisionPacket.model_validate_json(path.read_text())
        if packet.sha256() != digest:
            raise ValueError("stored decision digest mismatch")
        return packet


class OutcomeStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, outcome_id: str) -> Path:
        if not outcome_id or "/" in outcome_id or ".." in outcome_id or "\\" in outcome_id:
            raise ValueError("unsafe outcome ID")
        return self.root / "outcomes" / f"{outcome_id}.json"

    def retain(self, outcome: OutcomeObservation) -> str:
        path = self._path(outcome.outcome_id)
        if path.is_symlink():
            raise ValueError("outcome path must not be a symbolic link")
        if path.exists():
            raise ValueError(f"outcome is immutable and already exists: {outcome.outcome_id}")
        if outcome.supersedes_outcome_id:
            prior = self.get(outcome.supersedes_outcome_id)
            if prior.case_id != outcome.case_id:
                raise ValueError("outcome corrections must retain the same case identity")
            if prior.observed_at > outcome.observed_at:
                raise ValueError("a correction cannot predate the superseded observation")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = outcome.model_dump_json(indent=2, exclude_none=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(payload)
        except FileExistsError:
            raise ValueError(
                f"outcome is immutable and already exists: {outcome.outcome_id}"
            ) from None
        return outcome.outcome_id

    def supersede(self, correction: OutcomeObservation) -> str:
        if not correction.supersedes_outcome_id:
            raise ValueError("a correction must identify the superseded outcome")
        return self.retain(correction)

    def retire(self, retirement: OutcomeObservation) -> str:
        if retirement.review_state != "retired" or not retirement.supersedes_outcome_id:
            raise ValueError("retirement requires retired state and a superseded outcome")
        return self.retain(retirement)

    def get(self, outcome_id: str) -> OutcomeObservation:
        return OutcomeObservation.model_validate_json(self._path(outcome_id).read_text())

    def list_for_case(self, case_id: str) -> tuple[OutcomeObservation, ...]:
        directory = self.root / "outcomes"
        if not directory.exists():
            return ()
        outcomes = [
            OutcomeObservation.model_validate(json.loads(path.read_text()))
            for path in directory.glob("*.json")
        ]
        return tuple(
            sorted(
                (item for item in outcomes if item.case_id == case_id),
                key=lambda item: (item.observed_at, item.outcome_id),
            )
        )

    def active_for_case(self, case_id: str) -> OutcomeObservation | None:
        """Return the immutable correction-chain head, or none when it is retired."""
        outcomes = self.list_for_case(case_id)
        superseded = {item.supersedes_outcome_id for item in outcomes if item.supersedes_outcome_id}
        heads = [item for item in outcomes if item.outcome_id not in superseded]
        if len(heads) > 1:
            raise ValueError("case has divergent outcome correction heads")
        if not heads or heads[0].review_state == "retired":
            return None
        return heads[0]


def assess_release_drift(
    case: CBRCaseRecord, *, current_release_id: str, current_release_sha256: str
) -> ReleaseDrift:
    current = (
        case.rule_release_id == current_release_id
        and case.rule_release_sha256 == current_release_sha256
    )
    return ReleaseDrift(
        case_id=case.case_id,
        recorded_release_id=case.rule_release_id,
        current_release_id=current_release_id,
        status="current" if current else "requires_reevaluation",
        reason=(
            "release pins match"
            if current
            else "current rules differ; precedent must be re-evaluated before reuse"
        ),
    )
