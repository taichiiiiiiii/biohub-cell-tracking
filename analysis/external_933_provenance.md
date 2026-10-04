# External `.933` provenance and public-graph diagnostic

Updated: 2026-08-30 (Asia/Tokyo)

## 結論

`rishabhr0y/933-biohub-bidir30` の public LB `0.933` は、タイトルからの推測ではなく、Kaggle の公開 API が返す submission と実行 session の結合から**直接検証済み**である。採点された不変な対象は kernel version 2 (`versionId=207794815`)、run / `scriptVersionId=345883663`、submission `55877457` であり、status は `COMPLETE`、score は `0.933` である。latest pull の version 4 は `CANCEL_ACKNOWLEDGED` だが、採点済み version 2 と executable AST が一致するため、latest の status や title を採点根拠に使う必要はない。

また、source が自称する “SINGLE change ... SDW 0.475 -> 0.80; All else identical” は**偽**である。直接採点済みの完全一致親 `.931` と比較すると、動作を変える設定は次の 2 個である。

1. `BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT`: `0.15 -> 0.30`
2. `BIOHUB_SECONDARY_DETECTION_WEIGHT`: `0.475 -> 0.80`

したがって観測された `.931 -> .933` は 2 因子を同時に変えた joint delta `+0.002` であり、SDW 単独にも bidirectional weight 単独にも帰属できない。`+0.002` は gold-loop protocol の public-LB noise floor `0.005` 未満である。

以下で「検証済み」は Kaggle の公開 API / immutable session output / hash で直接確認した事実、「診断」は public 4 dummy videos 上の GT 非因果比較、「推論」はその事実からの再現方針を表す。

## 検証済み: 採点 version と submission の不変な結合

採点対象 URL:

`https://www.kaggle.com/code/rishabhr0y/933-biohub-bidir30?scriptVersionId=345883663`

| Field | Verified value |
|---|---:|
| kernel ID | `132471639` |
| kernel version | `2` |
| kernel version ID | `207794815` |
| version type / pinning | `BATCH` / `PINNED` |
| run ID / `scriptVersionId` | `345883663` |
| run status | `COMPLETE` |
| run created / evaluated | `2026-08-29T16:51:06.987Z` / `2026-08-29T16:51:08.107Z` |
| commit ID / created | `1401799191` / `2026-08-29T16:12:23.864257600Z` |
| accelerator / image digest | NVIDIA Tesla T4 / `37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461` |
| runtime | `2073.385281 s` (34m 33.385s) |
| output | `48,921,897 bytes`, 307 files |
| competition submission ID | `55877457` |
| `submission.sourceScriptVersionId` | `345883663` |
| `submission.scoreFormatted` | `0.933` |
| `bestSubmissionScore.kernelVersionNumber` | `2` |

全 version の公開履歴は次のとおりで、latest title/status は scored version の証拠ではない。

| Version | version ID | run / scriptVersionId | type | status | title |
|---:|---:|---:|---|---|---|
| 1 | `207788573` | `345876397` | BATCH | `ERROR` | `biohub-945_bidir30` |
| **2** | **`207794815`** | **`345883663`** | **BATCH** | **`COMPLETE`** | **`.933_biohub_bidir30`** |
| 3 | `207903189` | `346001262` | BATCH | `CANCEL_ACKNOWLEDGED` | `biohub-945_bidir30` |
| 4 | `207903225` | `346001300` | QUICK | `CANCEL_ACKNOWLEDGED` | `biohub-945_bidir30` |

raw session log も version 2 の実効値を直接記録している。

- preset: `harmonic_v3_division_wide`
- `BIOHUB_SECONDARY_DETECTION_WEIGHT=0.800`
- `BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT=0.3`
- prediction time: 9.02 min; session completion: 2073.385281 s
- public session output: 234,226 data rows
- train validator: enabled, held-out 4; printed `PROXY_SCORE=0.9360`

