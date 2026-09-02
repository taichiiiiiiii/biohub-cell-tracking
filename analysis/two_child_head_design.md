# Frozen-encoder explicit two-child head 設計契約

Updated: 2026-09-02 (Asia/Tokyo)

Status: **DESIGN_ONLY / HOLD_ARTIFACTS_AND_REMAINING_TRAIN**

## 1. 結論と仮説

最初に検証する学習候補は incremental candidate
`two_child_head_incremental_v1` だけとする。既存の primary
`UNetNodeTransformer` の encoder を完全凍結し、時刻 `t` の親候補 `P` と
`t+1` の異なる二娘候補 `A,B` のノード特徴、物理幾何、既存 association/detection
信号から、「`P` が `A,B` の共通親である」tuple logit を出す小型・娘交換不変 head
を学習する。

検証する因果仮説は次である。

> 1-to-1 association 用 head が第二娘へ確率質量を割けない場合でも、凍結済み
> encoder 表現には division を識別する情報が残っており、二娘を同時に見る
> permutation-invariant head は、full-stack outer-excluded評価で幾何だけより高いprecisionで真の
> `(P,{A,B})` を順位付けできる。

本候補は現行 `twin_only_v1` をそのまま置換しない。最初の production 接続は、
ST-R2 の structural eligibility、DeepCenter veto、transactional `Q->B` removal /
`P->B` additionの固有core不変量、frame/video cap を固定し、その **eligible tuple の gate と
cap 内 ranking だけ**を head score に置く別 profile
`e23_two_child_twin_gate_v1` とする。一般 orphan adoption、donor 条件緩和、synthetic
node、safe-division 半径変更、encoder fine-tune は別仮説であり v1 に混ぜない。
本候補単体の学習済み採用gateはcombined `+0.003`であり、gold gap `+0.023`
全体を所有するとは主張しない。portfolio計上はsection 9に固定する。

公式採否軸は常に
`adjusted_edge_jaccard + 0.1 * division_jaccard` である。分類 AUC/AP、loss、
calibration は前段 gate であって公式 graph metric の代用ではない。疎な GT のため、
未対応 prediction を false positive / negative label とみなさない。

## 2. 今回のローカル監査と現時点の HOLD

監査開始時の branch は `design/two-child-head`、基点 commit は
`0cff37903d8ed0c21523f061a1aa8e649682ebfa`、working tree は clean だった。
ネットワーク、Kaggle、eval36 GT は使用していない。

### 2.1 実在する関連コード

- `notebooks/pub923_repro/pub923_repro.ipynb` の pinned inference patch は
  `model.encode(imgs)` から `unet_out, det_logits` を受け、
  `model._index_features(unet_out[:, f_idx], p_coords, p_mask)` を primary / secondary
  両方で呼び、その特徴を `predict_edges` に渡している。従って、encoder の dense
  feature map からノード特徴を採る **既存の実行経路は存在する**。
- 同 notebook が pin する support source manifest は SHA-256
  `978b626d1fd1e7397435a437dfe68691defe1572fc3c20e61012d7c9b52ed029`。
  特に upstream `temporal_unet.py` は
  `d809c35d42f504161074ddeaaa7aee5b407e5bca7f9b4e1d5f9b2ff345666cac`、
  `simple_node_transformer.py` は
  `b97209edeb03840e80d903e3e2a8c81c520641c8ef343f6ca2904d0f80db064e`、
  `predict_unet_transformer.py` は
  `c44e771ba5980b820f93091e03a303c25dfe8f3232e501f54dc9565731c234b9`、
  `train_unet_transformer.py` は
  `c4f6317736bb3bb1ec8f3f6e9a6d935a463e3f0f1f685481b2d13218d35dc9ea`
  と宣言されている。
- frozen primary checkpoint の既知 SHA-256 は
  `12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771`
  (legacy epoch 400)、secondary は
  `9bac2fa0dadc4a6fc1899e0caf187f4b553e0a7cd90ba1261a68b35ffe9e305f`
  (legacy epoch 400) である。legacy診断は前者一個、promotionは同じprimary architectureの
  outer-excluded checkpointをfoldごとに一個使い、secondary featureは混ぜない。
- 既存 tiny patch CNN は raw `(t,t+1)` patch を二 channel 入力にし、
  4-fold video-grouped CV を行うが、parent-centered binary classification であり、
  二娘 relation を陽に入力しない。既存 division-window fine-tune は全モデルを
  warm-start し、T4 x2 / batch 8 で 3.3 s/iter、約 2.3 h/full epoch と記録されている。
  これは head-only 学習ではなく、runtime の上限参考にのみ使う。
- `analysis/training_loss_gate.md` は新規学習に binding である。CV fold stream、
  OOF、final refit、best/last/resume、component-wise numerator/denominator、pre-clip
  gradient norm、hash、strict warm-start、validation selector を本設計にも全適用する。
- 現在の `src/biohub/public_postproc/` には ST-R2 transactional mutator と production
  hook が land 済みで、safe division 後・division geometry / prune 前に
  `apply_twin_only_v1_plan` が動く。ただしこのAPIはlegacy `TwinPlan` order/validatorと不可分で、
  learned rankingにはsection 10の別type/validator/mutatorが必要である。

linked worktree の ignored directory は共有されないため、main project
`/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking` も read-only 監査した。
そこでは `official` が上記 gitlink で初期化済みかつ clean であり、次の実 bytes を確認した。

- `official/src/tracking_cellmot/models/temporal_unet.py` と
  `simple_node_transformer.py` はそれぞれ上記 support-pack 宣言 hash と完全一致する。
- `official/scripts/predict_unet_transformer.py` の実 hash は
  `0c0f82844fa212d783bcb942a46d5b5a6cbe30a41ff08f38d22774cf0b47ff26`、
  `train_unet_transformer.py` は
  `83e3f30a3313ea452b5072b118bfd06539302cf6886e317c542a602deb27d281` で、notebook が
  宣言する materialized support-pack script hash とは異なる。model source の一致を
  support-pack 全体の存在証明に拡張しない。
- 読み取った upstream source では default `unet_out_channels=32`、`encode` 出力は
  `(B,W,C,*spatial)`、`_index_features` は node voxel 座標を integer 化・clamp して
  `(B,N,C)` を返す。predictor は stride `W-1` で各 consecutive pair を一度だけ処理し、
  tuple `(P,A,B)` に必要な `P` source feature と `A,B` target feature は同じ pair windowから
  取得可能である。これは feature-tap API の source-level 実証である。
- DeepCenter `best.pt` の実 bytes が存在し、実測 SHA-256 は
  `8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0` と pin に一致した。

### 2.2 実 artifact inventory と不足

linked worktree 自体には `.pt/.pth/.ckpt/.npy/.npz/.csv/.parquet/.geff` の
raw/model/feature artifact がなく、ignored `data/`, `outputs/`, `work/` もない。main project
側には `data` 11,929,690,112 bytes、`outputs` 191,729,664 bytes が実在したが、read-only
top-level inventory（GEFF/Zarr の内部 array を開かない）では次の状態だった。

- `data/train` は GT GEFF directory 41 本、image Zarr directory 36 本だけで、Zarr は
  `44b6/6bba = 18/18`。stemだけのset照合ではpaired 36本、GEFF-only 5本、Zarr-only 0本である。
  全 train inventoryでも remaining-train の complete paired corpusでもない。
  この監査では GEFF node/edge/GT metadata、Zarr array/attribute を読んでいない。
- `outputs` にある raw GEFF は合計40 roots（public-four 4 + sealed evaluation 36）で、
  remaining-train raw prediction bundle はない。これはpath/root inventoryだけの確認で、sealed
  GEFF/GTやpublic/sealed submission/stats/score CSVは本設計の入力として読んでいない。
- 上記 DeepCenter checkpoint/manifest はある（checkpoint 37,876,911 bytes、manifest SHA
  `1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911`）が、primary
  `12f...`、secondary `9bac...` の checkpoint bytes は見つからない。
- materialized support-pack tree / wheels はなく、main `official` の model sourceだけが二file hashで
  一致する。manifest-declared support-pack pathはKaggle runtimeの `/kaggle/input/...` で、local
  実体ではない。
- two-child/node encoder feature、embedding、tuple dataset/cache はない。

従って remaining-train Zarr+GT、その baseline raw graphs、frozen feature cacheは現地に存在せず、
学習 dataset を構築できない。存在が文書化されている hash と、今回実 bytesをhashした artifactを
混同しない。

未検証の核心は次である。

- support-pack の全実 Python bytes/wheelsと、primary checkpoint configにおける feature channel、
  dtype、strict load（main official sourceのdefault/APIだけは確認済み）;
- primary / secondary checkpoint bytes と strict load;
- remaining-train image Zarr、GT GEFF、baseline raw GEFF、pair-context feature cache;
- raw GEFF node ID と feature tap 時点の candidate ID の exact 対応;
- head の実 runtime、RSS/VRAM、feature-cache disk 使用量。

`official` は gitlink
`075fc5f5a52d11077f9dc2b074644618f26939e2` だが、この worktree では未初期化
(`git submodule status` の先頭が `-`) であり、公式 scorer の実 bytes/test は今回
再検証できない。`official/` は引き続き read-only とする。

従って frozen feature tap は **SOURCE_API_VERIFIED / RUNTIME_BYTES_UNVERIFIED**、学習開始は
**HOLD_ARTIFACTS_AND_REMAINING_TRAIN** である。コードを推測して実装したり、別 checkpoint
や sealed evaluation data で穴埋めしない。

### 2.3 Upstream provenance blocker と promotion grade

既知primary epoch-400 checkpointと既存raw predictionsには、学習stem manifest、split、各stemを
除外したOOF checkpoint/featureの実artifactがない。primary encoder/detector/association stackが
全199 train videosを見た可能性を排除できない。このcheckpointからremaining videoのraw graphや
featureを作り、headだけをvideo-grouped CVしても、validation videoはupstream stackに対して
未接触とはいえない。

