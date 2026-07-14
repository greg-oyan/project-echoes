"""Atomic, deterministic storage and DuckDB exposure for lexical artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

import duckdb
import polars as pl

from echoes.corpus.storage import logical_frame_hash
from echoes.lexical.models import (
    LEXICAL_ARTIFACT_COLUMNS,
    LEXICAL_ARTIFACT_NAMES,
    LEXICAL_ARTIFACT_SCHEMAS,
    LEXICAL_ARTIFACT_SORT_COLUMNS,
    LEXICAL_SCHEMA_VERSION,
    METADATA_NONDETERMINISTIC_COLUMNS,
    LexicalArtifactName,
)
from echoes.lexical.resources import LexicalResourceError, configure_duckdb_connection
from echoes.manifest import sha256_file

TABLE_HASH_FILE = "table-hashes.json"

DUCKDB_ARTIFACT_NAMES: dict[LexicalArtifactName, str] = {
    "feature_vocabulary": "lexical_feature_vocabulary",
    "passage_feature_statistics": "lexical_passage_feature_statistics",
    "lexical_index_metadata": "lexical_index_metadata",
    "directional_rankings": "lexical_directional_rankings",
    "candidate_pairs": "lexical_candidate_pairs",
    "candidate_detector_scores": "lexical_candidate_detector_scores",
    "candidate_evidence": "lexical_candidate_evidence",
    "shared_evidence": "lexical_shared_evidence",
    "null_replicate_summaries": "lexical_null_replicates",
    "threshold_calibration": "lexical_threshold_calibration",
    "evaluation_results": "lexical_evaluation_results",
    "ablation_results": "lexical_ablation_results",
    "sensitivity_results": "lexical_sensitivity_results",
    "candidate_review_queue": "lexical_candidate_review_queue",
    "lexical_issues": "lexical_issues",
    "lexical_metadata": "lexical_metadata",
}

LEXICAL_CONVENIENCE_VIEWS: tuple[str, ...] = (
    "lexical_known_link_recovery",
    "lexical_unrepresented_candidates",
    "lexical_review_eligible_candidates",
    "lexical_formulaic_candidates",
    "lexical_rare_evidence_candidates",
    "lexical_english_derived_candidates",
    "lexical_ablation_failures",
    "lexical_candidate_ablation_results",
    "lexical_disputed_text_candidates",
    "lexical_reference_gap_candidates",
    "lexical_ketiv_sensitivity",
    "lexical_critical_core_sensitivity",
    "lexical_null_calibration",
    "lexical_detector_comparison",
    "lexical_performance_by_corpus_pair",
    "lexical_performance_by_mapping_status",
)


class LexicalStorageError(RuntimeError):
    """Raised when governed lexical storage cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ProcessedLexical:
    """One complete promoted lexical artifact set."""

    output_dir: Path
    schema_version: int
    table_counts: dict[str, int]
    table_logical_hashes: dict[str, str]
    table_physical_hashes: dict[str, str]
    file_hashes: dict[str, str]


