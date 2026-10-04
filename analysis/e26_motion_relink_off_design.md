# E26 — E23のmotion relink除去を一因子で反証する

最新設計状態（2026-09-08 06:17 UTC）: **提出0.922は不採用のまま。unit03/04を受入、初回local SCREENの数値予算を固定**。
終端観測は同日02:08:50 UTC、提出ref56069885/v3/scriptVersionId347872590。反復API確認は終了。
ユーザー変更に従いサブエージェントは使わず、親が指定6テスト定義を修正してunit02aを受入、
unit02bの比較統計/厳密gateまで実装した。関連1002 tests/Ruff PASS、全差分を自己レビュー。
unit03のCSV/生telemetry、完全な不透明input inventory、exclusive JSON、環境/seed/thread/RAM/wall検査部品を追加。
source20files/科学契約8files/依存102種、全選択入力と既存取得記録の照合、private/public登録pairと
登録検証CLIを追加。関連1556 tests/Ruff PASS。raw4/raw36と画像40本の完全byte照合もPASS。
さらに直列生成監督・子control・strict model receipt・全出力sealと、別processによる段階公式採点を接続。
親が全追加差分を自己レビューし、最終関連1648 tests/Ruff/diff-check PASS。元の設定/科学gateは不変。
詳細・source/test SHA・失敗対策・進行中runは[実験台帳](experiment_ledger.md)の同日06:17 UTC節。
本書は初回物理実行前の凍結文書。実行状態の更新は台帳で行い、登録から採点終了まで本書を変更しない。
SCREEN結果と原因・汎化差はまだ未確定。実装受入を精度改善や金メダル達成とは扱わない。
以下のモデル/dispatch/未作成/PENDING記述は各日時の履歴で、現在の実行指示ではない。

## 2026-09-08 06:17 UTC — 単独実装受入と初回物理予算の親判断

ユーザーのno-subagent指示に従い、親だけで設計・実装・原因分析・テスト・別工程の自己レビューを完了。
以下の古い独立agent/指定Qwenの受入条件は運用変更で置換し、独立レビューを実施したとは主張しない。
生成の順序/厳密config/入力byte固定/公式採点/固定gate/失敗保持の科学条件は全て維持する。

unit03: public4→baseline36→candidate36のfresh Python processを直列監督し、最初のparity不一致や
失敗・上限超過で停止する。unit04: generation sealと元登録pairを検証してから、別Python processで
eval12 baseline→candidate、合格時のみeval24を採点。eval36は保存済み行を公式summariseで集約する。
各armの公式行を完了直後に保存し、全てのREJECT/PASSを共通の再parse/再hash最終検査へ通す。
これはPython処理processであり、AIサブエージェントの起動ではない。

最終コードは関連1648件が210.19秒でPASS、Ruff/diff-check PASS。合成GTを公式APIで採点する
試験も含む。24 warningsは合成のedge無し予測に対する公式の明示警告で、実データの警告ではない。
`official/`と既存postproc/io/validate/evaluateは変更なし。unit02の受入済みsource/testの前半も
import/docstring以外のbyte一致を確認した。型check専用toolは本プロジェクトに未設定。

[実行予算JSON](e26_screen_budget.json)を初回登録前に固定する:

- public4 child 1200秒、baseline/candidate各5400秒、生成監督全体14400秒。
- scoring process/監督全体7200秒、eval12 1800秒、eval24 3600秒、保存行eval36 300秒。
- 各self-process peak RSS 8,589,934,592 bytes（8 GiB）。dataset/stage境界とreceiptで検査。
  process-tree RAMやOSのhard memory capではない。親は各子processをwall timeoutで停止・reapする。
  採点stageのwallはAPI呼出し前後/保存時に検査し、全score processには監督timeoutを適用する。
- 1つのfresh runのみ。failureの自動retry・出力再利用・上限延長・別IDへの無言再実行はしない。

根拠はgeneration contractに記載した既存E25のpublic4 core335.59秒/RSS4.40GBと
baseline36 core2499.70秒/RSS4.47GB。receiptの元SHAも再確認した。旧timerはmodel loadや
出力再検証を含まないため、それらと新候補の変動に余裕を持たせた親の運用上限である。
本機の実測RAM48GiB、利用可能disk約192GiBを確認。別projectのprocessは停止・変更しない。
既存rawへの固定後処理だけを行い、追跡モデルの全量推論・新学習・ダウンロード・GPU消費はしない。

親はこの予算で不透明preregistrationを作成し、両SHAを記録した後に初回生成を開始してよい。
生成seal検証完了後だけ同じ登録の段階採点へ進む。元E26提出の再提出は本評価に含めない。
実行中はsource/scientific docs/依存/入力/Git HEADを凍結し、commit/pushしない。

### 履歴：2026-09-07 05:50 UTC — v3提出受理時点

version2はCSV/graph/provenance合格だが、既存下限補正6件の見落としにより親のreport期待がFAIL。
元判定を維持し、[新v3事前契約](e26_bounds_v3_contract.md)で同一科学条件の再現確認を完了した。
親/独立二担当SHIP後、E26の一回だけの提出ref56069885/scriptVersionId347872590を受理。
新LBは未取得、SCREENはINCOMPLETE。既存2時間設定で当該IDを読取追跡する。
以下はversion2開始時点の履歴。
E26は既存E23 notebookを使うtarget-only探索提出経路へ進み、version 1の座標範囲外1件を
generic serializerで修正した。関連703 tests/Ruffと独立レビューに合格し、修正版を一度実行中。
完走・物理出力検証・提出・新LBは未取得。ローカルSCREEN runnerは依然INCOMPLETEであり、
下記unit02–04が完了したとは扱わない。現在の凍結条件は
[target実行契約](e26_bounds_target_run.md)、当初科学仮説は本書と[e26_target_run.md](e26_target_run.md)。
無人Cloud実行は解禁せず、元の失敗ログ/旧source/科学gateを保持する。

