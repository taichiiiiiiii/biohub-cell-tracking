# 提出パイプライン アーキテクチャ設計書（詳細・現状の書き起こし）

**最終更新: 2026-09-27**

この文書は**いま提出しているもの（`notebooks/pub923_repro/pub923_repro.ipynb`）のアーキテクチャ**を、コードを読んで書き起こしたもの。
新しい設計の提案ではない。仕様は `analysis/competition_spec.md`、計画は `analysis/endgame_plan_20260927.md`、
採否の記録は `analysis/experiment_ledger.md` にあり、ここには重複させない。

- 対象: notebook の commit `ba5480d`（E71-B）。**E70 の提出物（`1a0c71f`、kernel v15）に validator の計測設定（`VALIDATOR_N_PER_TYPE=6`）を足しただけ**で、`submission.csv` は E70 と同一（📏 両者のファイルサイズ 12,703,555 byte が一致）。
- 確度: ✅ コードで確認（cell 番号と行番号つき） ／ 📏 実行ログや出力で実測 ／ ⚠️ 未確認
- cell 番号は notebook の 0 始まり。行番号はその cell の source 内の 1 始まり。official は `official/scripts/predict_unet_transformer.py`。

---

## 目次

1. 全体構成
2. 実行環境とプロセス構成
3. 設定の仕組みと防護
4. 予測段（検出 → エッジ候補 → ILP）
5. 後処理段（9 段）
6. motion relink（E70 の因子）の詳細
7. 出力と監査
8. validator（計測系）
9. 効いていない設定
10. ローカル検証環境との違い
11. 既知のリスクと未確認事項

---

## 1. 全体構成

```text
test/<stem>.zarr  (T=100, Z=64, Y=256, X=256, uint16)
  │
  ├─[cell 9]  依存関係とモデル成果物の解決・sha256 検証（オフライン）
  │
  ├─[cell 11] official 予測スクリプトを文字列置換で改造 → GPU 2 枚でサブプロセス分割実行
  │     ┌ 検出: 8 方向 TTA → 2 シード混合 → frame retention guard → 局所最大
  │     ├ エッジ候補: 特徴量 TTA（encode 時）→ 全ペアのスコア → harmonic 双方向融合
  │     │            → low-margin 2 シード混合 → rank bonus → softmax → 閾値 0.48
  │     └ ILP（tracksdata ILPSolver）
  │     出力: tracking_repo/predictions/<user>/unet_transformer/split_0/<stem>.geff
  │
  ├─[cell 13] 動画ごとに .geff → filter_output_graph（後処理 9 段）→ submission.csv / run_stats.csv
  ├─[cell 15] submission.csv の独立監査
  ├─[cell 17-19] validator: train 12 本で予測と後処理をもう一度実行し、notebook 内の再実装採点器で採点（計測のみ）
  └─[cell 21] 全機構の実際の状態を表示（manifest）
```

**データの流れの要点**
- 動画は独立に処理される。動画をまたぐ情報は無い。
- 後処理は動画ごとに、`nodes_by_id: dict[int, dict]` と `edges: list[dict]` を各段で受け渡す。各段は `stats: dict[str,int]` にカウンタを積み、それが `run_stats.csv` の列になる。
- 後処理は画像（zarr のフレーム）を 2 か所で読み直す。合成ノードの位置補正（§5.4）と DeepCenter の veto（§5.4・§5.5）。

---

## 2. 実行環境とプロセス構成

| 項目 | 内容 | 出所 |
|---|---|---|
| マシン | Kaggle T4（GPU 有効）、インターネット無効 | ✅ `kernel-metadata.json` |
| 入力 dataset | 主モデル・副モデル・DeepCenter・DivNet の 4 つ（§4.1） | ✅ 同上 |
| GPU 分割 | `worker_count = min(2, GPU 数, 動画数)` が 2 以上かつ `SLICE` が空なら、`--slice i::2` で動画を 2 つに分け、別々のサブプロセスで予測。終了後に .geff をマージし、重複や欠落があれば停止。それ以外（動画 1 本など）は単一プロセス | ✅ cell 11 L472-518、L403-468 |
| GPU 必須 | CUDA が無ければ停止（CPU で黙って走らない） | ✅ cell 11 L1-8 |
| 実行時間 | カーネル全体で E70 40.83 分、E71-B 46.5 分（上限 12 時間）。E70 の内訳は、依存関係の解決 約 9.4 分、test 4 本の予測 9.20 分（GPU 2 枚並列）、後処理 約 5 分、validator 4 本 約 8 分。E71-B は validator が 12 本になった分だけ長い。hidden test は動画数が多く、ここからの単純な外挿では 12 時間に収まるとは言えない。収まる根拠は、同じ経路の E59 などが hidden test で採点まで完了していること | 📏 ログの `time` と `Prediction completed in` |

