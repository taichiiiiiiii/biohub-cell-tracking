# E28: 既存32D画像特徴によるmotion cost補正

2026-09-13、Issue #10。設計レビュー済み、pure helperとmotion optional経路を実装中。
実特徴入力との統合・特徴値の成績集計・CV評価は未実施。
canonicalの codex/issue-10-e28-appearance-cost で既存WIPを引き継ぐ。別checkoutは作らない。

## 一つの仮説

E23の幾何・既存selected-edge確率に、既存dual-seed UNet特徴の外観不一致penaltyを
加えると、検出済み細胞の接続誤りを減らせる。E27の未選択prior追加とは合成しない。
新モデル・学習・重み更新・半径拡張・閾値探索・検出変更・分裂規則変更はしない。
同じfused確率の再閾値化やforward/reverse混合係数の再探索ではない。
ただし特徴は同じ上流モデル由来であり、統計的独立情報や改善を事前に保証しない。

## 実装する前に確定する意味

受入済みE23 observer_off.pyでは、各W=2画像windowのUNet出力に_index_featuresを適用し、
source/targetの32D特徴を取り、そのままpredict_edgesへ渡す（589–601、663–674行）。
observerはdetach/CPU/copyで保存し、32D/float32/finiteを検証する。座標/時間特徴や
Transformer後のembeddingではない。primary/secondaryは別seedなのでvector同士を
seed横断で直接平均/内積しない。同じnodeでも隣接windowが異なる特徴を使い回さない。
既知12、groups00–02、1188pairのみ。pre graphのdetector_indices→graph_node_idsから
post/raw IDへ結合し、原座標・時刻・実raw signatureを照合する。refined centroid位置へ
特徴を取り直したことにはしない。欠損/重複/向き違い/不一致は失敗で、0埋めしない。

## 凍結する変更

各pair t→t+1、各seed内でsource/target特徴をfloat64へ変換しL2正規化する。
norm=0または非有限なら当該実験を技術失敗とし、係数変更や都合のよいpair除外はしない。
cosineの計算値が[-1,1]を1e-12超えて逸脱すれば失敗。許容丸め誤差だけclipする。

    appearance = ((1 - cosine_primary) + (1 - cosine_secondary)) / 2
    candidate_cost = E23_motion_cost + 1.0 * appearance

E23_motion_costはmotion_dist単体ではなく、motion_dist + 0.05*raw_dist −
learned_bonus*selected_probの最終assignment cost。加算先は有限なallowed cellだけ。
motion_dist/raw_distや既存出力telemetryの意味を書き換えない。

appearanceは[0,2]、係数1.0は既存costの距離単位に合わせた固定um係数で、再調整しない。
既存raw距離gateで許可された全pairへ同じ規則を適用。candidate集合/順序/big sentinel/
tight→relaxed/Hungarian/velocity/既存selected priorはE23と同じ。E27の追加priorは使わない。
ゼロpenaltyの合成条件では元assignmentを維持し、Noneでは実baseline CSV byte一致を要求。
新しい任意係数API/環境変数/複数variantは追加しない。

## 最小の接続と検証

既存read_packetのfile/array hash、shape、axis、座標検証を再利用し、1packetずつ読む。
特徴は1動画分だけ保持し、frame/seed/sideの区別とraw ID順を保持する。全100M dense cost
を永続保存しない。入力featureのarray hash/正規化仕様と使用IDのreceiptを保存する。
アプリ実装と直接テストはFlash、親は設計/選択適用/検証。元E27は完了済みなので再開せず、
影響する既存WIP sourceは変更前にhash付き保存する。official/は不変更。

必要な合成検証: 同一/逆向き/直交vectorのpenalty、seed平均の順序、ゼロnorm/NaN/欠損/
ID転置/window取り違え拒否、許可pairだけのcost変更、幾何不許可pair不変、tight/relaxedと
velocity履歴の維持、None/ゼロpenaltyの対照同値。架空GTや画像で精度改善とは主張しない。
別descriptorをE17 rankerの22特徴へ偽装しない。E17のHOLDは解除しない。

## 物理評価と採否

