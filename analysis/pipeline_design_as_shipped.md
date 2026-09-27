# 提出パイプライン設計書（現状の書き起こし）

**最終更新: 2026-09-27**

この文書は**いま提出しているもの（`notebooks/pub923_repro/pub923_repro.ipynb`）の現状の設計**を書き起こしたもの。
新しい設計の提案ではない。仕様は `analysis/competition_spec.md`、計画は `analysis/endgame_plan_20260927.md`、
採否の記録は `analysis/experiment_ledger.md` を参照し、ここには重複させない。

- 対象の状態: notebook の commit `ba5480d`（E71-B）＝ **E70 提出物（`1a0c71f`、kernel v15）に validator 計測（`VALIDATOR_N_PER_TYPE=6`）を足しただけ**。`submission.csv` は E70 と同一。
- 確度表記: ✅ コードで確認（cell 番号と行番号つき） ／ 📏 実行ログや出力で実測 ／ ⚠️ 未確認
- cell 番号は notebook の 0 始まり、行番号はその cell の source 内の行。

---

## 1. 全体の流れ

```text
test/*.zarr
  │
  ├─[cell 9]  オフラインの依存関係とモデル成果物を解決・sha256 で検証
  ├─[cell 11] official の predict_unet_transformer.py を文字列置換で改造して、GPU 2 枚で分割実行
  │     検出（8 方向 TTA、2 シード混合、frame retention guard）
  │     → エッジ候補のスコア（双方向 harmonic 融合 → 2 シード low-margin 混合 → edge-feature TTA → rank bonus）
  │     → ILP（tracksdata）→ 動画ごとの .geff
  ├─[cell 13] .geff → filter_output_graph（後処理 9 段）→ submission.csv
  ├─[cell 15] submission.csv の独立監査（スキーマ・id 連番・データセット一致・retention guard の記録）
  ├─[cell 17-19] validator: train の 12 本で同じパイプラインを回し、公式指標で採点（計測のみ）
  └─[cell 21] 全機構の実際の状態を表示（manifest）
```

---

## 2. 設定と防護（cell 3・5・7）

| 項目 | 内容 | 出所 |
|---|---|---|
| 設定の書き方 | すべて `os.environ["BIOHUB_*"]` に文字列で入れる | ✅ cell 3 |
| 設定を読む場所 | 主に cell 7 L43-151 で `os.environ.get(名前, 既定値)`。一部は cell 9 L644-655 と cell 11 のパッチ内で読む | ✅ |
| **既定値の罠** | cell 3 で設定しなかった変数は **cell 7 の既定値**になる。E70 以前の `OUTPUT_MOTION_RELINK` は未設定なので既定値 `"1"`（ON）だった | ✅ cell 7 L65 |
| Configuration guard | cell 5 の `_EXPECTED_TEXT` と実際の環境変数を突き合わせ、違えば停止。現在 26 キー | ✅ cell 5 |
| パッチの防護 | cell 11 の置換はすべて「置換元が 1 か所だけにあること」と「置換結果が残っていること」を確認し、違えば `RuntimeError` | ✅ cell 11 L54-295 |
| 無効化の防護 | rank bonus は最初に掛けた bonus が全ゼロなら `RANK_BONUS_NO_OP` で停止 | ✅ cell 11 L262-266 |

---

## 3. 予測段（cell 9・11）

### 3.1 モデル

| 役割 | 成果物（Kaggle dataset） | 出所 |
|---|---|---|
| 主モデル（検出＋エッジ予測） | `pilkwang/biohub-tracking-support-pack-50ep-v1` の `weights/unet_transformer/split_0/edge_predictor_best.pth` | ✅ cell 7 L34-36 |
| 副モデル（2 シード目） | `pilkwang/biohub-temporal-unet3d-seed314159-v1` | ✅ kernel-metadata.json、cell 9 L573-644 |
| DeepCenter（後処理の veto） | `pilkwang/biohub-deepcenter-unet3d-center-prior-v1` の `full_frame_center/best.pt`（epoch 2） | ✅ cell 3 |
| DivNet | `giorgosi/biohub-divnet-v2`。**読み込むが使っていない**（§6） | ✅ |

### 3.2 検出

| 段 | 処理 | 設定 | 出所 |
|---|---|---|---|
| 検出 TTA | 反転 3 通り＋90° 回転 2 通り＋転置 2 通り＋原画像 = **8 方向**の logit 平均 | `det_tta` | ✅ cell 11 L13-54 |
| 2 シード混合 | 検出 logit を `0.2·主 + 0.8·副` で混ぜる | `SECONDARY_DETECTION_WEIGHT=0.80` | ✅ cell 9 L651 |
| frame retention guard | 混合後の候補数が主モデル単独の **90% 未満**になったフレームは主モデル単独に戻す | `DUAL_SEED_MIN_CANDIDATE_RETENTION=0.90` | ✅ cell 11 L84-125 |
| ピーク抽出 | `F.max_pool3d` の局所最大かつ `sigmoid > 0.965` | `DET_THRESHOLD=0.965` | ✅ cell 3、official L283-286 |
| 座標 | ダウンサンプル格子の index × `(1,4,4)`。**Y/X は 4 の倍数のみ** | — | ✅ official L494-496、📏 E67 |
| 重心の補正 | 使っていない | `REFINE_CENTROIDS=0` | ✅ cell 3 |

