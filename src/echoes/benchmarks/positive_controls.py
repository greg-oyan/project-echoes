"""Standalone, reference-only positive controls for post-M7 detector evaluation.

This module deliberately does not reuse or mutate the historical Tier 1
placeholder or the OpenBible Tier 3 pipeline.  The tracked dataset is a small
CC BY-SA reference-only adaptation of a pinned UBS Parallel Passages snapshot.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.corpus.books import BOOKS
from echoes.corpus.greek_books import GREEK_BOOKS

POSITIVE_CONTROL_SCHEMA_VERSION = 1
POSITIVE_CONTROL_COLUMNS: tuple[str, ...] = (
    "control_id",
    "reference_a",
    "reference_b",
    "corpus_pair",
    "relationship_class",
    "source_tradition",
    "quotation_formula_status",
    "source_id",
    "source_version",
    "source_file",
    "source_file_sha256",
    "source_record_locator",
    "source_license",
    "relationship_family_id",
    "leakage_group_id",
    "split",
    "verification_status",
    "verification_method",
    "verified_by",
    "verified_at",
    "notes",
)

CorpusPair = Literal["hebrew_hebrew", "greek_greek", "hebrew_greek"]
RelationshipClass = Literal[
    "hebrew_parallel",
    "greek_parallel",
    "cross_corpus_parallel",
]
SourceTradition = Literal["hebrew", "greek", "hebrew_greek_cross_tradition"]
SplitPartition = Literal["train", "development", "test"]

_SHA256_PATTERN = r"^[a-f0-9]{64}$"
_COMMIT_PATTERN = r"^[a-f0-9]{40}$"
_CONTROL_ID_PATTERN = r"^PC_[a-f0-9]{64}$"
_GROUP_ID_PATTERN = r"^PC[FL]_[A-Z0-9]+(?:_[A-Z0-9]+)*$"
_LOCATOR_PATTERN = r"^Passages/Passage\[[1-9][0-9]*\]/Verse\[[1-9][0-9]*,[1-9][0-9]*\]$"
_REFERENCE_RE = re.compile(
    r"^(?P<book>[1-3]?[A-Z]{2,3}) (?P<chapter>[1-9][0-9]*):"
    r"(?P<verse>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?$"
)
_HEBREW_BOOKS = {book.code: book for book in BOOKS}
_GREEK_BOOKS = {book.code: book for book in GREEK_BOOKS}
_BOOK_ORDER = {
    **{book.code: book.order for book in BOOKS},
    **{book.code: len(BOOKS) + book.order for book in GREEK_BOOKS},
}


class PositiveControlError(ValueError):
    """Raised when positive-control configuration or data is not governed."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class PositiveControlSourceConfig(_StrictModel):
    """Pinned upstream identity and the license carried by every row."""

    source_id: Literal["ubs-parallel-passages"]
    repository_url: Literal["https://github.com/ubsicap/ubs-open-license"]
    source_version: str = Field(pattern=_COMMIT_PATTERN)
    source_file: Literal["parallel passages/ParallelPassages.xml"]
    source_file_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_reference_scheme: Literal["ubs-paratext-canonical-v1"]
    license: Literal["CC BY-SA 4.0"]
    license_url: Literal["https://creativecommons.org/licenses/by-sa/4.0/"]
    attribution: str = Field(min_length=1)


