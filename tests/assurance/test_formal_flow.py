# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import pytest
from pydantic import ValidationError

from ruler.assurance.formal_flow import FormalFlowRun, FormalHandoff, FormalStage

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


def test_digest_closed_ordered_handoff_validates() -> None:
    run = FormalFlowRun(
        run_id="run-1",
        stages=(
            FormalStage(
                stage_id="source",
                kind="source",
                performed_by="collector",
                input_digests=(),
                output_digest=D1,
                status="completed",
            ),
            FormalStage(
                stage_id="semantics",
                kind="semantics",
                performed_by="modeler",
                input_digests=(D1,),
                output_digest=D2,
                status="completed",
            ),
        ),
        handoffs=(
            FormalHandoff(
                producer_stage_id="source", consumer_stage_id="semantics", artifact_digest=D1
            ),
        ),
    )
    assert not run.release_authorized


def test_mismatched_digest_and_backward_handoff_fail() -> None:
    stages = (
        FormalStage(
            stage_id="source",
            kind="source",
            performed_by="collector",
            input_digests=(D2,),
            output_digest=D1,
            status="completed",
        ),
        FormalStage(
            stage_id="semantics",
            kind="semantics",
            performed_by="modeler",
            input_digests=(D1,),
            output_digest=D2,
            status="completed",
        ),
    )
    with pytest.raises(ValidationError, match="violates stage order"):
        FormalFlowRun(
            run_id="run-1",
            stages=stages,
            handoffs=(
                FormalHandoff(
                    producer_stage_id="semantics", consumer_stage_id="source", artifact_digest=D2
                ),
            ),
        )


def test_release_cannot_be_self_attested_from_partial_flow() -> None:
    with pytest.raises(ValidationError, match="every formal stage"):
        FormalFlowRun(
            run_id="run-1",
            stages=(
                FormalStage(
                    stage_id="source",
                    kind="source",
                    performed_by="collector",
                    input_digests=(),
                    output_digest=D1,
                    status="completed",
                ),
            ),
            handoffs=(),
            release_authorized=True,
        )


def test_release_requires_independent_authorities_and_unbroken_chain() -> None:
    digests = ["sha256:" + str(index) * 64 for index in range(1, 9)]
    kinds = (
        "source",
        "semantics",
        "interpretation",
        "projection",
        "execution",
        "certificate",
        "review",
        "release",
    )
    stages = tuple(
        FormalStage(
            stage_id=kind,
            kind=kind,
            performed_by="same-authority",
            input_digests=() if index == 0 else (digests[index - 1],),
            output_digest=digests[index],
            status="completed",
        )
        for index, kind in enumerate(kinds)
    )
    handoffs = tuple(
        FormalHandoff(
            producer_stage_id=kinds[index],
            consumer_stage_id=kinds[index + 1],
            artifact_digest=digests[index],
        )
        for index in range(len(kinds) - 1)
    )
    with pytest.raises(ValidationError, match="independent authorities"):
        FormalFlowRun(run_id="run-1", stages=stages, handoffs=handoffs, release_authorized=True)
