# Biohub Cell Tracking — Discussion 全 75 スレッド マイニング結果

対象: `biohub-cell-tracking-during-development` Discussion 全 75 トピック（Top ソート 4 ページで全件取得、2026-08-24 時点）。votes≥3 / comments≥3 / 技術タイトルの計 40 スレッドを全文読み込み（ネスト返信含む）。挨拶・重複質問スレは除外。

**凡例（信頼度）**: 🅐=主催者発言 / 🅑=複数人が再現・裏取りあり / 🅒=単独主張 / ⚠️=矛盾または未確認

---

## A. Hidden test / 評価に関する事実

- **hidden test の規模は train とほぼ同じ（≈199 本）** — Overview 原文 "When a notebook is submitted for rerun, a new hidden test set is swapped in. The size of the hidden test set is approximately the same size as the training dataset." を #717228（sergiquijano, 2026-07-01）と #734237（投稿者不明, 2026-08-20）が引用 — 🅐
- **test の embryo_id は 2 種類、train と重複なし** — #716793（host thibautgoldsborough, 2026-07-01）「there are two unique embryo_ids in the training set. You can assume the test set is roughly similar in size, with no overlap in embryo_ids between train and test」 — 🅐
- **public LB は test の約 29%、private が残り 71%** — #716793（Sangram, 2026-07-03）が LB ページ表記を引用。彼の「public=1 embryo / private=2 embryo」という内訳は本人も "is my assumption!!" と明記 — 🅑（29/71 は Kaggle 表示）/ 内訳は⚠️未確認
- **公開 test の 4 本は train と byte 一致のダミー。LB は別の大きな private set で train と重複なし** — #716062（報告者 2026-07-08 → host 返信 2026-07-10）「these are dummy placeholder files to help you ensure that your submission notebook actually produces a .csv … I assure you there is no overlap」 — 🅐
- **推論では全細胞を追跡する必要があるが、採点は注釈済みのランダム疎部分集合のみ** — #716062（host, welcome post, 2026-06-30）および #723694（host, 2026-07-07）「The task is to track ALL the cells in the video … at test time you are only evaluated on the tracks that we have annotated」 — 🅐
- **ランタイム上限は Code Requirements 記載の 12h GPU。「採点 rerun 専用のより短い上限があるか」は主催者未回答** — #724914（2026-07-13, 回答ゼロ・votes −1）。実測報告は 5.6h で完走→rerun は Notebook Timeout — ⚠️未確認（上限値そのものは公式回答なし）
- **提出 rerun は手元ノートブック実行の約 50 倍かかる** — #734237（2026-08-10）。同スレで「9–12 時間（モデル次第）」（2026-08-11）。#717228 では「199 本で 5 時間」「14 時間でタイムアウト」 — 🅑
- **遅いのは採点ではなく推論。公式スコアラーは train 全件で 1 分強** — #724917（返信, 2026-07-23）「local scoring on all train data runs just over 1 minute … Time how long your code takes over test set of 4 videos, scale it up」。#724917 の OP が立てた「採点コストは連結成分構造に依存」仮説はこの返信で否定 — 🅑（自前でも `local_eval.py` で追試可）
- **メトリクス exploit の中身（2026-07-22 パッチ以前）**: division Jaccard が weakly-connected-component 構造にのみ依存していた。画像外座標 (−10000,−10000,−10000) に「ハブ」ノードを 1 個置き全トラック根に接続 → 予測全体を 1 つの弱連結成分に併合、同座標に合成 fork チェーンを数本追加、実 fork は削除。div_jaccard ≈0 → ≈1.0、スコア +0.1 — #727154（当時3位の参加者, 2026-07-18） — 🅑（後述の公開 NB と一致）
- **exploit の元公開 NB**: `outwrest/metric-hack-minimal-baseline-tta-2gpu` の `augment_dataset` セル（MAX_COMPONENTS=1400、ハブ t=−1000/zyx=−10000、合成 division チェーン 5 本）。**ローカル metric チェックには影響せず提出 CSV だけを書き換える**設計だった。通報 #714101（ngyzly, 2026-07-17）→ NB 作者本人が「自分が見つけた。検証とパッチのために公開した」と表明（2026-07-17） — 🅑
- **パッチ内容（commit aa65e90, 7/17）は 3 つの穴を同時に塞いだ**: ① division は弱連結共有ではなく directed local topology を要求、② 2 フレーム以上を跨ぐ edge を削除、③ merged edge を collapse — #733877（nekkon, 2026-08-08）。同一グラフでの実測: ハブ+偽 fork 40 個で旧 0.9839→**1.0639**、新 0.9839→**0.9794** — 🅑（公式 repo で追試可）
- **再採点は 2026-07-23 01:16 UTC 完了。「exploit していない提出は影響を受けない」が実際は「ほとんどの提出が軽微に下がる」と告知** — #727154（host, 2026-07-18）/ #728324（host, 2026-07-22 → 07-23 完了） — 🅐
- **⚠️ 7月上旬のローカル CV 値は現行メトリクスと比較不能** — #733877（nekkon, 2026-08-08） — 🅑
- **完全重複 edge は edge Jaccard 計算前に除去され、1 GT edge は 1 TP にしか使えない** — #723655（host, 2026-07-16）。同時に「実際に metric を game できたら連絡してください」と明言＝exploit 報告は歓迎される — 🅐
- **スコアは 1.0 を超えうる（バグではない）**。疎 GT ゆえ N_pred < N_true になり adjusted 係数が 1 を超える。train 199 本の注釈ノード数中央値は約 659 — #728300（busyaprime, 2026-07-22） — 🅑
- **⚠️ 重要な訂正**: #734192（2026-08-10）の「`summarise()` は fork を 1 つも含まない提出では division 項を落とすので、fork なし提出＝純粋な adj_edge_jaccard が読める」という主張は**成り立たない**。`official/src/tracking_cellmot/metrics.py:509-522` は `division_tp+fp+fn == 0` のときだけ項を落とし、`division_metrics.py:570-572` は `fn = (GT division 総数) − tp` なので、採点対象 GT に分裂が 1 つでもあれば FN>0 → 項は残る。GT 分裂は 199 本中 87 本に存在（B 節参照）ため hidden 全体でゼロになる見込みはない — 私がソース検算済み・⚠️元主張は誤り
- **自前学習済みモデルを private Kaggle Dataset として推論ノートに載せるのは可。ただし優勝時は再現できること** — #724502（host, 2026-07-13, WinningModelDocumentationGuidelines へのリンク） — 🅐
- **Zebrahub の imaging データと `*_tracks.csv` は外部データとして使用可、test と重複なし** — #734330（host thibautgoldsborough, 2026-08-13）「Yes you are free to use the data and all resources in Zebrahub … There is no overlap with the test set」 — 🅐
- **Cell Tracking Challenge データセットは CTC 主催者からメールで使用許可取得済み（solution description に引用を入れる条件）** — #729057（2026-07-25, 許可メールのスクショ添付）。※Kaggle host ではなく CTC 側の許可 — 🅒（一次資料あり）
- **手ラベルが external data に当たるか・事前 open-source が必要かは未回答** — #737103（2026-08-23, 回答ゼロ） — ⚠️未確認
- **公開 Notebook の表示スコアはパッチ前の水増し値のまま**。"Highest Score" ソートで上位に残る「ゴースト」— #736937（2026-08-22, 主催者返信なし） — 🅑（CLAUDE.md の「公開 NB の表示スコアは信用しない」と整合）