---

## 3. 設定の仕組みと防護

### 3.1 設定値の経路

| 段階 | 内容 | 出所 |
|---|---|---|
| 書く（主） | cell 3 で `os.environ["BIOHUB_*"] = "文字列"` | ✅ cell 3 |
| 書く（ほか） | cell 9 L561（`DEEPCENTER_CHECKPOINT` を解決済みのパスで上書き）、cell 9 L644-655（副モデル関係と閾値 0.48）、cell 11 L85（`DUAL_SEED_MIN_CANDIDATE_RETENTION` を cell 3 の値に関係なく `"0.90"` で上書き） | ✅ |
| 読む（大半） | cell 7 L43-151 と L243-244（`DIVNET_VERIFY`、`DIV_MIN_PROB`）の `os.environ.get(名前, 既定値)` でモジュール定数にする | ✅ |
| 読む（一部） | cell 11 のパッチ文字列の中（予測サブプロセスが実行時に読む） | ✅ |
| 予測への受け渡し | cell 11 が `predict_cmd` の引数（`--det-threshold`、ILP の重みなど）と、サブプロセスに引き継ぐ環境変数の両方で渡す | ✅ cell 11 L321-348、L490 |

**既定値の罠**: cell 3 で設定しない変数は cell 7 の既定値になる。E70 以前は `OUTPUT_MOTION_RELINK` を設定していなかったため、既定値 `"1"`（ON）で動いていた（✅ cell 7 L65）。

### 3.2 防護

| 防護 | 内容 | 出所 |
|---|---|---|
| Configuration guard | cell 5 の `_EXPECTED_NUMERIC`（13 キー）と `_EXPECTED_TEXT`（13 キー）の計 26 キーが実際の環境変数と違えば停止 | ✅ cell 5 |
| パッチの一意性 | cell 11 の置換は、置換元がちょうど 1 か所にあることを確認し、違えば `RuntimeError`。**例外は最初の検出 TTA パッチ**で、見つからなければ警告を出して続行する（✅ L53-57）。ただし次のパッチの置換元がこのパッチの結果（`/ _nv`）を含むため、結果的にそこで停止する。置換後に残っていることの確認は edge-feature TTA・副の TTA・rank bonus の 3 つだけ（L215、L233、L294） | ✅ cell 11 |
| 無効化の検知 | edge-feature TTA と副の TTA は、TTA 前後で特徴量が変わらなければ停止（`EDGE-TTA NO-OP` / `SECONDARY_EDGE_TTA_NO_OP`、L209、L221）。双方向の重みが 0.15 でなければ停止（L171-180）。各パッチの後に `compile()` で構文を確認。rank bonus の `RANK_BONUS_NO_OP`（L263-267）は、列ごとに必ず最良が 1 つあるため空でないフレーム対では発火し得ず、実質的な防護になっていない | ✅ cell 11 |
| モデルの完全性 | 成果物の sha256 を検証 | ✅ cell 9 L469-560 |
| DeepCenter の版 | checkpoint の epoch が 2 でなければ読み込まない。1 つも読めなければ停止（`REQUIRE_DEEPCENTER_VETO=1`） | ✅ cell 13 L376-425 |

---

## 4. 予測段（cell 9・11 ＋ official）

### 4.1 モデル

| 役割 | 成果物 | 出所 |
|---|---|---|
| 主モデル（UNet エンコーダ＋Transformer のエッジ予測） | `pilkwang/biohub-tracking-support-pack-50ep-v1` の `weights/unet_transformer/split_0/edge_predictor_best.pth` | ✅ cell 7 L34-36 |
| 副モデル（同じ構造の別シード） | `pilkwang/biohub-temporal-unet3d-seed314159-v1` | ✅ cell 9 L573-644 |
| DeepCenter（細胞中心の heatmap。後処理の veto 専用） | `pilkwang/biohub-deepcenter-unet3d-center-prior-v1` の `full_frame_center/best.pt`（epoch 2） | ✅ cell 3 |
| DivNet | `giorgosi/biohub-divnet-v2`。dataset は attach されるが、`DIVNET_VERIFY=0` のため重みは読み込まれない（§9） | ✅ cell 13 L1737-1739、📏 ログ `DivNet mitosis gate disabled by configuration.` |

### 4.2 処理単位

official の `predict_video` は `window_size` フレームの窓を stride `W−1` でずらし、連続する全フレーム対をちょうど 1 回ずつ処理する（✅ official L297-360）。窓ごとに UNet で特徴量を作り、その窓内の全フレーム対のエッジ予測に使い回す。TTA が有効なので、窓ごとの encode は主モデル 8 回＋副モデル 8 回になる（✅ cell 11 L209、L221）。

