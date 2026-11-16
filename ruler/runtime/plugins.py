# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Publish only the four product workflow skills to Codex and Claude."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import tomllib

import yaml

from ruler.paths import REPO_ROOT

from ruler.runtime.product_workflows import WORKFLOWS

RUNTIME_INSTRUCTIONS = (
    "Use the connected RULER MCP server, started from a prepared checkout with "
    "`uv run ruler serve mcp`. The plugin supplies instructions, not a runtime, "
    "database, evidence, or credentials. If the four product tools are unavailable, "
    "report the missing connection; do not substitute demonstration workflows."
)
MANIFEST_PATHS = (
    ".codex-plugin/plugin.json",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
)


def _skills(root: Path) -> list[Path]:
    if (root / "plugin").is_symlink() or (root / "plugin/skills").is_symlink():
        raise ValueError("product skills root must not be a symlink")
    skills = sorted((root / "plugin/skills").rglob("SKILL.md"))
    if not skills:
        raise ValueError("product skills catalogue is empty")
    names: set[str] = set()
    for skill in skills:
        if skill.parent.parent != root / "plugin/skills":
            raise ValueError("product skills must be flat; nested skill exports are not allowed")
        if any(
            p.is_symlink() for p in (skill.parent, skill.parent.parent, *skill.parent.rglob("*"))
        ):
            raise ValueError(f"symlink in plugin skill: {skill}")
        text = skill.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise ValueError(f"missing skill frontmatter: {skill}")
        metadata = yaml.safe_load(text.split("---", 2)[1])
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if (
            not isinstance(name, str)
            or name != skill.parent.name
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        ):
            raise ValueError(f"invalid skill identity: {skill}")
        if name in names:
            raise ValueError(f"duplicate plugin skill name: {name}")
        names.add(name)
    expected = {"ruler-" + name.replace("_", "-") for name in WORKFLOWS}
    if names != expected:
        raise ValueError("plugin must contain exactly the four product workflow skills")
    return sorted(skills, key=lambda p: p.parent.name)


def _identity(root: Path) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project.get("name") != "ruler":
        raise ValueError("plugin source must be a RULER checkout")
    return {
        "name": "ruler",
        "version": project["version"],
        "description": "Prepare knowledge and requests, execute reasoning, and retrieve RULER product results.",
        "author": {"name": "Idiap Research Institute"},
        "license": "LicenseRef-Idiap-Research-Education",
    }


def _marketplace(identity: dict, source: str) -> dict:
    return {
        "name": "ruler",
        "owner": identity["author"],
        "plugins": [
            {"name": identity["name"], "source": source, "description": identity["description"]}
        ],
    }