class PositiveControlDatasetConfig(_StrictModel):
    """Frozen tracked-data identity and bounded scope."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    expected_row_count: int = Field(ge=1, le=100)
    expected_relationship_family_count: int = Field(ge=3)
    expected_leakage_group_count: int = Field(ge=3)
    reference_only: Literal[True]
    modification_statement: str = Field(min_length=1)

    @model_validator(mode="after")
    def path_is_safe_and_relative(self) -> Self:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".csv":
            raise ValueError("positive-control data path must be a safe relative CSV path")
        return self


class PositiveControlSelectionConfig(_StrictModel):
    """Required diversity dimensions for the bounded benchmark."""

    required_corpus_pairs: tuple[CorpusPair, ...]
    required_relationship_classes: tuple[RelationshipClass, ...]
    quotation_formula_policy: Literal["record_not_assessed_without_independent_evidence"]

    @model_validator(mode="after")
    def dimensions_are_complete_and_unique(self) -> Self:
        if set(self.required_corpus_pairs) != {
            "hebrew_hebrew",
            "greek_greek",
            "hebrew_greek",
        }:
            raise ValueError("all three governed corpus-pair strata are required")
        if set(self.required_relationship_classes) != {
            "hebrew_parallel",
            "greek_parallel",
            "cross_corpus_parallel",
        }:
            raise ValueError("all three governed positive-control classes are required")
        if len(self.required_corpus_pairs) != len(set(self.required_corpus_pairs)):
            raise ValueError("required corpus-pair strata must be unique")
        if len(self.required_relationship_classes) != len(set(self.required_relationship_classes)):
            raise ValueError("required relationship classes must be unique")
        return self


class PositiveControlVerificationConfig(_StrictModel):
    """Honest preproduction verification boundary."""

    required_status: Literal["verified_against_pinned_source"]
    required_method: Literal["manual_reference_and_source_record_check"]
    allowed_verifiers: tuple[str, ...] = Field(min_length=1)
    independent_human_review_required: Literal[False]

    @model_validator(mode="after")
    def verifier_ids_are_unique(self) -> Self:
        if len(self.allowed_verifiers) != len(set(self.allowed_verifiers)):
            raise ValueError("allowed positive-control verifier IDs must be unique")
        if any(not value or value.strip() != value for value in self.allowed_verifiers):
            raise ValueError("verifier IDs must be nonempty and whitespace-normalized")
        return self


class PositiveControlSplitWeights(_StrictModel):
    train: int = Field(ge=1)
    development: int = Field(ge=1)
    test: int = Field(ge=1)


class PositiveControlSplitConfig(_StrictModel):
    """Deterministic leakage-group split policy; rows are never randomized."""

    algorithm: Literal["sha256_ordered_weighted_cycle_v1"]
    seed: int = Field(ge=0)
    partition_unit: Literal["leakage_group"]
    random_row_splitting_allowed: Literal[False]
    weights: PositiveControlSplitWeights


class PositiveControlConfig(_StrictModel):
    """Complete configuration for one immutable positive-control CSV."""

    schema_version: Literal[1]
    benchmark_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    source: PositiveControlSourceConfig
    dataset: PositiveControlDatasetConfig
    selection: PositiveControlSelectionConfig
    verification: PositiveControlVerificationConfig
    splits: PositiveControlSplitConfig

    @model_validator(mode="after")
    def enough_groups_exist_for_every_partition(self) -> Self:
        cycle_size = sum(self.splits.weights.model_dump().values())
        if self.dataset.expected_leakage_group_count < cycle_size:
            raise ValueError("expected leakage groups must cover one complete split cycle")
        return self


class PositiveControlRow(_StrictModel):
    """One manually checked, reference-only positive-control pair."""

    control_id: str = Field(pattern=_CONTROL_ID_PATTERN)
    reference_a: str = Field(min_length=1)
    reference_b: str = Field(min_length=1)
    corpus_pair: CorpusPair
    relationship_class: RelationshipClass
    source_tradition: SourceTradition
    quotation_formula_status: Literal["not_assessed"]
    source_id: str = Field(min_length=1)
    source_version: str = Field(pattern=_COMMIT_PATTERN)
    source_file: str = Field(min_length=1)
    source_file_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_record_locator: str = Field(pattern=_LOCATOR_PATTERN)
    source_license: Literal["CC BY-SA 4.0"]
    relationship_family_id: str = Field(pattern=_GROUP_ID_PATTERN)
    leakage_group_id: str = Field(pattern=_GROUP_ID_PATTERN)
    split: SplitPartition
    verification_status: Literal["verified_against_pinned_source"]
    verification_method: Literal["manual_reference_and_source_record_check"]
    verified_by: str = Field(min_length=1)
    verified_at: date
    notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def strings_are_whitespace_normalized(self) -> Self:
        for name, value in self.model_dump(mode="python").items():
            if isinstance(value, str) and value.strip() != value:
                raise ValueError(f"{name} must not have leading or trailing whitespace")
        return self


class PositiveControlValidationResult(_StrictModel):
    """Machine-readable validation receipt for the tracked benchmark."""

    schema_version: Literal[1] = 1
    benchmark_id: str
    config_path: str
    config_sha256: str = Field(pattern=_SHA256_PATTERN)
    data_path: str
    data_sha256: str = Field(pattern=_SHA256_PATTERN)
    row_count: int = Field(ge=1)
    relationship_family_count: int = Field(ge=1)
    leakage_group_count: int = Field(ge=1)
    partition_counts: dict[SplitPartition, int]
    source_id: str
    source_version: str = Field(pattern=_COMMIT_PATTERN)
    source_file_sha256: str = Field(pattern=_SHA256_PATTERN)
    reference_only: Literal[True] = True
    independent_human_review_required: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PositiveControlDataset:
    """Validated config, rows, and their authentication receipt."""

    config: PositiveControlConfig
    rows: tuple[PositiveControlRow, ...]
    validation: PositiveControlValidationResult


@dataclass(frozen=True, slots=True)
class _Reference:
    book: str
    chapter: int
    verse: int
    end_verse: int
    corpus: Literal["hebrew", "greek"]

    @property
    def sort_key(self) -> tuple[int, int, int, int]:
        return (_BOOK_ORDER[self.book], self.chapter, self.verse, self.end_verse)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_yaml(path: Path) -> tuple[dict[str, object], str]:
    if not path.is_file():
        raise PositiveControlError(f"positive-control config does not exist: {path}")
    try:
        raw = path.read_bytes()
        loaded = yaml.safe_load(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PositiveControlError(f"could not read positive-control config {path}: {exc}") from exc
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise PositiveControlError("positive-control config root must be a string-keyed mapping")
    return cast(dict[str, object], loaded), _sha256_bytes(raw)


def load_positive_control_config(path: Path) -> PositiveControlConfig:
    """Load and strictly validate the standalone positive-control config."""

    values, _digest = _load_yaml(path)
    try:
        return PositiveControlConfig.model_validate(values)
    except ValidationError as exc:
        raise PositiveControlError(f"invalid positive-control config {path}:\n{exc}") from exc


def _parse_reference(value: str) -> _Reference:
    match = _REFERENCE_RE.fullmatch(value)
    if match is None:
        raise PositiveControlError(
            f"invalid positive-control reference {value!r}; expected BOOK chapter:verse[-verse]"
        )
    book_code = match.group("book")
    hebrew_book = _HEBREW_BOOKS.get(book_code)
    corpus: Literal["hebrew", "greek"]
    if hebrew_book is not None:
        corpus = "hebrew"
        chapter_count = hebrew_book.chapter_count
    else:
        greek_book = _GREEK_BOOKS.get(book_code)
        if greek_book is None:
            raise PositiveControlError(f"unknown positive-control book code: {book_code}")
        corpus = "greek"
        chapter_count = greek_book.chapter_count
    chapter = int(match.group("chapter"))
    verse = int(match.group("verse"))
    end_verse = int(match.group("end") or verse)
    if chapter > chapter_count:
        raise PositiveControlError(
            f"positive-control chapter exceeds {book_code} chapter count: {value}"
        )
    if end_verse < verse:
        raise PositiveControlError(f"positive-control range runs backward: {value}")
    return _Reference(book_code, chapter, verse, end_verse, corpus)


def build_positive_control_id(
    *,
    benchmark_id: str,
    source_reference_scheme: str,
    reference_a: str,
    reference_b: str,
) -> str:
    """Build a stable unordered pair ID independent of row order and split."""

    endpoints = sorted((reference_a, reference_b))
    payload = json.dumps(
        {
            "benchmark_id": benchmark_id,
            "reference_a": endpoints[0],
            "reference_b": endpoints[1],
            "schema_version": POSITIVE_CONTROL_SCHEMA_VERSION,
            "source_reference_scheme": source_reference_scheme,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"PC_{_sha256_bytes(payload.encode('utf-8'))}"


def deterministic_leakage_group_splits(
    leakage_group_ids: set[str] | frozenset[str],
    *,
    benchmark_id: str,
    split_config: PositiveControlSplitConfig,
) -> dict[str, SplitPartition]:
    """Assign whole leakage groups by a stable hash-ordered weighted cycle."""

    if not leakage_group_ids:
        raise PositiveControlError("positive-control split requires leakage groups")
    weights = split_config.weights
    cycle = cast(
        tuple[SplitPartition, ...],
        ("train",) * weights.train
        + ("development",) * weights.development
        + ("test",) * weights.test,
    )

    def digest(group_id: str) -> str:
        payload = f"{benchmark_id}\x00{split_config.seed}\x00{group_id}".encode()
        return _sha256_bytes(payload)

    ordered = sorted(leakage_group_ids, key=lambda value: (digest(value), value))
    return {group_id: cycle[index % len(cycle)] for index, group_id in enumerate(ordered)}


def _read_rows(path: Path) -> tuple[tuple[PositiveControlRow, ...], str]:
    if not path.is_file():
        raise PositiveControlError(f"positive-control CSV does not exist: {path}")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise PositiveControlError(f"could not read positive-control CSV {path}: {exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise PositiveControlError(
            "positive-control CSV must be UTF-8 without BOM, LF-only, final LF"
        )
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != POSITIVE_CONTROL_COLUMNS:
            raise PositiveControlError(
                "positive-control CSV columns or column order differ from schema version 1"
            )
        raw_rows = list(reader)
    except csv.Error as exc:
        raise PositiveControlError(f"invalid positive-control CSV syntax: {exc}") from exc
    if any(None in row for row in raw_rows):
        raise PositiveControlError("positive-control CSV row has more values than the schema")
    try:
        rows = tuple(PositiveControlRow.model_validate(row) for row in raw_rows)
    except ValidationError as exc:
        raise PositiveControlError(f"invalid positive-control row:\n{exc}") from exc
    return rows, _sha256_bytes(raw)


def _validate_rows(rows: tuple[PositiveControlRow, ...], config: PositiveControlConfig) -> None:
    if len(rows) != config.dataset.expected_row_count:
        raise PositiveControlError(
            "positive-control row count differs from config: "
            f"expected={config.dataset.expected_row_count}, actual={len(rows)}"
        )
    ids = Counter(row.control_id for row in rows)
    duplicate_ids = sorted(value for value, count in ids.items() if count > 1)
    if duplicate_ids:
        raise PositiveControlError(f"duplicate positive-control IDs: {duplicate_ids}")

    pairs: dict[tuple[str, str], str] = {}
    family_groups: dict[str, set[str]] = defaultdict(set)
    endpoint_groups: dict[str, set[str]] = defaultdict(set)
    group_splits: dict[str, set[SplitPartition]] = defaultdict(set)
    for row in rows:
        reference_a = _parse_reference(row.reference_a)
        reference_b = _parse_reference(row.reference_b)
        if reference_a.sort_key >= reference_b.sort_key:
            raise PositiveControlError(
                f"positive-control endpoints are not in canonical order: {row.control_id}"
            )
        pair = (row.reference_a, row.reference_b)
        if pair in pairs:
            raise PositiveControlError(
                f"duplicate unordered positive-control pair: {pairs[pair]}, {row.control_id}"
            )
        pairs[pair] = row.control_id
        expected_id = build_positive_control_id(
            benchmark_id=config.benchmark_id,
            source_reference_scheme=config.source.source_reference_scheme,
            reference_a=row.reference_a,
            reference_b=row.reference_b,
        )
        if row.control_id != expected_id:
            raise PositiveControlError(f"content-derived control_id mismatch: {row.control_id}")

        expected_pair: CorpusPair
        if reference_a.corpus == reference_b.corpus == "hebrew":
            expected_pair = "hebrew_hebrew"
        elif reference_a.corpus == reference_b.corpus == "greek":
            expected_pair = "greek_greek"
        else:
            expected_pair = "hebrew_greek"
        expected_classes: dict[CorpusPair, tuple[RelationshipClass, SourceTradition]] = {
            "hebrew_hebrew": ("hebrew_parallel", "hebrew"),
            "greek_greek": ("greek_parallel", "greek"),
            "hebrew_greek": ("cross_corpus_parallel", "hebrew_greek_cross_tradition"),
        }
        expected_class, expected_tradition = expected_classes[expected_pair]
        if (row.corpus_pair, row.relationship_class, row.source_tradition) != (
            expected_pair,
            expected_class,
            expected_tradition,
        ):
            raise PositiveControlError(
                f"corpus/class/tradition mismatch for positive control {row.control_id}"
            )
        if (
            row.source_id != config.source.source_id
            or row.source_version != config.source.source_version
            or row.source_file != config.source.source_file
            or row.source_file_sha256 != config.source.source_file_sha256
            or row.source_license != config.source.license
        ):
            raise PositiveControlError(
                f"row-level source provenance differs from config: {row.control_id}"
            )
        if (
            row.verification_status != config.verification.required_status
            or row.verification_method != config.verification.required_method
            or row.verified_by not in config.verification.allowed_verifiers
        ):
            raise PositiveControlError(f"row lacks governed manual verification: {row.control_id}")
        family_groups[row.relationship_family_id].add(row.leakage_group_id)
        endpoint_groups[row.reference_a].add(row.leakage_group_id)
        endpoint_groups[row.reference_b].add(row.leakage_group_id)
        group_splits[row.leakage_group_id].add(row.split)

    leaking_families = sorted(key for key, values in family_groups.items() if len(values) != 1)
    if leaking_families:
        raise PositiveControlError(
            f"relationship families cross leakage groups: {leaking_families}"
        )
    leaking_endpoints = sorted(key for key, values in endpoint_groups.items() if len(values) != 1)
    if leaking_endpoints:
        raise PositiveControlError(
            f"references cross positive-control leakage groups: {leaking_endpoints}"
        )
    split_groups = sorted(key for key, values in group_splits.items() if len(values) != 1)
    if split_groups:
        raise PositiveControlError(f"leakage groups cross split partitions: {split_groups}")

    families = set(family_groups)
    groups = set(group_splits)
    if len(families) != config.dataset.expected_relationship_family_count:
        raise PositiveControlError("positive-control relationship-family count differs from config")
    if len(groups) != config.dataset.expected_leakage_group_count:
        raise PositiveControlError("positive-control leakage-group count differs from config")
    expected_splits = deterministic_leakage_group_splits(
        groups,
        benchmark_id=config.benchmark_id,
        split_config=config.splits,
    )
    mismatches = sorted(
        row.control_id for row in rows if row.split != expected_splits[row.leakage_group_id]
    )
    if mismatches:
        raise PositiveControlError(
            f"positive-control split assignments are not frozen: {mismatches}"
        )
    if set(row.split for row in rows) != {"train", "development", "test"}:
        raise PositiveControlError("positive controls must populate train, development, and test")
    if set(row.corpus_pair for row in rows) != set(config.selection.required_corpus_pairs):
        raise PositiveControlError("positive controls do not cover all required corpus-pair strata")
    if set(row.relationship_class for row in rows) != set(
        config.selection.required_relationship_classes
    ):
        raise PositiveControlError("positive controls do not cover all required classes")


def validate_positive_controls(
    config_path: Path,
    *,
    data_path: Path | None = None,
) -> PositiveControlDataset:
    """Validate the pinned config, exact CSV bytes, provenance, leakage, and splits."""

    values, config_sha256 = _load_yaml(config_path)
    try:
        config = PositiveControlConfig.model_validate(values)
    except ValidationError as exc:
        raise PositiveControlError(
            f"invalid positive-control config {config_path}:\n{exc}"
        ) from exc
    resolved_data_path = data_path or Path(config.dataset.path)
    rows, data_sha256 = _read_rows(resolved_data_path)
    if data_sha256 != config.dataset.sha256:
        raise PositiveControlError(
            "positive-control CSV hash differs from config: "
            f"expected={config.dataset.sha256}, actual={data_sha256}"
        )
    _validate_rows(rows, config)
    partition_counts = Counter(row.split for row in rows)
    validation = PositiveControlValidationResult(
        benchmark_id=config.benchmark_id,
        config_path=config_path.as_posix(),
        config_sha256=config_sha256,
        data_path=resolved_data_path.as_posix(),
        data_sha256=data_sha256,
        row_count=len(rows),
        relationship_family_count=len({row.relationship_family_id for row in rows}),
        leakage_group_count=len({row.leakage_group_id for row in rows}),
        partition_counts={
            "train": partition_counts["train"],
            "development": partition_counts["development"],
            "test": partition_counts["test"],
        },
        source_id=config.source.source_id,
        source_version=config.source.source_version,
        source_file_sha256=config.source.source_file_sha256,
    )
    return PositiveControlDataset(config=config, rows=rows, validation=validation)
