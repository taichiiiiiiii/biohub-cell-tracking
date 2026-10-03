# 実験結果から組み直す次ループ設計 — 2026-09-05

状態: **E25棄却済み / D1診断・全個票監査SHIP / E26科学設計SHIP / unit01をcanonicalへ統合済み**。

最新状態（2026-09-07 05:50 UTC）: exact qwen3.8-maxによる実装とtoken-only更新を受入、
version3完走・親/独立二担当の物理監査SHIP。関連703 tests/Ruff PASS。科学設定/helperは不変。
version2の補正集計期待は親の設計誤りだったためFAILを維持し、事後救済せず別runで再現確認した。
E26を一度提出しref56069885/scriptVersionId347872590として受理、採点待ち。
既存2時間maintenanceに当該IDのread-only追跡だけを追加。LB改善/SCREEN完了/採用は未確認、
E23public0.924を基準維持。詳細は[e26_bounds_v3_contract.md](e26_bounds_v3_contract.md)。

以下は04:58 UTCの履歴: E26修正版version2はCOMPLETE。CSVは予定のy一座標差だけで
全236052行/グラフ検査に合格。ただし補正reportは既存の下限clip6件も含む合計7件で、
事前のreport合計1件という親の想定と不一致。原report条件はFAIL、原因の独立レビュー中で提出HOLD。
SCREENはINCOMPLETE、提出/LB改善はまだない。詳細は[e26_bounds_target_run.md](e26_bounds_target_run.md)。

以下は04:34 UTCの実装・実行開始履歴: E26 target version1は座標範囲外1件で提出不可。
exact qwen3.8-max/Token Plan/noneの修正helperをcanonicalへ採用。r2は独立反例でHOLD後に閉じ、
親が1関数+1testだけの次単位へ狭めた。限定修正は156 tests/独立review SHIP、統合後関連693件/
Ruff PASS。保存CSV写像はE23変更ゼロ、E26既知y256->255一件だけ。
notebook統合と独立reviewを完了し、関連703件/Ruff PASS。修正版を一回pushし、実version2がRUNNING。
全33cell source/private/T4/offline/assetsをAPI照合済み。完走・出力検証・提出/LB改善はまだ。
詳細は[e26_bounds_target_run.md](e26_bounds_target_run.md)。旧goal blockedをresumeしたとは扱わない。

以下は2026-09-06 17:20 UTCの履歴:
Flashは97PASS/2FAILと補正記録の実欠陥で未採用。その後ユーザーが「改善しなければ3.8MAXで」と
明示したため、exact qwen3.8-max/Token Planへ親が切替を決定した。Max専用設定は独立review
SHIP、運用42件/関連553件PASS。Maxは17:13:29.870505 UTCに164.016秒で正常応答したが、
隔離test112PASS/1FAIL、lint2件、実際の検証漏れを独立probeで確認し、受入HOLD。
テスト失敗自体は値を変えていない誤oracleであり、それとは別にprojection/ID/time/集計の欠陥がある。
本体未採用。残り監督枠内で安全に再修正・検証できないため、原600秒枠を延長せず単位を終了した。
Max選択は維持し、設定none/再試行0/自動fallbackなし。元Flash単位も閉じたままである。
次の修復設計と統合境界は[境界修復設計](e26_bounds_repair_design.md)、実証は実験台帳を参照。
新kernel/提出/LB改善はなく、E23 LB0.924が基準。旧goal blockedを親がresumeしたとは扱わない。

以下は2026-09-06 14:16 UTC時点の履歴: Qwen Cloud exact qwen3.7-plusの実装を受領したが、
public4の設定誤り、4件のテスト失敗、17件のlint違反でunit02aは未採用。
独立レビュー済みの修正依頼は10:51 UTCに共有枠busyで受付終了し、モデル要求は開始されなかった。
元の実装は保存済み、承認済みworktreeはa17eb02でclean。現在の共有枠の空きは未確認。
goalは14:16 UTCにactiveと確認後、同条件を再開後3連続で確認し14:20 UTCに再びblocked。
自動継続を対話的Cloud利用の承認とは扱わず、実装workerは起動していない。
unit02a修正受入→unit02b→unit03/04→直列物理評価の順序を維持し、精度改善は未確認。
最新の実行証拠は[Cloud実行復旧記録](e26_worker_scope_recovery.md)を参照する。

