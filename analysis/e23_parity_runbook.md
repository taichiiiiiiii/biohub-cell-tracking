# E23 public-four parity: fail-closed Phase 3/4 contract

Updated: 2026-08-30 (Asia/Tokyo)

This shared acceptance contract is fail-closed: every executable fence begins
`set -euo pipefail`, and a failed assertion, hash, `cmp`, test, or nonempty
check stops its fence. Run from repository root. Do not delete/overwrite an
output, mutate Kaggle/code inputs, or commit. Public four proves notebook
parity only. The governing boundary is [gold-loop protocol](gold_loop_protocol.md).

## Immutable pins

| item | required value |
|---|---|
| raw GEFF tree | 4 roots; 132 files; 1,583,021 bytes; `5fc5fb5e51d127612421970ed66f0ba4229f020940ed458dfdf0fa316f2e8bc1` |
| test tree | 4 roots; 408 files; 1,906,332,008 bytes; `0b9e6e060437104fb261b388f45eae494abcca59155b4bc9fc4fac24bedd9bbd` |
| reference submission | 240,126 rows; `33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a` |
| reference telemetry | 4 rows; `19f9a0b5b6bb3c903b3dd3d8f6cb25cc9f90a201fae009b3505b140b432fd956` |
| reference official JSON | `3afc4a1a5f4319daa27c92eb1486aed010d0e7e8231ad408bd7d2682b36ba71e` |
| official-input hash | `7c71134d70413986f3e557c91b59db019260d27a93e438ba3770fd5c464338fd` |
| base1 symlink tree | 132 files; 1,448,288 bytes; `7148a3adabe187768a8ef8eb27009b6a27f96f6a079b8f274cd00587b9cadb42` |
| base1 submission | `56b8fab98992bc5c6ed1dcaba32ad7116ebbf6c185a5fcc31ed39cc56fb992ab` |

Dataset order is 44b6_0113de3b, 44b6_0b24845f, 6bba_05b6850b,
6bba_05db0fb1. Raw tree SHA256s are
a4151aad5042a93e3fce9a7f42a2c5b994e83137d2686049c60540e8f9d56fdb,
dfb6885f043250ec106658dcba2bd3d1da14fd02cc75a0bbbbcdc229cd817528,
881a827867dc142236db6b5558a331fdc2f26d07ca15c2e978e5ef8c01c6412f,
ceb3bd1512cc1482b3349c3d52c4db1a79333209f8f978028daa38183ccfc515.
The test/GT tree SHA256 pairs, in the same order, are
987acb0038ef744c0265f028fc003e04182fccac0e520afb8704c426926425ac /
db3939aa55ca05306e1d563b80fc458e17f7e61bea60734bf265c695fb3f0fef;
0c50cb7ef2bb45d1e7414fce46c6c2e37c3829ce805295c3fcad0701440a7140 /
d2156aa79ee2b2a72d331fdaa4de67970c97540d2462fb97f94240dc54f45879;
8f3388f202ab0a483552becd6ffbac6cd13f29ee35ff760bd8c940f5198b5346 /
aec2da8c1abab059e07a2893a2ee92ebe7efe8101d72e10a0c6e445d4e5f4bcb;
fd1913480fcb34db07b72bcaeeb44d1e3488676c3fed982555cd4b06c123416a /
11ab0471fdc59dc15c51c9e94eac8c54482aaf2e7b5a2c7ead77a009eade6142.

## Preflight: assert, do not print

