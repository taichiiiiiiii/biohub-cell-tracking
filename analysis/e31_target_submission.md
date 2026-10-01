# E31 探索提出 — Issue #16

## 2026-09-13 開始時点

- ユーザー指示: 積極的に提出する。Private Scoreを目的とし、local/Publicへの合わせ込みはしない。
- Issue: https://github.com/taichiiiiiiii/biohub-cell-tracking/issues/16
- ブランチ: `codex/issue-16-e31-exploratory-submit`。既存WIPを保持して同じcheckoutで作業。
- 正しいcompetition: `biohub-cell-tracking-during-development`。
- 認証・提出履歴の取得は成功。本日提出0、残り5（開始時点のAPI実測）。
- E31は未提出。known12差分 `+0.0023561892` は探索結果であり、独立検証・Private改善の証拠ではない。
- E31のlocal REJECTとE23 incumbent（Public 0.924）を維持。探索提出と採用を分離する。

## 単一仮説と変更範囲

`analysis/e31_primary_consensus_design.md` のprimary-only reciprocal条件を変えない。
閾値探索・再学習・追加GTの参照はしない。現在の実装は固定train観測packetに依存するため、
未知testの推論中に同じprimary forward/reverse logitsから疎な一致ペアを取得する経路を作る。
argmaxはsolverによるノード削除より前の全detector候補で計算し、実際のgraph ID対応を使って
既存 `run_postproc_core(consensus_loader=...)` に渡す。IDを配列位置と仮定しない。
既存sourceへの観測hook挿入を再利用し、巨大な特徴量・logitの全量保存はしない。

## 実行前の必須確認

1. Qwen Cloud subscription `qwen3.8-max` の実装をレビューし、直接テストを通す。
2. observer OFF/ONでbaseline推論が変わらず、既存packet helperと疎ペアが一致することを確認。
3. notebookのsource/config/weights、入出力、非公開設定と無インターネット経路を固定。
4. 画像だけを推論入力とし、GT・train-only dataset ID・Publicスコアに依存しないことを確認。
5. Maxで提出前の重要な整合性リスクを評価。Private改善を保証したとは扱わない。
6. Kaggle実行を直列に行い、全test集合・CSV形式・座標範囲・追跡構造・時間/メモリを検証。
7. 完了したexact notebook versionと `submission.csv` を一度だけ提出し、submission IDと終端結果を記録。

ローカル改善幅未達だけを理由に提出を止めない。一方、実装差・由来不明・形式不正・実行失敗は提出しない。
提出後に同じ仮説の閾値をPublicスコアに合わせて修正しない。未完了のためcommit/push・Issue closeなし。

## 検証の独立性に関する訂正

Discussion #716793 の2026-07-01回答は、train/testのembryo_id非重複を明記している。
過去台帳の「同じ胚か未公表」はこの回答と矛盾し、設計の前提には使わない。
https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/discussion/716793

known12は反復参照済み。追加24も独立holdoutと決めつけず、学習/選択履歴を確認する。
胚別・動画別・edge/division/node別の結果を扱い、少数動画の改善を全体の汎化と混同しない。

## 実装初期の状態（履歴、終端結果は後続節）

最新確認ではE31 ID56213346はCOMPLETE/Public0.924。下記未提出・新規0件は実装初期の記録である。
Goal全体の件数と未完了候補は`analysis/experiment_ledger.md`冒頭を正とする。

Flashへのstreaming observer実装依頼を3回実施し、全て採用前レビューで棄却。
提出用notebookは未作成、Kaggle実行・新規提出は未実施（新規0件）。

- 1回目: 存在しないimport、tensor変換前の型拒否、detector indexとgraph IDの逆転、
  copy済み座標へのobject identity要求など。source/testsには適用しなかった。
- 2回目: 対応契約を明記して再依頼したが、primary後のstate更新がなくreverseが必ず失敗。
  tupleを属性参照する次transitionエラーもあった。source/testsには適用しなかった。
