"""Measure how much of a score difference is just sampling noise.

Run this before optimising anything. A leaderboard score is computed on a finite,
grouped sample, and when the per-group error distribution has a heavy tail — one
well, one patient, one document carrying a disproportionate share of the squared
error — the standard error of that score is far larger than intuition suggests.
Differences below it are not small effects. They are not effects.

Why this script exists: in the 2026 ROGII competition we spent a month ranking
configurations by differences of 0.01-0.05 in the public score. A bootstrap over
evaluation groups, which we could have run on day one from data we already had,
put the standard error of that score at 0.41 for the 52 groups the public board
scored. Every difference we were chasing was between an eighth and a fortieth of
that. When the private scores were finally revealed, the spread across nominally
identical configurations was 0.18 — close to this bootstrap's estimate for a set
of 200 groups (0.21), and ten times the public spread we had been treating as
signal.

Usage
-----
    # predictions and ground truth, joined on an id column
    python noise_floor.py preds.csv truth.csv --id id --pred pred --true target

    # the id encodes the evaluation group, e.g. "<well>_<row>"
    python noise_floor.py preds.csv truth.csv --group-from-id '^(.*)_[0-9]+$'

    # or the group is its own column
    python noise_floor.py preds.csv truth.csv --group well_id

    # what would the standard error be on a leaderboard of 52 groups?
    python noise_floor.py preds.csv truth.csv --group well_id --sizes 52 200

The bootstrap resamples *groups*, not rows, because that is how the competition
organiser drew the split. Resampling rows would understate the error by treating
correlated rows within a group as independent.
"""

from __future__ import annotations

import argparse
import re
import sys

import numpy as np
import pandas as pd

METRICS = {
    "rmse": lambda e: float(np.sqrt(np.mean(e**2))),
    "mae": lambda e: float(np.mean(np.abs(e))),
    "mse": lambda e: float(np.mean(e**2)),
}


def load(args) -> tuple[np.ndarray, np.ndarray]:
    """Return per-row errors and the group label each row belongs to."""
    preds = pd.read_csv(args.preds)
    truth = pd.read_csv(args.truth)
    for name, df in (("preds", preds), ("truth", truth)):
        if args.id not in df.columns:
            raise SystemExit(
                f"column '{args.id}' not found in {name}; have {list(df.columns)}"
            )
    preds[args.id] = preds[args.id].astype("string")
    truth[args.id] = truth[args.id].astype("string")
    merged = preds.merge(truth, on=args.id, how="inner", suffixes=("_pred", "_true"))
    if len(merged) == 0:
        raise SystemExit(f"no rows joined on '{args.id}' -- check the id column name")
    if len(merged) < len(truth):
        print(
            f"warning: joined {len(merged)} of {len(truth)} truth rows",
            file=sys.stderr,
        )

    pred_col = args.pred if args.pred in merged else f"{args.pred}_pred"
    true_col = args.true if args.true in merged else f"{args.true}_true"
    for col in (pred_col, true_col):
        if col not in merged:
            raise SystemExit(f"column '{col}' not found; have {list(merged.columns)}")

    err = merged[pred_col].to_numpy(float) - merged[true_col].to_numpy(float)

    if args.group:
        # Falling back to --group-from-id on a typo would silently compute a different
        # grouping and still print three decimals. Name the failure instead.
        col = args.group
        if col not in merged:
            alt = [c for c in (f"{col}_pred", f"{col}_true") if c in merged]
            if alt:
                col = alt[0]
            else:
                raise SystemExit(
                    f"column '{args.group}' not found after the join; "
                    f"have {list(merged.columns)}"
                )
        groups = merged[col].astype(str).to_numpy()
    elif args.group_from_id:
        pat = re.compile(args.group_from_id)
        ids = merged[args.id].astype(str)
        extracted = ids.str.extract(pat, expand=False)
        if extracted.isna().any():
            raise SystemExit(f"--group-from-id did not match every id, e.g. {ids.iloc[0]!r}")
        groups = extracted.to_numpy()
    else:
        raise SystemExit("give --group <column> or --group-from-id <regex>")

    return err, groups


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("preds")
    p.add_argument("truth")
    p.add_argument("--id", default="id")
    p.add_argument("--pred", default="pred")
    p.add_argument("--true", default="target")
    p.add_argument("--group", help="column holding the evaluation group")
    p.add_argument("--group-from-id", help="regex with one capture group, applied to --id")
    p.add_argument("--metric", default="rmse", choices=sorted(METRICS))
    p.add_argument("--sizes", type=int, nargs="*", help="hypothetical leaderboard sizes")
    p.add_argument("--n-boot", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    err, groups = load(args)
    metric = METRICS[args.metric]
    names = np.unique(groups)
    per_group = {g: err[groups == g] for g in names}

    print(f"groups: {len(names)}   rows: {len(err)}")
    print(f"{args.metric} on the full set: {metric(err):.4f}\n")

    # How concentrated is the error? A few groups dominating is what inflates the
    # standard error, and it is also what makes in-sample tuning misleading.
    contrib = np.array([np.sum(per_group[g] ** 2) for g in names])
    order = np.argsort(contrib)[::-1]
    total = contrib.sum()
    for frac in (0.05, 0.10, 0.25):
        k = max(1, int(round(frac * len(names))))
        share = contrib[order[:k]].sum() / total
        # With few groups the requested fraction rounds to a different one -- 5% of 10
        # groups is 1 group, i.e. 10%. Print what was actually taken so the number can
        # be compared against a run on a differently-sized set.
        actual = k / len(names)
        label = f"worst {frac:>4.0%}"
        if abs(actual - frac) > 1e-9:
            label += f" (= {k}/{len(names)} = {actual:.0%})"
        print(f"  {label} of groups carry {share:6.1%} of the squared error")
    print()

    rng = np.random.default_rng(args.seed)
    sizes = args.sizes or [len(names)]

    # Resampling k groups out of n observed ones only estimates the error for k when n
    # is comfortably large. With few groups the estimate is itself very uncertain --
    # on heavy-tailed data, resampling 10 groups reproduced the true 40-group answer
    # only to within a factor of ~20. Say so rather than printing three decimals of
    # false precision.
    if len(names) < 30:
        print(
            f"  WARNING: only {len(names)} groups observed. The numbers below are\n"
            f"  themselves uncertain -- treat them as an order of magnitude, and\n"
            f"  re-run once you have 30+ groups.\n"
        )
    for n in sizes:
        if n > len(names):
            print(f"  note: asked for {n} groups, only {len(names)} observed "
                  f"(resampled with replacement)")

    header = (f"{'eval groups':>12}  {'std error':>10}  {'95% width':>10}  "
              f"{'ignore differences below':>26}")
    print(header)
    for n in sizes:
        boots = np.empty(args.n_boot)
        for i in range(args.n_boot):
            pick = rng.choice(names, size=n, replace=True)
            boots[i] = metric(np.concatenate([per_group[g] for g in pick]))
        se = float(np.std(boots))
        print(f"{n:>12}  {se:>10.3f}  {1.96 * se:>10.3f}  {2.8 * se:>26.3f}")

    print(
        "\nThe last column is the difference two configurations must show before the\n"
        "comparison means anything (roughly the 95% threshold for a difference of two\n"
        "independent draws). Anything smaller is noise: do not rank on it, do not\n"
        "select on it, and do not spend days moving it."
    )


if __name__ == "__main__":
    main()
