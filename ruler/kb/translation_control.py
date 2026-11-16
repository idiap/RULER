# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Controlled translation and vocabulary bridge. It aligns French source spans, controlled
English translations, glossary terms, and predicate candidates for autoformalization.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ruler.io import load_model_list, read_yaml, stable_hash, write_yaml
from ruler.paths import BUILD_DIR, REPO_ROOT
from ruler.schemas import ExtractedClauseSpan

TRANSLATION_FIXTURE = REPO_ROOT / "tests/fixtures/translation"
KB_TRANSLATION_DIR = BUILD_DIR / "translation_control"
KB_PREDICATE_DIR = KB_TRANSLATION_DIR
KB_AUDIT_DIR = KB_TRANSLATION_DIR
TRANSLATION_UNITS_FILE = KB_TRANSLATION_DIR / "source_fr_units.yaml"
ENGLISH_TRANSLATION_UNITS_FILE = KB_TRANSLATION_DIR / "controlled_english_units.yaml"
TRANSLATION_GLOSSARY_FILE = KB_TRANSLATION_DIR / "glossary.yaml"
VOCABULARY_PREDICATE_MAP_FILE = KB_TRANSLATION_DIR / "vocabulary_predicate_map.yaml"
AUTOFORMALIZATION_ALIGNMENT_FILE = KB_TRANSLATION_DIR / "alignment_report.yaml"
POLICY_CLAUSE_SPANS_FILE = TRANSLATION_FIXTURE / "source_spans.yaml"


