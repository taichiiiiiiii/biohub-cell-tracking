# 検出器固定・association学習の次段階設計

## 2026-09-22 XY反転比較 — 取得待ちと独立した新規学習契約

Issue #18、ユーザーのデータ拡張調査・自律実行依頼に基づく。train32計画は変更しない。
新run `frozen-association-20260922-xyflip-v1` は既存train8/selection4、warm primary、
seed20260922、lr1e-5、785window×10epoch=7850更新、検出器固定を維持。
10epochは既存無拡張対照との同予算比較であって、十分な学習量や最適値の主張ではない。
変更は訓練時のXY反転のみ。仮説:方向への適合を減らして無拡張selectionの追跡Lossを改善する。
対照は失敗結果も保存された `frozen-association-20260922-v1`。開始前に同じwarmの
validation readbackを対照baselineと照合する。コードsnapshot hashは変更されるが、
既存経路の動作を回帰試験で保持する。複数seedによる効果確定とは呼ばない。

画像のXY軸を独立p=.5、2フレーム共通で反転し、実ノードの同じ軸だけS−1−cへ変換。
Z/時間/ノード順序/接続targets/masks/voxel_size/downsampleは維持。補間・clip・dropなし。
downsample後の座標は最大63.75等で最終voxel中心63を越える。既存train28/val10座標出現が
該当したため、0<=c<=S−1による拒否はしない。公式flipと同じ連続座標変換を用いる。
選択/検証/固定detector probeには拡張しない。公式default_rng()経由の拡張は使わない。
決定規則: compact ensure_ascii JSON `["biohub-xyflip-v1",seed,1-based epoch,example_id]`
のUTF8 SHA256先頭byteのbit0=Y,bit1=X。global/sampler RNGを消費しない。
全予定scheduleのSHAをmanifest model_configへ束縛し、実際の処理順IDからepoch別の
反転列と4組合せ件数を保存する。epoch境界resumeは復元samplerと絶対epochから同一列。

採否はv1のloss gate全数値・earliest-best selectorを保持。未達重みexport禁止。
augmented train Lossと元v1 train Lossの絶対値を改善比較しない。無拡張validationの
edge/det/totalと動画別結果を比較し、loss PASSでも最終graphのedge/division評価が別途必要。
selection4は既露出development、上流公開重みも学習露出あり。Private汎化の証明としない。
非有限Loss/gradient、固定検出器変化、input/source drift、readback不一致で停止。
実行はMPS float32/no fallback、重い処理は直列。前回epoch約448秒から1–2時間を目安とするが
baseline/hash照合の所要時間を含め保証しない。実行中に同じsourceを編集しない。

