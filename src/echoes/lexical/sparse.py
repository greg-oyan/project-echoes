"""Transparent deterministic sparse lexical indexes and blockwise retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt
from scipy import sparse

from echoes.lexical.sequences import PassageLexicalSequence
from echoes.manifest import sha256_file


class SparseIndexError(RuntimeError):
    """Raised when a governed sparse index cannot be built or queried."""


@dataclass(frozen=True, slots=True)
class SparseLexicalIndex:
    """Canonical count, binary, and explicit TF-IDF matrices."""

    representation_id: str
    family: str
    namespace: str
    passage_ids: tuple[str, ...]
    passage_corpora: tuple[str, ...]
    passage_books: tuple[str, ...]
    vocabulary: tuple[str, ...]
    counts: sparse.csr_matrix
    binary: sparse.csr_matrix
    tfidf: sparse.csr_matrix
    corpus_frequency: np.ndarray
    document_frequency: np.ndarray
    inverse_document_frequency: np.ndarray
    sublinear_tf: bool
    smooth_idf: bool
    l2_normalize: bool
    logical_hash: str


@dataclass(frozen=True, slots=True)
class SparseIndexFiles:
    """Physical files for one persisted sparse index."""

    root: Path
    files: dict[str, str]


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """One deterministic sparse first-stage retrieval hit."""

    query_index: int
    target_index: int
    score: float


class SparsePreparationResourceCheck(Protocol):
    """Fail-closed memory checkpoint used before retrieval precomputation."""

    def __call__(self, stage: str, *, estimated_additional_bytes: int = 0) -> None: ...


@dataclass(frozen=True, slots=True)
class PreparedSparseRetrieval:
    """Invariant sparse detector state cached for one fixed target population."""

    passage_ids: tuple[str, ...]
    index_logical_hash: str
    target_indices: npt.NDArray[np.int64]
    maximum_proposal_document_frequency: int
    maximum_corpus_frequency: int
    bm25_k1: float
    bm25_b: float
    tfidf_query_matrix: sparse.csr_matrix
    overlap_query_matrix: sparse.csr_matrix
    bm25_query_matrix: sparse.csr_matrix
    rare_query_matrix: sparse.csr_matrix
    tfidf_target_transpose: sparse.csc_matrix
    overlap_target_transpose: sparse.csc_matrix
    bm25_target_transpose: sparse.csc_matrix
    rare_target_transpose: sparse.csc_matrix


def namespaced_feature(namespace: str, family: str, value: str) -> str:
    """Build a stable, unambiguous feature string."""

    if namespace not in {"hb", "gk", "en"}:
        raise SparseIndexError(f"unsupported feature namespace: {namespace}")
    if not family or not value:
        raise SparseIndexError("feature family and value must be nonempty")
    return f"{namespace}:{family}:{value}"


def _validate_index(index: SparseLexicalIndex) -> None:
    """Fail closed on malformed or cross-language sparse index state."""

    row_count = len(index.passage_ids)
    column_count = len(index.vocabulary)
    shape = (row_count, column_count)
    if (
        len(set(index.passage_ids)) != row_count
        or tuple(sorted(index.passage_ids)) != index.passage_ids
    ):
        raise SparseIndexError("sparse index passage IDs must be unique and canonically sorted")
    if len(index.passage_corpora) != row_count or len(index.passage_books) != row_count:
        raise SparseIndexError("sparse index passage metadata lengths do not match its rows")
    if (
        len(set(index.vocabulary)) != column_count
        or tuple(sorted(index.vocabulary)) != index.vocabulary
    ):
        raise SparseIndexError("sparse index vocabulary must be unique and canonically sorted")
    prefix = f"{index.namespace}:{index.family}:"
    if any(not feature.startswith(prefix) or feature == prefix for feature in index.vocabulary):
        raise SparseIndexError("sparse index vocabulary violates its language/family namespace")
    if index.namespace == "hb" and set(index.passage_corpora).difference({"hebrew"}):
        raise SparseIndexError("hb sparse indexes may contain only Hebrew passages")
    if index.namespace == "gk" and set(index.passage_corpora).difference({"greek"}):
        raise SparseIndexError("gk sparse indexes may contain only Greek passages")
    if index.namespace == "en" and index.family != "english_gloss":
        raise SparseIndexError("the en namespace is restricted to English gloss indexes")
    for name, matrix in (
        ("counts", index.counts),
        ("binary", index.binary),
        ("tfidf", index.tfidf),
    ):
        if not sparse.isspmatrix_csr(matrix) or matrix.shape != shape:
            raise SparseIndexError(f"{name} must be a CSR matrix with shape {shape}")
        if matrix.dtype != np.dtype(np.float64):
            raise SparseIndexError(f"{name} must use float64")
        if not matrix.has_sorted_indices or not matrix.has_canonical_format:
            raise SparseIndexError(f"{name} CSR structure must be sorted and canonical")
        if matrix.nnz and not np.isfinite(matrix.data).all():
            raise SparseIndexError(f"{name} contains a non-finite value")
    if index.counts.nnz and (index.counts.data <= 0.0).any():
        raise SparseIndexError("count matrix values must be positive")
    if index.counts.nnz and not np.equal(index.counts.data, np.floor(index.counts.data)).all():
        raise SparseIndexError("count matrix values must be whole-number counts")
    if index.binary.nnz and not np.equal(index.binary.data, 1.0).all():
        raise SparseIndexError("binary matrix values must all equal one")
    if any(
        type(flag) is not bool
        for flag in (index.sublinear_tf, index.smooth_idf, index.l2_normalize)
    ):
        raise SparseIndexError("TF-IDF configuration flags must be booleans")
    for name, values in (
        ("corpus_frequency", index.corpus_frequency),
        ("document_frequency", index.document_frequency),
        ("inverse_document_frequency", index.inverse_document_frequency),
    ):
        if values.ndim != 1 or len(values) != column_count:
            raise SparseIndexError(f"{name} length does not match sparse index columns")
        if not np.isfinite(values).all():
            raise SparseIndexError(f"{name} contains a non-finite value")
    if index.corpus_frequency.dtype != np.dtype(np.int64):
        raise SparseIndexError("corpus_frequency must use int64")
    if index.document_frequency.dtype != np.dtype(np.int64):
        raise SparseIndexError("document_frequency must use int64")
    if index.inverse_document_frequency.dtype != np.dtype(np.float64):
        raise SparseIndexError("inverse_document_frequency must use float64")
    expected_binary = index.counts.copy()
    if expected_binary.nnz:
        expected_binary.data.fill(1.0)
    if (
        not np.array_equal(index.binary.indptr, expected_binary.indptr)
        or not np.array_equal(index.binary.indices, expected_binary.indices)
        or not np.array_equal(index.binary.data, expected_binary.data)
    ):
        raise SparseIndexError("binary matrix does not reproduce from the count matrix")
    expected_corpus_frequency = np.asarray(index.counts.sum(axis=0)).reshape(-1).astype(np.int64)
    expected_document_frequency = (
        np.asarray(expected_binary.sum(axis=0)).reshape(-1).astype(np.int64)
    )
    if not np.array_equal(index.corpus_frequency, expected_corpus_frequency):
        raise SparseIndexError("corpus_frequency does not reproduce from the count matrix")
    if not np.array_equal(index.document_frequency, expected_document_frequency):
        raise SparseIndexError("document_frequency does not reproduce from the count matrix")
    expected_tfidf, expected_idf = _explicit_tfidf(
        index.counts,
        index.document_frequency,
        sublinear_tf=index.sublinear_tf,
        smooth_idf=index.smooth_idf,
        l2_normalize=index.l2_normalize,
    )
    if (
        not np.array_equal(index.tfidf.indptr, expected_tfidf.indptr)
        or not np.array_equal(index.tfidf.indices, expected_tfidf.indices)
        or not np.array_equal(index.tfidf.data, expected_tfidf.data)
        or not np.array_equal(index.inverse_document_frequency, expected_idf)
    ):
        raise SparseIndexError("TF-IDF values do not reproduce from the governed formula")
    logical = _matrix_logical_hash(
        passage_ids=index.passage_ids,
        vocabulary=index.vocabulary,
        matrix=index.counts,
    )
    if logical != index.logical_hash:
        raise SparseIndexError("sparse index logical hash does not reproduce")


def _matrix_logical_hash(
    *,
    passage_ids: Sequence[str],
    vocabulary: Sequence[str],
    matrix: sparse.csr_matrix,
) -> str:
    canonical = matrix.copy().astype(np.float64)
    canonical.sort_indices()
    digest = hashlib.sha256()
    digest.update(json.dumps(list(passage_ids), ensure_ascii=False, separators=(",", ":")).encode())
    digest.update(json.dumps(list(vocabulary), ensure_ascii=False, separators=(",", ":")).encode())
    digest.update(np.asarray(canonical.shape, dtype="<i8").tobytes())
    digest.update(np.asarray(canonical.indptr, dtype="<i8").tobytes())
    digest.update(np.asarray(canonical.indices, dtype="<i8").tobytes())
    digest.update(np.asarray(canonical.data, dtype="<f8").tobytes())
    return digest.hexdigest()


def _explicit_tfidf(
    counts: sparse.csr_matrix,
    document_frequency: np.ndarray,
    *,
    sublinear_tf: bool,
    smooth_idf: bool,
    l2_normalize: bool,
) -> tuple[sparse.csr_matrix, np.ndarray]:
    n_documents = counts.shape[0]
    tfidf = counts.astype(np.float64).copy()
    if sublinear_tf and tfidf.nnz:
        tfidf.data = 1.0 + np.log(tfidf.data)
    if smooth_idf:
        idf = np.log((1.0 + n_documents) / (1.0 + document_frequency)) + 1.0
    else:
        safe = np.maximum(document_frequency, 1)
        idf = np.log(n_documents / safe) + 1.0
    tfidf = sparse.csr_matrix(tfidf.multiply(idf), dtype=np.float64)
    if l2_normalize:
        norms = np.sqrt(np.asarray(tfidf.multiply(tfidf).sum(axis=1)).reshape(-1))
        inverse = np.zeros_like(norms)
        nonzero = norms > 0
        inverse[nonzero] = 1.0 / norms[nonzero]
        tfidf = sparse.diags(inverse, dtype=np.float64).dot(tfidf).tocsr()
    tfidf.sort_indices()
    return tfidf, np.asarray(idf, dtype=np.float64)


def build_sparse_index(
    sequences: Sequence[PassageLexicalSequence],
    *,
    representation_id: str,
    family: str,
    namespace: str,
    sublinear_tf: bool = True,
    smooth_idf: bool = True,
    l2_normalize: bool = True,
) -> SparseLexicalIndex:
    """Build one canonical CSR index without creating a dense matrix."""

    ordered = sorted(sequences, key=lambda item: item.passage_id)
    if len({item.passage_id for item in ordered}) != len(ordered):
        raise SparseIndexError("duplicate passage IDs in sparse index input")
    if not representation_id:
        raise SparseIndexError("representation_id must be nonempty")
    if namespace not in {"hb", "gk", "en"}:
        raise SparseIndexError(f"unsupported feature namespace: {namespace}")
    if namespace == "en" and family != "english_gloss":
        raise SparseIndexError("English-derived indexes must use the english_gloss family")
    if namespace != "en" and family == "english_gloss":
        raise SparseIndexError("English gloss indexes must use the en namespace")
    expected_corpus = {"hb": "hebrew", "gk": "greek"}.get(namespace)
    if expected_corpus is not None and any(item.corpus != expected_corpus for item in ordered):
        raise SparseIndexError(f"{namespace} index contains a passage from another corpus")
    if namespace == "en":
        if len({(item.analysis_profile, item.granularity) for item in ordered}) > 1:
            raise SparseIndexError("one sparse index cannot mix profiles or granularities")
        reading_scopes = {(item.corpus, item.analysis_reading) for item in ordered}
        if any(
            (corpus == "hebrew" and reading not in {"qere", "ketiv"})
            or (corpus == "greek" and reading != "source")
            for corpus, reading in reading_scopes
        ):
            raise SparseIndexError("English gloss index contains an invalid corpus reading")
    elif (
        len({(item.analysis_profile, item.analysis_reading, item.granularity) for item in ordered})
        > 1
    ):
        raise SparseIndexError("one sparse index cannot mix profiles, readings, or granularities")
    all_features: set[str] = set()
    for passage in ordered:
        values = [namespaced_feature(namespace, family, value) for value in passage.values(family)]
        all_features.update(values)
    vocabulary = tuple(sorted(all_features))
    columns = {value: index for index, value in enumerate(vocabulary)}
    rows: list[int] = []
    column_indices: list[int] = []
    data: list[float] = []
    for row_index, passage in enumerate(ordered):
        feature_counts = Counter(
            namespaced_feature(namespace, family, value) for value in passage.values(family)
        )
        for value, count in sorted(feature_counts.items(), key=lambda item: columns[item[0]]):
            rows.append(row_index)
            column_indices.append(columns[value])
            data.append(float(count))
    shape = (len(ordered), len(vocabulary))
    counts_matrix = sparse.coo_matrix(
        (
            np.asarray(data, dtype=np.float64),
            (
                np.asarray(rows, dtype=np.int64),
                np.asarray(column_indices, dtype=np.int64),
            ),
        ),
        shape=shape,
        dtype=np.float64,
    ).tocsr()
    counts_matrix.sort_indices()
    binary = counts_matrix.copy()
    if binary.nnz:
        binary.data.fill(1.0)
    corpus_frequency = np.asarray(counts_matrix.sum(axis=0)).reshape(-1).astype(np.int64)
    document_frequency = np.asarray(binary.sum(axis=0)).reshape(-1).astype(np.int64)
    tfidf, idf = _explicit_tfidf(
        counts_matrix,
        document_frequency,
        sublinear_tf=sublinear_tf,
        smooth_idf=smooth_idf,
        l2_normalize=l2_normalize,
    )
    passage_ids = tuple(item.passage_id for item in ordered)
    logical_hash = _matrix_logical_hash(
        passage_ids=passage_ids,
        vocabulary=vocabulary,
        matrix=counts_matrix,
    )
    result = SparseLexicalIndex(
        representation_id=representation_id,
        family=family,
        namespace=namespace,
        passage_ids=passage_ids,
        passage_corpora=tuple(item.corpus for item in ordered),
        passage_books=tuple(item.book for item in ordered),
        vocabulary=vocabulary,
        counts=counts_matrix,
        binary=binary,
        tfidf=tfidf,
        corpus_frequency=corpus_frequency,
        document_frequency=document_frequency,
        inverse_document_frequency=idf,
        sublinear_tf=sublinear_tf,
        smooth_idf=smooth_idf,
        l2_normalize=l2_normalize,
        logical_hash=logical_hash,
    )
    _validate_index(result)
    return result


_SPARSE_ARRAY_FILES = (
    "counts-data.npy",
    "counts-indices.npy",
    "counts-indptr.npy",
    "tfidf-data.npy",
    "tfidf-indices.npy",
    "tfidf-indptr.npy",
    "shape.npy",
    "corpus-frequency.npy",
    "document-frequency.npy",
    "idf.npy",
)


def _write_sparse_directory(index: SparseLexicalIndex, root: Path) -> None:
    root.mkdir()
    arrays: dict[str, np.ndarray] = {
        "counts-data.npy": np.asarray(index.counts.data, dtype="<f8"),
        "counts-indices.npy": np.asarray(index.counts.indices, dtype="<i8"),
        "counts-indptr.npy": np.asarray(index.counts.indptr, dtype="<i8"),
        "tfidf-data.npy": np.asarray(index.tfidf.data, dtype="<f8"),
        "tfidf-indices.npy": np.asarray(index.tfidf.indices, dtype="<i8"),
        "tfidf-indptr.npy": np.asarray(index.tfidf.indptr, dtype="<i8"),
        "shape.npy": np.asarray(index.counts.shape, dtype="<i8"),
        "corpus-frequency.npy": np.asarray(index.corpus_frequency, dtype="<i8"),
        "document-frequency.npy": np.asarray(index.document_frequency, dtype="<i8"),
        "idf.npy": np.asarray(index.inverse_document_frequency, dtype="<f8"),
    }
    for filename, array in arrays.items():
        with (root / filename).open("wb") as handle:
            np.lib.format.write_array(handle, array, allow_pickle=False)
    metadata = {
        "representation_id": index.representation_id,
        "family": index.family,
        "namespace": index.namespace,
        "passage_ids": list(index.passage_ids),
        "passage_corpora": list(index.passage_corpora),
        "passage_books": list(index.passage_books),
        "vocabulary": list(index.vocabulary),
        "logical_hash": index.logical_hash,
        "dtype": "float64",
        "storage_format": "canonical-npy-csr-v1",
        "sublinear_tf": index.sublinear_tf,
        "smooth_idf": index.smooth_idf,
        "l2_normalize": index.l2_normalize,
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def persist_sparse_index(
    index: SparseLexicalIndex,
    root: Path,
    *,
    force: bool = False,
) -> SparseIndexFiles:
    """Atomically persist deterministic arrays without silent overwrite."""

    _validate_index(index)
    resolved = root.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and not resolved.is_dir():
        raise SparseIndexError(f"sparse index output exists and is not a directory: {resolved}")
    if resolved.exists() and not force:
        raise SparseIndexError(f"refusing to overwrite sparse index {resolved}; pass force=True")
    staging = Path(tempfile.mkdtemp(prefix=f".{resolved.name}.writing-", dir=resolved.parent))
    backup = staging.with_name(staging.name.replace(".writing-", ".backup-", 1))
    staging.rmdir()
    try:
        _write_sparse_directory(index, staging)
        if resolved.exists():
            resolved.replace(backup)
        try:
            staging.replace(resolved)
        except OSError:
            if backup.exists() and not resolved.exists():
                backup.replace(resolved)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except OSError as exc:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and not resolved.exists():
            backup.replace(resolved)
        raise SparseIndexError(f"could not persist sparse index {resolved}: {exc}") from exc
    files = {path.name: sha256_file(path) for path in sorted(resolved.iterdir()) if path.is_file()}
    return SparseIndexFiles(root=resolved, files=files)


def _load_npy(root: Path, filename: str) -> npt.NDArray[np.generic]:
    try:
        value = cast(npt.NDArray[np.generic], np.load(root / filename, allow_pickle=False))
    except (OSError, ValueError) as exc:
        raise SparseIndexError(f"could not read sparse array {filename}: {exc}") from exc
    return value


def _read_float64(root: Path, filename: str) -> npt.NDArray[np.float64]:
    value = _load_npy(root, filename)
    if value.dtype != np.dtype("<f8"):
        raise SparseIndexError(f"sparse array {filename} has dtype {value.dtype}, expected float64")
    return cast(npt.NDArray[np.float64], value)


def _read_int64(root: Path, filename: str) -> npt.NDArray[np.int64]:
    value = _load_npy(root, filename)
    if value.dtype != np.dtype("<i8"):
        raise SparseIndexError(f"sparse array {filename} has dtype {value.dtype}, expected int64")
    return cast(npt.NDArray[np.int64], value)


def load_sparse_index(root: Path) -> SparseLexicalIndex:
    """Load and fully validate one canonical persisted sparse index."""

    resolved = root.resolve()
    expected_files = {*_SPARSE_ARRAY_FILES, "metadata.json"}
    actual_files = (
        {path.name for path in resolved.iterdir() if path.is_file()} if resolved.is_dir() else set()
    )
    if actual_files != expected_files:
        raise SparseIndexError(
            f"sparse index file set differs from schema; expected={sorted(expected_files)}, "
            f"actual={sorted(actual_files)}"
        )
    try:
        metadata = json.loads((resolved / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SparseIndexError(f"could not read sparse index metadata: {exc}") from exc
    if not isinstance(metadata, dict) or metadata.get("storage_format") != "canonical-npy-csr-v1":
        raise SparseIndexError("sparse index metadata has an unsupported format")
    for flag in ("sublinear_tf", "smooth_idf", "l2_normalize"):
        if type(metadata.get(flag)) is not bool:
            raise SparseIndexError(f"sparse index metadata {flag} must be a boolean")
    shape_array = _read_int64(resolved, "shape.npy")
    if shape_array.shape != (2,) or (shape_array < 0).any():
        raise SparseIndexError("sparse index shape must contain two nonnegative dimensions")
    shape = (int(shape_array[0]), int(shape_array[1]))
    counts = sparse.csr_matrix(
        (
            _read_float64(resolved, "counts-data.npy"),
            _read_int64(resolved, "counts-indices.npy"),
            _read_int64(resolved, "counts-indptr.npy"),
        ),
        shape=shape,
        dtype=np.float64,
    )
    tfidf = sparse.csr_matrix(
        (
            _read_float64(resolved, "tfidf-data.npy"),
            _read_int64(resolved, "tfidf-indices.npy"),
            _read_int64(resolved, "tfidf-indptr.npy"),
        ),
        shape=shape,
        dtype=np.float64,
    )
    counts.sort_indices()
    tfidf.sort_indices()
    binary = counts.copy()
    if binary.nnz:
        binary.data.fill(1.0)
    try:
        index = SparseLexicalIndex(
            representation_id=str(metadata["representation_id"]),
            family=str(metadata["family"]),
            namespace=str(metadata["namespace"]),
            passage_ids=tuple(str(value) for value in metadata["passage_ids"]),
            passage_corpora=tuple(str(value) for value in metadata["passage_corpora"]),
            passage_books=tuple(str(value) for value in metadata["passage_books"]),
            vocabulary=tuple(str(value) for value in metadata["vocabulary"]),
            counts=counts,
            binary=binary,
            tfidf=tfidf,
            corpus_frequency=_read_int64(resolved, "corpus-frequency.npy"),
            document_frequency=_read_int64(resolved, "document-frequency.npy"),
            inverse_document_frequency=_read_float64(resolved, "idf.npy"),
            sublinear_tf=metadata["sublinear_tf"],
            smooth_idf=metadata["smooth_idf"],
            l2_normalize=metadata["l2_normalize"],
            logical_hash=str(metadata["logical_hash"]),
        )
    except (KeyError, TypeError) as exc:
        raise SparseIndexError(f"sparse index metadata is incomplete: {exc}") from exc
    _validate_index(index)
    return index


def _selected_indices(
    values: Iterable[int] | None,
    *,
    passage_count: int,
    name: str,
) -> npt.NDArray[np.int64]:
    selected = list(range(passage_count)) if values is None else list(values)
    if len(selected) != len(set(selected)):
        raise SparseIndexError(f"{name} indices must be unique")
    if any(isinstance(value, bool) or value < 0 or value >= passage_count for value in selected):
        raise SparseIndexError(f"{name} index is outside the sparse index row range")
    return np.asarray(selected, dtype=np.int64)


def _csr_storage_bytes(matrix: sparse.csr_matrix) -> int:
    """Return the exact bytes owned by one canonical CSR structure."""

    return int(matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes)


def _prepared_sparse_reservation_bytes(index: SparseLexicalIndex) -> int:
    """Conservatively bound cached matrices and their largest construction transient."""

    largest_matrix = max(
        _csr_storage_bytes(index.counts),
        _csr_storage_bytes(index.binary),
        _csr_storage_bytes(index.tfidf),
    )
    vector_bytes = int(
        index.corpus_frequency.nbytes
        + index.document_frequency.nbytes
        + index.inverse_document_frequency.nbytes
        + index.counts.shape[0] * np.dtype(np.float64).itemsize
    )
    # At most seven cached CSR/CSC structures and two construction transients coexist.
    # A tenth matrix-equivalent leaves headroom for SciPy indexing work arrays.
    return max(64 * 1024**2, largest_matrix * 10 + vector_bytes * 4)


def prepare_sparse_retrieval(
    index: SparseLexicalIndex,
    *,
    target_indices: Iterable[int] | None,
    maximum_proposal_document_frequency: int,
    maximum_corpus_frequency: int,
    k1: float,
    b: float,
    resource_check: SparsePreparationResourceCheck | None = None,
    resource_stage: str = "retrieval:sparse-preparation",
) -> PreparedSparseRetrieval:
    """Build invariant detector matrices once for all query blocks in one direction."""

    if maximum_proposal_document_frequency < 1:
        raise SparseIndexError("maximum proposal document frequency must be positive")
    if maximum_corpus_frequency < 1:
        raise SparseIndexError("maximum rare-feature corpus frequency must be positive")
    if not math.isfinite(k1) or k1 <= 0.0:
        raise SparseIndexError("BM25 k1 must be finite and positive")
    if not math.isfinite(b) or not 0.0 <= b <= 1.0:
        raise SparseIndexError("BM25 b must be finite and in [0, 1]")
    if not resource_stage:
        raise SparseIndexError("sparse preparation resource stage must be nonempty")
    targets = _selected_indices(
        target_indices,
        passage_count=len(index.passage_ids),
        name="target",
    )
    if resource_check is not None:
        resource_check(
            resource_stage,
            estimated_additional_bytes=_prepared_sparse_reservation_bytes(index),
        )

    proposal_mask = index.document_frequency <= maximum_proposal_document_frequency
    tfidf = index.tfidf[:, proposal_mask].tocsr()
    overlap = index.binary[:, proposal_mask].astype(np.float64).tocsr()

    counts = index.counts[:, proposal_mask].astype(np.float64).tocsr()
    lengths = np.asarray(index.counts.sum(axis=1)).reshape(-1)
    average_length = float(lengths.mean()) if len(lengths) else 0.0
    bm25_weighted = counts.copy()
    if average_length > 0.0:
        selected_df = index.document_frequency[proposal_mask]
        document_count = index.counts.shape[0]
        idf = np.log(1.0 + (document_count - selected_df + 0.5) / (selected_df + 0.5))
        for row in range(bm25_weighted.shape[0]):
            start = int(bm25_weighted.indptr[row])
            end = int(bm25_weighted.indptr[row + 1])
            if start == end:
                continue
            values = bm25_weighted.data[start:end]
            columns = bm25_weighted.indices[start:end]
            normalization = k1 * (1.0 - b + b * lengths[row] / average_length)
            bm25_weighted.data[start:end] = (
                idf[columns] * values * (k1 + 1.0) / (values + normalization)
            )

    rare_mask = (index.corpus_frequency > 0) & (index.corpus_frequency <= maximum_corpus_frequency)
    rare = index.binary[:, rare_mask].astype(np.float64).tocsr()
    if rare.shape[1]:
        rare_weights = 1.0 / index.corpus_frequency[rare_mask].astype(np.float64)
        rare_weighted = sparse.csr_matrix(rare.multiply(rare_weights), dtype=np.float64)
    else:
        rare_weighted = rare

    prepared = PreparedSparseRetrieval(
        passage_ids=index.passage_ids,
        index_logical_hash=index.logical_hash,
        target_indices=targets,
        maximum_proposal_document_frequency=maximum_proposal_document_frequency,
        maximum_corpus_frequency=maximum_corpus_frequency,
        bm25_k1=k1,
        bm25_b=b,
        tfidf_query_matrix=tfidf,
        overlap_query_matrix=overlap,
        bm25_query_matrix=overlap,
        rare_query_matrix=rare,
        tfidf_target_transpose=tfidf[targets].transpose(),
        overlap_target_transpose=overlap[targets].transpose(),
        bm25_target_transpose=bm25_weighted[targets].transpose(),
        rare_target_transpose=rare_weighted[targets].transpose(),
    )
    prepared.target_indices.setflags(write=False)
    return prepared


def retrieve_top_tfidf(
    index: SparseLexicalIndex,
    *,
    query_indices: Iterable[int] | None = None,
    target_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    maximum_proposal_document_frequency: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    """Retrieve blockwise from a DF-pruned sparse matrix with stable tie breaking."""

    if top_k < 1 or block_size < 1:
        raise SparseIndexError("top_k and block_size must be positive")
    if maximum_proposal_document_frequency < 1:
        raise SparseIndexError("maximum proposal document frequency must be positive")
    mask = index.document_frequency <= maximum_proposal_document_frequency
    return _retrieve_matrix_product(
        passage_ids=index.passage_ids,
        query_matrix=index.tfidf[:, mask].tocsr(),
        target_matrix=index.tfidf[:, mask].tocsr(),
        query_indices=query_indices,
        target_indices=target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def _retrieve_matrix_product(
    *,
    passage_ids: Sequence[str],
    query_matrix: sparse.csr_matrix,
    target_matrix: sparse.csr_matrix,
    query_indices: Iterable[int] | None,
    target_indices: Iterable[int] | None,
    top_k: int,
    block_size: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    if top_k < 1 or block_size < 1:
        raise SparseIndexError("top_k and block_size must be positive")
    if quantization_decimals < 0 or quantization_decimals > 15:
        raise SparseIndexError("quantization_decimals must be in [0, 15]")
    if query_matrix.shape != target_matrix.shape:
        raise SparseIndexError("query and target matrices must have identical shapes")
    if query_matrix.shape[0] != len(passage_ids):
        raise SparseIndexError("matrix rows do not match passage IDs")

    queries = _selected_indices(query_indices, passage_count=len(passage_ids), name="query")
    targets = _selected_indices(target_indices, passage_count=len(passage_ids), name="target")
    if query_matrix.shape[1] == 0:
        return []
    return _retrieve_prepared_matrix_product(
        passage_ids=passage_ids,
        query_matrix=query_matrix,
        target_transpose=target_matrix[targets].transpose(),
        queries=queries,
        targets=targets,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def _retrieve_prepared_matrix_product(
    *,
    passage_ids: Sequence[str],
    query_matrix: sparse.csr_matrix,
    target_transpose: sparse.csc_matrix,
    queries: npt.NDArray[np.int64],
    targets: npt.NDArray[np.int64],
    top_k: int,
    block_size: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    if top_k < 1 or block_size < 1:
        raise SparseIndexError("top_k and block_size must be positive")
    if quantization_decimals < 0 or quantization_decimals > 15:
        raise SparseIndexError("quantization_decimals must be in [0, 15]")
    if query_matrix.shape[0] != len(passage_ids):
        raise SparseIndexError("matrix rows do not match passage IDs")
    if query_matrix.shape[1] != target_transpose.shape[0]:
        raise SparseIndexError("query and prepared target feature dimensions differ")
    if target_transpose.shape[1] != len(targets):
        raise SparseIndexError("prepared target columns do not match target indices")
    if query_matrix.shape[1] == 0:
        return []

    hits: list[RetrievalHit] = []
    for start in range(0, len(queries), block_size):
        block_queries = queries[start : start + block_size]
        product = query_matrix[block_queries].dot(target_transpose).tocsr()
        for local_row, query_index_raw in enumerate(block_queries):
            query_index = int(query_index_raw)
            row_start = int(product.indptr[local_row])
            row_end = int(product.indptr[local_row + 1])
            candidates: list[tuple[float, str, int]] = []
            for position, score_raw in zip(
                product.indices[row_start:row_end],
                product.data[row_start:row_end],
                strict=True,
            ):
                target_index = int(targets[int(position)])
                if exclude_self and query_index == target_index:
                    continue
                score = round(float(score_raw), quantization_decimals)
                if not math.isfinite(score) or score <= 0.0:
                    continue
                candidates.append((-score, passage_ids[target_index], target_index))
            candidates.sort()
            for negative_score, _, target_index in candidates[:top_k]:
                hits.append(
                    RetrievalHit(
                        query_index=query_index,
                        target_index=target_index,
                        score=-negative_score,
                    )
                )
    return hits


def _prepared_queries(
    prepared: PreparedSparseRetrieval,
    query_indices: Iterable[int] | None,
) -> npt.NDArray[np.int64]:
    return _selected_indices(
        query_indices,
        passage_count=len(prepared.passage_ids),
        name="query",
    )


def retrieve_prepared_tfidf(
    prepared: PreparedSparseRetrieval,
    *,
    query_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    """Retrieve TF-IDF hits without rebuilding invariant sparse matrices."""

    return _retrieve_prepared_matrix_product(
        passage_ids=prepared.passage_ids,
        query_matrix=prepared.tfidf_query_matrix,
        target_transpose=prepared.tfidf_target_transpose,
        queries=_prepared_queries(prepared, query_indices),
        targets=prepared.target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def retrieve_prepared_overlap(
    prepared: PreparedSparseRetrieval,
    *,
    query_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    """Retrieve overlap hits without rebuilding invariant sparse matrices."""

    return _retrieve_prepared_matrix_product(
        passage_ids=prepared.passage_ids,
        query_matrix=prepared.overlap_query_matrix,
        target_transpose=prepared.overlap_target_transpose,
        queries=_prepared_queries(prepared, query_indices),
        targets=prepared.target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def retrieve_prepared_bm25(
    prepared: PreparedSparseRetrieval,
    *,
    query_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    """Retrieve BM25 hits without recomputing corpus-wide document weights."""

    return _retrieve_prepared_matrix_product(
        passage_ids=prepared.passage_ids,
        query_matrix=prepared.bm25_query_matrix,
        target_transpose=prepared.bm25_target_transpose,
        queries=_prepared_queries(prepared, query_indices),
        targets=prepared.target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def retrieve_prepared_rare(
    prepared: PreparedSparseRetrieval,
    *,
    query_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    """Retrieve rare-feature hits without rebuilding inverse-frequency weights."""

    return _retrieve_prepared_matrix_product(
        passage_ids=prepared.passage_ids,
        query_matrix=prepared.rare_query_matrix,
        target_transpose=prepared.rare_target_transpose,
        queries=_prepared_queries(prepared, query_indices),
        targets=prepared.target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def retrieve_top_overlap(
    index: SparseLexicalIndex,
    *,
    query_indices: Iterable[int] | None = None,
    target_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    maximum_proposal_document_frequency: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    """Retrieve by sparse shared-feature count before exact Jaccard reranking."""

    if maximum_proposal_document_frequency < 1:
        raise SparseIndexError("maximum proposal document frequency must be positive")
    mask = index.document_frequency <= maximum_proposal_document_frequency
    matrix = index.binary[:, mask].tocsr()
    return _retrieve_matrix_product(
        passage_ids=index.passage_ids,
        query_matrix=matrix,
        target_matrix=matrix,
        query_indices=query_indices,
        target_indices=target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def retrieve_top_bm25(
    index: SparseLexicalIndex,
    *,
    query_indices: Iterable[int] | None = None,
    target_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    maximum_proposal_document_frequency: int,
    quantization_decimals: int,
    exclude_self: bool,
    k1: float,
    b: float,
) -> list[RetrievalHit]:
    """Retrieve directional BM25 through explicit sparse query/document weights."""

    if maximum_proposal_document_frequency < 1:
        raise SparseIndexError("maximum proposal document frequency must be positive")
    if not math.isfinite(k1) or k1 <= 0.0:
        raise SparseIndexError("BM25 k1 must be finite and positive")
    if not math.isfinite(b) or not 0.0 <= b <= 1.0:
        raise SparseIndexError("BM25 b must be finite and in [0, 1]")
    mask = index.document_frequency <= maximum_proposal_document_frequency
    counts = index.counts[:, mask].astype(np.float64).tocsr()
    binary = index.binary[:, mask].astype(np.float64).tocsr()
    lengths = np.asarray(index.counts.sum(axis=1)).reshape(-1)
    average_length = float(lengths.mean()) if len(lengths) else 0.0
    if average_length <= 0.0:
        return []
    selected_df = index.document_frequency[mask]
    document_count = index.counts.shape[0]
    idf = np.log(1.0 + (document_count - selected_df + 0.5) / (selected_df + 0.5))
    weighted = counts.copy()
    for row in range(weighted.shape[0]):
        start = int(weighted.indptr[row])
        end = int(weighted.indptr[row + 1])
        if start == end:
            continue
        values = weighted.data[start:end]
        columns = weighted.indices[start:end]
        normalization = k1 * (1.0 - b + b * lengths[row] / average_length)
        weighted.data[start:end] = idf[columns] * values * (k1 + 1.0) / (values + normalization)
    return _retrieve_matrix_product(
        passage_ids=index.passage_ids,
        query_matrix=binary,
        target_matrix=weighted,
        query_indices=query_indices,
        target_indices=target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )


def retrieve_top_rare(
    index: SparseLexicalIndex,
    *,
    query_indices: Iterable[int] | None = None,
    target_indices: Iterable[int] | None = None,
    top_k: int,
    block_size: int,
    maximum_corpus_frequency: int,
    quantization_decimals: int,
    exclude_self: bool,
) -> list[RetrievalHit]:
    """Retrieve by transparent inverse-frequency shared rare-feature weight."""

    if maximum_corpus_frequency < 1:
        raise SparseIndexError("maximum rare-feature corpus frequency must be positive")
    mask = (index.corpus_frequency > 0) & (index.corpus_frequency <= maximum_corpus_frequency)
    matrix = index.binary[:, mask].astype(np.float64).tocsr()
    if matrix.shape[1]:
        weights = 1.0 / index.corpus_frequency[mask].astype(np.float64)
        weighted = sparse.csr_matrix(matrix.multiply(weights), dtype=np.float64)
    else:
        weighted = matrix
    return _retrieve_matrix_product(
        passage_ids=index.passage_ids,
        query_matrix=matrix,
        target_matrix=weighted,
        query_indices=query_indices,
        target_indices=target_indices,
        top_k=top_k,
        block_size=block_size,
        quantization_decimals=quantization_decimals,
        exclude_self=exclude_self,
    )
