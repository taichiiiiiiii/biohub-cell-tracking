# E27 eval12 採点境界（Issue #9）
2026-09-13、recorded_prior生成・採点前の親設計。

## 仮説と採否
E27 association priorの単一仮説と固定eval12/eval24/eval36 gateを継承する。
selected_onlyは対照であり、改善candidateとして採点しない。最初の比較は受理済み
selected_only CSV（baseline v2とbyte一致）対 recorded_prior。known12は既知の遡及評価で、
private改善や独立holdoutの証明ではない。eval12不合格なら残り24GTを読まず棄却する。

## 最小構成
scripts/e27_prior_score.pyを生成runnerとは別に置く。E26と生成runnerのsourceは変更しない。
E26専用score_screen/GENERATION_SEAL/registration検証の偽装・流用は行わない。
E27専用planはcandidate生成前にfresh保存し、そのSHAを親が記録する。
planには候補ID、exact12、対照の受理済み成果物bindings、未存在candidate出力path、
生成source closure、scorer/設計/公式metric source/dependency、既存GT登録の元SHAと
known12 inventory/画像metadata、固定予算/数値gateを束縛する。
GTは既存opaque登録のhash照合のみで準備し、生成へGT path/内容を渡さない。
生成前後を同じplanで照合し、予測が存在した後の登録や差替えを拒否する。
外側の同一呼出しでverify_plan(..., before_generation=True)を完了してから、
planのcandidate_outputにだけ既存supervise_baseline(mode=recorded_prior)を起動する。
検証後・起動前にplanフォルダーへPREGEN_PLAN_VERIFIED.jsonを排他的に保存し、
plan binding、candidate_output、mode、UTC、非提出flagを記録して後段で再照合する。
既存STARTED/SUPERVISORにはplan hashが無いため、時刻だけを事前検証の証拠にしない。
この記録は外側実行順の追跡用であり、改変不能な第三者署名ではない。

## 生成成果物の読取検証
RESULT/CONTROL/親SUPERVISOR_RESULT、親logと子artifact全件を実path/bytes/SHA照合する。
期待arm/status/run_id/datasets/false安全flag、prior receipt一致、source closure、
全artifact membershipとERROR/failed不存在を確認する。baselineは固定参照byte/SHA一致。
baseline/candidateのconfig/dependency/generation_input/reader/metadata/sourceは一致必須。
差分はmode/priorだけ。CSVの実構造・12動画coverage/counts/bounds/統計を再検証する。
親監督やPASS文字列だけを入力整合の証拠としない。GT import前に全入力検証を完了する。

## 公式採点と既存gate
freshなCPU score process、固定環境、seed0、matching distance7.0で、
biohub.evaluate.score_submissionをbaseline→candidateの順に各1回呼ぶ。
_check_stage_gtのknown12 preflight、_score_arm_record、_paired_score_recordと
公式summariseの数値処理を再利用する。返却summaryと保存rowの公式再集計を照合する。
E26 evaluate_gateのcandidate_idは数値rule実装の旧識別子でありE27候補IDではない。
薄いE27 adapterで旧値をrule_implementation_candidate_idとして明示保存し、
candidate_idだけE27へ付ける。gate数値/status/threshold/first_failureは一切変更しない。
元E26ソース・元成果物は不変。新旧IDを同一候補と主張しない。
division-freeのnull規則、全動画singleton/lineage/aggregate/TP FP FN、paired値を保存する。

## 成功・失敗の確定
eval12全体1800秒/self peakRSS8GiB/出力256MiB、固定環境の子processと親watchdogで監督。
既存GT登録のhash、採点source、予測/CONTROL/RESULT/親監督、CSV/全保存rowと再集計/gateを
採点後に再照合して初めて終端判定を書く。途中失敗はERROR、部分出力保持、再試行なし。
SCREEN_EVAL12_PASSでも「残り24へ進める」だけで採用・提出可ではない。
全安全flagはfalse。候補確定には固定後続gate・再現・CPU全規模・提出形式・由来を別途要求。
実装/合成テスト/独立評価と具体plan登録が完了するまでrecorded_prior生成を開始しない。
