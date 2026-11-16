# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Managed source-document corpus extraction.

This module keeps raw policy evidence separate from formalization artifacts. It turns
spreadsheet links into a deterministic corpus plan, downloads source bytes into
versioned folders, extracts reviewable text/layout views, and records enough metadata
for later autoformalization without promoting any claim into the KB.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from pypdf import PdfReader

from ruler.io import read_yaml, repo_relative_posix, write_text, write_yaml
from ruler.ingestion import AppendOnlySourceStore, SourceVersion, canonical_sha256, stable_id
from ruler.ingestion.source_controls import classify_fetch_failure
from ruler.paths import (
    SOURCE_EXTRACTED_DIR,
    SOURCE_INDEX_DIR,
    SOURCE_MANIFEST_DIR,
    SOURCE_RAW_DIR,
)
from ruler.testing.security import validate_public_http_url

DEFAULT_ORGANIZATION_ID = "source"
DEFAULT_SOURCE_GROUP = "sources"
SOURCE_CORPUS_TIMESTAMP = "2026-06-24T00:00:00+02:00"
# Complete accounting is the production default.  A numeric limit remains an
# explicit demo/debug selector and is recorded in the generated manifest.
MAX_LIVE_SAMPLE_DOCUMENTS = 3
MAX_LIVE_SAMPLE_BYTES = 25_000_000
MAX_EXACT_DOCUMENTS = 3
MAX_EXACT_DOCUMENT_BYTES = 25_000_000
MAX_EXACT_DOCUMENT_PAGES = 500

_EXACT_DOCUMENT_ALLOWED_KEYS = {
    "document_id",
    "organization",
    "fetch_url",
    "retrieval_url",
    "expected_raw_sha256",
    "source_kind",
    "provider",
    "product_family",
    "product_labels",
    "products",
    "policy_buckets",
    "jurisdiction",
    "language",
    "title",
    "row_refs",
    "selection_rationale",
}
_SENSITIVE_QUERY_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "signature",
    "token",
)

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