- 3回目: 上記実行エラーに限定したpatchを依頼。新しいwrapperがselfを受け取る一方で
  wrapped methodへselfを渡さず、全hookがTypeErrorになる新規不具合を確認。未適用。
- Max評価（trigger: flash-failed-twice、packet: `e31_flash_failure_evaluation.json`）もREJECT。
  親はself引数欠落とshape/初回range検証漏れを確認。Maxのwalrus変数に関する指摘は
  それ単独ではエラーを示していないため、棄却の根拠には採用しない。
- 既存helper/mapping/reservation/instrumentationは `.venv/bin/python -m pytest` で55件PASS。
  これは新observer・提出候補の検証成功を意味しない。既存WIPの `git diff --check` もPASS。

この時点のAGENTSでは実装をFlashに限定していたため、実装担当変更のユーザー判断を求めた。
Issueは未完了のまま保持。commit/pushなし。E23/E26の重複提出も行わない。

## 2026-09-14 再開

ユーザーがFlash限定を解除し、Qwen Cloud qwen3.8-max実装を明示指定。
Issue #17 / `codex/issue-17-qwen-max-implementation` でcanonical authoring入口と現行指示を更新。
共有provider既定、subscription-only、retries=0、adapter effort=noneは維持。
Max実装とread-only評価は別入口であり、実装結果だけを独立レビューとは呼ばない。
Max実装workerの受付ログで `route=cloud; model=qwen3.8-max` を確認した。
新しいGoalはE31修復と日次枠以内の異なる新規5件提出・終端結果記録。現在まだ新規提出0件。

### Max observer 修復・接続検証

Max作者のobserverを選択的に統合。初回17失敗/5成功から、状態遷移・graph ID対応・
range/shape・raw record型・single-frame時刻の修正後、observer 28件と既存関連55件、
計83件が成功。対象2ファイルのruff、既存差分のgit diff --checkも成功。
独立レビューはe31_target_mappingが読み取り専用で実施。Maxの不正fixtureは未採用にし、
FakeTensorをobserverに渡す誤り、start_pair省略、存在しない_error参照を具体的に訂正依頼した。

保存済みpublic4の各pair_0000を読み取り専用で再生し、空間座標を(1,4,4)倍した最終座標で
既存helperとのedge対応一致・入力bytes不変を確認。shape/対応数は
44b6_0113de3b=(221,224)/218、44b6_0b24845f=(456,437)/339、
6bba_05b6850b=(78,81)/69、6bba_05db0fb1=(791,793)/752。
各動画の先頭1区間のみであり、全推論parity・汎化・精度向上の証拠ではない。

次の未完了単位はGT-freeのE31 private notebook組立。固定E23の双方向weight>0と
secondary実ロードのassertを組込む（observerのreverse/secondary hooksが必須のため）。
全test集合/CSV/実行資源の検証後、exact notebook versionを新規提出する。
認証済みKaggle履歴では最新E26=0.922、最高E23=0.924、いずれもCOMPLETE。
この修復によるKaggle実行・新規提出はまだ0件。Issue16/17は未完了、commit/pushなし。

### 提出ノートブック統合中

ユーザーは必要に応じたlocal学習を追加承認した。E31は単一仮説の接続修復なので、
この候補に再学習を混ぜず、学習変更が必要なら次の独立仮説として設計する。
scripts/prepare_e31_submission.pyとscripts/e31_submission_runtime.pyをMaxで作成中。
builderは8cells/17payload filesを静的生成でき、全codecellの構文解析に成功。
competition_sources/非公開/GPU/offline設定を元metadataから保持する。
実行時API・CSV検証の接続修正中で、これはKaggleでの実行成功を意味しない。
独立レビューはREPO_DIR/src未登録を指摘。親はstrict DeepCenter loaderが
(cfg,checkpoint_path,manifest_path)->(bundle,receipt)であることを確認し、
誤った1引数callback指定を訂正依頼した。新規5件への進捗は引き続き0/5。