### 4.3 検出

| 順 | 処理 | 設定 | 出所 |
|---|---|---|---|
| 1 | **検出 TTA**: 原画像＋反転 3 通り＋90° 回転 2 通り＋転置＋反転置 = **8 方向**の検出 logit を平均 | `det_tta` | ✅ cell 11 L13-54 |
| 2 | **2 シード混合**: `(1−0.8)·主 + 0.8·副`。副も同じ 8 方向 TTA をかけ、平均と標準偏差を主に合わせてから混ぜる（標準偏差の比は 0.5〜2.0 にクリップ） | `SECONDARY_DETECTION_WEIGHT=0.80` | ✅ cell 9 L651、cell 11 L63（置換文字列内） |
| 3 | **frame retention guard**: フレームごとに、混合後の候補数が主モデル単独の 90% 未満なら、そのフレームは主モデル単独の logit を使う。E70 では 400 フレーム中 65 フレームで発動し、うち 64 は 44b6_0b24845f | `DUAL_SEED_MIN_CANDIDATE_RETENTION=0.90` | ✅ cell 11 L94-125、📏 `dual_seed_frame_retention_guard_report.json` |
| 4 | **局所最大**: `F.max_pool3d` の局所最大かつ `sigmoid > 0.965`。窓は `pool_kernel_um=3.0` からダウンサンプル格子で (3,3,3) | `DET_THRESHOLD=0.965` | ✅ cell 3、official L229-251、L283-286、📏 ログ `pool_kernel_um=3.0` |
| 5 | **座標**: ダウンサンプル格子の index に `(1,4,4)` を掛ける。**Y/X は 4 の倍数だけ**になり、int16 に丸める | — | ✅ official L494-496、📏 E67 |

重心による位置補正は使っていない（`REFINE_CENTROIDS=0`、✅ cell 3）。

### 4.4 エッジ候補のスコア

**エッジ予測の入力特徴量（edge-feature TTA）**: 窓の encode の段階で、UNet の特徴量も 8 方向 TTA の平均にする（`unet_out = _unet_acc / _nv`、フレーム対のループより前）。この特徴量が順方向・逆方向どちらのエッジ予測の入力にもなる。副モデルの特徴量は `0.25·単発 + 0.75·8 方向平均` にする。設定は `EDGE_FEATURE_TTA=1`、`SECONDARY_EDGE_FEATURE_TTA=1`、`_WEIGHT=0.75`（✅ cell 11 L206-234）。

official はフレーム対ごとに、**全 source × 全 target の組**についてエッジ logit `(n_src, n_tgt)` を出す（✅ official L407-453）。そのあと次の順で加工する。

| 順 | 処理 | 設定 | 出所 |
|---|---|---|---|
| 1 | **双方向 harmonic 融合**: 順方向と逆方向の確率を重み付き調和平均（`1/((1−w)/p_fwd + w/p_rev)`）し、正規化後に順方向の logit の中心とスケールへ戻す（スケール比は 0.5〜2.0 にクリップ） | `BIDIRECTIONAL_EDGE_WEIGHT=0.15`、`FUSION_MODE=harmonic_probability` | ✅ cell 11 L167-190 |
| 2 | **low-margin 2 シード混合**: (a) 副モデルの logit を、target 列ごとに主モデルの中心とスケールへ校正する（スケール比は 0.5〜2.0 にクリップ）。(b) target 列ごとの重みは `0.20 × clamp((0.35 − 主の margin)/0.35, 0, 1)`（margin = 親候補の softmax 確率の 1 位と 2 位の差）。(c) **主と副で最良の親が一致する列だけ**混ぜ、一致しない列の重みは 0。source が 2 未満のフレーム対も重み 0。**結果として、この混合は target ごとの最良の親を変えられない**（確率の鋭さだけを変える） | `SECONDARY_EDGE_WEIGHT=0.20`、`LINK_MODE=low_margin_consensus`、`LOW_MARGIN_MAX=0.35`、`MIX_TEMPERATURE=1` | ✅ cell 9 L645-654、cell 11 L64（置換文字列内） |
| 3 | **rank bonus**: 列（target ごと）で最良なら +β、行（source ごと）で最良なら +0.5β、相互最良ならさらに +0.5β（β=0.12 固定）を logit に足す | `RANK_BONUS=1` | ✅ cell 11 L237-295 |
| 4 | **確率化**: `softmax(dim=0)`、つまり **target ごとに親候補で正規化** | `edge_activation="softmax"`（`PredictConfig` の既定値。CLI からも config.json からも変更されず、cell 11 のパッチも触れない） | ✅ official L72、L172-200、L454-458、L646-653 |
| 5 | **閾値**: `prob > 0.48` の組を候補エッジにする。ILP を使うため、親や子の数の上限はここでは掛けない | `DUAL_SEED_EDGE_THRESHOLD=0.48` → `cfg.threshold` | ✅ cell 9 L655、cell 11 L66、official L85-93、L460-490 |

