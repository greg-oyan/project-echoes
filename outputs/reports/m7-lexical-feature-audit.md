# Milestone 7 lexical-feature and feasibility audit

This is a structural and quantitative audit. It contains no bulk source text and makes no interpretive claim.

## Coverage

| corpus | tokens | lemma | root | surface | normalized | English gloss | POS | morphology | entity | participant | punctuation | zero width |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hebrew | 475911 | 475911 | 0 | 475911 | 475911 | 459024 | 475911 | 475911 | 0 | 51759 | 0 | 6435 |
| greek | 137779 | 137779 | 0 | 137779 | 137779 | 137622 | 137779 | 137779 | 0 | 31046 | 0 | 0 |

Greek and Hebrew root coverage is zero in the governed full artifacts; root interfaces remain fixture-tested and no roots are fabricated.

## Distinct feature inventory

| corpus | lemmas | roots | normalized surfaces | POS | morphology |
| --- | --- | --- | --- | --- | --- |
| hebrew | 8412 | 0 | 88981 | 9 | 820 |
| greek | 5401 | 0 | 19446 | 11 | 1319 |

| corpus | distinct lemmas | hapax | frequency 2-3 | maximum frequency |
| --- | --- | --- | --- | --- |
| greek | 5401 | 1932 | 1300 | 19783 |
| hebrew | 8412 | 2631 | 1776 | 51004 |

### Primary-verse document-frequency distributions

| corpus | family | features | median DF | p95 DF | maximum DF | DF-ratio-threshold features |
| --- | --- | --- | --- | --- | --- | --- |
| hebrew | lemma | 8412 | 3 | 95 | 19875 | 35 |
| hebrew | root | 0 | 0 | 0 | 0 | 0 |
| hebrew | surface | 88980 | 1 | 9 | 13094 | 28 |
| hebrew | english_gloss | 11315 | 3 | 91 | 17869 | 51 |
| greek | lemma | 5401 | 2 | 56 | 6965 | 42 |
| greek | root | 0 | 0 | 0 | 0 | 0 |
| greek | surface | 19446 | 1 | 14 | 4978 | 43 |
| greek | english_gloss | 6277 | 2 | 62 | 6556 | 66 |

### Sanitized feature-frequency exemplars

The bounded tables below identify features by stable governed feature ID, not by redistributing source lexical strings. The IDs resolve against the local generated feature vocabulary. Counts come from the nonduplicated primary verse streams.

#### Most frequent lemmas, roots, and lemma n-grams