以下は09:35 UTC時点の履歴であり、現在の実装経路や起動指示ではない。
単発local復旧session54736は09:32 UTCの45分capでSIGINT/exit130終了。
patch/新source/実装test0、worktree clean/client終了/lock無し。今回はSSE/provider errorではない。
09:35 UTCの上流active1は09:42:37にactive0となり既知接続も消滅、枠解放を確認。
新worker/Cloud/自動retryは起動しない。実行範囲の別案は模擬検証・独立レビュー中で未採用。
unit03–04受け渡し設計は独立SHIPだが、実装・物理評価・精度改善の実績とは区別する。
詳細と次の限定検討は[復旧記録](e26_transport_recovery.md)。
以下は旧失敗と復旧前の履歴。unit02aは07:39:54 UTC頃にSSE idle timeoutで終了、親が07:40:56 UTCにexit1確認。
worktree clean・実装file0・lock無し。再試行/Cloudは行わない。共有担当の隔離transport診断では
commentがCodex 0.153.4のidleを更新しないことを再現済み。元障害の全原因は未確定。
その後、隔離修正60件PASS・独立レビューを経て共有ownerが修正を配備した。
08:43 UTCに親が実source hash・稼働PID・ready healthを確認、配備後模擬回帰33件PASS。
次は [最小復旧設計](e26_transport_recovery.md) に従い、独立配備監査後に単発local起動を判断する。
unit02b/03/04設計SHIPは維持するが、生成・採点・精度改善の実績はまだない。
以下のsession開始・監督記述は時点付き履歴であり、現行の待機指示ではない。

2026-09-06 07:13 UTC: 下記の停止を診断後、読む範囲とAPIを限定したconfig-only
unit02aを独立レビューSHIPのうえ一回再依頼。local Flash session `83288`、
当初07:33:26 UTCまで監督・自動retry0・Cloud無し。07:30 UTCの独立運用レビュー後、
同じlive sessionのcapを一回だけ合計45分、**07:58:26 UTC**へ延長した。
再起動/追加延長/Cloud無し。元unit02全体の科学要件は維持する。
新コード・test完了は未確認。同じsessionを継続監督し、観測timeoutだけで再起動しない。
unit02b詳細とunit04公式採点契約も独立設計レビューSHIP。実装/実データの成果とは区別する。

2026-09-06 07:05 UTC: unit02 local Flash session `11043`は20分の監督上限で
親が停止しexit130。worktree clean・実装file0・自動retry0・Cloud無し。
保存logを原因分析へ渡した。並行した[unit03生成契約](e26_generation_contract.md)は
独立設計レビューSHIP。unit02の実装/受入が先で、生成・科学採点は未実行。
現在の[E26実装記録](e26_motion_relink_off_design.md)を優先する。

2026-09-06 06:12 UTC更新: Qwen-authored unit01を検証済み単位としてcommitし、canonicalへ
`18234bd`で統合した。親の統合後検証511 PASS・Ruff PASS、既存WIPは保持、pushなし。
unit02–04/生成/採点は未実行。次の判定実装は[E26 unit02仕様](e26_unit02_task.md)に限定する。
06:38 UTC追記: 共有Flash主queueへの起動設定を`b6b0d15`へcommitし、模擬回帰16件・
関連527件の親検証と独立レビューを通過した。新しい実モデル呼出しは0で、無人Cloud・追加課金は禁止のまま。
モデル経路の検証範囲は[E26実装状態](e26_motion_relink_off_design.md)を優先する。
以下は時点付き履歴であり、現在の接続・未commit・再起動指示として読まない。

2026-09-06 03:53 UTC更新: 新しい直接ユーザー依頼による単一・監督付きcoding taskは、
公式のtool内Agent対話利用に該当すると親/独立SOLが判断し、session `57343`を起動した。
専用Token Plan経路で実応答を確認。04:02 UTCに反復停止し、04:05 UTCまでに有効なQwen-authored版を
復元、機械的import整形後に親/独立SOLのpytest 3 PASS・Ruff PASS・review SHIP。残Credits/実消費量は
未確認。retry/fallback/追加購入なし。unit01のみ検証済みでrunner全体/精度の成功ではない。
無人goal/heartbeatへの拡張はしない。以下03:48 UTC以前の保留は履歴とし、
最新の[E26実装状態](e26_motion_relink_off_design.md)を優先する。

2026-09-06更新: 旧session 35026はユーザー承認の中断でexit 130、成果物0。
現在のモデル設定はexact `qwen3.7-plus` / `qwen_token_plan`。旧retry予算0は維持し、
実接続は未検証。公式Personal Token Planの利用条件は確認でき、対話的利用に限られるため
現在の自動goal継続ではworkerを起動しない。指定Plus/Token Plan経路でのheadless利用条件、
または実際の対話的実行の適合性確認が必要。最新の[E26再開記録](e26_motion_relink_off_design.md)を優先する。
以下の9月5日の依頼・待機記述は履歴で、現在の再起動指示ではない。

後続ユーザー指示で費用方針は**既存サブスク範囲のみ**に確定した。従量課金への切替選択を
繰り返し求めず、追加枠購入/プラン変更/reset消費/別modelへの自動fallbackを行わない。
exact Plusの専用Token Plan経路を維持する。上限で停止し、対話的Agent利用と現在の
非対話launcherに残る利用条件の問題を分ける。現アカウント残量・実接続はまだ未確認。

