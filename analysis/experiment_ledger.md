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
| **雑音床（これ以下の差は無視）** | **12 本基底で再計算（08-24）**: base1 後処理の eval-12 per-video から動画再抽出ブートストラップ（再構成 0.9125=公式一致で検算済）: hidden **58 本 SD 0.0087 / 141 本 0.0054 / 199 本 0.0045**。∴ LB 上の差 <0.005 は動画抽選の揺れの帯域内＝**E5 linefit(+0.004) は LB では判定不能、division 帯(+0.03〜0.09) は判定可能**。これは「評価動画が引き直されたときの揺れ」（public↔private の転移）であり、**同一 hidden 上の A/B は対比較（paired）で別途扱う**。旧 4 本推定（58 本 0.014/199 本 0.008）は過大だった | 2026-08-24 |
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

### E2 base1（clean UNet+Transformer+ILP 再現）を Kaggle で実行・提出（2026-08-24・Issue #5）
1. **仮説**: `yusuketogashi/clean-approach…` の自称 clean LB 0.908 が、CV フェーズを外した再現カーネルで再現する。
2. **実装**: `notebooks/base1_clean_unet_ilp/`（元 NB から cell 2, 17–19 を削除。他は原文どおり）。T4、internet off、pack50 + cellmot-artifacts。
3. **事前登録した判定規則**: 公開 test 4 本のローカル公式 score が E1 の同 NB 出力 0.889 ± 0.005 に入れば「再現」。LB は記録のみ（比較対象なし）。実行時間/動画を記録し、×199 が 12h 以内かを判定。
4. **対照**: なし（再現実験）。
5. **結果**: Kaggle v1（T4、2026-08-24 01:34 push、14.9 分で完了）。ローカル公式 score **0.8890**（E1 の元 NB 出力と per-dataset TP/FP/FN まで完全一致: 44b6_0113de3b 47/2/3, 44b6_0b24845f 49/0/0, 6bba_05b6850b 836/7/9, 6bba_05db0fb1 1086/143/97、div 0/3/3）。バリデータ VALID（fork 34/72/9/191）。推論 9.54 分/4 本（1 GPU・D4 TTA）＝143 s/動画、後処理込みで約 201 s/動画 → **199 本で約 11.1h**（12h 上限に対し余裕 1h 未満）。LB: **未提出**（`competitions submit` は分類器ブロック。user 実行待ち）。
6. **判定**: **再現**（規則①）。実行時間は 2-GPU シャード無しでは採用不可寄り（規則③）。
7. **学び**: 生 ILP 出力 geff（`solution` フラグ・`edge_prob` 付き）がカーネル出力に含まれる → 後処理はローカルで回せる（移植中）。

### E3 base2（dual-seed + harmonic 0.20、0.915 構成の再現）を Kaggle で実行・提出（2026-08-24・Issue #5）
1. **仮説**: `kunaldesale2408` の実 LB 0.915 構成（bidir 0.20、safe-div 4.66/8.5/7.65）が再現し、base1 を上回る。
2. **実装**: `notebooks/base2_dual_seed_harmonic/`（cell 0 の未検証値を実証値へ戻す、validator セル削除、manifest の参照修正）。2-GPU シャード。
3. **事前登録した判定規則**: LB(base2) − LB(base1) > 0 で符号一致を記録。**雑音床未測定のため「改善」とは書かない**。E4 の再提出差が出るまで採否判定は保留。実行時間/動画 ×199 が 12h 以内であること（超えるなら採用不可）。
4. **対照**: base1（E2）。
5. **結果（ローカル・v3 2026-08-24）**: v1=manifest 参照バグ、v2=**隠しガード第 2 弾**（predict セル内 `expected_bidirectional_weight: 0.3` の ValueError）→ v3 で成功。ローカル公式 **0.8907**（base1 0.8890、Δ=+0.0017）。per-dataset edge TP/FP/FN = 47/2/3, 47/3/2, 833/18/12, 1104/134/79。div TP=0 **FP=6** FN=3（base1 は FP=3）。node_recall 0.9841。予測 9.27 分/4本（2-GPU シャード）→ 199 本換算 ≈ **7.7h < 12h** ✅。
6. **判定（ローカル分）**: Δ+0.0017 は雑音床（SD≈0.008–0.014）内 → ローカルでは優劣つかず。大きい動画（6bba_05db0fb1）は FN 97→79 と改善、小さい動画は微悪化＝**構成のトレードは動画サイズ依存**。ランタイム条件は合格。LB 提出待ち（提出コマンドは user へ提示済）。
7. **学び**: 公開 NB の**隠しガードは 1 箇所とは限らない**（cell 0 と predict セル内の 2 箇所）。パラメタ変更時は `grep -n <旧値>` を notebook 全体に必ず回す。safe-div しきい値を強めた base2 は div FP を 3→6 に増やした（div TP は依然 0）＝**現行 safe-div は division 項に対し純損失**で、stage-2 division の設計はここを置換する方向。

