import copy
import csv
import weakref

import numpy as np
import pytest

from biohub.public_postproc import pipeline as p
from biohub.public_postproc.config import build_config

OFF_ENV = {
    "BIOHUB_OUTPUT_SINGLE_PARENT_REPAIR": "0",
    "BIOHUB_OUTPUT_SINGLE_CHILD_REPAIR": "0",
    "BIOHUB_OUTPUT_GAP_CLOSE": "0",
    "BIOHUB_OUTPUT_GAP2_RECOVERY": "0",
    "BIOHUB_OUTPUT_SAFE_DIVISIONS": "0",
    "BIOHUB_OUTPUT_DIVISION_GEOMETRY_FILTER": "0",
    "BIOHUB_OUTPUT_PRUNE_ISOLATED": "0",
    "BIOHUB_OUTPUT_FILTER_SHORT_TRACKS": "0",
    "BIOHUB_OUTPUT_LINEFIT_SMOOTH": "0",
    "BIOHUB_ADAPTIVE_SHORT_TRACK_RESCUE": "0",
    "BIOHUB_USE_DEEPCENTER_VETO": "0",
    "BIOHUB_REFINE_ALL_CENTROIDS": "0",
    "BIOHUB_OUTPUT_MOTION_RELINK": "1",
}

DIM = 32


def _nodes():
    return {
        1: {"node_id": 1, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0},
        2: {"node_id": 2, "t": 1, "z": 0.0, "y": 0.0, "x": 1.0},
        3: {"node_id": 3, "t": 1, "z": 0.0, "y": 0.0, "x": 2.0},
    }


def _raw_edges():
    return [
        {"source_id": 1, "target_id": 2, "edge_prob": 0.8},
        {"source_id": 1, "target_id": 3, "edge_prob": 0.7},
    ]


def _frames(zero=False):
    e0 = np.zeros(DIM, dtype=np.float32)
    e0[0] = 1.0
    frame = {
        "t_source": 0,
        "t_target": 1,
        "source_ids": [1],
        "target_ids": [2, 3],
        "primary_source_features": e0[None, :],
        "secondary_source_features": e0[None, :],
        "primary_target_features": np.stack([e0 if zero else -e0, e0]),
        "secondary_target_features": np.stack([e0 if zero else -e0, e0]),
    }
    return {0: frame}


@pytest.fixture
def env(tmp_path):
    cfg = build_config(OFF_ENV, test_dir=tmp_path)
    geffs = tuple(tmp_path / name for name in ("b.geff", "a.geff"))
    state = {
        "calls": [],
        "loads": [],
        "pairs": [],
        "xs": [],
        "filters": 0,
        "deepcenter": 0,
        "refs": [],
    }

    def loader(path):
        state["loads"].append(path.stem)
        return copy.deepcopy(_nodes()), copy.deepcopy(_raw_edges())

    real_filter = p.filter_output_graph

    def spy(cfg, nodes, edges, **kwargs):
        state["filters"] += 1
        state["xs"].append(dict(nodes)[1]["x"])
        result = real_filter(cfg, nodes, edges, **kwargs)
        state["pairs"].append(
            sorted((int(e["source_id"]), int(e["target_id"])) for e in result[1])
        )
        return result

    def deepcenter_loader(_cfg):
        state["deepcenter"] += 1
        return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(p, "_load_geff_as_dicts", loader)
    monkeypatch.setattr(p, "filter_output_graph", spy)
    yield cfg, geffs, state, deepcenter_loader
    monkeypatch.undo()


def _run(tmp_path, cfg, geffs, out_name, appearance_loader, present=True):
    kwargs = {} if not present else {"appearance_loader": appearance_loader}
    return p.run_postproc_core(
        geffs,
        tmp_path / out_name,
        cfg,
        deepcenter_loader=lambda _cfg: None,
        write_run_stats_output=False,
        exclusive_output=True,
        **kwargs,
    )


def _rows(out_csv):
    with out_csv.open(newline="") as fh:
        return list(csv.DictReader(fh))


