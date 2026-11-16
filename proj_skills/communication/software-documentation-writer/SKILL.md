---
name: software-documentation-writer
description: Write RULER project documentation for software components, workflows, modules, artifacts, and developer-facing explanations without changing the main README unless explicitly requested.
---

# Software Documentation Writer

Use this skill when producing project documentation for RULER internals, architecture,
workflows, modules, generated artifacts, or developer handoff notes.

## Procedure

1. Identify the audience first: maintainer, researcher, demo reviewer, engineer, or operator.
2. Read the relevant source files before documenting behavior. Prefer `ruler/`, `kb/`,
   `.ruler/hooks.yaml`, `skills/SKILL_HOOKS.yaml`, and existing `docs/` artifacts.
3. Write outside the main `README.md` unless the user explicitly asks for README changes.
4. Use concrete file paths, CLI commands, generated artifacts, and validation gates.
5. Explain motivation, data flow, control boundaries, and failure modes before low-level APIs.
6. Separate confirmed behavior from proposed extensions.

## Recommended Sections

- Purpose
- Audience
- Component Map
- Data and Control Flow
- Key Files
- CLI Workflows
- Validation Gates
- Generated Artifacts
- Extension Points
- Known Boundaries

## RULER Documentation Anchors

- Runtime package: `ruler/`
- Canonical KB: `kb/`
- Workflow hooks: `.ruler/hooks.yaml`
- Runtime skills: `skills/`
- Project communication skills: `proj_skills/`
- Generated demos: `build/ruler/`
- Long-lived documentation: `docs/`

## Gates

- Do not invent capabilities absent from code or generated artifacts.
- Do not hide human-validation or outbound-communication controls.
- Do not merge project-communication docs into the main README unless explicitly asked.
- Include a validation command when a documented behavior has one.
