# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import importlib.util
from pathlib import Path


def test_neutral_core_has_no_retired_application_domain_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "audit_domain_coupling.py"
    spec = importlib.util.spec_from_file_location("audit_domain_coupling", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.audit() == []