E23の既存入力/重み/config/seed0/threads1/CPU/動画順を固定し、None対照を先にbyte再現。
対照と候補は新source/入力/feature/依存/output/予算を具体的receiptに登録して直列生成。
予算は各known12 arm1800秒・子self peak RSS8GiB・親子出力256MiB。特徴検証を含める。
上限超過を自動延長しない。常時OS RAM制限やhidden全体runtime保証とは呼ばない。
新候補IDはE28_APPEARANCE_COST_V1。eval12→eval24→eval36の順、公式metricと
analysis/e26_scoring_contract.md・既存_GATE_THRESHOLDSをそのまま継承する。
eval12 mean +0.005等のAND gate不合格なら残り24GTを開かず棄却。追跡/リーク/再現性/
CPU/形式/来歴、必要MAX評価を通るまで科学採用しない。既知12/36を独立holdoutと呼ばない。
actual deploymentで同じW2/seed特徴を追加モデルpassなしで得る経路と予算も採用前に証明する。
Kaggle実行・提出は別途登録と既存明示権限/検証条件に従う。5受理で停止、現在0/5。

## 中止・解釈

これは既存画像特徴に実用的な識別力があるかの一回の候補実験。値を見て係数/seed/距離を
選び直さない。特徴同士の比較がsource意味上成立しない場合は実装せず設計を棄却する。
不採用結果も台帳へ記録し、基盤修正やzero-norm等の技術失敗を有効CV失敗数に混ぜない。
新しい学習はないためLoss下降の報告対象はない。成功は機能testではなくGoalの全条件。

## 独立レビュー（2026-09-13、実装前）

Sol/high e28_design_review: 条件付きADOPT-DESIGN、意味上のshowstopperなし。
metric-learning保証はないが同seed/同window内のchannel basisは共通であり、固定一回の
検証仮説として受理。上記のcost定義を明示し、全motion対象IDの一意なdetector対応を必須化。
固定gateは変更しないが、score改善がdivisionやnode調整だけなら「接続誤りが減った」と
機序主張しない。公式edge TP/FP/FNとdivisionを分けて報告する。
親はこの条件で設計を採用。helper合成検証→統合→None byte parity→候補生成の順とし、
この設計採用だけで実データ候補実行や科学採用を許可しない。

## motion接続の固定契約（2026-09-13、実装前）

motion_relink_edgesのkeyword-only appearance_frames=Noneだけを追加する。
non-Noneはactiveなt→t+1のexact dict。各frameはt_source/t_target、source_ids/target_ids、
primary_source_features/primary_target_features/secondary_source_features/secondary_target_featuresの
8key。IDはbuiltin intの一意listで、motionのsorted全frame IDと順序まで一致する。
frame別32D特徴から全frame penaltyを1回計算し、tight/relaxedの部分集合はそのID indexで参照。
距離gateを通ったcellのcostだけに加算する。raw/motion距離・prior・edge telemetryは不変更。
frames欠損/余分/時刻違い/ID順序違い/row数不一致は失敗。appearance指定時にmotion無効や
large-frame fallbackが起きれば候補を失敗にする。Noneの従来fallbackはそのまま残す。

graph_opsの変更前内容はGit HEAD7368cebe2d445e7eb6d0492133fdfb9aed9e51f7内に保全済み。
変更前fileとGit blobがともに1ef40f3abb3c2a642513be123f7f241ccf400d08で一致することを確認済み。
既存pipelineのWIPはこの単位では変更しない。新しいpartial packet readerは作らず、
次のloaderは既存read_packetによる1packetずつの全検証を再利用する。

開発レビュー補足: nodes={}かつappearance_frames={}はactive transitionが無いため空結果を
許す現実装。独立レビューはエラー文との不一致を指摘した。これは実動画候補の受入を意味せず、
候補loader/runnerでは空動画を受入不可とする必要がある。非空framesでnodeなしは既に拒否。
この境界とloaderの実装検証が済むまでは候補生成に採用しない。

## 1動画loader契約（2026-09-13、値を読む前）