| corpus | family | feature ID | corpus frequency | document frequency |
| --- | --- | --- | --- | --- |
| hebrew | lemma | LF_992d928a7f757c33a90a41df6b1629d111021535f69c6b4cec26428b617de312 | 51004 | 19875 |
| hebrew | lemma | LF_87712125a0eba18b505b68cf3e26455be229124c69a98371da21fd7d6848d145 | 46940 | 17996 |
| hebrew | lemma | LF_68b3d704f5c4c66ecf12bb1bb2d113c99b31f507706b35529f4a7b5daf4186eb | 24011 | 11123 |
| hebrew | lemma | LF_dac7db9583ddc9e6a9b06d3b45d349d856846395ee594434898360868754e5e8 | 20446 | 11848 |
| hebrew | lemma | LF_aa8ab06a95f6acac3215ddb2a4b4c3665c4a3525537905efb7a1c4e6d06edfdb | 15765 | 10291 |
| hebrew | lemma | LF_6beca81fcc70e6ff83c4512f2dc7f1cefa6f9b60a4abf7b6d714f1eb07ad426b | 11870 | 7230 |
| hebrew | lemma | LF_d932fe8e841b91b8a0e3454be0c6ee8cf11ba7e6797599d6eb87ac45b70aa953 | 7728 | 5878 |
| hebrew | lemma | LF_a711628ff8c5accb09eaad7a574dd551ace5700c3f69b9be4e3ba3cb42e634f4 | 6521 | 5522 |
| hebrew | lemma | LF_6d4fd398a00b1b71dd5a650a3e146904d9a0d209937624767ee7ffcee3a594e1 | 5879 | 4581 |
| hebrew | lemma | LF_ffd409ae2d8b4c9971fa4a59139be6657072a98f756324ae2b9cde904608486e | 5515 | 4205 |
| hebrew | surface | LF_8875436f93b31801b2d6d80397287abb347af9f578e4ef3df1f9ad351bffa537 | 23484 | 13094 |
| hebrew | surface | LF_95a8f907976befe2be18b1c340c394f1240409941fa223c8124069815178af42 | 16091 | 8824 |
| hebrew | surface | LF_723f532007c41225f89db7746f2d9a83a43cc2aeb5976ba8c77d2e603214720e | 14735 | 8444 |
| hebrew | surface | LF_5c981a90724916bc62af04b5f10a1c3b29aea884510a0c88ee5c6f81360a8bc0 | 8217 | 5457 |
| hebrew | surface | LF_220795864a5a94ae8d258a021aaa8c7f18a898d213c22b2afc862c96c9b28af0 | 7964 | 5849 |
| hebrew | surface | LF_46f805f51ccc7b04569465fdd3aaaee2a9471b5c603466dcf383e34ba1a90870 | 7921 | 5964 |
| hebrew | surface | LF_c5081afd788c3fea2223fca0577e3f010c9f683246fd5662a01ac99af64fa5b7 | 6942 | 5068 |
| hebrew | surface | LF_c6ad6ec1aa112f4187cbff5ef0f47ea65983347d0c891c94a4c85cfc5f9370de | 6812 | 5157 |
| hebrew | surface | LF_e60962312a25daa2c647b597c4b0f363c520037ff76fb63ef919bb4c2a3412a4 | 6494 | 5389 |
| hebrew | surface | LF_b9a8e9b41c66a1422f5e4c3c009f729f067b133c61505b495efd3b746fff720a | 6289 | 4090 |
| hebrew | english_gloss | LF_beed6ded095496d3e9540df9075ac95d8aa2e2a2dbc59d08f04f562176896c16 | 39548 | 17869 |
| hebrew | english_gloss | LF_7ab7fece75c8bdfc6dfc49ff994fe6e892579857b74a5f6a1c715a5e133cab6f | 24467 | 11275 |
| hebrew | english_gloss | LF_c1f32fa779df2723a5b7329a34bfa2724d22ea12be105202917ff123f7173cc4 | 19026 | 11214 |
| hebrew | english_gloss | LF_bd6df7e6f1849d4e6d738894a9841ff54090c1d0a8d88cd550195ed54a30f324 | 8989 | 6900 |
| hebrew | english_gloss | LF_87d27091aa8b85d694bca3a5ca26e14aec9d98cf57384c5d07e5bff933d30459 | 7216 | 6062 |
| hebrew | english_gloss | LF_a909bcadaea22a2a97b8e4fb61ea8d2fd635b12e88a835efcd1a1c5c604a5d33 | 7110 | 5487 |
| hebrew | english_gloss | LF_192cccfe49340dab9e54cfa65aaee6e986d288841b8d00ceca0223388839c2c8 | 6268 | 4325 |
| hebrew | english_gloss | LF_3dd3505247ab39487b7d5f4e816d74679870f5a66dd41850f7af29e9c8faf62e | 6188 | 4071 |
| hebrew | english_gloss | LF_142978c1d4ea4c11025aa60e5b9e421b81a3ea18b0b0ccba20650cbd2dbb8e0b | 5970 | 3757 |
| hebrew | english_gloss | LF_2b05698fd754168673eb993a5bb23ddc0794504c4c7362127ca33b441525de8b | 5296 | 4075 |
| hebrew | lemma_2gram | LF_384d6261514a850a0d0dafca464685379bf772e774ce75843c090c2146bda095 | 9427 | 6786 |
| hebrew | lemma_2gram | LF_11ff7108ad08fdf9bc9bdd796a97d1ce8991b1af35224324bbde43c5390916ec | 4483 | 3699 |
| hebrew | lemma_2gram | LF_b37ae0299296ae987566d9101bff5c6709b4ceb3129e29a187536dce6ad826d3 | 3018 | 2690 |
| hebrew | lemma_2gram | LF_50a2b30a3f855e8fa4041e657b7d5e6d945f8c6fded66e9f51adb754b16deb4e | 2955 | 2560 |
| hebrew | lemma_2gram | LF_ac9e547527aa8375bacdffc08397715f4c921a0c5488419213aafce3c82ca0be | 2615 | 2330 |
| hebrew | lemma_2gram | LF_0c91dfb26332ee88d0336c4f3ff4f8be851946de240fd75d96dcd6723e6228b5 | 2380 | 1823 |
| hebrew | lemma_2gram | LF_8df7ca711a077274248ae7f5e83d3216972dfd4ad9896f4c4d6eebedefe1e861 | 2280 | 1440 |
| hebrew | lemma_2gram | LF_23d578122b028ec4499f4db30773e7aae96a284438a8ab74dd2a04c1c8e2bb2e | 2185 | 1888 |
| hebrew | lemma_2gram | LF_98c1133472fee24bad5172a6b566806309ec9318817f78a8f9a631bdd5a31d2d | 1763 | 1669 |
| hebrew | lemma_2gram | LF_ae4d2d2e929f22950d13cf01f78c8337c8bc942567f0e51b6178f1925a53dcd1 | 1634 | 1450 |
| hebrew | lemma_3gram | LF_6c2ebf661668c86f6bc87f236c36912550322cb3e360cf500c5ef7b16d0d6d4c | 648 | 585 |
| hebrew | lemma_3gram | LF_12925e22ddfc82c82617a3733083010d962a43cb53c92216fd86ce3c1415be13 | 545 | 431 |
| hebrew | lemma_3gram | LF_9df6811db423e6a4dc796731313561ffb55427747cd26b8aff168b852ef7bda6 | 545 | 386 |
| hebrew | lemma_3gram | LF_68224b4ca58e8724c7a6f19bbd59f381554507171517b3bfae68b05e88eaeaf2 | 533 | 518 |
| hebrew | lemma_3gram | LF_0852784b7cfbb1f14617cdfe10747446a6d29cbe879160d4579c686e8f3e7723 | 531 | 507 |
| hebrew | lemma_3gram | LF_fb3702136670d2f25a6cfd06a39d4212d7d625db3b6862e189f47975bbdeb12f | 487 | 475 |
| hebrew | lemma_3gram | LF_0019d44f52425dfc52171c6d06b939e62ed322a7839556c615b44fde65ec2c0a | 454 | 415 |
| hebrew | lemma_3gram | LF_20c04e756d0ac469aa32d6e4079255383ccfd4651877e98e2948468a9d343e3e | 435 | 412 |
| hebrew | lemma_3gram | LF_220851ba20a0a44ebc541424768a5f82177dd5d5711fd0fc0b3f723ed1f676c1 | 423 | 395 |
| hebrew | lemma_3gram | LF_fbde72772b6790f9abb99e31ebbf356fd5fda1b0cb0c34861beecc7392bf6ce7 | 419 | 393 |
| greek | lemma | LF_9c62b12d9352f8501dea189a32acf671c5763fe24659fead60720805c3399399 | 19783 | 6965 |
| greek | lemma | LF_3dd4166fc39b717ec3e5911478671038933510a4499e5e96c6b6820d958ebd46 | 8978 | 5126 |
| greek | lemma | LF_c38429e715122caca775025665ef000e42e1b5b90e44a4c7ec1ab8c8c797e2ce | 5561 | 3711 |
| greek | lemma | LF_7031322e2e69142fc342a07c4b50a2d3bc0f2dbbca952dd5b72dc7e91b5b45c9 | 2892 | 2027 |
| greek | lemma | LF_56a1f74972d4415da2436b9848db106f951e8731e4a0e2e662ab7b32bd297c17 | 2787 | 2476 |
| greek | lemma | LF_3dc8f82fe3a538cc1b9a60e03e5ab0ef53ce54116717f835dc99daac74984366 | 2743 | 2105 |
| greek | lemma | LF_6cb9c664af00abb5c0c64780927560531cb236b1e91f1f2ac9ad795a27f65203 | 2567 | 1827 |
| greek | lemma | LF_b510b4828bc4a7f4a84958f32931daf272349dde86c198b4f6585c8075d7b40c | 2457 | 2094 |
| greek | lemma | LF_3427a9dd67f407f8fd5baeec7164583321ba22fb69cb749c3820d08f08397c31 | 2255 | 1942 |
| greek | lemma | LF_56a00adf3f6a6508e2e739bc871c849c5b6b8346118e4eeb46162828dab9603b | 1766 | 1508 |
| greek | surface | LF_cc55dbf27778557fa4839f0f5148230c36afa30fff2c03ab45f249dd03f2759a | 8545 | 4978 |
| greek | surface | LF_dea88b1f63e14556cb4de08c10a7029a1e5989410c286f7dc857bd61ad74de56 | 2769 | 2179 |
| greek | surface | LF_5552c94248974e90aa9faf4c14eb177e76a7dc9e95ba64e59c8c41d0f5377786 | 2684 | 2062 |
| greek | surface | LF_5d2f9997760b413b67dc7484714f81020d9ea9cb851f3d06c90654d00e9c150b | 2620 | 2332 |
| greek | surface | LF_5d2df4fdbe5694e873c7cf11a9998d766c806ebe99373edd9cc5bc2ea2290da6 | 2497 | 1928 |
| greek | surface | LF_83da1d087977ab221fc7a4ce07c201fdf9c36569710624a63d9d4a15c4bca0bd | 1755 | 1501 |
| greek | surface | LF_238fb6cdeccb0b327007f6b37aab7fd680ad4a49af0d4f850ca0290df4a71c15 | 1658 | 1330 |
| greek | surface | LF_29cfbc906cd14ab73c7b833e59af60c9f7fd6b97af0557707c0257612054c779 | 1556 | 1308 |
| greek | surface | LF_4f578ed3632fc3b8e912b91dfbc0010b9e513139075478522f8d369e1f503d60 | 1518 | 1273 |
| greek | surface | LF_9a832ecd50fc0e441bd7e9dfa563f1c6aa7608c9b238bd6482837c8eadf21df3 | 1411 | 1191 |
| greek | english_gloss | LF_7ab7fece75c8bdfc6dfc49ff994fe6e892579857b74a5f6a1c715a5e133cab6f | 15618 | 6556 |
| greek | english_gloss | LF_2c6792805e355c21cd74043d89255a0b250f49f9e838b845d6c2c0f7e02ad022 | 8854 | 4915 |
| greek | english_gloss | LF_beed6ded095496d3e9540df9075ac95d8aa2e2a2dbc59d08f04f562176896c16 | 8599 | 4965 |
| greek | english_gloss | LF_c1f32fa779df2723a5b7329a34bfa2724d22ea12be105202917ff123f7173cc4 | 6712 | 4272 |
| greek | english_gloss | LF_3dd3505247ab39487b7d5f4e816d74679870f5a66dd41850f7af29e9c8faf62e | 4548 | 2606 |
| greek | english_gloss | LF_98fb953639a94406991441bc2cfaf011eb51944c39269329657eddd586923069 | 3283 | 2320 |
| greek | english_gloss | LF_bd6df7e6f1849d4e6d738894a9841ff54090c1d0a8d88cd550195ed54a30f324 | 3157 | 2397 |
| greek | english_gloss | LF_184554dd0fec91ee65a30e4e89af492515886ae047e5a070b6cba247b2dc37f5 | 2726 | 2151 |
| greek | english_gloss | LF_042d8f07cc8716674945c6c6a36355956412a8206c1f5c3cc296001c4dedf475 | 2660 | 2078 |
| greek | english_gloss | LF_2b05698fd754168673eb993a5bb23ddc0794504c4c7362127ca33b441525de8b | 2576 | 2083 |
| greek | lemma_2gram | LF_e4e0d984983696fcbd2c7ba7c8a16e3c565f6b24b1397b6108afe1a5f246ab4a | 1567 | 1249 |
| greek | lemma_2gram | LF_c43b9b73a56667674e08bb81fda6c157433e2f73a1a893b33b103fd03ad69b95 | 1050 | 920 |
| greek | lemma_2gram | LF_44db9f6765efa2fc576bd8bc40e07a5ad6dedf9ca02bbab7c738178c15f33db1 | 985 | 892 |
| greek | lemma_2gram | LF_9950cd568ed8dd7b2c61c77c591e69bdec6ec5c22e21173e2ae117a3dd0f580e | 845 | 780 |
| greek | lemma_2gram | LF_13f3ea649e0a53d7eaf61b1282406f32e1f171af7a8e91e48984fc0837d2b33c | 700 | 669 |
| greek | lemma_2gram | LF_0239372676f7700fb95e13532e6a40a0dbe64b2d8460f2a4d56f09d31c5d52e5 | 644 | 607 |
| greek | lemma_2gram | LF_bef10a03341a3339e8c89615059ebb9a4bf4ca149fae08fe811f19db226faf91 | 532 | 489 |
| greek | lemma_2gram | LF_919d3402f9d1b388a4f24d7c190335143639bb4d5e509399c7a7846ace930b90 | 494 | 470 |
| greek | lemma_2gram | LF_df2ef614d18fac6ec8079686a2c4ecbc34aaadc50ec08c6cae1b6f9c7040374e | 475 | 448 |
| greek | lemma_2gram | LF_75e37191baa50d1ab7fbd1afc3f22dbefdcbe06eec0c1b92c6e933a1277cbd51 | 450 | 410 |
| greek | lemma_3gram | LF_cbbc6dc853e9965974f224bd30319693233a48ff99cd801d98ea73805df6fe00 | 162 | 162 |
| greek | lemma_3gram | LF_d43e25d01d466db4ec980ea58ef25870a3441e6ff23f64aac40b4950f8da4058 | 127 | 122 |
| greek | lemma_3gram | LF_17d374f00398921e4707445bd8e6c09eade974e1123a9d6eb4adb30a08393109 | 116 | 116 |
| greek | lemma_3gram | LF_c758a7e8c7529ebdb077fa415a7a1924d2c800db426255a5e8bf86a59f539bba | 108 | 104 |
| greek | lemma_3gram | LF_b88c35e2b56628cafb45b976d4ddbdd72496802dba0ca825d95c2fffd9f170e8 | 105 | 100 |
| greek | lemma_3gram | LF_3df3fce5094518e463c3a8b7e43196d76cb37c3270253f702448793c435734e4 | 102 | 101 |
| greek | lemma_3gram | LF_e875e91972c388b01c8b4c8f7df83a773fb661a4c96f97d24c70bc7fd0921e8e | 97 | 94 |
| greek | lemma_3gram | LF_043607071ae6bca3ecb87576c5ec2f0e0f5232bf2cf9e00c44f74453d98824cd | 93 | 92 |
| greek | lemma_3gram | LF_3a989870ec64f88dfec34490890713dbba6d5f85d10339c9234091feca7fde53 | 93 | 91 |
| greek | lemma_3gram | LF_ae3f2a0ed8e89ab5e56a1d884eef553991dc82665aaa788bfef1d38ebff4a46b | 91 | 87 |

