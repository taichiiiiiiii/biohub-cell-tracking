# Twin-only structural rewire 設計

Updated: 2026-08-30 (Asia/Tokyo)

## 結論と事前登録する単一候補

最初に実装・評価するのは `twin_only_v1` だけである。E23 の
orphan-only safe-division を先にそのまま実行し、そこで fork にならなかった
mid-track 親 `P` と、同時刻に近接する track-start 親 `Q` が別々に
1 娘 `A,B` を持つ場合に限り、`Q→B` を `P→B` へ付け替える。

E7 の real steal 19 対は、13 対で現親 `Q` が GT 未マッチ、残る 6 対が
3 division の相互 twin だった。しかしこれは事後的な設計 prior であり、
`Q` が track-start であることも `Q→B` が誤りであることも保証しない。
`twin_only_v1` は「二重化した親候補が娘を 1 本ずつ所有した」という
狭い因果仮説だけを検証する。

`disposable_steal` は v1 に含めない。相互 twin でない一般の
one-edge donor から娘を奪うことは、valid continuation を切る別の edge-risk
仮説である。将来候補 `disposable_steal_v1` として明示的に **blocked** とし、
twin-only が失敗しても条件緩和として実行しない。別の事前登録、分離した
評価、valid-donor 切断の損失仮説が必要である。

これは gold strategy 全体ではなく、最初の bounded causal candidate である。
不発火または gate 失敗時は、E17 association ranker、検出/recall 改善、
frozen-encoder の two-child/division head の候補列に戻る。

## 根拠、metric と限界

- 公式 score は `adjusted_edge_jaccard + 0.1 * division_jaccard`。採否は
  [`src/biohub/evaluate.py`](../src/biohub/evaluate.py) が直接呼ぶ公式
  `per_sample_metrics` / `summarise` だけで行う。
- E7 eval-12 の GT division 18 件は `steal_needed=10 / orphan_recoverable=4 /
  daughter_undetected=3 / already_fork=1`。orphan 追加だけでは回収上限が低い。
- E7 の旧 `div_rewire.py` は twin 149 + adopt 8 + steal 16 の 173 編集で
  eval-12 `+0.0013`、division TP `2→3`、FP `23→31`、adjusted edge 変化なしだった。
  機構は動くが、近接 5 um + CNN rank だけの twin は過剰発火した。
- E15-b は誤 fork の edge FP 1 本が小分母動画を `-0.02` 級壊す事例を
  eval-12/eval-24 で再現した。division FP だけの損益計算は禁止する。
- 2 successor と divergence は precision を高める構造 heuristic であり、
  official division TP の必要条件でも十分条件でもない。公式 metric は
  GT parent/predecessor、2 娘と successor の局所窓で枝別 matching を行うが、
  その仕様からこの gate の正当性を導かない。
- 本 gate が false reject する真 division には、動画終端で `t+2` がない、
  娘が occlusion/gap/短い track で継続を失う、平行または一時的に収束して
  2.25 um 未満、関連付け誤りで successor が共有される、gap-synthetic を
  含む、DeepCenter が低信頼/位置ずれ、近傍親が同率、がある。
- external `.933` は再現 anchor であり、twin の因果証拠ではない。
  public-four も in-sample parity diagnostic であり採否に使わない。

## 現状と実装前のハードゲート

`develop@5907d08` には E23 all-node centroid refinement と pipeline 呼び出しが
land 済みである。「centroid が未接続」という旧記述は誤りである。一方、
E23 parity の active work は Phase 3 structural safe-division と Phase 4 DeepCenter
gap semantics で、まだ最終 parity 受入済みではない。従って次を全て満たすまで
twin-only の metric 結果を読まない。

1. Phase 3/4 完了後、E23 notebook oracle と local port が同一 raw GEFF で
   node ID、丸め後座標、directed edge、fork、per-video official input、許可された
   telemetry 以外に完全 parity する。
