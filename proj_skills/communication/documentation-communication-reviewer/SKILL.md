---
name: documentation-communication-reviewer
description: Review RULER documentation, diagrams, project explanations, and communication artifacts for clarity, audience fit, evidence grounding, boundaries, and unsupported claims.
---

# Documentation Communication Reviewer

Use this skill to review human-facing RULER documentation or diagrams before sharing
them with collaborators, reviewers, customers, or future maintainers.

## Review Lens

Check the artifact for:

- clear audience and purpose
- accurate component names and paths
- visible reasoning, KB, source, and validation boundaries
- distinction between implemented, generated, candidate-only, and proposed surfaces
- explicit human-validation and outbound-communication controls
- concise diagrams with useful edge labels
- validation commands for claims that can be checked

## Findings Format

Lead with findings, ordered by severity:

- `High` - misleading capability, unsafe omission, unsupported customer-facing claim.
- `Medium` - confusing architecture boundary, stale command, missing validation path.
- `Low` - readability, naming, or diagram-density issue.

Then provide:

- open questions
- suggested edits
- validation commands to run

## Gates

- Do not approve a document that implies candidate-only KB artifacts are active truth.
- Do not approve a diagram that hides the source-to-KB promotion boundary.
- Do not approve customer-facing language that lacks advisor/human-validation controls.
- Do not require main README changes unless the user explicitly requested them.