---

## B. データの癖

- **凍結フレーム（連続 2 フレームが byte 一致）が大量にある**。199 本全走査で: 44b6 = 71 本中 **0 本 / 0 ペア**、6bba = 128 本中 **114 本 / 947 ペア（ペア率 7.47%）**、全体 4.81%。しかも複数動画が**同一の freeze スケジュール**を共有（例 `6bba_05b6850b`/`07477033`/`5b28472a` はいずれも frame 4,12,27,42,52,57,59,62,66,76 の後で凍結） — #724283（hengck23, 2026-07-11） — 🅑（byte 比較で再現可能）
- **⚠️ 凍結フレームでも GT は動く**: `6bba_fc516dc6` の t=81/82 は `np.array_equal` が True なのに GT edge は **8.90 µm** 移動（(81,23,175,169)→(82,18,179,161)）。**マッチ半径 7 µm を超える**ので「凍結フレームは前フレームの検出をコピー」戦略は破綻する — #729082（2026-07-25） — 🅑。返信（2026-07-28）: この細胞は Z 方向に 15 voxel 超の大細胞で、正しい中心を出しても両端を 7 µm でカバーできない
- **疎 GT edge にも誤りがある（率は低い）** — #729053（hengck23, 2026-07-10 系の同一投稿者, 2026-07-25）。返信では該当細胞が暗すぎて 3D で位置決めできない例を提示（`bharat0/check-sample-6bba-1d0d8384`） — 🅑
- **人間の目と GT が食い違うケースが少なくない**。GUI で GT と自前の人手選択を比較したところ、食い違い時は自分の判断が正しいと 95% 確信。分裂後の細胞体積が親の 0.5 でなく **0.75** になっており、GT が分裂を正しく打っていない疑い — #732474（2026-08-03 / 2026-08-18） — 🅒
- **境界細胞の GT 分断**: `44b6_12dfb391` で 1 細胞が t=21–24 と t=29–37 の**2 系統**として注釈（間の t=25–28 は y=0 で FOV から半分外れる）。端点間は 4.0 µm。連続追跡すると FP+FN の両方を食う — #726381（2026-07-15, 主催者回答なし） — 🅒
- **train は 2 胚のみ: 44b6=71 本 / 6bba=128 本 = 199 本** — #724283 / #716793 — 🅑
- **2 胚は同一プロトコル・同一機材・同一発生ステージ。撮像セッションのみ別** — #724386（host, 2026-07-13） — 🅐
- **画像は多視点を融合したもので、視点間の輝度差は参照視点に線形スケーリング済み**。顕微鏡は Tomer 2012 設計の自作機 — #724582（host, 2026-07-13） — 🅐
- **voxel は非等方: (Z,Y,X)=(1.625, 0.40625, 0.40625) µm/voxel、Z/Y はちょうど 4.0**。voxel 単位で距離ゲートを書くと Z が 4 倍過小評価される — #734053（maximolorenzoylosada, 2026-08-09）/ #728300 / #733973 — 🅑
- **GEFF のノード座標は zarr のインデックスに直接対応（軸入替・反転・原点シフトなし）。物理スケールは距離計算のときだけ掛ける** — #733389（回答者, 2026-08-07, XY/XZ/YZ で検証済みと明記） — 🅑
- **輝度分位数が zarr メタデータに同梱**: 0.0→15, 0.1→75, 0.9→497, 0.99→1478, 0.999→2145, 1.0→4319。min-max だと 90% の voxel が 0.112 以下に潰れる → **p99 でクリップしてからスケール** — #734053 / #733973（nekkon） — 🅑
- **チャンクは 1 タイムポイント単位 (1,64,256,256) blosc/zstd+bitshuffle。時間方向アクセスは安いが、固定 z を全時刻走査すると I/O が 100 倍** — #734053 — 🅑
- **フレーム間変位（199 本・128,883 GT link）: 中央値 1.82 µm, p95 5.34 µm, p99 8.38 µm。8.4 µm 半径の最近傍で真の link の 99% を覆う**（x/y では ~21 voxel、z では ~5 voxel） — #733973（nekkon, 2026-08-09） — 🅑
- 独立測定: 中央値 **1.86 µm/frame**、lag-1 方向持続 +0.30、姉妹細胞分離 **7.24 µm** — #732103（josefreitasalvesneto, 2026-08-01）。別の 1 本のみの測定では平均 2.20 µm/step、最大 5.74 — #730486（2026-07-29） — 🅑（1.82 と 1.86 は整合）
- voxel 単位の |Δ| 分位（p50/p90/p95/p99）: dz 1/2/2/4、dy 0.5/1.25/1.75/3、dx 0.5/1.5/2/3.75。ただし dz に min −37 / max +35 の外れ値あり — #723655（hengck23, 2026-07-07） — 🅒
- **⚠️ 分裂の総数に矛盾**: #733973（nekkon）は「**151 件**、link 853 本に 1 本、199 本中 **112 本は分裂ゼロ**」。#732103（josefreitasalvesneto）は「**約 304 件**、ノードの 0.26%」。#732103 への返信（2026-08-08）は「2 胚で 26 対 125 = 151」と報告し **151 側を支持** — 151 が有力、304 は要検証
- **GT 疎度**: 全核の約 2.8% が注釈（#732103）。ただし 2 胚で大きく異なり **約 1% 対 約 9%**（#732103 返信, 2026-08-08）。1 動画あたり注釈ノード数の中央値 ≈659（#728300）、追跡系統は 1 動画あたり ≈22 本（#733973）、link は「1% 未満しかラベルされていない」（#723655, hengck23） — 🅑
- **GT edge は 100% が t→t+1 の 1 フレーム跨ぎ。ギャップ補完を学習する必要はなく、無注釈の blob は検出漏れではない** — #733973 — 🅑（`official/metrics.md` と整合）
- 動画間のスコア分散が大きい: **±0.14（変動係数 18%）、最悪 0.460 / 最良 0.984** — #730160（2026-07-28） — 🅒

