---
name: deliverable-completion-reviewer
description: Review RULER deliverable completion reports for evidence quality, missing deliverable categories, overclaimed completion status, stale generated artifacts, validation coverage, and release-readiness interpretation.
---

# Deliverable Completion Reviewer

Use this skill to review a generated deliverable completion report before using it as a
project-status or release-readiness artifact.

## Review Checklist

1. Confirm every completion claim cites a concrete file, generated artifact, command, or test.
2. Confirm partial and missing items are not hidden by the top-level score.
3. Confirm the report covers:
   - source and extraction;
   - controlled translation and KB;
   - reasoning and solvers;
   - audit logs and controls;
   - interfaces and demonstrators;
   - runtime integration;
   - tests and validation;
   - documentation and project communication;
   - compliance and packaging.
4. Confirm generated HTML is self-contained and includes `completion-report-data`.
5. Confirm the report avoids claiming production readiness from artifact existence alone.
6. Confirm validation recommendations include both CLI gates and pytest.

## Red Flags

- A group is scored complete without any evidence paths.
- Generated artifacts are treated as source-of-truth without pointing to validators.
- Uncommitted worktree changes are ignored for release readiness.
- The report describes future plans as completed work.
