# `final-discovery-v1` architecture and reproduction contract

Status: locally implemented and preregistered; production not launched

Semantic preregistration SHA-256:
`7b5c511fed3be041576f9c2ea784d71e028a0f539d7642d84ddcf61eccd22627`

Exact YAML file SHA-256:
`a38c2f6d1c3d84264c7b81a8a62c3a84cae8b993894f6634e339958cdc1f76b0`

The semantic hash is computed from the strictly validated model, independent
of YAML whitespace. The file hash authenticates the tracked bytes. Any
scientific change requires a new experiment identity and new hashes; neither
hash may be refreshed merely to match post-result tuning.

## Question and scope

The experiment asks:

> Can independent lexical, semantic, grammatical/syntactic, structural, and
> anomaly evidence identify passage relationships that survive knownness
> filtering, data-quality controls, English-feature ablation, and empirical
> null calibration?

The primary scope is whole-canon verse passages: Hebrew/Aramaic Old Testament
Qere and Greek New Testament source reading under `edition_complete`.
Critical-core Greek and Ketiv are distinct sensitivity records. They never
overwrite or silently annotate the primary passage text.

This is a retrieval and review experiment. A high score, Tier B rank, or
absence from the pinned OpenBible snapshot is not proof of dependence,
quotation, novelty, or discovery.

## Authenticated inputs

The campaign consumes, rather than recomputes, the sealed M7 lexical tree in
Backblaze B2 at
`project-echoes-archive/m7/canonical-schema-v1`. Stage 1 authenticates the
bucket and prefix, recursive object inventory, exact
`table-hashes.json` SHA-256
`e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6`,
the declared table hashes, and every manifest-listed file after
materialization. It then makes a bounded lexical projection; it never invokes
M7 candidate generation.

The prepared passage projection is derived from the governed Milestone 5
verse rows and canonical token tables. Every feature sequence retains passage,
profile, reading, source digest, and token alignment. The pinned OpenBible
mapping is used in both directions for knownness. The separate
`final-discovery-positive-controls-v1` dataset contains 24 reference-only,
manually checked rows in eight leakage groups (15 train, 3 development, 6
test); it neither modifies M7 nor stores UBS match text or biblical text. The
six test rows all belong to one correlated leakage group
(`PCL_LAST_SUPPER`). No independent scholar adjudicated their
original-language relationship labels. Recovery is therefore descriptive and
cannot establish independent held-out generalization or ancient-language
validity.

Secrets are never configuration values. The B2 adapter reads only
`B2_APPLICATION_KEY_ID` and `B2_APPLICATION_KEY` from the process environment,
creates an ephemeral rclone configuration in the child environment, redacts
subprocess errors, and binds all writes to one immutable destination prefix.
Only empty, exactly complete, or safely resumable exact-partial prefix state
is accepted.

## Detector families

| Family | Smallest registered implementation | Independence treatment |
| --- | --- | --- |
| Lexical | Authenticated M7 RRF score and its original evidence/ablation digests | All M7 subdetectors and lemma/root restatements share `lexical_m7` |
| Semantic | Source semantic-domain TF-IDF/overlap; ordered lemma/root representation; pinned multilingual E5 original-language embeddings; separately marked literal-English-gloss embeddings | Semantic annotations and pretrained semantics have separate registered groups; lemma/root shares the lexical group; English never counts independently |
| Grammar/syntax | IDF-weighted POS, morphology, source frame/clause patterns, global sequence alignment, registered grammatical markers, and rare combinations | All grammar subdetectors share `grammar_annotations` |
| Structure/narrative | Source frame, participant, entity, transition, action-progression, and possible role-reversal fingerprints | One `structural_annotations` group; no generated ontology or LLM features |
| Anomaly | Book/genre/corpus/length-stratified representation disagreement, lexical-semantic gap, unexpected-neighbor context, and formulaic downweight | Diagnostic `anomaly_diagnostic`; never independent proof |

Sparse and embedding retrieval are blockwise top-k operations. No dense
whole-canon all-pairs matrix is permitted. Global sequence alignment keeps two
rows in memory and runs only on candidate pairs.

The optional encoder is `intfloat/multilingual-e5-small` at commit
`614241f622f53c4eeff9890bdc4f31cfecc418b3`, with a nine-file exact allowlist,
MIT license, 384 dimensions, mean pooling plus L2 normalization, a 512-token
limit, and `query: ` on both sides for symmetric retrieval. The `models`
dependency group is exact and non-default, uses the official PyTorch CPU
index, and is installed only on the production host. The model was not
downloaded during local implementation. Broad web pretraining creates
possible, unquantified biblical/benchmark exposure; model similarity is
supplemental retrieval evidence, not philological evidence, and cosine alone
cannot produce Tier A.

