# E26 D2の実測結果と次の設計判断

2026-09-08 10:06 UTC。親単独の診断・自己レビュー。
**D2A/D2B完了。E26不採用、E23 LB 0.924維持。金メダル目標は未達。**
新しい学習、Loss値、Kaggle提出、LB改善はない。

## 固定入力と完了証拠

設計は[D2診断契約](e26_d2_diagnostic.md)。E26 v2で既に採点済みの12動画のみ。
旧control/失敗runとそのsource snapshotは残した。ID列schema修正以外の変更なし。
nullable Int64を明示する回帰を含む160 tests PASS、Ruff/diff check PASS。
別の実GTを必要とする公式3testsはデータ未配置で失敗し、その後の合成検証から明示除外した。
公式全テストPASSとは報告しない。元公式実装はclean/read-onlyのまま。

成功run: `outputs/local/e26_diagnostic/d2b_eval12_v2_202609081002/`

| 保存物 | SHA256 |
|---|---|
| control.json | `3b3819759a402f5f174939cefdec29dae815b4a2eca322a737237964ef3061d8` |
| result/RESULT.json | `2df2b4c2d4cb3aad978358c52b66a893de147b4428816448b2775e090753d767` |
| parent_all_records_audit.json | `25a565890cf6b1b6e25cacd725bd2efa277b99519618ca2ab37624eacb3a451b` |
| parent_all_records_audit.command.txt | `ec36b432718f139d19f5f5735d5c92951033e40f75922a22ca8999be72f49f99` |

実行session56168はexit0。ラベルは`DIAGNOSTIC_COMPLETE_NOT_ADOPTION`、submission_authorized=false。
診断区間10.25451899995096秒、peak self RSS621,985,792bytes、result発行前出力16,619,405bytes。
RESULT自体37,489bytes。wall600秒/RSS4GiB/output250MiB内。hiddenの実行時間保証ではない。
全12のGT node/edge、両armの全pred node/edge、GT edge遷移で84artifactを保存。
parentは全hash/入力/sourceを再照合し、保存tableをCSVの全node値と全edge multisetへ戻して検証。
7,591 GT edge全個票の状態・対応端点・座標・edge有無・TP遷移・集計を再計算した。
対応node数/GT node数も保存公式recallと完全一致。GT再matchingや新予測は監査で行っていない。

## TPの増減は少数の損失を隠していた

| dataset | 両方TP | 失われたTP | 新たなTP | 両方FN | TP純増 |
|---|---:|---:|---:|---:|---:|
| 44b6_12dfb391 | 735 | 9 | 2 | 27 | −7 |
| 44b6_267148e4 | 247 | 7 | 12 | 11 | +5 |
| 44b6_2a2eff9f | 196 | 4 | 3 | 7 | −1 |
| 44b6_341df25f | 203 | 3 | 0 | 3 | −3 |
| 44b6_587a1e22 | 353 | 1 | 11 | 6 | +10 |
| 44b6_5f15d135 | 246 | 5 | 5 | 17 | 0 |
| 6bba_062c8d37 | 883 | 0 | 6 | 9 | +6 |
| 6bba_07e24132 | 308 | 4 | 6 | 27 | +2 |
| 6bba_085bf656 | 1161 | 0 | 0 | 7 | 0 |
| 6bba_09961292 | 1763 | 9 | 22 | 77 | +13 |
| 6bba_0e7c0d07 | 168 | 6 | 16 | 8 | +10 |
| 6bba_12665c0e | 936 | 6 | 28 | 28 | +22 |
| 合計 | **7199** | **54** | **111** | **227** | **+57** |

全24armの全公式per-sample列は、元E26の保存行に完全一致。
総edge TP/FP/FN=7253/370/338→7310/256/281、division TP/FP/FN=4/16/14→4/16/14。
node 250465→247277、edge 240852→236613の全記録を保持した。
個別combined/系統別/aggregateは[E26本体の結果](e26_screen_readout_and_d2_design.md)を参照。

