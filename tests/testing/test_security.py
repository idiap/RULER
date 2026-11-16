# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic source-ingestion security boundary tests."""

from io import BytesIO
from pathlib import Path
import zipfile

import pytest

from ruler.testing.security import (
    enforce_payload_budget,
    inspect_workbook_archive,
    inspect_zip_archive,
    safe_destination,
    sensitive_findings,
    validate_public_http_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/policy",
        "http://127.0.0.1/policy",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/policy",
        "https://user:password@example.com/policy",
    ],
)
def test_ssrf_and_credentialed_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_http_url(url)


def test_public_https_url_is_accepted_without_network_resolution() -> None:
    assert validate_public_http_url("https://provider.example/policies/motor.pdf") == (
        "https://provider.example/policies/motor.pdf"
    )


@pytest.mark.parametrize("name", ["../policy.pdf", "/tmp/policy.pdf", "folder/policy.pdf", ".."])
def test_path_traversal_is_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        safe_destination(tmp_path, name)


def test_symlink_destination_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("do not overwrite", encoding="utf-8")
    (tmp_path / "policy.pdf").symlink_to(outside)
    with pytest.raises(ValueError, match="SOURCE_SYMLINK_REJECTED"):
        safe_destination(tmp_path, "policy.pdf")


def test_payload_budget_has_exact_boundary() -> None:
    assert enforce_payload_budget(b"1234", max_bytes=4) == b"1234"
    with pytest.raises(ValueError, match="SOURCE_PAYLOAD_BUDGET_EXCEEDED"):
        enforce_payload_budget(b"12345", max_bytes=4)


def _zip_payload(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return output.getvalue()


def test_archive_traversal_and_decompression_bomb_are_rejected() -> None:
    with pytest.raises(ValueError, match="ARCHIVE_PATH_TRAVERSAL_REJECTED"):
        inspect_zip_archive(_zip_payload({"../../outside.txt": b"escape"}))
    compressed = _zip_payload({"repeated.txt": b"A" * 1_000_000})
    with pytest.raises(ValueError, match="ARCHIVE_COMPRESSION_RATIO_EXCEEDED"):
        inspect_zip_archive(compressed, max_ratio=10)


def test_workbook_formula_macro_and_external_content_are_rejected() -> None:
    formula = _zip_payload(
        {
            "xl/worksheets/sheet1.xml": b'<worksheet><c><f>WEBSERVICE("x")</f></c></worksheet>',
        }
    )
    with pytest.raises(ValueError, match="WORKBOOK_FORMULA_REJECTED"):
        inspect_workbook_archive(formula)
    macro = _zip_payload({"xl/vbaProject.bin": b"fixture macro bytes"})
    with pytest.raises(ValueError, match="WORKBOOK_MACRO_REJECTED"):
        inspect_workbook_archive(macro)


def test_secret_scanner_reports_classes_without_echoing_values() -> None:
    secret = "api_key=sk-fixtureonlyabcdefghijklmnop"
    findings = sensitive_findings(f"fetch failed; {secret}")
    assert "credential_assignment" in findings
    assert secret not in repr(findings)
    assert sensitive_findings("The service_fee is CHF 500.") == ()
