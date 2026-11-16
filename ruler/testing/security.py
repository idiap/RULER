# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Fail-closed guards for hostile source references and fixture paths."""

from __future__ import annotations

import ipaddress
import io
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


def validate_public_http_url(url: str) -> str:
    """Reject authenticated, local, private, or ambiguous URLs before fetching."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("SOURCE_URL_SCHEME_OR_AUTH_REJECTED")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise ValueError("SOURCE_URL_PRIVATE_HOST_REJECTED")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("SOURCE_URL_PRIVATE_ADDRESS_REJECTED")
    if "\\" in unquote(parsed.path):
        raise ValueError("SOURCE_URL_AMBIGUOUS_PATH_REJECTED")
    return url


def safe_destination(root: Path, untrusted_name: str) -> Path:
    """Return a flat, root-contained destination for an untrusted filename."""
    if not untrusted_name or Path(untrusted_name).name != untrusted_name:
        raise ValueError("SOURCE_FILENAME_TRAVERSAL_REJECTED")
    if untrusted_name in {".", ".."} or "\x00" in untrusted_name:
        raise ValueError("SOURCE_FILENAME_INVALID")
    unresolved = root / untrusted_name
    if unresolved.is_symlink():
        raise ValueError("SOURCE_SYMLINK_REJECTED")
    destination = unresolved.resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("SOURCE_FILENAME_ESCAPE_REJECTED") from exc
    return destination


def enforce_payload_budget(payload: bytes, *, max_bytes: int) -> bytes:
    """Fail closed before parsing a source that exceeds its byte budget."""
    if len(payload) > max_bytes:
        raise ValueError("SOURCE_PAYLOAD_BUDGET_EXCEEDED")
    return payload


def inspect_zip_archive(
    payload: bytes,
    *,
    max_entries: int = 1_000,
    max_uncompressed_bytes: int = 50_000_000,
    max_ratio: int = 100,
) -> tuple[str, ...]:
    """Inventory a ZIP without extracting it and reject bomb/traversal shapes."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("ARCHIVE_INVALID") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > max_entries:
            raise ValueError("ARCHIVE_ENTRY_BUDGET_EXCEEDED")
        total = sum(info.file_size for info in infos)
        if total > max_uncompressed_bytes:
            raise ValueError("ARCHIVE_UNCOMPRESSED_BUDGET_EXCEEDED")
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("ARCHIVE_PATH_TRAVERSAL_REJECTED")
            if info.flag_bits & 0x1:
                raise ValueError("ARCHIVE_ENCRYPTED_ENTRY_REJECTED")
            compressed = max(info.compress_size, 1)
            if info.file_size / compressed > max_ratio:
                raise ValueError("ARCHIVE_COMPRESSION_RATIO_EXCEEDED")
        return tuple(info.filename for info in infos)


def inspect_workbook_archive(payload: bytes) -> tuple[str, ...]:
    """Reject active content and formulas before workbook values are parsed."""
    names = inspect_zip_archive(payload)
    lowered = {name.lower() for name in names}
    if any(name.endswith("vbaproject.bin") for name in lowered):
        raise ValueError("WORKBOOK_MACRO_REJECTED")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in names:
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                xml = archive.read(name)
                if b"<f" in xml:
                    raise ValueError("WORKBOOK_FORMULA_REJECTED")
            if name.lower().endswith(("externallinks.xml", "connections.xml")):
                raise ValueError("WORKBOOK_EXTERNAL_CONNECTION_REJECTED")
    return names


_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(?:api[_-]?key|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)


def sensitive_findings(text: str) -> tuple[str, ...]:
    """Return finding classes only; never echo matched secret material."""
    labels = ("credential_assignment", "api_token", "jwt")
    return tuple(
        label
        for label, pattern in zip(labels, _SENSITIVE_PATTERNS, strict=True)
        if pattern.search(text)
    )