---

## C. LB で効いたと報告された手法（引用数値つき）

- **ルールベース（学習なし）で当時 7 位 / 344 チーム、LB 0.826** — #716952（isakatsuyoshi, 2026-07-01, NB `isakatsuyoshi/biohub-rule-based-baseline`） — 🅑（NB 公開・LB 値つき）

  | # | 手法 | CV(edge) | LB(public) |
  |---|---|---|---|
  | 1 | DoG blob 検出 + Hungarian linking | 0.682 | 0.663 |
  | 2 | DoG scale 調整 + 8 µm linking | 0.791 | 0.786 |
  | 3 | + gap closing | 0.807 | 0.784 |
  | 4 | + division edges | 0.810 | **0.778** |
  | 5 | **multi-scale DoG（scale-space max）** | 0.824 | **0.826** |

  結論: **検出が最大のレバー**（multi-scale DoG だけで LB +0.040）。検出改善は CV≈LB が約 1:1 で追従。この提出の division Jaccard は「そもそも分裂を出していないので実質 0」。
- 別の参加者のヒューリスティック: CV 0.7448 → LB **0.834**（推論 2h）、CV 0.8213 → LB **0.846**（推論 3h） — #716952（2026-07-03） — 🅒
- **公開 TemporalUNet3D + node transformer + ILP パイプラインの実測**: clean single-seed **0.908** / 検出ロジット 2 seed 50:50 ブレンド **0.910**（出力ノード数が約 1.7% 減）/ 公開 2-seed NB **0.911** — #730924（2026-07-30） — 🅑
- **パッチ後の上位は 0.914–0.929。adj_edge は ~0.90–0.91 で頭打ち、div_jaccard はほぼ全員 ≈0** — #728551（2026-07-23） — 🅑
- 「公開 NB の予測に後段プラグインを付けるだけで **+0.030〜0.050**、単一公開モデルで **0.940 untuned**」— #735352（tweakai, 2026-08-15）。中身は非開示 — 🅒（検証不能）
- 「自前学習で **division 0.3（生値）**、edge は公開 NB より 0.01 低い」— #735352（2026-08-18） — 🅒
- 「public LB で **division_jaccard 0.30（重み後 0.03）/ edge 0.898**。分裂のみを提出して差分から分離した」— #734192（2026-08-10） — 🅒
- 「公開 NB の edge + 自前 division アルゴで **0.928**（3 週間更新なし）」— #737101（2026-08-23） — 🅒
- **過検出はほぼ無料**: GT にマッチしない予測ノードは FP にならず、コストは adjusted 項だけ。損益分岐線はちょうど `1 − 0.1 × 過検出率` なので、**ノードを 10% 増やすなら edge Jaccard の相対 +1% で元が取れる。多くの人はしきい値が高すぎる** — #733877（nekkon, 2026-08-08, 公式コードで合成グラフ実験） — 🅑
- **検出の重複複製は約 9% のコストで見返りゼロ**（1 対 1 割当なので 1 voxel 隣の双子は何にもマッチしない）。**2 モデルの検出を union するならマージ工程が必須** — #733877 — 🅑
- **1 対 1（Hungarian）linker は構造的に division 項を全部捨てる**。出次数が 2 になるノードが存在しないので division Jaccard は厳密に 0.000（テストで 40 FN / 40）。**1.1 のうち 0.1 が画像を見る前に失われる** — #733877 — 🅑（`official/metrics.md` の定義と整合）
- **診断の分解公式**: `edge recall ≈ node recall² × 条件付き linking 精度`。①7 µm 以内のノード recall と予測ノード数 vs 推定数、②両端点が検出できた箇所だけの linking 精度、③現検出のオラクル linker 上界、④分裂の候補 recall@K とランキング品質 — の 4 つを分けて測り、**検出を固定して linker を比較、linker を固定して検出を比較**する — #734604（2026-08-12） — 🅑（#737101 の返信 2026-08-23 も同趣旨: 「取りこぼし edge を『端点ノード欠落』と『association ミス』に二分せよ。自分の場合 linking 問題の多くは実はノード選択段階に起因していた」）
- **残る link 誤りは「2 候補が細胞半径 1 個分以内に並ぶ」少数箇所に集中**。ノード recall が高ければ物理距離最近傍だけで大半の link は解ける — #726924（2026-08-06） — 🅒
- **CV は leave-one-embryo-out（動画単位）で** — #730160（2026-08-02） — 🅑
- **分裂は 2 段目で扱え**: まず「BIRTH 1 個 DEATH 1 個」の分裂なしトラックを学習し、分裂は後処理／stage-2 分類器（外観変化と長期手がかり）で入れる。「2 フレームだけ見て分裂かどうかは人間にも難しい」— #726924（hengck23, 2026-08-06） — 🅒（#716952/#724323 の「素朴な分裂追加は害」と整合）
- **疎注釈下での学習可能ピーク検出**: 二値分類ではなく「各 voxel のロジットを近傍でソフトマックスしたピーク検出」に定式化し、**無注釈 voxel は損失計算に一切入れない** — #723655（hengck23, 2026-07-10） — 🅒
- **疑似ラベルによる密トラック生成**: cellpose 等で密な 3D 点を出し、ultrack / byotrack / ルールベースなど複数の OSS tracker の**一致**で 2–3 フレームの短トラックを作り、ILP / min-cost graph-cut で長トラックに繋ぐ。マスク入力を要求する tracker には**合成 3D ボールをレンダリングして与える** — #723655（hengck23, 2026-07-09/10） — 🅒
- **アフィニティ場 / 時間フロー場**: 「局所ベクトル場を予測してグラフ最適化器に接続を教える」。GT フローは光学フロー＋疎注釈トラックから作る。3D CUDA optical flow は `yongxb/OpticalFlow3d`、3D フロー+Kalman は byotrack — #723655（hengck23, 2026-07-07/10） — 🅒（LB 数値の裏付けなし）
- **CoTracker は 2D MIP なら有効**（LSA/motion/ILP が失敗する大きな方向転換を追える）が、3D 化不可・finetune で位置符号が壊れる・birth/death/division 非対応 — #726924（2026-08-03） — 🅒
- **公開 checkpoint はもう壁。post-processing だけで伸ばすより再学習（前処理・アーキ）** — #734604（2026-08-16） — 🅒

