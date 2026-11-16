---
name: ai-act-gdpr-architecture-reviewer
description: Review RULER EU AI Act and GDPR architecture compliance-analysis reports for unsupported legal claims, missing evidence paths, weak RAG+LLM contrast, absent residual gaps, and publication-readiness caveats.
---

# AI Act GDPR Architecture Reviewer

Use this skill when reviewing `architecture_compliance_analysis.html` or JSON
before sharing, committing, or incorporating it into project reports.

## Review Checklist

1. Confirm the report says it is architecture analysis, not legal advice.
2. Confirm every criterion has:
   - a regulation family;
   - a source URL;
   - RULER design strategies;
   - evidence paths;
   - RAG+LLM contrast;
   - residual gaps or next actions.
3. Check that strong compliance claims are avoided. Prefer:
   - `designed_strength`;
   - `partially_addressed`;
   - `requires_legal_review`;
   - `action_required`.
4. Verify GDPR sections distinguish data-protection design from lawful-basis
   determinations, which require deployment-specific legal review.
5. Verify EU AI Act sections distinguish provider/deployer responsibilities and
   do not classify the final deployment without context.
6. Check that the RAG+LLM comparison is fair and does not imply RAG+LLM is
   inherently non-compliant.

## Findings Format

- `High` - report claims legal compliance, lacks disclaimer, or omits human review
  and automated-decision safeguards.
- `Medium` - criterion lacks evidence path, source URL, residual gap, or RAG+LLM
  contrast.
- `Low` - wording, formatting, or missing output-path clarity.
