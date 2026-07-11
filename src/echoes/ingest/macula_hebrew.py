"""MACULA Hebrew node adapter with canonical identity and provenance preservation."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict

from echoes.corpus.analysis import AnalysisReading, derive_analysis_stream
from echoes.corpus.books import BookSpec, book_by_code, validate_reference
from echoes.corpus.models import (
    CANONICAL_TOKEN_COLUMNS,
    CANONICAL_TOKEN_POLARS_SCHEMA,
    CanonicalToken,
    IngestionIssue,
    Language,
    ValidationSeverity,
)
from echoes.corpus.token_ids import generate_source_edition_token_id
from echoes.manifests.sources import SourceManifest
from echoes.normalize.hebrew import is_punctuation, normalize_hebrew_token, normalize_lemma
from echoes.settings import HebrewNormalization

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_WORD_PATTERN = re.compile(
    r"^(?P<book>[A-Za-z0-9]{3})\s+(?P<chapter>[1-9][0-9]*):"
    r"(?P<verse>[1-9][0-9]*)!(?P<word>[1-9][0-9]*)$"
)
SOURCE_RECORD_PATTERN = re.compile(r"^[^\s/#\\]+$")
MORPHOLOGY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9/._:-]*$")
CHAPTER_FILE_PATTERN = re.compile(
    r"^(?P<book_number>[0-9]{2})-(?P<book>[A-Za-z0-9]{3})-(?P<chapter>[0-9]{3})\.xml$"
)
ROLE_CATEGORIES = {"S", "O", "O2", "IO", "V", "VC", "P", "PP", "ADV"}


class HebrewIngestionError(RuntimeError):
    """Raised when source structure cannot be mapped without data loss or fabrication."""


class IngestionSummary(BaseModel):
    """Concise deterministic summary of one adapter run."""

    model_config = ConfigDict(extra="forbid")

    source_records: int
    processed_tokens: int
    books: int
    chapters: int
    verses: int
    hebrew_tokens: int
    aramaic_tokens: int
    variant_tokens: int
    punctuation_tokens: int
    issues_by_severity: dict[str, int]


@dataclass(frozen=True, slots=True)
class ParsedReference:
    book: BookSpec
    chapter: int
    verse: int
    word_position: int


@dataclass(slots=True)
class NativeToken:
    source_file: str
    source_record_id: str
    source_word_id: str
    source_row_reference: str
    surface_form: str
    language: Language
    reference: ParsedReference
    attributes: dict[str, str]
    ancestry: list[dict[str, str]]
    sentence_id: str | None
    clause_id: str | None
    phrase_id: str | None
    syntactic_function: str | None
    alternate_tree_count: int


@dataclass(frozen=True, slots=True)
class AdapterResult:
    tokens: pl.DataFrame
    analysis_tokens: pl.DataFrame
    source_records: pl.DataFrame
    issues: list[IngestionIssue]
    summary: IngestionSummary

    def token_models(self) -> list[CanonicalToken]:
        """Materialize Pydantic tokens for small fixtures and focused inspection."""
        return [CanonicalToken.model_validate(row) for row in self.tokens.to_dicts()]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _clean_optional(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_reference(value: str) -> ParsedReference:
    match = SOURCE_WORD_PATTERN.fullmatch(value.strip())
    if match is None:
        raise HebrewIngestionError(
            f"invalid MACULA word reference '{value}'; expected BOOK chapter:verse!word"
        )
    try:
        book = book_by_code(match.group("book"))
        chapter = int(match.group("chapter"))
        verse = int(match.group("verse"))
        word_position = int(match.group("word"))
        validate_reference(book, chapter, verse)
    except ValueError as exc:
        raise HebrewIngestionError(str(exc)) from exc
    return ParsedReference(book, chapter, verse, word_position)


def _language(value: str | None, reference: ParsedReference) -> tuple[Language, bool]:
    normalized = (value or "").strip().lower()
    if normalized in {"h", "he", "heb", "hebrew"}:
        return Language.HEBREW, False
    if normalized in {"a", "arc", "aramaic"}:
        return Language.ARAMAIC, False
    aramaic_reference = (
        (
            reference.book.code == "EZR"
            and (reference.chapter in {5, 6} or (reference.chapter == 4 and reference.verse >= 8))
        )
        or (reference.book.code == "EZR" and reference.chapter == 7 and reference.verse <= 26)
        or (reference.book.code == "DAN" and (3 <= reference.chapter <= 7))
        or (reference.book.code == "DAN" and reference.chapter == 2 and reference.verse >= 4)
        or (reference.book.code == "JER" and reference.chapter == 10 and reference.verse == 11)
    )
    return (Language.ARAMAIC if aramaic_reference else Language.HEBREW), True


def _nearest_attribute(ancestry: list[dict[str, str]], *names: str) -> str | None:
    for attributes in reversed(ancestry):
        for name in names:
            value = _clean_optional(attributes.get(name))
            if value is not None:
                return value
    return None


def _syntactic_context(
    ancestry: list[dict[str, str]], source_file: str
) -> tuple[str | None, str | None, str | None]:
    clause_id = None
    phrase_id = None
    function = None
    for attributes in reversed(ancestry):
        category = attributes.get("Cat", "")
        node_id = _clean_optional(attributes.get("nodeId") or attributes.get("morphId"))
        if clause_id is None and category == "CL":
            clause_id = node_id and f"{source_file}#{node_id}"
        elif phrase_id is None and node_id is not None and category not in ROLE_CATEGORIES:
            phrase_id = f"{source_file}#{node_id}"
        if function is None and category in ROLE_CATEGORIES:
            function = category
    return clause_id, phrase_id, function


def _chapter_identity(path: Path) -> tuple[int, str, int]:
    match = CHAPTER_FILE_PATTERN.fullmatch(path.name)
    if match is None:
        raise HebrewIngestionError(f"unexpected MACULA chapter filename: {path.name}")
    return (
        int(match.group("book_number")),
        match.group("book").upper(),
        int(match.group("chapter")),
    )


def _token_from_element(
    element: ET.Element,
    *,
    ancestry: list[dict[str, str]],
    sentence_id: str | None,
    source_file: str,
    alternate_tree_count: int,
    issues: list[IngestionIssue],
) -> NativeToken:
    attributes = {str(key): str(value) for key, value in element.attrib.items()}
    source_record_id = _clean_optional(attributes.get(XML_ID))
    if source_record_id is None:
        source_record_id = _clean_optional(attributes.get("n"))
        if source_record_id is not None:
            issues.append(
                IngestionIssue(
                    severity=ValidationSeverity.WARNING,
                    code="source-id-fallback",
                    message="morpheme lacks xml:id; preserved upstream n identifier",
                    source_record_id=source_record_id,
                )
            )
    if source_record_id is None:
        raise HebrewIngestionError(f"morpheme without xml:id or n in {source_file}")
    if SOURCE_RECORD_PATTERN.fullmatch(source_record_id) is None:
        raise HebrewIngestionError(f"malformed source record ID: {source_record_id}")

    source_word_id = _clean_optional(attributes.get("word"))
    if source_word_id is None:
        raise HebrewIngestionError(f"morpheme {source_record_id} lacks required word reference")
    reference = _parse_reference(source_word_id)
    surface_form = element.text or ""
    is_zero_width = not surface_form
    if is_zero_width:
        issues.append(
            IngestionIssue(
                severity=ValidationSeverity.INFORMATIONAL,
                code="zero-width-morpheme",
                message="preserved an explicitly annotated source morpheme with empty surface text",
                source_record_id=source_record_id,
                book=reference.book.code,
                chapter=reference.chapter,
                verse=reference.verse,
            )
        )
    morphology = _clean_optional(attributes.get("morph"))
    if morphology is not None and MORPHOLOGY_PATTERN.fullmatch(morphology) is None:
        raise HebrewIngestionError(
            f"morpheme {source_record_id} has malformed morphology '{morphology}'"
        )
    language, inferred = _language(attributes.get("lang"), reference)
    if inferred:
        issues.append(
            IngestionIssue(
                severity=ValidationSeverity.WARNING,
                code="language-inferred",
                message="language was absent or unknown and was inferred from canonical passage",
                source_record_id=source_record_id,
                book=reference.book.code,
                chapter=reference.chapter,
                verse=reference.verse,
            )
        )
    clause_id, phrase_id, syntactic_function = _syntactic_context(ancestry, source_file)
    return NativeToken(
        source_file=source_file,
        source_record_id=source_record_id,
        source_word_id=source_word_id,
        source_row_reference=f"{source_file}#{source_record_id}",
        surface_form=surface_form,
        language=language,
        reference=reference,
        attributes=attributes,
        ancestry=ancestry,
        sentence_id=sentence_id,
        clause_id=clause_id,
        phrase_id=phrase_id,
        syntactic_function=syntactic_function,
        alternate_tree_count=alternate_tree_count,
    )


def _walk_preferred_tree(
    element: ET.Element,
    *,
    ancestry: list[dict[str, str]],
    sentence_id: str | None,
    source_file: str,
    alternate_tree_count: int,
    tokens: list[NativeToken],
    issues: list[IngestionIssue],
) -> None:
    name = _local_name(element.tag)
    next_ancestry = ancestry
    if name in {"Node", "c"}:
        next_ancestry = [*ancestry, {str(key): str(value) for key, value in element.attrib.items()}]
    if name == "m":
        tokens.append(
            _token_from_element(
                element,
                ancestry=next_ancestry,
                sentence_id=sentence_id,
                source_file=source_file,
                alternate_tree_count=alternate_tree_count,
                issues=issues,
            )
        )
        return
    for child in element:
        _walk_preferred_tree(
            child,
            ancestry=next_ancestry,
            sentence_id=sentence_id,
            source_file=source_file,
            alternate_tree_count=alternate_tree_count,
            tokens=tokens,
            issues=issues,
        )


def _parse_chapter(
    path: Path, *, raw_root: Path, issues: list[IngestionIssue]
) -> list[NativeToken]:
    source_file = path.relative_to(raw_root).as_posix()
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise HebrewIngestionError(f"could not parse {source_file}: {exc}") from exc

    book_number, filename_book, filename_chapter = _chapter_identity(path)
    chapter_tokens: list[NativeToken] = []
    sentences = [element for element in root.iter() if _local_name(element.tag) == "Sentence"]
    if not sentences:
        raise HebrewIngestionError(f"no Sentence elements found in {source_file}")
    for sentence_index, sentence in enumerate(sentences, start=1):
        trees = [element for element in sentence.iter() if _local_name(element.tag) == "Tree"]
        if not trees:
            raise HebrewIngestionError(f"sentence {sentence_index} has no Tree in {source_file}")
        sentence_label = _clean_optional(sentence.attrib.get("verse") or sentence.attrib.get("id"))
        sentence_id = f"{source_file}#sentence-{sentence_index:04d}"
        if sentence_label is not None:
            sentence_id = f"{sentence_id}:{sentence_label}"
        alternate_count = len(trees) - 1
        if alternate_count:
            issues.append(
                IngestionIssue(
                    severity=ValidationSeverity.INFORMATIONAL,
                    code="alternate-syntax-trees",
                    message=(
                        f"selected the first upstream syntax analysis and preserved the "
                        f"count of {alternate_count} alternative tree(s)"
                    ),
                    book=filename_book,
                    chapter=filename_chapter,
                )
            )
        _walk_preferred_tree(
            trees[0],
            ancestry=[],
            sentence_id=sentence_id,
            source_file=source_file,
            alternate_tree_count=alternate_count,
            tokens=chapter_tokens,
            issues=issues,
        )

    for token in chapter_tokens:
        if token.reference.book.source_number != book_number:
            raise HebrewIngestionError(f"book mismatch in {source_file}: {token.source_word_id}")
        if token.reference.book.code != filename_book:
            raise HebrewIngestionError(
                f"book-code mismatch in {source_file}: {token.source_word_id}"
            )
        if token.reference.chapter != filename_chapter:
            raise HebrewIngestionError(f"chapter mismatch in {source_file}: {token.source_word_id}")
    return chapter_tokens


def _morphology(native: NativeToken) -> str | None:
    keys = ("morph", "pos", "type", "stem", "person", "gender", "number", "state")
    values = {key: native.attributes[key] for key in keys if native.attributes.get(key)}
    return _canonical_json(values) if values else None


def _semantic_domain(native: NativeToken) -> str | None:
    return _clean_optional(
        native.attributes.get("ContextualDomain")
        or native.attributes.get("contextualdomain")
        or native.attributes.get("LexDomain")
        or native.attributes.get("lexdomain")
        or native.attributes.get("CoreDomain")
        or native.attributes.get("coredomain")
    )


def _variant_type(native: NativeToken) -> Literal["ketiv", "qere"] | None:
    raw_type = _clean_optional(native.attributes.get("type"))
    if raw_type is None:
        return None
    lowered = raw_type.lower()
    is_ketiv = "ketiv" in lowered or "kethiv" in lowered
    is_qere = "qere" in lowered
    if is_ketiv and is_qere:
        raise HebrewIngestionError(
            f"source record {native.source_record_id} ambiguously declares both Ketiv and Qere"
        )
    if is_ketiv:
        return "ketiv"
    if is_qere:
        return "qere"
    return None


def _variant_group_id(group: list[NativeToken]) -> str | None:
    variants = [token for token in group if _variant_type(token) is not None]
    if not variants:
        return None
    reading_types = [_variant_type(token) for token in variants]
    duplicate_types = [
        reading_type for reading_type, count in Counter(reading_types).items() if count > 1
    ]
    if duplicate_types:
        source_word_reference = variants[0].source_word_id
        raise HebrewIngestionError(
            f"variant group {source_word_reference} has duplicate readings: {duplicate_types}"
        )
    parsed_reference = variants[0].reference
    source_identity = "\0".join(sorted(token.source_record_id for token in variants))
    digest = hashlib.sha256(source_identity.encode("utf-8")).hexdigest()[:12]
    return (
        f"KQ_{parsed_reference.book.code}_{parsed_reference.chapter:03d}_"
        f"{parsed_reference.verse:03d}_{parsed_reference.word_position:04d}~{digest}"
    )


def _canonicalize(
    native_tokens: list[NativeToken],
    *,
    source: SourceManifest,
    normalization: HebrewNormalization,
    corpus_position_offset: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    source_ids = [token.source_record_id for token in native_tokens]
    duplicate_source_ids = sorted(
        source_id for source_id, count in Counter(source_ids).items() if count > 1
    )
    if duplicate_source_ids:
        preview = ", ".join(duplicate_source_ids[:5])
        raise HebrewIngestionError(f"duplicate source record IDs: {preview}")

    native_tokens.sort(
        key=lambda token: (
            token.reference.book.order,
            token.reference.chapter,
            token.reference.verse,
            token.reference.word_position,
            token.source_record_id,
        )
    )
    word_groups: dict[tuple[int, int, int, int], list[NativeToken]] = defaultdict(list)
    for token in native_tokens:
        key = (
            token.reference.book.order,
            token.reference.chapter,
            token.reference.verse,
            token.reference.word_position,
        )
        word_groups[key].append(token)
    variant_group_ids = {key: _variant_group_id(group) for key, group in word_groups.items()}

    verse_positions: Counter[tuple[int, int, int]] = Counter()
    clause_positions: Counter[str] = Counter()
    canonical_models: list[CanonicalToken] = []
    source_records: list[dict[str, object]] = []
    for corpus_position, native in enumerate(native_tokens, start=corpus_position_offset + 1):
        word_key = (
            native.reference.book.order,
            native.reference.chapter,
            native.reference.verse,
            native.reference.word_position,
        )
        group = word_groups[word_key]
        position_in_word = group.index(native) + 1
        verse_key = word_key[:3]
        verse_positions[verse_key] += 1
        if native.clause_id is not None:
            clause_positions[native.clause_id] += 1
            position_in_clause: int | None = clause_positions[native.clause_id]
        else:
            position_in_clause = None

        variant_type = _variant_type(native)
        variant_group_id = variant_group_ids[word_key]
        paired_group = variant_group_id is not None and {
            reading for item in group if (reading := _variant_type(item)) is not None
        } == {"ketiv", "qere"}
        token_id = generate_source_edition_token_id(
            book_identifier=native.reference.book.code,
            chapter=native.reference.chapter,
            verse=native.reference.verse,
            source_token_position=native.reference.word_position,
            source_subtoken_position=position_in_word if len(group) > 1 else None,
            source_record_id=native.source_record_id,
            disambiguate_with_source_record=variant_type is not None,
        )
        forms = (
            normalize_hebrew_token(native.surface_form, normalization)
            if native.surface_form
            else None
        )
        is_variant = variant_type is not None
        ketiv_form = native.surface_form if variant_type == "ketiv" else None
        qere_form = native.surface_form if variant_type == "qere" else None
        raw = {
            "attributes": native.attributes,
            "ancestry": native.ancestry,
            "alternate_tree_count": native.alternate_tree_count,
        }
        raw_json = _canonical_json(raw)
        morphology = _morphology(native)
        lemma = normalize_lemma(
            _nearest_attribute(native.ancestry, "lemma")
            or _clean_optional(native.attributes.get("lemma")),
            normalization,
        )
        canonical_models.append(
            CanonicalToken(
                token_id=token_id,
                source_id=source.source_id,
                source_version=source.version_or_commit or "UNPINNED",
                source_file=native.source_file,
                source_record_id=native.source_record_id,
                source_word_id=native.source_word_id,
                source_edition_reference=(
                    f"{native.reference.book.code} {native.reference.chapter}:"
                    f"{native.reference.verse}"
                ),
                source_row_reference=native.source_row_reference,
                book=native.reference.book.code,
                book_order=native.reference.book.order,
                chapter=native.reference.chapter,
                verse=native.reference.verse,
                sentence_id=native.sentence_id,
                clause_id=native.clause_id,
                phrase_id=native.phrase_id,
                position_in_verse=verse_positions[verse_key],
                position_in_clause=position_in_clause,
                position_in_corpus=corpus_position,
                position_in_word=position_in_word,
                surface_form=forms.surface_form if forms is not None else "",
                normalized_form=forms.normalized_form if forms is not None else "",
                unpointed_form=forms.unpointed_form if forms is not None else "",
                is_zero_width=forms is None,
                lemma=lemma,
                part_of_speech=_clean_optional(native.attributes.get("pos")),
                morphology_json=morphology,
                syntactic_function=native.syntactic_function,
                syntactic_head_source_id=None,
                semantic_domain=_semantic_domain(native),
                word_sense=_nearest_attribute(native.ancestry, "SenseNumber")
                or _clean_optional(native.attributes.get("sensenumber")),
                participant_id=_nearest_attribute(native.ancestry, "Ref")
                or _clean_optional(native.attributes.get("participantref")),
                speaker_id=_nearest_attribute(native.ancestry, "Speaker", "speaker"),
                entity_id=_clean_optional(native.attributes.get("entity")),
                english_gloss=_clean_optional(native.attributes.get("english")),
                language=native.language,
                is_punctuation=is_punctuation(native.surface_form),
                is_variant=is_variant,
                variant_type=variant_type,
                variant_group_id=variant_group_id,
                is_default_reading=(not paired_group or variant_type == "qere"),
                ketiv_form=ketiv_form,
                qere_form=qere_form,
                source_extras_json=raw_json,
            )
        )
        source_records.append(
            {
                "source_record_id": native.source_record_id,
                "source_file": native.source_file,
                "source_row_reference": native.source_row_reference,
                "source_word_id": native.source_word_id,
                "raw_json": raw_json,
                "raw_sha256": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
            }
        )

    validate_canonical_identities(canonical_models)
    canonical_rows = [token.model_dump(mode="json") for token in canonical_models]
    return canonical_rows, source_records


def validate_canonical_identities(tokens: list[CanonicalToken]) -> None:
    """Reject token-ID or canonical-position collisions without silently repairing them."""
    token_ids = [token.token_id for token in tokens]
    collisions = sorted(token_id for token_id, count in Counter(token_ids).items() if count > 1)
    if collisions:
        raise HebrewIngestionError(f"canonical token-ID collisions: {', '.join(collisions[:5])}")
    positions = [
        (token.book, token.chapter, token.verse, token.position_in_verse) for token in tokens
    ]
    duplicate_positions = sorted(
        position for position, count in Counter(positions).items() if count > 1
    )
    if duplicate_positions:
        raise HebrewIngestionError(
            f"duplicate canonical token positions: {duplicate_positions[:5]}"
        )


def parse_macula_hebrew_nodes(
    raw_root: Path,
    *,
    source: SourceManifest,
    normalization: HebrewNormalization,
    analysis_reading: AnalysisReading = "qere",
) -> AdapterResult:
    """Parse every pinned MACULA node chapter into deterministic canonical tokens."""
    nodes_dir = raw_root / "WLC" / "nodes"
    if not nodes_dir.is_dir():
        raise HebrewIngestionError(f"MACULA node directory does not exist: {nodes_dir}")
    chapter_paths = sorted(
        path for path in nodes_dir.glob("*.xml") if path.name != "macula-hebrew.xml"
    )
    if not chapter_paths:
        raise HebrewIngestionError(f"no MACULA chapter XML files found in {nodes_dir}")
    chapter_paths.sort(key=_chapter_identity)
    issues: list[IngestionIssue] = []
    token_frames: list[pl.DataFrame] = []
    source_record_frames: list[pl.DataFrame] = []
    seen_source_ids: set[str] = set()
    seen_token_ids: set[str] = set()
    corpus_position_offset = 0
    source_record_schema = {
        "source_record_id": pl.String,
        "source_file": pl.String,
        "source_row_reference": pl.String,
        "source_word_id": pl.String,
        "raw_json": pl.String,
        "raw_sha256": pl.String,
    }
    for path in chapter_paths:
        native_tokens = _parse_chapter(path, raw_root=raw_root, issues=issues)
        canonical_rows, source_record_rows = _canonicalize(
            native_tokens,
            source=source,
            normalization=normalization,
            corpus_position_offset=corpus_position_offset,
        )
        chapter_source_ids = {str(row["source_record_id"]) for row in source_record_rows}
        duplicate_source_ids = sorted(chapter_source_ids & seen_source_ids)
        if duplicate_source_ids:
            raise HebrewIngestionError(
                f"duplicate source record IDs across chapters: {duplicate_source_ids[:5]}"
            )
        chapter_token_ids = {str(row["token_id"]) for row in canonical_rows}
        duplicate_token_ids = sorted(chapter_token_ids & seen_token_ids)
        if duplicate_token_ids:
            raise HebrewIngestionError(
                f"canonical token-ID collisions across chapters: {duplicate_token_ids[:5]}"
            )
        seen_source_ids.update(chapter_source_ids)
        seen_token_ids.update(chapter_token_ids)
        token_frames.append(
            pl.DataFrame(
                canonical_rows,
                schema=CANONICAL_TOKEN_POLARS_SCHEMA,
                orient="row",
            ).select(CANONICAL_TOKEN_COLUMNS)
        )
        source_record_frames.append(
            pl.DataFrame(
                source_record_rows,
                schema=source_record_schema,
                orient="row",
            )
        )
        corpus_position_offset += len(canonical_rows)

    canonical = pl.concat(token_frames, how="vertical", rechunk=True)
    source_records = pl.concat(source_record_frames, how="vertical", rechunk=True)
    if canonical["token_id"].n_unique() != canonical.height:
        raise HebrewIngestionError("canonical token-ID collisions remain after batch assembly")
    if canonical["position_in_corpus"].n_unique() != canonical.height:
        raise HebrewIngestionError("duplicate canonical corpus positions remain after assembly")
    analysis_tokens = derive_analysis_stream(
        canonical,
        analysis_reading=analysis_reading,
    )
    summary = IngestionSummary(
        source_records=source_records.height,
        processed_tokens=canonical.height,
        books=canonical["book"].n_unique(),
        chapters=canonical.select("book", "chapter").unique().height,
        verses=canonical.select("book", "chapter", "verse").unique().height,
        hebrew_tokens=canonical.filter(pl.col("language") == "hebrew").height,
        aramaic_tokens=canonical.filter(pl.col("language") == "aramaic").height,
        variant_tokens=canonical.filter(pl.col("is_variant")).height,
        punctuation_tokens=canonical.filter(pl.col("is_punctuation")).height,
        issues_by_severity=dict(sorted(Counter(issue.severity.value for issue in issues).items())),
    )
    return AdapterResult(
        tokens=canonical,
        analysis_tokens=analysis_tokens,
        source_records=source_records,
        issues=issues,
        summary=summary,
    )
