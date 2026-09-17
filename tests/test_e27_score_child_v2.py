"""Synthetic lifecycle unit tests for e27_prior_score_v2.run_score_child.

These mock all scoring boundaries and use a fake signal module. They do not
establish parent supervision, fresh-process behavior, or real scoring.
The import-environment check is exercised synthetically: the mocked
verify_generation applies the three documented import side effects to os.environ
after its argument assertions. Real fresh-process observation is tested separately.
"""
import copy
import json
import os
import signal

import pytest

from biohub import e26_screen as e
from scripts import e27_prior_score_v2 as m


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

    additions = {
        "KMP_DUPLICATE_LIB_OK": "True",
        "_RJEM_MALLOC_CONF": "dirty_decay_ms:500,muzzy_decay_ms:1000",
        "ME_DSL_JIT_LIBTCC_PATH": str(
            root / ".venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib"),
    }

    calls = []
    fsig = FakeSignal()
    options = {"late_budget": False, "post_failure": False,
               "pregen_drift": False, "entry_failure": None,
               "import_side_effects": True}

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
                            apply_import_side_effects())[2])
    monkeypatch.setattr(m, "score_eval12_core", core)
    monkeypatch.setattr(m, "verify_score_core", post)

    def assert_mode(p, s):
        assert str(p) == str(planpath) and s == planref["sha256"]

    def assert_gen(mode, src, prior):
        assert mode == "recorded_prior" and src == {}
        assert prior == {"mode": "recorded_prior"}

    def apply_import_side_effects():
        # Synthetic stand-in for interpreter/library import side effects that a
        # real fresh child observes after verify_generation and seeding.
        if options["import_side_effects"]:
            for key, value in additions.items():
                monkeypatch.setitem(os.environ, key, value)
        return copy.deepcopy(candidate)

    return {"root": root, "out": out, "planpath": planpath,
            "planref": planref, "pregenref": pregenref, "calls": calls,
            "sig": fsig, "options": options, "checked": checked,
            "candidate": candidate, "core": core, "post": post,
            "planfolder": planfolder, "additions": additions}


def _run(box):
    return m.run_score_child(str(box["planpath"]), box["planref"]["sha256"],
                             box["pregenref"]["sha256"], str(box["out"]))


def test_success_writes_result_and_restores_signal(box):
    result = _run(box)
    written = json.loads((box["out"] / "SCORE_RESULT.json").read_text())
    assert written == result
    assert result["schema"] == "E27_SCORE_RESULT_V1"
    assert result["timing"]["peak_rss_bytes"] == 1000
    assert result["submission_authorized"] is False
    assert box["calls"].index("core") < box["calls"].index("post")
    assert "ERROR.json" not in [p.name for p in box["out"].iterdir()]
    assert box["sig"].handler is signal.SIG_DFL
    assert box["sig"].set_calls[-1] == (FakeSignal.ITIMER_REAL, 0.0)


def test_success_records_launch_env_and_import_additions(box):
    launch = e.generation_environment()
    _run(box)
    started = json.loads((box["out"] / "SCORE_STARTED.json").read_text())
    assert started["schema"] == "E27_SCORE_STARTED_V2"
    assert started["environment"] == launch
    assert started["import_environment_additions"] == box["additions"]
    # The recorded environment stays the launch snapshot; only the additions
    # map carries the observed import side effects.
    for key in box["additions"]:
        assert key not in started["environment"]


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


def test_import_environment_additions_verified(box):
    seen = []
    original = m.verify_import_environment

    def wrapper(launch, observed, libtcc_path):
        seen.append((copy.deepcopy(launch), copy.deepcopy(observed), libtcc_path))
        return original(launch, observed, libtcc_path)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(m, "verify_import_environment", wrapper)
    try:
        _run(box)
    finally:
        monkey.undo()
    assert len(seen) == 1
    launch, observed, libtcc_path = seen[0]
    assert launch == e.generation_environment()
    expected = dict(launch)
    expected.update(box["additions"])
    assert observed == expected
    assert libtcc_path == box["additions"]["ME_DSL_JIT_LIBTCC_PATH"]


