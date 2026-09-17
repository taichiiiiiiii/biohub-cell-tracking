# Kaggle向けループ v2 — 初期評価と提出確認の分離

2026-09-05 / **DESIGN_SHIP — active initial-screening protocol**

ユーザーの「切り替えて、ループエンジニアリングで進めてください」に基づく明示的な
計測手順の改訂。設計・優先順位・最終採否は親タスク、原因分析・実装・実装レビューは
別subagentが担当する。候補を結果に合わせて変更する許可ではない。

## 固定する仮説

最初の候補は既存`e23_twin_only_v1`。E23の一つの親に属するべき娘が近接する
二つの親へ分断されたケースを、既存のstrict twin motifだけで修正する。
候補、半径、cap、sort、DeepCenter epoch2/閾値、元raw、36動画と順序、
公式metric、eval12/24/36の数値gateは[既存設計](steal_twin_design.md)のまま。
新しいモデル学習は行わない。旧ST-R3のHOLDや未完成コードはそのまま保護する。

## 改訂範囲と結果ラベル

新entry point `kaggle_screen` を研究用初期評価専用にする。旧ST-R3のreceipt/schema、
`FEASIBILITY_PASS`、`EVAL36_ADOPTION_CANDIDATE`を発行/改変/代用しない。

| 項目 | v2初期評価 | 提出前確認 |
|---|---|---|
| 公式metric・候補・固定データ・数値gate | 必須、不変 | 必須、不変 |
| 現行E23 public-four参照CSVとの同値性 | 必須。別parity成果物で、36動画の採否へ混ぜない | 新しい提出codeへ再bind |
| 生成順 | 全36のdry-run→baseline→candidateを直列生成、全て固定してからGT採点 | 対象環境で再現性・順序効果を確認。既存ST-R3を使うなら全5実行を維持 |
| GT分離 | 生成/採点を別process、生成にGT pathを渡さず、レビュー済み明示inputのみ。手続き的な分離 | 使う確認契約で要求される隔離証拠を満たす |
| 固定入力・出力 | 開始/終了でcontent hash、実効config/source/dependency pin、fresh出力・上書き拒否、run中の編集禁止 | 提出artifactへ再bind、再実行一致 |
| 敵対的same-UID改変への完全防御 | 証明しない。既存データを壊さない通常のsafe publicationは維持 | 要求する脅威モデルを別途明記。旧ST-R3の保証を僭称しない |
| 時間/RSS | local wallとprocess RSSを記録、型/非有限/失敗検査。hiddenへの保証なし | 対象環境の時間・全体RAM・hidden約200本の余裕を検証。未検証なら提出不可 |
| 成功ラベル | `SCREEN_PASS_REQUIRES_CONFIRMATION`のみ | 独立確認後にだけ提出候補 |

初期評価からOS-level GT非可視、target calibration、完全process-tree/RSS証明、
full AB/BAを外すのは**この新診断経路だけ**の明示改訂である。
旧契約を通ったことにはしない。これらが精度/時間/再現性へ影響しないと推定もしない。
初期評価PASS後にモデル/候補を変えず、別の確認手順と環境を結果とは独立に固定する。
ここでの独立確認は別担当による運用確認であり、新しいholdoutを得たという意味ではない。

## 初期評価の開始条件

1. 実装前に本書を独立レビュー。候補実装を変更せず、薄いrunnerと検証だけを追加する。
2. canonical checkoutとfeature branchを維持。旧WIPは編集しない。
   dirty checkoutを隠さず、commitに加えて実行に関係するtracked/untracked sourceの
   exact bytes・実効設定・Python/dependency versions・lockfileをhash固定する。
   変更中に走らせず、親が単一writer/単一物理評価を管理する。
3. official gitlink/HEADは`075fc5f5a52d11077f9dc2b074644618f26939e2`でclean。
   scoringは`src/biohub/evaluate.py`の公式直呼びを使用。独自proxy採点は禁止。
4. 固定eval36 raw/image、GTのopaque bytesとscale metadata、DeepCenter、parity入力/
   参照出力のmanifestを検証する。GT graphの意味はscore段階まで読まない。
   保存receiptの存在だけで現在bytesの検証を代用しない。
5. ネットワーク・学習・Kaggle・自動downloadはrunnerに持たせない。CPU-only、
   明示argv/environment、`PYTHONHASHSEED=0`、明示DeepCenterのみ。未知`BIOHUB_*`は禁止。
6. 現行codeのE23 public-four出力が既知参照CSV/hashと一致することを、36生成の前に
   別のfresh parity出力で確認する。public-fourスコアは採否に使わない。

## 実行と判定