新module appearance_inputs.load_appearance_frames(root,group,dataset,bindings,raw_nodes)は
framesとreceiptを返す。bindingsは固定SHAの既存受入auditから親runnerが渡す値で、任意の
未検証manifestを信頼起点にしない。group00–02/known12の範囲は固定referenceでrunnerが確認。
loaderはreturned/pre/observer manifest/pair manifestのbytes+SHAを既存Readerで照合し、
observerからpair manifestへのSHAも照合。99packetの時刻・frame_countsを確認してから、
既存read_packetで1packetずつ全検証する。GTや学習/モデル/追加priorは読まない。
detector_lookupでraw全nodeのbuiltin IDと元t/z/y/xを一意照合する。rawはpreの部分集合を許すが、
未対応・座標違い・空rawは禁止。packet側detector indexからrawのsorted frame IDsへ特徴行を
取り出し、primary/secondary/source/targetと各W2 windowを保持。行並べ替え後もfloat32。
active transitionだけframeを保持。非activepacketも検証するが特徴やdense matrixを保持しない。
receiptは検証済みfile bindings、原feature array signatures、再配列後feature signaturesとIDを
記録する。返却前にReader.recheckとpacket file bytes/SHA再照合。実行時間/RSS/output上限は
後続の既存型supervisorが担い、Readerの300秒guardも維持する。
本APIだけではraw/GT/モデル全体のprovenanceやCV採用を証明せず、既存prepare_inputsの
post/raw signature検証を前提にrunnerで統合する。pipelineはraw読込直後・centroid補正前に
1動画loaderを呼び、motionまで特徴だけを渡す。None時は既存呼出形を保つ。

pipeline接続API: run_postproc_coreにappearance_loader=Noneを追加。指定時はmotion有効・
dataset stem一意・association_priors_by_dataset未指定を出力作成前に確認。raw読込直後の
scalar node dictのコピーをcallback(dataset,raw_nodes_copy)へ渡す。callbackは非空frames dictを
返し、receipt保存はrunner側closureが担う。filter_output_graph/pre_linefitはappearance_frames
optionalをmotionまで渡す。指定時のNone/空返却やE27 prior同時指定はエラーで、silentfallback
しない。None時は既存関数に新keywordも渡さず、旧mock/呼出契約を維持する。1動画のfilter終了
直後に特徴参照を解放し、次動画を読む間に前動画特徴を残さない。CSVwriter/動画順は不変更。
変更前pipeline WIPはoutputs/local/e28_appearance_20260913/pipeline_before_appearance.pyへ
同bytesで保全しcmp一致。SHA256 db4c47aa14f02daee374ea0682996d5fc6e6a7dbf981f25eca1ed1df91f7cd9c。

## 実行記録・監視の統合設計（2026-09-13、実候補未実行）

独立Sol/highレビューを踏まえ、新wrapper/別supervisorは作らず既存
scripts/e27_association_prior_screen.pyにe28_none/e28_appearanceを明示追加する。
旧E27 3modeのschema/status/prior receiptと挙動は維持。候補IDはE28_APPEARANCE_COST_V1、
E28 CONTROLはE28_GENERATION_CONTROL_V1。E28は両armともassociation_priors=None。
既存のmode!=baseline_none条件を流用せず、prior構築/再照合はselected_only/recorded_prior
だけに限定する。e28_noneはcallback keywordすら渡さず、reference CSV bytes/SHA一致必須。
差分許可はrecorded_prior/e28_appearanceだけとし、その他のparity条件を弱めない。

親判断: prepare_inputsの返却契約をgroup追加だけのために拡張しない。E28 helperが既存
_load(REFERENCE,REFERENCE_SHA)/_load(AUDIT,AUDIT_SHA)を再利用してfixed known12所属と
bindingsを得る。GT/stage JSONは使わない。callbackはSTEMS順1動画ずつ、framesだけ返し、
receiptだけを別listへ保持する。終了時に12動画・一意順序・group・99packet・flags=false・
各103fileの正確なmembership/bytes/SHAを照合し、全1188packetと動画別metadata照合48件
（共有manifest重複を含む、unique metadataは30file）を再束縛。
FEATURE_RECEIPTS.jsonをexclusive writeしてRESULTのbindingへ含め、CONTROLは後書きしない。
e28_noneではfeature receipt/artifactの存在を拒否する。CONTROLには固定audit/reference/
group所属・係数1.0・source/raw/config/dependency・予算を先に記録する。

source closureは全src/biohub Pythonと当該runnerにE28設計ファイルを追加して凍結。
子/親のstatusはE28専用で、候補生成をUNSCOREDと明示し、E27成功や提出許可を装わない。
既存supervisorの単回launch・process-group cleanup・1800秒・8GiB child self-RSS・親子合計
256MiBを維持。Noneと候補は別々に親が直列起動し、自動2arm runnerは追加しない。
必須検証: 旧mode不変、E28 prior混入拒否、None parity失敗、候補差分許可、12receiptの欠損/
重複/改変・file drift拒否、supervisor argv/status/source/artifact照合。実行前MAX評価を行う。