### 次のローカル評価修正の境界（親設計、2026-09-07。まだdispatchしない）

v3提出確認を優先し、GPU待ち中の独立原因分析を親が全source/test再読で確認した。
unit02a本体は再著作不要。rev3ログ
`outputs/local/e26_implementation/unit02a_cloud_test_revision3_WORKER.jsonl`
SHA `5a8a855ae51eb00a3b544faad92b4467cadde1d95e4fcc5ae8de3f843d3172d7` の
production block7758bytes/SHA `369469fac4a3bd90bee19948fd9cec60a746a4a99ca47aaae112c97e1e16b84f`
は既存Plus著作のまま固定し、Maxが本体を新規著作したとは扱わない。
test block12780bytes/SHA `721682f76283ec42939d0c6e5393e1fe41210a61790dbd61f8cc988f73b9d774`
の6定義だけを、別SOLによるoracle確認後にMaxへ渡す設計とする。

対象は全armの4 path明示assert、正常pairの戻り値None、不正configを片armずつ、
motion/twin8ケースと4種の正確なerror、他type3種×両arm、実在するcheckpoint/manifest
環境変数での独立性。その他のtestsと本体を保持し、import os除去/import整形は機械的変更のみ。
元失敗は本体を全面的に作り直す理由ではなく、配送違反/rev3の不足oracle/Ruff2件である。
現config.py SHA415a586ad4d8a81b96314025fa0cf05ce6c797df7ef8eb75e53f48efe192d882は一致。
canonicalのe26_screen.py/testは未作成のまま。新unit02a受入後もunit02b統計/gateと
unit03/04生成/段階公式採点は残り、SCREEN完成や精度改善とは呼ばない。
v3 source/helper/token/metadata、既存bounds tests、official/、科学設定は対象外。

05:40 UTCの独立oracleレビューでも、この6定義で元12項目を閉じられると確認。
motion/twinは8ケースそれぞれの完全エラー境界を`^... got value$`で検証し、
型違反は3種×baseline/candidateを片側ずつ、不正configも正常な他方を維持する。
全armで4 pathのbuiltin str型と明示値を個別assertし、環境変数は実在する
checkpoint/manifest（DEFAULTも含む）を使用する。存在しないBIOHUB_WEIGHT_PATHは使わない。
これは次単位の設計確認だけで、worker起動・コード統合・SCREEN受入はまだない。

## 実装状態の履歴（2026-09-06、10:56 UTC。現行モデル/起動指示ではない）

現在の指定実装者はQwen Cloud exact `qwen3.7-plus` / `qwen_token_plan`、
契約済みサブスク内のみ。Cloud専用launcher7368ceb、承認済worktreea17eb02に同期済み。
直接ユーザー依頼のoutput-only deliveryはexit0でsource/testsを生成し、親が全文を
確認して無改変適用したが、public4をbase1にする科学仕様違反、4pytest失敗、
17lint違反のため未採用。元Qwenの2filesはignored evidenceへ保存しworktreeはclean。
[修正依頼](e26_unit02a_cloud_revision_task.md)は独立レビューSHIP。
その受付は10:51 UTCに共有Cloud枠busyでexit2、モデル呼出し前に終了した。
前回は実装受領と検証結果を得たprogressであり、live workerのverified waitではない。

この自動goal継続は直接対話の実装要求へ読み替えず、Cloudを新規起動しない。
同時実行枠が空いてもproviderの無人利用条件は別の必須条件である。
モデルfallback・従量課金・lock強奪なし。詳しい実行証拠と失敗対策は
[実行復旧記録](e26_worker_scope_recovery.md)を優先する。
unit02a修正受入→unit02b→unit03/04受入→予算固定→直列物理評価の依存を維持する。
38件の既存公式採点/画像I/O/提出構造/motion分岐の合成回帰は親の現環境でPASS4.37s。
これはE26 runner、段階的GT分離、候補精度やKaggle提出の検証ではない。

### 実装待ちの依存確認（同日10:55–11:00 UTC）

親が現在の3fileを再hashし、parity/strict-loader固定値と一致を確認した。
参照CSV `33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a`、
checkpoint `8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0`、
manifest `1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911`。
重みはロードせず、画像frame/GT graphも開いていない。これら3fileの再取得は不要だが、
全raw/image treeの取得manifest照合・実行前後hashやfresh public4生成の代わりではない。

現在の`score_submission`はGT欠損動画をskipし、`read_scale`はmetadata欠損時に
defaultへfallbackする。既存testはこの旧API仕様を肯定しているため、38PASSだけで
E26のfail-closed保証にはしない。unit04の全動画存在、明示scale、n/n_adj/順序/件数と
公式値の有限性guardを必須のまま維持する。公式summariseのdivision分母0のNaNと
combined=adj仕様もsourceで再確認し、null理由の保存・eval36必須gate ERRORを免除しない。
既存本体/official/testsの差分なし、official HEADは固定値のままclean。

次の自動継続でSOL入力auditの完了報告を回収したが、そのagentの実在確認は0/40で、
文書確認だけだった。独立した現物確認の証拠とは数えない。親が続けてunit02bのliteral
EVAL12/EVAL24と固定public4を使い、指定40件すべてのraw GEFF root/画像root/
画像root metadata/配列metadataが存在することを実ファイルで確認した。
選択したraw/image root自体にsymlinkはなかったが、ancestor/内部chunk aliasの全追跡は未実施。
同じ40件の小さいmetadataだけを読み、4次元正整数shape、uint16、明示scale transformと
正の有限ZYX scaleを確認。chunk復号・raw graph・GT treeの読み込みや全treehashは無し。
場所とmetadataが揃うという限定証拠であり、取得manifestとの完全一致/strict model load/
fresh parity/候補評価は依然必要。自動Cloud不可の条件は2回目のgoal継続でも変わらない。

## 09:35 UTC時点の実装履歴（現行起動指示ではない）

