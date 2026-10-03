"""Synthetic API-boundary tests for e27_prior_score.score_eval12_core (issue9)."""
import copy
import json
from pathlib import Path

import pytest

from biohub import e26_screen as e
from biohub import evaluate
from scripts.experiments.e27 import e27_prior_score as m


@pytest.fixture
def prepare(tmp_path, monkeypatch):
    options = {"delta": 0.01, "bad_summary": False}
    calls, preflights = [], []
    base_csv = str(tmp_path / "baseline.csv")
    cand_csv = str(tmp_path / "candidate.csv")
    base_out = str(tmp_path / "baseline_run")
    cand_out = str(tmp_path / "candidate_run")
    src = {"test": "source"}

    def control(arm, prior, output):
        return {"config": {}, "dependency_binding": {}, "generation_input_binding": {},
                "metadata_bindings": {}, "reader_bindings": {}, "source_bindings": dict(src),
                "arm": arm, "association_priors": prior, "output": output}

    def record(csv, ctrl):
        rows = [{"dataset": s, "nodes": 1, "edges": 1, "forks": 0} for s in m.g.STEMS]
        return {"control": ctrl, "result": {"csv_binding": {"path": csv}},
                "csv_report": {"per_dataset": rows}}

    plan = {"plan": {"candidate_id": "E27_RECORDED_PRIOR_V1", "generation_sources": dict(src),
                     "baseline_prior": {"mode": "selected_only"},
                     "candidate_prior": {"mode": "recorded_prior"},
                     "baseline_output": base_out, "candidate_output": cand_out},
            "baseline": None, "gt_inputs": {}}
    plan["baseline"] = record(base_csv, control("selected_only",
                                                plan["plan"]["baseline_prior"], base_out))
    candidate = record(cand_csv, control("recorded_prior",
                                         plan["plan"]["candidate_prior"], cand_out))

    def fake_preflight(stage, inputs):
        assert stage == "eval12"
        assert inputs is plan["gt_inputs"]
        preflights.append(stage)
        return {"stage": stage, "videos": []}

    def fake_score(csv, gt_dir, max_distance, verbose):
        assert max_distance == 7.0
        assert verbose is False
        calls.append(str(csv))
        rows = []
        for s in m.g.STEMS:
            adj = 0.8 + (options["delta"] if str(csv) == cand_csv else 0.0)
            rows.append({"dataset": s, "edge_tp": 80, "edge_fp": 0, "edge_fn": 20,
                         "division_tp": 1, "division_fp": 0, "division_fn": 0,
                         "num_pred_nodes": 1, "node_recall": 1.0, "total_node_ratio": -0.5,
                         "edge_jaccard": 0.8, "adj_edge_jaccard": adj})
        summary = evaluate.summarise([{k: v for k, v in r.items() if k != "dataset"} for r in rows])
        if options["bad_summary"]:
            summary["score"] += 0.02
        return summary, rows

    monkeypatch.setattr(evaluate, "score_submission", fake_score)
    monkeypatch.setattr(e, "_check_stage_gt", fake_preflight)
    out = tmp_path / "out"
    out.mkdir()
    snapshot = copy.deepcopy({"plan": plan, "candidate": candidate})
    boxes = {"plan": plan, "candidate": candidate, "out": out, "calls": calls,
             "preflights": preflights, "options": options, "base_csv": base_csv,
             "cand_csv": cand_csv, "snapshot": snapshot}
    yield boxes
    assert plan == snapshot["plan"]
    assert candidate == snapshot["candidate"]


@pytest.mark.parametrize("delta,expect_status",
                         [(0.0, "SCREEN_REJECT_EVAL12"), (0.01, "SCREEN_EVAL12_PASS")])
