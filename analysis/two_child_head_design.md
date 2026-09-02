# Frozen-encoder explicit two-child head 設計契約

Updated: 2026-09-02 (Asia/Tokyo)

Status: **DESIGN_ONLY / HOLD_ARTIFACTS_AND_REMAINING_TRAIN**

## 1. 結論と仮説

最初に検証する学習候補は `two_child_head_v1` だけとする。既存の primary
`UNetNodeTransformer` の encoder を完全凍結し、時刻 `t` の親候補 `P` と
`t+1` の異なる二娘候補 `A,B` のノード特徴、物理幾何、既存 association/detection
信号から、「`P` が `A,B` の共通親である」tuple logit を出す小型・娘交換不変 head
を学習する。

検証する因果仮説は次である。

> 1-to-1 association 用 head が第二娘へ確率質量を割けない場合でも、凍結済み
> encoder 表現には division を識別する情報が残っており、二娘を同時に見る
> permutation-invariant head は、幾何だけより高い動画外 precision で真の
> `(P,{A,B})` を順位付けできる。

本候補は現行 `twin_only_v1` をそのまま置換しない。最初の production 接続は、
ST-R2 の structural eligibility、DeepCenter veto、transactional `Q->B` removal /
`P->B` addition、不変量、frame/video cap を固定し、その **eligible tuple の gate と
cap 内 ranking だけ**を head score に置く別 profile
`e23_two_child_twin_gate_v1` とする。一般 orphan adoption、donor 条件緩和、synthetic
node、safe-division 半径変更、encoder fine-tune は別仮説であり v1 に混ぜない。

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
  (legacy epoch 400) である。v1 の feature source は primary 一個に固定する。
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
  `apply_twin_only_v1_plan` が動く。head integration はこの純粋 mutation 境界を変えない。

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
- `outputs` にある raw GEFF は public-four diagnostic 4 本だけで、remaining-train raw prediction
  bundle はない。public submission/stats/score CSV は本設計の入力として読んでいない。
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
`plan_twin_only_v1` が structural eligibility、DeepCenter veto、conflict/cap 前後の immutable
recordsとして列挙する exact ST-R2 eligible tupleだけである。OOF official graph、candidate arm、
runtime/RSS、約200動画外挿はこの universe だけを使う。現行の parent `<=8 um`、sister
`5.5..11 um`、two-successor、non-synthetic、donor条件を広げない。head は exact eligible setを
threshold gateし、同じcap内でrankするだけである。

Phase 0 で、remaining-train の全 GT-positive fork が label envelope に入る recall を測る。
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

encoder は primary checkpoint のみを `eval()`、全 parameter
`requires_grad_(False)`、`torch.inference_mode()` で実行する。BatchNorm running state、
dropout、checkpoint bytes を一切変えない。primary full checkpoint を
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

## 4. Label contract と sparse-GT 防御

予測 node と GT node は、動画・frame ごとに物理 7 um gate の one-to-one assignment を行う。
label builder は公式 scorer の matching field を再利用してよいが、公式 metric codeを変更せず、
matching source/gitlink/hashを manifest に pin する。label は三値
`positive / certified_negative / ignore` で、unmatched を負例にしない。

### Positive

`P,A,B` がそれぞれ異なる GT node `p,a,b` に一意 match し、GT directed edge が
`p->a` と `p->b` の両方を持ち、`outdegree_GT(p)=2` のときだけ positive とする。
娘順は無視する。同一 GT fork から複数 predicted tuple が positive になる場合は、学習 weight
を `1 / positive_tuples_for_gt_fork` とし、一つの容易な fork が loss を支配しない。

### Certified negative

`P,A,B` が一意 match し、少なくとも片方の娘対応 node が GT 上で別の明示 parent を持つ場合
だけ negative とする。具体的には次のいずれかである。

- `p->a` は真だが `pred_GT(b)=q != p`（one-true-child impostor）;
- `p->b` は真だが `pred_GT(a)=q != p`;
- `pred_GT(a)!=p` かつ `pred_GT(b)!=p` で、両方の predecessor が明示される;
- positive fork の一方を保ち、同 frame の別 parent の明示 child と交換した wrong-sibling tuple。

