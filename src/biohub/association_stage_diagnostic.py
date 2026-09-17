"""Graph-only loss-stage diagnosis, distinct from official scores and causal claims."""

import copy
import warnings
from collections import Counter
from dataclasses import dataclass

import numpy as np
import polars as pl
import tracksdata as td
from scipy.sparse import SparseEfficiencyWarning
from tracksdata.metrics import DistanceMatching
from tracksdata.options import get_options, set_options

from biohub.e26_edge_diagnostic import edge_state, graph_with_ids, require, transition

K = td.DEFAULT_ATTR_KEYS
COORDS = ("t", "z", "y", "x")


@dataclass
class Stage:
    nodes: dict
    edges: set
    gt_to_submitted: dict
    positions: Counter
    mapping_rows: list


def map_stage(nodes, edges, gt, scale):
    """Use the official distance-matching algorithm even when no predicted edges exist."""
    require(len(scale) == 3 and all(np.isfinite(s) and s > 0 for s in scale), "invalid physical scale")
    require(nodes["t"].dtype.is_integer() and nodes["node_id"].dtype.is_integer(), "noninteger node ID/time")
    require(edges["source_id"].dtype.is_integer() and edges["target_id"].dtype.is_integer(), "noninteger edge ID")
    by_id = {int(r["node_id"]): tuple(r[k] for k in COORDS) for r in nodes.iter_rows(named=True)}
    require(len(by_id) == nodes.height, "duplicate node ID")
    pairs = set(zip(edges["source_id"].to_list(), edges["target_id"].to_list(), strict=True))
    require(len(pairs) == edges.height, "duplicate predicted edge")
    require(all(s in by_id and t in by_id and by_id[t][0] == by_id[s][0] + 1 for s, t in pairs),
            "dangling or nonadjacent predicted edge")
    graph, inverse = graph_with_ids(nodes, edges)
    if nodes.height and gt.num_nodes():
        previous = get_options().show_progress
        set_options(show_progress=False)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=SparseEfficiencyWarning)
                graph.match(gt, matching=DistanceMatching(max_distance=7., scale=scale))
        finally:
            set_options(show_progress=previous)
    attrs = [K.NODE_ID, K.T, "z", "y", "x"]
    if K.MATCHED_NODE_ID in graph.node_attr_keys():
        attrs.append(K.MATCHED_NODE_ID)
    rows, gt_map, gt_ids = [], {}, set(gt.node_ids())
    for r in graph.node_attrs(attr_keys=attrs).iter_rows(named=True):
        submitted = inverse[int(r[K.NODE_ID])]
        matched = r.get(K.MATCHED_NODE_ID)
        matched = None if matched is None or matched == -1 else int(matched)
        if matched is not None:
            require(matched in gt_ids and matched not in gt_map, "nonbijective or unknown GT assignment")
            gt_map[matched] = submitted
        rows.append({"internal_node_id": int(r[K.NODE_ID]), "submitted_node_id": submitted,
                     "gt_node_id": matched, **{k: r[k] for k in COORDS}})
    require(len(rows) == nodes.height, "incomplete node map")
    return Stage(by_id, pairs, gt_map, Counter(by_id.values()), rows)


def frames_from_npz(arrays):
    """Convert common trace arrays; preserve original edge-ID order, not endpoint sort order."""
    keys = {"node_node_id", "node_t", "node_z", "node_y", "node_x", "edge_edge_id", "edge_source_id", "edge_target_id"}
    require(keys <= set(arrays), "missing graph arrays")
    node_count, edge_count = len(arrays["node_node_id"]), len(arrays["edge_edge_id"])
    for k in keys:
        a = arrays[k]
        require(isinstance(a, np.ndarray) and a.ndim == 1 and np.isfinite(a).all(), "invalid graph array")
        require(len(a) == (node_count if k.startswith("node_") else edge_count), "graph array length mismatch")
        if k.endswith("_id") or k == "node_t":
            require(np.issubdtype(a.dtype, np.integer) and np.array_equal(a, a.astype(np.int64)), "lossy graph ID/time")
    require(len(set(arrays["edge_edge_id"].tolist())) == edge_count, "duplicate saved edge ID")
    order = np.argsort(arrays["edge_edge_id"], kind="stable")
    nodes = pl.DataFrame({"node_id": arrays["node_node_id"].astype(np.int64),
                          **{k: arrays[f"node_{k}"] for k in COORDS}})
    edges = pl.DataFrame({k: arrays[f"edge_{k}"][order].astype(np.int64) for k in ("source_id", "target_id")})
    return nodes, edges


def view(stage, source_gt, target_gt):
    source, target = stage.gt_to_submitted.get(source_gt), stage.gt_to_submitted.get(target_gt)
    both = source is not None and target is not None
    return {"source_id": source, "target_id": target,
            "source_position": stage.nodes.get(source), "target_position": stage.nodes.get(target),
            "both_matched": both, "edge_present": both and (source, target) in stage.edges}