従ってこのlegacy stack上の結果は状態を
`DIAGNOSTIC_ONLY_LEGACY_UPSTREAM_EXPOSURE_UNKNOWN` に固定する。「video-out」、OOF generalization、
promotion-ready、held-out改善と呼ばず、G4 promotionやsealed evaluation entryに使わない。

promotion gradeには、固定outer foldごとに次のfull-stack artifactを要求する。

1. `upstream_outer_k` checkpointはouter-val全stemとそのGT/画像/patch/cache/gradientを一度も見ず、
   outer-trainだけ（またはcompetition trainを含まないhash-pinned external pretrain）から作る;
2. outer-val raw GEFF、pair-context features、association/detection signalsはそのcheckpointだけで生成;
3. checkpoint training-stem manifest、input/code/config/seed/history/hash、open-file receiptが exclusionを
   証明し、単なるfilename宣言でなくloader実績と一致する;
4. outer-train用head featuresも同じ `upstream_outer_k` distributionから作る;
5. final upstream checkpointはremaining-trainだけから新規作成し、sealed evaluationを完全除外する。
   legacy all-train checkpointのwarm startは、warm-start自身がouter/sealed stemを見ていれば不可。

許容する取得路は、上記5 outer-excluded checkpoint/raw/feature bundleをprovenance付きで取得するか、
同じsplitでupstream stackを再学習することだけである。後者は既知約900 GPU-hour/full 400-epoch
規模から現quotaでは非現実的なので、budget gateを通らなければHOLDする。full-stack exclusionが
証明できない限り、以下のnested CVは実装健全性のdiagnosticに留まる。

## 3. Tuple と feature の厳密な意味

### 3.1 Tuple identity

一 example は次の canonical identity を持つ。

```text
example_id = sha256(
  schema_version || dataset || P || min(A,B) || max(A,B) || feature_manifest_sha256
)
tuple = (P, A, B), where A < B
t(A) = t(B) = t(P) + 1
P, A, B are distinct observed (non-synthetic) raw-node IDs
```

`A,B` に左右・既存子/候補子の意味を持たせない。label、model、serialization、score は
`(P,A,B)` と `(P,B,A)` で bitwise 同一でなければならない。ST-R2 へ接続するときだけ、
planner が既存 edge `P->A` と donor edge `Q->B` を mutation role として割り当てる。
head 自体には `Q` を渡さず、「donor を切って安全か」という別問題を学習させない。

物理座標は `(z,y,x)=(1.625,0.40625,0.40625) um/voxel` を明示して変換する。
全 edge/candidate は `t -> t+1` のみ。座標、feature、logit の非 finite は example reject
ではなく artifact validation failure とする。

### 3.2 Candidate universe

二つの universe を混同しない。

`label_recall_envelope_v1` は学習例を集め、encoder に division signal があるかを測るための
広い label universe である。これは deployment candidate 数、runtime、R2 feasibility の根拠に
してはならない。

1. 各 observed parent `P` について `t+1` の observed node を物理半径 `12.0 um` で検索。
2. `(distance,node_id)` で sort し、最大 `K=8` を保持する。8 番目と 9 番目が同距離
   `1e-9 um` 以内なら、その `P` は cap ambiguity として全 tuple を ignore し、ID tie-break
   で任意の娘を落とさない。
3. 保持した node の全 unordered pair を列挙し、`A<B` に canonicalize する。
4. sister distance `<=15.0 um` のみ feature 化する。これは label を見ず固定する recall
   envelope で、現行 twin structural 上限より広い。

`deployment_universe_v1` は、同じ post-safe-division graph、同じ frozen configで現行
`plan_twin_only_v1` の structural eligibilityとDeepCenter vetoを通過し、conflict/frame-cap/video-capを
かける前のimmutable recordとして列挙するexact ST-R2 eligible tupleだけである。resolved
planはその部分集合として別hash/countを持つ。OOF official graph、candidate arm、
runtime/RSS、約200動画外挿はこの universe だけを使う。現行の parent `<=8 um`、sister
`5.5..11 um`、two-successor、non-synthetic、donor条件を広げない。head は exact eligible setを
threshold gateし、同じcap内でrankするだけである。

Phase 2 dataset auditで、remaining-train の全 GT-positive fork が label envelope に入る recall を測る。
label-envelope recall `<0.95`、lineage 別 `<0.90`、または cap ambiguity に positive が
一件でも落ちるなら `K/radius` を結果を見て変更せず v1 を NO-GO とする。拡張は新 version
で再登録する。別に、OOF各videoでST-R2が列挙した全deployment tupleについて
`P,A,B`のpair-context feature coverageを **100%** 要求し、tuple set/order/hashをplanner artifact
と照合する。sidecar、node ID、時刻、raw coordinate、feature schema/hashのmissing/mismatchが
一件でもあればcandidate arm全体を開始前または実行中にfailし、部分CSV/metricを採用しない。

意図的なfallbackは独立した `baseline` profileだけに存在する。baselineはhead master offで、
head checkpoint/sidecarをopenせず exact E23を実行する。candidate profile内のvideo単位silent
fallback、missing tupleを単なるreject扱い、data依存のbaseline切替は禁止する。

### 3.3 Frozen feature sidecar

encoder はactive primary-family checkpoint（legacy診断ではexact `12f...`、promotionでは該当
`upstream_outer_k`）一個だけを `eval()`、全 parameter
`requires_grad_(False)`、`torch.inference_mode()` で実行する。BatchNorm running state、
dropout、checkpoint bytes を一切変えない。active full checkpoint を
`submodule_strict` と称して部分 load せず、既存 model class へ全 key/shape/dtype strict load
したあと encoder output を tap する。

per-video sidecar は pickle でなく、schema-versioned NPZ/Zarr と canonical JSON manifest
を用いる。featureは「nodeに一個」ではなく consecutive pair contextに束縛する。upstream predictor
では同じnodeが前pairのtargetと次pairのsourceになり得て、そのencoder windowが異なるからである。
tuple `t:P -> t+1:{A,B}` は必ず同じ一回の `(t,t+1)` pair forwardから `P` source featureと
`A,B` target featureを取る。異なるwindow/roleのfeature平均は禁止する。

sidecarは少なくとも次を持つ。

```text
dataset, pair_t, window_start, source_node_id[], target_node_id[],
source/target raw_zyx_voxel and raw_zyx_um,
source/target encoder_feature (float16 storage; float32 census receipt),
source/target detection_logit (float32), pair_occurrence_count (=1),
feature_dim, feature_dtype, feature_stride, tap_symbol,
raw_geff_sha256, image_inventory_sha256, checkpoint_sha256,
support_source_manifest_sha256, extraction_code_sha256
```

upstream sourceは各consecutive pairを一度だけ処理すると明記する。Phase 0は実primary configの
`window_size/stride`、全pairの `pair_occurrence_count==1`、raw GEFF global node index/idとのbijection、
source/target frame一致を実 bytesで再確認する。一件でも重複/欠落なら平均・先勝ちで修復せず
schema設計へ戻る。documented default `feature_dim=32` もcheckpoint config/実tensor shapeで再bindする。

feature extraction は raw prediction と同じ forward pass に同居させる。postprocess で encoder
を再実行しない。これにより head-only candidate のために primary checkpoint を現行 ST-R3
postprocess armへ新たに mount することを避ける。

### 3.4 三つの座標stageを混ぜない

同じnode IDに三種類の座標を持ち、schema fieldを省略しない。

- `tap_zyx_voxel`: downsample済みdetector座標で `_index_features` がinteger/clampして読む位置。
  featureとdetection logitのprovenance専用で、物理geometryやGT matchingに使わない。
- `planner_zyx_um`: E23 all-node centroid refinement後、safe division後、twin planner直前の物理座標。
  label envelope/deployment candidate列挙、headのdistance/vector/midpoint feature、remaining-GTへの
  direct label assignmentはこれだけを使う。
- `final_zyx_voxel/um`: twin mutation、prune/short-track、linefit後、CSV丸め前後の座標。
  official edge/division scoringと最終graph deltaだけに使い、head inputへ逆流させない。

sidecarは `tap_zyx`、planner artifactは `planner_zyx`、arm receiptはlinefit前後とCSV丸め後の
`final_zyx` hashを持つ。node IDごとに各stageの座標と変換scaleをjoinし、stage名のない `z,y,x`
fieldを禁止する。label builderがplanner座標以外を受けたらfailし、official scorer inputはfinal
CSV/graph以外を拒否する。

## 4. Label contract と sparse-GT 防御

予測 node の `planner_zyx_um` とGT nodeは物理7 um gateでone-to-one assignmentするが、単一frame
matchingだけでlabelを確定しない。公式division scorerは各GT forkについて
`grandparent -> divider -> children -> grandchildren` の局所windowを独立rematchし、pred forkの
predecessorもparent-side、pred branchのsuccessorもdaughter-side evidenceにできる。従って一frame
ずれやlocal rematchingで公式TPになり得るtupleを安易なnegativeにしない。

各endpoint mappingは次の全contextで同一でなければならない。

1. full-graph distance matching;
2. tuple時刻と交差し、endpointのいずれかが7 um内にある全GT division local window;
3. GT divider時刻 `t-1,t,t+1` のparent/child/grandchild role context;
4. section 4のversioned envelope/deployment counterfactual pairを公式 `score_divisions` へ渡した
   baseline/CF local candidate context。

各context/roleでchosen distance `<=7 um`、pred->GTとGT->predの相互best、second-best minus best
`>=1.0 um` を要求する。second candidateがない場合はmarginを`+inf`と記録する。mapping、role、
nearest/second distance、marginが一contextでも変わる、またはrelevant context列挙が空/不完全なら
ignoreとする。matching source/gitlink/hashと公式window enumerator hashをmanifestにpinし、公式
codeは変更しない。labelは三値 `positive / certified_negative / ignore` で、unmatchedを負例にしない。

