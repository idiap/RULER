# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Offline transport scenarios for crawl retry and redirect behavior."""

import pytest

from ruler.testing.offline_http import (
    OfflineHttpResolver,
    ScriptedResponse,
    follow_redirects,
)


def test_scripted_redirect_and_request_accounting() -> None:
    resolver = OfflineHttpResolver(
        {
            "https://fixture.invalid/start": [
                ScriptedResponse(302, {"location": "https://fixture.invalid/policy.pdf"}),
            ],
            "https://fixture.invalid/policy.pdf": [
                ScriptedResponse(200, {"content-type": "application/pdf"}, b"%PDF-fixture"),
            ],
        }
    )
    response = follow_redirects(resolver, "https://fixture.invalid/start")
    assert response.status == 200
    assert response.body == b"%PDF-fixture"
    assert len(resolver.requests) == 2
    resolver.assert_consumed()


def test_redirect_loop_and_request_budget_fail_closed() -> None:
    loop = OfflineHttpResolver(
        {
            "https://loop.invalid/a": [
                ScriptedResponse(302, {"location": "https://loop.invalid/b"})
            ],
            "https://loop.invalid/b": [
                ScriptedResponse(302, {"location": "https://loop.invalid/a"})
            ],
        }
    )
    with pytest.raises(RuntimeError, match="HTTP_REDIRECT_LOOP"):
        follow_redirects(loop, "https://loop.invalid/a")

    budgeted = OfflineHttpResolver(
        {"https://fixture.invalid": [ScriptedResponse(500), ScriptedResponse(200)]},
        max_requests=1,
    )
    assert budgeted.get("https://fixture.invalid").status == 500
    with pytest.raises(RuntimeError, match="HTTP_FIXTURE_BUDGET_EXHAUSTED"):
        budgeted.get("https://fixture.invalid")


def test_undeclared_network_target_cannot_be_used() -> None:
    with pytest.raises(RuntimeError, match="HTTP_FIXTURE_UNDECLARED_URL"):
        OfflineHttpResolver({}).get("https://example.com/live")
