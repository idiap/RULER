# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Explicitly provision ignored agent surfaces from public project documentation."""

from pathlib import Path

from ruler.paths import REPO_ROOT
from ruler.runtime.claude_code import REQUIRED_CLAUDE_SKILLS
from ruler.runtime.opencode import REQUIRED_OPENCODE_SKILLS


def prepare_agent_config(root: Path = REPO_ROOT) -> list[Path]:
    """Create missing defaults, preserving every existing local instruction file."""
    created: list[Path] = []

    def write_missing(relative: str, content: str) -> None:
        target = root / relative
        if target.exists() or target.is_symlink():
            return
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"agent configuration path escapes project: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8") as output:
                output.write(content)
        except FileExistsError:
            return
        created.append(target)

    guides = root / "docs" / "guides"
    execution = "\nUse the canonical skills/ catalogue and run `uv run ruler validate all`.\n"
    write_missing(
        "AGENTS.md",
        (guides / "codex.md").read_text(encoding="utf-8")
        + "\n"
        + (guides / "opencode.md").read_text(encoding="utf-8")
        + execution,
    )
    write_missing("CLAUDE.md", (guides / "claude_code.md").read_text(encoding="utf-8") + execution)
    for client, names in (
        ("claude", REQUIRED_CLAUDE_SKILLS),
        ("opencode", REQUIRED_OPENCODE_SKILLS),
    ):
        for name in sorted(names):
            command = (
                "workflow translation-control"
                if "translation" in name
                else (
                    "workflow cbr-case"
                    if "reasoning" in name
                    else (
                        f"validate {'claude-code' if client == 'claude' else client}"
                        if "bridge-maintainer" in name
                        else "validate all"
                    )
                )
            )
            description = (
                f"Run {name.removeprefix('ruler-').replace('-', ' ')} through the RULER CLI."
            )
            write_missing(
                f".{client}/skills/{name}/SKILL.md",
                f"---\nname: {name}\ndescription: {description}\n---\n\n"
                f"Use the canonical skills/ catalogue.\n\n```sh\nuv run ruler {command}\n```\n",
            )
    for name, command in {
        "validate": "validate all",
        "reason": "workflow cbr-case",
        "graphs": "workflow workflow-graphs",
    }.items():
        write_missing(
            f".opencode/commands/{name}.md",
            f"---\ndescription: Run RULER {name} through the project CLI.\n---\n\n"
            f"```sh\nuv run ruler {command}\n```\n",
        )
    workbench_readme = root / "codex-app-workbench" / "README.md"
    if workbench_readme.is_file():
        write_missing("codex-app-workbench/AGENTS.md", workbench_readme.read_text(encoding="utf-8"))
    return created
