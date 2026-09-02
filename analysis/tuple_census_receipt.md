# GT-blind two-child tuple feasibility census

Run date: 2026-09-02 (Asia/Tokyo)

This is a computational-volume receipt, not score or candidate-quality
evidence. The run read only the pinned eval-36 raw prediction GEFF bundle. It
did not read ground truth, image Zarrs, public-dummy artifacts, an official
metric/evaluator, a network service, or Kaggle.

## Frozen universe

- Dataset order and membership: the exact 36-stem `eval12 + eval24` sequence
  from the steal/twin evaluation contract, with 18 `44b6` and 18 `6bba` stems.
- `P` has exactly one selected raw outgoing edge `P -> A`.
- `B` is any distinct raw node at `t(P)+1`.
- Count `(P,A,B)` iff `d(P,B) <= 8.0 um` and `d(A,B) <= 11.0 um`, inclusive.
- Fixed voxel scale `(z,y,x) = (1.625,0.40625,0.40625) um`.
- No radius, filter, or ordering rule was selected from the observed counts.

Config SHA-256:
`1996d29f269e17a45581091ae12fec628e3b7ec49dcb4ed3ab60ec213c870710`.

## Input and command

The input passed the pinned identity gate: 36 GEFF roots, 1,224 directories,
1,188 regular files, 10,090,215 bytes, canonical sha256sum-tree SHA-256
`fa34dcf5f20054f240d750bd2225dd08fc6cf645e094cd9596ce2faf4bbf0ca2`,
and canonical directory-tree SHA-256
`687267b8e1a886f5ef3a564422718c2014b74f5fae9e21e039ce06a15448e1c6`.
Schema v2 includes the exact directory structure, so an unexpected empty
directory changes the identity and fails the gate. The tree was scanned and
compared both before and after graph traversal. Every absolute input path
component, including ancestors above `repo_root`, was opened from the
filesystem anchor with no-follow semantics.

```text
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/Users/taichi/biohub-sol-tuple-census/src \
/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking/.venv/bin/python \
scripts/tuple_census.py \
  --repo-root /Users/taichi/コンペティション/Kaggle/biohub-cell-tracking
```

Script SHA-256:
`3816a12423e3a6a470bb897626e24dd7ac2e53a73c48c393c40d5071d4e4f449`.
Canonical stdout JSON receipt: 11,223 bytes, SHA-256
`39afcfdc6dd74012d80e01f5648ce450f2493aac9ad039c93b17d527e6b8f9cf`.
The bytes were consumed directly by a streaming SHA-256/JSON verifier and were
not redirected to a file. On Darwin, `--output` is disabled during CLI
preflight, before census execution, path creation, open, unlink, or publication.
Linux file publication remains available only through `O_TMPFILE` plus
`linkat(AT_EMPTY_PATH)` and fails closed without a named fallback.

## Result

| Scope | videos | frames | one-child parents | active parents | tuples | median/video | p95/video | max/video |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all | 36 | 3,600 | 730,183 | 292,236 | 371,915 | 8,219.5 | 28,925.0 | 36,798 |
| `44b6` | 18 | 1,800 | 406,417 | 172,017 | 221,797 | 10,517.0 | 28,329.8 | 33,389 |
| `6bba` | 18 | 1,800 | 323,766 | 120,219 | 150,118 | 4,530.5 | 25,034.0 | 36,798 |

The maximum was 6 tuples for one parent and 607 tuples for one frame. Linear
200-video extrapolation is approximately 2,066,194 tuples and 4,056,572
one-child parents. This establishes only that a streaming lightweight head can
have a bounded candidate universe; an additional encoder/detector pass remains
a separate runtime risk.

Wall time was 9.48 seconds on the local machine (`user 8.51`, `sys 0.85`),
including both complete tree scans and all 36 graph loads. This is not a
target-class runtime receipt.

The prior exploratory counts were 730,183 one-child parents and 371,915 tuples.
The reproducible implementation matches both exactly; discrepancy: none.