```bash
set -euo pipefail
tree_sha() { (cd "$1" && find -L . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}'); }
files() { find -L "$1" -type f | wc -l | tr -d ' '; }
bytes() { find -L "$1" -type f -exec stat -f '%z' {} + | awk '{s+=$1} END {print s+0}'; }
eq() { test "$1" = "$2" || { echo "ASSERT $1 != $2" >&2; exit 1; }; }
RAW=outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0
shasum -a 256 -c <<'SHA256'
9cc95d3e00b75eaeeb05a1798cc1a1fd0cfb18be1d3239c9b64608527933806b  outputs/kaggle/e22_bidir030_public4_raw/DOWNLOAD_MANIFEST.json
33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a  outputs/kaggle/e23_reference/submission.csv
19f9a0b5b6bb3c903b3dd3d8f6cb25cc9f90a201fae009b3505b140b432fd956  outputs/kaggle/e23_reference/run_stats.csv
3afc4a1a5f4319daa27c92eb1486aed010d0e7e8231ad408bd7d2682b36ba71e  outputs/kaggle/e23_reference/official_public4_score.json
1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911  outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/ARTIFACT_MANIFEST.json
a05f5ef2aba1ae3b3ddfcbd4e655c0af98c63e522403c1b371e588f5d928c646  outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/SNAPSHOT_MANIFEST.json
9b0d1d8a0bbcd6661795efe1c1221288ee152f29a6d63ded26278986b74e97b3  outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/config.json
8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0  outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1/weights/full_frame_center/best.pt
SHA256
eq "$(files "$RAW")" 132; eq "$(bytes "$RAW")" 1583021; eq "$(tree_sha "$RAW")" 5fc5fb5e51d127612421970ed66f0ba4229f020940ed458dfdf0fa316f2e8bc1
eq "$(files data/test)" 408; eq "$(bytes data/test)" 1906332008; eq "$(tree_sha data/test)" 0b9e6e060437104fb261b388f45eae494abcca59155b4bc9fc4fac24bedd9bbd
eq "$(tree_sha "$RAW/44b6_0113de3b.geff")" a4151aad5042a93e3fce9a7f42a2c5b994e83137d2686049c60540e8f9d56fdb; eq "$(tree_sha "$RAW/44b6_0b24845f.geff")" dfb6885f043250ec106658dcba2bd3d1da14fd02cc75a0bbbbcdc229cd817528; eq "$(tree_sha "$RAW/6bba_05b6850b.geff")" 881a827867dc142236db6b5558a331fdc2f26d07ca15c2e978e5ef8c01c6412f; eq "$(tree_sha "$RAW/6bba_05db0fb1.geff")" ceb3bd1512cc1482b3349c3d52c4db1a79333209f8f978028daa38183ccfc515
eq "$(tree_sha data/test/44b6_0113de3b.zarr)" 987acb0038ef744c0265f028fc003e04182fccac0e520afb8704c426926425ac; eq "$(tree_sha data/test/44b6_0b24845f.zarr)" 0c50cb7ef2bb45d1e7414fce46c6c2e37c3829ce805295c3fcad0701440a7140; eq "$(tree_sha data/test/6bba_05b6850b.zarr)" 8f3388f202ab0a483552becd6ffbac6cd13f29ee35ff760bd8c940f5198b5346; eq "$(tree_sha data/test/6bba_05db0fb1.zarr)" fd1913480fcb34db07b72bcaeeb44d1e3488676c3fed982555cd4b06c123416a
eq "$(tree_sha data/train/44b6_0113de3b.geff)" db3939aa55ca05306e1d563b80fc458e17f7e61bea60734bf265c695fb3f0fef; eq "$(tree_sha data/train/44b6_0b24845f.geff)" d2156aa79ee2b2a72d331fdaa4de67970c97540d2462fb97f94240dc54f45879; eq "$(tree_sha data/train/6bba_05b6850b.geff)" aec2da8c1abab059e07a2893a2ee92ebe7efe8101d72e10a0c6e445d4e5f4bcb; eq "$(tree_sha data/train/6bba_05db0fb1.geff)" 11ab0471fdc59dc15c51c9e94eac8c54482aaf2e7b5a2c7ead77a009eade6142
for x in 44b6_0113de3b 44b6_0b24845f 6bba_05b6850b 6bba_05db0fb1; do test -d "$RAW/$x.geff" && test -d "data/test/$x.zarr" && test -d "data/train/$x.geff"; done
uv run --frozen --extra deepcenter python - <<'PY'
from pathlib import Path
import json, torch
r=Path('outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1'); b=r/'weights/full_frame_center/best.pt'
m=json.loads((r/'ARTIFACT_MANIFEST.json').read_text()); c=torch.load(b,map_location='cpu',weights_only=True)
assert b.stat().st_size == 37_876_911 and m['model']['best_checkpoint']['bytes'] == b.stat().st_size
assert m['model']['best_checkpoint']['sha256'] == '8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0'
assert c['epoch'] == 2 and len(c['model_state']) == 50
PY
```

