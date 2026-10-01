"""Synthetic supervisor unit tests for e27_prior_score_v2.supervise_score.

All child processes are faked: FakePopen writes the schemaV2 receipt files that
the real child would produce, including import_environment_additions derived
from the fixture root. These tests do not establish fresh-process behavior or
real scoring.

E28 is exercised through the same synthetic harness by an indirect fixture
parameter. The fake boundaries stay explicit: FakePopen only emulates the
child's seal files and the E28 verifier seams are monkeypatched, so these
tests check the real supervisor route/lifecycle (argument routing, launch
contract, receipt validation, error/kill behaviour) and never real process
scoring or any scientific score claim.
"""
import copy
import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from biohub import e26_screen as e
from scripts.experiments.e27 import e27_prior_score_v2 as m


@pytest.fixture
def box(tmp_path, monkeypatch, request):
    experiment = getattr(request, "param", "e27")
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
         "proc": None, "started": None, "experiment": experiment,
         "routing": [], "callback": None}

    additions = {
        "KMP_DUPLICATE_LIB_OK": "True",
        "_RJEM_MALLOC_CONF": "dirty_decay_ms:500,muzzy_decay_ms:1000",
        "ME_DSL_JIT_LIBTCC_PATH": str(
            root / ".venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib"),
    }

    checked = {"plan": {"candidate_output": str(root / "candidate"),
                        "generation_sources": {}, "candidate_prior": {}},
               "plan_binding": planref,
               "baseline": {"bindings": {"test": "base"}}}
    candidate = {"bindings": {"test": "candidate"}}
    verified = {"verified": True, "stage": "eval12",
                "candidate_id": "E27_RECORDED_PRIOR_V1",
                "status": "SCREEN_EVAL12_PASS", "paired": {},
                "arm_artifacts": {}, "submission_authorized": False}

    # Expected schemas/candidate ids are literal on purpose: importing
    # m._score_protocol here would make the oracle share its answer with the
    # code under test.
    if experiment == "e28":
        expected_module = "scripts.experiments.e28.e28_score"
        expected_started = "E28_SCORE_STARTED_V1"
        expected_result = "E28_SCORE_RESULT_V1"
        expected_cid = "E28_APPEARANCE_COST_V1"
    else:
        expected_module = "scripts.experiments.e27.e27_prior_score_v2"
        expected_started = "E27_SCORE_STARTED_V2"
        expected_result = "E27_SCORE_RESULT_V1"
        expected_cid = "E27_RECORDED_PRIOR_V1"

    if experiment == "e28":
        checked["plan"].pop("candidate_prior", None)
        checked["plan"]["appearance_plan"] = {"synthetic": True}
    verified["candidate_id"] = expected_cid

    class FakePopen:
        def __init__(self, argv, **kw):
            assert kw["env"] == e.generation_environment()
            assert kw["start_new_session"] is True
            assert Path(kw["cwd"]) == root
            assert argv[1:4] == ["-m", expected_module, "score-child"]
            self.pid = 4242
            self.rc = None
            self.waitcalls = 0
            b["calls"].append("launch")
            b["proc"] = self
            out.mkdir()
            write(out / "baseline.json", {})
            write(out / "candidate.json", {})
            coreref = write(out / "SCORE_CORE.json", {"test": True})
            if b["scenario"] == "old_schema":
                started = {"schema": "E27_SCORE_STARTED_V1", "pid": self.pid,
                           "environment": kw["env"], "plan_binding": planref,
                           "pregen_binding": pregref,
                           "seed": 0, "submission_authorized": False}
            else:
                observed = dict(additions)
                if b["scenario"] == "import_value":
                    observed["KMP_DUPLICATE_LIB_OK"] = "maybe"
                if b["scenario"] == "import_extra":
                    # Redundant launch-provided key must not be hidden by merge.
                    observed["PATH"] = kw["env"]["PATH"]
                started = {"schema": expected_started, "pid": self.pid,
                           "environment": kw["env"],
                           "import_environment_additions": observed,
                           "plan_binding": planref,
                           "pregen_binding": pregref,
                           "seed": 1 if b["scenario"] == "seed" else 0,
                           "submission_authorized": False}
            write(out / "SCORE_STARTED.json", started)
            b["started"] = json.loads((out / "SCORE_STARTED.json").read_text())
            result = {"schema": expected_result,
                      **copy.deepcopy(verified), "plan_binding": planref,
                      "pregen_binding": pregref, "core_binding": coreref,
                      "baseline_bindings": checked["baseline"]["bindings"],
                      "candidate_bindings": candidate["bindings"],
                      "timing": {"wall_seconds": 1.0, "peak_rss_bytes": 1000,
                                 "ram_scope": "self_process",
                                 "output_bytes": 100}}
            result["candidate_id"] = expected_cid
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

    if experiment == "e28":
        # E28 routes through scripts.experiments.e28.e28_score.appearance plus the shared
        # post-score core seam. m.verify_* stays forbidden so a route that
        # still uses the E27 seams fails loudly instead of silently passing.
        from scripts.experiments.e28 import e28_score as appearance

        def forbidden_verify(*args, **kwargs):
            raise AssertionError("unexpected E27 route")

        monkeypatch.setattr(m, "verify_plan", forbidden_verify)
        monkeypatch.setattr(m, "verify_generation", forbidden_verify)

        def verify_plan(path, sha, *, check_budget):
            assert Path(path) == planpath
            assert sha == planref["sha256"]
            assert callable(check_budget)
            b["callback"] = check_budget
            b["routing"].append("plan")
            return copy.deepcopy(checked)

        def verify_generation(candidate_path, mode, sources, appearance_plan,
                              check_budget):
            assert Path(candidate_path) == Path(checked["plan"]["candidate_output"])
            assert mode == "e28_appearance"
            assert sources == checked["plan"]["generation_sources"]
            assert appearance_plan == {"synthetic": True}
            assert check_budget is b["callback"]
            check_budget()
            b["routing"].append("generation")
            return copy.deepcopy(candidate)

        def verify_shared_post(path, sha, ck, cd, o, core, check_budget, *, experiment):
            assert experiment == "e28"
            assert check_budget is b["callback"]
            assert Path(path) == planpath
            assert sha == planref["sha256"]
            assert ck == checked
            assert cd == candidate
            assert Path(o) == out
            check_budget()
            b["routing"].append("post")
            return copy.deepcopy(verified)

        monkeypatch.setattr(appearance, "verify_plan", verify_plan)
        monkeypatch.setattr(appearance, "verify_generation", verify_generation)
        monkeypatch.setattr(m, "verify_score_core", verify_shared_post)

    realtree = m.g._output_tree_bytes

    def tree(p):
        if (b["scenario"] == "late" and Path(p) == audit
                and (audit / "SUPERVISOR_RESULT.json").exists()):
            return 256 * 1024 ** 2 + 1
        return realtree(p)

    monkeypatch.setattr(m.g, "_output_tree_bytes", tree)
    b["additions"] = additions
    return b


