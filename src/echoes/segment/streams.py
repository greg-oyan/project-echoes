"""Verified analytical token streams for passage segmentation.

The primary corpus tables and OSHB supplement are immutable inputs.  This
module verifies their pinned whole-corpus fingerprints, derives Qere/Ketiv and
Greek source streams, and applies analysis-profile membership without ever
rewriting a source row.  Selected-stream order is explicit because OSHB's
``position_in_corpus`` belongs to a different source domain from MACULA's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl

from echoes.corpus.kq_supplement import derive_supplemented_analysis_stream
from echoes.corpus.validation import (
    corpus_analytical_digest,
    corpus_content_digest,
    corpus_identity_digest,
)
from echoes.manifests.sources import SourceCatalog, SourceManifest, load_source_catalog
from echoes.settings import SegmentationConfig

HEBREW_TOKEN_COUNT = 475_911
GREEK_TOKEN_COUNT = 137_779
HEBREW_IDENTITY_DIGEST = "91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6"
HEBREW_CONTENT_DIGEST = "7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82"
HEBREW_ANALYTICAL_DIGEST = "9464a106684b63ff57bcd9dd754bcd0c875d7ea8157fc7bfe643d7eb66dab173"
GREEK_IDENTITY_DIGEST = "9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2"
GREEK_CONTENT_DIGEST = "a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683"
GREEK_ANALYTICAL_DIGEST = "31404eb29a1f71855f3670f6f895e3fadc3ab0b39e2685c3cf672620df08a2a1"
OSHB_LOGICAL_DIGESTS = {
    "ketiv_tokens": "7bb67cebc45c06943a7f1fc2e241202f100a19cf7ad6dd6b0933d999ac01d238",
    "locus_registry": "ae6e70a8d1dd75cccfef85bb5535051134104f03d57490976d4e30f93c60f022",
    "structural_alignments": "ac0c9ebffe971ef9178ef47edbf868d9f904a189133dccf907f815651b867df9",
}

CorpusName = Literal["hebrew", "greek"]
AnalysisProfileName = Literal["edition_complete", "critical_core"]
AnalysisReadingName = Literal["qere", "ketiv", "source"]

STREAM_TOKEN_SCHEMA = pl.Schema(
    {
        "token_id": pl.String,
        "corpus": pl.String,
        "analysis_profile": pl.String,
        "analysis_reading": pl.String,
        "language": pl.String,
        "source_id": pl.String,
        "source_version": pl.String,
        "source_edition_reference": pl.String,
        "source_word_id": pl.String,
        "book": pl.String,
        "book_order": pl.Int16,
        "chapter": pl.Int16,
        "verse": pl.Int16,
        "canonical_reference": pl.String,
        "source_position_in_corpus": pl.Int64,
        "stream_position_in_corpus": pl.Int64,
        "verse_ordinal_in_book": pl.Int32,
        "position_in_word": pl.Int16,
        "surface_form": pl.String,
        "normalized_form": pl.String,
        "unpointed_form": pl.String,
        "folded_form": pl.String,
        "leading_punctuation": pl.String,
        "trailing_punctuation": pl.String,
        "is_zero_width": pl.Boolean,
        "is_punctuation": pl.Boolean,
        "is_elided": pl.Boolean,
        "lemma": pl.String,
        "lexical_root": pl.String,
        "part_of_speech": pl.String,
        "semantic_domain": pl.String,
        "entity_id": pl.String,
        "participant_id": pl.String,
        "source_extras_json": pl.String,
        "variant_type": pl.String,
        "variant_group_id": pl.String,
        "analysis_sentence_id": pl.String,
        "analysis_clause_id": pl.String,
        "analysis_phrase_id": pl.String,
        "structural_resolution_status": pl.String,
        "sentence_resolution_status": pl.String,
        "clause_resolution_status": pl.String,
        "phrase_resolution_status": pl.String,
        "locus_id": pl.String,
        "default_membership_basis": pl.String,
    }
)
STREAM_TOKEN_COLUMNS: tuple[str, ...] = tuple(STREAM_TOKEN_SCHEMA)


class SegmentationInputError(RuntimeError):
    """Raised before generation when an immutable input or profile is unsafe."""


@dataclass(frozen=True, slots=True)
class InputDigestSet:
    """Pinned input fingerprints recorded in segmentation metadata."""

    hebrew_identity: str
    hebrew_content: str
    hebrew_analytical: str
    greek_identity: str
    greek_content: str
    greek_analytical: str
    oshb_logical: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-ready representation."""

        return {
            "hebrew_identity": self.hebrew_identity,
            "hebrew_content": self.hebrew_content,
            "hebrew_analytical": self.hebrew_analytical,
            "greek_identity": self.greek_identity,
            "greek_content": self.greek_content,
            "greek_analytical": self.greek_analytical,
            "oshb_logical": dict(sorted(self.oshb_logical.items())),
        }