候補エッジは `(source, target, edge_prob, edge_dist)` として保存される。`edge_dist` はダウンサンプル格子の voxel 単位で、µm ではない（✅ official L482-485）。

### 4.5 ILP

| 項目 | 値 | 出所 |
|---|---|---|
| ソルバ | `td.solvers.ILPSolver` | ✅ official L555-563 |
| 目的関数の重み | エッジ `−1.0 × edge_prob`、出現 0.0、消滅 2、分裂 1.2 | ✅ cell 3、cell 7 L46-49、official L556-560 |
| **ILP 出力の分裂** | **0**（E70 の 4 本すべてで fork 0、merge 0） | 📏 E70 の生 .geff |

**→ 提出物の分裂はすべて後処理の safe-division（§5.5）が作っている。** これは偶然ではない。出現コストが 0、エッジの報酬が最大 1.0（`−1.0 × edge_prob`、prob ≤ 1）なのに対し分裂コストが 1.2 なので、目的関数が各項の線形和であれば、分裂を選ぶと必ず目的関数が悪化する。つまり**この重みでは分裂は選ばれ得ない**（⚠️ tracksdata の目的関数の形は未確認。E59・E70 の生 .geff 計 8 本で fork 0 を確認済み）。

---

## 5. 後処理段（cell 13 `filter_output_graph`、L1458-1693）

cell 13 の主ループ（L1829-1920）が .geff を読み、`nodes_by_id`（`t,z,y,x` は voxel 単位の float）と `raw_edges`（`edge_prob` つき）にして渡す。

### 5.1 段の一覧と実測

右の 2 列は全 4 本の合計（📏 `run_stats.csv`）。

| 順 | 段 | 関数・行 | E59（relink ON） | E70（relink OFF） |
|---|---|---|---:|---:|
| 0 | 入力（ILP の .geff） | L1833-1858 | node 127,379 / edge 120,665 | 同左 |
| 1 | エッジ検査 | L1529-1542 | −10 edge（14 µm 超） | −10 edge（14 µm 超） |
| 2 | motion relink | `motion_relink_edges` L543-669、呼び出し L1544-1575 | 121,295 本で置換 | 実行しない |
| 3 | 単一親の修復 | L1577-1586 | 削除 0 | 削除 0 |
| 4a | 1 フレーム欠損の補完 | `close_single_frame_gaps` L671-937 | +629 node | +740 node |
| 4b | 2 フレーム欠損の補完 | `recover_strict_gap2` L954-1101 | +294 node | +310 node |
| 5 | safe-division | `add_safe_divisions_postlink` L1104-1256 | +99 分裂（tau で 99 件却下） | +101 分裂（tau で 118 件却下） |
| 6 | 分裂の幾何フィルタ | L1635-1677 | 無効 | 無効 |
| 7 | 孤立ノードの削除 | L1679-1685 | −52 | −4 |
| 8 | 短いトラックの削除 | `filter_short_track_components` L1260-1381 | −3,421 | −3,999（救済 +119） |
| 9 | 直線当てはめ平滑化 | `linefit_smooth_output_graph` L1384-1455 | 124,821 node | 124,410 node |
| — | 出力 | L1866-1905 | **node 124,829 / edge 120,463 / 分裂 99** | **node 124,426 / edge 119,595 / 分裂 101** |

採点側（`metrics.py`）が落とす重複エッジ・非 t+1・出次数 >2・merge は、提出物では**すべて 0 件**（📏 E72）。これは cell 15 の監査（§7）が非 t+1・入次数 >1・出次数 >2 を検出すると停止するため、構造的にも保証されている（重複エッジは入次数 2 になるので同じく止まる）。

### 5.2 段 1: エッジ検査

`t_target ≠ t_source + 1` のエッジと、長さが 14 µm を超えるエッジを捨てる（`OUTPUT_ENFORCE_NEXT_FRAME=1`、`OUTPUT_EDGE_MAX_UM=14.0`）。

### 5.3 段 3: 単一親の修復

入次数が 2 以上のノードについて、`edge_sort_key` が最大のエッジを 1 本だけ残す（✅ L1577-1586）。子の数の修復（`OUTPUT_SINGLE_CHILD_REPAIR`）は既定 0 で無効。