接続修正を選択適用し、notebooks/e31_primary_consensus/ に提出draft、metadata、
build-receiptを生成した（未push/未実行）。runtime sha256は
676d06f0bb69f07dbdfef3b467fce0116111a03d956e5a7f481aa462adf4762c。
builder lintと8code/markdown cellsの構文検査に成功。runtimeはnotebook globals依存のため
単体ruffにはF821/E402が残る。これを無視して動作確認済みとは扱わない。
次の必須作業: runtime模擬実行テスト（正常CSV/重複node/不正edge/入力欠落/再実行拒否）、
実呼出しのsource/config/weights整合レビュー、提出前Max評価、Kaggle直列実行。
単一GPUでのhidden-scale時間予算も未確認。新規提出は依然0件。

### 2026-09-14 Kaggle実測への判断

actual runtimeファイルをexecするmockテスト6件成功。関連計89件成功。
正常receipt/重複node/不正endpoint/範囲外/GT混入/再実行拒否を検証。
単体ソースをコピーしたテスト案は棄却して実ファイル読み込みに修正した。
独立nativeレビューは修正後のAPI/loader/path/configに具体的blockerなし。
Max評価packet=e31_runtime_submission_evaluation.jsonは提出REJECT。親はGPU実測と
hidden-scale時間予算の未検証を採用。Notebook globalsとexclusive-createは意図した
セル順序/再実行拒否であり、上書きで回避しない。det_threshold .96875とassociation
threshold .48は別概念。E23 profile維持は単一仮説の対照条件であり再調整しない。
instrument_sourceのhash/AST可逆性とhelper reciprocalテストは既存検証でカバー済み。
従って未検証のままcompetition提出はせず、まずprivate notebookの公開dummy入力で
実GPU end-to-end動作と所要時間を測る。これは汎化評価ではない。
draft notebook SHA256=aee26b12946a4ec1b928f1312a23843cab7b24cc42a5bbf67994d638576e790c。
旧E23/E26 kernelはCOMPLETE。ユーザーのKaggle実行許可で直列実行を開始する。
実行中は候補source/config/weightsを編集せず、commit/pushを行わない。

Kaggle kernel `taichiiiii/biohub-e31-primary-consensus-exploratory` version1のpush成功。
timeout10800秒。competition submissionではなくprivate GPU実行の開始で、提出数0/5。
追跡先 https://www.kaggle.com/code/taichiiiii/biohub-e31-primary-consensus-exploratory

### v1終端ERROR: DeepCenter target manifest不一致

Kaggle APIでERROR確定。log時刻1400.75秒に4動画のprediction保存、1404.55秒に
strict DeepCenter manifest SHA不一致で停止。CSV/competition submission未生成（0/5）。
実GPU predictorと全observer hooksは4動画を完走したが、全後処理は未検証。
期待manifest1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911に対し
現配布manifest3bfe97304e9bbc3b3481a095392a1e83937315325bac8b987eb527d2951b96f3。
現配布manifestをKaggle datasetから取得し、logのactualhashと一致確認。
旧版との差はep100→ep500のlast checkpoint/history、生成時刻、artifact名等。
利用対象best checkpoint/summary/config/coordinate contractに差分なし。
best.pt SHA8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0は維持。
仮説・モデル・旧strictloaderを変えず、新target専用pin wrapperで再検証する。

Qwen Maxのtarget専用wrapperとruntime import修正を選択適用。旧strict定数は不変。
新しいmanifestと実best.ptを使ったローカルCPU strictロードでepoch2と全pin検証成功。
関連39tests成功、builder/test lintとdiffcheck成功。新test案のmonkeypatch引数漏れ部分は
未採用で、今回の新経路は実ファイルロードと既存runtime mock/checkpointテストで確認。
v2はモデル/推論/consensus仮説を変更せず、同じprivate kernelで直列再実行する。

