# 0019 — Defer the LXX bridge and govern the supplemental embedding model

- Status: Accepted
- Date: 2026-08-08
- executing_agent: Codex

## Context

[ADR 0018](0018-close-m7-and-authorize-final-discovery-v1.md) makes a
Septuagint bridge optional for `final-discovery-v1`: a documented deferral
cannot block the campaign. The same experiment preregisters one optional
multilingual embedding model. Both choices require exact upstream identities,
license boundaries, and evidentiary limits before the production boundary can
be frozen.

The review is operational governance, not legal advice. It inspected upstream
metadata and notices but did not acquire an LXX corpus into Project Echoes and
did not download model weights or tokenizer assets.

## Decision

### Defer LXX activation without blocking `final-discovery-v1`

No LXX text, morphology, lemma layer, or Hebrew–Greek alignment is activated
for this campaign. The final experiment remains valid without an LXX bridge.
The preferred starting point for a later, separately governed bridge is the
Swete TEI transcription in
[OpenGreekAndLatin/First1KGreek at commit
`bfea9acd07ee1b7cea70cdd927c8f092d5637695`](https://github.com/OpenGreekAndLatin/First1KGreek/tree/bfea9acd07ee1b7cea70cdd927c8f092d5637695),
specifically the `data/tlg0527/**/tlg0527.*.1st1K-grc1.xml` files and an
explicit 39-book project-canon allowlist.

The TEI headers identify Henry Barclay Swete's printed *Old Testament in
Greek* volumes (1896, 1901, and 1905), which Project Echoes treats as public
domain in the United States. The separately created electronic TEI is licensed
under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), both in
the file-level headers and in the repository's
[pinned license](https://github.com/OpenGreekAndLatin/First1KGreek/blob/bfea9acd07ee1b7cea70cdd927c8f092d5637695/license.md).
Raw redistribution is therefore considered legally possible only with the
required creator/source attribution, license link and notice, modification
marking, and applicable ShareAlike treatment. Public redistribution of a
normalized, tokenized, aligned, indexed, or otherwise derived dataset still
requires a release-specific review of attribution, adaptation, database, and
mixed-source obligations.

Swete TEI is not ready for activation. It supplies encoded Greek text, not a
validated full-canon morphology, lemma layer, or Hebrew alignment. A later
adapter must also audit OCR/encoding corrections, markup, book selection,
recensional and edition identity, tokenization, and LXX/MT versification.

Three related candidates do not cure that gap for this campaign:

- [Open Scriptures GreekResources at commit
  `dd5a2fd530ab3c6b748c174cec38966c356d8111`](https://github.com/openscriptures/GreekResources/tree/dd5a2fd530ab3c6b748c174cec38966c356d8111)
  releases its own resources [under CC BY 4.0](https://github.com/openscriptures/GreekResources/blob/dd5a2fd530ab3c6b748c174cec38966c356d8111/README.md)
  and may be useful for a future lemma layer. Its
  [LxxLemmas documentation](https://github.com/openscriptures/GreekResources/blob/dd5a2fd530ab3c6b748c174cec38966c356d8111/LxxLemmas/readme.md)
  says the records conform to the CCAT `lxxmorph` ordering. That CATSS/Rahlfs
  lineage cannot be positionally joined to Swete without a validated edition,
  token, and versification crosswalk.
- CATSS/CCAT remains unsuitable for `final-discovery-v1`. The
  [project description](https://ccat.sas.upenn.edu/rak/catss.html) and
  [source-specific user declaration](https://ccat.sas.upenn.edu/gopher/text/religion/biblical/lxxmorph/0-user-declaration.txt)
  do not provide the clean open, redistributable, component-complete path the
  campaign needs, and the Greek text/annotations are tied to a Rahlfs lineage
  rather than the selected Swete candidate. Rahlfs-Hanhart is not substituted
  because it is a copyrighted modern critical edition.
- [UD Ancient Greek PTNK at commit
  `818fb315ff1f6cd95b6e7fa90f3707488d2b010d`](https://github.com/UniversalDependencies/UD_Ancient_Greek-PTNK/tree/818fb315ff1f6cd95b6e7fa90f3707488d2b010d)
  is [CC BY-SA 4.0](https://github.com/UniversalDependencies/UD_Ancient_Greek-PTNK/blob/818fb315ff1f6cd95b6e7fa90f3707488d2b010d/LICENSE.txt)
  and contains only Genesis and Ruth from a Codex Alexandrinus text. It may
  support a bounded future adapter or alignment QA sample, but it is not a full
  LXX bridge and cannot stand in for the Swete edition.

### Pin and constrain the optional embedding model

The only preregistered embedding model is
[`intfloat/multilingual-e5-small` at revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3).
The [pinned model card](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)
declares the MIT license. The allowed artifact set is closed and authenticated
by SHA-256:

| Artifact | SHA-256 |
|---|---|
| `1_Pooling/config.json` | `987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0` |
| `config.json` | `69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959` |
| `model.safetensors` | `1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477` |
| `modules.json` | `c6e29747481e8b5dd2b58401966aeac910de39092f90cda9a704b1545f902b04` |
| `sentence_bert_config.json` | `948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529` |
| `sentencepiece.bpe.model` | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |
| `special_tokens_map.json` | `d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7` |
| `tokenizer.json` | `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39` |
| `tokenizer_config.json` | `a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b` |

This lineage is the SentenceTransformers module configuration, XLM-R
SentencePiece tokenizer configuration, and safetensors weights recorded in
`config/experiments/final-discovery-v1.yaml`. It fixes 384-dimensional
mean-pooled, L2-normalized embeddings, a 512-token maximum, and the symmetric
`query: ` prefix. The production environment must use only those files and the
dependency versions frozen in the preregistration; a mutable model name or a
different backend export is not equivalent.

The model is supplemental retrieval evidence, not philological evidence or
proof of literary dependence. Its performance on modern multilingual tasks
does not validate Ancient Greek or Biblical Hebrew semantics. Broad web-based
pretraining makes exposure to biblical text, translations, commentary, or
evaluation links possible and unquantified. Consequently, cosine similarity
alone cannot create Tier A eligibility, the model remains in its own
`pretrained_semantic` independence group, tokenizer/truncation diagnostics are
required, and English-gloss embeddings remain separately marked and ablated.

## Rationale

Activating raw Swete text without compatible morphology and alignment would
add substantial edition, tokenization, versification, licensing, and QA work
without supplying a reliable bridge on the campaign schedule. Joining a
Rahlfs-ordered lemma stream to Swete by position would silently manufacture
provenance. CATSS terms and modern-edition rights add publication uncertainty.
The bounded UD sample is useful for testing but cannot resolve full-corpus
coverage.

Pinning the optional model by revision and file hash prevents silent upstream
drift while preserving a small, reproducible semantic baseline. Its explicit
scientific limits prevent a pretrained representation from being mistaken for
independent historical or philological confirmation.

## Consequences

- LXX absence is a recorded limitation, not a failed acceptance gate for
  `final-discovery-v1`.
- No LXX acquisition command, adapter, corpus rows, or alignment is added in
  this campaign.
- A later LXX activation needs a new source-manifest entry, exact file
  allowlist and hashes, adapter, corpus/versification validation, component
  attribution, derived-output review, and superseding ADR.
- A later Swete/GreekResources combination must establish an evidence-backed
  cross-edition mapping; ordinal position is never sufficient.
- Model acquisition, if separately performed during production preparation,
  must authenticate every allowed file before inference and must preserve the
  MIT notice. No model artifact is committed to Git.
- Reports must disclose possible pretraining exposure and describe embedding
  hits as supplemental retrieval signals.

## Alternatives considered

- Activate Swete as unannotated text now: rejected because it does not supply
  the validated morphology/alignment required for the intended bridge.
- Join GreekResources lemmas to Swete by verse and word number: rejected until
  a cross-edition alignment proves each mapping.
- Use CATSS/Rahlfs or Rahlfs-Hanhart as the production bridge: rejected for
  this campaign because its agreement, component provenance, redistribution,
  edition, and derived-output boundary are not acceptably resolved.
- Promote UD PTNK to the bridge corpus: rejected because its Genesis-and-Ruth
  sample and Codex Alexandrinus identity do not match full-corpus needs.
- Allow an unpinned hosted embedding endpoint: rejected because model bytes,
  preprocessing, privacy, and reproducibility would be unverifiable.