単発復旧session54736は09:32 UTCの45分capでSIGINT/exit130。最後までpatch/実装test0、
worktree clean/実装lock無し、client PID群も終了。今回SSE idle/provider errorは観測されず、
周辺再探索に時間を使った実装未完了である。上流active1は09:35には残っていたが、
09:42:37にactive0/既知接続消滅を確認し枠解放を確認した。新規起動許可とは別である。
新worker/Cloud/設定変更は許可せず、最終証拠を[復旧記録](e26_transport_recovery.md)へ保持。

以下は同試行の開始・設計受入履歴であり、現行の起動指示ではない。

修正配備と独立受入監査SHIP後、親が明示的に単発local復旧を開始。
session54736/thread `01a075e6-453f-7aa2-8d54-087695d85948`、08:47:00開始、09:32:00 UTC上限。
外側監督が2700秒で停止signalを送る。延長0、Cloud0、自動retry0。
task SHA `a9815c7019e2a1d650d9136bcc3a928b094b417210cfd9cd5de5b16c54f42416`。
科学本文は旧taskとbyte同一。新実装の受入、実データ評価、精度改善は未確認。

以下は旧失敗とその復旧判断の履歴であり、旧sessionは再開しない。

unit02aは07:39:54 UTC頃に `stream disconnected before completion: idle timeout waiting for SSE`
で終了し、親が07:40:56 UTCにexit1を確認。現在worktree clean・新規実装0・lock無し。
再確認でも保存logは50,549 B / 43 lines、SHA
`618d179ecc95fcf614d28bab00f7e0cc528672b540fdd0939802c0d94e6626ad`。
旧session handleは既に無く、継続監督・再試行はしない。科学生成/採点/提出は未実行。
独立SOLと親の静的確認では共有bridgeに5秒周期の独立keepalive threadが存在する。
共有担当の隔離診断は完了し、Codex 0.153.4ではcommentだけでidle timerが更新されず、
通常data eventの対照は継続することを再現した。元workerのpacket/状態/バイナリ同一性は未確認。
保存証拠と次判断は [transport復旧設計](e26_transport_recovery.md) に記録。
その後、隔離修正60件PASS・独立レビューを経て、条件付き承認の下で共有担当がbridgeのみ反映。
08:43 UTCに親が候補と同一の実source hash、bridge33154/backend61759、ready healthを確認した。
反映後の模擬回帰は33件PASS。復旧taskの独立設計レビューSHIP、配備受入の独立監査中。
単発local起動は別途親判断とし、Cloud・追加課金・元taskの自動再試行は許可しない。

以下の開始・延長は履歴で、現在の実行指示ではない。

原因分析と独立設計レビュー後、元unit02のconfig部分を
[unit02a依頼](e26_unit02a_task.md)へ分け、親がlocal Flashへ一回再依頼した。
session `83288`、thread `01a07590-9c7b-7753-9852-21b759c0718c`。
開始07:13:26 UTC、延長後の監督上限は**07:58:26 UTC**だったが、その前にエラー終了。
default/Cloud無し/自動retry0。
07:30 UTC、独立運用レビューSHIP後に親が同じlive sessionの監督上限だけを
20分から合計45分へ一回延長した。旧07:33:26より前の判断で、restart/new attemptではない。
同一local handleの継続のみ。追加延長0、retry0、Cloud/科学条件変更なし。
20分は親の運用capで科学gateではない。task bytesは下記SHAのまま保持し、
この監督変更は外部の親判断として記録する。共有待ち/推論時間の内訳は推定しない。
固定task SHA `5fc0b7d34bd02c5721f76e49d87dff2c38c796efa53e2ec5e7ac124675220d73`、
log `outputs/local/e26_implementation/unit02a_flash_attempt1_WORKER.jsonl`。
admitted 0.00s、route=flash、thread/turn開始と同session生存を確認した。
元unit02のsplit/統計/gate/異常系は02bへ残し、configだけで全unit完了とはしない。
残りの[unit02b詳細仕様](e26_unit02b_task.md)と[unit04採点契約](e26_scoring_contract.md)も
独立設計レビューSHIP。unit02a受入前の別worker/物理評価は開始しない。
元attemptを再送せず、科学条件・提出権限も変更していない。新コード・test成功は0。

### unit02最初の依頼の停止・診断（07:05 UTC）

unit02 session `11043`は20分監督上限07:05:08 UTCに親がCtrl-Cを送り、
07:05:12 UTCに**exit 130**を確認した。provider/quota障害ではなく監督停止と分類。
worktree clean、対象新規source/testは未作成、implementation lockは解放済み。
最終logは52,357 B / 21 lines、SHA
`f78b1824dd3a327f1beb8d58279f76ae7d9582566104c385e4636afdead45305`。
task SHAは不変。モデルによるsource/test等の読み取りは確認できたが、実装/test成功は0。
旧attemptを含む自動retry予算0、Cloud/共有サービス停止/新worker/物理評価は無し。
独立SOLへ保存logの原因分析を依頼し、次の依頼境界を見直す。同一依頼の自動再送はしない。

並行して親が[unit03生成契約](e26_generation_contract.md)を設計し、SOLのAPI診断と
独立設計レビューを完了した（SHIP）。source/科学条件のpre/post固定、CSV物理検査と
stage telemetryの保存則を明確化。unit02受入前にはunit03をdispatchしない。
これは設計と実行blockerの診断進捗であり、runner完成や精度改善ではない。

### unit02開始時点の履歴（06:45 UTC）

継続goalとunit01完了を根拠に、独立dispatchレビュー後、unit02を別の実装単位として一回開始。
session `11043`、internal thread `01a07576-b558-7541-9290-de1f9cbf08ed`。
開始06:45:08 UTC、親監督上限07:05:08 UTC、自動retry0、`--interactive`無し。
受付logはroute=flash / model=qwen38-flash-next / admitted 0.01sを確認。
task SHA `616feedd816c98f8523016f89456a158684815f81dd6dd88f6f049436b86841e`を固定し、
logを`outputs/local/e26_implementation/unit02_flash_attempt1_WORKER.jsonl`へ新規保存。
Cloud・実データ・生成・採点・提出は対象外。旧unit01のretry予算0は維持。
unit02成功や精度改善は未証明。以下06:40以前の未dispatch記述は開始前の履歴として扱う。