## Phase 3/4 blocker

Phase 3 structural safe-division must land before parity; structural funnel
telemetry must be truthful, not notebook-broken counter emulation.

Exact notebook Phase 4 routing:

| middle | nonmarginal (span < 8.5) | marginal (span >= 8.5) |
|---|---|---|
| observed/reused | increment strong_motion first; no model | increment observed_node; no model |
| synthetic (gap_synthetic == 1) | increment strong_motion first; no model | query DeepCenter at 0.25 |

The predicate is DEEPCENTER_GAP_VETO and marginal_gap and synthetic_middle,
never middle_reused. Rejected synthetic repair rolls back its node,
synthetic_added, gap_inserted_synthetic, and both proposed edges. It does
not roll back next_id (rejected node consumes an ID), or already recorded
refinement/DeepCenter telemetry. The stale synthetic-node bypass counter is a
hard failure.

Focused tests must cover all four observed/synthetic × marginal/nonmarginal
quadrants and synthetic rejection: no rejected node/edges, restored node/cap
accounting, retained refinement/DeepCenter telemetry, and a next accepted
synthetic ID that skips the rejected ID.

```bash
set -euo pipefail
uv run --frozen --extra dev pytest -q tests/test_public_postproc.py
uv run --frozen --extra dev ruff check src/biohub/public_postproc scripts/postproc_geffs.py tests/test_public_postproc.py
```

## Fresh E23 execution

```bash
set -euo pipefail
OUT=outputs/local/e23_parity_public4
test ! -e "$OUT" || { echo "refusing existing output: $OUT" >&2; exit 1; }
mkdir "$OUT"
printf 'code_sha=%s\nstarted_utc=%s\n' "$(git rev-parse HEAD)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$OUT/START_MARKER.txt"
DC=outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1
PYTHONHASHSEED=0 CUDA_VISIBLE_DEVICES='' uv run --frozen --extra deepcenter python scripts/postproc_geffs.py --geff-dir outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0 --test-dir data/test --profile e23 --set "BIOHUB_DEEPCENTER_CHECKPOINT=$DC/weights/full_frame_center/best.pt" --set "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT=$DC/weights/full_frame_center/best.pt" --set "BIOHUB_DEEPCENTER_MANIFEST=$DC/ARTIFACT_MANIFEST.json" --set "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT=$DC/ARTIFACT_MANIFEST.json" --out "$OUT/submission.csv" --run-stats "$OUT/run_stats.csv" 2>&1 | tee "$OUT/postproc.log"
test -s "$OUT/START_MARKER.txt"; test -s "$OUT/postproc.log"; test -s "$OUT/submission.csv"; test -s "$OUT/run_stats.csv"
! rg -i 'No usable DeepCenter checkpoint|Could not read DeepCenter manifest|Skipping incompatible DeepCenter checkpoint|DeepCenter add-only repair gate skipped because torch is unavailable|DeepCenter add-only repair gate disabled by configuration|missing DeepCenter checkpoint' "$OUT/postproc.log"
```

## Graph, telemetry, and score fences

