# Closest prior computational projects

Status: **Initial Milestone 1 comparison**
Search review date: 2026-07-10

These five primary-source precedents were selected for overlap with original-language biblical corpora, computational candidate discovery, whole-corpus or all-pairs scale, Project Echoes detector families, and reproducible evaluation. “Closest” is provisional and search-relative; continued literature review may change the set.

## Comparison

| Work | Corpus and method | Direction and scale | Detector families | Known-link treatment | Rejections/errors | Difference from Project Echoes |
|---|---|---|---|---|---|---|
| [Naaijer & Roorda 2016](https://arxiv.org/abs/1603.01541), [code/data](https://github.com/ETCBC/parallels) | Complete ETCBC Masoretic Text; all-by-all chunks using lexeme-set overlap, Levenshtein/LCS similarity, thresholds, cliques, and synoptic visualization | Undirected across the complete Masoretic Text; no Greek NT | Related transparent lexical/order measures | Known parallels serve as qualitative checks; no broad knownness exclusion | Reports 165 parameter runs, misses, drifting cliques, and formulaic matches; no adjudicated persistent ledger | Closest whole-Hebrew lexical precedent, but lacks Greek NT, independent semantic/syntactic/narrative detectors, broad knownness filtering, and review history |
| [McGovern et al. 2024](https://aclanthology.org/2024.ml4al-1.26/) | Leningrad Codex and Greek LXX/SBLGNT; OpenBible links train Siamese transformer retrieval; scholarly type-scene phrases query the corpus | Directed query-to-candidate retrieval; not the exact 66-book discovery boundary | One neural retrieval family with several pretrained encoders | Known links are weak supervision, not later exclusion | Manual error analysis notes irrelevant returns and confirmation bias; no rejection dataset | Direct narrative-retrieval precedent, but query-led, weakly supervised, low-recall, and not an independent-evidence ensemble |
| [McGovern, Sirin & Lippincott 2025](https://aclanthology.org/2025.naacl-short.13/), [code/data](https://github.com/comp-int-hum/literary-translation) | Complete Hebrew OT; E5 embeddings, cosine matrices, paired-versus-nonpaired sliding-window structure, and z-score threshold | Undirected local structural scan; no Greek NT and not a general distant-passage search | One embedding-based structural detector | No known-link exclusion reported | Top 100 annotated as chiastic, non-chiastic repetition, or no repetition | Strong structural precedent, but one local phenomenon, representation family, and language |
| [Smiley 2025](https://arxiv.org/abs/2506.24117), [code/data](https://github.com/dmsmiley/detect-bh) | BHSA; 558 established Chronicles–Samuel/Kings parallels; several transformer embeddings evaluated by similarity distributions and nearest-neighbor classification | Directed and restricted to Chronicles against Samuel/Kings | Several models from one dense-embedding family | Known links define positives; every unlisted comparison is treated as negative | Quantifies false positives but does not preserve reviewed discovery candidates | Useful semantic benchmark, but neither undirected, whole-canon, original-evidence-transparent, nor multi-family |
| [de la Selle & Mellerin 2026](https://doi.org/10.3390/rel17010088), [code/data](https://github.com/Tdelaselle/Psalms_in_NT) | 3,093 LXX Psalm verse-parts × 7,939 GNT verses; token, lemma, POS, stop-word, synonym, and semantic-domain representations with unsupervised scoring/clustering | All-pairs within fixed Psalms-to-NT direction; not whole canon | Literal, grammatical, lexical, and semantic channels derived from correlated pair representations | Top results checked against a 614-item literature-derived set | Reviews 68 possible additions and reports none as useful for exegetical/theological analysis; persistent ledger unknown | Closest transparent multi-representation Greek intertext detector, but limited corpus/direction and lacks Hebrew triangulation, broad knownness search, and independent detector agreement |

## Comparison conclusions

The prior work establishes that component methods—lexical reuse detection, neural retrieval, chiasmus scoring, semantic embeddings, and multi-representation Greek comparison—are known. Project Echoes therefore does not claim invention of these components.

In the primary sources checked, no single project was found that combines the exact Hebrew/Aramaic Old Testament plus Greek New Testament primary boundary, undirected cross-corpus candidate generation, independent lexical/semantic/syntactic/narrative/structural/anomaly families, multi-source knownness filtering, and a persistent ledger retaining accepted, rejected, and artifact candidates. This supports the charter's provisional integration statement only. It does not establish universal novelty.

## Methodological traps fixed before exploration

1. **Similarity is not discrimination.** High embedding similarity can also characterize negatives. Scalar cosine alone is not evidence; distribution separation, hard negatives, and inspectable features are required.
2. **Known-link supervision can reproduce existing bias.** Cross-reference training can encode English-translation, popularity, and editorial bias. Training, evaluation, and knownness collections remain distinct.
3. **Unlisted does not mean negative.** Incomplete known-link lists can place genuine or disputed relationships in a negative class. Such examples are unlabeled until reviewed.
4. **Textual-unit choice changes results.** Fixed chunks, verses, half-verses, clauses, and narrative windows behave differently. Several preregistered granularities are evaluated.
5. **Correlated representations are not independent confirmation.** Token, lemma, synonym, and semantic-domain views may share errors and evidence. Detector independence is argued, not counted mechanically.
6. **Top-k precision does not establish recall or prevalence.** Reviewing only top results can show ranking utility but not corpus-wide completeness.
7. **Model-selected additions can leak into evaluation.** Detector discoveries must not be added to a benchmark and then used as independent evidence for that same detector.
8. **Formula and genre create persuasive false positives.** Rarity, adjacency, book, genre, passage length, formulaic language, and alternative-source controls are mandatory.

## Verified citations

- Martijn Naaijer and Dirk Roorda, “Parallel Texts in the Hebrew Bible, New Methods and Visualizations” (2016), [arXiv:1603.01541](https://doi.org/10.48550/arXiv.1603.01541).
- Hope McGovern, Hale Sirin, Tom Lippincott, and Andrew Caines, “Detecting Narrative Patterns in Biblical Hebrew and Greek” (2024), [ML4AL/ACL Anthology](https://doi.org/10.18653/v1/2024.ml4al-1.26).
- Hope McGovern, Hale Sirin, and Tom Lippincott, “Computational Discovery of Chiasmus in Ancient Religious Text” (2025), [NAACL](https://doi.org/10.18653/v1/2025.naacl-short.13).
- David M. Smiley, “Intertextual Parallel Detection in Biblical Hebrew: A Transformer-Based Benchmark” (2025), [arXiv:2506.24117](https://doi.org/10.48550/arXiv.2506.24117).
- Théotime de la Selle and Laurence Mellerin, “Detection and Typology of Psalmic Text Reuses in the New Testament” (2026), [Religions 17(1):88](https://doi.org/10.3390/rel17010088).
