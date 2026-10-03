# E27 — ILP未選択候補の既存確率をmotion costへ渡す

2026-09-12、生成・採点前の親設計。候補生成runnerは未完成。

## 一つの仮説

E23のmotion costが参照する既存association確率をILP未選択対にも渡すことで、
幾何だけによる誤った接続を減らし、固定CVを改善できる。探索対集合・geometry gate・
velocity・bonus・検出・他後処理は変えない。追加モデル・閾値探索・GT label学習はしない。
E26のmotion全廃とは別仮説であり、E26の凍結validator/成果物を変更しない。

## 対照と評価順

1. 既存E23生成controlのconfig/重み/raw/image/動画順/CPU条件を再利用する。
2. known12を同じ順で、optional prior=Noneの新sourceで再生成し、既存baseline subset
   の予測/CSV byte一致を検証する。元global row IDはsubset生成の既存規則へ正規化する。
   selected-only priorも同値でなければ実装不合格。比較対象source snapshotは保持する。
3. 対照が一致してから同じ入力で候補を直列生成。差分はprior情報経路だけ。
4. 凍結eval12→eval24→eval36の順序/公式metric/閾値を継承する。eval12不合格なら
   残り24GTは開かない。既知12/36を独立holdoutやprivate改善の証明と呼ばない。
5. 採用には目標のリーク/追跡/再現/CPU/形式/成果物由来および必要MAX評価を全て要求する。
   public順位だけで採用しない。未完・検証失敗は提出しない。

数値gateはsrc/biohub/e26_screen.pyの既存 `_GATE_THRESHOLDS` とanalysis/e26_scoring_contract.mdを
新登録にhash束縛して再利用し、変更しない。候補IDだけは新E27として別に登録する。
この文書だけでは実行sealは成立せず、入力/新source/依存/出力/予算を具体的controlへ
固定してから実行する。既存E26 controlのcandidate_idを書き換えて流用しない。

## 直近の実装境界

既存Readerとraw_signatureを再利用してgeneration-onlyな入力を準備する。
固定REFERENCE_PLAN、collection監査、旧baseline CHILD_CONTROLをhash照合し、
known12だけのpre/post NPZとraw GEFFのsemantic signature・ID/座標/候補値の対応を確認。
prior辞書、raw paths、画像shape、入力bindingsを生成runnerへ渡す。
GT bindingやD2個票をgenerationに読ませない。未記録確率を真の0に置換しない。
画像全payload/重み/依存/新sourceの実行前後照合と実行予算/成功sealは生成段階で別途必須。

## known12 baseline再現の予算（2026-09-13、実行前）

最初の物理実行は候補ではなくprior=Noneのbaselineのみ。
全関数wall1800秒、self peak RSS8GiB、出力256MiBを上限とする。
既存baseline36のcore約2500秒/RSS約4.47GBを根拠に、12動画の再現確認として固定する。
画像等の事前・事後検証を時間に含め、signal timerと親のprocess watchdogを併用する。
上限超過時に延長/自動再試行せず失敗を記録する。GT・新追跡モデル推論・学習は行わない。
baseline設定の既存後処理と既存DeepCenterをCPUで実行する。
参照CSVは既存eval12_baseline.csv、25549191bytes、SHA
d4c976c69f850f3f1738523482a272d3468eaf8c99082e128069b9f690ff42a9。
同STEMS順で最初から生成するため、追加の事後正規化なしにbyte一致を要求する。
fresh出力のみ。部分成果物やERRORを保持し、全検証成功前にPASS/採用を発行しない。

成功の受理は子process exit0だけではなく、親監督の全binding再照合成功を必要とする。
親は起動前sourceと子の記録sourceの一致、正確なRESULT.json、ERROR.jsonと
RESULT.failed.jsonの不存在を確認する。失敗時の*.failed.jsonは元receiptを改変せず
残す証跡で、内部に以前のPASS文字列が残っても成功成果物として読まない。
親側の失敗でも子のRESULT.jsonを撤回し、親のERRORへ失敗型を記録する。
時間切れ時はprocess groupをTERM、5秒後も終了しなければKILLして回収する。
最後の回収も失敗した場合は例外を伝播し、実行中の成果物には触れず成功を発行しない。