### 5.4 段 4: 欠損の補完

**4a. 1 フレーム欠損（`close_single_frame_gaps`）**

| 手順 | 内容 |
|---|---|
| 対象 | フレーム t で終わるトラックの末端と、フレーム t+2 で始まるトラックの先頭。エッジを 1 本も持たない孤立ノードも、末端かつ先頭として含まれる（✅ L694-697） |
| 距離の上限 | `GAP_CLOSE_UM × 2 = 10 µm`。周囲 3 近傍の間隔の中央値が基準 6.5 µm より広ければ上限を広げ、狭ければ狭める（1 ステップあたり ±0.125 µm まで、`GAP_DENSITY_*`） |
| 割当 | `linear_sum_assignment` で末端と先頭を 1 対 1 に対応づける |
| 中間ノード | t+1 の孤立ノードが中点から 3.2 µm 以内にあれば再利用し、無ければ合成ノードを作る（上限: 全ノードの 5% と 2,000 個の小さい方）。再利用は E59・E70 とも 0 回（📏 `gap_reused_existing`） |
| 合成ノードの位置 | 中点のまわり（z±1, y/x±3 voxel）の輝度重心に動かす。3.2 µm を超えて動くなら中点のまま（`refine_synthetic_midpoint` L175-219） |
| DeepCenter の veto | **合成ノード**かつ**端点間が 8.5 µm 以上**のときだけ、DeepCenter heatmap の値が 0.25 未満なら取り消す。E70 では 140 件を検査して 121 件を取り消した（E59 は 121 件中 103 件） |
| **注意** | `GAP_CLOSE_MAX_GAP=2` と設定しているが、コード内で `min(GAP_CLOSE_MAX_GAP, 1)` に固定されており、**実際は常に 1**（✅ L758） |

**4b. 2 フレーム欠損（`recover_strict_gap2`）**

| 手順 | 内容 |
|---|---|
| 対象 | フレーム t で終わる末端と、t+3 で始まる先頭 |
| 条件 | 総距離 ≤ 10.2 µm かつ 1 ステップ ≤ 4.4 µm。さらに、末端の直前の動きか先頭の直後の動きの**少なくとも一方**が、補完の向きと整合すること（cos > −0.25 かつ速度差 ≤ 6 µm）。どちらの動きも無ければ却下（✅ L998-1024） |
| 選び方 | コスト `距離 + 2.0 × Σ max(0, 0.25 − cos)` の小さい順に貪欲に選ぶ（✅ L1025）。上限は全エッジの 0.45% と 180 本の小さい方。フレームごとの上限は、そのフレームの**末端の数**の 0.6%（✅ L1043） |
| 中間ノード | 1/3 と 2/3 の位置に合成ノードを 2 個置き、4a と同じ輝度重心の補正をかける |
| DeepCenter | **使わない**（4a と違い veto が無い） |

### 5.5 段 5: safe-division（提出物の分裂はすべてここから）

フレーム t ごとに次の条件をすべて満たす組を分裂として追加する（✅ L1104-1256）。

| 順 | 条件 | 値 |
|---|---|---|
| 1 | 親は子を 1 つだけ持ち、その子（既存の子）は t+1 にいて距離 ≤ 10 µm | `SAFE_DIV_EXISTING_CHILD_MAX_UM=10.0` |
| 2 | 親はトラックの途中にある（親自身に入ってくるエッジがある） | — |
| 3 | 候補（新しい子）は t+1 の「入ってくるエッジが無い」ノードで、親から 9 µm 以内 | `SAFE_DIV_MAX_UM=9.0` |
| 4 | 候補は、既存の子から見て**最も近い**親なしノードで、その距離（姉妹間距離）≤ 14 µm | `SAFE_DIV_SISTER_MAX_UM=14.0` |
| 5 | DeepCenter heatmap の候補位置の値 ≥ 0.25 | `DEEPCENTER_SAFE_DIV_THRESHOLD=0.25` |
| 6 | 姉妹が t+2 でどちらも 1 本だけ続き、t+2 での距離が t+1 より 2.25 µm 以上広がる | `SAFE_DIV_DIVERGE_UM=2.25` |
| 7 | **姉妹の非対称 veto（E56）**: `|d(親,既存の子) − d(親,候補)| / 平均 > 0.6` なら却下 | `SAFE_DIV_SISTER_SYMMETRY_TAU=0.6` |
| 8 | スコア `d(親,候補) + 0.15·姉妹間距離` の小さい順に採用。上限はフレームごとに親候補数の 0.76%、全体で全エッジの 0.375% | `SAFE_DIV_FRAME_FRAC_CAP`、`GLOBAL_FRAC_CAP` |

