# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

import hashlib

from ruler.io import read_yaml
from ruler.paths import REFERENCE_DIR
from ruler.runtime.skill_inventory import discover_skill_files


def test_upstream_skill_transfer_manifest_is_digest_bound_and_complete() -> None:
    payload = read_yaml(REFERENCE_DIR / "upstream_skill_transfer.yaml")
    names = sorted(payload["skills"])
    digest = "sha256:" + hashlib.sha256(("\n".join(names) + "\n").encode()).hexdigest()
    assert payload["inventory_sha256"] == digest
    assert set(names) <= set(discover_skill_files())
    assert names