unit01を承認済みworktreeで再検証し、テスト一ファイルだけを
`d9356bc4f260defbbc8f80ca9da4f01cdb72c45c`へcommitした。
canonicalの既存変更と重ならないことを確認してcherry-pickし、canonical commitは
`18234bd785cfd0dcf6a66ce0cc7cfd0fd8920142`。両方のfeature branchを維持し、pushはしていない。
親が新規3件と既存public-postproc 508件を同一processで実行し、worktreeで511 PASS (1.80s)、
canonicalで511 PASS (1.48s)、双方Ruff PASS。独立SOLの同一suite確認も511 PASS。
最終test SHAは下記と同一。統合前後の既存unstaged diff SHAも
`d151eb28b8d47fc120eaa2fcf5c5ca4a670021e8978c7aa07378db64d02dafbb`で一致し、既存WIPを保持した。
開始前のapproved worktreeはclean。unit02–04は未完成であり、runner完成・精度改善とは数えない。
次の小単位は[unit02依頼仕様](e26_unit02_task.md)。既存E25 gateはimportしない。

共有設定担当の配置後、委譲された起動設定だけをSOL subagentが変更し、別SOL reviewerがSHIP。
canonical commit `b6b0d1599b53ce956ecef00da6ed03ca1194ce0c`、承認済みworktreeへの同期commitは
`3ecd535e44a90cce3bf43d6f31bdba5c525f2e9c`。科学アプリ実装のSOL代行ではない。
既定はFlash固定、新queueへ明示`--interactive`を渡した監督付き直接依頼だけCloud候補となる。
待機後のworktree/branch/clean/index flags再検査、signal転送、未回収lock保持を模擬回帰した。
起動回帰16件は独立SOLでPASS、親はE26/public-postprocと合わせ527 PASS (23.41s)、Ruff/sh -nもPASS。
設定同期後のapproved worktreeでも親が527 PASS (23.67s)を確認し、worktree cleanを再確認した。
共有queue SHA `7c7d59a4e1edcc2a65d1620076a8250712175c570a3d73e633e7ac65c8973330`を照合済み。
この検証はfake Codex/queueとmock metadata、および共有sourceの静的importだけで、
実モデル/health/Keychain要求は0。新経路の実Cloud疎通・残量・実装品質は未検証。
共有ファイル・AGENTS・既存科学WIPを変更せず、旧attemptのretry予算0と採点HOLDを維持する。
無人goal/heartbeatはCloudへ流さず、サブスク限定・追加課金禁止を維持。
最新ユーザーのFlash主指示を旧モデル固定記述より優先する。今回新workerは起動していない。

### unit01実装・回収の履歴（2026-09-06 04:05 UTC）

新しい直接ユーザー指示「サブスク範囲で使用して」に対し、親と独立SOLは公式の
coding/agent tool内の対話的Agent利用の記載から、今回の単一・監督付きcoding taskを対象内と判断。
`codex exec`という内部subcommandだけで全利用を保留した従前の解釈は、この直接依頼には適用しない。
cron/無人goal継続/backend/batchに拡張せず、従量課金/追加購入/upgrade/reset/fallbackは禁止する。
根拠・接続先の秘密値なし照合・新規起動予算1/retry 0は[実験台帳](experiment_ledger.md)に記録した。

session `57343`で既存r3をexact `qwen3.7-plus` / `qwen_token_plan`へ依頼し、モデル応答と
コード生成を確認した。残Credits/実消費量は未確認。04:02 UTC、圧縮後の再読/書換反復を
抑えるため親が対象workerだけを停止（exit 1、正常完了ではない）。追加起動/retryは行わない。
ログ: `outputs/local/e26_implementation/unit01_contract_r3_plus_direct_user.log`。
モデル一覧のformat差/metadata不足warningは出たが会話は進行している。fallback metadataは
別モデルへのfallbackを意味しない。今回launcher/provider/metadata設定を変更していない。
最後の誤った書換版はignored出力へ保存し、log item_62のQwen-authored版を原文hash一致で復元。
親はRuffの機械的import修正だけ実施し、ロジックは実装していない。最終成果は承認済みworktreeの
`tests/test_e26_motion_relink_contract.py`、SHA
`0c5ef2972015ee4a5b1c4e7ea0e5a4151c87b0ec959281b3e8a6bc3ab1c82fc8`。
全差分再読、親/独立SOLのpytest `3 passed in 0.91s`、Ruff PASS、独立レビューSHIP。
この時点では新test一つを未commitで保持した。現在の統合状態は上節を優先する。
unit02–04/生成/採点/提出は未実行。unit01だけで精度改善とはしない。
次の実装依頼は、反復を抑える短い文脈・必要APIの限定提示・残存成果の保全を設計してから行う。
32k context/24k compactと初期文脈量の関係は原因候補であり、因果はまだ未検証。

## 利用経路確認の履歴（2026-09-06 03:03–03:48 UTC）

以下は直接ユーザー起点の新しい依頼より前の状態であり、現在状態は上節を優先する。

2026-09-06 03:11 UTC時点の履歴: 再開後3 goal turnで同じprovider利用条件のblockerを確認し、
goalをblocked（適合する接続先/実行方式の選択待ち）へ変更した。目標の縮小・達成ではない。
現providerのみ・実装4ファイル未作成・worktree clean・r3 hash不変を再確認済み。
Plus実装の代行、無断の従量課金切替、同じ状態の自動再確認を続けない。

03:38 UTC定期確認時もgoalはblocked。後続のユーザー指示でサブスク限定の費用方針と
接続先は確定済みであり、現在残るのはheadless実装経路の利用条件適合性・実接続の未確認。
このメンテナンスでは実装workerや評価を起動せず、接続先の選択を再度求めない。