execute_baseline_coreのoptional appearance_loaderを先行追加し、その後E28 modeへ接続。
既存runner WIPはoutputs/local/e28_appearance_20260913/e27_screen_before_appearance.pyへ
同bytesで保全済み、SHA49a9d8ad4d3d67c1ba6d26a046075aff04857e909422a70048affe2990e2cfd9。
E28 mode/FEATURE_RECEIPTS/supervisor/CLIを実装し、新mode専用の親子合成テスト17件を
含む関連97件が成功。終了時のplan/receipt検証と親RESULT書込も時間予算へ含め、時間超過で
子/親successを失効させる。合成テストを実CSV parityや科学改善の証拠にしない。候補の物理実行前に
E28公式採点への接続と実行前MAX評価を完了する。

None対照だけは、採点接続前に固定reference CSVのbytes/SHA完全一致を終端条件として
先行実行できる。MAXのNone実行準備評価を経て親が判断した限定的な順序変更で、候補生成・
採点・採用・提出のgateは変更しない。終端はNOT_CANDIDATEで科学的未改善件数に数えない。
None成功後は同じgeneration source closureを候補まで維持し、途中で生成sourceや本設計を
変える場合は古い対照を同一sourceの証拠として再利用しない。進捗追記はclosure外の台帳へ行う。

計画helperはprepare_appearance_plan、終端検証helperはverify_appearance_receiptsを同runnerへ
追加する。CONTROL用planはJSON往復で形が変わらないよう、各動画のoriginal_signaturesを
時刻順99要素のlistとする。OBSERVEDは4feature signatures、SKIPPED_EMPTYはNoneだが、
後者も座標signatureを持つ元recordとfile bindingを保持する。片側のみ空も有効なempty。
feature receiptのactive timesは一意昇順、original signaturesはplanと一致、mapped signatureの
dtype/shape/hash形式とside別ID件数を照合。終端時にfixed plan再構築と全file再hashを行う。
この検証だけで特徴変換を独立再計算したことにはせず、実loader・source binding・再現実行と
組み合わせる。receipt検証だけで特徴配列の独立再計算を証明したとは主張しない。

## 公式採点への接続方針（2026-09-13、GT追加読取前）

現E27 scorerのcandidate_id/arm/prior schemaをE28成果物に偽装しない。
scripts/e27_prior_score_v2.pyのread_generation_receiptsはexperiment非依存のpath・hash・
親子/log binding確認として再利用できるが、verify_generation/verify_plan/score_eval12_core
以降はE27 arm/prior/事前登録に依存する。E28用の小さな採点adapterでidentity検証だけ分け、
新しい監視frameworkやmetric/gateの複製・新規定義は避ける。

E28 generation検証では既存のCSV/bounds/raw統計/source/親子終了状態検証を維持し、
e28_none/e28_appearance専用status、candidate_id、CONTROL schema、priors=None、
同一appearance_planとFEATURE_RECEIPTSの実bindingを照合する。Noneはreference bytes/SHA
一致必須。両armのconfig/dependency/raw/input/metadata/sourceが同一であることを採点前に
照合する。生成前に固定するplanにknown12所属、GT stageとbindings、出力先、sourceと
基準値を含め、候補結果を見てから基準を追加しない。

採点本体は既存verify_import_environment、e26_screen._check_stage_gt("eval12",...)、
biohub.evaluate.score_submission(max_distance=7.0)、_score_arm_record、
_normalized_official_summary、_paired_score_recordを再利用する。最後のgate識別子のみ
E28にし、rule_implementation_candidate_idは保持。数式/閾値/lineage集計を変更しない。
eval12 gateを満たすまで追加24GTを開かない。実行時間・出力上限・採点前後のbinding
再検証を維持し、既存score child/parentの再利用可能範囲を実装前に具体化する。
この節は接続方針であり、採点adapterの実装完了や採点実行許可の証拠ではない。

