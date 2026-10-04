# D3 — 接続欠損のstage診断（前向き実装契約）

## 再開境界 — 2026-09-12

COLLECTION36_ARTIFACT_AUDIT_PASSにより取得待ちは解消。既存成果物を再取得せず、
まず既存stage診断とD2の全edge個票を結合する純粋関数をFlashへ依頼する。
入力は一動画ずつ、dataset/gt_edge_id/両GT endpointを厳密に照合し、重複・欠落・
余剰・IDの型変換を拒否する。全transitionを保持し、FNだけを選択して結合しない。
同じE23 CSVについてD2公式matchingとfinal診断matchingのsubmitted ID/辺存在を
比較するが、差を失敗へ変換せず別統計にする。これはpre/post/final IDの同一視ではない。
合成testで受入後にrunnerへ接続する。結合関数の成功は12動画実診断完了ではない。

runner固定入力の確認済みメタデータ:
- collection root: outputs/local/e23_collection_verified_20260912
- audit: outputs/local/e23_association_collection_audit_20260908/REAL_COLLECTION_AUDIT_20260912.json
  SHA e56db2ab1d9a79a94d8ed97d1b02d9d6391713caf842a2672a0777419391e70a
- D2: outputs/local/e26_diagnostic/d2b_eval12_v2_202609081002/result/RESULT.json
  SHA 2df2b4c2d4cb3aad978358c52b66a893de147b4428816448b2775e090753d767
- E23 baseline CSVは既存D2 scoring/eval12.jsonのsubsets.baseline.csvから取得。
  SHA d4c976c69f850f3f1738523482a272d3468eaf8c99082e128069b9f690ff42a9、25549191bytes。
- D2既露出12順は既存scripts/e26_edge_diagnostic.pyのSTEMSを維持する。
  reference group00–02は系統交互のためflat順は同じではない。集合の一致と
  一意なstem→group対応を検証し、D2順で直列処理する。
- pre/postはassociation_collection_run/{group}/observation/{stem}_{pre_ilp,post_ilp}.npz。
  returned座標は同group直下{stem}_returned.npz。全path/SHAはaudit.bindingsに束縛する。

実GT payload、残り24 GT、matrixの読出しや提出はこの結合実装単位に含めない。

独立Sol/highレビュー（known12_runner_review）はdataset辞書による結合と
公式/診断の意味分離を支持。runnerでは現在のGT node_id/t/z/y/xをD2両armの
gt_source/gt_targetへ照合することも必要と指摘。純粋join関数にGT読取を追加せず、
入力bindと実GTロード後のrunner検証として実施する。D2 artifact pathは成功run直下の
期待basenameへ制限し、全7591辺と7199/54/111/227の収支を最終段で再照合する。
出力COMPLETEは全12と入力前後hash/予算確認の後だけ。途中失敗を完了扱いにしない。

Flash分割実装の最初のidentity helperは合成15 testsで受入。
D2 rootにはgt_source_id/gt_target_idがなく、baseline/candidateの内側にある。
初稿のroot参照は3 happy-path失敗で検出し、正しいnested参照への限定訂正で解消。
旧monolithic join第二稿のMAX評価はREJECT（常時placeholder例外、D2未結合）。
MAXの「Counter/requireが未import」は既存moduleへのappend前提を見落とした指摘なので
棄却する。両名は既存moduleに定義/import済みで、実再現はplaceholder例外まで到達する。
当該MAXは未採用の旧稿評価であり、分割後実装や今後の実GT診断を承認したものではない。

分割後joinはidentity/公式state自己整合/完全bijection/差分集計を統合し、新32caseと
関連131 tests成功。実diagnose_arm→compare_arms、diagnose_stages→joinのE2E2caseで
公式空edgeと診断用matching差を保持することを確認した（2026-09-12）。
join_d2_transitions(stage,d2_records)は一動画のSTAGE_D2_JOIN_COMPLETE_NOT_ADOPTIONを返す。
この開発部品の受入は実known12診断・公式再採点・packet読出し・科学候補採用ではない。
当時runnerは未実装だった。2026-09-12に下記の固定条件で実装・実診断を完了した。

## Graph-only実行の固定条件 — 2026-09-12、実GT診断前

