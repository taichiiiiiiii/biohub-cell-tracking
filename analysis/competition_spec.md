# 競技仕様 — 一次情報の統合リファレンス

**最終更新: 2026-09-27**（Kaggle の Overview / Data / Rules / Discussion と `official/` 実装を直接確認）

このファイルの目的は、**課題仕様を1か所で参照できるようにすること**。
`analysis/experiment_ledger.md` は 1 MB を超えて実質参照不能であり、仕様が埋没していた。

確度表記: 🅐 主催者・Kaggle の公式表記 ／ 🅑 参加者の報告 ／ ⚠️ 未確認

関連既存ファイル（重複させず参照する）:
- `docs/research/discussion_mining_2026-08-24.md` — Discussion の一次引用集（2026-08-24 時点）
- `docs/research/public_notebooks_2026-08-24.md` — 公開 notebook 調査
- `analysis/gold_loop_protocol.md` — ループ手順と採用ゲート
- `official/metrics.md` — 指標の公式定義（本ファイルは要約のみ）

---

## 1. タスク

3D+time 顕微鏡動画（ゼブラフィッシュ胚）で細胞を検出し、フレーム間で結合して系統樹を再構成する。
分裂（mitosis）の同定を含む。🅐

## 2. 指標

```
score = adjusted_edge_jaccard + 0.1 × division_jaccard
```

| 要素 | 定義 | 出所 |
|---|---|---|
| node matching | 最適二部割当、**最大 7.0 µm**、物理スケール **z=1.625, y=x=0.40625 µm/voxel** | 🅐 Overview / `official/metrics.md` |
| edge TP | 両端が GT node に match し、その GT node 同士が GT edge で結ばれている | 🅐 `metrics.md` |
| edge FP | TP でない予測 edge のうち、**片端の match 先 GT node が別の相手と結ばれている**もの。**両端とも非 match の edge は分母に入らない** | 🅐 `metrics.md`、実装 `metrics.py:194` `pred_valid = out_valid(source) \| in_valid(target)` |
| node penalty | `adj = max(0, J·(1 − 0.1·(T_pred − T_true)/T_true))`。**符号付き**で、過少予測は**ボーナス** | 🅐 `metrics.md`、`ADJUSTMENT_ALPHA=0.1` |
| 集計 | adj edge は per-sample を **`w = TP+FP+FN` で加重平均**、division は **micro**（TP/FP/FN を合算後に1回 Jaccard） | 🅐 `metrics.md`「Final score」、実装 `metrics.py:470-535` |
| 上限 | **スコアは 1.0 を超えうる**（node ボーナスのため）と Overview が明記 | 🅐 |

**注意点（実測で確認）**: 現在の我々の `total_node_ratio = −0.150465` → 倍率 **1.015046**。
過少予測が罰則ではなくボーナスになっている。

**division metric は 2026-07 に exploit が発見され patch された。** `official/` の HEAD `075fc5f`
（2026-07-18、上流最新と同一）は patch commit `aa65e90` を含むので、ローカル採点は権威あり。🅐 Discussion #727154

## 3. データ

| 項目 | 値 | 出所 |
|---|---|---|
| 画像 | `.zarr` v3、`0/` に `(T,Z,Y,X)`、代表 **(100, 64, 256, 256)** uint16、chunk は 1 timepoint | 🅐 Data |
| GT | `.geff`（tracksdata）。`nodes/props/{t,z,y,x}/values` は**整数 voxel 座標**、`edges/ids` は `(N,2)` | 🅐 Data |
| GT の疎性 | **全細胞は注釈されていない**。実測: 我々の eval12 で推定真 node 287,137 に対し注釈 **7,839（2.7%）** | 🅐 + 実測 |
| `T_true` | `.geff` メタデータの `estimated_number_of_nodes` | 🅐 Data |
| **`T_true` は test 時に入手不可** | `.geff` は **train のみ**。test は `.zarr` だけ | 🅐 Data（導出） |
| 命名 | `{embryo_id}_{field_of_view}` | 🅐 Data |
| **train と test は embryo 非重複** | 「**Train and test sets are embryo-disjoint**」。train の embryo は **2 種のみ**（`44b6` / `6bba`）、test は同規模で重複なし | 🅐 Data + host #716793 |
| 可視 test | 「**Example test samples (copies from train)**」。提出時に hidden test へ差し替え | 🅐 Data |
| hidden test 規模 | 「approximately the same size as the training dataset」 | 🅐 Data |
| 総量 | 24,886 files / 87.61 GB、CC0 | 🅐 |

