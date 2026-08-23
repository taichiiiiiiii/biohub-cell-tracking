"""Streaming CSV writer + run_stats assembly, ported verbatim from the notebook cell."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TextIO

import pandas as pd

SUBMISSION_COLUMNS = ["dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id"]
CSV_COLUMNS = ["id", *SUBMISSION_COLUMNS]


class SubmissionCsvWriter:
    """Streaming writer with a single ``id`` counter running across all datasets.

    Row order (and therefore the ``id`` values) must match the notebook: for
    each dataset, node rows sorted by ``node_id`` then edge rows in the
    filtered-graph's edge-list order.
    """

    def __init__(self, handle: TextIO) -> None:
        self._writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        self._writer.writeheader()
        self.row_id = 0

    def write_nodes(self, dataset: str, nodes_by_id: dict[int, dict[str, object]]) -> None:
        for node_id in sorted(nodes_by_id):
            node = nodes_by_id[node_id]
            self._writer.writerow({
                "id": self.row_id,
                "dataset": dataset,
                "row_type": "node",
                "node_id": int(node["node_id"]),
                "t": int(node["t"]),
                "z": max(0, int(round(float(node["z"])))),
                "y": max(0, int(round(float(node["y"])))),
                "x": max(0, int(round(float(node["x"])))),
                "source_id": -1,
                "target_id": -1,
            })
            self.row_id += 1

    def write_edges(self, dataset: str, nodes_by_id: dict[int, dict[str, object]], edges: list[dict[str, object]]) -> dict[int, int]:
        """Write edge rows in list order; returns {source_id: out_degree} for division stats."""
        division_sources: dict[int, int] = {}
        for edge in edges:
            source_id = int(edge["source_id"])
            target_id = int(edge["target_id"])
            if source_id not in nodes_by_id or target_id not in nodes_by_id:
                raise AssertionError(f"{dataset}: dangling edge after filtering")
            self._writer.writerow({
                "id": self.row_id,
                "dataset": dataset,
                "row_type": "edge",
                "node_id": -1,
                "t": -1,
                "z": -1,
                "y": -1,
                "x": -1,
                "source_id": source_id,
                "target_id": target_id,
            })
            self.row_id += 1
            division_sources[source_id] = division_sources.get(source_id, 0) + 1
        return division_sources


def build_run_stats_frame(stats_rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(stats_rows).sort_values("dataset").reset_index(drop=True)


def write_run_stats(stats_rows: list[dict[str, object]], path: Path) -> pd.DataFrame:
    stats = build_run_stats_frame(stats_rows)
    stats.to_csv(path, index=False)
    return stats
