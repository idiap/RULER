---
name: ruler-generative-workflow-router
description: Route natural-language RULER workflow intents to bounded known hooks, skills, CLI commands, required inputs, expected artifacts, and validation gates. Use when a user asks what workflow or skill to run, asks for an interface to skills, or describes a task in prose.
---

# RULER Generative Workflow Router

Use this skill as the front door from prose intent to executable RULER workflows.

## Procedure

1. Run `uv run ruler route guide "<intent>"` for offline-safe deterministic guidance.
2. When a real provider is configured and the user authorizes network use, run
   `uv run ruler route guide --allow-network "<intent>"` for schema-constrained
   semantic interpretation.
3. Inspect the returned canonical routes, skills, required inputs, expected outputs,
   workflow commands, and validation gates. The receipt records provider/model and
   content hashes, never hidden model reasoning.
4. Treat every proposed route as advisory. Do not claim any selected skill ran, and
   do not execute or write from generated prose.
5. Execute only canonical commands reloaded from the registered route, subject to
   the command's normal authorization boundary.
6. If the guide asks a clarification question, resolve it before choosing a route.
7. Regenerate the catalogue with `uv run ruler workflow workflow-router` after editing hooks, skills, or route patterns.

## Gates

- `uv run ruler validate workflow-router`
- `uv run ruler validate hooks`
- `uv run ruler validate skills`

## Router Artifacts

- `data/use_cases/workflow_router.yaml`: route manifest.
- `build/ruler/workflow_router/workflow_router.yaml`: generated catalogue.
- `build/ruler/workflow_router/sample_route_packets.yaml`: smoke-test route packets.
