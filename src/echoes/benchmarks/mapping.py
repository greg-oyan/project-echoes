"""Conservative OpenBible-reference mapping to governed Milestone 5 verse passages."""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal

import duckdb

from echoes.benchmarks.identity import MappingIdentityPayload, build_mapping_identity
from echoes.benchmarks.models import (
    BenchmarkEndpointMappingRow,
    BenchmarkEndpointRow,
    MappingStatus,
)
from echoes.benchmarks.references import (
    GREEK_BOOKS,
    HEBREW_BOOKS,
    openbible_reference_corpus,
)


class BenchmarkMappingError(ValueError):
    """Raised when passage inputs or endpoint coordinates violate the mapping contract."""


@dataclass(frozen=True, slots=True)
class PassageTarget:
    """Slim verse target; biblical text is deliberately absent."""

    passage_id: str
    corpus: Literal["hebrew", "greek"]
    analysis_profile: Literal["edition_complete", "critical_core"]
    analysis_reading: Literal["qere", "source"]
    book: str
    chapter: int
    verse: int
    reference: str
    token_count: int
    disputed_passage_flag: bool
    disputed_passage_ids: tuple[str, ...]
    reference_gap: bool


@dataclass(frozen=True, slots=True)
class MappingRisk:
    """Sanitized versification or profile risk for tracked reports."""

    endpoint_id: str
    source_reference: str
    book: str | None
    target_profile: str
    mapping_status: str
    reason: str


@dataclass(frozen=True, slots=True)
class MappingBuildResult:
    """Mappings and a compact, reference-only risk inventory."""

    mappings: tuple[BenchmarkEndpointMappingRow, ...]
    risks: tuple[MappingRisk, ...]


class PassageReferenceIndex:
    """A small exact-reference index over the governed verse layers."""

    def __init__(self, targets: Iterable[PassageTarget]) -> None:
        self.by_key: dict[tuple[str, str, str, str, int, int], PassageTarget] = {}
        self.by_stream: dict[tuple[str, str, str, str], list[PassageTarget]] = {}
        self.by_stream_coordinates: dict[tuple[str, str, str, str], list[tuple[int, int]]] = {}
        for target in targets:
            key = (
                target.corpus,
                target.analysis_profile,
                target.analysis_reading,
                target.book,
                target.chapter,
                target.verse,
            )
            if key in self.by_key:
                raise BenchmarkMappingError(f"duplicate passage reference target: {key}")
            self.by_key[key] = target
            stream = (
                target.corpus,
                target.analysis_profile,
                target.analysis_reading,
                target.book,
            )
            self.by_stream.setdefault(stream, []).append(target)
        for values in self.by_stream.values():
            values.sort(key=lambda item: (item.chapter, item.verse, item.passage_id))
        self.by_stream_coordinates = {
            stream: [(target.chapter, target.verse) for target in values]
            for stream, values in self.by_stream.items()
        }

    @classmethod
    def from_duckdb(cls, database_path: Path) -> PassageReferenceIndex:
        """Load only verse identity/flag columns, never corpus text or memberships."""

        sql = """
            SELECT passage_id, corpus, analysis_profile, analysis_reading, book,
                   start_reference, token_count, disputed_passage_flag,
                   disputed_passage_ids_json, reference_gap
            FROM passages
            WHERE granularity='verse'
              AND ((corpus='hebrew' AND analysis_reading='qere')
                   OR (corpus='greek' AND analysis_reading='source'))
              AND analysis_profile IN ('edition_complete','critical_core')
            ORDER BY corpus,analysis_profile,analysis_reading,book_order,
                     start_stream_position_in_corpus,passage_id
        """
        try:
            with duckdb.connect(str(database_path), read_only=True) as connection:
                rows = connection.execute(sql).fetchall()
        except Exception as exc:
            raise BenchmarkMappingError(f"could not read governed passage targets: {exc}") from exc
        targets: list[PassageTarget] = []
        for row in rows:
            reference = str(row[5])
            try:
                _, coordinate = reference.split(" ", maxsplit=1)
                chapter_text, verse_text = coordinate.split(":", maxsplit=1)
                disputed = json.loads(str(row[8]))
            except (ValueError, json.JSONDecodeError) as exc:
                raise BenchmarkMappingError(
                    f"invalid passage target reference {reference!r}"
                ) from exc
            if not isinstance(disputed, list) or not all(
                isinstance(item, str) for item in disputed
            ):
                raise BenchmarkMappingError(f"invalid disputed passage IDs for {reference}")
            targets.append(
                PassageTarget(
                    passage_id=str(row[0]),
                    corpus=row[1],
                    analysis_profile=row[2],
                    analysis_reading=row[3],
                    book=str(row[4]),
                    chapter=int(chapter_text),
                    verse=int(verse_text),
                    reference=reference,
                    token_count=int(row[6]),
                    disputed_passage_flag=bool(row[7]),
                    disputed_passage_ids=tuple(disputed),
                    reference_gap=bool(row[9]),
                )
            )
        if not targets:
            raise BenchmarkMappingError("governed passage database contains no verse targets")
        return cls(targets)

    def span(
        self,
        *,
        corpus: str,
        profile: str,
        reading: str,
        book: str,
        start_chapter: int,
        start_verse: int,
        end_chapter: int,
        end_verse: int,
    ) -> list[PassageTarget]:
        stream = self.by_stream.get((corpus, profile, reading, book), [])
        coordinates = self.by_stream_coordinates.get((corpus, profile, reading, book), [])
        start = (start_chapter, start_verse)
        end = (end_chapter, end_verse)
        left = bisect_left(coordinates, start)
        right = bisect_right(coordinates, end)
        return stream[left:right]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _target_stream(book: str) -> tuple[Literal["hebrew", "greek"], Literal["qere", "source"]]:
    if book in HEBREW_BOOKS:
        return "hebrew", "qere"
    if book in GREEK_BOOKS:
        return "greek", "source"
    raise BenchmarkMappingError(f"unknown canonical target book: {book}")


