# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Catalogue-wide, artifact-level skill reasoning logs.

Profiles describe what every canonical skill is expected to make observable.  Actual
events are separate and are written only by a real invocation.  Neither representation
contains private deliberation or hidden chain-of-thought.
"""

from __future__ import annotations

import json
import hashlib
import re
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ruler.io import read_yaml, stable_hash, write_text, write_yaml
from ruler.paths import BUILD_DIR, REPO_ROOT, SKILL_HOOKS_FILE
from ruler.runtime.skill_inventory import discover_skill_files as _discover_skill_files
from ruler.schemas import SkillHookBinding

SKILL_REASONING_LOG_DIR = BUILD_DIR / "skill_reasoning_logs"
EXPECTED_CANONICAL_SKILL_COUNT = len(_discover_skill_files())
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SENSITIVE_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|authorization|bearer|password|secret|token)\s*[:=]\s*\S+"
)


_repository: ContextVar[Path | None] = ContextVar("skill_log_repository", default=None)


@contextmanager
def skill_log_context(context: dict):
    """Select an isolated catalogue/workspace for one native step, without global mutation."""
    root = Path(context["repository_root"]).resolve() if "repository_root" in context else None
    token = _repository.set(root)
    try:
        yield
    finally:
        _repository.reset(token)


def discover_skill_files():
    root = _repository.get()
    return _discover_skill_files(root / "skills" if root is not None else None)


def _log_default_dir():
    root = _repository.get()
    return (
        root / "build/ruler/skill_reasoning_logs" if root is not None else SKILL_REASONING_LOG_DIR
    )


def _hooks_file():
    root = _repository.get()
    return root / "skills/SKILL_HOOKS.yaml" if root is not None else SKILL_HOOKS_FILE


class SkillValidationContract(BaseModel):
    """Declared validation boundary; it does not assert that a command has run."""

    model_config = ConfigDict(extra="forbid")

    commands: tuple[str, ...]
    status: Literal["declared", "not_declared"]


class SkillReasoningProfile(BaseModel):
    """Normalized, plain-language observability contract for one canonical skill."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    skill_id: str
    purpose: str
    mode: Literal["deterministic", "generative", "hybrid"]
    mode_source: Literal["binding", "description_inference"]
    stages: tuple[str, ...]
    observable_inputs: tuple[str, ...]
    observable_actions: tuple[str, ...]
    observable_evidence: tuple[str, ...]
    observable_outputs: tuple[str, ...]
    decision_impact: str
    validation: SkillValidationContract
    executable: bool
    backend_ids: tuple[str, ...]
    limitations: tuple[str, ...]


class SkillArtifactEvidence(BaseModel):
    """Content-addressed artifact named by an actual skill invocation."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["input", "output", "evidence", "validation"]
    artifact_id: str
    digest: str

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("digest must be a sha256:<64 lowercase hex> value")
        return value

    @field_validator("artifact_id")
    @classmethod
    def validate_artifact_id(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("artifact_id must be a portable repository-relative identifier")
        return value


class SkillReasoningEvent(BaseModel):
    """Public, artifact-level record of one observed skill execution step."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    skill_id: str
    workflow_id: str
    invocation_id: str
    sequence: int = Field(ge=1)
    status: Literal["started", "succeeded", "blocked", "failed"]
    mode: Literal["deterministic", "generative", "hybrid"]
    stage: str
    question: str
    observable_move: str
    outcome: str
    decision_impact: str
    artifacts: tuple[SkillArtifactEvidence, ...] = ()
    validation_commands: tuple[str, ...] = ()
    validation_status: Literal["not_run", "passed", "failed", "blocked"] = "not_run"
    backend_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    hidden_reasoning_included: Literal[False] = False

    @model_validator(mode="after")
    def reject_private_or_secret_content(self) -> SkillReasoningEvent:
        public_text = "\n".join(
            (
                self.question,
                self.observable_move,
                self.outcome,
                self.decision_impact,
                *self.limitations,
            )
        )
        if _SENSITIVE_PATTERN.search(public_text):
            raise ValueError("reasoning events must not contain credentials or secrets")
        if self.status == "succeeded" and not self.artifacts:
            raise ValueError("succeeded reasoning events require typed artifact evidence")
        return self


