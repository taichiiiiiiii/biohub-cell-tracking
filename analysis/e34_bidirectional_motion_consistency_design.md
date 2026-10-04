# E34 事前設計 — bidirectional motion-consistency gate

更新日: 2026-09-13 (Asia/Tokyo)

## 仮説（1つ）

E29〜E32は上流のdetector consensusの選別方法を変え、E33は短い連結成分の除去境界を変えたが、現在の `motion_relink_edges` が時系列を一方向に処理することは検証していない。forwardでは局所的に最小コストでも、次時刻から見ると不自然なidentity swapを採用し得る。

E34では **baselineが選んだmotion-relink辺だけ**を対象に、同じ固定コスト・同じtight/relaxed gate・同じ一対一制約で時系列を逆向きにも解き、逆向き割当でも同じraw node pairが選ばれた辺だけを残す。前後の運動制約を同時に満たす辺に限定すれば、局所swapを減らしedge precisionを上げられる可能性がある。

これはconsensusの候補集合・logit符号・soft bonus・short-track長を変更しない、motion relinkの方向対称性だけを検証する単一仮説である。

## 固定条件と対象

- E23/E27 baselineのraw/filtered edge、detector、後続gap/division/filter、設定値を固定する。
- E29〜E33のappearance/consensus loaderおよびshort-track rescueは併用しない。
- forward runで得た `motion_relinked=1` の辺だけを候補にし、既存選択辺を新規追加しない。
- reverse passは同一の距離、velocity weight、learned probability、bonus、tight/relaxed gateを使う。新しい閾値、学習、追加データ、追加GT、探索的係数調整は行わない。
- reverse passは入力node/edge、行順、ID、座標を変更しない。元辺にないpairを返さず、division由来の辺やgap/synthetic辺を対象にしない。
- 逆向き計算の入力不整合（node ID/time、型、重複、範囲、非有限値、active transition、一対一制約）または計算例外が1つでもあれば候補を生成せずbaseline出力へfail-closedする。逆向き割当が空のtransitionも、そのtransitionのbaseline辺を消さずbaselineへ戻す。
- 逆向きで確認できた辺が0本の場合は科学的に無効とし、non-improvementカウントを増やさない。確認済み辺がある場合のみ物理評価を有効とする。

## 採否基準（評価前固定）

固定known12の公式paired meanがbaseline比 `>= +0.005`、paired median `>= 0`、各動画のworst gate、node/edge/divisionの追跡評価、リーク検査、CPU serial実行、再現実行、CSV形式、receipt/result/candidate SHA bindingを全て通過した場合のみ提出候補へ昇格する。それ以外はE34の有効な非改善として台帳に記録し、提出しない。明示承認なしのKaggle送信は行わない。

## 実装・検証計画

1. まずQwen Cloud `qwen3.8-flash` にbounded patchを依頼する。対象はgraphのreverse-consistency helper、既存pipelineのE34専用接続、runner/receipt/supervisorの識別、直接テストに限定する。
2. 親は差分をレビューし、baseline/E29〜E33経路の不変、fail-closed、pair集合の一対一性、入力不変性、空逆割当のbaseline parityを合成テストで確認する。
3. 本変更は複数moduleかつprivate scoreに直接影響するため、Flash実装後の独立評価はQwen Cloud `qwen3.8-max`を1回だけ依頼可能とする（Flashが同一変更を2回失敗した場合も同じ上限）。親が最終採否を決める。
4. テスト・Ruff・diff check成功後、固定known12を監督付きCPU serialで一度だけ実行し、成果物bindingと公式metricを検査する。

E33終了時点で有効な連続非改善は7/8であるため、E34が有効な非改善なら科学的探索を停止する。E34の実験結果と停止理由は台帳へ追記する。