最後の proxy は notebook 内の診断であり、公式 LB `0.933` の根拠には使わない。

## 検証済み: 取得 API とハッシュ

version 列挙は次の read-only request で取得した。

```text
POST https://www.kaggle.com/api/i/kernels.KernelsService/ListKernelVersions
{"kernelId":132471639}
```

採点 version / submission / score / rendered output の結合は次で取得した。

```text
POST https://www.kaggle.com/api/i/kernels.LegacyKernelsService/GetKernelViewModel
{"authorUserName":"rishabhr0y","kernelSlug":"933-biohub-bidir30","kernelVersionId":345883663,"tab":"script"}
```

raw log は authenticated official Kaggle SDK の
`kernels.KernelsApiService/GetKernelSessionLogsStream(kernel_session_id=345883663)`、全 public-session output の安定した入口は
`https://www.kaggle.com/code/svzip/345883663` である。API response 内の個別 `kaggleusercontent` URL は署名付きで失効し得るため、永続参照には上記 session ID と API body を使う。

scored source hash は、rendered `__results__.html` の 10 個の input code-cell text を実行順に抽出し、UTF-8 の単一 NUL で連結したもの。AST hash は各 cell を `ast.dump(ast.parse(cell), include_attributes=False)` し、同様に NUL 連結したもの。

| Artifact | Bytes / rows | SHA256 |
|---|---:|---|
| scored v2 rendered `__results__.html` | 1,150,031 B | `aa8352d20b70581dce60ee4413c1370605da7595251e35d219ab00c71327abce` |
| scored v2 canonical executed source | 10 cells, 187,331 B including separators | `75714eceb5da6504e2b72af8d5cd69ccbd7fb9beff43f30b90fb40576e397142` |
| scored v2 canonical AST | 10 cells | `0d1809e9e71ec410664ade0204b1a17896dc95954a721ea0bc46773f6fbb221d` |
| scored v2 raw log | 111,736 B, 624 events | `aeac1e8560e0ca9f4ff61c401bd10d542113a2b1769eeee0a0a65f185c790746` |
| scored v2 public-session `submission.csv` | 12,190,215 B; 234,227 lines incl. header | `20f36f69106b8f2781218cda7cf42188698a90703b2f4e04371d0769a43c1d9a` |
| latest v4 official pull `.ipynb` | 207,167 B | `c7cdda0acf9dc704865165feae06d933fc85748dd4d8e9454734b91a65f0eb10` |

latest v4 pull は scored v2 と canonical AST SHA が完全一致する。text 差は scored v2 の先頭 fork comment が v4 で消えたことと、2 cells の末尾 newline だけである。このため v4 source は executable-semantic reproduction source として使えるが、v4 run 自体は cancelled であり、v4 file SHA を scored v2 の raw notebook SHA と呼んではならない。

公開 session `submission.csv` は 4 public/dummy videos の出力であり、hidden evaluation prediction file ではない。Kaggle は後者の bytes を公開しない。したがって上の CSV SHA は public graph parity gate 用であり、LB score file の SHA ではない。

再取得可能な ignored bundle は `outputs/kaggle/external_933_reference/` にあり、全 filename / byte size / SHA / immutable ID / retrieval method は `ARTIFACT_MANIFEST.json` に記録した。tracked provenance はこの文書だけである。

## 検証済み: 直接採点済み `.931` 親と正確な semantic diff

コード先頭が明示する fork 元は
`stephennedumpally/pls-upvote-share-higher-scoring-ideas` であり、これは exact causal parent として使える。

親 URL:

`https://www.kaggle.com/code/stephennedumpally/pls-upvote-share-higher-scoring-ideas?scriptVersionId=344481175`