2026-09-05追記: E23 baseline eval12の一回のD0診断で、公式FN338本のうち
両端対応済み205本、片端以上未対応133本を確認した。保存できた集計は独立監査SHIP、
stdout省略による個票保存の欠落は台帳へ明記した。続くD1で両端対応済み205 FNを
rawから消失82／rawにも無い121／nonraw端点2に切り分け、全個票を直接保存した。
後処理で追加されたraw node間pairは公式TP37／FP156。次はmotion relinkだけを外す
一因子A/B（E26）の設計レビューはSHIP。既存APIを束ねる最小runnerは必要で、
ユーザーが一つのnested作業コピー作成を明示承認したため、`work/e26-flash`の専用branchで
Flashによる小単位の実装を再開する。runner実装・独立レビュー・検証前の物理実行はHOLD。
独立レビュー済みunit01 r2はqueue待ち後にローカルFlashの429でexit 1、実装ファイルは0。
workspace制約とは別の接続問題として先行prefillとの占有重複を診断した。正確な429発生経路は
未確定だが、idle確認を条件とする同一仕様の一回限定retryを別SOL reviewerがSHIP。
11:58:01 UTCにsession 35026で依頼済み、結果待ち。追加retry予算0・候補生成/採点なし。
詳細は[E26親設計](e26_motion_relink_off_design.md)。診断を精度改善とは数えず、E23 LB0.924を維持。
ranker元sourceはv21公開ページを確認できたが完全source取得は404、CLIと同じ版指定での
限定診断も403で失敗した。取得予算2回は消化済みで、R0 HOLD継続。D1はこの取得に依存しない。
以下のLoop S等は過去の固定設計であり、現在の再実行指示ではない。

2026-09-05 09:45 UTC追記: 下記のLoop Sは一度の直列生成・公式採点を完了し、
paired mean Δ `4.054474065928737e-07`が登録バー`0.005`に未達だったため、
`e23_twin_only_v1`を退役した。eval24/36は未採点、Kaggle提出なし。
元の設計・条件は履歴として保持するが、再実行指示ではない。
次は既知ranker lineage v21の元sourceを一件に限定して確認し、解禁済みE23 baseline
eval12のFN内訳診断を実行前に設計・レビューする。
最新の結果・原因・担当条件は[実験台帳のE25後の次ループ設計](experiment_ledger.md)を優先する。

同日追記: ユーザーの明示切替承認により、初期評価の実行手順は
[Kaggleループv2](kaggle_loop_protocol_v2.md)へ移行した。本書の候補順・科学的制約・
数値gateは維持するが、§5の旧ST-R3完全接続は初期SCREEN評価の開始条件ではなくなった。
旧ST-R3とそのHOLDは削除せず、SCREENの成功を旧契約の成功へ変換しない。

この文書は、E1–E24とcheckpoint/loss監査に基づく実行順・判断理由・担当境界を定める。
実験の数値条件や候補生成器は変更しない。個別の凍結仕様を優先し、実行前には最新の
code/artifact/環境を別の事前登録manifestへ固定する。本書だけでは実験開始条件を満たさない。

## 1. 設計判断

**E23を固定対照として、twin-onlyを一回反証し、その次にE17 rankerを試す。**
学習量や半径を増やす路線へすぐ戻らない。並列に進めるのは設計・実装・独立レビュー・
資産確認までで、性能を測る実行と結果の開示は直列にする。

- 現在の自分の提出基準はE23、public LB **0.924**。外部の0.933は別の再現anchorで、
  自分の提出結果でも、E23へ単独ノブを足した結果でもない。
- 0.945は**8月30日時点**のgold圏proxy、0.947は当時の余裕込み作業目標。
  現在のgold cutoffは本設計では再取得していない。0.947−0.924＝0.023は未達成差であり、
  候補の期待値を足して埋まったことにしない。最終目標はprivate gold圏で、保証はできない。
- 直近の完了条件は「追加の設計書」ではなく、**信頼できるtwin-onlyの採否結果一件**。
  評価基盤の修正と精度改善実験は別成果物として記録する。

twin単独で+0.023を埋める実証根拠はない。本設計は金メダルに向けた次の検証計画であり、
到達を裏付ける精度結果や成功確率を既に持っている、という意味ではない。

根拠: [実験台帳](experiment_ledger.md)、[gold-loop運用](gold_loop_protocol.md)。

## 2. 何を実験から学んだか

