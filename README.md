# Biohub – Cell Tracking During Development (Kaggle)

Code and research records for the Kaggle code competition
[Biohub – Cell Tracking During Development](https://www.kaggle.com/competitions/biohub-cell-tracking-during-development)
(ended 2026-09-29). The task is to detect and track cells in 3D+time light-sheet movies of zebrafish embryos and to
output a lineage graph (nodes per frame, edges t→t+1, divisions as one parent → two children).

**English summary.** The submitted pipeline is a UNet + Transformer detector/linker with an ILP solver, followed by a
graph post-processing stack. It is forked from public Apache-2.0 Kaggle notebooks (see
[Credits](#credits-and-licenses)) and improved by single-factor experiments. The best Public LB score was **0.945**.
Every experiment, including the failed ones, is recorded in [`analysis/experiment_ledger.md`](analysis/experiment_ledger.md).
The code-verified architecture of the final notebook is in
[`analysis/pipeline_design_as_shipped.md`](analysis/pipeline_design_as_shipped.md).
Documents are mostly in Japanese; code and commit messages are in English.

## 結果（Public LB）

主な提出のスコアです。原則として 1 因子だけを変えた比較です（E38 と、公開 0.947 の設定を一括で取り込んだ E49 は複合）。変更の根拠と事前登録した採否の基準は台帳にあります。

| 実験 | 変更 | Public |
|---|---|---:|
| E23 | 公開ノート（LB 0.923）を無改変でフォークして再現 | 0.924 |
| E38 | association の複合設定 | 0.930 |
| E56 | 姉妹の非対称 veto（tau = 0.6） | 0.944 |
| **E57** | **E56 + DeepCenter heatmap の 8 方向 TTA** | **0.945** |
| E59 | E56 + 密度グループ別の motion relink 設定 | 0.944 |

## 手法の概要

詳細と行番号つきの根拠は [`analysis/pipeline_design_as_shipped.md`](analysis/pipeline_design_as_shipped.md) にあります。

1. **検出**: UNet の検出 logit を 8 方向 TTA で平均し、2 つのシードのモデルを混ぜる（フレームごとの retention guard 付き）。局所最大で細胞中心を取る。
2. **エッジ候補**: Transformer が全ペアのエッジ logit を出す。順方向と逆方向を harmonic 融合し、2 シードの low-margin 混合、edge-feature TTA、rank bonus をかけたあと、softmax の閾値 0.48 で候補にする。
3. **ILP**: tracksdata の ILPSolver。この重みでは分裂が選ばれないため、分裂はすべて後処理で作る。
4. **後処理**: 1 フレーム・2 フレーム欠損の補完、safe-division（DeepCenter veto と姉妹の非対称 veto 付き）、短いトラックの削除と救済、直線当てはめによる平滑化。

## リポジトリ構成

| パス | 内容 |
|---|---|
| `notebooks/` | Kaggle に push したカーネル（1 ディレクトリ = 1 カーネル）。最終提出は `notebooks/pub923_repro/`。`SOURCE.md` があるものは公開ノートからの派生で、出典はそこに書いてある。無いものは独自のカーネル |
| `src/biohub/` | torch 不要の自前ツール（zarr/geff の読み込み、公式指標での採点、後処理のローカル移植 `public_postproc/` など） |
| `scripts/` | データ取得、ローカル採点、実験用スクリプト（`scripts/experiments/<id>/`） |
| `analysis/` | 実験台帳、競技仕様（[`competition_spec.md`](analysis/competition_spec.md)）、設計書、計画 |
| `docs/` | Discussion と公開ノートの調査記録、教訓 |
| `tests/` | pytest（合成データ。実データや過去の成果物が必要なテストは、無ければスキップ） |
| `official/` | 主催者の公式指標・ベースライン（git submodule） |

## データ

競技データは Kaggle からダウンロードしてください（CC0）。このリポジトリには含めていません。

| 分割 | 本数 | 容量 | 内容 |
|---|---|---|---|
| train | 199（`44b6` 71 / `6bba` 128） | 85.7 GB | `<name>.zarr`（画像）+ `<name>.geff`（疎な GT グラフ） |
| test | 4（各系統 2） | 1.9 GB | ダミー（train と同名・同内容）。LB は hidden test で採点 |

- 画像: zarr v3、`0` 配列 (T=100, Z=64, Y=256, X=256) uint16。スケール (Z,Y,X) = (1.625, 0.40625, 0.40625) µm/voxel。
- GT: ノード (t,z,y,x) は voxel 単位、エッジは t→t+1、分裂は親 1 → 子 2。**全細胞は注釈されていない**。
- 提出 CSV: `id,dataset,row_type,node_id,t,z,y,x,source_id,target_id`。
- 指標: `adj_edge_jaccard + 0.1 × division_jaccard`（定義は [`official/metrics.md`](official/metrics.md)、要約は [`analysis/competition_spec.md`](analysis/competition_spec.md)）。

## セットアップ

```bash
git clone --recurse-submodules <this repository>
uv python install 3.12
uv sync --frozen --python 3.12 --extra dev
```

Kaggle API の認証は `uv run --frozen kaggle auth login` で行います。トークンはログやチャットに出さないでください。

### データ準備とテスト

```bash
# データ本体を取らず、ファイル一覧だけ作る
uv run --frozen python scripts/build_manifest.py

# public test 4 本 + 対応 GT + 公式テスト fixture（約 1.9 GB）
uv run --frozen python scripts/download_data.py

# 自前テスト
uv run --frozen --extra dev pytest -q

# 公式 metric テスト（GT の場所を明示）
CELLMOT_DATA_DIR=data/train PYTHONPATH=official/src \
  uv run --frozen --extra dev pytest \
  official/tests/test_metrics.py official/tests/test_division_metrics.py -q
```

## ローカル採点（公式指標・torch 不要）

```bash
uv run --frozen python scripts/local_eval.py \
  submission.csv --gt-dir data/train --json outputs/score.json
```

`src/biohub/evaluate.py` が CSV → tracksdata グラフ → `official/src/tracking_cellmot/metrics.evaluate` を
torch を import せずに通します。

## Kaggle での実行

```bash
uv run --frozen kaggle kernels push -p notebooks/pub923_repro
uv run --frozen kaggle kernels status <user>/<kernel-slug>
```

カーネルの入力（モデル重みとサポートパック）は、`kernel-metadata.json` の `dataset_sources` に slug で書いてあります。
最終提出 `pub923_repro` の入力は、pilkwang ほかの公開 Kaggle dataset です。`taichiiiii/*` の dataset と kernel
（`biohub-divft-weights-v1`、`biohub-div-*`）はこのプロジェクトの非公開の成果物なので、それを入力にする notebook
（`base2_dual_seed_harmonic`、`eval_train_raw`、`div_*`）はそのままでは再実行できません。
自分のアカウントで push する場合は、`id` を自分の slug に書き換えてください。

## Credits and licenses

- **このリポジトリ独自のコード**: [MIT License](LICENSE)。
- **公開 Kaggle ノートブックからの派生部分**: Apache License 2.0（[`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt)）。
  出典と変更点は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)、各 notebook の `SOURCE.md`、各ファイル先頭のヘッダにあります。
  原作者の皆さんに感謝します: yusuketogashi、kunaldesale2408、evgendvorkin、haideptry、beraterolelk。
- **公式指標・ベースライン**: [royerlab/kaggle-cell-tracking-competition](https://github.com/royerlab/kaggle-cell-tracking-competition)（BSD-3-Clause、submodule として参照）。
- **モデル入力**: pilkwang ほかの公開 Kaggle dataset を slug で参照しています（重みはこのリポジトリに含めていません）。`taichiiiii/*` の dataset は非公開です。
