"""Typed configuration loading for Project Echoes."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from echoes.manifests.experiments import ExperimentManifest


class ConfigLoadError(ValueError):
    """Raised when a configuration file cannot be loaded or validated."""


class EchoesModel(BaseModel):
    """Base model that rejects undocumented configuration keys."""

    model_config = ConfigDict(extra="forbid")


class CorpusSpec(EchoesModel):
    """A planned or active corpus layer."""

    corpus_id: str = Field(min_length=1)
    role: Literal["primary", "bridge", "supplementary"]
    languages: list[Literal["hebrew", "aramaic", "greek", "english"]]
    status: Literal["planned", "blocked", "active"]
    activation_prerequisites: list[str] = Field(default_factory=list)


class CorporaConfig(EchoesModel):
    """Top-level corpus activation configuration."""

    schema_version: Literal[1]
    corpora: list[CorpusSpec]

    @model_validator(mode="after")
    def corpus_ids_are_unique(self) -> Self:
        ids = [corpus.corpus_id for corpus in self.corpora]
        if len(ids) != len(set(ids)):
            msg = "corpus_id values must be unique"
            raise ValueError(msg)
        return self


class HebrewTransformations(EchoesModel):
    """Explicit transformations used to derive Hebrew analytical forms."""

    unicode_normalization: Literal["NFD", "NFC"]
    collapse_whitespace: bool
    remove_combining_grapheme_joiner: bool
    normalized_remove_cantillation: bool
    normalized_remove_vowel_points: bool
    unpointed_remove_cantillation: bool
    unpointed_remove_vowel_points: bool
    split_maqqef: Literal[False]
    remove_paseq: Literal[False]
    remove_sof_pasuq: Literal[False]
    remove_punctuation: Literal[False]
    normalize_final_letters: Literal[False]
    collapse_orthographic_variants: Literal[False]
    segment_prefixes: Literal[False]
    segment_suffixes: Literal[False]
    collapse_ketiv_qere: Literal[False]
    normalize_divine_names: Literal[False]


class HebrewNormalization(EchoesModel):
    """Active, information-preserving Hebrew and Aramaic normalization policy."""

    status: Literal["active"]
    preserve_source_form: Literal[True]
    lemma_namespace: Literal["macula"]
    transformations: HebrewTransformations


class KetivQerePolicy(EchoesModel):
    """Selects the derived reading stream without mutating preserved records."""

    analysis_reading: Literal["qere", "ketiv"] = "qere"


class GreekTransformations(EchoesModel):
    """Explicit transformations used to derive Greek analytical forms.

    The surface form is immutable.  ``normalized_form`` is the
    punctuation-separated word core; ``folded_form`` is the case-folded,
    accent-insensitive comparison form.  Destructive options are pinned off.
    """

    unicode_normalization: Literal["NFC", "NFD"]
    collapse_whitespace: bool
    separate_punctuation: Literal[True]
    preserve_elision_mark: Literal[True]
    restore_elided_letters: Literal[False]
    decompose_crasis: Literal[False]
    folded_case_fold: Literal[True]
    folded_remove_accents: bool
    folded_remove_breathings: bool
    folded_remove_diaeresis: bool
    normalize_final_sigma_outside_folding: Literal[False]
    enclitic_accent_policy: Literal["preserve_source"]


class GreekNormalization(EchoesModel):
    """Active, information-preserving Greek normalization policy."""

    status: Literal["active"]
    preserve_source_form: Literal[True]
    lemma_namespace: Literal["macula"]
    transformations: GreekTransformations


class NormalizationConfig(EchoesModel):
    """Normalization configuration for the primary source languages."""

    schema_version: Literal[4]
    ketiv_qere: KetivQerePolicy
    hebrew: HebrewNormalization
    greek: GreekNormalization


class HebrewSpotCheck(EchoesModel):
    """One reproducible manual-inspection target and its required facets."""

    reference: str = Field(pattern=r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$")
    category: str = Field(min_length=1)
    expected_language: Literal["hebrew", "aramaic"]
    check: list[
        Literal[
            "token_order",
            "surface_forms",
            "lemmas",
            "morphology",
            "clause_or_phrase_ids",
            "language",
            "canonical_reference",
            "source_provenance",
            "normalized_forms",
            "ketiv_qere",
            "segmentation",
        ]
    ] = Field(min_length=1)


class HebrewIngestionConfig(EchoesModel):
    """Governed full-corpus expectations and manual spot-check registry."""

    schema_version: Literal[1]
    source_id: Literal["macula-hebrew"]
    status: Literal["blocked", "ready"]
    expected_books: Literal[39]
    expected_chapters: Literal[929]
    expected_tokens: Literal[475911]
    spot_checks: list[HebrewSpotCheck] = Field(min_length=10)

    @model_validator(mode="after")
    def spot_check_references_are_unique(self) -> Self:
        references = [item.reference for item in self.spot_checks]
        if len(references) != len(set(references)):
            raise ValueError("Hebrew spot-check references must be unique")
        return self


class GreekSpotCheck(EchoesModel):
    """One reproducible Greek manual-inspection target and its required facets."""

    reference: str = Field(pattern=r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$")
    category: str = Field(min_length=1)
    check: list[
        Literal[
            "token_order",
            "surface_forms",
            "lemmas",
            "morphology",
            "clause_or_phrase_ids",
            "canonical_reference",
            "source_provenance",
            "normalized_forms",
            "punctuation_separation",
            "elision",
            "enclitics",
            "disputed_passage",
            "versification",
        ]
    ] = Field(min_length=1)


class GreekIngestionConfig(EchoesModel):
    """Governed full-corpus Greek expectations and manual spot-check registry."""

    schema_version: Literal[1]
    source_id: Literal["macula-greek"]
    status: Literal["blocked", "ready"]
    expected_books: Literal[27]
    expected_chapters: Literal[260]
    expected_tokens: Literal[137779]
    expected_missing_verses: list[str] = Field(min_length=1)
    expected_out_of_sequence_verses: list[str] = Field(default_factory=list)
    spot_checks: list[GreekSpotCheck] = Field(min_length=8)

    @model_validator(mode="after")
    def references_are_well_formed_and_unique(self) -> Self:
        reference_pattern = r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$"
        for values in (self.expected_missing_verses, self.expected_out_of_sequence_verses):
            for reference in values:
                if re.fullmatch(reference_pattern, reference) is None:
                    raise ValueError(f"malformed verse reference: {reference}")
            if len(values) != len(set(values)):
                raise ValueError("verse reference lists must be unique")
        references = [item.reference for item in self.spot_checks]
        if len(references) != len(set(references)):
            raise ValueError("Greek spot-check references must be unique")
        return self


Granularity = Literal["clause", "sentence", "verse", "two_verse", "five_verse"]


class NonContiguousVerseAdjacency(EchoesModel):
    """Two verses that are numerically distant yet textually adjacent.

    Milestone 5 segmentation must treat the pair as adjacent (or explicitly
    exclude the span) instead of assuming verse-number continuity; this
    declaration only records the edition fact.
    """

    corpus: Literal["hebrew", "greek"]
    from_reference: str = Field(pattern=r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$")
    to_reference: str = Field(pattern=r"^[A-Z0-9]{3} [1-9][0-9]*:[1-9][0-9]*$")
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def adjacency_is_within_one_book_and_directed(self) -> Self:
        from_book = self.from_reference.split(" ", maxsplit=1)[0]
        to_book = self.to_reference.split(" ", maxsplit=1)[0]
        if from_book != to_book:
            raise ValueError("verse adjacency must stay inside one book")
        if self.from_reference == self.to_reference:
            raise ValueError("verse adjacency requires two distinct references")
        return self


class SegmentationConfig(EchoesModel):
    """Planned passage granularities and recorded edition adjacency facts."""

    schema_version: Literal[1]
    status: Literal["planned"]
    granularities: list[Granularity]
    preserve_token_boundaries: Literal[True]
    non_contiguous_verse_adjacencies: list[NonContiguousVerseAdjacency] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def adjacencies_are_unique(self) -> Self:
        pairs = [
            (item.corpus, item.from_reference, item.to_reference)
            for item in self.non_contiguous_verse_adjacencies
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError("non_contiguous_verse_adjacencies must be unique")
        return self


class ScoreComponent(EchoesModel):
    """A disabled or enabled transparent score component."""

    name: str = Field(min_length=1)
    enabled: bool
    weight: float = Field(ge=0)


NullPreservation = Literal[
    "book_level_token_or_lemma_frequencies",
    "passage_counts",
    "passage_lengths",
    "book_or_genre_conditioned_lemma_frequencies",
]


class NullModelFamily(EchoesModel):
    """One disabled, declarative null family for future lexical experiments."""

    name: Literal["within_book_reassignment", "frequency_preserving_synthetic_passages"]
    enabled: Literal[False]
    required_preservation: list[NullPreservation] = Field(min_length=2)
    optional_preservation: list[
        Literal[
            "part_of_speech_distributions",
            "morphological_distributions",
            "local_ngram_characteristics",
        ]
    ] = Field(default_factory=list)
    invalid_surrogates: list[Literal["passage_order_only", "passage_label_only"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def family_preserves_its_required_marginals(self) -> Self:
        required = set(self.required_preservation)
        if self.name == "within_book_reassignment":
            if required != {
                "book_level_token_or_lemma_frequencies",
                "passage_counts",
                "passage_lengths",
            }:
                raise ValueError("within-book reassignment must preserve all governed marginals")
            if set(self.invalid_surrogates) != {"passage_order_only", "passage_label_only"}:
                raise ValueError("within-book reassignment must reject both invalid surrogates")
        elif required != {
            "passage_lengths",
            "book_or_genre_conditioned_lemma_frequencies",
        }:
            raise ValueError("synthetic passages must preserve length and conditioned frequencies")
        return self


class NullModelsConfig(EchoesModel):
    """Governance-only requirements for later repeated empirical null simulations."""

    status: Literal["planned"]
    enabled: Literal[False]
    repetitions: None = None
    families: list[NullModelFamily] = Field(min_length=2, max_length=2)
    required_threshold_metrics: list[
        Literal[
            "observed_candidate_count",
            "mean_null_candidate_count",
            "empirical_null_interval_95",
            "observed_to_null_enrichment",
            "empirical_tail_probability",
            "estimated_empirical_false_discovery_rate",
        ]
    ] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def required_families_and_metrics_are_unique(self) -> Self:
        families = [family.name for family in self.families]
        if set(families) != {
            "within_book_reassignment",
            "frequency_preserving_synthetic_passages",
        }:
            raise ValueError("both required lexical null-model families must be declared")
        if len(self.required_threshold_metrics) != len(set(self.required_threshold_metrics)):
            raise ValueError("required null-model threshold metrics must be unique")
        return self


class RareEvidenceConfig(EchoesModel):
    """Planned conjunctive evidence rule; no scoring engine is activated here."""

    status: Literal["planned"]
    enabled: Literal[False]
    total_corpus_frequency_max: int = Field(ge=1)
    require_independent_co_signal: Literal[True]
    allowed_co_signals: list[
        Literal[
            "ordered_sequence_similarity",
            "shared_rare_phrase",
            "syntactic_match",
            "second_rare_lexical_item",
            "independent_detector_family",
        ]
    ] = Field(min_length=1)
    planned_evidence_fields: list[
        Literal[
            "expected_cooccurrence_independence",
            "hypergeometric_p_value",
            "null_model_empirical_rate",
            "multiple_testing_adjustment",
        ]
    ] = Field(min_length=4, max_length=4)
    hypergeometric_role: Literal["baseline_only"]
    empirical_calibration_priority: Literal["book_or_genre_conditioned_permutation"]

    @model_validator(mode="after")
    def evidence_lists_are_unique(self) -> Self:
        if len(self.allowed_co_signals) != len(set(self.allowed_co_signals)):
            raise ValueError("rare-evidence co-signals must be unique")
        if len(self.planned_evidence_fields) != len(set(self.planned_evidence_fields)):
            raise ValueError("planned rare-evidence fields must be unique")
        return self


class ScoringConfig(EchoesModel):
    """Typed future-scoring governance without activating an analysis engine."""

    schema_version: Literal[2]
    status: Literal["planned"]
    random_seed: int = Field(ge=0)
    components: list[ScoreComponent]
    null_models: NullModelsConfig
    rare_evidence: RareEvidenceConfig


class ModelSpec(EchoesModel):
    """A pinned model declaration for a later experiment."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["planned", "approved"]