### Counterfactual edit と causal attribution

label envelopeとdeployment recordは必要なedge editが異なるため、一つの汎用functionで
済ませない。将来 `src/biohub/two_child_counterfactuals.py` に次を実装する。入力はどちらも
`planner_zyx_um` 時点の同一immutable graph snapshotで、戻り値は baseline/edit の両方、
ordered edit list、pre/post graph SHA、validity receiptを持つ `CounterfactualPairV1` とする。

```text
make_label_envelope_counterfactual_v1(snapshot, P, A, B, downstream_spec)
make_deployment_counterfactual_v1(snapshot, records: tuple[TwinEligibleRecordV1, ...], downstream_spec)
score_counterfactual_pair_v1(pair, remaining_gt, scorer_spec)
```

`make_label_envelope_counterfactual_v1` は `P,A,B` がdistinct/non-synthetic、
`t(A)=t(B)=t(P)+1` であることを確認する。CF側では次の順序だけを行う。

1. `A` または `B` への入edge `(R,C)` で `R!=P` を `(source_id,target_id)` 順にremove;
2. `P` の出edge `(P,C)` で `C not in {A,B}` をtarget ID順にremove;
3. 存在しない `P->A`、`P->B` をこの順にadd。

これが envelope CF のindegree/outdegree validity restorationの全体であり、他edge/node/座標の
修復はしない。edit後に dangling/duplicate/nonconsecutive edge、indegree `>1`、outdegree `>2`
が残る、または同じordered editで再現できなければCF invalidとしてlabelをignoreする。

`make_deployment_counterfactual_v1` は明示的にorderedなrecordsを受け、label用は長1、oracle用は
長0--2とする。長2は六roleが互いにdisjoint、frame cap 1、video cap 2を満たす。
各exact recordの `P,Q,A,B,A2,B2` が六つの異なる
non-synthetic node、`P->A,Q->B,A->A2,B->B2` が存在、`P->B` が非存在、
`Q` indegree 0/outdegree 1、`P` indegree 1/outdegree 1、recordのmetadata tokenが `Q->B`
実edgeと一致することを検証する。CF editは各recordをresolver順に
**exactly** `remove(Q->B)` の後 `add(P->B)` とするだけで、全selectionを一回のatomic
transactionとする。削除metadataと追加 `distance_um/edge_prob=None` をreceiptに保存する。
他のvalidity restorationを必要とするrecordはstructural bugとしてarm failureにする。

両functionともbaselineは入力snapshotを無editでcopyし、baselineとCFを同一の
division geometry、isolated/short-track prune、linefit、CSV rounding順に通す。各stageのcode/config/input/output
SHA、node/edge count、`final_zyx` SHAを保存し、片腕だけのdownstream実行を禁止する。
`score_counterfactual_pair_v1` は同じofficial gitlink/scorer configで両graphをscoreし、
baseline/CFごとのnode matching、division-window candidate/pairing、GT event ID、raw TP/FP/FN、
adjusted-edge countsとscorer code/config/GT inventory SHAをmatching receiptに保存する。

`official_window_recoverable=true` は、対象GT fork `g`がbaseline TP setにおらずCF TP setに新規に
入り、`new_tp_events={g}` かつ `lost_tp_events={}`、さらに `g` の公式pairingが追加edge
の少なくとも1本を使う場合だけである。baselineが既に `g` をTPにする
`preexisting_fork_attribution`、無関係のTP交換、matching receipt不完全はpositive/negativeの
どちらにも使わずignoreとする。このcausal flagとdirect-fork labelを混合しない。

### Positive

primary supervised positiveを `direct_fork_positive` と呼ぶ。`P,A,B` がそれぞれ異なるGT node
`p,a,b` に上記全contextで一意matchし、GT directed edge が
`p->a` と `p->b` の両方を持ち、`outdegree_GT(p)=2` のときだけ positive とする。
娘順は無視する。同一 GT fork から複数 predicted tuple が positive になる場合は、学習 weight
を `1 / positive_tuples_for_gt_fork` とし、一つの容易な fork が loss を支配しない。

別field `official_window_recoverable` は対応する上記envelope/deployment functionが作る
baseline/CF final graph pairを公式scorerへ通し、そのtupleの
pred forkがGT division TP pairingに寄与した場合だけtrueにする。one-frame shiftやgrandchild fallback
により `direct_fork_positive=false, official_window_recoverable=true` はあり得るが、これをprimary
common-parent labelへ混ぜず診断/negative vetoにだけ使う。label-envelopeの「direct fork recall」と
最終graphの「official division TP/recall」は別field/表/plotにし、相互変換しない。

### Certified negative

`P,A,B` が上記全contextで一意・同一roleへmatchし、`official_window_recoverable=false`、かつ
少なくとも片方の娘対応 node がGT上で別の明示parentを持つ場合だけnegativeとする。具体的には
次のいずれかである。

- `p->a` は真だが `pred_GT(b)=q != p`（one-true-child impostor）;
- `p->b` は真だが `pred_GT(a)=q != p`;
- `pred_GT(a)!=p` かつ `pred_GT(b)!=p` で、両方の predecessor が明示される;
- positive fork の一方を保ち、同 frame の別 parent の明示 child と交換した wrong-sibling tuple。

GT nodeがpredecessorを持たない、prediction/GTのいずれかがunmatched、uniqueness margin未達、
context間mapping/role不一致、counterfactualが別時刻GT divisionを回収し得る、GT local topologyが
malformed、`preexisting_fork_attribution`、またはfalse childの異なるparentを証明できない
tupleはすべてignoreとする。GT
`outdegree=0/1`だけを根拠に「divisionでない」としない。

head labelは追加する `P->B` のcommon-parent妥当性だけを扱い、donor edge `Q->B` removalのedge
損失、安全性、QのGT対応をmodel化しない。従って分類precisionが高くてもpromotionできず、実際の
remove+add、downstream prune/linefit、公式window rematchingを含むG4 full-graph deltaが決定的である。

### Hard-negative sampling

各 outer-train split で positive は全件使用する。certified negatives を次の排他的 stratum に
分け、root/run/fold-derived seed でrun開始前に一度だけ最大 `8 negatives / positive` を
決定的に抽出し、全epochで同じIDを使う。

1. `wrong_sibling_nearest`: 真の片娘 + 最短の別-parent child;
2. `twin_like`: 現行 ST-R2 の structural eligibility を満たすが GT common-parent でない;
3. `association_confident`: false branch の frozen association signal が stratum 内上位;
4. `geometry_matched`: positive の parent-child / sister distance bin と一致;
5. `background_certified`: 残りから video/frame 均衡抽出。

同じ tuple を重複採用しない。各 stratum の universe size、sample size、inclusion probability、
seed、ID hash を保存する。学習だけがこのsampleを使い、validation/OOFは全certified
universeを使う。極端な学習weightの最大/中央値 ratio `>100` なら sampling
設計不良として停止する。validation/OOF の分類 readout は sampling せず全
`label_recall_envelope_v1` を scoreし、supervised AP/loss は positive + certified negative のみ。
official graph readoutはその中のexact `deployment_universe_v1` tupleだけを使う。

### 4.1 Literal weight / denominator contract

logitを見る前に `example_weight_v1.parquet` を作り、各
`(run_id, usage=train|probe|eval, example_id)` の次の値を
IEEE-754 `float64.hex()` とそのcanonical manifest SHAでfreezeする。後からclass balanceを
正規化したり、batch/fold平均1に再scaleしない。

```text
m_i  = number of predicted direct-positive tuples for i's GT fork
pi_i = n_sampled(video,stratum) / n_universe(video,stratum)
w_train_i = 1/m_i                    if direct_fork_positive
            1/pi_i                   if sampled certified_negative
w_eval_i  = 1/m_i                    if direct_fork_positive
            1                        if exhaustive certified_negative
            0                        if ignore
```

`pi_i` は抽出対象のouter/inner training partitionごとにliteral numerator/denominatorを持つ。
学習ID、weight、`D_train`はrun開始前にfreezeし、epoch間で変えない。
各実行のtraining BCEはそのrunで採用されたIDの `w_train_i` を使い、denominatorは
`D_train=sum_i w_train_i`。`fixed_train_probe` は学習setから事前freezeしたIDの同じ
`w_train_i` を変えず使い、`D_probe=sum_probe w_train_i`。inner validation BCEは全labeled
inner-valの `w_eval_i`、`D_inner_val=sum_inner_val w_eval_i`。四inner-valのmicro集約は
numeratorとdenominatorをそれぞれ加算する。temperature NLLも同じinner OOF ID、
`w_eval_i`、`D_inner_oof=sum_inner_oof w_eval_i` を使い、
`sum(w_eval_i*BCEWithLogits(logit_i/T,y_i))/D_inner_oof` を最小化する。

untouched outer raw-logit BCEは各exampleをそのouter-val出現で一度だけ含め、
`sum(w_eval_i*BCEWithLogits)/D_outer_all`、`D_outer_all=sum_all_outer w_eval_i`とする。
calibrated outer BCEは同じID/weight/denominatorで各foldの `logit_i/T_k` を使う。
calibrated Brierは同じID/weight/denominatorで
`sum(w_eval_i*(sigmoid(logit/T_k)-y_i)^2)/D_outer_all`。lineage別は対象lineageだけの
`sum w_eval_i` を分母にする。AP以外の全reportはweighted numerator、literal denominator、
ID hash、weight-table SHAを保存し、uncalibrated Brierは同式の `T_k=1`とする。
一つでも違えばarm全体をfailする。

## 5. Split: eval36 を sealed のまま残す

全 train stem inventory から supervisor が事前に hash-pinned した
`sealed_evaluation_exclusion.json` の stem set を機械的に引く。split builder は exclusion GT
path を引数に取らず、除外 stem の Zarr/GEFF を open してはならない。期待する残数は inventory
で検証し、想定と違えば停止する。除外された評価集合の GT count、division count、frame、
feature、画像統計を split 形成に使わない。

