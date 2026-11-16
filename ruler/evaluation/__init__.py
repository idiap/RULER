# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Domain-neutral rule evaluation and artifact-level trace contracts."""

from ruler.evaluation.contracts import (
    CounterfactualResult,
    EvaluationPacket,
    EvaluationRequest,
    EvaluationStatus,
    ExpectedRule,
    RuleConsequence,
)
from ruler.evaluation.pipeline import EvaluationPipeline, evaluate_request

__all__ = [
    "EvaluationPacket",
    "CounterfactualResult",
    "EvaluationPipeline",
    "EvaluationRequest",
    "EvaluationStatus",
    "ExpectedRule",
    "RuleConsequence",
    "evaluate_request",
]