### 当時の再開条件（2026-09-06 03:48 UTC）

後続ユーザー指示「サブスク範囲で使用してください」により、費用方針は既存サブスク内に固定。
`qwen3.7-plus` / Token Plan専用経路を維持し、従量課金、追加bundle購入、プランupgrade、
reset消費、別model/providerへの自動fallbackは行わない。上限到達/認証・routingエラーでは停止する。
現在の残量や実接続は未確認で、サブスク方針の確定を実装成功と扱わない。
従量課金への切替選択は不要になったが、非対話workerの利用条件は別問題として維持する。
対話的Agent利用は公式の対象であり、サブエージェントそのものを対象外と一般化しない。
現launcherの`codex exec`経路について公式文書は個別分類しておらず、今回新workerは起動していない。

旧Flash session 35026は承認済み中断で終端済み。旧queue/429/作業コピー承認や、
別候補E17のsource不足はE26再開の待機理由ではない。科学設計の独立再レビューもSHIP。
現在の依存は、**指定Plusで実装できる適合経路 → 実装・テスト・独立レビュー →
直列SCREEN → 対象環境の提出前確認**である。

親が[公式Token Plan Personal Overview](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/token-plan-personal-overview)
のMarkdown版を全文取得し、別SOL reviewerも利用範囲を独立確認した。
coding/agent tool内の対話的な呼出しは対象だが、automation script、custom backend、
非対話batchは禁止されている。自動goal継続を対話的な呼出しと読み替えず、今回workerは起動しない。
機械側設定のprovider名は`QwenCloud Token Plan Individual`、APIは`responses`、
認証は既存command-backed方式であることだけ再確認した。秘密値取得・認証command実行は無し。
公式のモデル一覧には`qwen3.7-plus`があるが、現アカウントの残量・実API互換・疎通の証拠ではない。
指定Plus/Token Plan経路でのheadless利用条件の適合性確認、または実際の対話的実行の適合性確認が必要であり、
単なる追加許可やモデル名変更では利用条件を解除しない。従量課金への無断切替もしない。

次依頼を`outputs/local/e26_implementation/unit01_contract_r3_plus_TASK.md`として準備した。
SHA `6fccfcc47ca6ebf1dd9afea2a990379a3c0095f81de347ac011200f87a4d967f`。
r2からの差分はタイトルとrouting/開始条件だけで、3つのtest、fixture、実行commandは同一。
旧r2/task/logを保持し、Plusの新worker・新retry予算はまだ発行していない。

親が固定する実装分割は次の4単位。単位ごとに指定Plusが実装し、SOLが全差分を再読して
focused pytest/Ruffを再実行し、別SOL reviewerの受入後に次へ進む。

1. `tests/test_e26_motion_relink_contract.py`: bool一項差とmotion分岐の合成test。
2. 新規`src/biohub/e26_screen.py`と`tests/test_e26_screen.py`: E26専用schema、
   固定順/config差分検査、純粋な段階gate、境界/未定義/ERRORのtests。
3. 同module/testsと新規`scripts/e26_screen.py`: GT-free生成親子process、fresh public-four
   baseline parity→baseline36→candidate36、入力/source/dependency pin、strict DeepCenter、
   CSV検査、stage telemetry、排他的出力/失敗保持、pre/post hashとseal。
4. 同module/CLI/tests: 別processでseal再検証、公式eval12→条件付きeval24→保存行36集約、
   最初の不合格と全公式行の保存、12失敗時の24非参照、誤昇格/no-submitのtests。

clean worktreeのHEADには未追跡E25 runnerが無い。既存のcommitted public-postproc/
strict loader/CSV validator/official metric APIを再利用し、E25/ST-R3の未完成sourceや
gateへ暗黙依存しない。unit01だけの成功をrunner完成や精度改善と数えない。
物理実行予算はrunnerの実装レビュー後に固定し、今回の準備から生成・採点を開始しない。
SCREEN_PASS後も対象環境の全pipeline時間/RAM、再現性、提出同値性、現行ルールの確認が別途必要。

## 結論と根拠

次の候補を **`e23_motion_relink_off_v1`** とする。
exact E23の`BIOHUB_OUTPUT_MOTION_RELINK`だけを`1`から`0`へ変更する。
rawの全辺を最終CSVへ戻す操作ではなく、全辺の作り直しを行う一段を通さず、
それ以外のE23後処理をそのまま実行するA/Bである。

D1の既露出baseline eval12診断では、両端対応済みFN205本中82本はsolved rawに
存在したpairが最終CSVから消えていた。121本は両方に無く、2本はnonraw端点を含む。
最終出力のraw node間新規pairには公式TP37本／FP156本があった。
`public_postproc/pipeline.py`のmotion relink経路は、非空の新しい辺集合が返れば
入力の辺集合を丸ごと置換する。このstageを除去した正味の効果を測る。

これはstageの原因確定ではない。D1のraw/final二地点から82本を消した個別stageは
特定できず、raw座標での正誤も測っていない。GTは疎で、37/156は公式評価対象の
部分集合に限る。raw保持にもFP199本があり、全復元や改善幅のoracle主張はしない。
新しい正解37本を失うリスク、gap/division/pruneを介する下流変化を採点へ含める。

根拠artifact: `outputs/local/e23_fn_diagnostic/d1_raw_final_v1_20260905/RESULT.json`、
SHA `82498d231340a1155cb8cabbd6f976497540bbfae75466505ba2ba6857040b71`。
保存7,828個票は別SOL agentがカテゴリ・集計・一意性を独立監査しSHIP。
写像本体は非保持なので、そのhashの独立再計算は監査の保証外。

旧E11の確率剪定、E12の加速度剪定、E13の候補閾値/ILP係数再調整とは別の介入である。
同じscoreや半径の再探索は行わない。E25 twin-onlyは棄却・退役済みのまま保持する。

## 固定仮説・変更境界