コードの注意点:
- 条件 4 の変数名は `_mutual` だが、実際は**片方向**の最近傍しか見ていない（✅ L1182-1188）。
- `SAFE_DIV_REQUIRE_DIVERGENCE` と `SAFE_DIV_REQUIRE_MUTUAL_NN` は cell 7 で読まれるが、この関数では使われず、条件 4・6 は常にかかる（✅ cell 7 L128-129 と本関数）。
- `safe_division_geometric_candidates` と `safe_division_mutual_nn_rejected` / `divergence_rejected` は、どこでも加算されない。そのためログに表示される `deepcenter_rejected=` は `0 − 採用候補数` の負の値になり、意味が無い（✅ L1623-1633）。
- ただし `run_stats.csv` の `deepcenter_safe_div_checked/rejected/accepted` は正しく数えられている。E70 では 5,348 件を検査して 4,116 件を却下（E59 は 4,804 件中 3,597 件）。**safe-division の最大の却下要因は DeepCenter** で、tau の却下（118 件）の約 35 倍（📏）。

### 5.6 段 6-9

| 段 | 内容 | 出所 |
|---|---|---|
| 6 分裂の幾何フィルタ | `OUTPUT_DIVISION_GEOMETRY_FILTER` が既定 0 なので**実行されない**。DivNet はこの中でしか呼ばれない | ✅ L1635-1677 |
| 7 孤立ノードの削除 | エッジを 1 本も持たないノードを消す | ✅ L1679-1685 |
| 8 短いトラックの削除 | 弱連結成分のノード数が 6 未満なら消す（分裂を含む成分は残す）。削除が全体の 10% 以上になった動画だけ救済: 長さ 4〜5 で、平均 `edge_prob` ≥ 0.88、平均エッジ長 ≤ 3.0 µm の成分を、スコア順に予算（全ノードの 1.2% と 120 個の小さい方）まで戻す | ✅ L1260-1381 |
| 9 直線当てはめ平滑化 | 各ノードについて前後 2 フレーム（分岐しない範囲）で 1 次式を当てはめ、元の位置と `0.2·元 + 0.8·当てはめ` で混ぜる。グラフの形は変えない | ✅ L1384-1455 |

**段 8 の救済の発動**: 救済は削除が 10% 以上の動画でだけ発動する（✅ L1318）。E59 では 4 本とも発動しなかった（最大の 44b6_0b24845f でも 2,179 / 23,857 = 9.13%）。E70 では同じ動画が 10.24% になって発動し、予算 120 に対して 119 node を戻した（📏 `run_stats.csv`）。発動した後の選別には `edge_prob` を使うため、relink ON（motion relink が付けた学習確率、無ければ 0）と OFF（ILP の .geff の確率）では選ばれる成分も変わりうる。

### 5.7 DeepCenter veto の共通動作

| 項目 | 内容 | 出所 |
|---|---|---|
| heatmap | フレームを Y/X 方向に 4 分の 1 に平均プーリング → 百分位で正規化 → UNet3D → sigmoid。直近 8 フレーム分をキャッシュ | ✅ L434-478 |
| 点の評価 | 点のまわり（z±1、y/x±2 のプーリング後の格子）の最大値 | ✅ L481-506 |
| **失敗時** | モデルが無い・値が取れない場合は**受け入れる**（fail-open）。ただし `REQUIRE_DEEPCENTER_VETO=1` のため、モデルが読めなければ起動時に停止する | ✅ L509-533 |
| TTA | `DEEPCENTER_TTA=0` で無効（E57 で試し、採用していない） | ✅ cell 3、L455-472 |

---

## 6. motion relink（E70 の因子）の詳細

### 6.1 処理（`motion_relink_edges`、L543-669）

- **ILP のエッジを使わない。** 全ノードをフレームごとに `linear_sum_assignment` で 1 対 1 に割り当て直す。ILP の確率はコストの bonus として入るだけ。
- コスト = `|target − 予測位置| + 0.05·|target − source| − bonus·prob`。予測位置は、直前に割り当てた親からの速度に `velocity_weight` を掛けて外挿する。
- まず 6 µm で割り当て（tight）、残りを 10 µm で割り当てる（relaxed）。
- 1 対 1 なので、段 2 の出力自体には分裂が無い（ILP の出力にも無い）。分裂数の差（99 → 101）は、段 5 の入力（親なしノードの集合）が変わることから生じる（§6.3）。
- 1 フレームのノードが 2,600 を超える動画ではスキップし、ILP のエッジのまま進む。

### 6.2 OFF にすると一緒に無効になるもの

