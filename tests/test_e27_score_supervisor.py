import copy
import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from biohub import e26_screen as e
from scripts import e27_prior_score as m


@pytest.fixture
def box(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "outputs" / "local").mkdir(parents=True)
    monkeypatch.setattr(m.g, "ROOT", root)
    plan_dir = root / "outputs" / "local" / "plan"
    plan_dir.mkdir()
    planpath = plan_dir / "PLAN.json"
    pregpath = plan_dir / "PREGEN_PLAN_VERIFIED.json"

    def write(path, obj):
        return e.write_json_exclusive(path, obj)

    planref = write(planpath, {"test": True})
    pregref = write(pregpath, {"test": True})

    out = root / "outputs" / "local" / "score"
    audit = out.with_name(out.name + "_supervisor")
    b = {"out": out, "audit": audit, "planpath": planpath, "planref": planref,
         "pregref": pregref, "scenario": "ok", "calls": [], "signals": [],
         "proc": None}

    checked = {"plan": {"candidate_output": str(root / "candidate"),
                        "generation_sources": {}, "candidate_prior": {}},
               "plan_binding": planref,
               "baseline": {"bindings": {"test": "base"}}}
    candidate = {"bindings": {"test": "candidate"}}
    verified = {"verified": True, "stage": "eval12",
                "candidate_id": "E27_RECORDED_PRIOR_V1",
                "status": "SCREEN_EVAL12_PASS", "paired": {},
                "arm_artifacts": {}, "submission_authorized": False}

    class FakePopen:
        def __init__(self, argv, **kw):
            assert kw["env"] == e.generation_environment()
            assert kw["start_new_session"] is True
            assert Path(kw["cwd"]) == root
            assert argv[1:4] == ["-m", "scripts.e27_prior_score", "score-child"]
            self.pid = 4242
            self.rc = None
            self.waitcalls = 0
            b["calls"].append("launch")
            b["proc"] = self
            out.mkdir()
            write(out / "baseline.json", {})
            write(out / "candidate.json", {})
            coreref = write(out / "SCORE_CORE.json", {"test": True})
            started = {"schema": "E27_SCORE_STARTED_V1", "pid": self.pid,
                       "environment": kw["env"], "plan_binding": planref,
                       "pregen_binding": pregref,
                       "seed": 1 if b["scenario"] == "seed" else 0,
                       "submission_authorized": False}
            write(out / "SCORE_STARTED.json", started)
            result = {"schema": "E27_SCORE_RESULT_V1",
                      **copy.deepcopy(verified), "plan_binding": planref,
                      "pregen_binding": pregref, "core_binding": coreref,
                      "baseline_bindings": checked["baseline"]["bindings"],
                      "candidate_bindings": candidate["bindings"],
                      "timing": {"wall_seconds": 1.0, "peak_rss_bytes": 1000,
                                 "ram_scope": "self_process",
                                 "output_bytes": 100}}
            write(out / "SCORE_RESULT.json", result)
            if b["scenario"] == "extra":
                nested = out / "nested"
                nested.mkdir(parents=True)
                write(nested / "extra.json", {})

        def wait(self, timeout=None):
            self.waitcalls += 1
            if b["scenario"] == "timeout" and self.waitcalls <= 2:
                raise subprocess.TimeoutExpired("fake", timeout)
            self.rc = -9 if b["scenario"] == "timeout" else (
                1 if b["scenario"] == "nonzero" else 0)
            return self.rc

        def poll(self):
            return self.rc

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(os, "killpg",
                        lambda pid, sig: b["signals"].append((pid, int(sig))))

    monkeypatch.setattr(m, "verify_plan", lambda *a, **k: copy.deepcopy(checked))
    monkeypatch.setattr(m, "verify_generation", lambda *a, **k: copy.deepcopy(candidate))
    monkeypatch.setattr(m, "verify_score_core", lambda *a, **k: copy.deepcopy(verified))

    realtree = m.g._output_tree_bytes

    def tree(p):
        if (b["scenario"] == "late" and Path(p) == audit
                and (audit / "SUPERVISOR_RESULT.json").exists()):
            return 256 * 1024 ** 2 + 1
        return realtree(p)

    monkeypatch.setattr(m.g, "_output_tree_bytes", tree)
    return b


def _run(box):
    return m.supervise_score(box["planpath"], box["planref"]["sha256"],
                             box["pregref"]["sha256"], box["out"])


def _error(box):
    return json.loads((box["audit"] / "ERROR.json").read_text())


def test_success(box):
    box["scenario"] = "ok"
    result = _run(box)
    assert result == json.loads((box["audit"] / "SUPERVISOR_RESULT.json").read_text())
    assert result["returncode"] == 0
    assert result["status"] == "SCREEN_EVAL12_PASS"
    assert result["submission_authorized"] is False
    assert box["signals"] == []
    assert box["calls"] == ["launch"]
    assert not (box["audit"] / "ERROR.json").exists()


def test_seed_set(box):
    box["scenario"] = "seed"
    with pytest.raises(RuntimeError, match="seed"):
        _run(box)
    assert not (box["audit"] / "SUPERVISOR_RESULT.json").exists()
    assert (box["out"] / "SCORE_RESULT.failed.json").exists()
    assert (box["audit"] / "ERROR.json").exists()
    assert _error(box)["status"] == "ERROR"


def test_extra_files(box):
    box["scenario"] = "extra"
    with pytest.raises(RuntimeError, match="child files"):
        _run(box)
    assert (box["audit"] / "ERROR.json").exists()
    assert not (box["audit"] / "SUPERVISOR_RESULT.json").exists()


def test_nonzero(box):
    box["scenario"] = "nonzero"
    with pytest.raises(RuntimeError, match="nonzero"):
        _run(box)
    assert box["calls"] == ["launch"]
    assert box["proc"].waitcalls == 2
    assert _error(box)["killpg_signals"] == []


def test_timeout(box):
    box["scenario"] = "timeout"
    with pytest.raises(subprocess.TimeoutExpired):
        _run(box)
    assert box["signals"] == [(4242, int(signal.SIGTERM)), (4242, int(signal.SIGKILL))]
    assert box["proc"].waitcalls == 3
    error = _error(box)
    assert error["killpg_signals"] == [int(signal.SIGTERM), int(signal.SIGKILL)]
    assert error["reap_error"] is None
    assert len(box["calls"]) == 1


def test_late_result(box):
    box["scenario"] = "late"
    with pytest.raises(RuntimeError, match="budget"):
        _run(box)
    assert (box["audit"] / "SUPERVISOR_RESULT.failed.json").exists()
    assert (box["out"] / "SCORE_RESULT.failed.json").exists()
    assert not (box["audit"] / "SUPERVISOR_RESULT.json").exists()
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    assert _error(box)["status"] == "ERROR"


def test_existing_out(box):
    box["out"].mkdir(parents=True, exist_ok=True)
    sentinel = box["out"] / "keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(RuntimeError):
        _run(box)
    assert sentinel.read_text() == "keep"
    assert box["calls"] == []
    assert not box["audit"].exists()
