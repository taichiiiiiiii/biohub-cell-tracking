"""Explicit screen-only CSV bounds adapter and complete correction audit.

No graph mutation or dataset-specific correction policy. The submitted helper is
reused unchanged; its sampled report is supplemented by every corrected node.
"""
from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path

from biohub.output_bounds import (
    OutputBoundsError,
    bounded_output_node,
    new_output_bounds_report,
)

BOUNDS_SCHEMA = "biohub.e26_screen.output_bounds.v2"
BOUNDS_POLICY = "python_round_then_xyz_clamp_to_registered_image_shape"
_AXES = ("z", "y", "x")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


class ScreenNodeSerializer:
    """Callable for the existing sole CSV writer; snapshots never alias state."""

    def __init__(self, shapes: dict[str, tuple[int, int, int, int]]) -> None:
        self.shapes = {dataset: tuple(shape) for dataset, shape in shapes.items()}
        self.reports = {dataset: new_output_bounds_report(dataset, shape)
                        for dataset, shape in self.shapes.items()}
        self.corrections: list[dict] = []

    def __call__(self, node: dict, dataset: str, row_id: int) -> dict:
        if dataset not in self.shapes:
            raise OutputBoundsError("node dataset missing from registered image shapes")
        report = self.reports[dataset]
        before = report["corrected_nodes"]
        row = bounded_output_node(node, dataset, row_id, self.shapes[dataset], report)
        if report["corrected_nodes"] != before:
            self.corrections.append({
                "dataset": dataset, "row_id": row_id,
                "node": {"node_id": row["node_id"], "t": row["t"],
                         **{axis: float(node[axis]) for axis in _AXES}},
                "legacy_csv_delta": {axis: row[axis] - max(0, round(float(node[axis]))) for axis in _AXES},
            })
        return row

    def snapshot(self) -> dict:
        return deepcopy({"schema_version": BOUNDS_SCHEMA, "policy": BOUNDS_POLICY,
                         "per_dataset": list(self.reports.values()), "corrections": self.corrections})


def verify_screen_output_bounds(
    payload: dict, csv_path: Path, *, shapes: dict[str, tuple[int, int, int, int]],
) -> None:
    """Replay every correction; compare aggregates and each actual CSV node row.

    The independent full CSV validator remains mandatory. This verifies captured
    corrections, not unrecorded pre-serialization floats or graph provenance.
    """
    if (type(payload) is not dict
            or set(payload) != {"schema_version", "policy", "per_dataset", "corrections"}
            or payload["schema_version"] != BOUNDS_SCHEMA or payload["policy"] != BOUNDS_POLICY
            or type(payload["corrections"]) is not list or type(payload["per_dataset"]) is not list):
        raise OutputBoundsError("invalid screen bounds schema/policy")
    replay = ScreenNodeSerializer(shapes)
    expected_rows = {}
    previous = -1
    for correction in payload["corrections"]:
        if (type(correction) is not dict or set(correction) != {"dataset", "row_id", "node", "legacy_csv_delta"}
                or type(correction["row_id"]) is not int or correction["row_id"] <= previous
                or type(correction["dataset"]) is not str
                or type(correction["node"]) is not dict
                or set(correction["node"]) != {"node_id", "t", *_AXES}):
            raise OutputBoundsError("invalid or reordered correction audit")
        # Captured node representation is closed and JSON-type exact.
        node = correction["node"]
        if (any(type(node[key]) is not int for key in ("node_id", "t"))
                or any(type(node[axis]) is not float for axis in _AXES)):
            raise OutputBoundsError("invalid correction node types")
        previous = correction["row_id"]
        before = len(replay.corrections)
        row = replay(node, correction["dataset"], previous)
        if len(replay.corrections) != before + 1 or _canonical(replay.corrections[-1]) != _canonical(correction):
            raise OutputBoundsError("correction audit differs from recomputed bounds/legacy delta")
        expected_rows[previous] = {key: str(value) for key, value in row.items()}

    counts = dict.fromkeys(shapes, 0)
    found = set()
    with csv_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["dataset"] not in counts:
                raise OutputBoundsError("CSV dataset missing from bounds registration")
            if row["row_type"] == "node":
                counts[row["dataset"]] += 1
            row_id = int(row["id"])
            if row_id in expected_rows:
                if row_id in found or row != expected_rows[row_id]:
                    raise OutputBoundsError("correction audit disagrees with actual CSV row")
                found.add(row_id)
    if found != set(expected_rows):
        raise OutputBoundsError("correction row missing from actual CSV")
    for dataset, report in replay.reports.items():
        if report["node_count"] > counts[dataset]:
            raise OutputBoundsError("more corrected nodes than actual CSV nodes")
        report["node_count"] = counts[dataset]
    if _canonical(payload) != _canonical(replay.snapshot()):
        raise OutputBoundsError("saved bounds report differs from complete audit/CSV counts")
