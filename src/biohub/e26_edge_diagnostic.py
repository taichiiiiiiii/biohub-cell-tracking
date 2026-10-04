"""Read-only, official-matching edge transitions; never generates predictions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import polars as pl
import tracksdata as td

from biohub.evaluate import graph_from_rows, node_recall, official_evaluate, per_sample_metrics

K = td.DEFAULT_ATTR_KEYS

# biohub.evaluate must pin the official module before importing its private extraction API.
from tracking_cellmot.metrics import _evaluate_matched_graph  # noqa: E402

STATES = (
    "tp", "source_unmatched_only", "target_unmatched_only", "both_unmatched",
    "both_matched_no_csv_edge", "both_matched_edge_not_official_tp",
)
TRANSITIONS = ("retained_tp", "lost_tp", "gained_tp", "shared_fn")
NODE_SCHEMA = {
    "internal_node_id": pl.Int64, "submitted_node_id": pl.Int64, "gt_node_id": pl.Int64,
    "t": pl.Int64, "z": pl.Float64, "y": pl.Float64, "x": pl.Float64,
}
EDGE_SCHEMA = {
    "internal_edge_id": pl.Int64, "internal_source_id": pl.Int64, "internal_target_id": pl.Int64,
    "submitted_source_id": pl.Int64, "submitted_target_id": pl.Int64,
    "source_gt_id": pl.Int64, "target_gt_id": pl.Int64,
    "evaluated": pl.Boolean, "pred_valid": pl.Boolean, "tp": pl.Boolean, "fp": pl.Boolean,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def edge_state(source_matched: bool, target_matched: bool, csv_edge: bool, tp: bool) -> str:
    require(not csv_edge or (source_matched and target_matched), "edge without matched endpoints")
    require(not tp or csv_edge, "TP without CSV edge")
    if tp:
        return "tp"
    if not source_matched and not target_matched:
        return "both_unmatched"
    if not source_matched:
        return "source_unmatched_only"
    if not target_matched:
        return "target_unmatched_only"
    return "both_matched_edge_not_official_tp" if csv_edge else "both_matched_no_csv_edge"


def transition(before: str, after: str) -> str:
    require(before in STATES and after in STATES, "unknown edge state")
    if before == "tp":
        return "retained_tp" if after == "tp" else "lost_tp"
    return "gained_tp" if after == "tp" else "shared_fn"


def graph_with_ids(nodes: pl.DataFrame, edges: pl.DataFrame):
    """Stock graph construction, recording the actual assigned IDs, not row offsets."""
    require(nodes["node_id"].n_unique() == nodes.height, "duplicate submitted node IDs")
    require(nodes.select(pl.all_horizontal(pl.col("z", "y", "x").is_finite()).all()).item(),
            "nonfinite coordinates")
    graph = td.graph.InMemoryGraph()
    for key in ("z", "y", "x"):
        graph.add_node_attr_key(key, pl.Float64, -999999.0)
    assigned = graph.bulk_add_nodes(nodes.select(
        pl.col("t").cast(pl.Int64), pl.col("z").cast(pl.Float64),
        pl.col("y").cast(pl.Float64), pl.col("x").cast(pl.Float64),
    ).to_dicts())
    forward = dict(zip(nodes["node_id"].to_list(), assigned, strict=True))
    inverse = {internal: submitted for submitted, internal in forward.items()}
    require(len(inverse) == nodes.height, "nonbijective internal ID map")
    pairs = list(zip(edges["source_id"].to_list(), edges["target_id"].to_list(), strict=True))
    require(all(s in forward and t in forward for s, t in pairs), "dangling edge")
    if pairs:
        graph.bulk_add_edges([{"source_id": forward[s], "target_id": forward[t]} for s, t in pairs])
    stock = graph_from_rows(nodes, edges)
    for method in ("node_attrs", "edge_attrs"):
        a, b = getattr(graph, method)(), getattr(stock, method)()
        require(a.schema == b.schema and a.columns == b.columns and a.equals(b), "stock graph differs")
    require(graph.node_ids() == stock.node_ids() and graph.edge_ids() == stock.edge_ids(),
            "stock internal IDs differ")
    return graph, inverse


@dataclass
class ArmDiagnostic:
    row: dict
    nodes: pl.DataFrame
    edges: pl.DataFrame
    gt_edges: list[dict]


def diagnose_arm(
    dataset: str, nodes: pl.DataFrame, edges: pl.DataFrame, gt,
    scale: tuple[float, float, float], estimated_nodes: float,
    expected_row: dict | None = None,
) -> ArmDiagnostic:
    pred, inverse = graph_with_ids(nodes, edges)
    er = official_evaluate(pred, gt, scale=scale, max_distance=7.0)
    recall = node_recall(pred, gt) if pred.num_edges() and pred.num_nodes() else 0.0
    row = {"dataset": dataset, **per_sample_metrics(er, estimated_nodes, recall)}
    if expected_row is not None:
        require(row == expected_row, f"{dataset}: official saved row mismatch: {row} != {expected_row}")

    # evaluate() leaves its full-graph matching on pred; division matching works on copies.
    attrs = [K.NODE_ID, K.T, "z", "y", "x"]
    pn = pred.node_attrs(attr_keys=attrs + ([K.MATCHED_NODE_ID] if pred.num_edges() else []))
    gt_ids = set(gt.node_ids())
    node_records, by_internal, gt_to_internal = [], {}, {}
    for node in pn.iter_rows(named=True):
        internal = int(node[K.NODE_ID])
        match = node.get(K.MATCHED_NODE_ID, -1)
        match = None if match is None or match == -1 else int(match)
        record = {
            "internal_node_id": internal, "submitted_node_id": int(inverse[internal]),
            "gt_node_id": match, "t": int(node[K.T]),
            **{key: float(node[key]) for key in ("z", "y", "x")},
        }
        node_records.append(record)
        by_internal[internal] = record
        if match is not None:
            require(match in gt_ids and match not in gt_to_internal, "nonbijective/unknown GT match")
            gt_to_internal[match] = internal
    require(len(node_records) == er.num_pred_nodes == len(inverse), "incomplete node map")

    evaluated = _evaluate_matched_graph(pred, gt) if pred.num_edges() else None
    evaluated_by_id = {} if evaluated is None else {
        int(r[K.EDGE_ID]): r for r in evaluated.iter_rows(named=True)
    }
    edge_records, recovered = [], set()
    for edge in pred.edge_attrs(attr_keys=[]).iter_rows(named=True):
        eid, source, target = (int(edge[k]) for k in (K.EDGE_ID, K.EDGE_SOURCE, K.EDGE_TARGET))
        evaluated_edge = evaluated_by_id.get(eid)
        tp = bool(evaluated_edge[K.MATCHED_EDGE_MASK]) if evaluated_edge is not None else False
        valid = bool(evaluated_edge["pred_valid"]) if evaluated_edge is not None else False
        record = {
            "internal_edge_id": eid, "internal_source_id": source, "internal_target_id": target,
            "submitted_source_id": int(inverse[source]), "submitted_target_id": int(inverse[target]),
            "source_gt_id": by_internal[source]["gt_node_id"],
            "target_gt_id": by_internal[target]["gt_node_id"],
            "evaluated": evaluated_edge is not None, "pred_valid": valid, "tp": tp, "fp": valid and not tp,
        }
        edge_records.append(record)
        if tp:
            recovered.add((record["source_gt_id"], record["target_gt_id"]))
    require(len(recovered) == sum(r["tp"] for r in edge_records) == er.edge_tp, "TP map mismatch")
    require(sum(r["fp"] for r in edge_records) == er.edge_fp, "FP map mismatch")
    require(len(edge_records) == edges.height, "incomplete predicted edge records")
    pred_pairs = {(r["internal_source_id"], r["internal_target_id"]) for r in edge_records}
    gt_nodes = {int(r[K.NODE_ID]): r for r in gt.node_attrs(attr_keys=attrs).iter_rows(named=True)}
    gt_edge_records = []
    for edge in gt.edge_attrs(attr_keys=[]).iter_rows(named=True):
        source, target = int(edge[K.EDGE_SOURCE]), int(edge[K.EDGE_TARGET])
        a, b = gt_to_internal.get(source), gt_to_internal.get(target)
        present = a is not None and b is not None and (a, b) in pred_pairs
        gt_edge_records.append({
            "gt_edge_id": int(edge[K.EDGE_ID]), "gt_source_id": source, "gt_target_id": target,
            "gt_source": gt_nodes[source], "gt_target": gt_nodes[target],
            "matched_source": by_internal.get(a), "matched_target": by_internal.get(b),
            "csv_edge_present": present,
            "state": edge_state(a is not None, b is not None, present, (source, target) in recovered),
        })
    gt_pairs = {(r["gt_source_id"], r["gt_target_id"]) for r in gt_edge_records}
    require(len(gt_pairs) == len(gt_edge_records) == gt.num_edges(), "duplicate GT edge")
    require(recovered <= gt_pairs, "recovered non-GT edge")
    require(sum(r["state"] != "tp" for r in gt_edge_records) == er.edge_fn, "FN map mismatch")
    # Sparse GT can leave the first hundreds of records unmatched. Never infer a Null
    # ID column from a prefix, or lose large GEFF IDs through float/int32 coercion.
    return ArmDiagnostic(row, pl.DataFrame(node_records, schema=NODE_SCHEMA),
                         pl.DataFrame(edge_records, schema=EDGE_SCHEMA), gt_edge_records)


def compare_arms(baseline: ArmDiagnostic, candidate: ArmDiagnostic) -> tuple[list[dict], dict]:
    require(baseline.row["dataset"] == candidate.row["dataset"], "dataset mismatch")
    indexed = []
    for arm in (baseline, candidate):
        mapping = {r["gt_edge_id"]: r for r in arm.gt_edges}
        require(len(mapping) == len(arm.gt_edges), "duplicate diagnostic GT edge ID")
        require(sum(r["state"] == "tp" for r in arm.gt_edges) == arm.row["edge_tp"], "arm TP mismatch")
        require(sum(r["state"] != "tp" for r in arm.gt_edges) == arm.row["edge_fn"], "arm FN mismatch")
        indexed.append(mapping)
    before, after = indexed
    require(before.keys() == after.keys(), "GT edge set mismatch")
    records = []
    for eid, b in before.items():
        c = after[eid]
        require(all(b[k] == c[k] for k in ("gt_source_id", "gt_target_id", "gt_source", "gt_target")),
                "GT endpoint mismatch")
        records.append({
            "dataset": baseline.row["dataset"], "gt_edge_id": eid,
            "transition": transition(b["state"], c["state"]), "baseline": b, "candidate": c,
        })
    counts = Counter(r["transition"] for r in records)
    require(counts["gained_tp"] - counts["lost_tp"] == candidate.row["edge_tp"] - baseline.row["edge_tp"],
            "paired TP mass balance mismatch")
    summary = {
        "dataset": baseline.row["dataset"], "gt_edges": len(records),
        "transitions": {k: counts[k] for k in TRANSITIONS},
        "lost_tp_candidate_state": {k: sum(r["transition"] == "lost_tp" and r["candidate"]["state"] == k
                                          for r in records) for k in STATES[1:]},
        "gained_tp_baseline_state": {k: sum(r["transition"] == "gained_tp" and r["baseline"]["state"] == k
                                          for r in records) for k in STATES[1:]},
        "baseline": baseline.row, "candidate": candidate.row,
    }
    return records, summary