### E4 同一コード 2 回提出による LB 再実行ばらつき（2026-08-24〜・Issue #2/#5）
1. **仮説**: hidden test の再実行は決定的でなく、同一コードでも LB が揺れる（ROGII 実測 0.017）。
2. **実装**: base2 を版を変えずに 2 回提出（または base1）。
3. **事前登録した判定規則**: |Δ| を「LB 再実行の下限雑音」として前提表に書く。以後、この値以下の LB 差は比較に使わない。
4. **対照**: なし。
5. **結果**: （未着）
6. **判定**: （未着）
7. **学び**: （未着）

### E5 linefit 平滑化のスイープ（window/weight）— ローカル後処理ループ第 1 弾（2026-08-24・Issue #5）
1. **仮説**: 座標のみを動かす linefit（トポロジ・ノード数不変）は 7 µm マッチングの取りこぼしを減らす。hiranorm は w=0.8/win=3 でローカル +0.0086 CI[+0.0048,+0.0116]・LB 転移率 ≥1 を報告。base1 既定は w=0.8/win=2。
2. **実装**: 移植済みスタック（`src/biohub/public_postproc/`）の linefit 直前チェックポイント → `scripts/relinefit.py` で linefit だけ差し替え。アーム: win∈{2,3,4}×w∈{0.6,0.8,1.0}（基準は win2/w0.8）。
3. **事前登録した判定規則**: 公開 test 4 本（in-sample）で、基準との paired Δscore が +0.002 以上 かつ 4 本中 3 本以上で Δadj_J ≥ 0 のアームのみ「LB 検証候補」。それ未満は棄却。**ローカル値だけでは採用しない**（メモ化 train での後処理 A/B は符号反転の前科 #730160。ただし linefit は「誤りを直す」型でなく座標ジッタ補正なので反転リスクは低いと判断、それでも LB 対提出で確認する）。
4. **対照**: 逆方向アーム = w=1.0（過平滑）と win=4（過大窓）。単調でない応答が出れば測定器を疑う。
5. **結果（2026-08-24）**: ゲート合格（checkpoint→relinefit 既定が base1 と 16 桁一致 0.8889681530680414）。8 アーム（score / Δ / 4本中非負）:
   | arm | score | Δ | 非負 | 判定 |
   |---|---|---|---|---|
   | win2_w0.6 | 0.8918 | +0.0028 | 4/4 | 候補 |
   | **win2_w1.0** | **0.8931** | **+0.0041** | 4/4 | **候補（最良）** |
   | win3_w0.6 | 0.8877 | −0.0013 | 3/4 | 棄却 |
   | win3_w0.8 | 0.8921 | +0.0032 | 4/4 | 候補 |
   | win3_w1.0 | 0.8917 | +0.0027 | 4/4 | 候補 |
   | win4_w0.6 | 0.8905 | +0.0015 | 4/4 | 棄却（Δ<0.002） |
   | win4_w0.8 | 0.8885 | −0.0005 | 2/4 | 棄却 |
   | win4_w1.0 | 0.8873 | −0.0017 | 2/4 | 棄却（44b6_0113de3b **−0.1005** 破壊） |
6. **判定**: 規則上は 4 アームが「LB 検証候補」、最良 **win2/w1.0**。ただし**正直な注記**: ①Δ の実体は全アームで**最大動画 6bba_05db0fb1 ただ 1 本**（他 3 本は Δ=+0.0000 の同値＝「非負 4/4」は同値を非負に数えた結果）＝実質 n=1。②w 応答は win2 で非単調（w0.6 も w1.0 も基準 w0.8 より良い）＝基準がたまたま谷。③win4/w1.0 の 44b6 破壊は過平滑がマッチング半径 7 µm を跨いで大量に外す実例＝**linefit は「効きも壊しも」ノード密度と変位の大きい動画に集中する**。→ 採否は LB 対提出（base1 v1 vs base1+w1.0）でのみ決める。E4 の再実行雑音が出るまで Δ+0.004 の LB 差は解釈しない。**base1 v2（LINEFIT_WEIGHT=1.0 のみ変更）を Kaggle 実行済: ローカル採点 0.8931 = 掃引の win2_w1.0 と完全一致**＝カーネル側実装検証済・提出可能。
7. **学び**: ①後処理 1 段だけの差し替えループ（checkpoint 方式）は 1 アーム約 2.5 分＝Kaggle 再実行（約 25 分＋キュー）の 1/10 以下で回る。②公開 test 4 本は 3 本が「linefit 不感」（エッジ数が少ない or ジッタが小さい）＝**この 4 本での後処理 A/B は事実上 6bba_05db0fb1 の単発測定**。hidden（≈200 本）への外挿は動画構成比に依存する。train 12 本 raw geff（eval_train_raw）が届けば n を増やして再測定する。