## Normalization, nulls, and ensemble

Every evidence row retains raw score, normalized score, normalization method,
empirical p-value, null method, detector/family/independence identity,
English-derived status, trace JSON, source artifact ID, and source SHA-256.
Normalization is the detector's preregistered empirical percentile, rank
percentile, or within-stratum z-score transform.

Within each independence group, the maximum registered normalized detector
score is retained. Missing groups are zero. The final score is the frozen
weighted mean:

| Independence group | Weight |
| --- | ---: |
| `lexical_m7` | 0.20 |
| `semantic_annotations` | 0.18 |
| `pretrained_semantic` | 0.14 |
| `english_bridge` | 0.03 |
| `grammar_annotations` | 0.20 |
| `structural_annotations` | 0.20 |
| `anomaly_diagnostic` | 0.05 |

The remove-all-English ablation sets the English group to zero while retaining
the registered denominator. Family-level controls use seeded conditioned
permutations. The final null independently reassigns group scores within the
registered corpus/genre/length strata, preserving every group marginal while
breaking multi-family conjunction. Candidate empirical p-values use the
finite-sample `+1` upper-tail correction; the ensemble estimates empirical FDR
from per-replicate candidate counts and applies Benjamini-Hochberg across the
complete retained hypothesis family. Thresholds and seeds are frozen before
candidate identity review.

## Output tiers

Tier A (`statistically_eligible`) requires all of the following:

1. ensemble score at least 0.65;
2. BH q-value at most 0.05;
3. estimated empirical FDR at most 0.20;
4. at least two distinct, qualifying, original-language-capable evidence
   families at normalized group score 0.90 or higher;
5. unknown status after checking OpenBible mappings in both directions;
6. no unresolved trace/overlap/data error and no preregistered disputed-text,
   reference-gap, or Ketiv-uncertainty quality exclusion; and
7. a passing remove-all-English ablation whenever English-derived evidence is
   present.

Tier B (`exploratory_not_statistically_accepted`) is the highest-scoring 100
unknown, non-Tier-A candidates after basic exclusions, sorted by score and
stable candidate ID. Tier A and Tier B are disjoint. Known, rejected, and
excluded pairs remain retained with reasons. An empty Tier A is a valid final
result.

## Review and publication artifacts

The review bundle contains a deterministic complete retained-candidate ledger
in CSV and Parquet, its manifest, one concise Markdown dossier for the first
100 score-ranked Tier A candidates and every Tier B candidate, and an Output J
template. Ledger rows include
references, family contributions, original-language traces, separately
labeled supplemental English evidence, knownness, null/FDR and ablation
status, quality flags, classification, rejection category, and notes. Known,
excluded, and rejected rows remain in the complete ledger even though they do
not each create a redundant dossier. Prior reviewer decisions are carried
forward only after exact candidate identity validation; rejected rows are
never deleted.

The required standalone preproduction Output J draft is
[`outputs/publications/output-j-final-discovery-v1-preproduction.md`](../outputs/publications/output-j-final-discovery-v1-preproduction.md).
It freezes the required sections and explicitly marks production and review
fields as placeholders. The generated Output J remains a template until the
production campaign and human review complete. Publication claims must report
Tier A and Tier B separately, review all Tier B rows, retain the
false-positive taxonomy, and state negative outcomes without creating a new
engine.

## Campaign limitations and interpretation boundary

- The primary discovery and calibrated hypothesis scope is whole-canon verse
  passages. Critical-core Greek and Ketiv are registered sensitivities;
  clause, sentence, two-verse, and five-verse interfaces do not establish
  production performance or claims at those granularities.
- Candidate generation is conditioned on the preregistered union of sparse,
  embedding, structural, and bounded M7 retrieval. BH q-values and empirical
  FDR apply to the complete *retained* hypothesis universe, not to every
  mathematically possible canon passage pair. A relationship outside the
  top-k candidate union was not tested by the final ensemble.
- `multilingual-e5-small` transfers from modern multilingual pretraining. Its
  validity for Biblical Hebrew, Biblical Aramaic, and Ancient Greek is not
  independently established. Broad web pretraining may contain biblical text,
  translations, commentary, or benchmark relationships. That exposure is
  unquantified and is not removed by the campaign's explicit English-feature
  ablation.
