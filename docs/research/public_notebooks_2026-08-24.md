# 公開ノートブック調査レポート — biohub-cell-tracking-during-development

作成 2026-08-24 / 対象: 34 カーネル（≥60 votes を全数 + 高 LB 数本）を `kaggle kernels pull` して読解。リポジトリは読み取りのみ、push/submit なし。

---

## 0. 先に確定した事実（ここが判断の土台）

| 項目 | 値 | 出所 |
|---|---|---|
| 実行時間上限 | **CPU/GPU ノートブック 12 時間**、インターネット **無効**、外部公開データ・学習済みモデルは可 | 公式 Code Requirements ページ |
| hidden test 規模 | train と同程度。**train = 199 本**（`6bba` 128 / `44b6` 71） | data-description + `data/manifest.csv` 実測 |
| ⇒ 1 動画あたり予算 | **12h / 199 ≈ 217 秒** | 上記から計算 |
| public test 4 本 | train のコピー。LB は全部 hidden | data-description |
| **division メトリクスの exploit は主催者がパッチ済み** | 2026-07-18 公表 → 07-23 **全提出リスコア完了** | Discussion #727154 / #728324（主催 thibautgoldsborough） |

**最重要**: 「hub ノード + 偽 fork」ハックは**もう効かない**。主催者説明では、パッチ後は弱連結でなく**強連結の parent→2 daughter を 7 µm 以内で要求**するため、遠方の偽 fork は **TP ではなく FP に計上される**。つまり今そのセルをコピーすると **score が下がる**。votes 上位に残っているハック NB は、この歴史的経緯を知らずに踏む罠。

---

## 1. ハック系の正体（コピー厳禁リスト）

5 本が**同一のコピペブロック**（`submission_clean.csv` を書いた後に走る "CELL 6"）を持つ。機序は完全に同一:

```python
MAX_COMPONENTS, FORKS = 3400, 32          # NB により 1200〜3400 / 5〜32
new_nodes = [row(ds,"node",hub_id, -1000, -10000,-10000,-10000)]   # t<0 かつ体積外
new_edges = [row(ds,"edge", s=hub_id, tg=root) for root in roots]  # out-degree 数千
for i in range(FORKS):                     # divider→child + divider→continuation の偽分裂鎖
    time = -999 + 2*i
```

| NB | votes | FORKS / MAX_COMPONENTS | 判定 |
|---|---|---|---|
| `kaiwalyaatulraut/biohub-cell-tracking-solution` | **210** | 20 / 3000 | **metric-exploit**（無条件実行） |
| `kirneo/metric-hack-last-call-update` | 126 | 32 / 3400 | metric-exploit |
| `boristown/dark-agi-biohub-cell-tracking-solution` | 97 | — / 1200（V8→V9 で LB 探りながら調整） | metric-exploit |
| `outwrest/metric-hack-minimal-baseline-tta-2gpu` | 83 | 4 / — | metric-exploit |
| `amanatar/improved-metric-hack-last-call` | 74 | 5 / — | metric-exploit |
| `kaiwalyaatulraut/biohub-competition-solution` | 67 | 5 / 1400 | metric-exploit |
| `yoikoarmor/biohub-modular-last-call-turned` | 65 | 4 / — | metric-exploit |
| `xiaoleilian/biohub-ct-mix-divaug` | **237** | 5 / 1400 | **本体は CLEAN、最終セルだけ metric-exploit**（`FORKS=5`、著者自ら "METRIC EXPLOIT" と明記、`VAL 0.8388 → 0.9203 (+0.0815)` と記録）。**セル 0–3 だけ使えば完全にクリーン** |

補足: `boristown/agi-biohub-cell-tracking`(72) は同じ配布群だがハック**なし**。votes だけで判断すると取り違える。

**副作用の実測証拠**: boristown の changelog に `V9: 减少虚拟Hub连接边以降低Edge FP`（hub の辺を減らして Edge FP を下げる）とある。つまり hub→root 辺はパッチ前から**すでに edge FP として課金されていた**。

---

## 2. クリーン系ノートブックの詳細

全て `enable_internet=false`。学習済み重みは Kaggle データセット添付（全て公開・DL 可を実際に確認済み）。

### 2-A. 学習系の共通土台（ほぼ全ての 0.89〜0.92 が同一系譜）

公式ベースライン `royerlab/kaggle-cell-tracking-competition` の `TemporalUNet3D`（検出）+ `SimpleNodeTransformer`（辺確率）+ **ILP**（`tracksdata` → `pyscipopt`/SCIP）。

共有パラメータ（`predict_unet_transformer.py` を実際にダウンロードして確認）:
- 前処理: クリップ内 **0.1%/99.9% 分位**で正規化、`clamp(0)`、空間 downsample **(1,4,4)** → 64³
- 検出: `_detect_cells_pooled` = `max_pool3d` 局所最大 & `sigmoid > det_threshold`。NMS 半径は `pool_kernel_um=3.0` を軸ごとに voxel 化（pooled グリッドでは実効 (3,3,3) ≈ 4.9 µm）
- `det_threshold` 既定 **0.99**（疎 GT ゆえ検出器は未較正、公式 NB のコメントに「0.5 は低すぎ、掃引で ~0.99 が最良」）
- ILP: `edge=-1.0, appearance=0.1, disappearance=0.1, division=1.0`（公式既定）。制約 `deg⁻≤1, deg⁺≤2, t_j=t_i+1`