---

## D. 害があった / 中立だったと報告されたもの

- **ルールベースへの division edge 追加: LB 0.784 → 0.778（CV は 0.807→0.810 と上昇）** — #716952（isakatsuyoshi, 2026-07-01） — 🅑
- **gap closing はほぼ中立〜わずかに害**: CV 0.791→0.807 なのに LB 0.786→0.784 — #716952 — 🅑
- **JIRKA ベースライン: `DETECT_DIV=True` で 0.728 → 0.695。`USE_COUNT_CALIBRATION=True` は変化なし** — #724323（2026-07-10） — 🅒
- **Edge Top-K / feature-TTA ブランチ: 0.885–0.886（ベース 0.908 から悪化）** — #730924（2026-07-30） — 🅒
- **最良構成周辺の検出/ILP パラメータ probe はすべて 0.908 で動かず** — #730924 — 🅒
- **🔴 train 上での ablation は符号が反転する**: 公開 checkpoint は `split_manifest.json` の通り **199 本すべてで学習済み**（その "test" 40 本も同じ集合の内側）。ある post-processing 段を切ると train 上で **+0.0184** 出たが、提出したら **LB 0.912 → 0.909**。理由は「これらの段は誤りを直すためのもので、暗記済み動画には直す誤りがないので正解を乱すだけ」。**train ハーネスは本番で最も効く部品を消せと言い続ける** — #730160（2026-08-03, 「これで 1 週間溶かした」） — 🅑（最重要の落とし穴）
- **CV と LB: 方向は合うが public LB は約 10% 楽観的** — #730160（2026-07-28） — 🅒
- **HOCT (royerlab/hoct, general_v0) に自前検出点を合成 3D ボールとして与える**: 調整済み ILP より edge 項で劣り、over-link し、本物の分裂ではなく偽 fork を量産、OSS ソルバで **~45 分/動画**＝提出非現実的。原因は実形態で学習したモデルに一様球がOODだからと推定 — #728551（2026-07-23） — 🅒（検証済みの徒労報告として有用）
- **🔴 時間方向の間引き（stride）で高速化すると edge が t→t+2 以上を跨ぎ、スコアが正確に 0.0 になる（エラーは出ない）**。GT edge は必ず連続フレームなので全 edge が構造的にマッチ不能。修正は **t=0 から連続ブロックを処理**すること。0.0 → 0.366 → 0.380 — #728613（2026-07-31, 自己解決報告） — 🅑
- **ノードの t が実フレーム数を超えると "Submission Scoring Error"（低スコアではなく拒否）**。二分探索で t=0–5 は成功 / t=0–9 は失敗。※事前に作った固定 CSV は無効（test フォルダは private サンプルに差し替わる） — #732674（2026-08-04 の訂正投稿） — 🅑
- **T4 は fp32 が約 25 倍遅い**。公式ベースライン 1 epoch: 素の fp32/bs=8 で 3h 超、AMP+bs=16 で約 2h、工夫後 50 分。自前 GPU なら 50 epoch で 4h — #716062 / #729930 / #732345（2026-08-02〜08-06） — 🅑
- **公開 NB は LB に過剰適合している疑い**（複数人が「使うのが怖い」「CV が低い」と発言） — #735352 / #737101 — 🅒