def test_score_eval12_core_delta(prepare, delta, expect_status):
    prepare["options"]["delta"] = delta
    result = m.score_eval12_core(prepare["plan"], prepare["candidate"],
                                 prepare["out"], lambda: {})
    assert prepare["calls"] == [prepare["base_csv"], prepare["cand_csv"]]
    assert prepare["preflights"] == ["eval12", "eval12"]
    gate = result["paired"]["gate"]
    assert gate["status"] == expect_status
    assert gate["candidate_id"] == "E27_RECORDED_PRIOR_V1"
    assert gate["rule_implementation_candidate_id"] == e.CANDIDATE_ID
    assert gate["paired_statistics"]["mean"] == pytest.approx(delta)
    assert result["submission_authorized"] is False
    assert not (prepare["out"] / "SCORE_RESULT.json").exists()
    for arm in ("baseline", "candidate"):
        doc = json.loads((prepare["out"] / (arm + ".json")).read_text())
        assert doc["arm"] == arm
        assert doc["candidate_id"] == "E27_RECORDED_PRIOR_V1"
        assert len(doc["official"]["rows"]) == 12


def test_control_config_mismatch_stops_before_scoring(prepare):
    original_config = prepare["candidate"]["control"]["config"]
    changed_config = {"changed": True}
    try:
        prepare["candidate"]["control"]["config"] = changed_config
        plan_snapshot = copy.deepcopy(prepare["plan"])
        candidate_snapshot = copy.deepcopy(prepare["candidate"])
        with pytest.raises(ValueError, match="CONTROL binding mismatch"):
            m.score_eval12_core(prepare["plan"], prepare["candidate"],
                                prepare["out"], lambda: {})
        assert prepare["plan"] == plan_snapshot
        assert prepare["candidate"] == candidate_snapshot
        assert prepare["calls"] == []
        assert prepare["preflights"] == []
    finally:
        prepare["candidate"]["control"]["config"] = original_config


def test_bad_summary_raises_no_final(prepare):
    prepare["options"]["bad_summary"] = True
    with pytest.raises(ValueError, match="official summary drift"):
        m.score_eval12_core(prepare["plan"], prepare["candidate"],
                            prepare["out"], lambda: {})
    assert not (prepare["out"] / "SCORE_RESULT.json").exists()


# ---- appended: post-score verifier boundary tests (issue #9) ----------------


def _verifier_args(prepare, core, out):
    return {"plan_path": str(prepare["out"] / "plan.json"),
            "expected_sha": "sha-under-test",
            "checked_plan": prepare["plan"],
            "candidate": prepare["candidate"],
            "output": out,
            "core": core,
            "check_budget": lambda: None}


@pytest.fixture
def scored_post(prepare, monkeypatch):
    """Authentic synthetic core, then forbid any further scoring/GT semantics."""
    core = m.score_eval12_core(prepare["plan"], prepare["candidate"],
                              prepare["out"], lambda: {})
    out = prepare["out"]
    for arm in ("baseline", "candidate"):
        (out / (arm + ".json")).write_bytes((out / (arm + ".json")).read_bytes())
    (out / "baseline.json").write_bytes(Path(out / "baseline.json").read_bytes())

    def forbidden(*args, **kwargs):
        raise AssertionError("POST-verifier must not score or check GT")

    monkeypatch.setattr(evaluate, "score_submission", forbidden)
    monkeypatch.setattr(e, "_check_stage_gt", forbidden)

    calls = {"plan": 0, "gen": 0}

    def fake_verify_plan(plan_path, expected_sha):
        calls["plan"] += 1
        assert str(plan_path) == str(out / "plan.json")
        assert expected_sha == "sha-under-test"
        return copy.deepcopy(prepare["plan"])

    def fake_verify_generation(output, mode, sources, prior):
        calls["gen"] += 1
        plan = prepare["plan"]["plan"]
        assert str(output) == plan["candidate_output"]
        assert mode == plan["candidate_prior"]["mode"] == "recorded_prior"
        assert sources == plan["generation_sources"]
        assert prior == plan["candidate_prior"]
        return copy.deepcopy(prepare["candidate"])

    monkeypatch.setattr(m, "verify_plan", fake_verify_plan)
    monkeypatch.setattr(m, "verify_generation", fake_verify_generation)
    prepare["calls"].clear()
    prepare["preflights"].clear()
    prepare["core"] = core
    prepare["post_calls"] = calls
    prepare["post_options"] = {"plan_path": str(out / "plan.json")}
    yield prepare
    assert calls["plan"] >= 0 and calls["gen"] >= 0


