---
name: dependency-license-reviewer
description: Review RULER dependency license inventories such as docs/governance/LICENSES.md for missing package metadata, ambiguous licenses, stale generation commands, and publication readiness.
---

# Dependency License Reviewer

Use this skill when reviewing a dependency inventory before sharing it, committing it,
or using it for project communication.

## Review Checklist

1. Confirm `docs/governance/LICENSES.md` includes package or framework name, version, scope,
   license, and URL.
2. Confirm the generation command points to the repo-local collector script.
3. Inspect `UNKNOWN` license or URL entries and decide whether they are acceptable
   for an internal engineering inventory.
4. Check that direct runtime and direct development dependencies from `pyproject.toml`
   appear in the table.
5. Make sure the document says it is not legal advice.

## Findings Format

- `High` - direct dependency missing, misleading license value, or generated file absent.
- `Medium` - unknown metadata that should be researched before external publication.
- `Low` - formatting, stale command text, or unclear scope wording.

## Gates

- Do not replace missing license metadata with guesses.
- Do not claim legal clearance from package metadata alone.
- Do not put the inventory in the main `README.md` unless explicitly requested.