| NB | votes | 申告 LB | 添付データセット | 判定 | 特記 |
|---|---|---|---|---|---|
| `thibautgoldsborough/unet-baseline-inference-submission` | 81 | ILP で **~0.73→0.79**（コメント） | `thibautgoldsborough/cellmot-baseline-artifacts`（repo+重み+wheels 同梱） | CLEAN | **公式・全 10 セル。最小経路** |
| `yusuketogashi/clean-approach-lightweight-local-cv-no-hack` | 194 | **clean baseline 0.908**（パッチ後と明記） | `pilkwang/biohub-tracking-support-pack-50ep-v1` のみ | **CLEAN・自己監査あり** | **公式指標のローカル再実装 + fixed-8 CV**（基準 `0.879219745`）。out-of-volume 検出器に**合成攻撃の自己テスト**を仕込み「発火しなければ AssertionError」。papermill 実測 **2313.5 秒 / 12 本** |
| `yusuketogashi/no-hack-biohub-cell-another-approch-3rd` | 149 | clean 0.915 参照・自身は未計測 | 上 + seed314159 + ranker | CLEAN・**hard 監査ゲート** | dual-seed + 双方向 harmonic + 22 特徴の MLP ranker + 前方加速度 lookahead |
| `yusuketogashi/lb897-baseline` | 158 | 0.897（別 NB からの継承値） | pack50 + cellmot-artifacts | CLEAN（構造上）だが**監査なし** | `min_track_len=7`、1 データセットのみ 6 に緩和 |
| `pilkwang/biohub-cell-tracking-learned-graph-w-gap-recovery` | 195 | 記載なし | pack50 | CLEAN | `det=0.985`、gap 5.75 µm、safe-div 4.5/6.8/7.3 µm |
| `pilkwang/biohub-cell-tracking-two-seeds-logit-blend` | 192 | 記載なし | pack50 + seed314159 + deepcenter | CLEAN | **dual-seed 0.475**、密度適応 gap、DeepCenter add-only veto、重み **SHA256 ピン** |
| `pilkwang/biohub-cell-tracking-blend-preprocessings` | 155 | 記載なし | pack50 + deepcenter(不使用) | CLEAN | 実体は**前処理でなく D4 8-view TTA**（検出 + 辺 logit 両方） |
| `yaroslavkholmirzayev/...-v4-unet-ilp-reproduction` | 130 | 記載なし（team best 0.899） | pack50 のみ | CLEAN | 修復が最も体系的。**非対称な学習型 edge veto**（除去専用・上限 1%） |
| `yunusgmsoy/lb-0-920-...-v17` / `kimi-notebook-v17` | 26 / 107 | タイトル 0.920 だが**コード内は 0.913→0.915**。**0.920 の根拠はコード内に無い（未確認）** | pack50 + seed314159 + deepcenter | CLEAN・自己監査 | 2 本の差は safe-div 半径 5 定数のみ（kimi 側は 12.0/15.0 と緩い実験中） |
| `raykkretzschmar/biohub-harmonic-bidirectional-association-v1` | 86 | baseline 0.913 参照・自身は `candidate_unverified` | pack50 + seed314159 + deepcenter | CLEAN・自己監査 | harmonic λ=0.20 |
| `indarkarhana/biohub-dual-seed-frame-retention-guard-v1` | 75 | **0.912 → 0.913 (+0.001)** | 同上 | CLEAN・自己監査 | guard は 400 フレーム中 60 で発火 |
| `lucifer19/biohub-cell-lineage-tracker` | 77 | **0.891**（106ep ckpt） | pack50 のみ | CLEAN（上限クランプ・監査なし） | ckpt 比較 **106ep 0.891 vs 129ep 0.886** |
| `anhadmahajan06/biohub-track-your-cells-development` | 78 | タイトル 0.920+、実体は 0.915 からの派生 | 上 + xiaolei 重み(**未使用**) | **要注意（ハックではない）** | `SINGLE_CHILD_REPAIR=1` で ILP 由来の分裂を全消し→ヒューリスティックで再生成、かつ **DeepCenter veto を OFF**・sister 9.2 µm に緩和。division 数を増やす方向に安全弁を外している |
| `hiranorm/new-lb-0-916-infer-ensemble-lf-exp002` | 21 | base **実 LB 0.914** | pack50 + seed314159 | CLEAN | **事前登録つき A/B**（後述、本調査で最も統計的に厳密） |
| `xiaoleilian/biohub-m001-ens3-sm6-sim2` | 69 | **VAL-24 公式指標 0.8623** | `xiaoleilian/biohub-unet3d-weights` (+v2models) | CLEAN | 3 モデル heatmap 平均 + flip 4-TTA |

### 2-B. 独立系（pilkwang 系譜に依存しない）

