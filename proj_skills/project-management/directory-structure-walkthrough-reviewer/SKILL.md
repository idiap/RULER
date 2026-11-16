---
name: directory-structure-walkthrough-reviewer
description: Review RULER directory-structure walkthroughs for correctness, concision, freshness against the repository tree, audience fit, and clear distinction between source, generated artifacts, KBs, runtime skills, and project-management skills.
---

# Directory Structure Walkthrough Reviewer

Use this skill when checking a directory walkthrough before sharing it with a
collaborator, maintainer, or future agent.

## Review Checklist

1. Verify the walkthrough matches the current top-level tree.
2. Verify `ruler/` subpackages are described using the current thematic layout:
   `reasoning`, `kb`, `source`, `interfaces`, `runtime`, and `solvers`.
3. Verify `tests/` mirrors the source package themes.
4. Verify `skills/` and `proj_skills/` are not conflated.
5. Verify generated folders such as `build/`, `.pytest_cache/`, `.ruff_cache/`, and
   `.venv/` are not treated as hand-authored source.
6. Check that the walkthrough is concise enough for onboarding.

## Findings Format

- `High` - stale path, misleading source-of-truth claim, or missing core directory.
- `Medium` - overlong section, ambiguous generated/source boundary, or missing validation path.
- `Low` - wording, ordering, or formatting improvement.

## Gates

- Do not approve walkthroughs that reference old flat module locations.
- Do not approve walkthroughs that omit KB, workflow control, or validation directories.
- Do not require README changes unless the user asked for them.
