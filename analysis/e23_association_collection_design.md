# D3 — 既露出36動画の接続情報収集

2026-09-08 12:15 UTC。親単独。公開4 OFF/ONの実artifact監査PASSを受けた次の実装契約。
目的は金メダルに向けた新接続モデルの設計に必要な原因情報を得ること。精度改善仮説の
採用/提出ではなく、既存E23を変更しない情報収集である。

## 固定入力と順序

- 公開4監査receipt SHA `a830c98c85be60b901ca101043340b8494008588d7398891608d2f193f344dab`。
  現地source22 files、共通24/観測8 NPZ、元E23座標/選択graphの一致を確認済み。
- raw36は `outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/unet_transformer_val/split_0`。
  36動画の名前/count/coordinate SHAは同reference directoryのdetector manifestから取得する。
  公開4が含まれる他shardの行は36参照として混ぜない。全36のGT graphは準備時に読まない。
- 最初の12はD2 RESULT SHA `2df2b4c2d4cb3aad978358c52b66a893de147b4428816448b2775e090753d767`
  に記録した既露出eval12のliteral set。2系統から各2本、名前順に4本×3group。
  残り24も各2本の4本×6group。各group内は名前順、全9groupを直列に実行する。
  全36が必要な範囲であり、最初の4/12だけで全量完了としない。
- Kaggle competitionのtrain画像を固定36だけのimage-only viewで参照する。
  sourceは画像とsplitだけを読む。GTを含むcompetition mountへのOSアクセスを遮断したと
  称さない。GT読み込み/採点はこの収集processでは禁止、後続の既露出12診断に分離する。

## 維持する計算と照合

公開4で通過したE23元source/14観測挿入/2checkpoint/環境変数/CFGをそのまま使う。
capture_moduleは件数可変の既存共通traceで、returned/pre/postとobserverを記録する。
公開4専用run_armのschema/4本guardを緩めず、collection用のrunnerと明示schemaを別実装する。
ONのみ、各groupはfresh process・共通seed23826・CUDA1台。公開4parityを全36同時OFF/ON実測と
読み替えず、全36それぞれについて旧E23座標SHA/count/選択raw semantic signatureの一致を要求。
不一致は参照を更新せずERRORとして保存。観測器のdtype/全matrix/ID/graph保存gateは不変更。

## 前向き予算

private/offline/T4、単一job、group3600秒、setup込み全体14400秒（4時間）、
child sampled tree/self RSS24GiB、開始空きdisk16GiB、全group合計収集出力12GiB。
writer累積1200秒およびobserver累積1200秒を全36合計でも維持する。
個別pair上限1,000,000・側2048node・全run450,000,000denseも維持。
既知全36は910,952 detectors/341,106,074dense、matrix+feature上限約7.29GB（ID等別）。
公開4 ON1194秒から画像本数比で約3時間、dense比でwriter約519秒が目安だが、
これは未測定36本の実時間/メモリ/圧縮率を保証しない。4時間で終わらなければERROR。
予算を事後に増やさず、自動再実行なし。失敗後のgroupは起動しない。
group終了時にprogress receiptを保存し、全9group/3564 pair完了でのみ全体COMPLETE。
run中の配信timeoutから終了を推定しない。終端receipt/log/小graphを先に取得し、
巨大matrix全量はローカルへ一括取得しない。

## 実装受入と後続

1. 前向き計画builderで全36の固定参照/3つの先行group/6つの後続group・source・SHAを束縛。
   合成testで重複/不足/別系統/不正countを拒否し、実rawを読み戻す統合testを行う。
2. fresh group runner/監督/診断専用notebookを実装し、起動前に自己レビュー・tests/lint。
   既存public4 notebook/receipt/sourceの再現性を壊さない。quota/private/dataを再確認して一度起動。
3. 全36取得後、まず既露出eval12の両端matching/全dense/threshold後/ILP後/最終CSVを比較。
   205件の接続なしFNの発生stageを実際のmatchingで分類し、IDを跨いで流用しない。
