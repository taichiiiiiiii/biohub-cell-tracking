# D3実Kaggle観測parity — 前向き契約

2026-09-08。親単独。前回D3観測器実装/合成保存probeはprogressだが、実E23とのparityは未確認。
金メダルへの次の一因子実験に必要な、seed別接続情報を収集するための診断である。
E23を変更/提出する科学候補ではなく、E17のsource HOLDを解除する操作でもない。

## 起動前に発見した計測器の設定欠陥

E23 notebook cell9の実効値はsecondary edge weight **0.15**、detection weight **0.475**、
low-margin max **0.35**、threshold **0.48**。保存E23とraw36の実行ログも同じ値。
前回観測器でthreshold0.10をE23と呼んだのは親の誤り。前回130テスト/負荷probeはその合成
契約の実測として保持するが、E23対応の証拠にはしない。まだ実Kaggleの起動はしていない。
元の観測器/testは`outputs/local/e23_association_observer_d3_20260908/source_before_config_fix/`
へbyte一致snapshotを保存。今回thresholdのみ0.48へ修正し、0.10拒否を回帰に追加する。
推論本体の設定・重み・元notebook・D2/E26の証拠は一切変更しない。

## 測定する差

- 同じE23 source/2モデル、公開4動画のみ、全100frame、同じCUDA device、OFF→ONの直列2process。
- OFFは前向き再構成sourceそのまま、ONは14箇所の観測挿入だけ。
  CLI bridgeは両arm共通で、通常predict_videoの戻り座標/全辺、build_graph後、save_graph直前の
  選択graphを小さなNPZへ記録する。モデル呼出し・乱数・値の変更はしない。
- ONだけ明示AssociationObserverを渡し、完走後finishする。CLIからのevaluateは拒否。
  GT/学習/CSV後処理/提出なし。公開4はダミー/in-sampleで、汎化精度を測るものではない。
- 4本の実detector countと座標SHAをE23保存manifestに照合し、戻りcoords/edge行順/値と
  graphの全列をOFF/ONで完全一致比較。元参照rawの選択graphにも別に照合する。
  複数process/旧run間のGPU非決定性による不一致もPASSへ読み替えず保存して診断する。

## 固定予算と停止

private/offline/T4、科学値不変更。各arm wall3600秒、診断全体8400秒、peak child RSS24GiB、
各arm出力12GiB、作業空きdisk開始時16GiB以上。観測writer1200秒/12GiBの上限も維持。
timeout/error/source・weight・入力・候補・dtype・座標・graph不一致はERROR/NO_SUBMITで停止。
既存runへ上書き/再開せず、自動retryしない。上限を実測後に緩めない。
巨大NPZ全量のローカル取得はせず、まずreceipt/log/差分要約だけを読む。

## 実装・起動条件

1. 元notebookのconfig/guard/setup/integrity/source patchを使い、推論起動部分だけ共通bridgeへ。
   E23原本を編集せず、新private診断notebookを作る。runtime全source/weights/入力をbindする。
2. bridge/比較器を合成module/graphで検証し、実supportをローカルimportしない。
   sourceに元の全計算文が残ること、kwargs伝播、4動画完備、OFF/ON間で入力/source不変を確認。
3. 親が全差分を自己レビュー、必要tests/lint成功、rules/asset license/quotaをread-only確認。
4. 親がsource/asset/planのSHAを記録後、一度だけprivate Kaggle kernelを起動する。
   起動した事実をparity成功としない。全36収集はpublic4完了結果を見て別に判断する。

提出は行わない。これは同じE23の計測器診断で、ユーザーの「ループごと提出」における
新しい科学的改善仮説ループではない。採用済みE23 LB0.924を維持する。

## 2026-09-08 11:14 UTC 起動前受入

親の自己レビューと関連151 tests/2.60秒、Ruff、diff checkが成功した。公式空graphの警告2件。
準備物を再構築し、元notebook/参照/6 runtime sourceを含む144 bindingsと、保存済み
notebook・metadata・PREPARATIONの全内容が一致した。タイトル修正後のlintの行長違反も
改行のみで訂正し、再検証済み。実推論sourceや計算条件の変更はない。

共通診断seed23826を両armのPython/NumPy/Torch CPU/CUDAに設定する。観測の有無で
終了後RNG digestが一致することを要求する。これは旧E23のseedを証明するものではなく、
保存E23座標と旧raw graphへの一致条件も別に維持する。
RSS監督はLinux `/proc` の全threadの子孫processを1秒ごとに走査するstdlib実装。
sampled tree peakと各arm自己ru_maxrssを区別し、瞬間的な全子孫peakの完全測定とはしない。
psutil未配置による初回test collection失敗は依存追加ではなくこの実装へ修正した。