@dataclass(frozen=True, slots=True)
class SegmentationInputs:
    """Verified immutable frames and their governed source versions."""

    hebrew_tokens: pl.DataFrame
    greek_tokens: pl.DataFrame
    ketiv_tokens: pl.DataFrame
    locus_registry: pl.DataFrame
    structural_alignments: pl.DataFrame
    source_versions: dict[str, str]
    digests: InputDigestSet


def _active_source(catalog: SourceCatalog, source_id: str) -> SourceManifest:
    source = catalog.find(source_id)
    if source is None or source.acquisition is None or source.version_or_commit is None:
        raise SegmentationInputError(
            f"source is not an acquired, pinned segmentation input: {source_id}"
        )
    return source


def _processed_source_directory(source: SourceManifest, data_root: Path) -> Path:
    if source.acquisition is None:
        raise SegmentationInputError(f"source has no acquisition version label: {source.source_id}")
    return data_root / "processed" / source.source_id / source.acquisition.version_label


def _read_required_parquet(path: Path) -> pl.DataFrame:
    if not path.is_file():
        raise SegmentationInputError(f"required segmentation input does not exist: {path}")
    try:
        return pl.read_parquet(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise SegmentationInputError(f"could not read segmentation input {path}: {exc}") from exc


def _read_oshb_logical_hashes(directory: Path) -> dict[str, str]:
    path = directory / "table-hashes.json"
    if not path.is_file():
        raise SegmentationInputError(f"OSHB table-hash document does not exist: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        values = document["logical_table_sha256"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SegmentationInputError(f"invalid OSHB table-hash document: {path}") from exc
    if not isinstance(values, dict):
        raise SegmentationInputError("OSHB logical hash record must be a mapping")
    return {name: str(values.get(name, "")) for name in OSHB_LOGICAL_DIGESTS}


def load_segmentation_inputs(
    *,
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    data_root: Path = Path("data"),
) -> SegmentationInputs:
    """Load and verify every immutable Milestone 5 input.

    A mismatch is a hard stop.  Regression constants are never updated here.
    """

    catalog = load_source_catalog(manifest_path)
    hebrew_source = _active_source(catalog, "macula-hebrew")
    greek_source = _active_source(catalog, "macula-greek")
    oshb_source = _active_source(catalog, "oshb-morphhb")
    hebrew_dir = _processed_source_directory(hebrew_source, data_root)
    greek_dir = _processed_source_directory(greek_source, data_root)
    oshb_dir = _processed_source_directory(oshb_source, data_root)

    hebrew = _read_required_parquet(hebrew_dir / "tokens.parquet")
    greek = _read_required_parquet(greek_dir / "tokens.parquet")
    ketiv = _read_required_parquet(oshb_dir / "kq_ketiv_tokens.parquet")
    registry = _read_required_parquet(oshb_dir / "kq_locus_registry.parquet")
    structural = _read_required_parquet(oshb_dir / "kq_structural_alignments.parquet")
    oshb_hashes = _read_oshb_logical_hashes(oshb_dir)

    digests = InputDigestSet(
        hebrew_identity=corpus_identity_digest(hebrew),
        hebrew_content=corpus_content_digest(hebrew),
        hebrew_analytical=corpus_analytical_digest(hebrew),
        greek_identity=corpus_identity_digest(greek),
        greek_content=corpus_content_digest(greek),
        greek_analytical=corpus_analytical_digest(greek),
        oshb_logical=oshb_hashes,
    )
    observed: dict[str, object] = {
        "hebrew token count": hebrew.height,
        "greek token count": greek.height,
        **digests.as_dict(),
    }
    expected: dict[str, object] = {
        "hebrew token count": HEBREW_TOKEN_COUNT,
        "greek token count": GREEK_TOKEN_COUNT,
        "hebrew_identity": HEBREW_IDENTITY_DIGEST,
        "hebrew_content": HEBREW_CONTENT_DIGEST,
        "hebrew_analytical": HEBREW_ANALYTICAL_DIGEST,
        "greek_identity": GREEK_IDENTITY_DIGEST,
        "greek_content": GREEK_CONTENT_DIGEST,
        "greek_analytical": GREEK_ANALYTICAL_DIGEST,
        "oshb_logical": OSHB_LOGICAL_DIGESTS,
    }
    mismatches = [
        name for name, expected_value in expected.items() if observed[name] != expected_value
    ]
    if mismatches:
        raise SegmentationInputError(
            "immutable segmentation input changed; stop before passage generation: "
            + ", ".join(mismatches)
        )
    return SegmentationInputs(
        hebrew_tokens=hebrew,
        greek_tokens=greek,
        ketiv_tokens=ketiv,
        locus_registry=registry,
        structural_alignments=structural,
        source_versions={
            hebrew_source.source_id: str(hebrew_source.version_or_commit),
            greek_source.source_id: str(greek_source.version_or_commit),
            oshb_source.source_id: str(oshb_source.version_or_commit),
        },
        digests=digests,
    )


def _with_verse_ordinals(frame: pl.DataFrame) -> pl.DataFrame:
    verses = (
        frame.select("book", "book_order", "chapter", "verse", "stream_position_in_corpus")
        .group_by("book", "book_order", "chapter", "verse", maintain_order=True)
        .agg(pl.col("stream_position_in_corpus").min().alias("_verse_start"))
        .sort("book_order", "_verse_start")
        .with_columns(
            pl.col("book").cum_count().over("book").cast(pl.Int32).alias("verse_ordinal_in_book")
        )
        .drop("_verse_start")
    )
    return frame.join(verses, on=["book", "book_order", "chapter", "verse"], how="left")


def _hebrew_base_stream(
    inputs: SegmentationInputs, reading: Literal["qere", "ketiv"]
) -> pl.DataFrame:
    selected = derive_supplemented_analysis_stream(
        inputs.hebrew_tokens,
        inputs.ketiv_tokens,
        inputs.locus_registry,
        inputs.structural_alignments,
        analysis_reading=reading,
    )
    all_tokens = pl.concat(
        [inputs.hebrew_tokens, inputs.ketiv_tokens], how="vertical", rechunk=True
    )
    alignments = inputs.structural_alignments.select(
        pl.col("ketiv_token_id").alias("token_id"),
        "locus_id",
    )
    joined = (
        selected.join(all_tokens, on="token_id", how="left", validate="1:1")
        .join(alignments, on="token_id", how="left", validate="m:1")
        .sort("analysis_position_in_corpus")
    )
    if joined.filter(pl.col("source_id").is_null()).height:
        raise SegmentationInputError(
            f"{reading} stream contains token IDs absent from source tables"
        )
    enriched = joined.select(
        "token_id",
        pl.lit("hebrew").alias("corpus"),
        pl.lit("edition_complete").alias("analysis_profile"),
        pl.lit(reading).alias("analysis_reading"),
        "language",
        "source_id",
        "source_version",
        "source_edition_reference",
        "source_word_id",
        "book",
        "book_order",
        "chapter",
        "verse",
        pl.format("{} {}:{}", "book", "chapter", "verse").alias("canonical_reference"),
        pl.col("position_in_corpus").cast(pl.Int64).alias("source_position_in_corpus"),
        pl.col("analysis_position_in_corpus").cast(pl.Int64).alias("stream_position_in_corpus"),
        pl.col("position_in_word").cast(pl.Int16),
        "surface_form",
        "normalized_form",
        "unpointed_form",
        pl.lit(None, dtype=pl.String).alias("folded_form"),
        pl.lit("").alias("leading_punctuation"),
        pl.lit("").alias("trailing_punctuation"),
        "is_zero_width",
        "is_punctuation",
        pl.lit(False).alias("is_elided"),
        "lemma",
        "lexical_root",
        "part_of_speech",
        "semantic_domain",
        "entity_id",
        "participant_id",
        "source_extras_json",
        "variant_type",
        "variant_group_id",
        "analysis_sentence_id",
        "analysis_clause_id",
        "analysis_phrase_id",
        pl.col("structural_status").alias("structural_resolution_status"),
        pl.when(pl.col("analysis_sentence_id").is_not_null())
        .then(pl.lit("resolved"))
        .otherwise(pl.lit("unresolved"))
        .alias("sentence_resolution_status"),
        pl.when(pl.col("analysis_clause_id").is_not_null())
        .then(pl.lit("resolved"))
        .otherwise(pl.lit("unresolved"))
        .alias("clause_resolution_status"),
        pl.when(pl.col("analysis_phrase_id").is_not_null())
        .then(pl.lit("resolved"))
        .otherwise(pl.lit("unresolved"))
        .alias("phrase_resolution_status"),
        "locus_id",
        pl.when(pl.col("source_id") == "oshb-morphhb")
        .then(pl.lit("ketiv_verse_stream"))
        .otherwise(pl.lit("qere_primary"))
        .alias("default_membership_basis"),
    )
    return _with_verse_ordinals(enriched)


def _greek_base_stream(inputs: SegmentationInputs) -> pl.DataFrame:
    tokens = inputs.greek_tokens.sort("position_in_corpus")
    enriched = tokens.select(
        "token_id",
        pl.lit("greek").alias("corpus"),
        pl.lit("edition_complete").alias("analysis_profile"),
        pl.lit("source").alias("analysis_reading"),
        "language",
        "source_id",
        "source_version",
        "source_edition_reference",
        "source_word_id",
        "book",
        "book_order",
        "chapter",
        "verse",
        pl.format("{} {}:{}", "book", "chapter", "verse").alias("canonical_reference"),
        pl.col("position_in_corpus").cast(pl.Int64).alias("source_position_in_corpus"),
        pl.col("position_in_corpus").cast(pl.Int64).alias("stream_position_in_corpus"),
        pl.lit(1, dtype=pl.Int16).alias("position_in_word"),
        "surface_form",
        "normalized_form",
        pl.lit(None, dtype=pl.String).alias("unpointed_form"),
        "folded_form",
        "leading_punctuation",
        "trailing_punctuation",
        pl.lit(False).alias("is_zero_width"),
        "is_punctuation",
        "is_elided",
        "lemma",
        pl.lit(None, dtype=pl.String).alias("lexical_root"),
        "part_of_speech",
        "semantic_domain",
        pl.lit(None, dtype=pl.String).alias("entity_id"),
        "participant_id",
        "source_extras_json",
        "variant_type",
        "variant_group_id",
        pl.col("sentence_id").alias("analysis_sentence_id"),
        pl.col("clause_id").alias("analysis_clause_id"),
        pl.col("phrase_id").alias("analysis_phrase_id"),
        pl.lit("source_native").alias("structural_resolution_status"),
        pl.lit("source_native").alias("sentence_resolution_status"),
        pl.lit("source_native").alias("clause_resolution_status"),
        pl.when(pl.col("phrase_id").is_not_null())
        .then(pl.lit("source_native"))
        .otherwise(pl.lit("unavailable"))
        .alias("phrase_resolution_status"),
        pl.lit(None, dtype=pl.String).alias("locus_id"),
        pl.lit("source_native").alias("default_membership_basis"),
    )
    return _with_verse_ordinals(enriched)


def _reference_parts(reference: str) -> tuple[str, int, int]:
    book, location = reference.split(" ", maxsplit=1)
    chapter, verse = location.split(":", maxsplit=1)
    return book, int(chapter), int(verse)


def _range_expression(book: str, start: tuple[int, int], end: tuple[int, int]) -> pl.Expr:
    coordinate = pl.col("chapter").cast(pl.Int64) * 1000 + pl.col("verse").cast(pl.Int64)
    lower = start[0] * 1000 + start[1]
    upper = end[0] * 1000 + end[1]
    return (pl.col("book") == book) & coordinate.is_between(lower, upper, closed="both")


def _profile_exclusion_expression(
    config: SegmentationConfig, profile: AnalysisProfileName
) -> pl.Expr:
    profiles = {item.name: item for item in config.analysis_profiles}
    selected = profiles.get(profile)
    if selected is None:
        raise SegmentationInputError(f"unknown analysis profile: {profile}")
    excluded_ids = set(selected.excluded_disputed_passage_ids)
    expression = pl.lit(False)
    for passage in config.disputed_passages:
        if passage.passage_id not in excluded_ids:
            continue
        start_book, start_chapter, start_verse = _reference_parts(passage.start_reference)
        end_book, end_chapter, end_verse = _reference_parts(passage.end_reference)
        if start_book != end_book:
            raise SegmentationInputError(f"disputed range crosses books: {passage.passage_id}")
        expression = expression | _range_expression(
            start_book,
            (start_chapter, start_verse),
            (end_chapter, end_verse),
        )
    return expression


def apply_analysis_profile(
    base_stream: pl.DataFrame,
    *,
    config: SegmentationConfig,
    profile: AnalysisProfileName,
) -> pl.DataFrame:
    """Apply one profile after proving source sentences/clauses are not truncated."""

    excluded = _profile_exclusion_expression(config, profile)
    audited = base_stream.with_columns(excluded.alias("_profile_excluded"))
    for field in ("analysis_sentence_id", "analysis_clause_id"):
        crossing = (
            audited.filter(pl.col(field).is_not_null())
            .group_by(field)
            .agg(pl.col("_profile_excluded").n_unique().alias("_states"))
            .filter(pl.col("_states") > 1)
        )
        if crossing.height:
            identifiers = crossing[field].head(5).to_list()
            raise SegmentationInputError(
                f"{profile} would truncate source {field}: {identifiers}; owner decision required"
            )
    return (
        audited.filter(~pl.col("_profile_excluded"))
        .drop("_profile_excluded")
        .with_columns(pl.lit(profile).alias("analysis_profile"))
        .cast(STREAM_TOKEN_SCHEMA)
        .select(STREAM_TOKEN_COLUMNS)
    )


def build_required_analysis_streams(
    inputs: SegmentationInputs,
    *,
    config: SegmentationConfig,
) -> dict[tuple[CorpusName, AnalysisProfileName, AnalysisReadingName], pl.DataFrame]:
    """Build every governed corpus/profile/reading combination."""

    bases: dict[tuple[CorpusName, AnalysisReadingName], pl.DataFrame] = {
        ("hebrew", "qere"): _hebrew_base_stream(inputs, "qere"),
        ("hebrew", "ketiv"): _hebrew_base_stream(inputs, "ketiv"),
        ("greek", "source"): _greek_base_stream(inputs),
    }
    streams: dict[tuple[CorpusName, AnalysisProfileName, AnalysisReadingName], pl.DataFrame] = {}
    for profile in ("edition_complete", "critical_core"):
        for (corpus, reading), base in bases.items():
            streams[(corpus, profile, reading)] = apply_analysis_profile(
                base,
                config=config,
                profile=profile,
            )
    return streams