---

## E. リソース（Kaggle slug / URL）

**公式・採点**
- `github.com/royerlab/kaggle-cell-tracking-competition`（BSD-3, `src/tracking_cellmot/metrics.py`, `scripts/evaluate.py`, `metrics.md`）。**CSV→geff 変換スクリプトは 2026-07-10 頃に追加された** — #716062 / #714101
- Kaggle dataset ミラー（パッチ済みスコアラー）: `dalloliogm/biohub-official-scorer-patched` — #727154
- NB `busyaprime/score-your-cell-tracker-locally`（提出 CSV + train dir → 正確なスコア） — #728300
- NB `inversion/cell-tracking-getting-started-w-nearest-neighbor`（公式 getting started） — #732674

**計測・EDA 系 NB**
- `nekkon/your-linker-cannot-score-a-single-division`（過検出コスト線・重複コスト・Hungarian の division 0） — #733877
- `nekkon/the-linking-radius-is-8-4-um`（変位分布・分裂頻度・geff は素の zarr） — #733973
- `maximolorenzoylosada/your-voxels-are-not-cubes`（異方性・輝度分位・チャンク） — #734053
- `isakatsuyoshi/biohub-rule-based-baseline`（v1–v5 の CV/LB つき） — #716952
- `bharat0/check-sample-6bba-1d0d8384`（GT 誤り例の可視化） — #729053
- ⚠️ `outwrest/metric-hack-minimal-baseline-tta-2gpu`（**パッチ済み exploit。現在は減点要因。使わない**） — #714101