### 3.3 エッジ候補のスコア（適用順）

| 順 | 処理 | 設定 | 出所 |
|---|---|---|---|
| 1 | **双方向 harmonic 融合**: 順方向と逆方向の確率を重み付き調和平均し、順方向の logit スケールに合わせて戻す | `BIDIRECTIONAL_EDGE_WEIGHT=0.15`、`FUSION_MODE=harmonic_probability` | ✅ cell 11 L167-190 |
| 2 | **2 シードの low-margin 混合**: 主モデルの margin が小さい候補だけ副モデルの logit を混ぜる | `SECONDARY_EDGE_WEIGHT=0.20`、`LINK_MODE=low_margin_consensus`、`LOW_MARGIN_MAX=0.35` | ✅ cell 9 L645-654、cell 11 L59-78 |
| 3 | **edge-feature TTA**: エッジ特徴も TTA 平均（主 1.0、副 0.75） | `EDGE_FEATURE_TTA=1`、`SECONDARY_EDGE_FEATURE_TTA=1`、`_WEIGHT=0.75` | ✅ cell 11 L206-234 |
| 4 | **rank bonus**: 列で最良なら +β、行で最良なら +0.5β、相互最良ならさらに +0.5β（β=0.12 固定） | `RANK_BONUS=1` | ✅ cell 11 L237-295 |
| 5 | 候補の閾値 | `DUAL_SEED_EDGE_THRESHOLD=0.48` を `cfg.threshold` に代入 | ✅ cell 9 L655、cell 11 L66 |

### 3.4 ILP

| 項目 | 値 | 出所 |
|---|---|---|
| 重み | edge −1.0、出現 0.0、消滅 2、分裂 1.2 | ✅ cell 3、cell 7 L46-49 |
| **ILP 出力の分裂数** | **0**（4 本とも fork 0、merge 0） | 📏 E70 の生 .geff |

**→ 提出物の分裂はすべて後処理の safe-division 段が作っている（§4 の 5）。**

---

## 4. 後処理段（cell 13 `filter_output_graph`、L1458-1693）

動画ごとに .geff を読み（L1833-1858）、次の順で処理する。右 2 列は全 4 本の合計（📏 `run_stats.csv`）。

| 順 | 段 | 内容 | 主な設定 | E59（ON） | E70（OFF） |
|---|---|---|---|---:|---:|
| 0 | 入力 | ILP の .geff | — | node 127,379 / edge 120,665 | 同左 |
| 1 | エッジ検査 | t+1 以外と 14 µm 超を削除 | `OUTPUT_EDGE_MAX_UM=14.0` | — | — |
| 2 | **motion relink** | §5。ON なら**エッジ集合を丸ごと置き換える** | `OUTPUT_MOTION_RELINK` | 121,295 本で置換 | **実行しない** |
| 3 | 単一親の修復 | 入次数 >1 のノードで最良 1 本だけ残す | `OUTPUT_SINGLE_PARENT_REPAIR=1` | 削除 0 | 削除 0 |
| 4a | 1 フレーム欠損の補完 | 欠けたフレームに合成ノードを入れる。DeepCenter の heatmap で veto | `GAP_CLOSE_*`、`DEEPCENTER_GAP_*` | +629 node | +740 node |
| 4b | 2 フレーム欠損の補完 | 厳しい条件で 2 フレーム欠損をつなぐ | `OUTPUT_GAP2_RECOVERY=1` | +294 node | +310 node |
| 5 | **safe-division** | 幾何条件 → DeepCenter veto → 姉妹の非対称 veto（tau=0.6）→ 上限。**提出物の分裂はこれが全部** | `SAFE_DIV_*`、`DEEPCENTER_SAFE_DIV_*` | +99（tau で 99 件却下） | +101（tau で 118 件却下） |
| 6 | 分裂の幾何フィルタ | **既定で OFF**（DivNet はこの中でしか呼ばれない） | `OUTPUT_DIVISION_GEOMETRY_FILTER` 未設定→0 | 無効 | 無効 |
| 7 | 孤立ノードの削除 | エッジを持たないノードを削除 | `OUTPUT_PRUNE_ISOLATED=1` | −52 | −4 |
| 8 | 短いトラックの削除 | 長さ 6 未満の成分を削除（分裂を含む成分は残す）。削りすぎたら救済 | `OUTPUT_MIN_TRACK_LEN=6`、`ADAPTIVE_SHORT_TRACK_RESCUE=1` | −3,421 | −3,999（救済 +119） |
| 9 | 直線当てはめ平滑化 | 前後 2 フレームの直線で座標を 0.8 の重みで寄せる | `OUTPUT_LINEFIT_*` | 124,821 node | 124,410 node |
| — | 出力 | 座標を四捨五入して CSV に書く。dangling edge は停止 | — | **node 124,829 / edge 120,463 / 分裂 99** | **node 124,426 / edge 119,595 / 分裂 101** |

