"""Non-negotiable upstream anchors for the Milestone 7 lexical experiment."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import duckdb

from echoes.lexical.resources import configure_duckdb_connection
from echoes.manifest import sha256_file

HEBREW_TOKEN_COUNT = 475_911
GREEK_TOKEN_COUNT = 137_779
CORPUS_IDENTITY_DIGESTS = {
    "hebrew": "91e923e6f4234e3d1946ad6fb1487f5894ec4e28f2fd3c919bf6ebd1680693b6",
    "greek": "9035fea8d73a2b2078ad2adc70f8389040dbe2051ee535b2ce88412f551df6f2",
}
CORPUS_CONTENT_DIGESTS = {
    "hebrew": "7fb443c3f0c42ada5d89f3abad61dd304145863044107ac86277c9f05f76cc82",
    "greek": "a5ede58d287c2d29d5dacc7adeb07ff5c6a10587e2949875928b2dd935c8c683",
}
CORPUS_ANALYTICAL_DIGESTS = {
    "hebrew": "9464a106684b63ff57bcd9dd754bcd0c875d7ea8157fc7bfe643d7eb66dab173",
    "greek": "31404eb29a1f71855f3670f6f895e3fadc3ab0b39e2685c3cf672620df08a2a1",
}
OSHB_LOGICAL_HASHES = {
    "ketiv_tokens": "7bb67cebc45c06943a7f1fc2e241202f100a19cf7ad6dd6b0933d999ac01d238",
    "locus_registry": "ae6e70a8d1dd75cccfef85bb5535051134104f03d57490976d4e30f93c60f022",
    "structural_alignments": "ac0c9ebffe971ef9178ef47edbf868d9f904a189133dccf907f815651b867df9",
}
PASSAGE_RUN_ID = "passages-v1-00e261abea9ed44ef087"
PASSAGE_COUNTS = {
    "passages": 914_497,
    "passage_membership": 21_530_271,
    "passage_adjacency": 913_445,
    "segmentation_exclusions": 148_948,
    "segmentation_issues": 0,
    "segmentation_metadata": 1,
}
PASSAGE_LOGICAL_HASHES = {
    "passages": "00047c9dc16ceaefdc0ff1b18a8fb2b4480a1be0534ed861cf5c11706d2048a0",
    "passage_membership": "726c6b9339a78e7806bac90f7d91930c7f86bec7c7c0be6a51bdedb7a54d40bd",
    "passage_adjacency": "1ca8c79f92b2742e12586b6c72eaddbcc834d5bce818b909f33b2c10b9db69bd",
    "segmentation_exclusions": "6a0e475398e76730b5a7a92370ee319b803c0d17ba45e01b7155fa3b28c7e209",
    "segmentation_issues": "2f3a57eada1dda388ca99bf67cd0b6de70fb31afa1abc1980eafbf605359eac3",
    "segmentation_metadata": "87b88f0b3d4efa88c9d4668ba1eb0aba5fce244b0350130a033deb1a087578cf",
}
PASSAGE_CONTENT_COUNTS = {
    key: value for key, value in PASSAGE_COUNTS.items() if key != "segmentation_metadata"
}
PASSAGE_CONTENT_LOGICAL_HASHES = {
    key: value for key, value in PASSAGE_LOGICAL_HASHES.items() if key != "segmentation_metadata"
}
BENCHMARK_RUN_ID = "benchmark-v1-dff1d3ef650c8ccd4930"
BENCHMARK_VERSION = "known-links-v1-dff1d3ef650c"
OPENBIBLE_SNAPSHOT = "snapshot-2026-07-12-sha256-18e63e370308"
OPENBIBLE_ARCHIVE_SHA256 = "18e63e370308868391a8458cfa7454e3b29bb8f94c0ca11dcac2d267d449c492"
OPENBIBLE_CANONICAL_STREAM_SHA256 = (
    "e3b2b3bb8c0097382ce4385c38342d4d4d07dd3cde05b331c0998a007840482e"
)
TIER1_HEADER_SHA256 = "7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b"
BENCHMARK_LOGICAL_HASHES = {
    "benchmark_source_records": "481e53738ae4f4940277d211176194b97e57908eb31ef172359524165409f1f4",
    "benchmark_relationships": "4bd3d602a2604d425c0016eb7d565667a844b353cb16d0d88f3c369c21a13a6f",
    "benchmark_relationship_source_records": (
        "f215928778e16ef496ec309282a327559d242f520d531240059ecdbe21ba64a1"
    ),
    "benchmark_endpoints": "a9560e443ba32b3900f635421f9390f461fdebe0c23f316ec295b7be28ba13c7",
    "benchmark_endpoint_mappings": (
        "d56e5211a415b51abbfa5080add85ade3ad8d4f30b6c95313fef19e5c6e956e3"
    ),
    "benchmark_leakage_groups": (
        "56c356147c61d12074dbdf88e7ea2dd111e8a2d0e34e7caa530d103e6d66f9d7"
    ),
    "benchmark_split_assignments": (
        "bda3c63f2aa15cd60567fd3a8dae3118402df35fc07921910a218a941c9ac5e0"
    ),
    "benchmark_presumed_negatives": (
        "9bf1ed5dd30c6a93b6ef359cd7d5fd39704f3c0cb3719e17cbcaae5bf524d6ff"
    ),
    "benchmark_issues": "f39d5494a1d13e68e9acf77b44e6c1a38dc419ec52abfb879a26f41165a07de0",
    "benchmark_metadata": "b406ab043ed90ba59204b1b6937ea742ea6d2e66a552a8678934d94b290086d8",
}
BENCHMARK_CONTENT_LOGICAL_HASHES = {
    key: value for key, value in BENCHMARK_LOGICAL_HASHES.items() if key != "benchmark_metadata"
}


class LexicalAnchorError(RuntimeError):
    """Raised immediately when any established input anchor changes."""


@dataclass(frozen=True, slots=True)
class AnchorVerification:
    """Successful exact upstream anchor verification."""

    corpus_counts: dict[str, int]
    corpus_identity_digests: dict[str, str]
    corpus_content_digests: dict[str, str]
    corpus_analytical_digests: dict[str, str]
    oshb_logical_hashes: dict[str, str]
    passage_run_id: str
    passage_counts: dict[str, int]
    passage_logical_hashes: dict[str, str]
    benchmark_run_id: str
    benchmark_version: str
    openbible_snapshot: str
    openbible_archive_sha256: str
    openbible_canonical_stream_sha256: str
    benchmark_logical_hashes: dict[str, str]
    tier1_row_count: int
    tier1_sha256: str


def _json_object(value: object) -> dict[str, object]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise LexicalAnchorError("upstream metadata JSON is not an object")
    return {str(key): item for key, item in parsed.items()}


def _expect(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise LexicalAnchorError(f"upstream anchor changed for {label}: {actual!r} != {expected!r}")


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalAnchorError(f"could not read {label} manifest {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LexicalAnchorError(f"{label} manifest is not a JSON object: {path}")
    return {str(key): value for key, value in parsed.items()}


def verify_upstream_anchors(
    *,
    database_path: Path,
    passage_root: Path,
    benchmark_root: Path,
    tier1_path: Path,
    oshb_root: Path,
    duckdb_memory_limit_bytes: int,
    duckdb_temp_directory: Path,
) -> AnchorVerification:
    """Verify every fixed corpus, OSHB, passage, benchmark, and Tier 1 anchor."""

    passage_manifest = _read_json_object(passage_root / "table-hashes.json", "passage")
    benchmark_manifest = _read_json_object(benchmark_root / "table-hashes.json", "benchmark")
    oshb_manifest = _read_json_object(oshb_root / "table-hashes.json", "OSHB")
    for manifest, key, label in (
        (passage_manifest, "table_counts", "passage counts"),
        (passage_manifest, "table_logical_sha256", "passage logical hashes"),
        (benchmark_manifest, "table_logical_sha256", "benchmark logical hashes"),
        (oshb_manifest, "logical_table_sha256", "OSHB logical hashes"),
    ):
        if not isinstance(manifest.get(key), dict):
            raise LexicalAnchorError(f"upstream manifest field is missing: {label}")
    _expect(passage_manifest["table_counts"], PASSAGE_COUNTS, "passage counts")
    _expect(
        passage_manifest["table_logical_sha256"],
        PASSAGE_LOGICAL_HASHES,
        "passage logical hashes",
    )
    _expect(
        benchmark_manifest["table_logical_sha256"],
        BENCHMARK_LOGICAL_HASHES,
        "benchmark logical hashes",
    )
    oshb_hashes = oshb_manifest["logical_table_sha256"]
    if not isinstance(oshb_hashes, dict):
        raise LexicalAnchorError("OSHB logical hash manifest is not an object")
    observed_oshb = {key: str(oshb_hashes[key]) for key in OSHB_LOGICAL_HASHES}
    _expect(observed_oshb, OSHB_LOGICAL_HASHES, "OSHB logical hashes")
    try:
        tier1_bytes_hash = sha256_file(tier1_path)
        with tier1_path.open(encoding="utf-8", newline="") as handle:
            tier1_rows = sum(1 for _ in csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise LexicalAnchorError(f"could not read Tier 1 fixture {tier1_path}: {exc}") from exc
    _expect(tier1_bytes_hash, TIER1_HEADER_SHA256, "Tier 1 header hash")
    _expect(tier1_rows, 0, "Tier 1 row count")
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            configure_duckdb_connection(
                connection,
                memory_limit_bytes=duckdb_memory_limit_bytes,
                temp_directory=duckdb_temp_directory,
                thread_count=1,
            )
            hebrew_row = connection.execute("SELECT count(*) FROM hebrew_tokens").fetchone()
            greek_row = connection.execute("SELECT count(*) FROM greek_tokens").fetchone()
            if hebrew_row is None or greek_row is None:
                raise LexicalAnchorError("corpus token tables are unavailable")
            corpus_counts = {
                "hebrew": int(hebrew_row[0]),
                "greek": int(greek_row[0]),
            }
            _expect(
                corpus_counts,
                {"hebrew": HEBREW_TOKEN_COUNT, "greek": GREEK_TOKEN_COUNT},
                "corpus counts",
            )
            segmentation = connection.execute(
                "SELECT segmentation_run_id, input_primary_identity_digests_json, "
                "input_surface_lemma_digests_json, input_analytical_digests_json, "
                "input_oshb_supplement_digests_json, table_counts_json, "
                "table_logical_hashes_json FROM segmentation_metadata"
            ).fetchone()
            if segmentation is None:
                raise LexicalAnchorError("segmentation metadata is missing")
            _expect(str(segmentation[0]), PASSAGE_RUN_ID, "passage run ID")
            identity = {k: str(v) for k, v in _json_object(segmentation[1]).items()}
            content = {k: str(v) for k, v in _json_object(segmentation[2]).items()}
            analytical = {k: str(v) for k, v in _json_object(segmentation[3]).items()}
            oshb = {k: str(v) for k, v in _json_object(segmentation[4]).items()}
            _expect(identity, CORPUS_IDENTITY_DIGESTS, "corpus identity digests")
            _expect(content, CORPUS_CONTENT_DIGESTS, "corpus content digests")
            _expect(analytical, CORPUS_ANALYTICAL_DIGESTS, "corpus analytical digests")
            _expect(oshb, OSHB_LOGICAL_HASHES, "segmentation OSHB digests")
            _expect(
                _json_object(segmentation[5]),
                PASSAGE_CONTENT_COUNTS,
                "database passage content counts",
            )
            _expect(
                _json_object(segmentation[6]),
                PASSAGE_CONTENT_LOGICAL_HASHES,
                "database passage content logical hashes",
            )
            benchmark = connection.execute(
                "SELECT benchmark_run_id, benchmark_version, source_archive_hashes_json, "
                "source_audit_json, tier1_header_sha256, source_versions_json, "
                "passage_input_run_id, passage_logical_hashes_json, "
                "logical_table_hashes_json FROM benchmark_metadata"
            ).fetchone()
            if benchmark is None:
                raise LexicalAnchorError("benchmark metadata is missing")
            _expect(str(benchmark[0]), BENCHMARK_RUN_ID, "benchmark run ID")
            _expect(str(benchmark[1]), BENCHMARK_VERSION, "benchmark version")
            archives = _json_object(benchmark[2])
            _expect(
                archives.get("openbible-cross-references"),
                OPENBIBLE_ARCHIVE_SHA256,
                "OpenBible archive hash",
            )
            source_audit = _json_object(benchmark[3])
            _expect(
                source_audit.get("canonical_stream_sha256"),
                OPENBIBLE_CANONICAL_STREAM_SHA256,
                "OpenBible canonical stream hash",
            )
            _expect(str(benchmark[4]), TIER1_HEADER_SHA256, "benchmark Tier 1 hash")
            source_versions = _json_object(benchmark[5])
            _expect(
                source_versions.get("openbible-cross-references"),
                OPENBIBLE_SNAPSHOT,
                "OpenBible snapshot",
            )
            _expect(str(benchmark[6]), PASSAGE_RUN_ID, "benchmark passage input run ID")
            _expect(
                _json_object(benchmark[7]),
                PASSAGE_LOGICAL_HASHES,
                "benchmark passage logical hashes",
            )
            _expect(
                _json_object(benchmark[8]),
                BENCHMARK_CONTENT_LOGICAL_HASHES,
                "database benchmark content logical hashes",
            )
    except (duckdb.Error, OSError, json.JSONDecodeError) as exc:
        raise LexicalAnchorError(f"could not verify upstream DuckDB anchors: {exc}") from exc
    return AnchorVerification(
        corpus_counts=corpus_counts,
        corpus_identity_digests=dict(CORPUS_IDENTITY_DIGESTS),
        corpus_content_digests=dict(CORPUS_CONTENT_DIGESTS),
        corpus_analytical_digests=dict(CORPUS_ANALYTICAL_DIGESTS),
        oshb_logical_hashes=dict(OSHB_LOGICAL_HASHES),
        passage_run_id=PASSAGE_RUN_ID,
        passage_counts=dict(PASSAGE_COUNTS),
        passage_logical_hashes=dict(PASSAGE_LOGICAL_HASHES),
        benchmark_run_id=BENCHMARK_RUN_ID,
        benchmark_version=BENCHMARK_VERSION,
        openbible_snapshot=OPENBIBLE_SNAPSHOT,
        openbible_archive_sha256=OPENBIBLE_ARCHIVE_SHA256,
        openbible_canonical_stream_sha256=OPENBIBLE_CANONICAL_STREAM_SHA256,
        benchmark_logical_hashes=dict(BENCHMARK_LOGICAL_HASHES),
        tier1_row_count=tier1_rows,
        tier1_sha256=tier1_bytes_hash,
    )