class _HTMLTextAndLinkParser(HTMLParser):
    """Collect visible-ish text and links with only the Python standard library."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.text_parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned)


def extract_exact_documents(
    manifest_path: Path,
    *,
    output_manifest: Path | None = None,
    force: bool = False,
    max_download_bytes: int = MAX_EXACT_DOCUMENT_BYTES,
    max_pdf_pages: int = MAX_EXACT_DOCUMENT_PAGES,
) -> dict[str, Any]:
    """Extract only the one-to-three exact documents named in a bounded manifest.

    The input is a YAML mapping with ``mode: bounded_exact_document_extraction_only``
    and a ``documents`` list. Each document requires ``document_id``, ``organization``,
    and ``fetch_url``. An optional ``retrieval_url`` may name a governed alternate
    download location without changing the canonical document identity. The command
    does not follow links, formalize content, or publish records. Its output is
    deterministic for the same source bytes and manifest.
    """
    source_manifest, documents = _load_exact_document_manifest(manifest_path)
    target = output_manifest or manifest_path.with_name(
        f"{manifest_path.stem}_extraction_manifest.yaml"
    )
    if target.resolve() == manifest_path.resolve():
        raise ValueError("output manifest must not overwrite the exact-document input manifest")
    if max_download_bytes < 1:
        raise ValueError("max_download_bytes must be positive")
    if max_pdf_pages < 1:
        raise ValueError("max_pdf_pages must be positive")

    extracted = [
        _download_and_extract_entry(
            document,
            force=force,
            max_download_bytes=max_download_bytes,
            max_pdf_pages=max_pdf_pages,
        )
        for document in documents
    ]
    result = {
        "schema_version": 1,
        "manifest_id": stable_id(
            "exact_document_extraction_manifest",
            {
                "source_manifest_id": source_manifest.get("manifest_id"),
                "documents": [
                    {
                        "document_id": item["document_id"],
                        "raw_sha256": item.get("raw_sha256"),
                        "status": item["status"],
                    }
                    for item in extracted
                ],
            },
        ),
        "mode": "bounded_exact_document_extraction_only_no_autoformalization",
        "source_link_manifest": repo_relative_posix(manifest_path),
        "architecture": _architecture_payload(),
        "limits": {
            "max_documents": MAX_EXACT_DOCUMENTS,
            "max_download_bytes_per_document": max_download_bytes,
            "max_pdf_pages_per_document": max_pdf_pages,
            "follow_discovered_links": False,
        },
        "summary": {
            "selected_documents": len(extracted),
            "documents_extracted": sum(item["status"] == "extracted" for item in extracted),
            "documents_failed": sum(item["status"] == "failed" for item in extracted),
            "pdf_documents": sum(item.get("content_kind") == "pdf" for item in extracted),
            "html_documents": sum(item.get("content_kind") == "html" for item in extracted),
            "discovered_documents_enqueued": 0,
            "autoformalization_outputs_written": 0,
            "published_outputs_written": 0,
        },
        "documents": extracted,
    }
    write_yaml(target, result)
    return result


def _load_exact_document_manifest(
    manifest_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = read_yaml(manifest_path)
    if not isinstance(payload, dict):
        raise ValueError("exact-document manifest must be a YAML mapping")
    if payload.get("mode") != "bounded_exact_document_extraction_only":
        raise ValueError(
            "exact-document manifest mode must be bounded_exact_document_extraction_only"
        )
    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list) or not 1 <= len(raw_documents) <= MAX_EXACT_DOCUMENTS:
        raise ValueError(f"exact-document manifest must contain 1-{MAX_EXACT_DOCUMENTS} documents")

    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for position, raw_document in enumerate(raw_documents, start=1):
        if not isinstance(raw_document, dict):
            raise ValueError(f"exact document {position} must be a YAML mapping")
        unexpected = sorted(set(raw_document) - _EXACT_DOCUMENT_ALLOWED_KEYS)
        if unexpected:
            raise ValueError(
                f"exact document {position} has unsupported fields: {', '.join(unexpected)}"
            )
        document_id = raw_document.get("document_id")
        organization = raw_document.get("organization")
        fetch_url = raw_document.get("fetch_url")
        retrieval_url = raw_document.get("retrieval_url")
        if not isinstance(document_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{2,127}", document_id
        ):
            raise ValueError(f"exact document {position} has an unsafe document_id")
        if not isinstance(organization, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{1,63}", organization
        ):
            raise ValueError(f"exact document {position} has an unsafe organization")
        canonical_url = _validate_exact_document_url(
            fetch_url,
            position=position,
            field="fetch_url",
            required=True,
        )
        canonical_retrieval_url = _validate_exact_document_url(
            retrieval_url,
            position=position,
            field="retrieval_url",
            required=False,
        )
        assert canonical_url is not None  # A required URL is validated above.
        expected_document_id = _document_id(canonical_url)
        if document_id != expected_document_id:
            raise ValueError(
                f"exact document {position} document_id must be {expected_document_id}"
            )
        if document_id in seen_ids:
            raise ValueError(f"duplicate exact document_id: {document_id}")
        if canonical_url in seen_urls:
            raise ValueError(f"duplicate exact document URL at position {position}")
        expected_hash = raw_document.get("expected_raw_sha256")
        if expected_hash is not None and (
            not isinstance(expected_hash, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_hash)
        ):
            raise ValueError(f"exact document {position} has an invalid expected_raw_sha256")
        document = dict(raw_document)
        document["fetch_url"] = canonical_url
        if canonical_retrieval_url is not None:
            document["retrieval_url"] = canonical_retrieval_url
        document.setdefault("source_kind", _source_kind_from_url(canonical_url))
        seen_ids.add(document_id)
        seen_urls.add(canonical_url)
        documents.append(document)
    return payload, documents


def _validate_exact_document_url(
    value: Any,
    *,
    position: int,
    field: str,
    required: bool,
) -> str | None:
    """Validate and canonicalize a governed exact-document source URL."""
    if value is None and not required:
        return None
    if not isinstance(value, str):
        if required:
            raise ValueError(f"exact document {position} requires {field}")
        raise ValueError(f"exact document {position} {field} must be a string")

    stripped = value.strip()
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"exact document {position} {field} requires a public HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError(f"exact document {position} {field} must not contain credentials")
    try:
        validate_public_http_url(stripped)
    except ValueError as exc:
        raise ValueError(
            f"exact document {position} {field} requires a public HTTP(S) URL"
        ) from exc

    query_keys = {
        key.casefold().replace("-", "_")
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if any(sensitive in key for key in query_keys for sensitive in _SENSITIVE_QUERY_KEY_PARTS):
        raise ValueError(f"exact document {position} {field} contains a sensitive query field")
    return _canonical_url(stripped)


def _download_and_extract_entry(
    entry: dict[str, Any],
    *,
    force: bool,
    max_download_bytes: int | None = None,
    max_pdf_pages: int | None = None,
) -> dict[str, Any]:
    """Fetch and extract one source while enforcing optional pilot resource limits."""
    organization = entry.get("organization", DEFAULT_ORGANIZATION_ID)
    raw_dir = SOURCE_RAW_DIR / organization / entry["document_id"]
    extracted_dir = SOURCE_EXTRACTED_DIR / organization / entry["document_id"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    try:
        retrieval_url = entry.get("retrieval_url", entry["fetch_url"])
        raw_path, content_type = _download_bytes(
            retrieval_url,
            raw_dir,
            force=force,
            max_bytes=max_download_bytes,
        )
        raw_bytes = raw_path.read_bytes()
        source_task_identity = {
            "provider_id": organization,
            "canonical_url": _canonical_url(entry["fetch_url"]),
        }
        if "retrieval_url" in entry:
            source_task_identity["retrieval_url"] = _canonical_url(retrieval_url)
        source_task_id = stable_id(
            "source_task",
            source_task_identity,
        )
        raw_sha256 = canonical_sha256(raw_bytes)
        expected_raw_sha256 = entry.get("expected_raw_sha256")
        if expected_raw_sha256 is not None and raw_sha256 != expected_raw_sha256:
            raise ValueError(f"raw SHA-256 mismatch for document_id={entry['document_id']}")
        source_version = SourceVersion(
            source_version_id=stable_id(
                "source_version",
                {"source_task_id": source_task_id, "raw_sha256": raw_sha256},
            ),
            source_task_id=source_task_id,
            raw_sha256=raw_sha256,
            byte_length=len(raw_bytes),
            retrieved_at=datetime.fromisoformat(SOURCE_CORPUS_TIMESTAMP),
            submitted_url=entry["fetch_url"],
            final_url=retrieval_url,
            http_status=200,
            content_type=content_type,
        )
        source_version = _preserve_existing_source_version_metadata(source_version)
        stored = AppendOnlySourceStore(SOURCE_RAW_DIR / "_content_addressed").put(
            raw_bytes, source_version
        )
        content_kind = _content_kind(raw_path, content_type)
        extracted_artifacts: list[dict[str, str]] = []
        discovered_document_urls: list[str] = []
        if content_kind == "pdf":
            extracted_artifacts = _extract_pdf_artifacts(
                raw_path,
                extracted_dir,
                max_pages=max_pdf_pages,
                force=force,
            )
        elif content_kind == "html":
            extracted_artifacts, discovered_document_urls = _extract_html_artifacts(
                raw_path,
                extracted_dir,
                retrieval_url,
            )
        else:
            extracted_artifacts = _extract_binary_note(raw_path, extracted_dir, content_type)
        return {
            **entry,
            "status": "extracted",
            "content_type": content_type,
            "content_kind": content_kind,
            "raw_path": repo_relative_posix(raw_path),
            "raw_sha256": raw_sha256,
            "raw_bytes": len(raw_bytes),
            "source_task_id": source_task_id,
            "source_version_id": source_version.source_version_id,
            "content_addressed_path": repo_relative_posix(stored.path),
            "extracted_artifacts": extracted_artifacts,
            "discovered_document_urls": discovered_document_urls,
            "autoformalized": False,
        }
    except Exception as exc:
        failure = classify_fetch_failure(exc)
        return {
            **entry,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "failure": failure.model_dump(mode="json"),
            "autoformalized": False,
        }


def _preserve_existing_source_version_metadata(candidate: SourceVersion) -> SourceVersion:
    """Reuse immutable metadata when cached bytes are extracted again.

    A cached file only exposes an extension-derived media type, which may be less
    specific than the original HTTP response (for example ``text/html`` instead of
    ``text/html; charset=utf-8``). The source-version identity is task-and-content
    derived, so an existing record with the same immutable acquisition coordinates is
    authoritative and must be reused byte-for-byte.
    """
    safe_version_id = candidate.source_version_id.replace(":", "_").replace("/", "_")
    metadata_path = SOURCE_RAW_DIR / "_content_addressed" / "versions" / f"{safe_version_id}.json"
    if not metadata_path.is_file():
        return candidate
    existing = SourceVersion.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    identity_fields = (
        "source_version_id",
        "source_task_id",
        "raw_sha256",
        "byte_length",
        "submitted_url",
        "final_url",
    )
    if any(getattr(existing, field) != getattr(candidate, field) for field in identity_fields):
        raise ValueError(f"existing source-version identity mismatch at {metadata_path}")
    return existing


def _download_bytes(
    url: str,
    raw_dir: Path,
    *,
    force: bool,
    max_bytes: int | None = None,
) -> tuple[Path, str]:
    """Return cached or fetched bytes, rejecting content beyond the declared cap."""
    if not force:
        existing = sorted(raw_dir.glob("source.*"))
        if existing:
            if max_bytes is not None and existing[0].stat().st_size > max_bytes:
                raise ValueError(f"source exceeds max_download_bytes={max_bytes}")
            return existing[0], _content_type_from_extension(existing[0])
    # Some provider CDNs return gateway errors for browser-like automation agents while
    # serving the same immutable document to command-line retrieval clients.
    request = Request(
        url,
        headers={"User-Agent": "Wget/1.21.4 RULER-source-corpus/0.1"},
    )
    with urlopen(request, timeout=90) as response:
        content_type = response.headers.get("content-type", "application/octet-stream")
        extension = _extension_from_url_or_type(url, content_type)
        raw_path = raw_dir / f"source{extension}"
        if raw_path.exists() and not force:
            return raw_path, content_type
        payload = response.read(max_bytes + 1) if max_bytes is not None else response.read()
        if max_bytes is not None and len(payload) > max_bytes:
            raise ValueError(f"source exceeds max_download_bytes={max_bytes}")
        raw_path.write_bytes(payload)
        return raw_path, content_type


def _content_type_from_extension(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    if path.suffix.lower() in {".html", ".htm"}:
        return "text/html"
    if path.suffix.lower() == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _extract_pdf_artifacts(
    raw_path: Path,
    extracted_dir: Path,
    *,
    max_pages: int | None = None,
    force: bool = False,
) -> list[dict[str, str]]:
    """Create dual PDF views after enforcing an optional page-count budget."""
    if max_pages is not None:
        page_count = len(PdfReader(raw_path).pages)
        if page_count > max_pages:
            raise ValueError(f"PDF has {page_count} pages; max_pdf_pages={max_pages}")
    markdown_path = extracted_dir / "docling.md"
    text_path = extracted_dir / "pypdf.txt"
    sections_path = extracted_dir / "sections.yaml"
    if force or not markdown_path.exists():
        markdown = _extract_docling_markdown(raw_path)
        write_text(markdown_path, markdown)
    else:
        markdown = markdown_path.read_text(encoding="utf-8", errors="ignore")
    text = _extract_pypdf_text(raw_path)
    write_text(text_path, text)
    write_yaml(sections_path, _markdown_sections(markdown))
    return [
        {"kind": "docling_markdown", "path": repo_relative_posix(markdown_path)},
        {"kind": "pypdf_text", "path": repo_relative_posix(text_path)},
        {"kind": "section_index", "path": repo_relative_posix(sections_path)},
    ]


def _extract_html_artifacts(
    raw_path: Path,
    extracted_dir: Path,
    base_url: str,
) -> tuple[list[dict[str, str]], list[str]]:
    html = raw_path.read_text(encoding="utf-8", errors="ignore")
    parser = _HTMLTextAndLinkParser()
    parser.feed(html)
    text_path = extracted_dir / "html_text.txt"
    links_path = extracted_dir / "discovered_links.yaml"
    discovered_document_urls = _discover_document_urls(parser.links, base_url)
    write_text(text_path, "\n".join(parser.text_parts) + "\n")
    write_yaml(
        links_path,
        {
            "base_url": base_url,
            "all_links": sorted({_canonical_url(urljoin(base_url, link)) for link in parser.links}),
            "document_links": discovered_document_urls,
        },
    )
    return (
        [
            {"kind": "html_text", "path": repo_relative_posix(text_path)},
            {"kind": "discovered_links", "path": repo_relative_posix(links_path)},
        ],
        discovered_document_urls,
    )


def _extract_binary_note(
    raw_path: Path,
    extracted_dir: Path,
    content_type: str,
) -> list[dict[str, str]]:
    note_path = extracted_dir / "extraction_note.txt"
    write_text(note_path, f"No text extractor configured for {content_type} at {raw_path.name}.\n")
    return [{"kind": "extraction_note", "path": repo_relative_posix(note_path)}]


def _extract_docling_markdown(pdf_path: Path) -> str:
    options = PdfPipelineOptions()
    options.do_ocr = False
    options.do_table_structure = True
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()


def _extract_pypdf_text(pdf_path: Path) -> str:
    reader = PdfReader(pdf_path)
    chunks = []
    for index, page in enumerate(reader.pages, start=1):
        chunks.append(f"\n\n--- page {index} ---\n")
        chunks.append(page.extract_text() or "")
    return "\n".join(line.rstrip() for line in "\n".join(chunks).splitlines()).strip() + "\n"


def _markdown_sections(markdown: str) -> list[dict[str, Any]]:
    sections = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if not match:
            continue
        sections.append(
            {
                "level": len(match.group(1)),
                "title": match.group(2).strip(),
                "line": line_number,
            }
        )
    return sections


def _discover_document_urls(raw_links: list[str], base_url: str) -> list[str]:
    discovered = []
    for link in raw_links:
        url = _canonical_url(urljoin(base_url, link))
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host != urlparse(base_url).netloc.lower():
            continue
        if parsed.path.lower().endswith(".pdf"):
            discovered.append(url)
    return sorted(set(discovered))


def _architecture_payload() -> dict[str, str]:
    return {
        "raw_root": repo_relative_posix(SOURCE_RAW_DIR),
        "extracted_root": repo_relative_posix(SOURCE_EXTRACTED_DIR),
        "manifest_root": repo_relative_posix(SOURCE_MANIFEST_DIR),
        "index_root": repo_relative_posix(SOURCE_INDEX_DIR),
        "formalization_boundary": "No writes to kb/ or data/candidates/ in this workflow.",
    }


def _source_kind_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if path.endswith((".html", ".htm")) or not Path(path).suffix:
        return "html_page"
    return "downloadable_resource"


def _content_kind(raw_path: Path, content_type: str) -> str:
    lowered_type = content_type.lower()
    suffix = raw_path.suffix.lower()
    if "pdf" in lowered_type or suffix == ".pdf":
        return "pdf"
    if "html" in lowered_type or suffix in {".html", ".htm"}:
        return "html"
    return "binary"


def _extension_from_url_or_type(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".pdf", ".html", ".htm", ".txt"}:
        return suffix
    lowered_type = content_type.lower()
    if "pdf" in lowered_type:
        return ".pdf"
    if "html" in lowered_type:
        return ".html"
    if "text/plain" in lowered_type:
        return ".txt"
    return ".bin"


def _document_id(url: str) -> str:
    parsed = urlparse(url)
    stem = Path(parsed.path).stem or "page"
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_") or "document"
    host_slug = re.sub(r"[^a-z0-9]+", "_", parsed.netloc.lower()).strip("_")
    return f"{host_slug}_{slug[:48]}_{hashlib.sha256(url.encode()).hexdigest()[:10]}"


def _organization_id(providers: list[str]) -> str:
    if len(providers) == 1:
        normalized = unicodedata.normalize("NFKD", providers[0]).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_") or DEFAULT_SOURCE_GROUP
    return DEFAULT_SOURCE_GROUP


def _canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in TRACKING_QUERY_KEYS and not key.startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query_items),
            "",
        )
    )
