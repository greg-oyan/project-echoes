"""Deterministic passage generation for one verified book-stream partition."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from itertools import pairwise
from typing import cast

import polars as pl

from echoes.segment.identity import IdentityMember, PassageIdRegistry, payload_from_membership
from echoes.segment.models import (
    PASSAGE_ADJACENCY_COLUMNS,
    PASSAGE_ADJACENCY_POLARS_SCHEMA,
    PASSAGE_COLUMNS,
    PASSAGE_MEMBERSHIP_COLUMNS,
    PASSAGE_MEMBERSHIP_POLARS_SCHEMA,
    PASSAGE_POLARS_SCHEMA,
    SEGMENTATION_EXCLUSION_COLUMNS,
    SEGMENTATION_EXCLUSION_POLARS_SCHEMA,
    SEGMENTATION_ISSUE_COLUMNS,
    SEGMENTATION_ISSUE_POLARS_SCHEMA,
    AnalysisProfile,
    AnalysisReading,
    Corpus,
    Granularity,
    PassageAdjacencyRow,
    PassageRow,
    SegmentationExclusionRow,
    SegmentationIssueRow,
    SegmentationSeverity,
)
from echoes.segment.reconstruction import PassageReconstruction, reconstruct_passage
from echoes.segment.streams import STREAM_TOKEN_COLUMNS, STREAM_TOKEN_SCHEMA
from echoes.settings import SegmentationConfig

_GRANULARITY_ORDER: dict[str, int] = {
    "clause": 0,
    "sentence": 1,
    "verse": 2,
    "two_verse": 3,
    "five_verse": 4,
}
_RESOLUTION_VALUES = {"source_native", "resolved", "partially_resolved", "unresolved"}


class PassageGenerationError(RuntimeError):
    """Raised when one stream partition cannot produce safe passages."""


@dataclass(frozen=True, slots=True)
class GeneratedPartition:
    """All logical segmentation tables emitted for one book stream."""

    passages: pl.DataFrame
    membership: pl.DataFrame
    adjacency: pl.DataFrame
    exclusions: pl.DataFrame
    issues: pl.DataFrame


@dataclass(slots=True)
class _PassageDraft:
    """One validated identity plus mutable neighbor convenience fields."""

    row: dict[str, object]
    tokens: pl.DataFrame
    references: tuple[str, ...]
    token_ids: tuple[str, ...]
    verse_ordinals: tuple[int, ...]
    constituent_verse_ids: tuple[str, ...]
    start_position: int
    end_position: int
    previous_id: str | None = None
    next_id: str | None = None
    overlap_previous: int = 0
    overlap_next: int = 0

    @property
    def passage_id(self) -> str:
        return cast(str, self.row["passage_id"])

    @property
    def granularity(self) -> Granularity:
        return cast(Granularity, self.row["granularity"])


@dataclass(frozen=True, slots=True)
class _Edge:
    """One deterministic passage relationship used for rows and neighbors."""

    left: _PassageDraft
    right: _PassageDraft
    source_successor: bool
    analytically_continuous: bool
    reference_gap: bool
    boundary_break: bool
    relation: str
    reason: str


@dataclass(slots=True)
class _GenerationContext:
    config: SegmentationConfig
    segmentation_run_id: str
    segmentation_config_hash: str
    corpus: Corpus
    profile: AnalysisProfile
    reading: AnalysisReading
    book: str
    book_order: int
    registry: PassageIdRegistry = field(default_factory=PassageIdRegistry)
    uncertain_ketiv_positions: tuple[int, ...] = ()


def _json_array(values: list[object] | tuple[object, ...]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _empty_frame(schema: pl.Schema, columns: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema).select(columns)


def _frame_from_model_rows(
    rows: list[dict[str, object]], schema: pl.Schema, columns: tuple[str, ...]
) -> pl.DataFrame:
    if not rows:
        return _empty_frame(schema, columns)
    return pl.DataFrame(rows, schema=schema, strict=False).select(columns)


def _reference_coordinates(reference: str) -> tuple[str, int, int]:
    book, location = reference.split(" ", maxsplit=1)
    chapter, verse = location.split(":", maxsplit=1)
    return book, int(chapter), int(verse)


def _reference_gap_between(left: str, right: str) -> bool:
    left_book, left_chapter, left_verse = _reference_coordinates(left)
    right_book, right_chapter, right_verse = _reference_coordinates(right)
    if left_book != right_book:
        return True
    if left_chapter == right_chapter:
        return right_verse != left_verse + 1
    if right_chapter == left_chapter + 1:
        return right_verse != 1
    return True


def _references_have_gap(references: tuple[str, ...]) -> bool:
    return any(_reference_gap_between(left, right) for left, right in pairwise(references))


def _range_contains_reference(start: str, end: str, reference: str) -> bool:
    start_book, start_chapter, start_verse = _reference_coordinates(start)
    end_book, end_chapter, end_verse = _reference_coordinates(end)
    book, chapter, verse = _reference_coordinates(reference)
    return book == start_book == end_book and (start_chapter, start_verse) <= (chapter, verse) <= (
        end_chapter,
        end_verse,
    )


def _disputed_ids(references: tuple[str, ...], config: SegmentationConfig) -> tuple[str, ...]:
    return tuple(
        passage.passage_id
        for passage in config.disputed_passages
        if any(
            _range_contains_reference(
                passage.start_reference,
                passage.end_reference,
                reference,
            )
            for reference in references
        )
    )


def _partition_value(stream: pl.DataFrame, field_name: str) -> object:
    values = stream[field_name].unique(maintain_order=True).to_list()
    if len(values) != 1 or values[0] is None:
        raise PassageGenerationError(
            f"generation requires one non-null {field_name} per partition; observed {values}"
        )
    return values[0]


def _validate_partition(stream: pl.DataFrame, config: SegmentationConfig) -> _GenerationContext:
    missing = sorted(set(STREAM_TOKEN_COLUMNS) - set(stream.columns))
    if missing:
        raise PassageGenerationError("stream partition is missing columns: " + ", ".join(missing))
    if stream.is_empty():
        raise PassageGenerationError("cannot generate passages from an empty stream partition")
    try:
        stream.cast(STREAM_TOKEN_SCHEMA).select(STREAM_TOKEN_COLUMNS)
    except pl.exceptions.PolarsError as exc:
        raise PassageGenerationError(f"stream partition does not match its schema: {exc}") from exc

    corpus = cast(Corpus, _partition_value(stream, "corpus"))
    profile = cast(AnalysisProfile, _partition_value(stream, "analysis_profile"))
    reading = cast(AnalysisReading, _partition_value(stream, "analysis_reading"))
    book = cast(str, _partition_value(stream, "book"))
    book_order = cast(int, _partition_value(stream, "book_order"))
    if corpus not in config.enabled_corpora:
        raise PassageGenerationError(f"corpus is not enabled for segmentation: {corpus}")
    if profile not in config.enabled_analysis_profiles:
        raise PassageGenerationError(f"analysis profile is not enabled: {profile}")
    if corpus == "hebrew" and reading not in config.enabled_analysis_readings.hebrew:
        raise PassageGenerationError(f"Hebrew reading is not enabled: {reading}")
    if corpus == "greek" and reading not in config.enabled_analysis_readings.greek:
        raise PassageGenerationError(f"Greek reading is not enabled: {reading}")

    uncertain: tuple[int, ...] = ()
    if corpus == "hebrew" and reading == "ketiv":
        uncertain = tuple(
            stream.filter(
                (pl.col("source_id") == "oshb-morphhb")
                & (
                    (pl.col("clause_resolution_status") != "resolved")
                    | (pl.col("phrase_resolution_status") != "resolved")
                )
            )["stream_position_in_corpus"].to_list()
        )
    return _GenerationContext(
        config=config,
        segmentation_run_id="",
        segmentation_config_hash="",
        corpus=corpus,
        profile=profile,
        reading=reading,
        book=book,
        book_order=book_order,
        uncertain_ketiv_positions=uncertain,
    )


def _intersects_uncertain_ketiv(
    context: _GenerationContext, start_position: int, end_position: int
) -> bool:
    positions = context.uncertain_ketiv_positions
    index = bisect_left(positions, start_position)
    return index < len(positions) and positions[index] <= end_position


def _passage_counts(tokens: pl.DataFrame) -> dict[str, int]:
    zero_width = tokens["is_zero_width"].sum()
    punctuation = tokens["is_punctuation"].sum()
    return {
        "token_count": tokens.height,
        "visible_token_count": tokens.height - int(zero_width),
        "zero_width_token_count": int(zero_width),
        "punctuation_token_count": int(punctuation),
        "word_count": tokens["source_word_id"].n_unique(),
        "sentence_count": tokens["analysis_sentence_id"].drop_nulls().n_unique(),
        "clause_count": tokens["analysis_clause_id"].drop_nulls().n_unique(),
    }


def _source_values_json(tokens: pl.DataFrame, field_name: str) -> str:
    values = _ordered_unique(cast(list[str], tokens[field_name].to_list()))
    return _json_array(values)


def _make_draft(
    tokens: pl.DataFrame,
    *,
    context: _GenerationContext,
    granularity: Granularity,
    source_unit_id: str | None,
    constituent_verse_ids: tuple[str, ...] = (),
    sensitivity_exclusion_count: int = 0,
) -> _PassageDraft:
    ordered = tokens.sort("stream_position_in_corpus")
    token_ids = tuple(cast(list[str], ordered["token_id"].to_list()))
    references = _ordered_unique(cast(list[str], ordered["canonical_reference"].to_list()))
    positions = cast(list[int], ordered["stream_position_in_corpus"].to_list())
    verse_ordinals = _ordered_unique(
        [str(value) for value in cast(list[int], ordered["verse_ordinal_in_book"].to_list())]
    )
    identity = context.registry.build_and_register(
        payload_from_membership(
            corpus=context.corpus,
            analysis_profile=context.profile,
            analysis_reading=context.reading,
            granularity=granularity,
            book=context.book,
            source_unit_id=source_unit_id,
            members=(
                IdentityMember(token_id, index, reference)
                for index, (token_id, reference) in enumerate(
                    zip(
                        token_ids,
                        cast(list[str], ordered["canonical_reference"].to_list()),
                        strict=True,
                    ),
                    start=1,
                )
            ),
        )
    )
    reconstruction: PassageReconstruction = reconstruct_passage(ordered, corpus=context.corpus)
    disputed = _disputed_ids(references, context.config)
    counts = _passage_counts(ordered)
    row = PassageRow(
        passage_id=identity.passage_id,
        identity_payload_sha256=identity.payload_sha256,
        segmentation_run_id=context.segmentation_run_id,
        corpus=context.corpus,
        analysis_profile=context.profile,
        analysis_reading=context.reading,
        granularity=granularity,
        book=context.book,
        book_order=context.book_order,
        start_reference=references[0],
        end_reference=references[-1],
        reference_sequence_json=_json_array(references),
        token_ids_json=reconstruction.token_ids_json,
        source_unit_id=source_unit_id,
        constituent_verse_passage_ids_json=_json_array(constituent_verse_ids),
        start_token_id=token_ids[0],
        end_token_id=token_ids[-1],
        start_stream_position_in_corpus=positions[0],
        end_stream_position_in_corpus=positions[-1],
        token_count=counts["token_count"],
        visible_token_count=counts["visible_token_count"],
        zero_width_token_count=counts["zero_width_token_count"],
        punctuation_token_count=counts["punctuation_token_count"],
        word_count=counts["word_count"],
        sentence_count=counts["sentence_count"],
        clause_count=counts["clause_count"],
        source_ids_json=_source_values_json(ordered, "source_id"),
        source_versions_json=_source_values_json(ordered, "source_version"),
        surface_text=reconstruction.surface_text,
        normalized_text=reconstruction.normalized_text,
        unpointed_text=reconstruction.unpointed_text,
        folded_text=reconstruction.folded_text,
        lemma_sequence_json=reconstruction.lemma_sequence_json,
        root_sequence_json=reconstruction.root_sequence_json,
        part_of_speech_sequence_json=reconstruction.part_of_speech_sequence_json,
        semantic_domain_sequence_json=reconstruction.semantic_domain_sequence_json,
        entity_ids_json=reconstruction.entity_ids_json,
        participant_ids_json=reconstruction.participant_ids_json,
        disputed_passage_flag=bool(disputed),
        disputed_passage_ids_json=_json_array(disputed),
        reference_gap=_references_have_gap(references),
        ketiv_structural_uncertainty=_intersects_uncertain_ketiv(
            context, positions[0], positions[-1]
        ),
        profile_truncated=False,
        sensitivity_exclusion_count=sensitivity_exclusion_count,
        previous_passage_id=None,
        next_passage_id=None,
        overlap_with_previous_token_count=0,
        overlap_with_next_token_count=0,
        segmentation_config_hash=context.segmentation_config_hash,
        created_by_schema_version=1,
    ).model_dump(mode="python")
    return _PassageDraft(
        row=row,
        tokens=ordered,
        references=references,
        token_ids=token_ids,
        verse_ordinals=tuple(int(value) for value in verse_ordinals),
        constituent_verse_ids=constituent_verse_ids,
        start_position=positions[0],
        end_position=positions[-1],
    )


def _source_unit_drafts(
    stream: pl.DataFrame,
    *,
    context: _GenerationContext,
    granularity: Granularity,
    field_name: str,
) -> list[_PassageDraft]:
    assigned = stream.filter(pl.col(field_name).is_not_null())
    groups = assigned.partition_by(field_name, maintain_order=True, include_key=True)
    null_positions = (
        tuple(
            cast(
                list[int],
                stream.filter(pl.col(field_name).is_null())["stream_position_in_corpus"].to_list(),
            )
        )
        if granularity == "clause"
        else ()
    )
    drafts: list[_PassageDraft] = []
    for group in groups:
        start_position = cast(int, group["stream_position_in_corpus"].min())
        end_position = cast(int, group["stream_position_in_corpus"].max())
        exclusion_count = (
            bisect_right(null_positions, end_position) - bisect_left(null_positions, start_position)
            if granularity == "clause"
            else 0
        )
        drafts.append(
            _make_draft(
                group,
                context=context,
                granularity=granularity,
                source_unit_id=cast(str, group[field_name][0]),
                sensitivity_exclusion_count=exclusion_count,
            )
        )
    return sorted(
        drafts, key=lambda item: (item.start_position, item.end_position, item.passage_id)
    )


def _verse_drafts(stream: pl.DataFrame, *, context: _GenerationContext) -> list[_PassageDraft]:
    return [
        _make_draft(group, context=context, granularity="verse", source_unit_id=None)
        for group in stream.partition_by(
            "verse_ordinal_in_book", maintain_order=True, include_key=True
        )
    ]


def _boundary_declaration(
    left_reference: str,
    right_reference: str,
    *,
    context: _GenerationContext,
) -> tuple[bool, str | None, str | None, bool]:
    boundary = next(
        (
            item
            for item in context.config.analytical_boundary_breaks
            if item.corpus == context.corpus
            and item.from_reference == left_reference
            and item.to_reference == right_reference
        ),
        None,
    )
    successor = next(
        (
            item
            for item in context.config.source_successors
            if item.corpus == context.corpus
            and item.from_reference == left_reference
            and item.to_reference == right_reference
        ),
        None,
    )
    return (
        boundary is not None,
        boundary.reason if boundary is not None else None,
        successor.relation if successor is not None else None,
        successor.reference_gap if successor is not None else False,
    )


def _edge_between(
    left: _PassageDraft,
    right: _PassageDraft,
    *,
    context: _GenerationContext,
    require_verse_successor: bool,
) -> _Edge:
    left_reference = left.references[-1]
    right_reference = right.references[0]
    boundary, boundary_reason, declared_relation, declared_gap = _boundary_declaration(
        left_reference, right_reference, context=context
    )
    left_ordinal = left.verse_ordinals[-1]
    right_ordinal = right.verse_ordinals[0]
    profile_gap = right_ordinal > left_ordinal + 1
    chapter_crossing = (
        _reference_coordinates(left_reference)[1] != _reference_coordinates(right_reference)[1]
    )
    source_successor = (
        right_ordinal == left_ordinal + 1 if require_verse_successor else not profile_gap
    )
    reference_gap = declared_gap or (
        source_successor
        and left_reference != right_reference
        and _reference_gap_between(left_reference, right_reference)
    )
    analytically_continuous = (
        source_successor
        and not profile_gap
        and not boundary
        and (not chapter_crossing or context.config.window_policy.cross_chapter_boundaries)
    )
    if boundary:
        relation = declared_relation or "analytical_boundary_break"
        reason = boundary_reason or "configured analytical boundary break"
    elif profile_gap:
        relation = "profile_exclusion"
        reason = "one or more source verses are excluded by the analysis profile"
    elif chapter_crossing:
        relation = "chapter_transition"
        reason = "configured source-order chapter transition"
    elif reference_gap:
        relation = "reference_gap"
        reason = "extant source-order neighbors span an edition-omitted verse number"
    else:
        relation = "source_order"
        reason = "consecutive passages in the selected source stream"
    return _Edge(
        left=left,
        right=right,
        source_successor=source_successor,
        analytically_continuous=analytically_continuous,
        reference_gap=reference_gap,
        boundary_break=boundary or profile_gap,
        relation=relation,
        reason=reason,
    )


def _verse_edges(verses: list[_PassageDraft], *, context: _GenerationContext) -> list[_Edge]:
    return [
        _edge_between(left, right, context=context, require_verse_successor=True)
        for left, right in pairwise(verses)
    ]


def _window_drafts(
    verses: list[_PassageDraft],
    verse_edges: list[_Edge],
    *,
    context: _GenerationContext,
    granularity: Granularity,
    size: int,
) -> list[_PassageDraft]:
    windows: list[_PassageDraft] = []
    for start in range(0, len(verses) - size + 1):
        if not all(edge.analytically_continuous for edge in verse_edges[start : start + size - 1]):
            continue
        constituents = verses[start : start + size]
        tokens = pl.concat([item.tokens for item in constituents], how="vertical", rechunk=False)
        windows.append(
            _make_draft(
                tokens,
                context=context,
                granularity=granularity,
                source_unit_id=None,
                constituent_verse_ids=tuple(item.passage_id for item in constituents),
            )
        )
    return windows


def _window_edges(windows: list[_PassageDraft]) -> list[_Edge]:
    edges: list[_Edge] = []
    for left, right in pairwise(windows):
        shifted = left.constituent_verse_ids[1:] == right.constituent_verse_ids[:-1]
        if not shifted:
            continue
        edges.append(
            _Edge(
                left=left,
                right=right,
                source_successor=True,
                analytically_continuous=True,
                reference_gap=False,
                boundary_break=False,
                relation="sliding_window",
                reason="windows differ by one analytically continuous constituent verse",
            )
        )
    return edges


def _source_unit_edges(drafts: list[_PassageDraft], *, context: _GenerationContext) -> list[_Edge]:
    return [
        _edge_between(left, right, context=context, require_verse_successor=False)
        for left, right in pairwise(drafts)
    ]


def _apply_neighbors(edges: list[_Edge]) -> None:
    for edge in edges:
        if not edge.analytically_continuous:
            continue
        overlap = len(set(edge.left.token_ids) & set(edge.right.token_ids))
        edge.left.next_id = edge.right.passage_id
        edge.left.overlap_next = overlap
        edge.right.previous_id = edge.left.passage_id
        edge.right.overlap_previous = overlap


def _adjacency_rows(edges: list[_Edge], *, context: _GenerationContext) -> list[dict[str, object]]:
    return [
        PassageAdjacencyRow(
            corpus=context.corpus,
            analysis_profile=context.profile,
            analysis_reading=context.reading,
            granularity=edge.left.granularity,
            from_passage_id=edge.left.passage_id,
            to_passage_id=edge.right.passage_id,
            source_successor=edge.source_successor,
            analytically_continuous=edge.analytically_continuous,
            reference_gap=edge.reference_gap,
            boundary_break=edge.boundary_break,
            relation=edge.relation,
            reason=edge.reason,
            segmentation_run_id=context.segmentation_run_id,
        ).model_dump(mode="python")
        for edge in edges
    ]


def _membership_basis_expression(context: _GenerationContext, granularity: Granularity) -> pl.Expr:
    if granularity in {"two_verse", "five_verse"}:
        return pl.lit("window_composition")
    if context.corpus == "greek":
        return pl.lit("source_native")
    if context.reading == "qere":
        return pl.lit("qere_primary")
    ketiv_basis = {
        "clause": "ketiv_clause_alignment",
        "sentence": "ketiv_sentence_alignment",
        "verse": "ketiv_verse_stream",
    }[granularity]
    return (
        pl.when(pl.col("source_id") == "oshb-morphhb")
        .then(pl.lit(ketiv_basis))
        .otherwise(pl.lit("qere_primary"))
    )


def _resolution_expression(context: _GenerationContext, granularity: Granularity) -> pl.Expr:
    if context.corpus == "greek" or context.reading == "qere":
        return pl.lit("source_native")
    field_name = {
        "clause": "clause_resolution_status",
        "sentence": "sentence_resolution_status",
        "verse": "structural_resolution_status",
        "two_verse": "structural_resolution_status",
        "five_verse": "structural_resolution_status",
    }[granularity]
    return (
        pl.when(pl.col("source_id") != "oshb-morphhb")
        .then(pl.lit("source_native"))
        .when(pl.col(field_name).is_in(_RESOLUTION_VALUES))
        .then(pl.col(field_name))
        .otherwise(pl.lit("unresolved"))
    )


def _membership_frame(draft: _PassageDraft, *, context: _GenerationContext) -> pl.DataFrame:
    return (
        draft.tokens.select(
            pl.lit(draft.passage_id).alias("passage_id"),
            "token_id",
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("position_in_passage"),
            "source_position_in_corpus",
            pl.col("canonical_reference").alias("source_reference"),
            "source_id",
            "variant_type",
            _membership_basis_expression(context, draft.granularity).alias("membership_basis"),
            _resolution_expression(context, draft.granularity).alias(
                "structural_resolution_status"
            ),
            pl.lit(context.segmentation_run_id).alias("segmentation_run_id"),
            pl.lit(context.corpus).alias("corpus"),
            pl.lit(context.profile).alias("analysis_profile"),
            pl.lit(context.reading).alias("analysis_reading"),
            pl.lit(draft.granularity).alias("granularity"),
            "stream_position_in_corpus",
            "source_edition_reference",
            "source_version",
            "locus_id",
        )
        .cast(PASSAGE_MEMBERSHIP_POLARS_SCHEMA)
        .select(PASSAGE_MEMBERSHIP_COLUMNS)
    )


def _clause_exclusions(
    stream: pl.DataFrame,
    clauses: list[_PassageDraft],
    *,
    context: _GenerationContext,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    tokens = list(stream.filter(pl.col("analysis_clause_id").is_null()).iter_rows(named=True))
    active: list[_PassageDraft] = []
    next_clause = 0
    for token in tokens:
        position = cast(int, token["stream_position_in_corpus"])
        while next_clause < len(clauses) and clauses[next_clause].start_position <= position:
            active.append(clauses[next_clause])
            next_clause += 1
        active = [clause for clause in active if clause.end_position >= position]
        related_clause_ids = tuple(clause.passage_id for clause in active)
        is_ketiv_unresolved = (
            context.corpus == "hebrew"
            and context.reading == "ketiv"
            and token["source_id"] == "oshb-morphhb"
        )
        reason_code = (
            "ketiv_clause_mapping_unresolved"
            if is_ketiv_unresolved
            else "primary_clause_annotation_unavailable"
        )
        token_id = cast(str, token["token_id"])
        identifier_payload = "|".join(
            (
                context.segmentation_run_id,
                context.profile,
                context.reading,
                "clause",
                token_id,
            )
        )
        exclusion_id = "X_CLAUSE_" + hashlib.sha256(identifier_payload.encode("utf-8")).hexdigest()
        rows.append(
            SegmentationExclusionRow(
                exclusion_id=exclusion_id,
                segmentation_run_id=context.segmentation_run_id,
                corpus=context.corpus,
                analysis_profile=context.profile,
                analysis_reading=context.reading,
                granularity="clause",
                token_id=token_id,
                locus_id=cast(str | None, token["locus_id"]),
                source_reference=cast(str, token["canonical_reference"]),
                reason_code=reason_code,
                resolution_status=(
                    "unresolved" if is_ketiv_unresolved else "source_annotation_unavailable"
                ),
                related_passage_ids_json=_json_array(related_clause_ids),
                notes=(
                    "supplementary Ketiv token has no resolved analytical clause mapping"
                    if is_ketiv_unresolved
                    else "primary source supplies no clause assignment for this token"
                ),
                source_id=cast(str, token["source_id"]),
                source_version=cast(str, token["source_version"]),
                source_edition_reference=cast(str, token["source_edition_reference"]),
                stream_position_in_corpus=position,
            ).model_dump(mode="python")
        )
    return rows


def _sentence_issues(
    stream: pl.DataFrame, *, context: _GenerationContext
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for token in stream.filter(pl.col("analysis_sentence_id").is_null()).iter_rows(named=True):
        token_id = cast(str, token["token_id"])
        issue_id = (
            "I_SENTENCE_"
            + hashlib.sha256(
                "|".join(
                    (
                        context.segmentation_run_id,
                        context.profile,
                        context.reading,
                        token_id,
                    )
                ).encode("utf-8")
            ).hexdigest()
        )
        rows.append(
            SegmentationIssueRow(
                issue_id=issue_id,
                segmentation_run_id=context.segmentation_run_id,
                severity=SegmentationSeverity.ERROR,
                code="sentence_mapping_unavailable",
                message="selected-stream token has no usable sentence mapping",
                corpus=context.corpus,
                analysis_profile=context.profile,
                analysis_reading=context.reading,
                granularity="sentence",
                passage_id=None,
                token_id=token_id,
                source_reference=cast(str, token["canonical_reference"]),
                details_json=json.dumps(
                    {
                        "locus_id": token["locus_id"],
                        "resolution_status": token["sentence_resolution_status"],
                        "source_id": token["source_id"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ).model_dump(mode="python")
        )
    return rows


def _finalize_passage_rows(drafts: list[_PassageDraft]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for draft in sorted(
        drafts,
        key=lambda item: (
            _GRANULARITY_ORDER[item.granularity],
            item.start_position,
            item.end_position,
            item.passage_id,
        ),
    ):
        draft.row.update(
            {
                "previous_passage_id": draft.previous_id,
                "next_passage_id": draft.next_id,
                "overlap_with_previous_token_count": draft.overlap_previous,
                "overlap_with_next_token_count": draft.overlap_next,
            }
        )
        rows.append(PassageRow.model_validate(draft.row).model_dump(mode="python"))
    return rows


def generate_partition(
    stream: pl.DataFrame,
    *,
    config: SegmentationConfig,
    segmentation_run_id: str,
    config_hash: str,
) -> GeneratedPartition:
    """Generate every Milestone 5 granularity for one book stream.

    The caller supplies one already verified corpus/profile/reading/book frame.
    Grouping and window composition occur per passage; authoritative membership
    is assembled with Polars expressions rather than per-membership Pydantic
    construction.
    """

    if not segmentation_run_id:
        raise PassageGenerationError("segmentation_run_id must be nonempty")
    ordered = stream.sort("stream_position_in_corpus").select(STREAM_TOKEN_COLUMNS)
    context = _validate_partition(ordered, config)
    context.segmentation_run_id = segmentation_run_id
    context.segmentation_config_hash = config_hash
    if len(context.segmentation_config_hash) != 64:
        raise PassageGenerationError("segmentation configuration hash must be SHA-256")

    clauses = _source_unit_drafts(
        ordered,
        context=context,
        granularity="clause",
        field_name="analysis_clause_id",
    )
    sentences = _source_unit_drafts(
        ordered,
        context=context,
        granularity="sentence",
        field_name="analysis_sentence_id",
    )
    verses = _verse_drafts(ordered, context=context)
    verse_edges = _verse_edges(verses, context=context)
    two_verse = _window_drafts(
        verses,
        verse_edges,
        context=context,
        granularity="two_verse",
        size=context.config.window_policy.window_sizes["two_verse"],
    )
    five_verse = _window_drafts(
        verses,
        verse_edges,
        context=context,
        granularity="five_verse",
        size=context.config.window_policy.window_sizes["five_verse"],
    )

    edge_groups = [
        _source_unit_edges(clauses, context=context),
        _source_unit_edges(sentences, context=context),
        verse_edges,
        _window_edges(two_verse),
        _window_edges(five_verse),
    ]
    for edges in edge_groups:
        _apply_neighbors(edges)

    all_drafts = clauses + sentences + verses + two_verse + five_verse
    passage_rows = _finalize_passage_rows(all_drafts)
    membership_frames = [_membership_frame(draft, context=context) for draft in all_drafts]
    membership = (
        pl.concat(membership_frames, how="vertical", rechunk=True)
        if membership_frames
        else _empty_frame(PASSAGE_MEMBERSHIP_POLARS_SCHEMA, PASSAGE_MEMBERSHIP_COLUMNS)
    )
    adjacency_rows = [
        row for edges in edge_groups for row in _adjacency_rows(edges, context=context)
    ]
    exclusion_rows = _clause_exclusions(ordered, clauses, context=context)

    passages = _frame_from_model_rows(passage_rows, PASSAGE_POLARS_SCHEMA, PASSAGE_COLUMNS)
    adjacency = _frame_from_model_rows(
        adjacency_rows,
        PASSAGE_ADJACENCY_POLARS_SCHEMA,
        PASSAGE_ADJACENCY_COLUMNS,
    )
    exclusions = _frame_from_model_rows(
        exclusion_rows,
        SEGMENTATION_EXCLUSION_POLARS_SCHEMA,
        SEGMENTATION_EXCLUSION_COLUMNS,
    )
    issues = _frame_from_model_rows(
        _sentence_issues(ordered, context=context),
        SEGMENTATION_ISSUE_POLARS_SCHEMA,
        SEGMENTATION_ISSUE_COLUMNS,
    )

    passage_order = passages.select("passage_id").with_row_index("_passage_order")
    membership = (
        membership.join(passage_order, on="passage_id", how="left", validate="m:1")
        .sort("_passage_order", "position_in_passage")
        .drop("_passage_order")
        .select(PASSAGE_MEMBERSHIP_COLUMNS)
    )
    return GeneratedPartition(
        passages=passages,
        membership=membership,
        adjacency=adjacency,
        exclusions=exclusions,
        issues=issues,
    )
