"""Synthetic orchestration tests for scripts.experiments.e27.e27_association_prior_screen.

Nothing here touches real materials, models, cores, runtimes, datasets or GT.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

import scripts.experiments.e27.e27_association_prior_screen as m
from biohub import e26_screen as e

REFERENCE_BYTES = b"a,b,c\n1,2,3\n"
REFERENCE_SHA256 = hashlib.sha256(REFERENCE_BYTES).hexdigest()


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
class Calls:
    def __init__(self) -> None:
        self.order: list[str] = []
        self.counts: dict[str, int] = {}

    def hit(self, name: str) -> int:
        self.counts[name] = self.counts.get(name, 0) + 1
        self.order.append(name)
        return self.counts[name]


class SigRecorder:
    def __init__(self, existing=(0.0, 0.0)) -> None:
        self.existing = existing
        self.setitimer_calls: list[tuple] = []
        self.signal_calls: list[tuple] = []

    def getitimer(self, _which):
        return self.existing

    def setitimer(self, which, *args):
        self.setitimer_calls.append((which, args))

    def signal(self, which, handler):
        self.signal_calls.append((which, handler))
        return lambda *a: None

    def getsignal(self, _which):
        return None


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "outputs" / "local").mkdir(parents=True)
    src = root / "src" / "biohub" / "fake_mod.py"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x = 1\n")

    monkeypatch.setattr(m, "ROOT", root)
    monkeypatch.setattr(m, "_source_closure_paths", lambda: [src])
    monkeypatch.setattr(m, "_REFERENCE_RELATIVE", Path("reference.csv"))
    monkeypatch.setattr(m, "_REFERENCE_BYTES", len(REFERENCE_BYTES))
    monkeypatch.setattr(m, "_REFERENCE_SHA256", REFERENCE_SHA256)

    ref = root / "reference.csv"
    ref.write_bytes(REFERENCE_BYTES)

    sig = SigRecorder()
    for name in ("getitimer", "setitimer", "signal", "getsignal"):
        monkeypatch.setattr(m.signal, name, getattr(sig, name))

    calls = Calls()
    cfg = object()
    bundle = object()
    init_box: dict[str, bool] = {"done": False}
    prepared_box: dict[str, object] = {}
    prior_state: dict[str, object] = {"receipt": None}

    def fake_initialize_inference_runtime():
        calls.hit("init")
        init_box["done"] = True
        return {"runtime": "fake"}

    def fake_prepare_inputs():
        calls.hit("prepare")
        assert init_box["done"] is True
        gen_binding = {
            "eval36": {
                "raw_inventory": {"selected_path": str(root / "raw")},
            }
        }
        c = {
            "config": {"synthetic": True},
            "dependency_binding": {"fake": True},
            "generation_input_binding": gen_binding,
        }
        prepared = {
            "baseline_control": c,
            "status": "INPUTS_PREPARED_NOT_GENERATED",
            "gt_read": False,
            "datasets": list(m.STEMS),
            "raw_paths": [root / "raw" / f"{s}.geff" for s in m.STEMS],
            "metadata_bindings": {},
            "reader_bindings": {},
        }
        prepared_box["prepared"] = prepared
        return prepared

    verify_state = {"n": 0}

    def fake_verify_prepared_materials(prepared):
        calls.hit("verify")
        verify_state["n"] += 1
        assert prepared is prepared_box["prepared"]
        if verify_state["n"] > env_params["verify_ok_after"]:
            raise RuntimeError("post-material verification failed")
        return cfg

    def fake_build_prior_inputs(prepared, mode):
        nth = calls.hit("prior")
        assert prepared is prepared_box["prepared"]
        assert mode == env_params["mode"]
        mapping = {stem: {(1, 2): 0.8} for stem in m.STEMS}
        receipt = {"synthetic_mode": mode}
        if nth > 1 and env_params["prior_drift"]:
            # Deliberately orchestration-only drift stub: the real receipt
            # semantics are exercised by the dedicated screen tests.
            receipt = {"drift": True}
        prior_state["receipt"] = receipt
        return mapping, receipt

    def fake_load_child_model(config, generation_input_binding):
        calls.hit("load")
        assert config is cfg
        prepared = prepared_box["prepared"]
        assert generation_input_binding is prepared["baseline_control"][
            "generation_input_binding"
        ]
        control_path = env_params["out"] / "CONTROL.json"
        control_raw = control_path.read_bytes()
        control = json.loads(control_raw.decode("utf-8"))
        assert control["schema"] == "E27_BASELINE_CONTROL_V1"
        assert control["arm"] == env_params["mode"]
        assert control["submission_allowed"] is False
        assert control["config"] == {"synthetic": True}
        assert control["generation_input_binding"] == prepared["baseline_control"][
            "generation_input_binding"
        ]
        expected_receipt = prior_state["receipt"]
        if env_params["mode"] != "baseline_none":
            assert expected_receipt is not None
            assert control["association_priors"] == expected_receipt
        if env_params["control_drift"]:
            control_path.write_bytes(control_raw + b"\n")
        return bundle, {"receipt": "fake"}

    def fake_execute_baseline_core(
        prep,
        config,
        mdl,
        out,
        check_budget,
        *,
        association_priors_by_dataset=None,
    ):
        calls.hit("core")
        if env_params["mode"] == "baseline_none":
            assert association_priors_by_dataset is None
        else:
            assert isinstance(association_priors_by_dataset, Mapping)
            assert list(association_priors_by_dataset) == list(m.STEMS)
            assert all(
                v == {(1, 2): 0.8} for v in association_priors_by_dataset.values()
            )
            assert prior_state["receipt"] is not None
        assert prep is prepared_box["prepared"]
        assert config is cfg
        assert mdl is bundle
        assert out == env_params["out"] and out.is_dir()
        csv_path = out / "submission.csv"
        csv_payload = env_params["csv_bytes"]
        if env_params["mutate_source"]:
            src.write_bytes(b"x = 2\n")
        if env_params["core_raises"]:
            raise RuntimeError("core exploded")
        csv_path.write_bytes(csv_payload)
        report = {
            "datasets": list(m.STEMS),
            "total_nodes": 12,
            "total_edges": 0,
            "total_rows": 12,
        }
        check_budget()
        return {
            "csv_path": csv_path,
            "report": report,
            "events": [],
            "raw_rows": [],
            "bounds": {},
            "loader_calls": 1,
        }

    def fake_check_runtime_budget(started, **kwargs):
        calls.hit("budget")
        assert kwargs["wall_limit_seconds"] == m._WALL_LIMIT_SECONDS
        if env_params["budget_raises"] and (env_params["out"] / "RESULT.json").exists():
            raise RuntimeError("late budget failure")
        return {"elapsed": 0.5, "ram_bytes": 1024}

    monkeypatch.setattr(
        e, "initialize_inference_runtime", fake_initialize_inference_runtime
    )
    monkeypatch.setattr(e, "_load_child_model", fake_load_child_model)
    monkeypatch.setattr(e, "check_runtime_budget", fake_check_runtime_budget)
    monkeypatch.setattr(m, "prepare_inputs", fake_prepare_inputs)
    monkeypatch.setattr(m, "verify_prepared_materials", fake_verify_prepared_materials)
    monkeypatch.setattr(m, "execute_baseline_core", fake_execute_baseline_core)
    monkeypatch.setattr(m, "build_prior_inputs", fake_build_prior_inputs)

    env_params.update(
        {
            "root": root,
            "src": src,
            "ref": ref,
            "out": None,
            "csv_bytes": REFERENCE_BYTES,
            "core_raises": False,
            "mutate_source": False,
            "budget_raises": False,
            "verify_ok_after": 99,
            "control_drift": False,
            "mode": "baseline_none",
            "prior_drift": False,
        }
    )
    return {
        "root": root,
        "src": src,
        "ref": ref,
        "calls": calls,
        "sig": sig,
        "cfg": cfg,
        "bundle": bundle,
        "params": env_params,
    }


env_params: dict[str, object] = {}


def _output(root: Path, name: str) -> Path:
    out = root / "outputs" / "local" / name
    env_params["out"] = out
    return out


def _reset_params(**overrides) -> None:
    env_params.clear()
    env_params.update(
        {
            "out": None,
            "csv_bytes": REFERENCE_BYTES,
            "core_raises": False,
            "mutate_source": False,
            "budget_raises": False,
            "verify_ok_after": 99,
            "control_drift": False,
            "mode": "baseline_none",
            "prior_drift": False,
        }
    )
    env_params.update(overrides)


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------
def test_happy_path(env):
    _reset_params()
    root = env["root"]
    result = m.run_baseline(_output(root, "run_ok"))

    calls = env["calls"]
    assert [name for name in calls.order if name != "budget"] == [
        "init",
        "prepare",
        "verify",
        "load",
        "core",
        "verify",
    ]
    assert calls.counts["load"] == 1
    assert calls.counts["core"] == 1
    assert calls.counts["verify"] == 2

    out = env_params["out"]
    saved = json.loads((out / "RESULT.json").read_text())
    assert saved == result
    assert result["status"] == "E27_BASELINE_PARITY_PASS_NOT_CANDIDATE"
    assert result["gt_read"] is False
    assert result["submission_allowed"] is False
    assert result["csv_binding"]["sha256"] == REFERENCE_SHA256
    assert result["csv_binding"]["bytes"] == len(REFERENCE_BYTES)
    assert result["artifact_bindings"]["submission.csv"]["sha256"] == REFERENCE_SHA256
    assert result["counts"]["datasets"] == list(m.STEMS)
    assert len(m.STEMS) == 12
    assert not (out / "ERROR.json").exists()
    assert not (out / "RESULT.failed.json").exists()
    assert (out / "CONTROL.json").is_file()
    assert (out / "STARTED.json").is_file()
    assert (out / "inference.json").is_file()
    assert (out / "deepcenter.json").is_file()

    # timer armed once and disarmed/restored afterwards
    sig = env["sig"]
    assert len(sig.setitimer_calls) == 2
    assert sig.setitimer_calls[-1][1] == (0,)
    assert len(sig.signal_calls) == 2
    assert sig.signal_calls[-1][1] is None


# --------------------------------------------------------------------------
# failure modes
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mode",
    [
        "core_raises",
        "source_mutated",
        "csv_mismatch",
        "late_budget",
        "post_material_fail",
        "control_drift",
    ],
)
def test_failure_modes(env, mode):
    _reset_params()
    root = env["root"]
    out = _output(root, f"run_{mode}")

    if mode == "core_raises":
        env_params["core_raises"] = True
    elif mode == "source_mutated":
        env_params["mutate_source"] = True
    elif mode == "csv_mismatch":
        env_params["csv_bytes"] = REFERENCE_BYTES + b"extra\n"
    elif mode == "late_budget":
        env_params["budget_raises"] = True
    elif mode == "post_material_fail":
        env_params["verify_ok_after"] = 1
    elif mode == "control_drift":
        env_params["control_drift"] = True
    else:  # pragma: no cover - guard against typos in the parametrisation
        raise AssertionError(mode)

    with pytest.raises(RuntimeError) as excinfo:
        m.run_baseline(out)

    assert type(excinfo.value).__name__ == "RuntimeError"

    calls = env["calls"]
    assert calls.counts.get("load", 0) <= 1
    assert calls.counts.get("core", 0) <= 1

    error = json.loads((out / "ERROR.json").read_text())
    assert error["exception_type"] == "RuntimeError"
    assert error["submission_allowed"] is False
    assert error["partial_outputs_preserved"] is True

    assert not (out / "RESULT.json").exists()
    if mode == "late_budget":
        assert (out / "RESULT.failed.json").is_file()
        moved = json.loads((out / "RESULT.failed.json").read_text())
        assert moved["status"] == "E27_BASELINE_PARITY_PASS_NOT_CANDIDATE"
    else:
        assert not (out / "RESULT.failed.json").exists()

    sig = env["sig"]
    assert len(sig.setitimer_calls) == 2
    assert sig.setitimer_calls[-1][1] == (0,)
    assert len(sig.signal_calls) == 2
    assert sig.signal_calls[-1][1] is None


# --------------------------------------------------------------------------
# timer ownership
# --------------------------------------------------------------------------
def test_refuses_to_steal_active_timer(env):
    _reset_params()
    env["sig"].existing = (10.0, 0.0)
    out = _output(env["root"], "run_timer_busy")
    with pytest.raises(RuntimeError) as excinfo:
        m.run_baseline(out)
    assert "active timer" in str(excinfo.value)
    assert env["calls"].counts == {}
    assert env["sig"].setitimer_calls == []
    assert env["sig"].signal_calls == []
    assert json.loads((out / "ERROR.json").read_text())["exception_type"] == "RuntimeError"


# --------------------------------------------------------------------------
# parent-directory alias rejection (real helpers, fixture paths only)
# --------------------------------------------------------------------------
def test_parent_directory_alias_rejected(env, monkeypatch):
    root = env["root"]
    src = env["src"]
    real_dir = src.parent
    alias_dir = root / "alias_dir"
    alias_dir.symlink_to(real_dir, target_is_directory=True)
    aliased = alias_dir / src.name

    monkeypatch.setattr(m, "_source_closure_paths", lambda: [aliased])

    with pytest.raises(RuntimeError) as excinfo:
        m._snapshot_source_closure()
    assert "aliased source file rejected" in str(excinfo.value)

    with pytest.raises(RuntimeError) as excinfo:
        m._binding_for_path(aliased, label="fixture")
    assert "aliased fixture rejected" in str(excinfo.value)

    alias_dir.unlink(missing_ok=True)
    monkeypatch.setattr(m, "_source_closure_paths", lambda: [src])
    assert m._snapshot_source_closure()["count"] == 1
    binding = m._binding_for_path(src, label="fixture")
    assert binding["path"] == str(src)
    assert binding["bytes"] == src.stat().st_size


# --------------------------------------------------------------------------
# prior-injection arms (orchestration only; stub receipts are not real)
# --------------------------------------------------------------------------
def _arm_result(out: Path) -> dict:
    return json.loads((out / "RESULT.json").read_text())


def _arm_control(out: Path) -> dict:
    return json.loads((out / "CONTROL.json").read_text())


@pytest.mark.parametrize(
    "mode,expected_status",
    [
        ("selected_only", "E27_SELECTED_ONLY_PARITY_PASS_NOT_CANDIDATE"),
        ("recorded_prior", "E27_RECORDED_PRIOR_GENERATED_UNSCORED"),
    ],
)
def test_nonbaseline_arms_record_matching_prior_receipts(env, mode, expected_status):
    env["params"].update(mode=mode)
    root = env["root"]
    out = _output(root, f"run_{mode}")

    result = m.run_baseline(out, mode=mode)

    calls = env["calls"]
    assert calls.counts["prior"] == 2
    assert [name for name in calls.order if name != "budget"] == [
        "init",
        "prepare",
        "verify",
        "prior",
        "load",
        "core",
        "prior",
        "verify",
    ]
    assert calls.counts["load"] == 1
    assert calls.counts["core"] == 1
    assert calls.counts["verify"] == 2

    saved = _arm_result(out)
    assert saved == result
    assert result["status"] == expected_status
    assert result["arm"] == mode
    assert result["gt_read"] is False
    assert result["submission_allowed"] is False
    assert result["association_priors"] == {"synthetic_mode": mode}

    control = _arm_control(out)
    assert control["arm"] == mode
    assert control["association_priors"] == result["association_priors"]

    assert (out / "submission.csv").read_bytes() == REFERENCE_BYTES
    assert not (out / "ERROR.json").exists()
    assert not (out / "RESULT.failed.json").exists()

    sig = env["sig"]
    assert len(sig.setitimer_calls) == 2
    assert sig.setitimer_calls[-1][1] == (0,)
    assert len(sig.signal_calls) == 2
    assert sig.signal_calls[-1][1] is None


def test_selected_only_requires_same_csv(env):
    env["params"].update(
        mode="selected_only", csv_bytes=REFERENCE_BYTES + b"extra\n"
    )
    root = env["root"]
    out = _output(root, "run_selected_changed_csv")

    with pytest.raises(RuntimeError):
        m.run_baseline(out, mode="selected_only")

    assert env["calls"].counts["prior"] == 2
    assert not (out / "RESULT.json").exists()
    error = json.loads((out / "ERROR.json").read_text())
    assert error["exception_type"] == "RuntimeError"
    assert error["submission_allowed"] is False


def test_recorded_tolerates_changed_csv_without_scoring(env):
    env["params"].update(
        mode="recorded_prior", csv_bytes=REFERENCE_BYTES + b"extra\n"
    )
    root = env["root"]
    out = _output(root, "run_recorded_changed_csv")

    result = m.run_baseline(out, mode="recorded_prior")

    assert result["status"] == "E27_RECORDED_PRIOR_GENERATED_UNSCORED"
    assert result["arm"] == "recorded_prior"
    assert result["submission_allowed"] is False
    assert result["association_priors"] == {"synthetic_mode": "recorded_prior"}
    assert (out / "submission.csv").read_bytes() == REFERENCE_BYTES + b"extra\n"
    assert _arm_control(out)["association_priors"] == result["association_priors"]
    assert not (out / "ERROR.json").exists()


@pytest.mark.parametrize(
    "mode",
    ["selected_only", "recorded_prior"],
)
def test_prior_receipt_drift_rejects_both_arms(env, mode):
    env["params"].update(mode=mode, prior_drift=True)
    root = env["root"]
    out = _output(root, f"run_{mode}_prior_drift")

    with pytest.raises(RuntimeError):
        m.run_baseline(out, mode=mode)

    calls = env["calls"]
    assert calls.counts["prior"] == 2
    assert calls.counts["load"] == 1
    assert calls.counts["core"] == 1
    assert not (out / "RESULT.json").exists()
    assert not (out / "RESULT.failed.json").exists()
    error = json.loads((out / "ERROR.json").read_text())
    assert error["exception_type"] == "RuntimeError"
    assert error["submission_allowed"] is False
    assert error["partial_outputs_preserved"] is True


@pytest.mark.parametrize("bad_mode", ["bad", None, True])
def test_invalid_mode_rejected_before_side_effects(env, bad_mode):
    root = env["root"]
    out = _output(root, "run_invalid_mode")

    with pytest.raises(ValueError):
        m.run_baseline(out, mode=bad_mode)

    assert env["calls"].counts == {}
    assert not out.exists()
    assert env["sig"].setitimer_calls == []
    assert env["sig"].signal_calls == []


# --------------------------------------------------------------------------
# E28 child: run_baseline orchestration (author-only synthetic coverage)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mode,fault,exc_type,match",
    [
        ("e28_none", None, None, None),
        ("e28_appearance", None, None, None),
        ("e28_appearance", "order", ValueError, "appearance loader called out of order"),
        ("e28_appearance", "duplicate", ValueError, "appearance loader called out of order"),
        ("e28_none", "csv", RuntimeError, "csv does not match reference binding"),
        ("e28_appearance", "control", RuntimeError, "CONTROL.json binding drift"),
    ],
)
def test_e28_run_baseline_orchestration(env, monkeypatch, mode, fault, exc_type, match):
    calls = env["calls"]
    bundle = env["bundle"]

    def fake_load_child_model(config, generation_input_binding):
        calls.hit("load")
        assert config is env["cfg"]
        control = json.loads((env_params["out"] / "CONTROL.json").read_text("utf-8"))
        assert generation_input_binding == control["generation_input_binding"]
        assert control["schema"] == "E28_GENERATION_CONTROL_V1"
        assert control["arm"] == mode
        assert control["candidate_id"] == "E28_APPEARANCE_COST_V1"
        assert control["association_priors"] is None
        assert control["appearance_plan"] == env_params["_plan"]
        return bundle, {"receipt": "fake"}

    def fake_execute_baseline_core(prep, config, mdl, out, check_budget, **kwargs):
        calls.hit("core")
        assert (
            prep["baseline_control"]["generation_input_binding"]
            == json.loads((out / "CONTROL.json").read_text("utf-8"))[
                "generation_input_binding"
            ]
        )
        assert config is env["cfg"]
        assert mdl is bundle
        assert out == env_params["out"] and out.is_dir()
        assert list(kwargs) == (
            ["appearance_loader"] if mode == "e28_appearance" else []
        )
        loader = kwargs.get("appearance_loader")
        expected = {}
        if loader is not None:
            stems = list(m.STEMS)
            if fault == "order":
                stems.reverse()
            if fault == "duplicate":
                stems.insert(1, stems[0])
            for stem in stems:
                raw = {(1, 2): 0.8}
                frames = loader(stem, raw)
                assert frames is loaded_frames[stem]
                expected[stem] = frames
        csv_path = out / "submission.csv"
        csv_path.write_bytes(
            b"candidate\n" if (mode == "e28_appearance" or fault == "csv")
            else REFERENCE_BYTES
        )
        if fault == "control":
            cp = out / "CONTROL.json"
            cp.write_bytes(cp.read_bytes() + b"\n")
        env_params["_expected_frames"] = expected
        check_budget()
        return {
            "csv_path": csv_path,
            "report": {"datasets": list(m.STEMS), "total_nodes": 12,
                       "total_edges": 0, "total_rows": 12},
            "events": [], "raw_rows": [], "bounds": {}, "loader_calls": len(m.STEMS),
        }

    def fake_prepare_appearance_plan():
        calls.hit("plan")
        plan = {
            "dataset_groups": {s: f"group-{s}" for s in m.STEMS},
            "bindings_by_dataset": {s: {"binding": s} for s in m.STEMS},
        }
        env_params["_plan"] = plan
        return plan

    requests = []
    loaded_frames = {}
    expected_receipts = []

    def fake_load_appearance_frames(collection_root, group, dataset, binding, raw_nodes):
        calls.hit("loader")
        nth = calls.counts["loader"]
        assert collection_root == m.COLLECTION_ROOT
        assert group == env_params["_plan"]["dataset_groups"][dataset]
        assert binding == env_params["_plan"]["bindings_by_dataset"][dataset]
        assert raw_nodes == {(1, 2): 0.8}
        requests.append((nth, dataset, str(group), str(binding)))
        frames = {"frames_for": dataset, "identity": object()}
        loaded_frames[dataset] = frames
        receipt = {"receipt_id": nth, "dataset": dataset, "group": str(group)}
        expected_receipts.append(receipt)
        return frames, receipt

    verified = []

    def fake_verify_appearance_receipts(plan, receipts, budget):
        calls.hit("receipt_verify")
        assert plan is env_params["_plan"]
        assert receipts == expected_receipts
        assert [r["dataset"] for r in receipts] == list(m.STEMS)
        assert [r["receipt_id"] for r in receipts] == list(range(1, len(m.STEMS) + 1))
        verified.append(list(receipts))
        budget()

    monkeypatch.setattr(e, "_load_child_model", fake_load_child_model)
    monkeypatch.setattr(m, "execute_baseline_core", fake_execute_baseline_core)
    monkeypatch.setattr(m, "prepare_appearance_plan", fake_prepare_appearance_plan)
    monkeypatch.setattr(m, "verify_appearance_receipts", fake_verify_appearance_receipts)
    monkeypatch.setattr("biohub.appearance_inputs.load_appearance_frames",
                        fake_load_appearance_frames)

    _reset_params(mode=mode)
    out = _output(env["root"], mode)
    if fault is not None:
        with pytest.raises(exc_type, match=match):
            m.run_baseline(out, mode=mode)
        assert not (out / "RESULT.json").exists()
        assert (out / "ERROR.json").is_file()
        assert env["sig"].setitimer_calls[-1][1] == (0,)
        return
    result = m.run_baseline(out, mode=mode)

    assert result["status"] == (
        "E28_APPEARANCE_NONE_PARITY_PASS_NOT_CANDIDATE" if mode == "e28_none"
        else "E28_APPEARANCE_COST_V1_GENERATED_UNSCORED")
    assert result["arm"] == mode and result["gt_read"] is False
    assert result["submission_allowed"] is False
    assert result["association_priors"] is None
    assert calls.counts.get("prior", 0) == 0
    assert calls.counts["load"] == 1 and calls.counts["core"] == 1
    control = json.loads((out / "CONTROL.json").read_text("utf-8"))
    assert control["schema"] == "E28_GENERATION_CONTROL_V1"
    assert control["candidate_id"] == "E28_APPEARANCE_COST_V1"
    assert control["appearance_plan"] == env_params["_plan"]
    assert result["control_binding"]["sha256"] == hashlib.sha256(
        (out / "CONTROL.json").read_bytes()).hexdigest()
    assert result["csv_binding"]["bytes"] == (
        len(b"candidate\n") if mode == "e28_appearance" else len(REFERENCE_BYTES))
    assert (out / "RESULT.json").is_file()
    assert not (out / "ERROR.json").exists()
    assert not (out / "RESULT.failed.json").exists()
    assert env["sig"].setitimer_calls[-1][1] == (0,)

    fr = out / "FEATURE_RECEIPTS.json"
    if mode == "e28_none":
        assert not fr.exists()
        assert result["feature_receipts_binding"] is None
        assert calls.counts.get("loader", 0) == 0
        assert calls.counts.get("receipt_verify", 0) == 0
        return
    assert fr.is_file()
    assert json.loads(fr.read_text("utf-8")) == verified[0]
    fb = result["feature_receipts_binding"]
    assert fb == m._binding_for_path(fr, label="feature_receipts")
    assert calls.counts["receipt_verify"] == 1 and calls.counts["loader"] == len(m.STEMS)
    assert [r[1] for r in requests] == list(m.STEMS)
    assert all(r[2] == f"group-{r[1]}" and r[3] == str({"binding": r[1]}) for r in requests)
    assert env_params["_expected_frames"].keys() == set(m.STEMS)
