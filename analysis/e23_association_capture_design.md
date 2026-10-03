# D3 — E23 association観測経路の設計

2026-09-08。親単独。前回D2は全12公式行/全7591辺を検証したprogress。
今回はモデル改善を設計するための、既存upstreamの情報取得可能性を調べる。
E23対照、E26退役、E17のsource HOLD/取得予算を維持。新学習・提出・Kaggle起動はまだしない。

## 保存物とソースから確定したこと

- support13 Python filesは保存collection receiptと全byte/SHA一致。predict原本は
  `c44e771ba5980b820f93091e03a303c25dfe8f3232e501f54dc9565731c234b9`。
  `outputs/local/e17_source_diagnosis/support-python-v10-hcCz5l/`は静的読解のみ、import/実行しない。
- E23 notebook cell11のliteral patch10個（TTA/ensemble6/retention/bidir/coordinate）を
  文字列として各anchor1回だけ適用すると46,933bytes/1087行、SHA
  `8e7ac19e8b436d6777576b7ea2269464c4ed8842990b45448d40bf178f8f62de`。
  AST構文検証のみ。これは**前向き再構成source**で、旧hiddenで実行されたbyteの証明ではない。
- 現行raw36のsolution arraysは全node787883/edge730183でTrueだけ。
  detector coordinate manifestのnode910952より少なく、ILP後の選択済みgraphである。
  E13時点の「rawに全候補保存」は旧経路の記録で、現行へ流用不可。
- ローカルoutputs内にpair_probs/encoder embedding/pre-ILP候補表は発見できない。
  古いE9/E18解析scriptは残るが、top5のみ・確率小数6桁・座標grid・未保存を0扱いする仕様。
  次の機械可読入力としては使わず、欠損を確率0や負例にしない。

## 観測点と意味

| 保存する量 | 元sourceの観測点 | shape / 意味 |
|---|---|---|
| primary_forward_logits | 最初のmodel.predict_edges直後、harmonicより前 | (source,target)、未校正logit |
| primary_reverse_logits | reverse_logits_native.transpose(1,2)、校正より前 | (source,target)へ向きを統一した逆呼出しlogit |
| secondary_forward_logits | secondary_model.predict_edges直後 | (source,target)、primaryと同じdetector座標で取得 |
| mixed_logits | raw=edge_logits_pair[0]時点 | harmonic→secondary校正/mix後の現行スコア |
| mixed_probabilities | softmax(raw,dim=0)後・閾値選別前 | targetごとの親分布。source軸和1。元tensor/ndarrayをそのまま保存 |
| primary/secondary source/target features | 各model._index_featuresの戻り値 | 各endpointの32次元UNet特徴。追加モデル呼出し不要 |
| source/target global indices、座標 | idx_src/idx_tgt、c_src/c_tgt | Int64 ID、Int16のabsolute t + downsampled z/y/x |

secondaryはE23のlow_margin_consensusで、harmonic後primaryのmarginを使う。
単なる独立2モデルの確率平均と解釈しない。reverseもsource側へ再正規化/校正する経路であり、
保存した逆logitをそのまま独立な娘分布と呼ばない。

`_index_features`はnodeごとの固定特徴ではない。W=2の前後windowによって同じnodeが
target/sourceになるため、**dataset・frame pair・side別**に保持し、node単位へ勝手にdedupしない。
位置埋め込みは4軸×8=32次元、timeはwindow-relative。appearance特徴に位置embeddingは含めない。
原本のedge_distはdownsampled grid上のEuclidean距離で、µmではない。
次の観測metadataではdownsampleとphysical scaleを明記し、原スコア/距離を変更しない。

## 容量と実装範囲

