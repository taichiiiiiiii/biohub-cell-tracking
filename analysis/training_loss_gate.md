# 新規学習 run の train / validation loss gate

Updated: 2026-09-05 (Asia/Tokyo)

本書は、今後このリポジトリで作る全ての新規学習 run に対する binding な
fail-closed 契約である。推論、後処理、既存 checkpoint の単純な再利用には適用しない。
ただし既存 checkpoint を warm start して新たに学習する時点から本契約を適用する。

`official/` は公式 metric の read-only 参照実装であり、変更してはならない。
学習計器は `src/biohub/`、`scripts/`、または学習 notebook 側に実装する。

## 遡及適用しない範囲と既知事実

- 回収した E22 inference-input bytes は primary `edge_predictor_best.pth`
  (8,363,159 bytes, `12f6881e...`)、secondary `edge_predictor_best.pth`
  (8,363,159 bytes, `9bac2fa0...`) であり、E22 runtime receipt の path/hash に一致する。
  これは strict load、re-run output parity、checkpoint-to-raw causal proof を示さない。
  両者を epoch 400 checkpoint と
  同一視しない。secondary だけは回収した exact 400-row history から
  best epoch 381、best validation score `0.9779747766406395` と確認できる。
  `checkpoint_last.pth` は別物で epoch 400 / 25,070,547 bytes /
  `ee6c1237...`、deployment 対象外である。secondary history では
  edge/detection/validation loss は first→last でそれぞれ 96.1% / 87.3% /
  70.3% 低下したが単調ではなく、final score は best より
  `0.0025860820161440756` 低い。さらに validation `test` 40 本は
  train 199 本の部分集で、`44b6` のみである。よって記録は
  `LEGACY_IN_SAMPLE_MONITORING_ONLY`、generalization/training gate は PASS 不可とする。
- Primary は complete history がなく、`12f6881e...` の best epoch は不明。
  別物の `checkpoint_last.pth` (25,069,651 bytes, `8294faaf...`) は
  `UNPINNED_LOCAL_OBSERVATION` である。その
  payload 上 epoch 402 だが、artifact 名は `400ep`、runtime の source slug/method
  呼称は `50ep` で矛盾する。loss trend、best epoch、training gate PASS を
  主張せず、`LEGACY_HISTORY_UNVERIFIED` のままとする。
- E20 eval-12 は fine-tune gradient train からは除外されたが、legacy upstream
  exposure を除外できず、先頭2本は epoch-end best-checkpoint selection に
  使われた。従って `LEGACY_UPSTREAM_EXPOSURE_UNKNOWN /
  MODEL_SELECTION_CONTAMINATED_LOCAL_MONITORING` であり、held-out/generalization
  または training gate PASS と呼ばない。
- DeepCenter (`8040999a...`) は別モデル・別学習 run である。保存済み履歴から
  epoch 2 の train/val loss が `0.01233046198 / 0.04500306242` で最良、epoch 100 が
  `0.00795250949 / 0.24764877340` と確認できる。これは「train loss が下がっても
  validation が悪化する」実証例であり、primary/secondary の状態を推論する根拠ではない。
- 現在の E23 parity、後処理、steal/twin 実験には optimizer がなく、training loss gate
  の対象外である。

## 必須成果物

各 run は一つの immutable run directory に、少なくとも次を保存する。manifest は
`purpose={candidate,diagnostic}`、`run_kind={single_split,cv,final_refit}`、一意な
`phase`、該当時は `fold_id` を必須とする。`diagnostic` は checkpoint を候補へ昇格
できない。`candidate` だけが後述の coverage、3 epoch、progression gate の対象となる。

1. `run_manifest.json`: schema version、run ID、purpose/run kind/phase/fold ID、Git SHA、
   学習コード tree SHA256、
   CLI、許可した環境変数、model/loss/optimizer/scheduler config、seed、依存版、hardware、
   入力 manifest SHA256、split SHA256、warm-start checkpoint SHA256、best selector、
   selector の方向と tie rule、required loss-component profile、total-loss 式と全 weight、
   deterministic validation snapshot、事前登録した採否閾値を持つ。
2. `history.jsonl`: 一 epoch 一行の append-only 履歴。中断時も完了済み epoch を残す。
3. `checkpoints/best.pt`: 事前登録 selector が選んだ deployment 候補。
4. `checkpoints/last.pt`: 最終完了 epoch の診断用 checkpoint。deployment に使わない。
5. `checkpoints/resume.pt`: model に加え optimizer、scheduler、AMP scaler、epoch、
   global step、best state、Python/NumPy/Torch CPU/CUDA RNG、sampler state、
   `history.jsonl` prefix SHA256 を含む再開専用 checkpoint。
