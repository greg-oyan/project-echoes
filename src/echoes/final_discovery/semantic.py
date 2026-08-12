"""Bounded semantic representations and authenticated optional embedding support."""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import os
import platform
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict

from echoes.final_discovery.config import DetectorRegistration, ModelPin
from echoes.final_discovery.features import (
    aligned_sequence_similarity,
    candidate_pair_id,
    canonical_json,
    cosine_counts,
    matched_aligned_value_trace,
    present,
    weighted_jaccard,
)
from echoes.final_discovery.models import PassageRecord, RawEvidence

_RUNTIME_PYTHON_VERSION = (
    sys.version_info.major,
    sys.version_info.minor,
    sys.version_info.micro,
)


class SemanticError(ValueError):
    """Raised when semantic inputs or optional model artifacts fail governance."""


class ModelArtifactReport(BaseModel):
    """Exact offline model-inventory authentication result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    revision: str
    file_hashes: dict[str, str]
    total_bytes: int
    inventory_sha256: str


class ModelRuntimeDependencyReport(BaseModel):
    """Exact interpreter and installed-distribution versions used by E5."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_version: str
    dependency_versions: dict[str, str]


class SentenceEncoder(Protocol):
    """Narrow injectable protocol; production may use SentenceTransformer offline."""

    def encode(
        self,
        sentences: Sequence[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
    ) -> np.ndarray: ...


class OfflineSentenceTransformerEncoder:
    """Narrow adapter around a hash-authenticated, network-disabled model."""

    def __init__(
        self,
        model: Any,
        report: ModelArtifactReport,
        runtime_dependency_report: ModelRuntimeDependencyReport,
    ) -> None:
        self._model = model
        self.model_artifact_report = report
        self.runtime_dependency_report = runtime_dependency_report

    def encode(
        self,
        sentences: Sequence[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
    ) -> np.ndarray:
        return np.asarray(
            self._model.encode(
                list(sentences),
                batch_size=batch_size,
                normalize_embeddings=normalize_embeddings,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        )


class Neighbor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str
    target_id: str
    cosine_similarity: float
    rank: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_artifacts(root: Path, pin: ModelPin) -> ModelArtifactReport:
    """Require the exact minimal safetensors inventory and reject extra files.

    This prevents an offline loader from silently selecting an unpinned ONNX,
    OpenVINO, or pickle-based weight file.
    """

    if not root.is_dir():
        raise SemanticError(f"offline model directory does not exist: {root}")
    observed_paths = sorted(path for path in root.rglob("*") if path.is_file())
    observed_names = {path.relative_to(root).as_posix() for path in observed_paths}
    expected_names = set(pin.allowed_files)
    if observed_names != expected_names:
        missing = sorted(expected_names - observed_names)
        unexpected = sorted(observed_names - expected_names)
        raise SemanticError(
            f"offline model inventory mismatch; missing={missing}, unexpected={unexpected}"
        )
    hashes: dict[str, str] = {}
    total_bytes = 0
    for path in observed_paths:
        name = path.relative_to(root).as_posix()
        actual = _sha256_file(path)
        expected = pin.allowed_files[name]
        if actual != expected:
            raise SemanticError(f"offline model hash mismatch for {name}: {actual} != {expected}")
        hashes[name] = actual
        total_bytes += path.stat().st_size
    inventory_payload = {
        "model_id": pin.model_id,
        "revision": pin.revision,
        "file_hashes": hashes,
        "total_bytes": total_bytes,
    }
    return ModelArtifactReport(
        model_id=pin.model_id,
        revision=pin.revision,
        file_hashes=hashes,
        total_bytes=total_bytes,
        inventory_sha256=hashlib.sha256(
            canonical_json(inventory_payload).encode("ascii")
        ).hexdigest(),
    )


def verify_model_runtime_dependencies(
    pin: ModelPin,
    *,
    version_getter: Callable[[str], str] = importlib.metadata.version,
    python_version_info: Sequence[int] = _RUNTIME_PYTHON_VERSION,
) -> ModelRuntimeDependencyReport:
    """Require Python 3.12 and every preregistered model distribution version."""

    if tuple(python_version_info[:2]) != (3, 12):
        raise SemanticError(
            "production embeddings require Python 3.12; "
            f"observed={'.'.join(str(value) for value in python_version_info[:3])}"
        )
    observed: dict[str, str] = {}
    for package, expected in sorted(pin.dependency_versions.items()):
        try:
            actual = str(version_getter(package))
        except importlib.metadata.PackageNotFoundError as exc:
            raise SemanticError(f"pinned model dependency is absent: {package}") from exc
        # CPU wheels such as torch may carry a PEP 440 local suffix (``+cpu``).
        # The public release component must still match the frozen version.
        if actual.split("+", 1)[0] != expected:
            raise SemanticError(
                f"pinned model dependency version differs: {package}={actual}, expected={expected}"
            )
        observed[package] = actual
    return ModelRuntimeDependencyReport(
        python_version=platform.python_version(),
        dependency_versions=observed,
    )


def load_offline_sentence_encoder(root: Path, pin: ModelPin) -> OfflineSentenceTransformerEncoder:
    """Load the exact E5 assets locally, with every Hub network path disabled."""

    report = verify_model_artifacts(root, pin)
    runtime_report = verify_model_runtime_dependencies(pin)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        sentence_transformers = import_module("sentence_transformers")
    except ImportError as exc:  # pragma: no cover - exercised only with the optional group
        raise SemanticError(
            "the pinned models dependency group is required for production embeddings"
        ) from exc
    sentence_transformer = sentence_transformers.SentenceTransformer
    try:
        model = sentence_transformer(
            str(root.resolve()),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
        )
        model.max_seq_length = pin.maximum_tokens
    except Exception as exc:  # pragma: no cover - third-party loader boundary
        raise SemanticError(f"could not load the authenticated offline model: {exc}") from exc
    return OfflineSentenceTransformerEncoder(model, report, runtime_report)


def encode_passages(
    passages: Sequence[PassageRecord],
    *,
    encoder: SentenceEncoder,
    pin: ModelPin,
    english_gloss: bool,
    batch_size: int = 32,
) -> dict[str, np.ndarray]:
    """Encode a bounded sequence using the pinned symmetric E5 prefix."""

    if batch_size < 1:
        raise SemanticError("embedding batch_size must be positive")
    texts: list[str] = []
    ids: list[str] = []
    for passage in passages:
        text = passage.english_gloss if english_gloss else passage.original_text
        if text is None or not text.strip():
            continue
        texts.append(f"{pin.symmetric_prefix}{text}")
        ids.append(passage.passage_id)
    if not texts:
        return {}
    matrix = np.asarray(
        encoder.encode(texts, batch_size=batch_size, normalize_embeddings=True),
        dtype=np.float64,
    )
    if matrix.shape != (len(texts), pin.dimensions):
        raise SemanticError(
            f"embedding shape mismatch: expected {(len(texts), pin.dimensions)}, got {matrix.shape}"
        )
    if not np.isfinite(matrix).all():
        raise SemanticError("encoder returned a non-finite embedding")
    norms = np.linalg.norm(matrix, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-6):
        raise SemanticError("encoder output must be L2 normalized")
    return {passage_id: matrix[index].copy() for index, passage_id in enumerate(ids)}


def blockwise_top_k_cosine(
    query_ids: Sequence[str],
    query_matrix: np.ndarray,
    target_ids: Sequence[str],
    target_matrix: np.ndarray,
    *,
    k: int,
    block_size: int,
    exclude_identical_ids: bool = True,
) -> tuple[Neighbor, ...]:
    """Retrieve exact cosine top-k while bounding the temporary score matrix."""

    queries = np.asarray(query_matrix, dtype=np.float64)
    targets = np.asarray(target_matrix, dtype=np.float64)
    if queries.ndim != 2 or targets.ndim != 2 or queries.shape[1] != targets.shape[1]:
        raise SemanticError("query and target embeddings require equal two-dimensional widths")
    if queries.shape[0] != len(query_ids) or targets.shape[0] != len(target_ids):
        raise SemanticError("embedding row counts must match the supplied IDs")
    if k < 1 or block_size < 1:
        raise SemanticError("k and block_size must be positive")
    if not np.isfinite(queries).all() or not np.isfinite(targets).all():
        raise SemanticError("cosine retrieval requires finite vectors")
    query_norms = np.linalg.norm(queries, axis=1, keepdims=True)
    target_norms = np.linalg.norm(targets, axis=1, keepdims=True)
    safe_queries = np.divide(
        queries, query_norms, out=np.zeros_like(queries), where=query_norms > 0
    )
    safe_targets = np.divide(
        targets, target_norms, out=np.zeros_like(targets), where=target_norms > 0
    )
    target_lookup = {target_id: index for index, target_id in enumerate(target_ids)}
    neighbors: list[Neighbor] = []
    retained = min(k, len(target_ids))
    for start in range(0, len(query_ids), block_size):
        stop = min(start + block_size, len(query_ids))
        scores = safe_queries[start:stop] @ safe_targets.T
        for local_index, query_id in enumerate(query_ids[start:stop]):
            row = scores[local_index]
            if exclude_identical_ids and query_id in target_lookup:
                row[target_lookup[query_id]] = -math.inf
            available = len(target_ids) - int(exclude_identical_ids and query_id in target_lookup)
            row_k = min(retained, available)
            if row_k < 1:
                continue
            indices = np.argpartition(-row, row_k - 1)[:row_k]
            ordered = sorted(
                indices.tolist(), key=lambda index: (-float(row[index]), target_ids[index])
            )
            neighbors.extend(
                Neighbor(
                    query_id=query_id,
                    target_id=target_ids[target_index],
                    cosine_similarity=float(row[target_index]),
                    rank=rank,
                )
                for rank, target_index in enumerate(ordered, start=1)
            )
    return tuple(neighbors)


def _registration(
    registrations: Mapping[str, DetectorRegistration], detector_id: str
) -> DetectorRegistration:
    try:
        registration = registrations[detector_id]
    except KeyError as exc:
        raise SemanticError(f"unregistered semantic detector: {detector_id}") from exc
    if registration.family != "semantic":
        raise SemanticError(f"detector {detector_id} is not registered as semantic")
    return registration


def _raw(
    passage_a: PassageRecord,
    passage_b: PassageRecord,
    *,
    registration: DetectorRegistration,
    score: float,
    trace: object,
    source_artifact_id: str,
    source_artifact_sha256: str,
) -> RawEvidence:
    first, second = sorted((passage_a, passage_b), key=lambda passage: passage.passage_id)
    pair_id = candidate_pair_id(first.passage_id, second.passage_id)
    bounded_score = min(max(score, 0.0), 1.0)
    return RawEvidence(
        candidate_pair_id=pair_id,
        passage_a_id=first.passage_id,
        passage_b_id=second.passage_id,
        detector_id=registration.detector_id,
        family="semantic",
        independence_group=registration.independence_group,
        raw_score=bounded_score,
        contains_english_derived_evidence=registration.contains_english_derived_evidence,
        original_language_evidence_remains=registration.original_language_capable,
        counts_for_independence=registration.counts_for_independence,
        english_ablation_raw_score=(
            0.0 if registration.contains_english_derived_evidence else bounded_score
        ),
        trace_json=canonical_json(trace),
        source_artifact_id=source_artifact_id,
        source_artifact_sha256=source_artifact_sha256,
    )


def semantic_pair_evidence(
    passage_a: PassageRecord,
    passage_b: PassageRecord,
    *,
    registrations: Mapping[str, DetectorRegistration],
    source_artifact_id: str,
    source_artifact_sha256: str,
    original_embeddings: Mapping[str, np.ndarray] | None = None,
    english_embeddings: Mapping[str, np.ndarray] | None = None,
    embedding_model: ModelPin | None = None,
    embedding_source_artifact_sha256: str | None = None,
    embedding_model_inventory_sha256: str | None = None,
    embedding_passage_projection_sha256: str | None = None,
) -> tuple[RawEvidence, ...]:
    """Compute all available semantic variants separately for one candidate pair."""

    domains_a = present(passage_a.semantic_domains)
    domains_b = present(passage_b.semantic_domains)
    shared_domains = sorted(set(domains_a) & set(domains_b))
    results = [
        _raw(
            passage_a,
            passage_b,
            registration=_registration(registrations, "semantic_domain_overlap"),
            score=weighted_jaccard(domains_a, domains_b),
            trace={
                "representation": "source_semantic_domain_multiset",
                "shared_domains": shared_domains,
                "matched_domain_evidence": matched_aligned_value_trace(
                    passage_a.passage_id,
                    passage_a.semantic_domains,
                    passage_a.token_ids,
                    passage_b.passage_id,
                    passage_b.semantic_domains,
                    passage_b.token_ids,
                ),
                "passage_a_feature_count": len(domains_a),
                "passage_b_feature_count": len(domains_b),
            },
            source_artifact_id=source_artifact_id,
            source_artifact_sha256=source_artifact_sha256,
        )
    ]
    lemmas_a = present(passage_a.lemma_sequence)
    lemmas_b = present(passage_b.lemma_sequence)
    roots_a = present(passage_a.root_sequence)
    roots_b = present(passage_b.root_sequence)
    component_scores = (
        cosine_counts(lemmas_a, lemmas_b),
        cosine_counts(roots_a, roots_b),
        aligned_sequence_similarity(lemmas_a, lemmas_b),
        aligned_sequence_similarity(roots_a, roots_b),
    )
    results.append(
        _raw(
            passage_a,
            passage_b,
            registration=_registration(registrations, "lemma_root_sequence_semantic"),
            score=math.fsum(component_scores) / len(component_scores),
            trace={
                "representation": "lemma_root_counts_and_ordered_alignment",
                "component_scores": component_scores,
                "shared_lemma_count": len(set(lemmas_a) & set(lemmas_b)),
                "shared_root_count": len(set(roots_a) & set(roots_b)),
                "matched_lemma_evidence": matched_aligned_value_trace(
                    passage_a.passage_id,
                    passage_a.lemma_sequence,
                    passage_a.token_ids,
                    passage_b.passage_id,
                    passage_b.lemma_sequence,
                    passage_b.token_ids,
                ),
                "matched_root_evidence": matched_aligned_value_trace(
                    passage_a.passage_id,
                    passage_a.root_sequence,
                    passage_a.token_ids,
                    passage_b.passage_id,
                    passage_b.root_sequence,
                    passage_b.token_ids,
                ),
                "correlated_with_m7_lexical": True,
            },
            source_artifact_id=source_artifact_id,
            source_artifact_sha256=source_artifact_sha256,
        )
    )
    if (original_embeddings is not None or english_embeddings is not None) and (
        embedding_model is None
        or embedding_source_artifact_sha256 is None
        or embedding_model_inventory_sha256 is None
        or embedding_passage_projection_sha256 is None
    ):
        raise SemanticError("embedding evidence requires exact model lineage")
    if original_embeddings is not None and all(
        passage.passage_id in original_embeddings for passage in (passage_a, passage_b)
    ):
        assert embedding_model is not None
        assert embedding_source_artifact_sha256 is not None
        assert embedding_model_inventory_sha256 is not None
        assert embedding_passage_projection_sha256 is not None
        left = original_embeddings[passage_a.passage_id]
        right = original_embeddings[passage_b.passage_id]
        score = float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))
        results.append(
            _raw(
                passage_a,
                passage_b,
                registration=_registration(registrations, "multilingual_e5_original_language"),
                score=(score + 1.0) / 2.0,
                trace={
                    "representation": "pinned_multilingual_e5_original_text",
                    "cosine_similarity": score,
                    "cosine_alone_is_insufficient": True,
                    "model_id": embedding_model.model_id,
                    "model_revision": embedding_model.revision,
                    "tokenizer": embedding_model.tokenizer,
                    "pooling": embedding_model.pooling,
                    "maximum_tokens": embedding_model.maximum_tokens,
                    "symmetric_prefix": embedding_model.symmetric_prefix,
                    "model_inventory_sha256": embedding_model_inventory_sha256,
                    "passage_projection_sha256": embedding_passage_projection_sha256,
                    "composite_source_sha256": embedding_source_artifact_sha256,
                },
                source_artifact_id=(f"{embedding_model.model_id}@{embedding_model.revision}"),
                source_artifact_sha256=embedding_source_artifact_sha256,
            )
        )
    if english_embeddings is not None and all(
        passage.passage_id in english_embeddings for passage in (passage_a, passage_b)
    ):
        assert embedding_model is not None
        assert embedding_source_artifact_sha256 is not None
        assert embedding_model_inventory_sha256 is not None
        assert embedding_passage_projection_sha256 is not None
        left = english_embeddings[passage_a.passage_id]
        right = english_embeddings[passage_b.passage_id]
        score = float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))
        results.append(
            _raw(
                passage_a,
                passage_b,
                registration=_registration(registrations, "multilingual_e5_english_gloss"),
                score=(score + 1.0) / 2.0,
                trace={
                    "representation": "pinned_multilingual_e5_literal_english_gloss",
                    "cosine_similarity": score,
                    "supplemental_english_derived": True,
                    "model_id": embedding_model.model_id,
                    "model_revision": embedding_model.revision,
                    "tokenizer": embedding_model.tokenizer,
                    "pooling": embedding_model.pooling,
                    "maximum_tokens": embedding_model.maximum_tokens,
                    "symmetric_prefix": embedding_model.symmetric_prefix,
                    "model_inventory_sha256": embedding_model_inventory_sha256,
                    "passage_projection_sha256": embedding_passage_projection_sha256,
                    "composite_source_sha256": embedding_source_artifact_sha256,
                },
                source_artifact_id=(f"{embedding_model.model_id}@{embedding_model.revision}"),
                source_artifact_sha256=embedding_source_artifact_sha256,
            )
        )
    return tuple(results)