目的はE23の接続欠損を保存済みcandidate/ILP/final各段階へ分解し、D2の全7591辺へ
結合すること。これは新しい精度改善候補の実験ではなく、次の一因子仮説を設計するための
観測診断。E26のhidden悪化をこのE23 traceだけで因果説明したとは扱わない。
実行入口はscripts/e23_association_stage_diagnostic.py。既存D2 collect/verifyと
受入済みReader/diagnose_stages/join_d2_transitionsを再利用する。

- 対象: 固定STEMS順の既露出12のみ。参照group00–02はdataset辞書で解決。
- 固定入力: 前記hashのaudit/reference/D2 RESULT、D2 control/12個票、24 pre/post NPZ、
  既存GT_BINDING/既知12GT filetree/scale metadata/固定baseline CSV。
- 予測はbaseline CSVだけ。GTはGEFF、scaleは画像ZARR metadataから読む。
  GT node_id/t/z/y/xをD2両armへ完全照合し、GTをfinal予測へ流用しない。
- CPU単一process・動画直列。PYTHONHASHSEED=0、OMP/MKL/OpenBLAS/Polars=1、CUDA無効。
  診断区間wall600s、self peakRSS4GiB、出力250MiB。起動/事前binding時間とは区別する。
- fresh出力に事前CONTROL（source/input/versions/budget）を保存し、各動画stage/joinを保存。
  全12/7591辺と7199 retained・54 lost・111 gained・227 sharedを照合してからRESULT。
  前後input/source/control/artifact SHA・GTtree membership・公式source・依存を再照合。
- 時間超過/入力変化/部分成功は完了ではない。最終書込後の失敗時もRESULTをfailedへ隔離。
- matrix読取・packet取得・学習・新予測・新公式スコア・科学候補採用・提出は行わない。

実行前のbinding-only現認は12jobs/308inputbindings/12GTtreesでPASS。
これはGTのbyte照合であり、GT意味解析や全12stage診断の完了ではない。

### 実行前受入、2026-09-12

固定input binderは実308bindings/12jobsで成功。関連85 tests（新runner guard4case、
既存stage/join/readout/D2runner）2.71s、Ruff/diff check成功。新guard testはpreload拒否、
import前後source変更拒否、fresh既存出力保護を検証。全runner mock成功を証明するものではない。
複雑なmock routing testのFlash応答はコードを返さず不採用。既存の実API合成E2E、
親の全source確認と独立科学レビュー、実固定入力bindingを根拠にread-only診断へ進める。
独立レビューのGT/CSV分離・D2座標/edge identity・件数/部分完了扱いは妥当との判断を採用。
指摘されたsource gapは全project import closureの束縛とpreload拒否、import前後照合で修正。
600sは事前bindingを含まない診断区間という既存契約を維持する。

runner SHAb22585c9091d0e003bea8adafdc1a5cdacc654e1b6d5f253e35f4543d83c42f9、
D2入口SHAc6129e57f8f3be89b41225943fc0dc62f7b0302992105f8b4dadb5f1b5668934。
fresh CLIで上記bytesを確認して開始し、実行中はsourceを変更しない。
保存先outputs/local/e23_known12_graph_stage_20260912_v1。まだ完了/精度改善とはしない。
MAXによる科学候補採用承認ではなく、親が管理する既露出データの観測診断である。

### 実診断受入、2026-09-12

上記保存先でsession87983がexit0。全12/7591辺とD2収支が一致し、24成果物を生成。
終了後の458bindings再照合も成功。診断8.759659s、peak RSS552370176bytes。
RESULT SHA d56934295aee62cb2bef3851ce78c8026726315a8e7c045ab24bc64c999dd5ab。
全baseline-final対応ID/辺存在差0。FN338は候補なし108、ILP辺除去14、
ILP endpoint除去14、候補保持149、pre endpoint未対応53。
保持149はpostにも辺があり、finalでは対応あり辺なし102、endpoint未対応47。
この分類は因果介入ではない。次はreturned段階と座標変換を含む後処理の限定診断を設計し、
同一辺の削除とmatching変化を分離する。新candidate/提出/全matrix取得は未実施。
詳細と失敗履歴はexperiment_ledger.mdの同日known12完了節を一次記録とする。

### 次の限定診断設計（結果未測定）

訂正（2026-09-12、次turnのsource確認）: returned.npzはpredict_videoのcoords/candidate
返却値であり、post後の中間出力ではない。association_parity.py:videoと
association_artifact_audit.py:audit_videoがreturned/pre候補対応を検証している。
したがって以下のpost→returned→CSV案は採用せず、postとCSVの直接照合を先に行う。

