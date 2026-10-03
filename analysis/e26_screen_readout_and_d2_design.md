# E26 SCREEN結果と次ループD2 — 2026-09-08

親単独で設計・分析・実装・テスト・自己レビューを行う。サブエージェント、Qwen委任、
代理タスクは使わない。自己レビューを独立レビューとは呼ばない。

## 結論と証拠

E26 `e23_motion_relink_off_v1` は **SCREEN_REJECT_EVAL12**。採用せず退役する。
E23の自分のLB **0.924**を維持。既知のE26提出は **0.922**で不採用、再提出しない。
ローカル集約の上昇を金メダル圏の精度やhiddenでの改善へ読み替えない。

run: `e26_motion_off_screen_v2_20260908073709Z`。
生成session43110、採点session77264はともにexit0で終了。例外やtimeoutによる棄却ではない。
全3armの生成・構造・生統計・全境界補正・source/input/依存・元登録pair・直列性の検証後、
fresh score processが公式APIを使いeval12だけを採点。共通finalizerと監督の再検証も完了した。
eval24/36の採点artifactは無く、当runではeval24のGT graphを意味的に開いていない。
整合性確認のための不透明GT byte照合とは区別する。

| 保存物 | SHA256 |
|---|---|
| PREREGISTRATION.json | `5abd92bd3ccd6533769a66e71e44f61b4b0a7b88d5d8228c0dbd195a43d1aa02` |
| GT_BINDING.json | `f2842591cfa6750a443aae0d6d2ffd44616b1c0d7ad3bb93cb0f6a83a662b3b1` |
| GENERATION_SEAL.json | `38e7ca8c768d3a4263bbea92687ebde90f8a85a5e7847ff0babcaf7449c55a2d` |
| scoring/eval12.json | `0e53e36ae3efb5636a1b8ee46fc2b5cdd1aa3d8090c1c5853daef9ea2eaf45f4` |
| scoring/SCORE_RESULT.json | `ecb81ff87e08f7c74ab1d4b60357aae2f81373a9f564574bccc4fd9ebeaaac57` |
| scoring/SCREEN_RESULT.json | `ab7476b5eff490229be573ce5e55ef467a0b2a5ddc1c895862eb8548040cd216` |

保存先は既存canonical内の`outputs/local/e26_screen_preregistrations/<run>/`と
`outputs/local/e26_screen/<run>/`。元v1失敗、v2 source/契約、提出済v3も改変しない。

## 公式採点の内訳

| eval12の量 | E23基準 | motion OFF候補 | 候補−基準 |
|---|---:|---:|---:|
| 公式aggregate combined | 0.9272489144560833 | 0.9484374561398542 | +0.021188541683770934 |
| aggregate adjusted edge J | 0.9154842085737304 | 0.9366727502575013 | +0.021188541683770934 |
| aggregate division J | 0.11764705882352941 | 0.11764705882352941 | 0 |
| edge TP / FP / FN | 7253 / 370 / 338 | 7310 / 256 / 281 | +57 / −114 / −57 |
| division TP / FP / FN | 4 / 16 / 14 | 4 / 16 / 14 | 0 / 0 / 0 |
| predicted nodes | 250465 | 247277 | −3188 |
| 公式summary node recall | 0.983701512198933 | 0.9824228081735836 | −0.0012787040253494 |

paired combined mean **+0.035353698667888935**、median **+0.01645282711621321**、
worst **−0.01332052562821795**。meanは公式aggregate差ではない。
6条件のうち最初の不合格は`paired_worst`（必要値≥−0.002）、他5条件は通過。
9本良化・3本悪化。全12本の差を隠さず記録する:

| dataset | paired combined Δ |
|---|---:|
| 44b6_12dfb391 | −0.007086620200060012 |
| 44b6_267148e4 | +0.05338592359877192 |
| 44b6_2a2eff9f | −0.011340747558933328 |
| 44b6_341df25f | −0.01332052562821795 |
| 44b6_587a1e22 | +0.11246675190274813 |
| 44b6_5f15d135 | +0.074735648474065 |
| 6bba_062c8d37 | +0.012732195295557247 |
| 6bba_07e24132 | +0.018707921600465194 |
| 6bba_085bf656 | +0.00042138858609186425 |
| 6bba_09961292 | +0.014197732631961224 |
| 6bba_0e7c0d07 | +0.12534669725944458 |
| 6bba_12665c0e | +0.04399801805277337 |

系統aggregate combined差は44b6 **+0.021455222700112464**、6bba **+0.021703176904293686**。
division FPは44b6で7→4、6bbaで9→12と相殺。全体のdivision不変は全動画不変を意味しない。
44b6_587a1e22と44b6_5f15d135はdivision FP削減が各singleton combinedに+0.05を寄与し、
paired meanを押し上げている。疎GT・小分母の動画を全体の改善幅へ一般化しない。

