"""Source-specific corpus ingestion adapters."""

from echoes.ingest.macula_hebrew import (
    AdapterResult,
    HebrewIngestionError,
    IngestionSummary,
    parse_macula_hebrew_nodes,
    validate_canonical_identities,
)

__all__ = [
    "AdapterResult",
    "HebrewIngestionError",
    "IngestionSummary",
    "parse_macula_hebrew_nodes",
    "validate_canonical_identities",
]
