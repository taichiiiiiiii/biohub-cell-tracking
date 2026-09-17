"""Synthetic tensors and graphs only; never load the quarantined model source."""

import json
import random
from dataclasses import replace

import numpy as np
import polars as pl
import pytest
import torch
import tracksdata as td

from biohub.association_capture import CaptureLimits
from biohub.association_observer import AssociationObserver


class TablesGraph:
    def __init__(self, nodes, edges):
        self.nodes, self.edges = nodes, edges

    def num_edges(self):
        return self.edges.height

    def node_attrs(self, attr_keys):
        return self.nodes.select(attr_keys)

    def edge_attrs(self, attr_keys):
        return self.edges.select(attr_keys)


def detect(counts):
    return np.array([[t, 1, 2, i + 1] for t, n in enumerate(counts) for i in range(n)],
                    dtype=np.int16).reshape(-1, 4)


def synthetic_prediction(observer=None, counts=(2, 3, 0, 1, 2)):
    coords = detect(counts)
    offsets = np.cumsum([0, *counts])
    edges = []
    if observer:
        observer.start_video("v", len(counts), 2, (1, 4, 4), (1.625, .40625, .40625), "softmax")
    for t, (ns, nt) in enumerate(zip(counts[:-1], counts[1:], strict=True)):
        if observer:
            observer.start_pair(t, offsets[t], offsets[t + 1], offsets[t + 1], offsets[t + 2], coords)
        if not ns or not nt:
            continue
        # Seed/window/side-specific deterministic values, no actual model invocation.
        src = torch.arange(ns * 32, dtype=torch.float32).reshape(1, ns, 32) / 7 + t
        tgt = torch.arange(nt * 32, dtype=torch.float32).reshape(1, nt, 32) / 13 - t
        primary = torch.arange(ns * nt, dtype=torch.float32).reshape(1, ns, nt) / 11
        if observer:
            observer.primary(primary, src, tgt)
        reverse_native = torch.arange(ns * nt, dtype=torch.float32).reshape(1, nt, ns) / 3 + 4
        reverse = reverse_native.transpose(1, 2)
        if observer:
            observer.reverse(reverse)
        secondary = primary * 2 + .125
        if observer:
            observer.secondary(secondary, src * 3, tgt * 5)
        mixed = (primary + reverse + secondary)[0] / 3
        probs = torch.softmax(mixed, dim=0).numpy()
        if observer:
            observer.mixed(mixed, probs)
        # Mutation after callbacks must not change saved raw stage values.
        primary.add_(100)
        secondary.zero_()
        reverse_native.add_(90)
        src.zero_()
        for s, target in zip(*np.where(probs > .48), strict=True):
            i, j = int(offsets[t] + s), int(offsets[t + 1] + target)
            distance = float(np.linalg.norm(coords[i, 1:].astype(np.float32) - coords[j, 1:]))
            edges.append((i, j, float(probs[s, target]), distance))
    original_coords = coords.copy()
    original_coords[:, 1:] *= (1, 4, 4)
    if observer:
        observer.end_video(original_coords, edges)
    return original_coords, edges


def graph_from_prediction(coords, edges):
    graph = td.graph.InMemoryGraph()
    for axis in ("z", "y", "x"):
        graph.add_node_attr_key(axis, pl.Float64, 0.)
    ids = graph.bulk_add_nodes([{"t": int(t), "z": float(z), "y": float(y), "x": float(x)}
                                for t, z, y, x in coords])
    if edges:
        for attr in ("edge_prob", "edge_dist"):
            graph.add_edge_attr_key(attr, pl.Float64, 0.)
        graph.bulk_add_edges([{"source_id": ids[s], "target_id": ids[t], "edge_prob": p, "edge_dist": d}
                              for s, t, p, d in edges])
    return graph, ids


def full_capture(observer, counts=(2, 3, 0, 1, 2)):
    coords, edges = synthetic_prediction(observer, counts)
    graph, ids = graph_from_prediction(coords, edges)
    observer.pre_graph(coords, edges, ids, graph)
    observer.selected_graph(graph)
    return observer.finish()