remaining videos を単位とする outer 5-fold CV を、feature extraction、raw prediction、
candidate generation、prediction-to-GT matching、tuple label、negative stratumのどれよりも前に一回だけ
作る。許可するsplit inputはhash-pinned remaining stem inventory、recording/embryo family ID、
lineage ID、GT graphのみから決定した `direct_gt_fork_count`（outdegree exactly 2、
predicted node/coordinate非使用）だけである。GT fork counterのcode/config/hashとstemごとのliteral countを
`split_inputs_v1.json` にpinする。画像統計、frame数、prediction、candidate、matched positive tuple、
certified negative、ignore、label-envelope/deployment countは使わない。

stemを超える family IDがある場合はfamilyをatomic groupとし、未取得のままstem独立を
仮定しない。各groupにlineageごとの `group_present_indicator` とgroup内stemの
`direct_gt_fork_count` 合計を持たせ、全groupを `(-total_group_gt_forks, family_or_stem_id)`
順に並べる。現在の `(lineage group-present count, lineage direct_gt_fork_count)` の各4dimensionを
`global_dimension_total/5` で割り、仮置き後の
objective tuple `(maximum fold range across dimensions, sum squared deviation from 1, fold_id)` が
lexicographic最小のfoldへgreedy配置する。global total 0のdimensionはobjectiveから除く。
`outer_split_v1.json` はalgorithm/code SHA、input SHA、全
stem/group/fold、lineage/fork count、exclusion manifest SHAを持つ。

このsplitを全 `upstream_outer_k` trainingより前にfreezeし、training-stem manifestの親にする。
その後に作るlabel/candidateのcoverageが悪い、foldがclass欠落する、または一動画が
positiveを支配する場合は、splitを改定せずv1をNO-GOとする。各outer foldに両lineage、
direct GT fork `>=5`、lineageごとdirect GT fork `>=2` をsplit時に要求し、後段G1で
positive/certified-negativeの存在を別に要求する。frame/window/exampleや同一stem由来の抽出物を
fold横断させない。headだけがstemを除外したlegacy CVを「video-out」と表現しない。

## 6. Model architecture

実 feature channel 数を `d` とし、Phase 0 が `feature_schema.json` に固定する。入力は
encoder feature `f_P,f_A,f_B`、各 node の detection logit、既存 forward/reverse association
signal、物理 relation だけ。lineage ID、dataset ID、GT degree、GT match distance、label stratum、
ST-R2 accept/reject reason は model 入力にしない。
encoder featureは `tap_zyx` 由来、全geometry scalar/vectorは `planner_zyx_um` 由来に固定し、
tap/raw/final座標からgeometryを再計算しない。

public scoring APIは最初に `canonicalize_children` を呼び、`node_id(A)<node_id(B)` へfeature、座標、
logit、maskをまとめて並べ替える。node IDは並替えにだけ使いtensorへ入力しない。内部modelも順序に
依存しないよう、child-specific branchには同じweight/functionを適用し、その後はcommutative relation
だけを使う。

```text
node(z) = Linear(d -> 64)(LayerNorm(z)); SiLU; Linear(64 -> 64)

branch(P,C) = MLP_2x64([
  node(P), node(C), node(C)-node(P), node(P)*node(C),
  dz,dy,dx,distance, detection_logits(P,C),
  forward_assoc(P,C), reverse_assoc(P,C)
])

pair(P,{A,B}) = [
  node(P),
  (branch(P,A)+branch(P,B))/2,
  abs(branch(P,A)-branch(P,B)),
  branch(P,A)*branch(P,B),
  sister abs(dz),abs(dy),abs(dx),distance,distance^2,
  parent-to-child-midpoint dz,dy,dx,distance,
  cosine(branch vectors), abs(child-distance difference)
]

logit = Linear(32 -> 1)(Dropout(0.10)(SiLU(Linear(pair_dim -> 32))))
```

全 MLP weight は head artifact のみで、encoder / existing association head は凍結する。
association signal が upstream tap で取得不能なら 0 埋めせず schema/version を変更し、まず
`encoder+geometry` preregistrationへ戻る。feature と scalar は fold-train の finite mean/std で
標準化し、その統計を fold checkpoint に含める。validation 統計を混ぜない。

signed `A->B` sister vector、ordered concatenation、`distance(P,A)-distance(P,B)`、role-specific child
weightを禁止する。plannerのmutation role（既存子A、donor子B）はmodel tensorと別metadataに保つ。

必須gradient testはCPU float64 / dropout offで、同一parameter stateに対し
`L1=forward(P,A,B).sum()` と `L2=forward(P,B,A).sum()` を別graphでbackwardする。logitとparameter
gradientは`torch.equal`、`grad_P1==grad_P2`、`grad_A1==grad_B2`、`grad_B1==grad_A2`を
`torch.equal`で要求する。CUDA float32 repeat testは同じ対応に `rtol=0, atol=1e-7` を許す。
加えてbatch/order不変、mask/NaN fail-closed、strict shape/schema、同一inputのbitwise repeat、
encoder parameter/BN bufferのtraining前後SHA一致を要求する。

## 7. Loss、optimizer、training-loss gate

v1 の optimization loss は inverse-inclusion weighted binary cross entropy 一個に固定する。
ranking/focal/auxiliary edge loss は ablation であり v1 total loss に足さない。
weightとdenominatorはsection 4.1のliteral tableをそのまま使う。

```text
L_bce = sum_i w_i * BCEWithLogits(logit_i, y_i) / sum_i w_i
L_total = L_bce
optimizer = AdamW(head_only, lr=3e-4, weight_decay=1e-4)
scheduler = cosine, warmup=1 epoch
batch_size = pilotでVRAMを測り固定 (default proposal 1024 cached tuples)
max_epochs = 30; gradient_clip_pre_norm = 5.0
primary selector = minimum val weighted BCE, earliest tie
```

`analysis/training_loss_gate.md` の artifact/schema を省略しない。特に各 epoch で
`train.losses.bce/total` と `val.losses.bce/total` を別 object とし、weighted numerator、
weight denominator、reduction=`sum_weighted_over_labeled_tuples` を保存する。batch mean の平均を
loss と呼ばない。全 optimizer step で clip 前 global grad norm を記録する。

さらに「optimizer が実際に loss を下げた」ことを validation と混同せず証明するため、各 fold
train set から label/stratum/video を固定した `fixed_train_probe` を、frozen outer/inner splitを
入力とするdataset構築時・学習開始前にhash-pinする。outer split自体の作成入力にはしない。
augmentation/dropout off、同一順序・同一 weight で各 epoch 後に評価し、history に
`train_fixed_probe.losses.total` と明記する。optimization progression gate は

```text
median(last 3 complete epochs fixed_train_probe_loss)
    <= 0.95 * median(first 3 complete epochs fixed_train_probe_loss)
```

とし、最低 6 epoch を要求する。これは train-only optimization gate で、汎化・checkpoint
選択・採用の証拠ではない。validation loss は別系列で primary selector にだけ使う。
optimizer-batch loss、fixed-train-probe loss、validation loss を同じ field/plot title に重ねない。

全 fold で progression、finite、zero nonfinite、strict checkpoint load、encoder hash immutability、
stem separation を PASS しなければ OOF metric を promotion 用に読まない。best と last は別保存、
resume は optimizer/scheduler/scaler/RNG/sampler/history-prefix を完全復元する。

`training_loss_gate.md` のbaseline progressionを満たす comparatorは
`geometry_symmetric_mlp` に固定する。同じlabel universe、split、negative IDs/weights、optimizer
budget、nested selectionを使い、encoder featureとassociation/detection signalだけを除く。個別runの
selectorは最小validation weighted BCE（earliest tie）のまま、bundle advancement marginは実行前に
次へ固定する。

```text
pooled untouched weighted_BCE(candidate) / weighted_BCE(comparator) <= 0.98
video-macro AP delta                                             >= 0.000
44b6 weighted-BCE ratio                                         <= 1.02
6bba weighted-BCE ratio                                         <= 1.02
44b6 video-macro AP delta                                       >= -0.02
6bba video-macro AP delta                                       >= -0.02
calibrated Brier delta                                           <= 0.000
```

weighted BCEはtemperature適用前raw logitsのuntouched outer predictionから同じweightで再計算し、
primary advancementとする。AP/Brierとlineage条件を直交non-inferiorityとする。train loss、
inner selector、outer bundle comparatorのfieldを共有しない。legacy stackでは同じ値をdiagnosticとして
出してもadvancement PASSを名乗れない。

## 8. Nested OOF、calibration、threshold lock

outer fold `k` ごとにepoch、temperature、thresholdの三つをouter-train内だけで完結してfreezeする。
promotion-gradeではsection 2.3の `upstream_outer_k` を使い、outer-valはupstream/head/calibration/
thresholdの全stackに対して未接触でなければならない。

1. outer-trainをvideo-grouped/lineage-aware inner 4-foldに分ける。各inner headをmax 30 epochまで
   学習し、epochごとのinner-val weighted BCE numerator/denominatorを保存する。
2. 四つのinner-valをmicro集約したweighted BCEが最小の共通epochを `E_k` とする。同値は最早。
   fixed-train progression、training-loss integrity、各inner coverageを満たさないepoch/runは選べない。
3. 各inner modelのexact epoch `E_k` checkpointからinner OOF raw logitsを一回再生成する。そのinner
   OOFだけでsection 4.1のID/`w_eval_i`/literal denominatorを使い、positive temperature
   `T_k`をweighted NLL最小化する。範囲 `[0.25,4.0]`、同値は
   `|log(T)|`が小さく、それも同じなら小さいTとする。