4. seed別追加識別力と疎GTの確定正負/ignoreを確認してから学習条件/Loss監視/採否gateを固定。
   改善候補を公式評価し、必要な提出へ進む。公開4 parity自体は改善候補ではなく提出しない。

この契約時点で収集job未起動、学習なし、Loss/LB更新なし。E23 0.924、E26不採用、E17 HOLDを維持。

## 参照準備の実装結果

`scripts/prepare_e23_association_collection.py`を実装。監査済みpublic4証拠のSHAを再確認し、
既露出36のraw1,188 files/10,090,215bytesをread-onlyで読み、選択graph署名を束縛した。
4本×9groupは各系統2本、最初の3groupはD2診断済み12と完全一致する。
最大group06は67,524,955denseで、public4の75,120,102denseより小さい。ただし実時間の保証ではない。
`outputs/local/e23_association_collection_20260908/REFERENCE_PLAN.json`は123,442bytes、SHA
`08395ca8615b6eeaaaeec521cd937c62d2212b7a20cf18be1a27478afd4af7ac`。再生成との完全一致を確認。
source SHA `85888777b1a0381988c456700a3ff6aea884a6ebd061ff5505c6847b969db8f0`、
test SHA `40df2e16d0db4cc4c2f5204f99fa12a591636b298cb225a255499bd7e222480c`。

親の全source/test自己レビュー、新規準備testと既存association6 modulesの計102 tests/2.43秒、
Ruff/diff check PASS。初回lintのzip strict指定漏れ2件はstrict=Trueを明示して再検証した。
GT graph/画像/モデルを読まず、runtime/public4 notebookは不変更。
準備物のJSON表示がtool出力上限で切れた一回は保存せず、compact JSONで取得し再照合した。
次の未完了はcollection group runner/全体監督/notebook。その実装受入後にquota等を確認し起動する。
この時点のstatusは`REFERENCES_PREPARED_NOT_DISPATCHED`で、収集/学習/提出完了ではない。

## 2026-09-08 12:33 UTC — runtime実装と起動前受入

前回turnは公開4実artifact監査と固定36参照builderの実装でprogress。
今回、collection group runner・9group直列監督・10cell診断専用notebookを別ファイルで実装した。
元の6 runtime payload/sourceとpublic4 notebookは不変更。現地で25 Python全件を
公開4で確認した22件（payload配置名だけ変更）+今回追加3件の固定SHAへ照合する。
group schemaはpublic4 schemaとは別で、毎回固定reference SHAからliteral4動画を照合する。
GT無しimage-only view、splitのtrain空/指定4本のみ、前後の画像/重み/source SHA、座標/選択raw
一致、全396pair/12traceを要求。公開4と依存versionが違う場合も後続を起動しない。

group停止・timeout・RSS/出力超過・master改変・累積観測時間超過・RESULT欠損・依存差、
runnerのsource/画像改変と保存失敗を合成fixtureで検証。関連139 tests/3.51秒、Ruff/diff PASS。
全新source/testと生成手順を親が自己レビュー。独立レビューなし。初回lintの行長1件を改行で修正。
累積writer/observer1200秒はgroup終了境界で判定（各group内は既存同期call境界1200秒）。
全run出力12GiBは実行中1秒samplingと最終manifest生成前に検査。硬い瞬間上限とは称さない。

生成notebook318,181bytes SHA `42454b149e20e7cf2cb493cb9f771266fc998e0b0272bf2481c013049ce64d8e`、
metadata617bytes SHA `ca48f4c2225d0713a275c802692cf7afe09ba1f40d8d7daceb4c8daa9a840326`、
PREPARATION5169bytes SHA `d1882e1d5e3ddc8926b52a7d4daa16c72cda811b46e2ef66dac04713121f92af`。
再構築は3ファイル全内容一致。全cell未実行、credential-like pattern無しを確認した。
コンペ参加済み、GPU残28.02h、同名所有slug未発見。3pack metadataの`info.licenses`はCC0-1.0。
同じ既存asset利用であり、E17別assetのHOLDは解除しない。前回確認したcompetition rules条件を維持。
`outputs/local/e23_association_collection_20260908/PREFLIGHT.json`へ15ファイルSHAと検証結果を保存。
親がprivate/offline/T4、timeout14400秒、単一jobの一回起動を決定。推論採取だけで、提出なし。
受付応答が不確かなら同じslug/versionを確認し、二重pushを行わない。

