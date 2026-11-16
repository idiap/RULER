# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import pytest
from pydantic import ValidationError

from ruler.assurance.argumentation import (
    ArgumentFramework,
    ArgumentRelation,
    ArgumentRelationKind,
    StructuredArgument,
    evaluate_argument_framework,
)


def _argument(argument_id: str, conclusion: str, contrary: str) -> StructuredArgument:
    return StructuredArgument(
        argument_id=argument_id,
        conclusion=conclusion,
        contrary=contrary,
        premise_ids=(f"premise:{argument_id}",),
        source_refs=(f"span:{argument_id}",),
        context_id="case-1",
    )


def test_grounded_preferred_stable_and_asp_crosscheck_agree() -> None:
    framework = ArgumentFramework(
        framework_id="framework-1",
        context_id="case-1",
        arguments=(
            _argument("support", "allowed", "forbidden"),
            _argument("attack", "forbidden", "allowed"),
            _argument("defense", "allowed", "forbidden"),
        ),
        relations=(
            ArgumentRelation(
                relation_id="r1",
                source_argument_id="attack",
                target_argument_id="support",
                kind="rebuttal",
            ),
            ArgumentRelation(
                relation_id="r2",
                source_argument_id="defense",
                target_argument_id="attack",
                kind="undercut",
            ),
        ),
        finite_assumption="the supplied argument graph is complete for this bounded query",
    )
    result = evaluate_argument_framework(framework, "allowed")
    assert result.grounded_extension == ("defense", "support")
    assert result.preferred_extensions == (("defense", "support"),)
    assert result.stable_extensions == (("defense", "support"),)
    assert result.backend_equivalent is True
    assert result.target_status == "argumentatively_warranted"


def test_cycles_remain_undecided_and_budget_blocks_enumeration() -> None:
    framework = ArgumentFramework(
        framework_id="framework-cycle",
        context_id="case-1",
        arguments=(
            _argument("left", "allowed", "forbidden"),
            _argument("right", "forbidden", "allowed"),
        ),
        relations=(
            ArgumentRelation(
                relation_id="r1",
                source_argument_id="left",
                target_argument_id="right",
                kind="rebuttal",
            ),
            ArgumentRelation(
                relation_id="r2",
                source_argument_id="right",
                target_argument_id="left",
                kind="rebuttal",
            ),
        ),
        finite_assumption="bounded",
    )
    result = evaluate_argument_framework(framework, "allowed", max_arguments=1)
    assert result.undecided == ("left", "right")
    assert not result.enumeration_complete
    assert result.blockers == ("argument_enumeration_budget_exceeded",)


def test_preferences_require_cited_basis_and_revision() -> None:
    with pytest.raises(ValidationError, match="legal basis"):
        ArgumentRelation(
            relation_id="preference",
            source_argument_id="left",
            target_argument_id="right",
            kind=ArgumentRelationKind.DECLARED_PREFERENCE,
        )
