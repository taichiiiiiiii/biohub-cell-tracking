"""Synthetic-only tests for the E27 baseline supervisor. No subprocess/model runs."""
import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

import scripts.e27_association_prior_screen as m
from biohub import e26_screen as e


class FakeProcess:
    def __init__(self, returncode=0, poll_returns=None, wait_raises=None):
        self.pid = 424242
        self._poll = list(poll_returns or [])
        self._waits = list(wait_raises or [])
        self.returncode = returncode
        self.reaped = False

    def poll(self):
        if self._poll:
            return self._poll.pop(0)
        return self.returncode

    def wait(self, timeout=None):
        assert timeout is not None
        if self._waits:
            item = self._waits.pop(0)
            if isinstance(item, Exception):
                raise item
        self.reaped = True
        return self.returncode


CHILD_STATUS_BY_MODE = {
    "baseline_none": "E27_BASELINE_PARITY_PASS_NOT_CANDIDATE",
    "selected_only": "E27_SELECTED_ONLY_PARITY_PASS_NOT_CANDIDATE",
    "recorded_prior": "E27_RECORDED_PRIOR_GENERATED_UNSCORED",
}

PARENT_STATUS_BY_MODE = {
    "baseline_none": "E27_BASELINE_SUPERVISED_PASS_NOT_CANDIDATE",
    "selected_only": "E27_SELECTED_ONLY_SUPERVISED_PASS_NOT_CANDIDATE",
    "recorded_prior": "E27_RECORDED_PRIOR_SUPERVISED_UNSCORED",
}


def _receipt_for_mode(mode):
    if mode == "baseline_none":
        return None
    eligible = 0 if mode == "selected_only" else 1
    return {
        "mode": mode,
        "datasets": list(m.STEMS),
        "entries_by_dataset": {stem: 2 for stem in m.STEMS},
        "eligible_unselected_by_dataset": {stem: eligible for stem in m.STEMS},
        "sha256": "a" * 64,
    }


def _make_child_output(output, tmp_path, csv_body=b"synthetic\n", bad_csv=False,
                       mode="baseline_none"):
    receipt = _receipt_for_mode(mode)
    output.mkdir(parents=True)
    control = output / "CONTROL.json"
    control.write_text(
        json.dumps({"arm": mode, "association_priors": receipt}), encoding="utf-8"
    )
    csv = output / "submission.csv"
    csv.write_bytes(csv_body)
    sidecar = output / "sidecar.json"
    sidecar.write_text("{}", encoding="utf-8")
    cb = m._binding_for_path(control, label="CONTROL.json")
    sb = m._binding_for_path(sidecar, label="sidecar.json")
    csvb = m._binding_for_path(csv, label="submission.csv")
    if bad_csv:
        csvb = dict(csvb, sha256="0" * 64)
    result = {
        "status": CHILD_STATUS_BY_MODE[mode],
        "arm": mode,
        "association_priors": receipt,
        "counts": {"report": 1},
        "source_bindings": {},
        "control_binding": cb,
        "artifact_bindings": {
            "CONTROL.json": cb,
            "sidecar.json": sb,
            "submission.csv": m._binding_for_path(csv, label="submission.csv"),
        },
        "csv_binding": csvb,
        "gt_read": False,
        "submission_allowed": False,
    }
    (output / "RESULT.json").write_text(json.dumps(result), encoding="utf-8")
    return result


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "outputs" / "local").mkdir(parents=True)
    monkeypatch.setattr(m, "ROOT", root)
    monkeypatch.setattr(e, "generation_environment", lambda: {"SAFE": "1"})
    monkeypatch.setattr(m, "_snapshot_source_closure", lambda: {})
    monkeypatch.setattr(m, "_verify_source_closure", lambda snap: snap)

    ref_body = b"synthetic\n"

    def fake_reference(label):
        return {
            "label": label,
            "sha256": hashlib.sha256(ref_body).hexdigest(),
            "bytes": len(ref_body),
        }

    monkeypatch.setattr(m, "_verify_reference_binding", fake_reference)
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        proc = fake_popen.process
        out = Path(kwargs_pop_output(argv))
        fake_popen.builder(out)
        return proc

    def kwargs_pop_output(argv):
        return argv[argv.index("--output") + 1]

    fake_popen.calls = calls
    fake_popen.process = FakeProcess(returncode=0)
    fake_popen.builder = lambda out: _make_child_output(out, tmp_path)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    killed = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    fake_popen.killed = killed
    return fake_popen