#### Highest-document-frequency features

| corpus | family | feature ID | corpus frequency | document frequency |
| --- | --- | --- | --- | --- |
| hebrew | lemma | LF_992d928a7f757c33a90a41df6b1629d111021535f69c6b4cec26428b617de312 | 51004 | 19875 |
| hebrew | lemma | LF_87712125a0eba18b505b68cf3e26455be229124c69a98371da21fd7d6848d145 | 46940 | 17996 |
| hebrew | lemma | LF_dac7db9583ddc9e6a9b06d3b45d349d856846395ee594434898360868754e5e8 | 20446 | 11848 |
| hebrew | lemma | LF_68b3d704f5c4c66ecf12bb1bb2d113c99b31f507706b35529f4a7b5daf4186eb | 24011 | 11123 |
| hebrew | lemma | LF_aa8ab06a95f6acac3215ddb2a4b4c3665c4a3525537905efb7a1c4e6d06edfdb | 15765 | 10291 |
| hebrew | lemma | LF_6beca81fcc70e6ff83c4512f2dc7f1cefa6f9b60a4abf7b6d714f1eb07ad426b | 11870 | 7230 |
| hebrew | lemma | LF_d932fe8e841b91b8a0e3454be0c6ee8cf11ba7e6797599d6eb87ac45b70aa953 | 7728 | 5878 |
| hebrew | lemma | LF_a711628ff8c5accb09eaad7a574dd551ace5700c3f69b9be4e3ba3cb42e634f4 | 6521 | 5522 |
| hebrew | lemma | LF_6d4fd398a00b1b71dd5a650a3e146904d9a0d209937624767ee7ffcee3a594e1 | 5879 | 4581 |
| hebrew | lemma | LF_ad9c00c49509f709bd839eb782cc59eec4bf5be67628129fe31ae3918dee2d3a | 5500 | 4438 |
| hebrew | surface | LF_8875436f93b31801b2d6d80397287abb347af9f578e4ef3df1f9ad351bffa537 | 23484 | 13094 |
| hebrew | surface | LF_95a8f907976befe2be18b1c340c394f1240409941fa223c8124069815178af42 | 16091 | 8824 |
| hebrew | surface | LF_723f532007c41225f89db7746f2d9a83a43cc2aeb5976ba8c77d2e603214720e | 14735 | 8444 |
| hebrew | surface | LF_46f805f51ccc7b04569465fdd3aaaee2a9471b5c603466dcf383e34ba1a90870 | 7921 | 5964 |
| hebrew | surface | LF_220795864a5a94ae8d258a021aaa8c7f18a898d213c22b2afc862c96c9b28af0 | 7964 | 5849 |
| hebrew | surface | LF_5c981a90724916bc62af04b5f10a1c3b29aea884510a0c88ee5c6f81360a8bc0 | 8217 | 5457 |
| hebrew | surface | LF_e60962312a25daa2c647b597c4b0f363c520037ff76fb63ef919bb4c2a3412a4 | 6494 | 5389 |
| hebrew | surface | LF_c6ad6ec1aa112f4187cbff5ef0f47ea65983347d0c891c94a4c85cfc5f9370de | 6812 | 5157 |
| hebrew | surface | LF_c5081afd788c3fea2223fca0577e3f010c9f683246fd5662a01ac99af64fa5b7 | 6942 | 5068 |
| hebrew | surface | LF_b9a8e9b41c66a1422f5e4c3c009f729f067b133c61505b495efd3b746fff720a | 6289 | 4090 |
| hebrew | english_gloss | LF_beed6ded095496d3e9540df9075ac95d8aa2e2a2dbc59d08f04f562176896c16 | 39548 | 17869 |
| hebrew | english_gloss | LF_7ab7fece75c8bdfc6dfc49ff994fe6e892579857b74a5f6a1c715a5e133cab6f | 24467 | 11275 |
| hebrew | english_gloss | LF_c1f32fa779df2723a5b7329a34bfa2724d22ea12be105202917ff123f7173cc4 | 19026 | 11214 |
| hebrew | english_gloss | LF_bd6df7e6f1849d4e6d738894a9841ff54090c1d0a8d88cd550195ed54a30f324 | 8989 | 6900 |
| hebrew | english_gloss | LF_87d27091aa8b85d694bca3a5ca26e14aec9d98cf57384c5d07e5bff933d30459 | 7216 | 6062 |
| hebrew | english_gloss | LF_a909bcadaea22a2a97b8e4fb61ea8d2fd635b12e88a835efcd1a1c5c604a5d33 | 7110 | 5487 |
| hebrew | english_gloss | LF_192cccfe49340dab9e54cfa65aaee6e986d288841b8d00ceca0223388839c2c8 | 6268 | 4325 |
| hebrew | english_gloss | LF_2c6792805e355c21cd74043d89255a0b250f49f9e838b845d6c2c0f7e02ad022 | 5231 | 4244 |
| hebrew | english_gloss | LF_2b05698fd754168673eb993a5bb23ddc0794504c4c7362127ca33b441525de8b | 5296 | 4075 |
| hebrew | english_gloss | LF_3dd3505247ab39487b7d5f4e816d74679870f5a66dd41850f7af29e9c8faf62e | 6188 | 4071 |
| greek | lemma | LF_9c62b12d9352f8501dea189a32acf671c5763fe24659fead60720805c3399399 | 19783 | 6965 |
| greek | lemma | LF_3dd4166fc39b717ec3e5911478671038933510a4499e5e96c6b6820d958ebd46 | 8978 | 5126 |
| greek | lemma | LF_c38429e715122caca775025665ef000e42e1b5b90e44a4c7ec1ab8c8c797e2ce | 5561 | 3711 |
| greek | lemma | LF_56a1f74972d4415da2436b9848db106f951e8731e4a0e2e662ab7b32bd297c17 | 2787 | 2476 |
| greek | lemma | LF_3dc8f82fe3a538cc1b9a60e03e5ab0ef53ce54116717f835dc99daac74984366 | 2743 | 2105 |
| greek | lemma | LF_b510b4828bc4a7f4a84958f32931daf272349dde86c198b4f6585c8075d7b40c | 2457 | 2094 |
| greek | lemma | LF_7031322e2e69142fc342a07c4b50a2d3bc0f2dbbca952dd5b72dc7e91b5b45c9 | 2892 | 2027 |
| greek | lemma | LF_3427a9dd67f407f8fd5baeec7164583321ba22fb69cb749c3820d08f08397c31 | 2255 | 1942 |
| greek | lemma | LF_6cb9c664af00abb5c0c64780927560531cb236b1e91f1f2ac9ad795a27f65203 | 2567 | 1827 |
| greek | lemma | LF_56a00adf3f6a6508e2e739bc871c849c5b6b8346118e4eeb46162828dab9603b | 1766 | 1508 |
| greek | surface | LF_cc55dbf27778557fa4839f0f5148230c36afa30fff2c03ab45f249dd03f2759a | 8545 | 4978 |
| greek | surface | LF_5d2f9997760b413b67dc7484714f81020d9ea9cb851f3d06c90654d00e9c150b | 2620 | 2332 |
| greek | surface | LF_dea88b1f63e14556cb4de08c10a7029a1e5989410c286f7dc857bd61ad74de56 | 2769 | 2179 |
| greek | surface | LF_5552c94248974e90aa9faf4c14eb177e76a7dc9e95ba64e59c8c41d0f5377786 | 2684 | 2062 |
| greek | surface | LF_5d2df4fdbe5694e873c7cf11a9998d766c806ebe99373edd9cc5bc2ea2290da6 | 2497 | 1928 |
| greek | surface | LF_83da1d087977ab221fc7a4ce07c201fdf9c36569710624a63d9d4a15c4bca0bd | 1755 | 1501 |
| greek | surface | LF_238fb6cdeccb0b327007f6b37aab7fd680ad4a49af0d4f850ca0290df4a71c15 | 1658 | 1330 |
| greek | surface | LF_29cfbc906cd14ab73c7b833e59af60c9f7fd6b97af0557707c0257612054c779 | 1556 | 1308 |
| greek | surface | LF_4f578ed3632fc3b8e912b91dfbc0010b9e513139075478522f8d369e1f503d60 | 1518 | 1273 |
| greek | surface | LF_9a832ecd50fc0e441bd7e9dfa563f1c6aa7608c9b238bd6482837c8eadf21df3 | 1411 | 1191 |
| greek | english_gloss | LF_7ab7fece75c8bdfc6dfc49ff994fe6e892579857b74a5f6a1c715a5e133cab6f | 15618 | 6556 |
| greek | english_gloss | LF_beed6ded095496d3e9540df9075ac95d8aa2e2a2dbc59d08f04f562176896c16 | 8599 | 4965 |
| greek | english_gloss | LF_2c6792805e355c21cd74043d89255a0b250f49f9e838b845d6c2c0f7e02ad022 | 8854 | 4915 |
| greek | english_gloss | LF_c1f32fa779df2723a5b7329a34bfa2724d22ea12be105202917ff123f7173cc4 | 6712 | 4272 |
| greek | english_gloss | LF_3dd3505247ab39487b7d5f4e816d74679870f5a66dd41850f7af29e9c8faf62e | 4548 | 2606 |
| greek | english_gloss | LF_bd6df7e6f1849d4e6d738894a9841ff54090c1d0a8d88cd550195ed54a30f324 | 3157 | 2397 |
| greek | english_gloss | LF_98fb953639a94406991441bc2cfaf011eb51944c39269329657eddd586923069 | 3283 | 2320 |
| greek | english_gloss | LF_184554dd0fec91ee65a30e4e89af492515886ae047e5a070b6cba247b2dc37f5 | 2726 | 2151 |
| greek | english_gloss | LF_2b05698fd754168673eb993a5bb23ddc0794504c4c7362127ca33b441525de8b | 2576 | 2083 |
| greek | english_gloss | LF_042d8f07cc8716674945c6c6a36355956412a8206c1f5c3cc296001c4dedf475 | 2660 | 2078 |