10:50–10:53 UTCの認証済み公式SDK確認でコンペ参加済み、既存3packのlicense表示CC0-1.0、
rulesは公開モデル/外部データの利用条件を含むことを確認。E17の別asset HOLDは解除しない。
11:11 UTCのquota再確認はGPU残28.81h/30h。11:13 UTCの所有notebook検索4件に
新slug `taichiiiii/biohub-e23-association-observer-parity` は無く、既存runを置換しない。
GPU1台可視化・private・offline・8400秒上限で一度だけ起動することを親が決定する。
起動直前receiptは `outputs/local/e23_association_target_20260908/PREFLIGHT.json`。
notebook SHA `f88ae36117a629e6ce5146d458c6584110e3b799c674ff8ade72bccbde8a15c2`、
metadata SHA `002d306a6488856a82ae8d8154bb5e100c56bb7be1c9403df70fb1318fb3ac15`、
PREPARATION SHA `cc8396c58d40bd284e18aa4740faebb9a0ebf53c724541252d14f06302803a73`。
API受付結果と実行versionを取得後に別receiptへ記録し、不確かな応答から二重起動しない。

11:13:46 UTC、初回pushはversion **1** / kernelId **133543583** を受付、exec72357 exit0。
`DISPATCH.json`を保存し、同じslugのstatus RUNNINGを確認した。二重push/提出なし。
明示版`/1`のsource取得は403だった。current slugのsource/metadata取得は成功し、全10cellの
type/text完全一致、private/offline/T4、競合data+3pack完全一致、同一kernelIdを確認。
API受付version1とcurrent source一致は別証拠で、明示版取得成功とは報告しない。
`remote_current/`と`REMOTE_READBACK.json`へ保存。11:15頃の限定output取得ではlog/receipt未公開。
RUNNINGを完了やparity成功と扱わず、この同一jobの結果を確認する。

11:27 UTC、installed CLIの`kernels logs --follow`を確認し、同じjobのlive stream取得に成功。
通常のoutput一覧は空でもlive logは利用可能だった。log時刻84.613秒に依存import成功、
support13とprimary/DeepCenter/secondaryのSHA一致、595.084秒にTesla T4とbidir0.3、
595.349秒にplan SHA `a8b951b2fbf378d31054fcfcb3846509fe0f66d273ea6bfa60891b44f7880b54`、
595.377秒にOFF PID71起動を確認した。約595秒はOFF開始までのsetupで、推論時間ではない。
`LIVE_LOG_1127.json`へ選択イベント143件中9件を保存。15秒の限定stream観測はRead timeoutで
終了したが、診断jobの終了を示すものではない。継続listenerはexec session82562。
子processの詳細stdoutはoff.logへ分離されているため、live notebook logだけで処理動画数を
推測しない。全4完走・ON実行・parity成功は未確認のまま。

11:42 UTC追記: 同じlive listenerに`D3 ARM_FINISHED off exit=0`と
`D3 ARM_STARTED on PID 117`が到着。APIもRUNNING。OFF正常終了→ON起動まで進んだ。
`WATCH_ON_STARTED_1142.json`を保存。個別RESULT/PROCESS/arrayは通常outputでまだ取得できず、
実artifact監査は未完。最終PARITY_RESULTの成功、実36収集、学習、採用、提出は未証明。

## 2026-09-08 12:10 UTC — terminal結果と親artifact監査

v1は12:01:57 UTC API COMPLETE。両arm exit0、実行側は
`PUBLIC4_ASSOCIATION_OBSERVER_PARITY_PASS`。PARITY_RESULT SHA
`d3da638833ed845bb418fd3f6388a6afb84ec5ca653f29a5ed727a65071080b9`。
親の手元再照合も`PARENT_PUBLIC4_ARTIFACT_AUDIT_PASS`となった。
共通24/観測8 NPZの実array、22 runtime Python、元E23 detector/選択rawが一致した。
全nodeの実ID座標写像、戻り全辺→pregraph、post選択辺の値保存も再検証した。

| 動画 | detector数 | threshold後全候補辺 | ILP選択node | ILP選択辺 |
|---|---:|---:|---:|---:|
| 44b6_0113de3b | 26,356 | 25,346 | 25,828 | 24,901 |
| 44b6_0b24845f | 32,582 | 23,636 | 22,447 | 19,625 |
| 6bba_05b6850b | 7,161 | 6,377 | 6,361 | 6,035 |
| 6bba_05db0fb1 | 75,656 | 70,635 | 71,491 | 67,648 |

OFF1066.247秒、ON1194.206秒、観測追加約128秒（約12.0%）。observer133.619秒は
ON内の計測区間であり、OFF/ONのwall差と同じ定義ではない。writer114.309秒。
最大自己RSS4,237,594,624bytes、CUDAallocated681,518,080/reserved977,272,832bytes。
PASSログ時刻2855.841秒はsetup込みのログ時刻。全て固定runtime/RSS上限内。
396 packet、dense75,120,102、1,396,686,843bytes。全pair manifest契約を手元再検証。
matrix NPZ全量は手元に取得せず、現地sourceの全pair即時roundtrip/最終hashに依拠する。
画像/重みの手元再hashも未実施。観測manifest自体の`NOT_PARITY`は保存層だけの判定で、
別のOFF/ON comparisonと親のactual graph監査でparityを確認したことと矛盾しない。

再現scriptと全artifact SHAは
`outputs/local/e23_association_target_20260908/audit_terminal.py` / `PARENT_ARTIFACT_AUDIT.json`。
親単独の自己レビュー。公開4はin-sample、精度/Loss改善やhidden汎化は未評価。
全36収集は未起動で別契約へ進む。E17 HOLD、E26不採用、E23 LB0.924維持、提出なし。
