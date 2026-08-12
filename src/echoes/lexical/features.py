"""Governed lexical feature frequencies, vocabulary rows, and passage statistics."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

import polars as pl

from echoes.lexical.config import FeatureFamily
from echoes.lexical.identity import (
    FeatureIdentityPayload,
    LanguageNamespace,
    build_feature_identity,
)
from echoes.lexical.models import (
    FEATURE_VOCABULARY_SCHEMA,
    PASSAGE_FEATURE_STATISTICS_SCHEMA,
)
from echoes.lexical.sequences import PassageLexicalSequence, sequence_digest


class LexicalFeatureError(RuntimeError):
    """Raised when feature statistics violate governed assumptions."""


_SEQUENCE_FAMILY_MAP: dict[FeatureFamily, str] = {
    "lemma": "lemma",
    "root": "root",
    "normalized_surface": "surface",
    "part_of_speech": "part_of_speech",
    "morphology": "morphology",
    "english_gloss": "english_gloss",
}


def _feature_normalization_method(family: FeatureFamily) -> str:
    if family == "english_gloss":
        return "nfkc_casefold_punctuation_strip_whitespace_tokenize_no_stemming-v1"
    if family == "normalized_surface":
        return "source_governed_normalized_form-v1"
    return "source_annotation_nfc-v1"


def build_feature_vocabulary(
    sequences: Sequence[PassageLexicalSequence],
    *,
    family: FeatureFamily,
    namespace: LanguageNamespace,
    feature_order: int = 1,
    rare_maximum_corpus_frequency: int,
    high_frequency_document_ratio: float,
    formulaic_document_ratio: float,
    formulaic_minimum_corpus_count: int,
    book_genres: dict[str, str],
) -> pl.DataFrame:
    """Compute nonduplicated corpus/document/book/genre feature statistics."""

    if family not in _SEQUENCE_FAMILY_MAP:
        raise LexicalFeatureError(f"feature family requires derived phrase builder: {family}")
    if feature_order != 1:
        raise LexicalFeatureError("unigram feature vocabularies require feature_order=1")
    if rare_maximum_corpus_frequency < 1:
        raise LexicalFeatureError("rare maximum corpus frequency must be positive")
    if formulaic_minimum_corpus_count < 2:
        raise LexicalFeatureError("formulaic minimum corpus count must be at least two")
    if not 0.0 <= high_frequency_document_ratio <= 1.0:
        raise LexicalFeatureError("high-frequency document ratio must be in [0, 1]")
    if not 0.0 <= formulaic_document_ratio <= 1.0:
        raise LexicalFeatureError("formulaic document ratio must be in [0, 1]")
    if family == "english_gloss" and namespace != "en":
        raise LexicalFeatureError("English gloss vocabulary requires the en namespace")
    if family != "english_gloss" and namespace == "en":
        raise LexicalFeatureError("the en namespace is reserved for English gloss vocabulary")
    expected_corpus = {"hb": "hebrew", "gk": "greek"}.get(namespace)
    if expected_corpus is not None and any(item.corpus != expected_corpus for item in sequences):
        raise LexicalFeatureError(f"{namespace} vocabulary contains a passage from another corpus")
    if len({item.passage_id for item in sequences}) != len(sequences):
        raise LexicalFeatureError("duplicate passage IDs in feature-vocabulary input")
    sequence_family = _SEQUENCE_FAMILY_MAP[family]
    corpus_frequency: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    books: dict[str, set[str]] = defaultdict(set)
    genres: dict[str, set[str]] = defaultdict(set)
    seen_stream_occurrences: set[tuple[str, str, int]] = set()
    for passage in sequences:
        occurrences = getattr(passage, sequence_family)
        values = tuple(
            unicodedata.normalize("NFC", occurrence.value.strip()) for occurrence in occurrences
        )
        if any(not value for value in values):
            raise LexicalFeatureError("feature values must remain nonempty after normalization")
        occurrence_ordinals: Counter[tuple[str, str]] = Counter()
        for occurrence, value in zip(occurrences, values, strict=True):
            occurrence_key = (occurrence.token_id, value)
            ordinal = occurrence_ordinals[occurrence_key]
            occurrence_ordinals[occurrence_key] += 1
            stream_key = (occurrence.token_id, value, ordinal)
            if stream_key not in seen_stream_occurrences:
                corpus_frequency[value] += 1
                seen_stream_occurrences.add(stream_key)
        unique = set(values)
        document_frequency.update(unique)
        genre = book_genres.get(passage.book, "unassigned")
        for value in unique:
            books[value].add(passage.book)
            genres[value].add(genre)
    n_documents = len(sequences)
    rows: list[dict[str, object]] = []
    for value in sorted(corpus_frequency):
        df = document_frequency[value]
        idf = math.log((1.0 + n_documents) / (1.0 + df)) + 1.0
        identity = build_feature_identity(
            FeatureIdentityPayload(
                feature_family=family,
                language_namespace=namespace,
                feature_value=value,
                feature_order=feature_order,
            )
        )
        ratio = (df / n_documents) if n_documents else 0.0
        rows.append(
            {
                "feature_id": identity.identifier,
                "lexical_schema_version": 1,
                "feature_family": family,
                "language_namespace": namespace,
                "feature_value": value,
                "feature_order": feature_order,
                "corpus_frequency": corpus_frequency[value],
                "document_frequency": df,
                "inverse_document_frequency": idf,
                "book_frequency": len(books[value]),
                "genre_frequency": len(genres[value]),
                "is_rare": corpus_frequency[value] <= rare_maximum_corpus_frequency,
                "is_high_frequency": ratio >= high_frequency_document_ratio,
                "is_formulaic": (
                    corpus_frequency[value] >= formulaic_minimum_corpus_count
                    and ratio >= formulaic_document_ratio
                ),
                "contains_english_derived_content": family == "english_gloss",
                "normalization_method": _feature_normalization_method(family),
                "notes": "",
            }
        )
    return pl.DataFrame(rows, schema=FEATURE_VOCABULARY_SCHEMA, orient="row").sort("feature_id")


def combine_feature_vocabularies(frames: Iterable[pl.DataFrame]) -> pl.DataFrame:
    """Combine feature families while rejecting any identity collision."""

    available = [frame for frame in frames]
    if not available:
        return pl.DataFrame(schema=FEATURE_VOCABULARY_SCHEMA)
    combined = pl.concat(available, how="vertical_relaxed").cast(
        FEATURE_VOCABULARY_SCHEMA, strict=True
    )
    collisions = (
        combined.group_by("feature_id")
        .agg(pl.struct(pl.all().exclude("feature_id")).n_unique().alias("row_count"))
        .filter(pl.col("row_count") > 1)
    )
    if collisions.height:
        raise LexicalFeatureError("feature identity collision or inconsistent duplicate detected")
    return combined.unique("feature_id", keep="first").sort("feature_id")


def _passage_feature_digest(passage: PassageLexicalSequence) -> str:
    payload = {
        family: list(passage.values(family))
        for family in (
            "lemma",
            "root",
            "surface",
            "folded_surface",
            "part_of_speech",
            "morphology",
            "english_gloss",
        )
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def build_passage_feature_statistics(
    sequences: Sequence[PassageLexicalSequence],
    vocabulary: pl.DataFrame,
) -> pl.DataFrame:
    """Create one deterministic, text-free feature summary per passage."""

    if vocabulary.is_empty():
        rare_values: dict[tuple[str, str], set[str]] = {}
        formulaic_values: dict[tuple[str, str], set[str]] = {}
    else:
        rare_values = {
            (str(namespace), str(family)): set(group.get_column("feature_value").to_list())
            for (namespace, family), group in vocabulary.filter(pl.col("is_rare")).group_by(
                "language_namespace", "feature_family", maintain_order=False
            )
        }
        formulaic_values = {
            (str(namespace), str(family)): set(group.get_column("feature_value").to_list())
            for (namespace, family), group in vocabulary.filter(pl.col("is_formulaic")).group_by(
                "language_namespace", "feature_family", maintain_order=False
            )
        }
    rows: list[dict[str, object]] = []
    for passage in sorted(sequences, key=lambda item: item.passage_id):
        namespace = "hb" if passage.corpus == "hebrew" else "gk"
        lemma = passage.values("lemma")
        root = passage.values("root")
        surface = passage.values("surface")
        original_occurrences = (
            *passage.lemma,
            *passage.root,
            *passage.surface,
            *passage.folded_surface,
            *passage.part_of_speech,
            *passage.morphology,
        )
        eligible = len({occurrence.token_id for occurrence in original_occurrences})
        formulaic_count = 0
        rare_count = 0
        for feature_family, sequence_family in _SEQUENCE_FAMILY_MAP.items():
            feature_namespace = "en" if feature_family == "english_gloss" else namespace
            values = passage.values(sequence_family)
            formulaic_count += sum(
                value in formulaic_values.get((feature_namespace, feature_family), set())
                for value in values
            )
            rare_count += sum(
                value in rare_values.get((feature_namespace, feature_family), set())
                for value in values
            )
        rows.append(
            {
                "passage_id": passage.passage_id,
                "analysis_profile": passage.analysis_profile,
                "analysis_reading": passage.analysis_reading,
                "granularity": passage.granularity,
                "corpus": passage.corpus,
                "book": passage.book,
                "token_count": passage.token_count,
                "eligible_token_count": eligible,
                "distinct_lemma_count": len(set(lemma)),
                "distinct_root_count": len(set(root)),
                "distinct_surface_count": len(set(surface)),
                "lemma_sequence_length": len(lemma),
                "root_sequence_length": len(root),
                "english_gloss_sequence_length": len(passage.english_gloss),
                "formulaic_feature_count": formulaic_count,
                "rare_feature_count": rare_count,
                "feature_vector_digest": _passage_feature_digest(passage),
                "source_passage_digest": passage.source_passage_digest,
            }
        )
    return pl.DataFrame(rows, schema=PASSAGE_FEATURE_STATISTICS_SCHEMA, orient="row").sort(
        "passage_id"
    )


def passage_sequence_hashes(
    sequences: Sequence[PassageLexicalSequence], family: str
) -> dict[str, str]:
    """Expose ordered per-passage sequence hashes for null conservation checks."""

    return {
        passage.passage_id: sequence_digest(passage.values(family))
        for passage in sorted(sequences, key=lambda item: item.passage_id)
    }