**外部データ**
- 合成データ CC0 18.5GB: dataset `josefreitasalvesneto/biohub-synthetic-dataset` / explorer NB `josefreitasalvesneto/synthetic-3d-microscopy-data-for-cell-tracking`。1,539 静止ボリューム + 2,174 時系列、**165,267 分裂 / 4,056,226 ノード**。評価器と同じ `vol[:, ::4, ::4]` stride ダウンサンプルを再現。DoG 再現率は合成 0.89（中密度）/0.76（高密度）vs 実データ 0.91–0.94 ＝**合成の方がやや難しい**。分裂率は意図的に水増し（4.07% vs 実 0.26%）→ 損失の再重み付けが必要。作者推奨は「事前学習 → 実データで fine-tune」 — #732103
- Zebrahub: `zebrahub.sf.czbiohub.org/imaging` + `*_tracks.csv`（**主催者が明示的に許可**）。ただし tracks は Ultrack 生成の**疑似ラベル**で、分裂と高密度領域に系統誤差あり。手修正は検証用の一部のみ — #734330 / #732474
- Cell Tracking Challenge: `celltrackingchallenge.net/datasets/`（CTC 主催者から引用条件つきで許可取得済み） — #729057

**ツール・可視化**
- napari 可視化 `github.com/tom99763/celltrack-studio`（自前 post-processing のアップロード、動画単位スコア、t→t+1 マッチ確認、3D 軌跡とエラー表示） — #724130
- `github.com/funkelab/motile_tracker`（系統樹表示）、`github.com/royerlab/napari-chatgpt` — #724130
- `github.com/royerlab/hoct` + arXiv 2607.11754（著者が本人と明記。学習コードは査読中で未公開、精度はセグメンテーション品質依存） — #726521
- `github.com/yongxb/OpticalFlow3d`（3D CUDA optical flow）、`byotrack`（3D flow+Kalman） — #723655
- `github.com/luisrosa/from-detection-to-identity`（MIT。動きモデル検証 0.570 µm vs 零運動 1.035 µm = −44.9%。実装本体は非公開） — #734093
- 参考文献: ultrack / trackastra / laptrack / cellect / ascent / OrganoidTracker（#716062）、MPM CVPR2020、Nature Biotech 2022（#716062）、"Cell as Point" arXiv 2411.14833（#726924）、Tomer 2012 顕微鏡設計（#724582）
- `virtual-embryo-zoo.sf.czbiohub.org/dataset/danior`（タスクの動画イメージ） — #722668
- 環境構築チュートリアル（zarr オフライン導入の対処つき、日本語版 Zenn あり） — #727462