**仮説:** E23のmotion relinkは正しいraw associationを置換する損失が利得を上回り、
このstageだけを除けば公式combined scoreが動画にまたがって改善する。

- 対照はexact E23。同一solved raw、画像、DeepCenter epoch2/閾値、依存、sourceを使う。
- 有効configの意味のある差は`OUTPUT_MOTION_RELINK: True → False`だけ。
  実験識別は外部run metadataへ記録し、`EXPERIMENT_TAG`も変えない。
- 検出、centroid refinement、linefit、gap closing、safe division、single-parent repair、
  短track削除、全閾値・半径・sort・モデル重みは変更しない。
- 新しいlearned score、確率閾値、motion bonus、rawとfinalの混合、GTを使う復元規則は作らない。
- `OUTPUT_STEAL_TWIN_REWIRE=False`を双方で確認する。twin再実験ではない。
- 無効化で生じる最終node/edge/divisionの差は効果の一部として記録し、
  同数に強制して隠さない。E25専用の「1辺削除・1辺追加」保存則は適用しない。

## 実行方式と保証範囲

これは[Kaggleループv2](kaggle_loop_protocol_v2.md)と同じ**初期SCREEN水準**の、
別candidate-specific手順である。E25の凍結doc/source/seal/結果は変更せず、
旧ST-R3の証明書や採用ラベルを発行しない。

1. 親が設計と実効config差分を固定し、実装者以外のSOL agentがレビューする。
   まず既存`build_config`、`run_postproc_core`、strict DeepCenter loader、
   既存CSV validator、公式`score_submission`等の呼出しで完結するかを確認する。
   新しい候補関数やrunnerは、承認済みの一つのnested worktreeで指定Qwenが実装する。
   実装・独立レビューと親の検証が完了するまで物理評価はHOLD。
   `.txt`などの名目で恒久runner実装や指定モデルの迂回を行わない。
2. canonical checkoutとfeature branchを維持する。既存WIPに触れず、旧sourceと
   新しい実験命令、実効config、依存、raw36/image36/DeepCenter/GT metadataをhash固定。
   実行中の関連ファイル編集を禁止し、開始・終了時の内容一致を確認する。
3. GT-freeな小fixtureでconfig差分、無効時のstage不実行、既存CSV検査と公式score経路を
   確認する。実データでの試運転・局所動画による候補選抜はしない。
4. 現行sourceでfresh public-four **baseline E23** parityを先に確認する。
   既知参照CSV/hashと一致必須。public-fourの候補scoreは取得・採否使用しない。
5. 全36動画をliteral `eval12 + eval24`順で、fresh baseline→fresh candidateの別processへ
   直列に渡す。候補はboolean stage除去でtwin plannerを使わないため、
   E25専用twin dry-runはN/A。baselineは省略せずfreshに作る。
6. 生成には画像/solved raw/固定DeepCenter以外の入力、GT path、採点callbackを渡さない。
   CPU-only、固定thread/seed、network/download/Kaggleなし。既存strict loaderを用い、
   モデル未取得時のfallbackやsilent veto解除を禁止する。
7. 出力はcanonical配下の新規runディレクトリに限定し、排他的作成・上書き拒否。
   baseline/candidateの全36出力を検査・固定してから、別processで採点する。
   CSVのdataset順/集合、node ID、dangling/重複/非連続辺、有限座標を検査する。
   実効configとstage telemetryで有効/無効の発火を確認する。
8. wall timeとprocess RSSを保存し、有限・非負・正常終了を確認する。
   これだけで約200 hidden動画の時間や全process-tree RAMを保証しない。
9. 公式指標は`official/`のHEAD
   `075fc5f5a52d11077f9dc2b074644618f26939e2`をread-onlyで直接使用する。
   explicit ZYX scaleと7 µm matching距離を固定し、独自proxyを採否に使わない。
10. eval12→通過時だけ残りeval24→保存済み公式行の36集約を直列に行う。
    途中不合格なら以後のGTを開かない。予測やthresholdは結果後に変えない。

手続き的GT分離を用いる初期評価であり、同一ユーザーからの敵対的な改変耐性や、
OS-level GT非可視を主張しない。eval36は反復利用済みで新しいholdoutではない。
完全出力は実行時に直接新規保存→再parse/hash/件数検証し、toolには短い要約だけを返す。

## 初回readout前に固定する採否条件

scoreはadjusted edge Jaccard + 0.1 × division Jaccard。
paired mean/median/worstは同一動画のcandidate−baselineであり、公式aggregateと区別する。
以下は新candidate E26の条件で、既に棄却済みE25の条件を変更するものではない。

| 段階 | 全て必須の条件 |
|---|---|
| eval12 | paired mean Δ≥+0.005、median≥0、worst≥−0.002、公式aggregate adj-edge Δ≥−0.002、44b6/6bba双方の公式aggregate combined Δ≥0 |
| eval24 | paired mean Δ≥+0.003、その他はeval12と同じ |
| eval36保存行集約 | aggregate adj-edge Δ≥0、combined Δ≥0、division J Δ≥0、paired median≥0、worst≥−0.002、44b6/6bba双方のaggregate combined Δ≥0 |

E25固有のdivision TP純増4本は、association stage除去の仮説には課さない。
その代わり36集約ではadj-edgeを非悪化とし、division Jも非悪化を要求する。
丸め前の数値で機械的に比較し、不合格条件の裁量的な免除はしない。

全公式TP/FP/FNとdivision TP/FP/FN、pred node数/recall、動画ごとの両score成分、
paired差の分布、系統別集約を完全保存する。成功labelはSCREEN_PASS_REQUIRES_CONFIRMATIONのみ。
診断中の82/121/37/156を期待改善値・達成TP数・採用条件へ読み替えない。

### 実装時の統計・未定義値の扱い