| 機構 | 理由 | 出所 |
|---|---|---|
| density group の上書き（E59） | `if OUTPUT_MOTION_RELINK:` ブロックの中でしか読まれない | ✅ L1544-1575 |
| `MOTION_RELINK_LEARNED_BONUS` / `VELOCITY_WEIGHT` / `TIGHT_UM` / `RELAXED_UM` | 同上 | ✅ |

density group は、1 フレームあたりの平均ノード数が 120 未満なら low、400 未満なら middle、それ以上なら high。ON のときは `velocity_weight` と `learned_bonus` だけがグループごとに変わる（`tight_um` / `relaxed_um` は表示されるが適用されない。公開 0.951 と同じ、✅ L1-26、L1560-1569）。

**→ E70 は実質「E56 − motion relink」。**

### 6.3 ON/OFF の差が伝わる経路

OFF にすると、段 2 が変わるだけでなく、段 4〜9 の入力も変わる。

| 段 | 変化（E59 → E70、4 本合計） | 理由 |
|---|---|---|
| 4a 1 フレーム補完 | +629 → +740 node | ILP は途切れたトラックを多く残す（relink は全ノードをつなぎ直す） |
| 5 safe-division | 分裂 99 → 101、tau の却下 99 → 118 | 親なしノードの集合が変わる |
| 8 短トラック削除 | −3,421 → −3,999、救済 0 → +119 | 同上。救済が発動するかどうかも変わる |

---

## 7. 出力と監査

| 項目 | 内容 | 出所 |
|---|---|---|
| CSV の列 | `id,dataset,row_type,node_id,t,z,y,x,source_id,target_id`。node 行の source/target は −1、edge 行の node 列は −1 | ✅ L28-29、L1860-1897 |
| 座標 | `max(0, round(値))` の整数で書く | ✅ L1873-1875 |
| 書き込み時の検査 | dangling edge、データセットの過不足、行カウンタの不一致、ヘッダの不一致があれば停止 | ✅ L1887、L1922-1929 |
| cell 15 の監査 | 書き終えた CSV を読み直し、列・id の連番・行種別・データセット集合・retention guard のログを検査する。さらに**グラフの形**も検査し、エッジが t→t+1 でない、入次数 >1、出次数 >2、座標が負、のどれかがあれば停止する | ✅ cell 15 L65-94 |
| 監査レポートの注意 | cell 15 が書く `dual_seed_frame_retention_guard_report.json` の `configuration` ブロックは**ハードコードされた古い値**（`detector_threshold: 0.96875`、`ilp_disappearance_weight: 1.5`、`gap_close_um: 5.8`）で、実際の設定（0.965 / 2 / 5.0）と違う。実際の設定は cell 21 の manifest と cell 5 の guard を見る。同じ JSON の `diagnostics`（retention guard の発動数）は実測値として使える | ✅ cell 15 L136-148、cell 3 |
| run_stats.csv | 動画ごとの全カウンタと予測時間 | ✅ L1899-1933 |

---

## 8. validator（計測系、cell 17-19）

### 8.1 構成

| 項目 | 内容 | 出所 |
|---|---|---|
| 動画の選び方 | train を embryo の接頭辞（44b6 / 6bba）ごとに分け、「GT に分裂がある」動画を優先して名前順に `VALIDATOR_N_PER_TYPE` 本ずつ選ぶ。6 本ずつで計 12 本 ＝ eval12 と同じ集合 | ✅ cell 17 L10-54、✅ 台帳 L8069-8071 の eval12 と `validator_results.csv` の stem 集合が完全一致 |
| test との重複除外 | `TEST_DIR` にある stem は除外する | ✅ cell 17 L13-17 |
| 予測 | 本番と同じ予測コマンドを、method 名 `unet_transformer_val` で実行 | ✅ cell 17 L131 |
| 後処理 | **本番と同じ `filter_output_graph`**。フレームを読むために `TEST_DIR` を一時的に `TRAIN_DIR` に差し替え、終わったら必ず戻す | ✅ cell 19 L355-368 |
| submission.csv への影響 | なし（CSV を書いて監査した後に実行する） | ✅ |

### 8.2 採点器は公式の再実装（重要）

**cell 19 は `official/src/tracking_cellmot/metrics.py` を import していない。** notebook 内に独自の採点器がある（✅ cell 19 L1-300）。