def _canonical_aggregate(leaves: dict[str, dict[str, object]], key: str) -> str:
    payload = [
        {"path": path, "row_count": values["row_count"], key: values[key]}
        for path, values in sorted(leaves.items())
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_output_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.name != "schema-v1" or resolved.parent.name != "lexical":
        raise LexicalStorageError(
            "lexical output must be the governed data/processed/lexical/schema-v1 directory"
        )
    return resolved


def _logical_columns(name: LexicalArtifactName) -> tuple[str, ...]:
    """Return columns that belong to governed logical content.

    The same exclusion policy applies wherever a governed runtime field occurs,
    not only to the one-row metadata table.  In particular, per-replicate null
    runtimes are measurements and must not make two identical simulations have
    different logical table hashes.
    """

    return tuple(
        column
        for column in LEXICAL_ARTIFACT_COLUMNS[name]
        if column not in METADATA_NONDETERMINISTIC_COLUMNS
    )


def _prepare_frame(name: LexicalArtifactName, frame: pl.DataFrame) -> pl.DataFrame:
    expected = LEXICAL_ARTIFACT_COLUMNS[name]
    if tuple(frame.columns) != expected:
        raise LexicalStorageError(
            f"{name} columns differ from governed schema; expected={expected}, "
            f"actual={tuple(frame.columns)}"
        )
    try:
        typed = frame.cast(LEXICAL_ARTIFACT_SCHEMAS[name], strict=True)
    except (pl.exceptions.PolarsError, TypeError) as exc:
        raise LexicalStorageError(f"{name} does not match its storage schema: {exc}") from exc
    sort_columns = list(LEXICAL_ARTIFACT_SORT_COLUMNS[name])
    for column, dtype in zip(typed.columns, typed.dtypes, strict=True):
        if dtype in {pl.Float32, pl.Float64} and typed.get_column(column).is_nan().any():
            raise LexicalStorageError(f"{name}.{column} contains NaN")
    return typed.sort(sort_columns, nulls_last=True) if typed.height else typed


def _logical_hasher(name: LexicalArtifactName) -> hashlib._Hash:
    """Initialize the canonical table hash used by ``logical_frame_hash``."""

    digest = hashlib.sha256()
    schema = LEXICAL_ARTIFACT_SCHEMAS[name]
    columns = _logical_columns(name)
    digest.update("\0".join(columns).encode("utf-8"))
    digest.update(b"\0")
    digest.update("\0".join(str(schema[column]) for column in columns).encode("utf-8"))
    digest.update(b"\0")
    return digest


def _update_logical_hasher(digest: hashlib._Hash, frame: pl.DataFrame) -> None:
    if not frame.height:
        return
    for value in frame.hash_rows(seed=0, seed_1=1, seed_2=2, seed_3=3):
        digest.update(int(value).to_bytes(8, byteorder="little", signed=False))


def _comparable_sort_key(values: tuple[object, ...]) -> tuple[tuple[bool, object], ...]:
    """Map one typed row key to the same nulls-last ordering used by Polars."""

    return tuple((value is None, 0 if value is None else value) for value in values)


class LexicalArtifactWriter:
    """Incrementally write one complete lexical run behind an atomic boundary."""

    def __init__(
        self,
        output_dir: Path,
        *,
        force: bool = False,
        required_free_bytes: int = 0,
        duckdb_memory_limit_bytes: int,
    ) -> None:
        self.output_dir = _validate_output_path(output_dir)
        if required_free_bytes < 0:
            raise LexicalStorageError("required_free_bytes cannot be negative")
        if duckdb_memory_limit_bytes < 1:
            raise LexicalStorageError("duckdb_memory_limit_bytes must be positive")
        self.output_dir.parent.mkdir(parents=True, exist_ok=True)
        available = shutil.disk_usage(self.output_dir.parent).free
        if available < required_free_bytes:
            raise LexicalStorageError(
                f"insufficient disk space for lexical output: "
                f"required={required_free_bytes}, available={available}"
            )
        if self.output_dir.exists() and not force:
            raise LexicalStorageError(
                f"refusing to overwrite lexical artifacts at {self.output_dir}; pass --force"
            )
        token = uuid4().hex
        self.staging_dir = self.output_dir.parent / f".{self.output_dir.name}.writing-{token}"
        self.backup_dir = self.output_dir.parent / f".{self.output_dir.name}.backup-{token}"
        self.staging_dir.mkdir()
        self._leaves: dict[LexicalArtifactName, dict[str, dict[str, object]]] = {
            name: {} for name in LEXICAL_ARTIFACT_NAMES
        }
        self._counts: dict[str, int] = {name: 0 for name in LEXICAL_ARTIFACT_NAMES}
        self._logical_hashers = {
            name: _logical_hasher(name)
            for name in LEXICAL_ARTIFACT_NAMES
            if name != "lexical_metadata"
        }
        self._last_sort_keys: dict[LexicalArtifactName, tuple[tuple[bool, object], ...]] = {}
        self._parts_globally_sorted: dict[LexicalArtifactName, bool] = {
            name: True for name in LEXICAL_ARTIFACT_NAMES if name != "lexical_metadata"
        }
        self._content_hash_cache: tuple[dict[str, str], dict[str, str]] | None = None
        self._sparse_paths: set[str] = set()
        self._duckdb_memory_limit_bytes = duckdb_memory_limit_bytes
        self._required_free_bytes = required_free_bytes
        self._closed = False

    def __enter__(self) -> LexicalArtifactWriter:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._closed:
            self.abort()

    def check_free_disk(self, stage: str) -> None:
        """Fail closed when the configured free-disk floor is no longer available."""

        if self._required_free_bytes == 0:
            return
        available = shutil.disk_usage(self.output_dir.parent).free
        if available < self._required_free_bytes:
            raise LexicalStorageError(
                "lexical output crossed the governed free-disk floor at "
                f"{stage}: required={self._required_free_bytes}, available={available}"
            )

    def write_frame(
        self,
        name: LexicalArtifactName,
        frame: pl.DataFrame,
        *,
        part: int = 0,
    ) -> Path:
        """Validate and write one deterministically numbered Parquet leaf."""

        if self._closed:
            raise LexicalStorageError("lexical artifact writer is closed")
        if name == "lexical_metadata":
            raise LexicalStorageError("lexical metadata must be supplied to finalize")
        if part < 0:
            raise LexicalStorageError("part number cannot be negative")
        expected_part = len(self._leaves[name])
        if part != expected_part:
            raise LexicalStorageError(
                f"{name} part numbers must be contiguous from zero; "
                f"expected={expected_part}, actual={part}"
            )
        prepared = _prepare_frame(name, frame)
        relative = Path(name) / f"part-{part:05d}.parquet"
        key = relative.as_posix()
        if key in self._leaves[name]:
            raise LexicalStorageError(f"duplicate lexical artifact leaf: {key}")
        self.check_free_disk(f"{name}:part-{part}:before")
        sort_columns = list(LEXICAL_ARTIFACT_SORT_COLUMNS[name])
        if prepared.height:
            keys = prepared.select(sort_columns)
            first_key = _comparable_sort_key(keys.row(0))
            last_key = _comparable_sort_key(keys.row(-1))
            previous = self._last_sort_keys.get(name)
            if previous is not None and first_key < previous:
                self._parts_globally_sorted[name] = False
            self._last_sort_keys[name] = last_key
        path = self.staging_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_parquet(
            path,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        self.check_free_disk(f"{name}:part-{part}:after")
        logical_projection = prepared.select(_logical_columns(name))
        logical = logical_frame_hash(
            logical_projection,
            sort_by=sort_columns,
        )
        _update_logical_hasher(self._logical_hashers[name], logical_projection)
        self._leaves[name][key] = {
            "row_count": prepared.height,
            "parquet_sha256": sha256_file(path),
            "logical_sha256": logical,
        }
        self._counts[name] += prepared.height
        self._content_hash_cache = None
        return path

    def write_sparse_bytes(self, relative_path: Path, content: bytes) -> Path:
        """Write deterministic sparse-index bytes inside the staging boundary."""

        if self._closed:
            raise LexicalStorageError("lexical artifact writer is closed")
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise LexicalStorageError("sparse index path must be confined and relative")
        if not relative_path.parts or relative_path == Path("."):
            raise LexicalStorageError("sparse index path must name a file")
        key = relative_path.as_posix()
        if key in self._sparse_paths:
            raise LexicalStorageError(f"duplicate sparse index path: {key}")
        self.check_free_disk(f"sparse:{key}:before")
        target = self.staging_dir / "indexes" / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self.check_free_disk(f"sparse:{key}:after")
        self._sparse_paths.add(key)
        return target

    def content_hashes(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return aggregate hashes for non-metadata tables already staged."""

        if self._content_hash_cache is not None:
            cached_logical, cached_physical = self._content_hash_cache
            return dict(cached_logical), dict(cached_physical)
        self.check_free_disk("content_hashes:before")

        missing = [
            name
            for name in LEXICAL_ARTIFACT_NAMES
            if name != "lexical_metadata" and not self._leaves[name]
        ]
        if missing:
            raise LexicalStorageError(f"missing required lexical artifacts: {missing}")
        logical: dict[str, str] = {}
        for name in LEXICAL_ARTIFACT_NAMES:
            if name == "lexical_metadata":
                continue
            if self._parts_globally_sorted[name]:
                logical[str(name)] = self._logical_hashers[name].copy().hexdigest()
            else:
                logical[str(name)] = self._externally_sorted_logical_hash(name)
        physical: dict[str, str] = {
            str(name): _canonical_aggregate(self._leaves[name], "parquet_sha256")
            for name in LEXICAL_ARTIFACT_NAMES
            if name != "lexical_metadata"
        }
        self._content_hash_cache = (dict(logical), dict(physical))
        self.check_free_disk("content_hashes:after")
        return logical, physical

    def _externally_sorted_logical_hash(self, name: LexicalArtifactName) -> str:
        """Hash out-of-order parts through a bounded DuckDB external merge sort."""

        glob = (self.staging_dir / name / "part-*.parquet").as_posix().replace("'", "''")
        order = ", ".join(
            f'"{column}" NULLS LAST' for column in LEXICAL_ARTIFACT_SORT_COLUMNS[name]
        )
        digest = _logical_hasher(name)
        spill_directory = self.staging_dir / ".logical-hash-spill"
        try:
            with duckdb.connect() as connection:
                configure_duckdb_connection(
                    connection,
                    memory_limit_bytes=self._duckdb_memory_limit_bytes,
                    temp_directory=spill_directory,
                    thread_count=1,
                )
                reader = connection.execute(
                    f"SELECT * FROM read_parquet('{glob}') ORDER BY {order}"
                ).to_arrow_reader(50_000)
                for batch in reader:
                    frame = cast(pl.DataFrame, pl.from_arrow(batch, rechunk=False)).select(
                        _logical_columns(name)
                    )
                    _update_logical_hasher(digest, frame)
        except (
            duckdb.Error,
            OSError,
            pl.exceptions.PolarsError,
            LexicalResourceError,
        ) as exc:
            raise LexicalStorageError(
                f"could not externally sort {name} for logical hashing: {exc}"
            ) from exc
        finally:
            shutil.rmtree(spill_directory, ignore_errors=True)
        return digest.hexdigest()

    def finalize(self, metadata: pl.DataFrame) -> ProcessedLexical:
        """Write metadata and hash manifest, then atomically promote the run."""

        if metadata.height != 1:
            raise LexicalStorageError("finalize requires exactly one lexical metadata row")
        self.check_free_disk("finalize:before")
        logical_before, physical_before = self.content_hashes()
        prepared = _prepare_frame("lexical_metadata", metadata)
        declared_logical = json.loads(str(prepared["table_logical_hashes_json"][0]))
        declared_physical = json.loads(str(prepared["table_physical_hashes_json"][0]))
        if declared_logical != logical_before:
            raise LexicalStorageError(
                "lexical metadata table_logical_hashes_json does not match staged artifacts"
            )
        if declared_physical != physical_before:
            raise LexicalStorageError(
                "lexical metadata table_physical_hashes_json does not match staged artifacts"
            )
        relative = Path("lexical_metadata") / "part-00000.parquet"
        path = self.staging_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_parquet(path, compression="zstd", compression_level=6, statistics=True)
        logical_projection = prepared.select(_logical_columns("lexical_metadata"))
        self._leaves["lexical_metadata"][relative.as_posix()] = {
            "row_count": 1,
            "parquet_sha256": sha256_file(path),
            "logical_sha256": logical_frame_hash(
                logical_projection,
                sort_by=["experiment_run_id"],
            ),
        }
        self._counts["lexical_metadata"] = 1
        table_logical = {
            **logical_before,
            # Metadata is exactly one governed row/leaf, so its leaf logical
            # hash is also its global, part-boundary-independent table hash.
            "lexical_metadata": str(
                self._leaves["lexical_metadata"][relative.as_posix()]["logical_sha256"]
            ),
        }
        table_physical = {
            **physical_before,
            "lexical_metadata": _canonical_aggregate(
                self._leaves["lexical_metadata"], "parquet_sha256"
            ),
        }
        file_hashes = {
            relative_path: str(values["parquet_sha256"])
            for leaves in self._leaves.values()
            for relative_path, values in sorted(leaves.items())
        }
        for sparse_path in sorted((self.staging_dir / "indexes").rglob("*")):
            if sparse_path.is_file():
                file_hashes[sparse_path.relative_to(self.staging_dir).as_posix()] = sha256_file(
                    sparse_path
                )
        manifest = {
            "schema_version": LEXICAL_SCHEMA_VERSION,
            "metadata_nondeterministic_columns": sorted(METADATA_NONDETERMINISTIC_COLUMNS),
            "table_counts": self._counts,
            "table_logical_sha256": table_logical,
            "table_physical_sha256": table_physical,
            "file_sha256": file_hashes,
            "artifacts": self._leaves,
        }
        (self.staging_dir / TABLE_HASH_FILE).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.check_free_disk("finalize:staged")
        try:
            if self.output_dir.exists():
                self.output_dir.replace(self.backup_dir)
            try:
                self.staging_dir.replace(self.output_dir)
            except OSError:
                if self.backup_dir.exists() and not self.output_dir.exists():
                    self.backup_dir.replace(self.output_dir)
                raise
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir)
        except OSError as exc:
            self.abort()
            raise LexicalStorageError(f"could not promote lexical artifacts: {exc}") from exc
        self._closed = True
        return ProcessedLexical(
            output_dir=self.output_dir,
            schema_version=LEXICAL_SCHEMA_VERSION,
            table_counts=dict(self._counts),
            table_logical_hashes=table_logical,
            table_physical_hashes=table_physical,
            file_hashes=file_hashes,
        )

    def abort(self) -> None:
        """Remove incomplete confined state and restore a displaced prior run."""

        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
        if self.backup_dir.exists() and not self.output_dir.exists():
            self.backup_dir.replace(self.output_dir)
        self._closed = True


def read_hash_manifest(output_dir: Path) -> dict[str, object]:
    """Read and minimally validate the lexical hash manifest."""

    path = _validate_output_path(output_dir) / TABLE_HASH_FILE
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalStorageError(f"could not read lexical hash manifest {path}: {exc}") from exc
    if not isinstance(parsed, dict) or parsed.get("schema_version") != LEXICAL_SCHEMA_VERSION:
        raise LexicalStorageError(f"invalid lexical hash manifest: {path}")
    required = {
        "table_counts",
        "table_logical_sha256",
        "table_physical_sha256",
        "file_sha256",
        "artifacts",
    }
    if not required.issubset(parsed):
        raise LexicalStorageError(f"lexical hash manifest is incomplete: {path}")
    for key in required:
        if not isinstance(parsed[key], dict):
            raise LexicalStorageError(f"lexical hash manifest field {key} is not an object")
    expected_names = set(LEXICAL_ARTIFACT_NAMES)
    if set(parsed["table_counts"]) != expected_names:
        raise LexicalStorageError("lexical hash manifest table counts have unexpected names")
    if set(parsed["table_logical_sha256"]) != expected_names:
        raise LexicalStorageError("lexical hash manifest logical hashes have unexpected names")
    if set(parsed["table_physical_sha256"]) != expected_names:
        raise LexicalStorageError("lexical hash manifest physical hashes have unexpected names")
    return cast(dict[str, object], parsed)


def processed_from_directory(output_dir: Path) -> ProcessedLexical:
    """Reconstruct a processed-run handle from its governed hash manifest."""

    root = _validate_output_path(output_dir)
    manifest = read_hash_manifest(root)
    return ProcessedLexical(
        output_dir=root,
        schema_version=LEXICAL_SCHEMA_VERSION,
        table_counts={
            str(k): int(str(v))
            for k, v in cast(dict[str, object], manifest["table_counts"]).items()
        },
        table_logical_hashes={
            str(k): str(v)
            for k, v in cast(dict[str, object], manifest["table_logical_sha256"]).items()
        },
        table_physical_hashes={
            str(k): str(v)
            for k, v in cast(dict[str, object], manifest["table_physical_sha256"]).items()
        },
        file_hashes={
            str(k): str(v) for k, v in cast(dict[str, object], manifest["file_sha256"]).items()
        },
    )


def read_artifact_frame(output_dir: Path, name: LexicalArtifactName) -> pl.DataFrame:
    """Read one artifact in stable governed order."""

    root = _validate_output_path(output_dir) / name
    paths = sorted(root.glob("part-*.parquet"))
    if not paths:
        raise LexicalStorageError(f"no Parquet leaves exist for {name} in {root}")
    try:
        frame = pl.read_parquet(paths, rechunk=True).select(LEXICAL_ARTIFACT_COLUMNS[name])
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise LexicalStorageError(f"could not read lexical artifact {name}: {exc}") from exc
    return _prepare_frame(name, frame)


def _drop_relation(connection: duckdb.DuckDBPyConnection, name: str) -> None:
    tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    if name not in tables:
        return
    relation_type = connection.execute(
        "SELECT table_type FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()
    if relation_type and str(relation_type[0]) == "VIEW":
        connection.execute(f'DROP VIEW "{name}"')
    else:
        connection.execute(f'DROP TABLE "{name}"')


def load_lexical_duckdb(
    processed: ProcessedLexical,
    database_path: Path,
    *,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
) -> None:
    """Transactionally expose only governed lexical Parquet and convenience views."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb.connect(str(database_path)) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            connection.execute("BEGIN TRANSACTION")
            try:
                for view in LEXICAL_CONVENIENCE_VIEWS:
                    _drop_relation(connection, view)
                for artifact, relation in DUCKDB_ARTIFACT_NAMES.items():
                    _drop_relation(connection, relation)
                    glob = (processed.output_dir / artifact / "part-*.parquet").as_posix()
                    escaped = glob.replace("'", "''")
                    connection.execute(
                        f'CREATE VIEW "{relation}" AS '
                        f"SELECT * FROM read_parquet('{escaped}', union_by_name=true)"
                    )
                connection.execute(
                    "CREATE VIEW lexical_known_link_recovery AS "
                    "SELECT * FROM lexical_evaluation_results WHERE benchmark_tier = 3"
                )
                connection.execute(
                    "CREATE VIEW lexical_unrepresented_candidates AS "
                    "SELECT * FROM lexical_candidate_pairs WHERE known_link_status = "
                    "'not_represented_in_openbible_snapshot'"
                )
                connection.execute(
                    "CREATE VIEW lexical_review_eligible_candidates AS "
                    "SELECT * FROM lexical_candidate_pairs WHERE review_eligible"
                )
                connection.execute(
                    "CREATE VIEW lexical_formulaic_candidates AS "
                    "SELECT p.*, e.formulaic_penalty FROM lexical_candidate_pairs p "
                    "JOIN lexical_candidate_evidence e USING (candidate_pair_id) "
                    "WHERE e.formulaic_penalty > 0"
                )
                connection.execute(
                    "CREATE VIEW lexical_rare_evidence_candidates AS "
                    "SELECT p.*, e.shared_rare_lemma_count, e.shared_rare_root_count, "
                    "e.rare_rule_passed FROM lexical_candidate_pairs p "
                    "JOIN lexical_candidate_evidence e USING (candidate_pair_id) "
                    "WHERE e.shared_rare_lemma_count + e.shared_rare_root_count > 0"
                )
                connection.execute(
                    "CREATE VIEW lexical_english_derived_candidates AS "
                    "SELECT * FROM lexical_candidate_pairs "
                    "WHERE contains_english_derived_evidence"
                )
                connection.execute(
                    "CREATE VIEW lexical_ablation_failures AS "
                    "SELECT * FROM lexical_ablation_results "
                    "WHERE changed AND NOT review_eligible_after"
                )
                connection.execute(
                    "CREATE VIEW lexical_candidate_ablation_results AS "
                    "SELECT * FROM lexical_ablation_results WHERE subject_type='candidate_pair'"
                )
                connection.execute(
                    "CREATE VIEW lexical_disputed_text_candidates AS "
                    "SELECT * FROM lexical_candidate_pairs WHERE disputed_passage_flag"
                )
                connection.execute(
                    "CREATE VIEW lexical_reference_gap_candidates AS "
                    "SELECT * FROM lexical_candidate_pairs WHERE reference_gap"
                )
                connection.execute(
                    "CREATE VIEW lexical_ketiv_sensitivity AS "
                    "SELECT * FROM lexical_sensitivity_results "
                    "WHERE sensitivity_type='hebrew_qere_ketiv'"
                )
                connection.execute(
                    "CREATE VIEW lexical_critical_core_sensitivity AS "
                    "SELECT * FROM lexical_sensitivity_results "
                    "WHERE sensitivity_type='critical_core_profile'"
                )
                connection.execute(
                    "CREATE VIEW lexical_null_calibration AS "
                    "SELECT c.*, n.null_family, n.iteration, n.candidate_count AS null_count "
                    "FROM lexical_threshold_calibration c LEFT JOIN lexical_null_replicates n "
                    "USING (experiment_run_id, corpus_pair, representation_id, "
                    "detector, threshold_id)"
                )
                connection.execute(
                    "CREATE VIEW lexical_detector_comparison AS "
                    "SELECT corpus_pair, detector, metric, k, avg(value) AS mean_value "
                    "FROM lexical_evaluation_results GROUP BY ALL"
                )
                connection.execute(
                    "CREATE VIEW lexical_performance_by_corpus_pair AS "
                    "SELECT corpus_pair, detector, metric, k, avg(value) AS mean_value, "
                    "sum(eligible_query_count) AS eligible_query_count "
                    "FROM lexical_evaluation_results GROUP BY ALL"
                )
                connection.execute(
                    "CREATE VIEW lexical_performance_by_mapping_status AS "
                    "SELECT mapping_status, corpus_pair, detector, metric, k, "
                    "avg(value) AS mean_value FROM lexical_evaluation_results GROUP BY ALL"
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
    except (duckdb.Error, OSError, LexicalResourceError) as exc:
        raise LexicalStorageError(f"could not load lexical DuckDB {database_path}: {exc}") from exc
