# E26 SCREEN v2 — 出力境界修正（前向き契約）

2026-09-08。親単独で設計・実装・自己レビューする。独立レビューとは呼ばない。
これは失敗したv1の判定変更ではない。実装受入・予算再固定・新規登録前の再実行はしない。

## 診断と証拠

v1 `e26_motion_off_screen_v1_20260908061704Z` はbaseline36の全core処理後にexit2。
wall2584.1039365000324秒、timeoutではない。候補未起動・生成seal無し・GT採点無し。
GENERATION_FAILURE SHA256は `868748daf1c66bd4628615d531e003d156842cc971450af0641cd1f8a7eec6b2`。
基準CSV SHA256 `72d2a94c6ee4a9fce37a9f330c7c9d0a7097976d013a511ea6fe4b2b6e383273` は
旧E25基準CSVとbyte一致。1,491,393行（760,783nodes/730,610edges）の全件走査で以下5件を確認した。

| dataset | row id | node id | t | 範囲外field | raw予測の同field |
|---|---:|---:|---:|---|---:|
| 44b6_a21120c2 | 705187 | 3048 | 12 | x=256 | 252.0 |
| 44b6_a21120c2 | 712807 | 10909 | 44 | x=256 | 252.0 |
| 6bba_2312ac41 | 1129139 | 12160 | 81 | y=256 | 252.0 |
| 6bba_3db54e20 | 1437327 | 10589 | 68 | y=256 | 252.0 |
| 6bba_3db54e20 | 1437377 | 10649 | 68 | y=256 | 252.0 |

各実画像のshapeはT100/Z64/Y256/X256。整数座標の上限はdim−1。
既存writerはround→下限0だけで上限を適用しない。rawは範囲内なので後処理中に移動したことは
確認できるが、保存整数CSVから最終floatやcentroid/linefit等の個別寄与は復元できない。
この証拠だけで特定の上流stageを原因と断定しない。

v1はvalidation後に統計保存する順序だったため、全36本のraw_stats/eventsはmemoryにしかなく
失われた。stdoutのhook完了は残るが実counter値は未保存。旧E25値で穴埋めしない。
元run・登録pair・submitted v3 notebook/helper/出力は変更せず、失敗として保持する。
変更前のrunner/CLI/tests/csv_out/pipelineは `outputs/local/e26_screen_v1_source_snapshot_20260908/`
に6ファイルのみ保存した。別checkout/入力コピー/新しい実験出力ではない。

## 変更範囲と不変条件

1. 唯一の既存SubmissionCsvWriterとrun_postproc_coreに任意node_serializer callbackを追加する。
   省略時のlegacy CSVはbyte不変。graph loop/モデル/後処理config/edge/順序/ID/tは変えない。
2. E26の3arm全てへ同じround→XYZ上下限clampを明示適用する。shapeは登録画像metadataから取得。
   既存 `output_bounds.bounded_output_node` と `new_output_bounds_report` を再利用し、helper自体は不変更。
   ID別・動画別例外、GT依存、validator緩和、既存CSVの書換えは禁止。
3. 全補正ノードの最終入力float/IDを保存し、sample20件制限とは別の完全auditを持つ。
   既存の下限clipもreport対象だがlegacy CSVとの差は0。上限補正だけを新しいCSV差として区別する。
   verifierはauditから補正/集約を再計算し、実CSV行・shape・node数・literal動画順と照合する。
4. coreが返った時点でraw_stats/events/bounds reportをexclusive保存し、CSV検証失敗時も残す。
   core途中で例外が起きた場合も、その時点までの観測をfinallyで保持する。部分記録に成功labelを付けない。
   OS強制終了・電源断・保存先障害時の完全保存は保証しない。core wallは観測保存時間を含めず計測する。
5. 新しいpublic登録・child・arm・sealのschemaはv2。旧v1を新コードで成功に昇格させない。
   GTの不透明bindingや入力inventoryの意味は同じなので、そのschemaはv1のまま維持する。
   source closureへoutput_boundsとadapter、scientific closureへこの契約を追加する。
6. E26既定のmotion ON/OFFのみの対比、動画分割、19採否gate、GT分離、serial実行は不変更。
   この文書はv2に限りunit03の「既存postproc不変更」をcallback API追加について上書きする。
   public4は依然E23 referenceとの完全byte parity必須。金メダル精度の達成や提出許可を意味しない。

## 再実行前の受入と次の物理確認

- 小さいfixtureで全XYZ上限/下限/ties-to-even、入力不変、全補正保存（20件超）、不正値拒否、
  CSV一致/改変検出、デフォルトwriter互換、coreでのcallback呼出を検査する。
- runner統合testで3armへの適用、旧schema拒否、validation失敗時の統計保持、sealing前のaudit照合を検査。
- 親がdiffを読み返して関連pytest/Ruffを実行。提出済helper/notebookと失敗v1のSHA不変を確認。
- 受入後に親が新run IDと数値予算を明示固定する。古い登録/CSV/旧E25統計を新runの証拠に流用しない。
- 新baselineの全行を失敗v1と診断比較し、既定5fieldの256→255以外が変われば原因調査して停止。
  これは比較oracleであり、5ノードだけを補正するproduction allowlistではない。
  候補の補正対象は未観測なので事前に5件などへ固定しない。全記録を確認し大きな補正は原因調査する。
- 3armの成功sealができた場合だけ既定eval12→eval24→eval36採点へ進む。再提出は行わない。

## 2026-09-08 07:37 UTC — 実装受入・v2物理予算の親判断

親の自己レビューと13関連module **1818 PASS / 241.52秒**、Ruff/diff-check PASSで受入。
24 warningsは合成のedge無しgraphに対する既存公式警告。実competition GTは未採点。
最初の3moduleは1493 PASS。レビューでcore wallに保存時間を含めない位置へ計測を修正し、
境界エラーをE26Errorへ統一、3armの完全補正記録・callback未使用時の拒否も追加して拡大検証した。
型check専用toolは未設定。提出済helper/notebook、元v1登録pair/失敗receiptのSHAは不変。

新run IDは **e26_motion_off_screen_v2_20260908073709Z**、新規実行はこの1回だけ。
`analysis/e26_screen_budget.json` の数値をそのまま再採用する（上限延長はしない）。
SHA256 `2b0c93b53d0a4ba02ccce67e0a5c25a2f7251536142cec1454a4b21bed47103e`。
public4 1200秒、baseline/candidate各5400秒、生成全体14400秒。
採点全体7200秒、eval12/24/36 1800/3600/300秒、self RSS上限8GiB（OS hard capではない）。
旧v1の387秒/2584秒に余裕があり、追加serializerの合成1万node計測は0.259秒
（760,783nodesへ単純外挿約19.7秒、実arm時間の証明ではない）。本機空きdisk191GiB。

親は全実入力・コード・科学契約を新たにpreregisterし、public/private元SHAを記録してからgenerateする。
旧v1は終端失敗のまま。新登録後は対象source/科学契約/入力/依存/HEADを再凍結し、台帳だけ進行追記する。
基準完了後は新旧全行比較を行い、想定外差分があれば直列監督を停止して診断する。
自動retry/旧CSV差替え/既存失敗run再開/Cloud/学習/新提出/commit/pushは実施しない。