```bash
set -euo pipefail
OUT=outputs/local/e23_parity_public4
test -s "$OUT/submission.csv"
test "$(shasum -a 256 "$OUT/submission.csv" | awk '{print $1}')" = 33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a
cmp -s "$OUT/submission.csv" outputs/kaggle/e23_reference/submission.csv
PYTHONPATH=src uv run --frozen python - <<'PY'
from hashlib import sha256
import json
from pathlib import Path
import polars as pl
from biohub.evaluate import graph_from_rows, read_submission
want={'44b6_0113de3b':(50253,25485,24768,57),'44b6_0b24845f':(38558,19905,18653,77),'6bba_05b6850b':(12085,6142,5943,11),'6bba_05db0fb1':(139230,70675,68555,118)}
def norm(p):
 f=read_submission(p); out={}; assert set(f['dataset'].unique().to_list())==set(want)
 for d in want:
  q=f.filter(pl.col('dataset')==d); n=q.filter(pl.col('row_type')=='node'); e=q.filter(pl.col('row_type')=='edge')
  forks=sum(v >= 2 for v in __import__('collections').Counter(e['source_id'].to_list()).values())
  assert (q.height,n.height,e.height,forks)==want[d] and len(set(e.select('source_id','target_id').rows()))==e.height
  g=graph_from_rows(n,e)
  out[d]={'nodes':g.node_attrs().sort('node_id').select('node_id','t','z','y','x').rows(),'edges':g.edge_attrs().sort('edge_id').select('edge_id','source_id','target_id').rows()}
 return out
ref=norm(Path('outputs/kaggle/e23_reference/submission.csv')); got=norm(Path('outputs/local/e23_parity_public4/submission.csv'))
assert got==ref
assert sha256(json.dumps(got,sort_keys=True,separators=(',',':'),default=list).encode()).hexdigest()=='7c71134d70413986f3e557c91b59db019260d27a93e438ba3770fd5c464338fd'
PY
```

```bash
set -euo pipefail
uv run --frozen python - <<'PY'
import csv
E={'44b6_0113de3b','44b6_0b24845f','6bba_05b6850b','6bba_05db0fb1'}
X={'predict_minutes_total','experiment_tag','safe_division_geometric_candidates','safe_division_mutual_nn_rejected','safe_division_divergence_rejected'}
F={'safe_division_candidates','safe_divisions_added','safe_division_skipped_cap','safe_division_geometric_candidates','safe_division_mutual_nn_rejected','safe_division_divergence_rejected'}
C={'centroid_refine_examined','centroid_refine_moved','centroid_refine_no_signal','centroid_refine_rejected_shift'}
def load(p):
 with open(p,newline='') as h:
  a=list(csv.reader(h)); assert a and a[0] and len(a[0])==len(set(a[0])) and all(len(x)==len(a[0]) for x in a[1:])
  rows=[dict(zip(a[0],x,strict=True)) for x in a[1:]]; ds=[x.get('dataset') for x in rows]; assert len(rows)==4 and set(ds)==E and len(ds)==len(set(ds)); return a[0],{x['dataset']:x for x in rows}
rh,r=load('outputs/kaggle/e23_reference/run_stats.csv'); ch,g=load('outputs/local/e23_parity_public4/run_stats.csv')
required=set(rh)-X; assert required <= set(ch)
assert 'deepcenter_gap_bypassed_observed_node' in ch and 'deepcenter_gap_bypassed_synthetic_node' not in ch and F <= set(ch) and C <= set(ch)
for d in E:
 for k in required: assert g[d][k]==r[d][k],(d,k)
 for k in F: assert g[d][k].isdigit() and int(g[d][k])>=0,(d,k)
 raw=int(r[d]['raw_nodes']); assert int(g[d]['centroid_refine_examined'])==raw==int(g[d]['centroid_refine_moved']) and int(g[d]['centroid_refine_no_signal'])==int(g[d]['centroid_refine_rejected_shift'])==0
PY
```

