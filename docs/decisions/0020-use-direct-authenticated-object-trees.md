# 0020 — Use direct authenticated object trees for production-scale persistence

- Status: Accepted
- Date: 2026-08-08
- executing_agent: Codex

## Context

ADR 0018 requires independently restartable, hash-authenticated stages and an
exactly verified final B2 result for `final-discovery-v1`. The initial
pre-production design language assumed that each completed stage and the final
result would be materialized as deterministic archive files before upload.

At whole-canon scale, archive materialization would create another physical
copy of every included byte on the production SSD. Per-stage archives followed
by a final aggregate archive would make local disk demand grow with the
cumulative checkpoint payload in addition to the authenticated stage store.
That is incompatible with a defensible bounded-disk design: it can consume the
launch reserve or cross the registered disk-abort floor even though the
scientific artifacts themselves remain valid. The existing stage completion
manifests already bind every artifact path, size, SHA-256, dependency,
configuration identity, and code identity, so an additional byte container is
not needed to establish scientific identity.

## Decision

1. Persist every durable stage checkpoint as a direct authenticated object
   tree. Its payload contains `checkpoint.json`, the exact `completion.json`,
   the stage `artifacts/` tree, and any explicitly inventoried supplemental
   files. No tar, compressed tar, or other aggregate archive is materialized.
2. Build each local checkpoint payload with same-filesystem hardlinks to the
   already authenticated stage files. The operation fails closed if hardlinks
   cannot be created or do not resolve to the same file; it does not fall back
   to an unbounded physical copy. New checkpoint metadata remains separately
   written and authenticated.
3. Inventory the complete payload by normalized relative path, byte size, and
   content hash before transfer. Upload only to the stage's registered
   immutable prefix. An empty prefix receives a new upload and a complete
   prefix is accepted only when `check_tree` proves exact equality. A strictly
   partial prefix may be resumed only when every existing path belongs to the
   complete tree and every existing size agrees; local test stores additionally
   require the same SHA-256. The B2 adapter then uses immutable, checksum-aware
   copy semantics to add absent objects without replacing any existing object,
   followed by the same complete-tree verification. Extra, changed, renamed,
   or same-sized conflicting objects remain blocking and preserved.
4. For Backblaze B2, require identical portable path/size inventory identity
   and an `rclone check --download` content comparison. This avoids treating
   B2's commonly exposed SHA-1 metadata as if it were a local SHA-256 while
   still verifying the bytes. The transfer receipt binds store identity,
   portable local and remote inventory hashes, object count, and total size.
5. Persist the final result in the same form. Stage 11 builds
   `upload/package/` as a same-filesystem hardlink tree and writes
   `upload/package-receipt.json` with package format
   `authenticated_directory_v1`, source inventory SHA-256, file count, total
   size, hardlink-staging status, and `archive_materialized=false`. Stage 11
   uploads and verifies the complete `upload/` tree directly; it never creates
   a final archive.
6. Treat this as an operational storage and transfer deviation only. It does
   not alter stage order, scientific inputs, serialized artifact bytes,
   detector definitions, calibration, nulls, ensemble weights, Tier A or Tier
   B rules, seeds, configuration, or preregistration semantics and hashes.
   Stage completion manifests and their artifact hashes remain the scientific
   authorities.
7. In the Python result contract, `CampaignRunResult.package_path` identifies
   `package-receipt.json`, not an archive or the package directory, and
   `package_sha256` identifies that receipt's bytes. The receipt's source
   inventory fields identify the authenticated package tree.
8. Preserve all source stages, checkpoint workspaces, failed attempts, and
   remote partial state for diagnosis. This decision does not authorize
   deletion or replacement of any staging or checkpoint data.
9. Treat the Stage 11 checkpoint as the post-package finalization object. Its
   supplemental inventory contains the campaign seal and, in production, the
   separate all-11-stage validation report and receipt. The seal names the
   exact immutable checkpoint prefix and requires remote reverification before
   server cleanup. After that upload succeeds, write a deterministic local
   `finalization-receipt.json` binding the seal, validation identities, Stage
   11 completion, checkpoint inventory, and verified remote identity. Preserve
   both this binding and every UUID-named per-attempt checkpoint receipt; the
   latter alone records whether transport was new, resumed, or already
   complete. This closes the post-package circularity without changing Stage
   11 or pretending that a receipt can authenticate its own bytes.
10. Before a managed worker starts, inspect the complete registered B2 base
    namespace once. New campaigns require an empty namespace. Restarts allow
    objects only beneath registered checkpoint/final prefixes, and every
    active prefix must be an exact path/size complete tree or strict subset of
    a preserved local transfer tree. Stage-specific immutable transfer still
    performs the content check before accepting or resuming a tree. Bind the
    namespace receipt into the immutable launch intent.

## Rationale

Hardlinks provide another governed directory view of immutable bytes without
allocating a second copy of their data blocks. Direct object-tree transfer
retains independently addressable files, and exact inventory plus downloaded
content verification supplies stronger cross-backend evidence than an archive
name or container hash alone. Failing closed on cross-filesystem staging keeps
the disk bound explicit instead of silently reverting to a potentially
unbounded copy.

The scientific record is already defined by authenticated stage manifests and
canonical artifact bytes. Changing only their local staging and remote
transport container therefore removes a production-scale storage hazard
without changing the experiment being run.

## Consequences

- Stage checkpoint receipts declare
  `transfer_mode=direct_authenticated_tree` and record that local payload files
  use same-filesystem hardlinks.
- The production work directory and checkpoint staging roots must reside on a
  filesystem that supports hardlinks. A cross-filesystem or unsupported
  layout blocks the run instead of copying data.
- The final B2 prefix contains a browsable `package/` object tree beside its
  package receipt, rather than one downloadable tar file. Recovery and audit
  tooling must materialize and authenticate the complete tree.
- Exact relative paths, sizes, object counts, and content are part of transfer
  acceptance. Partial state is never accepted as complete; extra, renamed, or
  changed objects block both resume and verification.
- A transport-interrupted exact partial prefix is resumable without deleting
  it or recomputing its completed scientific stage. Receipts distinguish
  `resumed_partial` from a new upload and verification of an existing complete
  tree. Resume only adds absent objects; it never overwrites or deletes remote
  state.
- There is no single archive hash. The package-receipt SHA-256 authenticates
  the receipt, while the receipt's source-inventory SHA-256 authenticates the
  package tree and the transfer receipt authenticates local-versus-remote
  equality.
- Avoiding archive copies preserves disk headroom but does not reduce the need
  to retain authenticated staging and failed attempts until owner-approved
  cleanup.
- The final package alone is deliberately not the terminal acceptance record:
  the independently uploaded Stage 11 checkpoint carries the campaign seal
  and all-stage validation. Server destruction is blocked until that exact
  remote payload is reverified and its local deterministic and per-attempt
  receipts are copied to durable owner-controlled storage.

## Alternatives considered

- Materialize one uncompressed tar per stage and one final tar: rejected
  because it duplicates large payload bytes on the bounded local SSD.
- Compress the archives: rejected because it still needs aggregate
  materialization and adds substantial CPU, runtime, and failure surface for
  no scientific benefit.
- Fall back to ordinary copies when hardlinks fail: rejected because it makes
  the storage ceiling depend silently on payload size.
- Use filesystem-specific reflinks: rejected as the binding contract because
  support and copy-on-write behavior vary across filesystems and hosts.
- Upload unauthenticated directories and rely on provider metadata alone:
  rejected because backend digest algorithms differ and inventory metadata
  alone does not prove cross-backend byte equality.
