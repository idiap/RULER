# SPDX-FileCopyrightText: 2026 Idiap Research Institute
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Four product boundaries over the native, governed KB services.

The MCP worker supplies a database-materialized workspace. Requests are pinned to
published knowledge; run records contain public evidence, never reasoning internals.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from ruler.contracts.common import StrictContract
from ruler.kb.workspace_contracts import (
    AddKBArtifactRequest,
    CreateKnowledgeBaseRequest,
    KBInferenceRequest,
)
from ruler.kb.workspace_governance import ReleaseEvidence, ReleaseStage
from ruler.kb.workspace_inference import KBInferenceService
from ruler.runtime.mcp_projects import ProjectMCPService, project_fields

WORKFLOWS = (
    "prepare_knowledge",
    "prepare_request",
    "execute_reasoning",
    "retrieve_results",
)
BACKENDS = frozenset({"clingo-ground-query-v1", "legal-packet-assurance-v1"})


class KnowledgeInput(StrictContract):
    action: Literal[
        "discover",
        "inspect",
        "plan_import",
        "apply_import",
        "create",
        "add_artifact",
        "transition",
        "batch_status",
        "batch_stage",
    ] = "discover"
    project_id: str | None = None
    corpus_id: str | None = None
    kb_id: str | None = None
    plan_id: str | None = None
    definition: CreateKnowledgeBaseRequest | None = None
    artifact: AddKBArtifactRequest | None = None
    target: ReleaseStage | None = None
    evidence: list[ReleaseEvidence] = Field(default_factory=list, max_length=100)
    batch_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")
    stage: str | None = None


class PreparedRequest(StrictContract):
    kb_id: str
    content_sha256: str
    request: KBInferenceRequest


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _required(value, name):
    if value is None or value == "":
        raise ValueError(f"{name} is required for this action")
    return value


class ProductWorkflows:
    def __init__(self, projects: ProjectMCPService):
        self.projects = projects
        self.catalog = projects.catalog

    def prepare_knowledge(self, input: KnowledgeInput, *, allow_write=False, allow_network=False):
        """Discover, import, author and release knowledge with native evidence gates."""
        action = input.action
        if (
            action in {"apply_import", "create", "add_artifact", "transition", "batch_stage"}
            and not allow_write
        ):
            return {"status": "blocked", "reason": "knowledge changes require allow_write=true"}
        if action == "discover":
            return {
                **self.projects.list_projects(),
                "knowledge_bases": [self._metadata(kb.kb_id) for kb in self.catalog.list()],
            }
        if action == "inspect":
            if input.kb_id:
                return self._metadata(input.kb_id)
            return self.projects.inspect(_required(input.project_id, "project_id"))
        if action == "plan_import":
            return self.projects.plan_import(
                _required(input.project_id, "project_id"),
                _required(input.corpus_id, "corpus_id"),
                input.kb_id,
            )
        if action == "apply_import":
            return self.projects.apply_import(_required(input.plan_id, "plan_id"), allow_write=True)
        if action == "create":
            definition = _required(input.definition, "definition")
            self.projects.inspect(definition.domain_id)
            return self._metadata(self.catalog.create(definition).kb_id)
        if action == "add_artifact":
            kb = self.catalog.add_artifact(
                _required(input.kb_id, "kb_id"),
                _required(input.artifact, "artifact"),
            )
            return self._metadata(kb.kb_id)
        if action == "transition":
            release = self.catalog.transition_release(
                _required(input.kb_id, "kb_id"),
                _required(input.target, "target"),
                input.evidence,
            )
            return {"status": "transitioned", "release": release.model_dump(mode="json")}
        from ruler.ingestion.batch_pipeline import PipelineStage, batch_status, run_batch_stage

        batch_id = _required(input.batch_id, "batch_id")
        if action == "batch_status":
            return batch_status(batch_id)
        stage = PipelineStage(_required(input.stage, "stage"))
        # Native stages can invoke configured producers; opt in for any stage
        # that is not an inspection. Native ordering and gates remain mandatory.
        if stage != PipelineStage.STATUS and not allow_network:
            return {"status": "blocked", "reason": "batch execution requires allow_network=true"}
        return run_batch_stage(batch_id, stage)

    def _metadata(self, kb_id):
        kb = self.catalog.get(kb_id)
        value = kb.model_dump(mode="json", exclude={"versions"})
        value["content_sha256"] = kb.current_version.content_sha256
        value["artifacts"] = [
            artifact.model_dump(mode="json", exclude={"path"})
            for artifact in kb.current_version.artifacts
        ]
        value["releases"] = [r.model_dump(mode="json") for r in self.catalog.releases(kb_id)]
        value["capabilities"] = [
            row
            for row in KBInferenceService(self.catalog).capabilities(kb_id)
            if row["backend_id"] in BACKENDS
        ]
        return project_fields(value)

    def prepare_request(self, kb_id: str, request: KBInferenceRequest):
        """Validate a structured request and pin it to a published KB release."""
        if request.parameters.get("allow_preview"):
            raise ValueError("product requests require published knowledge")
        if request.backend_id not in BACKENDS:
            raise ValueError("select an advertised product backend")
        release = self.catalog.execution_release(kb_id)
        if request.version_id and request.version_id != release.version_id:
            raise ValueError("requested version is not the active published release")
        if self.catalog.get(kb_id).current_version_id != release.version_id:
            raise ValueError("current knowledge revision must be published before use")
        capabilities = KBInferenceService(self.catalog).capabilities(kb_id)
        if not any(
            row["backend_id"] == request.backend_id
            and request.operation in row["operations"]
            and (request.artifact_id is None or row["artifact_id"] == request.artifact_id)
            for row in capabilities
        ):
            raise ValueError("request is not supported by this KB's product capabilities")
        pinned = request.model_copy(update={"version_id": release.version_id})
        prepared = PreparedRequest(
            kb_id=kb_id, content_sha256=release.content_sha256, request=pinned
        )
        return {"status": "prepared", "prepared": prepared.model_dump(mode="json")}

    def execute_reasoning(self, prepared: PreparedRequest, *, allow_execute=False):
        """Revalidate the release, execute the selected backend and save its evidence."""
        if not allow_execute:
            return {
                "status": "blocked",
                "reason": "execution and result storage require allow_execute=true",
            }
        checked = self.prepare_request(prepared.kb_id, prepared.request)["prepared"]
        if checked != prepared.model_dump(mode="json"):
            raise ValueError("prepared request differs from the active published knowledge")
        result = KBInferenceService(self.catalog).execute(prepared.kb_id, prepared.request)
        if result.status != "completed":
            return result.model_dump(mode="json")
        run_id = uuid4().hex
        record = {
            "run_id": run_id,
            "prepared": checked,
            "result": result.model_dump(mode="json"),
        }
        envelope = {"record": record, "sha256": _digest(record)}
        path = self.catalog.repo_root / "build/ruler/product_runs" / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as output:
            json.dump(envelope, output, sort_keys=True)
        return {"status": "completed", "run_id": run_id, "result": record["result"]}

    def retrieve_results(self, run_id: str):
        """Read a completed run by opaque ID and verify its stored evidence digest."""
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("invalid run identifier")
        path = self.catalog.repo_root / "build/ruler/product_runs" / f"{run_id}.json"
        if path.is_symlink():
            raise ValueError("run records must not be symbolic links")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if (
            envelope["record"]["run_id"] != run_id
            or _digest(envelope["record"]) != envelope["sha256"]
        ):
            raise ValueError("run evidence digest mismatch")
        return envelope
