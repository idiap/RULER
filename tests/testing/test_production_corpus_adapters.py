# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Offline integration tests for the existing production corpus adapters."""

from __future__ import annotations

from email.message import Message
from pathlib import Path

import pytest

from ruler.io import read_yaml
from ruler.source import source_corpus


class _FixtureResponse:
    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.headers = Message()
        self.headers["content-type"] = content_type

    def __enter__(self) -> "_FixtureResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_production_downloader_uses_injected_offline_response_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fixture_urlopen(request: object, timeout: int) -> _FixtureResponse:
        calls.append(request.full_url)
        assert timeout == 90
        return _FixtureResponse(b"%PDF-offline-fixture", "application/pdf")

    monkeypatch.setattr(source_corpus, "urlopen", fixture_urlopen)
    path, content_type = source_corpus._download_bytes(
        "https://fixture.invalid/policy.pdf?utm_source=test",
        tmp_path,
        force=False,
    )
    assert path.read_bytes() == b"%PDF-offline-fixture"
    assert content_type == "application/pdf"
    cached, _ = source_corpus._download_bytes(
        "https://fixture.invalid/policy.pdf?utm_source=test",
        tmp_path,
        force=False,
    )
    assert cached == path
    assert calls == ["https://fixture.invalid/policy.pdf?utm_source=test"]


def test_production_html_extractor_preserves_text_and_filters_document_hosts(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "source.html"
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    raw.write_text(
        "<html><script>ignore()</script><p>Policy conditions</p>"
        '<a href="/docs/policy.pdf?utm_source=x">PDF</a>'
        '<a href="https://evil.invalid/payload.pdf">external</a></html>',
        encoding="utf-8",
    )
    artifacts, urls = source_corpus._extract_html_artifacts(
        raw,
        extracted,
        "https://www.provider_a.ch/downloads/index.html",
    )
    assert (extracted / "html_text.txt").read_text(encoding="utf-8") == (
        "Policy conditions\nPDF\nexternal\n"
    )
    assert urls == ["https://www.provider_a.ch/docs/policy.pdf"]
    links = read_yaml(extracted / "discovered_links.yaml")
    assert links["document_links"] == urls
    assert {item["kind"] for item in artifacts} == {"html_text", "discovered_links"}


def test_production_canonical_url_is_order_stable_and_removes_tracking() -> None:
    first = source_corpus._canonical_url(
        "https://provider_a.ch/policy.pdf?utm_source=x&edition=2024&gclid=secret#page=2"
    )
    second = source_corpus._canonical_url(
        "https://provider_a.ch/policy.pdf?edition=2024&utm_campaign=y"
    )
    assert first == second == "https://provider_a.ch/policy.pdf?edition=2024"