GT node が predecessor を持たない、prediction/GT のいずれかが unmatched、assignment が同率、
GT local topology が malformed、または false child の異なる parent を証明できない tuple は
すべて ignore とする。GT `outdegree=0/1` だけを根拠に「division でない」としない。

### Hard-negative sampling

各 outer-train split で positive は全件使用する。certified negatives を次の排他的 stratum に
分け、epoch-derived seed で最大 `8 negatives / positive` を決定的に抽出する。

1. `wrong_sibling_nearest`: 真の片娘 + 最短の別-parent child;
2. `twin_like`: 現行 ST-R2 の structural eligibility を満たすが GT common-parent でない;
3. `association_confident`: false branch の frozen association signal が stratum 内上位;
4. `geometry_matched`: positive の parent-child / sister distance bin と一致;
5. `background_certified`: 残りから video/frame 均衡抽出。

同じ tuple を重複採用しない。各 stratum の universe size、sample size、inclusion probability、
seed、ID hash を保存し、BCE は inverse-inclusion weight で certified universe risk を推定する。
weight は fold 内平均 1 に正規化するが clip しない。極端な最大/中央値 ratio `>100` なら sampling
設計不良として停止する。validation/OOF の分類 readout は sampling せず全
`label_recall_envelope_v1` を scoreし、supervised AP/loss は positive + certified negative のみ。
official graph readoutはその中のexact `deployment_universe_v1` tupleだけを使う。

## 5. Split: eval36 を sealed のまま残す

全 train stem inventory から supervisor が事前に hash-pinned した
`sealed_evaluation_exclusion.json` の stem set を機械的に引く。split builder は exclusion GT
path を引数に取らず、除外 stem の Zarr/GEFF を open してはならない。期待する残数は inventory
で検証し、想定と違えば停止する。除外された評価集合の GT count、division count、frame、
feature、画像統計を split 形成に使わない。

remaining videos を単位とする outer 5-fold CV を一回だけ作る。frame/window/example を fold
横断させない。同一 stem 由来の raw prediction、augmentation、再抽出、primary/secondary seed
variant は全て同じ group に置く。もし stem を超える embryo/recording family ID が metadata に
存在するなら、それを group key とし、未取得のまま stem 独立を仮定しない。

fold assignment は label 作成後、remaining GT だけを用いて次の vector を greedy snake-draft
で均衡化する。

```text
(lineage 44b6/6bba, positive GT forks, positive tuples,
 certified negatives by five strata, total candidate tuples, video frames)
```

各 lineage 内で `(-positive_forks,-positive_tuples,-certified_negatives,stem)` 順に並べ、
現在の vector imbalance 増分が最小の fold へ置く。同値は fold ID が小さい方。split manifest
は algorithm/version、全 stem/group/fold、各 count、source inventory hash、exclusion manifest
hash を保存する。各 validation fold に両 lineage、positive と certified negative があり、
positive GT fork `>=5`、各 lineage positive `>=2` がなければ 5-fold を無理に実行せず NO-GO。
fold 数を結果後に変えない。

## 6. Model architecture

実 feature channel 数を `d` とし、Phase 0 が `feature_schema.json` に固定する。入力は
encoder feature `f_P,f_A,f_B`、各 node の detection logit、既存 forward/reverse association
signal、物理 relation だけ。lineage ID、dataset ID、GT degree、GT match distance、label stratum、
ST-R2 accept/reject reason は model 入力にしない。

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
  sister dz,dy,dx,distance,
  parent-to-child-midpoint dz,dy,dx,distance,
  cosine(branch vectors), child-distance asymmetry
]

