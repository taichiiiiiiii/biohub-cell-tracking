# 実験台帳 — Biohub Cell Tracking

このファイルが一次記録である。**判定規則は結果が届く前に書く。** 後から書き換えない。
E 番号は採番前に `grep -n "### E" analysis/experiment_ledger.md` で衝突を確認する。

## 前提（Day 1 に埋める）

| 項目 | 値 | 確認日 |
|---|---|---|
| コンペ | `biohub-cell-tracking-during-development`（コード提出のみ・5 件/日・チーム上限 5・締切 2026-09-29・新規参加/合流締切 09-22。出典: Kaggle API `competitions_list` の `isKernelsSubmissionsOnly`/`maxDailySubmissions`/`mergerDeadline`/`newEntrantDeadline`） | 2026-08-24 |
| 指標 | `score = adj_edge_jaccard + 0.1 × division_jaccard`。edge J = TP/(TP+FP+FN)、7 µm 最適割当、疎 GT ゆえ未マッチノードは FP にならない。`adj = max(0, J·(1 − 0.1·(N_pred − N_true)/N_true))`、N_true = geff メタ `estimated_number_of_nodes`。動画横断はマイクロ平均（adj edge は w=TP+FP+FN 加重）。定義 `official/metrics.md`、実装 `official/src/tracking_cellmot/metrics.py` | 2026-08-23 |
| 評価単位 | 動画。2 系統 `44b6`（train 71 本）/ `6bba`（train 128 本） | 2026-08-23 |
| 公開 test 4 本 | `44b6_0113de3b`, `44b6_0b24845f`, `6bba_05b6850b`, `6bba_05db0fb1` = train と同一・GT 付きの**ダミー**（主催者回答 Discussion #716062, 2026-07-10）。ローカル値は **in-sample 扱い** | 2026-08-24 |
| hidden test | train と重複なし・**規模は train と同程度**（Overview 引用 #734237 ≈ 200 本）。採点は「ランダムな疎部分集合」。系統比・public/private 内訳は**未確認**（Issue #2） | 2026-08-24 |
| 採点時間 | ノートブック実行の約 50 倍、9〜12 時間の報告（#734237）。上限値は未確認 | 2026-08-24 |
| 指標の改訂 | 2026-07-22 に division 指標 exploit をパッチ・全提出再採点（#728324）。`official/` は 08-18 更新の main を固定 | 2026-08-24 |
| GT の疎さ | `44b6_0113de3b` 52 ノード / N_true 25,755、`44b6_0b24845f` 51 / 32,795、`6bba_05b6850b` 861 / 6,362、`6bba_05db0fb1` 1,229 / 69,800、`6bba_c328f2fd` 511 / 31,228 | 2026-08-23 |
| **雑音床（これ以下の差は無視）** | **未測定**（Issue #2。動画単位ブートストラップ、train 全量で per-dataset 行を取る） | — |
| LB 再実行のばらつき | 未測定（同一コード 2 回提出） | — |
| 誤差の集中度 | 未測定 | — |
| オラクル上界 | 未測定（GT 自身 / 検出のみ完璧） | — |
| カーネル実行時間の上限 | **未確認**（Rules / Code Requirements ページ。ローカルで閲覧不可のため公開 NB の記述か user 経由で確認） | — |
| 1 動画あたり実行時間 | smoke（NN スターター、CPU ローカル）: 約 6.5 秒/動画 | 2026-08-23 |
| ベースライン | smoke NN スターター: 公開 test 4 本でローカル公式 score **0.0446**（adj_edge_J 0.0446、div_J 0、node_recall 0.065） | 2026-08-23 |
| 参考（外部・未再現） | LB 首位 0.962、公開 NB 自称 clean 0.908 / UNet 0.857 | 2026-08-23 |
| 目標 | 未設定（Day 1 後に決める） | — |

> **雑音床が埋まるまで「改善」と書かない。**

## 固定分割（Week 1 で確定する）

| 名前 | 動画 | 用途 |
|---|---|---|
| （未確定） | 各系統 4 本の固定セットを決める。公開 NB の weights が学習済みの動画は除外 | ゲート |

---

## 書式

```
### E<番号> <一行の要約>（<日付>・Issue #N）
1. **仮説**: 何がなぜ効くと考えたか
2. **実装**: 何をどう変えたか（差分の場所）
3. **事前登録した判定規則**: 採用条件 / 棄却条件を数値で（score Δ と系統別の符号）
4. **対照**: 逆方向のアーム、またはプラセボ
5. **結果**: per-dataset 表（TP/FP/FN・N_pred・adj_J）と summary。雑音床との比較つき
6. **判定**: 規則の機械適用。規則に合わないなら「判定不能」
7. **学び**: 次に転用できる形で
```

---

## 実験

### E0 smoke: NN スターターの端から端までの実行（2026-08-23・Issue #1）
1. **仮説**: なし（環境検証）。
2. **実装**: `notebooks/smoke_nn_baseline/main.py`（90 パーセンタイル閾値 + 連結成分 + ハンガリアン NN、15 µm ゲート）。
3. **事前登録した判定規則**: なし（採否対象でない）。
4. **対照**: なし。
5. **結果**: 公開 test 4 本、ローカル 26 秒。

   | dataset | nodes | edges | edge TP/FP/FN | div TP/FP/FN | adj_J |
   |---|---|---|---|---|---|
   | 44b6_0113de3b | 2,106 | 1,347 | 2/3/48 | 0/0/0 | 0.0412 |
   | 44b6_0b24845f | 1,258 | 639 | 0/0/49 | 0/0/0 | 0.0000 |
   | 6bba_05b6850b | 415 | 304 | 69/15/776 | 0/0/0 | 0.0877 |
   | 6bba_05db0fb1 | 3,288 | 2,339 | 17/12/1,166 | 0/0/3 | 0.0156 |

   summary: score 0.0446（edge_J 0.0408、adj_edge_J 0.0446、div_J 0: TP/FP/FN=0/0/3）、node_recall 0.0646。出典 `outputs/smoke_local/score.json`。