| Field | Verified value |
|---|---:|
| kernel ID / version | `131761963` / v1 |
| version ID | `206467176` |
| run / `scriptVersionId` | `344481175` |
| status / runtime | `COMPLETE` / `1909.2848685 s` |
| created / evaluated | `2026-08-24T01:03:33.680Z` / `2026-08-24T01:03:36.200Z` |
| submission / score | `55729735` / `0.931` |
| `sourceScriptVersionId` | `344481175` |
| rendered source SHA | `effd76c9b099acb6591919056e93c6cc30725833bec5f8390f62f91166069a28` |
| canonical AST SHA | `8975898b683042861ca0d80cde9080c290ebac54ae79d42fe4ca74b5c78ecbb2` |
| public-session CSV | 12,367,560 B; 237,612 lines; SHA `e7ee404d499a06aaa5bd5a3f62f291687743685ea5154391487e476dff0e4905` |

10 cells の exact rendered input diff は次の 2 behavioral controls と、それに追随する guard/comment だけである。他の executable cell content は同一である。

```diff
-os.environ["BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT"] = "0.15"
+os.environ["BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT"] = "0.30"

-    "BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT": 0.15,
+    "BIOHUB_BIDIRECTIONAL_EDGE_WEIGHT": 0.30,

-os.environ["BIOHUB_SECONDARY_DETECTION_WEIGHT"] = "0.475"
+os.environ["BIOHUB_SECONDARY_DETECTION_WEIGHT"] = "0.80"

-    _bidirectional_weight_guard, 0.15, ...
+    _bidirectional_weight_guard, 0.30, ...
-        "expected_bidirectional_weight": 0.15,
+        "expected_bidirectional_weight": 0.30,
```

加えて child が次の comment を追加しているが、上の bidirectional 変更と矛盾する。

```text
# SINGLE change vs that fork: BIOHUB_SECONDARY_DETECTION_WEIGHT 0.475 -> 0.80 ...
# ... All else identical.
```

従って single-change comment は**明確に false**である。guard 数値の変更は bidirectional control の整合性 assertion であり、第三の behavioral lever ではない。

比較として `evgendvorkin/biohub-0-931-lb` の最良採点 version は v17 (`versionId=207759531`, `scriptVersionId=345856539`, `COMPLETE`, 2000.437325 s)、submission `55869000`, score `0.931` である。
URL は `https://www.kaggle.com/code/evgendvorkin/biohub-0-931-lb?scriptVersionId=345856539`、canonical source SHA は `9ea2afcc438cae6d3b183276022d11561c9263a9ba3ee3629fd1c19cc69d915a`。latest v18 は title が `0.931` でも submission `55869893` の実 score は `0.930` であり、title 非証拠性を再確認できる。ただし Evgen v17 は safe-div 等に実質差があるため、`.933` の因果親には使わない。

## 診断のみ: `.931` parent -> `.933` child の public graph 差

これは 4 public/dummy videos 上の in-sample comparison であり、GT causal attribution でも hidden-test generalization evidence でもない。raw node ID は detection の追加・削除後に変化し得るので直接比較せず、dataset と `t` を固定し、voxel scale `(z,y,x)=(1.625,0.40625,0.40625) um`、7 um gate の minimum-distance Hungarian matching で 1:1 node map を作った。edge Jaccard は両端 node が match した directed edge に限定した topology-only conditional 値である。

### Per-dataset graph size

各 cell は `parent -> child (delta)`。rows は header を除く node + edge rows。

| Dataset | Rows | Nodes | Edges | Fork sources |
|---|---:|---:|---:|---:|
| `44b6_0113de3b` | 50,185 -> 50,227 (+42) | 25,444 -> 25,459 (+15) | 24,741 -> 24,768 (+27) | 68 -> 81 (+13) |
| `44b6_0b24845f` | 37,439 -> 35,444 (-1,995) | 19,312 -> 18,304 (-1,008) | 18,127 -> 17,140 (-987) | 73 -> 65 (-8) |
| `6bba_05b6850b` | 11,985 -> 11,870 (-115) | 6,089 -> 6,035 (-54) | 5,896 -> 5,835 (-61) | 8 -> 8 (0) |
| `6bba_05db0fb1` | 138,002 -> 136,685 (-1,317) | 70,002 -> 69,352 (-650) | 68,000 -> 67,333 (-667) | 171 -> 153 (-18) |
| **Total** | **237,611 -> 234,226 (-3,385)** | **120,847 -> 119,150 (-1,697)** | **116,764 -> 115,076 (-1,688)** | **320 -> 307 (-13)** |

