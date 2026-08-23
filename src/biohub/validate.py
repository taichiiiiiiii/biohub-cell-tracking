"""Hard pre-submission validator (raises on the first violation).

Rules (union of the checks the clean public notebooks implement, plus the
upper-bound clamp almost all of them lack):
  1. every dataset in the CSV exists in the test set, and every test dataset has node rows
  2. node rows: 0 <= t < T, 0 <= z < Z, 0 <= y < Y, 0 <= x < X   (upper bounds too)
  3. node_id unique per dataset; edges reference existing nodes of the same dataset
  4. every edge satisfies t_target == t_source + 1
  5. in-degree <= 1 and out-degree <= 2
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from biohub.io import SUBMISSION_COLUMNS, open_volume

Shape4 = tuple[int, int, int, int]


class SubmissionError(ValueError):
    """A rule fired. The message names the dataset and the rule."""


def test_shapes(test_dir: Path | str) -> dict[str, Shape4]:
    """{stem: (T, Z, Y, X)} for every .zarr under ``test_dir`` (metadata only)."""
    test_dir = Path(test_dir)
    return {p.name[:-5]: open_volume(p).shape for p in sorted(test_dir.glob("*.zarr"))}


def _check_nodes(name: str, nodes: pl.DataFrame, shape: Shape4) -> None:
    if nodes.height == 0:
        raise SubmissionError(f"{name}: no node rows")
    if nodes["node_id"].n_unique() != nodes.height:
        raise SubmissionError(f"{name}: duplicate node_id")
    t_max, z_max, y_max, x_max = shape
    bad_t = nodes.filter((pl.col("t") < 0) | (pl.col("t") >= t_max))
    if bad_t.height:
        raise SubmissionError(f"{name}: {bad_t.height} node rows with t out of range [0, {t_max})")
    bad_xyz = nodes.filter(
        (pl.col("z") < 0) | (pl.col("z") >= z_max)
        | (pl.col("y") < 0) | (pl.col("y") >= y_max)
        | (pl.col("x") < 0) | (pl.col("x") >= x_max)
    )
    if bad_xyz.height:
        raise SubmissionError(f"{name}: {bad_xyz.height} node rows with coordinate out of range (Z,Y,X)<{shape[1:]}")


def _check_edges(name: str, nodes: pl.DataFrame, edges: pl.DataFrame) -> int:
    """Return the number of forks (out-degree == 2)."""
    if edges.height == 0:
        return 0
    t_of = dict(zip(nodes["node_id"].to_list(), nodes["t"].to_list(), strict=True))
    src = edges["source_id"].to_list()
    tgt = edges["target_id"].to_list()
    unknown = [(s, t) for s, t in zip(src, tgt, strict=True) if s not in t_of or t not in t_of]
    if unknown:
        raise SubmissionError(f"{name}: {len(unknown)} edges reference unknown node_id, e.g. {unknown[:3]}")
    bad_dt = [(s, t) for s, t in zip(src, tgt, strict=True) if t_of[t] != t_of[s] + 1]
    if bad_dt:
        raise SubmissionError(f"{name}: {len(bad_dt)} edges with t_target != t_source + 1, e.g. {bad_dt[:3]}")
    out_deg = edges.group_by("source_id").len()
    if out_deg.filter(pl.col("len") > 2).height:
        raise SubmissionError(f"{name}: node with out-degree > 2")
    in_deg = edges.group_by("target_id").len()
    if in_deg.filter(pl.col("len") > 1).height:
        raise SubmissionError(f"{name}: node with in-degree > 1")
    return out_deg.filter(pl.col("len") == 2).height


def validate_submission(df: pl.DataFrame, shapes: dict[str, Shape4]) -> dict[str, dict]:
    """Validate a submission DataFrame; return per-dataset counts. Raises SubmissionError."""
    missing = [c for c in SUBMISSION_COLUMNS if c not in df.columns]
    if missing:
        raise SubmissionError(f"missing columns {missing}")
    if df.filter(~pl.col("row_type").is_in(["node", "edge"])).height:
        raise SubmissionError("row_type must be node or edge")
    report: dict[str, dict] = {}
    present = set(df["dataset"].unique().to_list())
    ghost = sorted(present - set(shapes))
    if ghost:
        raise SubmissionError(f"datasets {ghost} not in the test set")
    for name, shape in sorted(shapes.items()):
        g = df.filter(pl.col("dataset") == name)
        nodes = g.filter(pl.col("row_type") == "node")
        edges = g.filter(pl.col("row_type") == "edge")
        _check_nodes(name, nodes, shape)
        forks = _check_edges(name, nodes, edges)
        report[name] = {"nodes": nodes.height, "edges": edges.height, "forks": forks}
    return report


def validate_csv(csv_path: Path | str, test_dir: Path | str) -> dict[str, dict]:
    return validate_submission(pl.read_csv(csv_path), test_shapes(test_dir))


def self_test(shapes: dict[str, Shape4] | None = None) -> None:
    """Inject canaries and require every rule to fire. Call before trusting a green run."""
    shapes = shapes or {"canary": (3, 4, 8, 8)}
    name = next(iter(shapes))
    cols = ["dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]

    def df(nodes, edges):
        rows = [(name, "node", *n, -1, -1) for n in nodes] + [(name, "edge", -1, -1, -1, -1, -1, *e) for e in edges]
        return pl.DataFrame(rows, schema=cols, orient="row")

    good = [(1, 0, 1, 1, 1), (2, 1, 1, 1, 1), (3, 2, 1, 1, 1)]
    canaries = {
        "hub out of volume": df(good + [(9, -1000, -10000, -10000, -10000)], [(1, 2)]),
        "upper bound": df(good + [(9, 0, shapes[name][1], 0, 0)], []),
        "t skip": df(good, [(1, 3)]),
        "out-degree 3": df(good + [(4, 1, 2, 2, 2), (5, 1, 3, 3, 3)], [(1, 2), (1, 4), (1, 5)]),
        "in-degree 2": df(good + [(4, 0, 2, 2, 2)], [(1, 2), (4, 2)]),
        "dangling": df(good, [(1, 99)]),
    }
    for label, bad in canaries.items():
        try:
            validate_submission(bad, {name: shapes[name]})
        except SubmissionError:
            continue
        raise AssertionError(f"validator self-test: rule for '{label}' did not fire")
    validate_submission(df(good, [(1, 2), (2, 3)]), {name: shapes[name]})