#### Formulaic features

| corpus | family | feature ID | corpus frequency | document frequency | governed action |
| --- | --- | --- | --- | --- | --- |
| hebrew | lemma | LF_992d928a7f757c33a90a41df6b1629d111021535f69c6b4cec26428b617de312 | 51004 | 19875 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_87712125a0eba18b505b68cf3e26455be229124c69a98371da21fd7d6848d145 | 46940 | 17996 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_dac7db9583ddc9e6a9b06d3b45d349d856846395ee594434898360868754e5e8 | 20446 | 11848 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_68b3d704f5c4c66ecf12bb1bb2d113c99b31f507706b35529f4a7b5daf4186eb | 24011 | 11123 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_aa8ab06a95f6acac3215ddb2a4b4c3665c4a3525537905efb7a1c4e6d06edfdb | 15765 | 10291 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_6beca81fcc70e6ff83c4512f2dc7f1cefa6f9b60a4abf7b6d714f1eb07ad426b | 11870 | 7230 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_d932fe8e841b91b8a0e3454be0c6ee8cf11ba7e6797599d6eb87ac45b70aa953 | 7728 | 5878 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_a711628ff8c5accb09eaad7a574dd551ace5700c3f69b9be4e3ba3cb42e634f4 | 6521 | 5522 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_6d4fd398a00b1b71dd5a650a3e146904d9a0d209937624767ee7ffcee3a594e1 | 5879 | 4581 | marked_formulaic_and_retained_for_audit |
| hebrew | lemma | LF_ad9c00c49509f709bd839eb782cc59eec4bf5be67628129fe31ae3918dee2d3a | 5500 | 4438 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_8875436f93b31801b2d6d80397287abb347af9f578e4ef3df1f9ad351bffa537 | 23484 | 13094 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_95a8f907976befe2be18b1c340c394f1240409941fa223c8124069815178af42 | 16091 | 8824 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_723f532007c41225f89db7746f2d9a83a43cc2aeb5976ba8c77d2e603214720e | 14735 | 8444 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_46f805f51ccc7b04569465fdd3aaaee2a9471b5c603466dcf383e34ba1a90870 | 7921 | 5964 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_220795864a5a94ae8d258a021aaa8c7f18a898d213c22b2afc862c96c9b28af0 | 7964 | 5849 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_5c981a90724916bc62af04b5f10a1c3b29aea884510a0c88ee5c6f81360a8bc0 | 8217 | 5457 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_e60962312a25daa2c647b597c4b0f363c520037ff76fb63ef919bb4c2a3412a4 | 6494 | 5389 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_c6ad6ec1aa112f4187cbff5ef0f47ea65983347d0c891c94a4c85cfc5f9370de | 6812 | 5157 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_c5081afd788c3fea2223fca0577e3f010c9f683246fd5662a01ac99af64fa5b7 | 6942 | 5068 | marked_formulaic_and_retained_for_audit |
| hebrew | surface | LF_b9a8e9b41c66a1422f5e4c3c009f729f067b133c61505b495efd3b746fff720a | 6289 | 4090 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_beed6ded095496d3e9540df9075ac95d8aa2e2a2dbc59d08f04f562176896c16 | 39548 | 17869 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_7ab7fece75c8bdfc6dfc49ff994fe6e892579857b74a5f6a1c715a5e133cab6f | 24467 | 11275 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_c1f32fa779df2723a5b7329a34bfa2724d22ea12be105202917ff123f7173cc4 | 19026 | 11214 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_bd6df7e6f1849d4e6d738894a9841ff54090c1d0a8d88cd550195ed54a30f324 | 8989 | 6900 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_87d27091aa8b85d694bca3a5ca26e14aec9d98cf57384c5d07e5bff933d30459 | 7216 | 6062 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_a909bcadaea22a2a97b8e4fb61ea8d2fd635b12e88a835efcd1a1c5c604a5d33 | 7110 | 5487 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_192cccfe49340dab9e54cfa65aaee6e986d288841b8d00ceca0223388839c2c8 | 6268 | 4325 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_2c6792805e355c21cd74043d89255a0b250f49f9e838b845d6c2c0f7e02ad022 | 5231 | 4244 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_2b05698fd754168673eb993a5bb23ddc0794504c4c7362127ca33b441525de8b | 5296 | 4075 | marked_formulaic_and_retained_for_audit |
| hebrew | english_gloss | LF_3dd3505247ab39487b7d5f4e816d74679870f5a66dd41850f7af29e9c8faf62e | 6188 | 4071 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_9c62b12d9352f8501dea189a32acf671c5763fe24659fead60720805c3399399 | 19783 | 6965 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_3dd4166fc39b717ec3e5911478671038933510a4499e5e96c6b6820d958ebd46 | 8978 | 5126 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_c38429e715122caca775025665ef000e42e1b5b90e44a4c7ec1ab8c8c797e2ce | 5561 | 3711 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_56a1f74972d4415da2436b9848db106f951e8731e4a0e2e662ab7b32bd297c17 | 2787 | 2476 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_3dc8f82fe3a538cc1b9a60e03e5ab0ef53ce54116717f835dc99daac74984366 | 2743 | 2105 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_b510b4828bc4a7f4a84958f32931daf272349dde86c198b4f6585c8075d7b40c | 2457 | 2094 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_7031322e2e69142fc342a07c4b50a2d3bc0f2dbbca952dd5b72dc7e91b5b45c9 | 2892 | 2027 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_3427a9dd67f407f8fd5baeec7164583321ba22fb69cb749c3820d08f08397c31 | 2255 | 1942 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_6cb9c664af00abb5c0c64780927560531cb236b1e91f1f2ac9ad795a27f65203 | 2567 | 1827 | marked_formulaic_and_retained_for_audit |
| greek | lemma | LF_56a00adf3f6a6508e2e739bc871c849c5b6b8346118e4eeb46162828dab9603b | 1766 | 1508 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_cc55dbf27778557fa4839f0f5148230c36afa30fff2c03ab45f249dd03f2759a | 8545 | 4978 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_5d2f9997760b413b67dc7484714f81020d9ea9cb851f3d06c90654d00e9c150b | 2620 | 2332 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_dea88b1f63e14556cb4de08c10a7029a1e5989410c286f7dc857bd61ad74de56 | 2769 | 2179 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_5552c94248974e90aa9faf4c14eb177e76a7dc9e95ba64e59c8c41d0f5377786 | 2684 | 2062 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_5d2df4fdbe5694e873c7cf11a9998d766c806ebe99373edd9cc5bc2ea2290da6 | 2497 | 1928 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_83da1d087977ab221fc7a4ce07c201fdf9c36569710624a63d9d4a15c4bca0bd | 1755 | 1501 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_238fb6cdeccb0b327007f6b37aab7fd680ad4a49af0d4f850ca0290df4a71c15 | 1658 | 1330 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_29cfbc906cd14ab73c7b833e59af60c9f7fd6b97af0557707c0257612054c779 | 1556 | 1308 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_4f578ed3632fc3b8e912b91dfbc0010b9e513139075478522f8d369e1f503d60 | 1518 | 1273 | marked_formulaic_and_retained_for_audit |
| greek | surface | LF_9a832ecd50fc0e441bd7e9dfa563f1c6aa7608c9b238bd6482837c8eadf21df3 | 1411 | 1191 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_7ab7fece75c8bdfc6dfc49ff994fe6e892579857b74a5f6a1c715a5e133cab6f | 15618 | 6556 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_beed6ded095496d3e9540df9075ac95d8aa2e2a2dbc59d08f04f562176896c16 | 8599 | 4965 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_2c6792805e355c21cd74043d89255a0b250f49f9e838b845d6c2c0f7e02ad022 | 8854 | 4915 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_c1f32fa779df2723a5b7329a34bfa2724d22ea12be105202917ff123f7173cc4 | 6712 | 4272 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_3dd3505247ab39487b7d5f4e816d74679870f5a66dd41850f7af29e9c8faf62e | 4548 | 2606 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_bd6df7e6f1849d4e6d738894a9841ff54090c1d0a8d88cd550195ed54a30f324 | 3157 | 2397 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_98fb953639a94406991441bc2cfaf011eb51944c39269329657eddd586923069 | 3283 | 2320 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_184554dd0fec91ee65a30e4e89af492515886ae047e5a070b6cba247b2dc37f5 | 2726 | 2151 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_2b05698fd754168673eb993a5bb23ddc0794504c4c7362127ca33b441525de8b | 2576 | 2083 | marked_formulaic_and_retained_for_audit |
| greek | english_gloss | LF_042d8f07cc8716674945c6c6a36355956412a8206c1f5c3cc296001c4dedf475 | 2660 | 2078 | marked_formulaic_and_retained_for_audit |

