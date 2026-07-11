"""Typed configuration loading for Project Echoes."""

from __future__ import annotations

import os
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


class GreekNormalization(EchoesModel):
    """Deferred Greek normalization policy."""

    status: Literal["planned"]
    preserve_source_form: Literal[True]
    transformations: dict[str, bool]


class NormalizationConfig(EchoesModel):
    """Normalization configuration for the primary source languages."""

    schema_version: Literal[2]
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


Granularity = Literal["clause", "sentence", "verse", "two_verse", "five_verse"]


class SegmentationConfig(EchoesModel):
    """Planned passage granularities."""

    schema_version: Literal[1]
    status: Literal["planned"]
    granularities: list[Granularity]
    preserve_token_boundaries: Literal[True]


class ScoreComponent(EchoesModel):
    """A disabled or enabled transparent score component."""

    name: str = Field(min_length=1)
    enabled: bool
    weight: float = Field(ge=0)


class ScoringConfig(EchoesModel):
    """Seed and placeholder score components."""

    schema_version: Literal[1]
    status: Literal["planned"]
    random_seed: int = Field(ge=0)
    components: list[ScoreComponent]


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