| NB | votes | LB | 依存 | 判定 |
|---|---|---|---|---|
| `xiaoleilian/biohub-ct-mix-divaug` **セル 0–3 のみ** | 237 | ローカル VAL **0.8388** | `xiaoleilian/biohub-unet3d-weights` (47 MB) のみ。**pip install ゼロ** | CLEAN |
| `xiaoleilian/biohub-cell-tracking-3d-u-net-training` | 21 | 学習結果が **public LB 0.841** | **添付なし**（コンペデータ + GT から直接学習） | CLEAN・**自前重みを作れる唯一の完結レシピ** |

`3d-u-net-training` の要点: XY-pool ×4 → 64³、`BASE=24`、`GAUSS_SIGMA=1.0`、**PU 学習**（GT 中心=正例・明確に暗い voxel=負例 weight 1・曖昧な明部は **ignore weight 0.05**）、Adam `lr=1e-3` + cosine、40 epoch / 171 movies、`val_recall≈0.65`。**public LB 4 本 `TEST4` を学習から除外**する胚グループ分割を実装済み。

### 2-C. ルールベース（重み不要・CPU）

| NB | votes | 申告 LB | 主要パラメータ |
|---|---|---|---|
| `isakatsuyoshi/biohub-rule-based-baseline` | 86 | **0.826**（LB 実測と一致） | DoG `[[1.5,4.0],[2.2,5.5]]` µm、`rel_threshold=0.045`、`min_distance=3.2 µm`、`max_link=8.0 µm`、gap 1 フレーム/6.0 µm、**分裂 OFF**、孤立ノード除去。公式指標のローカル複製を同梱 |
| `seshurajup/lb-0-857-best-rule-base-v14` | 95 | **0.826→0.835(V1)→0.842(V3)**（タイトルは 0.857） | 上の fork。`xy_downsample=2`、`rel_threshold=0.025`、`min_distance=3.0 µm`、`smooth_w=0.8` |
| `romanrozen/strong-start-dog-band-pass-lb-0-73` | 79 | 0.73+ | DoG σ=(1.0,1.8,3.0)/K=1.6、NMS 4 µm、2 パス Hungarian（tight 6 / full 10 µm）、**動画ごとのノード数較正**（`BUDGET_SAFETY=1.15`） |
| `xiaoleilian/biohub-cell-tracking-classical-baseline` | 72 | コメントに 0.720 | `thresh_rel=0.18`、`max_link=11.0 µm`、`tight=7.0 µm` |

3 本とも **`pip install` ゼロ・添付データセットゼロ・GPU 不要**。

---

## 3. 依存関係とデータセット（オフライン成立性）