---

## 推奨アクション上位 5（期待スコア利得 × 信頼度 順）

1. **検出しきい値を下げて recall を稼ぐ + 重複マージを必ず入れる**（期待 +0.02〜0.04）
   根拠: 過検出のコストは厳密に `1 − 0.1×過検出率` で、10% 増に対し相対 +1% の Jaccard で損益分岐（#733877 🅑）。実 LB では multi-scale DoG による検出強化だけで **+0.040**（#716952 🅑）。`edge recall ≈ node recall²` なので検出漏れは二乗で効く（#734604）。ただし union するなら重複は 1 個あたり ~9% を無駄払いするのでマージ工程は必須（#733877）。

2. **1 対 1 linker をやめ、分裂を「別の 2 段目」で出す**（期待 +0.01〜0.03）
   根拠: Hungarian は構造的に division Jaccard = 0.000 で 1.1 のうち 0.1 を捨てる（#733877 🅑）。実際に「公開 NB の edge + 自前 division」で 0.928（#737101 🅒）、「division 生値 0.30 = +0.03」（#734192 🅒）。**ただし linker に素朴に分裂を混ぜると edge が壊れる**（LB 0.784→0.778, #716952 🅑 / DETECT_DIV で 0.728→0.695, #724323 🅒）。ゆえに分裂なしトラックを先に確定し、外観変化と長期手がかりを使う後段分類器で fork を足す設計（#726924 🅒）。合成データ（165k 分裂, #732103）と Zebrahub（主催者許可済, #734330 🅐）が教師源。