def _numeric_gaps(targets: list[PassageTarget]) -> bool:
    for previous, current in pairwise(targets):
        if previous.chapter == current.chapter:
            if current.verse != previous.verse + 1:
                return True
        elif current.chapter != previous.chapter + 1 or current.verse != 1:
            return True
    return False


def _targets_cover_endpoint(
    endpoint: BenchmarkEndpointRow,
    targets: list[PassageTarget],
    edition_targets: list[PassageTarget],
) -> bool:
    """Recognize an exact extant span without assuming one chapter's verse count."""

    if not targets:
        return False
    if not endpoint.is_range:
        return (
            len(targets) == 1
            and targets[0].chapter == endpoint.parsed_start_chapter
            and targets[0].verse == endpoint.parsed_start_verse
        )
    if not edition_targets:
        return False
    same_as_edition = tuple(target.reference for target in targets) == tuple(
        target.reference for target in edition_targets
    )
    return (
        same_as_edition
        and targets[0].chapter == endpoint.parsed_start_chapter
        and targets[0].verse == endpoint.parsed_start_verse
        and targets[-1].chapter == endpoint.parsed_end_chapter
        and targets[-1].verse == endpoint.parsed_end_verse
        and not any(target.reference_gap for target in edition_targets)
        and not _numeric_gaps(edition_targets)
    )