接続実装の現在地: scripts/e28_score.pyにverify_generation(output,arm,expected_sources,
expected_appearance_plan,check_budget)とscore_eval12_core(checked_plan,candidate,output,
check_budget)を追加。前者はE27 generic read_generation_receiptsを再利用し、E28 identity/
feature receipt照合と既存CSV/bounds/raw統計検証を行う。返却はdocs、csv_report、JSON型の
shapes、output。後者は公式score_submissionと既存E26 gate集計をそのまま使い、E28の
CONTROL/appearance_plan/prior=Noneの一致を先に検査する。双方budget callbackは引数なし。

注意: g._binding_for_pathはpath/bytes/sha256の3field。appearance入力Reader.bindingsの
bytes/sha256の2fieldとは別契約。CONTROLにはappearance_plan、RESULT/SUPERVISORには
feature_receipts_bindingがあり、後からCONTROLへfeature receipt bindingを書き足さない。

新adapterの合成11testは生成記録/実file bindingを使う照合7caseと、既存集計/gateを使う
採点core4case。CSV/GT本体をstubにするため、実CSV意味やCV精度を証明しない。
verify_planも追加済み。E28_EVAL12_PLAN_V1の固定keyset、source closure、baseline receipt、
appearance plan、legacy public/private SHA、known12だけのGT/image inventory、各事後bindingを
照合する。check_budget省略/非callableは拒否する。9合成testを含め採点側20件成功。
legacy SHAを合成fixtureで置換するtestはproduction anchorの証明ではない。
未実装: PREGEN記録と候補生成の結合、verify_score_core、CPU score child、
親supervisor/CLI。既存E27のこれらはschema/mode/candidate/priorを固定しているため、そのまま
呼べない。global monkeypatchやE27への偽装は行わず、固定legacy input/GT bindingsと
環境/タイマー/終了状態/事後再検証を残す最小の明示接続を実装する。実行前にscore_sourcesへ
新adapterと実際にimportするE27 reader/environment/公式metric closureを含める。

## 残る採点実行の共有境界（2026-09-13、設計のみ）

約650行のpost-verifier/child/supervisorをE28へ複製しない。MAXの条件付き設計承認を受け、
既存scripts/e27_prior_score_v2.pyのverify_score_core/run_score_child/supervise_scoreに
keyword-only experiment="e27"を追加する方針。exact strのe27/e28だけをIO前に受け入れ、
固定の内部label表・CLI module・candidate IDを選ぶ。PLANから実行先やschemaを推測しない。
E28のplan/generation/coreはscripts/e28_score.pyへ明示分岐し、必要なbudget callbackを渡す。
E27既定の呼出形・record key/label・数学・予算・環境・cleanupは不変更。
任意callback registry、動的plugin、global monkeypatch、汎用frameworkは作らない。

| 用途 | E27既定 | E28明示選択 |
| --- | --- | --- |
| candidate | E27_RECORDED_PRIOR_V1 | E28_APPEARANCE_COST_V1 |
| candidate arm | recorded_prior | e28_appearance |
| child module | scripts.e27_prior_score_v2 | scripts.e28_score |
| PREGEN | E27_PREGEN_PLAN_VERIFIED_V1 | E28_PREGEN_PLAN_VERIFIED_V1 |
| SCORE_STARTED | E27_SCORE_STARTED_V2 | E28_SCORE_STARTED_V1 |
| SCORE_RESULT | E27_SCORE_RESULT_V1 | E28_SCORE_RESULT_V1 |
| SCORE_ERROR | E27_SCORE_ERROR_V1 | E28_SCORE_ERROR_V1 |
| SUPERVISOR | E27_SCORE_SUPERVISOR_V1 | E28_SCORE_SUPERVISOR_V1 |
| SUPERVISOR_ERROR | E27_SCORE_SUPERVISOR_ERROR_V1 | E28_SCORE_SUPERVISOR_ERROR_V1 |

共有post-verifierも同じe26._score_arm_record/_paired_score_recordを使い、candidate識別子だけ
適応する。現在のE28 core testで同じgate構造を確認済みで、E28固有の数学的な分岐は不要。
明示的な署名分岐、未知experimentの無副作用拒否、旧label不変、E28 child CLI/argv/envと
再束縛、事後検証がscore/GT semanticsを繰り返さないことをテストしてから実行へ進む。
登録生成run_registered_generationはこの共有化の対象外。E28 PREGENとSTARTEDの時間順序・
plan固定・物理前後検証は別途接続し、未完了のまま候補を生成しない。