def stable_positions(a, b, before, after):
    if not a["both_matched"] or not b["both_matched"]:
        return "unmatched_endpoint"
    positions = (a["source_position"], a["target_position"])
    if positions != (b["source_position"], b["target_position"]):
        return "position_changed"
    if any(before.positions[p] != 1 or after.positions[p] != 1 for p in positions):
        return "ambiguous_duplicate_position"
    return "same_unique_positions"


def diagnose_stages(dataset, pre_frames, post_frames, final_frames, gt, scale):
    stages = {name: map_stage(*frames, gt, scale) for name, frames in
              (("pre", pre_frames), ("post", post_frames), ("final", final_frames))}
    pre, post, final = (stages[k] for k in ("pre", "post", "final"))
    require(all(pre.nodes.get(i) == p for i, p in post.nodes.items()), "ILP selected node changed/unknown")
    require(post.edges <= pre.edges, "ILP selected edge not in candidates")
    records, gt_pairs = [], set()
    gt_node_map = {int(r[K.NODE_ID]): r for r in gt.node_attrs(attr_keys=[K.NODE_ID, K.T]).iter_rows(named=True)}
    for edge in gt.edge_attrs(attr_keys=[]).iter_rows(named=True):
        gs, gt_id = int(edge[K.EDGE_SOURCE]), int(edge[K.EDGE_TARGET])
        require((gs, gt_id) not in gt_pairs, "duplicate GT edge")
        gt_pairs.add((gs, gt_id))
        require(gt_node_map[gt_id][K.T] == gt_node_map[gs][K.T] + 1, "nonadjacent GT edge")
        views = {name: view(stage, gs, gt_id) for name, stage in stages.items()}
        origin = views["pre"]
        s, t = origin["source_id"], origin["target_id"]
        if not origin["both_matched"]:
            loss = "pre_unmatched_endpoint"
        elif not origin["edge_present"]:
            loss = "absent_from_recorded_candidates"
        elif s not in post.nodes or t not in post.nodes:
            loss = "ilp_removed_origin_endpoint"
        elif (s, t) not in post.edges:
            loss = "ilp_removed_origin_edge"
        else:
            loss = "origin_candidate_retained"
        same_assignment = (origin["both_matched"] and views["post"]["both_matched"]
                           and (s, t) == (views["post"]["source_id"], views["post"]["target_id"]))
        records.append({"dataset": dataset, "gt_edge_id": int(edge[K.EDGE_ID]),
                        "gt_source_id": gs, "gt_target_id": gt_id, "stage_views": views,
                        "fixed_pre_pair_state": loss, "pre_post_same_assignment": same_assignment,
                        "post_final_position_relation": stable_positions(views["post"], views["final"], post, final),
                        "matrix_read": False, "official_tp_claimed": False})
    require(len(records) == gt.num_edges(), "incomplete GT edge diagnosis")
    counts = Counter(r["fixed_pre_pair_state"] for r in records)
    summary = {"gt_edges": len(records), "fixed_pre_pair_states": dict(counts),
               "edge_presence_by_stage": {name: sum(r["stage_views"][name]["edge_present"] for r in records)
                                          for name in stages}}
    return {"schema_version": "biohub.association.graph_stage_diagnostic.v1", "dataset": dataset,
            "status": "GRAPH_STAGE_DIAGNOSTIC_COMPLETE", "matching_mode": "distance7um_without_edge_short_circuit",
            "official_score_computed": False, "causal_intervention_performed": False,
            "matrix_read": False, "submission_authorized": False,
            "node_maps": {name: stage.mapping_rows for name, stage in stages.items()},
            "records": records, "summary": summary}


