"""Governed Milestone 5 passage projection for ``final-discovery-v1``.

The primary projection contains edition-complete Hebrew Qere and Greek source
verse passages.  Critical-core and Hebrew Ketiv rows are opt-in sensitivity
records with their own existing passage identities; this module never merges
them into, or mutates, a primary record.

The pure row adapter is deliberately independent of filesystem layout so small
fixtures can exercise every scientific invariant.  The Parquet adapter adds
strict physical-hash authentication and reads one book partition at a time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import cast
from uuid import uuid4

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from echoes.final_discovery.models import PassageRecord
from echoes.manifest import sha256_file
from echoes.segment.models import PASSAGE_COLUMNS, PassageRow
from echoes.settings import BenchmarkConfig, load_config

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_PASSAGE_TABLE = "passages"
_TABLE_HASH_FILE = "table-hashes.json"

_HEBREW_TOKEN_COLUMNS = (
    "token_id",
    "corpus",
    "book",
    "morphology_json",
    "english_gloss",
    "clause_id",
    "syntactic_function",
    "syntactic_head_source_id",
)
_GREEK_TOKEN_COLUMNS = (
    "token_id",
    "corpus",
    "book",
    "morphology_json",
    "english_gloss",
    "frame_json",
)


class PassageProjectionError(ValueError):
    """Raised when a passage projection cannot preserve its governed meaning."""


@dataclass(frozen=True, slots=True)
class PassageProjectionScope:
    """Primary rows plus explicitly requested, identity-distinct sensitivities."""

    include_greek_critical_core: bool = False
    include_hebrew_ketiv: bool = False

    def includes(self, row: PassageRow) -> bool:
        """Return whether a governed verse row belongs to this projection."""

        if row.granularity != "verse":
            return False
        if row.corpus == "hebrew":
            return row.analysis_profile == "edition_complete" and (
                row.analysis_reading == "qere"
                or (self.include_hebrew_ketiv and row.analysis_reading == "ketiv")
            )
        return row.analysis_reading == "source" and (
            row.analysis_profile == "edition_complete"
            or (self.include_greek_critical_core and row.analysis_profile == "critical_core")
        )


PRIMARY_PASSAGE_SCOPE = PassageProjectionScope()


@dataclass(frozen=True, slots=True)
class PassageParquetSources:
    """Locations of authenticated M5 passages and canonical token tables."""

    passage_root: Path
    hebrew_tokens_path: Path
    greek_tokens_path: Path
    hebrew_ketiv_tokens_path: Path | None = None
    benchmark_config_path: Path = Path("config/benchmark.yaml")
    passage_hash_manifest_path: Path | None = None
    hebrew_hash_manifest_path: Path | None = None
    greek_hash_manifest_path: Path | None = None
    hebrew_ketiv_hash_manifest_path: Path | None = None

    @property
    def resolved_passage_hash_manifest_path(self) -> Path:
        return self.passage_hash_manifest_path or self.passage_root / _TABLE_HASH_FILE

    @property
    def resolved_hebrew_hash_manifest_path(self) -> Path:
        return self.hebrew_hash_manifest_path or self.hebrew_tokens_path.parent / _TABLE_HASH_FILE

    @property
    def resolved_greek_hash_manifest_path(self) -> Path:
        return self.greek_hash_manifest_path or self.greek_tokens_path.parent / _TABLE_HASH_FILE

    @property
    def resolved_hebrew_ketiv_hash_manifest_path(self) -> Path:
        if self.hebrew_ketiv_hash_manifest_path is not None:
            return self.hebrew_ketiv_hash_manifest_path
        if self.hebrew_ketiv_tokens_path is None:
            raise PassageProjectionError("Ketiv projection requires its governed token table")
        return self.hebrew_ketiv_tokens_path.parent / _TABLE_HASH_FILE


@dataclass(frozen=True, slots=True)
class PassageJsonlReceipt:
    """Identity of one atomically persisted PassageRecord stream."""

    path: Path
    row_count: int
    sha256: str

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValueError("JSONL row count cannot be negative")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("JSONL receipt requires a lowercase SHA-256")


class PassageProjectionAuthenticationReceipt(BaseModel):
    """Reproducible proof that prepared JSONL exactly equals governed extraction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    projection_algorithm: str = "m5_authenticated_full_record_equality_v1"
    extraction_code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prepared_jsonl_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    logical_records_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    row_count: int = Field(ge=1)
    passage_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    hebrew_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    greek_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    hebrew_ketiv_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    include_greek_critical_core: bool
    include_hebrew_ketiv: bool


