"""Synthetic orchestration tests for scripts.experiments.e28.e28_score.verify_generation."""

import copy
import hashlib
import json

import pytest

import scripts.experiments.e28.e28_score as m
from biohub import e26_screen as e
from biohub import evaluate

g = m.g
STEMS = ["synthA", "synthB"]
VIDS = [{"dataset": s, "metadata": {"shape_tzyx": [100, 2, 4, 4]}} for s in STEMS]
COUNTS = {"datasets": list(STEMS), "videos": len(STEMS)}


def _binding(path, label):
    return g._binding_for_path(path, label=label)


@pytest.fixture
def builder(tmp_path, monkeypatch):
    calls = {"budget": 0, "bounds": 0, "csv": 0, "raw": 0, "closure": 0,
             "receipts": 0, "plan": 0}
    root = tmp_path.resolve()
    plan = {"synthetic": True}

    def budget():
        calls["budget"] += 1

    def verify_raw(raw, arm=None, csv_report=None):
        calls["raw"] += 1
        assert raw == {}
        assert arm == "baseline"
        assert csv_report == COUNTS

    def fake_csv(path, datasets=None, shapes=None):
        calls["csv"] += 1
        assert list(datasets) == STEMS
        assert sorted(shapes) == sorted(STEMS)
        return dict(COUNTS)

    def fake_bounds(bounds, csv_path, shapes):
        calls["bounds"] += 1
        assert bounds == {}

    def verify_receipts(expected, receipts, cb):
        calls["receipts"] += 1
        assert expected == plan
        assert receipts == [{"dataset": "fake"}]
        cb()

    def closure(sources):
        calls["closure"] += 1
        assert sources == {}

    monkeypatch.setattr(g, "ROOT", root)
    monkeypatch.setattr(g, "STEMS", list(STEMS))
    monkeypatch.setattr(g, "_REFERENCE_BYTES", len(b"baseline\n"))
    monkeypatch.setattr(g, "_REFERENCE_SHA256",
                        hashlib.sha256(b"baseline\n").hexdigest())
    monkeypatch.setattr(g, "_verify_source_closure", closure)
    monkeypatch.setattr(g, "prepare_appearance_plan", lambda: (calls.__setitem__(
        "plan", calls["plan"] + 1), plan)[1])
    monkeypatch.setattr(g, "verify_appearance_receipts", verify_receipts)
    monkeypatch.setattr(g, "validate_known12_statistics", verify_raw)
    monkeypatch.setattr(e, "validate_generated_csv", fake_csv)
    monkeypatch.setattr(e, "_validate_screen_bounds", fake_bounds)

    def build(mode, fault=None):
        output = root / "outputs" / "local" / "run"
        audit = output.with_name(output.name + "_supervisor")
        output.mkdir(parents=True)
        audit.mkdir(parents=True)

        body = b"tampered\n" if fault == "csv" else (
            b"baseline\n" if mode == "e28_none" else b"candidate\n")
        control_plan = {"synthetic": False} if fault == "plan" else plan

        control = {
            "schema": "E28_GENERATION_CONTROL_V1", "arm": mode,
            "run_id": output.name, "candidate_id": "E28_APPEARANCE_COST_V1",
            "submission_allowed": False, "output": str(output),
            "datasets": list(STEMS), "source_bindings": {},
            "appearance_plan": control_plan, "association_priors": None,
            "generation_input_binding": {"eval36": {"videos": VIDS}},
        }
        (output / "CONTROL.json").write_text(json.dumps(control))

        (output / "submission.csv").write_bytes(body)
        (output / "raw_statistics.json").write_text("{}")
        (output / "output_bounds.json").write_text("{}")

        childfiles = ["CONTROL.json", "submission.csv", "raw_statistics.json",
                      "output_bounds.json"]
        feats = None
        if mode != "e28_none":
            (output / "FEATURE_RECEIPTS.json").write_text(
                json.dumps([{"dataset": "fake"}]))
            childfiles.append("FEATURE_RECEIPTS.json")
            feats = _binding(output / "FEATURE_RECEIPTS.json",
                             "FEATURE_RECEIPTS.json")

        arts = {}
        for name in childfiles:
            key = str(name)
            arts[key] = _binding(output / key, key)

        r_feature_binding = feats
        if fault == "feature_binding":
            r_feature_binding = {"path": feats["path"],
                                 "bytes": feats["bytes"],
                                 "sha256": "0" * 64}

        result = {
            "status": ("E28_APPEARANCE_NONE_PARITY_PASS_NOT_CANDIDATE"
                       if mode == "e28_none"
                       else "E28_APPEARANCE_COST_V1_GENERATED_UNSCORED"),
            "arm": mode, "run_id": output.name,
            "candidate_id": "E28_APPEARANCE_COST_V1",
            "submission_allowed": False, "gt_read": False,
            "counts": dict(COUNTS),
            "source_bindings": {}, "association_priors": None,
            "csv_binding": _binding(output / "submission.csv", "csv"),
            "control_binding": _binding(output / "CONTROL.json", "CONTROL.json"),
            "artifact_bindings": arts,
            "feature_receipts_binding": r_feature_binding,
        }
        sup = {
            "status": ("E28_APPEARANCE_NONE_SUPERVISED_PASS_NOT_CANDIDATE"
                       if mode == "e28_none"
                       else "E28_APPEARANCE_COST_V1_SUPERVISED_UNSCORED"),
            "arm": mode, "candidate_id": "E28_APPEARANCE_COST_V1",
            "submission_allowed": False, "gt_read": False,
            "counts": dict(COUNTS), "returncode": 0, "reap_error": None,
            "killpg_signals": [], "output": str(output),
            "audit_dir": str(audit),
            "association_priors": None, "source_bindings": {},
            "feature_receipts_binding": feats,
        }

        (audit / "stdout.log").write_bytes(b"")
        (audit / "stderr.log").write_bytes(b"")

        result_path = output / "RESULT.json"
        result_path.write_text(json.dumps(result))
        sup["result_binding"] = _binding(result_path, "RESULT.json")
        sup["log_bindings"] = {
            "stdout.log": _binding(audit / "stdout.log", "stdout.log"),
            "stderr.log": _binding(audit / "stderr.log", "stderr.log"),
        }
        (audit / "SUPERVISOR_RESULT.json").write_text(json.dumps(sup))

        if fault == "drift":
            orig = g.validate_known12_statistics

            def drifting(raw, arm=None, csv_report=None):
                orig(raw, arm=arm, csv_report=csv_report)
                (output / "raw_statistics.json").write_bytes(b"{}\n")

            monkeypatch.setattr(g, "validate_known12_statistics", drifting)

        return output, budget

    return build, calls