| データセット | サイズ | 中身 | 公開 DL |
|---|---|---|---|
| `pilkwang/biohub-tracking-support-pack-50ep-v1` | 349 MB | `repo/`（推論・学習コード）+ `weights/unet_transformer/split_0/edge_predictor_best.pth` + **wheels/**（tracksdata, pyscipopt, ilpy, geff, polars, blosc2…） | ✅ 実際に取得確認 |
| `pilkwang/biohub-temporal-unet3d-seed314159-v1` | 350 MB | 別シード重み + 同 wheels | ✅ |
| `pilkwang/biohub-deepcenter-unet3d-center-prior-v1` | 71 MB | `best.pt`(ep2) / `checkpoint_last.pt`(ep500) | ✅ |
| `thibautgoldsborough/cellmot-baseline-artifacts` | — | 公式 repo + 重み + wheels | ✅ |
| `xiaoleilian/biohub-unet3d-weights` | 47 MB | `unet3d.pt` / `_aug` / `_bright` / `_traintophat` | ✅ |
| `dalloliogm/biohub-official-scorer-patched` | 61 KB | **パッチ後の公式スコアラ**（commit `075fc5f`）。ローカル採点用 | ✅ |

インストールは全 NB 共通で `pip install --no-index --no-deps --find-links <dataset>/wheels`（オンライン fallback は `BIOHUB_ALLOW_PIP_INSTALL=1` 時のみ、既定 OFF）。**internet OFF で成立**。

⚠️ **チェックポイント版数の地雷**: `pack50` の同一パスに少なくとも 3 種の別ファイルが存在した履歴。本日時点の実測 sha256 = `12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771`（pilkwang / yunusgmsoy / raykkretzschmar のピン値と一致）。一方 lucifer19 がピンする `135dec66…`(106ep) とは**不一致**＝あの 0.891 は今の配布物では再現しない。さらに `ARTIFACT_MANIFEST.json` の `artifact_name` は `…-400ep-snapshot-v1` でスラッグの "50ep" と矛盾。**必ず SHA を記録してから測る**。

⚠️ `saitejabandaruin/biohub-top-notebook-0-913` は `enable_internet: true`。そのままでは提出不可。

---

## 4. 実行時間（唯一の実測値と自前ベンチ）

- **公開 NB 唯一の実測**: `clean-approach` の papermill が **2313.5 秒 / 12 本**（hidden test 4 + CV 8）＝ **約 193 秒/本**。→ **199 本で約 10.6 時間**。12h 上限に対し余裕がほとんどない。
- 同 NB 自己申告「T4 1 枚で 8 本の推論に 16〜30 分」＝ 120〜225 秒/本。同じ帯。
- Discussion #727154 に「以前は 5 時間で終わっていた採点が 11 時間経っても終わらない」という参加者報告あり（未確認・キュー待ちを含む可能性）。
- **これが、上位 NB の多くが 2 GPU シャーディング（`worker_count=min(2, gpu_count, len(test_stems))`）を実装している理由**。T4×2 を選ぶこと。
- 自前ベンチ（本番より遅いローカル 1 コア箱、`data/test` 実データ）:
  - CPU DoG 検出（xy_ds=4）: 1242 ms/frame → **199 本で 6.9 h**、xy_ds=2 で **8.8 h**
  - U-Net 経路の CPU 側（pool_norm + peak_local_max + refine + NMS）: 318 ms/frame → **199 本で 1.8 h**（GPU U-Net 時間は別）
  - ⇒ ルールベースを `xy_downsample=2` で回すのは 12h に対して危険。**ds=4 を既定にすべき**。

---

## 5. 比較表（要約）

| # | kernel ref | votes | 系統 | 申告 LB | CLEAN | GPU | 添付 DS 数 | pip | 12h 適合 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `yusuketogashi/clean-approach-lightweight-local-cv-no-hack` | 194 | UNet+ILP | 0.908 | ✅ 自己監査+攻撃テスト | 要 | 1 | offline | △ 193s/本・2GPU 推奨 |
| 2 | `pilkwang/biohub-cell-tracking-two-seeds-logit-blend` | 192 | UNet+ILP dual | — | ✅ | 要 | 4 | offline | △ TTA で更に増 |
| 3 | `yaroslavkholmirzayev/...-v4-unet-ilp-reproduction` | 130 | UNet+ILP | —(team 0.899) | ✅ | 要 | 1 | offline | △ |
| 4 | `indarkarhana/biohub-dual-seed-frame-retention-guard-v1` | 75 | UNet+ILP dual | 0.913 | ✅ | 要 | 4 | offline | △ |
| 5 | `hiranorm/new-lb-0-916-infer-ensemble-lf-exp002` | 21 | UNet+ILP dual | base 0.914 | ✅ | 要 | 2 | offline | △ |
| 6 | `thibautgoldsborough/unet-baseline-inference-submission` | 81 | UNet+ILP 公式 | ~0.79 | ✅ | 要 | 1 | offline | ○ |
| 7 | `xiaoleilian/biohub-ct-mix-divaug` **cell 0-3** | 237 | 3D U-Net×2 + Hungarian | VAL 0.8388 | ✅ | 要 | 1 (47MB) | **なし** | ◎ |
| 8 | `xiaoleilian/biohub-m001-ens3-sm6-sim2` | 69 | 3D U-Net×3 + TTA | VAL-24 0.8623 | ✅ | 要 | 2 | **なし** | ○ |
| 9 | `seshurajup/lb-0-857-best-rule-base-v14` | 95 | ルールベース | 0.842 | ✅ | 不要 | **0** | **なし** | △ ds=2 で 8.8h |
| 10 | `isakatsuyoshi/biohub-rule-based-baseline` | 86 | ルールベース | 0.826 | ✅ | 不要 | **0** | **なし** | ◎ ds=4 |
| 11 | `xiaoleilian/biohub-cell-tracking-3d-u-net-training` | 21 | **学習** | 出力が 0.841 | ✅ | 要 | 0 | なし | 学習用 |
| — | `kaiwalyaatulraut/biohub-cell-tracking-solution` 他 7 本 | 210他 | — | — | ❌ **metric-exploit** | — | — | — | コピー禁止 |

---

## 6. 推奨

### ベース① 最初に再現すべきもの — `yusuketogashi/clean-approach-lightweight-local-cv-no-hack`（Biohub 132 構成）

**理由**: (a) パッチ後の clean baseline **0.908** を自称し、その根拠として**公式指標をローカル再実装した fixed-8 CV を実際に走らせている**唯一の NB、(b) 提出後に `t<0` / 体積外 / `outdeg>2` / dangling / 非連続辺を **CSV から再検証して AssertionError で落とす**、(c) さらに `(-10000,-10000,-10000)` を食わせて**検出器が発火することを自己テスト**している、(d) 添付が **1 データセットのみ**。当リポジトリの `src/biohub/evaluate.py` + `scripts/local_eval.py` と役割が重なるので、突き合わせ検証にも使える。

- kernel ref: `yusuketogashi/clean-approach-lightweight-local-cv-no-hack`
- 必要データセット: `pilkwang/biohub-tracking-support-pack-50ep-v1` のみ（+ コンペデータ）
- 検算用に別途: `dalloliogm/biohub-official-scorer-patched`
- アクセラレータ: **T4 ×2**（12h 予算のため必須級）、internet OFF

**最小コード経路**:
1. `pip install --no-index --no-deps --find-links {pack}/wheels tracksdata zarr pyscipopt geff ilpy polars blosc2 …`
2. `shutil.copytree({pack}/repo, /kaggle/working/repo)` → `sys.path.insert(0, repo/src)`
3. `kaggle_test_splits.json` に test の全 stem を 1 fold で書き出す
4. `python scripts/predict_unet_transformer.py --data-dir $TEST_DIR --splits … --weights weights/unet_transformer/split_0/edge_predictor_best.pth --det-threshold 0.96875 --use-ilp --ilp-edge-weight -1.0 --ilp-appearance-weight 0.0 --ilp-disappearance-weight 1.575 --ilp-division-weight 1.0`
5. `filter_output_graph`（motion relink tight 6.0 / relaxed 9.5 µm → single-parent repair → gap close 6.0 µm 密度適応 → safe-div 4.66/8.5/7.65 µm → min_track_len=6 → linefit w=0.8 win=2）
6. `.geff` → CSV 平坦化（node 行 / edge 行）
7. **監査セル**（§7 のチェックリスト）を通してから保存

**先に踏むべき踏み台**: `thibautgoldsborough/unet-baseline-inference-submission`（全 10 セル）。オフライン wheel → repo コピー → 推論 → CSV の配線がこれだけで通ることを確認してから①に進むのが安全。

### ベース② フォールバック（重み不要・純ルールベース） — `isakatsuyoshi/biohub-rule-based-baseline` を土台に `seshurajup` の定数

**理由**: 添付データセット 0・`pip install` 0・GPU 不要。学習系が壊れても必ず提出できる保険。0.826〜0.842 が実測ベース。

- kernel refs: `isakatsuyoshi/biohub-rule-based-baseline`（原典・単一 `.py`）、`seshurajup/lb-0-857-best-rule-base-v14`（定数改良版）
- データセット: **不要**
- 最小コード経路: zarr 1 フレーム読み → XY pool ×4 → **多スケール DoG `[[1.5,4.0],[2.2,5.5]]` µm** → `rel_threshold` 閾値 → 強度重心 refine → **µm NMS 3.0〜3.2** → 2 パス µm ゲート Hungarian（`max_link_um=8.0`）→ 1 フレーム gap close（6.0 µm）→ 孤立ノード除去 → linefit `smooth_w=0.8` → CSV
- ⚠️ **`xy_downsample` は 2 ではなく 4 で始める**（自前ベンチで ds=2 は 199 本 8.8h、ds=4 は 6.9h。ローカルは本番より遅いが、余裕は ds=4 側にしかない）
- ⚠️ 分裂は既定 OFF。division 項は最大 0.1 しかないのに FP は edge 側にも刺さるため、原典の判断は妥当。

---

## 7. 提出前バリデータ（必ず自動化する）

ハック検出と自分のバグ検出を兼ねる。上位クリーン NB が実装しているものの合成:

1. `0 <= t <= 99`（node 行）
2. `0 <= z < 64`, `0 <= y,x < 256` — **上限も**。調べた NB の**ほぼ全部が `max(0,...)` の下限クランプしか持たない**（共通の盲点）。zarr の実 shape から導出すること
3. すべての辺で `t_target == t_source + 1`
4. `in-degree <= 1` かつ `out-degree <= 2`
5. 辺の両端が**同一 dataset** に解決される（クロスクリップ辺なし）
6. dangling edge・重複 node_id なし
7. `N_pred` vs geff メタの `estimated_number_of_nodes` の乖離率を印字（過検出の早期検知）
8. **自己テスト**: `(-10000,-10000,-10000)` を注入して 1〜6 が**実際に落ちること**を確認（検査が発火しない検査は情報量ゼロ）

---

## 8. 改善アイデア Top 8（著者申告の delta 付き）

| # | アイデア | 出典 NB | 著者申告の delta |
|---|---|---|---|
| 1 | **双方向 harmonic 辺融合** — 同じ transformer を source/target 逆で走らせ転置、mean/std を前向きに較正し、確率空間で調和平均 `1/((1-λ)/p_fwd + λ/p_rev)`、λ=0.20。片方向しか支持しない辺を構造的に罰する。追加コストは前向き 1 パス分のみ | `yusuketogashi/no-hack-…-3rd` (v18) → `yunusgmsoy/…v17`, `raykkretzschmar/…harmonic` | **+0.002**（0.913→0.915、yunusgmsoy コード内コメント） |
| 2 | **dual-seed 検出 logit ブレンド**（scale 較正後に 0.475/0.525） | `pilkwang/…two-seeds-logit-blend` | Discussion #730924 の第三者検証: **0.908→0.910**、かつ**出力ノード数 −1.7%**（＝効いたのは検出 precision） |
| 3 | **frame retention guard** — フレーム単位で `N(blend)/N(primary) < 0.90` なら primary 単独に戻す。アンサンブル崩壊をフレーム局所に封じ込める | `indarkarhana/…retention-guard-v1` | **0.912 → 0.913 (+0.001)**。400 フレーム中 60 で発火し 1,758 node / 1,638 edge を回復。著者自身「3 桁表示の丸め幅内」と注記 |
| 4 | **linefit 平滑化を w=0.8 / window=3 に** — 単親単子の直線区間で z,y,x を Δt に対し 1 次回帰し 80% ブレンド。**トポロジ不変・ノード数不変**なので 7 µm マッチングだけに効く | `hiranorm/…lf-exp002` | ローカル wide96 で **+0.0086 CI[+0.0048,+0.0116]**。過去に「ローカル +0.0068 → 実 LB +0.010」で**転移率 1 以上**の実績（ノード数不変軸ゆえ割引なし） |
| 5 | **division fork の topk を 50 → 20** — divJ は micro 平均なので最適 N は hidden の分裂密度依存 | `hiranorm/…lf-exp002` | divJ **0.0636 → 0.0833**。#4 と同梱で **SCORE +0.0048 CI[+0.0015,+0.0086], P(new>base)=0.999**。⚠️著者が**反証も明記**: 旧構成では topk50 0.864 > topk10 0.860 |
| 6 | **動画ごとのノード数較正** — test に `estimated_number_of_nodes` は無いので、画像統計→細胞数の回帰を train で学習し、**寛容に検出してから動画ごとの予算で topk 打ち切り**（`BUDGET_SAFETY=1.15`）。adjusted Jaccard の罰則に直接効く | `romanrozen/strong-start-dog-band-pass` | DoG 自体は合成勾配動画で **recall 0.38→0.79、深部細胞 0.00→0.88**（LB delta は未提示） |
| 7 | **マルチモデル heatmap 平均 + flip 4-TTA + short-track 6 + 外観コスト** — logit を sigmoid 前に平均、リンクコストに `2.0*|logit(s_prev)-logit(s_curr)|` を加算 | `xiaoleilian/biohub-m001-ens3-sm6-sim2` | VAL-24（公式指標）**0.8547 → 0.8584(ens3) → 0.8601(sm6) → 0.8623(sim2)**。⚠️同著者が明記: **検出の union は禁物**（DoG-union U-Net は 0.661、過検出でノード罰則に轢かれる） |
| 8 | **2 パス motion relink で ILP 出力を上書き** — 予測位置 `q + 0.5·v` に対し cost `= motion_dist + 0.05·raw_dist − 0.75·edge_prob`、tight 6.0 µm → 残りを relaxed 10.0 µm | pilkwang / yusuketogashi / yaroslav 全系統 | 単独 delta の明示なし（**未確認**）。ただし全上位 clean NB が採用 |

**次点で有望**（枠外だが記録）: ① 学習型 edge veto を**除去専用・上限 1%・分裂 source は除外**で使う非対称設計（yaroslav、OOF AUC 0.71 の弱分類器を安全に活かす型）、② safe-division に「**前方発散チェック**」（2 娘が t+2 でさらに離れていることを要求）+ DeepCenter veto（yunusgmsoy。veto を切ると safe-div が自候補の **81〜100%** を通してしまうとテレメトリで判明）、③ チェックポイント選択（lucifer19: **106ep 0.891 vs 129ep 0.886** — 学習しすぎで固定閾値 0.99 を通る検出が減り recall が落ちる）。

---

## 9. 未確認・注意事項

- 表中の「申告 LB」は**ノートブック内の記述**。LB CSV の値はチーム最良であり特定 NB に帰属できない（参考: pilkwang 0.921 / yunusgmsoy 0.923 / hiranorm 0.925 / yusuketogashi 0.918 / xiaoleilian 0.918 / anhadmahajan 0.916 / raykkretzschmar 0.915 / saitejabandaru 0.913 / romanrozen 0.909 / kaiwalyaatulraut 0.901 / yaroslav 0.899 / isakatsuyoshi 0.826、2026-08-23 スナップショット）。
- `yunusgmsoy` の **0.920 はタイトルのみ**でコード内根拠なし。`anhadmahajan` の 0.920+ も同様に目標値。**未確認**。
- `xiaoleilian/ct-mix-divaug` の `VAL 0.8388 → 0.9203` は**パッチ前**のホスト指標レプリカ上の値。パッチ後の +0.0815 は消えている（むしろ負に転じるはず）が、**再測定していないので未確認**。
- 12h 適合の判定は 193 秒/本（1 本の papermill 実測）と自前ローカルベンチからの外挿。**Kaggle 実機での測定は未実施**。
- ほぼ全ての公開 NB に**壁時計ガードが無い**（199 本の途中で 12h に当たると全損）。時間予算チェックと途中保存は自前で足す必要がある。
- `hiranorm` の A/B は 2 変数同時（linefit と fork topk）で**交絡している**と著者自身が明記。分離が要るなら別枠で。

---

最後の担当エージェントの報告が届きました。本報告への**追補と 1 件の訂正**です。

## 追補: 0.902 系 2 本 + 0.913 の判定

| NB | votes | 申告 LB | 判定 | 要点 |
|---|---|---|---|---|
| `evgendvorkin/biohub-0-902-lb` | — | タイトル **0.923**、コード内の基準は `public LB 0.913` | **CLEAN・自己監査が最強** | dual-seed + **harmonic λ=0.30**（参照値 0.20 から変更）、`det=0.96875`、ILP `disappear=1.5`、DeepCenter veto **ON**（`best.pt` epoch **2**） |
| `praxel/biohub-0-902-motion-division-calibration` | 62 | **0.902**（提出 ID `54633411` + CSV SHA256 まで明記＝本調査で最も追跡可能な申告） | **CLEAN**（ただし監査セルは弱い） | 単一モデル・アンサンブルなし、`det=0.9700`、`OUTPUT_EDGE_MAX_UM=14.0`、motion relink の learned bonus を 0.75→**1.0** |
| `saitejabandaruin/biohub-top-notebook-0-913` | 47 | タイトルのみ 0.913 | **コードは CLEAN だが、配布状態では実行不能** | `enable_gpu:false` / `dataset_sources:[]` / `competition_sources:[]` なのに、コードは **GPU を hard-require** し pilkwang 3 データセット＋コンペデータを要求。wheels も無いので `ensure_dependencies()` で即死 |

**§3 の訂正**: `saitejabandaruin` について私は「`enable_internet:true` なので提出不可」とだけ書きましたが、実際はそれ以前の問題です。**添付データセットもコンペデータ宣言も空**で、GPU も無効。再現対象から外してください（メトリクスハックではなく、成果物として成立していない）。

**新たな注意点**: DeepCenter のチェックポイント指定が NB 間で食い違っています — `evgendvorkin` は `best.pt` の **epoch 2** を assert、`saitejabandaruin` は `checkpoint_last.pt` の **epoch 500** を assert。同じ「DeepCenter veto」でも中身が別物です。採用時はどちらか明示的に選ぶこと。

**共通の弱点（3 本とも）**: ダウンロードした `.ipynb` に**保存済みセル出力が 1 つも無い**（evgendvorkin は 21 コードセル中 0）。つまり申告 LB はすべて markdown/コメント上の記述で、成果物からは検証不能です。§9 の「未確認」扱いをこの 3 本にも適用してください。

## Top 8 への補強（順位は変えず、実装ディテールを追加）

- **#3 frame retention guard** に加えて、`evgendvorkin` の**分裂フィルタ 2 段**が有効そうです: (a) 提案する第 2 娘が第 1 娘にとって**相互最近傍の未使用ノード**であること、(b) **前方発散** — 2 娘の次フレーム後継が、娘同士の間隔より `SAFE_DIV_DIVERGE_UM=2.25 µm` 以上開いていること。距離閾値だけより精度制御が強い。
- **gap closing を密度適応に**: 参照間隔 `6.5 µm`・ゲイン `0.040`・ステップ上限 `0.125 µm`・近傍 3 点。混雑部で締め、疎な部分で緩める。
- **gap 補間ノードの重心リファイン**: 線形補間した中点を、20 パーセンタイルを差し引いた強度重心で `±1z, ±3yx` 窓内に再配置し、`3.2 µm` 超の移動なら棄却。
- **ローカル CV の層化**: 胚 prefix に加えて「**GT に分裂が含まれるか**」で層化する。`evgendvorkin` のコメントによれば GT 動画のうち分裂を含むのは **約 44%**（著者コメント・**未確認**）。層化しないと division_jaccard がローカルでほぼ動かず、A/B が空振りします。
- **設定ドリフト検知**: 期待ハイパーパラメータの dict を実行時に `os.environ` と突き合わせて raise（`evgendvorkin` Cell 5）。NB をコピー改変した後に別設定で提出する事故を防ぎます。

一方で**やらない方がよい示唆**も 1 件: `praxel` は DeepCenter veto が実測で**候補を 1 つも検査していなかった**（no-op）ことを確認し、公開版から**削除**しました。§8 の次点②で挙げた veto は、**発火テレメトリを取ってから**でないと「入れたつもり」になります（[[feedback_verify_the_check_actually_fires]] と同型）。

なお §5 比較表・§6 の推奨（ベース① = `yusuketogashi/clean-approach-lightweight-local-cv-no-hack`、ベース② = `isakatsuyoshi` + `seshurajup` 定数）は、この追補で**変更ありません**。0.902 系 2 本はいずれもベース①と同一系譜で、かつベース①より低い申告値なので、最初の再現対象を置き換える理由になりません。

---

最後のエージェントも完了。**メトリクスに関する重要な発見が 1 件**あり、これは本報告の前提を補正します。

## ⚠️ 追補 2: adjusted Jaccard には「過小検出ボーナス」がある（公式ドキュメントで確認済み）

私は §8 で「adjusted Jaccard は過検出を罰する」とだけ書きましたが、**逆側にクリップが無い**ことを見落としていました。`official/metrics.md` の定義:

```
adjusted_jaccard = max(0, jaccard · (1 − a · (T_pred − T_true) / T_true)),  a = 0.1
```

`max(0, …)` はあるが **`min(1, …)` も ratio の下側クリップも無い**。したがって `T_pred < T_true` なら乗数が **1 を超える**。公式 Evaluation ページの「**Due to the nature of the metric, it is possible for scores to exceed 1.0**」がこれを裏づけます。

これを **2 名の著者が独立に発見し、いずれも意図的に使わなかった**と記録しています:

- `hiranorm`: holdout16 で `det=0.96875` の方が高スコア（**0.9344** vs `det=0.90` の 0.9315）だったが、**ノード数が −6.5%** でボーナスが混入し分解できないため不採用。代わりに融合後のノード数が単独モデル比 **99.6%** になるよう `det_threshold` を 0.96875→**0.90** に較正。
- `xiaoleilian`: DoG union 融合が過検出で **0.661** に落ちたことから union を棄却（こちらは過検出側の実測）。

**含意（要判断）**: これは §1 の hub ハックとは性質が違います。パッチ済みの exploit ではなく**現行メトリクスの定義そのもの**であり、閾値を上げてノードを減らすのは正当なチューニング軸とも読めます。ただし **hidden の `T_true` に依存**するため、public 4 本で得た最適閾値が転移する保証はありません。**当面は hiranorm 方式（ノード数を基準に合わせて較正し、ボーナス由来の見かけ上の改善を混ぜない）を既定にすることを推奨**します。そうしないと A/B の効果量が「実力」と「ボーナス」の合成になり、[[project_nedo_baggage_loading]] で繰り返した「複数の効果が結合した指標で採否を決める」失敗と同型になります。

## 追補 2b: hidden test の本数に矛盾がある（未解決）

| 出所 | 主張 |
|---|---|
| 公式 data-description | hidden test は「train とほぼ同規模」＝ **199 本**（`manifest.csv` 実測） |
| `hiranorm` の実証 | `assert n_zarr <= 16` が**実提出 2 件（`55321087`, `55323981`）を殺した**。hidden は public 4 本の **約 17.5 倍 ≈ 67〜70 本**と記述 |

§4 の実行時間見積り（193 秒/本 × 199 本 ≈ 10.6h）は 199 本前提です。**70 本なら約 3.7h で余裕**、199 本なら綱渡り。**どちらか未確認**なので、12h ガードと途中保存は本数に関わらず入れてください。同時に hiranorm の教訓 —**外部データ形状の仮定を hard assert にするな（print に落とせ）**— は必ず採用を。提出を殺した実例が 2 件あります。

## 追補 2c: §5 比較表の訂正 1 件

**`hiranorm/new-lb-0-916-infer-ensemble-lf-exp002` は現状の pull では再現不能**です。検出器・リンカ本体は外部コードデータセット `hiranorm/biohub-exp002-code` にあり、これは `dataset_sources` に**名前付きスラッグとして解決できません**（空文字エントリのみ）。私の表では「添付 DS 数 2」としましたが、**中核コードが欠けています**。§8 の改善アイデア #4・#5（linefit w=0.8、fork topk 20）は**パラメータとして採用可能**ですが、この NB を base に選ぶことはできません。

加えてタイトルの `0.916` は、本文の確定ベースライン `実LB 0.914` とも予測 `0.918〜0.920` とも一致しません。**ローカル予測が実 LB を上回った（＝転移率 1 未満だった）**兆候と読むのが自然です。§8 #4 で引用した「転移率 1 以上」という著者の主張は、この食い違いを踏まえると**割り引いて扱うべき**です（**未確認**）。

## 追補 2d: 新規 2 本（いずれも CLEAN、推奨は不変）

| NB | votes | 判定 | 要点 |
|---|---|---|---|
| `abhijithneilabraham/solution` | 83 | CLEAN | 祖先 NB が **LB 0.897**、自身の値は記載なし。`det=0.97`、safe-div 4.66/7.05/**7.65** µm。⚠️ preset 名が `deepcenter_add_only_repair_gate_min6` なのに **DeepCenter veto は無効**（`BIOHUB_USE_DEEPCENTER_VETO="0"`）＝名前と実体の不一致。自前重みを探す死にコードあり（該当データセット未添付で常に fallback） |
| `kunaldesale2408/biohub-cell-tracking` | 73 | **CLEAN・実行時ガードが本調査で最強** | baseline **0.913**、Cell 1–7 のみなら **0.915** 再現。自身の harmonic 実験は `candidate_unverified` と自己申告。**実 LB ベースの ablation が最も豊富**: ILP division weight `0.3/1.0/2.0/3.0` は**全て 0.915**（＝この軸は効かない）／`SAFE_DIV_MAX_UM=7.0` はローカル改善だが**実 LB は 0.914 に低下**（ローカルと LB が逆行した実例）／bidirectional 0.20 で **+0.002**（0.913→0.915） |

`kunaldesale2408` の Cell 6 は、§7 で私が提案した検査項目（`t<0`／負座標／`t_target==t_source+1`／`in-deg≤1`／`out-deg≤2`／dataset 集合一致）を**実際に `raise` する形で実装している唯一の NB**です。§7 の実装リファレンスとしてはこれを直接参照してください（ただし**上限クランプが無い**のは全 NB 共通の穴なので、そこは自前で足すこと）。

**推奨（§6）は変更なし**: ベース① = `yusuketogashi/clean-approach-lightweight-local-cv-no-hack`、ベース② = `isakatsuyoshi` + `seshurajup` 定数。ただし①に着手する際、ノード数を固定した上で A/B する運用（追補 2a）を最初から入れてください。