2. `base1` の出力は byte-identical、`e23` は固定 parity artifact と完全一致する。
3. off と dry-run は node/edge/coordinate と入力 list/dict object を変更しない。
4. eval36 raw bundle は 36 GEFF roots、1,188 files、**10,090,215 bytes** であることを
   manifest で再確認する。

参照手順は [E23 parity runbook](e23_parity_runbook.md)、運用境界は
[gold-loop protocol](gold_loop_protocol.md) を一次仕様とする。

## 不変 pre-rewire snapshot と検証

rewire は E23 safe-division 後、下流 pass 前の graph から一度だけ
immutable snapshot を作る。snapshot は node を `node_id` 昇順、edge を
`(source_id,target_id,input_position)` 昇順で保持し、そこから predecessor/successor、
degree、frame pool、距離を構築する。候補受理のたびに作業 graph を再読取せず、
受理済み編集は conflict/cap のみに反映する。
snapshot の node/edge は元 dict への reference ではなく、検証済み scalar の
read-only copy とする。入力 list/dict とその嵌め込み metadata を候補列挙や
dry-run で mutate しない。

候補列挙前に video 全体を次の順で検証する。失敗時はその video を
fail closed し、グラフに一切変更を加えない。

1. node ID が一意な整数、`t,z,y,x` が存在して全て finite、`t` が整数。
2. edge 端点が存在し dangling edge なし、`(source_id,target_id)` の duplicate なし。
3. 全 edge が `t→t+1`、`indegree<=1`、`outdegree<=2`。設計内で修復しない。
4. 距離計算結果が finite。voxel scale は `(z,y,x)=(1.625,0.40625,0.40625) um`。

各 frame に物理座標の spatial index を 1 回構築し、半径 query でのみ
`P/Q` 候補を作る。フレーム内ノードの全組合せや、旧 E7 のような
100 万対級の brute-force enumeration は禁止する。index の返却順に依存せず、
近傍結果は必ず `(distance,node_id)` で sort する。

## Exact `twin_only_v1` motif

時刻は `t(P)=t(Q)=t`, `t(A)=t(B)=t+1`, `t(A2)=t(B2)=t+2` とする。
`pred(X)`/`succ(X)` は degree 1 の場合のみ唯一ノードを返す。

### 固定 pool と相互 unique nearest

各 frame `t` で snapshot から次の sorted pool を作る。

- `P_pool[t]`: `indegree(P)=1`, `outdegree(P)=1`, `succ(P)=A`。
- `Q_pool[t]`: `indegree(Q)=0`, `outdegree(Q)=1`, `succ(Q)=B`。

`P_pool`, `Q_pool` と各 successor list は node ID 昇順に固定する。各 `P` を
一度ずつ source とし、同 frame に `Q` が 1 つ以上あるときにその `P` を
1 enumerated record とする。spatial index で `P` から最近の `Q` と、その
`Q` から最近の `P` を求める。各向きで最短距離から `1e-9 um`
以内のノードが 1 つだけ、かつ互いを選んだときにだけ mutual unique とする。
`P` 側の同率は `ambiguous_p_nn`、`Q` 側の同率は `ambiguous_q_nn`、
一意だが相互でない場合は `not_mutual_parent_nn` とし、ID で勝者を作らない。
`d(P,Q)<=5.0 um` も必須である。nearest query 自体は全対列挙せず、
5.0 um を超えるときは `distance_twin` で打ち切る。

### eligibility

enumerated `P` ごとに、`distance_twin`、`ambiguous_p_nn`、
`ambiguous_q_nn`、`not_mutual_parent_nn` の順で nearest gate を評価する。
mutual unique `P,Q` だけに対し、以下を記載順に評価し、最初の
失敗理由で打ち切る。

1. E23 safe-division 後も `outdegree(P)=1`, `succ(P)=A`, `indegree(P)=1`、
   `d(P,A)<=10.0 um`。既存 fork は触らない。
2. `indegree(B)=1`, `pred(B)=Q!=P`, `outdegree(Q)=1`, `succ(Q)=B`。
   `Q→B` 削除後の `Q` は isolated になる。