- Literal-English-gloss embeddings can import translation and annotation
  choices across languages. They are supplemental, never independent
  original-language evidence, and a candidate using them must survive the
  registered remove-all-English ablation. Passing that ablation does not
  validate the ancient-language model or prove the absence of training
  exposure.
- The 24-row positive controls are manually source-checked but descriptive:
  eight leakage groups are too small for broad class claims, their six-row
  test split is one correlated group, and they have no independent
  original-language adjudication.
- No `final-discovery-v1` production artifacts, candidate counts, Tier A or
  Tier B membership, review decisions, dossiers, expected-noise values, or
  scientific conclusions exist at this preproduction boundary. Fixture and
  local validation results establish software behavior only.

## Durable stages

| No. | Stage | Restart boundary |
| ---: | --- | --- |
| 1 | Authenticate and materialize inputs | B2/local inventory and M7 projection receipt |
| 2 | Semantic representations and indexes | Model/inventory lineage plus reusable matrices |
| 3 | Semantic candidate evidence | Raw semantic evidence and retrieval union |
| 4 | Grammatical/syntactic evidence | Raw grammar evidence |
| 5 | Structural/narrative evidence | Raw structural evidence |
| 6 | Anomaly evidence | Stratified diagnostic evidence |
| 7 | Empirical null controls | Detector and ensemble null distributions |
| 8 | Transparent final ensemble | Normalized evidence and retained candidates |
| 9 | Tier A and Tier B outputs | Disjoint tier records and review bundle |
| 10 | Strict validation | Scientific/traceability validation receipt |
| 11 | Assemble authenticated directory, direct B2 upload, verify | Package-tree receipt and exact transfer receipt |

### Scale-safe checkpoint and package persistence

ADR 0020 governs physical persistence for these boundaries. After an
upload-enabled stage completes, the runner reauthenticates its completion and
artifact inventory, then creates a checkpoint payload containing
`checkpoint.json`, `completion.json`, `artifacts/`, and any registered
supplemental files. Existing immutable files are staged with same-filesystem
hardlinks. Hardlink failure blocks checkpointing; the runner never falls back
to a potentially unbounded physical copy.

The complete payload is inventoried by normalized relative path, byte size,
and content hash and uploaded directly as an object tree. A new destination
must be empty. An existing complete destination is accepted only when
`check_tree` proves exact equality. A transport-interrupted strict subset may
be resumed by adding only absent objects with immutable, checksum-aware copy
semantics; unexpected or conflicting objects block the run and nothing is
overwritten or deleted. B2 verification additionally uses downloaded content
comparison so differing backend hash algorithms cannot hide changed bytes.
There is no per-stage tar or other aggregate archive.

Stage 11 likewise creates `upload/package/` as a hardlink-staged authenticated
directory and writes `upload/package-receipt.json`. The receipt declares
`authenticated_directory_v1`, the exact source inventory SHA-256, file count,
total size, hardlink staging, and that no archive was materialized. The full
`upload/` tree is uploaded and checked directly. In the Python API,
`CampaignRunResult.package_path` points to `package-receipt.json`, and
`package_sha256` is the receipt SHA-256; the receipt's source-inventory fields
identify the directory tree itself.

The final package cannot contain proof that Stage 11 itself completed without
creating a circular identity. After Stage 11 completes, the runner therefore
uploads a separate Stage 11 checkpoint whose supplemental inventory contains
`campaign-seal.json` and, in production, the all-11-stage validation report
and receipt. The seal names that checkpoint's exact immutable object-store
prefix. A deterministic local `finalization-receipt.json` then binds the seal,
validation files, Stage 11 completion, complete checkpoint payload inventory,
and verified remote identity. UUID-named per-attempt checkpoint receipts are
also preserved because they record whether that transfer was new, resumed, or
already complete. The cloud cleanup gate requires remote reverification and
durable preservation of both receipt forms.

This is an operational storage/transfer contract only. The stage manifests,
scientific artifact bytes and hashes, detector and null definitions, tier
rules, configuration, and preregistration remain unchanged.

Each completion manifest records the fixed stage specification, attempt ID,
input/dependency hashes, semantic configuration hash, code-tree hash, Git
commit, exact file inventory, and output hash. It is published last without
replacement. Authenticated completions skip safely. Exceptions and abandoned
in-progress attempts retain failure records and staging; no recovery path
deletes them. Thus a stage 8 failure cannot invalidate embeddings, and a stage
11 failure cannot invalidate candidates.

## Bounded resource evidence