| 観測 | 言えること | 次設計への制約 |
|---|---|---|
| E3: base1 0.908 → base2 0.919 | 複合構成の提出改善。dual-seed単独の因果効果は未分離 | 同一対照・同一入力で変更一つを比較する |
| E5: public-four local +0.0041、LB 0.907 | 一動画に集中したlocal利得では採用できなかった | 平均だけでなく最悪動画、中央値、両系統を必須にする |
| E10: 旧eval12でedge FP 410、both-linked FN 131 | 誤った関連付けに大きい誤差がある | associationは有力。ただしoracle約+0.065は達成予測でもE23残余でもない |
| E11–E13: 既存確率・margin・限定運動・ILPスカラー変更は最大約+0.0014 | 試した同一モデル由来の後処理は登録バー未達 | 同じ確率の再閾値化を止め、別の情報を試す |
| E7/E9/E18: CNN AUC 0.867でもdeployment top10=0、既存forward/reverseも順位バー未達 | 小さい正例比率ではAUCだけでは運用precisionを保証しない | 新headは全deployment候補上のprecisionと公式graph損益を評価する |
| E7: 旧混合rewire 173編集でTP +1 / division FP +8 / local +0.0013 | 編集できることと正しく直せることは別 | 一般stealを混ぜず、構造を限定したtwinだけを試す |
| E14-b: 検出閾値緩和はrecall +0.0007、score −0.0015 | 低信頼検出の単純追加は失敗 | 検出を再開するなら追加の一致情報が必要 |
| E15: 半径拡幅はeval24 +0.0016、20/24動画で負、worst −0.0226 | 小分母動画の正しい辺を壊す損失が大きい | 半径拡幅は再試行しない。division TPだけで採用しない |
| E20: division TPは2のまま、LB 0.906 | 同型oversampling fine-tuneは棄却 | E21も凍結。汚染local +0.0096を汎化改善や機序の根拠にしない |
| E22: mean +0.0010、median +0.0001、22/36非負 | mean +0.002バーを満たさない | bidir 0.30単独の再掃引はしない。E23の他変更との相互作用は未分離 |
| E23: 自分のLB 0.924、public-fourのbyte/graph/公式score parity成立 | 提出基準と移植同値性の根拠 | 全候補をexact E23へ接地。public-fourの0.8845を候補採否に使わない |

注意: E22台帳の「meanとmedianが未達」は数値との不整合で、記録値+0.0001は
登録されたmedian >0を満たす。**mean未達なので棄却結論は変わらない**。
「divisionの全情報を測り尽くした」「学習headしか残らない」は過大な一般化であり採用しない。
失敗したのは、旧base2候補集合上の具体的な選別器・特徴・ノブである。

## 3. 評価データとLossの扱い

- eval12とeval24は過去に反復利用済み。非重複でも独立holdoutではない。
  eval36はその合計で、第三の検証集合ではない。固定候補を落とすための
  **段階的な既存データ検証**としてのみ使う。
- 同じlegacy重みのpaired A/Bは、その固定データ上の変更効果を比較できるが、
  上流の学習露出や設計時の反復利用は消えない。
- 動画再抽出からのSD約0.0045は母集団移動の粗い目安で、同じhiddenでの再実行雑音ではない。
  E2/E4の0.908二回一致は表示上の一致だけ。少数例から精密な信頼区間を作らない。
- secondaryの400 epoch履歴ではfirst→lastのedge/detection/validation lossが
  96.1% / 87.3% / 70.3%低下した。しかしvalidation 40本はtrain 199本の部分集合で
  44b6だけ。best epoch 381という選択履歴は確認できても、汎化PASSではない。
  primaryはcomplete historyがなく、best epochやloss低下を主張できない。
- 新規学習は[training-loss gate](training_loss_gate.md)を必須とし、train loss、
  固定train probe、validation lossを別系列で保存する。Loss低下だけで提出しない。
  上流まで未接触の評価を確保できなければ、legacy診断をpromotion-gradeへ格上げしない。

## 4. Loop S: twin-onlyを最初に試す

候補は既存の **`e23_twin_only_v1`** のみ。
細部は[twin-only設計](steal_twin_design.md)、
[ST-R3評価契約](steal_twin_st_r3_eval_contract.md)をそのまま使う。

### 固定仮説と変更

同時刻に近接する親P/Qが娘A/Bを一本ずつ所有している一部のケースは、真の分裂が
二つの親へ分断された状態である。E23のorphan safe-division後、限定された候補だけ
`Q→B`を削除して`P→B`を追加する。

- Pはmid-track、Qはtrack-start。相互に一意な最近傍で親間距離≤5.0 µm。
- P–B≤8.0 µm、P–A≤10.0 µm、娘間5.5–11.0 µm。
- 両娘に異なるt+2 successorがあり、分離距離が≥2.25 µm増える。
- synthetic nodeは対象外。DeepCenter epoch2 / 0.12 vetoを固定する。
- 既存のsort、frame最大1 / video最大2、衝突規則を維持する。
- mutation直後はノード不変、辺を一本削除・一本追加。下流prune等による追加変化は
  最終出力で別計上する。一般steal、モデル、検出、半径、capは同時に変えない。