#### Rare, hapax, and near-hapax features

| corpus | family | feature ID | corpus frequency | document frequency | rarity class |
| --- | --- | --- | --- | --- | --- |
| hebrew | lemma | LF_8b519e47eb5e19cfe52900be9b8b975497ed8b88f964e99d83fc1cc640c42faf | 1 | 1 | hapax |
| hebrew | lemma | LF_af2c6e3d454356809e1c3e5734c7b663aa666ae5161e4e58b44f879b4fb5eaf2 | 1 | 1 | hapax |
| hebrew | lemma | LF_c1b1a5665dbc8dbc3c41190d3165063132e35a15b23e6707f2b12f7abd064f95 | 1 | 1 | hapax |
| hebrew | lemma | LF_aebd9eb73dbb1684bdae0341500cbcb94e2ef32fa8a550b76c8e8630919fb465 | 1 | 1 | hapax |
| hebrew | lemma | LF_d919cd39d9d87e43a3f8ce13f90fcc0e8d94ac75bb9bc89ed2f6fe56d6f159be | 1 | 1 | hapax |
| hebrew | lemma | LF_6df1636d88eb74d1055693d99c1b65956a1e76657a1a689e76aba5c7e50a73d5 | 1 | 1 | hapax |
| hebrew | lemma | LF_dba81e3e2347f9c18e3897818fcdd4f8b2be86b6ddaa20cbd7b22af2dd0b54cd | 1 | 1 | hapax |
| hebrew | lemma | LF_c0da9a10d042a9a2fc867e22346a3395160636cb0f3c6c29544c550fdce1f92d | 1 | 1 | hapax |
| hebrew | lemma | LF_4c732ac9b2021aeea2c0cf5adcb9f5333c0a8409ac27c0c8cd8ee24dcdd7629a | 1 | 1 | hapax |
| hebrew | lemma | LF_0322baec1533ecb8512b1ae1f893c46fd781c252db7d17726b5659ddc3dc366f | 1 | 1 | hapax |
| hebrew | surface | LF_ccd7fdaf4c51c6c1a5deecb5ac2f624284e447608b6b7e64dda518219fd0e2f3 | 1 | 1 | hapax |
| hebrew | surface | LF_542c3f8744a469364455f997976e16fc9d5ef6c1f63e0bc08de6f195e324a804 | 1 | 1 | hapax |
| hebrew | surface | LF_b0a86a0fb96c4ca8e542aaead39bcde5d40b00607c548f70ceb3ff2988343636 | 1 | 1 | hapax |
| hebrew | surface | LF_ca84d6dfce82d3ebd3348e4ee127f8cfe9b0a2e81e892a0e94411012eb808d76 | 1 | 1 | hapax |
| hebrew | surface | LF_79bf4374234cdbec0266e168c468a84e71f9fc1764451ed281ee209190564e9b | 1 | 1 | hapax |
| hebrew | surface | LF_e219efbe65945d11ef3b6d45aa5dc42abffca2d37efac7a37b0eaac6c2d4ff28 | 1 | 1 | hapax |
| hebrew | surface | LF_6b08e781767caaa4bbdf332a24194806617d32c67cc6fcf9c9b67a033b37d84e | 1 | 1 | hapax |
| hebrew | surface | LF_1bc3a096e59b6fd1496a2aa648bcaceb1dc97b809249ac83cd8afd2ded32f754 | 1 | 1 | hapax |
| hebrew | surface | LF_693323c06f7e127a31bc57c864e849fb6c9d83aaf812dee58b2ad99ba904f50f | 1 | 1 | hapax |
| hebrew | surface | LF_60de86a0532130fc1a52beec386ccbcda8532c56841209a68c3ab71ab8dbbda5 | 1 | 1 | hapax |
| hebrew | english_gloss | LF_23ab82d2bf104510e7bca12fb44e0d09b94a2befec1ac8c37f64917fc219fd64 | 1 | 1 | hapax |
| hebrew | english_gloss | LF_2014194bc97905bc785e46081d8d0d08c7876a9122b4cc536c33397718b31862 | 1 | 1 | hapax |
| hebrew | english_gloss | LF_153473ba57b8abd5cfab771cc5ce0950ec859c0ae3e34186e5b82b548d21e6bb | 1 | 1 | hapax |
| hebrew | english_gloss | LF_9572004c605cd6f2547b3f011bd2130a2d4b3c007c7ffbed413dafc0537d5d86 | 1 | 1 | hapax |
| hebrew | english_gloss | LF_3c8511e8f5ac416957d4a890c51faff7f04b141f41fa11e7ba39e6361dbec09b | 1 | 1 | hapax |
| hebrew | english_gloss | LF_f9dbac71676aae08249f5a36c29c06f84c059255de039c0697c34ae48dfcad77 | 1 | 1 | hapax |
| hebrew | english_gloss | LF_08e4566fbedb4c5eb264f01f23140f85f41c903e6542678d134c80fa0268d02c | 1 | 1 | hapax |
| hebrew | english_gloss | LF_cc0b92bef1bfd8b5801359ae1054c309f54714bec69232a5ecc5f1ff958c7216 | 1 | 1 | hapax |
| hebrew | english_gloss | LF_1ff41be97de5565774f41e8bf9a44c052f0c00264438adb6d99ea89078571ce1 | 1 | 1 | hapax |
| hebrew | english_gloss | LF_ec7d5a30897c58b6d0bfd79a35cc8dfbe94e03ec3519854607672c4e9a18c0a6 | 1 | 1 | hapax |
| greek | lemma | LF_aad6c8e24d7979ae5d664129fa6af5e04a9ad9c0cfd9396fe5dddce7c97af7f3 | 1 | 1 | hapax |
| greek | lemma | LF_1b950bb3dd820130c0397c9d9b3f02dfad763eed4a2c29ef217a218495f9dc99 | 1 | 1 | hapax |
| greek | lemma | LF_41efff73e30e46fe335a6e2855b80ad8fc708b355ff5be2a18451da39c0a890f | 1 | 1 | hapax |
| greek | lemma | LF_99a81ed4dbbf7d29b7f51d8543dd96467e45c2efe6f0c199e2d31db76137b99c | 1 | 1 | hapax |
| greek | lemma | LF_60f2c260f15cfe41c777b4bb444e87fc31dc7ccf5935dfd4660519ee5da56896 | 1 | 1 | hapax |
| greek | lemma | LF_11e4446290d3320dd018752046989bb409b3006179c0fe1a62bad7c9d25bc733 | 1 | 1 | hapax |
| greek | lemma | LF_8bd0dce50207f1218e2f8432a9c50ddffff4cad9f3ad69c70fe64c51a6de4126 | 1 | 1 | hapax |
| greek | lemma | LF_e6b53cdbca0c9e94ab0922b88a5407f21b503eed2ebb85d70c907bbbb7ca8908 | 1 | 1 | hapax |
| greek | lemma | LF_f10a09a9da46028a2f712f0f4b2af3bd88b3b16b5f8e6164bb5d9089e5a5a724 | 1 | 1 | hapax |
| greek | lemma | LF_2dd07ad628588964fbbbac317119d34539a0c58318a0fe49f0dca3c6c48dd751 | 1 | 1 | hapax |
| greek | surface | LF_3779cdba3873d0328bd5ab0227d139d113f8c922e29361b7f6bb1d7f0e699923 | 1 | 1 | hapax |
| greek | surface | LF_1a5d345b71b11cd18b8cbc526fa9aac608d2dfb754d51e9f4ed529ba62a37769 | 1 | 1 | hapax |
| greek | surface | LF_32f4b1912c2978714cb6683dbcfc97e40d6db81b71ea8aed2bfb5896782bc0ec | 1 | 1 | hapax |
| greek | surface | LF_357e14199cfa7725d115b18ebe744e10f619fc033e621799b135d0ec0c877540 | 1 | 1 | hapax |
| greek | surface | LF_913d00007b4f8f42169bbe86c107d628448bf12209a89d06ba82178117a002f4 | 1 | 1 | hapax |
| greek | surface | LF_18068d8c9f27e4ee481d695154a2df726fac572d808cc2453ce2a1b96610d3a5 | 1 | 1 | hapax |
| greek | surface | LF_a2e98ee741beda7cc6b22f3a8a69393e6bcdd328ca412e55df92063b992f4904 | 1 | 1 | hapax |
| greek | surface | LF_da272530ba170b7b6bb4bd4829fb159a5112fe7e5bce5d4d82991c9a051ee4d3 | 1 | 1 | hapax |
| greek | surface | LF_5d5c00a8dc5ec6e840e5cd44a0a6df4db71b0c7b38b6b4ea0000d2aa6b95c962 | 1 | 1 | hapax |
| greek | surface | LF_f02ea536d1d2abea58772becfca9d1e67301cc5542e08292f180a8c98c251431 | 1 | 1 | hapax |
| greek | english_gloss | LF_b4b81b1ea3e68b7d7a9e1f9403c9d7cca2dd6e83fb4330fa89fb9a051467d67e | 1 | 1 | hapax |
| greek | english_gloss | LF_eb66b52385cc5a0aa4b92e54ed2c24c374016c3a6fbb36730d2c327ad94ff2fd | 1 | 1 | hapax |
| greek | english_gloss | LF_614045e66f2cb724c036597cb589c7e483b2cfde1991e51fe77d410125b60480 | 1 | 1 | hapax |
| greek | english_gloss | LF_f836a3c91f81135f9b1b6c69d148e7213ffeae9edc7e6b6bdbb8fd9fd1f56faf | 1 | 1 | hapax |
| greek | english_gloss | LF_2e09a6b6739eff5a7c932320fad2de4cadb3142c3851db1f1ac6b2e638ac8ff5 | 1 | 1 | hapax |
| greek | english_gloss | LF_ed4de0b9accdade3c821bce06eeb52df44055290f163e791927befe2a59c65b4 | 1 | 1 | hapax |
| greek | english_gloss | LF_9da47ecf214b71e63ff3b87e1d1277bff257ec4ff2866c0ed0184834f5ec1531 | 1 | 1 | hapax |
| greek | english_gloss | LF_35ab9ecdeb0c77329b3b95d9d054d165d14f338ac34426a3a0e429b0455f4746 | 1 | 1 | hapax |
| greek | english_gloss | LF_f375838cb76fb750fe91ec896570fde0ca30a515ae745999b347b78b7e021e7a | 1 | 1 | hapax |
| greek | english_gloss | LF_f3dc2adbb2ae6f6c0658e39b2b033e8f944242fae3a6caad3d310b75596921cf | 1 | 1 | hapax |