12:33:38 UTC、初回pushは **kernelId133552379/version1** を受付、exec23763 exit0。
slug `taichiiiii/biohub-e23-association-collection36` はAPI RUNNING。DISPATCH receiptを保存。
current sourceを読み戻し、全10cellのtype/text完全一致とprivate/offline/T4/3pack/competitionを確認。
明示版取得ではないことを区別してREMOTE_READBACKへ記録。Docker digestはpublic4と同じ。
起動成功は全36完了や精度改善の証拠ではない。再起動/再push/コンペ提出なし。
12GiBは収集root全体の予算で、setup/重みmaterialization/画像viewのKaggle保存処理とは
区別する。最終output一覧の実容量も確認する。

続くlive logで36画像パスの存在、support13/primary/DeepCenterのSHA一致を確認。
secondary準備とgroup00開始はまだ未確認。API RUNNING、同jobのlistenerはexec17863。
`LIVE_SETUP_WATCH.json`へ記録。CLI text streamの個別イベント時刻は未取得で、推論時間を推定しない。

12:46 UTC追記: 同じlive logにsecondary SHA一致、Tesla T4、master seal
`7ae5c6786dc53fa807093346cafecc232bf229ddbb8b378f9632cc7a219c9840` と
`D3 COLLECTION_STARTED group00 PID 78`を確認。API RUNNING、source15 filesも不変更。
`WATCH_GROUP00_STARTED.json`へ保存。group完了/全36完了は未確認、同job/listenerを追跡する。

13:01 UTC追記: 同listener17863で`D3 COLLECTION_FINISHED group00 exit=0`と
`D3 COLLECTION_STARTED group01 PID 122`を取得。同slug APIはRUNNING。
`WATCH_GROUP01_STARTED.json`へ保存。4動画分のprocess終了は確認したが、group artifactの
親による取得・受入はまだ。全36完了とは呼ばない。ログの一時再接続はjob停止ではなく、
再push/restartしなかった。現行15 source/test/notebookのbytes/SHAは再照合して不変更。

## 終端後の親による実artifact受入（2026-09-08 13:11 UTC、結果受取前）

実行側の完了manifestに加え、ダウンロードしたreturned/pre/postとobserver pre/postの
1動画5 NPZを確認する。共通traceとobserverの全graph列が並べ替え後にdtype/値まで一致し、
detector index→実graph ID→座標が全nodeで全単射、returned候補の確率/距離がpre graphと一致、
postのnode座標/edge確率/距離がpreの部分集合、post semantic signatureが固定旧E23参照と
一致することを求める。396pair/groupの全coverage、整数count、dtype/shape、軸、hash、
empty状態、合計bytes/denseを別検証する。

ここではmatrix本体を全量downloadしない。全matrix保存時のroundtrip/SHAはKaggle実行側で
行った処理であり、親のローカル検証は全manifest＋実graphであることを明記する。
必要packetを後で読む時はreaderが実arrayを検証する。core checkerを合成異常系と
終了済み公開4の実graph/manifestで先に検証し、全36受入とは呼ばない。
全36の受入にはさらにmaster/result/process/log/source25本/参照/依存/budgetの整合と
9groupの完全性が必要で、core単体PASSでGT診断を開始しない。

### Core受入 — 2026-09-08 13:17 UTC