3. `A!=B`, `P→B` は存在せず、`d(P,B)<=8.0 um`、
   `5.5<=d(A,B)<=11.0 um`。
4. `outdegree(A)=outdegree(B)=1`、`A2=succ(A)`, `B2=succ(B)`、
   `A2!=B2`、全時刻が上記定義と一致する。
5. `d(A2,B2)-d(A,B)>=2.25 um`。
6. `P,Q,A,B,A2,B2` のいずれも `gap_synthetic=1` ではない。
7. 下記の strict DeepCenter node-existence veto が `B` を accept する。

radius の上下限は包含する。距離と divergence が nonfinite なら候補 reject、
snapshot 全体の基礎座標/エッジ不正なら video fail-closed とする。

### Strict DeepCenter veto

E23 と同じ exact `best.pt` epoch 2 と threshold `0.12` を使う。pipeline が持つ
共通 `frame_cache` と `(dataset,t)` 単位の共通 heatmap cache を safe-division と
twin-only で再利用し、候補ごとに frame/model inference を繰り返さない。

`B` の判定は fail closed とする。detector bundle なし、dataset なし、
checkpoint/epoch/config 不一致、frame read 失敗、heatmap が missing/empty/nonfinite、
patch が empty/nonfinite、raw score が missing/nonfinite、または score `<0.12` はすべて
reject である。例外を accept へ倒さない。raw score は debug record に保存するが
sort/rank/conflict resolution に使わない。この frozen model score は `B` という
検出ノードの存在を veto するだけで、division らしさ、`P→B` の association、
または donor の誤りをスコアするモデルではない。

## Conflict resolution と pure mutation

全 eligibility 候補を immutable snapshot から一度列挙し、次の完全な key で
stable sort する。

```text
(
  d(P,B) + 0.15 * d(A,B),
  -(d(A2,B2) - d(A,B)),
  d(P,Q),
  P, Q, A, B, A2, B2,
)
```

先に受理した候補と `{P,Q,A,B,A2,B2}` の 1 ノードでも共有すれば
`conflict` reject とする。各 frame 最大 1、各 video 最大 2 受理とし、cap は
sort 後の受理数に対してかける。dict/CSV/spatial-index 返却順に依存しない。

受理 1 件の pure mutation は厳密に次の 2 操作だけである。

```text
remove(Q→B)
add({source_id: P, target_id: B,
     distance_um: recomputed d(P,B), edge_prob: None})
```

新 edge の `distance_um` は編集時の immutable node 座標から再計算する。
donor `Q→B` の `edge_prob` や他親の probability はコピーせず `None` とする。
削除後の入力 edge 順を保ち、新 edge を acceptance 順に append する。

downstream pass に渡す直前の pure-mutation boundary で、受理数 `k` に対して
次を assertion する。

- node ID/set/coordinate/metadata は snapshot と完全一致。
- edge 数は不変、`removed == added == k`、edge-set symmetric difference は厳密に `2k`。
- 無関係成分と非受理候補の edge metadata は不変。
- duplicate/dangling なし、全 edge `t→t+1`、`indegree<=1`、`outdegree<=2`。

この `2k` 不変量を最終 CSV に要求しない。後続 isolated prune は `Q` を削除し、
short-track filter はその他成分を削除し得る。linefit は座標を変える。従って
end-to-end では baseline/candidate それぞれの最終 `num_nodes`, `num_edges`,
`fork_sources`, `coordinate_changed_nodes`、及び delta、rewire 後 prune/short-track の
node/edge 削除数を別の telemetry として保存する。

## 正確な pipeline 順序

`twin_only_v1` は次の順序以外に接続しない。括弧内の E23 inert pass も
順序から省略しない。

1. all-node centroid refinement
2. raw edge の dangling/time/distance filter
3. motion relink
4. single-parent repair
5. single-child repair（E23 で off/inert）
6. single-frame gap close
7. strict gap2（E23 で off/inert）
8. E23 orphan-only safe divisions
9. **twin-only rewire**
10. division geometry filter（E23 で off/inert）
11. isolated-node prune
12. short-track filter（adaptive rescue は E23 で off/inert）
13. linefit smoothing