gateの実装はE26専用の別schemaとし、旧E25 gateをimport/読み替えしない。
paired combinedは同一動画の公式`summary.score`のcandidate−baselineであり、
stage/系統aggregateは保存済み公式行をそれぞれ公式`summarise`で再集約する。
eval24は追加24本だけ、eval36は12+24保存行の合計であり、新しい36本の採点ではない。
paired meanは`math.fsum(delta)/n`、偶数medianはsort後の中央2値の`math.fsum/2`、
worstは`min`。入力検証後に表の順でgateを確認し、最初の不合格を固定保存する。
必要なgate値の欠損、型違い、非有限、動画順/集合/母数の不一致はREJECTではなくERROR。

公式`summarise`はdivision TP+FP+FN=0の動画でdivision JをNaNとしつつ、
combined scoreをadj-edgeと等しくする。これを正常な公式仕様として区別する。
補助診断のdivision J未定義値は分母0を確認してJSON `null`と理由を保存し、
combinedを独自にNaNや0へ置換しない。全JSON値へ無差別にfinite要求をかけて正常な
singletonを落とさず、gateに必要なcombined/adj等はfiniteを必須にする。
eval36ではdivision J差が必須gateなので未定義ならERRORであり、gateの免除はしない。

## 失敗記録と次の行動

- 正常に採点されREJECT: v1を退役。戻り値、最初の失敗gate、動画/系統/両score成分、
  topology/node count変化を台帳へ記録する。混合率やmotion bonusの救済探索はしない。
- 計測器ERROR: 失敗出力を保持し、具体的な欠陥一件を診断。無言再実行や候補変更をしない。
- SCREEN_PASS: 候補bytesを維持し、Kaggle対象環境の時間/RAM/再現性・提出同値性と
  現行競技ルールを別途確認する。その条件を満たす場合にだけ、親が必要な一回を提出する。
- 次の原因診断では保存した出力を使う。raw有無だけでILP/モデル/特定stageを断定しない。
- 新学習は無し。新しいLoss値はN/A。学習へ進む別候補にはtraining-loss gateを適用する。

設計・採否・外部操作: 親。原因分析/実行経路の確認: SOL subagent。
独立レビュー/結果監査: 別SOL subagent。恒久code/test実装が発生する場合: 指定Qwen workerのみ。

## 独立レビュー結果と実行開始までの不足

2026-09-05、別SOL reviewerは仮説・単一bool差分・数値gateを**SHIP**と判定した。
生成開始は**HOLD**。処理本体は既存APIで再利用できるが、既存CLIだけでは下記を同時に
満たせないため、別schemaの最小E26 runner/CLI/testsの実装が必要である。

- `postproc_geffs.py`はsorted discoveryと非exclusive出力で、strictな固定DeepCenter、
  開始前parity、入力seal、段階的なGT開示をまとめて保証しない。
- `kaggle_screen`と既存ST-R3 gateはtwin-only専用。候補名の読み替えや既存gateの
  monkeypatchでE26を通さない。特にdivision TP+4を含む旧gateをE26判定へ呼ばない。
- 新runnerの担当は実験呼出しと検査だけ。`official/`、既存postproc本体・E25 sourceと
  成果物、旧ST-R3 WIPは変更しない。実効config差分はbool一項をassertする。
- baselineでmotion stageの有効化と実際の発火、candidateでは無効化と非発火を記録する。
  各動画のskip/fallbackを区別し、baselineが全動画で全辺置換したと決め付けない。

実装用の受入条件は、本書の固定順/別process/fresh出力/入力と設定のpin、公式CSV検査、
新しい段階gateの境界、12不合格時に24を読まない、失敗保持とno-submit、旧schemaとの
混同拒否を小fixtureで検証すること。親はFlash差分全体を読み、関連pytest/ruffを再実行する。
別SOL reviewerの実装レビュー後にのみ、親が一回の直列物理実行を指示する。

### 作業コピーの承認と実装分割（2026-09-05）

ユーザーの「作成していいです」により、canonical配下に実装用の一時linked worktreeを
**一つだけ**作ることが明示承認された。`work/e26-flash`をHEAD
`e410a7aa0b7d394997d0b73421b61d1625b28076`から作成し、専用branchは
`feat/e26-motion-relink-off`。canonicalの既存WIP・ブランチは保持する。
data/models/outputsの複製、追加worktree、launcherの拒否解除は行わない。
既存の未検証WIPをclean化のためにcommitしない。物理評価はcanonicalでのみ実行する。

最初のFlashタスクは新規`tests/test_e26_motion_relink_contract.py`一つに限定し、
全dataclass差分がbool一項、exact候補でmotion関数非呼出し、exact対照で呼出しありの
三点を合成graphで検証する。旧E25/ST-R3 sourceには依存・変更しない。
runner全体を一括で依頼せず、完了・レビュー・検証できた単位から次へ進む。
この承認はworkspaceのブロック解消であり、runner完成・精度改善・採用を意味しない。

unit01の独立レビューで、exact E23のcentroid refinementは`dataset=None`で早期returnせず
例外となり、当初の合成テスト仕様がmotion分岐へ到達しない点を発見した。
初回依頼は共有slot待ちのまま取り消し（session 53554、exit 143、ログ67 bytes、
model/threadイベントなし）、元task/logを保持した。別作業・サービスは中断していない。
修正版`unit01_contract_r2_TASK.md`では画像依存refinementだけを同じsignatureのno-opへ
stubし、exact configと実pipelineのmotion分岐は維持する。画像あり本番parityの証明とは
区別する。修正版の独立レビューSHIP後にのみFlashへ渡す。

unit01 r2は独立SOL reviewerのSHIP（task SHA
`db5b8d474222cc7950be6e77a056a63a083a4d0446d3a9c1e0926c82b56dfcb7`）後、
11:49:13 UTCに起動した。共有queue待ちを経てthreadが開始したが、
`exceeded retry limit, last status: 429 Too Many Requests`で終了し、親がsession 51827の
exit 1を確認した。これはローカルFlash接続のエラーで、Kaggle API/提出ではない。
ログ`outputs/local/e26_implementation/unit01_contract_r2_WORKER.jsonl`は385 bytes、
SHA `f483b61146727d518371cb362ed8c83c7364189e9e24a63621d6f0f68b647839`。
worktreeはcleanのまま、実装ファイル0、テスト未実行。原因確定前の再試行や別モデル
fallbackはせず、SOL原因分析へ渡した。完了確認だけのautomation追加は終了検知により
除去し、元の2時間メンテナンス・通知設定は維持した。

