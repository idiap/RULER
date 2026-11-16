---
name: resource-rule-constraint-compiler
description: Materialize approved resource rules and compile decision-dependent effects into a typed, unit-safe, solver-neutral optimization problem.
---

# Resource Rule Constraint Compiler

Run `uv run ruler portfolio compile`. Compile only approved, typed linear rules and
prove the resulting hard model satisfiable with the registered Z3 backend.
Every constraint must retain a source rule or named model-axiom origin. Unknown
eligibility, conflicting hard rules, unsupported constructs, unit mismatch, missing
bounds, and arbitrary big-M values fail closed.

## Validation

`uv run ruler validate resource-portfolio`