### v2 COMPLETE / 時間予算の未合格

Kaggle version2はCOMPLETE。4動画のend-to-endを完走しVALIDATED_E31_SUBMISSIONを確認。
予測954.557秒（15.909分）、最終log1453.685秒（24.228分）。
CSV SHA2842635b8416fc3745fdb0b69c7d8d96adaace2a476be922b41bd20d395de9c8。
122223nodes/117944edges、4dataset全件、t→t+1、入次数<=1/出次数<=2、重複なし、
CSV/payload hashes・全bounds auditをローカルで独立再確認。E23既存CSVとは異なる。
予約edge数は順に23989/18341/5788/64783でありcallbackが実処理に効いている。
これは公開dummyでの動作証拠で、Private精度改善の証拠ではない。

公式OverviewのCode Requirements（2026-09-14取得）はGPU/CPUとも12時間上限。
https://www.kaggle.com/competitions/biohub-cell-tracking-during-development/overview
約200動画へ単純外挿するとpredictionだけで795分（13.26時間）となるため、現singleGPU
実装を時間予算合格とはしない。実hidden分布は未確認で、これは見積もりであり実測ではない。
提出枠消費前に元E23の2GPU動画分割を復元する設計へ進む。モデル/閾値/仮説は不変。
現段階でcompetition submissionは0/5。v2を無検証のまま提出しない。

### v3 2GPU実行開始（2026-09-14）

version3 push成功、Kaggle APIでRUNNINGを確認。timeout10800秒、NvidiaTeslaT4。
Notebook SHA0b8a771e592dbff8289574bcd17be80356ef7737e288476d042dca9499c4b855。
2GPU独立動画shard＋実CSV ID-only streaming merge、19payloadを凍結。
95関連tests、独立レビュー修正、Max GO FOR DUMMY GPU VALIDATIONを経て開始。
設計/検証詳細はe31_dual_gpu_design.md、評価packetはe31_dual_gpu_evaluation.json。
終了後は各child log/timing/receipt、全CSV/bounds/hash、v2 byte/semantic parityを調査する。
これはprivate notebook実行でcompetition submissionではない。新規提出0/5のまま。

### 実行待ち中の次候補整理（read-only review）

既存凍結仮説の比較価値はE29（primary+reverse+secondary一致によるhard予約）と
E32（primary一致をhard予約せずassignment costでsoft優遇）が高い。いずれもknown12
露出済み・既存efficacy gate未達というREJECTは変更しない。E30は正logit条件追加だけで
差別化が弱く、E33は独立したexact5-node救済だが既存負結果があるので優先しない。
枠埋め目的の提出・同一予測・Public結果後の条件変更はしない。E31の提出結果を受けても
同一loop条件は再調整せず、後続候補は元の固定条件と実装/出力検証が必要。
E34はpipeline.pyのbidirectional_motion_consistency末尾で全edgeのsourceを一意化するため
正当なdivision forkも失われる。既存負値を仮説反証や提出成果物として使わない。
台帳の当時の8/8停止記録を根拠なく緩めて新仮説探索は再開しない。E34無効性との
集計不整合は残課題として記録し、今回のread-only確認だけで有効非改善数を再認定しない。
この整理は新規物理実験/採点/提出ではない。E31 v3の候補sourceは凍結継続。

### v3 COMPLETE・提出前検証（2026-09-14 03:47 JST頃）

Kaggle APIでCOMPLETE確定、出力をoutputs/kaggle/e31_primary_consensus_v3へ取得。
19payloadの実SHAがbuild/parent/両child receiptと完全一致。全CSV validator/bounds replay成功。
122223nodes/117944edges/240167rows、全4dataset、連番ID、t+1、入次数<=1/出次数<=2、重複なし。
CSV SHA2842635b8416fc3745fdb0b69c7d8d96adaace2a476be922b41bd20d395de9c8はv2とBYTE EXACT。
v2は未提出なので既受理候補の重複提出ではない。既存E23/E26とは異なる。