def _out(tmp_path, name="run01"):
    return tmp_path.resolve() / "outputs" / "local" / name


def test_happy_path_single_launch(tmp_path, sandbox):
    out = _out(tmp_path)
    rec = m.supervise_baseline(out)
    assert rec["status"] == "E27_BASELINE_SUPERVISED_PASS_NOT_CANDIDATE"
    assert rec["submission_allowed"] is False and rec["gt_read"] is False
    assert len(sandbox.calls) == 1
    argv, kwargs = sandbox.calls[0]
    assert argv[:3] == [os.sys.executable, "-m", "scripts.e27_association_prior_screen"]
    assert "--supervise" not in argv
    assert kwargs["cwd"] == str(m.ROOT)
    assert kwargs["env"] == {"SAFE": "1"}
    assert kwargs["start_new_session"] is True
    assert (out / "submission.csv").exists()
    audit = Path(rec["audit_dir"])
    assert (audit / "stdout.log").is_file() and (audit / "stderr.log").is_file()
    assert (audit / "SUPERVISOR_RESULT.json").is_file()
    assert audit.parent == m.ROOT / "outputs" / "local"


def test_timeout_terminates_and_revokes(tmp_path, sandbox):
    out = _out(tmp_path, "run_timeout")
    sandbox.process = FakeProcess(
        returncode=-15,
        poll_returns=[None],
        wait_raises=[subprocess.TimeoutExpired(cmd="x", timeout=1)],
    )
    with pytest.raises(TimeoutError):
        m.supervise_baseline(out)
    assert [(p, s) for p, s in sandbox.killed] == [(424242, signal.SIGTERM)]
    assert sandbox.process.reaped is True
    assert not (out / "RESULT.json").exists()
    assert (out / "RESULT.failed.json").is_file()
    err_path = out.parent / "run_timeout_supervisor" / "ERROR.json"
    assert err_path.is_file()
    err = json.loads(err_path.read_text(encoding="utf-8"))
    assert err["exception_type"] == "TimeoutError"
    assert err["submission_allowed"] is False
    assert err["reap_error"] is None


def test_nonzero_returncode_fails(tmp_path, sandbox):
    out = _out(tmp_path, "run_rc")
    sandbox.process = FakeProcess(returncode=7)
    with pytest.raises(RuntimeError):
        m.supervise_baseline(out)
    assert not (out / "RESULT.json").exists()
    assert (out / "RESULT.failed.json").is_file()
    err = json.loads((out.parent / "run_rc_supervisor" / "ERROR.json").read_text(encoding="utf-8"))
    assert err["exception_type"] == "RuntimeError"


def test_bad_csv_binding_revokes_result(tmp_path, sandbox):
    out = _out(tmp_path, "run_drift")
    sandbox.builder = lambda o: _make_child_output(o, tmp_path, bad_csv=True)
    with pytest.raises(RuntimeError):
        m.supervise_baseline(out)
    assert not (out / "RESULT.json").exists()
    assert (out / "RESULT.failed.json").is_file()
    err = json.loads((out.parent / "run_drift_supervisor" / "ERROR.json").read_text(encoding="utf-8"))
    assert err["exception_type"] == "RuntimeError"
    assert not (out.parent / "run_drift_supervisor" / "SUPERVISOR_RESULT.json").exists()


def test_existing_child_dir_rejected_without_launch(tmp_path, sandbox):
    out = _out(tmp_path, "run_pre")
    out.mkdir(parents=True)
    with pytest.raises(ValueError):
        m.supervise_baseline(out)
    assert len(sandbox.calls) == 0
    assert list((m.ROOT / "outputs" / "local").iterdir()) == [out]

@pytest.mark.parametrize("mode", ["selected_only", "recorded_prior"])
def test_supervise_baseline_nonbaseline_modes_pass(tmp_path, sandbox, mode):
    out = _out(tmp_path, f"run_{mode}")
    sandbox.builder = lambda o: _make_child_output(o, tmp_path, mode=mode)
    rec = m.supervise_baseline(out, mode=mode)
    assert rec["status"] == PARENT_STATUS_BY_MODE[mode]
    assert rec["submission_allowed"] is False and rec["gt_read"] is False
    assert len(sandbox.calls) == 1
    argv, _kwargs = sandbox.calls[0]
    assert argv[argv.index("--mode") + 1] == mode
    assert argv[argv.index("--output") + 1] == str(out)
    assert argv.index("--mode") > argv.index("--output")