これにより E23 orphan repair を優先し、それが作った fork を上書きしない。
centroid refinement 後の共通 frame cache と safe-division の共通 DeepCenter heatmap cache を
step 9 へ渡す。

## Config と preset 契約

`base1`/`e23` の default は変えない。新 profile は `e23_twin_only_v1`、mode は
`twin_only_v1` とする。プリセットは必ず `E23_PRESET` の exact extension とし、
実装と test で次の whitelist 以外の effective config diff がないことを assertion する。

```text
TWIN_ONLY_V1_PRESET = {
  **E23_PRESET,
  <the BIOHUB_STEAL_TWIN_* values below>,
  BIOHUB_EXPERIMENT_TAG=e23_twin_only_v1,
}

whitelist = all BIOHUB_STEAL_TWIN_* fields + {EXPERIMENT_TAG}
diff(asdict(build_config(profile="e23")),
     asdict(build_config(profile="e23_twin_only_v1"))) == whitelist
```

| control | v1 | purpose |
|---|---:|---|
| `BIOHUB_OUTPUT_STEAL_TWIN_REWIRE` | `1` | master switch |
| `BIOHUB_STEAL_TWIN_MODE` | `twin_only_v1` | exact semantics/version guard |
| `BIOHUB_STEAL_TWIN_DRY_RUN` | `0` | telemetry only, graph identity |
| `BIOHUB_STEAL_TWIN_PARENT_MAX_UM` | `8.0` | `P→B` gate |
| `BIOHUB_STEAL_TWIN_EXISTING_CHILD_MAX_UM` | `10.0` | `P→A` gate |
| `BIOHUB_STEAL_TWIN_SISTER_MIN_UM` | `5.5` | E6 census lower bound |
| `BIOHUB_STEAL_TWIN_SISTER_MAX_UM` | `11.0` | E23 upper bound |
| `BIOHUB_STEAL_TWIN_DIVERGE_UM` | `2.25` | two-generation precision heuristic |
| `BIOHUB_STEAL_TWIN_TWIN_MAX_UM` | `5.0` | mutual parent radius |
| `BIOHUB_STEAL_TWIN_REQUIRE_TWO_SUCCESSORS` | `1` | exact v1 gate |
| `BIOHUB_STEAL_TWIN_REJECT_SYNTHETIC` | `1` | no synthetic evidence |
| `BIOHUB_STEAL_TWIN_DEEPCENTER_VETO` | `1` | strict node-existence veto |
| `BIOHUB_STEAL_TWIN_FRAME_CAP_ABS` | `1` | local damage cap |
| `BIOHUB_STEAL_TWIN_VIDEO_CAP_ABS` | `2` | video damage cap |
| `BIOHUB_STEAL_TWIN_DEBUG_JSONL` | empty | explicit opt-in path only |
| `BIOHUB_STEAL_TWIN_DEBUG_MAX_RECORDS` | `200` | hard per-run record cap |

bool gate の無効化、半径/threshold/cap 変更、DeepCenter を ranker として使う arm は
v1 ではない。`disposable_steal` 用 config は v1 に追加しない。

## Telemetry contract

### 保存カウンタ

`run_stats.csv` に dataset ごとに次を integer で保存する。

- `steal_twin_examined_frames`, `steal_twin_p_pool`, `steal_twin_q_pool`
- `steal_twin_enumerated`
- first-failure rejection: `distance_twin`, `ambiguous_p_nn`, `ambiguous_q_nn`,
  `not_mutual_parent_nn`, `distance_existing_child`, `distance_parent`,
  `distance_sister_low`, `distance_sister_high`, `time`,
  `missing_successor`, `shared_successor`, `divergence`, `synthetic`,
  `deepcenter_bundle`, `deepcenter_dataset`, `deepcenter_frame`, `deepcenter_heatmap`,
  `deepcenter_nonfinite`, `deepcenter_threshold`, `conflict`, `frame_cap`, `video_cap`