6. `ARTIFACT_MANIFEST.json`: 上記全 file の path、bytes、SHA256 と gate verdict を持つ。

上記の validation history、selector、`checkpoints/best.pt`、3 validation epoch は
`run_kind=final_refit` のみ例外とする。final refit は代わりに
`checkpoints/fixed_epoch.pt` を必須とし、status を `CV_DERIVED_REFIT_ONLY` に固定する。
その history の val field は明示的に `null`、required component profile は train のみとする。

CV は root bundle を一つの candidate 判定単位とする。`fold/<fold_id>/` ごとに独立した
manifest/history/checkpoint stream を持ち、
`oof/` は全 fold の prediction、example ID、fold ID、集約 metric と各 SHA256 を持つ。
OOF を見て決めた epoch 数による全データ final refit は `final_refit/` の別 run/artifact
とし、CV history や OOF prediction を追記・上書きしない。子 final refit は validation、
selector、best checkpoint を持たず単独昇格できない。全 fold と OOF gate が PASS し、
親 root が pin した固定 epoch、config、input、code、warm-start、split/artifact hash の全てが
一致する場合だけ、親 CV bundle の deployment checkpoint として
`final_refit/checkpoints/fixed_epoch.pt` を参照できる。

書込みは一時 file を同一 filesystem 上で完成させてから atomic rename する。
weights-only の `best.pt` と完全状態の `resume.pt` を混同しない。

新規single-splitのオンライン実行では、明示的に
`execution_hash_policy=predeclared_with_result_bindings_v1`を選択できる（2026-09-22、Issue #18）。
この場合のみconfig hashから`acceptance_thresholds.per_video.sha256`を除外する。
これは学習後に生まれる結果fileのbytes bindingであり、閾値・direction・source・pathなどの
判定条件は全て学習前config hashへ残す。finalizationで実file SHAを確定し、最終verifierは
従来どおり実体との完全一致を要求する。policy未指定の既存runのhash計算は変更しない。

## `history.jsonl` schema

各行は最低限、次の field を持つ。epoch は 1-based、`global_step` は単調増加とする。

```text
schema_version, run_id, purpose, run_kind, phase, fold_id,
epoch, global_step, lr, epoch_seconds,
train_batches, train_examples, val_batches, val_examples,
train.losses.<component>.{value,numerator,denominator,reduction},
val.losses.<component>.{value,numerator,denominator,reduction},
val_by_lineage.{44b6,6bba}, task_metrics,
grad_norm_pre_clip.{max,mean,last,checked_steps,clip_threshold},
nonfinite_count, selector_value, best_so_far, checkpoint_sha256
```

各 loss component は必ず `{value,numerator,denominator,reduction}` の object とする。
`reduction` は `sum_over_examples`、`sum_over_pairs` 等の母集団を一意に記述する。
manifest の required component profile は、例えば UNet なら train/val の
`edge_loss`、`det_loss`、`total_loss` を列挙し、`total_loss = edge_loss + w_det * det_loss`
と `w_det` を pin する。分類器なら BCE 等の component と reduction を同様に pin する。
required でない component は object 全体を `null` にできるが、省略は禁止する。
required validation component が未計装、null、または再計算不能なら `FAIL` とする。
単純な batch-mean の平均だけを numerator としてはならず、run 後に同じ母集団で
再集計可能にする。

`best_so_far` はその epoch 完了時点で selector が過去最良を更新したことを示すため、
append-only history 内で複数行が true になり得る。`checkpoint_sha256` は、その epoch の
immutable checkpoint を実際に保存した場合だけ SHA256 string、それ以外は `null` とする。
最終選択は history を書き換えず manifest にだけ記録する。single split は
`final_selection.{epoch,selector_value,checkpoint_sha256}`、CV root は
`final_selection.{oof_selector_value,fold_selections,final_refit_ref}` とし、各
`fold_selections` は fold ID、epoch、selector value、checkpoint SHA256、
`final_refit_ref` は別 artifact の run ID、固定 epoch 数、checkpoint SHA256 を持つ。

オンライン保存のimmutable epoch checkpointは`kind=epoch`、またはその行の
`best_so_far=true`なら`kind=best`、falseなら`kind=last`を許可する（2026-09-22、Issue #18）。
後続epochで最良値が更新されても、過去のcheckpointや履歴hashを変更しない。
最終`best.pt`/`last.pt`のkind、selector、epoch、tensor、SHAの検査は従来どおり必須。

分類器は `val_auc` 等の task metric を追加する。split manifest は train/validation の
stem、動画数、example 数、lineage 数、該当時の positive/negative 数を保存する。

## Best epoch と checkpoint 選択

- primary selector は結果を見る前に固定し、train loss では選ばない。既定は最小
  `val.losses.total_loss.value`。分類器で grouped-validation AUC を主 selector にする場合は、最大
  `val_auc` と明記し、最小 val-loss checkpoint も別名で保持する。