4. `logit/T_k`をinner OOFへ適用し、固定grid
   `{0.50,0.70,0.80,0.90,0.95,0.975}` をexact inner deployment graphsで比較する。
   `N` をremaining stem数、`n_k` をouter-trainのunique stem数とし、次の全literal constraintを
   満たすthresholdだけをfeasibleとする。division TPだけをdataset量で事前frozen scalingし、
   score/Jaccard/paired thresholdはscaleしない。

   ```text
   inner official aggregate division_tp delta      >= ceil(4 * n_k / N)
   inner official aggregate adjusted-edge delta    >= -0.002
   inner official aggregate combined-score delta   >= +0.003
   inner official aggregate division_jaccard delta >= 0
   inner paired median combined-score delta         >= 0
   inner paired worst combined-score delta          >= -0.002
   inner 44b6 aggregate combined-score delta        >= 0
   inner 6bba aggregate combined-score delta        >= 0
   inner accepted mutations                          >= 1
   ```

   `N,n_k,ceil(4*n_k/N)` をsplit manifestにliteral保存する。feasible中でcombined score最大、
   同値は高いthresholdを `tau_k` とする。feasible thresholdがなければouter foldを
   scoreせずNO-GOとし、threshold/grid/scaleを変えない。
5. outer-train全体でheadをexact `E_k` epoch refitし、normalizationもouter-trainだけでfitする。
   `(E_k,T_k,tau_k)` と全hashをmanifestへfreezeしてからouter-valを一回だけpredictし、immutable
   raw/calibrated scoreとcandidate graphをsealする。
6. G0.5の事前登録済みoracle firewall以外は、全outer predictionがsealされるまで
   outer-val label/metricをhead学習・選択・閲覧processから読まない。seal後、一回だけ公式scoreし、
   untouched outer predictionsを結合したものだけをG4とする。outer labelでcheckpoint、T、threshold、
   radius、cap、feature、foldを選び直さない。

legacy checkpointを使う同じ手順はhead-level nestingのdiagnosticであり、outer-valがfull-stack未接触
ではないためG4とは呼ばず `D4_LEGACY_STACK` と記録する。

OOF bundle はlabel envelope全candidateの
`example_id,dataset,P,A,B,fold,raw_logit,calibrated_probability,label_or_ignore,
gt_fork_group,in_deployment_universe,planner_record_id,E_k,T_k,tau_k,upstream_checkpoint_sha256`
を保存する。報告は次を含む。

- pooled と video-macro PR-AUC / ROC-AUC、fold/lineage 別値;
- weighted BCE、Brier、adaptive ECE (bin merge rule を事前固定)、reliability counts;
- GT fork 単位 recall（同じ fork の重複 tuple を一件として扱う）;
- precision-recall と false-positive stratum、動画対応 bootstrap CI;
- calibrated probability の fold drift と temperature;
- exact deployment universeだけを production graphへ適用した per-video official raw counts と aggregate。

G4 PASS後のfinal stackはouter labels/outer metricをhyperparameter集約に使わない。五つのinner-derived
selectionを数値昇順に並べ、`E_final=median(E_k)`、`T_final=median(T_k)`、
`tau_final=median(tau_k)` とする（5個なので一意）。この集約式自体を実行前にpinする。

final refitは六つ目の独立upstream contextを先に完成させる。まずsection 2.3の
remaining-only final upstream checkpointを、sealed evaluationを除外したremainingだけで学習する。
upstreamのepoch/configはouter training historyの事前登録集約で固定し、head outer metricで選ばない。
このupstream training自体はsection 12の30 GPU-hour外であり、provenance付き実artifactを
取得できなければ、別の事前budget contractなしに実行せずHOLDする。
そのcheckpointだけでremaining全videoの final raw GEFF、pair feature、association/detection
signalを一回生成し、`final_upstream_context_v1` manifest/checkpoint/raw/feature/code SHAを
sealする。outer-context featureと混合またはdeduplicateしない。

head final dataset/normalization/negative samplingはこの final contextだけから再構築し、remaining全データを
`E_final` epochでfinal refitする。`T_final,tau_final`をそのまま使う。parent CV bundle、
final upstream context、final datasetの三SHAをpinする `fixed_epoch.pt` だけをdeployment候補にでき、
final refitにvalidation PASSを捏造しない。grid外補間、動画/lineage別threshold、outer結果後の
変更は禁止する。

## 9. Go / no-go gates

順番に評価し、一段でも失敗した run は後段へ進めない。

### G0 Artifact / feature tap

- support source 全 bytesとmanifestが上記 pinに完全一致。legacy診断のみprimary checkpoint
  SHAが `12f...`に一致し、promotionは各outer/final bundleが宣言する別checkpoint SHA、
  同一architecture/source schema、training-stem provenanceに完全一致;
- promotion gradeでは全 `upstream_outer_k` のtraining-stem exclusion/provenanceとouter-val raw/feature
  generator hashがsection 2.3を満たす。legacy provenance unknownはdiagnostic-only;
- strict load、feature shape/dtype/stride、pair-context/node-ID mapping、repeatability PASS;
- train inventory と exclusion manifest set/hashが一致し、excluded GT/image/featureを一度も open
  していない open-file receipt がある;
- label-envelope positive recall overall `>=0.95`、lineage別 `>=0.90`;
- exact deployment tuple/feature coverage `==100%`、planner record set/order/hash一致;
- encoder parameters と buffers の pre/post hash が同一。

### G0.5 Pre-training exact deployment oracle ceiling

head parameterを一つも学習する前に、remaining-trainだけでexact
`deployment_universe_v1` のlabel-aware oracle censusを実行する。pre-conflict poolから、元のnode conflict、
frame cap 1、video cap 2を満たす `none / singleton / compatible ordered pair` の全selectionを
列挙する。compatible pairは両permutationを評価し、final graph/downstream/scorer receiptが完全同一と
証明できた場合だけhash deduplicateする。それぞれ
section 4の `make_deployment_counterfactual_v1` によるexact `Q->B` remove / `P->B` add、
同一baseline-vs-CF downstream、`final_zyx`、matching receipt付き公式 scorerを通す。
pre-existing fork attributionはoracle gainから除く。candidate countだけやdirect fork
labelからdivision TPを推定しない。
promotion oracleでは各videoをそのvideoがouter-valになる `upstream_outer_k` raw/feature contextで一度だけ
評価する。legacy contextのoracleはceiling diagnosticでありpromotion gateを解除しない。このoracleは
remaining-train labelを読むため、G4の意味は「仮説クラス自体が未閲覧」ではなく、「各outer headの出力と
`E_k,T_k,tau_k`がouter labelで選ばれていない」である。このconditional claimをG4 reportに明記する。

全video alternativeのcartesian choiceについて、official aggregate combined scoreを最大化するexact
branch-and-bound / dynamic programとcertificateを要求する。pruning boundはper-video official sufficient
countsの区間から作ってよいが、最終winnerとrunner-upは実graphを `src/biohub/evaluate.py` 経由で再scoreし、
official raw counts/summaryが一致しなければfailする。探索をexact完了できなければceiling unknownとして
trainingを始めない。

oracle実行は別process/ACLに隔離する。detailed artifactは下記raw countsやGT eventを含む
`sealed_oracle_detail_v1/` とし、trainerへmountしない。別ディレクトリの
`oracle_gate_receipt.json` はcanonical JSON objectで、次のexact key allowlistだけを持つ。

```text
schema_version                  = "oracle_gate_receipt_v1"
candidate_version               = "two_child_head_incremental_v1"
status                          = "PASS" | "NO_GO"
contract_sha256                 = <64 lower-hex>
outer_split_manifest_sha256     = <64 lower-hex>
deployment_universe_sha256      = <64 lower-hex>
outer_bundle_manifest_sha256    = <64 lower-hex>
oracle_gate_spec_sha256         = <64 lower-hex>
sealed_detail_sha256            = <64 lower-hex>
sealed_detail_bytes             = <nonnegative integer>
oracle_code_sha256              = <64 lower-hex>
```

trainerはregular fileのこのreceipt一個だけをopenし、duplicate key、symlink、unknown/missing key、
scalar型不一致、`PASS`以外、現在のcontract/split/universe/bundle/gate/code SHAとの不一致を
拒否する。receiptにmetric、delta、winner、GT ID、path、timestamp、自由記述を追加できない。
trainerは `sealed_detail_sha256/bytes` をopaque commitmentとして記録するだけでdetailをopenしない。
PASSの場合はdetailをG4 outer prediction全sealまで閲覧不可とし、NO_GOの場合は学習を
開始しない。oracle後にcandidate generator、model、split、gate、margin、budgetを変えることは、
詳細を見たか否かに関わらずv1を終了した新仮説とする。

sealed detailed oracle artifactはpre/post pool hash、全alternative、cap/conflict、選択、direct-fork coverage、
official division TP/FP/FN、adjusted-edge、combined、lineage/paired deltaを保存する。direct fork recallと
official division TPは別欄にする。本候補の学習済みG4 target `+0.003`に対し、
oracleは2倍のheadroom `+0.006` を要求する。cap-compatible exact oracleが次を全て
満たさなければ **NO-GO before training** とする。

```text
official aggregate combined-score delta >= +0.006
official aggregate division_tp delta     >= +4
official aggregate adjusted-edge delta   >= -0.002
paired worst delta                       >= -0.002
both lineage combined-score delta        >= 0
```

oracle winner/GT deltaをhead input、hard-negative priority、loss weight、threshold、resolver sortへ渡さない。
oracleはceilingによる早期停止だけに使う。

### Gold-gap portfolio accounting（未達成budget）

`analysis/gold_candidate_landscape.md` に記録済みのE23 `0.924` からbuffered target
`0.947` への差は `+0.023`（今回score artifactを再読した値ではない）。その
research budgetを次のようにpreregisterする。これは達成予測ではなく、未達成枠はcredit 0である。

```text
two_child_head_incremental_v1                         +0.003
future E17/ranker allocation                         +0.008
future broader association/lineage-recovery allocation +0.007
future independent representation/ensemble allocation  +0.005
allocated total                                      +0.023
remaining after this candidate alone                 +0.020
```