予測shard0=430.045691秒、shard1=533.253925秒、並列予測+後処理+統合=621.830600秒。
main VALIDATED時刻960.550秒、Notebook最終log970.058417秒。v2から全体約33%短縮。
200動画への単純外挿は50*621.8306+(970.0584-621.8306)=31439.758秒=8.733時間。
12h公式上限/9.6h計画bufferを名目上下回るが、public4代表性・hidden密度・GPU変動は未測定。
GPUtokens0/1、両child device=cuda、予測時間和963.3秒に対しwall621.8秒で並行性を支持。
物理GPU UUIDはログ未記録で、binding独立実測を保証とはしない。実行error/OOMなし。
60件retention guardは元E23と同じ意図したprimary保護であり、新たな例外fallbackではない。

公式Overviewを再取得し12h/offline/公開外部モデル可/submission.csvを確認。
認証済API: entry=True、deadline2026-09-29 23:59 UTC、num_today0/num_total7/num_allowed_now5。
known12 REJECT（+0.0023561892<+0.005）は維持し、Private改善の主張はしない。
実GPU新証拠によりsubmission用Max評価packet=e31_v3_submission_evaluation.jsonを別途実行中。

提出判断: MaxはSUBMIT ONCE（hidden-runtime riskを明示受容）で具体的blockerなし。
親も単回exploratory提出を採用。前回dummy承認とは異なり実2GPU完走・byte同値・全検証が
今回の新証拠である。8.733hは約200動画に対する計画見積もりで、3.27hの名目余裕があるが
hidden処理コストが約40%以上高ければ超過し得る。hidden実測やPrivate改善は未証明。
ユーザーの積極提出指示の範囲でこの実行リスクを受容し、version3/submission.csvを1回のみ送信。
E23 incumbentは維持し、結果に合わせた同一loopの条件再調整はしない。

### 終端確認（2026-09-19、Issue #16）

2026-09-21 08:07 UTC定期確認: 提出履歴CLIが再び認証要求で終了。再試行・利用枠照会を
中止し、ユーザー再認証待ち。直前の成功確認値はE38 COMPLETE/Public 0.930、
E31 COMPLETE/Public 0.924で、今回の最新履歴/枠は取得していない。

後続定期確認21:51 UTCでは提出履歴CLIが認証要求で停止。再試行せず利用枠照会も中止した。
2026-09-20 15:59 UTC、並行作業のE38受理記録を新たな根拠として既存CLI読取を再開し、認証成功。
E31 COMPLETE/0.924は不変。E38 ID56400188 PENDINGを確認し、最新総数は台帳冒頭へ反映した。

認証済Kaggle提出履歴で56213346はCOMPLETE、Public 0.924、Privateは空欄と確認。
確認日であり、実際の採点終了時刻はAPI一覧から不明。E23も表示値0.924のため上回ったとはしない。
known12 REJECTとE23 incumbentは維持。実行・提出経路は終端到達したが、Private汎化改善は未証明。
現Goalは受理1/5・終端結果記録1/5。全履歴8件、当日0件、提出可能枠5件を同時確認。
E31単独の採点待ち追跡は終了し、再送・再実行なし。後続E29/E32は設計材料であって
承認済み凍結提出物ではないため、この定期確認では新規提出・Qwen・学習を起動しない。

定期保守で既存の41件のstaged script移動と関連unstaged変更を確認した。
現在のE31入口はscripts/experiments/e31/配下へ移動中で、下記旧パスは提出時の履歴を表す。
未検証の並行WIPを提出済みv3と同一とは見なさず、新たなbuild前にruntime内パスと
payload bindingの整合検証が必要。既存移動・source・testsには触れず、commit/pushなし。