@pytest.mark.parametrize("mode", ["selected_only", "recorded_prior"])
def test_changed_csv_accepted_only_for_recorded(tmp_path, sandbox, mode):
    out = _out(tmp_path, f"run_{mode}_diffcsv")
    sandbox.builder = lambda o: _make_child_output(
        o, tmp_path, csv_body=b"different\n", mode=mode
    )
    if mode == "recorded_prior":
        rec = m.supervise_baseline(out, mode=mode)
        assert rec["status"] == PARENT_STATUS_BY_MODE[mode]
        assert rec["submission_allowed"] is False
        assert len(sandbox.calls) == 1
    else:
        with pytest.raises(RuntimeError):
            m.supervise_baseline(out, mode=mode)
        assert not (out / "RESULT.json").exists()
        assert (out / "RESULT.failed.json").is_file()
        err = json.loads(
            (out.parent / f"run_{mode}_diffcsv_supervisor" / "ERROR.json").read_text(
                encoding="utf-8"
            )
        )
        assert err["exception_type"] == "RuntimeError"
        assert err["submission_allowed"] is False


def test_wrong_arm_in_baseline_builder_fails(tmp_path, sandbox):
    out = _out(tmp_path, "run_wrongarm")
    sandbox.builder = lambda o: _make_child_output(
        o, tmp_path, mode="baseline_none"
    )
    original = _make_child_output

    def mismatched(output, tmp, **kwargs):
        kwargs["mode"] = "selected_only"
        return original(output, tmp, **kwargs)

    sandbox.builder = lambda o: mismatched(o, tmp_path, mode="baseline_none")
    with pytest.raises(RuntimeError):
        m.supervise_baseline(out, mode="recorded_prior")
    assert not (out / "RESULT.json").exists()
    assert (out / "RESULT.failed.json").is_file()


@pytest.mark.parametrize("bad_mode", ["bogus", None, True])
def test_invalid_mode_fails_before_launch(tmp_path, sandbox, bad_mode):
    out = _out(tmp_path, "run_badmode")
    with pytest.raises(ValueError):
        m.supervise_baseline(out, mode=bad_mode)
    assert len(sandbox.calls) == 0
    assert not out.exists()
    assert list((m.ROOT / "outputs" / "local").iterdir()) == []