調査根拠: 公式`official/scripts/augmentations.py`には同時画像/座標flip実装がある。
[酵母追跡研究](https://www.nature.com/articles/s41540-024-00466-x)も画像/GTへ共通幾何変換を
使用するが、2D酵母・密なsegmentation labels・F-scoreと本競技の3D疎注釈/公式metricは異なる。
外部データ/重み/コードは導入せず、効果を移植可能と決めつけない。輝度/ノイズ/回転/合成生成は
今回は同時追加しない。Qwen Cloud Maxが変換部品を作成、親が実データ境界とテストを修正統合。

実行状況: 最終82 tests/ruff PASS、独立レビューSHIP後にsession14618/PID32941で起動。
v1 baseline SHA `8cc8d764fe50776e0b5ba5a6caccca1662efc33624a2eb1d1e1cfdc469a57ff2`を指定し、
無拡張baseline照合PASS。`optimizer_updates_started, epoch=1`まで確認済み。
開始時点では新規学習開始のみを示していた。

05:23 UTC終端確認: 10epoch/7850更新完了、session14618 exit2、loss gate FAIL。
best epoch4: validation total改善0.049314%（必要1%未達）、edge改善0.517878%、改善動画2/4、
44b6 precision非劣性未達。epoch10 edgeはwarm比7.102029%悪化。この重みはexport/提出しない。
best後の延長や別拡張の同時追加ではなく、動画別誤接続とgateのverdict記録不一致を次の診断候補とする。
詳細・hashは実験台帳の同時刻結果節。過去の起動/進行中記述は観測履歴として保持する。

## 2026-09-22 新規学習の直接依頼後の準備状況

ユーザーの新規学習依頼を受け、fixed-budget train32 の準備を再開。
session7603 の新しい配布一覧照合は93ページ・対象3198filesまで進み、
HTTP **429（rate limit）**で停止した。再試行・認証更新は行っていない。
これは以前のstatus不明HTTPErrorの原因を遡及確定するものではない。
追加train24の2952files（10,560,588,727bytes）はローカルsize一致0件。
audit8込みの14,166,405,270bytesという以前の規模と区別する。
配布一覧照合未完了・追加データ未取得のため、学習本体の開始条件は未達。
次の取得照合では要求間隔と再開可能な途中記録を用意し、全ページを高速に再走査しない。

監督下のQwen Cloud `qwen3.8-max`（subscription-cloud-only、fallback/retryなし）に
永続samplerのみを実装依頼し完了。親が整数/device/seed検証とテストを補強した。
新規 `src/biohub/association_step_sampler.py` は785step区切りをまたぐ順序と
checkpoint復元を提供する独立部品。既存v1のtrainer/data/manifest/重みは未変更。
独立レビューでseed/cycleと順列・RNGの意味的一致不足を指摘され、seedからの再生照合と
別状態の有効テンソル差替え拒否テストを追加。20 focused tests と既存47 tests、ruffはPASS。
**train32入口への統合・取得契約・実行前受入は未完了**で、
この部品の完成を新規学習開始や学習gate PASSとは扱わない。

## 最新判断: v1終了と次の原因診断（2026-09-22）

`frozen-association-20260922-v1`は10epoch完走、採用gate FAIL。以下の開始前設計は
歴史的契約として残す。best epoch2でも合計Loss改善0.01161%、改善動画1/4で基準未達。
この重みをexport・提出しない。E47座標writerの探索提出とは別の実験である。

成分別の親再集計: train edge Lossはepoch1→10で24.74548%低下、selection edge Lossは
学習前→epoch10で12.83133%増加。best epoch2のedge改善も0.121886%にとどまる。
検出Lossは全epoch不変。固定成分が合計値を支配するため、合計値だけで改善を説明しない。
trainはdropout有効かつepoch中に重みが更新され、selectionはeval modeなので、
両者の絶対差だけで過学習を確定しない。既存gateをedge基準へ遡及変更もしない。

診断契約（独立診断で妥当性確認済み、後述のとおり実行完了）:
- 仮説: 同一eval modeでも更新後の重みはtrain8に適合しselection4で悪化している。
- 新学習や候補探索ではなく、学習前・best epoch2・last epoch10の保存重みだけを比較する。
  同じ固定train8/selection4と有効windowで、dropoutなし・optimizerなしの読み出しを行う。
- edge/det Lossを分け、動画別・系統別の分子/分母と注釈mask内precision/recallを報告する。
  別動画への交換、新GT、しきい値探索、再学習、提出は含めない。
- train改善とselection悪化が再現すれば一般化不足と整合的。再現しなければtrain/eval modeや
  集計差を優先して調べる。どちらでもPrivate性能の証明や失敗gateの救済とは扱わない。
- 既存入力/source/hashを固定し、失敗runを上書きしない。実装が必要ならQwen Cloud Maxへ
  この読み出しだけを依頼し、レビュー後に重い実行を直列で1回行う。

独立SOL/medium診断: 既存reportには固定checkpointでのeval-mode train8測定がないため、
上記読み出しが必要。trainのepoch内重み更新/dropoutとselectionとの差は測定条件差であり、
直ちに実装バグとはしない。Lossは公式のwindow内mask平均をwindow間で等重み平均する。
selection各動画は99windowだが正例edge出現数は119–880と異なり、動画構成差も残る。
baseline二重評価と毎epochの復元readbackはselection悪化の再現性を支持するが、原因は確定しない。
eval-mode train改善が再現しない場合も「dropoutが主因」と断定せず、online集計を含む差を
追加切り分け対象にする。保存済みFAILと数値gateは維持する。

保存baselineとepoch10から動画別の追跡Loss差も再集計した（新推論なし）。
44b6_144b256d:+9.430196e-6、44b6_81c256f0:+4.839113e-6、
6bba_43fea39d:+4.320387e-5、6bba_d6ecebbb:+1.452374e-5で、全4動画が悪化している。
各99windowなので平均悪化の約60.0%は6bba_43fea39d由来だが、単一動画だけの異常ではない。
注釈mask内precision差は順に−0.015336/+0.000051/−0.009900/−0.000978、
recall差は0/+0.005076/+0.004673/+0.004808。Lossとしきい値付き指標の方向は同一でなく、
recall微増だけで採用しない。これらはepoch10の診断でありbest epoch2のgate判定とは区別する。

### 同一eval条件の診断完了

session31304 exit0。warm/best/last×train8/selection4の6評価を完了し、selection3評価は
保存baseline/epoch2/epoch10とのreadback照合に成功。optimizer stepは全て0。
訓練側edge Lossはwarm 0.0002088612026831142、best 0.00018196717353162085、
last 0.00014276893291272264（warm比−12.8765%、−31.6441%）。最終の系統別変化も
44b6 −33.4733%、6bba −29.3009%。検証側はbest −0.121886%、last +12.83133%。
両側とも検出Lossは不変。重み・source・入力の前後照合を通過し、元runは不変更。
証拠は`outputs/local/association_candidates/frozen-association-20260922-v1-eval-readback/`。
completed.json SHA256 `88ab9740c4be729fa8ae27ee0d282f340ebb72cd7d22e21694d4f1d7b5f57675`。

解釈: 訓練側改善はdropout/online集計だけの見かけではなく、固定重みevalでも再現した。
訓練集合への適合と検証への転移不足を支持する。ただし動画数不足、分布差、モデル容量、
正則化不足のどれが主因かは、この比較だけでは識別できない。失敗重みの採用根拠にはしない。

次の仮説候補は動画被覆の拡大とする。同じselection4を使ったlr/epoch/閾値探索は行わない。
開始前に、学習動画の追加数・画像/注釈を見ない選定規則・既存eval集合との非重複・
未接触の追加監査集合・計算予算を事前固定する。既存selection4の再利用は露出ありと明記し、
追加監査集合も上流公開重みの学習露出があるretrospective評価とする。現在は仮説候補であり、
新データ取得・実装・再学習・5件目の提出を開始した意味ではない。

### 次runレビュー案: fixed-budget train32（結果・追加GT参照前）

仮説H-data32: 検出器固定associationを同じ7850 optimizer更新で学習しても、動画被覆を
8→32本へ増やせば、小さなtrain8への適合偏重を軽減して選択/監査動画へ転移する。
変更は訓練集合のみ。10epochをそのまま32動画へ適用すると更新が約4倍となるので採用しない。
元warm startから再開し、lr1e-5、batch1、seed20260922、loss/dropout/optimizer/clip等はv1と同じ。
32動画の全有効windowをseed固定の無復元shuffleで巡回し、7850更新で停止する。
785更新ごとの計10checkpointで従来selection4を評価し、同じearliest-best selectorとgateを使う。
これはv1のhistoryを変更せず、新runのstep単位契約として実装する必要がある。

動画は既存train8を保持し、追加24本（各系統12）を選ぶ。除外はEVAL12+EVAL24、
元train8/selection4、manifestのtest画像4本。残りを系統別に
SHA256("biohub-frozen-association-20260922:"+stem)昇順で並べ、先頭12を追加train、
次の4を監査用とする。初期のmetadata-only計算でpublic4の1本混入を検出し、
追加GT/画像参照前にpublic4明示除外を適用した。結果を見た動画入替ではない。

追加train44b6: 3bb3690f, 551a5dba, 87bba6c4, e28840c6, 0c582fdc, 8f9ecab4,
3a861e03, 8cc6506c, 808952d6, c15fded2, cf8fed6b, cf2536e8。
追加train6bba: 76db78c1, d3da753b, b204cac7, 784a78c9, 7f87b3d8, 5a4d9360,
5dfe9ad1, 2646afc7, 907271db, 6feb10f0, fbc898dc, 5f89039d。
監査44b6: d78e09d9, 949adeb1, 415c0a3a, c771cb04。
監査6bba: edf14583, 789f8168, bbb708ca, afb141ff。
各IDには記載の系統prefixとunderscoreを付ける。全集合は動画単位で非重複。

追加32動画の保存manifest上の規模は3936files/14,166,405,270bytes、sorted compact
path→size JSON SHA256 `ff52fdbe7e7d4861495943327d4994e56d80a3361ede97afc3f4ff2685c924ff`。
元data/manifest.csv SHA256 `6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4`。
APIの最新inventoryや取得内容との一致は未検証。監査8のローカルgeff directoryは全て不在。
これは過去の全経路で未露出の証明ではなく、上流公開重みの露出も残る。

監査8はcheckpoint選択に使わず、重み凍結後にだけ公式graph評価を開く。既存selection4の
失敗を監査側で救済しない。graph生成はGTなし、E39固定設定のcontrol/candidateで同じ入力、
weight以外同一、生成物hash封印後に採点。監査screen案は既存eval12数値gateを流用:
paired mean>=0.005、median>=0、worst>=-0.002、aggregate adj-edge>=-0.002、
両lineage aggregate score>=0。8動画は小標本retrospectiveでPrivate推定と呼ばない。
数値gate未達候補も探索提出の一般方針は残るが、v1同様loss gate FAIL重みのexportは禁止。

計算予算はv1と同じ更新数・selection読出し回数。動画寸法差による実時間増加は未実測で、
保証しない。取得/実装/実行前に独立レビュー、literal plan/hash固定、受入テストが必要。
Qwenによる新実装を自動goal継続から無人起動する許可にはしない。現状はレビュー案である。

実装上の注意（既存source確認）: acquisition/data/manifestはv1の12本/train8とhashを
意図的に固定している。定数の置換や検証削除でv1を拡張せず、v1契約を保った別run契約が必要。
785更新区切りをepochと偽装しない。全train集合のcoverageと各step区間で実際に見たwindowを
区別し、sampler巡回番号・permutation・cursor/RNGをresume状態に含める。7850更新中に
全有効windowが少なくとも1回現れたことを確認し、無断の打切りや部分集合平均を防ぐ。
候補選択のvalidation4は常に全396window。新動画のサイズ/正例不足で失敗したら差替えず停止。
v1のepoch実測中央値448.13秒は参考値に限り、32動画でも同時間とは保証しない。

独立設計レビューはHOLD。以下を必須仕様として採用し、未完成の取得契約を理由に
現段階では実装/取得/学習を開始しない。

1. 仮説は「固定更新数で動画多様性を増やす運用条件」の比較に限定する。各動画の反復回数、
   順序、最終巡回の部分消費も変わるため、動画数だけの独立した因果効果とは呼ばない。
2. samplerは単一の永続seed済みpermutation stream。全indexを1回ずつ処理した巡回境界だけで
   reshuffleし、785step checkpointでも途中permutation/cursorを維持する。resumeも同一列を
   再現し、785,1570,…,7850で評価、7850で厳密停止。巡回内重複/欠落、checkpointstep不一致、
   resume不一致、usable/positive windowが0の動画はFAIL。index/動画別露出数とsampler hashを残す。
3. selection4は露出済みdevelopment集合。lr/budget/threshold/ID/gateの再調整には使わない。
   このloss gate FAILならaudit8 GTを開かず停止。PASSは必要条件であって確認的な汎化証拠でない。
4. 取得前に完全prefix付きliteral train/selection/audit/public4/eval36 ID、選定規則/domain、
   source manifestとexpected path/size inventory、非重複assertionを機械可読契約へ封印する。
   現在はこの契約ファイルと最新API照合が未完了。audit8は全動画の入力/coverage整合性確認後、
   選択重み/configを封印→GTなしgraph生成→出力封印→GT採点の順に限定する。
   六条件はAND: 公式combined-score paired mean>=0.005、median>=0、worst>=-0.002、
   公式aggregate adjusted-edge差>=-0.002、44b6/6bbaそれぞれaggregate combined-score差>=0。
   これはaudit8専用事前gateであり、eval12と同じ統計的保証を意味しない。

2026-09-22追記（先の設計HOLDを更新）: 機械可読契約
`analysis/frozen_association_train32_plan.json`を固定し、独立SOLレビューは
**SHIP-for-supervised-implementation only**。32/4/8の非重複と、保存manifestから再導出した
3936files/14,166,405,270bytes/path-size hash一致も独立確認済み。親はこの範囲の
監督下Qwen Cloud qwen3.8-max実装のみ着手可とする。自動goalからの無人Qwen起動は不可。
最新API照合は96ページ後HTTPErrorで未完了（再試行なし）。したがって取得/学習開始は不可。
この設計レビューをdata freshness/content hash、coverage、runtime/RAM、同device resume、
実装受入・実行前レビューの代用にしない。既存v1と共有notebookは不変更で保持する。

## 学習後の接続先調査（2026-09-22、未実装・未実行）

独立SOL/mediumのread-only調査と親のsource確認により、保存済みE38実行版
`outputs/kaggle/e38_v27_submission_run/tracking_repo/scripts/predict_unet_transformer.py`
の`predict(..., evaluate=False)`を生成側の再利用候補とする。既存のE38ローカルrunnerは
6動画固定・自動採点・ILP直後graphであり、最終CSVの対照/候補比較にはそのまま使わない。

実装時に必要な接続は、同じ固定画像集合をGTなしで直列生成する薄い入口と、生成後の
共通postprocess。exportはraw重みのみで、predictorの`load_model`は隣接config.jsonが
ないと既定値へfallbackするため、両armのconfig実体・hashを明示的に束縛して欠落を拒否する。
primary以外の重み・source・実効設定は同一とし、生成前後で照合する。

`public_postproc.production_adapter`の`baseline`はe23 profileだが、`candidate`は
別仮説のsteal-twin profileへ切り替わる。学習候補という名称だけで`candidate`を選ばず、
両GEFF rootへ同じbaseline/e23後処理を使う。既存adapterの入力集合・型・hash契約を
迂回しない。E23 collectionも歴史的なsource/重み/reference固定のため直接流用しない。

これは実装経路の調査結果であり、全依存の同一性やE38再現を証明したものではない。
学習gate PASS後、固定config・画像集合・生成物の束縛を実装/レビューし、E38対照再現、
両armの検出座標不変、最終CSVの完全性を先に確認する。生成物を封印してから別processで
公式採点する。既存の数値条件とeval36のretrospective位置付けは変更しない。

2026-09-22 JST / Issue #18 / DESIGN_ONLY — 実行・採用・提出の承認記録ではない。

## 仮説と現時点の結論

UNetとdetect_headを完全固定してassociationのみ学習すれば、検出品質を変えずに
最終追跡graphの誤辺を減らせるかを検証する。
v3は固定機能が成立しただけで、既露出2動画・8frameのproxy accuracyには差がない。
v1/v2/v3は診断成果物であり、この設計の候補checkpointへ昇格しない。
小さなLoss差を公式score差として換算しない。

## 実験前に解消する条件

- `analysis/training_loss_gate.md` のcandidate契約を満たす学習経路が必要。
  現入口はdiagnostic-only。完全resume、best選択のearliest tie、validation再読出し、
  成分の母数、全依存source/config/inputのpin等を満たしたと主張しない。
- 学習、checkpoint選択、最終比較を動画単位で分離し、各集合のliteral IDとhashを先に固定する。
  diagnosticsの4動画を独立holdoutと呼ばない。frameをばらして分割しない。
- 公開primary重みの上流学習露出があるため、現在のローカル比較はretrospective screening。
  データ分割だけで上流露出が消えたことにはならない。未接触GT境界は維持する。
- 実効window/正例coverageを動画別に確認する。空動画の黙った除外は禁止。
- 独立レビューと親側の採否を経る。旧Qwen launcherや古い役割文書を再利用しない。

## 対照と変更範囲

対照は採点済みE38の推論設定を固定して再現する。Public 0.930は参考結果であり選択基準ではない。
E44の結果待ちを理由に設計を止めず、E44のR+S変更や採点結果をこの比較へ途中追加しない。

候補と対照の差分はprimary association weightsのみ。primary検出器、secondary全重み、
検出しきい値、双方向/secondary混合重み、ILP、後処理、CSVwriterを同じbytes/configに固定。
optimizerに渡すtrainable集合を記録し、固定部の全parameters/buffersをepochごとに照合する。
同一validation入力で検出logitと検出座標の不変を確認する。

## 段階と評価

1. 設計レビューで学習split・学習量・selector・noise floorを数値まで確定する。
   本書の段階では未確定なので学習を開始しない。
2. candidate loss gateとartifact検証を通す。一番最後のcheckpointを無条件に選ばない。
3. baseline/candidateの最終CSVを同一動画集合で直列生成する。
   生成processへGT/scoreを渡さず、生成終了後に入力・source・出力hashを照合する。
4. `src/biohub/evaluate.py::score_submission` 経由で公式metricを採点する。
   同関数はGT欠落動画をskipするため、返却dataset集合が予定集合と完全一致しなければ無効。
   部分集合平均、train proxy accuracy、検出recallを公式scoreの代用にしない。
5. 動画別score、edge/division TP/FP/FN、node数、両系統別結果、paired mean/median/worst、
   公式micro aggregateを区別して記録する。
6. 提出前には未変更候補をKaggle環境で再現し、CSV検証とhidden規模の時間/RAMを確認する。
   日次枠消化目的の提出・同一予測の重複提出は禁止。

既存の構造修復用eval12/24/36 gateを本設計で上書きしない。新しい学習候補に適用する
数値gateは独立レビューで事前固定し、結果を見た後の緩和は禁止。

## 次の具体作業

### データ配置監査と分割案（2026-09-22）

`data/train` の画像rootは36、GEFF rootは41。画像36は既存EVAL12+EVAL24と完全一致し、
評価集合以外で画像と注釈が揃う動画は0。現在のローカル画像だけで本学習を始めない。
この監査はdirectory名とmanifestのみを読み、新しいGT内容は読んでいない。

ローカルmanifestにはtrain画像199動画が記載され、eval36を除く候補は44b6=53、6bba=110。
各系統で `SHA256("biohub-frozen-association-20260922:" + stem)` の昇順に並べ、
先頭4本を学習、次の2本をcheckpoint選択用とする**分割案**を作成した。
score・注釈の密度・モデル出力を見て選んだ集合ではない。

- 学習44b6: `44b6_e35b117d`, `44b6_66f9292d`, `44b6_1d530831`, `44b6_e57ff5c6`
- 学習6bba: `6bba_15403b9a`, `6bba_61ecbe65`, `6bba_f20478e9`, `6bba_6479435d`
- 選択44b6: `44b6_81c256f0`, `44b6_144b256d`
- 選択6bba: `6bba_d6ecebbb`, `6bba_43fea39d`

既存eval36は最終retrospective screeningとして別に維持する。公開重みの上流露出は残る。
新12動画の画像全量は保存manifest上5,102,963,047 bytes（注釈等別）。
2026-09-22に既存認証のKaggle CLIで全125ページを読み取り、新12動画の画像・注釈
1,476ファイル、5,103,093,406 bytesについて保存manifestとのパス・size一致を確認した。
欠落0、余剰0、size相違0。これは配布一覧の一致であり、実体の取得・内容hash検証ではない。
対象path→sizeをキー順・compact JSON化したSHA256:
`7e0f453c1d457e6c20e40121c91551f42ad5593114aa0a9b6918859fe08259d9`。
ローカル対象ファイルは0件。ダウンロードや新GT内容の参照は未実施。
既存download入口は指定train以外にtest等514ファイルも選択するが、現在は全てsize一致でskip対象。
取得時は対象限定を再確認し、認証失敗で後続要求を出さないよう直列・fail-fastが必要。
現入口の関連テストは29件成功。分割承認・学習条件の確定は別条件で、取得可能性だけで開始しない。
親レビューで集合を固定し、必要データを取得・検証してから実効coverageを確認する。
欠落や正例不足を見て都合の良い動画へ入れ替えず、停止理由として記録する。

学習候補の実行ではなく、candidate loss gateの不足項目を現実装と照合して完了条件を確定する。
それと並行可能な読み取り作業として、既存評価動画IDの重複・学習露出・データ実体を確認する。
この準備に有効な候補が生まれなければ、診断モデルを提出して5件を埋めない。

## 本学習の数値契約案（2026-09-22、取得中・GT内容確認前）

これは次の実装の入力となるレビュー案。下記の候補経路はまだ存在せず、診断入口の上限を
外すだけで実行しない。取得完了・全hash検証・契約実装とレビュー完了後にrunを登録する。

- Split: `frozen_association_acquisition.json` のtrain8/selection4をそのまま使用。
  全100frame中の有効な連続2frame windowを使用し、無注釈window/空動画を黙って除外しない。
  実効window数・正例数・除外理由を動画ごとに記録。各動画の正例windowが0なら中止。
  不足を見て別動画へ交換しない。eval36は学習にもcheckpoint選択にも使用しない。
- Warm start: primary `12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771`。
  全key/shape/dtypeのstrict load。UNet 32/[32,64,128]、downsample [1,4,4]、window2。
  unet/detect_headの全parameter/bufferを固定。その他の構成は読み込む公式sourceとpinする。
- 学習量: 10 epoch、batch1、workers0、全有効window、max-iters打切りなし。
  seed20260922、MPS/float32、AMPなし、schedulerなし、augmentationなし。
  AdamWはrequires_grad=Trueだけを対象、lr1e-5、betas[0.9,0.999]、eps1e-8、weight_decay0.01。
  dropout0.3は既存モデル構成のまま。gradient clip1.0、全stepのclip前normを記録。
- 入力精度の明記（実GT読出し前のsource確認）: official `FrameWindowDataset` は
  quantile正規化した画像を`.half()`で返し、epoch coreは`.float()`でモデルへ渡す。
  上記float32はモデル計算のdtypeであり、画像を一度も半精度へ丸めない意味ではない。
  この公式前処理を維持し、downsample[1,4,4]・clamp下限0・quantile値とともにpinする。
  入力精度を変える追加実験は本候補に混ぜない。
- Loss記録は各成分の実値をhost精度で集計し、`total_loss`を成分numeratorと固定weightから
  再構成する。逆伝播へ渡したfloat32の合計は`objective_total_loss`として別途保存する。
  丸め差を隠したりformula検証toleranceを緩めたりせず、勾配計算自体は変更しない。
- Loss: edge_loss + 1.0 * det_loss、det_neg_weight0.01、pool_kernel_um5.0。
  batch1・window2でも平均値だけを保存せず、成分ごとのnumerator/denominator/reductionを記録。
- 学習前baseline: 同じstrict warm startをselection4全windowで、augmentation/shuffleなし、
  eval modeで2回評価。lossのrtol1e-5/atol1e-7、count/ID完全一致を要求。
  差が大きければtrainingを始めず原因診断し、結果を見てtoleranceを緩和しない。
- Selector: 全selection windowで最小total loss、同値はearliest epoch。
  train lossやPublic scoreでは選択しない。best/last/resumeを区別する。
- 学習段階の数値gate案: best total lossが学習前baselineより相対1%以上低いこと。
  selection全window合計のbaseline total lossが0なら相対改善は定義できないため停止
  （便宜的なepsilonは加えない）。以下の個別動画/lineageのzero処理とは集計範囲が異なる。
  4動画中3動画以上でtotal lossが厳密に改善、各動画の相対悪化は2%以下、
  各lineage合計の相対悪化は0.5%以下。動画単位の差と不確実性も報告し、4動画を
  精密な汎化推定とは呼ばない。baselineの動画/lineage lossが0の場合は絶対悪化0のみ許容。
- 直交する非劣化確認: 既存proxy edge accuracyの低下がlineageごとに絶対0.002以下。
  さらにedge precisionとedge recallの低下がlineageごとにそれぞれ絶対0.005以下。
  TP/FP/FNを全windowで整数加算し、precision=TP/(TP+FP)、recall=TP/(TP+FN)。
  既存`_evaluate_pair`と同じ未pad領域、active_rows OR active_colsの注釈mask内だけを数え、
  softmax(dim=0)>0.5を予測正例とする。疎な未注釈領域を偽陽性として数えない。
  baselineまたはcandidateで必須指標の分母が0なら未定義としてgate FAIL。便宜的に0/1を入れない。
  これは改善量の上限ではなく、悪化方向のみの制限。動画別countsも必須とする。
  detector logit/検出座標の不変性は、同一inputをeval modeで再読出しして検査する。
  accuracyのclass imbalanceとdetector固定によるnode recall不変は既知なので、これらを
  最終tracking graphの改善やPrivate汎化の証拠とはしない。
- 終了後: 全artifactを`training_loss_gate.md`のcandidate verifierに通し、validation-only
  readbackと中断再開の連続実行一致を先に検証する。PASS前に診断artifactを昇格しない。
  最終tracking graph比較は前節どおり別processでGTなし生成→hash固定→公式metric。
  この学習gateを満たしても自動採用・自動提出とはせず、既存の評価/提出条件を適用する。

この案の閾値を既存v1/v2/v3へ遡及せず、新12動画のGT/モデル結果を見た後に変更しない。

### 4動画のreadout表現（GT内容読出し前に固定）

既存verifierへ各動画のbaseline lossと2%許容幅、厳密改善動画数3以上を別々の数値条件として渡す。
paired artifactの値は各動画の`candidate - (baseline + 0.02 * baseline)`とし、全て0以下を要求。
baseline0も除外せず、candidate0だけがこの条件を満たす。相対値のepsilon補完は行わない。
不確実性はこのloss許容幅に対する超過量の平均について、4動画から復元抽出する4^4=256通りを
全列挙し、95 percentile（linear interpolation）を記録する。上限0を要求するが、全動画の
超過量が0以下なら必ず満たすため、元の2%非劣化条件を変更しない。これは小標本retrospective
な許容幅超過量のreadoutであり、Privateの汎化区間や改善の有意性とは解釈しない。

### 独立レビューへの対応

Qwenは初回HOLD（数値契約の曖昧さ・class imbalance等）を返した。親はGT内容確認前に
上記の集計範囲明記とprecision/recall条件を採用した。zero動画を除外する提案は、
事前固定4動画を変えてしまうため不採用。個別baseline0は絶対悪化0で比較に残す。
全window集計のdenominatorをbatch1と同一視する指摘は不正確であり、実際のwindow数を
分母として記録する。当該reviewはコード実証ではない。

CPU/float64だけのresume検証はMPS/float32実行の証拠にならないため不採用。
synthetic fixtureの連続/中断再開比較とvalidation readbackは実際の実行device/dtypeで行い、
既定toleranceを満たせない場合は停止する。現在のCPU/MPS evaluate parity test成功は
resume検証の代わりではない。両lineageの悪化を制限する厳しい小標本screenであり、
各lineageで必ず改善する条件とは同一ではない（0.5%以内の悪化は許容している）。

親の判断: 上記で修正した契約の**実装着手は可**。取得完了・source/config/inputのpin・
candidate verifier・同device再開検証が未完了のため**実データ学習開始は不可**。
次の実装単位はcandidate用の実学習ループとartifact出力の接続であり、診断用機能の追加ではない。

### 実データ実行条件の充足（2026-09-22 JST、Issue #18）

上記は実装前時点の開始不可判断。後続でcandidate入口・artifact verifier・同device resume/
readbackを接続し、独立reviewの整合性指摘を修正・再確認した。MPS4testsもPASS。
取得recovery2は2026-09-21T18:59:33UTCに正常終了し、学習側verify_acquisitionでも
1,476files/5,103,093,406bytesと全local SHAを再検証した。files manifest SHA:
`1a9652ab24dfc2b37a530a23e3110861ef51acc70384881ea699b2695cdc9b6d`。
provider発行content hashとの照合を主張しない。ここまで新12動画GT内容は未読。

親判断: 既存ユーザーのlocal学習許可の範囲で、固定条件のrun
`frozen-association-20260922-v1`を開始可とする。既知の重いPython実行がないことも確認済み。
source/input snapshot・実coverage・学習前baseline再現は入口内で学習更新前に検証し、
不合格なら停止する。条件・動画を結果に合わせて変更しない。学習開始は候補採用や
提出許可判定の代用ではなく、終了後の既定gateと公式graph比較を引き続き必須とする。