各後続候補は、その時点でacceptedな最新stackに対する新しいpreregistered paired
incremental evaluationでのみcreditを得る。portfolio計上は
`credit_j=min(allocation_j,max(0,remaining-train sequential G4 delta_j),
max(0,independently authorized sequential public delta_j))` とする。public delta未取得の候補は
credit 0。standalone deltaの単純加算、oracle ceiling、重複効果をcreditにしない。
local combined metricからpublic scoreへの移送性も仮定しない。すべてのsequential creditの合計が
`0.023`に届かない限りgold target達成を主張しない。

### G1 Label / split

- unmatched->negative が 0、positive/certified-negative/ignore が再計算可能;
- `outer_split_v1` がupstream-independent inputだけで事前freezeされ、後段改定0、
  video/group leakage 0、各 outer fold が section 5 のGT/lineage coverageと後段の
  direct-positive tuple `>=1`、certified-negative `>=1`、両lineageのdirect-positive存在を満たす;
- duplicate example ID 0、daughter swap consistency 100%;
- positive fork と negative stratum の動画集中度を保存し、一動画が positive の `>20%` を持つなら
  HOLDして bootstrap/gate を再設計する（その run で split を動かさない）。

### G2 Optimization integrity

- `training_loss_gate.md` 全項目 PASS、全 outer/inner必要 run の fixed-train progression PASS;
- encoder hash不変、nonfinite 0、grad norm coverage 100%、best/last/resume strict load PASS。

### G3 OOF discrimination / calibration

- section 7のweighted-BCE comparator margin、Brier、両lineage non-inferiorityを全て満たす;
- geometry-only symmetric MLP に対し video-macro AP の paired mean delta `>=+0.05` かつ
  video bootstrap 95% lower bound `>0`;
- calibrated weighted BCE と Brier が uncalibrated より非劣化、adaptive ECE `<=0.05`;
- selected threshold で certified OOF precision の one-sided 95% lower bound `>=0.80`、
  GT-fork recall `>=0.25`、true positive GT forks `>=20`;
- 両 lineage の AP delta `>=0`。一動画だけを除くと成立しない場合は NO-GO。

### G4 Remaining-train OOF official graph

G4はsection 2.3のfull-stack outer exclusionを証明した五つのuntouched outer predictionsだけを
結合する。各foldでbaseline/candidateは同じ `upstream_outer_k` raw prediction、同じpostprocess、
code、DeepCenter bytesを使い、head gateだけoff/onにする。candidateは
`e23_two_child_twin_gate_v1`で、R2 structural motif/capsとtransactional remove/add coreは固定するが、
scored-plan schema/validator/orderはsection 10の新versionである。outer-val graphはsection 8でfreezeした
`E_k,T_k,tau_k`から一度だけ生成・sealし、公式score後に再生成しない。

legacy all-train upstream上の同型比較は `D4_LEGACY_STACK` であり、下記数値を満たしてもG4 PASS、
video-out、promotion evidenceにならない。

```text
official aggregate division_tp delta        >= +4
official aggregate adjusted-edge delta      >= -0.002
official aggregate combined-score delta     >= +0.003
official aggregate division_jaccard delta   >= 0
paired median combined-score delta           >= 0
paired worst combined-score delta            >= -0.002
44b6 aggregate combined-score delta          >= 0
6bba aggregate combined-score delta          >= 0
```

候補発火 0 なら分類 metric が良くても NO-GO。head は R2 eligible set を gate/rank するだけなので、
R2 が列挙しなかった tuple の改善を主張しない。

### G5 Feasibility / sealed evaluation entry

- section 12の101-fit / 6-context projectionとGPU/disk/oracle total budgetを全て満たす;
- G4 PASS後にremaining-only final upstream checkpointを検証し、それだけから六つ目の
  raw/feature contextとfinal head datasetを生成したprovenance/coverage/hashが100% PASS;
- target-equivalent T4 run で candidate wall `<=1.10 * baseline wall`、追加 peak VRAM `<=1.0 GiB`、
  OOM 0、feature sidecar追加 diskをmanifest化;
- より上位の ST-R3 feasibility 条件を弱めず、少なくとも mirrored timing の
  `candidate_wall_gate <=1.25*baseline_wall_gate`、whole-job RSS、hidden-200 80% wall budgetを満たす;
- 現行 ST-R3 runへ checkpoint/sidecarを差し込まず、新しい candidate名、artifact list、config
  whitelist、adapter appendix、preregistrationを作る;
- ここまで全 PASS 後にだけ sealed evaluation を別承認・別 state machine で開始する。本設計・
  training/OOF phase は sealed evaluation GTを読まない。

## 10. Production R2 / R3 との整合

### 10.1 必要なpre-conflict resolver boundary

現在の `twin_plan_hook` はconflict/cap解決済み `TwinPlan` を観測するため、そこへhead scoreを足しても
cap内rankingを変えられない。さらに現行 `divisions.py` の `TwinPlan`、
`_validate_twin_plan_for_mutation`、`apply_twin_only_v1_plan` はlegacy structural sort/decision/counter
schemaを組として検証する。learned probabilityでsortしthreshold rejectを追加するplanはその
validator/orderと同じではないため、`TwinPlan` に偽装しない。

実装時は `src/biohub/public_postproc/divisions.py` に次の新規シンボルを追加する。

```text
enumerate_twin_eligible_records_v1(snapshot, cfg, deepcenter_evidence)
    -> TwinEligiblePoolV1
score_twin_candidates_v1(pool, pair_feature_sidecar, head_bundle, T, tau)
    -> tuple[ScoredTwinRecordV1, ...]
resolve_scored_twin_plan_v1(pool, scored_records, cfg)
    -> ScoredTwinPlanV1
_validate_scored_twin_plan_v1_for_mutation(plan)
    -> validated scored-plan state
apply_scored_twin_plan_v1(nodes, edges, plan)
    -> edges, ScoredTwinMutationSummaryV1
```

`TwinEligibleRecordV1` はexact type/schema version `"twin_eligible_record_v1"`、
`record_id,dataset,frame,P,Q,A,B,A2,B2`、元 `Q->B` の完全frozen metadata token、
予定 `P->B` row、全structural/DC evidence、現行formulaの `structural_sort_key`、
snapshot/config/DC hashを持つ。label/oracle counterfactualはこのstructural recordだけを受け、
head scoreを必要としない。`ScoredTwinRecordV1` はexact type/schema version
`"scored_twin_record_v1"`、一つの `TwinEligibleRecordV1`へのidentity-preserving reference、
`raw_logit_float64,temperature_float64,probability_float64,threshold_float64,score_passed`、
feature/head/normalization hashを持つ。mutation roleは
`A=existing child of P`, `B=child of donor Q` のまま保存するが、model inputは
`canonicalize_children(P,A,B)` によりunorderedである。GT path/label/metric callbackはAPI引数にない。

enumeratorは現行 `divisions.py` の次をexactに再計算する。nodeはunique integer ID/timeと
finite `z,y,x`、edgeはvalid endpoint、duplicateなし、`t->t+1`、indegree `<=1`、
outdegree `<=2`。`P` はindegree 1/outdegree 1、`Q` はindegree 0/outdegree 1。P/Qは
`STEAL_TWIN_TWIN_MAX_UM` 内で `1e-9` ambiguity ruleによるunique mutual nearest。
`d(P,A)<=STEAL_TWIN_EXISTING_CHILD_MAX_UM`、`d(P,B)<=STEAL_TWIN_PARENT_MAX_UM`、
`STEAL_TWIN_SISTER_MIN_UM<=d(A,B)<=STEAL_TWIN_SISTER_MAX_UM`。A/Bは異なる一successor
A2/B2を持ち、`d(A2,B2)-d(A,B)>=STEAL_TWIN_DIVERGE_UM`。六roleはnon-synthetic、
DeepCenter decisionは現行normalizerとliteral threshold `0.12`を通過する。structural keyは
`(d_pb+0.15*d_ab, -divergence_growth, d_pq, P,Q,A,B,A2,B2)` とし、すべての
float token、必須edge `P->A,Q->B,A->A2,B->B2`、`P->B` 非存在、metadataを検証する。

probabilityはhash-pinned reference functionでCPU float64の
`sigmoid(raw_logit_float64/temperature_float64)` を一回計算し、`float.hex()` tokenをrecordに
固定する。scoreがfiniteかつ `probability>=tau` のrecordだけを次でsortする。

```text
(-probability_float64_exact, structural_sort_key, record_id)
```

epsilon tieやrounded display値を使わず、同じIEEE-754値だけをtieとして下位keyへ進む。その順に
既存 `{P,Q,A,B,A2,B2}` node conflict、frame cap、video capを適用する。threshold rejectをcap消費に
数えない。resolverは入力を変更せず、同一pool/score/configからbitwise同一planを返す。

`ScoredTwinPlanV1` はexact type/schema version `"scored_twin_plan_v1"`、`validation_reason`、
immutable nodes/edges snapshot、structural pool、scored records、resolution decisions、accepted records、
`SCORED_TWIN_V1_COUNTER_KEYS`、上記provenance hash、threshold/capを持つ。counter keyは
「少なくとも」ではなく、次の固定順全体とする。
decisionはstructural recordごとに一個で、`accepted=true, reason=None` または
`accepted=false, reason in {"score_threshold","conflict","frame_cap","video_cap"}` だけ。
nonfinite score/probabilityはthreshold rejectではなくarm validation failureとする。