| 部分 | 公式との関係 | 評価 |
|---|---|---|
| ノード対応 | フレームごとに µm 距離で `linear_sum_assignment`、7 µm で打ち切り | 公式（tracksdata の `DistanceMatching`）と同等と思われるが ⚠️ 未検証 |
| edge の TP/FP/FN | 「source が対応する GT ノードに出るエッジがある、または target が対応する GT ノードに入るエッジがある」ものを FP の対象にする | 公式の `pred_valid` と同じ論理。公式の前処理（重複・非 t+1・merge・出次数 >2）は提出物では 0 件なので影響しない（📏 E72） |
| adj と集計 | `w=TP+FP+FN` の加重平均、`T_true` は GT の `estimated_number_of_nodes` | 公式と同じ式 |
| **division** | 弱連結成分を使った独自の判定（GT の姉妹の子孫が、GT 分裂の親と同じ予測成分に入り、その成分に fork があれば TP） | **公式と別物**。公式は窓単位の対応＋4 種類の FP 規則（`competition_spec.md` §7.2） |

**影響**: E71 で「実パイプラインの division 5/5/13 とローカル port の 3/10/15 の差は、tau veto の有無と整合する」と書いたが、2 つの数字は**別の採点器**で出している（ローカルは公式の `division_metrics.py`）。**差がどこから来たか（tau veto か採点器か）は切り分けられていない。** edge 側の比較（0.920452 と 0.918091）は同じ論理の採点器なので比較できる可能性が高いが、ノード対応の同等性は未検証。

---

## 9. 効いていない設定（読まれるが結果に影響しない）

| 設定 | 状態 | 理由 | 出所 |
|---|---|---|---|
| DivNet（`DIVNET_VERIFY=0`、`DIV_MIN_PROB`） | 死んだコード | 段 6 が既定 0 で実行されず、DivNet はその中でしか呼ばれない。公開 0.951 でも同じ | ✅ L1635-1677、📏 E58（CSV が E56 と完全一致） |
| `DENSITY_GROUP_OVERRIDES=1` | OFF では無効 | §6.2 | ✅ |
| `GAP_CLOSE_MAX_GAP=2` | 実際は 1 | コード内で 1 に固定 | ✅ L758 |
| `SAFE_DIV_REQUIRE_DIVERGENCE`、`SAFE_DIV_REQUIRE_MUTUAL_NN` | 無視される | 条件は常にかかる | ✅ §5.5 |
| `DENSITY_GROUP_OVERRIDES` の `tight_um` / `relaxed_um` | 適用されない | 公開 0.951 と同じ | ✅ L1560-1569 |
| `DEEPCENTER_TTA=0` | 無効 | E57 で試し、採用していない | ✅ cell 3 |
| `REFINE_CENTROIDS=0` | 無効 | Discussion で公開 LB −0.002 の報告 | ✅ cell 3 |
| `RUN_OUTPUT_DIAGNOSTICS=0` | 無効 | — | ✅ cell 3 |

---

## 10. ローカル検証環境との違い

| 項目 | 提出パイプライン | ローカル（`src/biohub/public_postproc/`＋ローカル予測） | 出所 |
|---|---|---|---|
| 姉妹の非対称 veto（tau） | あり（0.6） | **なし**（`SYMMETRY_TAU` の出現 0 件） | ✅ grep |
| edge-feature TTA | あり | **なし** | ✅ grep |
| rank bonus | あり | **なし** | ✅ grep |
| 採点器 | notebook 内の再実装（§8.2） | 公式 `metrics.py` / `division_metrics.py` | ✅ |
| eval12 の adj edge（base） | 0.920452 | 0.918091 | 📏 E71 |
| eval12 の division（base） | 5/5/13（再実装の採点器） | 3/10/15（公式の採点器） | 📏 E71。**採点器が違うため比較できない** |
| base → off の adj の Δ | +0.023468 | +0.023214 | 📏 E71 |

**運用ルール**: 採否の判定には、提出 notebook の validator の **adj edge** を使う。division は、公式の採点器で採点し直すまで判定に使わない。ローカルの値は予備スクリーニングにだけ使う。

---

## 11. 既知のリスクと未確認事項

| 項目 | 内容 |
|---|---|
| embryo をまたぐ汎化 | どの測定系でも測れない。E26 では同じ因子がローカル +0.021 → LB −0.002 |
| 最悪の動画 | OFF は 44b6_12dfb391 で −0.002388。採用ゲート (e) を 0.0004 差で満たさない（📏 E71） |
| validator の division | 公式と別の判定（§8.2）。公式で採点し直すには、validator の後処理済みグラフを保存する必要がある（現在は生の .geff だけが残る） |
| 実行時間 | 可視 test 4 本でカーネル全体 40.83 分（E70）。hidden test では動画数が増えるため、単純な外挿では 12 時間に収まる保証は無い。同じ経路の E59 などが hidden test で採点まで完了していることが、現状で唯一の根拠（§2） |
| ⚠️ 未確認 | ILP の制約の細部（tracksdata 側）、主・副・DeepCenter の学習条件、tracksdata の `DistanceMatching` と validator のノード対応が同じか |