独立Sol/high known12_result_interpretationもmatrixより段階追跡を優先すると提案。
保持は全体の高ベースレートなので「105/111が保持」単独を原因証拠にしない。
対象は保持FN149（gained105/shared44）、保持lost21および同dataset/frameの保持TP対照。
仮説: post→returned→CSVの特定変換署名（座標丸め・重複・ID再対応・端点欠落）が
最終FNと関連する。元IDの対応根拠を確認し、グラフの実辺除去とGT距離matchingの
相手変更を別ラベルで記録する。102件も現時点では「finalの対応先間に辺なし」であり、
元辺102本の物理削除を証明していない。dataset/frame別の分母・署名頻度を報告する。
同層TP対照と差がなければ変換署名による局在仮説を支持しない。
E26との因果関係はE23だけのtraceでは検証不能。両armの対応段階証拠か固定一因子の
再生実験が揃うまで「E26が変換を回避した」と結論しない。
この段階は入力追跡の診断で、閾値探索・新GT露出・候補採用・提出は含めない。

### 次の情報利用可能性probe（2026-09-12、確率集計前に固定）

現pipelineはmotionへILP後かつ距離filter後の辺のlearned_edge_probsだけを渡す。
graph_opsは辞書にない辺のpriorを0にする。閾値以上のpre候補に記録済みの値でも、
ILP未選択ならmotionが参照しない構造がある。仮説は「現在motionへ渡らないpre候補確率が、
実際の最終辺にも存在する」。計測単位はknown12の同ID辺、pre/post/両CSV集合差と
pre記録確率。未計測値を真の確率0としない。preありpostなしの最終辺が1本以上あれば
情報経路を拡張できる実例あり、0ならこの最終辺ベースの根拠は不支持とする。
これは改善候補の採否gateではなく情報利用可能性の診断。GTの追加読出し・新matching・
閾値調整・motion bonus変更・新予測・提出を行わない。結果が支持しても次の一因子案は
「幾何/bonus/解法は固定し、利用可能なpre候補priorだけを渡す」として別途事前登録する。

### probe結果と次の一因子案（実装・CV実行前）

probeは614本/全12動画で条件を満たした。台帳の同日「後処理ID照合」節が一次結果。
意味は「既存候補scoreに未利用の経路がある」であり、正しさ・精度向上ではない。
motionは元々geometry gate内の全対を探索するため「候補追加」という説明は使わない。

親の次実装設計は、E23のmotionに渡すpriorを、従来のILP選択辺に加えて
ILP未選択の記録pre候補にも付ける一点。従来priorの値/距離filter扱いを上書きしない。
存在しない端点、非隣接frameはmotionの対象外、記録なしはunknownとして記録する。
探索集合・二段geometry gate・bonus・velocity・順序・他の後処理・検出は変更しない。
学習/閾値探索/分裂正例を負例化する処理は加えない。pre→post ID/座標・入力由来を
検証できない場合は実行失敗とし、別graphへ推測で紐付けない。

実装前に対照E23とselected-only配管の同値条件、candidate artifact/source/config、
既存固定CVとworst等のgate参照、実行予算を一つの実験契約として固定する。
selected-onlyでbyte不一致なら科学評価を開始せず実装を訂正する。
独立Sol/highの指摘どおり、ILPの競合制約・分裂構造を局所1対1へ戻す危険と
後続frameへの伝播があるため、edge/divisionと動画別損益を必ず評価する。
E26全廃は負の参照のみ。レビュー提案のshuffle/constant nullは第一候補の採否を
後付け変更するために使わず、候補が既定gateを通った場合の別の事前登録検証として検討。
MAXの高リスク採用前評価は必要。現在3/17、第四評価は上限を超えるため採用は保留し、
訂正呼出しや形式的task分割で分母を増やさない。開発検証は科学候補採用と区別する。

### 任意prior入力の開発契約 — 2026-09-12、Flash著作前