@pytest.mark.parametrize(
    "mode,fault,expected_error",
    [
        ("e28_none", None, None),
        ("e28_appearance", None, None),
        ("e28_none", "csv", "reference does not match"),
        ("e28_appearance", "schema", "control schema mismatch"),
        ("e28_appearance", "plan", "control appearance_plan mismatch"),
        ("e28_appearance", "feature_binding", "feature_receipts binding mismatch"),
        ("e28_none", "unexpected_feature", "must not emit FEATURE_RECEIPTS"),
        ("e28_appearance", "verify", "receipt verifier fail"),
        ("e28_appearance", "plan_timeout", "supervisor exceeded wall budget"),
        ("e28_appearance", "verify_timeout", "supervisor exceeded wall budget"),
        ("e28_appearance", "write_timeout", "supervisor exceeded wall budget"),
    ],
)
def test_e28_supervised_matrix(tmp_path, monkeypatch, sandbox, mode, fault, expected_error):
    child_status = ("E28_APPEARANCE_NONE_PARITY_PASS_NOT_CANDIDATE" if mode == "e28_none"
                    else "E28_APPEARANCE_COST_V1_GENERATED_UNSCORED")
    parent_status = ("E28_APPEARANCE_NONE_SUPERVISED_PASS_NOT_CANDIDATE" if mode == "e28_none"
                     else "E28_APPEARANCE_COST_V1_SUPERVISED_UNSCORED")
    out = _out(tmp_path, mode)
    built = []
    clock = [0.0]
    if fault in ("plan_timeout", "verify_timeout", "write_timeout"):
        monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])

    def builder(output):
        result = _make_child_output(
            output, tmp_path,
            csv_body=b"synthetic\n" if (mode == "e28_none" and fault != "csv") else b"candidate\n",
            mode="baseline_none",
        )
        control = output / "CONTROL.json"
        control.write_text(json.dumps({
            "arm": mode, "association_priors": None,
            "schema": "E28_GENERATION_CONTROL_V1" if fault != "schema" else "WRONG_SCHEMA",
            "candidate_id": "E28_APPEARANCE_COST_V1",
            "appearance_plan": {"synthetic": True} if fault != "plan" else {"synthetic": False},
        }), encoding="utf-8")
        cb = m._binding_for_path(control, label="CONTROL.json")
        csvb = m._binding_for_path(output / "submission.csv", label="submission.csv")
        arts = {k: v for k, v in result["artifact_bindings"].items() if k != "RESULT.json"}
        arts["CONTROL.json"] = cb
        result.update({"status": child_status, "arm": mode, "association_priors": None,
                       "control_binding": cb, "csv_binding": csvb,
                       "candidate_id": "E28_APPEARANCE_COST_V1"})
        fp = output / "FEATURE_RECEIPTS.json"
        if mode == "e28_none":
            if fault == "unexpected_feature":
                fp.write_text(json.dumps([{"dataset": "fake"}]), encoding="utf-8")
                arts["FEATURE_RECEIPTS.json"] = m._binding_for_path(fp, label="feature_receipts")
            result["feature_receipts_binding"] = None
        else:
            fp.write_text(json.dumps([{"dataset": "fake"}]), encoding="utf-8")
            arts["FEATURE_RECEIPTS.json"] = m._binding_for_path(fp, label="feature_receipts")
            result["feature_receipts_binding"] = (
                {"sha256": "0" * 64} if fault == "feature_binding"
                else arts["FEATURE_RECEIPTS.json"]
            )
        result["artifact_bindings"] = arts
        (output / "RESULT.json").write_text(json.dumps(result), encoding="utf-8")
        rb = m._binding_for_path(output / "RESULT.json", label="RESULT.json")
        built.append((result, rb))

    sandbox.builder = builder
    plan = {"synthetic": True}
    seen = []

    def prepare():
        if fault == "plan_timeout":
            clock[0] = m._WALL_LIMIT_SECONDS + 1
        return plan

    monkeypatch.setattr(m, "prepare_appearance_plan", prepare)

    def verify(p, receipts, check_budget):
        assert p == plan
        assert receipts == [{"dataset": "fake"}]
        seen.append(receipts)
        assert check_budget() is not None
        if fault == "verify_timeout":
            clock[0] = m._WALL_LIMIT_SECONDS + 1
            return None
        if fault == "verify":
            raise RuntimeError("receipt verifier fail")
        return None

    monkeypatch.setattr(m, "verify_appearance_receipts", verify)

    real_write = e.write_json_exclusive
    if fault == "write_timeout":
        def write_json_exclusive(path, payload):
            real_write(path, payload)
            if path.name == "SUPERVISOR_RESULT.json":
                clock[0] = m._WALL_LIMIT_SECONDS + 1
        monkeypatch.setattr(e, "write_json_exclusive", write_json_exclusive)

    audit = out.with_name(out.name + "_supervisor")
    if fault is not None:
        with pytest.raises(RuntimeError, match=expected_error):
            m.supervise_baseline(out, mode=mode)
        assert not (out / "RESULT.json").exists()
        assert (out / "RESULT.failed.json").exists()
        assert not (audit / "SUPERVISOR_RESULT.json").exists()
        assert json.loads((audit / "ERROR.json").read_text(encoding="utf-8"))["status"] == (
            "E28_APPEARANCE_SUPERVISED_FAIL_NOT_CANDIDATE")
        if fault == "write_timeout":
            assert (audit / "SUPERVISOR_RESULT.failed.json").exists()
        return

    record = m.supervise_baseline(out, mode=mode)
    result, expected_binding = built[0]
    argv, _kwargs = sandbox.calls[0]
    assert record["status"] == parent_status
    assert record["arm"] == mode
    assert record["candidate_id"] == "E28_APPEARANCE_COST_V1"
    assert record["association_priors"] is None
    assert record["result_binding"] == expected_binding
    assert record["child_status"] == child_status
    assert record["feature_receipts_binding"] == result["feature_receipts_binding"]
    assert argv.count("--mode") == 1 and argv[argv.index("--mode") + 1] == mode
    assert len(sandbox.calls) == 1 and sandbox.killed == []
    assert record["returncode"] == 0 and record["gt_read"] is False
    assert (seen == [[{"dataset": "fake"}]]) if mode == "e28_appearance" else seen == []