6. **判定**: 対象外。
7. **学び**: `44b6` 系は GT が 50 ノード程度しかなく、粗い検出では 7 µm 以内にほぼ当たらない（TP 2 と 0）。系統別に検出器の感度を変える必要がある可能性。N_pred は N_true の 5〜8% なのでこの段階では adj ペナルティは負（ボーナス側）。

### E1 公開 NB の出力 CSV を公式指標で再測定（2026-08-24・Issue #5）
1. **仮説**: なし（測定）。公開 NB の「表示スコア」がどれだけ実体を表すか、系譜ごとの実力を同じ物差しで並べる。
2. **実装**: `scripts/score_kernel_output.py`（`kaggle kernels output` で公開 NB の submission.csv を取得 → `src/biohub/evaluate.py`）。公開 test 4 本＝train のダミーなので **in-sample**（学習系の重みは train 199 本すべてで学習済み）。
3. **事前登録した判定規則**: なし（採否対象でない）。
4. **対照**: なし。
5. **結果**（score = adj_edge_J + 0.1·div_J、4 本マイクロ平均）:

   | NB | score | edge_J | div_J | node_recall | N_pred | 判定 |
   |---|---|---|---|---|---|---|
   | inversion/cell-tracking-getting-started-w-nearest-neighbor | nan | nan | nan | nan | 0 | clean |
   | kaiwalyaatulraut/biohub-cell-tracking-solution | 0.9178 | 0.9227 | 0.0 | 0.998 | 135,824 | **HACK**（hub+偽fork セル） |
   | anhadmahajan06/biohub-track-your-cells-development | 0.8955 | 0.8946 | 0.0 | 0.998 | 122,910 | clean |
   | yusuketogashi/lb897-baseline | 0.8918 | 0.8913 | 0.0 | 0.983 | 126,469 | clean |
   | raykkretzschmar/biohub-harmonic-bidirectional-association-v1 | 0.8907 | 0.8893 | 0.0 | 0.984 | 122,083 | clean |
   | yusuketogashi/no-hack-biohub-cell-another-approch-3rd | 0.8905 | 0.8901 | 0.0 | 0.984 | 123,090 | clean |
   | pilkwang/biohub-cell-tracking-two-seeds-logit-blend | 0.8897 | 0.8875 | 0.0 | 0.983 | 119,039 | clean |
   | yusuketogashi/clean-approach-lightweight-local-cv-no-hack | 0.8890 | 0.8855 | 0.0 | 0.982 | 120,246 | clean |
   | yunusgmsoy/kimi-notebook-v17 | 0.8878 | 0.8864 | 0.0 | 0.983 | 122,208 | clean |
   | kunaldesale2408/biohub-cell-tracking | 0.8878 | 0.8864 | 0.0 | 0.983 | 122,208 | clean |
   | pilkwang/biohub-cell-tracking-learned-graph-w-gap-recovery | 0.8876 | 0.8928 | 0.0 | 0.998 | 136,809 | clean |
   | evgendvorkin/biohub-0-902-lb | 0.8870 | 0.8856 | 0.0 | 0.983 | 122,252 | clean |
   | xiaoleilian/biohub-ct-mix-divaug | 0.8696 | 0.8706 | 0.0 | 0.972 | 145,511 | clean |
   | thibautgoldsborough/unet-baseline-inference-submission | 0.8081 | 0.8197 | 0.0 | 0.986 | 164,682 | clean |
   | seshurajup/lb-0-857-best-rule-base-v14 | 0.7840 | 0.7823 | 0.0 | 0.919 | 136,208 | clean |
   | pilkwang/biohub-cell-tracking-data-model-eda-baseline | 0.7444 | 0.7418 | 0.0 | 0.882 | 129,289 | clean |

   smoke（E0）は 0.0446。出典 `outputs/public_nb/*.json`。
6. **判定**: 対象外。
7. **学び**: ①**全 NB で division TP=0**（0.1 の項が空席）。②学習系（pack50 UNet+Transformer+ILP）は 0.87〜0.89、ルールベースは 0.74〜0.78、公式 UNet は 0.81（N_pred 過多 55k vs N_true 33k で −7%）。③最高値 0.918 の `kaiwalyaatulraut` は hub+偽 fork の HACK 系で除外。④adj 係数は N_pred<N_true で 1 を超える（`44b6_0b24845f` で 1.038）＝ノード数を減らす方向の「見かけの改善」が混入するので、A/B ではノード数を固定して比較する。⑤in-sample なので hidden の推定には使わない（LB 自称 0.908 に対し 0.889）。

---

## 撤回した結論

後から誤りと分かった結論をここに集める。**消さずに残す。** 撤回したら
`grep -rn "<撤回した数値>" analysis/ CLAUDE.md README.md docs/` で引用箇所をすべて直す。

| 元の主張 | いつ・何で覆ったか | 訂正後 |
|---|---|---|
| （まだ無し） | | |