### E6 division stage-2 の事前登録（2026-08-24・Issue #5）— 空席 0.1 項への最初の攻め
1. **仮説**: div TP=0 の主因は検出器でなくリンカ形状。GT division 形態（完全 geff 30 本・n=12）: d_child_min med 4.65/p90 6.20、**d_child_max med 7.12/p90 12.08**（8.4 µm ゲート超え多数）、**sister med 11.04/p10 8.54/max 17.13 µm**。現行 safe-div は SISTER_MAX_UM=8.5（GT 中央値未満）＝**実 division の ~90% を幾何条件で棄却する設計**。エッジ指標のための「安全な」二叉であって division 検出器ではない。
2. **実装案**: eval_train_raw の train 12 本 raw geff（division 含む選抜）に対し、ローカル checkpoint ループで division 候補生成→2 子エッジ付与→公式 division_jaccard を直接測る。候補幾何は GT 分布から: sister ≤ 18 µm、child 変位 ≤ 14 µm、親は t、子は t+1。
3. **事前登録した判定規則**: train 12 本で division_TP ≥ 3 かつ adj_edge_jaccard の劣化 ≤ 0.001（division エッジ追加は edge FP にもなり得るため差引で判定）。score 合成 Δ ≥ +0.003 で LB 検証候補。**div FP の増加数も必ず記録**（division_J = TP/(TP+FP+FN)）。
4. **対照**: 現行 safe-div（sister 8.5）を同一 raw geff に適用した場合の div TP/FP。
5. **結果（中間・2026-08-24 プロトタイプ、公開 test 4 本）**:
   - **標的注入検証**: 6bba_05db0fb1 の t=24 division の正しい第 2 子エッジを 1 本だけ追加 → score 0.8890 → **0.9061（+0.0171）**（div TP=1、division_J 0→0.1667、そのエッジ自体も edge TP +1）。**メトリクス機構は orphan 養子縁組を div TP として受理する**ことを実証。1 復元 ≈ +0.017（この 4 本セット）。
   - **GT 診断（3 division の失敗様態）**: ①t=24 = 第 2 娘が pred に orphan（in=0、0.91 µm 一致）として存在＝養子縁組で復元可能 ②t=52/62 = 両娘とも既に他トラックへ in=1 リンク済＝**エッジ奪取（rewire）が必要**（in-deg≤1 制約下で既存エッジ削除+追加）。
   - **幾何のみの候補選別は基底率で敗北**: 事前分布に完全適合（sister≈10-11、d_pc≈7）する偽候補が 1 動画に 13+ 本あり、cap を実例が勝ち取れない。3 通りのランキング（near-first / sister下限 / prior-fit）全て div TP=0。偽 orphan の大半はメトリクス不可視（端点が GT 未マッチ）で edge へは無害、しかし div TP も取れない。
   - **cap 掃引（prior ランキング+border≥15 µm+sister≥7.5）**: cap50 = 0.8863（div FP 11、TP 0＝**逆効果**）／cap200 = 0.8907（**div TP 1** 入るが div FP 14・edge FP +6 で純益 +0.0017 のみ）。広く養子縁組は「ほぼ無料」ではない（採用の ~7% が div FP 化）。
   - **特徴分離度の実測（6bba_05db0fb1、候補 ~3,000 対 実 1-3）**: ①境界距離: real 28 µm vs fake med 9.8（p10=0）＝**有効**（~2-3× 削減）②娘ペア対称性 |P−midpoint(C1,C2)|/sister: real 0.35 = fake の 7.6 pctile＝**有効**（13× 削減、229/2995 残存）③orphan 初速・後方外挿: 分離せず ④**輝度（染色質凝縮仮説）: n=3 で pctile 12/63/34 とバラバラ＝分離せず**（t=24 の「暗い重心」は一般化しなかった）。
