"""E27 registered-generation ordering guards (mocked boundaries)."""

import copy
import json
from pathlib import Path

import pytest

from biohub import e26_screen as e
from scripts import e27_prior_score as m


@pytest.fixture
def plan(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    pdir = root / "plan"
    pdir.mkdir()
    plan_path = pdir / "PLAN.json"

    fullref = e.write_json_exclusive(plan_path, {"test": True})

    checked = {
        "plan": {
            "candidate_output": str(root / "candidate"),
            "generation_sources": {},
            "candidate_prior": {"mode": "recorded_prior"},
        },
        "plan_binding": copy.deepcopy(fullref),
        "baseline": {"bindings": {}},
        "gt_inputs": {},
    }

    calls = {"before": [], "drift_call": 0, "launches": 0, "fail_gen": False}

    def _verify_plan(path, expected_sha, before_generation):
        calls["before"].append(bool(before_generation))
        n = len(calls["before"])
        assert Path(path) == plan_path
        assert expected_sha == checked["plan_binding"]["sha256"]
        if n == calls["drift_call"]:
            drift = copy.deepcopy(checked)
            drift["plan_binding"] = {"path": str(plan_path), "sha256": "b" * 64}
            return drift
        return copy.deepcopy(checked)

    def _supervise_baseline(out, mode):
        assert Path(out) == Path(checked["plan"]["candidate_output"])
        assert mode == "recorded_prior"
        pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
        assert pregen.exists(), "pre-generation receipt must exist before launch"
        doc = json.loads(pregen.read_text(encoding="utf-8"))
        assert doc["plan_binding"] == checked["plan_binding"]
        calls["launches"] += 1
        if calls["fail_gen"]:
            raise RuntimeError("generation failure")

    monkeypatch.setattr(m, "verify_plan", _verify_plan)
    monkeypatch.setattr(m.g, "supervise_baseline", _supervise_baseline)
    monkeypatch.setattr(
        m, "verify_generation", lambda *a, **k: {"bindings": {"verified": True}}
    )
    return plan_path, checked, calls


def test_success(plan):
    plan_path, checked, calls = plan
    result = m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["before"] == [True, True, False]
    assert calls["launches"] == 1
    assert result["status"] == "GENERATED_NOT_SCORED"
    assert result["submission_authorized"] is False
    pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    assert result["pregen_binding"] == m.g._binding_for_path(pregen, label="pregen")


def test_existing_receipt_preserved(plan):
    plan_path, checked, calls = plan
    pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    pregen.write_text(json.dumps({"old": True}), encoding="utf-8")
    with pytest.raises((FileExistsError, e.E26Error)):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert pregen.read_bytes() == json.dumps({"old": True}).encode("utf-8")
    assert calls["launches"] == 0


def test_plan_drift_before_launch(plan):
    plan_path, checked, calls = plan
    calls["drift_call"] = 2
    with pytest.raises(RuntimeError):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["launches"] == 0
    assert (plan_path.parent / "PREGEN_PLAN_VERIFIED.json").exists()


def test_third_call_drift_after_receipt(plan):
    plan_path, checked, calls = plan
    calls["drift_call"] = 3
    with pytest.raises(RuntimeError):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["launches"] == 1
    assert (plan_path.parent / "PREGEN_PLAN_VERIFIED.json").exists()


def test_generation_failure_no_retry(plan):
    plan_path, checked, calls = plan
    calls["fail_gen"] = True
    with pytest.raises(RuntimeError, match="generation failure"):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["launches"] == 1
    assert (plan_path.parent / "PREGEN_PLAN_VERIFIED.json").exists()