logit = Linear(32 -> 1)(Dropout(0.10)(SiLU(Linear(pair_dim -> 32))))
```

全 MLP weight は head artifact のみで、encoder / existing association head は凍結する。
association signal が upstream tap で取得不能なら 0 埋めせず schema/version を変更し、まず
`encoder+geometry` preregistrationへ戻る。feature と scalar は fold-train の finite mean/std で
標準化し、その統計を fold checkpoint に含める。validation 統計を混ぜない。

必須 unit property は娘交換の logit/gradient 一致、batch/order 不変、mask/NaN fail-closed、
strict shape/schema、同一 input の bitwise repeat、encoder parameter/BN buffer の training 前後
SHA 一致である。

## 7. Loss、optimizer、training-loss gate

v1 の optimization loss は inverse-inclusion weighted binary cross entropy 一個に固定する。
ranking/focal/auxiliary edge loss は ablation であり v1 total loss に足さない。

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
train set から label/stratum/video を固定した `fixed_train_probe` を split 作成時に hash-pinned
する。augmentation/dropout off、同一順序・同一 weight で各 epoch 後に評価し、history に
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

## 8. Nested OOF、calibration、threshold lock

outer 5 folds の各 validation video は、その stem を一度も見ていない head で score する。
calibration label の自己利用を避けるため、各 outer-train 内で 4-fold inner OOF logits を作り、
その inner OOF だけで正の temperature `T` を weighted NLL 最小化する。head を outer-train 全体で
固定 epoch refit し、outer-val logits に `logit/T` を適用する。`T` の探索範囲 `[0.25,4.0]`、
optimizer、tie rule、inner split hash を事前固定する。outer-val label で T を fit しない。

OOF bundle はlabel envelope全candidateの
`example_id,dataset,P,A,B,fold,raw_logit,calibrated_probability,label_or_ignore,
gt_fork_group,in_deployment_universe,planner_record_id` を保存する。報告は次を含む。

- pooled と video-macro PR-AUC / ROC-AUC、fold/lineage 別値;
- weighted BCE、Brier、adaptive ECE (bin merge rule を事前固定)、reliability counts;
- GT fork 単位 recall（同じ fork の重複 tuple を一件として扱う）;
- precision-recall と false-positive stratum、動画対応 bootstrap CI;
- calibrated probability の fold drift と temperature;
- exact deployment universeだけを production graphへ適用した per-video official raw counts と aggregate。

deployment threshold は固定 grid
`{0.50,0.70,0.80,0.90,0.95,0.975}` だけを nested OOF graph 上で評価する。下記 graph constraint
を全て満たす threshold のうち aggregate combined score 最大、同値は高い threshold を選ぶ。
grid 外補間、動画/lineage 別 threshold、結果後の radius/cap変更は禁止する。threshold 選択後、
outer best epoch の中央値（earliest integer tie）で remaining 全データを `final_refit` し、parent CV
bundle が pin する `fixed_epoch.pt` だけを deployment 候補にできる。final refit 自体に validation
PASS を捏造しない。

## 9. Go / no-go gates

順番に評価し、一段でも失敗した run は後段へ進めない。

### G0 Artifact / feature tap

- support source 全 bytes、manifest、primary checkpoint SHA が上記 pin と完全一致;
- strict load、feature shape/dtype/stride、pair-context/node-ID mapping、repeatability PASS;
- train inventory と exclusion manifest set/hashが一致し、excluded GT/image/featureを一度も open
  していない open-file receipt がある;
- label-envelope positive recall overall `>=0.95`、lineage別 `>=0.90`;
- exact deployment tuple/feature coverage `==100%`、planner record set/order/hash一致;
- encoder parameters と buffers の pre/post hash が同一。

### G1 Label / split

- unmatched->negative が 0、positive/certified-negative/ignore が再計算可能;
- video/group leakage 0、各 outer fold が section 5 の coverage を満たす;
- duplicate example ID 0、daughter swap consistency 100%;
- positive fork と negative stratum の動画集中度を保存し、一動画が positive の `>20%` を持つなら
  HOLDして bootstrap/gate を再設計する（その run で split を動かさない）。

### G2 Optimization integrity

- `training_loss_gate.md` 全項目 PASS、全 outer/inner必要 run の fixed-train progression PASS;
- encoder hash不変、nonfinite 0、grad norm coverage 100%、best/last/resume strict load PASS。

### G3 OOF discrimination / calibration

- geometry-only symmetric MLP に対し video-macro AP の paired mean delta `>=+0.05` かつ
  video bootstrap 95% lower bound `>0`;
- calibrated weighted BCE と Brier が uncalibrated より非劣化、adaptive ECE `<=0.05`;
- selected threshold で certified OOF precision の one-sided 95% lower bound `>=0.80`、
  GT-fork recall `>=0.25`、true positive GT forks `>=20`;
- 両 lineage の AP delta `>=0`。一動画だけを除くと成立しない場合は NO-GO。

### G4 Remaining-train OOF official graph

baseline は同じ held-out raw prediction、同じ postprocess、同じ code、同じ DeepCenter bytes で、
head gate のみ off。candidate は `e23_two_child_twin_gate_v1` で、R2 motif/mutation/caps は同一。

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

- target-equivalent T4 run で candidate wall `<=1.10 * baseline wall`、追加 peak VRAM `<=1.0 GiB`、
  OOM 0、feature sidecar追加 diskをmanifest化;
- より上位の ST-R3 feasibility 条件を弱めず、少なくとも mirrored timing の
  `candidate_wall_gate <=1.25*baseline_wall_gate`、whole-job RSS、hidden-200 80% wall budgetを満たす;
- 現行 ST-R3 runへ checkpoint/sidecarを差し込まず、新しい candidate名、artifact list、config
  whitelist、adapter appendix、preregistrationを作る;
- ここまで全 PASS 後にだけ sealed evaluation を別承認・別 state machine で開始する。本設計・
  training/OOF phase は sealed evaluation GTを読まない。

## 10. Production R2 / R3 との整合

現行 R2 の pure mutation は `remove(Q->B); add(P->B)` の二操作、node不変、edge数不変、
accepted `k` に対し symmetric difference `2k` である。新 head は planner が作った immutable
candidate recordの `P,A,B` を scoreし、threshold reject と cap内順序を返すだけにする。
mutation関数、metadata token、fail-closed validation、safe-division後のhook位置、後段 geometry /
isolated prune / short-track / linefit を変更しない。off時は model/sidecarをloadせず exact E23 identity。
candidateはpreflightで全expected sidecar/head/schema/hashを検証し、不一致ならarm全体を失敗させ、
video別fallbackも部分outputも作らない。

現在の ST-R3 `twin_only_v1` は postprocess-onlyで、primary/secondary checkpointは live inputでなく、
DeepCenterだけが live checkpointである。新規学習 checkpointは loss gateを通ってもその candidateへ
入れられず、別 preregistrationが必要という既存契約を維持する。本 head candidateの live artifactは
少なくとも次を追加するため、adapter/content hash/open-file audit/runtime/RSSを再bindする。

```text
two_child_head fixed_epoch.pt + config/normalization
per-video frozen feature sidecars + manifests
feature extraction source and support source manifest
CV/OOF/final-refit parent artifact manifest
selected threshold and candidate-generator schema
```

DeepCenter checkpoint epoch 2 / SHA
`8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0`、
official gitlink、baseline raw bytes、E23 configは比較両腕で固定する。head結果で現行 ST-R3 の
metric gateを再解釈したり、既存 run directoryへ追記しない。

## 11. Reproducibility と provenance

root CV manifest は最低限次を pin する。

- superproject Git SHA/tree、dirty flag、official gitlink/HEAD/clean flag;
- support source各file SHAとcanonical manifest SHA、feature-tap patch SHA;
- primary frozen checkpoint bytes、strict state schema、epoch/config、feature schema;
- train Zarr/GT/raw GEFF/sidecar canonical inventory SHA、exclusion manifest SHA;
- candidate/label/split algorithm versionと全 config、physical scale;
- outer/inner fold assignment、seed (`20260902` rootからrun/fold/epochへhash派生);
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

storage とhead計算の事前式は次である。

```text
feature_bytes ~= sum_over_pairs((N_source + N_target) * (2*d + scalar/id bytes))
tuples_per_parent <= C(K,2) = 28 (K=8)
head_activation_bytes <= chunk_size * pair_dim * 4 * safety_factor
```

tuple tensor全体をmaterializeせずvideo/frame順にchunk (`4096` proposal) scoreする。Phase 0の1動画
pilotで `N_nodes,d,tuples,sidecar bytes,extract wall,head wall,peak CPU RSS,peak CUDA allocated/reserved`
を取り、10動画（両lineage、node-count decileを含む）で事前式を較正する。約200動画への外挿は
総node/tuple count比例と動画固定costを分け、最大/p95/slowest、係数、残差を保存する。ローカル
macOS `ru_maxrss`だけでtarget RAM PASSを出さない。

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
2. exact primary checkpoint bytesとconfig、必要ならprovenanceだけのsecondary hash;
3. remaining trainのcomplete Zarr + GT GEFF inventoryとsealed exclusion manifest;
4. pinned baseline raw GEFFを再生成できるinference command/config;
5. initializedかつcleanなofficial submodule（read-only）;
6. exact DeepCenter artifact/manifest（OOF graph integration時のみ）;
7. upstream pair-context/node-ID mappingを確定するfeature-tap audit;
8. `training_loss_gate.md` schema writer/verifier（文書には統合候補しかなく現コード未実装）;
9. group metadata（同一embryo/recordingが複数stemなら必須）;
10. target-class T4 runtime/RSS measurement手段とquota/wall宣言。

一つでも欠ければ feature抽出・学習・公式metric読出しを開始しない。

## 15. 将来の実行 phase と concrete commands

以下は implementation 後の契約形であり、今回実行していない。全 phase はnetwork disabled、
`official/` write禁止、fresh output directoryで行う。実スクリプト名/CLIが実装レビューで変わる場合は
本契約を先にversion-upし、存在しないfallbackをrunnerに持たせない。

```bash
# Phase 0: local, read-only inventories / source and checkpoint verification
git status --short
git rev-parse HEAD
git -C official status --short
git -C official rev-parse HEAD
sha256sum <support-pack>/src/biohub_tracking/models/temporal_unet.py \
  <support-pack>/src/biohub_tracking/models/simple_node_transformer.py \
  <support-pack>/scripts/predict_unet_transformer.py \
  <support-pack>/scripts/train_unet_transformer.py \
  <primary-checkpoint>