- 同値は最も早い epoch を選ぶ。現行 UNet trainer の `score >= best_score` のように
  後の同値 epoch を上書きしてはならない。
- manifest の `final_selection` は、primary selector、方向、earliest-tie rule を全 history
  または全 fold OOF readout に再適用した結果と一致し、該当 epoch の checkpoint SHA256
  と一致しなければならない。選択された row の `checkpoint_sha256` は non-null とする。
- `last.pt` は best と同じ SHA256 の場合を除き、提出用 artifact に昇格させない。

## Fail-closed integrity gate

次の一つでも満たさなければ、その candidate run は `FAIL` であり metric 評価へ進めない。
diagnostic run は同じ schema/hash/nonfinite 検査を受けるが、3 epoch、lineage coverage、
baseline progression を免除され、verdict は `DIAGNOSTIC_ONLY` のままとする。
`CV_DERIVED_REFIT_ONLY` は上記専用例外を受けるが、親 CV bundle 以外からは参照できない。
以下の validation/split/selector 条件は final refit には適用せず、親pin一致条件で置換する。
schema、hash、train loss、nonfinite、grad、checkpoint load の検査は免除しない。

- train/validation は動画単位で分離され、stem の交差がゼロ。split/input/config/code/
  warm-start hash が manifest と一致する。
- candidate の validation は空でなく、両 lineage を含む。二値分類では各 validation fold に
  positive/negative の両方を含む。
- candidate には少なくとも 3 epoch の完全な validation record がある。epoch/global step は単調、
  epoch の重複や欠番がない。
- required loss component の denominator は正でなければならない。任意 component で
  対象 example がゼロの場合は component object を `null` とし、理由と zero count を
  manifest に記録する。`0/0` を 0 loss に変換してはならない。
- 全 loss、selector、task metric、pre-clip grad norm が finite。後述する zero-best-loss の
  `loss_degradation_ratio=null` と、final refit の degradation 4 field の `null` は、指定
  reason を伴う場合だけこの finite gate の明示例外とする。loss は非負で、
  `nonfinite_count == 0`。NaN/Inf を検出した時点で直ちに停止し、その後の checkpoint を
  candidate として保存しない。
- pre-clip global grad norm は optimizer step ごとに clip 前に測定し、epoch ごとの
  max/mean/last、checked steps、固定 clip threshold を保存する。`checked_steps` は
  optimizer steps と一致しなければならない。
- run kind に適用される best/last/resume/fixed-epoch checkpoint を strict key/shape で
  load でき、全 file SHA256 と schema が一致する。

## Resume と warm start

Resume は同一 run の継続である。config、input、split、code、warm-start hash と history
prefix SHA256 を照合し、optimizer/scheduler/scaler/RNG/sampler を全て復元する。再開前に
checkpoint を validation-only で読み戻し、保存済み値と manifest に metric 別に pin した
tolerance 以内で一致させる。loss の既定は `rtol=1e-5, atol=1e-7`、count/ID は完全一致、
AUC 等は既定 `atol=1e-8` とする。次の epoch/global step が連続しなければ中止する。

MPSで学習またはvalidationを行うrunは、上記Python/NumPy/Torch CPU/CUDA payloadに加えて
`torch_mps` の実RNG状態を必須とする（2026-09-22、Issue #18）。MPS非使用runの既存schemaは
変更せず、MPS stateをCPU/CUDA stateで代用しない。snapshotのdeviceと実行環境を一致させ、
実device/dtypeで中断再開のreadbackを検証する。CPUだけの成功をMPS再開成功とは扱わない。

validation snapshot は example ID と順序、入力/split hash、preprocessing config、seed、
許可環境変数、device、dtype、framework version を pin し、shuffle/augmentation を無効化する。
sampler が完全な状態を serialize できない場合は、`seed = H(run_id, epoch, fold_id)` のような
epoch-derived seed と deterministic index order を使い、式と hash を manifest に記録する。

Warm start は新しい run であり、optimizer 等を引き継がない。mode は
`full_strict` または `submodule_strict` の二つだけとする。`full_strict` は model 全 key の
完全一致を要求する。`submodule_strict` は許可する key prefix、期待 key の完全な sorted
list/hash、各 shape/dtype、意図的に新規初期化する key list/hash を事前に pin し、許可
prefix 内を strict load する。無制限な `strict=False`、実行後に missing/unexpected key を
眺めて受理する運用は禁止する。元 checkpoint hash、key/shape/dtype、mode の不一致は
fail closed とする。

## Overfit gate と採否