def test_missing_import_addition_rejected(box):
    del box["additions"]["_RJEM_MALLOC_CONF"]
    with pytest.raises(RuntimeError, match="import environment verification failed"):
        _run(box)
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    assert (box["out"] / "ERROR.json").exists()
    assert "core" not in box["calls"] and "post" not in box["calls"]


def test_changed_import_addition_value_rejected(box):
    box["additions"]["KMP_DUPLICATE_LIB_OK"] = "False"
    with pytest.raises(RuntimeError, match="import environment verification failed"):
        _run(box)
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    assert (box["out"] / "ERROR.json").exists()
    assert "core" not in box["calls"]


def test_extra_import_addition_rejected(box):
    box["additions"]["PATH"] = os.environ.get("PATH", "/usr/bin") + ":/extra"
    with pytest.raises(RuntimeError, match="import environment verification failed"):
        _run(box)
    assert not (box["out"] / "SCORE_RESULT.json").exists()
    assert (box["out"] / "ERROR.json").exists()
    assert "core" not in box["calls"]


def test_environment_drift_rejected_before_started_receipt(box, monkeypatch):
    original = m.verify_generation

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setitem(os.environ, "E27_TEST_UNEXPECTED", "1")
        return result

    monkeypatch.setattr(m, "verify_generation", wrapper)

    with pytest.raises(RuntimeError, match="import environment verification failed"):
        _run(box)

    out = box["out"]
    assert not (out / "SCORE_STARTED.json").exists()
    assert not (out / "SCORE_RESULT.json").exists()
    assert (out / "ERROR.json").exists()
    assert "core" not in box["calls"]
    assert "post" not in box["calls"]


class _E28StringSubclass(str):
    pass


class _E28EqualSpoofer:
    def __eq__(self, other):
        return True


def test_e28_route_dispatch_and_cleanup(box, monkeypatch):
    from scripts import e28_score as appearance

    sentinel_handler = lambda signum, frame: None  # noqa: E731
    box["sig"].handler = sentinel_handler

    def forbidden_verify_plan(*args, **kwargs):
        pytest.fail("E27 route")

    monkeypatch.setattr(m, "verify_plan", forbidden_verify_plan)

    selected = []

    def e28_verify_plan(path, sha, *, check_budget):
        assert path == box["planpath"]
        assert sha == box["planref"]["sha256"]
        assert callable(check_budget)
        check_budget()
        selected.append((path, sha))
        raise RuntimeError("E28 PLAN sentinel")

    monkeypatch.setattr(appearance, "verify_plan", e28_verify_plan)

    with pytest.raises(RuntimeError, match="E28 PLAN sentinel"):
        m.run_score_child(
            str(box["planpath"]),
            box["planref"]["sha256"],
            box["pregenref"]["sha256"],
            str(box["out"]),
            experiment="e28",
        )

    assert len(selected) == 1
    assert "core" not in box["calls"]
    assert "post" not in box["calls"]
    assert box["sig"].handler is sentinel_handler
    assert box["sig"].timer == (0.0, 0.0)

    error_path = box["out"] / "ERROR.json"
    assert error_path.exists()
    payload = json.loads(error_path.read_text())
    assert payload["schema"] == "E28_SCORE_ERROR_V1"

    assert not (box["out"] / "SCORE_STARTED.json").exists()
    assert not (box["out"] / "SCORE_CORE.json").exists()
    assert not (box["out"] / "SCORE_RESULT.json").exists()


@pytest.mark.parametrize(
    "bad_experiment",
    [
        "",
        "e29",
        None,
        True,
        _E28StringSubclass("e28"),
        _E28EqualSpoofer(),
    ],
)
def test_strict_selector_rejection(box, bad_experiment):
    with pytest.raises(ValueError, match="unsupported experiment"):
        m.run_score_child(
            str(box["planpath"]),
            box["planref"]["sha256"],
            box["pregenref"]["sha256"],
            str(box["out"]),
            experiment=bad_experiment,
        )

    assert box["calls"] == []
    assert not box["out"].exists()