def _run(box):
    if box["experiment"] == "e28":
        return m.supervise_score(box["planpath"], box["planref"]["sha256"],
                                 box["pregref"]["sha256"], box["out"],
                                 experiment="e28")
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


def test_success_validates_receipt_additions(box):
    box["scenario"] = "ok"
    result = _run(box)
    started = json.loads((box["out"] / "SCORE_STARTED.json").read_text())
    assert started["schema"] == "E27_SCORE_STARTED_V2"
    assert started["environment"] == e.generation_environment()
    assert started["import_environment_additions"] == box["additions"]
    assert result["returncode"] == 0


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


@pytest.mark.parametrize("scenario,reason", [
    ("import_value", "import environment verification failed"),
    ("import_extra", "import additions keys"),
    ("old_schema", "SCORE_STARTED keys"),
])
def test_bad_import_environment_receipt_rejected(box, scenario, reason):
    box["scenario"] = scenario
    with pytest.raises(RuntimeError, match=reason):
        _run(box)
    assert not (box["audit"] / "SUPERVISOR_RESULT.json").exists()
    assert (box["audit"] / "ERROR.json").exists()
    assert _error(box)["status"] == "ERROR"
    assert (box["out"] / "SCORE_RESULT.failed.json").exists()
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    # The child seal is retained and no parent success is recorded.
    assert (box["out"] / "SCORE_STARTED.json").exists()


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


@pytest.mark.parametrize("box", ["e28"], indirect=True)
def test_e28_success_routes_and_lifecycle(box):
    box["scenario"] = "ok"
    result = _run(box)
    assert result == json.loads(
        (box["audit"] / "SUPERVISOR_RESULT.json").read_text())
    assert result["schema"] == "E28_SCORE_SUPERVISOR_V1"
    assert result["returncode"] == 0
    assert result["submission_authorized"] is False
    assert result["argv"][1:4] == ["-m", "scripts.experiments.e28.e28_score", "score-child"]
    assert result["environment"] == e.generation_environment()
    assert box["routing"] == ["plan", "generation", "post"]
    assert box["calls"] == ["launch"]
    assert box["signals"] == []
    assert box["started"]["schema"] == "E28_SCORE_STARTED_V1"
    assert not (box["audit"] / "ERROR.json").exists()


@pytest.mark.parametrize("box", ["e28"], indirect=True)
@pytest.mark.parametrize("scenario",
                         ["import_value", "old_schema", "late", "timeout"])
def test_e28_error_paths(box, scenario):
    box["scenario"] = scenario
    expected = (subprocess.TimeoutExpired if scenario == "timeout"
                else RuntimeError)
    with pytest.raises(expected):
        _run(box)
    # No parent success seal and no child success seal for either experiment.
    assert not (box["audit"] / "SUPERVISOR_RESULT.json").exists()
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    error = _error(box)
    assert error["schema"] == "E28_SCORE_SUPERVISOR_ERROR_V1"
    assert error["status"] == "ERROR"
    assert error["submission_authorized"] is False
    assert len(box["calls"]) == 1
    if scenario == "late":
        assert (box["audit"] / "SUPERVISOR_RESULT.failed.json").exists()
        assert (box["out"] / "SCORE_RESULT.failed.json").exists()
    else:
        assert (box["out"] / "SCORE_RESULT.failed.json").exists()
    if scenario == "timeout":
        assert box["signals"] == [(4242, int(signal.SIGTERM)),
                                  (4242, int(signal.SIGKILL))]
        assert box["proc"].waitcalls == 3
        assert error["killpg_signals"] == [int(signal.SIGTERM),
                                           int(signal.SIGKILL)]
    else:
        assert box["signals"] == []
        assert error["killpg_signals"] == []
    # Lifecycle/routing only: no scientific score claim is made here.