filter_output_graph/pre_linefitにkeyword-only association_priors=Noneを追加する。
None/selected-onlyは従来同値。元raw_edgesにある対は距離filter後に消えても追加対象に
戻さない。pre候補のうちraw未選択、両端が現node集合に存在、t→t+1の対だけを
motionの既存prior辞書へ追加する。選択済みpriorは上書きしない。
keyは厳密intのpair、値は有限[0,1]を検証し、入力を変更しない。preのILP除去nodeを
参照する対は対象外、既知両端の非隣接pairや不正値は例外。検証はgraph変更前。
既存motion/geometry/config/stat/他後処理は変更しない。環境変数や本番CLIでは有効化
せず、候補生成runnerが今後明示入力するAPIの開発だけとする。
Flashはpipelineへの限定literal editsと直接testsを著作し、親が適用/レビュー/検証する。
変更前のtests/test_public_postproc.pyは509 passed（2.25s）。実CVや精度改善ではない。

### API開発検証の状態 — 2026-09-12

optional入力/helper/wrapperをFlash著作で統合。新44caseと既存509caseの553 tests成功、
Ruff/diff check成功。新しいpriorは本番で有効化していない。実motion計算での追加testは
2返却のAPI/schema不備で未採用。次は既存の正しいmotion test fixtureへ最小差分で
selected-only同値とcross-priorの指定集合への切替を追加検証する。
既存入力による旧snapshotとのCSV byte比較、collection priorの束縛adapter、
実験事前登録/直列生成/固定CV/再現性/CPU/形式/採用前MAXは未完のまま。
旧pipeline snapshotと現source/test SHA、失敗経過は台帳の同日API節に保存した。

追記: 実在するconfig定義と成功済み呼出しを渡したFlashの2 literal訂正により、
実motion testを受入。default/selected-only完全同値、cross priorで指定cross辺への
切替を実solverで確認し、計554 tests成功（1.48s）。詳細は台帳の同日実motion節。
API単位は開発受入済み（完了実装下限18/MAX3）、旧実CSV byte同値やCV改善は未確認。
次の接続は凍結E26を改造せず新候補用に行う。coreへpriorを指定する場合はdataset完全一致、
pre/postとraw GEFFの入力由来/ID/座標/辺検証が必須。map.getによる欠落の黙認は禁止。
既存pre NPZの確率を使い、packet取得はこの仮説に追加しない。

### core接続受入 — 2026-09-12

run_postproc_coreにassociation_priors_by_dataset=Noneを追加。指定時はdataset完全一致、
一意stem、厳密dict/key/valueを副作用前に検証し、内側dictをsnapshotして逐次転送する。
Flash著作の新17caseと関連571 tests成功（1.48s）。None/空map byte一致はfilterをspyにした
合成writer確認に限る。実CV/旧実CSV byte一致は未検証。台帳の同日core節にsource/test SHA。
親は実known12 raw GEFF/post NPZ/referenceのsemantic signature一致も確認済み。
追加Reader/全matrix取得は不要。次の候補生成は既存Readerとこの対応を再利用し、
raw/image/model/source/configを新しい実験controlへ固定して実行する。入力接続の成功を
精度改善や科学候補採用と混同しない。完了実装下限19/MAX3、採用前評価条件は維持する。

## 次ループの実装境界 — 2026-09-09 サブエージェント診断

SOL/mediumの読み取り専用診断で、known12（group00–02）のgraph NPZは60/60存在、
collectionのmanifestは9組存在、一方collection packet NPZは手元に0と確認した。
既存coreを再実装する必要はないが、graphの存在だけで全collection受入や実GT診断開始を
認定しない。全HTTPサイズ・artifact受入後に、以下をQwen実装単位として進める。

1. 固定known12/GT binding/E23 baseline CSV/D2 RESULT/collection受入RESULTをSHAで束縛し、
   対象外24のGTを読まない入力境界を作る。safe NPZ loadとfresh出力、数値budgetは必須。
2. 動画を直列に処理し、既存`diagnose_stages`の結果をD2の7,591 GT edge個票へ
   dataset・gt_edge_id・GT endpointsで完全突合する。matchingの再計算による差は別に残す。
3. `plan_queries`で必要packetを列挙する段階と、取得・照合済みpacketへの
   `attach_packet_evidence`を分離する。計画のみの出力を診断COMPLETEと呼ばない。
4. 全12の入力前後hash、件数と分類収支、時間/RSS/容量を照合して最終RESULTを発行する。
   一部成功や途中ERRORを全件完了へ昇格させない。

E26のlocal retained7,199/lost54/gained111/sharedFN227をE23 stageへ結合し、
動画・系統別に候補不在/ILP除去/final変化を分ける。ただしE23のtraceだけではE26側の
中間処理やhidden悪化の因果は証明できない。経路差と母集団差は未解決として別記する。
新しい一因子候補の設計はこの測定の後。E26再提出や既存threshold救済探索は再開しない。

