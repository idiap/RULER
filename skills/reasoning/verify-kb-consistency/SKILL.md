---
name: verify-kb-consistency
description: Run focused read-only consistency checks over RULER contracts, formalized KB records, semantic preservation, bilingual annotations, reasoning integration, and statistics. Use before or after each progressive onboarding checkpoint and before considering compilation or publication.
---

# Verify KB Consistency

## Procedure

2. Treat contract, semantic-preservation, commentary, reasoning, and statistics failures as blocking.
3. Trace failures to exact source, formal-element, annotation, rule, release, or projection IDs.
4. Do not regenerate artifacts to make a validator pass. Use the owning generation workflow explicitly, then rerun this read-only check.
5. Record the successful command output or failure artifact as onboarding checkpoint evidence.

## Interpretation

- Duplicate or contradictory canonical semantics block release.
- Missing source, annotation, dependency, or cross-reference closure blocks release.
- Candidate or ungated records must remain outside runtime truth.
- NL commentary must remain bilingual and bound to the same semantic hash.
- Statistics describe the KB; they never establish semantic correctness by themselves.