def load_book_genres(path: Path = Path("config/benchmark.yaml")) -> dict[str, str]:
    """Load the strict, exactly-66-book broad-genre registry."""

    loaded = load_config(path)
    if not isinstance(loaded, BenchmarkConfig):
        raise PassageProjectionError(f"genre configuration is not BenchmarkConfig: {path}")
    return dict(loaded.book_genres)


def _require_sha256(value: str, *, label: str) -> str:
    if not _SHA256.fullmatch(value):
        raise PassageProjectionError(f"{label} must be a lowercase SHA-256")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _parse_json_object(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PassageProjectionError(f"{label} must be JSON text or null")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PassageProjectionError(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise PassageProjectionError(f"{label} must encode a JSON object")
    return _canonical_json(parsed)


def _optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PassageProjectionError(f"{label} must be text or null")
    return value if value else None


def _required_string(row: Mapping[str, object], field: str, *, row_label: str) -> str:
    if field not in row:
        raise PassageProjectionError(f"{row_label} is missing required field {field}")
    value = row[field]
    if not isinstance(value, str) or not value:
        raise PassageProjectionError(f"{row_label}.{field} must be nonempty text")
    return value


def _token_index(
    rows: Iterable[Mapping[str, object]],
    *,
    expected_corpus: str,
) -> dict[str, Mapping[str, object]]:
    index: dict[str, Mapping[str, object]] = {}
    for row_number, raw_row in enumerate(rows, start=1):
        row = dict(raw_row)
        row_label = f"{expected_corpus} token row {row_number}"
        token_id = _required_string(row, "token_id", row_label=row_label)
        corpus = _required_string(row, "corpus", row_label=row_label)
        _required_string(row, "book", row_label=row_label)
        if corpus != expected_corpus:
            raise PassageProjectionError(
                f"{row_label} has corpus {corpus!r}, expected {expected_corpus!r}"
            )
        if token_id in index:
            raise PassageProjectionError(
                f"duplicate canonical {expected_corpus} token_id: {token_id}"
            )
        index[token_id] = row
    return index


def _passage_row(value: PassageRow | Mapping[str, object], row_number: int) -> PassageRow:
    if isinstance(value, PassageRow):
        return value
    try:
        return PassageRow.model_validate(value)
    except ValidationError as exc:
        raise PassageProjectionError(
            f"passage row {row_number} violates the governed M5 schema: {exc}"
        ) from exc


def _string_sequence(row: PassageRow, field_name: str) -> tuple[str | None, ...]:
    raw = cast(str, getattr(row, field_name))
    values = json.loads(raw)
    return tuple(cast(list[str | None], values))


def _hebrew_frame(token: Mapping[str, object], *, token_id: str) -> str | None:
    """Derive only categorical, transparent Hebrew clause/syntax facts.

    Raw clause and head identifiers are deliberately not embedded in the frame:
    they are source-local identities, not comparable grammatical categories.
    Their presence may be recorded without pretending that two identifier
    strings constitute a shared narrative frame.
    """

    clause_id = _optional_string(token.get("clause_id"), label=f"{token_id}.clause_id")
    syntactic_function = _optional_string(
        token.get("syntactic_function"),
        label=f"{token_id}.syntactic_function",
    )
    head_id = _optional_string(
        token.get("syntactic_head_source_id"),
        label=f"{token_id}.syntactic_head_source_id",
    )
    if clause_id is None and syntactic_function is None and head_id is None:
        return None
    return _canonical_json(
        {
            "has_clause_assignment": clause_id is not None,
            "has_syntactic_head": head_id is not None,
            "syntactic_function": syntactic_function,
        }
    )


def _projection_source_digest(
    *,
    passage_source_sha256: str,
    token_source_sha256: str,
    genre_source_sha256: str,
    passage_identity_sha256: str,
) -> str:
    payload = {
        "genre_source_sha256": _require_sha256(
            genre_source_sha256,
            label="genre source digest",
        ),
        "passage_identity_sha256": _require_sha256(
            passage_identity_sha256,
            label="passage identity digest",
        ),
        "passage_source_sha256": _require_sha256(
            passage_source_sha256,
            label="passage source digest",
        ),
        "token_source_sha256": _require_sha256(
            token_source_sha256,
            label="token source digest",
        ),
    }
    return hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()


def project_passage_rows(
    passages: Iterable[PassageRow | Mapping[str, object]],
    *,
    hebrew_tokens: Iterable[Mapping[str, object]],
    greek_tokens: Iterable[Mapping[str, object]],
    book_genres: Mapping[str, str],
    passage_source_sha256: str,
    hebrew_token_source_sha256: str,
    greek_token_source_sha256: str,
    hebrew_ketiv_token_source_sha256: str | None = None,
    genre_source_sha256: str,
    scope: PassageProjectionScope = PRIMARY_PASSAGE_SCOPE,
) -> Iterator[PassageRecord]:
    """Project governed M5 rows using fixture-friendly token iterables.

    Passage annotations remain sourced from :class:`PassageRow`; canonical
    token rows contribute morphology, Greek frames, transparent Hebrew syntax,
    and supplemental English glosses.  Every lookup is exact and one-to-one.
    """

    _require_sha256(passage_source_sha256, label="passage source digest")
    _require_sha256(hebrew_token_source_sha256, label="Hebrew token source digest")
    _require_sha256(greek_token_source_sha256, label="Greek token source digest")
    if hebrew_ketiv_token_source_sha256 is not None:
        _require_sha256(
            hebrew_ketiv_token_source_sha256,
            label="Hebrew Ketiv token source digest",
        )
    _require_sha256(genre_source_sha256, label="genre source digest")
    hebrew_index = _token_index(hebrew_tokens, expected_corpus="hebrew")
    greek_index = _token_index(greek_tokens, expected_corpus="greek")
    seen_passage_ids: set[str] = set()
    seen_scope_keys: dict[tuple[str, str, str, str], str] = {}

    for row_number, raw_passage in enumerate(passages, start=1):
        passage = _passage_row(raw_passage, row_number)
        if passage.passage_id in seen_passage_ids:
            raise PassageProjectionError(f"duplicate M5 passage_id: {passage.passage_id}")
        seen_passage_ids.add(passage.passage_id)
        if not scope.includes(passage):
            continue
        scope_key = (
            passage.corpus,
            passage.analysis_profile,
            passage.analysis_reading,
            passage.start_reference,
        )
        prior_passage_id = seen_scope_keys.get(scope_key)
        if prior_passage_id is not None:
            raise PassageProjectionError(
                "duplicate M5 verse scope key with distinct identities: "
                f"key={scope_key}, passage_ids={[prior_passage_id, passage.passage_id]}"
            )
        seen_scope_keys[scope_key] = passage.passage_id
        if passage.start_reference != passage.end_reference:
            raise PassageProjectionError(
                f"verse passage spans multiple references: {passage.passage_id}"
            )
        genre = book_genres.get(passage.book)
        if not isinstance(genre, str) or not genre:
            raise PassageProjectionError(f"book has no governed broad genre: {passage.book}")

        token_ids = cast(tuple[str, ...], _string_sequence(passage, "token_ids_json"))
        if len(token_ids) != len(set(token_ids)):
            raise PassageProjectionError(
                f"passage contains duplicate token IDs: {passage.passage_id}"
            )
        token_index = hebrew_index if passage.corpus == "hebrew" else greek_index
        if passage.corpus == "greek":
            token_source_digest = greek_token_source_sha256
        elif passage.analysis_reading == "ketiv":
            token_source_digest = hebrew_ketiv_token_source_sha256 or hebrew_token_source_sha256
        else:
            token_source_digest = hebrew_token_source_sha256
        tokens: list[Mapping[str, object]] = []
        for position, token_id in enumerate(token_ids, start=1):
            token = token_index.get(token_id)
            if token is None:
                raise PassageProjectionError(
                    f"missing canonical {passage.corpus} token_id {token_id} "
                    f"for passage {passage.passage_id} at position {position}"
                )
            token_book = _required_string(
                token,
                "book",
                row_label=f"canonical token {token_id}",
            )
            if token_book != passage.book:
                raise PassageProjectionError(
                    f"canonical token {token_id} belongs to {token_book}, "
                    f"not passage book {passage.book}"
                )
            tokens.append(token)

        morphology = tuple(
            _parse_json_object(
                token.get("morphology_json"),
                label=f"{token_id}.morphology_json",
            )
            for token_id, token in zip(token_ids, tokens, strict=True)
        )
        if passage.corpus == "greek":
            frames = tuple(
                _parse_json_object(
                    token.get("frame_json"),
                    label=f"{token_id}.frame_json",
                )
                for token_id, token in zip(token_ids, tokens, strict=True)
            )
        else:
            frames = tuple(
                _hebrew_frame(token, token_id=token_id)
                for token_id, token in zip(token_ids, tokens, strict=True)
            )
        gloss_parts = tuple(
            gloss.strip()
            for token_id, token in zip(token_ids, tokens, strict=True)
            if (
                gloss := _optional_string(
                    token.get("english_gloss"),
                    label=f"{token_id}.english_gloss",
                )
            )
            is not None
            and gloss.strip()
        )

        yield PassageRecord(
            passage_id=passage.passage_id,
            reference=passage.start_reference,
            corpus=passage.corpus,
            book=passage.book,
            genre=genre,
            analysis_profile=passage.analysis_profile,
            analysis_reading=passage.analysis_reading,
            granularity="verse",
            token_count=passage.token_count,
            token_ids=token_ids,
            original_text=passage.surface_text,
            normalized_text=passage.normalized_text,
            lemma_sequence=_string_sequence(passage, "lemma_sequence_json"),
            root_sequence=_string_sequence(passage, "root_sequence_json"),
            pos_sequence=_string_sequence(passage, "part_of_speech_sequence_json"),
            morphology_sequence=morphology,
            semantic_domains=_string_sequence(passage, "semantic_domain_sequence_json"),
            entities=_string_sequence(passage, "entity_ids_json"),
            participants=_string_sequence(passage, "participant_ids_json"),
            frames=frames,
            english_gloss=" ".join(gloss_parts) if gloss_parts else None,
            disputed_passage=passage.disputed_passage_flag,
            reference_gap=passage.reference_gap,
            ketiv_uncertainty=(
                passage.analysis_reading == "ketiv" or passage.ketiv_structural_uncertainty
            ),
            formulaic_language=False,
            source_digest=_projection_source_digest(
                passage_source_sha256=passage_source_sha256,
                token_source_sha256=token_source_digest,
                genre_source_sha256=genre_source_sha256,
                passage_identity_sha256=passage.identity_payload_sha256,
            ),
        )


def _read_parquet_hashes(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        raw_hashes = document["parquet_sha256"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PassageProjectionError(f"invalid Parquet hash manifest: {path}") from exc
    if not isinstance(raw_hashes, dict):
        raise PassageProjectionError(f"Parquet hash inventory must be a mapping: {path}")
    hashes: dict[str, str] = {}
    for raw_name, raw_digest in raw_hashes.items():
        if not isinstance(raw_name, str) or not isinstance(raw_digest, str):
            raise PassageProjectionError(f"invalid Parquet hash entry in {path}")
        normalized_name = Path(raw_name).as_posix()
        hashes[normalized_name] = _require_sha256(
            raw_digest,
            label=f"manifest digest for {normalized_name}",
        )
    return hashes


def _authenticate_parquet(path: Path, hashes: Mapping[str, str], *, key: str) -> str:
    normalized_key = Path(key).as_posix()
    expected = hashes.get(normalized_key)
    if expected is None:
        raise PassageProjectionError(
            f"Parquet hash manifest does not authenticate {normalized_key}: {path}"
        )
    if not path.is_file():
        raise PassageProjectionError(f"authenticated Parquet file does not exist: {path}")
    observed = sha256_file(path)
    if observed != expected:
        raise PassageProjectionError(
            f"Parquet SHA-256 mismatch for {normalized_key}: "
            f"expected={expected}, observed={observed}"
        )
    return observed


def _scope_patterns(scope: PassageProjectionScope) -> tuple[tuple[str, str, str], ...]:
    patterns: list[tuple[str, str, str]] = [
        ("hebrew", "edition_complete", "qere"),
        ("greek", "edition_complete", "source"),
    ]
    if scope.include_hebrew_ketiv:
        patterns.append(("hebrew", "edition_complete", "ketiv"))
    if scope.include_greek_critical_core:
        patterns.append(("greek", "critical_core", "source"))
    return tuple(patterns)


def _selected_passage_paths(
    passage_root: Path,
    scope: PassageProjectionScope,
) -> tuple[Path, ...]:
    root = passage_root / _PASSAGE_TABLE
    selected: set[Path] = set()
    for corpus, profile, reading in _scope_patterns(scope):
        pattern = (
            f"corpus={corpus}/analysis_profile={profile}/analysis_reading={reading}/"
            "granularity=verse/book=*/*.parquet"
        )
        selected.update(path for path in root.glob(pattern) if path.is_file())
    paths = tuple(sorted(selected, key=lambda path: path.as_posix()))
    if not paths:
        raise PassageProjectionError(
            f"no governed verse passage Parquet leaves match the requested scope: {root}"
        )
    return paths


def _read_book_tokens(path: Path, *, corpus: str, book: str) -> list[dict[str, object]]:
    columns = _HEBREW_TOKEN_COLUMNS if corpus == "hebrew" else _GREEK_TOKEN_COLUMNS
    try:
        frame = (
            pl.scan_parquet(path)
            .filter(pl.col("book") == book)
            .select(columns)
            .collect(engine="streaming")
        )
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise PassageProjectionError(
            f"could not read canonical {corpus} tokens for {book}: {path}"
        ) from exc
    return cast(list[dict[str, object]], list(frame.iter_rows(named=True)))


def _assert_unique_token_ids(path: Path, *, corpus: str) -> None:
    try:
        summary = (
            pl.scan_parquet(path)
            .select(
                pl.len().alias("row_count"),
                pl.col("token_id").drop_nulls().n_unique().alias("unique_token_count"),
                pl.col("token_id").null_count().alias("null_token_count"),
            )
            .collect(engine="streaming")
        )
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise PassageProjectionError(
            f"could not audit canonical {corpus} token IDs: {path}"
        ) from exc
    row_count = int(summary.item(0, "row_count"))
    unique_count = int(summary.item(0, "unique_token_count"))
    null_count = int(summary.item(0, "null_token_count"))
    if null_count:
        raise PassageProjectionError(
            f"canonical {corpus} token table contains {null_count} null token IDs"
        )
    if row_count != unique_count:
        raise PassageProjectionError(
            f"canonical {corpus} token table contains duplicate token IDs: "
            f"rows={row_count}, unique={unique_count}"
        )


def iter_passage_records_from_parquet(
    sources: PassageParquetSources,
    *,
    scope: PassageProjectionScope = PRIMARY_PASSAGE_SCOPE,
) -> Iterator[PassageRecord]:
    """Authenticate and project selected passage leaves one book at a time."""

    book_genres = load_book_genres(sources.benchmark_config_path)
    genre_source_sha256 = sha256_file(sources.benchmark_config_path)
    passage_hashes = _read_parquet_hashes(sources.resolved_passage_hash_manifest_path)
    hebrew_hashes = _read_parquet_hashes(sources.resolved_hebrew_hash_manifest_path)
    greek_hashes = _read_parquet_hashes(sources.resolved_greek_hash_manifest_path)
    hebrew_token_sha256 = _authenticate_parquet(
        sources.hebrew_tokens_path,
        hebrew_hashes,
        key=sources.hebrew_tokens_path.name,
    )
    greek_token_sha256 = _authenticate_parquet(
        sources.greek_tokens_path,
        greek_hashes,
        key=sources.greek_tokens_path.name,
    )
    ketiv_token_sha256: str | None = None
    if scope.include_hebrew_ketiv:
        if sources.hebrew_ketiv_tokens_path is None:
            raise PassageProjectionError("Ketiv projection requires its governed token table")
        ketiv_hashes = _read_parquet_hashes(sources.resolved_hebrew_ketiv_hash_manifest_path)
        ketiv_token_sha256 = _authenticate_parquet(
            sources.hebrew_ketiv_tokens_path,
            ketiv_hashes,
            key=sources.hebrew_ketiv_tokens_path.name,
        )
    _assert_unique_token_ids(sources.hebrew_tokens_path, corpus="hebrew")
    _assert_unique_token_ids(sources.greek_tokens_path, corpus="greek")
    if sources.hebrew_ketiv_tokens_path is not None and scope.include_hebrew_ketiv:
        _assert_unique_token_ids(sources.hebrew_ketiv_tokens_path, corpus="hebrew Ketiv")

    seen_passage_ids: set[str] = set()
    seen_scope_keys: dict[tuple[str, str, str, str], str] = {}
    for passage_path in _selected_passage_paths(sources.passage_root, scope):
        relative_path = passage_path.relative_to(sources.passage_root).as_posix()
        passage_sha256 = _authenticate_parquet(
            passage_path,
            passage_hashes,
            key=relative_path,
        )
        try:
            passage_frame = pl.read_parquet(passage_path).select(PASSAGE_COLUMNS)
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise PassageProjectionError(f"could not read M5 passage leaf: {passage_path}") from exc
        if passage_frame.is_empty():
            raise PassageProjectionError(f"selected M5 passage leaf is empty: {passage_path}")
        corpora = passage_frame.get_column("corpus").unique().to_list()
        books = passage_frame.get_column("book").unique().to_list()
        if len(corpora) != 1 or corpora[0] not in {"hebrew", "greek"}:
            raise PassageProjectionError(
                f"passage leaf must contain one supported corpus: {passage_path}"
            )
        if len(books) != 1 or not isinstance(books[0], str):
            raise PassageProjectionError(f"passage leaf must contain one book: {passage_path}")
        corpus = cast(str, corpora[0])
        book = books[0]
        token_rows = _read_book_tokens(
            sources.hebrew_tokens_path if corpus == "hebrew" else sources.greek_tokens_path,
            corpus=corpus,
            book=book,
        )
        if corpus == "hebrew" and scope.include_hebrew_ketiv:
            assert sources.hebrew_ketiv_tokens_path is not None
            token_rows.extend(
                _read_book_tokens(
                    sources.hebrew_ketiv_tokens_path,
                    corpus="hebrew",
                    book=book,
                )
            )
        rows = cast(list[dict[str, object]], list(passage_frame.iter_rows(named=True)))
        projected = project_passage_rows(
            rows,
            hebrew_tokens=token_rows if corpus == "hebrew" else (),
            greek_tokens=token_rows if corpus == "greek" else (),
            book_genres=book_genres,
            passage_source_sha256=passage_sha256,
            hebrew_token_source_sha256=hebrew_token_sha256,
            greek_token_source_sha256=greek_token_sha256,
            hebrew_ketiv_token_source_sha256=ketiv_token_sha256,
            genre_source_sha256=genre_source_sha256,
            scope=scope,
        )
        for record in projected:
            if record.passage_id in seen_passage_ids:
                raise PassageProjectionError(
                    f"duplicate M5 passage_id across Parquet leaves: {record.passage_id}"
                )
            scope_key = (
                record.corpus,
                record.analysis_profile,
                record.analysis_reading,
                record.reference,
            )
            prior_passage_id = seen_scope_keys.get(scope_key)
            if prior_passage_id is not None:
                raise PassageProjectionError(
                    "duplicate M5 verse scope key across Parquet leaves: "
                    f"key={scope_key}, passage_ids={[prior_passage_id, record.passage_id]}"
                )
            seen_passage_ids.add(record.passage_id)
            seen_scope_keys[scope_key] = record.passage_id
            yield record


def write_passage_records_jsonl(
    records: Iterable[PassageRecord],
    path: Path,
    *,
    force: bool = False,
) -> PassageJsonlReceipt:
    """Atomically persist a deterministic PassageRecord JSONL stream."""

    if path.exists() and not force:
        raise PassageProjectionError(f"refusing to overwrite passage JSONL: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f".{path.name}.writing-{uuid4().hex}"
    seen: set[str] = set()
    row_count = 0
    try:
        with staging.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                if record.passage_id in seen:
                    raise PassageProjectionError(
                        f"duplicate PassageRecord passage_id during JSONL write: "
                        f"{record.passage_id}"
                    )
                seen.add(record.passage_id)
                handle.write(
                    json.dumps(
                        record.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                row_count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, path)
    except Exception:
        if staging.exists():
            staging.unlink()
        raise
    return PassageJsonlReceipt(path=path, row_count=row_count, sha256=sha256_file(path))


def read_passage_records_jsonl(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> Iterator[PassageRecord]:
    """Stream strict PassageRecords and reject malformed or duplicate rows."""

    if expected_sha256 is not None:
        expected = _require_sha256(expected_sha256, label="expected passage JSONL digest")
        observed = sha256_file(path)
        if observed != expected:
            raise PassageProjectionError(
                f"passage JSONL SHA-256 mismatch: expected={expected}, observed={observed}"
            )
    seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise PassageProjectionError(
                        f"blank line in passage JSONL at line {line_number}: {path}"
                    )
                try:
                    record = PassageRecord.model_validate_json(line)
                except ValidationError as exc:
                    raise PassageProjectionError(
                        f"invalid PassageRecord at JSONL line {line_number}: {path}: {exc}"
                    ) from exc
                if record.passage_id in seen:
                    raise PassageProjectionError(
                        f"duplicate PassageRecord passage_id at JSONL line {line_number}: "
                        f"{record.passage_id}"
                    )
                seen.add(record.passage_id)
                yield record
    except (OSError, UnicodeError) as exc:
        raise PassageProjectionError(f"could not read passage JSONL {path}: {exc}") from exc


def authenticate_prepared_passage_projection(
    prepared_path: Path,
    sources: PassageParquetSources,
    *,
    scope: PassageProjectionScope,
    extraction_code_sha256: str,
    expected_passage_manifest_sha256: str,
    expected_hebrew_manifest_sha256: str,
    expected_greek_manifest_sha256: str,
    expected_hebrew_ketiv_manifest_sha256: str | None = None,
) -> PassageProjectionAuthenticationReceipt:
    """Recompute the governed projection and compare every complete typed row.

    The prepared JSONL is only a cache.  Its operator-provided filename or hash
    is never treated as source authentication: every record must equal the
    deterministic projection from the manifest-authenticated M5/token Parquet.
    """

    _require_sha256(extraction_code_sha256, label="extraction code digest")
    manifests = (
        (
            sources.resolved_passage_hash_manifest_path,
            _require_sha256(
                expected_passage_manifest_sha256,
                label="expected passage manifest digest",
            ),
            "passage",
        ),
        (
            sources.resolved_hebrew_hash_manifest_path,
            _require_sha256(
                expected_hebrew_manifest_sha256,
                label="expected Hebrew manifest digest",
            ),
            "Hebrew",
        ),
        (
            sources.resolved_greek_hash_manifest_path,
            _require_sha256(
                expected_greek_manifest_sha256,
                label="expected Greek manifest digest",
            ),
            "Greek",
        ),
    )
    for path, expected, label in manifests:
        observed = sha256_file(path)
        if observed != expected:
            raise PassageProjectionError(
                f"{label} hash manifest differs from preregistration: "
                f"expected={expected}, observed={observed}"
            )
    ketiv_manifest_sha256: str | None = None
    if scope.include_hebrew_ketiv:
        if expected_hebrew_ketiv_manifest_sha256 is None:
            raise PassageProjectionError(
                "Ketiv projection requires a preregistered OSHB manifest digest"
            )
        expected_ketiv = _require_sha256(
            expected_hebrew_ketiv_manifest_sha256,
            label="expected Hebrew Ketiv manifest digest",
        )
        ketiv_path = sources.resolved_hebrew_ketiv_hash_manifest_path
        ketiv_manifest_sha256 = sha256_file(ketiv_path)
        if ketiv_manifest_sha256 != expected_ketiv:
            raise PassageProjectionError(
                "Hebrew Ketiv hash manifest differs from preregistration: "
                f"expected={expected_ketiv}, observed={ketiv_manifest_sha256}"
            )

    logical_digest = hashlib.sha256()
    row_count = 0
    missing = object()
    supplied = read_passage_records_jsonl(prepared_path)
    expected_rows = iter_passage_records_from_parquet(sources, scope=scope)
    for row_number, pair in enumerate(
        zip_longest(supplied, expected_rows, fillvalue=missing),
        start=1,
    ):
        observed_row, expected_row = pair
        if observed_row is missing or expected_row is missing:
            raise PassageProjectionError(
                f"prepared projection row count differs at row {row_number}"
            )
        assert isinstance(observed_row, PassageRecord)
        assert isinstance(expected_row, PassageRecord)
        if observed_row != expected_row:
            raise PassageProjectionError(
                "prepared projection differs from governed M5 extraction at "
                f"row {row_number}: observed={observed_row.passage_id}, "
                f"expected={expected_row.passage_id}"
            )
        logical_digest.update(_canonical_json(observed_row.model_dump(mode="json")).encode("ascii"))
        logical_digest.update(b"\n")
        row_count += 1
    if row_count < 1:
        raise PassageProjectionError("prepared passage projection is empty")
    return PassageProjectionAuthenticationReceipt(
        extraction_code_sha256=extraction_code_sha256,
        prepared_jsonl_sha256=sha256_file(prepared_path),
        logical_records_sha256=logical_digest.hexdigest(),
        row_count=row_count,
        passage_manifest_sha256=expected_passage_manifest_sha256,
        hebrew_manifest_sha256=expected_hebrew_manifest_sha256,
        greek_manifest_sha256=expected_greek_manifest_sha256,
        hebrew_ketiv_manifest_sha256=ketiv_manifest_sha256,
        include_greek_critical_core=scope.include_greek_critical_core,
        include_hebrew_ketiv=scope.include_hebrew_ketiv,
    )
