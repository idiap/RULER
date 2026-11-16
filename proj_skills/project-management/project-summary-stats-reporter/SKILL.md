---
name: project-summary-stats-reporter
description: Generate a self-contained RULER HTML summary report with project metrics, agent and skill counts, prompt-like instruction artifacts, Python classes/functions/methods, test cases, lines of code, workflows, completed TODOs, and extraction/onboarding status.
---

# Project Summary Stats Reporter

Use this skill when the user wants a quantitative and qualitative project summary:
agent and skill inventory, prompts, Python code structure, tests, lines of code,
solver stack, main workflows, delivery TODOs, extraction state, and functionality-level breakdowns.

## Procedure

1. Generate the report from repo-local evidence:

```bash
uv run python proj_skills/project-management/project-summary-stats-reporter/scripts/render_project_summary_stats.py
```

2. Read the generated artifacts:
   - `build/ruler/project_summary_stats/project_summary_stats.html`
   - `build/ruler/project_summary_stats/project_summary_stats.json`
3. Treat counts as repository-snapshot metrics. If the tree changes, rerun the script.
4. Keep claims evidence-backed:
   - skills are counted from `skills/**/SKILL.md` and `proj_skills/**/SKILL.md`;
   - prompts are prompt-like control artifacts: `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, and files with `prompt` in the filename;
   - classes, methods, functions, and test cases are counted through Python AST parsing;
   - workflows are read from `data/use_cases/workflow_router.yaml`;
   - registered workflows, hooks, tools, and agent configurations are counted from
     `.ruler/`, `skills/**/agents/openai.yaml`, and client wrappers;
   - TODO completion is available only when an optional `to-do.md` exists; otherwise
     report it as unavailable;
   - extraction progress comes from the append-only onboarding ledger, bounded
     batch artifacts, and source manifests;
   - solver descriptions are inferred from dependency declarations and solver/rule artifacts.

## Output Contract

The HTML report must be self-contained and include:

- headline metrics;
- skill and prompt breakdowns;
- skills per cluster with skill names and concise descriptions;
- Python class/function/method/test counts;
- source-line and artifact-line counts;
- underlying solvers and evidence paths;
- main workflows and hooks;
- concise completed/remaining TODOs and current extraction/onboarding batches;
- code metrics by key functionality;
- embedded JSON payload for machine reuse.

## Validation

After changing this skill or its script, run:

```bash
git diff --check
uv run python proj_skills/project-management/project-summary-stats-reporter/scripts/render_project_summary_stats.py --output-dir /tmp/ruler-project-summary-check
uv run pytest -q tests/project_management/test_project_summary_stats_reporter.py
uv run ruler validate skills
```