#### Lemma frequencies changed by Qere/Ketiv reading

| feature ID | Qere frequency | Ketiv frequency | Ketiv minus Qere |
| --- | --- | --- | --- |
| LF_87712125a0eba18b505b68cf3e26455be229124c69a98371da21fd7d6848d145 | 46940 | 46551 | -389 |
| LF_992d928a7f757c33a90a41df6b1629d111021535f69c6b4cec26428b617de312 | 51004 | 50724 | -280 |
| LF_68b3d704f5c4c66ecf12bb1bb2d113c99b31f507706b35529f4a7b5daf4186eb | 24011 | 23925 | -86 |
| LF_dac7db9583ddc9e6a9b06d3b45d349d856846395ee594434898360868754e5e8 | 20446 | 20368 | -78 |
| LF_aa8ab06a95f6acac3215ddb2a4b4c3665c4a3525537905efb7a1c4e6d06edfdb | 15765 | 15700 | -65 |
| LF_d932fe8e841b91b8a0e3454be0c6ee8cf11ba7e6797599d6eb87ac45b70aa953 | 7728 | 7695 | -33 |
| LF_e7ef74a1d7803d8996a05a2df1eef7eabe0a6326ddb9fc8817fb2d0729f43c9c | 1574 | 1550 | -24 |
| LF_6137204f9203e63175c32fb51d3ba7019aa99b577d61da8baeec9e63bbfd81cb | 2558 | 2536 | -22 |
| LF_f807cf385eb3495d1bb6ee6442a2f48737cc582cb4c19517c5b577097e557e58 | 1055 | 1039 | -16 |
| LF_a1018f57440253e78ad9d1c2e900ab3b08ea96c41b7413e2b0491ba5b893b8cd | 3560 | 3545 | -15 |
| LF_7aca3006124cf1513ac6565bcc9e3094cb48fafb24c3f6b04a1d24a7829a1688 | 2965 | 2950 | -15 |
| LF_6d4fd398a00b1b71dd5a650a3e146904d9a0d209937624767ee7ffcee3a594e1 | 5879 | 5864 | -15 |
| LF_292e240fa1205874ae2b88e6c5bfd7f9e8b15c0c905fef025b872cfc70613894 | 799 | 785 | -14 |
| LF_915496c64a57a199180356642ee02eee3243305004aa205db51a3764a3d608bd | 1442 | 1429 | -13 |
| LF_a826c37f3d15218324ee8ce3cb5b0b945ccd6012718d3c7fc5114dde6817d3b7 | 67 | 54 | -13 |
| LF_03d049f45afec91c7e5fc9ab05468dfee74bed2d520196a0f82ae134e5989d20 | 49 | 37 | -12 |
| LF_c61f640c08a56b2dd1c45cb803229af5ee7932be26b0954a00bed912f7423d49 | 188 | 176 | -12 |
| LF_45f379342a0d031ed229b8a6e36f8d2e2bbf56e5d67489c9e81e6cade86b22df | 2629 | 2618 | -11 |
| LF_cbb6d435d9f5965da62a2dfefa122e6b527537fb641a54d9d5e53a03fb7e122b | 16 | 6 | -10 |
| LF_1c2c0797c044c79dd3d721c643ed05b60cc7a5af142c10ce30f61921b84a5c01 | 5308 | 5298 | -10 |
| LF_d833e7e4ba521a2c3280bf7be0bd9b74dfce2c4d87c60dc5fc8402e2dbdc4627 | 1618 | 1608 | -10 |
| LF_aa25955d9342708a7da2f893e69da700c742ea98f707c24dc57e0c5d75ad12a1 | 1078 | 1068 | -10 |
| LF_a8aa27ee1eb8a7a97c0169cf3af02604e8d056fa956352703babde81f8c4c89f | 894 | 884 | -10 |
| LF_922b2be305ea550b837931ee3679b5b71af1908e478c2602471a7694c668050f | 28 | 18 | -10 |
| LF_cdb34d02abd9a74bc17fe8fc3efc5b49ceeb4c02b0ea35d9077c02647dc65c92 | 4936 | 4927 | -9 |