def plugin_manifests(root: Path = REPO_ROOT) -> dict[str, dict]:
    """Describe both hosts with only the four product skills."""
    identity = _identity(root)
    paths = ["./" + p.parent.relative_to(root).as_posix() for p in _skills(root)]
    return {
        MANIFEST_PATHS[0]: {**identity, "skills": "./plugin/skills/"},
        MANIFEST_PATHS[1]: {**identity, "skills": paths},
        MANIFEST_PATHS[2]: _marketplace(identity, "./"),
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def refresh_plugin_manifests(root: Path = REPO_ROOT) -> None:
    """Explicitly refresh version and skill declarations after catalogue edits."""
    for relative, value in plugin_manifests(root).items():
        _write_json(root / relative, value)


def validate_plugin_catalogue(root: Path = REPO_ROOT) -> list[str]:
    """Return drift errors without generating or repairing any input."""
    errors: list[str] = []
    try:
        licensing = root / "REUSE.toml"
        if licensing.is_symlink():
            raise ValueError("REUSE.toml must not be a symlink")
        if tomllib.loads(licensing.read_text(encoding="utf-8")).get("version") != 1:
            errors.append("REUSE.toml must declare version = 1")
        expected = plugin_manifests(root)
        for relative, value in expected.items():
            try:
                actual = json.loads((root / relative).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                errors.append(f"{relative}: {exc}")
                continue
            if actual != value:
                errors.append(f"{relative}: stale; run ruler prepare plugins --refresh-manifests")
        for skill in _skills(root):
            if RUNTIME_INSTRUCTIONS not in skill.read_text(encoding="utf-8"):
                errors.append(f"{skill.relative_to(root)}: missing MCP connection instructions")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    return errors


def prepare_plugin_package(root: Path = REPO_ROOT) -> Path:
    """Build a flat skills-only marketplace, excluding runtime and private inputs."""
    errors = validate_plugin_catalogue(root)
    if errors:
        raise ValueError("\n".join(errors))
    licensing = root / "REUSE.toml"
    if not licensing.is_file() or licensing.is_symlink():
        raise ValueError("plugin source requires a regular REUSE.toml file")
    destination = root / "build" / "ruler" / "plugins"
    # Only replace our own generated tree, never a symlink or unrelated directory.
    if any(p.is_symlink() for p in (root / "build", destination.parent, destination)):
        raise ValueError("plugin output must not be a symlink")
    marker = destination / ".ruler-generated"
    if destination.exists():
        if not marker.is_file() or marker.read_text() != "ruler-plugin-package\n":
            raise ValueError(f"refusing to replace an unmanaged directory: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    marker.write_text("ruler-plugin-package\n")
    package = destination / "ruler"
    identity = _identity(root)
    _write_json(
        package / "plugin.json",
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            **identity,
        },
    )
    for host in ("codex", "claude"):
        _write_json(package / f".{host}-plugin/plugin.json", {**identity, "skills": "./skills/"})
    for skill in _skills(root):
        shutil.copytree(skill.parent, package / "skills" / skill.parent.name)
    # Generated JSON and skill definitions need exact-path manifest coverage.
    source_annotations = tomllib.loads(licensing.read_text(encoding="utf-8"))["annotations"]
    plugin_annotation = next(
        item for item in source_annotations if ".codex-plugin/plugin.json" in item["path"]
    )
    notice_lines = [
        "SPDX-FileCopyrightText: " + plugin_annotation["SPDX-FileCopyrightText"],
        *("SPDX-FileContributor: " + value for value in plugin_annotation["SPDX-FileContributor"]),
        "SPDX-License-" "Identifier: " + plugin_annotation["SPDX-License-Identifier"],
    ]
    markdown_notice = "<!--\n" + "\n".join(notice_lines) + "\n-->\n\n"
    license_dir = package / "LICENSES"
    license_dir.mkdir()
    shutil.copyfile(root / "LICENSES/LicenseRef-Idiap-Research-Education.txt", license_dir / "LicenseRef-Idiap-Research-Education.txt")
    (package / "README.md").write_text(
        markdown_notice + "# RULER skills plugin\n\n" + RUNTIME_INSTRUCTIONS + "\n\n"
        "Set up that checkout with `uv sync --extra dev --locked`. "
        "Read its documentation and use `uv run ruler --help`. "
        "Some workflows need separately prepared evidence and native solvers.\n\n"
        "Claude skills use `/ruler:<skill-name>`; Codex exposes the same named skills. "
        "Only prepare-knowledge, prepare-request, execute-reasoning and retrieve-results are exported. "
        "The package includes no automatic hooks, MCP configuration, credentials or data.\n",
        encoding="utf-8",
    )
    _write_json(destination / ".claude-plugin/marketplace.json", _marketplace(identity, "./ruler"))
    _write_json(
        destination / ".agents/plugins/marketplace.json",
        {
            "name": "ruler",
            "interface": {"displayName": "RULER"},
            "plugins": [
                {
                    "name": "ruler",
                    "source": {"source": "local", "path": "./ruler"},
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                    "category": "Developer Tools",
                }
            ],
        },
    )
    for manifest_root, paths in (
        (package, [
            "plugin.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json",
            *(str(path.relative_to(package)) for path in sorted((package / "skills").rglob("SKILL.md"))),
        ]),
        (destination, [
            ".ruler-generated", ".claude-plugin/marketplace.json",
            ".agents/plugins/marketplace.json",
        ]),
    ):
        annotation = {**plugin_annotation, "path": paths}
        content = "".join("# " + line + "\n" for line in notice_lines)
        content += "\nversion = 1\n\n[[annotations]]\n" + "".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
            for key, value in annotation.items()
        )
        (manifest_root / "REUSE.toml").write_text(content, encoding="utf-8")
    return destination
