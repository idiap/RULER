# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral case inputs."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ruler.contracts.common import StrictContract, TypedValue


class CaseContext(StrictContract):
    context_id: str
    domain_id: str
    subject_id: str | None = None
    facts: dict[str, TypedValue | bool | int | float | str | None] = Field(default_factory=dict)
    event_facts: tuple[str, ...] = ()
    parties: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