## 4. Public / Private 分割 — 最重要

| 項目 | 値 | 出所 |
|---|---|---|
| **Public LB = test の約 29%** | 「This leaderboard is calculated with approximately 29% of the test data」 | 🅑 #716793 が Kaggle 表示を引用 |
| **Private LB = 残り 71%** | 同上。**最終順位は Private で決まる** | 🅑 / 規約 3.7 は 🅐 |
| どの sample がどちらか | **参加者に開示されない** | 🅐 規約 3.18(a) |
| public が 1 embryo・private が 2 embryo という内訳 | **本人が "is my assumption!!" と明記** | ⚠️ 未確認 |

**帰結（方法論に直結）**:
1. ローカル eval は **train の 2 embryo** 上の測定。LB は**未知 embryo への転移**を測っている。
   → 同一 embryo 内の改善は LB に出ない可能性がある。
2. `gold_loop_protocol.md` の採用ゲート「**両 embryo で Δ 非負**」は、
   偶然ではなく**唯一利用可能な embryo 間汎化の代理指標**である。最優先で効かせる。
3. Public の 1 read は test の 3 割弱。LB 量子化 0.001 と実測ノイズ床 0.000（E51）は
   **この 29% 上の再現性**であり、Private の再現性ではない。

## 5. 提出

| 項目 | 値 |
|---|---|
| 形式 | notebook のみ（code competition）。`submission.csv` |
| runtime | CPU / GPU いずれも **12 時間以内** |
| ネット | **不可** |
| 外部データ | **公開・無償なら可（事前学習モデル含む）** |
| 1日の上限 | **5 回**（00:00 UTC リセット） |
| 最終選択 | **2 つ**。未選択なら **Kaggle が自動選択** |
| チーム上限 | 5 名。Entry / Merger 締切は 2026-09-22（終了） |
| **最終提出締切** | **2026-09-29 23:59 UTC** |
| 採点遅延（実測） | **7–9 時間** |

### CSV の仕様と、採点側の読み戻しで注意すべき点

列: `id,dataset,row_type,node_id,t,z,y,x,source_id,target_id`
- `row_type=node`: `node_id,t,z,y,x` を埋め、`source_id/target_id` は `-1`
- `row_type=edge`: `source_id,target_id` を埋め、他は `-1`
- `id` は連番の捨て列、`dataset` は test のフォルダ名（`.zarr` を除く）
- **test の全 dataset が現れる必要がある** 🅐

`official/scripts/csv_to_geffs.py` を読んで確認した実装上の性質:

| 性質 | 行 | 含意 |
|---|---|---|
| `z,y,x` を **`pl.Float64` で読む**（丸めない） | L28-30 | 非整数座標は保持される。ただし Data ページは「integer centroid coordinates」と規定し、E47 の float 提出は LB 0.917（当時 0.924）で**実測的に負** |
| `id_map` が **dict** | L33 | **dataset 内で `node_id` が重複すると edge が黙って誤配線される** |
| `id_map[s]` を直接引く | L38 | **存在しない `node_id` を参照する edge は KeyError で落ちる** |
| `zip(..., strict=True)` | L33,L40 | 長さ不一致は例外 |
| dedup・範囲検査なし | — | 同一 `(t,z,y,x)` の重複 node は許容される |

`official/scripts/geffs_to_csv.py` は逆方向で `round(0).cast(Int64)`（L31-33）。

## 6. 賞金・順位

1位 $18,000 / 2位 $12,000 / 3位 $8,000 / 4位 $6,000 / 5位 $6,000 / 6位 $5,000 / 7位 $5,000、計 **$60,000**。
Research カテゴリ、**medal 対象**。勝者ライセンス **MIT**、データ **CC0**。🅐

