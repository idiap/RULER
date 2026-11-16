# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Capability routing and orthogonal reasoning-assurance contracts."""

from ruler.assurance.contracts import (
    BackendCapability,
    BackendProfile,
    ProjectionLoss,
    ProjectionPolicy,
    ReasoningQuery,
    ReasoningResultAxes,
)
from ruler.assurance.router import BackendRouter
from ruler.assurance.argumentation import (
    ArgumentConclusionStatus,
    ArgumentFramework,
    ArgumentRelation,
    ArgumentRelationKind,
    ArgumentationEvaluation,
    StructuredArgument,
    evaluate_argument_framework,
)
from ruler.assurance.formal_flow import FormalFlowRun, FormalHandoff, FormalStage, FormalStageKind

__all__ = [
    "BackendCapability",
    "BackendProfile",
    "BackendRouter",
    "ProjectionLoss",
    "ProjectionPolicy",
    "ReasoningQuery",
    "ReasoningResultAxes",
    "ArgumentConclusionStatus",
    "ArgumentFramework",
    "ArgumentRelation",
    "ArgumentRelationKind",
    "ArgumentationEvaluation",
    "StructuredArgument",
    "evaluate_argument_framework",
    "FormalFlowRun",
    "FormalHandoff",
    "FormalStage",
    "FormalStageKind",
]