6. **判定（中間）**: 機構は実証済・選別が未解決。幾何+トラック特徴のスタックで ~50:1 まで削減可能だが精度不足。n=1-3 での閾値調整は過学習なので、**eval_train_raw の 12 本（GT division 選抜）で特徴を再測定してから**候補ランキングを確定する。それでも足りなければ学習型 division 検出器（3D patch 分類器、train GT ~151 陽性、Kaggle GPU 学習）＝全公開 NB が div TP=0 の中の真の差別化要素。
7. **学び（設計段階→全数確定 08-24）**: **全 199 geff census: 151 divisions / 87 動画（0.76/動画）**。形態（n=151）: d_child_min med 4.08/p90 6.86、d_child_max med 7.13/p90 10.05/max 13.53、sister med 10.57/**p10 6.36**/p90 14.36/**max 20.30** µm、t は 0〜97 全域（med 48）。n=12 暫定との差: sister の裾が両側に広い → ゲートは sister∈[5.5,21]・d_pc≤14 に改訂。44b6 系は 26 divisions/71 本、6bba 系は 125/128 本。**規模感: hidden ≈150 divisions、現行 div FP ≈0.75/動画も同規模 → 完全復元+FP 半減で division_J ~0.5 = LB +0.05**（首位との差 0.047 に相当）＝**division が本コンペの差別化軸**という E6 の作業仮説を定量確認。**「1 division = +0.017」は division 項が少数イベントの micro 平均であるため**＝復元 1 本の価値がエッジ数百本分に相当する。rewire は edge TP を壊すリスクと表裏（既存エッジが GT TP なら −1TP+1FN）。

### E7 学習型 division 分類器（2026-08-24・Issue #5）— 3D patch CNN
1. **user 指示（08-24）**: 「学習の推移と public のオーバーフィットに注意して進めて」→ 本実験の設計制約として明記:
   - **学習推移**: per-epoch train loss + val AUC を全 fold で記録（history.json）、best-epoch と最終 epoch の val AUC 差で後期過学習を可視化。
   - **リーク防止**: fold は**動画単位**（同一動画のパッチは同一 fold）。正規化はパッチ内 med/MAD のみ（データセット統計を使わない）。
   - **public 過適合防止**: 閾値は OOF のみから選ぶ。採否判定は train 12 本 eval セット（E6）で行い、公開 test 4 本や LB への繰り返し照会で調整しない。E5 の教訓（効果が 1 動画集中= n=1）を適用し、divison 改善も**動画別の寄与分布**を必ず見る。
2. **データセット（`biohub-div-patches` v3 完了）**: X=(3458, 2ch=t/t+1, 5z, 25y, 25x) uint16。陽性 151（=全 GT division 親、44b6:26 / 6bba:125）、陰性 3,307（midtrack 2,388 + trackstart 919）。全 199 動画・全ゼロパッチ 0。
3. **学習カーネル（`biohub-div-classifier`）**: tiny 3D CNN（Conv3d 16→32→64, GAP, dropout 0.3）+ BCE pos_weight ≈22。4-fold・動画グループ・系統/陽性数で snake-draft 平衡（実測 pos 38/37/37/39、44b6 pos 6/6/6/8）。最終モデルの epoch 数は fold best の中央値+1（固定 40 をやめた）。v1=マウントパス FileNotFound → v2=rglob 探索で再投入。
4. **結果（v2/v3 完了・2026-08-24）**:
   - **学習曲線**: val AUC は ep0 から 0.83–0.92 で平坦（後期過学習なし、best−last の gap ≤ +0.01）。train loss は 1.04→0.72 と下がり続けるが val は不動＝この容量・データ量では epoch 数は効かない。
   - **v2 の教訓: pooled OOF AUC 0.59 は fold 間キャリブレーション混合のアーチファクト**（fold 別 AUC は 0.83–0.92）。fold 内 rank 正規化後の pooled AUC = **0.867**（v3、fold 別 [0.883, 0.900, 0.880, 0.808]）。**スコアを fold 横断で比較・閾値化するときは必ず rank 正規化**。
   - **precision@recall（rank 正規化 OOF、基底率 1:22）**: recall 0.9→prec 0.10 / 0.8→0.15 / 0.7→0.20 / 0.5→0.29。
   - **陰性種別で難度が大きく違う**: div_parent vs trackstart AUC **0.941**（recall 0.9 で prec 0.51）／vs midtrack AUC 0.855。
   - 成果物: fold0–3.pt（各動画を外した fold のモデル＝リーク無し採点用）+ final（14 epochs、全データ）。
5. **eval-12 の現状測定（base1 プリセット後処理・公式指標）**: score **0.9125** = adj_edge_J 0.9076 + 0.1×div_J 0.0488（**div TP=2 / FP=23 / FN=16**、GT div 18）。カーネル同梱バリデータ（base2 構成・deepcenter veto ON）は adj 0.9116 / div_J 0.0800（TP=2 / FP=7 / FN=16）＝**veto は FP を 23→7 に減らすが TP は増やさない**。division 満点の帯域 +0.095 が空いたまま。
6. **eval-12 の失敗様態census（18 GT division・base1 後処理グラフ）**: **steal_needed 10 / orphan_recoverable 4 / daughter_undetected 3 / already_fork 1**。∴ 養子縁組のみの上限は TP 2→6（divJ≈0.24）、steal 込みで TP≈15（divJ≈0.6、+0.05 帯）＝**rewire 機構が価値の過半**。
7. **候補プール（12 本合計）**: adopt 30,766 対 / real 4、steal 1,202,521 対 / real 19（1 division が複数の妥当対を持つ）。ユニーク親 230,947・real 親 18。**oracle 箱フィルタ（real 全維持の最タイト幾何箱）でも 63.9% しか残せない**＝real の特徴レンジが全域に散る。
8. **E6 の border ゲートは n=1 過適合だった（撤回）**: test4 では「境界距離 real 28 µm vs fake 9.8＝有効」だったが、eval-12 の real は border min **1.6 µm**。`border>=15` は real 親 **6/18** しか残さない（>=10 で 9/18、>=5 で 14/18）。divstage2 の BORDER_MIN_UM=15 既定は実 division の 2/3 を捨てる設計＝撤回表に登録。
9. **次**: div_score_cands カーネル（v1 投入済・T4）で 231,615 親パッチをリーク無し採点 → CNN スコア単独と幾何スタックの「real 親の動画内 rank」分布で deployment 判定。既存 fork 668 個の CNN veto 効果も同時測定。
9b. **steal の損益構造（2026-08-24・real steal 19 対の実測）**: 現親 Q が GT 未マッチ（>7 µm）= **奪取エッジの削除がメトリクス不可視 = 13/19（ほぼ無料）**。残り 6/19 は**全て相互 twin 型**（44b6_587a1e22 / 44b6_5f15d135 / 6bba_09961292 の 3 division: P と Q が互いに相手の娘の現親＝分裂親が 2 ノードに割れて各娘を 1 本ずつ持つ motif）。twin 型は「どちらを fork 親にするか」の選択問題で、正解側を選べば edge TP −0（相手の子エッジは元々 GT エッジと不一致）+ div TP +1。∴ steal 機構は ①無料型: Q 未マッチなら単純 rewire ②twin 型: P/Q の近接ペア検出→fork 集約、の 2 パスで設計する。
10. **事前登録（スコア到着前・2026-08-24 10:10）**:
   - **読み出し 1（adopt 経路）**: 動画ごとに親を CNN スコアで順位付けし、real 親 18 個の動画内 rank を記録。top-1 / top-3 / top-10 / 上位 1% の本数を報告。
   - **読み出し 2（固定形スタック）**: `rank_norm(CNN) × rank_norm(幾何 prior-fit)`（重み学習なし・係数フリー）。同じ rank 分布を報告。**eval-12 で重みを調整することは禁止**（調整するなら別の held-out が必要）。
   - **読み出し 3（FP veto）**: 既存 fork 668 の CNN スコア分布を「GT divider 7 µm 以内（TP 相当）」vs それ以外（FP 候補）で比較。veto 閾値 τ を **OOF の trackstart 表**（recall 0.9 → rank 0.60 相当）から取り、eval-12 での div FP 削減数と div TP 損失数を報告。
   - **採用バー**: (a) adopt: top-1 一致が 4 recoverable 中 2 以上、かつ FP veto で div FP ≥ 半減が見込める場合に base1 v3 カーネルへ統合して LB 対提出 1 回で検証。(b) どちらも未達なら steal 機構の設計に先に投資（価値の過半は steal 側 10/18）。
   - **過適合ガード**: 閾値はすべて OOF 由来に固定。eval-12 は「読み出し」にのみ使い、eval-12 上の掃引で閾値を選ばない。LB 照会は統合後 1 回。
11. **結果（読み出し・2026-08-24 10:20）**: 事前登録の採用バー **(a) 未達**。
   - 読み出し 1（CNN 単独・親 rank）: real 18 親 → top1=0 / top3=0 / top10=0 / 上位1%=2。real 親の生スコア 0.03–0.10。
   - 読み出し 2（固定スタック・対 rank）: real 23 対 → **top1=1**（44b6_587a1e22 の steal 対が 87,183 中 1 位）/ top10=2。
   - 読み出し 3（fork veto）: near_GT fork の cnn_rank 0.602 = fake 中央値 0.608 と同じ＝**veto 分離もほぼ無し**。
   - **診断: モデル出力は「fold 定数 + 微小変動」**（GT 中心 OOF ですら positive と negative が 4 桁まで同値の cluster。AUC 0.87 は微小差の順序性で成立していた）。1:22 の学習基底率では見えるが 1:19,000 の deployment では消滅。
   - **機序仮説（設計バグ・次で単独修正）**: RXY=12 の窓は中心 ±4.9 µm しか覆わないが、GT の親→娘変位は med 7.13 / p90 10.05 µm ＝ **第 2 娘がパッチ外**。CNN が見ているのは「親 + せいぜい片娘」で移動細胞と区別不能。
11b. **機構検証（div_rewire を v1 弱スコアで通し・2026-08-24）**: twin 149（過剰=偽 twin 多数）+ adopt 8 + steal 16 の 173 編集で eval-12 公式 **0.9125→0.9138（+0.0013）**。div TP 2→3・FP 23→31・**adj_edge_J は ±0.0000**。★重要: **疎 GT の不可視性により rewire の edge 項コストは実測ゼロ**＝division 攻めのリスクは div FP に局在。選別器の精度がそのまま利得になる構造を確認。twin ゲートは CNN rank 0.95 でも 149 発火＝v4 スコア到着後に再検討。
12. **v4 の事前登録（2026-08-24）**: 変更は**窓の拡大のみ**（RXY 12→24 = ±9.75 µm で d_child p90 を被覆、RZ 2→3）。学習プロトコル・fold・閾値規約は v3 と同一。判定: 同じ読み出し 1–3 を再実行し、(i) real 親 top10 ≥ 4 なら統合設計に進む (ii) 改善が top1% 数個どまりなら hard-negative mining を次の単独変更として実施 (iii) それでも不足なら patch 分類器路線を棄却し steal 幾何+トラック形状特徴の学習（GBDT）へ転線。
13. **v4 結果 = 棄却（CV 段階で悪化・読み出しに進まず）**: fold AUC [0.789, 0.770, 0.850, **0.564**]・pooled rank 0.741（v3 0.867）。★学習曲線の形が v3 と質的に違う: v3 は ep0 から平坦、**v4 は中盤ピーク（0.79-0.85 @ep8-10）→終盤崩落（0.47-0.62）＝真の過学習**。機序解釈: 密組織では ±10 µm 窓に近傍細胞が常在し「2 細胞に見える」が判別力を持たない。広窓は娘被覆と引き換えにニュアンス変動を注入し、151 陽性の tiny CNN では負ける。**「第 2 娘がパッチ外」仮説は誤り側に倒れた**（信号は娘の出現でなく親の形態変化にある可能性）。
14. **寄与分解（v1 スコア・eval-12）**: 幾何 prior 単独 top50=**0**・CNN 単独 top50=**0**・**積スタック top1=1/top10=2/top50=4** ＝ 2 信号は直交、結合のみが濃縮する。∴ CNN の微小信号は実在 → (ii) hard-negative mining を実施する根拠。
15. **次ループの事前登録（hard negatives・単独変更）**: 窓は v3（RZ2/RXY12）へ戻す。eval_train_raw v3 の新規 24 本（eval-12 と不交差）に base1 後処理→候補列挙→v3 fold モデル採点（各動画は held-out fold で）→動画毎 top-K 偽親（K=40、real 除外）を hard negative として div_patches v5 に追加、分類器 v6 を同一プロトコルで学習。判定は eval-12 で読み出し 1–3 再実行（バーは E7-12 と同じ）。並行アーム: 同じ 24 本の pair 特徴で GBDT 選別器（幾何+トラック形状のみ・CNN 不使用）を学習し、同じ読み出しで比較=(iii) の下調べ。

### 提出記録（2026-08-24 11:28 JST・user 許可「必要に応じて提出して」に基づく）
| # | kernel | ver | 実験 | ローカル値 | 予測 |
|---|---|---|---|---|---|
| 1 | biohub-base1-clean-unet-ilp | v1 | E2 再現 | 0.8890 (in-sample) | LB との初アンカー |
| 2 | biohub-base2-dual-seed-harmonic | v3 | E3 | 0.8907 | E2 との符号比較（雑音床 0.0045 未満なら判定不能扱い） |
| 3 | biohub-base1-clean-unet-ilp | v1 | E4 再実行雑音 | 同一コード | #1 との差 = LB 再実行ばらつきの実測 |
| 4 | biohub-base1-clean-unet-ilp | v2 | E5 linefit w1.0 | 0.8931 | Δ+0.004 は雑音床未満＝符号記録のみ、採否には使わない |
残 1 枠は温存。採点 9-12h 報告 → 結果は 08-25 に回収予定。

### 日次監視メモ（2026-08-24 スイープ）
- **LB**: 首位 z7777 0.962 不変。#2 0.959（08-23 新）・#3 TWEAK 0.952（「任意の公開検出器に +0.03-0.05 のプラグイン」を自称した勢力）。0.939-0.962 に上位が密集し 08-22/23 提出でシャッフル中。
- **★Discussion #737101（08-23）**: 「0.928 で停滞」スレの返信者が**自作 division アルゴリズムで division score 0.3** を報告（edge は弱い）＝**非公開勢では division 項の実取得が現実に起きている**。0.1×0.3=+0.03 が実在の到達点として観測された＝E6/E7 路線の外部確証。同スレの助言「edge 失敗を『端点ノード欠落』と『関連付け誤り』に分けて分析せよ」は我々の失敗様態 census と同型。
- 公開 NB に division 突破なし: `0-926-biohub-divsub` はタイトル詐欺（実体 0.912-0.913 の検出崩壊ガード、safe-div は既知の壊れた幾何のまま）。`divaug` 系は 7 月パッチ済み exploit の死骸。
- #736937: NB の「Highest Score」ソートはパッチ前スコアが残留＝NB の表示スコアは信用しない（既知運用則の再確認）。#737103: 手動ラベルが external data か未回答（要追跡）。

### Arm B（合成事前学習）の中間判定（2026-08-24・保留）
- v1-v3 の失敗series: ①FOV 外ノード（境界バグ）②座標がネイティブスケール格納（sniff で解決、v4 で patch 数 9→150/系列に回復）。
- **v4 実測: SYNTH val AUC 0.63→0.67（4ep、上昇途上）**。ただし**決定的制約が判明: sequences は (T=6, Z64, Y64, X64) = XY 1.625 µm/px で競技データ（0.406 µm/px）の 4 倍粗い**。パッチの物理スケール・サンプリングが不一致で、fine-scale の appearance 事前学習としての転移価値は乏しい（作者の 165k division ラベルは検出/motion 学習向きで、我々のパッチ形態分類には解像度が足りない）。
- **判定: Arm B は保留**（v4 の重みは残す。Arm A=hard negatives が停滞した場合のみ「pretrain init vs random init」の 1 対照実験で再訪）。教訓: **外部データは「ラベル数」でなく「測定スケールの一致」を先に検査する**。

### eval-24 ベースライン確定（2026-08-24 12:15）
base1 後処理・公式指標: **score 0.8919**（adj_edge_J 0.8891 / div_J 0.0282、div TP=2 FP=38 FN=31、GT 33、n=24）。eval-12（0.9125）より低い＝division-first 選抜の先頭 12 本は易しい側。**eval-36 合算: GT 51 division・div TP 4 / FP 61 / FN 47（divJ 0.036）**、満点帯 +0.096。GBDT 学習対 492,072（real 36・偽 20% 抽出）と candidates24（465,513 親・real 28・fork 1,467）を Kaggle へ。

### Arm C（GBDT 幾何選別器）判定 = 棄却（2026-08-24 12:20）
eval-24 の 492k 対（real 36）で LightGBM・動画グループ 4-fold: **CV AUC 0.4326 ± 0.2114**（fold 別 0.64/0.58/0.41/**0.10**）。36 陽性では幾何+トラック形状は雑音に過学習するのみ（寄与分解の幾何単独 top50=0 と整合）。**(iii) 単独路線は棄却**。選別は CNN×幾何スタック + hard negatives に一本化。

### hardneg ラウンド判定 = バー未達（2026-08-24 13:20）
v5（960 hardnegs 追加・n=4,418）: fold AUC [0.859, 0.819, 0.804, 0.808]（hardnegs で課題が難化した分の低下は想定内）・**初の後期過学習出現**（fold3 gap +0.17 → fold 保存を best-epoch に変更済）。**eval-12 読み出し: CNN 単独 top10=0/18・スタック top1=1/top10=2＝v3 と実質同一**。スコアの「fold 定数+微小変動」構造も不変。→ **E7-12 バー (top10≥4) 未達、(ii) hardneg 1 巡でも不足、(iii) GBDT は既に棄却済＝登録済み経路が尽きた**。
**構造診断**: RF 計算で conv3 段の受容野 ≈ 15 px < sister 26 px（0.4 µm/px）＝**「1 細胞→2 細胞」の空間パターンを物理的に見られない**うえ GAP が位置情報を消す。tiny CNN が学べたのは輝度/テクスチャ統計の微小信号のみ、という全観測と整合。
**次仮説（新規・高事前確率）**: 生 geff の Transformer **edge_prob** を division 選別に転用（199 本の追跡目的で学習済みのモデル出力を只で使う）。まず real 23 対の候補エッジ被覆率を測る。

### E9 事前登録: Transformer edge_prob の division 転用（2026-08-24 13:45・実行中）
1. **仮説**: 199 本で追跡学習済みの Transformer は、真の娘 C2 に対する「親候補分布」P(src|C2) で divider に高い質量を割く（ILP が別親に割当てた後でも）。データ枯渇の tiny CNN より遥かに強い特徴で、しかも**追加学習ゼロ**。
2. **実装**: eval_train_raw v4 = predict の probs 行列から各 target の top-5 (src, tgt, prob, 座標) を dump（`BIOHUB_DUMP_PAIR_PROBS_DIR`）。val 選抜は eval-12 に戻した。
3. **判定規則（読み出し前に固定）**: eval-12 の real 23 対について、(P,C2) の transformer prob の動画内 rank（solution エッジ除外プール）を測る。**top10 合計 ≥ 4 で rewire の選別器として統合**（E7-12 と同じバー）。幾何との積スタックも同時に測る。
4. **対照**: patch CNN v5 の同じ読み出し（top10=2）。

## ローカル↔LB 相関プロトコル（user 指示 2026-08-24・常設）

**目的**: ローカル評価が LB の順序を予測すること（絶対値の一致ではない）。

| 規約 | 内容 |
|---|---|
| 測定器 | 公式 submodule 直呼びのみ（自前指標での代理判定禁止） |
| 判定セット | eval-36（44b6:6bba=18:18、train と決定が独立）。public test 4 本は in-sample につき判定使用禁止 |
| 判定形式 | **動画対応 paired Δ**（summary 差でなく per-video 差の符号と分布） |
| 分解能 | video-draw SD 0.0045（hidden 199 換算）・GT-draw f=0.5 で adj −0.006〜−0.011 系統。**LB 差 <0.005 は判定不能として扱う** |
| LB 照会 | 事前登録した変更 1 件 = 照会 1 回。public LB への反復照会で選抜しない（ROGII: 可視計器最適化は ρ=−0.47 の反予測子を生んだ） |
| 記録 | 下の相関表に全提出を追記。3 点以上で順位相関を計算し、乖離が出たら原因（系統比・GT 疎さ・実行差）を特定してから次を出す |

### 相関表（提出ごとに追記）
| 提出日 | kernel/ver | 実験 | local test4 | local eval-12 | local eval-36 | LB | 順序整合 |
|---|---|---|---|---|---|---|---|
| 08-24 | base1 v1 | E2 | 0.8890 | 0.9125 | (待) | (採点中) | — |
| 08-24 | base2 v3 | E3 | 0.8907 | — | — | (採点中) | — |
| 08-24 | base1 v1 | E4 | 0.8890 | 0.9125 | (待) | (採点中) | E2 との差=再実行雑音 |
| 08-24 | base1 v2 | E5 | 0.8931 | — | — | (採点中) | Δ+0.004<床=判定不能予告 |

既知の相関リスク（対処不能・記録のみ）: hidden が train と同じ 2 胚由来か新規胚かは未公表。新規胚ならドメインシフトが支配し、ローカル相関の上限そのものが下がる。

---

## 撤回した結論

後から誤りと分かった結論をここに集める。**消さずに残す。** 撤回したら
`grep -rn "<撤回した数値>" analysis/ CLAUDE.md README.md docs/` で引用箇所をすべて直す。

| 元の主張 | いつ・何で覆ったか | 訂正後 |
|---|---|---|
| E6中間「境界距離は有効な選別特徴（real 28 µm vs fake med 9.8、2-3×削減）」・divstage2 の BORDER_MIN_UM=15 既定 | 2026-08-24 E7 eval-12（18 GT division）で real の border min 1.6 µm、border>=15 は real 親 6/18 しか残さない | 境界ゲートは n=1（test4 の 1 division）への過適合。ゲートとして使うなら >=5 µm が上限（14/18）だが、選別は学習型スコアに委ねる |
| E7 v2「pooled OOF AUC 0.59」 | 同日 v2 ログ精査: fold 別 AUC は 0.83-0.92。生スコアの fold 間キャリブレーション差が混合されただけ | fold 内 rank 正規化後 pooled AUC 0.867（v3） |
