"""Synthetic module API tests, no external model import or competition data."""

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest
import torch
import tracksdata as td

from biohub.association_parity import (
    CFG,
    E23_ENV,
    capture_module,
    compare_results,
    graph_arrays,
    semantic_graph_signature,
)


def fake_module():
    module = SimpleNamespace(PredictConfig=lambda **kw: SimpleNamespace(**kw))
    coords = np.array([[0, 1, 8, 4], [1, 1, 8, 4]], dtype=np.int16)
    edges = [(0, 1, 1., 0.)]

    def video(model, path, device, **kwargs):
        observer = kwargs.get("association_observer")
        if observer:
            observer.start_video(path.stem, 100, 2, (1, 4, 4), (1.625, .40625, .40625), "softmax")
            grid = coords.copy()
            grid[:, 1:] //= (1, 4, 4)
            observer.start_pair(0, 0, 1, 1, 2, grid)
            matrix = torch.ones((1, 1, 1))
            feat = torch.ones((1, 1, 32))
            observer.primary(matrix, feat, feat)
            observer.reverse(matrix)
            observer.secondary(matrix, feat, feat)
            observer.mixed(matrix[0], matrix[0].numpy())
            observer.start_pair(1, 1, 2, 2, 2, grid)
            for t in range(2, 99):
                observer.start_pair(t, 2, 2, 2, 2, grid)
            observer.end_video(coords, edges)
        return coords, edges

    def build(coords, edges, association_observer=None):
        graph = td.graph.InMemoryGraph()
        for k in ("z", "y", "x"):
            graph.add_node_attr_key(k, pl.Float64, 0.)
        ids = graph.bulk_add_nodes([dict(t=int(t), z=float(z), y=float(y), x=float(x)) for t, z, y, x in coords])
        for k in ("edge_prob", "edge_dist"):
            graph.add_edge_attr_key(k, pl.Float64, 0.)
        graph.bulk_add_edges([dict(source_id=ids[s], target_id=ids[t], edge_prob=p, edge_dist=d)
                              for s, t, p, d in edges])
        if association_observer:
            association_observer.pre_graph(coords, edges, ids, graph)
        return graph

    def predict(**kwargs):
        assert vars(kwargs["cfg"]) == CFG
        assert kwargs["evaluate"] is False and kwargs["fold"] == 0 and kwargs["unet_batch_size"] == 4
        for name in ("v0", "v1", "v2", "v3"):
            obs = kwargs.get("association_observer")
            c, e = module.predict_video(None, Path(name + ".zarr"), None, association_observer=obs)
            graph = module.build_graph(c, e, association_observer=obs)
            if obs:
                obs.selected_graph(graph)
            module.save_graph(graph, Path(name + ".geff"))

    module.predict_video, module.build_graph = video, build
    module.save_graph = lambda graph, path: None
    module.predict = predict
    expected_graph = semantic_graph_signature(graph_arrays(build(coords, edges)))
    record = {"frame_counts": [1, 1] + [0] * 98,
              "coordinate_sha256": hashlib.sha256(coords.tobytes()).hexdigest(),
              "raw_graph_signature": expected_graph}
    plan = {"datasets": {f"v{i}": copy.deepcopy(record) for i in range(4)},
            "data_dir": "images", "splits_file": "splits.json", "primary_weights": "primary.pth"}
    return module, plan


def test_common_bridge_off_on_full_video_coverage_and_restore(tmp_path):
    module, plan = fake_module()
    original = module.predict_video, module.build_graph, module.save_graph
    results = {}
    for arm in ("off", "on"):
        root = tmp_path / arm
        root.mkdir()
        result = capture_module(module, plan, root, arm)
        assert (module.predict_video, module.build_graph, module.save_graph) == original
        assert result["dataset_order"] == ["v0", "v1", "v2", "v3"] and len(result["records"]) == 12
        result.update(status="ARM_COMPLETE", arm=arm, input_inventory=[], dependencies={},
                      environment=E23_ENV, model_config=CFG, rng_after={}, plan_sha256="same-plan")
        results[arm] = result
    assert results["off"]["records"] == results["on"]["records"]
    assert compare_results(results["off"], results["on"])["status"] == "PUBLIC4_ASSOCIATION_OBSERVER_PARITY_PASS"
    assert (tmp_path / "on/observation/MANIFEST.json").exists()
    assert not (tmp_path / "off/observation").exists()


@pytest.mark.parametrize("case", ["coords", "raw", "missing_video"])
def test_bridge_reference_failure_never_completes(tmp_path, case):
    module, plan = fake_module()
    original = module.predict_video, module.build_graph, module.save_graph
    if case == "coords":
        plan["datasets"]["v0"]["coordinate_sha256"] = "bad"
    elif case == "raw":
        plan["datasets"]["v0"]["raw_graph_signature"] = {}
    else:
        module.predict = lambda **kwargs: None
    with pytest.raises(ValueError, match="mismatch|incomplete"):
        capture_module(module, plan, tmp_path, "off")
    assert (module.predict_video, module.build_graph, module.save_graph) == original


@pytest.mark.parametrize("field", ["records", "input_inventory", "dependencies", "environment",
                                  "rng_after", "model_config", "dataset_order", "plan_sha256"])
def test_any_paired_drift_rejected(field):
    common = {k: {} for k in ("records", "input_inventory", "dependencies", "environment", "rng_after", "model_config")}
    common.update(status="ARM_COMPLETE", dataset_order=["v0", "v1", "v2", "v3"], plan_sha256="same")
    common["records"] = [{"dataset": name, "stage": stage} for name in common["dataset_order"]
                         for stage in ("returned", "pre", "post")]
    off = dict(common, arm="off", observation_complete=False)
    on = dict(copy.deepcopy(common), arm="on", observation_complete=True)
    on[field] = "different"
    with pytest.raises(ValueError, match="mismatch|coverage"):
        compare_results(off, on)


def test_no_complete_status_without_observer():
    common = {k: {} for k in ("records", "input_inventory", "dependencies", "environment", "rng_after", "model_config")}
    common.update(status="ARM_COMPLETE", dataset_order=[], plan_sha256="same")
    with pytest.raises(ValueError, match="incomplete"):
        compare_results(dict(common, arm="off"), dict(common, arm="on", observation_complete=False))