```bash
set -euo pipefail
OUT=outputs/local/e23_parity_public4
uv run --frozen python scripts/local_eval.py "$OUT/submission.csv" --gt-dir data/train --json "$OUT/official_score.json"
test -s "$OUT/official_score.json"
test "$(shasum -a 256 "$OUT/official_score.json" | awk '{print $1}')" = 3afc4a1a5f4319daa27c92eb1486aed010d0e7e8231ad408bd7d2682b36ba71e
cmp -s "$OUT/official_score.json" outputs/kaggle/e23_reference/official_public4_score.json
```

## Base1 non-regression

```bash
set -euo pipefail
tree_sha() { (cd "$1" && find -L . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}'); }
test "$(find -L outputs/local/eval4_raw_geffs -type f | wc -l | tr -d ' ')" = 132
test "$(find -L outputs/local/eval4_raw_geffs -type f -exec stat -f '%z' {} + | awk '{s+=$1} END{print s+0}')" = 1448288
test "$(tree_sha outputs/local/eval4_raw_geffs)" = 7148a3adabe187768a8ef8eb27009b6a27f96f6a079b8f274cd00587b9cadb42
OUT=outputs/local/e23_parity_base1
test ! -e "$OUT" || { echo "refusing existing output: $OUT" >&2; exit 1; }
mkdir "$OUT"; printf 'code_sha=%s\nstarted_utc=%s\n' "$(git rev-parse HEAD)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$OUT/START_MARKER.txt"
PYTHONHASHSEED=0 uv run --frozen python scripts/postproc_geffs.py --geff-dir outputs/local/eval4_raw_geffs --test-dir data/train --profile base1 --out "$OUT/submission.csv" --run-stats "$OUT/run_stats.csv"
test -s "$OUT/START_MARKER.txt"; test -s "$OUT/submission.csv"; test -s "$OUT/run_stats.csv"
test "$(shasum -a 256 "$OUT/submission.csv" | awk '{print $1}')" = 56b8fab98992bc5c6ed1dcaba32ad7116ebbf6c185a5fcc31ed39cc56fb992ab
cmp -s "$OUT/submission.csv" outputs/local/eval4_base1/submission.csv
uv run --frozen python - <<'PY'
import csv
expected={'44b6_12dfb391','44b6_267148e4','44b6_2a2eff9f','44b6_341df25f'}
runtime={'predict_minutes_total','experiment_tag'}
old_synthetic_schema={'deepcenter_gap_bypassed_synthetic_node'}
new_zero={'centroid_refine_examined','centroid_refine_moved','centroid_refine_no_signal','centroid_refine_rejected_shift','deepcenter_gap_bypassed_observed_node','safe_division_geometric_candidates','safe_division_mutual_nn_rejected','safe_division_divergence_rejected'}
def load(p):
 with open(p,newline='') as h:
  rows=list(csv.reader(h)); assert rows and rows[0] and len(rows[0])==len(set(rows[0])) and all(len(r)==len(rows[0]) for r in rows[1:]),p
  data=[dict(zip(rows[0],r,strict=True)) for r in rows[1:]]; names=[r.get('dataset') for r in data]
  assert len(data)==4 and set(names)==expected and len(names)==len(set(names)),(p,names)
  return set(rows[0]),{r['dataset']:r for r in data}
old_fields,old=load('outputs/local/eval4_base1/run_stats.csv'); new_fields,new=load('outputs/local/e23_parity_base1/run_stats.csv')
required_old=old_fields-runtime-old_synthetic_schema
assert required_old <= new_fields,(required_old-new_fields)
assert new_zero <= new_fields,(new_zero-new_fields)
for d in expected:
 for k in required_old: assert old[d][k]==new[d][k],(d,k)
 for k in new_zero: assert new[d][k].isdigit() and int(new[d][k])==0,(d,k,new[d][k])
PY
```

Record fresh directory, code SHA/start marker, pins, command, runtime,
comparisons, and verdict in analysis/experiment_ledger.md.