```text
two_child_examined_frames
two_child_p_pool
two_child_q_pool
two_child_preconflict_enumerated
two_child_rejected_distance_twin
two_child_rejected_ambiguous_p_nn
two_child_rejected_ambiguous_q_nn
two_child_rejected_not_mutual_parent_nn
two_child_rejected_distance_existing_child
two_child_rejected_distance_parent
two_child_rejected_distance_sister_low
two_child_rejected_distance_sister_high
two_child_rejected_time
two_child_rejected_missing_successor
two_child_rejected_shared_successor
two_child_rejected_divergence
two_child_rejected_synthetic
two_child_rejected_deepcenter_bundle
two_child_rejected_deepcenter_dataset
two_child_rejected_deepcenter_frame
two_child_rejected_deepcenter_heatmap
two_child_rejected_deepcenter_nonfinite
two_child_rejected_deepcenter_threshold
two_child_structural_eligible
two_child_feature_covered
two_child_scores_checked
two_child_score_threshold_rejected
two_child_score_passed
two_child_conflict_rejected
two_child_frame_cap_rejected
two_child_video_cap_rejected
two_child_accepted
two_child_edges_planned_removed
two_child_edges_planned_added
two_child_edges_removed
two_child_edges_added
two_child_isolated_donors
two_child_validation_failed
```

各境界はsource snapshot/config/DeepCenter evidence/pool/feature manifest/head checkpoint/normalization/
temperature/threshold/scored pool/final planのcanonical JSON SHA-256を持ち、floatは`float.hex()`でserializeする。
conservationは `preconflict_enumerated=sum(all structural/deepcenter rejected)+structural_eligible`、
`structural_eligible=feature_covered=scores_checked=score_threshold_rejected+score_passed`、
`score_passed=conflict+frame_cap+video_cap+accepted`（first-reject排他的）、
`accepted=planned_removed=planned_added`、pre-mutationの
`edges_removed=edges_added=isolated_donors=validation_failed=0`。不一致はmutation前failである。

`_validate_scored_twin_plan_v1_for_mutation` はexact class/schema/key order/typeのみを許容し、現在の
snapshotがplan snapshotとedge row order/metadataまで同一か、上記structural条件とkeyが再計算と
bitwise一致するか、logit/T/probability/threshold passとlearned sortが再計算に一致するか、
decision-record identity、six-role conflict、`cfg.STEAL_TWIN_FRAME_CAP_ABS==1`、
`cfg.STEAL_TWIN_VIDEO_CAP_ABS==2`、counter conservationが成立するかを検証する。
legacy `_validate_twin_plan_for_mutation` を呼ばず、両validatorのacceptance/order parityを主張しない。

master off baselineはenumerator、sidecar、head、resolver、counter allocationを一切呼ばずexact E23
byte identityを保つ。learned dry-runは全preflight/enumerate/score/resolve/hashを行うがmutationしない。
current `twin_only_v1` profileは旧structural resolverを維持し、新profileだけがscored resolverを使う。

### 10.2 Mutation / R3 boundary

新 `apply_scored_twin_plan_v1` が現行R2から保存するのはtransactional edit coreだけである。
各accepted recordにexactly `remove(Q->B); add(P->B)`、node不変、edge数不変、accepted
`k` に対しsymmetric difference `2k`、Qの完全isolation、indegree `<=1`/outdegree `<=2`、
partial-application拒否、exact-pre/exact-post idempotence、all-or-nothing publicationを必須とする。削除する
`Q->B` metadata tokenはvalidated snapshotと一致させ、new rowは
`source_id,target_id,distance_um,edge_prob=None` だけを持つ。survivor rowのidentity/orderを保ち、
new rowは **learned accepted order**
でappendする。このorderはlegacy `TwinPlan` sort/mutation orderと同一とは主張しない。
`ScoredTwinMutationSummaryV1` はexact schema version、
`status in {applied,already_applied,no_changes}`、plan/pre/post SHA、accepted count、nodes/edges
before/after、removed/added/symmetric-difference count、isolated donor countを持ち、validatorが上記式から
再計算する。

新 head は immutable recordの `P,A,B` を scoreし、threshold reject と cap内順序を返すだけにする。
safe-division後のhook位置と後段 geometry / isolated prune / short-track / linefit は固定するが、
scored-plan type/validator/resolution/mutation orderはversionedな新boundaryである。off時は新code pathを呼ばず
model/sidecarをloadせず exact E23 identity。
candidateはpreflightで全expected sidecar/head/schema/hashを検証し、不一致ならarm全体を失敗させ、
video別fallbackも部分outputも作らない。

現在の ST-R3 `twin_only_v1` は postprocess-onlyで、primary/secondary checkpointは live inputでなく、
DeepCenterだけが live checkpointである。新規学習 checkpointは loss gateを通ってもその candidateへ
入れられず、別 preregistrationが必要という既存契約を維持する。本 head candidateの live artifactは
少なくとも次を追加するため、adapter/content hash/open-file audit/runtime/RSSを再bindする。

```text
two_child_head fixed_epoch.pt + config/normalization
5 outer + 1 final per-video frozen feature/raw contexts + manifests
feature extraction source and support source manifest
CV/OOF/final-refit parent artifact manifest
selected threshold and candidate-generator schema
ScoredTwinPlanV1 schema/counter/validator/mutator source hashes
outer_split_v1 + example_weight_v1 manifests
oracle_gate_receipt_v1 (detailed oracle remains sealed and unmounted)
```

DeepCenter checkpoint epoch 2 / SHA
`8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0`、
official gitlink、baseline raw bytes、E23 configは比較両腕で固定する。head結果で現行 ST-R3 の
metric gateを再解釈したり、既存 run directoryへ追記しない。

## 11. Reproducibility と provenance

root CV manifest は最低限次を pin する。

- superproject Git SHA/tree、dirty flag、official gitlink/HEAD/clean flag;
- support source各file SHAとcanonical manifest SHA、feature-tap patch SHA;
- active primary-family checkpoint bytesごとのSHA、strict state schema、epoch/config、feature schema、
  training-stem manifest（legacy診断は `12f...`、promotionは5 outer + finalを個別にpin）;
- train Zarr/GT/raw GEFF/sidecar canonical inventory SHA、exclusion manifest SHA;
- candidate/label/split/counterfactual/scored-plan algorithm versionと全 config、physical scale;
- outer/inner fold assignment、seed (`20260902` rootからrun/fold/epochへhash派生);
- `split_inputs_v1`、literal example-weight/denominator table、matching receipt、minimal oracle receiptと
  sealed-detail opaque commitment;
- model/loss/optimizer/scheduler、PyTorch/CUDA/cuDNN/NumPy、GPU、determinism flags;
- 全 command、allowlisted env、network-disabled receipt、open-file receipt;
- fold history/checkpoint、OOF rows/calibrator/threshold table、official rows、final refit参照;
- fileごとのbytes/SHA256とatomic-publication receipt。

同じ input/schema/checkpointで feature sidecarを二回作り、manifestとarray bytesが一致しなければ
cacheを採用しない。GPU reductionでbitwise再現不能な場合は、許容する fieldと `rtol/atol` を
事前登録し、IDs/count/hashは完全一致、feature floatは最大絶対差も保存する。

## 12. Runtime / memory 見積りと計測契約

現地 artifactsがないため絶対値を捏造しない。現時点で言えるのは、full encoder fine-tuneの既知
上限が T4 x2 / batch 8で3.3 s/iter、約2.3 h/full epochであり、本設計は encoder backwardを
行わず feature extractionを既存 inference forwardへpiggybackし、head trainingはcache上だけで
あることだけである。

promotion-gradeの必須work countを先に固定する。

```text
primary head:             5 * (4 inner + 1 outer) = 25 fits
geometry symmetric MLP:  5 * (4 inner + 1 outer) = 25 fits
no-association ablation:  5 * (4 inner + 1 outer) = 25 fits
geometry logistic:        5 * (4 inner + 1 outer) = 25 fits
primary final refit:                                  1 fit
maximum total:                                      101 head fits
```

各fitは最大30 epoch。temperature fit、threshold grid、oracle graph alternativesはhead fit数に含めず
別計測する。最初のG3/G4 decisionに必要なのはprimary+comparatorの50 fitsで、残りablationは前段
PASS後だけ実行するが、最終総budgetには最初から含める。

section 2.3の5 `upstream_outer_k` を使う場合、innerごとにencoder inferenceを繰り返さず、各outer
contextでremaining全videoのraw/featuresを一度生成してreuseするため、最大 `5*N_remaining`
video-checkpoint inference。final upstream用を加えると `6*N_remaining` である。異なるcheckpointの
featureを同じsidecarとしてdeduplicateしない。upstream checkpoint自体の再学習は既知約900
GPU-hour/checkpoint級で下記30 GPU-hour budget外であり、既存の真正outer-excluded artifactsがなければ
promotion routeはHOLDする。

storage とhead計算の事前式は次である。

```text
feature_bytes_per_context ~= sum_over_pairs((N_source + N_target) * (2*d + scalar/id bytes))
outer_feature_bytes      ~= sum_over_5_outer_contexts(feature_bytes_per_context)
final_feature_bytes      ~= feature_bytes(final_upstream_context_v1)
promotion_feature_bytes  ~= outer_feature_bytes + final_feature_bytes
tuples_per_parent <= C(K,2) = 28 (K=8)
head_activation_bytes <= chunk_size * pair_dim * 4 * safety_factor
```

tuple tensor全体をmaterializeせずvideo/frame順にchunk (`4096` proposal) scoreする。Phase 0の1動画
pilotで `N_nodes,d,tuples,sidecar bytes,extract wall,head wall,peak CPU RSS,peak CUDA allocated/reserved`
を取り、10動画（両lineage、node-count decileを含む）で事前式を較正する。label envelopeとexact
deployment universeのtuple数/wallを別々に測り、広いenvelope値をR2 production実行時間に流用しない。

pilot後・どのfit/generationより前に次のhard total budgetをmanifestへ数値固定する。
CPU timeはprocessごとのuser+systemの全worker合計、I/OはOS/filesystem counterのread/write bytes、
RSSはtarget Linuxのprocess tree peakで計測する。cache hitのみの計測でbudget PASSを出さない。