今回の検証: 親の関連120 tests（7.94秒）と5module Ruff/diff check PASS、
診断子のstage/readout40 tests（3.05秒）PASS。これは設計・既存部品の確認であり、
runner実装、Qwen起動、実GT診断、学習、提出、精度改善は今回まだ行っていない。

## 現在の実行入口と不足点 — 2026-09-08 14:33 UTC

SOL/medium子によるread-only入口監査。GT payloadは未読、実装変更なし。
親も関数signatureと既存D2の固定入力入口を確認した。診断関数のtest成功だけで
全36取得後に実12診断を直ちに実行できる状態とは言えない。

実呼出しは `diagnose_stages(dataset, frames_from_npz(pre), frames_from_npz(post),
final_frames, gt, scale)` → `attach_packet_evidence(stage, pre, coords,
manifest_path, manifest_sha)`。CLI/物理診断runnerはまだ無い。

- 全36受入後、固定referenceのknown12順だけを使いstem→groupを一意に解決する。
- pre/postはgroupのobservation下、coordsは同groupのreturned NPZから読む。
  preにはdetector_indices/graph_node_ids/edge_edge_probも必要。
- finalは既存D2の固定baseline CSVを読む。GT bindingとscaleは
  `scripts/e26_edge_diagnostic.py` の既露出12契約に照合し、eval24へ広げない。
- collection監査はpacket全matrixの実読出しではない。必要packetをmanifestと同じ
  相対namespaceへSHA/bytes照合付きで取得してからpacket readerへ渡す。
- 未実装: 安全NPZ loadと入力再照合、fresh動画別JSON保存、時間/RSS/容量上限、
  12本集約、既存D2個票とのgt_edge_id突合。既存coreを再実装しない。
- runnerの順序は入力bind→動画ごとに直列stage/readout/D2突合→入力再照合→
  全12完了RESULT。途中失敗をCOMPLETEにせず、診断専用matchingと公式得点を分ける。

これは次の実装境界の確定であり、実GT診断・学習・精度改善の結果ではない。

2026-09-08。親単独。collection36 v1/kernelId133552379を実行中のまま維持し、
取得後に使う診断を合成データで実装する。collection runtimeの変更/再起動/提出はしない。

## 診断上の落とし穴

1. 公式`metrics._evaluate`はpredにedgeが無いとnode matching前にreturnする。
   既存D2はこの公式挙動を忠実に保存している。そのboth_unmatchedを検出器の失敗へ
   読み替えてはならない。今回は公式が使う`DistanceMatching(max_distance=7, scale=...)`
   と`graph.match`で、edgeゼロでもnodeを対応付ける**診断専用のmatching**を別に記録する。
   公式スコアや公式TPの代替とは呼ばない。D2/公式コードは変更しない。
2. ILPでnodeが消えると最適node assignmentが変わり得る。同じGT edgeについて各stageの
   assignmentを再計算し、固定pre assignmentの実node/edge生存と区別する。
3. 後処理CSVはID再採番・座標補正・合成nodeがある。postとfinalのIDを比較しない。
   対応GT endpointの(t,z,y,x)が厳密一致し、両stage内でその座標が一意な場合だけ
   「同じ位置の対応点」と記録する。それでも完全な物理cell identity/介入因果の証明ではない。
4. threshold後の候補graphは一sourceから3辺以上を含み得る。公式は最低edge IDの2辺へcapする。
   このgraphの存在被覆を公式TPと呼ばない。candidate coverage、採用graph、公式採点を分ける。

## 初回の出力

全GT edgeを一度ずつ記録し、各stage（pre candidate / ILP-selected / final CSV）の
実submitted→internal→GT写像と、両端対応・接続存在を保存する。
固定pre対応pairについて、両端不在/候補graphに接続無し/ILPでnodeまたはedge消失/
同じ接続保持を分類する。ILP-selected graphがpreのnode・座標・edgeの部分集合かを先に確認する。
postのGT対応pairがpreのものと違う場合はassignment changeとして別に記録し、
node削除・assignment変化・edge選択変化を混同しない。
post→finalは対応点の位置一致/曖昧性/接続遷移を記録し、ID由来の削除断定はしない。

