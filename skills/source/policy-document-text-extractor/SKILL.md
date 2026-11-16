---
name: policy-document-text-extractor
description: Extract reviewable text, markdown, section indexes, and shallow discovered document links from downloaded policy documents without autoformalization. Use when raw PDFs or HTML source pages need layout-aware extraction surfaces for later controlled translation and reasoning.
---

# Policy Document Text Extractor

Create text and layout surfaces from raw source documents.

## Procedure

1. Read raw files from `data/sources/raw/<organization>/<document_id>/`.
2. For PDFs:
   - write Docling markdown to `docling.md`
   - write PyPDF text to `pypdf.txt`
   - write a heading inventory to `sections.yaml`
3. For HTML pages:
   - write visible text to `html_text.txt`
   - write all links and document links to `discovered_links.yaml`
4. Queue same-domain discovered PDF links as child corpus documents.
5. Record every derived artifact in `data/sources/manifests/<source>_extraction_manifest.yaml`.

## Gates

- This skill extracts surfaces only; it must not translate, summarize into claims, formalize, or promote.
- Keep discovered child documents linked to their parent page.
- Keep section indexes descriptive and non-normative.
- Treat extraction errors as audit data, not as missing evidence.
