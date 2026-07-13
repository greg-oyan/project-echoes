# Milestone 6 spot-check evidence

- Benchmark run ID: `benchmark-v1-dff1d3ef650c8ccd4930`
- Benchmark version: `known-links-v1-dff1d3ef650c`
- Selection: lowest stable identity matching each governed criterion, unless the criterion defines a weight ordering.
- Content boundary: references, identities, mappings, counts, and provenance only; no biblical quotation text is reproduced.
- Manual review verdict: `PASS`
- Manual reviewer: `Codex`
- Manual review date: `2026-07-12`
- Manual field review: selected identity or audited absence, source-record provenance, original references, direction, weight, tier and eligibility, mapping method/status/targets, disputed and gap flags, leakage groups, split assignment, and negative collision controls were checked where applicable.

## Normal Old Testament to Old Testament link

- Status: `selected`
- Matching artifact count: `138898`
- Deterministically selected identity: `BR_0000ddc29a26373a300e5a031b3aa6371a3226bee001b673a2179a320ae376f2`
- Relationship ID: `BR_0000ddc29a26373a300e5a031b3aa6371a3226bee001b673a2179a320ae376f2`
- Original source references: `1Chr.9.3` → `2Chr.11.16`
- Direction: `a_to_b`
- Source weight sum / maximum: `2` / `2`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_3c17b125d06135585731569aa0e72ba1a9e423d8ef22f8af4f94bcf08ff0b5e9 (cross_references.txt:82107, sha256=6b72337d389a5a70eb609b7c9bc3da09d6bd9a194efec41456eff15d51947215, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | 1Chr.9.3 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_1CH_009_003~4d500be04e0517db8b6352ede7c4ac0c8ae8c3170add5b1ca585b96ddd62280f"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | 1Chr.9.3 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_1CH_009_003~7043ab93f34f1793ffe5551f930fff40d54f890b5b6d89271ceb16fe42161aad"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | 2Chr.11.16 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_2CH_011_016~1dbff33aed53da26f37e7c5770351eb3310b7df20320a8c1ac47dc45c2b55cc7"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | 2Chr.11.16 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_2CH_011_016~c3891e4f780b9df77bbe1da0eda57ebc0482f4e7a568ed13c687966012920fe0"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_693998028093520e1f726f5c0dd510588206e6481fda74eaf0c2a4043ecc916d (1CH\|2CH); exact_directed_pair:BLG_3b93d52655aa2318565913d3aef97d8ab04c33f7a5a924ca3ce42c78122aab3d (BDP_50eb1152ffc2aff6b724fd2e27de6430e046a8f0bcb8256d6ecee3fe8928a876); exact_unordered_pair:BLG_dc1fd7e7254ca1149dacc95aec6aa45d64329453663be9699e88bfbfa72e9fc0 (BUP_6faed13315b8d685faa4bf8fcf385373e144cf811cd9956756fefadb21f6e144); overlapping_endpoint_range:BLG_3137804fc5572f1b7ce4764275196c3971d48f5853b49b8c124476e84a986a65 (2CH\|11016); overlapping_endpoint_range:BLG_e4665a5003a91338b8794d080126f0b0c2dc1425345e6f12414b268aa363c623 (1CH\|9003); overlapping_target_passage:BLG_07136dcfb6328f18b507719dbdb058786db4010b16a4c220a099c82e0240bfd4 (1CH\|366); overlapping_target_passage:BLG_5e5f767e0f83f6b8b1c24ee4a8fdf4b1c0007bf7478c41146dd754585c3c73e2 (2CH\|236); shared_endpoint:BLG_331e2158a39c14b9ff204f7f6116dbf84f1d8b4c1d51dcfe5842032687873b41 (1Chr.9.3); shared_endpoint:BLG_f4b4c358cbea770066d8a1124b5e62e39166b63183abd37dc747249b59b97ba1 (2Chr.11.16); shared_target_passage:BLG_7d278c79beab8e1cd458f2248ecc04ecc396c5a348a105aaf4324ca127b02ea9 (P_HB_EDITION_COMPLETE_QERE_VERSE_2CH_011_016~c3891e4f780b9df77bbe1da0eda57ebc0482f4e7a568ed13c687966012920fe0); shared_target_passage:BLG_8c0a781f6c0430e95f9547cf2cf98dc0dd31f32bdd244ec7d9396e5aaf3061dc (P_HB_EDITION_COMPLETE_QERE_VERSE_1CH_009_003~7043ab93f34f1793ffe5551f930fff40d54f890b5b6d89271ceb16fe42161aad)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=train (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Normal New Testament to New Testament link

- Status: `selected`
- Matching artifact count: `62599`
- Deterministically selected identity: `BR_0001342618ecb989b38ed31fa91b22232a1c8ae7dc94bf9bfbb504aac44a0448`
- Relationship ID: `BR_0001342618ecb989b38ed31fa91b22232a1c8ae7dc94bf9bfbb504aac44a0448`
- Original source references: `Gal.2.8` → `Acts.21.19`
- Direction: `a_to_b`
- Source weight sum / maximum: `3` / `3`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_83b7c93b248d9155312bffd0c7c7a419a962b4326e4a64c6d1fc3153cf8f1640 (cross_references.txt:306211, sha256=cd2ad553551306057f02061b142cd495663f44d6364ef70a2979c80e54bfa072, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Gal.2.8 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_GAL_002_008~e9525d7974ee837c4f89171a0057f5203700f94f9dfeca4bad241f9d5c5074ed"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Gal.2.8 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_GAL_002_008~a4eebf2c65fac36b8a8040f4408b17e6c4c21be79b37a55e61160eebc55e20d3"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Acts.21.19 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_ACT_021_019~c743694f496f84e94ef22a060cecbb8114f62a3221f1dde8affd38771b44b2f6"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Acts.21.19 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_ACT_021_019~f32a6fbf0a852d4cf2c9e6fdfde174988b160a792ff08ac4dcff7e73e3677975"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_018c8c1025b7acab0c9bb14a7363182c35027d7be40c824cfad3ab5f5c210058 (ACT\|GAL); exact_directed_pair:BLG_a8ebff727e4db4a5b9f9f5059a71d53dc24b27472088b262bd1336286ccacf3e (BDP_5e5c6dac203b31322f2362d1e2e0184ab8469124f9c1bd78da3a8e70cf8ea954); exact_unordered_pair:BLG_41a224b823cbf1f23b7f749882316a5130065c379140a5f40c8bbc319f4dc89d (BUP_ad2ddc4b905b0acd5a7aa4ba056428864814fdd1a7516aaeeda58988ce541d17); overlapping_endpoint_range:BLG_abec124f1c45b6b89351151abbfae2887921e811d63c1fea91cf16ebc6d10b44 (GAL\|2008); overlapping_endpoint_range:BLG_b5a28779cd38703ac7b7ac74fbf304b250df868880b8bb976acd738bdf860824 (ACT\|21019); overlapping_target_passage:BLG_4a7cc54407904734815da4d679658d652df40dad2349486318334acc36f72fa9 (GAL\|32); overlapping_target_passage:BLG_cd5f896357f7831186a5ab23e44033501c91cc1fc59806de7ae05652562dea23 (ACT\|757); shared_endpoint:BLG_30fc0266c6b909692656437a596e5565a9a446361dbb23877d6f50bcc8fa81f0 (Acts.21.19); shared_endpoint:BLG_b9c744a735a876282abb433e5f26891602d8f17b4a3ff0d9b96652685cda9baa (Gal.2.8); shared_target_passage:BLG_5e5215b943b2ba5bdb0e193df5016bde5a6f7d2cc0a84da33b872a56bd2ed7e3 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_GAL_002_008~a4eebf2c65fac36b8a8040f4408b17e6c4c21be79b37a55e61160eebc55e20d3); shared_target_passage:BLG_5ec75a8e0aded02f72602fd179ec1dbba5c79ff1315c22e9670681348fbf506c (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_ACT_021_019~f32a6fbf0a852d4cf2c9e6fdfde174988b160a792ff08ac4dcff7e73e3677975)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=train (eligibility=eligible, reason=None, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=excluded (eligibility=excluded, reason=endpoint_partition_conflict, seed=6103)`
- Manual criterion verdict: `PASS`

## Normal cross-testament link

- Status: `selected`
- Matching artifact count: `52424`
- Deterministically selected identity: `BR_000545447208b22ed6ba919550a125e5e51f08ec5a2b81ffd8319617b548231b`
- Relationship ID: `BR_000545447208b22ed6ba919550a125e5e51f08ec5a2b81ffd8319617b548231b`
- Original source references: `Ps.34.21` → `Luke.19.27`
- Direction: `a_to_b`
- Source weight sum / maximum: `3` / `3`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_e00cd1293395bbfdd3b0d502f46db10951172b6e44f6991be21c5c1a5071b6fb (cross_references.txt:115988, sha256=b931a6d63c6762719b6fa0e12ee51fe94c830cd4fa9c894bc5ac0f5327db66f5, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Ps.34.21 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_PSA_034_021~aa264377de4266e3836d129b5c43c8083378d1ae2e6bad1b33a91f65fb200295"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Ps.34.21 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_034_021~7bad50328c954cd3945e70128b1f071cd4678a590d2b665e1dac7dda647a9a99"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Luke.19.27 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_LUK_019_027~86e0a2386febe529032e982f858845165e37c9643c87fb6398321d2255f0fbb4"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Luke.19.27 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_LUK_019_027~57408614827b9b2c4ef616ef7bee5e28669a40336f70fcceefe266bd42222590"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_dca7cd79f30c40b70093a0bd6a248d762d9a87e9d7a3bffa488f645549b60b3d (LUK\|PSA); exact_directed_pair:BLG_cb26084932ec334b893d775fa28ce3bc4f1f8b2e80e6fca2c610b636fd6f8542 (BDP_4728b4e974f43016c1d4239cbd06c2215e32a5413803ebbf530ca1f75e053bff); exact_unordered_pair:BLG_0aede028aeec4f028f617dd4f03391e3b4f0abeca726712771d41941cc278a48 (BUP_73ad76ce4be66e3d2bf6930b847488b5590b4d10e0ac8bea02abd10de2dd6ed6); overlapping_endpoint_range:BLG_40b7e8aa447c344a00310f9e9310083d29a288d600842c8ec6c89519203a9f5e (PSA\|34021); overlapping_endpoint_range:BLG_e650056288dda6297681311537d9fb482af25d62c9431c6a50a0be0d0536bab3 (LUK\|19027); overlapping_target_passage:BLG_0c9607b3df52dc3a41d0ffc2a885bd61ad97980441a5ccfa25e1c387db177fff (LUK\|864); overlapping_target_passage:BLG_15e6c2d343e413c45bc74827c4bd5faac231870e5aa9ebb2b73ec0d7b9445894 (PSA\|485); shared_endpoint:BLG_07fa5657b756a1f1271766fb8f7de8da694f3b39ab5f60c187065247158cb130 (Ps.34.21); shared_endpoint:BLG_ef767f178e0f58933b70692da69f815e68e0debebb85ba92c67d424628745765 (Luke.19.27); shared_target_passage:BLG_4895651b1f9a639e7cc89147e7d50bf41ff3b51b15c447a5af44c93c33fafbf4 (P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_034_021~7bad50328c954cd3945e70128b1f071cd4678a590d2b665e1dac7dda647a9a99); shared_target_passage:BLG_fdf05e5c955586e868d534ac38e39eeea57f4e97eb4e2d0c2234455ae789bce2 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_LUK_019_027~57408614827b9b2c4ef616ef7bee5e28669a40336f70fcceefe266bd42222590)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=train (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Range endpoint

- Status: `selected`
- Matching artifact count: `88150`
- Deterministically selected identity: `BR_00020c4ac26ca39335fef72cb07b92fa33f65a62f7276e06a2d0c7cccc0f157a`
- Relationship ID: `BR_00020c4ac26ca39335fef72cb07b92fa33f65a62f7276e06a2d0c7cccc0f157a`
- Original source references: `John.10.26` → `John.12.37-John.12.40`
- Direction: `a_to_b`
- Source weight sum / maximum: `5` / `5`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_26d1165edba81a45d2794530794a53c9f13bb4af15c3a2b3e1ea2bf53baefb25 (cross_references.txt:268928, sha256=ca125b3e7ead13fb41d65ab269257926d15f66b66fda2bcc308b6243e5015e8f, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | John.10.26 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_JHN_010_026~15ac66a82392325c61337a9b64358d1fc1ba51de12d08f3c51a154b309a74a80"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | John.10.26 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_010_026~9ca5472ae2cad800aca42069b48f7238610ec0f6d79485b49c8b9048a4bfeb9f"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | John.12.37-John.12.40 | True | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_JHN_012_037~e6b9b7fb614e530f24b974a1f16e26658c62249ebdc0d2a80c0e5d6e6307b1fb","P_GNT_CRITICAL_CORE_SOURCE_VERSE_JHN_012_038~265e64fac7af9d9173cdbd524dc11e7f5ad055b72a35ed8143047e37f4d9790a","P_GNT_CRITICAL_CORE_SOURCE_VERSE_JHN_012_039~2f5b1495310fce22227a779949e5521062fcf987681bea2f449042df5fd9b47c","P_GNT_CRITICAL_CORE_SOURCE_VERSE_JHN_012_040~436ef94d827cd3e7b62b5d2438efba6c4c291ea3ab397bf2e5095431e8899b24"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | John.12.37-John.12.40 | True | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_037~5241ec59db05d8c8e4ac1a5835316c8f2f17789d956d2c6bb2d0f990236cb8d8","P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_038~5f24cfb003f9376a2050bc658c2716173327884e8d540f7ca9947a8dc6611bec","P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_039~ed71944479d44c0124eb34bdef1821f7f3c6d9dc2de6aa7e67626707c14afe34","P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_040~36af611326deb015592a8f67f66f158d51207af34c69c4512007624cb35451ca"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (20 membership(s); first 25): `canonical_book_pair:BLG_9f5ba36e10b87e6357042ca59fe6e59bba951ba1bcfdabd71cf97749266de7a1 (JHN\|JHN); exact_directed_pair:BLG_2533cf9733f75119c7f5bba193ecae066980526c24c135732eb59fb120670f6d (BDP_829ab285290d96e98f9452127f53f5acd5431ab1f3461762162262135eee1bad); exact_unordered_pair:BLG_3c5f9ada9cb395fbc35d65022037aca81d862e0af21987a2fb4189c6fd4e8f15 (BUP_fc645b91d90708ea9360b9c69e6431fbb987e85f8b3e56fbd1d363a983be4d46); overlapping_endpoint_range:BLG_155174f0d5fc12eed3b0989dd00a7b15047ac6ba7897427023e0b211d26e73ce (JHN\|12040); overlapping_endpoint_range:BLG_1af12bd899035deeacd14c97d8e38d5f8e2875db5b5428ae08b5a39390087477 (JHN\|12038); overlapping_endpoint_range:BLG_4b2c853b9f1ba587f07d54e6fb32906d85feb0744b211162c077f9f78ca7625b (JHN\|10026); overlapping_endpoint_range:BLG_4f57e2432e0e1d6e7653055c9103ba551bee7ec733fa98f85a77fd8eab20ea24 (JHN\|12039); overlapping_endpoint_range:BLG_951ad98a59294018b4999690345a23cb50e13988569e79c6625002e9d533e86b (JHN\|12037); overlapping_target_passage:BLG_2e6074ed69948442aae06f7612a1638eb7a43c0e0f6847781b8c7e1f5ecd8d49 (JHN\|575); overlapping_target_passage:BLG_5ddbc75ee2da6748a0a644a3bdecf07fbcda56d25371d8e8379cff1bea6e1c91 (JHN\|574); overlapping_target_passage:BLG_79c29470ddd923387652b0ed2183ac3fa53153afc635ba488e4f6ab78d54b298 (JHN\|573); overlapping_target_passage:BLG_c6aae92ec3b55f34455aaeec19c9ed659ba526f0213af08ccd52876912e8fc93 (JHN\|576); overlapping_target_passage:BLG_d62a32011303b9b35c67264936262807b4408c3c0fd1610afd90ccef7b21a674 (JHN\|463); shared_endpoint:BLG_6ae0599181ee6584c4e70dbfaada8d75baefcc0f5184ce8e8e3bdeefebc12468 (John.10.26); shared_endpoint:BLG_834eaa4cbd714472030c27942958d96597ee1a915505f48c415b1801e695c65f (John.12.37-John.12.40); shared_target_passage:BLG_04a42d3bf5fbeb9bda4b9367e4083abec3544e6e11892a9313a0dd406f4a775f (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_010_026~9ca5472ae2cad800aca42069b48f7238610ec0f6d79485b49c8b9048a4bfeb9f); shared_target_passage:BLG_4685074f62cb82a6f83424e7dbfd91254b6af8a8643ee4d9c3900e2d79b4c45e (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_038~5f24cfb003f9376a2050bc658c2716173327884e8d540f7ca9947a8dc6611bec); shared_target_passage:BLG_6e7b8981befaf2f82c17d5e767c839324390436e537371522f8d050271fc7001 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_039~ed71944479d44c0124eb34bdef1821f7f3c6d9dc2de6aa7e67626707c14afe34); shared_target_passage:BLG_ce96e4466bcae9bad6e37c682c77652dc68dd042204b9cb305290ece6eb0565b (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_040~36af611326deb015592a8f67f66f158d51207af34c69c4512007624cb35451ca); shared_target_passage:BLG_e1f33dad544e3c1b678ae6891b35335dc123f3ffc71e669fdc21af29f9ab8d82 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_JHN_012_037~5241ec59db05d8c8e4ac1a5835316c8f2f17789d956d2c6bb2d0f990236cb8d8)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=excluded (eligibility=excluded, reason=range_overlap_guard, seed=6103)`
- Manual criterion verdict: `PASS`

## Highest-weight relationship

- Status: `selected`
- Matching artifact count: `344799`
- Deterministically selected identity: `BR_dc26e9548deaab159925e883bf47d083220a62e54fb08cf65e50f751e40d45d5`
- Relationship ID: `BR_dc26e9548deaab159925e883bf47d083220a62e54fb08cf65e50f751e40d45d5`
- Original source references: `Jer.29.11` → `Isa.55.8-Isa.55.12`
- Direction: `a_to_b`
- Source weight sum / maximum: `1281` / `1281`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_8aff7a9162a016fa19c0d3a184b3f41a328b127baa77416c52a911f81e181ef7 (cross_references.txt:184187, sha256=f6b24d4e295df90955e58eb312edeca3399ae755497a40e6cf3e572baaf34117, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Jer.29.11 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_JER_029_011~26c51bff267d27421befe5aa6a7746df181293a724d4e94b303c0c2c14832bbe"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Jer.29.11 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_JER_029_011~c9db208082ca3bdfe788a1f4e1a5ccb18d0104f58273937b097c6f0216659ebc"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Isa.55.8-Isa.55.12 | True | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_ISA_055_008~f643b6bd78dbd557fe2317efc6369f921bd9bc8801db2c2e1841c5b85fabe7b9","P_HB_CRITICAL_CORE_QERE_VERSE_ISA_055_009~565afb9a6a1a1b4abc06a7755eff41a02a3970e201ca65d1177a7e8b0550f196","P_HB_CRITICAL_CORE_QERE_VERSE_ISA_055_010~3e42ad8d4346fbf6b005f9d49fdb4071e8aea5c0489fae343e65dafa3b5f160a","P_HB_CRITICAL_CORE_QERE_VERSE_ISA_055_011~99a199a66f2af33eb4f65aa476e14aa4d9fbd480492fd7fd1f19c680dac61d38","P_HB_CRITICAL_CORE_QERE_VERSE_ISA_055_012~a73183a2929d10f25fd265dc6ca63f52302c58da5d7a770a5191fcdcb522be04"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Isa.55.8-Isa.55.12 | True | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_008~e61510e69e5322b51774adc8443014898a213a233dd54d4cf363a09f77c655f8","P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_009~8391d239ee30844e552e31e7f40e433176a127e8181ef5e32985a67b03d36d69","P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_010~c43ea7da6b269094b3061c37858230614bd6830e568b36133c85ce8794c7c9cf","P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_011~3f2fbaaa0ba98a4cae8da07f744f63159ecf2f8a8e37bfaaf11f6535fd56660b","P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_012~769bf52d5b0a0671e07fbd6aec58164a256c11be489849a46571931503fc9924"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (22 membership(s); first 25): `canonical_book_pair:BLG_dc4d4598675a2801d04a2276e7d76a5bf813e790592b874f42e245bd641ab960 (ISA\|JER); exact_directed_pair:BLG_bfbe86ad727c4bc81a3dd3d01d46f1783e953c0e483b17191db5cc5cbc9ef34a (BDP_eea1e8847d8ad8b0340b8a057ce0cf70ca05bc39276b1afc1b79268902c5413f); exact_unordered_pair:BLG_a95e851aa506078cf4bc53b86ca8405962fd4da3522efa770bbdb8b234678d67 (BUP_8a28a57332c0b85f6092c07bee2fdf5a3236d1a0bd168dcf2c2b8deb16ea0556); overlapping_endpoint_range:BLG_349fc9a8e6e5c3c06f6247592b4813b035e4f0e6aebc021b2c00ba3cfd4c38b4 (ISA\|55009); overlapping_endpoint_range:BLG_6737352cb3f5abce0728846f7ebf7c818512af43e9b7315b26b24fde91d2db5a (ISA\|55008); overlapping_endpoint_range:BLG_6c6ea2ee8727b6e9d34fdc3f5cf0db66fea4bb16411cc26ec3e4f0ecf1c91bf5 (ISA\|55011); overlapping_endpoint_range:BLG_72ab1c4924121c6ef49082dc2b48ac1d36c1bc93700ae2e38d15093de2a6bd3f (ISA\|55012); overlapping_endpoint_range:BLG_90a2768df1faf855550de6f0a6f7b1a4689fed331efc8542ed944ef859e98108 (JER\|29011); overlapping_endpoint_range:BLG_ec8f698e9ef17127572e66fc3a22d082348cca0c4e2d174d8cc4c096778738cf (ISA\|55010); overlapping_target_passage:BLG_1a9301f2ea03623fd4fcb60cfc82ee406f5db89e0a8e1c6a7893ab68ed60711d (ISA\|1097); overlapping_target_passage:BLG_369659f6e80170ef9d2c6f5832e3b9860583892dda0defe7080ee67a40479e32 (ISA\|1094); overlapping_target_passage:BLG_69cd36ff59b907faec891fcfe9995c6a3623f7bdfea185730f8c84a15f7056a2 (ISA\|1095); overlapping_target_passage:BLG_c20400e53323209f6ff515db76f47d3b71428011b6c006cf022f9228ae606b89 (ISA\|1098); overlapping_target_passage:BLG_d5e9815b3960b91e5cf427b91659af029eb832be9e40a11b5e645702e763be55 (JER\|700); overlapping_target_passage:BLG_e96a46ca49eadc65b9d6fd3611ac5a5568690e8f8c4af356312c457b9be1db36 (ISA\|1096); shared_endpoint:BLG_95ceeedb43fa26fabf34f83b00ecf97b39b6c10b112b20febf746bc2b015605b (Jer.29.11); shared_target_passage:BLG_036cae240e7c144c8e6954aae357feec9364c2159d8958fd56ebe60efa54c357 (P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_010~c43ea7da6b269094b3061c37858230614bd6830e568b36133c85ce8794c7c9cf); shared_target_passage:BLG_30a4841496673bb1f3bfa1534442c833351696a3ce98749644e6685c9b128c4e (P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_011~3f2fbaaa0ba98a4cae8da07f744f63159ecf2f8a8e37bfaaf11f6535fd56660b); shared_target_passage:BLG_cb07dec22db4a3e8c12e37e2d6ba2bc622a4a6b86ae8e4f07840c01c6c2236bc (P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_008~e61510e69e5322b51774adc8443014898a213a233dd54d4cf363a09f77c655f8); shared_target_passage:BLG_d23c819d5c314ba45dc71bdb6f70c5ddb707c409bb504a1729fd0a1734787a34 (P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_012~769bf52d5b0a0671e07fbd6aec58164a256c11be489849a46571931503fc9924); shared_target_passage:BLG_e7e9945eded3e70035ecb36f74e40df9b13b61f44c40ae36ca09d04db43e29df (P_HB_EDITION_COMPLETE_QERE_VERSE_ISA_055_009~8391d239ee30844e552e31e7f40e433176a127e8181ef5e32985a67b03d36d69); shared_target_passage:BLG_f07a3a7ce919a4c012ca0e4fa09bc92cbece41f5f1c655e46bfc71cdc350e21f (P_HB_EDITION_COMPLETE_QERE_VERSE_JER_029_011~c9db208082ca3bdfe788a1f4e1a5ccb18d0104f58273937b097c6f0216659ebc)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=excluded (eligibility=excluded, reason=range_overlap_guard, seed=6103)`
- Manual criterion verdict: `PASS`

## Lowest-weight relationship

- Status: `selected`
- Matching artifact count: `344799`
- Deterministically selected identity: `BR_2a75a5f061e40dd84fc656e1496fd9f89f8b4d6fc51852fc29da8a1043c3fc51`
- Relationship ID: `BR_2a75a5f061e40dd84fc656e1496fd9f89f8b4d6fc51852fc29da8a1043c3fc51`
- Original source references: `Eph.6.17` → `1Sam.17.58`
- Direction: `a_to_b`
- Source weight sum / maximum: `-86` / `-86`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_0576e4f493028c1493aa751f2578b1fc226aeb113a562f245b20f538fab9f2f6 (cross_references.txt:311535, sha256=ef364ece5738765197dca4811a3948942ae0e2b3036b4b1328f574d28e7c9c4b, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Eph.6.17 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_EPH_006_017~c838e08d2d8b2faa119558c269659cb320ff291b8e605b0dd26a328d46f2dfb0"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Eph.6.17 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_EPH_006_017~274f7745956636e1dedfe9566ab9064ac497f39a1df3f07c2e444f1c918de570"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | 1Sam.17.58 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_1SA_017_058~a3fb6cdd7780689db095327d0580dd9b8372c61f96bd788611d7057f4c7bccd2"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | 1Sam.17.58 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_1SA_017_058~8380bd2ff1f66e65616c1d9f94a2443720aa568b4b08c8fae6e42198180eca00"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_c7caec696a6a715f477e499f7207da76930e04b8267a04099658d3f28527c17b (1SA\|EPH); exact_directed_pair:BLG_76ef728bb8550dd26efeb488931b951441b1ddcd11a085e7c529e2f91e2afc70 (BDP_8dfe01705dd79809991b54b266f89a9fd75dc7fbeab37ebd2492ffd04c16e900); exact_unordered_pair:BLG_951ad75163a5d7357e489bde07d64b2b35bae74d01100717fd23f6f78fc3e32e (BUP_936041b47416590411846fb20f49ea5e66c40eeb732f4f92faf15a9d10a4fca7); overlapping_endpoint_range:BLG_0f6a1cdc8ce2c189e1516a66f0dfb78b8a10dd6d85f93a1bbec0004cc549aa4b (1SA\|17058); overlapping_endpoint_range:BLG_528b5cea204987a6282a420d641dc7fe04194072f2cbc717d1523bae3a5de503 (EPH\|6017); overlapping_target_passage:BLG_55a81231dcfda81345d9d15221980ea674a7f75176a026ec9e0d2d91bdd09e93 (EPH\|148); overlapping_target_passage:BLG_6ef69c3433aca8cec02b5e9762491a9beacc1342432be99e9e5ecf3e99faf8de (1SA\|464); shared_endpoint:BLG_451d779a4a47a1a5d33eaa3a9069e3e212158ad29c86f5aa3bb1ab0cf68def4d (1Sam.17.58); shared_endpoint:BLG_6b7f65c529a871fd1821922dd617c87697e33f0f59092af8b2eadb4b7a9b9d31 (Eph.6.17); shared_target_passage:BLG_6e8b0f21661a979bd851c54612d1fe4ff872d02fa09abd37ee9f7938cc73c01e (P_HB_EDITION_COMPLETE_QERE_VERSE_1SA_017_058~8380bd2ff1f66e65616c1d9f94a2443720aa568b4b08c8fae6e42198180eca00); shared_target_passage:BLG_989a10de79a0373ad3e04d6da0563d9746da9568bdecd4fa49c46898c2d6e6eb (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_EPH_006_017~274f7745956636e1dedfe9566ab9064ac497f39a1df3f07c2e444f1c918de570)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=excluded (eligibility=excluded, reason=endpoint_partition_conflict, seed=6103)`
- Manual criterion verdict: `PASS`

## Duplicate source record

- Status: `audited_absence`
- Matching artifact count: `0`
- Absence policy: The audited snapshot may contain zero duplicates; report that fact.
- No example was fabricated.
- Manual criterion verdict: `PASS`

## Reverse pair

- Status: `selected`
- Matching artifact count: `59756`
- Deterministically selected identity: `BR_00046417ec2b8ef6c64d005478d07bf4d5d53dff46605d70d9d3bbff8ff00267`
- Relationship ID: `BR_00046417ec2b8ef6c64d005478d07bf4d5d53dff46605d70d9d3bbff8ff00267`
- Original source references: `Job.29.3` → `Prov.13.9`
- Direction: `a_to_b`
- Source weight sum / maximum: `5` / `5`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_5d8e10dac2d6c66f1fed1a683029b5db2e5fbf03b2f3b968a4a885217f7baf6e (cross_references.txt:105533, sha256=2f8a21c26e46fe93fd7ae6e80cee9f95a725d58ecf84b2e6e3c974c648d9a3c0, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Job.29.3 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_JOB_029_003~43e7ddacdcad58d74fbebd832ba3c1225b216ffbb3ee0848f8d49de2d282e87e"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Job.29.3 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_JOB_029_003~8c22b92c45888ef7a29c6f67c45708ef671a8cd9288e7df3bf106684f3b04a5f"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Prov.13.9 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_PRO_013_009~86c902afbd616abc21f226f55b2c35d03019debe8623248d98c34e5de66cbdf1"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Prov.13.9 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_PRO_013_009~592abb3213eb0238d6d8c42aff0e4b9e51c5513422fe8d2598b81adf43eb862f"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_9e3951abd1c3daeca39dd8a4ce1ddff25321b19dd50b01bcc0dee328c479c95d (JOB\|PRO); exact_directed_pair:BLG_1514a408f1837e0e6bbf8452f8c180c08f56bfe939e2e711d5fefa64d74303b6 (BDP_fb605735382c2bf099fe84d0dddf95a3b9583733f8e6c914fff1eadbaace9ef7); exact_unordered_pair:BLG_5e7d2843b1d86c94fc4be8de97e9fcb9bd57b78bdf4f44e62ecea4713b72416c (BUP_632e954a0181f2371d850429763c036f631a604f2040ea3705fc487ccb7fea01); overlapping_endpoint_range:BLG_28dd201a5c331341bcd6ec1daf3ef2ffe9af070c53ea1d95788904e6f1d8b62c (PRO\|13009); overlapping_endpoint_range:BLG_7cfc14b15cb124bc5633e152c14592d0bd006974ed652086900f250b0cbe1ff5 (JOB\|29003); overlapping_target_passage:BLG_64717bbc66dfaf9a90e88802ae3f1101bb7e0cd68a6d51fb9f4181a48c8dcd99 (PRO\|356); overlapping_target_passage:BLG_94ad39469741631b0c7527b497a02e623ffee4598cbfa24c545d75a54156c831 (JOB\|666); shared_endpoint:BLG_0a66410e1a8b03b115dc04f9ee728aa9e8c696e8baa95ae687c837dfb228d055 (Job.29.3); shared_endpoint:BLG_777ffa41dcf1266353341c5b773798c98c09c920b80450125e21798cf10d9520 (Prov.13.9); shared_target_passage:BLG_0d2fa5218f14008c5c623051bc0124fe51310bcd69a2a8bd3dbbbbcd162767bc (P_HB_EDITION_COMPLETE_QERE_VERSE_JOB_029_003~8c22b92c45888ef7a29c6f67c45708ef671a8cd9288e7df3bf106684f3b04a5f); shared_target_passage:BLG_403a731bc60b352cbb2d3f9a41f997de37f446b2899bd423519b0a6660182d8c (P_HB_EDITION_COMPLETE_QERE_VERSE_PRO_013_009~592abb3213eb0238d6d8c42aff0e4b9e51c5513422fe8d2598b81adf43eb862f)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=test (eligibility=eligible, reason=None, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=train (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Self-link source record

- Status: `audited_absence`
- Matching artifact count: `0`
- Absence policy: The audited snapshot may contain zero self-links; report that fact.
- No example was fabricated.
- Manual criterion verdict: `PASS`

## Disputed-passage link

- Status: `selected`
- Matching artifact count: `638`
- Deterministically selected identity: `BR_00c30a5a867c897362381bfe8afaf58e2d72911c4955ee669bc968a8b5db7b67`
- Relationship ID: `BR_00c30a5a867c897362381bfe8afaf58e2d72911c4955ee669bc968a8b5db7b67`
- Original source references: `Mark.16.11` → `Job.9.16`
- Direction: `a_to_b`
- Source weight sum / maximum: `3` / `3`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_200a9b4381a20b77804ffba5e1c1875735613b7fe953ae76abc67de9c9c25920 (cross_references.txt:250336, sha256=4132e5bfe7c4a0090fc504cca0f020ff483f0c1b984b1d76d706214c5c87353d, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Mark.16.11 | False | critical_core | critical_core_profile_compatibility | excluded_by_profile | profile_excluded | [] | True ["mark_longer_ending"] | False | target exists in edition_complete but is excluded by critical_core |
  | a | Mark.16.11 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_011~87e3a464629d74bc3d5bb8cd513fcf197ea9de6b2e7041c53ca0896e45c95b67"] | True ["mark_longer_ending"] | False | same-label mapping has no approved external versification crosswalk |
  | b | Job.9.16 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_JOB_009_016~35a1eb9245d75c02a7a48d6963b7c01319248d8c3f45b8fec32833276528327a"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Job.9.16 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_JOB_009_016~f4ccc8d8aa984675d0f0378789e84481f82ba1f93ab745ab2b791d34e3b905b3"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_d93ee01399e898c45863dfe37f265fbced8f1557e8eb490c1cce947ef434868e (JOB\|MRK); exact_directed_pair:BLG_d8929a061959a0ab732c2bdd244e2762830c832a50db7dedbc3403a90bb29809 (BDP_cf4134d623f4f63b89507761359fa08c7a0b83fa12bcbdd23b08cd8c3dee4161); exact_unordered_pair:BLG_d884528e0f5eb570b2f2b6528d401288bb34aa8f9fc9d903f523ec17a6099a1c (BUP_0ebbdedabc6a8b0e3b980720051568b4eba30fd87b57e846e5a2250a6d8107e8); overlapping_endpoint_range:BLG_0e45c3b2d895a0fe2c030848764589df75e18ab8ed578cc09576995bacbb4cd5 (JOB\|9016); overlapping_endpoint_range:BLG_4454482b599529dffbe439db4373a02019629fd0eb06af9ae6718ba229311bfa (MRK\|16011); overlapping_target_passage:BLG_78c19c3cecacf98fe5e4d519f2111345789d3bd3810c286d716d9b607b7a5766 (MRK\|664); overlapping_target_passage:BLG_dbf7bbfd4864ca7499879b1f301d6941c2071f3cb05caaf5d96f22a1fe4ffd0d (JOB\|198); shared_endpoint:BLG_7d1097099f33ee96d09b15906b31e305e920c9361aff89ad32f30d6e38e145ae (Job.9.16); shared_endpoint:BLG_9f70b68192ab570ed8a42d22556563e0e9c08238e28b0800ec8ab0b4d7c4fac7 (Mark.16.11); shared_target_passage:BLG_23f515f39eb9939847f91e826245ffb167a1763262d79200f2abace59595edf2 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_016_011~87e3a464629d74bc3d5bb8cd513fcf197ea9de6b2e7041c53ca0896e45c95b67); shared_target_passage:BLG_60f2ded34f181d7b338838de40620bcdeb521bda805bbc0c29f2ed2c06cb55e6 (P_HB_EDITION_COMPLETE_QERE_VERSE_JOB_009_016~f4ccc8d8aa984675d0f0378789e84481f82ba1f93ab745ab2b791d34e3b905b3)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=train (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Edition-omitted New Testament reference

- Status: `selected`
- Matching artifact count: `69`
- Deterministically selected identity: `BR_01ff731621f5cc5c1022811d1878d1dab7a1fff9b34c520547228adf17d6a901`
- Relationship ID: `BR_01ff731621f5cc5c1022811d1878d1dab7a1fff9b34c520547228adf17d6a901`
- Original source references: `2Cor.13.14` → `1Cor.12.13`
- Direction: `a_to_b`
- Source weight sum / maximum: `2` / `2`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_4a9064bbd0c39b3a8c87ea47e17eb6d28ae6e845b1c2849d0af311e4d2cf5b7d (cross_references.txt:305686, sha256=179522fc440432801f6eb245a15d216093ca436c557bf3d6eca50cc206ce308e, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | 2Cor.13.14 | False | critical_core | same_label_extant_reference | unresolved_missing_target | unresolved | [] | False [] | False | exact target reference is absent from the pinned source edition |
  | a | 2Cor.13.14 | False | edition_complete | same_label_extant_reference | unresolved_missing_target | unresolved | [] | False [] | False | exact target reference is absent from the pinned source edition |
  | b | 1Cor.12.13 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_1CO_012_013~73a7774fe3f8b7cdf4d7608caec27edec1a20ae7b30a8e1dc7901d83988de80a"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | 1Cor.12.13 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_1CO_012_013~1b9883753b90f7004ecefb9f651ea34ac0a207ef1b4325e776e6fdc5063ddbf6"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (9 membership(s); first 25): `canonical_book_pair:BLG_6f994ec1966efc638bbc2fc2b812708f1aa06f17b4d152f594fd3855195b86ee (1CO\|2CO); exact_directed_pair:BLG_f806cfb9bf52de8b71a8a2bc93eabfaf4136660f020ee842941b8f6384ba0c2c (BDP_abf1134cf6c012cd2509f685e8970282986b5cfc5753aef29a5c8494d400e027); exact_unordered_pair:BLG_5a646d629e25d400e82b6ec4d5a19f636393ae44709a0399ec8088f6bed2d590 (BUP_88eb7907644cdaaf8c263a7a439ab6826f9ac5cdb5a2bb2c440363aa0e77534b); overlapping_endpoint_range:BLG_34e602345b08133b4b8e09512165bdbccbc83cb5781de1fb3738a89900cfdb2e (1CO\|12013); overlapping_endpoint_range:BLG_b64a137e61dca3d757c3374a8e688cd495adc55b3dae0254cc00dc8e06ab657a (2CO\|13014); overlapping_target_passage:BLG_c05df7e8632747c5653cc5223181f40f2c4733dd6ef2d7cdf2cb868662c86be6 (1CO\|284); shared_endpoint:BLG_62c4564417eb393ef32593745bdac84cece4f04d3bed2cd1bf718abd11ab375c (1Cor.12.13); shared_endpoint:BLG_d2832de54ad4af45f43c9c3cc70ba027aafb07b346cc33ba9a9ade9c5adb8bcd (2Cor.13.14); shared_target_passage:BLG_8a1048db49ed36e73fd1c98c017459c4eb79dd70af4ddf92134e2f1d8ad69098 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_1CO_012_013~1b9883753b90f7004ecefb9f651ea34ac0a207ef1b4325e776e6fdc5063ddbf6)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=mapping_ineligible, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=mapping_ineligible, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=mapping_ineligible, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=excluded (eligibility=excluded, reason=mapping_ineligible, seed=6103)`
- Manual criterion verdict: `PASS`

## Partially mapped range

- Status: `selected`
- Matching artifact count: `393`
- Deterministically selected identity: `BR_00166d7cd0e35c5dd2d73f27501cc5ad2709808387e2f575f6b944dcf143733a`
- Relationship ID: `BR_00166d7cd0e35c5dd2d73f27501cc5ad2709808387e2f575f6b944dcf143733a`
- Original source references: `Luke.22.63` → `Mark.15.27-Mark.15.32`
- Direction: `a_to_b`
- Source weight sum / maximum: `2` / `2`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_3fb67a16916d03c23d5f4b683900871520235f92c1fb367d4329a62f1bab1947 (cross_references.txt:261864, sha256=177100a20fcd492988306b585bde80f52ad14c5beb4ceeaf8ccdd1437b6c2f5b, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Luke.22.63 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_LUK_022_063~d4da8d470262e4584f1e80eac88272c3e9671fc4d672de8f01121aeebf8fe238"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Luke.22.63 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_LUK_022_063~ca7d9e2441024ffae975263f736b851104bf2ef2529935ebc821a2f3d87f01c6"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Mark.15.27-Mark.15.32 | True | critical_core | same_label_extant_reference | mapped_partial | partial_provisional | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_MRK_015_027~29dff91cf3b3a0f09dbf4538a4231c1f08ec6ee4d5ced7a318c82fc295be089b","P_GNT_CRITICAL_CORE_SOURCE_VERSE_MRK_015_029~ab18056d2452ef8f6535bceef7e53d8fb9a897c6f6a4f4ac968b6ab87d37ef62","P_GNT_CRITICAL_CORE_SOURCE_VERSE_MRK_015_030~624d1c2d6ef72f167f6c7afd5c09cf7422311ec6d21a3b7a79c2d914310025e1","P_GNT_CRITICAL_CORE_SOURCE_VERSE_MRK_015_031~f2665e56f77d37389024988c129af8b819a68257d970017ff41ceab2474af729","P_GNT_CRITICAL_CORE_SOURCE_VERSE_MRK_015_032~d2d8c95f51a985d3af2b223af19f0c687ac41b39ec8a51fca575d951d2ba2507"] | False [] | True | range maps only to ordered extant verses or contains a reference gap |
  | b | Mark.15.27-Mark.15.32 | True | edition_complete | same_label_extant_reference | mapped_partial | partial_provisional | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_027~c7d1a93faa1752290e47fee1c7fd33343912fdd9519396e94ed7b07e31a423b0","P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_029~c3f2bd3f75c8d9ba63c67cf545800d85e8400d611f748845e058a4a1d04d45e8","P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_030~71c434c0028ed0284363cd5ad5ae79d1ab31bbdd02d9900843affc5466c68629","P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_031~2290f693b068cfa31e638a3ab2e97981671fdfef0914d787a3672a32b51726ee","P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_032~ec1c9af1ba0df1014d72bc6c9d757c2288a86923e3f6f626f76b8257efd4e7ec"] | False [] | True | range maps only to ordered extant verses or contains a reference gap |
- Leakage groups (23 membership(s); first 25): `canonical_book_pair:BLG_20d86ca84d1da117c8406dd1f7ba5fe0b176d3566882767bf286f92e19053b8f (LUK\|MRK); exact_directed_pair:BLG_1bfe1629dcbc1dec76af7b832bb9128d4d48c66b38f6ad0d2ee01395e5c89044 (BDP_7daac373c5cd68587f6e037e5948fc05d38978019ce30e8873c01d10b598693e); exact_unordered_pair:BLG_420f345f24a8a4f0be1a0b216dcc758bf0b7a21a1a42a6f66f236a5d90d1deb9 (BUP_55ae9021052f64a461a67868140caa13d8a0dca0b525a32cc5603863bbe87806); overlapping_endpoint_range:BLG_04d2722ae56c1a4cd80a33b667fef577e5067e9637563bce764df37cee1c60a8 (MRK\|15027); overlapping_endpoint_range:BLG_2a503c14639df7c21d031bf2457e69bdb307fead2002c26245bf8344d35a2770 (MRK\|15029); overlapping_endpoint_range:BLG_308699e10ad082d1c966d28c6c7f39cb1a7b9b82a398893eb9fad7b615eef3fb (MRK\|15032); overlapping_endpoint_range:BLG_46bf64df980b32c16521f4a18a3542dfc2669bf91f3835b1d67bb86e3807f7df (MRK\|15031); overlapping_endpoint_range:BLG_87a8941bb23e68d7fd7a54540473803731c7213129f1828da0a44c6c6b407871 (MRK\|15030); overlapping_endpoint_range:BLG_bee26c8b576a9c95304955656d5e31396d5f61dabb0ae34d0812a8ba5fec2c7f (LUK\|22063); overlapping_target_passage:BLG_1ae81b1bfb8342efe680324d078f03f4463abede68da6ed55670e05b70138e92 (MRK\|635); overlapping_target_passage:BLG_2569879c8c7d5174a73cb0ce557b159ad012dea38db3ca7a10362a46c21c2a8b (MRK\|638); overlapping_target_passage:BLG_275576ece5cfbb88d26e0fc707aa7634cb0a668cbdc7b6eb33842a49b036727a (MRK\|636); overlapping_target_passage:BLG_56d3dd4acfb8cba742d357efbd9c7bc474a80f6d93445371693d3b6ff517249a (MRK\|637); overlapping_target_passage:BLG_f044c75d7f4bda894957a172a353b516ea7c931552590ec2eb4b8ba6a36f8f48 (MRK\|634); overlapping_target_passage:BLG_f4a41e076820e14391b760129c3f5455eb349bb09d1541023c1f6cc9553f6363 (LUK\|1033); shared_endpoint:BLG_8db5a6c3d98f093ecf4f8035d5f44d6b2c782d4f852b5a2c7be5e4128974f8f9 (Luke.22.63); shared_endpoint:BLG_f9a25b4a51586ed6cfa6bd3b8267d3dea9033664b2dd22c89a29cf9fa00515e8 (Mark.15.27-Mark.15.32); shared_target_passage:BLG_2d25e9018997e815c44e3af0efccabd4a20c6a9806723835a14702e101d561f9 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_032~ec1c9af1ba0df1014d72bc6c9d757c2288a86923e3f6f626f76b8257efd4e7ec); shared_target_passage:BLG_32a571658cd0fe16e911b99f0ec691c5b5345c1fb1d67729bafcd7a79327d12c (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_031~2290f693b068cfa31e638a3ab2e97981671fdfef0914d787a3672a32b51726ee); shared_target_passage:BLG_623d4764b21b541aa55e850be083903c7ea4fc2bc5cf60268e2dcc80023e2d3f (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_LUK_022_063~ca7d9e2441024ffae975263f736b851104bf2ef2529935ebc821a2f3d87f01c6); shared_target_passage:BLG_8c005af3ab17688d9a79a3f82bdcaae18dfc863756a970523f2ae6b5dcd22c63 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_030~71c434c0028ed0284363cd5ad5ae79d1ab31bbdd02d9900843affc5466c68629); shared_target_passage:BLG_be2b968d81ddc21b27498a37cc7f8cc5502f05bb7c20d0b035b93bb7e42e487b (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_029~c3f2bd3f75c8d9ba63c67cf545800d85e8400d611f748845e058a4a1d04d45e8); shared_target_passage:BLG_db899ce2cb726842fe87f5d64119fc771f010c15077620edb7a9cf17facc2120 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MRK_015_027~c7d1a93faa1752290e47fee1c7fd33343912fdd9519396e94ed7b07e31a423b0)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=excluded (eligibility=excluded, reason=range_overlap_guard, seed=6103)`
- Manual criterion verdict: `PASS`

## Old Testament versification/crosswalk risk

- Status: `selected`
- Matching artifact count: `259795`
- Deterministically selected identity: `BR_0000ddc29a26373a300e5a031b3aa6371a3226bee001b673a2179a320ae376f2`
- Relationship ID: `BR_0000ddc29a26373a300e5a031b3aa6371a3226bee001b673a2179a320ae376f2`
- Original source references: `1Chr.9.3` → `2Chr.11.16`
- Direction: `a_to_b`
- Source weight sum / maximum: `2` / `2`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_3c17b125d06135585731569aa0e72ba1a9e423d8ef22f8af4f94bcf08ff0b5e9 (cross_references.txt:82107, sha256=6b72337d389a5a70eb609b7c9bc3da09d6bd9a194efec41456eff15d51947215, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | 1Chr.9.3 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_1CH_009_003~4d500be04e0517db8b6352ede7c4ac0c8ae8c3170add5b1ca585b96ddd62280f"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | 1Chr.9.3 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_1CH_009_003~7043ab93f34f1793ffe5551f930fff40d54f890b5b6d89271ceb16fe42161aad"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | 2Chr.11.16 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_2CH_011_016~1dbff33aed53da26f37e7c5770351eb3310b7df20320a8c1ac47dc45c2b55cc7"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | 2Chr.11.16 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_2CH_011_016~c3891e4f780b9df77bbe1da0eda57ebc0482f4e7a568ed13c687966012920fe0"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_693998028093520e1f726f5c0dd510588206e6481fda74eaf0c2a4043ecc916d (1CH\|2CH); exact_directed_pair:BLG_3b93d52655aa2318565913d3aef97d8ab04c33f7a5a924ca3ce42c78122aab3d (BDP_50eb1152ffc2aff6b724fd2e27de6430e046a8f0bcb8256d6ecee3fe8928a876); exact_unordered_pair:BLG_dc1fd7e7254ca1149dacc95aec6aa45d64329453663be9699e88bfbfa72e9fc0 (BUP_6faed13315b8d685faa4bf8fcf385373e144cf811cd9956756fefadb21f6e144); overlapping_endpoint_range:BLG_3137804fc5572f1b7ce4764275196c3971d48f5853b49b8c124476e84a986a65 (2CH\|11016); overlapping_endpoint_range:BLG_e4665a5003a91338b8794d080126f0b0c2dc1425345e6f12414b268aa363c623 (1CH\|9003); overlapping_target_passage:BLG_07136dcfb6328f18b507719dbdb058786db4010b16a4c220a099c82e0240bfd4 (1CH\|366); overlapping_target_passage:BLG_5e5f767e0f83f6b8b1c24ee4a8fdf4b1c0007bf7478c41146dd754585c3c73e2 (2CH\|236); shared_endpoint:BLG_331e2158a39c14b9ff204f7f6116dbf84f1d8b4c1d51dcfe5842032687873b41 (1Chr.9.3); shared_endpoint:BLG_f4b4c358cbea770066d8a1124b5e62e39166b63183abd37dc747249b59b97ba1 (2Chr.11.16); shared_target_passage:BLG_7d278c79beab8e1cd458f2248ecc04ecc396c5a348a105aaf4324ca127b02ea9 (P_HB_EDITION_COMPLETE_QERE_VERSE_2CH_011_016~c3891e4f780b9df77bbe1da0eda57ebc0482f4e7a568ed13c687966012920fe0); shared_target_passage:BLG_8c0a781f6c0430e95f9547cf2cf98dc0dd31f32bdd244ec7d9396e5aaf3061dc (P_HB_EDITION_COMPLETE_QERE_VERSE_1CH_009_003~7043ab93f34f1793ffe5551f930fff40d54f890b5b6d89271ceb16fe42161aad)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=train (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Held-out-book split

- Status: `selected`
- Matching artifact count: `34996`
- Deterministically selected identity: `BR_0001bb2b09dbc687b26d4469686b8bf7b6a6e50b846702446eb92f7f728b045f`
- Relationship ID: `BR_0001bb2b09dbc687b26d4469686b8bf7b6a6e50b846702446eb92f7f728b045f`
- Original source references: `Ezek.21.6` → `Ezek.4.12`
- Direction: `a_to_b`
- Source weight sum / maximum: `2` / `2`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_09e698a377799d9bd289f4cab2c07f82a31ab4b565770b8e24641ed936c632ba (cross_references.txt:200762, sha256=6c101105d365545b6dde4bfc7a726ac9a8346a4e2c351fb22b58ff4368b7a7b1, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Ezek.21.6 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_EZK_021_006~3b11c952f9c930ff8bb7a7c269a937d5adb7ecfd2f894d980af493f666d1cf0a"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Ezek.21.6 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_EZK_021_006~f16f4e568b644baf490f6e5e4b1ea81fff817790e1889d179ca36c143e57af00"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Ezek.4.12 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_EZK_004_012~79cbaa8e3c11d1d9d5b7d239f26a97bc5bf0d360d27af65a3ce9aea94b598bba"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Ezek.4.12 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_EZK_004_012~b6143ae3b2c41cf92c3ccc7628dfc35d35894611c73d85d7509c6e764e0f3005"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_08492d8de697b06871d3955ca299baa855ec759d22c78e10d43e68f7f9d08385 (EZK\|EZK); exact_directed_pair:BLG_47e94b596c703b99a8c933a4a1a730cda37f41e10f926b9f379720ee75bff8fe (BDP_5f35703640a6a1e5e0de1398eeaa3dc798bdfcb39824afbdd5fbe6cc49a05411); exact_unordered_pair:BLG_015d9ef8b63be354940cbb9f6163ee9a44e6695158a156b7179ab827065fef57 (BUP_1f90e698b983af41a873aa6064b5a31064440056d17b9320749e109fe856bf5b); overlapping_endpoint_range:BLG_990cbdb6cf0e8308d310ced7c1ea679f0420a2f32769e2135169b6257ef09f3e (EZK\|21006); overlapping_endpoint_range:BLG_cd9b5745c9cc29683dc05d16bb8b1f04852fac818f7c7e392f2fbd727d3a5614 (EZK\|4012); overlapping_target_passage:BLG_1cf350b099bcd8b845a2a9afa2d88496dac0ffb01ef25913611d2f4a2ca92c64 (EZK\|481); overlapping_target_passage:BLG_374eb41299a56c2d72a9ffb56c12b86140ed6cf7084098d351e40c741be00a94 (EZK\|77); shared_endpoint:BLG_2c525947a3e92b40f1ccda7c4b6b0654f0da791a59ee5c5460240348c01445b4 (Ezek.4.12); shared_endpoint:BLG_a3f88ef281eeae505aee8969927ff9052b8f1b75d336b3176c0c1249dc2dd569 (Ezek.21.6); shared_target_passage:BLG_481e64839b02cccd7515253607151a361dde4c16ac16e60a5940b0bd5ecbd2ca (P_HB_EDITION_COMPLETE_QERE_VERSE_EZK_021_006~f16f4e568b644baf490f6e5e4b1ea81fff817790e1889d179ca36c143e57af00); shared_target_passage:BLG_bbe636353b16e46438bd27c6cceb82ae17beefc022060e5415325813149b3c85 (P_HB_EDITION_COMPLETE_QERE_VERSE_EZK_004_012~b6143ae3b2c41cf92c3ccc7628dfc35d35894611c73d85d7509c6e764e0f3005)`
- Split assignments: `held_out_book=test (eligibility=eligible, reason=None, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=train (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Held-out-book-pair split

- Status: `audited_absence`
- Matching artifact count: `0`
- Absence policy: Record audited absence if the split has no held-out relationship.
- No example was fabricated.
- Manual criterion verdict: `PASS`

## Held-out-source-passage split

- Status: `selected`
- Matching artifact count: `4982`
- Deterministically selected identity: `BR_0010bfde5c14b673f62bd21d9c2e894efd8cd7dde9baaeec2d642bd82b9610a2`
- Relationship ID: `BR_0010bfde5c14b673f62bd21d9c2e894efd8cd7dde9baaeec2d642bd82b9610a2`
- Original source references: `Matt.4.13` → `Matt.17.24`
- Direction: `a_to_b`
- Source weight sum / maximum: `2` / `2`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_1cba3e7527a87dcc46c32b1fe916e260bf41a0cafcb850233bedfcb27034a4ea (cross_references.txt:231387, sha256=c5bfbc2fe42739f4251ad1768dbc49b379a98a3a2f4152041177757884efca47, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Matt.4.13 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_MAT_004_013~edd9eed1ab7987e25ba6e3a4075cb3134a3d2f1a63194e5783778dac15aac696"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Matt.4.13 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MAT_004_013~caf63000f1636b3854affc186eb791f86d8a3daa4c006bb135787dd0fbf3bedc"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Matt.17.24 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_CRITICAL_CORE_SOURCE_VERSE_MAT_017_024~1fcfc44b15ed1524611c1860c5cae73a1902c343fbdecb1b98b9ed4f4f947b0c"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Matt.17.24 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MAT_017_024~86798f871aa68012f6460568275575c990f5763d17af01229ace85a72377c65a"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_625df9587585ed139f5c3e0af5ecea32fb9fcb3dca0e456101d817cd925f80ae (MAT\|MAT); exact_directed_pair:BLG_e28ab04a7476a9ee68b59e1a04a13cdf7d0685c7cad6df9688133a6ef4420f7c (BDP_90913d013126a3c3166e193fd8a659b9ff02f0fffe6045e9bebc9b6b82ffdf15); exact_unordered_pair:BLG_74609f342a4e6553375a95f87efd31540c542b539ac09d99b562b816aa7c295e (BUP_0e3e26b74c33f11c776ba49f062ee40ba9623d923ffa54f8657f35c61512fb56); overlapping_endpoint_range:BLG_59db2f5df9250bd654a7eff5414fac54abb8cc1ad335681a14332716dbd11ec5 (MAT\|4013); overlapping_endpoint_range:BLG_8d2c5868a5366e27e2d0ac022d70964bf0020b532f9436a82d95186df6707c32 (MAT\|17024); overlapping_target_passage:BLG_132a8172e7394fec8547021b8f0d1c83e201c75c6650fbc2d54dc55c05090b86 (MAT\|579); overlapping_target_passage:BLG_4cdf929fc873968901a187354747cf5302ce4a295ea69a756880a5746c0e76fc (MAT\|78); shared_endpoint:BLG_44c25a566a661ec8eb89f86a1276ef0aa81260a75c4ff37f932e62c671599721 (Matt.4.13); shared_endpoint:BLG_b0ac4036543bd509e44de25c25ff959ae24c15d83e7bc2353784283f1a82b29b (Matt.17.24); shared_target_passage:BLG_463dd1e10a723ad00b9c91a9c91ae93c2da394184fc377af9bf78d8333465376 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MAT_017_024~86798f871aa68012f6460568275575c990f5763d17af01229ace85a72377c65a); shared_target_passage:BLG_4b825d7a8eea7c492baa10b250575fc5554193467d7b136707b642251d805529 (P_GNT_EDITION_COMPLETE_SOURCE_VERSE_MAT_004_013~caf63000f1636b3854affc186eb791f86d8a3daa4c006bb135787dd0fbf3bedc)`
- Split assignments: `held_out_book=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_endpoint_range, seed=6101); held_out_book_pair=train (eligibility=eligible, reason=None, seed=6102); held_out_genre=train (eligibility=eligible, reason=None, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=test (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Held-out-genre split

- Status: `selected`
- Matching artifact count: `32297`
- Deterministically selected identity: `BR_00042ccb5b50534548deda80d0f3087ca30bfc9cee8baf04d09149b3656725c6`
- Relationship ID: `BR_00042ccb5b50534548deda80d0f3087ca30bfc9cee8baf04d09149b3656725c6`
- Original source references: `Ps.27.12` → `Ps.41.11`
- Direction: `a_to_b`
- Source weight sum / maximum: `7` / `7`
- Tier: `3`
- Eligibility flags: weak supervision=`True`, knownness=`True`, primary evaluation=`False`, Tier 1=`False`
- Data quality / license: `valid` / `cc_by_4_0_verified`
- Source-record provenance (1 record(s)): `BSR_8dc487475b2e3878cd7e8b66de40aa364bf17c2790d8eaea59b61205f0da933e (cross_references.txt:114366, sha256=52b1ab14f1b4abcc0e56ceccaa70c29c07cc70a6839757ead6bda7c9d26c0621, role=supporting_source_record)`
- Endpoint mappings:

  | Side | Source reference | Range | Profile | Method | Status | Confidence | Target passage IDs | Disputed | Reference gap | Ambiguity |
  |---|---|---:|---|---|---|---|---|---:|---:|---|
  | a | Ps.27.12 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_PSA_027_012~05d87e249e02be42890615627a26356f0ac341776f2448792fe320f1513f61a4"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | a | Ps.27.12 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_027_012~fdd53f02c28bb9a0cb3e94c19e19ef2b9c13d1d525b297bd4044adfe6b9f8561"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Ps.41.11 | False | critical_core | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_CRITICAL_CORE_QERE_VERSE_PSA_041_011~05ac094685314654b25679d51b82e6d5480de75220f6edb9201d6bbfb49439fe"] | False [] | False | same-label mapping has no approved external versification crosswalk |
  | b | Ps.41.11 | False | edition_complete | same_label_extant_reference | mapped_provisional | provisional_mechanical | ["P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_041_011~e8b1594d187e12c5e7d075769868281b50c83981a8971d23d8a8b164e976ae3f"] | False [] | False | same-label mapping has no approved external versification crosswalk |
- Leakage groups (11 membership(s); first 25): `canonical_book_pair:BLG_251d0c1d1fa94505ecadddeff6f77489e7581fb4d7f546e114d7d4a7effcee6a (PSA\|PSA); exact_directed_pair:BLG_b620ac239afff8d7abb144e364f95371ae3e22edb9098f5518390992732cf296 (BDP_6486b71ad7a0df0eeba2abef6b1a4e4482f1534828781200a84532bb6e806ec4); exact_unordered_pair:BLG_77b68f7dd72f40af96ca46051d513d48fe1e98780ca2780cc1f016fa962f9875 (BUP_91809b9c6ee71f0531986bcf7d8558ecdb50a541a3788d99f78bb8ea611bad98); overlapping_endpoint_range:BLG_1216536faa28356e3aac275c90ef1b804a0472355fc61b1fc16316ae41422bc8 (PSA\|41011); overlapping_endpoint_range:BLG_e48e4e4b0629297dc812dc3ee63a03e12c5bf515b7cae20e56a5095e67a98a94 (PSA\|27012); overlapping_target_passage:BLG_a77243c9560452d03960ea102097f55fe43fdc02dc571e98da4065ae96c3af80 (PSA\|371); overlapping_target_passage:BLG_bbd569ed8390583255c7c14b601c5f2f59ff132f85e8d97b8f1764b8d49f23a1 (PSA\|634); shared_endpoint:BLG_b713939a810d4fb0b9f96407e136619d1944cf4cfd0a3885bd5a3607a42ab342 (Ps.27.12); shared_endpoint:BLG_baa1e867c7f04aa32c33be63262f756c1fca1e1d66cbfb6d5b599c6f708d342e (Ps.41.11); shared_target_passage:BLG_1c830c313e1186e77a027b2a2047c285831bc5d7e8ac3e0442f96fe3e770ef0d (P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_027_012~fdd53f02c28bb9a0cb3e94c19e19ef2b9c13d1d525b297bd4044adfe6b9f8561); shared_target_passage:BLG_329a9b30b57e19d82b153af4fa37b13b4d5bb7122411d7d3801d26b90c175bc8 (P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_041_011~e8b1594d187e12c5e7d075769868281b50c83981a8971d23d8a8b164e976ae3f)`
- Split assignments: `held_out_book=test (eligibility=eligible, reason=None, seed=6101); held_out_book_pair=excluded (eligibility=excluded, reason=leakage_group_partition_conflict:overlapping_target_passage, seed=6102); held_out_genre=test (eligibility=eligible, reason=None, seed=6105); held_out_relationship_family=excluded (eligibility=excluded, reason=relationship_family_unavailable, seed=6104); held_out_source_passage=train (eligibility=eligible, reason=None, seed=6103)`
- Manual criterion verdict: `PASS`

## Presumed length-matched negative

- Status: `selected`
- Matching artifact count: `5855`
- Deterministically selected identity: `BC_0005a567268d3fe5f640bb3da54babe163cc2c65865ac1c95693df21fb65a2bd`
- Contrastive ID: `BC_0005a567268d3fe5f640bb3da54babe163cc2c65865ac1c95693df21fb65a2bd`
- Passage IDs: `P_HB_EDITION_COMPLETE_QERE_VERSE_EZK_013_006~f45f6b12601e369a6a9230153708c6a860ecf8f13c2bd85f82d31ff29a12c58b` / `P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_022_030~125678ab85436c058fc01bc3c6a869a59114720c51fc368330898cfe4c540989`
- Corpus / book / genre pairs: `hebrew|hebrew` / `EZK|PSA` / `major_prophets|poetry_and_wisdom`
- Strategy: `length_matched_random_unlinked`; length difference: `1`
- Split: `held_out_book` / `test`; seed: `6201`
- Generation config SHA-256: `b58c7d96d2e8e9a2082e8e0c0aaa5ce3827a217cb4d9a8a7a61de994b71509fe`
- Collision controls: presumed=`True`, positive graph=`True`, reverse pair=`True`, overlap=`True`, leakage=`True`
- Interpretation: Presumed negative only: absence from configured known-link sources is not proof of nonrelationship.
- Manual criterion verdict: `PASS`

## Presumed same-genre negative

- Status: `selected`
- Matching artifact count: `5855`
- Deterministically selected identity: `BC_000409553a790de80a2353c8c3d9ee422b1901f82f9b1a4a7fdcc6639567c408`
- Contrastive ID: `BC_000409553a790de80a2353c8c3d9ee422b1901f82f9b1a4a7fdcc6639567c408`
- Passage IDs: `P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_092_011~a3b7160bce5caa2ca20be059921233403c3ef0651848b8dbf7b8f86c681f890d` / `P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_145_017~ca5bfefe202d1c322d11ded30bfecf5b857722eaf76a8a957507bf2e255aad8a`
- Corpus / book / genre pairs: `hebrew|hebrew` / `PSA|PSA` / `poetry_and_wisdom|poetry_and_wisdom`
- Strategy: `same_broad_genre_unlinked`; length difference: `2`
- Split: `held_out_book` / `test`; seed: `6204`
- Generation config SHA-256: `b58c7d96d2e8e9a2082e8e0c0aaa5ce3827a217cb4d9a8a7a61de994b71509fe`
- Collision controls: presumed=`True`, positive graph=`True`, reverse pair=`True`, overlap=`True`, leakage=`True`
- Interpretation: Presumed negative only: absence from configured known-link sources is not proof of nonrelationship.
- Manual criterion verdict: `PASS`

## Presumed nearby-context negative

- Status: `selected`
- Matching artifact count: `5855`
- Deterministically selected identity: `BC_0002f4bd6c256189b0923748d12f16a9f7c7740061751521ce2613f7da75251a`
- Contrastive ID: `BC_0002f4bd6c256189b0923748d12f16a9f7c7740061751521ce2613f7da75251a`
- Passage IDs: `P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_144_003~5e07135b8bd672110d197cbe0d7b63748998e39087de3407fec5caffbc71feff` / `P_HB_EDITION_COMPLETE_QERE_VERSE_PSA_144_008~3478005b641d0fd9e47ec736fb5c2961338bec267eb2d1da91492186e09751d1`
- Corpus / book / genre pairs: `hebrew|hebrew` / `PSA|PSA` / `poetry_and_wisdom|poetry_and_wisdom`
- Strategy: `nearby_context_unlinked`; length difference: `1`
- Split: `held_out_book` / `test`; seed: `6205`
- Generation config SHA-256: `b58c7d96d2e8e9a2082e8e0c0aaa5ce3827a217cb4d9a8a7a61de994b71509fe`
- Collision controls: presumed=`True`, positive graph=`True`, reverse pair=`True`, overlap=`True`, leakage=`True`
- Interpretation: Presumed negative only: absence from configured known-link sources is not proof of nonrelationship.
- Manual criterion verdict: `PASS`

## Empty Tier 1 quotation CSV

- Status: `validated_placeholder`
- Canonical path: `data/benchmarks/tier1_quotations.csv`
- Data-row count: `0`
- Header SHA-256: `7d687548139586fe97479429e121e89c2a3f4494806e7e0aaa7ee3e72ea5136b`
- Metadata hash agreement: `True`
- Governance: schema placeholder only; no generated or curated evidence rows.
- Manual criterion verdict: `PASS`