class TranslationUnit(BaseModel):
    """Typed translation unit artifact used by the translation control workflow."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    span_id: str
    clause_id: str
    source_id: str
    source_language: str
    page_start: int
    page_end: int
    section: str
    source_title: str
    source_text: str
    source_text_hash: str
    term_ids: list[str] = Field(default_factory=list)


class EnglishTranslationUnit(BaseModel):
    """Typed english translation unit artifact used by the translation control workflow."""

    model_config = ConfigDict(extra="forbid")

    translation_id: str
    source_unit_id: str
    target_language: str
    controlled_title: str
    controlled_statement: str
    predicate_candidates: list[str] = Field(default_factory=list)
    semantic_constraints: list[str] = Field(default_factory=list)
    translation_status: str
    semantic_hash: str


class TranslationGlossaryEntry(BaseModel):
    """Typed translation glossary entry artifact used by the translation control workflow."""

    model_config = ConfigDict(extra="forbid")

    term_id: str
    source_language: str
    source_term: str
    preferred_english: str
    literal_english: str
    domain: str
    usage_note: str
    do_not_translate: bool
    review_status: str
    source_span_ids: list[str] = Field(default_factory=list)


class VocabularyPredicateMapping(BaseModel):
    """Typed vocabulary predicate mapping artifact used by the translation control workflow."""

    model_config = ConfigDict(extra="forbid")

    term_id: str
    source_term: str
    preferred_english: str
    predicate: str
    predicate_role: str
    source_span_ids: list[str] = Field(default_factory=list)
    target_rule_files: list[str] = Field(default_factory=list)
    status: str


def build_translation_units(
    spans: list[ExtractedClauseSpan] | None = None,
) -> list[TranslationUnit]:
    """Build translation units for the translation control workflow."""
    if spans is None:
        spans = load_model_list(POLICY_CLAUSE_SPANS_FILE, ExtractedClauseSpan)
    return [
        TranslationUnit(
            unit_id=f"translation_unit_{span.span_id.lower()}",
            span_id=span.span_id,
            clause_id=span.clause_id,
            source_id=span.source_id,
            source_language="fr",
            page_start=span.page_start,
            page_end=span.page_end,
            section=span.section,
            source_title=span.title,
            source_text=span.text,
            source_text_hash=span.text_sha256,
            term_ids=_term_ids_for_span(span.span_id),
        )
        for span in spans
    ]


def build_english_translation_units(
    units: list[TranslationUnit] | None = None,
) -> list[EnglishTranslationUnit]:
    """Build english translation units for the translation control workflow."""
    units = units or build_translation_units()
    translations: list[EnglishTranslationUnit] = []
    for unit in units:
        controlled = _translation_catalogue()["translations"][unit.span_id]
        payload = {
            "source_unit_id": unit.unit_id,
            "controlled_title": controlled["title"],
            "controlled_statement": controlled["statement"],
            "predicate_candidates": controlled["predicates"],
            "semantic_constraints": controlled["constraints"],
        }
        translations.append(
            EnglishTranslationUnit(
                translation_id=f"english_{unit.unit_id}",
                source_unit_id=unit.unit_id,
                target_language="en",
                controlled_title=controlled["title"],
                controlled_statement=controlled["statement"],
                predicate_candidates=controlled["predicates"],
                semantic_constraints=controlled["constraints"],
                translation_status="controlled_draft_needs_legal_review",
                semantic_hash=stable_hash(payload),
            )
        )
    return translations


def build_translation_glossary() -> list[TranslationGlossaryEntry]:
    """Build translation glossary for the translation control workflow."""
    return [TranslationGlossaryEntry(**entry) for entry in _translation_catalogue()["glossary"]]


def build_vocabulary_predicate_map() -> list[VocabularyPredicateMapping]:
    """Build vocabulary predicate map for the translation control workflow."""
    return [VocabularyPredicateMapping(**entry) for entry in _translation_catalogue()["predicates"]]


def build_autoformalization_alignment_report(
    *,
    units: list[TranslationUnit] | None = None,
    translations: list[EnglishTranslationUnit] | None = None,
    predicate_map: list[VocabularyPredicateMapping] | None = None,
    glossary: list[TranslationGlossaryEntry] | None = None,
) -> dict[str, Any]:
    """Build autoformalization alignment report for the translation control workflow."""
    if units is None:
        units = build_translation_units()
    if translations is None:
        translations = build_english_translation_units(units)
    if predicate_map is None:
        predicate_map = build_vocabulary_predicate_map()
    if glossary is None:
        glossary = build_translation_glossary()
    glossary_ids = {entry.term_id for entry in glossary}
    mapping_by_term = {entry.term_id: entry for entry in predicate_map}
    translated_by_unit = {translation.source_unit_id: translation for translation in translations}
    checks = []
    for unit in units:
        translation = translated_by_unit[unit.unit_id]
        mapped_terms = [term_id for term_id in unit.term_ids if term_id in mapping_by_term]
        missing_terms = sorted(set(unit.term_ids) - glossary_ids)
        checks.append(
            {
                "span_id": unit.span_id,
                "clause_id": unit.clause_id,
                "source_language": unit.source_language,
                "target_language": translation.target_language,
                "translation_id": translation.translation_id,
                "mapped_term_ids": mapped_terms,
                "predicate_candidates": sorted(
                    {mapping_by_term[term_id].predicate for term_id in mapped_terms}
                ),
                "missing_term_ids": missing_terms,
                "status": "pass" if mapped_terms and not missing_terms else "warn",
            }
        )
    return {
        "report_id": "autoformalization_translation_alignment",
        "translation_unit_count": len(units),
        "glossary_term_count": len(glossary_ids),
        "predicate_mapping_count": len(predicate_map),
        "checks": checks,
    }


def write_translation_control_artifacts() -> dict[str, Any]:
    """Write translation control artifacts for the translation control workflow."""
    units = build_translation_units()
    translations = build_english_translation_units(units)
    glossary = build_translation_glossary()
    predicate_map = build_vocabulary_predicate_map()
    report = build_autoformalization_alignment_report()
    return write_translation_control_payloads(units, translations, glossary, predicate_map, report)


def write_translation_control_payloads(
    units: list[TranslationUnit],
    translations: list[EnglishTranslationUnit],
    glossary: list[TranslationGlossaryEntry],
    predicate_map: list[VocabularyPredicateMapping],
    report: dict[str, Any],
) -> dict[str, Any]:
    """Serialize the native writer's five artifacts in order, without rollback."""
    paths = {
        "translation_units": TRANSLATION_UNITS_FILE,
        "english_translation_units": ENGLISH_TRANSLATION_UNITS_FILE,
        "translation_glossary": TRANSLATION_GLOSSARY_FILE,
        "vocabulary_predicate_map": VOCABULARY_PREDICATE_MAP_FILE,
        "autoformalization_alignment": AUTOFORMALIZATION_ALIGNMENT_FILE,
    }
    write_yaml(paths["translation_units"], [unit.model_dump(mode="json") for unit in units])
    write_yaml(
        paths["english_translation_units"],
        [translation.model_dump(mode="json") for translation in translations],
    )
    write_yaml(paths["translation_glossary"], [entry.model_dump(mode="json") for entry in glossary])
    write_yaml(
        paths["vocabulary_predicate_map"],
        [entry.model_dump(mode="json") for entry in predicate_map],
    )
    write_yaml(paths["autoformalization_alignment"], report)
    return paths


