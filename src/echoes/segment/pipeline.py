"""End-to-end orchestration for deterministic passage segmentation."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from echoes.segment.models import (
    PASSAGE_ID_SCHEMA_VERSION,
    PASSAGE_SCHEMA_VERSION,
    SEGMENTATION_METADATA_COLUMNS,
    SEGMENTATION_METADATA_POLARS_SCHEMA,
    Granularity,
    SegmentationMetadataRow,
)
from echoes.segment.streams import (
    GREEK_TOKEN_COUNT,
    HEBREW_TOKEN_COUNT,
    AnalysisProfileName,
    AnalysisReadingName,
    CorpusName,
    InputDigestSet,
    SegmentationInputs,
    build_analysis_stream,
    load_segmentation_inputs,
)
from echoes.settings import SegmentationConfig

SEGMENTATION_ALGORITHM_VERSION = 1


class PassagePipelineError(RuntimeError):
    """Raised when a requested segmentation run is incomplete or unsafe."""


class SegmentationSelection(BaseModel):
    """A validated full or stream-specific generation selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    all_streams: bool = False
    corpus: Literal["hebrew", "greek"] | None = None
    analysis_profile: Literal["edition_complete", "critical_core"] | None = None
    analysis_reading: Literal["qere", "ketiv", "source"] | None = None
    granularity: Literal["clause", "sentence", "verse", "two_verse", "five_verse"] | None = None
    book: str | None = Field(default=None, pattern=r"^[A-Z0-9]{3}$")

    def selected_streams(
        self,
    ) -> tuple[
        tuple[
            Literal["hebrew", "greek"],
            Literal["edition_complete", "critical_core"],
            Literal["qere", "ketiv", "source"],
        ],
        ...,
    ]:
        """Return exact governed stream keys or reject an ambiguous selector."""

        if self.all_streams:
            if any(
                value is not None
                for value in (
                    self.corpus,
                    self.analysis_profile,
                    self.analysis_reading,
                    self.granularity,
                    self.book,
                )
            ):
                raise PassagePipelineError("--all cannot be combined with stream selectors")
            return (
                ("hebrew", "edition_complete", "qere"),
                ("hebrew", "edition_complete", "ketiv"),
                ("hebrew", "critical_core", "qere"),
                ("hebrew", "critical_core", "ketiv"),
                ("greek", "edition_complete", "source"),
                ("greek", "critical_core", "source"),
            )
        if self.corpus is None or self.analysis_profile is None or self.analysis_reading is None:
            raise PassagePipelineError(
                "select --all or provide --corpus, --profile, and --reading together"
            )
        if self.corpus == "hebrew" and self.analysis_reading not in {"qere", "ketiv"}:
            raise PassagePipelineError("Hebrew segmentation requires qere or ketiv reading")
        if self.corpus == "greek" and self.analysis_reading != "source":
            raise PassagePipelineError("Greek segmentation requires the source reading")
        return ((self.corpus, self.analysis_profile, self.analysis_reading),)


@dataclass(frozen=True, slots=True)
class SegmentationRunContext:
    """Deterministic run identity and its provenance-bearing inputs."""

    run_id: str
    config_hash: str
    config_canonical_json: str
    selection: SegmentationSelection
    source_versions: dict[str, str]
    digests: InputDigestSet


@dataclass(frozen=True, slots=True)
class SegmentationPipelineResult:
    """Completed local passage generation and database exposure."""

    context: SegmentationRunContext
    output_dir: Path
    database_path: Path
    table_counts: dict[str, int]
    table_logical_hashes: dict[str, str]
    table_physical_hashes: dict[str, str]
    runtime_seconds: float
    output_size_bytes: int


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def segmentation_config_fingerprint(config: SegmentationConfig) -> tuple[str, str]:
    """Hash semantic configuration independently of YAML comments or paths."""

    payload = config.model_dump(mode="json")
    output_policy = payload.get("output_partitioning")
    if isinstance(output_policy, dict):
        output_policy = dict(output_policy)
        output_policy.pop("schema_directory", None)
        payload["output_partitioning"] = output_policy
    canonical = _canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), canonical


