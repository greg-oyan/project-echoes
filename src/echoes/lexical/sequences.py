"""Deterministic lexical sequences derived from authoritative passage membership."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from echoes.lexical.resources import LexicalResourceError, configure_duckdb_connection


class LexicalSequenceError(RuntimeError):
    """Raised when lexical passage sequences cannot be derived safely."""


_GLOSS_PUNCTUATION = re.compile(r"[^\w\s'-]+", flags=re.UNICODE)
_GLOSS_WHITESPACE = re.compile(r"\s+")
_SEQUENCE_FAMILIES = frozenset(
    {
        "lemma",
        "root",
        "surface",
        "folded_surface",
        "part_of_speech",
        "morphology",
        "english_gloss",
    }
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite morphology JSON number is not allowed: {value}")


def normalize_english_gloss(value: str | None) -> tuple[str, ...]:
    """Apply the registered conservative, non-stemming gloss normalization."""

    if value is None:
        return ()
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _GLOSS_PUNCTUATION.sub(" ", normalized)
    normalized = _GLOSS_WHITESPACE.sub(" ", normalized).strip(" '-")
    if not normalized:
        return ()
    return tuple(part for part in normalized.split(" ") if part)


def coarse_morphology(value: str | None) -> str | None:
    """Return a stable coarse morphology signature from source annotations only."""

    if not value:
        return None
    try:
        parsed = json.loads(value, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    allowed = {
        "case",
        "cat",
        "gender",
        "mood",
        "number",
        "person",
        "pos",
        "stem",
        "tense",
        "type",
        "voice",
    }
    selected = {
        str(key).casefold(): (
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).casefold()
            if isinstance(item, (dict, list))
            else str(item).casefold()
        )
        for key, item in parsed.items()
        if str(key).casefold() in allowed and item not in (None, "")
    }
    if not selected:
        # Formal tags are a source-provided compact morphology, not an inferred tree.
        for key in ("FormalTag", "FunctionalTag", "morph"):
            item = parsed.get(key)
            if item not in (None, ""):
                selected[key.casefold()] = str(item).casefold()
                break
    return json.dumps(selected, sort_keys=True, separators=(",", ":")) if selected else None


@dataclass(frozen=True, slots=True)
class FeatureOccurrence:
    """One lexical feature occurrence retaining token and passage positions."""

    value: str
    position_in_passage: int
    token_id: str
    source_word_id: str | None


@dataclass(frozen=True, slots=True)
class PassageLexicalSequence:
    """Governed lexical representations for one passage."""

    passage_id: str
    corpus: str
    book: str
    book_order: int
    analysis_profile: str
    analysis_reading: str
    granularity: str
    start_reference: str
    end_reference: str
    source_passage_digest: str
    start_stream_position_in_corpus: int
    token_count: int
    disputed_passage_flag: bool
    reference_gap: bool
    ketiv_structural_uncertainty: bool
    lemma: tuple[FeatureOccurrence, ...]
    root: tuple[FeatureOccurrence, ...]
    surface: tuple[FeatureOccurrence, ...]
    folded_surface: tuple[FeatureOccurrence, ...]
    part_of_speech: tuple[FeatureOccurrence, ...]
    morphology: tuple[FeatureOccurrence, ...]
    english_gloss: tuple[FeatureOccurrence, ...]
    provenance_token_ids: tuple[str, ...]
    zero_width_token_ids: tuple[str, ...]
    punctuation_token_ids: tuple[str, ...]
    elided_token_ids: tuple[str, ...]

    def values(self, family: str) -> tuple[str, ...]:
        """Return feature values for a governed family name."""

        if family not in _SEQUENCE_FAMILIES:
            raise LexicalSequenceError(f"unsupported sequence family: {family}")
        occurrences = getattr(self, family)
        return tuple(item.value for item in occurrences)


@dataclass(slots=True)
class _PassageBuilder:
    passage_id: str
    corpus: str
    book: str
    book_order: int
    analysis_profile: str
    analysis_reading: str
    granularity: str
    start_reference: str
    end_reference: str
    source_passage_digest: str
    start_stream_position_in_corpus: int
    token_count: int
    disputed_passage_flag: bool
    reference_gap: bool
    ketiv_structural_uncertainty: bool
    lemma: list[FeatureOccurrence] = field(default_factory=list)
    root: list[FeatureOccurrence] = field(default_factory=list)
    surface: list[FeatureOccurrence] = field(default_factory=list)
    folded_surface: list[FeatureOccurrence] = field(default_factory=list)
    part_of_speech: list[FeatureOccurrence] = field(default_factory=list)
    morphology: list[FeatureOccurrence] = field(default_factory=list)
    english_gloss: list[FeatureOccurrence] = field(default_factory=list)
    provenance_token_ids: list[str] = field(default_factory=list)
    zero_width_token_ids: list[str] = field(default_factory=list)
    punctuation_token_ids: list[str] = field(default_factory=list)
    elided_token_ids: list[str] = field(default_factory=list)
    membership_positions: list[int] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> _PassageBuilder:
        return cls(
            passage_id=str(row["passage_id"]),
            corpus=str(row["corpus"]),
            book=str(row["book"]),
            book_order=int(str(row["book_order"])),
            analysis_profile=str(row["analysis_profile"]),
            analysis_reading=str(row["analysis_reading"]),
            granularity=str(row["granularity"]),
            start_reference=str(row["start_reference"]),
            end_reference=str(row["end_reference"]),
            source_passage_digest=str(row["identity_payload_sha256"]),
            start_stream_position_in_corpus=int(str(row["start_stream_position_in_corpus"])),
            token_count=int(str(row["token_count"])),
            disputed_passage_flag=bool(row["disputed_passage_flag"]),
            reference_gap=bool(row["reference_gap"]),
            ketiv_structural_uncertainty=bool(row["ketiv_structural_uncertainty"]),
        )

    def add(self, row: dict[str, object]) -> None:
        token_id = str(row["token_id"])
        position = int(str(row["position_in_passage"]))
        source_word_id = str(row["source_word_id"]) if row["source_word_id"] is not None else None
        self.provenance_token_ids.append(token_id)
        self.membership_positions.append(position)
        if bool(row["is_zero_width"]):
            self.zero_width_token_ids.append(token_id)
            return
        if bool(row["is_punctuation"]):
            self.punctuation_token_ids.append(token_id)
            return
        if bool(row["is_elided"]):
            self.elided_token_ids.append(token_id)

        def occurrence(value: object) -> FeatureOccurrence | None:
            if value is None or str(value) == "":
                return None
            return FeatureOccurrence(str(value), position, token_id, source_word_id)

        values = {
            "lemma": occurrence(row["lemma"]),
            "root": occurrence(row["lexical_root"]),
            "surface": occurrence(row["normalized_form"]),
            "folded_surface": occurrence(row["folded_form"]),
            "part_of_speech": occurrence(row["part_of_speech"]),
            "morphology": occurrence(
                coarse_morphology(str(row["morphology_json"]))
                if row["morphology_json"] is not None
                else None
            ),
        }
        for family, item in values.items():
            if item is not None:
                getattr(self, family).append(item)
        for gloss_token in normalize_english_gloss(
            str(row["english_gloss"]) if row["english_gloss"] is not None else None
        ):
            self.english_gloss.append(
                FeatureOccurrence(gloss_token, position, token_id, source_word_id)
            )

    def freeze(self) -> PassageLexicalSequence:
        if len(self.provenance_token_ids) != self.token_count:
            raise LexicalSequenceError(
                f"passage {self.passage_id} membership count differs from token_count: "
                f"{len(self.provenance_token_ids)} != {self.token_count}"
            )
        if self.membership_positions != list(range(1, self.token_count + 1)):
            raise LexicalSequenceError(
                f"passage {self.passage_id} membership positions are not contiguous source order"
            )
        return PassageLexicalSequence(
            passage_id=self.passage_id,
            corpus=self.corpus,
            book=self.book,
            book_order=self.book_order,
            analysis_profile=self.analysis_profile,
            analysis_reading=self.analysis_reading,
            granularity=self.granularity,
            start_reference=self.start_reference,
            end_reference=self.end_reference,
            source_passage_digest=self.source_passage_digest,
            start_stream_position_in_corpus=self.start_stream_position_in_corpus,
            token_count=self.token_count,
            disputed_passage_flag=self.disputed_passage_flag,
            reference_gap=self.reference_gap,
            ketiv_structural_uncertainty=self.ketiv_structural_uncertainty,
            lemma=tuple(self.lemma),
            root=tuple(self.root),
            surface=tuple(self.surface),
            folded_surface=tuple(self.folded_surface),
            part_of_speech=tuple(self.part_of_speech),
            morphology=tuple(self.morphology),
            english_gloss=tuple(self.english_gloss),
            provenance_token_ids=tuple(self.provenance_token_ids),
            zero_width_token_ids=tuple(self.zero_width_token_ids),
            punctuation_token_ids=tuple(self.punctuation_token_ids),
            elided_token_ids=tuple(self.elided_token_ids),
        )


def _token_projection(corpus: str) -> str:
    common = (
        "token_id, source_word_id, normalized_form, lemma, part_of_speech, "
        "morphology_json, english_gloss, is_punctuation"
    )
    if corpus == "hebrew":
        projection = (
            f"{common}, lexical_root, normalized_form AS folded_form, "
            "coalesce(is_zero_width, false) AS is_zero_width, false AS is_elided"
        )
        return (
            f"SELECT {projection} FROM hebrew_tokens UNION ALL BY NAME "
            f"SELECT {projection} FROM hebrew_kq_ketiv_tokens"
        )
    if corpus == "greek":
        return (
            f"SELECT {common}, NULL::VARCHAR AS lexical_root, folded_form, "
            "false AS is_zero_width, coalesce(is_elided, false) AS is_elided "
            "FROM greek_tokens"
        )
    raise LexicalSequenceError(f"unsupported corpus: {corpus}")


def iter_passage_sequences(
    database_path: Path,
    *,
    corpus: str,
    analysis_profile: str,
    analysis_reading: str,
    granularity: str,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
    limit: int | None = None,
) -> Iterator[PassageLexicalSequence]:
    """Stream governed passages without reparsing reconstructed display text."""

    if limit is not None and limit < 1:
        raise LexicalSequenceError("limit must be positive when supplied")
    expected_readings = {"hebrew": {"qere", "ketiv"}, "greek": {"source"}}
    if corpus not in expected_readings:
        raise LexicalSequenceError(f"unsupported corpus: {corpus}")
    if analysis_reading not in expected_readings[corpus]:
        raise LexicalSequenceError(
            f"reading {analysis_reading!r} is not valid for corpus {corpus!r}"
        )
    if analysis_profile not in {"edition_complete", "critical_core"}:
        raise LexicalSequenceError(f"unsupported analysis profile: {analysis_profile}")
    if granularity not in {"clause", "sentence", "verse", "two_verse", "five_verse"}:
        raise LexicalSequenceError(f"unsupported granularity: {granularity}")
    if not database_path.is_file():
        raise LexicalSequenceError(f"DuckDB database does not exist: {database_path}")
    token_projection = _token_projection(corpus)
    limit_clause = f"LIMIT {limit:d}" if limit is not None else ""
    query = f"""
        WITH selected_passages AS (
            SELECT * FROM passages
            WHERE corpus = ? AND analysis_profile = ? AND analysis_reading = ?
              AND granularity = ?
            ORDER BY passage_id
            {limit_clause}
        ), tokens AS ({token_projection})
        SELECT p.passage_id, p.corpus, p.book, p.book_order, p.analysis_profile,
               p.analysis_reading, p.granularity, p.start_reference, p.end_reference,
               p.identity_payload_sha256, p.start_stream_position_in_corpus,
               p.token_count, p.disputed_passage_flag,
               p.reference_gap, p.ketiv_structural_uncertainty,
               m.token_id, t.token_id AS resolved_token_id, m.position_in_passage,
               t.source_word_id,
               t.normalized_form, t.folded_form, t.lemma, t.lexical_root,
               t.part_of_speech, t.morphology_json, t.english_gloss,
               t.is_punctuation, t.is_zero_width, t.is_elided
        FROM selected_passages p
        JOIN passage_membership m USING (passage_id)
        LEFT JOIN tokens t USING (token_id)
        ORDER BY p.passage_id, m.position_in_passage
    """
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            reader = connection.execute(
                query,
                [corpus, analysis_profile, analysis_reading, granularity],
            ).to_arrow_reader(50_000)
            builder: _PassageBuilder | None = None
            for batch in reader:
                for row in batch.to_pylist():
                    if row["resolved_token_id"] is None:
                        raise LexicalSequenceError(
                            "passage token does not resolve to governed source data: "
                            f"{row['token_id']}"
                        )
                    if builder is None or builder.passage_id != str(row["passage_id"]):
                        if builder is not None:
                            yield builder.freeze()
                        builder = _PassageBuilder.from_row(row)
                    builder.add(row)
            if builder is not None:
                yield builder.freeze()
    except (duckdb.Error, OSError, LexicalResourceError) as exc:
        raise LexicalSequenceError(f"could not derive lexical sequences: {exc}") from exc


def sequence_digest(values: Iterable[str]) -> str:
    """Hash an ordered feature sequence with unambiguous canonical separators."""

    digest = hashlib.sha256()
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()