SOL原因診断と親の既存log/code確認で、429終了時間は別の25,875-token prefillと
重なっていた。queueのflockはCodex child終了で解放される一方、bridgeには別の
`INFERENCE_SLOT`があり、占有中の即429とbackend 429透過の両経路がある。
ローカル同時占有と整合するが、保存error本文だけではどちらの429かは識別できず、
正確なrace経路を確定したとは主張しない。確認時はlock保持者なし、両portはLISTENのみ。
共有運用担当へ証拠を伝え、サービス停止/queue変更/新しい推論は依頼していない。
親は同一仕様の新規実装attemptを**最大一回だけ**、再確認時にもidleかつworktree cleanなら
許可する案を独立レビューへ渡した。閾値や候補の変更・科学評価の再試行ではない。
再度終端失敗したら追加retryせず保持する。レビューSHIP前には開始しない。

この再試行案は別SOL reviewerがSHIP。11:58:01 UTC、親が直前にworktree clean・旧成果0・
task SHA一致・共有lock保持者なし・両portのESTABLISHEDなしを確認し、一回だけ起動した。
sessionは35026、threadは`01a0716e-c88d-7873-b838-27d3f9967506`、新規ログは
`outputs/local/e26_implementation/unit01_contract_r2_retry1_WORKER.jsonl`。
12:01 UTCには開始イベントに加え、設定・作業先を読むcommandの正常終了を確認した。
実装成功・テストPASSはまだ主張しない。追加retry予算は0。
既存automation id 2は2時間間隔・元の通知設定を維持したまま、この実行の完了確認を
一時的に追加した。終了時に全差分・対象pytest/ruff・独立レビューを確認し、追加節だけを外す。
恒久runnerの実装・物理評価・提出はこの小テストの完了とは別である。

2026-09-06、共有運用担当がユーザー承認により同実行を中断し、親もsession 35026の
**exit 130**を確認した。正常完了やモデル障害とは分類しない。ログは1,976,990 B、
SHA `44acb83dd15ea4e40d35143ce2f435da93786b54d8556bd18894ef1d710d8d56`。
worktree clean・成果物0のため、新規testのレビュー/pytest対象は存在しない。
終了確認専用のautomation追記を除去し、2時間メンテナンス本体と通知設定を維持した。

続くユーザー指示で、今後の実装モデル設定はexact `qwen3.7-plus` /
既存`qwen_token_plan`へ変更した。旧Flash専用queue/catalogは使わず、認証は既存の
機械側設定からCodexが取得する。設定のオフライン検証のみで、実接続・アカウントの
利用可能性・無人自動実行の利用条件は未検証。旧ログ/凍結科学条件は変更しない。
次の最小実装単位の設計は、既存unit01 r2と同じ3つの合成contract test一ファイルである。
接続/利用条件と別途の実行予算が確定するまで新依頼は出さず、runner全体へ拡張しない。
モデル設定変更を旧attemptの追加retry許可や科学評価の開始条件充足へ読み替えない。

以下は承認前の経緯として保持する。Flash launcherがclean linked worktreeを要求し、
当時のcanonical-only条件と矛盾していたため実装を停止していた。現在は上記の一箇所を
例外として承認済みであり、別モデルfallbackは引き続き行わない。

2026-09-05 11:22 UTCの再確認: Flashのstatusはbackend/bridgeともready。
新しいワーカーや推論は開始していない。登録worktreeはcanonical一箇所だけで、
起動scriptの128/138行はprimary checkoutを、167行はdirty worktreeを拒否する。
launcher SHAは`07135147f201d3b44061d46802a2c0f4e93b257c5db26247cc47321be7088ec9`。
共有`OPERATIONS.md`もcanonical制約の確認前に作業コピー追加/拒否解除をしない旨を維持。
サービス障害やFlashモデル固有のworking-directory制約とは混同しない。
公式CLIの`--cd / -C`は作業先を指定する機能であり、本件の拒否はproject launcherの
明示条件に由来する（[公式CLIリファレンス](https://learn.chatgpt.com/docs/developer-commands?surface=cli)）。
この確認は起動規則の変更許可でも、実装が完了できるという性能証明でもない。

### 既存small-fixtureの検証（2026-09-05 11:27 UTC）

SOL subagentの既存テスト調査を受け、親もfixture本文を確認し、次の6件を再実行した。
`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`
へ以下のnode IDを指定し、**6 passed in 3.23s / exit 0**。
親のsession `83679`は終了済み、terminal chunk `db395b`。合成GTのみで競技実データ・
実モデルは使用せず、D0/D1/E25の評価を再実行したものではない。

- `tests/test_public_postproc.py::test_e23_profile_exact_values`
- `tests/test_public_postproc.py::test_overrides_win_over_the_selected_profile`
- `tests/test_public_postproc.py::test_single_parent_repair_keeps_the_higher_scoring_edge`
- `tests/test_public_postproc.py::test_csv_writer_schema_and_row_shape`
- `tests/test_validate_submission.py::test_valid_submission_passes`
- `tests/test_evaluate.py::test_perfect_submission_scores_edge_jaccard_one`

これらはE23設定、override優先、motion OFF設定下の後続single-parent処理、CSV形状、
validator正常系と公式metric合成正常系を確認する。全テストsuiteやE26の実行保証ではない。
特に**baseline/candidateのdataclass差分がbool一項だけであること**と、
**motion OFF時に該当関数が実際に未呼出しであること**の直接testは未整備。
新runnerの段階gate・異常系とともにFlash実装の必須受入へ含め、既存6件PASSで代用しない。
