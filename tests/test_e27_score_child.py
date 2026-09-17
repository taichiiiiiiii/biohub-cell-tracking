"""Synthetic lifecycle unit tests for e27_prior_score.run_score_child.

These mock all scoring boundaries and use a fake signal module. They do not
establish parent supervision, freshprocess behavior, or real scoring.
"""
import copy
import json
import signal

import pytest

from biohub import e26_screen as e
from scripts import e27_prior_score as m


class FakeSignal:
    ITIMER_REAL = signal.ITIMER_REAL
    SIGALRM = getattr(signal, "SIGALRM", 14)
    SIG_DFL = signal.SIG_DFL

    def __init__(self):
        self.handler = signal.SIG_DFL
        self.timer = (0.0, 0.0)
        self.set_calls = []

    def getitimer(self, which):
        return self.timer

    def getsignal(self, which):
        return self.handler

    def signal(self, which, handler):
        old = self.handler
        self.handler = handler
        return old

    def setitimer(self, which, seconds, *rest):
        self.set_calls.append((which, seconds))
        self.timer = (seconds, 0.0 if seconds else 0.0)
        return self.timer


@pytest.fixture
def box(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    out = root / "outputs" / "local" / "scorefresh"
    planfolder = root / "outputs" / "local" / "plan"
    cand = root / "outputs" / "local" / "siblingcandidate"
    for d in (out.parent, planfolder, cand):
        d.mkdir(parents=True, exist_ok=True)

    import os
    monkeypatch.setattr(os, "environ", e.generation_environment())
    monkeypatch.setattr(m.g, "ROOT", root)
    planpath = planfolder / "PLAN.json"
    planref = e.write_json_exclusive(planpath, {"test": True})
    startedref = e.write_json_exclusive(cand / "STARTED.json", {
        "pid": 1, "argv": [], "utc": "20260913010001+0000"})

    checked = {"plan": {"candidate_output": str(cand), "generation_sources": {},
                        "candidate_prior": {"mode": "recorded_prior"}},
               "plan_binding": planref,
               "baseline": {"bindings": {"test": "baseline"}}}
    candidate = {"result": {"artifact_bindings": {"STARTED.json": startedref}},
                 "bindings": {"test": "candidate"}}
    pregen = {"schema": "E27_PREGEN_PLAN_VERIFIED_V1", "plan_binding": planref,
              "candidate_output": str(cand), "mode": "recorded_prior",
              "utc": "20260913010000+0000", "submission_authorized": False}
    pregenref = e.write_json_exclusive(
        planfolder / "PREGEN_PLAN_VERIFIED.json", pregen)

    calls = []
    fsig = FakeSignal()
    options = {"late_budget": False, "post_failure": False,
               "pregen_drift": False, "entry_failure": None}

    def budget():
        calls.append("budget")
        if options["late_budget"] and (out / "SCORE_RESULT.json").exists():
            raise RuntimeError("late budget")
        return {"wall_seconds": 1.0, "peak_rss_bytes": 1000,
                "ram_scope": "self_process"}

    def core(ck, cd, o, cb):
        calls.append("core")
        cb()
        return {"synthetic": True}

    def post(p, s, ck, cd, o, co, cb):
        calls.append("post")
        if options["pregen_drift"]:
            with open(planfolder / "PREGEN_PLAN_VERIFIED.json", "a") as fh:
                fh.write("\n")
        if options["post_failure"]:
            raise ValueError("post failure")
        return {"verified": True, "stage": "eval12",
                "candidate_id": "E27_RECORDED_PRIOR_V1",
                "status": "SCREEN_EVAL12_PASS", "paired": {},
                "arm_artifacts": {}, "submission_authorized": False}

    def runtime():
        calls.append("runtime")
        monkeypatch.setattr(os, "environ", e.generation_environment())
        if options["entry_failure"]:
            raise options["entry_failure"]

    monkeypatch.setattr(e, "_check_score_entry_runtime", runtime)
    monkeypatch.setattr(e, "check_runtime_budget",
                        lambda *a, **k: budget())
    monkeypatch.setattr(signal, "getitimer", fsig.getitimer)
    monkeypatch.setattr(signal, "getsignal", fsig.getsignal)
    monkeypatch.setattr(signal, "signal", fsig.signal)
    monkeypatch.setattr(signal, "setitimer", fsig.setitimer)
    monkeypatch.setattr(m, "verify_plan",
                        lambda p, s: (calls.append("verify_plan"),
                                      assert_mode(p, s), copy.deepcopy(checked))[2])
    monkeypatch.setattr(m, "verify_generation",
                        lambda p, mode, src, prior: (
                            calls.append("verify_gen"),
                            assert_gen(mode, src, prior),
                            copy.deepcopy(candidate))[2])
    monkeypatch.setattr(m, "score_eval12_core", core)
    monkeypatch.setattr(m, "verify_score_core", post)

    def assert_mode(p, s):
        assert str(p) == str(planpath) and s == planref["sha256"]

    def assert_gen(mode, src, prior):
        assert mode == "recorded_prior" and src == {}
        assert prior == {"mode": "recorded_prior"}

    return {"root": root, "out": out, "planpath": planpath,
            "planref": planref, "pregenref": pregenref, "calls": calls,
            "sig": fsig, "options": options, "checked": checked,
            "candidate": candidate, "core": core, "post": post,
            "planfolder": planfolder}




def _run(box):
    return m.run_score_child(str(box["planpath"]), box["planref"]["sha256"],
                             box["pregenref"]["sha256"], str(box["out"]))


def test_success_writes_result_and_restores_signal(box):
    result = _run(box)
    written = json.loads((box["out"] / "SCORE_RESULT.json").read_text())
    assert written == result
    assert result["timing"]["peak_rss_bytes"] == 1000
    assert result["submission_authorized"] is False
    assert box["calls"].index("core") < box["calls"].index("post")
    assert "ERROR.json" not in [p.name for p in box["out"].iterdir()]
    assert box["sig"].handler is signal.SIG_DFL
    assert box["sig"].set_calls[-1] == (FakeSignal.ITIMER_REAL, 0.0)


def test_late_budget_after_result_keeps_core_file(box):
    box["options"]["late_budget"] = True
    with pytest.raises(RuntimeError, match="late budget"):
        _run(box)
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    assert (box["out"] / "SCORE_RESULT.failed.json").exists()
    err = json.loads((box["out"] / "ERROR.json").read_text())
    assert err["error_type"] == "RuntimeError"
    assert (box["out"] / "SCORE_CORE.json").exists()
    assert box["sig"].handler is signal.SIG_DFL
    assert box["sig"].set_calls[-1] == (FakeSignal.ITIMER_REAL, 0.0)


def test_post_failure_records_error_and_preserves_core(box):
    box["options"]["post_failure"] = True
    with pytest.raises(ValueError, match="post failure"):
        _run(box)
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    err = json.loads((box["out"] / "ERROR.json").read_text())
    assert err["error_type"] == "ValueError"
    assert (box["out"] / "SCORE_CORE.json").exists()
    assert box["sig"].handler is signal.SIG_DFL


def test_pregen_drift_after_scoring_is_rejected(box):
    box["options"]["pregen_drift"] = True
    with pytest.raises(RuntimeError, match="pregen changed after scoring"):
        _run(box)
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    err = json.loads((box["out"] / "ERROR.json").read_text())
    assert err["error_type"] == "RuntimeError"


def test_wrong_pregen_sha_rejects_before_core_and_post(box):
    with pytest.raises(RuntimeError, match="pregen binding mismatch"):
        m.run_score_child(str(box["planpath"]), box["planref"]["sha256"],
                          "0" * 64, str(box["out"]))
    assert "core" not in box["calls"] and "post" not in box["calls"]
    assert not (box["out"] / "SCORE_RESULT.json").exists()


def test_entry_failure_raises_before_output_creation(box):
    box["options"]["entry_failure"] = RuntimeError("entry blocked")
    with pytest.raises(RuntimeError, match="entry blocked"):
        _run(box)
    assert not box["out"].exists()
    assert {p.name for p in box["out"].parent.iterdir()} == {"plan", "siblingcandidate"}
    assert not (box["out"].parent / "score.fresh").exists()


def test_existing_output_dir_rejected_without_touching_sentinel(box):
    box["out"].mkdir()
    sentinel = box["out"] / "SENTINEL.txt"
    sentinel.write_text("keep")
    with pytest.raises(ValueError):
        _run(box)
    assert sentinel.read_text() == "keep"
    assert not (box["out"] / "ERROR.json").exists()


def test_environment_drift_rejected_before_started_receipt(box, monkeypatch):
    import os

    original = m.verify_generation

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setitem(os.environ, "E27_TEST_UNEXPECTED", "1")
        return result

    monkeypatch.setattr(m, "verify_generation", wrapper)

    with pytest.raises(RuntimeError, match="score environment changed after entry"):
        _run(box)

    out = box["out"]
    assert not (out / "SCORE_STARTED.json").exists()
    assert not (out / "SCORE_RESULT.json").exists()
    assert (out / "ERROR.json").exists()
    assert "core" not in box["calls"]
    assert "post" not in box["calls"]