既存raw36 producerの全100frame detector countから、全隣接pairの直積は341106074件。
最大frame-pairは682260要素、最大videoは6bba_3abfe10aの43217325要素。
5×float32 matrixは6,822,121,480bytes、2seed×2endpoint×32×float32 featureの
保守上限466,407,424bytes、合計7,288,528,904bytes（座標/ID/metadata/zip overhead別）。
これは既存検出数からの見積もりで、実際の新run完走や容量上限内を保証しない。
全dense matrixをframe pairごとにlossless npzで保存し、top-k切捨て/6桁丸め/float16化をしない。

最初の実装単位は`src/biohub/association_capture.py`のNumPy保存部と合成testのみ。
学習モデル/予測/ILP objective/CSV writerは変更しない。保存先は新run内、上書き拒否。
float32、有限値、shape/ID/時間方向、probability範囲と列和、完全なkey集合を確認する。
保存後に全arrayのdtype/shape/値を読み戻して照合する。pickle/object arraysは使わない。
入力arrayを変更せず、packet自身にdataset/frame-pair/downsample/scaleを保持する。
空pairは明示的なSKIPPED_EMPTYレコード。計算されていない特徴を0で捏造しない。

収集器の固定上限: 一pair1000000候補、各側2048nodes、全run450000000候補、
出力12GiB、累積保存部wall1200秒。超過はERRORで打ち切り、top-k等へ自動fallbackしない。
この上限は保存部のみ。Kaggle本体の時間/RAM/GPU上限を保証するものではない。
W=2以外、特徴次元32以外、dtype違いは未対応として拒否する。元モデルを暗黙変換しない。

自己レビュー/必須tests: 非正方matrixの向き、確率の正規化軸、未保存key/形状/NaN/型拒否、
先頭/末尾ID、入力非変更、空pair、同じnodeの別window特徴保持、既存run/同pairの上書き拒否、
exact roundtrip、個数/容量/時間上限、未完収集からCOMPLETEを発行しないこと。

## 次の統合単位（この保存部だけではKaggle実行不可）

1. E23の前向き再構成sourceへobserverだけを差し込み、元の全計算文を保つ。
   primary/reverse/secondaryの上書き前値をcloneし、モデル追加呼出し/乱数消費/計算順変更なし。
   暗黙のautocast/device変換をせず、targetで実dtypeを検証する。
2. 全36×99frame-pairの完備性と、空pairを含むdetector ID/座標を確認する。
   build_graphのbulk_add_nodes戻りID写像、全pre-ILP辺、選択後graphも別に保持して
   行indexをgraph node IDと仮定しない。collector単独ではこの統合を証明できない。
3. 合成予測経路のobserver OFF/ONでreturn coords/edgesと乱数状態が同一、
   さらに実Kaggleで既存E23 public4/固定raw参照とのparityを確認する計測手順を先に固定。
   不一致ならbaselineを取り替えず診断する。GTは予測processに渡さない。
4. asset/source/input/依存/全run時間・RAM・disk予算を固定し、既存外部操作条件を確認後、
   親が一回のKaggle収集を別判断する。巨大artifactの全量ローカルdownloadは前提にしない。

新候補は未確定。同じfused probabilityの再剪定ではなく、保存したseed/window別の情報に
有効な追加識別力があるかを検証してから、一因子仮説・疎GT label/ignore・Loss/採否gateを設計する。
E9〜E13の失敗を名前だけ変えて再試行せず、E17の外部rankerと混同しない。

## D3統合の前向き実装契約 — 2026-09-08 10:36 UTC

前回D3はsource/raw実体監査と保存部の実装を行ったprogress。直前の設定再確認は精度上の
progressではない。ユーザーgoal継続を受け、今回は観測hookとgraph写像を統合する。
元E23 notebook・隔離support・旧実験の登録sourceは変更しない。

- `association_observer.py` は予測側から明示的に渡す任意observer。無効時は追加処理なし。
  literal detector count計画、scale/downsample/W=2を確認。各pairで座標/ID、primary、
  reverse、secondary、最終mixedの順でdetach/CPU/copyし、計算用tensorを変更しない。
  空pairも元のcontinueの前で記録する。不足stageを別pairの値で補わない。