def _run(builder, mode, fault=None):
    build, calls = builder
    out, budget = build(mode, fault)
    return m.verify_generation(out, mode, {}, {"synthetic": True}, budget)


@pytest.mark.parametrize("mode", ["e28_none", "e28_appearance"])
def test_happy_paths(builder, mode):
    report = _run(builder, mode)
    assert report["output"] == str(g.ROOT / "outputs" / "local" / "run")
    assert report["csv_report"] == COUNTS
    assert report["shapes"] == {s: [100, 2, 4, 4] for s in STEMS}
    _, calls = builder
    assert calls["receipts"] == (0 if mode == "e28_none" else 1)
    assert calls["plan"] >= 1
    assert calls["closure"] == 2
    assert calls["csv"] == calls["bounds"] == calls["raw"] == 1
    assert calls["budget"] > 0


def test_none_arm_csv_must_match_reference(builder):
    with pytest.raises(ValueError, match="CSV must match"):
        _run(builder, "e28_none", "csv")


def test_candidate_feature_binding_mismatch(builder):
    with pytest.raises(ValueError, match="result feature_receipts_binding mismatch"):
        _run(builder, "e28_appearance", "feature_binding")


def test_control_plan_mismatch(builder):
    with pytest.raises(ValueError, match="control appearance_plan mismatch"):
        _run(builder, "e28_appearance", "plan")


def test_artifact_drift_after_validation(builder):
    with pytest.raises(ValueError, match="artifact hash drift after validation"):
        _run(builder, "e28_appearance", "drift")


def test_budget_must_be_callable_before_data_operations(builder):
    build, calls = builder
    out, _ = build("e28_appearance")
    before = calls.copy()
    with pytest.raises(ValueError, match="check_budget must be callable"):
        m.verify_generation(out, "e28_appearance", {}, {"synthetic": True}, None)
    assert calls == before


# ---- appended: issue #10 e28_score.score_eval12_core API-boundary tests -----