def _index_stage_d2(dataset, stage_records, d2_records):
    """Identity-index stage/D2 rows by gt_edge_id and validate they match exactly."""
    require(type(dataset) is str and dataset, "dataset must be a nonempty str")
    require(type(stage_records) is list, "stage_records must be a list")
    require(type(d2_records) is list, "d2_records must be a list")

    def identity(row, where):
        require(type(row) is dict, f"{where} row must be a dict")
        for field in ("gt_edge_id", "gt_source_id", "gt_target_id"):
            require(field in row, f"{where} row missing {field}")
            value = row[field]
            require(type(value) is int, f"{where} {field} must be an exact int")
        return (row["gt_edge_id"], row["gt_source_id"], row["gt_target_id"])

    stage = {}
    stage_endpoints = set()
    for row in stage_records:
        require(type(row) is dict and row.get("dataset") == dataset, "stage row dataset mismatch")
        edge_id, source_id, target_id = identity(row, "stage")
        require(edge_id not in stage, f"duplicate stage gt_edge_id {edge_id!r}")
        pair = (source_id, target_id)
        require(pair not in stage_endpoints, f"duplicate stage endpoint pair {pair!r}")
        stage_endpoints.add(pair)
        stage[edge_id] = pair

    d2_by_edge_id = {}
    d2_endpoints = set()
    for row in d2_records:
        require(type(row) is dict and row.get("dataset") == dataset, "D2 row dataset mismatch")
        require("baseline" in row and "candidate" in row, "D2 row missing baseline/candidate")
        require("gt_edge_id" in row, "D2 row missing gt_edge_id")
        edge_id = row["gt_edge_id"]
        require(type(edge_id) is int, "D2 gt_edge_id must be an exact int")
        base = identity(row["baseline"], "D2 baseline")
        cand = identity(row["candidate"], "D2 candidate")
        source_id, target_id = base[1], base[2]
        require(edge_id not in d2_by_edge_id, f"duplicate D2 gt_edge_id {edge_id!r}")
        pair = (source_id, target_id)
        require(pair not in d2_endpoints, f"duplicate D2 endpoint pair {pair!r}")
        d2_endpoints.add(pair)
        require(edge_id in stage, f"unexpected D2 gt_edge_id {edge_id!r}")
        triple = (edge_id, source_id, target_id)
        require(base == triple, f"D2 baseline identity mismatch for {edge_id!r}")
        require(cand == triple, f"D2 candidate identity mismatch for {edge_id!r}")
        require(stage[edge_id] == pair, f"stage/D2 endpoint disagreement for {edge_id!r}")
        d2_by_edge_id[edge_id] = row

    missing = set(stage) - set(d2_by_edge_id)
    require(not missing, f"missing D2 rows for gt_edge_ids {sorted(missing)}")
    require(set(d2_by_edge_id) == set(stage), "D2/stage edge ID sets differ")
    return d2_by_edge_id


# --- appended to existing module (join_d2_transitions) ---

_TRANSITION_KEYS = ("retained_tp", "lost_tp", "gained_tp", "shared_fn")
_PRE_PAIR_STATES = (
    "pre_unmatched_endpoint",
    "absent_from_recorded_candidates",
    "ilp_removed_origin_endpoint",
    "ilp_removed_origin_edge",
    "origin_candidate_retained",
)


def _require_exact_bool(value, message):
    if not isinstance(value, bool):
        raise ValueError(message)


def _require_strict_id(value, message):
    if value is None:
        return
    if type(value) is not int:
        raise ValueError(message)


def _side_state(arm, edge_id, side, tp):
    source_matched = arm["matched_source"]
    target_matched = arm["matched_target"]
    csv_present = arm["csv_edge_present"]
    state = arm["state"]
    for name, matched in (("source", source_matched), ("target", target_matched)):
        if matched is None:
            continue
        if not isinstance(matched, dict):
            raise ValueError(
                f"D2 {edge_id} {name} matched must be null or object: {side}"
            )
        if "submitted_node_id" not in matched:
            raise ValueError(
                f"D2 {edge_id} {name} matched requires submitted_node_id: {side}"
            )
        node_id = matched["submitted_node_id"]
        if node_id is None or type(node_id) is not int:
            raise ValueError(
                f"D2 {edge_id} {name} submitted_node_id must be strict int: {side}"
            )
    _require_exact_bool(
        csv_present, f"D2 {edge_id} csv_edge_present must be exact bool: {side}"
    )
    expected = edge_state(
        source_matched=source_matched is not None,
        target_matched=target_matched is not None,
        csv_edge=csv_present,
        tp=tp,
    )
    if state != expected:
        raise ValueError(
            f"D2 {edge_id} state inconsistent ({state} != {expected}): {side}"
        )
    return state


