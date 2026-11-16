# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""The aggregate gate must detect stale artifacts, never repair them."""

import inspect

from ruler.cli import validate_all_command


def test_validate_all_contains_no_generation_calls() -> None:
    source = inspect.getsource(validate_all_command.callback)
    assert "_write_" not in source
    assert "write_" not in source
    assert "generative-kb-quality-config" in source
    assert "live source and Codex profiles skipped" in source