def _mapping_for_profile(
    endpoint: BenchmarkEndpointRow,
    index: PassageReferenceIndex,
    profile: Literal["edition_complete", "critical_core"],
    *,
    collect_risk: bool,
) -> tuple[BenchmarkEndpointMappingRow, MappingRisk | None]:
    if endpoint.parse_status != "parsed" or endpoint.parsed_book is None:
        inferred_corpus = openbible_reference_corpus(endpoint.source_reference)
        corpus: Literal["hebrew", "greek"] = inferred_corpus or "hebrew"
        reading: Literal["qere", "source"] = "qere" if corpus == "hebrew" else "source"
        passage_ids: tuple[str, ...] = ()
        references: tuple[str, ...] = ()
        status: MappingStatus = (
            "invalid" if endpoint.parse_status.startswith("invalid") else "unresolved_reference"
        )
        method = "no_mapping_invalid_or_unsupported_reference"
        confidence = "unresolved"
        ambiguity = endpoint.parse_status
        disputed_ids: tuple[str, ...] = ()
        disputed = False
        reference_gap = False
    else:
        corpus, reading = _target_stream(endpoint.parsed_book)
        assert endpoint.parsed_start_chapter is not None
        assert endpoint.parsed_start_verse is not None
        assert endpoint.parsed_end_chapter is not None
        assert endpoint.parsed_end_verse is not None
        targets = index.span(
            corpus=corpus,
            profile=profile,
            reading=reading,
            book=endpoint.parsed_book,
            start_chapter=endpoint.parsed_start_chapter,
            start_verse=endpoint.parsed_start_verse,
            end_chapter=endpoint.parsed_end_chapter,
            end_verse=endpoint.parsed_end_verse,
        )
        edition_targets = targets
        if profile != "edition_complete":
            edition_targets = index.span(
                corpus=corpus,
                profile="edition_complete",
                reading=reading,
                book=endpoint.parsed_book,
                start_chapter=endpoint.parsed_start_chapter,
                start_verse=endpoint.parsed_start_verse,
                end_chapter=endpoint.parsed_end_chapter,
                end_verse=endpoint.parsed_end_verse,
            )
        passage_ids = tuple(target.passage_id for target in targets)
        references = tuple(target.reference for target in targets)
        disputed_ids = tuple(
            sorted({item for target in edition_targets for item in target.disputed_passage_ids})
        )
        disputed = any(target.disputed_passage_flag for target in edition_targets)
        reference_gap = any(target.reference_gap for target in edition_targets) or _numeric_gaps(
            edition_targets
        )
        complete = _targets_cover_endpoint(endpoint, targets, edition_targets)
        method = "same_label_extant_reference"
        confidence = "provisional_mechanical"
        ambiguity = None
        if not targets and profile == "critical_core" and edition_targets:
            status = "excluded_by_profile"
            method = "critical_core_profile_compatibility"
            confidence = "profile_excluded"
            ambiguity = "target exists in edition_complete but is excluded by critical_core"
        elif not targets:
            status = "unresolved_missing_target"
            confidence = "unresolved"
            ambiguity = "exact target reference is absent from the pinned source edition"
        elif not complete or reference_gap:
            status = "mapped_partial"
            confidence = "partial_provisional"
            ambiguity = "range maps only to ordered extant verses or contains a reference gap"
        else:
            status = "mapped_provisional"
            ambiguity = "same-label mapping has no approved external versification crosswalk"

    identity = build_mapping_identity(
        MappingIdentityPayload(
            endpoint_id=endpoint.endpoint_id,
            target_corpus=corpus,
            target_analysis_profile=profile,
            target_analysis_reading=reading,
            target_granularity="verse",
            mapping_method=method,
            crosswalk_version=None,
            target_passage_ids=passage_ids,
        )
    )
    row = BenchmarkEndpointMappingRow(
        mapping_id=identity.identifier,
        endpoint_id=endpoint.endpoint_id,
        target_corpus=corpus,
        target_analysis_profile=profile,
        target_analysis_reading=reading,
        target_granularity="verse",
        target_passage_ids_json=_canonical_json(passage_ids),
        target_reference_sequence_json=_canonical_json(references),
        mapping_method=method,
        mapping_confidence=confidence,
        mapping_status=status,
        reference_gap=reference_gap,
        disputed_passage_flag=disputed,
        disputed_passage_ids_json=_canonical_json(disputed_ids),
        crosswalk_source=None,
        crosswalk_version=None,
        ambiguity_reason=ambiguity,
        notes="Mapping uncertainty does not alter source relationship identity.",
    )
    risk = None
    if collect_risk and (status != "mapped_verified" or reference_gap or disputed):
        risk = MappingRisk(
            endpoint_id=endpoint.endpoint_id,
            source_reference=endpoint.source_reference,
            book=endpoint.parsed_book,
            target_profile=profile,
            mapping_status=status,
            reason=ambiguity or "disputed passage or reference gap",
        )
    return row, risk


def _iter_mapping_results(
    endpoints: Iterable[BenchmarkEndpointRow],
    index: PassageReferenceIndex,
    *,
    collect_risks: bool,
) -> Iterator[tuple[BenchmarkEndpointMappingRow, MappingRisk | None]]:
    """Yield profile mappings while retaining only endpoint identity keys."""

    seen_endpoints: set[str] = set()
    ordered = sorted(endpoints, key=lambda item: (item.relationship_id, item.endpoint_side))
    for endpoint in ordered:
        if endpoint.endpoint_id in seen_endpoints:
            raise BenchmarkMappingError(
                f"duplicate endpoint identity before mapping: {endpoint.endpoint_id}"
            )
        seen_endpoints.add(endpoint.endpoint_id)
        for profile in ("edition_complete", "critical_core"):
            yield _mapping_for_profile(
                endpoint,
                index,
                profile,
                collect_risk=collect_risks,
            )


def iter_benchmark_endpoint_mappings(
    endpoints: Iterable[BenchmarkEndpointRow],
    index: PassageReferenceIndex,
) -> Iterator[BenchmarkEndpointMappingRow]:
    """Stream both governed profile mappings without a full row-model tuple.

    This is the production build path.  Callers may aggregate compact counts
    or default-profile facts as they consume the iterator, then convert rows
    into bounded columnar batches.  The fixture convenience API below retains
    its complete mapping/risk result contract.
    """

    for mapping, _risk in _iter_mapping_results(
        endpoints,
        index,
        collect_risks=False,
    ):
        yield mapping


def map_benchmark_endpoints(
    endpoints: Iterable[BenchmarkEndpointRow],
    index: PassageReferenceIndex,
    *,
    collect_risks: bool = True,
) -> MappingBuildResult:
    """Map every endpoint to default and critical-core compatibility profiles."""

    mappings: list[BenchmarkEndpointMappingRow] = []
    risks: list[MappingRisk] = []
    for mapping, risk in _iter_mapping_results(
        endpoints,
        index,
        collect_risks=collect_risks,
    ):
        mappings.append(mapping)
        if risk is not None:
            risks.append(risk)
    return MappingBuildResult(tuple(mappings), tuple(risks))