- `steal_twin_eligible`, `steal_twin_accepted`, `steal_twin_edges_removed`,
  `steal_twin_edges_added`, `steal_twin_isolated_donors`
- `steal_twin_validation_failed` と validation reason別 counter
- pure-mutation 直後と final output の node/edge/fork/coordinate counters 及び baseline delta 用 fields

`examined_frames` は `P_pool` または `Q_pool` を含む時刻の異なり数とし、
フレームの多重 query 数にしない。`enumerated` は同 frame に `Q` が
1 つ以上ある `P` の数である。各 enumerated 候補は固定した nearest/eligibility
順序の **最初の 1 失敗理由**、または eligible 後の accepted/conflict/frame_cap/
video_cap のいずれか 1 つだけに入る。次を dataset ごとに assertion する。

```text
enumerated == sum(all_first_failure_reasons) + eligible
eligible == accepted + conflict + frame_cap + video_cap
edges_removed == edges_added == accepted
accepted <= examined_frames
accepted <= video_cap
```

validation fail-closed は enumerated 前なので上記 conservation と混ぜない。

### bounded debug JSONL

JSONL は `BIOHUB_STEAL_TWIN_DEBUG_JSONL` に明示 path を与えたときだけ書く。
採否 run の標準 path は
`outputs/local/steal_twin/<immutable_run_id>/rewire_debug.jsonl` とし、run manifest で
完全な path と SHA256 を固定する。dataset 昇順、上記 sort key 順に書き、
accepted または resolution-rejected (`conflict/frame_cap/video_cap`) の record だけを
対象とする。eligibility reject の全件ダンプは禁止する。hard cap 200 を超えた
分は書かず `debug_records_dropped` に数え、この counter も保存する。

各 record は dataset、decision/reason、`P/Q/A/B/A2/B2`、完全 sort key、
5 距離、divergence growth、DeepCenter raw score/threshold/decision、編集前後 edge を持つ。
JSONL は診断用であり metric/adoption input にしない。

## Metric 損益仮説

1 編集は pure boundary の edge 数を一定に保つが、公式 edge TP/FP/FN は一定ではない。

| latent case | delete `Q→B` | add `P→B` | expected edge effect |
|---|---|---|---|
| `Q` unmatched, `P/B` correctly matched | invisible or FP removal | TP | nonnegative, often positive |
| duplicate `P,Q` compete for one GT parent | duplicate/wrong edge removal | second-daughter TP | owner selection が正しければ非負 |
| `Q→B` is a true continuation | TP removal | FP/wrong edge | severe negative |
| all relevant nodes sparse-GT unmatched | invisible | invisible | edge-neutral, division FP の危険 |

E7 の「13/19 はほぼ無料」は prior に過ぎず、現行 metric 下での不可視性を
保証しない。v1 の ambitious な仮説は「eval36 で division TP を 4 件以上
純増しつつ、adjusted edge、combined score、division Jaccard を同時に守る」である。

## Tests required before reading scores

### Unit/property tests

- master off で base1/e23 の node/edge/stats common fields が一致。dry-run も graph identity。
- 最小 eligible twin で `Q→B` だけを削除し `P→B` だけを追加。
- non-twin disposable donor は、他の条件が良くても v1 で必ず reject/非列挙。
- invalid node、nonfinite、dangling/duplicate edge、非連続 edge、degree 違反で video fail-closed。
- 各距離境界、`1e-9 um` tie、missing/shared successor、divergence
  `2.25-eps/2.25/2.25+eps`、synthetic、全 DeepCenter failure mode、conflict/cap。
- 新 edge は `distance_um` 再計算、`edge_prob is None`、donor probability 非コピー。
- node/edge/dict/spatial-query 順を random permutation しても edge set、accepted IDs、
  first-failure telemetry、JSONL bytes が不変。