### Spatially matched overlap and topology

`old-only/new-only` は match 済み両端上の directed edge 差。fork J は match 済み fork source set の Jaccard。

| Dataset | Matched nodes | Node J | Exact / moved | distance p90 | Conditional edge J | old-only / new-only | Fork-source J |
|---|---:|---:|---:|---:|---:|---:|---:|
| `44b6_0113de3b` | 25,278 | 0.9865 | 21,373 / 3,905 | 0.406 um | 0.9941 | 66 / 79 | 0.4949 |
| `44b6_0b24845f` | 17,248 | 0.8468 | 12,336 / 4,912 | 1.675 um | 0.9804 | 156 / 162 | 0.3958 |
| `6bba_05b6850b` | 5,905 | 0.9495 | 4,225 / 1,680 | 1.625 um | 0.9956 | 14 / 11 | 0.2308 |
| `6bba_05db0fb1` | 68,119 | 0.9563 | 50,561 / 17,558 | 1.625 um | 0.9727 | 889 / 936 | 0.3376 |
| **Total** | **116,550** | **0.9441** | **88,495 / 28,055** | **1.625 um** | **0.9796** | **1,125 / 1,188** | **170 / 445 = 0.3820** |

parent 4,297 nodes と child 2,600 nodes が unmatched で、unmatched node に触れる edge は parent 4,597、child 2,846。これに対し、両端が対応した上での topology-only edge churn は 1,125 + 1,188 である。従って bulk の出力差は主に detection/retention と座標変化に現れている。一方、ordinary conditional edge J は 0.9796 と高いのに fork-source J は 0.3820 と低く、division-like topology は大きく入れ替わっている。これは SDW と bidirectional の 2 lever がそれぞれ detection と topology に作用した mixed signature と整合するが、score gain の因果分解ではない。

### Official scorer on local public-four dummy GT

repository の official metric path で同じ 2 CSV を local public-four dummy GT に対して採点した in-sample diagnostic は次のとおり。public test は dummy/in-sample なので一般化性能とは呼ばない。

| Dataset | Parent adj edge J | Child adj edge J | Delta | Parent TP/FP/FN -> child | Division FP parent -> child |
|---|---:|---:|---:|---|---:|
| `44b6_0113de3b` | 0.904938 | 0.868922 | -0.036016 | 47/2/3 -> 46/3/4 | 0 -> 0 |
| `44b6_0b24845f` | 0.961027 | 0.925977 | -0.035051 | 48/3/1 -> 47/4/2 | 2 -> 2 |
| `6bba_05b6850b` | 0.972798 | 0.958767 | -0.014031 | 834/16/11 -> 827/22/18 | 1 -> 2 |
| `6bba_05db0fb1` | 0.839574 | 0.852741 | +0.013167 | 1101/128/82 -> 1107/116/76 | 3 -> 4 |

aggregate official diagnostic は `0.8942400393 -> 0.8952864612`、delta `+0.0010464219`。hidden LB の方向 `+0.002` と同じだが、4 datasets 中 3 つは悪化し、division Jaccard は両方 0、division FP は 6 -> 8 である。したがってこの public-four 結果は adoption gate ではなく、効果の不均一性を示す診断に留める。

## 診断のみ: E23 reference -> scored `.933` public graph

E23 は `.933` parent と違って多数の knobs が異なるため因果比較ではない。gold-loop の reproduction anchor として、同じ matching を `outputs/kaggle/e23_reference/submission.csv` に適用した。