2026-09-27 時点: **3,929 teams** / 13,475 entrants / 87,465 submissions。

## 7. 実装上の重要事実（`official/` を読んで確認）

| 事実 | 出所 |
|---|---|
| 検出は `F.max_pool3d` の local-max + `sigmoid > det_threshold` | `predict_unet_transformer.py:283-286` |
| 座標は **ダウンサンプル格子の整数 index** をそのまま使う | 同 L286-293 |
| 最後に `coords[:, 1:] *= ds_arr` で掛け戻すだけ（**センタリング補正なし**） | 同 L494-496 |
| `nms_3d` も peak voxel を返すだけ。重心計算・sub-voxel 補正は**無い** | `img_proc.py:140-185` |
| **実測**: 予測 node 299,853 件の **Y mod 4 = 0 が 100%、X mod 4 = 0 が 100%**（`downsample=(1,4,4)`） | E67 |
| **実測**: node recall は **7,803 / 7,839 = 99.54%**、match 済み平均距離 **1.70 µm**（7 µm 門の 1/4）。**node 位置に余地なし** | E67 |

### 7.1 採点側のグラフ前処理（`metrics.py` 全文通読、2026-09-27）

`_evaluate_matched_graph` は Jaccard 計算前に予測 edge を次の順で**落とす**（落ちた edge は TP にも FP にも数えない）:

| 順 | 処理 | 出所 |
|---|---|---|
| 1 | 同一 (source,target) の重複 edge を 1 本に | `metrics.py:61-66` |
| 2 | `t_target − t_source ≠ 1` の edge を削除 | 同 L74-87 |
| 3 | 同じ GT edge に写る複数予測 edge は **EDGE_ID 最小の 1 本だけ残す**（merge の水増し防止） | 同 L94-135 |
| 4 | **出次数 > 2 のノードは EDGE_ID 小さい 2 本だけ残す** | 同 L140-153 |
| 5 | `pred_valid = out_valid(src) \| in_valid(tgt)`、未マッチは False → 両端が GT 外の edge は分母に入らない | 同 L165-195 |

- `summarise`: adj edge は `w=TP+FP+FN` 加重平均、division は micro、`node_recall` は単純平均（`metrics.py:471-536`）。
- `evaluate_datasets`（micro のみ）は LB の集計ではない。LB と同じ集計は `summarise`。

### 7.2 division の FP 規則（`division_metrics.py` 全文通読、2026-09-27）

FP = `(considered ∪ evaluable ∪ cross_component ∪ malformed) − TP`（fork ID の和集合、`division_metrics.py:389`）。

| 集合 | 条件 | GT 依存 |
|---|---|---|
| considered | GT division の窓（親側マッチ node とその後継）に入った予測 fork で TP にならなかったもの | あり |
| evaluable | fork 自身が GT node にマッチし、その GT node の out_degree ≥ 1 | あり |
| cross_component | 異なる子枝の最寄りマッチ証拠が**別の GT 弱連結成分** | あり |
| **malformed** | 子の predecessors が `{fork}` でない（子が merge 先）、または未マッチ子の孫が merge 先 | **子レベルは GT 非依存** |

**malformed 規則は GT 注釈の外でも FP を生みうる**ため構造だけで検査できる。実測（E59 / E70 / E57 の submission.csv）:
merge（入次数>1）**0**、出次数>2 **0**、非 t+1 edge **0**、merge 子を持つ fork **0**（fork 数 99 / 101 / 99）。
**→ この規則から取れる点は無い（仮説棄却）。** 残る未検査は「未マッチ子の孫が merge 先」だが、merge が 0 件なので同じく 0。

## 8. 2026-08-24 時点で既に結論が出ていたのに、我々が守っていない方法論

`docs/research/discussion_mining_2026-08-24.md:152` に既にこう書かれている:

> **CV を leave-one-embryo-out・動画単位に固定し、公開 checkpoint での train 上 ablation を一切信じない**

**我々の eval12 は 44b6 と 6bba を混在させており、leave-one-embryo-out になっていない。**
この乖離は 2026-09-27 時点で未解消。採用判定では少なくとも
「両 embryo で Δ 非負」を必須条件として運用する。