The text-free disk benchmark exercises the canonical raw/evidence streams,
all nine registered detectors, detector calibration, both final-null scopes,
the external-sort ensemble, and review offset lookups. The governed medium
shape is 10,000 compact pairs at 20 iterations plus a separate 1,000-pair,
9,000-evidence-row calibration sample, 32 strata, four candidate-sort chunks,
and direct 100,000-score timings of both null kernels at all 1,000 production
iterations. It reads no source text, loads no model, makes no network request,
and starts no cloud resource.

The latest bounded implementation measurement completed in 32.097 seconds on
the Windows development laptop. Detector calibration took 9.159 seconds after
row-wise DuckDB binding was replaced by exact Arrow batch insertion; the
direct permutation-like and bootstrap kernels took 4.112 and 0.995 seconds.
Bit-exact disk-versus-reference tests retain the registered detector, stratum,
candidate, seed, RNG, batching, p-value, and normalization semantics.

Production projection uses the frozen caps independently: 2,592,480 retained
pairs, 11,718,699 raw/calibrated evidence rows, at most 6,633 pair strata and
59,697 detector-strata, 10.123211 billion permutation-like cells, and 1.595488
billion bootstrap cells. It counts the compact group/null integration path
only once. With a 1.25 measured-work safety factor, measured stages project to
20.77 hours. An additional explicit 32-hour planning reserve covers the
unbenchmarked representation/detector feature work, B2 transfer and
verification, strict validation, packaging, and review artifacts. The current
planning range is therefore 20.77--52.77 hours against the 96-hour ceiling.
This is a capacity estimate, not a runtime guarantee or evidence that E5 is
valid for ancient-language similarity.

Projected persistent benchmark artifacts are 121,424,656,152 bytes (113.086
GiB). Including the documented 17.149-GiB M7 tree gives 139,838,254,692 bytes
(130.235 GiB). A 280-GiB-free launch would retain approximately 149.765 GiB,
above the 80-GiB checkpoint floor; the modeled minimum initial free space is
225,737,600,612 bytes (210.235 GiB).

The schema-2 acceptance gate also requires a measurable process peak RSS no
greater than the registered production cgroup `MemoryMax=56G`. A missing peak
RSS measurement fails closed. The benchmark command preserves its report but
returns nonzero whenever the runtime, memory, disk, or exact-cardinality gate
does not pass.

The authoritative report path is
`outputs/reports/final-discovery-preproduction-benchmark.json`. It must be
generated outside the repository from a clean, committed tree and added only
afterward, so its `report_status` is `commit_bound_clean` and its recorded
commit, code hashes, configuration hashes, and report SHA-256 agree. Dirty-tree
development reports are explicitly provisional and must not be promoted as
the launch artifact. The clean report is therefore a post-commit gate, not a
hash that may be predeclared in this document.

## Local reproduction boundary

Normal local setup does not install the model group:

```text
uv sync --locked
uv run echoes validate-config
uv run echoes validate-positive-controls
uv run python scripts/benchmark_final_discovery.py \
  --pairs 10000 --iterations 20 \
  --calibration-pairs 1000 --strata 32 \
  --lookup-count 500 --candidate-chunk-size 250 \
  --kernel-sample-size 100000 --duckdb-memory-mib 512 \
  --work-dir <new-absolute-work-directory> \
  --output <new-absolute-report-path>
uv run echoes run-final-discovery --fixture --work-dir data/processed/final-discovery-fixture
uv run echoes validate-final-discovery --all --work-dir data/processed/final-discovery-fixture
```

The fixture command uses synthetic annotations and a local object-store
fixture, exercises every stage, and starts no cloud resource. The production
command is documented in `docs/final-discovery-cloud-runbook.md`; it refuses
Windows, a missing exact authorization value, dirty/unexpected code identity,
unauthenticated inputs, unpinned model files, Python or installed model-package
version drift, nonmatching output-prefix state, or a foreground/unmanaged
launch. The launcher binds the actual installed versions and initial B2
namespace receipt into its immutable intent. Only an empty prefix, an exactly complete
verified tree, or a resumable exact partial tree can proceed.

## LXX and stop rule

ADR 0019 records the non-blocking LXX deferral. Swete First1KGreek TEI is a
promising future raw text under CC BY-SA 4.0, but this campaign has no
validated full-canon morphology or Hebrew alignment for it. CATSS/Rahlfs paths
remain unsuitable or unresolved. `final-discovery-v1` is valid without LXX;
token-level Hebrew-LXX alignment is out of scope.

After the canonical run and top-100 review, stop building retrieval engines.
A second full run requires separate authorization and is justified only by an
invalidating infrastructure failure, a result worth reproducing, or a
publication-level determinism need.