```text
raw + pair-feature generation (all contexts) <= 24 T4 GPU-hours
all 101 cached head fits + calibration         <=  6 T4 GPU-hours
new GPU total                                  <= 30 T4 GPU-hours
oracle/postprocess search                      <= 24 wall-hours on declared 8 CPU cores
GT fork census + label/rematching + CF scoring <= 64 CPU-core-hours
inner/outer threshold graph construction       <= 64 CPU-core-hours
oracle exact search + downstream rescoring     <= 192 CPU-core-hours
manifest validation + atomic publication       <=  8 CPU-core-hours
new CPU total                                  <= 328 CPU-core-hours
label/rematch/CF process-tree peak RSS          <= 32 GiB
oracle/threshold process-tree peak RSS          <= 48 GiB
publication process-tree peak RSS               <= 16 GiB
whole-job host RAM peak                         <= 64 GiB
filesystem bytes read (all six contexts incl.) <=  3 TiB
filesystem bytes written incl. transient files <= 500 GiB
simultaneous scratch space                      <= 150 GiB
all pair-feature sidecars                      <= 100 GiB
all new run artifacts incl. checkpoints/OOF    <= 120 GiB
additional production peak VRAM                <= 1.0 GiB
```

label/rematching/CF、threshold graph、oracle、publicationのCPU合計は重複しないcategoryとし、
total `328`はその和である。projected/observed totalが一つでも超える、exact oracle searchが
完了しない、またはsource data込みdisk余裕が不足する場合、fold/candidate/contextを間引かず
HOLDする。約200動画への外挿はexact deployment
node/tuple count比例と動画固定costを分け、最大/p95/slowest、係数、残差を保存する。ローカルmacOS
`ru_maxrss`だけでtarget RAM PASSを出さない。

## 13. 必須 ablation（探索順を固定）

同一 split/candidate/label/OOF artifactで次だけを比較する。

1. `geometry_logistic`: section 6の物理scalarのみの正則化logistic regression;
2. `geometry_symmetric_mlp`: encoder featureなし、同じsymmetric head;
3. `frozen_encoder_v1`: 主候補;
4. `frozen_encoder_no_assoc`: association/detection scalarを除き、encoder+geometryの寄与を分離;
5. `parent_patch_cnn_reference`: 既存tiny patch CNN scoreが同じcandidate上で利用可能な場合のみ、
   既存artifactを再学習せず診断比較。

primary+secondary feature融合、encoder unfreeze、ranking/focal loss、time feature、lineage別calibrator、
radius/K/cap変更、broader orphan/steal mutationはv1 ablationに入れない。主候補がgateを落ちた後に
同じOOFを見て追加variantを作らず、新しいhypothesis/versionへ戻る。

## 14. Artifact prerequisites / gaps

学習実装へ進む前に次が必要である。

1. hash-pinned support-pack source treeとoffline wheels;
2. legacy診断にはexact primary checkpoint bytes/config、promotionには5 outer-excluded upstream
   checkpoint/raw/feature bundlesとfinal remaining-only upstream checkpoint/raw/feature context;
3. remaining trainのcomplete Zarr + GT GEFF inventoryとsealed exclusion manifest;
4. 各outer contextのpinned baseline raw GEFFを再生成できるinference command/config/provenance;
5. initializedかつcleanなofficial submodule（read-only）;
6. exact DeepCenter artifact/manifest（OOF graph integration時のみ）;
7. upstream pair-context/node-ID mappingを確定するfeature-tap audit;
8. `training_loss_gate.md` schema writer/verifier（文書には統合候補しかなく現コード未実装）;
9. group metadata（同一embryo/recordingが複数stemなら必須）;
10. target-class T4 runtime/RSS measurement手段とquota/wall宣言;
11. upstream-independent GT-fork census/split builderとfrozen `outer_split_v1.json`;
12. exact `ScoredTwinPlanV1` resolver/validator/mutator APIと両counterfactual edit function;
13. pre-training cap-compatible official oracle、sealed detail publisher、strict minimal receipt parser;
14. CPU/RAM/I/O/process-tree measurementとatomic publication harness。

一つでも欠ければ feature抽出・学習・公式metric読出しを開始しない。

## 15. 将来の実行 phase と concrete commands

以下は implementation 後の契約形であり、今回実行していない。全 phase はnetwork disabled、
`official/` write禁止、fresh output directoryで行う。実スクリプト名/CLIが実装レビューで変わる場合は
本契約を先にversion-upし、存在しないfallbackをrunnerに持たせない。

```bash
# Phase 0a: local, read-only inventories / source verification
git status --short
git rev-parse HEAD
git -C official status --short
git -C official rev-parse HEAD
sha256sum <support-pack>/src/biohub_tracking/models/temporal_unet.py \
  <support-pack>/src/biohub_tracking/models/simple_node_transformer.py \
  <support-pack>/scripts/predict_unet_transformer.py \
  <support-pack>/scripts/train_unet_transformer.py \
  <primary-checkpoint>

# Phase 0b: freeze outer split BEFORE any upstream training/prediction/feature/label work
PYTHONPATH="src:official/src" uv run python scripts/build_two_child_outer_split.py \
  --remaining-inventory <remaining-stems.json> --gt <remaining-gt-only> \
  --recording-families <recording-family-metadata.json> \
  --exclude-manifest <sealed_evaluation_exclusion.json> \
  --out <fresh-split-dir>/outer_split_v1.json

# Phase 0c: validate five upstream contexts against the already-frozen split
uv run python scripts/validate_upstream_outer_provenance.py \
  --split <fresh-split-dir>/outer_split_v1.json \
  --outer-bundles <upstream-outer-bundle-root> \
  --out <fresh-provenance-receipt.json>

# Phase 1: label-blind raw prediction + pair-feature extraction for 5 outer contexts
uv run python scripts/extract_two_child_features.py \
  --train-images <remaining-images> \
  --outer-upstream-bundles <upstream-outer-bundle-root> \
  --support-pack <support-pack> \
  --exclude-manifest <sealed_evaluation_exclusion.json> \
  --out <fresh-outer-raw-feature-dir> --network-disabled

# Phase 2: labels/weights only; the frozen outer split is input and cannot be revised
PYTHONPATH="src:official/src" uv run python scripts/build_two_child_dataset.py \
  --features <fresh-outer-raw-feature-dir> --gt <remaining-gt-only> \
  --split <fresh-split-dir>/outer_split_v1.json \
  --exclude-manifest <sealed_evaluation_exclusion.json> \
  --out <fresh-dataset-dir>

# Phase 2b: isolated exact oracle; publish only a minimal receipt outside sealed detail
PYTHONPATH="src:official/src" uv run python scripts/census_two_child_deployment_oracle.py \
  --dataset <fresh-dataset-dir> --outer-raw <fresh-outer-raw-feature-dir> \
  --gt <remaining-gt-only> --deepcenter <exact-best.pt> \
  --sealed-detail-out <sealed-oracle-detail-dir> \
  --gate-receipt-out <fresh-oracle-gate-dir>/oracle_gate_receipt.json

# Phase 3: nested grouped CV + loss-gate artifact validation
uv run python scripts/train_two_child_head.py \
  --dataset <fresh-dataset-dir> --split <fresh-split-dir>/outer_split_v1.json \
  --upstream-provenance <fresh-provenance-receipt.json> \
  --oracle-gate-receipt <fresh-oracle-gate-dir>/oracle_gate_receipt.json \
  --config configs/two_child_head_incremental_v1.json --out <fresh-cv-dir>
uv run python scripts/validate_training_run.py <fresh-cv-dir>

# Phase 4: OOF calibration, frozen threshold grid, untouched outer graph arms
PYTHONPATH="src:official/src" uv run python scripts/evaluate_two_child_oof.py \
  --cv <fresh-cv-dir> --outer-raw <fresh-outer-raw-feature-dir> \
  --images <remaining-images> --deepcenter <exact-best.pt> \
  --out <fresh-oof-eval-dir>

# Phase 5a: validate an acquired sixth, remaining-only upstream checkpoint.
# Retraining it is outside this 30-GPU-hour contract and needs a prior contract revision.
uv run python scripts/validate_final_upstream_provenance.py \
  --checkpoint <final-remaining-only-upstream.pt> \
  --training-manifest <final-upstream-training-manifest.json> \
  --split <fresh-split-dir>/outer_split_v1.json \
  --out <fresh-final-upstream-bundle> \
  --exclude-manifest <sealed_evaluation_exclusion.json>

# Phase 5b: generate final raw/features once from only that final checkpoint
uv run python scripts/extract_two_child_features.py \
  --train-images <remaining-images> \
  --final-upstream-bundle <fresh-final-upstream-bundle> \
  --support-pack <support-pack> \
  --exclude-manifest <sealed_evaluation_exclusion.json> \
  --out <fresh-final-context-dir> --network-disabled
PYTHONPATH="src:official/src" uv run python scripts/build_two_child_dataset.py \
  --features <fresh-final-context-dir> --gt <remaining-gt-only> \
  --split <fresh-split-dir>/outer_split_v1.json \
  --exclude-manifest <sealed_evaluation_exclusion.json> \
  --final-context-only --out <fresh-final-dataset-dir>

# Phase 5c: final head refit only after G0-G4 PASS
uv run python scripts/train_two_child_head.py \
  --final-refit-from <fresh-cv-dir>/root_manifest.json \
  --dataset <fresh-final-dataset-dir> \
  --features <fresh-final-context-dir> \
  --final-upstream-bundle <fresh-final-upstream-bundle> \
  --out <fresh-final-refit-dir>

# Code-quality gates; official remains unmodified
uv run --frozen --extra dev pytest -q tests/test_two_child_head.py \
  tests/test_two_child_counterfactuals.py tests/test_scored_twin_plan.py \
  tests/test_training_history.py tests/test_public_postproc.py
uv run --frozen --extra dev ruff check src scripts tests
git diff --check
git status --short
```

この設計の次の正当な状態は、artifactを取得・hash検証した上での Phase 0 audit と、feature tap
だけの実装契約である。現状態からtrain、eval36 GT read、Kaggle push/submit、official変更へ進む
ことは許可しない。
