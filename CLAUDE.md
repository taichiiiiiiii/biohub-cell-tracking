# Biohub – Cell Tracking During Development（Kaggle）

## プロジェクト概要

- **目的**: 3D+時間の顕微鏡動画（ゼブラフィッシュ胚、2系統 `44b6`/`6bba`）から細胞の検出・追跡グラフを出し、公式指標（adjusted edge Jaccard + 0.1×division Jaccard）で上位を取る。
- **成果物**: Kaggle 上で hidden test に対して動く推論ノートブック（コード形式コンペ）と `submission.csv`。
- **現在の状態**: 2026-08-23 環境構築。未提出。締切 **2026-09-29 23:59 UTC**（$60k、2,658 チーム、LB 首位 0.962・clean 公開 NB 0.908）。

## 応答とドキュメントの言語

応答・ドキュメント・Issue・台帳は日本語。コード・コミットメッセージ・識別子は英語。

## 有効なグローバル規範

- 有効: `common/` + `python/`
- 逸脱: 重い処理（学習・全量推論）は**全面 Kaggle**。ローカルは軽い分析とテストのみ（[[feedback_memory_heavy_tasks_on_kaggle]]）。

## 情報源の優先順位

1. 公式メトリクス実装 `official/`（royerlab/kaggle-cell-tracking-competition の submodule）と Kaggle の実スコア
2. このリポジトリのコードとテスト
3. `analysis/experiment_ledger.md`・公開ノートブック・Discussion

> 実測が古い記述と矛盾したら記述を直す。公開 NB の「表示スコア」は信用しない（CHECKLIST Week 1）。

## プロジェクト構成

```
official/          公式ベースライン＋公式メトリクス（submodule・読み取り専用・編集禁止）
src/biohub/        自前の torch 不要ツール: io.py（zarr/geff 読み）, evaluate.py（CSV→公式スコア）
scripts/           build_manifest.py / download_data.py / local_eval.py / noise_floor.py / submission_status.py
notebooks/         Kaggle に push するカーネル（kernel-metadata.json 同梱・1 ディレクトリ=1 カーネル）
data/              ローカル部分データ（gitignore）: manifest.csv, test/ 4本, train/ の GT geff 数本
analysis/          experiment_ledger.md（一次記録）
outputs/           ローカル生成物（gitignore）
tests/             pytest（`uv run --extra dev pytest`）
```

## アーキテクチャ（複数ファイルを跨ぐ要点だけ）

- **データ**: `<name>.zarr/0` = (T=100, Z=64, Y=256, X=256) uint16、1 タイムポイント 1 チャンク（blosc2/zstd）。スケール (Z,Y,X)=(1.625, 0.40625, 0.40625) µm/voxel。GT は `<name>.geff`（tracksdata グラフ、ノード t/z/y/x は voxel 単位、分裂=1 親→2 子）。**GT は疎**（全細胞を注釈していない）。
- **test の 4 本は train と同名・同内容**（GT 付き）。本番は hidden test で再実行される。∴ローカル評価は `data/train/*.geff` に対して `scripts/local_eval.py`。
- **提出 CSV**: `id,dataset,row_type,node_id,t,z,y,x,source_id,target_id`。node 行は source/target=-1、edge 行は node_id/t/z/y/x=-1。edge は必ず t→t+1。
- **評価の流れ**: CSV → tracksdata InMemoryGraph（`src/biohub/evaluate.py`）→ `official/src/tracking_cellmot/metrics.evaluate`（7 µm 最適割当）→ `summarise`。torch を import しない経路にしてある。

## コマンド

```bash
uv sync --extra dev                                  # セットアップ（torch なし・約 30 秒）
uv run --extra dev pytest -q                         # 自前テスト
PYTHONPATH=official/src uv run --extra dev pytest official/tests/test_metrics.py official/tests/test_division_metrics.py -q   # 公式メトリクスのテスト
uv run ruff check src/ scripts/ tests/               # リント（official/ notebooks/ は除外）
uv run python scripts/download_data.py --train <stem...>   # 部分データ取得（manifest 必須）
uv run python scripts/local_eval.py outputs/submission.csv  # 公式指標でローカル採点
kaggle kernels push -p notebooks/<kernel>            # Kaggle 実行（user 承認後）
```

## 実行環境の制約

- **ローカル RAM 3.8 GB / 空き 16 GB**: 全量 87.6 GB は置けない。1 フレーム 8.4 MB、1 動画 840 MB raw。学習・全量推論は Kaggle（T4: `"machine_shape":"NvidiaTeslaT4"`）。
- **Kaggle MCP は未認証・Playwright MCP は X なし**で不可。Kaggle 操作は `kaggle` CLI、ページ閲覧は不可（公開 NB を `kaggle kernels pull` で読む）。

## 測定プロトコル

- **指標**: `score = adj_edge_jaccard + 0.1 × division_jaccard`。edge Jaccard = TP/(TP+FP+FN)、7 µm 最適割当、疎 GT ゆえ未マッチノードは FP にならない。`adj = max(0, J·(1 − 0.1·(N_pred − N_true)/N_true))`（`N_true` は geff メタの `estimated_number_of_nodes`）。動画横断はマイクロ平均（adj edge は w=TP+FP+FN 加重）。定義は `official/metrics.md`。
- **ベースライン**: 未測定（Issue #2 で NN ベースライン→ローカル採点→同一コード 2 回提出）。
- **雑音床**: 未測定（Issue #2。評価単位=動画、hidden test の本数は不明→Discussion で調査）。
- **分割**: 評価単位は動画。`44b6`/`6bba` の 2 系統を層化。public 4 本は train と同一なので**公開 test での採点値を汎化性能と呼ばない**。
- **採否のバー**: 雑音床確定後に台帳へ記載。それまで「改善」と書かない。

## 重要な技術的制約

- **`official/` を編集しない**: 公式メトリクスとの一致が唯一の真実源。変更が必要なら `src/biohub/` 側に書く。
- **edge は t→t+1 のみ**: 公式 `_evaluate_matched_graph` が非連続エッジを落とす。ギャップ補完は中間ノードを作って埋める。
- **ノードを増やしすぎない**: adjusted Jaccard のペナルティ（α=0.1）が N_pred に線形に効く。
- **提出 CSV は `scripts/local_eval.py` の検証を通してから**: 重複 node_id・dangling edge は raise する設計。

## 承認が必要な操作

- `kaggle competitions submit`（提出。**サブエージェントは絶対に実行しない**）
- `kaggle kernels push`（Kaggle 上の実行。GPU 枠を消費する）
- `git push` 以外のリモート破壊操作・Release・タグ

## 禁止事項（サブエージェント共通）

- 提出・push・PR 作成・外部送信・`official/` の編集・`data/` の削除
