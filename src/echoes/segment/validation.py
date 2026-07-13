"""Leaf-streaming validation for persisted Milestone 5 passage artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field

from echoes.corpus.kq_supplement import KQ_SORT_COLUMNS
from echoes.corpus.storage import logical_frame_hash
from echoes.corpus.validation import (
    corpus_analytical_digest,
    corpus_content_digest,
    corpus_identity_digest,
)
from echoes.manifest import sha256_file
from echoes.segment.identity import IdentityMember, build_passage_identity, payload_from_membership
from echoes.segment.models import (
    PassageAdjacencyRow,
    PassageRow,
    SegmentationExclusionRow,
    SegmentationIssueRow,
    SegmentationMetadataRow,
)
from echoes.segment.pipeline import segmentation_config_fingerprint
from echoes.segment.reconstruction import ReconstructionError, reconstruct_passage
from echoes.segment.storage import (
    ARTIFACT_COLUMNS,
    ARTIFACT_NAMES,
    ARTIFACT_SCHEMAS,
    ARTIFACT_SORT_COLUMNS,
    METADATA_NONDETERMINISTIC_COLUMNS,
    ArtifactName,
    PassageStorageError,
    read_hash_manifest,
)
from echoes.segment.streams import SegmentationInputs, build_analysis_stream
from echoes.settings import SegmentationConfig

ValidationSeverity = Literal["error", "warning", "informational"]


class PassageValidationFinding(BaseModel):
    """One persisted-artifact validation finding."""

    model_config = ConfigDict(extra="forbid")

    severity: ValidationSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    table: str | None = None
    relative_path: str | None = None
    passage_id: str | None = None
    token_id: str | None = None


class PassageValidationReport(BaseModel):
    """Machine-readable result suitable for a CLI nonzero exit decision."""

    model_config = ConfigDict(extra="forbid")

    output_dir: str
    strict: bool
    passed: bool
    segmentation_run_id: str | None
    table_counts: dict[str, int]
    table_logical_hashes: dict[str, str]
    table_physical_hashes: dict[str, str]
    issues: list[PassageValidationFinding]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def informational_count(self) -> int:
        return sum(issue.severity == "informational" for issue in self.issues)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1


@dataclass(frozen=True, slots=True)
class _PassageFact:
    passage_id: str
    corpus: str
    profile: str
    reading: str
    granularity: str
    book: str
    references: tuple[str, ...]
    constituents: tuple[str, ...]
    previous_id: str | None
    next_id: str | None
    previous_overlap: int
    next_overlap: int
    reference_gap: bool
    uncertainty: bool
    disputed_ids: tuple[str, ...]
    exclusion_count: int


@dataclass(frozen=True, slots=True)
class _ExclusionFact:
    uncertainty: bool
    exclusion_count: int


@dataclass(slots=True)
class _SemanticIndex:
    passage_ids: set[str]
    exclusion_facts: dict[str, _ExclusionFact]


@dataclass(slots=True)
class _State:
    output_dir: Path
    strict: bool
    findings: list[PassageValidationFinding]
    table_counts: dict[str, int]
    table_logical_hashes: dict[str, str]
    table_physical_hashes: dict[str, str]
    run_id: str | None = None

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: ValidationSeverity = "error",
        table: str | None = None,
        path: str | None = None,
        passage_id: str | None = None,
        token_id: str | None = None,
    ) -> None:
        self.findings.append(
            PassageValidationFinding(
                severity=severity,
                code=code,
                message=message,
                table=table,
                relative_path=path,
                passage_id=passage_id,
                token_id=token_id,
            )
        )


def _mapping(value: object) -> dict[str, object]:
    return dict(cast(Mapping[str, object], value)) if isinstance(value, dict) else {}


def _string_mapping(value: object) -> dict[str, str]:
    return {str(key): str(item) for key, item in _mapping(value).items()}


def _int_mapping(value: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in _mapping(value).items():
        if isinstance(item, int) and not isinstance(item, bool):
            result[str(key)] = item
    return result


def _json_object(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return cast(dict[str, object], parsed)


def _json_strings(value: str) -> tuple[str, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("expected JSON string array")
    return tuple(cast(list[str], parsed))


def _logical_projection(table: ArtifactName, frame: pl.DataFrame) -> pl.DataFrame:
    if table != "segmentation_metadata":
        return frame
    return frame.select(
        column for column in frame.columns if column not in METADATA_NONDETERMINISTIC_COLUMNS
    )


def _aggregate(leaves: Mapping[str, Mapping[str, object]], key: str) -> str:
    payload = [
        {
            "path": path,
            "row_count": cast(int, values["row_count"]),
            key: str(values[key]),
        }
        for path, values in sorted(leaves.items())
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_leaf(
    state: _State,
    table: ArtifactName,
    path: Path,
) -> pl.DataFrame | None:
    relative = path.relative_to(state.output_dir).as_posix()
    try:
        frame = pl.read_parquet(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        state.add("parquet-unreadable", str(exc), table=table, path=relative)
        return None
    expected_columns = ARTIFACT_COLUMNS[table]
    if tuple(frame.columns) != expected_columns:
        state.add(
            "schema-columns",
            f"expected {expected_columns}, found {tuple(frame.columns)}",
            table=table,
            path=relative,
        )
        return None
    if frame.schema != ARTIFACT_SCHEMAS[table]:
        state.add(
            "schema-types",
            f"expected {ARTIFACT_SCHEMAS[table]}, found {frame.schema}",
            table=table,
            path=relative,
        )
    sorted_frame = frame.sort(list(ARTIFACT_SORT_COLUMNS[table])) if frame.height else frame
    if not frame.equals(sorted_frame):
        state.add(
            "nondeterministic-sort",
            "leaf rows are not in governed order",
            table=table,
            path=relative,
        )
    return frame


def _audit_storage(state: _State) -> dict[str, object] | None:
    try:
        manifest = read_hash_manifest(state.output_dir)
    except PassageStorageError as exc:
        state.add("hash-manifest", str(exc))
        return None
    manifest_artifacts = _mapping(manifest.get("artifacts"))
    observed_by_table: dict[str, dict[str, dict[str, object]]] = {}
    for table in ARTIFACT_NAMES:
        leaves: dict[str, dict[str, object]] = {}
        paths = sorted((state.output_dir / table).rglob("*.parquet"))
        if not paths:
            state.add("missing-artifact", f"no Parquet leaves for {table}", table=table)
        expected_leaves = _mapping(manifest_artifacts.get(table))
        for path in paths:
            relative = path.relative_to(state.output_dir).as_posix()
            frame = _read_leaf(state, table, path)
            if frame is None:
                continue
            logical = logical_frame_hash(
                _logical_projection(table, frame),
                sort_by=list(ARTIFACT_SORT_COLUMNS[table]),
            )
            physical = sha256_file(path)
            values = {
                "row_count": frame.height,
                "logical_sha256": logical,
                "parquet_sha256": physical,
            }
            leaves[relative] = values
            expected = _mapping(expected_leaves.get(relative))
            for key, actual in values.items():
                if expected.get(key) != actual:
                    state.add(
                        f"{key.replace('_sha256', '')}-mismatch",
                        f"manifest {key} differs from persisted leaf",
                        table=table,
                        path=relative,
                    )
        if set(expected_leaves) != set(leaves):
            state.add("manifest-leaf-set", "manifest and filesystem leaf sets differ", table=table)
        observed_by_table[table] = leaves
        state.table_counts[table] = sum(
            cast(int, values["row_count"]) for values in leaves.values()
        )
        state.table_logical_hashes[table] = _aggregate(leaves, "logical_sha256")
        state.table_physical_hashes[table] = _aggregate(leaves, "parquet_sha256")

    expected_counts = _int_mapping(manifest.get("table_counts"))
    expected_logical = _string_mapping(manifest.get("table_logical_sha256"))
    expected_physical = _string_mapping(manifest.get("table_physical_sha256"))
    for table in ARTIFACT_NAMES:
        if expected_counts.get(table) != state.table_counts.get(table):
            state.add("table-count-mismatch", "table count differs from manifest", table=table)
        if expected_logical.get(table) != state.table_logical_hashes.get(table):
            state.add("table-logical-hash-mismatch", "table logical hash differs", table=table)
        if expected_physical.get(table) != state.table_physical_hashes.get(table):
            state.add("table-physical-hash-mismatch", "table physical hash differs", table=table)
    return manifest


def _partition_value(path: Path, name: str) -> str | None:
    prefix = name + "="
    for part in path.parts:
        if part.startswith(prefix):
            return part.removeprefix(prefix)
    return None


def _artifact_paths(output_dir: Path, table: ArtifactName) -> list[Path]:
    return sorted((output_dir / table).rglob("*.parquet"))


def _passage_path_order(path: Path) -> tuple[int, str]:
    order = {"verse": 0, "clause": 1, "sentence": 2, "two_verse": 3, "five_verse": 4}
    return order.get(_partition_value(path, "granularity") or "", 99), path.as_posix()


def _load_adjacency_leaf(state: _State, path: Path) -> list[PassageAdjacencyRow]:
    frame = _read_leaf(state, "passage_adjacency", path)
    if frame is None:
        return []
    models: list[PassageAdjacencyRow] = []
    for row in frame.iter_rows(named=True):
        try:
            models.append(PassageAdjacencyRow.model_validate(row))
        except ValidationError as exc:
            state.add("adjacency-row", str(exc), table="passage_adjacency")
    return models


def _membership_groups(frame: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """Index one membership leaf in linear time for O(1) passage lookup."""

    groups = frame.partition_by("passage_id", maintain_order=True, as_dict=True)
    indexed: dict[str, pl.DataFrame] = {}
    for raw_key, group in groups.items():
        key = raw_key[0] if isinstance(raw_key, tuple) else raw_key
        indexed[str(key)] = group
    return indexed


def _stream_key(path: Path) -> tuple[str, str, str, str] | None:
    values = tuple(
        _partition_value(path, field)
        for field in ("corpus", "analysis_profile", "analysis_reading", "book")
    )
    if any(value is None for value in values):
        return None
    return cast(tuple[str, str, str, str], values)


def _expected_stream(
    streams: Mapping[tuple[str, str, str], pl.DataFrame], key: tuple[str, str, str, str]
) -> pl.DataFrame | None:
    stream = streams.get(key[:3])
    return None if stream is None else stream.filter(pl.col("book") == key[3])


def _validate_membership_group(
    state: _State,
    passage: PassageRow,
    membership: pl.DataFrame,
) -> tuple[str, ...] | None:
    passage_id = passage.passage_id
    positions = membership["position_in_passage"].to_list()
    token_ids = tuple(str(value) for value in membership["token_id"].to_list())
    references = tuple(
        dict.fromkeys(str(value) for value in membership["source_reference"].to_list())
    )
    if positions != list(range(1, membership.height + 1)):
        state.add(
            "membership-position",
            "positions are not one-based and continuous",
            passage_id=passage_id,
        )
    if len(token_ids) != len(set(token_ids)):
        state.add(
            "membership-duplicate-token", "duplicate token inside passage", passage_id=passage_id
        )
    if membership.height != passage.token_count:
        state.add(
            "membership-token-count", "membership count differs from passage", passage_id=passage_id
        )
    if token_ids and (
        token_ids[0] != passage.start_token_id or token_ids[-1] != passage.end_token_id
    ):
        state.add(
            "membership-boundary", "membership boundary token IDs differ", passage_id=passage_id
        )
    if tuple(json.loads(passage.token_ids_json)) != token_ids:
        state.add(
            "membership-token-sequence",
            "token_ids_json differs from membership",
            passage_id=passage_id,
        )
    stream_positions = membership["stream_position_in_corpus"].to_list()
    if stream_positions != sorted(stream_positions):
        state.add(
            "membership-stream-order",
            "membership does not follow selected-stream order",
            passage_id=passage_id,
        )
    if stream_positions and (
        stream_positions[0] != passage.start_stream_position_in_corpus
        or stream_positions[-1] != passage.end_stream_position_in_corpus
    ):
        state.add(
            "membership-stream-boundary",
            "stream boundary positions differ from membership",
            passage_id=passage_id,
        )
    if tuple(json.loads(passage.reference_sequence_json)) != references:
        state.add(
            "membership-reference-sequence", "reference sequence differs", passage_id=passage_id
        )
    if any(reference.split(" ", 1)[0] != passage.book for reference in references):
        state.add(
            "membership-cross-book", "passage membership crosses a book", passage_id=passage_id
        )
    for column, expected in (
        ("corpus", passage.corpus),
        ("analysis_profile", passage.analysis_profile),
        ("analysis_reading", passage.analysis_reading),
        ("granularity", passage.granularity),
        ("segmentation_run_id", passage.segmentation_run_id),
    ):
        if membership[column].unique().to_list() != [expected]:
            state.add("membership-context", f"membership {column} differs", passage_id=passage_id)
    try:
        payload = payload_from_membership(
            corpus=passage.corpus,
            analysis_profile=passage.analysis_profile,
            analysis_reading=passage.analysis_reading,
            granularity=passage.granularity,
            book=passage.book,
            source_unit_id=passage.source_unit_id,
            members=[
                IdentityMember(
                    str(row["token_id"]),
                    int(row["position_in_passage"]),
                    str(row["source_reference"]),
                )
                for row in membership.iter_rows(named=True)
            ],
        )
        identity = build_passage_identity(payload)
        if (
            identity.passage_id != passage_id
            or identity.payload_sha256 != passage.identity_payload_sha256
        ):
            state.add(
                "passage-identity",
                "identity does not reproduce from membership",
                passage_id=passage_id,
            )
    except (ValueError, ValidationError) as exc:
        state.add("passage-identity", str(exc), passage_id=passage_id)
    return token_ids if token_ids else None


def _validate_reconstruction(
    state: _State,
    passage: PassageRow,
    membership: pl.DataFrame,
    stream: pl.DataFrame,
) -> None:
    joined = (
        membership.select("token_id", "position_in_passage")
        .join(stream, on="token_id", how="left", validate="1:1")
        .sort("position_in_passage")
    )
    if joined.filter(pl.col("surface_form").is_null()).height:
        state.add(
            "reconstruction-token-lookup",
            "membership token absent from stream",
            passage_id=passage.passage_id,
        )
        return
    try:
        reconstruction = reconstruct_passage(joined, corpus=passage.corpus)
    except ReconstructionError as exc:
        state.add("reconstruction", str(exc), passage_id=passage.passage_id)
        return
    for field in (
        "surface_text",
        "normalized_text",
        "unpointed_text",
        "folded_text",
        "token_ids_json",
        "lemma_sequence_json",
        "root_sequence_json",
        "part_of_speech_sequence_json",
        "semantic_domain_sequence_json",
        "entity_ids_json",
        "participant_ids_json",
    ):
        if getattr(reconstruction, field) != getattr(passage, field):
            state.add("reconstruction-mismatch", f"{field} differs", passage_id=passage.passage_id)
    for value in (
        passage.surface_text,
        passage.normalized_text,
        passage.unpointed_text,
        passage.folded_text,
    ):
        if value is not None:
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                state.add(
                    "invalid-unicode",
                    "reconstructed text is not valid UTF-8",
                    passage_id=passage.passage_id,
                )


def _validate_semantics(
    state: _State,
    config: SegmentationConfig | None,
    streams: Mapping[tuple[str, str, str], pl.DataFrame],
    *,
    passage_paths: Sequence[Path] | None = None,
    seen_passage_ids: set[str] | None = None,
) -> _SemanticIndex:
    """Validate one or more artifact streams one book at a time.

    Membership leaves are partitioned once by passage ID.  This avoids the
    former O(passages x memberships) per-leaf filtering loop and bounds rich
    passage facts to one book while retaining only compact exclusion indexes.
    """

    selected_paths = list(
        _artifact_paths(state.output_dir, "passages") if passage_paths is None else passage_paths
    )
    global_seen = seen_passage_ids if seen_passage_ids is not None else set()
    index = _SemanticIndex(set(), {})
    grouped_paths: dict[tuple[str, str, str, str], list[Path]] = {}
    for path in selected_paths:
        key = _stream_key(path)
        if key is None:
            state.add(
                "partition-path",
                "passage partition lacks corpus/profile/reading/book keys",
                table="passages",
                path=path.relative_to(state.output_dir).as_posix(),
            )
            continue
        grouped_paths.setdefault(key, []).append(path)

    disputed = (
        {
            item.passage_id: (item.start_reference, item.end_reference)
            for item in config.disputed_passages
        }
        if config is not None
        else {}
    )
    for key, book_paths in sorted(grouped_paths.items()):
        stream = _expected_stream(streams, key)
        facts: dict[str, _PassageFact] = {}
        verse_members: dict[str, tuple[str, ...]] = {}
        continuous: set[tuple[str, str]] = set()
        edge_gaps: dict[tuple[str, str], bool] = {}
        adjacency_rows: list[PassageAdjacencyRow] = []

        for passage_path in sorted(book_paths, key=_passage_path_order):
            relative_tail = passage_path.relative_to(state.output_dir / "passages")
            membership_path = state.output_dir / "passage_membership" / relative_tail
            adjacency_path = state.output_dir / "passage_adjacency" / relative_tail
            passage_frame = _read_leaf(state, "passages", passage_path)
            membership_frame = _read_leaf(state, "passage_membership", membership_path)
            if passage_frame is None or membership_frame is None:
                continue
            membership_groups = _membership_groups(membership_frame)
            granularity = _partition_value(passage_path, "granularity")
            actual_coverage: list[str] = []
            passage_ids: set[str] = set()
            sample_models: list[PassageRow] = []
            for row in passage_frame.iter_rows(named=True):
                try:
                    model = PassageRow.model_validate(row)
                except ValidationError as exc:
                    state.add("passage-row", str(exc), table="passages")
                    continue
                passage_ids.add(model.passage_id)
                sample_models.append(model)
                sample_models.sort(
                    key=lambda item: hashlib.sha256(item.passage_id.encode()).hexdigest()
                )
                del sample_models[3:]
                if (
                    model.corpus,
                    model.analysis_profile,
                    model.analysis_reading,
                    model.book,
                ) != key:
                    state.add(
                        "partition-context",
                        "passage row differs from its partition path",
                        passage_id=model.passage_id,
                    )
                if granularity != model.granularity:
                    state.add(
                        "partition-granularity",
                        "passage granularity differs from its partition path",
                        passage_id=model.passage_id,
                    )
                if model.passage_id in global_seen:
                    state.add(
                        "duplicate-passage-id",
                        "passage ID appears more than once",
                        passage_id=model.passage_id,
                    )
                global_seen.add(model.passage_id)
                index.passage_ids.add(model.passage_id)
                if model.ketiv_structural_uncertainty or model.sensitivity_exclusion_count:
                    index.exclusion_facts[model.passage_id] = _ExclusionFact(
                        model.ketiv_structural_uncertainty,
                        model.sensitivity_exclusion_count,
                    )
                if state.run_id is None:
                    state.run_id = model.segmentation_run_id
                elif state.run_id != model.segmentation_run_id:
                    state.add(
                        "run-id-mismatch",
                        "passage rows contain multiple run IDs",
                        passage_id=model.passage_id,
                    )
                members = membership_groups.get(model.passage_id)
                if members is None:
                    state.add(
                        "passage-membership-set",
                        "passage has no membership rows",
                        passage_id=model.passage_id,
                        path=relative_tail.as_posix(),
                    )
                    continue
                token_ids = _validate_membership_group(state, model, members)
                if token_ids is None:
                    continue
                if granularity in {"clause", "sentence", "verse"}:
                    actual_coverage.extend(token_ids)
                references = _json_strings(model.reference_sequence_json)
                constituents = _json_strings(model.constituent_verse_passage_ids_json)
                facts[model.passage_id] = _PassageFact(
                    model.passage_id,
                    model.corpus,
                    model.analysis_profile,
                    model.analysis_reading,
                    model.granularity,
                    model.book,
                    references,
                    constituents,
                    model.previous_passage_id,
                    model.next_passage_id,
                    model.overlap_with_previous_token_count,
                    model.overlap_with_next_token_count,
                    model.reference_gap,
                    model.ketiv_structural_uncertainty,
                    _json_strings(model.disputed_passage_ids_json),
                    model.sensitivity_exclusion_count,
                )
                if model.granularity == "verse":
                    verse_members[model.passage_id] = token_ids
                elif model.granularity in {"two_verse", "five_verse"}:
                    expected_window_tokens = tuple(
                        token
                        for identifier in constituents
                        for token in verse_members.get(identifier, ())
                    )
                    if expected_window_tokens != token_ids:
                        state.add(
                            "window-membership",
                            "window membership differs from constituent verse concatenation",
                            passage_id=model.passage_id,
                        )
                if (
                    "unresolved" in members["structural_resolution_status"].to_list()
                    and not model.ketiv_structural_uncertainty
                ):
                    state.add(
                        "missing-ketiv-uncertainty",
                        "unresolved membership is not flagged",
                        passage_id=model.passage_id,
                    )

            if stream is not None and granularity in {"clause", "sentence", "verse"}:
                field = {
                    "clause": "analysis_clause_id",
                    "sentence": "analysis_sentence_id",
                }.get(granularity)
                expected = stream if field is None else stream.filter(pl.col(field).is_not_null())
                expected_ids = set(str(value) for value in expected["token_id"].to_list())
                if (
                    len(actual_coverage) != len(set(actual_coverage))
                    or set(actual_coverage) != expected_ids
                ):
                    state.add(
                        "source-unit-coverage",
                        f"{granularity} coverage differs from selected stream",
                        path=relative_tail.as_posix(),
                    )

            if stream is not None:
                for model in sample_models:
                    members = membership_groups.get(model.passage_id)
                    if members is not None:
                        _validate_reconstruction(state, model, members, stream)

            if passage_ids != set(membership_groups):
                state.add(
                    "passage-membership-set",
                    "passage and membership leaf ID sets differ",
                    path=relative_tail.as_posix(),
                )

            leaf_adjacency = _load_adjacency_leaf(state, adjacency_path)
            adjacency_rows.extend(leaf_adjacency)
            for edge in leaf_adjacency:
                edge_key = (edge.from_passage_id, edge.to_passage_id)
                if edge.analytically_continuous:
                    continuous.add(edge_key)
                edge_gaps[edge_key] = edge.reference_gap

        for edge in adjacency_rows:
            left = facts.get(edge.from_passage_id)
            right = facts.get(edge.to_passage_id)
            if left is None or right is None:
                state.add(
                    "adjacency-passage-missing",
                    "adjacency references an unknown passage",
                    passage_id=edge.from_passage_id,
                )
                continue
            expected_context = (left.corpus, left.profile, left.reading, left.granularity)
            edge_context = (
                edge.corpus,
                edge.analysis_profile,
                edge.analysis_reading,
                edge.granularity,
            )
            right_context = (right.corpus, right.profile, right.reading, right.granularity)
            if expected_context != edge_context or expected_context != right_context:
                state.add(
                    "adjacency-context",
                    "adjacency context differs from its passages",
                    passage_id=edge.from_passage_id,
                )

        for fact in facts.values():
            if (
                len(fact.references) > 1
                and "MRK 16:20" in fact.references
                and "MRK 16:99" in fact.references
            ):
                state.add(
                    "mark-endings-combined",
                    "multi-verse passage combines longer and alternate endings",
                    passage_id=fact.passage_id,
                )
            if _has_numeric_reference_gap(fact.references) and not fact.reference_gap:
                state.add(
                    "unmarked-reference-gap",
                    "passage spans a numbering gap without reference_gap",
                    passage_id=fact.passage_id,
                )

            if disputed:
                disputed_ids = tuple(
                    name
                    for name, (start, end) in disputed.items()
                    if _references_intersect(fact.references, start, end)
                )
                if set(fact.disputed_ids) != set(disputed_ids):
                    state.add(
                        "disputed-membership",
                        "disputed passage identifiers differ from configured overlap",
                        passage_id=fact.passage_id,
                    )
                if fact.profile == "critical_core" and disputed_ids:
                    state.add(
                        "critical-core-membership",
                        "critical-core passage contains excluded text",
                        passage_id=fact.passage_id,
                    )

        for fact in facts.values():
            if fact.granularity not in {"two_verse", "five_verse"}:
                continue
            expected_size = 2 if fact.granularity == "two_verse" else 5
            if len(fact.constituents) != expected_size:
                state.add(
                    "partial-window",
                    "window has wrong constituent count",
                    passage_id=fact.passage_id,
                )
                continue
            constituent_facts = [facts.get(identifier) for identifier in fact.constituents]
            if any(item is None for item in constituent_facts):
                state.add(
                    "window-constituent",
                    "window references an unknown verse",
                    passage_id=fact.passage_id,
                )
                continue
            typed_facts = cast(list[_PassageFact], constituent_facts)
            if any(item.granularity != "verse" or item.book != fact.book for item in typed_facts):
                state.add(
                    "window-boundary",
                    "window crosses a book or uses a non-verse constituent",
                    passage_id=fact.passage_id,
                )
            pairs = list(zip(fact.constituents, fact.constituents[1:], strict=False))
            if any(pair not in continuous for pair in pairs):
                state.add(
                    "window-continuity",
                    "window contains a discontinuous verse edge",
                    passage_id=fact.passage_id,
                )
            if fact.reference_gap != any(edge_gaps.get(pair, False) for pair in pairs):
                state.add(
                    "window-reference-gap",
                    "window reference-gap flag differs from adjacency",
                    passage_id=fact.passage_id,
                )
            expected_tokens = tuple(
                token
                for identifier in fact.constituents
                for token in verse_members.get(identifier, ())
            )
            if len(expected_tokens) != len(set(expected_tokens)):
                state.add(
                    "window-duplicate-token",
                    "window constituent concatenation duplicates a token",
                    passage_id=fact.passage_id,
                )

        for fact in facts.values():
            tokens = set(
                token
                for identifier in fact.constituents
                for token in verse_members.get(identifier, ())
            )
            for neighbor_id, recorded, direction in (
                (fact.previous_id, fact.previous_overlap, "previous"),
                (fact.next_id, fact.next_overlap, "next"),
            ):
                if neighbor_id is None:
                    if recorded:
                        state.add(
                            "neighbor-overlap",
                            f"{direction} overlap exists without neighbor",
                            passage_id=fact.passage_id,
                        )
                    continue
                neighbor = facts.get(neighbor_id)
                if neighbor is None:
                    state.add(
                        "neighbor-missing",
                        f"{direction} passage does not exist",
                        passage_id=fact.passage_id,
                    )
                    continue
                neighbor_tokens = set(
                    token
                    for identifier in neighbor.constituents
                    for token in verse_members.get(identifier, ())
                )
                if fact.granularity in {"two_verse", "five_verse"} and recorded != len(
                    tokens & neighbor_tokens
                ):
                    state.add(
                        "neighbor-overlap",
                        f"{direction} overlap count differs",
                        passage_id=fact.passage_id,
                    )
    return index


def _reference_coordinate(reference: str) -> tuple[str, int, int]:
    book, location = reference.split(" ", 1)
    chapter, verse = location.split(":", 1)
    return book, int(chapter), int(verse)


def _references_intersect(references: Sequence[str], start: str, end: str) -> bool:
    start_coord = _reference_coordinate(start)
    end_coord = _reference_coordinate(end)
    return any(
        (coordinate := _reference_coordinate(reference))[0] == start_coord[0]
        and start_coord <= coordinate <= end_coord
        for reference in references
    )


def _has_numeric_reference_gap(references: Sequence[str]) -> bool:
    coordinates = [_reference_coordinate(reference) for reference in references]
    return any(
        left[0] == right[0] and left[1] == right[1] and right[2] > left[2] + 1
        for left, right in pairwise(coordinates)
    )


def _validate_exclusions(
    state: _State,
    streams: Mapping[tuple[str, str, str], pl.DataFrame],
    semantic_index: _SemanticIndex,
    *,
    exclusion_paths: Sequence[Path] | None = None,
) -> None:
    verse_paths: dict[tuple[str, str, str, str], Path] = {}
    clause_contexts: set[tuple[str, str, str, str]] = set()
    for path in _artifact_paths(state.output_dir, "passage_membership"):
        key = _stream_key(path)
        if key is None:
            continue
        granularity = _partition_value(path, "granularity")
        if granularity == "verse":
            verse_paths[key] = path
        elif granularity == "clause":
            clause_contexts.add(key)

    related_counts: dict[str, int] = {}
    selected_paths = list(
        _artifact_paths(state.output_dir, "segmentation_exclusions")
        if exclusion_paths is None
        else exclusion_paths
    )
    for path in selected_paths:
        frame = _read_leaf(state, "segmentation_exclusions", path)
        if frame is None:
            continue
        key = _stream_key(path)
        stream = _expected_stream(streams, key) if key is not None else None
        stream_tokens = (
            set(str(value) for value in stream["token_id"].to_list())
            if stream is not None
            else set()
        )
        verse_tokens: set[str] | None = None
        if key is not None and (verse_path := verse_paths.get(key)) is not None:
            verse_frame = _read_leaf(state, "passage_membership", verse_path)
            if verse_frame is not None:
                verse_tokens = set(str(value) for value in verse_frame["token_id"].to_list())
        observed_clause: set[str] = set()
        for row in frame.iter_rows(named=True):
            try:
                model = SegmentationExclusionRow.model_validate(row)
            except ValidationError as exc:
                state.add("exclusion-row", str(exc), table="segmentation_exclusions")
                continue
            if stream is not None and model.token_id not in stream_tokens:
                state.add(
                    "exclusion-token-outside-stream",
                    "excluded token is absent from the selected analysis stream",
                    token_id=model.token_id,
                )
            if verse_tokens is not None and model.token_id not in verse_tokens:
                state.add(
                    "silent-token-loss",
                    "excluded token is absent from verse analysis",
                    token_id=model.token_id,
                )
            related_ids = _json_strings(model.related_passage_ids_json)
            for passage_id in related_ids:
                related_counts[passage_id] = related_counts.get(passage_id, 0) + 1
                fact = semantic_index.exclusion_facts.get(passage_id)
                if passage_id not in semantic_index.passage_ids:
                    state.add(
                        "exclusion-related-passage",
                        "exclusion references an unknown passage",
                        token_id=model.token_id,
                    )
                elif model.reason_code == "ketiv_clause_mapping_unresolved" and (
                    fact is None or not fact.uncertainty
                ):
                    state.add(
                        "exclusion-uncertainty",
                        "related Ketiv passage is not marked uncertain",
                        passage_id=passage_id,
                        token_id=model.token_id,
                    )
            if model.granularity == "clause":
                observed_clause.add(model.token_id)

        if key is not None and key in clause_contexts and stream is not None:
            expected = set(
                str(value)
                for value in stream.filter(pl.col("analysis_clause_id").is_null())[
                    "token_id"
                ].to_list()
            )
            if observed_clause != expected:
                state.add(
                    "clause-exclusion-coverage",
                    "clause exclusions differ from unresolved stream tokens",
                    path=path.relative_to(state.output_dir).as_posix(),
                )

    expected_counts = {
        passage_id: fact.exclusion_count
        for passage_id, fact in semantic_index.exclusion_facts.items()
        if fact.exclusion_count
    }
    for passage_id in set(expected_counts) | set(related_counts):
        if expected_counts.get(passage_id, 0) != related_counts.get(passage_id, 0):
            state.add(
                "passage-exclusion-count",
                "passage sensitivity exclusion count differs from exclusion rows",
                passage_id=passage_id,
            )


def _input_digest_set(inputs: SegmentationInputs) -> dict[str, object]:
    return {
        "hebrew_identity": corpus_identity_digest(inputs.hebrew_tokens),
        "hebrew_content": corpus_content_digest(inputs.hebrew_tokens),
        "hebrew_analytical": corpus_analytical_digest(inputs.hebrew_tokens),
        "greek_identity": corpus_identity_digest(inputs.greek_tokens),
        "greek_content": corpus_content_digest(inputs.greek_tokens),
        "greek_analytical": corpus_analytical_digest(inputs.greek_tokens),
        "oshb_logical": {
            "ketiv_tokens": logical_frame_hash(
                inputs.ketiv_tokens, sort_by=KQ_SORT_COLUMNS["ketiv_tokens"]
            ),
            "locus_registry": logical_frame_hash(
                inputs.locus_registry, sort_by=KQ_SORT_COLUMNS["locus_registry"]
            ),
            "structural_alignments": logical_frame_hash(
                inputs.structural_alignments, sort_by=KQ_SORT_COLUMNS["structural_alignments"]
            ),
        },
    }


def _validate_inputs(state: _State, inputs: SegmentationInputs) -> tuple[pl.DataFrame, ...]:
    snapshots = tuple(
        frame.clone()
        for frame in (
            inputs.hebrew_tokens,
            inputs.greek_tokens,
            inputs.ketiv_tokens,
            inputs.locus_registry,
            inputs.structural_alignments,
        )
    )
    observed = _input_digest_set(inputs)
    expected = inputs.digests.as_dict()
    if observed != expected:
        state.add("input-digest-anchor", "current inputs differ from pinned segmentation anchors")
    return snapshots


def _validate_inputs_after(
    state: _State, inputs: SegmentationInputs, snapshots: tuple[pl.DataFrame, ...]
) -> None:
    current = (
        inputs.hebrew_tokens,
        inputs.greek_tokens,
        inputs.ketiv_tokens,
        inputs.locus_registry,
        inputs.structural_alignments,
    )
    if any(not frame.equals(snapshot) for frame, snapshot in zip(current, snapshots, strict=True)):
        state.add("source-mutation", "validation or generation mutated an immutable source frame")
    if _input_digest_set(inputs) != inputs.digests.as_dict():
        state.add("input-digest-after", "input anchors differ after validation")


def _validate_metadata(
    state: _State,
    manifest: Mapping[str, object],
    *,
    config: SegmentationConfig | None,
    inputs: SegmentationInputs | None,
) -> None:
    paths = _artifact_paths(state.output_dir, "segmentation_metadata")
    if len(paths) != 1:
        state.add("metadata-cardinality", f"expected one metadata leaf, found {len(paths)}")
        return
    frame = _read_leaf(state, "segmentation_metadata", paths[0])
    if frame is None or frame.height != 1:
        state.add("metadata-cardinality", "metadata table must contain one row")
        return
    try:
        metadata = SegmentationMetadataRow.model_validate(frame.row(0, named=True))
    except ValidationError as exc:
        state.add("metadata-row", str(exc), table="segmentation_metadata")
        return
    if state.run_id is None:
        state.run_id = metadata.segmentation_run_id
    elif state.run_id != metadata.segmentation_run_id:
        state.add("metadata-run-id", "metadata and passage run IDs differ")
    comparisons = (
        ("table_counts_json", _int_mapping(manifest.get("table_counts"))),
        ("table_logical_hashes_json", _string_mapping(manifest.get("table_logical_sha256"))),
        ("table_physical_hashes_json", _string_mapping(manifest.get("table_physical_sha256"))),
    )
    for field, manifest_values in comparisons:
        recorded = _json_object(cast(str, getattr(metadata, field)))
        for key, value in recorded.items():
            if manifest_values.get(key) != value:
                state.add("metadata-manifest-mismatch", f"{field} differs for {key}")
    if config is not None:
        expected_config_hash, _ = segmentation_config_fingerprint(config)
        if metadata.segmentation_config_hash != expected_config_hash:
            state.add("metadata-config-hash", "metadata configuration hash differs")
    if inputs is not None:
        expected_objects: dict[str, dict[str, object]] = {
            "input_source_versions_json": dict(inputs.source_versions),
            "input_primary_identity_digests_json": {
                "hebrew": inputs.digests.hebrew_identity,
                "greek": inputs.digests.greek_identity,
            },
            "input_surface_lemma_digests_json": {
                "hebrew": inputs.digests.hebrew_content,
                "greek": inputs.digests.greek_content,
            },
            "input_analytical_digests_json": {
                "hebrew": inputs.digests.hebrew_analytical,
                "greek": inputs.digests.greek_analytical,
            },
            "input_oshb_supplement_digests_json": dict(inputs.digests.oshb_logical),
        }
        for field, expected in expected_objects.items():
            if _json_object(cast(str, getattr(metadata, field))) != expected:
                state.add("metadata-input-anchor", f"metadata {field} differs")


def _validate_persisted_issues(state: _State) -> None:
    for path in _artifact_paths(state.output_dir, "segmentation_issues"):
        frame = _read_leaf(state, "segmentation_issues", path)
        if frame is None:
            continue
        for row in frame.iter_rows(named=True):
            try:
                model = SegmentationIssueRow.model_validate(row)
            except ValidationError as exc:
                state.add("issue-row", str(exc), table="segmentation_issues")
                continue
            state.add(
                f"persisted-{model.code}",
                model.message,
                severity=model.severity.value,
                table="segmentation_issues",
                passage_id=model.passage_id,
                token_id=model.token_id,
            )


def _validate_duckdb(state: _State, database_path: Path) -> None:
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
            for table in ARTIFACT_NAMES:
                if table not in tables:
                    state.add("duckdb-table-missing", f"DuckDB lacks {table}", table=table)
                    continue
                row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
                count = int(row[0]) if row is not None else -1
                if count != state.table_counts.get(table):
                    state.add(
                        "duckdb-count-mismatch", "DuckDB and Parquet counts differ", table=table
                    )
            duplicate = connection.execute(
                "SELECT count(*) - count(DISTINCT passage_id) FROM passages"
            ).fetchone()
            if duplicate is not None and int(duplicate[0]):
                state.add("duckdb-duplicate-passage", "DuckDB passage IDs are not unique")
    except (duckdb.Error, OSError) as exc:
        state.add("duckdb-unavailable", str(exc))


def validate_passage_artifacts(
    output_dir: Path,
    *,
    database_path: Path | None = None,
    config: SegmentationConfig | None = None,
    inputs: SegmentationInputs | None = None,
    strict: bool = False,
) -> PassageValidationReport:
    """Validate persisted passage artifacts without loading global membership."""

    resolved = output_dir.resolve(strict=False)
    state = _State(resolved, strict, [], {}, {}, {})
    snapshots = _validate_inputs(state, inputs) if inputs is not None else None
    manifest = _audit_storage(state)
    passage_paths = _artifact_paths(state.output_dir, "passages")
    exclusion_paths = _artifact_paths(state.output_dir, "segmentation_exclusions")
    seen_passage_ids: set[str] = set()
    if config is not None and inputs is not None:
        stream_keys = sorted(
            {key[:3] for path in passage_paths if (key := _stream_key(path)) is not None}
        )
        greek_heights: dict[str, int] = {}
        for corpus, profile, reading in stream_keys:
            matching_passages = [
                path
                for path in passage_paths
                if (key := _stream_key(path)) is not None and key[:3] == (corpus, profile, reading)
            ]
            matching_exclusions = [
                path
                for path in exclusion_paths
                if (key := _stream_key(path)) is not None and key[:3] == (corpus, profile, reading)
            ]
            streams: dict[tuple[str, str, str], pl.DataFrame] = {}
            try:
                stream = build_analysis_stream(
                    inputs,
                    config=config,
                    corpus=cast(Literal["hebrew", "greek"], corpus),
                    profile=cast(Literal["edition_complete", "critical_core"], profile),
                    reading=cast(Literal["qere", "ketiv", "source"], reading),
                )
            except (ValueError, RuntimeError, pl.exceptions.PolarsError) as exc:
                state.add("stream-rebuild", str(exc))
            else:
                streams[(corpus, profile, reading)] = stream
                if corpus == "greek" and reading == "source":
                    greek_heights[profile] = stream.height
            semantic_index = _validate_semantics(
                state,
                config,
                streams,
                passage_paths=matching_passages,
                seen_passage_ids=seen_passage_ids,
            )
            _validate_exclusions(
                state,
                streams,
                semantic_index,
                exclusion_paths=matching_exclusions,
            )
        if (
            greek_heights.get("edition_complete", 0) >= 100_000
            and "critical_core" in greek_heights
            and greek_heights["edition_complete"] - greek_heights["critical_core"] != 390
        ):
            state.add(
                "critical-core-token-count",
                "critical-core must exclude exactly 390 Greek tokens",
            )
    else:
        semantic_index = _validate_semantics(
            state,
            config,
            {},
            passage_paths=passage_paths,
            seen_passage_ids=seen_passage_ids,
        )
        _validate_exclusions(
            state,
            {},
            semantic_index,
            exclusion_paths=exclusion_paths,
        )
    if manifest is not None:
        _validate_metadata(state, manifest, config=config, inputs=inputs)
        _validate_persisted_issues(state)
    if database_path is not None:
        _validate_duckdb(state, database_path)
    if inputs is not None and snapshots is not None:
        _validate_inputs_after(state, inputs, snapshots)
    errors = sum(issue.severity == "error" for issue in state.findings)
    warnings = sum(issue.severity == "warning" for issue in state.findings)
    passed = errors == 0 and (not strict or warnings == 0)
    return PassageValidationReport(
        output_dir=str(resolved),
        strict=strict,
        passed=passed,
        segmentation_run_id=state.run_id,
        table_counts=state.table_counts,
        table_logical_hashes=state.table_logical_hashes,
        table_physical_hashes=state.table_physical_hashes,
        issues=state.findings,
    )