全 epoch の最小 validation loss を `best_loss` と定義し、loss degradation を次のように
必ず記録する。`best_loss > 0` なら `loss_degradation_ratio` は
`(last_val_loss - best_loss) / best_loss`、`best_loss == last_val_loss == 0` なら ratio は `0`、
`best_loss == 0 < last_val_loss` なら ratio は `null` とし、
`loss_degradation_absolute = last_val_loss - best_loss` と `ZERO_BEST_LOSS` flag を保存する。
最後の場合の warning 判定には、実行前に pin した absolute degradation threshold を使う。
ratio が finite の場合は `>0.10` を `OVERFIT_WARN`、`>0.25` を `STRONG_OVERFIT` とする。
後半が悪化しても、best checkpoint が正しく選択・pin されていれば artifact integrity は
通せるが、last checkpoint は使用禁止。
最大化 selector は別の `selector_degradation = best_selector - last_selector`、最小化
selector は `last_selector - best_selector` として、常に正が悪化になるよう記録する。
loss degradation と selector degradation を同じ field や閾値で扱わない。
`run_kind=final_refit` は validation を持たないため degradation の算出対象外とする。
`loss_degradation_ratio`、`loss_degradation_absolute`、`ZERO_BEST_LOSS`、
`selector_degradation` は全て `null`、reason は
`CV_DERIVED_REFIT_NO_VALIDATION` とし、親 CV bundle の fold/OOF degradation artifact を
manifest から参照する。

新規学習 candidate が公式 metric 評価へ進むための必要条件は次の全てである。

- 上記 integrity gate が PASS。
- 事前登録した primary selector が baseline を事前登録幅だけ改善する。loss selector なら
  best validation loss、分類器なら grouped OOF AUC 等を使える。分類器へ一律の val-loss
  `1%` 改善を強制しない。
- primary selector と直交する事前登録 non-inferiority 指標を満たす。例として loss を
  primary にした場合は task metric、grouped OOF AUC を primary にした場合は val loss と
  calibration を使う。両 lineage の許容悪化幅も selector ごとに実行前固定する。
- 改善が一動画だけに集中せず、動画対応の readout と uncertainty を保存している。

小標本や task 固有の閾値が上記より厳しい場合は、実行前に台帳へ固定した値を優先する。
loss gate は必要条件であって採用条件ではない。通過後も、未接触の動画単位 split と
`src/biohub/evaluate.py` から直呼びする公式 metric で、該当実験の事前登録 gate を通す。
public test 4本や notebook 内 proxy metric で代用しない。

## Repo 統合候補

- `src/biohub/training_history.py`: schema、atomic writer、best selector、checkpoint/resume。
- `scripts/validate_training_run.py`: network/GPU 不要の fail-closed artifact verifier。
- `tests/test_training_history.py`: schema、hash、selector、resume の fixture。
- 対象 trainer: `notebooks/div_classifier/div_classifier.py`、
  `notebooks/div_pretrain/div_pretrain.py`、`notebooks/div_finetune/*.py`、
  `notebooks/div_finetune_secondary/*.py`、`notebooks/train_probe/train_probe.py`。

support pack の trainer を使う場合も、実行時の非構造的な文字列置換だけに依存せず、
repo-owned wrapper/instrumentation から同じ schema を出す。wrapper の bytes/SHA256 と、
取得した support-pack trainer 自体の bytes/SHA256 の双方を manifest に pin する。
`official/` は編集しない。

## 必須 verification fixture とコマンド

fixture は正常 run に加え、NaN/Inf、empty validation、stem overlap、片 lineage 欠落、
required/unrequired zero denominator、required component 未計装、total-loss 式/weight drift、
hash drift、late overfit、selector tie、複数 `best_so_far` と唯一の final selection、nullable
checkpoint SHA、CV fold/OOF/final-refit stream 混線、diagnostic の昇格拒否、resume history/
validation snapshot mismatch、epoch/step 重複、metric tolerance、sampler再開、pre-clip grad
集計不足、final-refit単独昇格と親pin mismatch、zero-best-loss の3分岐、
final-refit degradation の全null/reason/親CV参照、full/submodule strict key/shape/prefix
mismatch、wrapper/support trainer hash drift を含める。

```bash
uv run --frozen --extra dev pytest -q tests/test_training_history.py
uv run --frozen --extra dev ruff check \
  src/biohub/training_history.py scripts/validate_training_run.py \
  tests/test_training_history.py
uv run --frozen python scripts/validate_training_run.py outputs/<run>
git diff --check
```

Kaggle から取得した run は、提出 notebook に接続する前に local verifier を PASS させ、
verdict、best epoch/value、checkpoint SHA256、`loss_degradation_ratio` と
`loss_degradation_absolute`、`ZERO_BEST_LOSS`、`selector_degradation` を
experiment ledger に記録する。