def join_d2_transitions(stage, d2_records):
    """Join per-edge stage diagnostics with D2 baseline/candidate transitions."""
    if not isinstance(stage, dict):
        raise ValueError("stage diagnostic must be an object")
    if stage.get("schema_version") != "biohub.association.graph_stage_diagnostic.v1":
        raise ValueError("unexpected stage schema_version")
    if stage.get("status") != "GRAPH_STAGE_DIAGNOSTIC_COMPLETE":
        raise ValueError("unexpected stage status")
    if stage.get("matching_mode") != "distance7um_without_edge_short_circuit":
        raise ValueError("unexpected stage matching_mode")
    for flag in (
        "official_score_computed",
        "causal_intervention_performed",
        "matrix_read",
        "submission_authorized",
    ):
        if stage.get(flag) is not False:
            raise ValueError(f"stage {flag} must be exactly False")

    index = _index_stage_d2(stage["dataset"], stage["records"], d2_records)

    summary = stage.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("stage summary must be an object")
    gt_edges = summary.get("gt_edges")
    if isinstance(gt_edges, bool) or not isinstance(gt_edges, int) or gt_edges < 0:
        raise ValueError("stage summary gt_edges must be nonnegative strict int")
    if gt_edges != len(stage["records"]):
        raise ValueError("stage summary gt_edges disagrees with record count")
    pre_counts = summary.get("fixed_pre_pair_states")
    if not isinstance(pre_counts, dict):
        raise ValueError("stage summary fixed_pre_pair_states must be an object")
    actual_pre = Counter()
    for record in stage["records"]:
        actual_pre[record["fixed_pre_pair_state"]] += 1
    for _key, value in pre_counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("stage pre-pair counts must be nonnegative strict ints")
    if dict(actual_pre) != dict(pre_counts):
        raise ValueError("stage fixed_pre_pair_states does not match records")

    records = []
    transition_counts = Counter()
    assignment_differences = 0
    presence_differences = 0

    for record in stage["records"]:
        edge_id = record["gt_edge_id"]
        if record.get("matrix_read") is not False:
            raise ValueError("stage record matrix_read must be exactly False")
        if record.get("official_tp_claimed") is not False:
            raise ValueError("stage record official_tp_claimed must be exactly False")
        pre_state = record.get("fixed_pre_pair_state")
        if pre_state not in _PRE_PAIR_STATES:
            raise ValueError(f"unknown fixed_pre_pair_state: {edge_id}")

        views = record.get("stage_views")
        if not isinstance(views, dict) or not isinstance(views.get("final"), dict):
            raise ValueError(f"stage record requires stage_views.final: {edge_id}")
        final = views["final"]
        for key in ("source_id", "target_id"):
            if key not in final:
                raise ValueError(
                    f"stage final missing {key}: {edge_id}"
                )
        final_source = final["source_id"]
        final_target = final["target_id"]
        _require_strict_id(
            final_source, f"stage final source_id must be strict int or null: {edge_id}"
        )
        _require_strict_id(
            final_target, f"stage final target_id must be strict int or null: {edge_id}"
        )
        both_matched = final.get("both_matched")
        edge_present = final.get("edge_present")
        _require_exact_bool(
            both_matched, f"stage final both_matched must be exact bool: {edge_id}"
        )
        _require_exact_bool(
            edge_present, f"stage final edge_present must be exact bool: {edge_id}"
        )
        agrees = final_source is not None and final_target is not None
        if both_matched is not agrees:
            raise ValueError(
                f"stage final both_matched disagrees with ids: {edge_id}"
            )
        if edge_present and not agrees:
            raise ValueError(
                f"stage final edge_present requires both ids: {edge_id}"
            )

        d2_row = index[edge_id]
        baseline = d2_row["baseline"]
        candidate = d2_row["candidate"]
        baseline_state = _side_state(baseline, edge_id, "baseline", baseline["state"] == "tp")
        candidate_state = _side_state(
            candidate, edge_id, "candidate", candidate["state"] == "tp"
        )
        declared = d2_row["transition"]
        expected_transition = transition(baseline_state, candidate_state)
        if declared != expected_transition:
            raise ValueError(
                f"D2 {edge_id} transition mismatch ({declared} != {expected_transition})"
            )
        transition_counts[expected_transition] += 1

        row = copy.deepcopy(record)
        base_source = (baseline["matched_source"] or {}).get("submitted_node_id")
        base_target = (baseline["matched_target"] or {}).get("submitted_node_id")
        row["d2_transition"] = expected_transition
        row["d2_baseline_state"] = baseline_state
        row["d2_candidate_state"] = candidate_state
        assignment_equal = (
            base_source == final_source and base_target == final_target
        )
        presence_equal = baseline["csv_edge_present"] == edge_present
        row["baseline_final_assignment_equal"] = assignment_equal
        row["baseline_final_csv_edge_presence_equal"] = presence_equal
        if not assignment_equal:
            assignment_differences += 1
        if not presence_equal:
            presence_differences += 1
        records.append(row)

    for key in _TRANSITION_KEYS:
        transition_counts.setdefault(key, 0)

    return {
        "schema_version": "biohub.association.stage_d2_join.v1",
        "status": "STAGE_D2_JOIN_COMPLETE_NOT_ADOPTION",
        "dataset": stage["dataset"],
        "records": records,
        "official_score_computed": False,
        "causal_intervention_performed": False,
        "matrix_read": False,
        "submission_authorized": False,
        "summary": {
            "gt_edges": gt_edges,
            "d2_transitions": dict(transition_counts),
            "fixed_pre_pair_states": copy.deepcopy(dict(pre_counts)),
            "baseline_final_assignment_differences": assignment_differences,
            "baseline_final_csv_edge_presence_differences": presence_differences,
        },
    }