- 全detector座標が元の戻り値と一致すること、bulk_add_nodesの実IDとの一対一写像、
  閾値後・ILP前の全候補graph、ILP後の全選択graphを保存する。選択graphのnode/edgeは
  pre-ILPの部分集合であり、座標・確率・距離を変更していないことを検査する。
  graphの行順をIDと仮定しない。全候補を保存するがGT/採点/学習は扱わない。
- `association_instrumentation.py` はSHA固定済み前向き再構成textだけを受け、元の文の
  削除/置換をせず観測文と任意引数を挿入する。追加を取り除いたASTが元ASTに完全一致する
  検査を実装する。隔離supportのimport/実行はしない。
- 合成Torch/NumPy/graph fixtureでstageの順序、逆行列の向き、完全値、空pair、
  ID写像、部分集合、OFF/ONの戻り値とPython/NumPy/Torch CPU RNG不変をテストする。
  実sourceは静的検証のみであり、合成testを実GPUでのE23 parityと呼ばない。
- 保存部全体の12GiB/1200秒は維持し、各観測呼出しの終了境界で計測/判定する。
  これは同期処理の境界検査で、単一I/Oを途中で強制停止するhard timeoutではない。
  終了manifest自身のencode/writeは保存時間に含めず、対象の計測scopeを明記する。
  コピーの遅延を含めた実Kaggle全体予算とoff/on parity手順は起動前に別途固定する。

この統合が通っても推論実測・収集完了・精度改善・提出許可は未証明。実装を受入後、
public4での一回の観測parity計測を準備し、通過した場合のみ全36収集へ進む。

負荷probeを先に固定: ローカルで最大既知pairサイズ830×822だけを一回、固定seed23826の
合成float32 tensor/32特徴で観測する。新モデル/画像/GTを使わず、確率はsource-axis softmax。
全閾値後候補→実tracksdata graph→全選択のfixtureまで保存し、wall/peak self RSS/bytesを測る。
この1pairをGPU推論や36本全量runtimeの証明へ換算しない。fresh probe出力を保持する。

### この統合単位の結果

関連130 tests/2.13秒、Ruff/diff check PASS。親の全source/test自己レビュー済み。
最初の失敗14件の原因・修正は[実験台帳の10:45節](experiment_ledger.md)に記録。
静的差込みsourceはSHA `e2fda47e41d970a2c650bbbbb5fe068b6e1b9667fdd91cb59cc2a3ac8ba95a9c`、
元sourceへのbytes/AST復元一致。実コードを動かした結果ではない。
最大pairの合成probeはsession30364 exit0、wall0.44178620795719326秒、
peak self RSS464027648bytes、全出力13089910bytes、全artifact/source/test hash再照合済み。
実測receiptは`outputs/local/e23_association_observer_d3_20260908/`。

次の未完了はCLIからのobserver生成/finish接続と、実Kaggleのpublic4 OFF→ON parity。
上流モデル・環境・入力・参照座標・全run予算を固定してから一回の計測へ進む。
実36本の特徴取得、疎GT label設計、新学習/Loss監視、公式評価、候補提出はまだ先の段階。
今回の成功は収集器の実装受入であり、E23の精度やLBの改善ではない。

### 2026-09-08 11:14 UTC 訂正と次の実装受入

上記合成probeは誤ったthreshold0.10契約であり、実E23の閾値は0.48だった。
旧source/probeは保持し、観測器を0.48へ修正して0.10拒否を追加した。推論本体は不変更。
CLI接続・OFF/ON監督・固定4動画参照の準備は現在完了し、関連151 tests成功。
合成実装受入と実Kaggle parityは別で、実36収集は未着手。
現在の正しい値・固定予算・起動判断は[e23_association_target_parity.md](e23_association_target_parity.md)。