class SkillReasoningLogManifest(BaseModel):
    """Coverage statement kept separate from actual execution coverage."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    canonical_skill_count: int
    profile_count: int
    actual_event_count: int
    executed_skill_count: int
    profile_coverage: str
    execution_coverage: str
    profiles_digest: str
    notes: tuple[str, ...]


def build_skill_reasoning_profiles() -> list[SkillReasoningProfile]:
    """Build exactly one normalized profile for every canonical skill."""
    inventory = discover_skill_files()
    bindings = {
        item.skill: item
        for item in (SkillHookBinding.model_validate(raw) for raw in read_yaml(_hooks_file()))
    }
    profiles: list[SkillReasoningProfile] = []
    for skill_id, skill in sorted(inventory.items()):
        binding = bindings[skill_id]
        mode = binding.execution_mode or _infer_mode(skill_id, skill.description)
        executable = bool(binding.execution_commands or binding.backend_ids)
        profiles.append(
            SkillReasoningProfile(
                skill_id=skill_id,
                purpose=_plain_purpose(skill.description),
                mode=mode,
                mode_source=(
                    "binding" if binding.execution_mode is not None else "description_inference"
                ),
                stages=tuple(binding.stages),
                observable_inputs=tuple(binding.required_inputs)
                or ("Invocation request supplied at the workflow boundary.",),
                observable_actions=tuple(binding.execution_commands)
                or tuple(f"Apply the {stage.replace('-', ' ')} stage." for stage in binding.stages),
                observable_evidence=tuple(
                    dict.fromkeys(
                        binding.evidence_outputs
                        + binding.fixture_paths
                        + binding.implementation_refs
                        + binding.required_outputs
                        + [f"validation: {command}" for command in binding.validation_commands]
                    )
                ),
                observable_outputs=tuple(binding.required_outputs)
                or ("Result returned to the caller; no persistent artifact is declared.",),
                decision_impact=_decision_impact(skill.group),
                validation=SkillValidationContract(
                    commands=tuple(binding.validation_commands),
                    status="declared" if binding.validation_commands else "not_declared",
                ),
                executable=executable,
                backend_ids=tuple(binding.backend_ids) if executable else (),
                limitations=_limitations(mode, executable),
            )
        )
    return profiles


def record_skill_reasoning_event(
    event: SkillReasoningEvent,
    output_dir: Path | None = None,
) -> Path:
    """Append an event supplied by a real invocation; never synthesize execution."""
    if event.skill_id not in discover_skill_files():
        raise ValueError(f"unknown canonical skill: {event.skill_id}")
    base = output_dir or _log_default_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / "actual_events.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(event.model_dump_json() + "\n")
    return path


def load_skill_reasoning_events(path: Path) -> list[SkillReasoningEvent]:
    """Load and type-check an actual-event JSONL stream."""
    if not path.exists():
        return []
    events: list[SkillReasoningEvent] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(SkillReasoningEvent.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid skill reasoning event: {exc}") from exc
    return events


def write_skill_reasoning_log_artifacts(output_dir: Path | None = None) -> dict[str, Path]:
    """Write catalogue profiles and an honest execution-coverage manifest."""
    base = output_dir or _log_default_dir()
    base.mkdir(parents=True, exist_ok=True)
    profiles = build_skill_reasoning_profiles()
    paths = {
        "jsonl": base / "profiles.jsonl",
        "json": base / "profiles.json",
        "yaml": base / "profiles.yaml",
        "markdown": base / "profiles.md",
        "events": base / "actual_events.jsonl",
        "manifest": base / "manifest.yaml",
    }
    profile_payload = [profile.model_dump(mode="json") for profile in profiles]
    write_text(paths["jsonl"], "\n".join(profile.model_dump_json() for profile in profiles) + "\n")
    write_text(
        paths["json"], json.dumps({"profiles": profile_payload}, indent=2, ensure_ascii=False)
    )
    write_yaml(paths["yaml"], {"profiles": profile_payload})
    write_text(paths["markdown"], render_skill_reasoning_profiles_markdown(profiles))
    if not paths["events"].exists():
        write_text(paths["events"], "")
    events = load_skill_reasoning_events(paths["events"])
    executed = {event.skill_id for event in events}
    manifest = SkillReasoningLogManifest(
        canonical_skill_count=len(discover_skill_files()),
        profile_count=len(profiles),
        actual_event_count=len(events),
        executed_skill_count=len(executed),
        profile_coverage=f"{len(profiles)}/{len(discover_skill_files())}",
        execution_coverage=f"{len(executed)}/{len(discover_skill_files())}",
        profiles_digest=stable_hash(profile_payload),
        notes=(
            "Profiles are capability contracts, not evidence that a skill ran.",
            "Only actual_events.jsonl reports real invocations.",
            "Logs expose observable artifacts and decisions, never hidden chain-of-thought.",
        ),
    )
    write_yaml(paths["manifest"], manifest.model_dump(mode="json"))
    return paths


def validate_skill_reasoning_log_artifacts(output_dir: Path | None = None) -> list[str]:
    """Check profile completeness, cross-format identity, and actual-event integrity."""
    base = output_dir or _log_default_dir()
    paths = {
        "jsonl": base / "profiles.jsonl",
        "json": base / "profiles.json",
        "yaml": base / "profiles.yaml",
        "markdown": base / "profiles.md",
        "events": base / "actual_events.jsonl",
        "manifest": base / "manifest.yaml",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        return [f"missing skill reasoning log artifacts: {missing}"]
    errors: list[str] = []
    inventory = discover_skill_files()
    if len(inventory) != EXPECTED_CANONICAL_SKILL_COUNT:
        errors.append(
            f"canonical skill count changed: expected {EXPECTED_CANONICAL_SKILL_COUNT}, got {len(inventory)}"
        )
    try:
        jsonl_profiles = [
            SkillReasoningProfile.model_validate_json(line)
            for line in paths["jsonl"].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        json_profiles = [
            SkillReasoningProfile.model_validate(item)
            for item in json.loads(paths["json"].read_text(encoding="utf-8"))["profiles"]
        ]
        yaml_profiles = [
            SkillReasoningProfile.model_validate(item)
            for item in read_yaml(paths["yaml"])["profiles"]
        ]
        events = load_skill_reasoning_events(paths["events"])
        manifest = SkillReasoningLogManifest.model_validate(read_yaml(paths["manifest"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [f"invalid skill reasoning log artifact: {exc}"]
    profile_ids = [profile.skill_id for profile in jsonl_profiles]
    if len(profile_ids) != len(set(profile_ids)):
        errors.append("profiles JSONL must contain exactly one entry per skill")
    if set(profile_ids) != set(inventory):
        errors.append("profiles JSONL does not exactly match the canonical skill inventory")
    if jsonl_profiles != json_profiles or jsonl_profiles != yaml_profiles:
        errors.append("JSONL, JSON, and YAML skill profiles disagree")
    unknown_events = sorted({event.skill_id for event in events} - set(inventory))
    if unknown_events:
        errors.append(f"actual events reference unknown skills: {unknown_events}")
    profile_by_id = {profile.skill_id: profile for profile in jsonl_profiles}
    for event in events:
        profile = profile_by_id.get(event.skill_id)
        if profile is not None and event.mode != profile.mode:
            errors.append(
                f"{event.invocation_id}/{event.sequence}: mode {event.mode} does not match "
                f"{event.skill_id} profile mode {profile.mode}"
            )
    event_keys = [(event.invocation_id, event.sequence) for event in events]
    if len(event_keys) != len(set(event_keys)):
        errors.append("actual event invocation_id/sequence pairs must be unique")
    events_by_invocation: dict[str, list[SkillReasoningEvent]] = {}
    for event in events:
        events_by_invocation.setdefault(event.invocation_id, []).append(event)
    for invocation_id, invocation_events in events_by_invocation.items():
        ordered = sorted(invocation_events, key=lambda event: event.sequence)
        if [event.sequence for event in ordered] != list(range(1, len(ordered) + 1)):
            errors.append(f"{invocation_id}: event sequences must be contiguous from 1")
        if ordered[-1].status not in {"succeeded", "blocked", "failed"}:
            errors.append(f"{invocation_id}: event stream must end in a terminal status")
        if len({(event.skill_id, event.workflow_id) for event in ordered}) != 1:
            errors.append(f"{invocation_id}: events must identify one skill and workflow")
    executed = {event.skill_id for event in events}
    expected_digest = stable_hash([profile.model_dump(mode="json") for profile in jsonl_profiles])
    if manifest.profile_count != len(jsonl_profiles) or manifest.profiles_digest != expected_digest:
        errors.append("skill reasoning log manifest is stale")
    if manifest.actual_event_count != len(events) or manifest.executed_skill_count != len(executed):
        errors.append("skill reasoning execution coverage is stale")
    markdown = paths["markdown"].read_text(encoding="utf-8")
    if "Capability profiles are not execution evidence" not in markdown:
        errors.append("Markdown does not distinguish profiles from actual execution")
    return errors


def render_skill_reasoning_profiles_markdown(
    profiles: list[SkillReasoningProfile],
) -> str:
    """Render a compact human index with understandable per-skill contracts."""
    lines = [
        "# Skill reasoning-log catalogue",
        "",
        f"Canonical skills: **{len(profiles)}**. Profile coverage: **{len(profiles)}/{len(profiles)}**.",
        "",
        "> Capability profiles are not execution evidence. Actual invocations are recorded separately in `actual_events.jsonl`.",
        "",
        "These records explain observable inputs, actions, evidence, outputs, and decision effects. They never expose hidden chain-of-thought.",
        "",
    ]
    for profile in profiles:
        lines.extend(
            [
                f"## {profile.skill_id}",
                "",
                profile.purpose,
                "",
                f"- Mode: `{profile.mode}`",
                f"- Mode source: `{profile.mode_source}`",
                f"- Stages: {_display(profile.stages)}",
                f"- Inputs: {_display(profile.observable_inputs)}",
                f"- Observable actions: {_display(profile.observable_actions)}",
                f"- Evidence: {_display(profile.observable_evidence)}",
                f"- Outputs: {_display(profile.observable_outputs)}",
                f"- Decision impact: {profile.decision_impact}",
                f"- Validation: `{profile.validation.status}`; {_display(profile.validation.commands)}",
                f"- Backends: {_display(profile.backend_ids)}",
                f"- Limitations: {' '.join(profile.limitations)}",
                "",
            ]
        )
    return "\n".join(lines)


def artifact_evidence(role: str, path: Path) -> SkillArtifactEvidence:
    """Create a portable, content-addressed evidence reference for a real file."""
    resolved = path.resolve()
    try:
        artifact_id = resolved.relative_to(_repository.get() or REPO_ROOT).as_posix()
    except ValueError:
        artifact_id = path.name
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return SkillArtifactEvidence.model_validate(
        dict(role=role, artifact_id=artifact_id, digest=digest)
    )


def _infer_mode(
    skill_id: str, description: str
) -> Literal["deterministic", "generative", "hybrid"]:
    text = f"{skill_id} {description}".lower()
    if "generative" in text or "autoformalization" in text:
        return (
            "hybrid"
            if any(word in text for word in ("validat", "controlled", "determin"))
            else "generative"
        )
    return "deterministic"


def _plain_purpose(description: str) -> str:
    purpose = description.split(" Use when ", 1)[0].strip()
    return purpose.rstrip(".") + "."


def _decision_impact(group: str) -> str:
    impacts = {
        "autoformalization": "Controls which natural-language claims become formal, reviewable knowledge.",
        "demonstrators": "Shapes how grounded results are presented without changing the underlying decision.",
        "reasoning": "Contributes explicit evidence, constraints, rankings, or explanations to the decision.",
        "runtime": "Controls whether execution is safe, reproducible, and admissible for downstream use.",
        "source": "Controls which source evidence is available and traceable downstream.",
        "synthetic": "Controls test coverage without representing real-world evidence.",
        "translation": "Preserves meaning across formal or human-readable representations.",
        "workflow": "Selects or coordinates bounded workflow stages; it does not itself prove a domain conclusion.",
    }
    return impacts[group]


def _limitations(
    mode: Literal["deterministic", "generative", "hybrid"], executable: bool
) -> tuple[str, ...]:
    items = ["This profile declares an observability contract; it is not evidence of execution."]
    if mode in {"generative", "hybrid"}:
        items.append("Generated content requires the declared deterministic validation boundary.")
    if not executable:
        items.append(
            "No direct executable backend is declared; execution is composed by a workflow boundary."
        )
    return tuple(items)


def _display(values: tuple[str, ...]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none declared"


def append_skill_log_guardian(artifacts: dict[str, Path], output_dir: Path | None = None) -> Path:
    """Append the CLI-owned guardian event using initial-write evidence."""
    return record_skill_reasoning_event(
        SkillReasoningEvent(
            skill_id="policy-reasoning-log-guardian",
            workflow_id="skill-reasoning-logs",
            invocation_id=f"skill-reasoning-logs-{secrets.token_hex(8)}",
            sequence=1,
            status="succeeded",
            mode="deterministic",
            stage="reasoning-log",
            question="Does every canonical skill have an understandable logging contract?",
            observable_move=(
                "Built one typed capability profile per canonical skill and kept actual "
                "execution evidence in a separate event stream."
            ),
            outcome="Catalogue profiles were written in JSONL, JSON, YAML, and Markdown.",
            decision_impact=(
                "Auditors can compare skill contracts consistently without mistaking hook "
                "membership for execution."
            ),
            artifacts=tuple(
                artifact_evidence("output", artifacts[name])
                for name in ("jsonl", "json", "yaml", "markdown")
            ),
            validation_commands=("uv run ruler validate skill-reasoning-logs",),
            validation_status="not_run",
            limitations=(
                "This event proves profile generation only; it does not prove other skills ran.",
            ),
        ),
        output_dir=output_dir,
    )


def announce_skill_log_paths(artifacts: dict[str, Path], target) -> None:
    """Emit the source heading and all six paths in native insertion order."""
    target.print("[green]wrote skill reasoning-log artifacts[/green]")
    for name, path in artifacts.items():
        target.print(f"{name}: {path}")