| 損益が発生した側のFN状態 | TP損失54の候補側 | TP獲得111の基準側 |
|---|---:|---:|
| 両端対応済み、対応端点間にCSV edgeなし | 35 | 88 |
| 両端ともGT未対応 | 12 | 9 |
| sourceのみGT未対応 | 3 | 7 |
| targetのみGT未対応 | 4 | 7 |
| CSV edgeはあるが公式TPではない | 0 | 0 |

接続欠損35/88のうち両armで同じsubmitted端点IDがGTに対応するのは17/75。
残る18/13はGTに割り当てられた予測のIDが変わっている。全損益を単純な辺の削除/追加とは呼ばない。
同一IDだけで生成nodeの物理的同一性を断定せず、t/z/y/xも個票へ保持した。

最悪`44b6_341df25f`ではGT edge ID1/4/7の3辺がすべて両端未対応へ変化。
これはt=0→1→2→3の4つの連続GT nodeの鎖である。基準の対応submitted IDは
30→135→239→342、候補最終CSVには4 IDとも存在しない。
したがって単に既存ノードのmatching先だけが変わったケースではない。
ただしraw/中間stageの完全traceが無いので、「短track filterがこの4nodeを落とした」とまでは
断定しない。出力収支の短track削除増という観測と、個別stage因果は分ける。

## 設計判断 — E26を救済せずE23の接続誤りへ戻る

E23の338 FN中、205は両端検出がGT対応済みで接続なし、133は少なくとも片端が未対応。
E26はこの内訳を153/128へ変えたが、正しい54辺を失い、既定worst gateと実LBの双方で不採用。
「motionを全廃すればよい」「検出を増やせばよい」のどちらも結果は支持していない。
短track長・motion blend/bonus/radiusを、この12本の損失を救うために再調整しない。
とくに最悪の境界近傍4nodeだけに合わせた救済規則を追加しない。

次の設計対象は、**E23を対照に、検出済み細胞の接続候補を別情報で見分ける**方式。
既存E17の取得予算/HOLDを解除したり、同じ候補名で独自実装へ置換したりしない。
まだ新候補の数値条件・学習・推論を実行したわけではない。

### 次の実装単位D3 — upstream候補情報の取得可能性を確定する

1. 既存notebookとsupport sourceだけから、pre-ILPのcandidate source/target ID、各seedの
   association probability、distance、encoder/appearance特徴をどのstageで保存可能か確認する。
   解済みraw GEFFから棄却済み候補を復元したことにしない。既存archiveを一度棚卸しする。
2. 診断用に過去のE23 GT対応を使う場合、正例は公式GT edge、負例は疎GTで矛盾が確定する候補、
   未対応/未注釈はignoreとして設計する。source出次数2を負例化せず、target側の親選択と
   division側の二娘選択を混同しない。この概要だけで学習labelを生成しない。
3. 保存特徴が不足する場合は、同一のE23推論で必要な表を保存する一回のKaggle計測を設計する。
   before/afterでbaseline予測byte不変、全候補/欠損率/shape・単位、時間/RAM/disk上限を先に固定。
   結果を取得してから特徴定義や対象動画を変更しない。
4. 学習型の新候補を作る前に、候補集合の正解被覆・動画分割/上流重みの露出を確認する。
   学習時はtrain/validation Loss、非有限値、best/last checkpointを記録する。
   既露出12/36を独立holdoutと呼ばず、探索提出と採用判断を分ける。

D3は単独で行う。GT24・新モデル・Kaggle計測・提出は、この棚卸しから自動起動しない。
利用可能性を確認後、親が新しい一因子仮説と数値gateをここで設計する。

2026-09-08 10:45 UTC追記: D3棚卸しと合成観測器の実装・自己レビューを完了。
現行rawはILP選択済みで棄却候補を含まないことを実物から確認した。
実モデルの値をlossless保存するhook/graph写像を用意し、関連130 testsと合成最大pairの
保存probeが成功。実Kaggle収集/学習/採点はまだ行っていない。
次はCLI bridgeとpublic4の観測OFF/ON確認。[D3の現行設計](e23_association_capture_design.md)を参照。