3. **CV を leave-one-embryo-out・動画単位に固定し、公開 checkpoint での train 上 ablation を一切信じない**（期待: 誤った採用の回避＝負の利得を防ぐ）
   根拠: 公開重みは 199 本すべてで学習済み。train 上で +0.0184 と出た ablation が LB では 0.912→0.909 と**符号反転**した実測がある（#730160 🅑）。動画間分散は ±0.14（CV 18%, 最悪 0.460 / 最良 0.984, #730160）＝評価単位が動画である以上、雑音床を先に測らないと 0.001 級の差は判定不能（#735352 も同懸念）。public LB は約 10% 楽観的（#730160 🅒）。

4. **提出 CSV の構造検証とランタイム見積もりを提出前に必ず通す**（期待: 0.0 / Scoring Error による枠の空費を回避）
   根拠: 時間方向の間引きで edge が 2 フレーム跨ぎになると**エラーなしでスコアが正確に 0.0**（#728613 🅑）。ノードの t が実フレーム数を超えると Scoring Error（#732674 🅑）。採点 rerun は手元実行の約 50 倍・実測 9–12h、上限は Code Requirements の 12h GPU で、rerun 専用の短い上限があるかは**主催者未回答**（#724914 ⚠️）。見積もりは「4 本での秒数 × 約 200 本」で行う（#724917 🅑）。5 件/日・チーム 5 名。

5. **物理距離ゲート 8.4 µm（異方性スケール適用）+ 輝度は p99 クリップ後にスケール**（期待 +0.005〜0.02、実装コスト極小）
   根拠: GT link 128,883 本の実測で p99 = 8.38 µm、8.4 µm 半径で真の link の 99% を覆う。voxel 単位で書くと Z が 4 倍過小になる（#733973 / #734053 🅑）。輝度は 90% の voxel が range の 11.2% 以下に集中しており min-max では潰れる（#734053 🅑）。
   併せて **6bba の凍結フレーム（114/128 本, 947 ペア）** を検出したうえで「前フレームをコピー」しないこと — GT は凍結フレームでも 8.9 µm 動く実例がある（#724283 / #729082 🅑）。

---

### 未確認としてマークする項目（再調査候補）
- 採点 rerun 専用のランタイム上限の有無と値（#724914、主催者未回答）
- 手ラベルデータの外部データ該当性・事前 open-source 義務（#737103、回答ゼロ）
- 分裂総数 151 vs 304 の食い違い（#733973 vs #732103）— ローカルの `data/train/*.geff` で自前カウント可能
- public LB 29% の内訳が「1 胚 / 2 胚」かどうか（#716793 の推測、主催者は肯定していない）
- #735352 の「プラグインで +0.030〜0.050、0.940 untuned」（中身非開示・検証不能）
- 各メッセージの投稿者名（Kaggle MCP が author を返さないため、本文から特定できたものだけ記載）