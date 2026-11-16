<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Add a domain pack

A domain pack contributes vocabulary and optional behavior without becoming a dependency of
the Ruler core.

1. Implement the `DomainPack` protocol from `ruler/domains/base.py` under
   `ruler/domains/<domain>/`.
2. Declare a stable lowercase `domain_id`, schema version, accepted document kinds, value types,
   predicates, normative-unit taxonomy, materiality roles, and translation contracts.
3. Implement `load_case` and `scope_matches`. Keep source acquisition, UI labels, and optional
   decision strategy inside the pack rather than in core.
4. Register the pack explicitly in the application composition root. Registry validation rejects
   duplicate IDs, malformed predicates, and unknown value types.
5. Add tests proving that exact evidence, unknown states, and pack-specific semantics survive
   deterministic replay.

Use `ruler/domains/regulatory/` as a minimal example and
`ruler/domains/legal/` for evidence-bound interpretation. Core contracts must not
import domain packs; `scripts/audit_domain_coupling.py` enforces this direction.

Validate with:

```bash
uv run ruler domains list
uv run ruler domains inspect <domain-id>
uv run pytest -q tests/domains tests/architecture
```
