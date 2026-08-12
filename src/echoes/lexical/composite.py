"""Transparent rank fusion and correlated-evidence guard primitives."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

FamilyPolicy = Literal["best", "all"]


@dataclass(frozen=True, slots=True)
class RRFContribution:
    """One detector's reciprocal-rank contribution for one candidate."""

    detector: str
    family: str
    rank: int
    value: float


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    """One fused candidate with used and correlation-suppressed contributions."""

    candidate_id: str
    score: float
    contributions: tuple[RRFContribution, ...]
    suppressed_contributions: tuple[RRFContribution, ...]


@dataclass(frozen=True, slots=True)
class ReciprocalRankFusionResult:
    """A deterministically ordered RRF result."""

    rrf_k: int
    family_policy: FamilyPolicy
    candidates: tuple[FusedCandidate, ...]


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    """A potential co-signal with explicit derivation and correlation identity."""

    signal_id: str
    detector_family: str
    independence_key: str
    evidence_feature_ids: frozenset[str]
    english_derived: bool = False

    def __post_init__(self) -> None:
        if not self.signal_id or not self.detector_family or not self.independence_key:
            raise ValueError("evidence signal identity fields cannot be empty")
        if not self.evidence_feature_ids or any(not item for item in self.evidence_feature_ids):
            raise ValueError("evidence signals require nonempty evidence feature IDs")


@dataclass(frozen=True, slots=True)
class RejectedEvidenceSignal:
    """A rejected co-signal and its auditable reason."""

    signal: EvidenceSignal
    reason: Literal[
        "deterministic_restatement",
        "correlated_duplicate",
        "english_derived",
    ]


@dataclass(frozen=True, slots=True)
class IndependentEvidenceResult:
    """Accepted independent co-signals and every rejected restatement."""

    accepted: tuple[EvidenceSignal, ...]
    rejected: tuple[RejectedEvidenceSignal, ...]


def rank_scored_candidates(scores: Mapping[str, float]) -> tuple[str, ...]:
    """Rank descending scores with candidate ID as the final stable tie-break."""

    for candidate_id, score in scores.items():
        if not candidate_id:
            raise ValueError("candidate IDs cannot be empty")
        if not math.isfinite(score):
            raise ValueError("candidate scores must be finite")
    return tuple(
        candidate_id for candidate_id, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    )


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]],
    detector_families: Mapping[str, str],
    *,
    rrf_k: int = 60,
    family_policy: FamilyPolicy = "best",
) -> ReciprocalRankFusionResult:
    """Fuse rankings while retaining a complete detector contribution audit.

    The default ``best`` policy keeps only the strongest contribution from each
    registered detector family for a candidate.  This prevents correlated
    variants from becoming multiple nominally independent votes.  Suppressed
    contributions remain present in the result for audit.
    """

    if rrf_k < 0:
        raise ValueError("rrf_k cannot be negative")
    if family_policy not in {"best", "all"}:
        raise ValueError("family_policy must be best or all")
    if set(rankings) != set(detector_families):
        missing = sorted(set(rankings).difference(detector_families))
        extra = sorted(set(detector_families).difference(rankings))
        raise ValueError(f"detector family registration mismatch: missing={missing}, extra={extra}")

    by_candidate: dict[str, list[RRFContribution]] = {}
    for detector in sorted(rankings):
        if not detector or not detector_families[detector]:
            raise ValueError("detector and family names cannot be empty")
        ranking = tuple(rankings[detector])
        if any(not candidate_id for candidate_id in ranking):
            raise ValueError("candidate IDs cannot be empty")
        if len(ranking) != len(set(ranking)):
            raise ValueError(f"ranking {detector!r} contains duplicate candidates")
        for rank, candidate_id in enumerate(ranking, start=1):
            by_candidate.setdefault(candidate_id, []).append(
                RRFContribution(
                    detector=detector,
                    family=detector_families[detector],
                    rank=rank,
                    value=1.0 / (rrf_k + rank),
                )
            )

    fused: list[FusedCandidate] = []
    for candidate_id, raw_contributions in by_candidate.items():
        ordered = sorted(raw_contributions, key=lambda item: (item.family, item.detector))
        if family_policy == "all":
            used = ordered
            suppressed: list[RRFContribution] = []
        else:
            best_by_family: dict[str, RRFContribution] = {}
            suppressed = []
            for contribution in ordered:
                current = best_by_family.get(contribution.family)
                if current is None or (contribution.rank, contribution.detector) < (
                    current.rank,
                    current.detector,
                ):
                    if current is not None:
                        suppressed.append(current)
                    best_by_family[contribution.family] = contribution
                else:
                    suppressed.append(contribution)
            used = sorted(best_by_family.values(), key=lambda item: (item.family, item.detector))
            suppressed.sort(key=lambda item: (item.family, item.detector))
        fused.append(
            FusedCandidate(
                candidate_id=candidate_id,
                score=math.fsum(contribution.value for contribution in used),
                contributions=tuple(used),
                suppressed_contributions=tuple(suppressed),
            )
        )
    fused.sort(key=lambda item: (-item.score, item.candidate_id))
    return ReciprocalRankFusionResult(
        rrf_k=rrf_k,
        family_policy=family_policy,
        candidates=tuple(fused),
    )


def independent_cosignals(
    primary_feature_ids: frozenset[str],
    signals: Sequence[EvidenceSignal],
    *,
    primary_independence_keys: frozenset[str] = frozenset(),
    permit_english_derived: bool = False,
) -> IndependentEvidenceResult:
    """Reject deterministic restatements and duplicate correlation groups.

    A signal derived only from the primary rare feature(s), or sharing a
    registered source-token/correlation key with them, cannot become an
    independent co-signal merely because it was emitted by another detector.
    Among other signals sharing an ``independence_key``, the lexicographically
    first signal is retained and all others are recorded as correlated duplicates.
    """

    if not primary_feature_ids or any(not item for item in primary_feature_ids):
        raise ValueError("primary_feature_ids must be nonempty")
    if any(not item for item in primary_independence_keys):
        raise ValueError("primary_independence_keys cannot contain empty values")
    signal_ids = [signal.signal_id for signal in signals]
    if len(signal_ids) != len(set(signal_ids)):
        raise ValueError("evidence signal IDs must be unique")
    accepted: list[EvidenceSignal] = []
    rejected: list[RejectedEvidenceSignal] = []
    used_independence_keys: set[str] = set()
    for signal in sorted(signals, key=lambda item: item.signal_id):
        if signal.english_derived and not permit_english_derived:
            rejected.append(RejectedEvidenceSignal(signal, "english_derived"))
        elif signal.independence_key in primary_independence_keys or (
            signal.evidence_feature_ids.issubset(primary_feature_ids)
        ):
            rejected.append(RejectedEvidenceSignal(signal, "deterministic_restatement"))
        elif signal.independence_key in used_independence_keys:
            rejected.append(RejectedEvidenceSignal(signal, "correlated_duplicate"))
        else:
            accepted.append(signal)
            used_independence_keys.add(signal.independence_key)
    return IndependentEvidenceResult(accepted=tuple(accepted), rejected=tuple(rejected))