def test_observer_off_on_prediction_and_all_cpu_rng_states_equal(tmp_path):
    def state():
        return random.getstate(), np.random.get_state(), torch.get_rng_state().clone()

    before = state()
    off_coords, off_edges = synthetic_prediction()
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3, 0, 1, 2]})
    on_coords, on_edges = synthetic_prediction(observer)
    assert on_coords.tobytes() == off_coords.tobytes() and on_edges == off_edges
    graph, ids = graph_from_prediction(on_coords, on_edges)
    pre_nodes = graph.node_attrs(attr_keys=["z", "y", "x"]).clone()
    pre_edges = graph.edge_attrs(attr_keys=["edge_prob", "edge_dist"]).clone()
    observer.pre_graph(on_coords, on_edges, ids, graph)
    observer.selected_graph(graph)
    result = observer.finish()
    assert graph.node_attrs(attr_keys=["z", "y", "x"]).equals(pre_nodes)
    assert graph.edge_attrs(attr_keys=["edge_prob", "edge_dist"]).equals(pre_edges)
    after = state()
    assert before[0] == after[0]
    assert before[1][0] == after[1][0] and np.array_equal(before[1][1], after[1][1])
    assert before[1][2:] == after[1][2:] and torch.equal(before[2], after[2])
    assert result["graph_ID_mapping_complete"] and not result["inference_parity_verified"]
    assert not result["submission_authorized"]
    with np.load(observer.root / "pairs/v/pair_0000.npz", allow_pickle=False) as packet:
        expected_reverse = torch.arange(6, dtype=torch.float32).reshape(1, 3, 2) / 3 + 4
        assert np.array_equal(packet["primary_reverse_logits"], expected_reverse.transpose(1, 2)[0].numpy())
        assert np.array_equal(packet["primary_forward_logits"], np.arange(6, dtype=np.float32).reshape(2, 3) / 11)
        assert packet["primary_source_features"][0, 1] != 0
    with np.load(observer.root / "pairs/v/pair_0001.npz", allow_pickle=False) as packet:
        assert json.loads(str(packet["metadata"]))["status"] == "SKIPPED_EMPTY"
    with np.load(observer.root / "v_pre_ilp.npz", allow_pickle=False) as packet:
        assert np.array_equal(packet["graph_node_ids"], ids)
        assert np.array_equal(packet["detector_indices"], np.arange(len(ids)))


@pytest.mark.parametrize("counts", [(0, 0, 0), (0, 3, 0), (1, 1), (3, 2, 1)])
def test_empty_and_single_and_rectangular_graphs(tmp_path, counts):
    observer = AssociationObserver(tmp_path / "capture", {"v": list(counts)})
    result = full_capture(observer, counts)
    assert result["status"] == "ASSOCIATION_OBSERVATION_COMPLETE_NOT_PARITY"


@pytest.mark.parametrize("case", ["offsets", "window", "scale", "activation", "frames", "missing_stage"])
def test_bad_plan_or_stage_fails_closed(tmp_path, case):
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3]})
    with pytest.raises(ValueError):
        observer.start_video("v", 3 if case == "frames" else 2, 3 if case == "window" else 2,
                             (1, 4, 4), (1, 1, 1) if case == "scale" else (1.625, .40625, .40625),
                             "sigmoid" if case == "activation" else "softmax")
        if case == "missing_stage":
            observer.reverse(torch.ones(1, 2, 3))
        else:
            observer.start_pair(0, 0, 2, 2, 99, detect((2, 3)))
    assert observer.failed and (observer.root / "ERROR.json").exists()
    with pytest.raises(ValueError, match="failed or closed"):
        observer.finish()
    assert not (observer.root / "MANIFEST.json").exists()


@pytest.mark.parametrize("case", ["mapping", "coordinates", "edge_probability", "selected_node",
                                  "selected_edge", "duplicate_edge", "corrupt_file", "incomplete"])
