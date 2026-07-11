# Tier 1 explicit-quotation benchmark curation instructions

Status: **planned; schema only, no curated rows**

These instructions govern the future Project Echoes Tier 1 benchmark of explicit New Testament quotations of Old Testament passages. The target of approximately 300 reviewed entries is descriptive, not a quota that permits lowering evidentiary standards.

## Allowed source indexes

Curators may begin from the public-domain *Treasury of Scripture Knowledge* and from other quotation indexes only after their specific edition is verified as public domain or used under an explicit compatible license and recorded in the source manifest. The OpenBible.info graph may suggest leads under its Tier 3 role, but it cannot independently establish a Tier 1 row. Public accessibility, age of a website, or the absence of a copyright notice is not proof of public-domain status.

Copyrighted UBS, Nestle-Aland, or comparable quotation/allusion appendices are not import sources. They may be manually consulted where lawful, but their selection, organization, wording, labels, or systematic contents must not be copied or reconstructed.

## Row-level provenance

Every row must record a stable `quotation_id`, edition-specific `nt_reference` and `ot_reference`, `ot_source_tradition`, `relationship_class`, any explicit `quotation_marker`, the exact bibliographic or URL-level `curation_source`, the source's `source_public_domain_status`, the named `curator`, `review_status`, and explanatory `notes`. Notes must distinguish evidence observed in the biblical texts from a lead supplied by an index and must identify relevant editions or witnesses.

`source_public_domain_status` uses `verified_public_domain`, `compatible_license_documented`, `permission_documented`, or `unresolved`. `review_status` uses `pending`, `needs_adjudication`, `verified`, `ambiguous`, or `rejected`. A non-public-domain source needs its exact license or permission in the row provenance; the status label alone is not a rights determination.

A row lacking a traceable source, rights determination, or edition-specific references remains `pending` and cannot enter a release or evaluation split.

## Relationship classifications

Accepted Tier 1 rows use one of these controlled classes:

- `direct_quotation_formula_marked` — an explicit introductory or concluding quotation formula identifies the reuse.
- `direct_quotation_unmarked` — sustained, identifiable quotation is present without an explicit formula.
- `composite_quotation` — one New Testament context combines identifiable material from multiple source passages.
- `adapted_direct_quotation` — the quotation is explicit but materially adapted, abbreviated, or expanded.
- `ambiguous` — boundaries, source, or quotation status remain unresolved; this class is reviewable but not an accepted Tier 1 positive.

Probable allusions, possible echoes, thematic relationships, and generic parallels do not belong in this explicit-quotation tier.

## Source-tradition identification

`ot_source_tradition` records one of `hebrew`, `septuagint`, `both_or_indeterminate`, `other_named_witness`, or `unresolved`, with the edition or witness named in `notes`. Hebrew-versus-Septuagint identification requires direct comparison of the relevant original-language passages and cannot be inferred from an English rendering. Where wording is compatible with more than one tradition, use `both_or_indeterminate`; do not force a choice. Statistical lemma alignment may support later analysis but cannot replace this human determination.

## Duplicate and ambiguous-source handling

Exact duplicate NT–OT pairs are one row with all independent curation sources cited. Repeated quotation events in distinct New Testament contexts remain distinct rows. Composite quotations use one row per quotation event, list every component source in a deterministic order, and explain the components in `notes`. Near-duplicates and members of the same quotation family receive a shared leakage group in the later benchmark schema before evaluation splitting.

If several plausible source passages compete, retain the row as `pending` or `ambiguous`, list each alternative, and state why the source is unresolved. Do not create multiple positive rows merely to avoid adjudication.

## Review procedure

1. A curator records the candidate and all required provenance without consulting evaluation predictions.
2. The curator verifies the NT and proposed OT passage in identified original-language editions, including context and quotation marker.
3. A second qualified reviewer independently checks quotation status, boundaries, source tradition, references, provenance, and rights status.
4. Disagreement remains visible as `needs_adjudication`; an adjudicator records the resolution and rationale.
5. Only `verified` rows enter the released Tier 1 positive set. `pending`, `needs_adjudication`, `ambiguous`, and `rejected` rows remain auditable but are excluded from positive evaluation.
6. Before release, automated checks validate the schema, uniqueness, controlled values, required notes, provenance, licensing, and leakage groups; a human confirms the generated diff.

Human verification is mandatory. An imported label, script, model, or LLM cannot mark a row `verified`.

## Project licensing

The resulting Project Echoes-authored selection, classifications, and curation metadata will be released under CC BY 4.0 with Project Echoes attribution and modification notices. This license applies only to original project contributions. It does not relicense biblical text, third-party indexes, bibliographic works, or source annotations. Released rows contain references and project metadata, not copied copyrighted appendix content or substantial biblical text. Any source with incompatible terms is excluded or requires a separately documented permission decision.
