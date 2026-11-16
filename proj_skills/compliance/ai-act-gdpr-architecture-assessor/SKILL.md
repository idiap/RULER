---
name: ai-act-gdpr-architecture-assessor
description: Assess RULER architecture against EU AI Act and GDPR design criteria, contrast it with a pure RAG+LLM architecture, and generate self-contained HTML and JSON compliance-analysis reports with evidence paths, residual gaps, and non-legal-advice caveats.
---

# AI Act GDPR Architecture Assessor

Use this skill when evaluating how RULER's architecture supports EU AI Act
and GDPR-aligned controls, especially for recommendation, profiling,
source-grounded reasoning, auditability, human review, and data minimization.

## Procedure

1. Refresh regulatory references if the output will be used externally.
   Prefer official EU/EUR-Lex/European Commission sources.
2. Generate the repo-local assessment:

```bash
uv run python proj_skills/compliance/ai-act-gdpr-architecture-assessor/scripts/render_architecture_compliance_analysis.py
```

3. Read:
   - `build/ruler/architecture_compliance/architecture_compliance_analysis.json`
   - `build/ruler/architecture_compliance/architecture_compliance_analysis.html`
4. Treat the output as architecture-readiness analysis, not legal advice.
5. Keep the contrast with RAG+LLM architectures concrete:
   - recurring full-text processing;
   - lower determinism and source trace stability;
   - harder record-keeping and human-review boundaries;
   - provider/API data-transfer and retention surfaces;
   - prompt and retrieval-context leakage risks.

## Required Analysis Criteria

- EU AI Act: risk management, data governance, technical documentation,
  record keeping, transparency, human oversight, accuracy/robustness/cybersecurity,
  post-market monitoring, and deployer-side logging/governance readiness.
- GDPR: lawfulness/fairness/transparency, purpose limitation, data minimization,
  accuracy, storage limitation, integrity/confidentiality, accountability,
  privacy by design/default, records of processing, security, DPIA readiness,
  automated-decision safeguards, data-subject rights, and processor/subprocessor
  control surfaces.

## Output Contract

The report must include:

- regulatory criterion;
- source URL;
- RULER design strategy;
- concrete evidence paths;
- RAG+LLM contrast;
- current status;
- residual gaps and recommended next actions;
- non-legal-advice disclaimer;
- embedded JSON payload for machine reuse.

## Validation

```bash
git diff --check
uv run python proj_skills/compliance/ai-act-gdpr-architecture-assessor/scripts/render_architecture_compliance_analysis.py --output-dir /tmp/ruler-ai-gdpr-check
uv run pytest -q tests/compliance/test_ai_act_gdpr_architecture_assessor.py
uv run ruler validate skills
```