def create_run_context(
    *,
    config: SegmentationConfig,
    selection: SegmentationSelection,
    inputs: SegmentationInputs,
) -> SegmentationRunContext:
    """Derive a stable run ID from governed semantics and immutable inputs."""

    selection.selected_streams()
    config_hash, config_json = segmentation_config_fingerprint(config)
    payload = {
        "kind": "project-echoes-passage-segmentation",
        "passage_schema_version": PASSAGE_SCHEMA_VERSION,
        "passage_id_schema_version": PASSAGE_ID_SCHEMA_VERSION,
        "segmentation_algorithm_version": SEGMENTATION_ALGORITHM_VERSION,
        "segmentation_config": json.loads(config_json),
        "selection": selection.model_dump(mode="json"),
        "source_versions": dict(sorted(inputs.source_versions.items())),
        "input_digests": inputs.digests.as_dict(),
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return SegmentationRunContext(
        run_id=f"passages-v{PASSAGE_SCHEMA_VERSION}-{digest[:20]}",
        config_hash=config_hash,
        config_canonical_json=config_json,
        selection=selection,
        source_versions=dict(sorted(inputs.source_versions.items())),
        digests=inputs.digests,
    )


def processing_environment() -> dict[str, object]:
    """Return portable implementation versions without local paths or clocks."""

    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "polars": pl.__version__,
        "duckdb": duckdb.__version__,
        "byte_order": sys.byteorder,
    }


def default_passage_output(config: SegmentationConfig, project_root: Path = Path(".")) -> Path:
    """Resolve the governed repository-relative generated output directory."""

    root = project_root.resolve()
    output = (root / config.output_partitioning.schema_directory).resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise PassagePipelineError("passage output resolves outside the repository") from exc
    return output


def _selected_granularities(
    selection: SegmentationSelection, config: SegmentationConfig
) -> tuple[Granularity, ...]:
    if selection.granularity is not None:
        return (selection.granularity,)
    return tuple(config.granularities)


def _estimated_output_bytes(
    stream_keys: tuple[tuple[CorpusName, AnalysisProfileName, AnalysisReadingName], ...],
) -> int:
    """Conservatively estimate compressed output before staging any partition."""

    tokens = 0
    for corpus, profile, reading in stream_keys:
        if corpus == "hebrew":
            tokens += HEBREW_TOKEN_COUNT if reading == "qere" else 474_932
        elif profile == "critical_core":
            tokens += GREEK_TOKEN_COUNT - 390
        else:
            tokens += GREEK_TOKEN_COUNT
    return tokens * 2_500


def _metadata_frame(
    *,
    context: SegmentationRunContext,
    config: SegmentationConfig,
    stream_keys: tuple[tuple[CorpusName, AnalysisProfileName, AnalysisReadingName], ...],
    granularities: tuple[Granularity, ...],
    table_counts: dict[str, int],
    table_logical_hashes: dict[str, str],
    table_physical_hashes: dict[str, str],
    runtime_seconds: float,
    output_size_bytes: int,
) -> pl.DataFrame:
    identities = {
        "hebrew": context.digests.hebrew_identity,
        "greek": context.digests.greek_identity,
    }
    contents = {
        "hebrew": context.digests.hebrew_content,
        "greek": context.digests.greek_content,
    }
    analytical = {
        "hebrew": context.digests.hebrew_analytical,
        "greek": context.digests.greek_analytical,
    }
    row = SegmentationMetadataRow(
        segmentation_run_id=context.run_id,
        segmentation_config_hash=context.config_hash,
        input_source_versions_json=_canonical_json(context.source_versions),
        input_primary_identity_digests_json=_canonical_json(identities),
        input_surface_lemma_digests_json=_canonical_json(contents),
        input_analytical_digests_json=_canonical_json(analytical),
        input_oshb_supplement_digests_json=_canonical_json(context.digests.oshb_logical),
        enabled_corpora_json=_canonical_json(list(dict.fromkeys(key[0] for key in stream_keys))),
        analysis_profiles_json=_canonical_json(list(dict.fromkeys(key[1] for key in stream_keys))),
        analysis_readings_json=_canonical_json(list(dict.fromkeys(key[2] for key in stream_keys))),
        granularities_json=_canonical_json(list(granularities)),
        table_counts_json=_canonical_json(table_counts),
        table_logical_hashes_json=_canonical_json(table_logical_hashes),
        table_physical_hashes_json=_canonical_json(table_physical_hashes),
        processing_environment_json=_canonical_json(processing_environment()),
        runtime_seconds=runtime_seconds,
        approximate_peak_memory_bytes=None,
        output_size_bytes=output_size_bytes,
    ).model_dump(mode="python")
    return pl.DataFrame([row], schema=SEGMENTATION_METADATA_POLARS_SCHEMA).select(
        SEGMENTATION_METADATA_COLUMNS
    )