### 提出受理 1/5（以下は受理当時の履歴）

2026-09-13 18:50:14.763 UTC（09-14 03:50 JST）、version3/submission.csvを送信。
CLI正常終了・当日残り4件。直後の履歴APIでsubmission ID **56213346** / **PENDING**を確認。
これで現Goal新規受理1/5。Public/Private scoreは未確定で、完了・改善・金圏達成とはしない。
終端score/errorまで同じIDを追跡し再送禁止。source/config凍結と重い実行の直列制約を維持。

### 採点待ち中のローカル学習入口確認（2026-09-14、Issue #16）

ユーザーは必要に応じたlocal学習を明示許可した。E31は既存checkpointの後処理変更であり、
この許可によって採点中のE31へ再学習モデルを混ぜない。新規学習はこのIssueの実装対象外で、
開始する場合は別の固定仮説・Issue・training_loss_gateに従う。
現状のscripts/local_train_unet_transformer.pyはCUDA同期をno-opへ置換するだけで、
公式trainerをrunpyで呼ぶ。公式trainerのdevice選択はCUDAまたはCPUであり、MPS実装ではない。
現在の保存経路はacc*recallの同値でもbestを上書きするため、学習契約のearliest-tieと不一致。
この入口はhistory.jsonl/manifest/resumeの計装にも接続されていない。
従って「local実行可能」と「提出用training gate合格」を区別し、既存診断checkpointは
DIAGNOSTIC_ONLYのまま。train/validationの動画分離、両lineageの検証、検出/追跡/総Loss、
非有限値・勾配監視、best/lastの分離とhash保存を満たしてから新規候補学習を実施する。
本確認ではsource変更、新規学習、追加GT読取、再提出を行っていない。

### E29/E31既存receipt比較（2026-09-14、Issue #16、read-only）

Sol/high独立分析はe29_consensus_20260913_r6とe31_primary_consensus_20260913_r4の
CONSENSUS_RECEIPTS.jsonおよび既存集計のみを確認。12動画の入力bindings/logit signaturesは
同一。親も(dataset,t_source,source_id,target_id)集合差を再確認した。
raw_pairsは233942→239015、E29-only=0、E31-only=5073。既存raw_statisticsによる
予約数は225694→229877（+4183）だが、最終edge総数240990→240987、node250584で同数、
fork627→628。これは候補増加が最終edge純増にならないというcount診断で、正解率や生存証明ではない。
receiptは予約前raw_pairsを保存するが、実予約pairと最終edge identityの段階間対応を保存しない。
従ってどの予約edgeが最終出力へ残ったかは現集計から判定不能。今後必要なら固定生成時に
reserved/post-relink/finalの対応を保存する単一診断を設計し、件数からidentityを推定しない。
新規metric計算・閾値調整・科学的採否変更なし。E31採点中は計装も変更しない。

次候補E29の接続差分（read-only設計）: 現PrimaryConsensusObserver.reverseはprimaryの
reciprocal対を確定してforward行列を解放し、secondaryフックは呼出し順だけを検証する。
従ってE31 runtimeの候補名やschema変更だけでE29にはならない。E29には既存3行列helperと
一致するsecondary列方向の一意最大条件を、全detector集合のまま追加する必要がある。
primary reciprocal対を保持し、secondary到着時に同shape/有限値を検証してその対を絞れば、
元の3行列helperと同じ集合を得られる（実装・同値テストは未実施）。subset後の再順位付け禁止。
既存observerはE31用に保持し、将来の限定実装では新E29経路と3行列helperの同値、secondary
tie/不一致/非有限/shape違い、raw欠落、既知fork保護、None対照を検証する。追加モデルpassや
閾値変更は不要。2GPU実行・CSV統合を再利用しても、新候補のhash/receipt/実完走検証は必要。
この設計はE29の探索提出許可や実装済み宣言ではなく、E31終端後の次候補判断材料に限る。