- idempotence、pure-boundary `2k`、無関係成分不変、graph invariant。
- 共通 frame/heatmap cache により同じ `(dataset,t)` の read/inference が 1 回。
- candidate profile と exact E23 preset の config diff が whitelist と一致。
- end-to-end fixture で downstream prune/short-track/linefit delta と pure `2k` を混同しない。

### Parity and official-metric tests

- twin code より先に E23 parity suite を off で通す。
- 小 GT/pred fixture を `score_submission` に通し、正しい rewire と valid donor
  切断の反例を公式 edge/division metric で評価する。独自 proxy で代用しない。
- eval manifest で raw input tree hash、baseline/candidate code SHA、profile、effective config、
  output schema、dataset set、JSONL hash、command を固定する。

## Frozen retrospective staged falsification

### 独立性に関する制約

eval12 と eval24 は過去の候補設計・分析・意思決定ですでに使われている。
従ってどちらも holdout ではなく、その非重複性も独立確認や一般化性能を
証明しない。eval36 も両者の roll-up であり、第 3 の validation set ではない。
この手順ができるのは、今ここで仕様を凍結した候補を段階的に falsify し、
無意味または危険な候補を早く止めることだけである。結果を見て v1 を調整しない。

eval12 は次の 12 本、eval24 は残る 24 本に固定する。

```text
eval12:
44b6_12dfb391 44b6_267148e4 44b6_2a2eff9f 44b6_341df25f
44b6_587a1e22 44b6_5f15d135 6bba_062c8d37 6bba_07e24132
6bba_085bf656 6bba_09961292 6bba_0e7c0d07 6bba_12665c0e

eval24:
44b6_706092f0 44b6_74d0c52e 44b6_7a302da0 44b6_996155de
44b6_9be80b04 44b6_a21120c2 44b6_aaf8b0ea 44b6_c50204e0
44b6_c8e2a523 44b6_d2f34f90 44b6_d5e7d891 44b6_d754aa59
6bba_1d0d8384 6bba_207c6aaf 6bba_20852818 6bba_2312ac41
6bba_268e1230 6bba_2819ca14 6bba_32db13fc 6bba_337b1b3a
6bba_3abfe10a 6bba_3c5691b6 6bba_3db54e20 6bba_3fda6b25
```

public-four dummy は全 gate から除外する。

### Readout

baseline/candidate の各 video で official `per_sample_metrics` の 1 row を作り、
それを 1-row list として official `summarise` に渡す。per-sample の全 count、
`num_pred_nodes`、node recall、edge/division Jaccard、adjusted edge と、1-row
`summarise` の combined score を丸めない full precision で JSON/CSV に保存する。
表示のみに丸め値を使う。

全 36、eval12、eval24、`44b6`、`6bba` のそれぞれで、baseline と candidate
の row に official `summarise` を別々呼び、後から summary の差を取る。
per-video `score` delta の mean/median/worst も別に報告する。独自の
summary 式で official micro aggregate を再実装しない。

### Staged gates

1. **Parity/dry-run:** E23 parity、off identity、dry-run identity、全 test が通る。
2. **eval12 falsification:** paired mean score delta `>=+0.005`、median `>=0`、
   worst `>=-0.002`、official aggregate adjusted-edge delta `>=-0.002`、両系統の
   official aggregate score delta `>=0`。一つでも失敗で reject。
3. **eval24 staged falsification:** 同一の frozen bytes/config を 1 回適用。paired mean
   score delta `>=+0.003`、median `>=0`、worst `>=-0.002`、official aggregate
   adjusted-edge delta `>=-0.002`、両系統の official aggregate score delta `>=0`。
   これは非重複でも独立 confirmation とは呼ばない。
4. **eval36 roll-up/adoption:** 上記に加え、official aggregate division TP 純増
   `>=4`、adjusted-edge delta `>=-0.002`、**combined score delta `>=0`**、
   **division_jaccard delta `>=0`**、median `>=0`、worst `>=-0.002`、両系統の
   aggregate score delta `>=0`。全条件で初めて adoption candidate とする。

