"""MACULA Greek Nestle1904 node adapter with canonical identity and provenance."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from pydantic import BaseModel, ConfigDict

from echoes.corpus.greek_books import (
    GreekBookSpec,
    greek_book_by_code,
    validate_greek_reference,
)
from echoes.corpus.greek_models import (
    GREEK_TOKEN_COLUMNS,
    GREEK_TOKEN_POLARS_SCHEMA,
    CanonicalGreekToken,
)
from echoes.corpus.models import IngestionIssue, ValidationSeverity
from echoes.corpus.token_ids import generate_source_edition_token_id
from echoes.manifests.sources import SourceManifest
from echoes.normalize.greek import (
    is_greek_elided,
    is_greek_punctuation,
    normalize_greek_lemma,
    normalize_greek_token,
)
from echoes.settings import GreekNormalization

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_WORD_PATTERN = re.compile(
    r"^(?P<book>[A-Z0-9]{3})\s+(?P<chapter>[1-9][0-9]*):"
    r"(?P<verse>[1-9][0-9]*)!(?P<word>[1-9][0-9]*)$"
)
SOURCE_RECORD_PATTERN = re.compile(r"^[^\s/#\\]+$")
BOOK_FILE_PATTERN = re.compile(r"^(?P<book_number>[0-9]{2})-(?P<stem>[a-z0-9]+)\.xml$")
ROLE_CATEGORIES = {"S", "O", "O2", "IO", "V", "VC", "P", "ADV"}
MORPHOLOGY_KEYS = (
    "FunctionalTag",
    "FormalTag",
    "Cat",
    "Type",
    "Case",
    "Gender",
    "Number",
    "Person",
    "Tense",
    "Voice",
    "Mood",
    "Degree",
)


class GreekIngestionError(RuntimeError):
    """Raised when source structure cannot be mapped without data loss or fabrication."""


class GreekIngestionSummary(BaseModel):
    """Concise deterministic summary of one Greek adapter run."""

    model_config = ConfigDict(extra="forbid")

    source_records: int
    processed_tokens: int
    books: int
    chapters: int
    verses: int
    elided_tokens: int
    punctuation_bearing_tokens: int
    issues_by_severity: dict[str, int]


@dataclass(frozen=True, slots=True)
class ParsedGreekReference:
    book: GreekBookSpec
    chapter: int
    verse: int
    word_position: int


@dataclass(slots=True)
class NativeGreekToken:
    source_file: str
    source_record_id: str
    source_word_id: str
    source_row_reference: str
    surface_form: str
    reference: ParsedGreekReference
    attributes: dict[str, str]
    ancestry: list[dict[str, str]]
    sentence_id: str | None
    clause_id: str | None
    phrase_id: str | None
    syntactic_function: str | None
    alternate_tree_count: int


@dataclass(frozen=True, slots=True)
class GreekAdapterResult:
    tokens: pl.DataFrame
    source_records: pl.DataFrame
    issues: list[IngestionIssue]
    summary: GreekIngestionSummary

    def token_models(self) -> list[CanonicalGreekToken]:
        """Materialize Pydantic tokens for small fixtures and focused inspection."""
        return [CanonicalGreekToken.model_validate(row) for row in self.tokens.to_dicts()]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _clean_optional(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_reference(value: str) -> ParsedGreekReference:
    match = SOURCE_WORD_PATTERN.fullmatch(value.strip())
    if match is None:
        raise GreekIngestionError(
            f"invalid MACULA Greek word reference '{value}'; expected BOOK chapter:verse!word"
        )
    try:
        book = greek_book_by_code(match.group("book"))
        chapter = int(match.group("chapter"))
        verse = int(match.group("verse"))
        word_position = int(match.group("word"))
        # The pinned edition encodes the shorter ending of Mark at 16:99;
        # verse numbers are validated as positive, chapter ranges strictly.
        validate_greek_reference(book, chapter, verse)
    except ValueError as exc:
        raise GreekIngestionError(str(exc)) from exc
    return ParsedGreekReference(book, chapter, verse, word_position)


def _book_identity(path: Path) -> tuple[int, str]:
    match = BOOK_FILE_PATTERN.fullmatch(path.name)
    if match is None:
        raise GreekIngestionError(f"unexpected MACULA Greek book filename: {path.name}")
    return int(match.group("book_number")), match.group("stem")


def _syntactic_context(
    ancestry: list[dict[str, str]], source_file: str
) -> tuple[str | None, str | None, str | None]:
    clause_id = None
    phrase_id = None
    function = None
    for attributes in reversed(ancestry):
        category = attributes.get("Cat", "")
        node_id = _clean_optional(attributes.get("nodeId"))
        if clause_id is None and category == "CL":
            clause_id = node_id and f"{source_file}#{node_id}"
        elif (
            phrase_id is None
            and node_id is not None
            and category not in ROLE_CATEGORIES
            and category != "CL"
        ):
            phrase_id = f"{source_file}#{node_id}"
        if function is None and category in ROLE_CATEGORIES:
            function = category
    return clause_id, phrase_id, function


def _token_from_element(
    element: ET.Element,
    *,
    ancestry: list[dict[str, str]],
    sentence_id: str | None,
    source_file: str,
    alternate_tree_count: int,
) -> NativeGreekToken:
    attributes = {str(key): str(value) for key, value in element.attrib.items()}
    source_record_id = _clean_optional(attributes.get(XML_ID))
    if source_record_id is None:
        raise GreekIngestionError(f"leaf word node without xml:id in {source_file}")
    if SOURCE_RECORD_PATTERN.fullmatch(source_record_id) is None:
        raise GreekIngestionError(f"malformed source record ID: {source_record_id}")
    source_word_id = _clean_optional(attributes.get("ref"))
    if source_word_id is None:
        raise GreekIngestionError(f"leaf word node {source_record_id} lacks required ref")
    reference = _parse_reference(source_word_id)
    surface_form = (element.text or "").strip()
    if not surface_form:
        raise GreekIngestionError(f"leaf word node {source_record_id} has empty text")
    clause_id, phrase_id, syntactic_function = _syntactic_context(ancestry, source_file)
    return NativeGreekToken(
        source_file=source_file,
        source_record_id=source_record_id,
        source_word_id=source_word_id,
        source_row_reference=f"{source_file}#{source_record_id}",
        surface_form=surface_form,
        reference=reference,
        attributes=attributes,
        ancestry=ancestry,
        sentence_id=sentence_id,
        clause_id=clause_id,
        phrase_id=phrase_id,
        syntactic_function=syntactic_function,
        alternate_tree_count=alternate_tree_count,
    )


def _walk_tree(
    element: ET.Element,
    *,
    ancestry: list[dict[str, str]],
    sentence_id: str | None,
    source_file: str,
    alternate_tree_count: int,
    tokens: list[NativeGreekToken],
) -> None:
    name = _local_name(element.tag)
    if name == "Node" and len(element) == 0:
        tokens.append(
            _token_from_element(
                element,
                ancestry=ancestry,
                sentence_id=sentence_id,
                source_file=source_file,
                alternate_tree_count=alternate_tree_count,
            )
        )
        return
    next_ancestry = ancestry
    if name == "Node":
        next_ancestry = [*ancestry, {str(key): str(value) for key, value in element.attrib.items()}]
    for child in element:
        _walk_tree(
            child,
            ancestry=next_ancestry,
            sentence_id=sentence_id,
            source_file=source_file,
            alternate_tree_count=alternate_tree_count,
            tokens=tokens,
        )


def _parse_book(
    path: Path, *, raw_root: Path, issues: list[IngestionIssue]
) -> list[NativeGreekToken]:
    source_file = path.relative_to(raw_root).as_posix()
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise GreekIngestionError(f"could not parse {source_file}: {exc}") from exc

    book_number, stem = _book_identity(path)
    book_tokens: list[NativeGreekToken] = []
    sentences = [element for element in root.iter() if _local_name(element.tag) == "Sentence"]
    if not sentences:
        raise GreekIngestionError(f"no Sentence elements found in {source_file}")
    for sentence_index, sentence in enumerate(sentences, start=1):
        trees = [element for element in sentence.iter() if _local_name(element.tag) == "Tree"]
        if not trees:
            raise GreekIngestionError(f"sentence {sentence_index} has no Tree in {source_file}")
        sentence_label = _clean_optional(sentence.attrib.get("ref"))
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
                )
            )
        _walk_tree(
            trees[0],
            ancestry=[],
            sentence_id=sentence_id,
            source_file=source_file,
            alternate_tree_count=alternate_count,
            tokens=book_tokens,
        )

    expected_book = None
    for token in book_tokens:
        if expected_book is None:
            expected_book = token.reference.book
            if expected_book.source_number != book_number:
                raise GreekIngestionError(
                    f"book-number mismatch in {source_file}: file {book_number:02d}, "
                    f"references {expected_book.code}"
                )
            if expected_book.source_file_stem != stem:
                raise GreekIngestionError(
                    f"book-name mismatch in {source_file}: file stem '{stem}', "
                    f"references {expected_book.code}"
                )
        elif token.reference.book is not expected_book:
            raise GreekIngestionError(f"book mismatch in {source_file}: {token.source_word_id}")
    return book_tokens


def _morphology(native: NativeGreekToken) -> str | None:
    values = {key: native.attributes[key] for key in MORPHOLOGY_KEYS if native.attributes.get(key)}
    return _canonical_json(values) if values else None


def _frame(native: NativeGreekToken) -> str | None:
    values = {
        key: native.attributes[key]
        for key in ("Frame", "SubjRef", "Ref")
        if native.attributes.get(key)
    }
    return _canonical_json(values) if values else None


def _canonicalize(
    native_tokens: list[NativeGreekToken],
    *,
    source: SourceManifest,
    normalization: GreekNormalization,
    corpus_position_offset: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    source_ids = [token.source_record_id for token in native_tokens]
    duplicate_source_ids = sorted(
        source_id for source_id, count in Counter(source_ids).items() if count > 1
    )
    if duplicate_source_ids:
        preview = ", ".join(duplicate_source_ids[:5])
        raise GreekIngestionError(f"duplicate source record IDs: {preview}")

    native_tokens.sort(
        key=lambda token: (
            token.reference.book.order,
            token.reference.chapter,
            token.reference.verse,
            token.reference.word_position,
            token.source_record_id,
        )
    )
    word_counts = Counter(
        (
            token.reference.book.order,
            token.reference.chapter,
            token.reference.verse,
            token.reference.word_position,
        )
        for token in native_tokens
    )
    duplicate_words = sorted(key for key, count in word_counts.items() if count > 1)
    if duplicate_words:
        raise GreekIngestionError(
            f"multiple leaf nodes share one source word reference: {duplicate_words[:5]}"
        )

    verse_positions: Counter[tuple[int, int, int]] = Counter()
    clause_positions: Counter[str] = Counter()
    canonical_models: list[CanonicalGreekToken] = []
    source_records: list[dict[str, object]] = []
    for corpus_position, native in enumerate(native_tokens, start=corpus_position_offset + 1):
        verse_key = (
            native.reference.book.order,
            native.reference.chapter,
            native.reference.verse,
        )
        verse_positions[verse_key] += 1
        if native.clause_id is not None:
            clause_positions[native.clause_id] += 1
            position_in_clause: int | None = clause_positions[native.clause_id]
        else:
            position_in_clause = None

        token_id = generate_source_edition_token_id(
            book_identifier=native.reference.book.code,
            chapter=native.reference.chapter,
            verse=native.reference.verse,
            source_token_position=native.reference.word_position,
            corpus_prefix="GNT",
        )
        forms = normalize_greek_token(native.surface_form, normalization)
        punctuation_only = is_greek_punctuation(native.surface_form)
        raw = {
            "attributes": native.attributes,
            "ancestry": native.ancestry,
            "alternate_tree_count": native.alternate_tree_count,
        }
        raw_json = _canonical_json(raw)
        canonical_models.append(
            CanonicalGreekToken(
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
                surface_form=forms.surface_form,
                normalized_form=forms.normalized_form,
                folded_form=forms.folded_form,
                source_normalized_form=_clean_optional(native.attributes.get("NormalizedForm")),
                leading_punctuation=forms.leading_punctuation,
                trailing_punctuation=forms.trailing_punctuation,
                is_elided=is_greek_elided(native.surface_form),
                lemma=normalize_greek_lemma(native.attributes.get("UnicodeLemma"), normalization),
                strong_number=_clean_optional(native.attributes.get("StrongNumber")),
                part_of_speech=_clean_optional(native.attributes.get("Cat")),
                morphology_json=_morphology(native),
                syntactic_function=native.syntactic_function,
                semantic_domain=_clean_optional(native.attributes.get("LexDomain")),
                word_sense=_clean_optional(native.attributes.get("LN")),
                participant_id=_clean_optional(
                    native.attributes.get("Ref") or native.attributes.get("SubjRef")
                ),
                frame_json=_frame(native),
                english_gloss=_clean_optional(native.attributes.get("Gloss")),
                is_punctuation=punctuation_only,
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

    validate_greek_canonical_identities(canonical_models)
    canonical_rows = [token.model_dump(mode="json") for token in canonical_models]
    return canonical_rows, source_records


def validate_greek_canonical_identities(tokens: list[CanonicalGreekToken]) -> None:
    """Reject token-ID or canonical-position collisions without silently repairing them."""
    token_ids = [token.token_id for token in tokens]
    collisions = sorted(token_id for token_id, count in Counter(token_ids).items() if count > 1)
    if collisions:
        raise GreekIngestionError(f"canonical token-ID collisions: {', '.join(collisions[:5])}")
    positions = [
        (token.book, token.chapter, token.verse, token.position_in_verse) for token in tokens
    ]
    duplicate_positions = sorted(
        position for position, count in Counter(positions).items() if count > 1
    )
    if duplicate_positions:
        raise GreekIngestionError(f"duplicate canonical token positions: {duplicate_positions[:5]}")


def parse_macula_greek_nodes(
    raw_root: Path,
    *,
    source: SourceManifest,
    normalization: GreekNormalization,
) -> GreekAdapterResult:
    """Parse every pinned MACULA Greek node book into deterministic canonical tokens."""
    nodes_dir = raw_root / "Nestle1904" / "nodes"
    if not nodes_dir.is_dir():
        raise GreekIngestionError(f"MACULA Greek node directory does not exist: {nodes_dir}")
    book_paths = sorted(nodes_dir.glob("*.xml"))
    if not book_paths:
        raise GreekIngestionError(f"no MACULA Greek book XML files found in {nodes_dir}")
    book_paths.sort(key=_book_identity)
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
    for path in book_paths:
        native_tokens = _parse_book(path, raw_root=raw_root, issues=issues)
        canonical_rows, source_record_rows = _canonicalize(
            native_tokens,
            source=source,
            normalization=normalization,
            corpus_position_offset=corpus_position_offset,
        )
        book_source_ids = {str(row["source_record_id"]) for row in source_record_rows}
        duplicate_source_ids = sorted(book_source_ids & seen_source_ids)
        if duplicate_source_ids:
            raise GreekIngestionError(
                f"duplicate source record IDs across books: {duplicate_source_ids[:5]}"
            )
        book_token_ids = {str(row["token_id"]) for row in canonical_rows}
        duplicate_token_ids = sorted(book_token_ids & seen_token_ids)
        if duplicate_token_ids:
            raise GreekIngestionError(
                f"canonical token-ID collisions across books: {duplicate_token_ids[:5]}"
            )
        seen_source_ids.update(book_source_ids)
        seen_token_ids.update(book_token_ids)
        token_frames.append(
            pl.DataFrame(
                canonical_rows,
                schema=GREEK_TOKEN_POLARS_SCHEMA,
                orient="row",
            ).select(GREEK_TOKEN_COLUMNS)
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
        raise GreekIngestionError("canonical token-ID collisions remain after batch assembly")
    if canonical["position_in_corpus"].n_unique() != canonical.height:
        raise GreekIngestionError("duplicate canonical corpus positions remain after assembly")
    summary = GreekIngestionSummary(
        source_records=source_records.height,
        processed_tokens=canonical.height,
        books=canonical["book"].n_unique(),
        chapters=canonical.select("book", "chapter").unique().height,
        verses=canonical.select("book", "chapter", "verse").unique().height,
        elided_tokens=canonical.filter(pl.col("is_elided")).height,
        punctuation_bearing_tokens=canonical.filter(
            (pl.col("leading_punctuation") != "") | (pl.col("trailing_punctuation") != "")
        ).height,
        issues_by_severity=dict(sorted(Counter(issue.severity.value for issue in issues).items())),
    )
    return GreekAdapterResult(
        tokens=canonical,
        source_records=source_records,
        issues=issues,
        summary=summary,
    )