| Dataset | Rows E23 -> .933 | Nodes | Edges | Forks | Node J | Conditional edge J |
|---|---:|---:|---:|---:|---:|---:|
| `44b6_0113de3b` | 50,253 -> 50,227 | 25,485 -> 25,459 | 24,768 -> 24,768 | 57 -> 81 | 0.9798 | 0.9877 |
| `44b6_0b24845f` | 38,558 -> 35,444 | 19,905 -> 18,304 | 18,653 -> 17,140 | 77 -> 65 | 0.8102 | 0.9742 |
| `6bba_05b6850b` | 12,085 -> 11,870 | 6,142 -> 6,035 | 5,943 -> 5,835 | 11 -> 8 | 0.9341 | 0.9935 |
| `6bba_05db0fb1` | 139,230 -> 136,685 | 70,675 -> 69,352 | 68,555 -> 67,333 | 118 -> 153 | 0.9499 | 0.9622 |
| **Total** | **240,126 -> 234,226** | **122,207 -> 119,150** | **117,919 -> 115,076** | **263 -> 307** | **0.9316** | **0.9710** |

E23 に対して `.933` は nodes -3,057、edges -2,843、forks +44。116,408 nodes を match できたが、exact coordinates は 32,327、moved は 84,081、conditional old-only/new-only edges は 1,501/1,789 だった。この差は parent comparison より広く、`E23 0.924 -> external 0.933` の `+0.009` を特定 lever に帰属させる根拠にはならない。

## API gap と最小安全 reproduction plan

### 検証済み API gap

- 他 user の versioned `kernels pull owner/slug/2` と internal `GetKernelVersion` は 403 で、Kaggle raw historical `.ipynb` bytes は取得不能。
- ただし scored session の rendered output は exact executed code-cell input を全て含む。10 cells の text と実行順は復元済み。
- latest v4 official pull は scored v2 と AST-identical なので、再実行 source の executable semantics は固定できる。
- competitor submission の hidden evaluation file は非公開。公開 API が直接与える `submission.id`, `sourceScriptVersionId`, score の結合は検証済みだが、hidden output SHA は得られない。

### 推論: reproduction implications

1. まず ignored bundle の manifest と SHA を検証し、scored v2 reconstructed cells または AST-identical v4 pull を source anchor にする。raw historical notebook と誤称しない。
2. v2 commit の data sources を不変に pin する。
   - competition: `sourceId=136605`, `databundleVersionId=18327164`
   - DeepCenter: `sourceId=17751825`, `datasetId=11061989`
   - secondary seed: `sourceId=18187037`, `datasetId=11184174`
   - support pack: `sourceId=17804310`, `datasetId=10999845`
3. 最初の replay は 2 knobs を含む `.933` bundle 全体の portability/runtime anchor とし、SDW 単独の勝利とは呼ばない。public-four graph は node/rounded coordinate/directed edge/fork と CSV SHA を照合する。
4. train validator は score-irrelevant だが scored v2 では enabled。validator を外す場合は、その前後で public-session graph/SHA equivalence を証明してから runtime-only change として扱う。
5. `0.933` の真偽確認のためだけに新しい LB query を使う必要はない。score mapping は直接検証済み。将来の account-level replay は portability と hidden runtime を確認する実験であり、claim verification ではない。
6. 2 因子を分離するなら、bidir を `0.30` に固定して SDW `0.475 vs 0.80` を local parity artifact 上で比較するか、完全な `2 x 2` を事前登録する。ただし既存 bidir audit を重複させず、`+0.002` は noise floor 未満なので、この provenance だけを理由に単独 LB probe を承認しない。

最終 verdict は「external `.933` は直接 verified、source semantics は再現可能、hidden output file だけが API gap」である。一方、その `.002` delta の原因は未同定であり、gold queue 上では exact reproduction anchor のまま扱い、次の causal engineering は既定どおり steal/twin、次いで ranker を優先する。
