# Biohub – Cell Tracking During Development（Kaggle）

作業リポジトリ。運用規則は [CLAUDE.md](CLAUDE.md)、進行順は [CHECKLIST.md](CHECKLIST.md)、
一次記録は [analysis/experiment_ledger.md](analysis/experiment_ledger.md)、教訓は [docs/LESSONS.md](docs/LESSONS.md)。

## Status（2026-08-24 02:45）

**ベースライン = base1**（公式 UNet+Transformer+ILP、`yusuketogashi/clean-approach…` の clean 再現、自称 LB 0.908）。
自カーネル `taichiiiii/biohub-base1-clean-unet-ilp` v1 が Kaggle 実行済・ローカル公式 score **0.8890**（元 NB と TP/FP/FN 一致、台帳 E2）。**LB 未提出**（提出コマンドは user 実行が必要）。
base2（dual-seed + harmonic、0.915 構成の再現）を実行中（E3）。後処理スタックはローカル移植済（ゲート一致）で、linefit スイープ（E5）から改善ループ開始。
hidden ≈ train 同規模（≈200 本）・公開 test 4 本はダミー（Discussion 出典、台帳前提表）。雑音床は桁のみ（SD 0.008–0.014）。

| 項目 | 値 |
|---|---|
| slug | `biohub-cell-tracking-during-development` |
| 形式 | **コード提出のみ**（`isKernelsSubmissionsOnly`）。カーネルが hidden test（train と同規模 ≈200 本・重複なし）に対して `submission.csv` を書く。**5 件/日**、チーム上限 5 |
| 締切 | 2026-09-29 23:59 UTC（チーム合流・新規参加は 09-22） |
| 賞金 / 参加 | $60,000 / 2,659 チーム（2026-08-24） |
| LB（08-23） | 首位 0.962（CLI 確認）。公開 NB の自称値: clean 0.908 / 公式 UNet 0.857（**未再現**） |
| 指標 | `adj_edge_jaccard + 0.1 × division_jaccard`（定義: [`official/metrics.md`](official/metrics.md)） |
| 公式実装 | [royerlab/kaggle-cell-tracking-competition](https://github.com/royerlab/kaggle-cell-tracking-competition)（`official/` submodule） |

## データ

| 分割 | 本数 | 容量 | 内容 |
|---|---|---|---|
| train | 199（`44b6` 71 / `6bba` 128） | 85.7 GB | `<name>.zarr`（画像）+ `<name>.geff`（疎な GT グラフ） |
| test | 4（各系統 2） | 1.9 GB | **ダミー**（train と同名・同内容、主催者回答）。LB は hidden test |

- 画像: zarr v3、`0` 配列 (T=100, Z=64, Y=256, X=256) uint16、1 タイムポイント 1 チャンク（blosc2/zstd）。
  スケール (Z,Y,X) = (1.625, 0.40625, 0.40625) µm/voxel。
- GT: ノード (t,z,y,x) は voxel 単位。エッジは t→t+1。分裂 = 親 1 → 子 2。**全細胞は注釈されていない**。
  geff メタに `estimated_number_of_nodes`（adjusted Jaccard の分母）。
- 提出 CSV: `id,dataset,row_type,node_id,t,z,y,x,source_id,target_id`。

ローカル（RAM 3.8 GB / 空き 16 GB）には test 4 本と GT のみ置く。全量は Kaggle で扱う。

## セットアップ

```bash
uv sync --extra dev
uv run python scripts/build_manifest.py          # data/manifest.csv（125 ページ・約 10 分・初回のみ）
uv run python scripts/download_data.py           # test 4 本 + GT geff（1.9 GB）
uv run --extra dev pytest -q                     # 自前テスト
PYTHONPATH=official/src uv run --extra dev pytest official/tests/test_metrics.py official/tests/test_division_metrics.py official/tests/test_division_sandbox_examples.py -q
```

## ローカル採点（公式指標・torch 不要）

```bash
BIOHUB_TEST_DIR=data/test uv run python notebooks/smoke_nn_baseline/main.py   # submission.csv を生成
uv run python scripts/local_eval.py submission.csv --json outputs/score.json
```

`src/biohub/evaluate.py` が CSV → tracksdata グラフ → `official/src/tracking_cellmot/metrics.evaluate` を
torch を import せずに通す。公式 `scripts/evaluate.py` は `io.py` 経由で torch を要求するため使わない。

## Kaggle 実行

```bash
kaggle kernels push -p notebooks/smoke_nn_baseline     # user 承認後
kaggle kernels status taichiiiii/biohub-smoke-nn-baseline
kaggle kernels output taichiiiii/biohub-smoke-nn-baseline -p outputs/smoke
```

## 参考（公開ノートブック・08-23 時点、票数順）

- `inversion/cell-tracking-getting-started-w-nearest-neighbor`（484 票。Kaggle 公式スターター、本リポの smoke 雛形の元）
- `yusuketogashi/clean-approach-lightweight-local-cv-no-hack`（194 票。UNet+Transformer+ILP、自称 clean 0.908、fixed-8 local CV）
- `pilkwang/biohub-cell-tracking-data-model-eda-baseline`（154 票。DoG 検出 + 物理空間リンク、rule-based）
- `thibautgoldsborough/unet-baseline-inference-submission`（81 票。公式 UNet ベースライン推論、自称 0.857）
- Discussion: #716062（主催者 Welcome・推奨パッケージ）, #734237（hidden ≈ train 規模・採点 9〜12h）, #728324/#727154（07-22 指標パッチ）, #724283（GT のジャンプ）, #729053（GT エッジの誤り）
- 「metric hack」系 NB が複数あるが Kaggle 側で対処済みとされる。**hack に依存しない**。