これは旧E7の混合rewireの再実行ではない。ただし成功の保証はなく、
限定された候補集合ではTP純増4に届かない可能性も含めて検証する。

### 凍結済み採否条件の要約

| 段階 | 必須条件（全て満たす） |
|---|---|
| 生成・実行可能性 | 同値性、再現性、入力固定、GT非可視、全体メモリ、対象環境時間の全gate |
| eval12 | 動画対応mean Δscore≥+0.005、median≥0、worst≥−0.002、aggregate adj-edge Δ≥−0.002、両系統aggregate Δscore≥0 |
| eval24 | 同じ凍結出力でmean≥+0.003。他の上記条件は同じ |
| eval36集約 | 保存済み12+24行のみ。aggregate division TP純増≥4、adj-edge Δ≥−0.002、combined Δ≥0、division J Δ≥0、median≥0、worst≥−0.002、両系統Δ≥0 |

eval36のcombined条件を勝手に+0.003へ変更しない。ranker/headの条件とは別である。
公式`per_sample_metrics`と`summarise`を直接使い、動画meanと公式aggregateを混同しない。
一段でも不合格なら終端にし、次の集合を開かず、同じv1の修正・再生成をしない。

### 一回の物理評価

同一runの全36本を、GTを見ない状態で
**安全dry-run → baseline AB → candidate AB → candidate BA → baseline BA**
の順に生成する。同時実行しない。再現性・実行可能性通過後だけeval12→eval24→集約へ進む。
速い方だけを選ばず、既存契約の保守的統計を用いる。
candidate時間≤baselineの1.25倍、RSS≤baseline+1 GiBかつ対象RAMの80%、
対象環境への保守外挿≤宣言時間上限の80%を維持する。local Mac単体の計測では代替しない。

## 5. 実験開始までの最短経路

9月5日時点で画像は36 roots / 3,672 filesのREADY、GT欠損の回復receiptも存在する。
画像証跡は`outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct/READY.json`
（SHA-256 `8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e`）、
GT回復証跡は`outputs/local/st_r3_gt_recovery/20260905T023957Z/RECEIPT.json`
（SHA-256 `b42409cdb94b9fc936a2ea4e3ba3e94be7a9246168566bab1970568e07d93899`）。
本設計の作成時に両receiptを再hashした。GT graphの解析や再採点はしていない。
しかし「データ回復」「単体テスト合格」「採否に使える評価完了」は別である。
現行generationは`GENERATION_HELD`、scorerのproduction validatorは
`HOLD_INTERFACE_INCOMPLETE`を返す。新候補の性能はまだ読めない。
現generatorはterminal HOLDも発行するため、接続修正前に五実行を先に回しても
そのrunを後から正規評価へ再利用できない。**現行generatorの先行物理実行はしない**。

| タスク | 作業境界と完了条件 | Agent effort / 実行順 |
|---|---|---|
| S0: 実行環境の可否 | read-onlyでGT/host隔離、network禁止、whole-process-tree計測と対象環境whole-job/cgroup校正の実現方法を確認。方式不成立ならplatform HOLD | medium棚卸し / high方式レビュー。S1と並列可 |
| S1: producer最終レビュー | raw/checkpoint、image/GT viewの差分・既存指摘を独立検証。正式producer→consumer形式、固定出力、入力再検証と必要テストが成立 | high。独立ファイルは並列可 |
| S2: production接続 | generation/feasibility/scoringの正式API、opaque GT scanner、canonical CSV/order、sandbox/計測を接続。合成fixtureで正常・停止経路を検証 | high。schema確定後に担当分割、統合は直列 |
| S3: code freeze | 検証済みclean commitと候補/config/数値gate/次行動を固定。旧未完成差分を巻き込まない | highレビュー、medium操作。直列 |
| S4: 正式な前提証跡 | 同commitのE23/base1 parity、raw/image/live input、opaque GT inventory、依存・platform証跡。必要ならGT非接触の対象環境校正実行を先に行いreceiptを取得 | medium操作 / high検証。独立collectorは並列可、物理計測は直列 |
| S5: final preregistration | S3/S4の全参照と校正・対象資源・命令列をhash固定。未取得の校正を自己申告PASSにしない | medium操作 / high検証。直列 |
| S6: 5実行とgeneration seal | §4のdry-run/AB/BAを実行。独立verifierが入力・再現性・保存則を再計算してGENERATION_SEALED | medium操作 / high検証。完全直列 |
| S7: GT view build/verify/import | S6 hashと事前opaque inventoryにbindした採点専用viewを発行。GT graphはまだ解析しない | medium操作 / high検証。S6後に直列 |
| S8: feasibility | S6/S7と生の時間/RSS/対象環境receiptから全gateを再計算してFEASIBILITY_PASS。自己申告booleanは不可 | high。S7後に直列 |
| S9: 公式readout | production validator通過後、一度のstage allで12→通過時24→保存行集約。HOLD/REJECTを含む終端判定と台帳で完了 | medium操作 / high判定監査。完全直列 |

