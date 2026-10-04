import hashlib
import json
from pathlib import Path

import pytest

import scripts.experiments.e27.e27_association_prior_screen as m
from biohub.public_postproc import pipeline


def _envelope(mode, entries):
    return json.dumps(
        {"mode": mode, "datasets": list(m.STEMS), "entries": entries},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(mode, entries):
    return hashlib.sha256(_envelope(mode, entries)).hexdigest()


@pytest.fixture
def real_loader():
    return pipeline._load_geff_as_dicts


@pytest.fixture
def prepared():
    pre = {(1, 2): 0.8, (1, 3): 0.6}
    return {
        "datasets": list(m.STEMS),
        "raw_paths": [Path(s + ".geff") for s in m.STEMS],
        "priors_by_dataset": {s: dict(pre) for s in m.STEMS},
    }


@pytest.fixture
def one_edge(monkeypatch, prepared):
    nodes = {1: {"t": 0}, 2: {"t": 1}, 3: {"t": 1}}
    edges = [{"source_id": 1, "target_id": 2, "edge_prob": 0.8}]
    monkeypatch.setattr(
        pipeline, "_load_geff_as_dicts", lambda path: (nodes, edges)
    )
    return prepared


def test_baseline_none(one_edge, real_loader, monkeypatch):
    calls = []

    def boom(path):
        calls.append(path)
        raise AssertionError("loader must not run for baseline_none")

    monkeypatch.setattr(pipeline, "_load_geff_as_dicts", boom)
    mapping, receipt = m.build_prior_inputs(one_edge, "baseline_none")
    assert mapping is None
    assert calls == []
    assert receipt["entries_by_dataset"] == {s: 0 for s in m.STEMS}
    assert receipt["eligible_unselected_by_dataset"] == {s: 0 for s in m.STEMS}
    assert receipt["sha256"] == _digest("baseline_none", [])


def test_selected_only(one_edge):
    mapping, receipt = m.build_prior_inputs(one_edge, "selected_only")
    assert mapping[m.STEMS[0]] == {(1, 2): 0.8}
    assert receipt["entries_by_dataset"] == {s: 1 for s in m.STEMS}
    assert receipt["eligible_unselected_by_dataset"] == {s: 0 for s in m.STEMS}
    assert sum(len(v) for v in mapping.values()) == len(m.STEMS)


def test_no_mutation_and_fresh_maps(one_edge):
    snapshot = json.dumps(
        {s: {f"{a}|{b}": v for (a, b), v in d.items()}
         for s, d in one_edge["priors_by_dataset"].items()},
        sort_keys=True,
    )
    first, _ = m.build_prior_inputs(one_edge, "selected_only")
    second, _ = m.build_prior_inputs(one_edge, "selected_only")
    assert first == second
    assert first is not second
    assert all(first[s] is not second[s] for s in m.STEMS)
    assert json.dumps(
        {s: {f"{a}|{b}": v for (a, b), v in d.items()}
         for s, d in one_edge["priors_by_dataset"].items()},
        sort_keys=True,
    ) == snapshot


def test_receipt_digest_matches_entries(one_edge):
    _, receipt = m.build_prior_inputs(one_edge, "selected_only")
    entries = [[s, 1, 2, 0.8] for s in m.STEMS]
    assert receipt["sha256"] == _digest("selected_only", entries)


def test_recorded_prior_success(one_edge):
    mapping, receipt = m.build_prior_inputs(one_edge, "recorded_prior")
    flat = [entry for s in m.STEMS for entry in ([s, 1, 2, 0.8], [s, 1, 3, 0.6])]
    for s in m.STEMS:
        assert mapping[s] == {(1, 2): 0.8, (1, 3): 0.6}
        assert mapping[s] is not one_edge["priors_by_dataset"][s]
        assert receipt["entries_by_dataset"][s] == 2
        assert receipt["eligible_unselected_by_dataset"][s] == 1
    assert receipt["sha256"] == _digest("recorded_prior", flat)


def test_no_novel_pair_rejected(one_edge):
    for s in m.STEMS:
        del one_edge["priors_by_dataset"][s][(1, 3)]
    with pytest.raises(ValueError, match="no eligible"):
        m.build_prior_inputs(one_edge, "recorded_prior")


def test_nonadjacent_pair_rejected(one_edge, monkeypatch):
    nodes = {1: {"t": 0}, 2: {"t": 1}, 3: {"t": 2}}
    edges = [{"source_id": 1, "target_id": 2, "edge_prob": 0.8}]
    monkeypatch.setattr(pipeline, "_load_geff_as_dicts", lambda *a, **k: (nodes, edges))
    with pytest.raises(ValueError, match="adjacent"):
        m.build_prior_inputs(one_edge, "recorded_prior")