@pytest.fixture
def prepare_core(tmp_path, monkeypatch):
    options = {"delta": 0.01, "bad_summary": False}
    calls, preflights = [], []
    base_csv = str(tmp_path / "baseline.csv")
    cand_csv = str(tmp_path / "candidate.csv")
    base_out = str(tmp_path / "baseline_run")
    cand_out = str(tmp_path / "candidate_run")
    src = {"test": "source"}

    def control(arm, prior, output):
        return {"schema": "E28_GENERATION_CONTROL_V1",
                "config": {}, "dependency_binding": {}, "generation_input_binding": {},
                "metadata_bindings": {}, "reader_bindings": {}, "source_bindings": dict(src),
                "arm": arm, "association_priors": prior, "output": output,
                "candidate_id": "E28_APPEARANCE_COST_V1",
                "appearance_plan": {"synthetic": True}}

    def record(csv, ctrl):
        rows = [{"dataset": s, "nodes": 1, "edges": 1, "forks": 0} for s in m.g.STEMS]
        return {"control": ctrl, "result": {"csv_binding": {"path": csv}},
                "csv_report": {"per_dataset": rows}}

    appearance_plan = {"synthetic": True}
    plan = {"plan": {"candidate_id": "E28_APPEARANCE_COST_V1",
                     "generation_sources": dict(src),
                     "appearance_plan": appearance_plan,
                     "baseline_output": base_out, "candidate_output": cand_out},
            "baseline": None, "gt_inputs": {}}
    plan["baseline"] = record(base_csv, control("e28_none", None, base_out))
    candidate = record(cand_csv, control("e28_appearance", None, cand_out))

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
def test_score_eval12_core_delta(prepare_core, delta, expect_status):
    prepare_core["options"]["delta"] = delta
    result = m.score_eval12_core(prepare_core["plan"], prepare_core["candidate"],
                                 prepare_core["out"], lambda: {})
    assert prepare_core["calls"] == [prepare_core["base_csv"], prepare_core["cand_csv"]]
    assert prepare_core["preflights"] == ["eval12", "eval12"]
    gate = result["paired"]["gate"]
    assert gate["status"] == expect_status
    assert gate["candidate_id"] == "E28_APPEARANCE_COST_V1"
    assert gate["rule_implementation_candidate_id"] == e.CANDIDATE_ID
    assert gate["paired_statistics"]["mean"] == pytest.approx(delta)
    assert result["submission_authorized"] is False
    assert not (prepare_core["out"] / "SCORE_RESULT.json").exists()
    for arm in ("baseline", "candidate"):
        doc = json.loads((prepare_core["out"] / (arm + ".json")).read_text())
        assert doc["arm"] == arm
        assert doc["candidate_id"] == "E28_APPEARANCE_COST_V1"
        assert len(doc["official"]["rows"]) == 12


def test_control_config_mismatch_stops_before_scoring(prepare_core):
    original_config = prepare_core["candidate"]["control"]["config"]
    changed_config = {"changed": True}
    try:
        prepare_core["candidate"]["control"]["config"] = changed_config
        plan_snapshot = copy.deepcopy(prepare_core["plan"])
        candidate_snapshot = copy.deepcopy(prepare_core["candidate"])
        with pytest.raises(ValueError, match="CONTROL binding mismatch"):
            m.score_eval12_core(prepare_core["plan"], prepare_core["candidate"],
                                prepare_core["out"], lambda: {})
        assert prepare_core["plan"] == plan_snapshot
        assert prepare_core["candidate"] == candidate_snapshot
        assert prepare_core["calls"] == []
        assert prepare_core["preflights"] == []
    finally:
        prepare_core["candidate"]["control"]["config"] = original_config


def test_bad_summary_raises_no_final(prepare_core):
    prepare_core["options"]["bad_summary"] = True
    with pytest.raises(ValueError, match="official summary drift"):
        m.score_eval12_core(prepare_core["plan"], prepare_core["candidate"],
                            prepare_core["out"], lambda: {})
    assert not (prepare_core["out"] / "SCORE_RESULT.json").exists()


# ---- appended: issue #10 shared post-verifier route/binding tests -----

