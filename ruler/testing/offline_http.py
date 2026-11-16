# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Scripted HTTP transport used by ingestion tests; it never opens a socket."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScriptedResponse:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass
class OfflineHttpResolver:
    """Consume declared responses in order and account for every request."""

    scripts: dict[str, list[ScriptedResponse]]
    max_requests: int = 20
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> ScriptedResponse:
        """Consume the next declared response and enforce the request budget."""
        if len(self.requests) >= self.max_requests:
            raise RuntimeError("HTTP_FIXTURE_BUDGET_EXHAUSTED")
        self.requests.append((url, dict(headers or {})))
        responses = self.scripts.get(url)
        if not responses:
            raise RuntimeError(f"HTTP_FIXTURE_UNDECLARED_URL:{url}")
        return responses.pop(0)

    def assert_consumed(self) -> None:
        """Fail when a test did not exercise every response in its protocol script."""
        remaining = {url: len(items) for url, items in self.scripts.items() if items}
        if remaining:
            raise AssertionError(f"HTTP_FIXTURE_UNUSED_RESPONSES:{remaining}")


def follow_redirects(
    resolver: OfflineHttpResolver,
    url: str,
    *,
    max_redirects: int = 5,
) -> ScriptedResponse:
    """Resolve a scripted redirect chain with loop and bound protection."""
    seen: set[str] = set()
    for _ in range(max_redirects + 1):
        if url in seen:
            raise RuntimeError("HTTP_REDIRECT_LOOP")
        seen.add(url)
        response = resolver.get(url)
        if response.status not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            raise RuntimeError("HTTP_REDIRECT_WITHOUT_LOCATION")
        url = location
    raise RuntimeError("HTTP_REDIRECT_LIMIT")