候補数、幾何分布、DeepCenter score、public-four、external `.933` overlap は診断であり
採否条件ではない。LB 照会は adoption gate 後に別途承認を得た 1 回だけで、
この仕様は push/submit を許可しない。

## Runtime/RSS feasibility gate

official metric を読む前の eval36 dry-run と、baseline/candidate の eval36 実行で、
同一 machine、cold process、同一 raw/image/artifact、`PYTHONHASHSEED=0` を使い、
wall-clock と OS が報告する peak RSS を manifest に保存する。個別 frame/candidate 数とともに
最遅 video も保存し、cache 効果を隠さない。

- candidate eval36 wall time は E23 baseline の `1.25x` 以下。
- candidate peak RSS は baseline `+1 GiB` 以下、かつ target job の宣言 RAM の
  `80%` 以下。宣言 RAM が不明なら gate は未成立。
- hidden 約 200 video の保守外挿は `T_hidden = T_eval36 * 200/36`。これが
  target Kaggle session の宣言 wall-time limit の `80%` 以下でなければ reject。
- スケーリング sanity check として enumerated pair 数と runtime を video/frame node 数に
  対して報告し、全親×全親の二次列挙がないことを確認する。

どの feasibility bar にも失敗したら、同じ raw 入力に対する exact `e23` profile を
fallback とし、twin を本番経路に入れない。半径を狭めて実行時間を合わせるのは
v1 の事後調整なので行わない。

## Bounded implementation phases

E23 parity の Phase 0–4 と混同しないよう、rewire 作業は `ST-R0`–`ST-R4` と呼ぶ。
各 phase は別 diff とし、SOL が全 diff を読み、focused tests/ruff を再実行してから次へ進む。

1. **ST-R0 — prerequisite audit only:** `develop@5907d08` の centroid landed を確認し、
   active E23 parity Phase 3/4 の land/review/parity artifact を待つ。twin code を書かない。
2. **ST-R1 — pure candidate engine + telemetry:** immutable validator/snapshot、sorted pools、
   spatial index、exact eligibility、strict veto、sort/conflict/cap、first-failure telemetry、
   bounded debug と unit/property tests。pipeline には dry-run でのみ接続。
3. **ST-R2 — mutation adapter:** remove-one/add-one、metadata contract、pure `2k` invariant を
   実装し、safe-div 後/prune 前に opt-in 接続。base1/e23/off parity を再確認。
4. **ST-R3 — official evaluation harness:** immutable manifest、dataset assertion、official
   per-video rows / `summarise`、full-precision `num_pred_nodes`、gate の機械判定、
   wall-time/peak-RSS 計測を実装。
5. **ST-R4 — local artifacts, no retuning:** eval36 dry-run census/runtime → eval12 →
   通過時のみ eval24 → eval36 roll-up。command/hash/runtime/RSS/counts/verdict を ledger に追記。

ST-R1–R3 の想定範囲は `src/biohub/public_postproc/config.py`, `divisions.py`,
`pipeline.py`, `tests/test_public_postproc.py` と 1 本の local-eval script に限る。
`official/`、検出/学習/関連付け、notebook は編集しない。

## Stop conditions と ship/hold 判定

- E23 parity、snapshot validation、off/dry-run identity、pure mutation invariant のいずれかが
  不成立なら即停止。
- eval12 または eval24 staged gate 失敗で v1 を reject。同じ 36 本で条件を
  少しだけ緩めない。
- eval36 で division TP `+4`、adjusted edge、combined score、division Jaccard、
  lineage/median/worst のどれかを満たさなければ reject。
- runtime/RSS/hidden-200 外挿 gate 失敗は metric が勝っても hold。fallback は exact E23。
- `disposable_steal_v1` は本仕様下で常に blocked。実行や v1 への混入は不可。

現時点の判定は **HOLD** である。理由は active E23 parity Phase 3/4 が
完了していないためで、twin-only 仮説自体の否定を意味しない。`SHIP` は
ST-R0–R4、全 metric gate、feasibility gate を通過し、さらに Kaggle 外部操作の
明示承認を得た後にだけ検討する。