def _e27ize(box):
    plan = copy.deepcopy(box["plan"])
    candidate = copy.deepcopy(box["candidate"])
    plan["plan"].pop("appearance_plan", None)
    plan["plan"]["candidate_id"] = "E27_RECORDED_PRIOR_V1"
    plan["plan"]["baseline_prior"] = {"mode": "selected_only"}
    plan["plan"]["candidate_prior"] = {"mode": "recorded_prior"}
    plan["baseline"]["control"].update(
        {"arm": "selected_only", "association_priors": {"mode": "selected_only"},
         "candidate_id": "E27_RECORDED_PRIOR_V1",
         "schema": "E27_BASELINE_CONTROL_V1"})
    plan["baseline"]["control"].pop("appearance_plan", None)
    candidate["control"].update(
        {"arm": "recorded_prior", "association_priors": {"mode": "recorded_prior"},
         "candidate_id": "E27_RECORDED_PRIOR_V1",
         "schema": "E27_BASELINE_CONTROL_V1"})
    candidate["control"].pop("appearance_plan", None)
    return plan, candidate


@pytest.mark.parametrize("route,fault",
                         [("e27_default", None), ("e27_explicit", None),
                          ("e28", None), ("e28", "artifact"), ("e28", "plan")])
def test_verify_score_core_routes(prepare_core, monkeypatch, route, fault):
    from pathlib import Path

    import scripts.experiments.e27.e27_prior_score_v2 as shared
    e28 = route == "e28"
    if not e28:
        checked, cand = _e27ize(prepare_core)
    else:
        checked = copy.deepcopy(prepare_core["plan"])
        cand = copy.deepcopy(prepare_core["candidate"])
    checked["gt_inputs"] = prepare_core["plan"]["gt_inputs"]
    core = (m if e28 else shared).score_eval12_core(
        checked, cand, prepare_core["out"], lambda: {})
    calls = {"plan": 0, "gen": 0}

    def bad(*a, **k):
        raise AssertionError("wrong route validator called")

    def vp(path, sha, check_budget=None):
        calls["plan"] += 1
        assert path == prepare_core["out"] / "PLAN.json"
        assert sha == "test-sha"
        assert check_budget is budget
        return copy.deepcopy(checked)

    def vplan(path, sha):
        calls["plan"] += 1
        assert path == prepare_core["out"] / "PLAN.json"
        assert sha == "test-sha"
        return copy.deepcopy(checked)

    def gen(path, kind, sources, payload, budget_arg=None):
        calls["gen"] += 1
        assert path == Path(expected_out)
        assert kind == ("e28_appearance" if e28 else "recorded_prior")
        assert sources == expected_sources
        assert payload == expected_payload
        assert budget_arg is (budget if e28 else None)
        return copy.deepcopy(cand)

    def vgen(path, kind, sources, payload):
        return gen(path, kind, sources, payload, None)

    expected_out = checked["plan"]["candidate_output"]
    expected_sources = checked["plan"]["generation_sources"]
    expected_payload = (checked["plan"]["appearance_plan"] if e28
                        else checked["plan"]["candidate_prior"])

    def budget():
        return {}

    monkeypatch.setattr(m, "verify_plan", vp if e28 else bad)
    monkeypatch.setattr(m, "verify_generation", gen if e28 else bad)
    monkeypatch.setattr(shared, "verify_plan", bad if e28 else vplan)
    monkeypatch.setattr(shared, "verify_generation", bad if e28 else vgen)
    monkeypatch.setattr(evaluate, "score_submission", bad)
    monkeypatch.setattr(e, "_check_stage_gt", bad)
    before_files = {
        p.name: p.read_bytes() for p in sorted(Path(prepare_core["out"]).iterdir())
    }
    inputs = copy.deepcopy([checked, cand, core])
    if fault == "artifact":
        artifact = Path(prepare_core["out"]) / "candidate.json"
        artifact.write_bytes(artifact.read_bytes() + b"\n")
    if fault == "plan":
        fresh = copy.deepcopy(checked)
        fresh["baseline"]["control"]["metadata_bindings"] = {"drift": True}
        monkeypatch.setattr(
            m if e28 else shared, "verify_plan",
            lambda *a, **k: (calls.update(plan=calls["plan"] + 1), fresh)[1])
    kwargs = {} if route == "e27_default" else {
        "experiment": "e27" if route == "e27_explicit" else "e28"}
    if fault:
        with pytest.raises(
                ValueError,
                match=("candidate artifact binding changed" if fault == "artifact"
                       else "plan drifted since scoring")):
            shared.verify_score_core(
                prepare_core["out"] / "PLAN.json", "test-sha",
                checked, cand, prepare_core["out"], core, budget, **kwargs)
        assert not (Path(prepare_core["out"]) / "SCORE_RESULT.json").exists()
        return
    result = shared.verify_score_core(
        prepare_core["out"] / "PLAN.json", "test-sha",
        checked, cand, prepare_core["out"], core, budget, **kwargs)
    assert result["verified"] is True
    assert result["candidate_id"] == (
        "E28_APPEARANCE_COST_V1" if e28 else "E27_RECORDED_PRIOR_V1")
    assert result["paired"] == core["paired"]
    assert result["submission_authorized"] is False
    assert calls == {"plan": 2, "gen": 2}
    assert [checked, cand, core] == inputs
    assert {
        p.name: p.read_bytes() for p in sorted(Path(prepare_core["out"]).iterdir())
    } == before_files
    assert prepare_core["calls"] == [prepare_core["base_csv"], prepare_core["cand_csv"]]