def test_graph_mutation_and_incomplete_run_rejected(tmp_path, case):
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3]})
    coords, edges = synthetic_prediction(observer, (2, 3))
    graph, ids = graph_from_prediction(coords, edges)
    nodes, edge_table = observer._graph_tables(graph)
    if case == "mapping":
        ids = ids[::-1]
    elif case == "coordinates":
        coords[0, 1] += 1
    elif case == "edge_probability":
        graph = TablesGraph(nodes, edge_table.with_columns(pl.lit(.125).alias("edge_prob")))
    with pytest.raises(ValueError):
        observer.pre_graph(coords, edges, ids, graph)
        if case == "incomplete":
            observer.finish()
        if case == "selected_node":
            nodes = nodes.with_columns((pl.col("z") + 1).alias("z"))
        if case == "selected_edge":
            edge_table = edge_table.with_columns(pl.lit(.01).alias("edge_prob"))
        if case == "duplicate_edge":
            edge_table = pl.concat([edge_table, edge_table.head(1)])
        observer.selected_graph(TablesGraph(nodes, edge_table))
        if case == "corrupt_file":
            with (observer.root / "v_pre_ilp.npz").open("ab") as stream:
                stream.write(b"bad")
        observer.finish()
    assert observer.failed and not (observer.root / "MANIFEST.json").exists()


def test_selected_subset_and_reordered_graph_rows_keep_actual_id_map(tmp_path):
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3]})
    coords, edges = synthetic_prediction(observer, (2, 3))
    graph, ids = graph_from_prediction(coords, edges)
    nodes, edge_table = observer._graph_tables(graph)
    # Deliberately non-row IDs even if installed tracksdata currently uses contiguous IDs.
    mapping = {i: i * 7 + 100 for i in ids}
    nodes = nodes.with_columns(pl.col("node_id").replace_strict(mapping))
    edge_table = edge_table.with_columns(pl.col("source_id").replace_strict(mapping),
                                         pl.col("target_id").replace_strict(mapping))
    observer.pre_graph(coords, edges, [mapping[i] for i in ids], TablesGraph(nodes.reverse(), edge_table.reverse()))
    subset = edge_table.head(1)
    selected_ids = subset["source_id"].to_list() + subset["target_id"].to_list()
    observer.selected_graph(TablesGraph(nodes.filter(pl.col("node_id").is_in(selected_ids)), subset))
    assert observer.finish()["graph_ID_mapping_complete"]


def test_observer_time_includes_cpu_copy(tmp_path, monkeypatch):
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3]})
    times = iter([0., 1201.])
    monkeypatch.setattr("biohub.association_observer.time.perf_counter", lambda: next(times))
    with pytest.raises(ValueError, match="time budget"):
        observer.start_video("v", 2, 2, (1, 4, 4), (1.625, .40625, .40625), "softmax")


def test_pair_plus_graph_budget_is_joint(tmp_path):
    probe = AssociationObserver(tmp_path / "probe", {"v": [2, 3]})
    full_capture(probe, (2, 3))
    pair_bytes = probe.pairs.output_bytes
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3]},
                                   limits=replace(CaptureLimits(), output_bytes=pair_bytes + 1))
    with pytest.raises(ValueError, match="byte budget"):
        full_capture(observer, (2, 3))
    assert observer.failed


def test_existing_root_rejected_without_overwrite(tmp_path):
    root = tmp_path / "capture"
    AssociationObserver(root, {"v": [2, 3]})
    with pytest.raises(ValueError, match="already exists"):
        AssociationObserver(root, {"v": [2, 3]})


@pytest.mark.parametrize("case", ["missing", "probability", "distance", "duplicate"])
def test_returned_candidates_are_exactly_saved_dense_threshold_selection(tmp_path, case, monkeypatch):
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3]})
    original_end = observer.end_video

    def corrupt(coords, edges):
        if case == "missing":
            edges = edges[1:]
        elif case == "duplicate":
            edges = edges + edges[:1]
        else:
            first = list(edges[0])
            first[2 if case == "probability" else 3] += .01
            edges = [tuple(first), *edges[1:]]
        return original_end(coords, edges)

    monkeypatch.setattr(observer, "end_video", corrupt)
    with pytest.raises(ValueError, match="candidates differ|duplicate returned"):
        synthetic_prediction(observer, (2, 3))
    assert observer.failed


@pytest.mark.parametrize("override", [{"threshold": .1}, {"threshold": .2},
                                     {"max_parents": 1}, {"max_children": 2}])
def test_non_e23_greedy_candidate_policy_rejected(tmp_path, override):
    observer = AssociationObserver(tmp_path / "capture", {"v": [2, 3]})
    with pytest.raises(ValueError, match="candidate filtering mismatch"):
        observer.start_video("v", 2, 2, (1, 4, 4), (1.625, .40625, .40625), "softmax", **override)