def translation_lookup_by_span() -> dict[str, EnglishTranslationUnit]:
    """Translation lookup by span for the translation control workflow."""
    units = build_translation_units()
    translations = build_english_translation_units(units)
    unit_by_id = {unit.unit_id: unit for unit in units}
    return {
        unit_by_id[translation.source_unit_id].span_id: translation for translation in translations
    }


def predicate_candidates_by_span() -> dict[str, list[str]]:
    """Predicate candidates by span for the translation control workflow."""
    by_span: dict[str, set[str]] = {}
    for mapping in build_vocabulary_predicate_map():
        for span_id in mapping.source_span_ids:
            by_span.setdefault(span_id, set()).add(mapping.predicate)
    return {span_id: sorted(predicates) for span_id, predicates in by_span.items()}


def validate_translation_control_artifacts() -> list[str]:
    """Validate translation control artifacts for the translation control workflow."""
    errors: list[str] = []
    for path in [
        TRANSLATION_UNITS_FILE,
        ENGLISH_TRANSLATION_UNITS_FILE,
        TRANSLATION_GLOSSARY_FILE,
        VOCABULARY_PREDICATE_MAP_FILE,
        AUTOFORMALIZATION_ALIGNMENT_FILE,
    ]:
        if not path.exists():
            errors.append(f"missing {path.relative_to(REPO_ROOT)}")
    if errors:
        return errors
    units = load_model_list(TRANSLATION_UNITS_FILE, TranslationUnit)
    translations = load_model_list(ENGLISH_TRANSLATION_UNITS_FILE, EnglishTranslationUnit)
    glossary = load_model_list(TRANSLATION_GLOSSARY_FILE, TranslationGlossaryEntry)
    predicates = load_model_list(VOCABULARY_PREDICATE_MAP_FILE, VocabularyPredicateMapping)
    unit_ids = {unit.unit_id for unit in units}
    glossary_ids = {entry.term_id for entry in glossary}
    for translation in translations:
        if translation.source_unit_id not in unit_ids:
            errors.append(f"{translation.translation_id}: unknown source unit")
        if not translation.predicate_candidates:
            errors.append(f"{translation.translation_id}: missing predicate candidates")
        if not translation.semantic_hash.startswith("sha256:"):
            errors.append(f"{translation.translation_id}: semantic_hash must use sha256")
    for unit in units:
        missing = sorted(set(unit.term_ids) - glossary_ids)
        if missing:
            errors.append(f"{unit.unit_id}: unknown term ids {missing}")
    for mapping in predicates:
        if mapping.term_id not in glossary_ids:
            errors.append(f"{mapping.term_id}: predicate mapping lacks glossary entry")
        if not mapping.source_span_ids:
            errors.append(f"{mapping.term_id}: predicate mapping lacks source spans")
    return errors


def _term_ids_for_span(span_id: str) -> list[str]:
    """Internal helper for term ids for span in the translation control workflow."""
    return [
        entry["term_id"]
        for entry in _translation_catalogue()["glossary"]
        if span_id in entry.get("source_span_ids", [])
    ]


def _translation_catalogue() -> dict[str, Any]:
    """Load demo inputs only when translation is requested, not during MCP startup."""
    return read_yaml(TRANSLATION_FIXTURE / "catalogue.yaml")
