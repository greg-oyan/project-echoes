"""Atomic, deterministic storage and DuckDB exposure for lexical artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast
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
from echoes.manifest import load_execution_manifest, sha256_file

TABLE_HASH_FILE = "table-hashes.json"
LEXICAL_PROMOTION_COMMIT_RELATION = "lexical_promotion_commit"
PROMOTION_JOURNAL_SCHEMA_VERSION = 1
PromotionRecoveryState = Literal[
    "no_journal",
    "staging_restored",
    "canonical_committed",
]

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
    "lexical_directional_english_ablation",
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
class LexicalPromotionJournal:
    """Durable cross-boundary intent for artifact promotion and DuckDB exposure."""

    output_dir: Path
    staging_dir: Path
    backup_dir: Path
    database_path: Path
    execution_manifest_path: Path
    execution_id: str
    promotion_id: str
    table_hash_manifest_sha256: str

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": PROMOTION_JOURNAL_SCHEMA_VERSION,
            "output_dir": str(self.output_dir),
            "staging_dir": str(self.staging_dir),
            "backup_dir": str(self.backup_dir),
            "database_path": str(self.database_path),
            "execution_manifest_path": str(self.execution_manifest_path),
            "execution_id": self.execution_id,
            "promotion_id": self.promotion_id,
            "table_hash_manifest_sha256": self.table_hash_manifest_sha256,
        }


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


def lexical_promotion_journal_path(output_dir: Path) -> Path:
    """Return the single governed journal path beside canonical lexical output."""

    resolved = _validate_output_path(output_dir)
    return resolved.parent / f".{resolved.name}.promotion-intent.json"


def read_lexical_promotion_journal(output_dir: Path) -> LexicalPromotionJournal:
    """Read and validate the active durable promotion journal."""

    return _read_promotion_journal(lexical_promotion_journal_path(output_dir))


def _sync_directory(path: Path) -> None:
    """Durably order a journal or rename on POSIX; Windows lacks directory fsync."""

    if os.name == "nt":
        return
    flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise LexicalStorageError(f"could not durably sync directory {path}: {exc}") from exc


def _write_promotion_journal(journal: LexicalPromotionJournal) -> Path:
    path = lexical_promotion_journal_path(journal.output_dir)
    if path.exists() or path.is_symlink():
        raise LexicalStorageError(f"lexical promotion journal already exists: {path}")
    pending = path.with_name(f".{path.name}.writing-{uuid4().hex}")
    encoded = (json.dumps(journal.as_json(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with pending.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
        _sync_directory(path.parent)
    except OSError as exc:
        raise LexicalStorageError(
            f"could not write lexical promotion journal {path}: {exc}"
        ) from exc
    finally:
        if pending.exists():
            pending.unlink()
    return path


def _read_promotion_journal(path: Path) -> LexicalPromotionJournal:
    if not path.is_file() or path.is_symlink():
        raise LexicalStorageError(f"lexical promotion journal is missing or unsafe: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalStorageError(f"invalid lexical promotion journal {path}: {exc}") from exc
    expected_keys = {
        "schema_version",
        "output_dir",
        "staging_dir",
        "backup_dir",
        "database_path",
        "execution_manifest_path",
        "execution_id",
        "promotion_id",
        "table_hash_manifest_sha256",
    }
    if not isinstance(raw, dict) or set(raw) != expected_keys:
        raise LexicalStorageError(f"lexical promotion journal has an unexpected schema: {path}")
    if raw["schema_version"] != PROMOTION_JOURNAL_SCHEMA_VERSION:
        raise LexicalStorageError(f"unsupported lexical promotion journal version: {path}")
    string_fields = (
        "output_dir",
        "staging_dir",
        "backup_dir",
        "database_path",
        "execution_manifest_path",
        "execution_id",
        "promotion_id",
        "table_hash_manifest_sha256",
    )
    if any(not isinstance(raw[field], str) or not raw[field] for field in string_fields):
        raise LexicalStorageError(f"lexical promotion journal contains invalid values: {path}")
    manifest_sha256 = str(raw["table_hash_manifest_sha256"])
    if len(manifest_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in manifest_sha256
    ):
        raise LexicalStorageError(f"lexical promotion journal has an invalid manifest hash: {path}")
    promotion_id = str(raw["promotion_id"])
    if len(promotion_id) != 32 or any(
        character not in "0123456789abcdef" for character in promotion_id
    ):
        raise LexicalStorageError(f"lexical promotion journal has an invalid promotion ID: {path}")
    execution_id = str(raw["execution_id"])
    if not execution_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in execution_id
    ):
        raise LexicalStorageError(f"lexical promotion journal has an invalid execution ID: {path}")
    output_dir = _validate_output_path(Path(str(raw["output_dir"])))
    staging_dir = Path(str(raw["staging_dir"])).resolve()
    backup_dir = Path(str(raw["backup_dir"])).resolve()
    expected_parent = output_dir.parent
    if staging_dir.parent != expected_parent or not staging_dir.name.startswith(
        f".{output_dir.name}.writing-"
    ):
        raise LexicalStorageError("lexical promotion journal staging path is not governed")
    if backup_dir.parent != expected_parent or not backup_dir.name.startswith(
        f".{output_dir.name}.backup-"
    ):
        raise LexicalStorageError("lexical promotion journal backup path is not governed")
    return LexicalPromotionJournal(
        output_dir=output_dir,
        staging_dir=staging_dir,
        backup_dir=backup_dir,
        database_path=Path(str(raw["database_path"])).resolve(),
        execution_manifest_path=Path(str(raw["execution_manifest_path"])).resolve(),
        execution_id=execution_id,
        promotion_id=promotion_id,
        table_hash_manifest_sha256=manifest_sha256,
    )


def _archive_promotion_journal(path: Path, *, outcome: str) -> Path:
    if path.is_symlink():
        raise LexicalStorageError(f"refusing to archive symlinked promotion journal: {path}")
    if not outcome or any(character not in "abcdefghijklmnopqrstuvwxyz-" for character in outcome):
        raise LexicalStorageError(f"invalid lexical promotion journal outcome: {outcome}")
    destination = path.parent / (f".schema-v1.promotion-journal-{outcome}-{uuid4().hex}.json")
    if destination.exists() or destination.is_symlink():
        raise LexicalStorageError(f"promotion journal archive already exists: {destination}")
    try:
        path.replace(destination)
        _sync_directory(path.parent)
    except OSError as exc:
        raise LexicalStorageError(
            f"could not archive lexical promotion journal {path}: {exc}"
        ) from exc
    return destination


def _assert_promotion_execution_succeeded(journal: LexicalPromotionJournal) -> None:
    """Require the exact durable success sidecar before archiving active intent."""

    try:
        manifest = load_execution_manifest(journal.execution_manifest_path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise LexicalStorageError(
            "lexical promotion execution manifest is unreadable or invalid: "
            f"{journal.execution_manifest_path}: {exc}"
        ) from exc
    manifest_output = Path(manifest.artifact_output_directory)
    output_identity_matches = (
        not manifest_output.is_absolute()
        and ".." not in manifest_output.parts
        and any(
            (parent / manifest_output).resolve() == journal.output_dir
            for parent in journal.output_dir.parents
        )
    )
    if (
        manifest.execution_id != journal.execution_id
        or manifest.execution_status != "succeeded"
        or manifest.output_hash_manifest_sha256 != journal.table_hash_manifest_sha256
        or not output_identity_matches
    ):
        raise LexicalStorageError(
            "committed lexical promotion is awaiting its exact successful execution manifest"
        )


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
        resume_staging_dir: Path | None = None,
        preserve_staging_on_error: bool = False,
    ) -> None:
        self.output_dir = _validate_output_path(output_dir)
        if required_free_bytes < 0:
            raise LexicalStorageError("required_free_bytes cannot be negative")
        if duckdb_memory_limit_bytes < 1:
            raise LexicalStorageError("duckdb_memory_limit_bytes must be positive")
        self.output_dir.parent.mkdir(parents=True, exist_ok=True)
        pending_promotion = lexical_promotion_journal_path(self.output_dir)
        if pending_promotion.exists() or pending_promotion.is_symlink():
            raise LexicalStorageError(
                "an interrupted lexical promotion must be recovered before opening a writer: "
                f"{pending_promotion}"
            )
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
        self._write_token = token
        if resume_staging_dir is None:
            self.staging_dir = self.output_dir.parent / f".{self.output_dir.name}.writing-{token}"
        else:
            self.staging_dir = resume_staging_dir.resolve()
            expected_prefix = f".{self.output_dir.name}.writing-"
            if (
                self.staging_dir.parent != self.output_dir.parent
                or not self.staging_dir.name.startswith(expected_prefix)
                or not self.staging_dir.is_dir()
                or self.staging_dir.is_symlink()
            ):
                raise LexicalStorageError(
                    "resume staging must be an existing, non-symlinked governed sibling "
                    f"named {expected_prefix}*"
                )
        self.backup_dir = self.output_dir.parent / f".{self.output_dir.name}.backup-{token}"
        if resume_staging_dir is None:
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
        self._verify_existing_writes = resume_staging_dir is not None
        self._preserve_staging_on_error = (
            preserve_staging_on_error or resume_staging_dir is not None
        )
        self._promotion_pending = False
        self._promotion_journal_path: Path | None = None
        self._promotion_id: str | None = None
        self._closed = False
        if resume_staging_dir is not None:
            self._preserve_interrupted_writes()
            self._adopt_existing_state()

    def __enter__(self) -> LexicalArtifactWriter:
        return self

    @property
    def pending_promotion_id(self) -> str:
        """Return the nonce that the DuckDB transaction must durably witness."""

        if not self._promotion_pending or self._promotion_id is None:
            raise LexicalStorageError("no deferred lexical promotion ID is pending")
        return self._promotion_id

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._closed:
            if self._preserve_staging_on_error:
                self._closed = True
            else:
                self.abort()

    def _pending_path(self, target: Path) -> Path:
        return target.with_name(f".{target.name}.writing-{self._write_token}")

    def _write_parquet_atomically(self, target: Path, frame: pl.DataFrame) -> None:
        pending = self._pending_path(target)
        if pending.exists() or pending.is_symlink():
            raise LexicalStorageError(f"pending lexical write already exists: {pending}")
        frame.write_parquet(
            pending,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        pending.replace(target)

    def _write_bytes_atomically(self, target: Path, content: bytes) -> None:
        pending = self._pending_path(target)
        if pending.exists() or pending.is_symlink():
            raise LexicalStorageError(f"pending lexical write already exists: {pending}")
        pending.write_bytes(content)
        pending.replace(target)

    def _preserve_interrupted_writes(self) -> None:
        """Move recognized partial writes aside without deleting recovery evidence."""

        pending = sorted(
            path
            for path in self.staging_dir.rglob(".*.writing-*")
            if path.is_file() and ".writing-" in path.name
        )
        if not pending:
            return
        quarantine = (
            self.output_dir.parent
            / f".{self.output_dir.name}.interrupted-writes-{self._write_token}"
        )
        if quarantine.exists() or quarantine.is_symlink():
            raise LexicalStorageError(f"interrupted-write quarantine already exists: {quarantine}")
        for source in pending:
            relative = source.relative_to(self.staging_dir)
            destination = quarantine / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)

    def _adopt_existing_state(self) -> None:
        """Validate and register every governed leaf in an interrupted staging tree."""

        if (self.staging_dir / TABLE_HASH_FILE).exists():
            raise LexicalStorageError(
                "resume staging already contains a finalized table hash manifest"
            )
        metadata_root = self.staging_dir / "lexical_metadata"
        if metadata_root.exists():
            raise LexicalStorageError(
                "resume staging already contains lexical metadata and is not an "
                "interrupted pre-promotion build"
            )
        for name in LEXICAL_ARTIFACT_NAMES:
            if name == "lexical_metadata":
                continue
            root = self.staging_dir / name
            if not root.exists():
                continue
            if not root.is_dir() or root.is_symlink():
                raise LexicalStorageError(
                    f"resume artifact root is not a governed directory: {root}"
                )
            unexpected = [
                path
                for path in root.iterdir()
                if not path.is_file()
                or not path.name.startswith("part-")
                or path.suffix != ".parquet"
            ]
            if unexpected:
                raise LexicalStorageError(
                    f"resume artifact root contains unexpected entries: {unexpected[:5]}"
                )
            paths = sorted(root.glob("part-*.parquet"))
            for part, path in enumerate(paths):
                expected_name = f"part-{part:05d}.parquet"
                if path.name != expected_name:
                    raise LexicalStorageError(
                        f"{name} resume parts are not contiguous: "
                        f"expected={expected_name}, actual={path.name}"
                    )
                try:
                    observed = pl.read_parquet(path, rechunk=True)
                    prepared = _prepare_frame(name, observed)
                except (OSError, pl.exceptions.PolarsError) as exc:
                    raise LexicalStorageError(
                        f"could not adopt interrupted {name} leaf {path.name}: {exc}"
                    ) from exc
                if not observed.equals(prepared, null_equal=True):
                    raise LexicalStorageError(
                        f"interrupted {name} leaf is not in governed typed order: {path.name}"
                    )
                relative = Path(name) / path.name
                key = relative.as_posix()
                sort_columns = list(LEXICAL_ARTIFACT_SORT_COLUMNS[name])
                if prepared.height:
                    keys = prepared.select(sort_columns)
                    first_key = _comparable_sort_key(keys.row(0))
                    last_key = _comparable_sort_key(keys.row(-1))
                    previous = self._last_sort_keys.get(name)
                    if previous is not None and first_key < previous:
                        self._parts_globally_sorted[name] = False
                    self._last_sort_keys[name] = last_key
                logical_projection = prepared.select(_logical_columns(name))
                _update_logical_hasher(self._logical_hashers[name], logical_projection)
                self._leaves[name][key] = {
                    "row_count": prepared.height,
                    "parquet_sha256": sha256_file(path),
                    "logical_sha256": logical_frame_hash(
                        logical_projection,
                        sort_by=sort_columns,
                    ),
                }
                self._counts[name] += prepared.height
                del observed, prepared, logical_projection
        indexes_root = self.staging_dir / "indexes"
        if indexes_root.exists():
            if not indexes_root.is_dir() or indexes_root.is_symlink():
                raise LexicalStorageError("resume sparse-index root is not a directory")
            self._sparse_paths = {
                path.relative_to(indexes_root).as_posix()
                for path in indexes_root.rglob("*")
                if path.is_file()
            }

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
        relative = Path(name) / f"part-{part:05d}.parquet"
        key = relative.as_posix()
        prepared = _prepare_frame(name, frame)
        if key in self._leaves[name]:
            if not self._verify_existing_writes:
                raise LexicalStorageError(f"duplicate lexical artifact leaf: {key}")
            path = self.staging_dir / relative
            try:
                existing = _prepare_frame(name, pl.read_parquet(path, rechunk=True))
            except (OSError, pl.exceptions.PolarsError) as exc:
                raise LexicalStorageError(
                    f"could not verify resumed lexical artifact leaf {key}: {exc}"
                ) from exc
            logical_columns = _logical_columns(name)
            if not existing.select(logical_columns).equals(
                prepared.select(logical_columns), null_equal=True
            ):
                raise LexicalStorageError(
                    f"regenerated lexical artifact differs from resumed leaf: {key}"
                )
            return path
        expected_part = len(self._leaves[name])
        if part != expected_part:
            raise LexicalStorageError(
                f"{name} part numbers must be contiguous from zero; "
                f"expected={expected_part}, actual={part}"
            )
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
        self._write_parquet_atomically(path, prepared)
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
            target = self.staging_dir / "indexes" / relative_path
            if self._verify_existing_writes and target.read_bytes() == content:
                return target
            raise LexicalStorageError(f"duplicate sparse index path differs: {key}")
        self.check_free_disk(f"sparse:{key}:before")
        target = self.staging_dir / "indexes" / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_bytes_atomically(target, content)
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

    def finalize(
        self,
        metadata: pl.DataFrame,
        *,
        pre_promotion_validator: Callable[[Path], None] | None = None,
        defer_promotion_commit: bool = False,
        promotion_database_path: Path | None = None,
        promotion_execution_manifest_path: Path | None = None,
        promotion_execution_id: str | None = None,
    ) -> ProcessedLexical:
        """Seal and validate staged artifacts, then atomically promote the run."""

        if metadata.height != 1:
            raise LexicalStorageError("finalize requires exactly one lexical metadata row")
        if defer_promotion_commit and promotion_database_path is None:
            raise LexicalStorageError(
                "deferred lexical promotion requires its governed DuckDB database path"
            )
        if defer_promotion_commit and (
            promotion_execution_manifest_path is None or promotion_execution_id is None
        ):
            raise LexicalStorageError(
                "deferred lexical promotion requires its execution-manifest identity"
            )
        if not defer_promotion_commit and promotion_database_path is not None:
            raise LexicalStorageError(
                "promotion_database_path is valid only for deferred lexical promotion"
            )
        if not defer_promotion_commit and (
            promotion_execution_manifest_path is not None or promotion_execution_id is not None
        ):
            raise LexicalStorageError(
                "promotion execution identity is valid only for deferred lexical promotion"
            )
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
        self._write_parquet_atomically(path, prepared)
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
        self._write_bytes_atomically(
            self.staging_dir / TABLE_HASH_FILE,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        self.check_free_disk("finalize:staged")
        if pre_promotion_validator is not None:
            pre_promotion_validator(self.staging_dir)
            self.check_free_disk("finalize:validated")
        if defer_promotion_commit:
            assert promotion_database_path is not None
            assert promotion_execution_manifest_path is not None
            assert promotion_execution_id is not None
            if not promotion_database_path.is_file() or promotion_database_path.is_symlink():
                raise LexicalStorageError(
                    "deferred lexical promotion database is missing or unsafe: "
                    f"{promotion_database_path}"
                )
            if (
                not promotion_execution_manifest_path.is_file()
                or promotion_execution_manifest_path.is_symlink()
            ):
                raise LexicalStorageError(
                    "deferred lexical promotion execution manifest is missing or unsafe: "
                    f"{promotion_execution_manifest_path}"
                )
            promotion_id = uuid4().hex
            journal = LexicalPromotionJournal(
                output_dir=self.output_dir,
                staging_dir=self.staging_dir,
                backup_dir=self.backup_dir,
                database_path=promotion_database_path.resolve(strict=True),
                execution_manifest_path=promotion_execution_manifest_path.resolve(strict=True),
                execution_id=promotion_execution_id,
                promotion_id=promotion_id,
                table_hash_manifest_sha256=sha256_file(self.staging_dir / TABLE_HASH_FILE),
            )
            self._promotion_journal_path = _write_promotion_journal(journal)
            self._promotion_id = promotion_id
        try:
            if self.output_dir.exists():
                self.output_dir.replace(self.backup_dir)
            try:
                self.staging_dir.replace(self.output_dir)
                _sync_directory(self.output_dir.parent)
            except OSError:
                if self.backup_dir.exists() and not self.output_dir.exists():
                    self.backup_dir.replace(self.output_dir)
                    _sync_directory(self.output_dir.parent)
                raise
            self._promotion_pending = defer_promotion_commit
            if self.backup_dir.exists() and not defer_promotion_commit:
                shutil.rmtree(self.backup_dir)
        except OSError as exc:
            if self._preserve_staging_on_error:
                self._closed = True
            else:
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


def _lexical_catalog_sha256(connection: duckdb.DuckDBPyConnection) -> str:
    """Hash the exact governed artifact and convenience view definitions."""

    expected_names = set(DUCKDB_ARTIFACT_NAMES.values()) | set(LEXICAL_CONVENIENCE_VIEWS)
    definitions = {
        str(name): str(sql)
        for name, sql in connection.execute(
            "SELECT view_name, sql FROM duckdb_views() "
            "WHERE database_name = current_database() AND schema_name = 'main'"
        ).fetchall()
        if str(name) in expected_names
    }
    if set(definitions) != expected_names:
        missing = sorted(expected_names.difference(definitions))
        unexpected = sorted(set(definitions).difference(expected_names))
        raise LexicalStorageError(
            "lexical DuckDB exposure catalog is incomplete: "
            f"missing={missing}, unexpected={unexpected}"
        )
    encoded = json.dumps(definitions, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_lexical_duckdb(
    processed: ProcessedLexical,
    database_path: Path,
    *,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
    promotion_id: str,
    table_hash_manifest_sha256: str,
) -> None:
    """Transactionally expose only governed lexical Parquet and convenience views."""

    if len(promotion_id) != 32 or any(
        character not in "0123456789abcdef" for character in promotion_id
    ):
        raise LexicalStorageError("lexical DuckDB promotion ID must be 32 lowercase hex characters")
    if len(table_hash_manifest_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in table_hash_manifest_sha256
    ):
        raise LexicalStorageError("lexical table-hash manifest identity must be SHA-256")
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
                _drop_relation(connection, LEXICAL_PROMOTION_COMMIT_RELATION)
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
                    "CREATE VIEW lexical_directional_english_ablation AS "
                    "SELECT ranking_id, experiment_run_id, query_passage_id, "
                    "target_passage_id, corpus_pair, experiment_scope, analysis_profile, "
                    "query_reading, target_reading, granularity, representation_id, detector, "
                    "rank AS rank_before, raw_score AS score_before, "
                    "score_after_removing_all_english_features AS score_after, "
                    "rank_after_removing_all_english_features AS rank_after, "
                    "query_gloss_feature_count, target_gloss_feature_count, "
                    "query_gloss_coverage, target_gloss_coverage, gloss_overlap_count, "
                    "contains_english_derived_evidence, non_english_evidence_remains, "
                    "english_ablation_survives, classification_after_english_ablation "
                    "FROM lexical_directional_rankings "
                    "WHERE corpus_pair='hb_gnt_english_bridge'"
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
                catalog_sha256 = _lexical_catalog_sha256(connection)
                connection.execute(
                    f'CREATE TABLE "{LEXICAL_PROMOTION_COMMIT_RELATION}" ('
                    "promotion_id VARCHAR NOT NULL, "
                    "table_hash_manifest_sha256 VARCHAR NOT NULL, "
                    "catalog_sha256 VARCHAR NOT NULL)"
                )
                connection.execute(
                    f'INSERT INTO "{LEXICAL_PROMOTION_COMMIT_RELATION}" VALUES (?, ?, ?)',
                    [
                        promotion_id,
                        table_hash_manifest_sha256,
                        catalog_sha256,
                    ],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
    except (duckdb.Error, OSError, LexicalResourceError) as exc:
        raise LexicalStorageError(f"could not load lexical DuckDB {database_path}: {exc}") from exc


def _verified_promotion_artifact_root(
    root: Path,
    *,
    journal: LexicalPromotionJournal,
) -> None:
    if not root.is_dir() or root.is_symlink():
        raise LexicalStorageError(f"journaled lexical artifact root is missing or unsafe: {root}")
    manifest = root / TABLE_HASH_FILE
    if not manifest.is_file() or manifest.is_symlink():
        raise LexicalStorageError(
            f"journaled lexical hash manifest is missing or unsafe: {manifest}"
        )
    observed = sha256_file(manifest)
    if observed != journal.table_hash_manifest_sha256:
        raise LexicalStorageError(
            "journaled lexical hash manifest changed during interrupted promotion: "
            f"expected={journal.table_hash_manifest_sha256}, observed={observed}"
        )


def _database_has_committed_lexical_exposure(
    database_path: Path,
    journal: LexicalPromotionJournal,
) -> bool:
    """Classify the DuckDB side of a journal as wholly committed or wholly absent."""

    with (
        TemporaryDirectory(prefix="echoes-lexical-promotion-recovery-") as temporary,
        duckdb.connect(str(database_path), read_only=True) as connection,
    ):
        configure_duckdb_connection(
            connection,
            memory_limit_bytes=256 * 1024**2,
            temp_directory=Path(temporary) / "spill",
            thread_count=1,
        )
        marker_count_row = connection.execute(
            "SELECT count(*) FROM duckdb_tables() "
            "WHERE database_name = current_database() AND schema_name = 'main' "
            "AND table_name = ?",
            [LEXICAL_PROMOTION_COMMIT_RELATION],
        ).fetchone()
        marker_count = 0 if marker_count_row is None else int(marker_count_row[0])
        if marker_count == 0:
            return False
        if marker_count != 1:
            raise LexicalStorageError("DuckDB lexical promotion marker is ambiguous")
        marker_rows = connection.execute(
            f"SELECT promotion_id, table_hash_manifest_sha256, catalog_sha256 "
            f'FROM "{LEXICAL_PROMOTION_COMMIT_RELATION}"'
        ).fetchall()
        if len(marker_rows) != 1:
            raise LexicalStorageError("DuckDB lexical promotion marker must contain one row")
        marker_promotion_id, marker_manifest_sha256, marker_catalog_sha256 = (
            str(value) for value in marker_rows[0]
        )
        if marker_promotion_id != journal.promotion_id:
            return False
        if marker_manifest_sha256 != journal.table_hash_manifest_sha256:
            raise LexicalStorageError(
                "DuckDB promotion marker manifest hash differs from its durable journal"
            )
        observed_catalog_sha256 = _lexical_catalog_sha256(connection)
        if marker_catalog_sha256 != observed_catalog_sha256:
            raise LexicalStorageError(
                "DuckDB lexical view catalog changed after the promotion transaction"
            )
        definitions = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT view_name, sql FROM duckdb_views() "
                "WHERE database_name = current_database() AND schema_name = 'main'"
            ).fetchall()
        }
        exact_relations: list[str] = []
        for artifact, relation in DUCKDB_ARTIFACT_NAMES.items():
            definition = definitions.get(relation)
            if definition is None:
                continue
            expected_glob = (
                (journal.output_dir / artifact / "part-*.parquet").as_posix().replace("'", "''")
            )
            if expected_glob in definition:
                exact_relations.append(relation)
        if not exact_relations:
            return False
        missing_relations = sorted(set(DUCKDB_ARTIFACT_NAMES.values()).difference(definitions))
        missing_convenience = sorted(set(LEXICAL_CONVENIENCE_VIEWS).difference(definitions))
        if (
            len(exact_relations) != len(DUCKDB_ARTIFACT_NAMES)
            or missing_relations
            or missing_convenience
        ):
            raise LexicalStorageError(
                "interrupted DuckDB lexical exposure is neither wholly committed nor absent: "
                f"exact={len(exact_relations)}/{len(DUCKDB_ARTIFACT_NAMES)}, "
                f"missing_relations={missing_relations}, "
                f"missing_convenience={missing_convenience}"
            )
        for relation in DUCKDB_ARTIFACT_NAMES.values():
            connection.execute(f'SELECT 1 FROM "{relation}" LIMIT 1').fetchone()
        for relation in LEXICAL_CONVENIENCE_VIEWS:
            connection.execute(f'SELECT * FROM "{relation}" LIMIT 0')
    return True


def _matching_archived_promotion_journals(
    output_dir: Path,
    database_path: Path,
) -> list[LexicalPromotionJournal]:
    archives = sorted(
        (
            *output_dir.parent.glob(".schema-v1.promotion-journal-canonical-committed-*.json"),
            *output_dir.parent.glob(".schema-v1.promotion-journal-committed-*.json"),
        )
    )
    if not archives:
        return []
    if not database_path.is_file() or database_path.is_symlink():
        raise LexicalStorageError(
            "archived lexical promotion journal requires its governed database"
        )
    matching: list[LexicalPromotionJournal] = []
    try:
        for archive in archives:
            journal = _read_promotion_journal(archive)
            if journal.output_dir != output_dir or journal.database_path != database_path:
                continue
            if not _database_has_committed_lexical_exposure(database_path, journal):
                continue
            _verified_promotion_artifact_root(journal.output_dir, journal=journal)
            _assert_promotion_execution_succeeded(journal)
            matching.append(journal)
    except LexicalStorageError:
        raise
    except (duckdb.Error, OSError, LexicalResourceError) as exc:
        raise LexicalStorageError(
            f"could not authenticate archived lexical promotion state: {exc}"
        ) from exc
    if len(matching) > 1:
        raise LexicalStorageError(
            "multiple archived journals claim the current lexical promotion commit"
        )
    return matching


def read_current_lexical_promotion_witness(
    output_dir: Path,
    database_path: Path,
) -> LexicalPromotionJournal:
    """Read the active or archived journal that authenticates the current commit."""

    resolved_output = _validate_output_path(output_dir)
    resolved_database = database_path.resolve(strict=False)
    active_path = lexical_promotion_journal_path(resolved_output)
    if active_path.exists() or active_path.is_symlink():
        journal = _read_promotion_journal(active_path)
        if journal.output_dir != resolved_output:
            raise LexicalStorageError(
                "promotion journal output path does not match witness request"
            )
        if journal.database_path != resolved_database:
            raise LexicalStorageError(
                "promotion journal database path does not match witness request"
            )
        if (
            not resolved_database.is_file()
            or resolved_database.is_symlink()
            or not _database_has_committed_lexical_exposure(resolved_database, journal)
        ):
            raise LexicalStorageError(
                "active lexical promotion journal does not witness a committed exposure"
            )
        _verified_promotion_artifact_root(journal.output_dir, journal=journal)
        return journal

    matching = _matching_archived_promotion_journals(
        resolved_output,
        resolved_database,
    )
    if not matching:
        raise LexicalStorageError(
            "no active or archived journal witnesses the current lexical exposure"
        )
    return matching[0]


def recover_interrupted_lexical_promotion(
    output_dir: Path,
    database_path: Path,
    *,
    archive_committed: bool = False,
) -> PromotionRecoveryState:
    """Resolve a durable promotion journal without guessing across the DB boundary.

    A canonical tree is retained only when every governed lexical relation was
    committed against it. Otherwise the exact validated tree is moved back to
    its journaled staging path. Ambiguous state is preserved and rejected.
    """

    resolved_output = _validate_output_path(output_dir)
    journal_path = lexical_promotion_journal_path(resolved_output)
    if not journal_path.exists() and not journal_path.is_symlink():
        resolved_database = database_path.resolve(strict=False)
        matching = _matching_archived_promotion_journals(
            resolved_output,
            resolved_database,
        )
        return "canonical_committed" if matching else "no_journal"
    journal = _read_promotion_journal(journal_path)
    resolved_database = database_path.resolve(strict=False)
    if journal.output_dir != resolved_output:
        raise LexicalStorageError("promotion journal output path does not match recovery request")
    if journal.database_path != resolved_database:
        raise LexicalStorageError("promotion journal database path does not match recovery request")
    if (
        not resolved_database.is_file()
        or resolved_database.is_symlink()
        or not journal.execution_manifest_path.is_file()
        or journal.execution_manifest_path.is_symlink()
        or journal.staging_dir.is_symlink()
        or journal.output_dir.is_symlink()
        or journal.backup_dir.is_symlink()
    ):
        raise LexicalStorageError("promotion recovery encountered a missing or unsafe path")

    staging_exists = journal.staging_dir.exists()
    output_exists = journal.output_dir.exists()
    backup_exists = journal.backup_dir.exists()
    if backup_exists and not journal.backup_dir.is_dir():
        raise LexicalStorageError("journaled lexical backup is not a directory")

    try:
        if staging_exists:
            _verified_promotion_artifact_root(journal.staging_dir, journal=journal)
            if output_exists:
                if backup_exists:
                    raise LexicalStorageError(
                        "promotion recovery found staging, canonical, and backup simultaneously"
                    )
            elif backup_exists:
                journal.backup_dir.replace(journal.output_dir)
                _sync_directory(journal.output_dir.parent)
            _archive_promotion_journal(journal_path, outcome="staging-restored")
            return "staging_restored"

        if not output_exists:
            raise LexicalStorageError(
                "promotion journal exists but both canonical and staging artifacts are absent"
            )
        _verified_promotion_artifact_root(journal.output_dir, journal=journal)
        if _database_has_committed_lexical_exposure(
            resolved_database,
            journal,
        ):
            # A SIGKILL/OOM may arrive after DuckDB COMMIT but before the
            # in-process finalizer. The catalog and bounded reads are the durable
            # commit witness; a prior canonical backup remains preserved.
            if archive_committed:
                _assert_promotion_execution_succeeded(journal)
                _archive_promotion_journal(journal_path, outcome="canonical-committed")
            return "canonical_committed"

        journal.output_dir.replace(journal.staging_dir)
        if backup_exists:
            journal.backup_dir.replace(journal.output_dir)
        _sync_directory(journal.output_dir.parent)
        _archive_promotion_journal(journal_path, outcome="staging-restored")
        return "staging_restored"
    except LexicalStorageError:
        raise
    except (duckdb.Error, OSError, LexicalResourceError) as exc:
        raise LexicalStorageError(
            f"could not recover interrupted lexical promotion {journal_path}: {exc}"
        ) from exc