## Issue #7 — known12検証adapter修正後の対照v2（生成前）

v1は全12動画のCSVが参照に完全一致したが、E26の36本専用統計validatorの誤適用で
検証途中に失敗した。元runはFAILのまま保持し、後から成功sealを追加しない。
E26のコード・採否閾値は変更せず、同じ型・件数・比率・motion規則をE27のSTEMS12と
baseline armだけへ適用する検証adapterを使う。予測生成処理・cfg・重み・入力は変更しない。
保存済み実raw/CSV/CONTROLのhash固定テストと異常系を通過後、独立差分レビューを行う。

次の対照はoutputs/local/e27_baseline_parity_20260913_v2（監督は同名_supervisor）へ
fresh生成する。prior=None、全関数1800秒/selfRSS8GiB/親子出力計256MiB、CPU fp32/seed0/
threads1、同じ12動画順、同じ参照CSV byte/SHA一致を要求する。自動延長・再試行なし。
既存v1の元sourceはoutputs/local/e27_prior_prepare_flash_20260912/BASELINE_V1_screen.pyに
SHA ea2c0c9e28a2b87319a17486ec2d8d07952c2ed7e2795bd5604f1b6911ac24edで保全。
修正後source/designは新CONTROLへ再束縛する。これは対照の検証回復で、科学的な
改善仮説の追加・採用・提出ではない。Issueは検証/commit/push未完の間Openとする。

## Issue #9 — prior入力経路と実験識別（候補生成前）

baseline v2の親監督PASSを前提に、同じrunnerを3つの明示modeへ最小拡張する。
baseline_noneは既存None、selected_onlyはraw GEFF選択済み対の記録済み確率だけ、
recorded_priorは全pre-ILP記録対の確率を渡す。coreの既存helperが選択済み対を除外し、
既存rawにないendpointは使用しない。候補集合・geometry・velocity・bonusは固定。
各modeのprior内容は動画/ID対の安定順JSONでhash化し、入力NPZ/materialと合わせてCONTROLへ
束縛する。selected_onlyが導入する未選択対は0、recorded_priorは既知12全体で正数を要求。

selected_onlyは基準CSVのbyte完全一致が必須。recorded_priorは一致を採否基準にせず、
生成形式/材料/統計/親監督の全検証を維持して別の未採点statusにする。モード違いの成果物を
baseline成功と誤認しない。candidate生成の成功をCV合格や提出可と呼ばない。
各modeはfresh出力/1800秒/selfRSS8GiB/出力256MiB、CPU fp32/seed0/threads1で直列実行。
前節のeval12→eval24→eval36と全数値gateを変更しない。selected_onlyが一致しなければ
候補評価へ進まず実装不合格。候補eval12未達なら残り24GTを開かず負結果を台帳へ残す。

### Issue #9 — 統合後selected-only対照の実行登録

2026-09-13、生成前。新modeはcoreへ明示prior辞書を渡し、CONTROL/RESULT/親監督に
armとreceiptを保持する。baseline_noneだけは既存CONTROLのNoneと引数省略を維持し、
helperの空receiptは保存しない。非baselineは生成後に入力辞書とreceiptを再構築照合する。
known12統計validatorのarm=baselineはmotion-on schemaを意味し、候補採用判定ではない。

次のfresh出力はoutputs/local/e27_selected_only_parity_20260913_v1、監督は同名_supervisor。
MAX読取評価に重大未解決事項がなく、関連テスト・静的検査成功を確認してから、
--supervise --mode selected_onlyを実行する。1800秒/8GiB self RSS/親子256MiB、CPU fp32、
seed0、threads1、12動画順と参照CSV hash/byteを維持。再試行・延長なし、GTなし。
expected prior receipt SHA4891e86e7e6cab22ab662cd937dced1dbda549ac0e24a7395c9e4e8b98fad619、
240884 entries、eligible unselected0。生成時source/design/inputは新CONTROLで固定。
子E27_SELECTED_ONLY_PARITY_PASS_NOT_CANDIDATEと親E27_SELECTED_ONLY_SUPERVISED_PASS_NOT_CANDIDATE
の両方・exit0・全照合成功が対照受理条件。これをCV改善や提出候補の確定とは呼ばない。