## Passage-length distributions

| corpus | profile | reading | granularity | count | min | median | p95 | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| greek | critical_core | source | clause | 46072 | 1 | 2.0 | 8.0 | 155 |
| greek | critical_core | source | five_verse | 7806 | 23 | 85.0 | 119.0 | 163 |
| greek | critical_core | source | sentence | 7984 | 1 | 14.0 | 40.0 | 165 |
| greek | critical_core | source | two_verse | 7890 | 4 | 34.0 | 52.0 | 88 |
| greek | critical_core | source | verse | 7918 | 2 | 17.0 | 30.0 | 58 |
| greek | edition_complete | source | clause | 46216 | 1 | 2.0 | 8.0 | 155 |
| greek | edition_complete | source | five_verse | 7834 | 23 | 85.0 | 119.0 | 163 |
| greek | edition_complete | source | sentence | 8011 | 1 | 14.0 | 40.0 | 165 |
| greek | edition_complete | source | two_verse | 7915 | 4 | 34.0 | 52.0 | 88 |
| greek | edition_complete | source | verse | 7943 | 2 | 17.0 | 30.0 | 58 |
| hebrew | critical_core | ketiv | clause | 97034 | 1 | 4.0 | 11.0 | 54 |
| hebrew | critical_core | ketiv | five_verse | 23057 | 15 | 105.0 | 157.0 | 251 |
| hebrew | critical_core | ketiv | sentence | 23213 | 2 | 19.0 | 39.0 | 81 |
| hebrew | critical_core | ketiv | two_verse | 23174 | 4 | 40.0 | 69.0 | 123 |
| hebrew | critical_core | ketiv | verse | 23213 | 2 | 19.0 | 39.0 | 81 |
| hebrew | critical_core | qere | clause | 97106 | 1 | 4.0 | 11.0 | 54 |
| hebrew | critical_core | qere | five_verse | 23057 | 15 | 105.0 | 157.0 | 251 |
| hebrew | critical_core | qere | sentence | 23213 | 2 | 19.0 | 39.0 | 81 |
| hebrew | critical_core | qere | two_verse | 23174 | 4 | 40.0 | 69.0 | 123 |
| hebrew | critical_core | qere | verse | 23213 | 2 | 19.0 | 39.0 | 81 |
| hebrew | edition_complete | ketiv | clause | 97034 | 1 | 4.0 | 11.0 | 54 |
| hebrew | edition_complete | ketiv | five_verse | 23057 | 15 | 105.0 | 157.0 | 251 |
| hebrew | edition_complete | ketiv | sentence | 23213 | 2 | 19.0 | 39.0 | 81 |
| hebrew | edition_complete | ketiv | two_verse | 23174 | 4 | 40.0 | 69.0 | 123 |
| hebrew | edition_complete | ketiv | verse | 23213 | 2 | 19.0 | 39.0 | 81 |
| hebrew | edition_complete | qere | clause | 97106 | 1 | 4.0 | 11.0 | 54 |
| hebrew | edition_complete | qere | five_verse | 23057 | 15 | 105.0 | 157.0 | 251 |
| hebrew | edition_complete | qere | sentence | 23213 | 2 | 19.0 | 39.0 | 81 |
| hebrew | edition_complete | qere | two_verse | 23174 | 4 | 40.0 | 69.0 | 123 |
| hebrew | edition_complete | qere | verse | 23213 | 2 | 19.0 | 39.0 | 81 |

