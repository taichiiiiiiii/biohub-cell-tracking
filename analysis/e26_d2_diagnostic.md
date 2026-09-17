# E26 D2 — 保存経路比較と既露出12動画の追跡損益診断

2026-09-08。親単独の診断。新候補・新しいholdout評価・学習・提出ではない。
元のE26登録・source・数値gateは変更せず、E26棄却、E23 LB 0.924維持。

## D2A結果 — 比較は閉じたが、hidden実行同値は証明できない

機械可読の全項目表は既存canonical内の
`outputs/local/e26_d2a_saved_route_audit_20260908.json`（69,718bytes、
SHA256 `5e3d800aa2fc267d5ecc152268a9fdf4d88635c0cc49e62f1844fb26944fdee7`）。
10入力のpath/size/SHAと、各armの全101設定の対応根拠を保持した。
自動抽出部分の再現コマンドは同名`.command.txt`
（SHA `8517e2248c8164d9becee6e29ab7caf468cba215503384d2cc92735d24190948`）。
manual_field_coverageとadditional_findingsは親のソース読解による注記で、
このコマンドが自動的に再現するとは扱わない。09:52 UTCに全10入力を再hash照合した。

| 比較対象 | 提出済みE23→E26 | local→target / 証拠の限界 |
|---|---|---|
| 保存notebook | 33cell中変更は3/13だけ。3はmotion OFFと後段validator OFF、13は同一helperを1回埋め込み、境界補正とaudit/provenanceを追加 | 保存source比較であり、historical hidden実行全byteの証明ではない |
| 保存ログの実効設定81項目 | 型も含め差はmotion relink true→falseだけ | localの全101項目との対応はJSONへ保存。72項目は静的に完全一致、3項目はtagと既定asset path差、1項目はTEST_DIR、25項目は構造・手動指定・無効機能等から別途対応 |
| 出力境界補正 | E23はround/下限clip、E26は上下限補正 | **相違:** local v2は両armで同一の上下限補正。target比較だけはmotion以外に境界補正差がある |
| 境界補正の対象範囲 | 保存reportはpublic4で新規上限1件とlegacy下限6件 | **未検証:** hidden補正件数・影響。LB差をmotionだけに帰属させない |
| raw生成 | E23/E26ログはbidir harmonic 0.30、dual seed、同じ検出閾値/ILP設定 | raw36 v11ログも0.30。現在のraw notebookはE22後に0.20へ戻されており、v11生成sourceとして代用不可 |
| raw36旧ログの後処理設定 | safe division threshold/radiiの4項目がE23と異なる | localは旧producerの最終CSVでなく後処理前raw GEFFからE23設定で実行。旧CSVはpublic4のみ。これら4項目をlocal設定差と誤認しない |
| source integrity | support13file manifestとモデル3個のhashは保存ログで一致 | **未検証:** integrity receiptはdynamic patch前。v11の完全なpatched predict sourceは保存物から発見できず、実行code全体の同値を主張しない |
| DeepCenter重み | 同じSHA、epoch2の成功記録 | **相違:** local strict CPU/float32、targetはCUDA優先の実装。T4実行ログはあるがpostprocess全parameter dtype/device receiptはない |
| experiment tag / asset path | target共通tag、local別tag、mount path違い | tagはログ・stats用。path文字列一致でなくcheckpoint/manifestの内容identityを優先 |
| refinement/safe-div/twin | 保存target実装のhardcoded refinement、mid-track-parent条件、無効twinとlocal設定を照合 | manual25項目の根拠をJSONに列挙。静的対応を101項目すべての実測receiptとは呼ばない |
| 後段validator | E23 ON/E26 OFF | 保存sourceの後段はstats出力のみでsubmissionを書き換えない。visible output経路で差なし |

主な固定identity（完全なpathはJSONのbindings）:

- E23 notebook: `08507f9123d9f40e185d0db8eda3dd21cb405e50febb720827c2e655f68d5ec1`
- E26 v3 notebook: `0976f955fec21352fe37e1afb37b8c40d992fbde61cdea2a43b189d4eae185f2`
- raw36 v11 log: `eaf6749aafacfc87b5c9ec953add016adff61d5a3da8d3112385590029ce5129`
- support source manifest: `978b626d1fd1e7397435a437dfe68691defe1572fc3c20e61012d7c9b52ed029`
- primary checkpoint: `12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771`
- secondary checkpoint: `9bac2fa0dadc4a6fc1899e0caf187f4b553e0a7cd90ba1261a68b35ffe9e305f`
- DeepCenter checkpoint: `8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0`

判断: 未知のhiddenや旧producer sourceを取り直してE26を救済しない。
保存CSV同士の**ローカルで観測した局所損失**はこの不確実性と分離して診断できる。
D2Bへ進むが、結果をLB悪化の因果説明へ昇格しない。

## D2B固定実装単位 — 実GT実行前

入力はv2 scoringの保存`eval12_baseline.csv`/`eval12_candidate.csv`と`eval12.json`、
そのliteral12動画のGT GEFF・scale metadataのみ。新予測も画像frame読込も行わない。
GTを意味的に開く前に、元GT_BINDINGの対象12だけの全file bytesとscaleを再照合し、
新診断のsource/依存/入力SHAをcontrolに固定する。残り24は意味解析・走査しない。

公式APIは`biohub.evaluate`がpinする`tracking_cellmot.metrics.evaluate`をそのまま使う。
graph生成はstockの小さい関数にactual bulk_add_nodes戻りID保存だけを加え、
stock graphの全node/edge値・schema・順序・internal IDと実行ごとに完全一致を検証する。
`_evaluate_matched_graph`は公式採点後のmask/有効FP抽出にだけ使う。独自proxy採点はしない。
全12×2armの全per-sample列（7counts、recall、ratio、J、adjusted J）を保存公式行に一致させる。

GT edgeのarm内状態は相互排他的な6分類:
`tp` / `source_unmatched_only` / `target_unmatched_only` / `both_unmatched` /
`both_matched_no_csv_edge` / `both_matched_edge_not_official_tp`。
arm間は`retained_tp` / `lost_tp` / `gained_tp` / `shared_fn`。
TPの消失と増加を全動画で対称に分類し、各GT edgeの個票と集計の完全一致を確認する。
未対応予測を一律FPにしない。FPは公式`pred_valid & ~matched`だけ。

全pred nodeのsubmitted↔internal ID、GT対応ID（未対応も含む）、t/z/y/xを保持する。
全GT node/edge、全pred edgeと公式評価対象/TP/FPフラグもParquetに保持する。
GT edge個票は両armの対応端点ID・座標・CSV edge有無と公式TPを持つ。
生成nodeの同じsubmitted IDをarm間で同じ物理細胞と仮定しない。
未対応という事実だけからnode削除や座標変化の原因stageを断定しない。

実行予算は**wall600秒、self peak RSS4GiB、出力250MiB**。単一process、CPUのみ、
OMP/MKL/OpenBLAS/Polars thread数1、PYTHONHASHSEED=0、network/workerなし。
wallは入力事前照合後の診断区間にsignal timer、RSS/出力は各動画/保存の境界で確認
（全起動時間やOS hard memory limitではない）。
違反・例外・公式行不一致はERROR、既存出力を上書き/無言retryしない。
12動画だけでも完走結果を待たずに分類規則を調整しない。

先に合成fixtureで6状態/4遷移、ID写像、疎GTのFP除外、divisionを含む公式一致、
不整合入力拒否、完全集計を検証し、親が自己レビュー。その後一回の物理診断を行う。
結果は診断完了ラベルのみ。E26再採用・gate変更・提出許可は発行しない。
