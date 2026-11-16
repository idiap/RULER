---
name: directory-structure-walkthrough-writer
description: Write concise RULER directory-structure walkthroughs for project management, onboarding, handoff, and technical orientation, grounded in the current repository tree and package layout.
---

# Directory Structure Walkthrough Writer

Use this skill when producing or refreshing a concise walkthrough of the RULER
repository structure.

## Procedure

1. Inspect the current tree before writing:
   - `find . -maxdepth 2 -type d | sort`
   - `find ruler -maxdepth 2 -type f -name '*.py' | sort`
   - `find tests -maxdepth 2 -type f | sort`
2. Organize the explanation by reader task:
   - run the system
   - understand source and KB material
   - follow reasoning code
   - inspect generated artifacts
   - add or review skills
   - run validation
3. Keep each folder description to one or two sentences.
4. Distinguish runtime skills in `skills/` from project communication skills in
   `proj_skills/`.
5. Mention generated or cache-like folders only when useful, and mark them as generated.
6. Write durable output under `docs/`; do not edit the main `README.md` unless requested.

## Recommended Sections

- Quick Orientation
- Runtime Package Map
- Data, KB, and Reference Material
- Skills and Workflow Control
- Generated Artifacts
- Tests and Validation
- Where to Start

## Gates

- Do not list every file; explain directory responsibilities.
- Do not use stale flat module paths when the code now lives under thematic packages.
- Do not present generated build artifacts as source of truth.
- Do not merge this walkthrough into the main README unless explicitly requested.