def segment_passages(
    *,
    config: SegmentationConfig,
    selection: SegmentationSelection,
    manifest_path: Path = Path("data/manifests/sources.yaml"),
    data_root: Path = Path("data"),
    output_dir: Path | None = None,
    database_path: Path | None = None,
    force: bool = False,
) -> SegmentationPipelineResult:
    """Generate selected passage partitions after every immutable-input gate."""

    from echoes.segment.generation import generate_partition
    from echoes.segment.storage import (
        ArtifactPartition,
        PassageArtifactWriter,
        load_passage_duckdb,
    )

    started = perf_counter()
    stream_keys = selection.selected_streams()
    granularities = _selected_granularities(selection, config)
    inputs = load_segmentation_inputs(manifest_path=manifest_path, data_root=data_root)
    context = create_run_context(config=config, selection=selection, inputs=inputs)
    resolved_output = output_dir or default_passage_output(config)
    resolved_database = database_path or data_root / "processed" / "project_echoes.duckdb"
    estimated_bytes = _estimated_output_bytes(stream_keys)
    required_free_bytes = estimated_bytes * 3 + 5 * 1024**3

    with PassageArtifactWriter(
        output_dir=resolved_output,
        force=force,
        estimated_output_bytes=estimated_bytes,
        required_free_bytes=required_free_bytes,
    ) as writer:
        for corpus, profile, reading in stream_keys:
            stream = build_analysis_stream(
                inputs,
                config=config,
                corpus=corpus,
                profile=profile,
                reading=reading,
            )
            if selection.book is not None:
                stream = stream.filter(pl.col("book") == selection.book)
                if stream.is_empty():
                    raise PassagePipelineError(
                        f"selected book {selection.book} is absent from {corpus}"
                    )
            for book_stream in stream.partition_by("book", maintain_order=True, include_key=True):
                book = str(book_stream.item(0, "book"))
                generated = generate_partition(
                    book_stream,
                    config=config,
                    segmentation_run_id=context.run_id,
                    config_hash=context.config_hash,
                )
                artifact_frames: dict[
                    Literal["passages", "passage_membership", "passage_adjacency"],
                    pl.DataFrame,
                ] = {
                    "passages": generated.passages,
                    "passage_membership": generated.membership,
                    "passage_adjacency": generated.adjacency,
                }
                for granularity in granularities:
                    for table, frame in artifact_frames.items():
                        writer.write_partition(
                            ArtifactPartition(
                                table=table,
                                frame=frame.filter(pl.col("granularity") == granularity),
                                corpus=corpus,
                                analysis_profile=profile,
                                analysis_reading=reading,
                                granularity=granularity,
                                book=book,
                            )
                        )
                exclusions = generated.exclusions.filter(pl.col("granularity").is_in(granularities))
                writer.write_partition(
                    ArtifactPartition(
                        table="segmentation_exclusions",
                        frame=exclusions,
                        corpus=corpus,
                        analysis_profile=profile,
                        analysis_reading=reading,
                        granularity="clause" if "clause" in granularities else granularities[0],
                        book=book,
                    )
                )
                writer.write_partition(
                    ArtifactPartition(
                        table="segmentation_issues",
                        frame=generated.issues,
                        corpus=corpus,
                        analysis_profile=profile,
                        analysis_reading=reading,
                        granularity=None,
                        book=book,
                    )
                )
        summary = writer.content_summary()
        runtime = round(perf_counter() - started, 6)
        metadata = _metadata_frame(
            context=context,
            config=config,
            stream_keys=stream_keys,
            granularities=granularities,
            table_counts=summary.table_counts,
            table_logical_hashes=summary.table_logical_hashes,
            table_physical_hashes=summary.table_physical_hashes,
            runtime_seconds=runtime,
            output_size_bytes=summary.output_size_bytes,
        )
        processed = writer.finalize(
            ArtifactPartition(table="segmentation_metadata", frame=metadata)
        )
    load_passage_duckdb(processed, resolved_database)
    return SegmentationPipelineResult(
        context=context,
        output_dir=processed.output_dir,
        database_path=resolved_database,
        table_counts=processed.table_counts,
        table_logical_hashes=processed.table_logical_hashes,
        table_physical_hashes=processed.table_physical_hashes,
        runtime_seconds=runtime,
        output_size_bytes=summary.output_size_bytes,
    )