@pytest.mark.parametrize("bad", ["bad", True, None])
def test_verify_score_core_rejects_experiment(bad):
    from scripts.experiments.e27 import e27_prior_score_v2 as shared

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid experiment rejected before callback")

    with pytest.raises(ValueError, match="unsupported experiment"):
        shared.verify_score_core(
            None, None, None, None, None, None, forbidden, experiment=bad)


PLAN_SHA = "a" * 64
PREGEN_SHA = "b" * 64


def _shared():
    from scripts.experiments.e27 import e27_prior_score_v2 as shared

    return shared


@pytest.mark.parametrize("command", ["score-child", "score"])
def test_synthetic_routing(command, tmp_path, capsys, monkeypatch):
    shared = _shared()
    calls = []

    def selected(plan, plan_sha, pregen_sha, output, *, experiment):
        calls.append((plan, plan_sha, pregen_sha, output, experiment))
        return {"status": "SYNTHETIC_ONLY"}

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden route")

    if command == "score-child":
        monkeypatch.setattr(shared, "run_score_child", selected)
        monkeypatch.setattr(shared, "supervise_score", forbidden)
    else:
        monkeypatch.setattr(shared, "run_score_child", forbidden)
        monkeypatch.setattr(shared, "supervise_score", selected)

    argv = [
        command,
        "--plan",
        str(tmp_path / "PLAN.json"),
        "--plan-sha",
        PLAN_SHA,
        "--pregen-sha",
        PREGEN_SHA,
        "--output",
        str(tmp_path / "out"),
    ]

    assert m.main(argv) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {"status": "SYNTHETIC_ONLY", "submission_authorized": False}

    assert len(calls) == 1
    plan, plan_sha, pregen_sha, output, experiment = calls[0]
    assert plan == tmp_path / "PLAN.json"
    assert plan_sha == PLAN_SHA
    assert pregen_sha == PREGEN_SHA
    assert output == tmp_path / "out"
    assert experiment == "e28"

    assert list(tmp_path.iterdir()) == []


def test_error_path_does_not_leak_message(tmp_path, capsys, monkeypatch):
    shared = _shared()

    def raiser(*args, **kwargs):
        raise RuntimeError("do not disclose this text")

    monkeypatch.setattr(shared, "run_score_child", raiser)

    argv = [
        "score-child",
        "--plan",
        str(tmp_path / "PLAN.json"),
        "--plan-sha",
        PLAN_SHA,
        "--pregen-sha",
        PREGEN_SHA,
        "--output",
        str(tmp_path / "out"),
    ]

    assert m.main(argv) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload == {
        "error_type": "RuntimeError",
        "status": "ERROR",
        "submission_authorized": False,
    }
    assert "do not disclose this text" not in captured.err
    assert "do not disclose this text" not in captured.out


def test_generate_rejected_before_dispatch(tmp_path, capsys, monkeypatch):
    shared = _shared()

    def forbidden(*args, **kwargs):
        pytest.fail("dispatched despite invalid command")

    monkeypatch.setattr(shared, "run_score_child", forbidden)
    monkeypatch.setattr(shared, "supervise_score", forbidden)

    argv = [
        "generate",
        "--plan",
        str(tmp_path / "PLAN.json"),
        "--plan-sha",
        PLAN_SHA,
        "--pregen-sha",
        PREGEN_SHA,
        "--output",
        str(tmp_path / "out"),
    ]

    with pytest.raises(SystemExit) as excinfo:
        m.main(argv)

    assert excinfo.value.code == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "generate" in captured.err
    assert list(tmp_path.iterdir()) == []
