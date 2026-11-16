---
name: dependency-license-inventory
description: Collect locked RULER Python and Node dependency metadata and generate docs/governance/LICENSES.md with package or framework name, version, license, URL, ecosystem, and direct or transitive dependency scope.
---

# Dependency License Inventory

Use this skill when the project needs a dependency license inventory, dependency
attribution table, or refreshed `docs/governance/LICENSES.md`.

## Procedure

1. Read `pyproject.toml`, including optional dependencies and PEP 735 dependency
   groups, to identify direct Python runtime and development dependencies.
2. Require `uv.lock` and resolve Python package metadata from the active locked
   `uv` environment.
3. Read the Codex workbench `package.json` and `package-lock.json` and collect
   every locked Node runtime, development, transitive, and platform package.
4. Traverse installed Python transitive dependencies from the direct dependency
   set while respecting environment and optional-extra markers.
5. Generate `docs/governance/LICENSES.md` with:
   - Python or Node ecosystem
   - package or framework name
   - installed version
     (list exact locked build variants together for the same base release, such
     as the Linux CPU wheel, to keep the inventory consistent across platforms)
   - dependency scope: direct runtime, direct development, or transitive
   - license metadata
   - homepage, repository, or documentation URL
6. Preserve generation and freshness-check commands.

## Command

Run from the repository root:

```bash
uv run python proj_skills/compliance/dependency-license-inventory/scripts/generate_licenses_md.py
```

CI or a release check can verify freshness without rewriting the inventory:

```bash
uv run python proj_skills/compliance/dependency-license-inventory/scripts/generate_licenses_md.py --check
```

## Gates

- Run `uv lock --check` to verify that Python declarations and the committed lock
  resolve together.
- Do not hand-write dependency rows when package metadata can be read from a
  locked environment or lockfile.
- Treat a missing `uv.lock`, `package.json`, or matching `package-lock.json` as a
  dependency-management failure.
- Mark unknown or ambiguous license fields explicitly rather than guessing.
- Prefer repository or homepage URLs over issue trackers and changelogs.
- Keep this inventory separate from the main `README.md`.
