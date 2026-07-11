"""Derived, configuration-selected analysis streams over preserved tokens."""

from __future__ import annotations

from typing import Literal

import polars as pl

AnalysisReading = Literal["qere", "ketiv"]

ANALYSIS_TOKEN_POLARS_SCHEMA = {
    "schema_version": pl.Int16,
    "analysis_reading": pl.String,
    "token_id": pl.String,
    "source_edition_reference": pl.String,
    "variant_group_id": pl.String,
    "variant_type": pl.String,
    "analysis_position_in_verse": pl.Int32,
    "analysis_position_in_clause": pl.Int32,
    "analysis_position_in_corpus": pl.Int64,
}
ANALYSIS_TOKEN_COLUMNS: tuple[str, ...] = tuple(ANALYSIS_TOKEN_POLARS_SCHEMA)


def derive_analysis_stream(
    tokens: pl.DataFrame,
    *,
    analysis_reading: AnalysisReading,
) -> pl.DataFrame:
    """Select one reading from complete pairs and derive continuous positions.

    Unpaired variant annotations remain in the stream because there is no
    alternate source record to select.  The input frame is never mutated.
    """
    if analysis_reading not in {"qere", "ketiv"}:
        raise ValueError("analysis_reading must be 'qere' or 'ketiv'")

    paired_groups = (
        tokens.filter(pl.col("variant_group_id").is_not_null())
        .group_by("variant_group_id")
        .agg(
            pl.col("variant_type").n_unique().alias("reading_count"),
            pl.col("variant_type").eq("qere").any().alias("has_qere"),
            pl.col("variant_type").eq("ketiv").any().alias("has_ketiv"),
        )
        .filter((pl.col("reading_count") == 2) & pl.col("has_qere") & pl.col("has_ketiv"))
        .select("variant_group_id")
        .with_columns(pl.lit(True).alias("is_paired_group"))
    )
    selected = (
        tokens.join(paired_groups, on="variant_group_id", how="left")
        .filter(pl.col("is_paired_group").is_null() | (pl.col("variant_type") == analysis_reading))
        .sort("position_in_corpus")
        .with_columns(
            pl.col("token_id")
            .cum_count()
            .over("book", "chapter", "verse")
            .cast(pl.Int32)
            .alias("analysis_position_in_verse"),
            pl.when(pl.col("clause_id").is_not_null())
            .then(pl.col("token_id").cum_count().over("clause_id"))
            .otherwise(None)
            .cast(pl.Int32)
            .alias("analysis_position_in_clause"),
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).alias("analysis_position_in_corpus"),
        )
        .select(
            pl.lit(1, dtype=pl.Int16).alias("schema_version"),
            pl.lit(analysis_reading).alias("analysis_reading"),
            "token_id",
            "source_edition_reference",
            "variant_group_id",
            "variant_type",
            "analysis_position_in_verse",
            "analysis_position_in_clause",
            "analysis_position_in_corpus",
        )
    )
    return selected.cast(pl.Schema(ANALYSIS_TOKEN_POLARS_SCHEMA)).select(ANALYSIS_TOKEN_COLUMNS)
