"""Orchestration-only tests for ``e27_association_prior_screen.execute_baseline_core``.

These tests never generate or infer anything: every heavy collaborator
(``run_postproc_core``, the deepcenter loader, CSV/bounds/raw validators) is a
mock, and the fixture data are synthetic labels only (no competition data). The
only real collaborator is ``write_json_exclusive``, so the persisted JSON files
are genuinely written. Tests assert orchestration shape: event ordering, file
contents, validator invocation, and failure-path partial persistence.
"""

import copy
import json

import pytest

from biohub import e26_screen as e
from biohub.public_postproc import pipeline
from scripts import e27_association_prior_screen as m

STEMS = list(m.STEMS)
N = len(STEMS)
SHAPE = (100, 64, 256, 256)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _prepared(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    prepared = {
        "datasets": list(STEMS),
        "raw_paths": [out / f"{name}.geff" for name in STEMS],
        "shapes": {name: SHAPE for name in STEMS},
    }
    return prepared, out


def _report():
    return {
        "datasets": list(STEMS),
        "total_nodes": 24,
        "total_edges": 12,
        "total_rows": 36,
    }


class Recorder:
    """Records calls to check_budget-style zero-arg callables."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"elapsed_s": float(self.calls)}


def _install_core(monkeypatch, behavior, bundle, cfg):
    """Install a fake ``pipeline.run_postproc_core`` driving *behavior*.

    Returns dict of recorded state shared with the assertions.
    """

    state = {
        "core_calls": [],
        "loader_calls": 0,
        "loader_cfgs": [],
        "events": [],
        "wrote_csv": False,
    }

    def fake_core(paths, csv_path, actual_cfg, **kw):
        state["core_calls"].append((tuple(paths), csv_path, actual_cfg, kw))
        assert "association_priors_by_dataset" not in kw

        loader = kw["deepcenter_loader"]
        start = kw["dataset_start_hook"]
        finish = kw["dataset_finish_hook"]
        raw_stats = kw["raw_stats_hook"]

        if behavior == "loader_wrong_cfg":
            loader(object())
            return _report()

        if behavior == "loader_twice":
            first = loader(cfg)
            second = loader(cfg)
            assert first is bundle and second is bundle
            return _report()

        # Normal single load; returns the injected bundle identity.
        loaded = loader(cfg)
        assert loaded is bundle

        if behavior == "wrong_event_name":
            start(0, "wrong")
            return _report()

        if behavior == "core_raises_after_first_start":
            start(0, STEMS[0])
            raise RuntimeError("synthetic core failure")

        for seq, name in enumerate(STEMS):
            start(seq, name)
            raw_stats({"dataset": name})
            finish(seq, name)

        csv_path.write_text("synthetic\n", encoding="utf-8")
        state["wrote_csv"] = True
        return _report()

    monkeypatch.setattr(pipeline, "run_postproc_core", fake_core)
    return state


def _install_validators(monkeypatch, report=None):
    calls = {"csv": 0, "bounds": 0, "raw": 0}
    report = _report() if report is None else report

    def fake_validate_generated_csv(csv_path, datasets, shapes):
        calls["csv"] += 1
        return report

    def fake_bounds(snapshot, csv_path, shapes):
        calls["bounds"] += 1
        return None

    def fake_raw(raw_rows, arm, csv_report):
        calls["raw"] += 1
        assert arm == "baseline"
        assert csv_report is report
        return None

    monkeypatch.setattr(e, "validate_generated_csv", fake_validate_generated_csv)
    monkeypatch.setattr(e, "_validate_screen_bounds", fake_bounds)
    monkeypatch.setattr(m, "validate_known12_statistics", fake_raw)
    return calls


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------

def test_execute_baseline_core_happy_path(tmp_path, monkeypatch):
    prepared, output = _prepared(tmp_path)
    snapshot = copy.deepcopy(prepared)

    cfg = object()
    bundle = object()
    budget = Recorder()
    state = _install_core(monkeypatch, "happy", bundle, cfg)
    validator_calls = _install_validators(monkeypatch)

    result = m.execute_baseline_core(prepared, cfg, bundle, output, budget)

    # Core was invoked exactly once with cfg positional third and no priors arg.
    assert len(state["core_calls"]) == 1
    paths, csv_path, actual_cfg, kw = state["core_calls"][0]
    assert actual_cfg is cfg
    assert paths == tuple(prepared["raw_paths"])
    assert csv_path == output / "submission.csv"
    assert "association_priors_by_dataset" not in kw
    assert kw["write_run_stats_output"] is False
    assert kw["exclusive_output"] is True

    # Loader called exactly once and returned the injected bundle.
    assert result["loader_calls"] == 1

    # 36 events in exact start/raw_stats/finish order per dataset.
    events = result["events"]
    assert len(events) == 36
    kinds = ["start", "raw_stats", "finish"]
    for idx, ev in enumerate(events):
        seq = idx // 3
        assert ev["event"] == kinds[idx % 3]
        assert ev["sequence"] == seq
        assert ev["dataset"] == STEMS[seq]
        assert isinstance(ev["timing"], dict)

    # Raw rows mirror the datasets actually reported by the fake core.
    assert [r["dataset"] for r in result["raw_rows"]] == STEMS

    # All three validators ran once.
    assert validator_calls == {"csv": 1, "bounds": 1, "raw": 1}

    # Real write_json_exclusive persisted all three sidecar files.
    on_disk_events = json.loads((output / "events.json").read_text(encoding="utf-8"))
    on_disk_raw = json.loads((output / "raw_statistics.json").read_text(encoding="utf-8"))
    on_disk_bounds = json.loads((output / "output_bounds.json").read_text(encoding="utf-8"))
    assert len(on_disk_events) == 36
    assert len(on_disk_raw) == N
    assert on_disk_events == events
    assert on_disk_raw == result["raw_rows"]
    assert isinstance(on_disk_bounds, (dict, list))
    assert result["bounds"] == on_disk_bounds

    # Report passthrough / consistency fields.
    assert result["report"]["total_nodes"] == 24
    assert result["report"]["total_edges"] == 12
    assert result["report"]["total_rows"] == 36

    # No success RESULT artifact is produced by the target function.
    assert not any(p.name.upper().startswith("RESULT") for p in output.iterdir())

    # check_budget was consulted per event plus one final time.
    assert budget.calls == 37

    # Prepared input is unmodified.
    assert prepared == snapshot


# ---------------------------------------------------------------------------
# negative modes
# ---------------------------------------------------------------------------

NEGATIVE_MODES = [
    "loader_wrong_cfg",
    "loader_twice",
    "wrong_event_name",
    "core_raises_after_first_start",
]


@pytest.mark.parametrize("mode", NEGATIVE_MODES)
def test_execute_baseline_core_failure_persists_partial_state(tmp_path, monkeypatch, mode):
    prepared, output = _prepared(tmp_path)
    cfg = object()
    bundle = object()
    budget = Recorder()
    _install_core(monkeypatch, mode, bundle, cfg)
    _install_validators(monkeypatch)

    expected = {
        "loader_wrong_cfg": ValueError,
        "loader_twice": RuntimeError,
        "wrong_event_name": ValueError,
        "core_raises_after_first_start": RuntimeError,
    }[mode]
    with pytest.raises(expected):
        m.execute_baseline_core(prepared, cfg, bundle, output, budget)

    # finally-block artifacts exist and reflect partial progress.
    events_path = output / "events.json"
    raw_path = output / "raw_statistics.json"
    bounds_path = output / "output_bounds.json"
    assert events_path.is_file()
    assert raw_path.is_file()
    assert bounds_path.is_file()

    events = json.loads(events_path.read_text(encoding="utf-8"))
    raw_rows = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw_rows == [], "raw hook must not have run for mode: " + mode
    bounds = json.loads(bounds_path.read_text(encoding="utf-8"))
    assert bounds is not None

    # Never a full run, never a success marker.
    assert len(events) < 36
    assert not (output / "submission.csv").exists()
    assert not any(p.name.upper().startswith("RESULT") for p in output.iterdir())


def test_execute_baseline_core_forwards_association_priors(tmp_path, monkeypatch):
    prepared, output = _prepared(tmp_path)
    cfg = {"source_csvs": [str(output)]}
    bundle = object()
    budget = Recorder()
    _install_core(monkeypatch, "happy", bundle, cfg)
    calls = _install_validators(monkeypatch)
    original = pipeline.run_postproc_core

    priors = {s: {(1, 2): 0.8} for s in m.STEMS}
    snapshot = copy.deepcopy(priors)
    seen = []

    def forwarded(*args, **kwargs):
        assert kwargs.pop("association_priors_by_dataset") is priors
        seen.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_postproc_core", forwarded)
    report = m.execute_baseline_core(prepared, cfg, bundle, output, budget,
                                     association_priors_by_dataset=priors)
    assert len(seen) == 1
    assert priors == snapshot
    assert report["loader_calls"] == 1
    assert calls == {"csv": 1, "bounds": 1, "raw": 1}
    assert len(report["events"]) == 36


def test_execute_baseline_core_forwards_appearance_loader(tmp_path, monkeypatch):
    prepared, output = _prepared(tmp_path)
    cfg = object()
    bundle = object()
    budget = Recorder()
    state = _install_core(monkeypatch, "happy", bundle, cfg)
    _install_validators(monkeypatch)

    def callback(dataset, raw_nodes):
        return {0: {}}

    result = m.execute_baseline_core(
        prepared, cfg, bundle, output, budget, appearance_loader=callback)

    assert state["core_calls"][0][3]["appearance_loader"] is callback
    assert "association_priors_by_dataset" not in state["core_calls"][0][3]
    assert len(result["events"]) == 36
    assert result["loader_calls"] == 1


def test_execute_baseline_core_rejects_bad_or_mixed_loader_inputs(tmp_path):
    output = tmp_path / "never-created"
    prepared = {"datasets": list(STEMS)}

    for bad, prior in ((3, None), (lambda *_: {}, {})):
        with pytest.raises(ValueError):
            m.execute_baseline_core(
                prepared, object(), object(), output, lambda: {},
                appearance_loader=bad, association_priors_by_dataset=prior)

    assert not output.exists()
