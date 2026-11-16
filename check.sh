#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

status=0
run() {
  printf '\n+ %s\n' "$*"
  "$@" || status=1
}

run uv run --locked pytest
run uv run --locked pytest .idiap-sd/tests
run uv run --locked ruff check .
run uv run --locked black --check .
run uv run --locked black --check .idiap-sd/idiap_sd.py .idiap-sd/tests/test_software_disclosure.py
run uv run --locked pyright
run uv run --locked pyright .idiap-sd
run uv run --locked vulture .
run uv run --locked python .idiap-sd/idiap_sd.py frontend-test
run uv run --locked python .idiap-sd/idiap_sd.py reuse
run uv run --locked python .idiap-sd/idiap_sd.py check --metadata-only
run uv run --locked ruler validate all
run git diff --check
exit "$status"
