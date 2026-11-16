---
name: decision-point-explanation-builder
description: Deprecated compatibility alias for recommendation-trace-guardian and recommendation-argument-composer. Use only to route an older decision-point request to the canonical certificate-first explanation skills.
---

# Decision-Point Explanation Builder — Deprecated Alias

Do not execute an explanation workflow under this skill and do not emit a legacy
decision-point artifact.

Route the request as follows:

1. Use `$recommendation-trace-guardian` to produce and validate the required
   `DecisionArgumentCertificate`.
2. Use `$recommendation-argument-composer` to render the certificate as a readable,
   single-column argument.

This alias must not bypass the certificate, merge a changed-policy sensitivity with
a same-model runner-up, treat `unique_feasible` as objective preference, or give a
candidate KB solver authority.
