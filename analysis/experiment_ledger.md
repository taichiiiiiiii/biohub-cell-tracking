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
| **雑音床（これ以下の差は無視）** | **桁の推定のみ**（`scripts/noise_floor_tracking.py`、base1 の 4 本から動画再抽出ブートストラップ）: hidden 58 本で SD 0.014 / 141 本で 0.009 / 199 本で 0.008。⚠️ 4 本ゆえ桁としてのみ扱う。これは「評価動画が引き直されたときの揺れ」（public↔private の転移）であり、**同一 hidden 上の A/B は対比較（paired）で別途扱う**。eval_train_raw の 12 本が届いたら再計算 | 2026-08-24 |
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
6. **判定**: 規則上は 4 アームが「LB 検証候補」、最良 **win2/w1.0**。ただし**正直な注記**: ①Δ の実体は全アームで**最大動画 6bba_05db0fb1 ただ 1 本**（他 3 本は Δ=+0.0000 の同値＝「非負 4/4」は同値を非負に数えた結果）＝実質 n=1。②w 応答は win2 で非単調（w0.6 も w1.0 も基準 w0.8 より良い）＝基準がたまたま谷。③win4/w1.0 の 44b6 破壊は過平滑がマッチング半径 7 µm を跨いで大量に外す実例＝**linefit は「効きも壊しも」ノード密度と変位の大きい動画に集中する**。→ 採否は LB 対提出（base1 v1 vs base1+w1.0）でのみ決める。E4 の再実行雑音が出るまで Δ+0.004 の LB 差は解釈しない。
7. **学び**: ①後処理 1 段だけの差し替えループ（checkpoint 方式）は 1 アーム約 2.5 分＝Kaggle 再実行（約 25 分＋キュー）の 1/10 以下で回る。②公開 test 4 本は 3 本が「linefit 不感」（エッジ数が少ない or ジッタが小さい）＝**この 4 本での後処理 A/B は事実上 6bba_05db0fb1 の単発測定**。hidden（≈200 本）への外挿は動画構成比に依存する。train 12 本 raw geff（eval_train_raw）が届けば n を増やして再測定する。

### E6 division stage-2 の事前登録（2026-08-24・Issue #5）— 空席 0.1 項への最初の攻め
1. **仮説**: div TP=0 の主因は検出器でなくリンカ形状。GT division 形態（完全 geff 30 本・n=12）: d_child_min med 4.65/p90 6.20、**d_child_max med 7.12/p90 12.08**（8.4 µm ゲート超え多数）、**sister med 11.04/p10 8.54/max 17.13 µm**。現行 safe-div は SISTER_MAX_UM=8.5（GT 中央値未満）＝**実 division の ~90% を幾何条件で棄却する設計**。エッジ指標のための「安全な」二叉であって division 検出器ではない。
2. **実装案**: eval_train_raw の train 12 本 raw geff（division 含む選抜）に対し、ローカル checkpoint ループで division 候補生成→2 子エッジ付与→公式 division_jaccard を直接測る。候補幾何は GT 分布から: sister ≤ 18 µm、child 変位 ≤ 14 µm、親は t、子は t+1。
3. **事前登録した判定規則**: train 12 本で division_TP ≥ 3 かつ adj_edge_jaccard の劣化 ≤ 0.001（division エッジ追加は edge FP にもなり得るため差引で判定）。score 合成 Δ ≥ +0.003 で LB 検証候補。**div FP の増加数も必ず記録**（division_J = TP/(TP+FP+FN)）。
4. **対照**: 現行 safe-div（sister 8.5）を同一 raw geff に適用した場合の div TP/FP。
5. **結果**: （未着 — eval_train_raw v2 の raw geff 待ち）
6. **判定**: （未着）
7. **学び（設計段階）**: n=12 の分布は暫定。全 199 geff の DL 完了後に census を更新し、しきい値は最終分布で引き直す。

---

## 撤回した結論

後から誤りと分かった結論をここに集める。**消さずに残す。** 撤回したら
`grep -rn "<撤回した数値>" analysis/ CLAUDE.md README.md docs/` で引用箇所をすべて直す。

| 元の主張 | いつ・何で覆ったか | 訂正後 |
|---|---|---|
| （まだ無し） | | |