def test_equivalence_of_appearance_loader(env, tmp_path):
    cfg, geffs, state, _dc = env

    res_omitted = _run(tmp_path, cfg, geffs, "omitted.csv", None, present=False)
    res_none = _run(tmp_path, cfg, geffs, "none.csv", None, present=True)

    def zero_callback(dataset, raw_nodes):
        state["calls"].append(dataset)
        return _frames(zero=True)

    res_cb = _run(tmp_path, cfg, geffs, "cb.csv", zero_callback)

    assert state["calls"] == ["b", "a"]
    for res in (res_omitted, res_none, res_cb):
        assert res["total_nodes"] == 6
        assert res["total_edges"] == 2
    b = [(tmp_path / n).read_bytes() for n in ("omitted.csv", "none.csv", "cb.csv")]
    assert b[0] == b[1] == b[2]
    rows = _rows(tmp_path / "cb.csv")
    assert len(rows) == 8
    assert state["filters"] == 3 * len(geffs)


def test_callback_flip_copy_isolation_and_lifetime(env, tmp_path):
    cfg, geffs, state, _dc = env
    seen = []

    def loader(dataset, raw_nodes):
        if seen:
            assert seen[-1]() is None
        state["calls"].append(dataset)
        assert raw_nodes[1]["x"] == 0.0
        raw_nodes[1]["x"] = 999.0
        frames = _frames(zero=False)
        seen.append(weakref.ref(frames[0]["primary_source_features"]))
        return frames

    res = _run(tmp_path, cfg, geffs, "flip.csv", loader)

    assert res["total_nodes"] == 6
    assert res["total_edges"] == 2
    assert state["calls"] == ["b", "a"]
    assert state["xs"] == [0.0, 0.0]
    assert state["pairs"] == [[(1, 3)], [(1, 3)]]
    assert state["filters"] == 2


@pytest.mark.parametrize("bad", [None, {}, [], object()])
def test_bad_loader_raises_before_filter(env, tmp_path, bad):
    cfg, geffs, state, _dc = env
    out_csv = tmp_path / "bad.csv"
    with pytest.raises(ValueError):
        _run(tmp_path, cfg, geffs, "bad.csv", lambda dataset, raw_nodes: bad)
    assert state["filters"] == 0
    assert state["loads"] == ["b"]
    assert state["calls"] == []
    assert out_csv.exists()
    assert _rows(out_csv) == []


@pytest.mark.parametrize(
    "case",
    ["noncallable", "motion_off", "priors_mix", "duplicate_geffs"],
)
def test_invalid_arguments_fail_before_any_io(env, tmp_path, case):
    cfg, geffs, state, deepcenter_loader = env
    parent = tmp_path / "nested"
    out_csv = parent / "out.csv"

    kwargs = {
        "deepcenter_loader": deepcenter_loader,
        "write_run_stats_output": False,
        "exclusive_output": True,
    }
    good_loader = lambda dataset, raw_nodes: _frames(zero=True)  # noqa: E731

    if case == "noncallable":
        call_kwargs = {"appearance_loader": 3}
        use_cfg = cfg
        use_geffs = geffs
    elif case == "motion_off":
        motion_off = dict(OFF_ENV)
        motion_off["BIOHUB_OUTPUT_MOTION_RELINK"] = "0"
        call_kwargs = {"appearance_loader": good_loader}
        use_cfg = build_config(motion_off, test_dir=tmp_path)
        use_geffs = geffs
    elif case == "priors_mix":
        call_kwargs = {
            "appearance_loader": good_loader,
            "association_priors_by_dataset": {},
        }
        use_cfg = cfg
        use_geffs = geffs
    else:
        call_kwargs = {"appearance_loader": good_loader}
        use_cfg = cfg
        use_geffs = (geffs[0], geffs[0])

    with pytest.raises(ValueError):
        p.run_postproc_core(use_geffs, out_csv, use_cfg, **kwargs, **call_kwargs)

    assert state["filters"] == 0
    assert state["loads"] == []
    assert state["calls"] == []
    assert state["deepcenter"] == 0
    assert not parent.exists()