## 分かった原因と、まだ分からない原因

1. **判定の原因は確定:** 3悪化動画すべてがworstの許容幅を超える。最悪動画はedge TP206→203、
   FP1→1、FN3→6、division counts不変。単に分裂評価の揺れだけで落ちたのではない。
   残る悪化2本のedge TP/FP/FN差は順に−7/−1/+7、−1/+2/+1。
2. **処理経路の変化は実測:** 全36のmotion countersは候補で全7種0。
   最終nodes−12580の内訳はgap追加+2194、孤立node削除減による+375、短track削除増−15149。
   この収支は各36動画でも厳密一致する。edgeは全体で−16939、safe divisionsは+211。
3. **「短track削除増がスコア悪化原因」とはまだ言えない:** eval12ではedge TP増・FP減もあり、
   少ない出力が全て誤削除ではない。各GTに対応したnode/edgeの変化を追う必要がある。
   GTは疎なので未対応予測を一律FP扱いしない。
4. **local/LBの符号差は未解決:** local aggregateは正、既知LB差は−0.002。
   localは反復利用済み12動画・固定raw・CPU後処理、LBはhiddenのfull pipeline。
   source/入力生成/実行条件の差と、データ構成による差を分離していない。
   0.005のvideo-resampling bufferを同じhiddenへの提出差の標準誤差とは扱わない。

## 次ループD2の固定設計

目的はE26を救済することではなく、**次候補を選ぶ前に、移植差と局所的な追跡損失を区別すること**。
新学習・予測生成・閾値探索・GTによる復元規則・E26再提出はこの診断へ含めない。

### D2A — まず保存物だけでlocalと提出経路を比較

2026-09-08追記: 保存経路比較を完了。[D2診断の証拠表・次の実装単位](e26_d2_diagnostic.md)を参照。
targetだけにある境界補正差、local/targetのdevice方針差、旧raw生成sourceの未保存範囲を明記した。

- 仮説A: local改善とLB悪化の差に、実効source/config/raw生成/重み/実行環境の違いが混入している。
- 元E23と提出済E26 v3の保存notebook/source/metadata/log/出力provenanceを、local登録と対比する。
  同名profileやpublic4の一致だけで、hidden全体の実行同値性を認定しない。
- 表に各比較項目の元path/SHA、値、同一/相違/未検証と、その差が影響し得るstageを書く。
  target E23→E26の意図した差と、local→targetの差を別の列へ分離する。
- ネットワーク再取得・terminal LB再照会・新workerは不要。保存物が不足なら、その項目だけ未検証とする。
- 終了条件: 全候補条件とraw生成設定・weight/device・bounds処理について証拠対応表を完成。
  相違が見つかっても直ちに本番や旧runを修正しない。artifact同値と科学的同値の限界を明記する。

### D2B — 既露出eval12だけで正しい追跡の損益を分類

- 仮説B: 悪化3動画では、基準が正しく結んだGT edgeの一部が、候補の端点消失・座標対応変更・
  対応端点間のedge消失のいずれかで失われている。これは分類仮説であり、閾値変更の仮説ではない。
- D2Aの結果を受けて、保存済CSVと同じ公式matchingの再利用APIを先に確認する。
  既存D0/D1の集約や非保持matching hashだけを新しい写像の証拠として流用しない。
- 診断対象は既に採点済みのliteral eval12全12本。悪化3本だけを選んで説明を作らず、
  良化9本も同じ分類で比較する。eval24のGTは開かない。
- matchingを保存していないため、実GT診断の前に、使う公開API、完全な対応写像/個票の保存、
  合成fixtureの分類テスト、読み込むGT/CSVのSHA、数値時間/RAM上限を次の実装単位で固定する。
  この文書だけで新しい実GT診断を起動したとは扱わない。
- 終了条件: 全12本のedge TP/FP/FNとdivision countsを今回の保存公式行へ一致させ、
  基準→候補の各GT edgeの遷移を相互排他的に分類し、個票合計と集計が一致すること。
  端点ID、t、座標、edge有無を保持し、raw/finalだけから中間stageを断定しない。

### 次候補への判断

- 実行経路の意味のある不一致が見つかった場合は、その影響範囲を先に診断する。
- 一致が確認できてもhiddenで同じ効果があるとは証明しない。局所損失の分類と過去の棄却群を踏まえ、
  新しい情報を使う一因子候補を設計する。同じmotionのblend/bonus/radius救済探索へ戻らない。
- E17 rankerは元source完全取得の既存HOLDを保ち、消化済み取得予算を無言で追加しない。
- 新学習へ進む設計なら、動画分割の汚染確認、training/validation Lossの推移とcheckpoint選択根拠を
  事前に必須化する。今回の固定重み後処理に新しいLoss値はない。

金メダル目標は未達・active。進捗はE26の採否確定であり、文書数やテスト数を精度改善と数えない。