S2は変更前に独立レビューする。実作業量はS2が大、他は小〜中を見込むが、
絶対所要時間は実行環境確認前に捏造しない。各段は前提が閉じたときだけ次へ渡す。
今回の設計依頼ではこれらの実装・物理実行・提出は開始しない。

### 接続設計の重要点

1. generation sealは**label-blindな生成物の完全性**、feasibility PASSは**実行可能性**、
   score PASSは**精度条件**であり、相互に代用しない。
2. `HOLD_SCORING_NOT_RUN`をgeneration sealの条件にすると循環する。
   GT viewはgeneration sealを消費する一方、generationが将来のGT import hashや
   scoreを要求してはならない。先にopaque GT content hashを固定し、後続receiptから
   generationへ一方向に参照する。形式変更は独立レビューしてから実装する。
   対象環境時間/RSSの未校正はfeasibility段階のHOLDで、GT非可視等のgeneration要件と
   所属を分ける。最終事前登録が校正receiptを要求する場合は、GT非接触の独立した
   校正実行または事前検証済み保守係数を先に用意する。結果後に係数を選ばない。
3. GT import/内容の同一性確認はGT graph解析とは別。実際のGT解析は
   `FEASIBILITY_PASS`後の該当stageだけ。GT viewをgenerationのsandboxへ渡さない。
   専用opaque-byte scannerを事前登録前に用意し、36 GEFFと採点用36 Zarr metadataの
   inventoryを作る。既存のGT回復receiptは輸送の証拠で、この正式schemaの代用ではない。
   `GENERATION_SEALED → GT view build/verify/import → FEASIBILITY_PASS`を明文化し、
   feasibility manifestがgeneration hashとGT import hashの双方を束ねる。
   凍結済みの論理stateは不変で、このview処理はsealとfeasibilityの間の
   **graph解析を伴わないbyte-binding処理**である。
4. 全HOLDを一括削除して通さない。GT隔離、再現性、全体RSS、対象環境校正、入力固定は
   既存binding要件のまま。型付き生成物と再計算できる証拠で一件ずつ閉じる。
5. primary/secondaryはST-R3のlive inputではなくrawの来歴情報。
   歴史的なtraining PASSやcheckpoint→raw再実行証明を捏造しない一方、
   **今回のpostprocess実験のために二つのbackboneを再学習・再推論しない**。
   live modelは固定DeepCenterだけである。
6. レビュー追加は、入力取り違え、GT漏洩、未計測process、出力改変、誤った採否等、
   この契約の正当性へ影響する再現可能な欠陥へ結び付ける。別用途の汎用基盤化はしない。
7. generationのcanonical typed graphだけではscorerへ渡せない。固定パスのbaseline/
   candidate `submission.csv`、行数・partition hashを保存する正式publisherを接続する。
   dataset順は名前sortではなくliteral `eval12 + eval24`。JSON keyの正規化順と
   意味のあるdataset順を分離し、順序付きrecordとして検証する。
8. 古いpublic-four parity CSV/logが存在することと、同じcandidate commitに結び付いた
   ST-R3形式のstrict receiptがあることは別。producerから正式receiptを発行し、
   fixtureの自己申告PASSや旧ログの人手解釈で置き換えない。

必須と任意を分ける。公式metric、候補一因子、5実行の再現性、staged gateは正しさの必須条件。
GT/network/FD隔離、snapshot/lock、atomic publicationは現契約の必須安全条件であり、
対象環境の時間/RSS校正も**提出時へ後回しにできない採点前必須条件**である。
Kaggle用package・提出は採用候補になった後の別作業。追加repeat、任意debug/可視化、
契約を超えた上流来歴の追加調査は任意で、primary比較の代替やgate救済に使わない。

## 6. Loop R: 別情報によるassociation修正

候補 **`e23_e17_ranker_tiebreak_v1`** は[tie-break設計](e17_ranker_e23_design.md)を維持する。
**twin成功/失敗にかかわらず、最初のranker A/Bの親はexact E23**。
twinとの同時投入は行わない。両者が単独で通っても、合成は別の相互作用実験にする。

- 22特徴rankerを、ILP前の同じtargetに入る上位2候補だけへ適用する。
  margin≤0.35、順位スコア`0.15*p_base + 0.85*p_ranker`を固定。
- 新スコアで全辺を書き換えず、元の二つのE23 objective slotの割当だけを入れ替える。
  候補の追加/削除、tail候補の昇格、全体vetoは禁止。ILPと下流E23は不変。
