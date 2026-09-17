"""Wiring tests for run_postproc_core's opt-in association-prior passthrough.

These tests exercise only the pipeline core contract: validation ordering,
snapshot isolation, per-dataset routing, and byte-identical default output.
No model, training, or inference is involved.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from biohub.public_postproc import pipeline as p
from biohub.public_postproc.config import build_config


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fresh_nodes() -> dict[int, dict[str, object]]:
    return {
        1: {"node_id": 1, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0},
        2: {"node_id": 2, "t": 1, "z": 0.0, "y": 0.0, "x": 1.0},
    }


def _fresh_edges() -> list[dict[str, object]]:
    return [{"source_id": 1, "target_id": 2, "edge_prob": 0.7}]


def _install_mocks(monkeypatch, captures: list[dict[str, object]]) -> None:
    def fake_load(_path):
        return _fresh_nodes(), _fresh_edges()

    def fake_filter(cfg, nodes, edges, **kwargs):
        captures.append(dict(kwargs))
        return nodes, edges, p.new_stats()

    monkeypatch.setattr(p, "_load_geff_as_dicts", fake_load)
    monkeypatch.setattr(p, "filter_output_graph", fake_filter)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _run(tmp_path, monkeypatch, priors, *, geff_names=("b.geff", "a.geff"), hooks=None):
    captures: list[dict[str, object]] = []
    _install_mocks(monkeypatch, captures)
    out_csv = tmp_path / "submission.csv"
    cfg = build_config({}, test_dir=tmp_path)
    kwargs = dict(hooks or {})
    result = p.run_postproc_core(
        tuple(tmp_path / name for name in geff_names),
        out_csv,
        cfg,
        deepcenter_loader=lambda _cfg: None,
        write_run_stats_output=False,
        exclusive_output=True,
        association_priors_by_dataset=priors,
        **kwargs,
    )
    return result, out_csv, captures


INVALID_PRIORS = [
    ({}, "outer"),
    ({"b": {}}, "missing dataset"),
    ({"b": {}, "a": {}, "c": {}}, "extra dataset"),
    ([{"b": {}, "a": {}}], "outer list"),
    ({"b": None, "a": {}}, "inner None"),
    ({"b": [], "a": {}}, "inner list"),
    ({1: {}, "a": {}}, "non-str key"),
    ({"b": {(1, "a"): 0.5}, "a": {}}, "bad pair member"),
    ({"b": {(1, 2): 1.5}, "a": {}}, "value above range"),
    ({"b": {(1, 2): -0.1}, "a": {}}, "value below range"),
    ({"b": {(1, 2): float("nan")}, "a": {}}, "non-finite value"),
    ({"b": {(1, 2): "0.5"}, "a": {}}, "non-numeric value"),
]


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------
def test_default_none_keeps_legacy_behaviour(tmp_path, monkeypatch):
    result, out_csv, captures = _run(tmp_path, monkeypatch, None)

    assert [c["dataset"] for c in captures] == ["b", "a"]
    assert all(c["association_priors"] is None for c in captures)
    assert result["datasets"] == ["b", "a"]
    assert result["total_nodes"] == 4
    assert result["total_edges"] == 2
    assert result["total_rows"] == 6
    assert result["run_stats"] is None


def test_empty_inner_maps_produce_identical_bytes(tmp_path, monkeypatch):
    baseline_csv = tmp_path / "baseline"
    baseline_csv.mkdir()
    _, base_path, base_caps = _run(baseline_csv, monkeypatch, None)

    supplied_csv = tmp_path / "supplied"
    supplied_csv.mkdir()
    result, sup_path, sup_caps = _run(supplied_csv, monkeypatch, {"b": {}, "a": {}})

    assert base_path.read_bytes() == sup_path.read_bytes()
    assert result["run_stats"] is None
    assert [c["dataset"] for c in sup_caps] == [c["dataset"] for c in base_caps]
    assert [c["association_priors"] for c in sup_caps] == [{}, {}]


def test_priors_are_routed_per_dataset_in_geff_order(tmp_path, monkeypatch):
    prior_b = {(1, 2): 0.25}
    prior_a = {(2, 1): 0.75}
    supplied = {"b": prior_b, "a": prior_a}

    _, out_csv, captures = _run(tmp_path, monkeypatch, supplied)

    # Row order follows the supplied GEFF sequence, which is deliberately b,a.
    rows = _read_rows(out_csv)
    assert [r["dataset"] for r in rows] == ["b"] * 3 + ["a"] * 3
    assert [r["id"] for r in rows] == [str(i) for i in range(6)]
    assert [r["row_type"] for r in rows] == ["node", "node", "edge"] * 2

    assert captures[0]["dataset"] == "b" and captures[1]["dataset"] == "a"
    assert captures[0]["association_priors"] == {(1, 2): 0.25}
    assert captures[1]["association_priors"] == {(2, 1): 0.75}
    # The caller's dicts were snapshotted, never handed out or mutated.
    assert supplied["b"] == prior_b and supplied["a"] == prior_a
    assert captures[0]["association_priors"] is not prior_b
    assert captures[1]["association_priors"] is not prior_a


def test_hook_cannot_mutate_a_downstream_snapshot(tmp_path, monkeypatch):
    original_a = {(2, 1): 0.75}
    supplied = {"b": {(1, 2): 0.25}, "a": original_a}

    def start_hook(sequence, dataset):
        # Runs before dataset "a" is loaded/filtered; must not leak into "a".
        supplied["a"].clear()
        supplied["a"][(9, 9)] = 0.99

    _, _, captures = _run(
        tmp_path, monkeypatch, supplied, hooks={"dataset_start_hook": start_hook}
    )

    assert captures[0]["dataset"] == "b"
    assert captures[1]["dataset"] == "a"
    assert captures[1]["association_priors"] == {(2, 1): 0.75}


# --------------------------------------------------------------------------
# rejection happens before any side effect
# --------------------------------------------------------------------------
@pytest.mark.parametrize("priors", [case[0] for case in INVALID_PRIORS], ids=[c[1] for c in INVALID_PRIORS])
def test_invalid_priors_rejected_before_any_side_effect(tmp_path, monkeypatch, priors):
    calls: list[str] = []
    monkeypatch.setattr(p, "_load_geff_as_dicts", lambda _path: calls.append("load"))
    monkeypatch.setattr(
        p, "filter_output_graph", lambda *_a, **_k: calls.append("filter")
    )

    def boom(*_args, **_kwargs):
        calls.append("hook")

    out_parent = tmp_path / "never-created"
    out_csv = out_parent / "submission.csv"
    cfg = build_config({}, test_dir=tmp_path)

    with pytest.raises(ValueError):
        p.run_postproc_core(
            (tmp_path / "b.geff", tmp_path / "a.geff"),
            out_csv,
            cfg,
            deepcenter_loader=lambda _cfg: calls.append("deepcenter"),
            dataset_start_hook=boom,
            dataset_finish_hook=boom,
            write_run_stats_output=False,
            exclusive_output=True,
            association_priors_by_dataset=priors,
        )

    assert calls == []
    assert not out_parent.exists()
    assert not out_csv.exists()


def test_duplicate_stems_rejected_with_valid_map(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(p, "_load_geff_as_dicts", lambda _path: calls.append("load"))
    monkeypatch.setattr(
        p, "filter_output_graph", lambda *_a, **_k: calls.append("filter")
    )

    out_parent = tmp_path / "never-created"
    out_csv = out_parent / "submission.csv"
    cfg = build_config({}, test_dir=tmp_path)

    with pytest.raises(ValueError):
        p.run_postproc_core(
            (tmp_path / "a.geff", tmp_path / "a.geff"),
            out_csv,
            cfg,
            deepcenter_loader=lambda _cfg: calls.append("deepcenter"),
            write_run_stats_output=False,
            exclusive_output=True,
            association_priors_by_dataset={"a": {(1, 2): 0.5}},
        )

    assert calls == []
    assert not out_parent.exists()