採点側（`metrics.py`）が落とす重複・非 t+1・出次数 >2・merge は、提出物では**すべて 0 件**（📏 E72）。

---

## 5. motion relink（E70 の因子）

`motion_relink_edges`（cell 13 L543-669）の処理:

- **ILP のエッジを使わない。** 全ノードをフレームごとに `linear_sum_assignment` で 1 対 1 に割り当て直す。ILP の確率は bonus としてコストに入るだけ。
- コスト = `|target − 予測位置| + 0.05·|target − source| − bonus·prob`。予測位置は直前の速度 × `velocity_weight` で外挿する。
- 6 µm の tight pass で割り当て、残りを 10 µm の relaxed pass で割り当てる。
- **1 対 1 なので分裂は作れない。** ただし ILP も分裂 0 なので、ON/OFF で分裂の扱いは変わらない。
- 1 フレームのノードが 2,600 を超える動画ではスキップする。

**OFF にすると連動して無効になるもの**（どちらも motion relink の中でしか使われない）:

| 機構 | 理由 | 出所 |
|---|---|---|
| density group の上書き（E59） | `if OUTPUT_MOTION_RELINK:` ブロックの中でしか読まれない | ✅ cell 13 L1544-1575 |
| `MOTION_RELINK_LEARNED_BONUS` / `TIGHT_UM` / `RELAXED_UM` | 同上 | ✅ |

**→ E70 は実質「E56 − motion relink」。** ON/OFF の差は §4 の 2 段目だけでなく、その後の 4〜9 段の入力が変わることでも生じる（補完 +111 node、短トラック削除 +578 など）。

---

## 6. 効いていない設定（読まれるが結果に影響しない）

| 設定 | 状態 | 理由 | 出所 |
|---|---|---|---|
| DivNet（`DIVNET_VERIFY`、`DIV_MIN_PROB`） | 死んだコード | `OUTPUT_DIVISION_GEOMETRY_FILTER` が既定 0 で、DivNet はその中でしか呼ばれない。公開 0.951 でも同じ | ✅ cell 13 L1635-1678、📏 E58（CSV が E56 と完全一致） |
| `DENSITY_GROUP_OVERRIDES=1` | OFF では無効 | §5 | ✅ |
| `DEEPCENTER_TTA=0` | 無効 | E57（0.945）で採用していない | ✅ cell 3 |
| `REFINE_CENTROIDS=0` | 無効 | Discussion で公開 LB −0.002 の報告 | ✅ cell 3 |
| `OUTPUT_SINGLE_CHILD_REPAIR` | 既定 0 | — | ✅ cell 7 L63 |
| `RUN_OUTPUT_DIAGNOSTICS=0` | 無効 | — | ✅ cell 3 |

---

## 7. 監査と validator（cell 15・17-19）

| cell | 役割 | submission.csv への影響 |
|---|---|---|
| 15 | submission.csv を読み直し、列・id 連番・行種別・データセット集合・retention guard のログを検査 | 読むだけ |
| 17 | train から `VALIDATOR_N_PER_TYPE` 本ずつ選ぶ（6 → 12 本＝eval12 と同じ集合）。**TEST_DIR にある stem は除外** | なし（書き込み後に実行） |
| 19 | 公式指標（7 µm、w 加重）で採点 | なし |

**限界**: validator は train の同じ 2 embryo で採点する。**hidden test は別 embryo** なので、embryo をまたいだ汎化は測れない。

---

## 8. ローカル検証環境との違い（パリティ）

| 項目 | 提出パイプライン | ローカル（`src/biohub/public_postproc/`＋ローカル予測） | 出所 |
|---|---|---|---|
| 姉妹の非対称 veto（tau） | あり（0.6） | **なし**（`SYMMETRY_TAU` の出現 0 件） | ✅ grep |
| edge-feature TTA | あり | **なし** | ✅ grep |
| rank bonus | あり | **なし** | ✅ grep |
| eval12 の adj edge（base） | **0.920452** | 0.918091 | 📏 E71 |
| eval12 の division（base） | **5/5/13** | 3/10/15 | 📏 E71 |
| base → off の Δ | **+0.023468** | +0.023214 | 📏 E71 |

**運用ルール**: 採否の判定には、提出 notebook の validator（cell 17-19）の値を使う。ローカルの値は予備スクリーニングにだけ使う。

---

## 9. 既知のリスクと未確認事項

| 項目 | 内容 |
|---|---|
| embryo をまたぐ汎化 | どの測定系でも測れない。E26 では同じ因子がローカル +0.021 → LB −0.002 |
| 最悪の動画 | OFF は 44b6_12dfb391 で −0.002388。採用ゲート (e) を 0.0004 差で満たさない（📏 E71） |
| 実行時間 | 約 41 分 / 12 時間。hidden test の規模でも余裕あり（📏 E70 40.83 分） |
| ⚠️ 未確認 | ILP の制約の細部（official 側）、副モデルの学習条件、DeepCenter の学習条件、`close_single_frame_gaps`・`recover_strict_gap2`・`add_safe_divisions_postlink` の内部の分岐（この文書では入出力と設定だけ確認） |