def test_verify_score_core_pass_no_mutation_no_rewrite(scored_post):
    p = scored_post
    out = p["out"]
    before = {a: (out / (a + ".json")).read_bytes() for a in ("baseline", "candidate")}
    refs_before = copy.deepcopy(p["core"]["arm_artifacts"])
    result = m.verify_score_core(**_verifier_args(p, p["core"], out))
    assert p["post_calls"]["plan"] == 2
    assert p["post_calls"]["gen"] == 2
    assert result["verified"] is True
    assert result["stage"] == "eval12"
    assert result["submission_authorized"] is False
    assert result["candidate_id"] == "E27_RECORDED_PRIOR_V1"
    assert result["paired"] == p["core"]["paired"]
    assert result["paired"]["gate"]["candidate_id"] == "E27_RECORDED_PRIOR_V1"
    assert result["paired"]["gate"]["rule_implementation_candidate_id"] == e.CANDIDATE_ID
    assert result["arm_artifacts"] == refs_before
    after = {a: (out / (a + ".json")).read_bytes() for a in ("baseline", "candidate")}
    assert after == before
    assert p["core"]["arm_artifacts"] == refs_before
    assert not (out / "SCORE_RESULT.json").exists()
    assert p["calls"] == []
    assert p["preflights"] == []


@pytest.mark.parametrize("which,target",
                         [("plan", "plan"), ("plan", "fresh2"),
                          ("gen", "gen"), ("gen", "gen2")])
def test_verifier_drift_on_first_or_second_call(scored_post, which, target):
    p = scored_post
    first = target in ("plan", "gen")
    seen = {"plan": 0, "gen": 0}
    original = m.verify_plan if which == "plan" else m.verify_generation

    def drifting(*args, **kwargs):
        key = "plan" if which == "plan" else "gen"
        seen[key] += 1
        value = original(*args, **kwargs)
        if (seen[key] == 1) == first:
            value["drift_sentinel"] = "post-score-drift"
        return value

    setattr(m, "verify_plan" if which == "plan" else "verify_generation", drifting)
    try:
        with pytest.raises(ValueError, match="drift"):
            m.verify_score_core(**_verifier_args(p, p["core"], p["out"]))
        expected = 1 if first else 2
        assert seen[which] == expected
        assert not (p["out"] / "SCORE_RESULT.json").exists()
    finally:
        setattr(m, "verify_plan" if which == "plan" else "verify_generation", original)


def test_artifact_binding_changed_rejects_final(scored_post):
    p = scored_post
    path = p["out"] / "baseline.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="baseline artifact binding changed"):
        m.verify_score_core(**_verifier_args(p, p["core"], p["out"]))
    assert not (p["out"] / "SCORE_RESULT.json").exists()


def test_gate_tamper_detected_as_paired_mismatch(scored_post):
    p = scored_post
    tampered = copy.deepcopy(p["core"])
    tampered["paired"]["gate"]["status"] = "FORGED"
    with pytest.raises(ValueError, match="adapted paired record differs"):
        m.verify_score_core(**_verifier_args(p, tampered, p["out"]))
    assert p["core"]["paired"]["gate"]["status"] != "FORGED"
    assert not (p["out"] / "SCORE_RESULT.json").exists()


def test_official_arm_tamper_detected(scored_post):
    p = scored_post
    tampered = copy.deepcopy(p["core"])
    summary = tampered["arms"]["baseline"]["groups"]["eval12"]["summary"]
    summary["score"] += 0.01
    with pytest.raises(ValueError, match="baseline rebuilt official record differs"):
        m.verify_score_core(**_verifier_args(p, tampered, p["out"]))
    assert p["core"]["arms"]["baseline"]["groups"]["eval12"]["summary"]["score"] \
        == tampered["arms"]["baseline"]["groups"]["eval12"]["summary"]["score"] - 0.01
    assert not (p["out"] / "SCORE_RESULT.json").exists()
