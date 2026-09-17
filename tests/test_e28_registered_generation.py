"""E28 registered-generation ordering and budget guards (mocked boundaries)."""

import copy
import json
from pathlib import Path

import pytest

from biohub import e26_screen as e
from scripts import e28_score as m


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
            "appearance_plan": {"synthetic": True},
        },
        "plan_binding": copy.deepcopy(fullref),
        "baseline": {"bindings": {}},
        "gt_inputs": {},
    }

    calls = {
        "before": [],
        "drift_call": 0,
        "launches": 0,
        "fail_gen": False,
        "budget": 0,
        "expire": None,
        "verify_generation": 0,
    }

    def _verify_plan(path, expected_sha, *, before_generation, check_budget):
        assert callable(check_budget)
        n = len(calls["before"])
        if n == 0:
            calls["first_check_budget"] = check_budget
        else:
            assert check_budget is calls["first_check_budget"]
        calls["before"].append(bool(before_generation))
        check_budget()
        assert Path(path) == plan_path
        assert expected_sha == checked["plan_binding"]["sha256"]
        if n + 1 == calls["drift_call"]:
            drift = copy.deepcopy(checked)
            drift["plan_binding"] = {"path": str(plan_path), "sha256": "b" * 64}
            return drift
        return copy.deepcopy(checked)

    def _supervise_baseline(out, mode):
        assert Path(out) == Path(checked["plan"]["candidate_output"])
        assert mode == "e28_appearance"
        pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
        assert pregen.exists(), "pre-generation receipt must exist before launch"
        doc = json.loads(pregen.read_text(encoding="utf-8"))
        assert doc["schema"] == "E28_PREGEN_PLAN_VERIFIED_V1"
        assert doc["mode"] == "e28_appearance"
        assert doc["submission_authorized"] is False
        assert doc["plan_binding"] == checked["plan_binding"]
        calls["launches"] += 1
        if calls["fail_gen"]:
            raise RuntimeError("generation failure")

    def _verify_generation(path, arm, sources, appearance_plan, check_budget):
        assert Path(path) == Path(checked["plan"]["candidate_output"])
        assert arm == "e28_appearance"
        assert sources == {}
        assert appearance_plan == {"synthetic": True}
        assert callable(check_budget)
        assert check_budget is calls["first_check_budget"]
        check_budget()
        calls["verify_generation"] += 1
        return {"bindings": {"verified": True}}

    def _check_runtime_budget(start, *, wall_limit_seconds, ram_limit_bytes):
        assert wall_limit_seconds == 1800
        assert ram_limit_bytes == 8 * 1024**3
        calls["budget"] += 1
        if calls["expire"] == "entry":
            raise RuntimeError("wrapper budget")
        if calls["expire"] == "after_launch" and calls["launches"] > 0:
            raise RuntimeError("wrapper budget")
        return {
            "wall_seconds": 1,
            "peak_rss_bytes": 100,
            "ram_scope": "self_process",
        }

    monkeypatch.setattr(m, "verify_plan", _verify_plan)
    monkeypatch.setattr(m.g, "supervise_baseline", _supervise_baseline)
    monkeypatch.setattr(m, "verify_generation", _verify_generation)
    monkeypatch.setattr(e, "check_runtime_budget", _check_runtime_budget)
    return plan_path, checked, calls


def test_success(plan):
    plan_path, checked, calls = plan
    result = m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["before"] == [True, True, False]
    assert calls["launches"] == 1
    assert calls["verify_generation"] == 1
    assert result["status"] == "GENERATED_NOT_SCORED"
    assert result["submission_authorized"] is False
    pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    assert result["pregen_binding"] == m.g._binding_for_path(pregen, label="pregen")
    assert result["schema"] == "E28_REGISTERED_GENERATION_V1"
    assert calls["budget"] >= len(calls["before"]) + 1


def test_existing_receipt_preserved(plan):
    plan_path, checked, calls = plan
    pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    pregen.write_text(json.dumps({"old": True}), encoding="utf-8")
    with pytest.raises((FileExistsError, e.E26Error)):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert pregen.read_bytes() == json.dumps({"old": True}).encode("utf-8")
    assert calls["launches"] == 0
    assert calls["verify_generation"] == 0


def test_plan_drift_before_launch(plan):
    plan_path, checked, calls = plan
    calls["drift_call"] = 2
    with pytest.raises(RuntimeError):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["launches"] == 0
    assert calls["verify_generation"] == 0
    assert (plan_path.parent / "PREGEN_PLAN_VERIFIED.json").exists()


def test_third_call_drift_after_receipt(plan):
    plan_path, checked, calls = plan
    calls["drift_call"] = 3
    with pytest.raises(RuntimeError):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["launches"] == 1
    assert calls["verify_generation"] == 0
    assert (plan_path.parent / "PREGEN_PLAN_VERIFIED.json").exists()


def test_generation_failure_no_retry(plan):
    plan_path, checked, calls = plan
    calls["fail_gen"] = True
    with pytest.raises(RuntimeError, match="generation failure"):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["launches"] == 1
    assert calls["verify_generation"] == 0
    assert (plan_path.parent / "PREGEN_PLAN_VERIFIED.json").exists()


def test_budget_expiry_at_entry_blocks_before_regen(plan):
    plan_path, checked, calls = plan
    calls["expire"] = "entry"
    pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    with pytest.raises(RuntimeError, match="wrapper budget"):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert not pregen.exists()
    assert calls["launches"] == 0
    assert calls["before"] == []
    assert calls["verify_generation"] == 0


def test_budget_expiry_after_launch_does_not_regenerate(plan):
    plan_path, checked, calls = plan
    calls["expire"] = "after_launch"
    pregen = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    with pytest.raises(RuntimeError, match="wrapper budget"):
        m.run_registered_generation(plan_path, checked["plan_binding"]["sha256"])
    assert calls["launches"] == 1
    assert pregen.exists()
    assert calls["before"] == [True, True]
    assert calls["verify_generation"] == 0