`association_artifact_audit.py`を親単独で実装し、33新規合成test、関連133 tests成功（4.88秒）。
Ruff/diff PASS。最初のfixtureはwriterのメモリ内tupleを渡してJSONのlistと不一致になったため、
fixtureを実保存manifestの読出しへ修正した。実データの条件は緩和していない。
node/edge重複、座標・確率・距離・参照の改変、ILP部分集合違反、欠損pair、軸/型/empty不一致を拒否。
続いて終了済み公開4の実20 NPZと396 manifest recordを新coreで読出し、PASS（0.523秒）。
`outputs/local/e23_association_artifact_audit_20260908/PUBLIC4_CORE_AUDIT.json`、SHA
`a7e3d6f57247ffe019ab32e3b2178d41f215527d900273958bffc1256e266e44`。
新source SHA `b0a8f1abf426d546448da90abcd3e49cfe6ef303cba8a1350139cf6e96dd7301`、test SHA
`32b953cf1274968c87f6e68678e8ea32f183edbd5f3e5b5effd37b2cdc1e1306`。
自己レビューのみ、独立レビューなし。実36 collection受入、GT読取、新学習・提出はまだ。

同job API RUNNING。旧listener17863が再接続後exit0となったため、APIを確認して
同slugへのログ購読だけを新session76565へ接続。replayでgroup01 exit0とgroup02/PID166開始を確認。
8動画のprocess正常終了を確認したが、actual collection artifactsの受入は未実施。
`WATCH_GROUP02_STARTED.json`に保存。現行15 files不変更、Kaggle再push/restartなし。

### 全collection検証器 — 2026-09-08 13:37 UTC

association_collection_audit.pyを実装。固定参照/master、25 runtime Pythonの実bytes、
9group plan/split/result/process/progress、画像inventoryの対象範囲、依存/予算、
36動画×5実graph/returned NPZ、3,564pair manifest、終了logと実output inventoryを照合する。
期待値は出力treeから自己採取せず、固定local preparationと観測済みmaster sealから渡す。
matrix本体のローカル全再読出しは行わず、別のpacket readerと区別する。
合成9group/36動画/3,564tiny packet/180graph NPZのend-to-endを含む新18 testsを実装し、
関連157 tests成功（8.29秒）、Ruff/diff PASS。fixtureへの画像inventory配置ミスと
unused import lintは修正・再実行済み。Kaggle実行側の15 filesは不変更。
自己レビューのみ、独立レビューなし。実collectionの完了/受入はまだ。

source SHA 45483b728a0b933a2409294fce286f90111d7078b0a721d93fc4e0da5829b651、
test SHA 500e91ffa7bbe6c2a423e48bf7c93022c7653b9733c29c6fdbf2d20d5ff895f4。
outputs/local/e23_association_collection_audit_20260908/PREPARATION.jsonへ保存。

#### 実API probeで見つかった取得側の注意

終了済み公開4でkernels_list_filesの先頭2件はbasenameのみで、サイズ933/899を返したが、
同じsession_outputの実GETはPARITY_RESULT.json 773bytes、off.log 13154bytesだった。
前者の実GET SHAは既存sealedコピーと一致し、既存実artifactが変わった証拠ではない。
list-filesサイズを受入条件に使うと偽の欠損判定になるため使用しない。
HEADは2件とも404で原因未確定。一方GET Range bytes=0-0は206、Content-Range
bytes 0-0/773、本文1byteで実サイズを取得できた。
session_outputはfull pathを返すがsize無し。logはfilesとは別fieldで、CLIが独立ファイルに保存する。
したがって全ページのfull path列挙＋有限のHTTP Rangeでの実サイズ取得、別途log SHA保存を
受入前に実装する。signed URLは記録/表示しない。probe詳細は同directoryのOUTPUT_API_PROBE.json。
この取得部分と固定期待値のCLI接続は未完。

13:33 UTCのlive logでgroup02 exit0→group03/PID210を確認、API RUNNING。
先行12動画のprocessは終了したが、実artifact未取得なので12診断は開始していない。
WATCH_GROUP03_STARTED.jsonへ記録。listener76565を継続、再push/restart/提出なし。