この段階ではmatrix未読。候補に無い辺を「p=0」「p<0.48」と数値化しない。
後で該当packetを実際に読むときに、matrix軸・detector index・GT写像と確率/順位を照合する。
全dense被覆やseed別特徴の追加識別力も、このgraph-only診断だけでは証明しない。
全36収集の受入後、既露出eval12だけを物理診断し、既存D2 final TP/FNと別に突き合わせる。
eval24のGT読取/学習/新しい科学候補の採用・提出はこの実装単位には含めない。

## testsと受入

非連番ID・stageごとの別ID、同一座標の曖昧な複数node、edgeゼロでも座標一致するcase、
疎GTで未対応の余剰node、両娘のdivision、node/edge削除、ILP後assignment変化、
座標補正後finalに同じGT edgeが存在するcaseを合成testに含める。
GT辺の重複/欠落や部分集合違反は拒否。全stageの入力DataFrameは変更しない。
診断は公式スコア計算とは別物であることを出力schemaにも明示する。

## 実装受入 — 2026-09-08 12:46 UTC

`association_stage_diagnostic.py`を実装し、合成18 testsと既存D2/共通parityの合計90 testsが成功
（2.52秒、公式空edge警告2件）。Ruff/diffもPASS。import順と長い行のlint指摘3件は整理後再検証。
非empty graphでは新node対応がD2の公式対応と完全一致し、GT graph自体も不変更と確認した。
空edge/空node、異方性scale、非連番・2^53超ID、重複座標、division両娘、再対応、
post→final再採番/座標補正を検証。NPZ読出しは元edge ID順を復元し、無断の並べ替えで
公式outdegree capの優先辺を変えない。候補存在を公式TPとは呼ばない。

親が全source/testを自己レビュー。独立レビューなし。source SHA
`b434da10a023761f179ea0e0e8aeb18f4c666af5850b1d15b717a9cf4f8673ca`、test SHA
`3281041307eb82d86004175ed22448758e3a10270455fce6351e28fb520395a7`。
検証receiptは`outputs/local/e23_association_stage_diagnostic_20260908/PREPARATION.json`。
実competition GTは今回読まず、36収集のartifact受入後に既露出12の実診断へ進む。
matrix reader/候補の確率・順位照合/疎GT学習label/物理診断runnerは次の実装単位。
現行収集の15ファイルSHAは再検証して不変更。新しいKaggle実行・学習・提出・commit/pushなし。

## 次の単位 — packetの完全検証と固定GT対応pairのquery

matrix readerはread-onlyで、登録済みpacketのfile bytes/SHA、内部metadata、全array SHA/
dtype/shape、source/target軸・W2・scale/downsample・連続global detector indexを照合する。
returned detector座標を別入力とし、grid×downsampleが元座標へ厳密に戻ることを確認する。
単一packet最大1,000,000dense/各側2048node、展開NPZは32MiBまで。1packetずつ処理し、
全36matrixをRAMへ積まない。未取得・空pair・指定node不在は例外/明示状態であり、確率0ではない。

queryは実pre graphのdetector index→graph ID写像を使い、固定pre GT対応の2endpointが
packetのsource/targetに実在することを確認する。実mixed probabilityとpre候補の存在/確率が
threshold>0.48の条件と一致するか照合し、不一致なら原因統計へ混ぜず停止する。
target列内のsource順位はfloat32の同値をそのまま残し、最良順位/最悪順位の区間を報告する。
raw logitsは保存値を返すだけで、特にreverse logitを独立な親確率とは呼ばない。
他sourceが無い場合のbest-otherはnull。rankやprobabilityからGT負例や擬似labelを自動生成しない。
非正方行列/向きの取り違え/同値順位/欠損packet/改変/空pair/IDずれを合成testする。

### 実artifactでのreader確認（事前固定、2026-09-08 12:59 UTC）

合成29 tests/Ruff成功後、終了済み公開4 parity v1の各動画t=0→1を1packetずつ取得する。
選択はGTや確率を見ずに全4動画の先頭pairで固定。合計16,343,431bytes/882,357dense。
既存の受入済みmanifest SHA・returned/pre graph実artifactと照合し、全denseの閾値後
候補集合/確率一致、targetごとの最大/最小sourceのqueryとsource順位を確認する。
GTは読まない。これは読み出し器の実データ確認のみで精度評価ではない。
全396packetや収集中36動画のmatrix受入へ拡大解釈しない。現行Kaggleジョブは変更しない。

