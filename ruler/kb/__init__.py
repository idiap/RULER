# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Knowledge-base construction, loading, and immutable repository interfaces."""

from ruler.kb.repository import (
    CoherenceIssue,
    CoherenceReport,
    KnowledgeRepository,
    ProjectionRequest,
    ReleasedAssertion,
    RuntimeProjection,
)
from ruler.kb.release_store import (
    PublishedRepositoryBundle,
    load_repository_bundle,
    publish_repository_bundle,
)

__all__ = [
    "CoherenceIssue",
    "CoherenceReport",
    "KnowledgeRepository",
    "ProjectionRequest",
    "ReleasedAssertion",
    "RuntimeProjection",
    "PublishedRepositoryBundle",
    "load_repository_bundle",
    "publish_repository_bundle",
]