class ModelsConfig(EchoesModel):
    """Model registry; intentionally empty during Milestone 0."""

    schema_version: Literal[1]
    offline_only: bool
    models: list[ModelSpec]


class ReviewConfig(EchoesModel):
    """Placeholder review policy without a review application."""

    schema_version: Literal[1]
    status: Literal["planned"]
    preserve_rejections: Literal[True]
    require_evidence_trace: Literal[True]


CONFIG_SCHEMAS: Mapping[str, type[BaseModel]] = {
    "corpora.yaml": CorporaConfig,
    "normalization.yaml": NormalizationConfig,
    "hebrew_ingestion.yaml": HebrewIngestionConfig,
    "greek_ingestion.yaml": GreekIngestionConfig,
    "segmentation.yaml": SegmentationConfig,
    "scoring.yaml": ScoringConfig,
    "models.yaml": ModelsConfig,
    "review.yaml": ReviewConfig,
}
REQUIRED_CONFIG_FILES: frozenset[str] = frozenset(CONFIG_SCHEMAS)


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Local runtime paths and logging level."""

    config_dir: Path = Path("config")
    output_dir: Path = Path("outputs")
    log_level: str = "INFO"

    ENV_PREFIX: ClassVar[str] = "ECHOES_"

    @classmethod
    def from_environment(cls) -> RuntimeSettings:
        """Build settings from documented environment variables."""
        return cls(
            config_dir=Path(os.getenv("ECHOES_CONFIG_DIR", "config")),
            output_dir=Path(os.getenv("ECHOES_OUTPUT_DIR", "outputs")),
            log_level=os.getenv("ECHOES_LOG_LEVEL", "INFO").upper(),
        )


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ConfigLoadError(f"configuration file does not exist: {path}")

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigLoadError(f"could not parse {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigLoadError(f"configuration root must be a mapping: {path}")
    if not all(isinstance(key, str) for key in loaded):
        raise ConfigLoadError(f"configuration keys must be strings: {path}")
    return cast(dict[str, object], loaded)


def schema_for_path(path: Path) -> type[BaseModel]:
    """Select the strict schema associated with a configuration path."""
    if path.parent.name == "experiments":
        return ExperimentManifest
    try:
        return CONFIG_SCHEMAS[path.name]
    except KeyError as exc:
        raise ConfigLoadError(f"no configuration schema is registered for {path}") from exc


def load_config(path: Path) -> BaseModel:
    """Load one YAML file and validate it against its registered Pydantic schema."""
    values = _load_yaml_mapping(path)
    schema = schema_for_path(path)
    try:
        return schema.model_validate(values)
    except ValidationError as exc:
        raise ConfigLoadError(f"validation failed for {path}:\n{exc}") from exc


def validate_config_directory(config_dir: Path) -> dict[Path, BaseModel]:
    """Validate every project YAML configuration and require the Milestone 0 set."""
    if not config_dir.is_dir():
        raise ConfigLoadError(f"configuration directory does not exist: {config_dir}")

    paths = sorted(config_dir.rglob("*.yaml"))
    if not paths:
        raise ConfigLoadError(f"no YAML configuration files found in {config_dir}")

    validated = {path: load_config(path) for path in paths}
    experiment_locations: dict[str, Path] = {}
    for path, model in validated.items():
        if not isinstance(model, ExperimentManifest):
            continue
        previous = experiment_locations.get(model.experiment_name)
        if previous is not None:
            raise ConfigLoadError(
                f"duplicate experiment_name '{model.experiment_name}' in {previous} and {path}"
            )
        experiment_locations[model.experiment_name] = path
    present_root_files = {path.name for path in paths if path.parent == config_dir}
    missing = sorted(REQUIRED_CONFIG_FILES - present_root_files)
    if missing:
        missing_list = ", ".join(missing)
        raise ConfigLoadError(f"required configuration files are missing: {missing_list}")
    return validated
