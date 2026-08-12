"""Sparse blockwise candidate retrieval shared by annotation families."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from echoes.final_discovery.features import canonical_pair
from echoes.final_discovery.models import PassageRecord


class RetrievalError(ValueError):
    """Raised when a sparse candidate index violates bounded retrieval rules."""


@dataclass(frozen=True, slots=True)
class SparseRepresentation:
    passage_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]
    matrix: sparse.csr_matrix


@dataclass(frozen=True, slots=True)
class SparseNeighbor:
    query_id: str
    target_id: str
    score: float
    rank: int


FeatureExtractor = Callable[[PassageRecord], Sequence[str]]


def build_tfidf_representation(
    passages: Sequence[PassageRecord], extractor: FeatureExtractor
) -> SparseRepresentation:
    """Build deterministic L2-normalized TF-IDF from transparent annotations."""

    ordered = tuple(sorted(passages, key=lambda passage: passage.passage_id))
    if len({passage.passage_id for passage in ordered}) != len(ordered):
        raise RetrievalError("passage IDs must be unique")
    extracted = [tuple(extractor(passage)) for passage in ordered]
    vocabulary = tuple(sorted({feature for values in extracted for feature in values}))
    vocabulary_index = {feature: index for index, feature in enumerate(vocabulary)}
    document_frequency: Counter[str] = Counter()
    for values in extracted:
        document_frequency.update(set(values))
    rows: list[int] = []
    columns: list[int] = []
    data: list[float] = []
    document_count = len(ordered)
    for row_index, values in enumerate(extracted):
        counts = Counter(values)
        for feature, count in sorted(counts.items()):
            idf = math.log((1 + document_count) / (1 + document_frequency[feature])) + 1.0
            rows.append(row_index)
            columns.append(vocabulary_index[feature])
            data.append((1.0 + math.log(count)) * idf)
    matrix = sparse.csr_matrix(
        (np.asarray(data, dtype=np.float64), (rows, columns)),
        shape=(len(ordered), len(vocabulary)),
        dtype=np.float64,
    )
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).reshape(-1))
    inverse = np.divide(1.0, norms, out=np.zeros_like(norms), where=norms > 0.0)
    normalized = sparse.diags(inverse, format="csr") @ matrix
    return SparseRepresentation(
        passage_ids=tuple(passage.passage_id for passage in ordered),
        feature_ids=vocabulary,
        matrix=normalized.tocsr(),
    )


def blockwise_top_k_sparse(
    representation: SparseRepresentation,
    *,
    k: int,
    block_size: int,
    allow_pair: Callable[[str, str], bool] | None = None,
) -> tuple[SparseNeighbor, ...]:
    """Retrieve sparse cosine neighbors with a bounded dense score block."""

    if k < 1 or block_size < 1:
        raise RetrievalError("k and block_size must be positive")
    ids = representation.passage_ids
    matrix = representation.matrix
    if matrix.shape[0] != len(ids):
        raise RetrievalError("sparse matrix rows do not match passage IDs")
    neighbors: list[SparseNeighbor] = []
    for start in range(0, len(ids), block_size):
        stop = min(start + block_size, len(ids))
        scores = (matrix[start:stop] @ matrix.T).toarray()
        for local_index, query_id in enumerate(ids[start:stop]):
            row = scores[local_index]
            eligible = [
                index
                for index, target_id in enumerate(ids)
                if target_id != query_id
                and (allow_pair is None or allow_pair(query_id, target_id))
                and row[index] > 0.0
            ]
            ordered = sorted(eligible, key=lambda index: (-float(row[index]), ids[index]))[:k]
            neighbors.extend(
                SparseNeighbor(
                    query_id=query_id,
                    target_id=ids[target_index],
                    score=float(row[target_index]),
                    rank=rank,
                )
                for rank, target_index in enumerate(ordered, start=1)
            )
    return tuple(neighbors)


def canonical_neighbor_pairs(neighbors: Sequence[SparseNeighbor]) -> tuple[tuple[str, str], ...]:
    """Collapse directional retrieval support to stable undirected pairs."""

    return tuple(
        sorted({canonical_pair(neighbor.query_id, neighbor.target_id) for neighbor in neighbors})
    )