- raw GEFFは解済みの辺しか持たず、棄却された候補や22特徴を復元できない。
  全pre-ILP表を一回の固定推論で保存し、同じ表からoff/onを解く必要がある。
- ローカルにはhash一致の**隔離cache**がある。利用可能な配布物が完成したわけではない。
  版番号とsource IDの対応、license、support-source、特徴の単位・正規化・欠損規則・
  出力意味を[取得runbook](e17_ranker_artifact_acquisition_runbook.md)どおり確認する。
  不明な特徴を推測/0埋めしない。過去の429 cooldownを現在も継続中と推定しない。
- R0はこの利用適格性監査のみをS系と並列に行える。取得条件/特徴契約が閉じなければ
  rankerはHOLDであり、その場で別モデルへ置換しない。
- とくに**学習groupがsource側かtarget側か、label、pre/post-ILPの特徴抽出位置、
  出力domain/calibration、元のconsumer**をexact sourceで確認する。
  隔離statsは126,705 groupsに対し126,828 positive rowsで、単純な「targetごとに
  正しい親が最大一つ」の解釈と整合しない可能性がある。集計単位が不明なので
  source-local/posthocモデルだとも断定しない。incoming/pre-ILPへの適合が証明できなければ
  frozen v1はHOLDとし、転置・特徴近似・下流移植で救済しない。
- gateは既存仕様のeval12 mean≥+0.005、eval24≥+0.003、eval36の公式aggregateと
  paired mean≥+0.003、分裂非悪化・一動画集中制限・系統/最悪動画・runtimeを全て維持。
  twinの数値を流用しない。期待+0.003〜+0.008は未検証仮説であり予測LBは書かない。

## 7. 後続候補は条件付きで設計する

### 検出consensus: 次の未実装候補

残余の誤差診断が「検出欠損」を支持し、rankerが不成立/利用不可なら、二つのdetector seedと
DeepCenterが一致するsub-threshold中心だけを救う案を次の設計候補とする。
生の閾値緩和とは異なるが、独立な情報であることも利得もまだ実証されていない。
per-seed pre-threshold出力、候補対応、座標、閾値、競合解消、node budgetが未固定なので、
**この概要から実装しない**。新しい単一候補契約と対照・gateを結果取得前にレビューする。
seed間matching/tie/NMS、追加nodeからのassociation生成、centroid/retentionの適用順まで
固定する。ノードを増やすだけで関連付けが未定義のままにしない。
余分なdetector full passを前提にせず、必要特徴は可能なら同じ推論へ同居させる。

### Two-child head: 大きな投資の前に上限と実現可能性を判定

[既存head設計](two_child_head_design.md)のv1は、親と二娘を共同評価する対称headだが、
**既存twin eligible集合のgate/rankだけ**を変える。一般分裂検出器ではない。

- twin失敗が偽陽性/順位付け由来ならheadに検討価値がある。候補集合自体の被覆不足や
  正しい編集の上限不足なら、同じ集合を使うheadも解決しない。
  新規学習前のexact deployment oracle gateを維持し、半径を広げて救済しない。
  当該oracleのcombined純増≥+0.006 / division TP純増≥4等に届かないなら、
  完璧な分類器でもそのv1の条件を満たせない。単なるtwin score不合格とは区別する。
- [tuple census](tuple_census_receipt.md)の371,915件 / 36動画は、広いraw候補集合の
  計算量であって、strict twin件数、正例数、学習効果、対象環境の所要時間ではない。
- frozen encoderのpair-context特徴と幾何からchild順序不変headを学習する。
  sparse GTの未マッチを負例と決め付けず、certified label/ignoreを保持する。
- 現契約は上流までouter foldを除外した5つのstackと最終用stack、最大101 head fitsを
  要求する。legacy重みでheadだけ動画分離してもpromotion不可。
  真正なupstream除外artifact、remaining-train inventory、計算/保存予算が閉じなければHOLD。
  151 divisionsを全て独立学習例として使えると仮定しない。
- Lossは最低6 epoch、固定train probeの後半3 epoch中央値が最初3 epoch比≤0.95、
  別のvalidation selector、best/last分離、全fold非有限値0、grad記録を要求する。
  さらに既存OOF precision/公式graph gateを全て通す。AUC単独では採用しない。

SDWの二点分離は因果解明用の予備候補で、goldへの大幅改善策として前倒ししない。
linefit、単純半径拡幅、同一確率の剪定、scalar ILP、3-frame加速度、同型oversampling、
根拠のないcheckpoint rollbackは、新しい独立根拠なしに再開しない。

## 8. Agentへの引渡しとループ終了条件