# Phase 1: label-blind raw prediction + feature extraction on remaining train only
uv run python scripts/extract_two_child_features.py \
  --train-images <remaining-images> --raw-geff <remaining-raw-geff> \
  --support-pack <support-pack> --weights <primary-checkpoint> \
  --exclude-manifest <sealed_evaluation_exclusion.json> \
  --out <fresh-feature-dir> --network-disabled

# Phase 2: labels/splits; excluded GT directory is not mounted/passed
PYTHONPATH="src:official/src" uv run python scripts/build_two_child_dataset.py \
  --features <fresh-feature-dir> --gt <remaining-gt-only> \
  --exclude-manifest <sealed_evaluation_exclusion.json> \
  --out <fresh-dataset-dir>

# Phase 3: nested grouped CV + loss-gate artifact validation
uv run python scripts/train_two_child_head.py \
  --dataset <fresh-dataset-dir> --split <split-manifest.json> \
  --config configs/two_child_head_v1.json --out <fresh-cv-dir>
uv run python scripts/validate_training_run.py <fresh-cv-dir>

# Phase 4: OOF calibration, frozen threshold grid, held-out graph arms
PYTHONPATH="src:official/src" uv run python scripts/evaluate_two_child_oof.py \
  --cv <fresh-cv-dir> --raw-geff <remaining-raw-geff> \
  --images <remaining-images> --deepcenter <exact-best.pt> \
  --out <fresh-oof-eval-dir>

# Phase 5: final refit only after G0-G4 PASS
uv run python scripts/train_two_child_head.py \
  --final-refit-from <fresh-cv-dir>/root_manifest.json \
  --out <fresh-final-refit-dir>

# Code-quality gates; official remains unmodified
uv run --frozen --extra dev pytest -q tests/test_two_child_head.py \
  tests/test_training_history.py tests/test_public_postproc.py
uv run --frozen --extra dev ruff check src scripts tests
git diff --check
git status --short
```

この設計の次の正当な状態は、artifactを取得・hash検証した上での Phase 0 audit と、feature tap
だけの実装契約である。現状態からtrain、eval36 GT read、Kaggle push/submit、official変更へ進む
ことは許可しない。