The primary calibrated v1 scope contains 23,213 Hebrew/Aramaic Qere verses and 7,943 Greek source verses. Other granularities are production interfaces with bounded smoke tests only.

## Phrase feasibility

| corpus | lemma bigrams count>=2 | lemma trigrams count>=2 | lemma skipgrams count>=2 | maximum bigram count | maximum trigram count | maximum skipgram count |
| --- | --- | --- | --- | --- | --- | --- |
| greek | 13485 | 13303 | 24223 | 1567 | 162 | 5824 |
| hebrew | 34408 | 51153 | 65589 | 9427 | 648 | 12103 |

| corpus | root bigrams count>=2 | root trigrams count>=2 | root skipgrams count>=2 | maximum bigram count | maximum trigram count | maximum skipgram count |
| --- | --- | --- | --- | --- | --- | --- |
| greek | 0 | 0 | 0 | 0 | 0 | 0 |
| hebrew | 0 | 0 | 0 | 0 | 0 | 0 |

## Tokenization and sensitivity

| measure | count |
| --- | --- |
| hebrew_multi_morpheme_words | 145993 |
| greek_elided_tokens | 1223 |
| ketiv_supplement_tokens | 1268 |
| qere_affected_verse_passages | 0 |
| ketiv_affected_verse_passages | 2198 |

| sensitivity | paired verses | token changes | lemma changes |
| --- | --- | --- | --- |
| Hebrew Qere versus Ketiv | 23213 | 1099 | 1099 |
| Greek edition-complete versus critical-core | 7918 | 0 | 0 |

Zero-width and punctuation records remain in provenance but are excluded from visible lexical features. Hebrew morpheme order and word boundaries and Greek elision flags are preserved.

## Namespace and sparse-index feasibility

Raw cross-language lemma serialization overlaps: **0**. Language-prefixed lemma identity collisions: **0** (required: 0). Raw overlap is never treated as lexical equivalence.

| representation | rows | columns | estimated nonzeros | estimated count-CSR bytes |
| --- | --- | --- | --- | --- |
| hb:lemma | 23213 | 8412 | 342576 | 5666928 |
| hb:root | 23213 | 0 | 0 | 185712 |
| gk:lemma | 7943 | 5401 | 109854 | 1821216 |
| gk:root | 7943 | 0 | 0 | 63552 |
| en:gloss | 31156 | 13396 | 539475 | 8880856 |

Count-CSR estimates include float64 values, int64 column indices, and the int64 row pointer. Binary/TF-IDF matrices, vocabulary metadata, and transient retrieval blocks require additional bounded memory.

Audited physical memory: 7,866,327,040 bytes where available. Governed memory ceiling: 6,442,450,944 bytes. Free disk near the database: 28,464,963,584 bytes; configured minimum: 10,737,418,240 bytes. Governed retrieval block: 1,024 passages. Retrieval uses CSR matrices, stable vocabulary order, blockwise products, bounded candidate unions, and no dense all-pairs matrix.

## Benchmark feasibility

| corpus pair | relationships | mapped pairs | queries A | queries B |
| --- | --- | --- | --- | --- |
| gnt_gnt | 84302 | 140519 | 7662 | 7934 |
| hb_gnt_english_bridge | 72724 | 127979 | 18188 | 21794 |
| hb_hb | 184900 | 340102 | 21309 | 22907 |

Endpoint mappings with one target: 598,922; with multiple targets: 87,780; maximum targets: 182.

### Mapping status

| status | count |
| --- | --- |
| excluded_by_profile | 639 |
| mapped_partial | 781 |
| mapped_provisional | 1371984 |
| unresolved_missing_target | 5756 |
| unresolved_reference | 36 |

### OpenBible vote strata

| descriptive vote stratum | relationships |
| --- | --- |
| 1-2 | 128994 |
| 11-25 | 26896 |
| 26+ | 11626 |
| 3-5 | 123092 |
| 6-10 | 50675 |
| negative | 1239 |
| zero | 2277 |

### Governed split assignments

| strategy | partition | count |
| --- | --- | --- |
| held_out_book | development | 137 |
| held_out_book | excluded | 306941 |
| held_out_book | test | 34859 |
| held_out_book | train | 2862 |
| held_out_book_pair | excluded | 338769 |
| held_out_book_pair | train | 6030 |
| held_out_genre | excluded | 304087 |
| held_out_genre | test | 32297 |
| held_out_genre | train | 8415 |
| held_out_relationship_family | excluded | 344799 |
| held_out_source_passage | development | 2375 |
| held_out_source_passage | excluded | 177222 |
| held_out_source_passage | test | 2607 |
| held_out_source_passage | train | 162595 |

OpenBible remains Tier 3 weak supervision; same-label mappings remain provisional and votes are descriptive ranking values, not calibrated confidence.

## Feasibility decision

The verse-level transparent lexical experiment is feasible within the audited machine limits using deterministic sparse, blockwise retrieval. Root evidence is unavailable in the full corpora and must be reported as such. English-gloss cross-testament retrieval is a separately namespaced exploratory bridge requiring complete ablation.