全員が本書、gold-loop、担当の凍結契約、現在差分を先に読む。
主作業場所はcanonical checkout、`feat/eval36-kernel-recovery`を維持する。
ユーザー承認済みの例外は、その配下の`work/e26-flash`一箇所だけで、
実装用のbranchは`feat/e26-motion-relink-off`。既存フォルダー名は維持し、追加コピーは作成しない。
設計/採否は親、原因分析・独立レビューはSOLで分担し、棚卸しmedium、診断/review highを
基本にする。今後のcode/test実装は最新`.codex/bin/qwen-implement`経由のクラウドQwen
（今回の境界修復はexact `qwen3.8-max` / `qwen_token_plan` / 設定effort `none`）に委譲する。
Flash不合格時Maxという最新ユーザー条件を適用済み。明示selectorは
`--cloud-only --cloud-model qwen3.8-max`。他projectの既定Plus/既存Flashは変更しない。
作業先の不整合は上記一箇所の承認で解消済み。unit01 r2の一回限定retry
（session 35026）はユーザー承認により中断済み、追加retry予算は0。
共有Flash切替の完了連絡は受領済み。Personal Token Planは無人自動実行には使わない。
03:53 UTCの直接ユーザー起点unit01は単発起動予算1/retry 0を消化し、反復停止済み。
専用Plusの実応答と復元したunit01成果の検証は完了。残Credits/実消費量は未確認。
ローカルFlash queueには流さず、一つのworktreeを複数実装workerで同時編集しない。
制約迂回・Plus/Max/SOL実装への自動fallbackは行わない。これは過去のSOL実装履歴を
変更せず、read-onlyの調査・診断・レビューを妨げない。

- 実装担当: レビュー済みの一つの差分だけ。共有ファイルは一人が所有する。
- 独立レビュー担当: 実装者と別。仮説/入力/公式metric/失敗停止/再現性を確認する。
- 評価担当: hash固定後に直列実行。数値条件を機械適用し、未開示stageを勝手に開かない。
- 親担当: 差分を再読、必要なテスト・lint・型確認を実施し、結果と次の設計を統合する。

各ループの順序は **仮説固定 → 原因診断 → 独立レビュー → 変更だけ実装 → テスト →
直列物理評価 → 失敗原因と対策を記録 → 次ループ設計**。
開始前の診断と結果後の説明を区別し、事後説明を事前仮説へ書き換えない。

実行前に、各評価stemの既知の学習/特徴設計/閾値選択/採否への利用を露出履歴として
manifestへ固定する。結果後の行動も先に定める: 全PASSなら同じ候補の外部一回確認。
有効なscoreのREJECTはlabelと段階GT停止を維持するが、最新の各ループ提出方針により
その科学仮説の探索的提出一回を別判断できる。計測エラーなら候補不変で計測器を修正する。
同じ36本で複数winnerを選び、その最高値を汎化性能と呼ばない。

実験台帳へcandidate ID、code/input/output SHA、変更一つ、対照、事前gate、計測の独立性、
実時間/RSS、動画別公式counts/delta、最初の失敗条件、判定、次に試さないことを残す。
HOLDは評価不能、REJECTは有効な評価で条件未達、ADOPTION_CANDIDATEはローカルgate通過で、
いずれも金メダル達成ではない。
追加の非gating診断として変更動画数、厳密に正/負の動画数、最大単一動画寄与、
leave-one-video-out感度を記録する。median≥0は不変動画が多いだけでも通るため、
広い改善の証明にはしない。再標本化は既知集合への感度であって汎化CIではない。

必要な提出は、仮説・source/config/assets・提出物と判断条件を固定し、一科学ループ一照会とする。
その時点の公式制約/LB境界を再確認し、standing authority内で実行する。local efficacy gate
未達でもREJECTと段階GT停止を維持した探索的提出は可能だが、実装review・再現性・安全性・
正しい有限graph/CSV・完走済み出力の検証は必須。今回のbounds integrity FAILは提出不可。
提出と採用を混同せず、旧E25の退役を解除しない。commit/pushは完了・検証済みの論理単位だけで、
既存の未完成変更を巻き込まず、main/masterへ直接pushしない。

## 9. 今回の設計レビュー記録

2026-09-05、SOL highの独立担当3者で実験根拠、候補の機序/利用適格性、
評価契約/依存順を監査し、指摘修正後は全てDESIGN SHIP。
E17の古い「モデル不在」「parity未完」を現在状態へ訂正し、source-semantics確認を明示した。
既存の候補定義・数値gateは変更していない。

今回変更したのは本書、E17設計の状態/前提整理、gold-loopの参照先だけ。
Markdown参照先と差分の空白検査を確認した。コード変更・コードテスト再実行、
GT graph解析、新しい学習/推論/公式採点、Kaggle操作、commit/pushは行っていない。
作業開始時から存在した未完成コード差分はそのまま保持している。