実行単位はcandidateとprotocol versionを含む一意なrun ID。
出力先は`outputs/local/kaggle_screen/<run_id>/`のみ、既存runは再開/上書きしない。
失敗途中の出力も保持し、原因修正は新runにする。秘密情報やambient environmentは保存しない。

1. 全36をliteral `eval12 + eval24`順でdry-run、baseline、candidateの各fresh processへ渡す。
   同じraw/image/DeepCenter/sourceを使い、許可されたprofile差分以外があれば停止する。
   dry-runはtwinを列挙しても編集しない。
2. 生成processへGT引数・採点module・score callbackを渡さない。
   生成後はCSVのschema/dataset/ID/座標/辺・各plan/config/statsを確認する。
   offとdry-runのCSV・graph・共通telemetryが同値、candidateは既存の保存則とcapを満たす。
3. 三出力と全入力/sourceを再hashし、`SCREEN_GENERATION_SEALED`を発行する。
   これはST-R3の`GENERATION_SEALED`とは別schemaで、相互変換しない。
4. 別score processがsealとhashを検証した後、eval12だけを公式採点。
   一つでもgate未達なら`SCREEN_REJECT_EVAL12`、以後のGTを開かない。
5. 通過した場合だけ、保存済み全36CSVから残り24を機械的に抽出して公式採点。
   未達なら`SCREEN_REJECT_EVAL24`。予測を作り直さない。
6. 両段階通過後、保存済み公式行を結合して公式`summarise`で集約する。
   下の全gate通過で`SCREEN_PASS_REQUIRES_CONFIRMATION`、未達は`SCREEN_REJECT_EVAL36`。

数値は丸めず比較する。最初の失敗gateも保存し、gate間の裁量的な救済はしない。

| 段階 | 凍結数値 |
|---|---|
| eval12 | paired mean score Δ≥+0.005、median≥0、worst≥−0.002、公式aggregate adj-edge Δ≥−0.002、両lineage公式aggregate score Δ≥0 |
| eval24 | paired mean Δ≥+0.003、他はeval12と同じ |
| eval36 | aggregate division TP純増≥4、adj-edge Δ≥−0.002、combined Δ≥0、division J Δ≥0、median≥0、worst≥−0.002、両lineage aggregate score Δ≥0 |

全36は既露出のretrospective screeningであってholdoutではない。
meanと公式micro aggregateを混ぜず、TP/FP/FN、node count/recall、changed/正/負動画数、
最悪動画と系統別結果を保存する。候補zero editsも有効な棄却候補で、条件を緩めない。
Loss gateはpostprocess-onlyなのでN/A。新規学習へ移る場合は既存training-loss gate必須。

## 実装範囲・レビュー終了条件

原因分析は既存R2入口と公式score APIの再利用可否を確認する。
親がその結果から実装境界を確定し、実装Agentは新runner/CLI/testsの担当ファイルのみ編集。
既存の候補・`official/`・旧ST-R3のHOLD・未完成変更を触らない。
実装者以外のAgentが、仮説不変、GT順序、誤採点、入力取り違え、壊れたCSV、
設定未発火、silent fallback、上書き、非有限値、結果の誤昇格を重点レビューする。
明示的な保証範囲外の敵対的同一ユーザー攻撃・汎用container基盤はこの差分のblockerにしない。

必須tests: 固定順/集合、profile差分、unknown override、off/dry同値、入力/出力hash変更、
CSV重複/dangling/非連続辺/非有限、公式fixtureとstage gate境界、12失敗時の24非参照、
score前の生成未完拒否、旧ST-R3互換拒否、fresh出力/失敗保存、no-submitラベル。
小fixtureテスト→独立レビュー→直列物理評価とし、実データを実装中のテストに使わない。

## 終了後の行動

- 有効なscoreのREJECT: そのv1を退役。観測した失敗原因を台帳へ記録し、次はE17の
  source-semantics適格性を確認する。同じ36でradius/capを再調整しない。
- 計測器ERROR: 候補/数値は固定したまま、再現可能なバグ一件を次の実装ループへ。
- SCREEN_PASS: まだ提出不可。候補bytesを凍結し、対象環境での時間/RAM/再現性と
  提出物の同値性を独立に確認する。現在の公式ルールを再確認してから必要な一回を提出する。

進捗単位は「採否が出た仮説」と「解消した実行blocker」。文書/テスト/commit数を
精度改善と数えない。軽い原因分析/実装/レビューは並列可、重い物理評価は一件ずつ。

設計レビュー: `screen_protocol_review`（SOL high、2026-09-05）SHIP。
実装・物理評価の結果は未取得であり、設計SHIPから推定しない。