def test_e28_child_success_routes_and_seals(box, monkeypatch):
    from pathlib import Path

    from scripts import e28_score as appearance

    planpath = box["planpath"]
    planref = box["planref"]
    planfolder = box["planfolder"]
    out = box["out"]
    checked = box["checked"]
    candidate = box["candidate"]
    additions = box["additions"]
    calls = box["calls"]

    checked["plan"].pop("candidate_prior")
    checked["plan"]["appearance_plan"] = {"synthetic": True}

    pregen_path = Path(planfolder) / "PREGEN_PLAN_VERIFIED.json"
    with open(pregen_path) as fh:
        pregen_doc = json.load(fh)
    pregen_doc["schema"] = "E28_PREGEN_PLAN_VERIFIED_V1"
    pregen_doc["mode"] = "e28_appearance"
    with open(pregen_path, "w") as fh:
        json.dump(pregen_doc, fh)
    box["pregenref"] = m.g._binding_for_path(pregen_path, label="pregen")

    def forbidden(*args, **kwargs):
        raise AssertionError("production verification/score path must not run")

    monkeypatch.setattr(m, "verify_plan", forbidden)
    monkeypatch.setattr(m, "verify_generation", forbidden)
    monkeypatch.setattr(m, "score_eval12_core", forbidden)

    cb_seen = []

    def selected_plan(path, sha, *, check_budget):
        assert str(path) == str(planpath)
        assert sha == planref["sha256"]
        cb_seen.append(check_budget)
        check_budget()
        return copy.deepcopy(checked)

    def selected_generation(path, mode, sources, appearance_plan, check_budget):
        assert Path(path) == Path(checked["plan"]["candidate_output"])
        assert mode == "e28_appearance"
        assert sources == {}
        assert appearance_plan == {"synthetic": True}
        assert check_budget is cb_seen[0]
        for key, value in additions.items():
            monkeypatch.setitem(os.environ, key, value)
        check_budget()
        return copy.deepcopy(candidate)

    monkeypatch.setattr(appearance, "verify_plan", selected_plan)
    monkeypatch.setattr(appearance, "verify_generation", selected_generation)
    monkeypatch.setattr(appearance, "score_eval12_core", box["core"])

    def selected_post(path, sha, ck, cd, o, core, cb, *, experiment):
        assert experiment == "e28"
        assert cb is cb_seen[0]
        assert str(path) == str(planpath)
        assert sha == planref["sha256"]
        assert ck == checked
        assert cd == candidate
        assert Path(o) == Path(out)
        result = box["post"](path, sha, ck, cd, o, core, cb)
        result["candidate_id"] = "E28_APPEARANCE_COST_V1"
        return result

    monkeypatch.setattr(m, "verify_score_core", selected_post)

    returned = m.run_score_child(
        str(planpath),
        planref["sha256"],
        box["pregenref"]["sha256"],
        str(out),
        experiment="e28",
    )

    with open(Path(out) / "SCORE_RESULT.json") as fh:
        sealed = json.load(fh)
    assert returned == sealed
    assert sealed["schema"] == "E28_SCORE_RESULT_V1"
    assert sealed["candidate_id"] == "E28_APPEARANCE_COST_V1"
    assert sealed["submission_authorized"] is False
    assert sealed["status"] == "SCREEN_EVAL12_PASS"

    with open(Path(out) / "SCORE_STARTED.json") as fh:
        started = json.load(fh)
    assert started["schema"] == "E28_SCORE_STARTED_V1"
    assert started["environment"] == e.generation_environment()
    assert started["import_environment_additions"] == additions

    assert calls.index("core") < calls.index("post")
    assert box["sig"].handler is signal.SIG_DFL
    assert box["sig"].timer == (0.0, 0.0)
    assert not (Path(out) / "ERROR.json").exists()
