"""Deterministic feature primitives shared by final-discovery detectors."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def canonical_json(value: object) -> str:
    """Serialize a persisted trace without platform-specific whitespace."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_pair(passage_a_id: str, passage_b_id: str) -> tuple[str, str]:
    """Return stable undirected passage ordering and reject self-pairs."""

    if passage_a_id == passage_b_id:
        raise ValueError("candidate pairs require two different passage IDs")
    return tuple(sorted((passage_a_id, passage_b_id)))  # type: ignore[return-value]


def candidate_pair_id(passage_a_id: str, passage_b_id: str) -> str:
    """Build a compact stable ID from the full canonical pair payload."""

    first, second = canonical_pair(passage_a_id, passage_b_id)
    digest = hashlib.sha256(canonical_json([first, second]).encode()).hexdigest()
    return f"FDPAIR~{digest}"


def evidence_id(pair_id: str, detector_id: str, source_hash: str) -> str:
    payload = canonical_json([pair_id, detector_id, source_hash])
    return f"FDEVID~{hashlib.sha256(payload.encode()).hexdigest()}"


def present(values: Iterable[str | None]) -> tuple[str, ...]:
    """Retain nonempty governed annotation strings in source order."""

    return tuple(value for value in values if value is not None and value != "")


def matched_aligned_value_trace(
    passage_a_id: str,
    values_a: Sequence[str | None],
    token_ids_a: Sequence[str],
    passage_b_id: str,
    values_b: Sequence[str | None],
    token_ids_b: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Return exact shared values with one-based positions and governed token IDs.

    Empty token-ID sequences are retained solely for backward-compatible test
    fixtures.  They are represented as ``null`` rather than synthesized IDs;
    production ``PassageRecord`` projections carry an ID for every position.
    """

    if token_ids_a and len(token_ids_a) != len(values_a):
        raise ValueError(f"token IDs do not align for passage {passage_a_id}")
    if token_ids_b and len(token_ids_b) != len(values_b):
        raise ValueError(f"token IDs do not align for passage {passage_b_id}")
    shared = sorted(
        (set(present(values_a)) & set(present(values_b))),
        key=lambda value: value.encode("utf-8"),
    )
    rows: list[dict[str, Any]] = []
    for value in shared:
        positions_a = tuple(
            position for position, item in enumerate(values_a, start=1) if item == value
        )
        positions_b = tuple(
            position for position, item in enumerate(values_b, start=1) if item == value
        )
        rows.append(
            {
                "value": value,
                "occurrences": {
                    passage_a_id: {
                        "positions": positions_a,
                        "token_ids": (
                            tuple(token_ids_a[position - 1] for position in positions_a)
                            if token_ids_a
                            else None
                        ),
                    },
                    passage_b_id: {
                        "positions": positions_b,
                        "token_ids": (
                            tuple(token_ids_b[position - 1] for position in positions_b)
                            if token_ids_b
                            else None
                        ),
                    },
                },
            }
        )
    return tuple(rows)


def weighted_jaccard(
    left: Iterable[str],
    right: Iterable[str],
    *,
    weights: Mapping[str, float] | None = None,
) -> float:
    """Multiset weighted Jaccard, with explicit empty-union behavior."""

    left_counts = Counter(left)
    right_counts = Counter(right)
    features = set(left_counts) | set(right_counts)
    if not features:
        return 0.0
    supplied = weights or {}
    numerator = math.fsum(
        min(left_counts[item], right_counts[item]) * supplied.get(item, 1.0) for item in features
    )
    denominator = math.fsum(
        max(left_counts[item], right_counts[item]) * supplied.get(item, 1.0) for item in features
    )
    return numerator / denominator if denominator else 0.0


def cosine_counts(left: Iterable[str], right: Iterable[str]) -> float:
    """Cosine similarity over transparent term-frequency vectors."""

    left_counts = Counter(left)
    right_counts = Counter(right)
    shared = set(left_counts) & set(right_counts)
    numerator = math.fsum(left_counts[item] * right_counts[item] for item in shared)
    left_norm = math.sqrt(math.fsum(value * value for value in left_counts.values()))
    right_norm = math.sqrt(math.fsum(value * value for value in right_counts.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def aligned_sequence_similarity(
    left: Sequence[str],
    right: Sequence[str],
    *,
    match_score: float = 2.0,
    mismatch_score: float = -1.0,
    gap_score: float = -1.0,
) -> float:
    """Bounded global sequence alignment normalized to ``[0, 1]``.

    The implementation retains only two rows, bounding memory by the shorter
    passage length. It is intended for candidate reranking, not all-pairs use.
    """

    if not left or not right:
        return 0.0
    if len(right) > len(left):
        left, right = right, left
    previous = [index * gap_score for index in range(len(right) + 1)]
    for left_index, left_value in enumerate(left, start=1):
        current = [left_index * gap_score]
        for right_index, right_value in enumerate(right, start=1):
            diagonal = previous[right_index - 1] + (
                match_score if left_value == right_value else mismatch_score
            )
            current.append(
                max(
                    diagonal,
                    previous[right_index] + gap_score,
                    current[right_index - 1] + gap_score,
                )
            )
        previous = current
    raw = previous[-1]
    best = min(len(left), len(right)) * match_score
    worst = max(len(left), len(right)) * gap_score
    if best == worst:
        return 0.0
    return min(max((raw - worst) / (best - worst), 0.0), 1.0)


def adjacent_ngrams(values: Sequence[str], size: int) -> tuple[str, ...]:
    if size < 1:
        raise ValueError("ngram size must be positive")
    return tuple(
        "\u241f".join(values[index : index + size]) for index in range(len(values) - size + 1)
    )


def empirical_upper_tail(observed: float, null_scores: Sequence[float]) -> float:
    """Finite-sample corrected empirical upper-tail probability."""

    if not math.isfinite(observed) or not null_scores:
        raise ValueError("empirical calibration requires finite observed and null scores")
    if any(not math.isfinite(value) for value in null_scores):
        raise ValueError("null scores must be finite")
    return (1 + sum(value >= observed for value in null_scores)) / (len(null_scores) + 1)


def empirical_percentile(observed: float, reference_scores: Sequence[float]) -> float:
    """Stable mid-rank percentile with deterministic tie treatment."""

    if not reference_scores:
        raise ValueError("percentile normalization requires a reference distribution")
    below = sum(value < observed for value in reference_scores)
    tied = sum(value == observed for value in reference_scores)
    return (below + 0.5 * tied) / len(reference_scores)