### Reader受入 — 2026-09-08 13:01 UTC

`src/biohub/association_packet_readout.py`を親が実装・自己レビューした。非連番/2^53超の
実graph ID、source列順位の同値区間、float32のstrict threshold、empty/missing、改変、
非正方transpose、軸正規化、座標復元、ZIP展開上限を含む合成29 tests成功（0.23秒）。
既存capture/observer/parity/collection/stage/D2と合わせ238 tests成功（4.14秒）、
公式empty graph警告2件のみ。Ruff/diff PASS。独立レビューなし。

固定した公開4先頭packetを実取得し、全882,357denseのarray/SHA/shape/dtypeを再読出し。
閾値後1,411候補の集合と保存確率が実pre graphに完全一致した。各targetの最大/最小sourceと
全candidateの3,070 queryについて確率/順位を別計算で照合した。結果は
`outputs/local/e23_association_packet_readout_20260908/PUBLIC4_T0_READOUT.json`、SHA
`ddca9ef57e8384c9273aa9b460cbe9e5ed607fab8135a4bed8020a26718caff3`。
検証scopeは公開4のt0のみ。GT、学習label、公式スコア、全36受入は未実施。
実データでreaderが動くことは確認できたが、接続を改善できるという科学仮説の支持ではない。

source SHA `7092a76a1b084fc068cfe41d839d27beb4153f99ff84f1c91d801e668a4a8cfb`、
test SHA `d15d423518664b23175506f81cb3459538b2a127c2504e49d055c9303b7dc967`。
同directoryの`PREPARATION.json`に関連testsとsource bindingsを記録。収集中の15ファイルは不変更。
次は収集終端の実artifact受入と、既露出12のみのstage/FN診断runnerを接続する。

## Stageとpacketの接続契約 — 2026-09-08 13:06 UTC、実GT診断前

1動画のstage診断出力を、実pre graph/node写像と再照合する。GT edge ID/endpointを保持し、
両端がpreに対応した辺だけについてframe別の必要packetリストを確率未読で作る。
対応不明は`UNMATCHED_ENDPOINT`で確率null。GT negative/TPを新たに判定しない。
対応済み辺はmanifestで束縛されたpacketを1個ずつ読み、source/targetの実ID・座標・
pre候補存在と確率を照合する。GT分裂の2娘はそれぞれ保持する。rankは各target列のsource順位。
planはdownload対象path/SHA/bytesを返すだけでネットワークを実行しない。
実読出し時の不足・改変・stageとgraphの不一致は例外で終了し、成功した一部だけを
完全診断として返さない。manifest/stage/pre/coordsを前後照合する。
合成stage→計画→実NPZ再読出しをend-to-endで検証する。競争用GTの新たな読取は
全36の実artifact受入後の既露出12に限定し、残り24はこの診断で使用しない。

### Stage/packet接続の合成受入 — 2026-09-08 13:09 UTC

`association_stage_readout.py`の`plan_queries`と`attach_packet_evidence`を親単独で実装。
実matching→stage診断→必要packet計画→NPZ読出しの合成end-to-endを確認した。
22新規caseを含む関連128 tests成功（3.32秒、公式空graph警告2件）、Ruff/diff PASS。
GT分裂の2娘・閾値未満の実確率・未対応null・2^53超の実ID・JSON roundtrip・
不足packet・manifest/座標/ID/候補不一致・入力途中改変・同frame一回読出しを検証。
自己レビューで、query後にpacketが変わる場合も最後のSHA再照合で拒否するよう追加した。
planningはmatrixを読まないため不足fileでも取得計画を返し、実readout時には不足を拒否する。

source SHA `760f8626029aeed73f21599544b88f70d0bef18a63ffc15dcfe8e489b950b4f9`、test SHA
`c53f148c81dc56b41febdba3dd69d785613b4cbe7f8b8e6048d151e66a7eefa6`。
`outputs/local/e23_association_stage_readout_20260908/PREPARATION.json`に検証結果を保存。
親が全source/testを自己レビュー、独立レビューなし。実competition GT診断・学習label生成は未実施。
collection36 v1は同slugのAPI RUNNINGで再確認、同listener17863を維持して再起動なし。
次の物理実行に必要なcollection artifact受入と、時間/RSS/outputを制限するrunnerは未完。
