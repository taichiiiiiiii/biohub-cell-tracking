"""Synthetic-fixture tests for e28_score.verify_plan (Issue #10).

These tests stub the *legacy hash identity* only (the two fixed PREREGISTRATION.json /
GT_BINDING.json sha constants) so a tmp_path fixture can reach the real guards. This is
NOT proof of the production anchor values, and it never weakens g._binding_for_path for
any other path. No real run artifacts, GT data, model, or network access is used.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from biohub import e26_screen as e
from scripts.experiments.e28 import e28_score as m

g = m.g

LEGACY_REL = "outputs/local/e26_screen_preregistrations/e26_motion_off_screen_v2_20260908073709Z"
FIXED_SHA = {
    "PREREGISTRATION.json": "5abd92bd3ccd6533769a66e71e44f61b4b0a7b88d5d8228c0dbd195a43d1aa02",
    "GT_BINDING.json": "f2842591cfa6750a443aae0d6d2ffd44616b1c0d7ad3bb93cb0f6a83a662b3b1",
}


def _fixture(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    monkeypatch.setattr(g, "ROOT", root)
    monkeypatch.setattr(g, "STEMS", ("synthA", "synthB"))
    monkeypatch.setattr(g, "COLLECTION_ROOT", root / "collection")

    plan_path = root / "outputs" / "local" / "plan" / "PLAN.json"
    baseline_output = root / "outputs" / "local" / "baseline"
    candidate_output = root / "outputs" / "local" / "candidate"

    def binding(path, label=None):
        return g._binding_for_path(path, label=label)

    real_binding = g._binding_for_path
    legacy_paths = {(root / LEGACY_REL / "PREREGISTRATION.json").resolve(): "PREREGISTRATION.json",
                    (root / LEGACY_REL / "GT_BINDING.json").resolve(): "GT_BINDING.json"}

    def patched(path, label=None):
        rp = Path(path).resolve()
        name = legacy_paths.get(rp)
        if name is None:
            return real_binding(path, label=label)
        ref = dict(real_binding(path, label=label))
        ref["sha256"] = FIXED_SHA[name]
        return ref

    monkeypatch.setattr(g, "_binding_for_path", patched)

    sources = [root / "scripts" / "experiments" / "e28" / "e28_score.py",
               root / "scripts" / "experiments" / "e27" / "e27_prior_score_v2.py",
               root / "scripts" / "experiments" / "e27" / "e27_score_environment_v2.py",
               root / "analysis" / "e28_appearance_cost_design.md",
               root / ".venv" / "lib" / "python3.12" / "site-packages" / "threadpoolctl.py",
               root / ".venv" / "lib" / "python3.12" / "site-packages" / "polars" / "__init__.py",
               root / ".venv" / "lib" / "python3.12" / "site-packages" / "blosc2" / "__init__.py",
               root / ".venv" / "lib" / "python3.12" / "site-packages" / "blosc2" / "lib" / "libtcc.dylib",
               root / "src" / "fake.py",
               root / "official" / "src" / "tracking_cellmot" / "fake.py"]
    for s in sources:
        s.parent.mkdir(parents=True, exist_ok=True)
        s.write_text("synthetic\n")
    expected_rels = {str(s.relative_to(root)) for s in sources}
    score_sources = {r: binding(root / r, label=r) for r in sorted(expected_rels)}

    def fake_closure():
        return [root / "src" / "fake.py"]

    monkeypatch.setattr(g, "_source_closure_paths", fake_closure)
    monkeypatch.setattr(g, "_verify_source_closure",
                        lambda gs: (_ for _ in ()).throw(RuntimeError("generation_sources"))
                        if gs != {"synthetic": True} else None)
    monkeypatch.setattr(e, "_git_identity", lambda: {"commit": "synthetic"})

    gib = {"checkpoint": {"selected_path": str(root / "artifacts" / "checkpoint")},
           "manifest": {"selected_path": str(root / "artifacts" / "manifest")},
           "eval36": {"raw_inventory": {"selected_path": str(root / "artifacts" / "raw")},
                      "videos": [{"dataset": s,
                                  "image_inventory": {"selected_path": str(root / "data" / "train" / (s + ".zarr"))},
                                  "metadata": {"shape_tzyx": [100, 2, 4, 4]}} for s in g.STEMS]}}
    private = {"videos": [{"dataset": s,
                           "gt_inventory": {"selected_path": str(root / "data" / "train" / (s + ".geff"))},
                           "image_metadata": {"shape_tzyx": [100, 2, 4, 4]}} for s in g.STEMS]
                       + [{"dataset": "sealed_extra",
                           "gt_inventory": {"selected_path": "DO_NOT_TOUCH"}}]}
    public = {"generation_input_binding": gib, "dependency_binding": {}}
    baseline = {"bindings": {"synthetic": "baseline"},
                "control": {"generation_input_binding": gib, "dependency_binding": {},
                            "metadata_bindings": {}, "reader_bindings": {}}}

    def fake_verify_generation(path, source_id, gen_sources, ap, cb):
        assert Path(path) == baseline_path
        assert source_id == "e28_none"
        assert gen_sources == {"synthetic": True}
        assert isinstance(cb, object) and callable(cb)
        cb()
        return copy.deepcopy(baseline)

    baseline_path = baseline_output
    monkeypatch.setattr(m, "verify_generation", fake_verify_generation)
    monkeypatch.setattr(g, "prepare_appearance_plan", lambda: {"synthetic": True})

    inventory = []

    def fake_dep(db):
        assert db == {}

    def fake_inv(rec):
        inventory.append(rec["selected_path"])
        if rec["selected_path"] == "DO_NOT_TOUCH":
            raise RuntimeError("refusing sealed extra")

    monkeypatch.setattr(e, "verify_dependency_binding", fake_dep)
    monkeypatch.setattr(e, "verify_inventory", fake_inv)
    monkeypatch.setattr(e, "bind_image_metadata",
                        lambda rec: {"shape_tzyx": [100, 2, 4, 4]})

    lp = root / LEGACY_REL
    lp.mkdir(parents=True, exist_ok=True)
    (lp / "PREREGISTRATION.json").write_text(json.dumps(public))
    (lp / "GT_BINDING.json").write_text(json.dumps(private))

    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan = {"schema": "E28_EVAL12_PLAN_V1",
            "candidate_id": "E28_APPEARANCE_COST_V1",
            "datasets": list(g.STEMS),
            "baseline_output": str(baseline_output),
            "candidate_output": str(candidate_output),
            "baseline_bindings": baseline["bindings"],
            "generation_sources": {"synthetic": True},
            "appearance_plan": {"synthetic": True},
            "score_sources": score_sources,
            "legacy_public": binding(lp / "PREREGISTRATION.json", label="PREREGISTRATION.json"),
            "legacy_private": binding(lp / "GT_BINDING.json", label="GT_BINDING.json"),
            "submission_allowed": False}
    plan_path.write_text(json.dumps(plan))
    sha = binding(plan_path, label="plan")["sha256"]

    calls = []

    def budget():
        calls.append(1)

    return {"path": plan_path, "sha": sha, "plan": plan, "baseline": baseline,
            "inventory": inventory, "budget": budget, "calls": calls, "root": root}


def test_happy_path(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    result = m.verify_plan(fx["path"], fx["sha"], before_generation=True, check_budget=fx["budget"])
    assert result["baseline"] == fx["baseline"]
    assert result["plan_binding"] == g._binding_for_path(fx["path"], label="plan")
    assert [v["dataset"] for v in result["gt_inputs"]["private"]["videos"]] == list(g.STEMS)
    r = fx["root"]
    assert fx["inventory"] == [str(r / "artifacts" / "checkpoint"), str(r / "artifacts" / "manifest"),
                              str(r / "artifacts" / "raw")] + \
        [str(r / "data" / "train" / (s + ext)) for s in g.STEMS for ext in (".geff", ".zarr")]
    assert not any("DO_NOT_TOUCH" in p for p in fx["inventory"])
    assert fx["path"].read_text() == json.dumps(fx["plan"])
    assert fx["calls"]


@pytest.mark.parametrize("mutate,match", [
    ("candidate", "plan schema/candidate mismatch"),
    ("appearance", "appearance_plan mismatch"),
    ("missing_source", "score_sources keyset mismatch"),
    ("baseline_bindings", "baseline bindings mismatch"),
    ("same_output", "candidate_output path invalid"),
])
def test_plan_mutations_rejected(tmp_path, monkeypatch, mutate, match):
    fx = _fixture(tmp_path, monkeypatch)
    plan = json.loads(json.dumps(fx["plan"]))
    if mutate == "candidate":
        plan["candidate_id"] = "OTHER"
    elif mutate == "appearance":
        plan["appearance_plan"] = {"synthetic": False}
    elif mutate == "missing_source":
        plan["score_sources"].pop(sorted(plan["score_sources"])[0])
    elif mutate == "baseline_bindings":
        plan["baseline_bindings"] = {"synthetic": "tampered"}
    else:
        plan["candidate_output"] = plan["baseline_output"]
    fx["path"].write_text(json.dumps(plan))
    sha = hashlib.sha256(fx["path"].read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match=match):
        m.verify_plan(fx["path"], sha, before_generation=True, check_budget=fx["budget"])
    assert fx["inventory"] == []


def test_wrong_digest_rejects_before_inventory(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="plan sha256 mismatch"):
        m.verify_plan(fx["path"], "0" * 64, before_generation=True, check_budget=fx["budget"])
    assert fx["inventory"] == []


def test_existing_candidate_rejects_before_inventory(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    Path(fx["plan"]["candidate_output"]).mkdir(parents=True)
    with pytest.raises(RuntimeError, match="candidate output already exists"):
        m.verify_plan(fx["path"], fx["sha"], before_generation=True, check_budget=fx["budget"])
    assert fx["inventory"] == []


def test_plan_changing_during_verification_is_caught(tmp_path, monkeypatch):
    fx = _fixture(tmp_path, monkeypatch)
    original = e.verify_inventory
    state = {"done": False}

    def wrapper(rec):
        original(rec)
        if not state["done"]:
            state["done"] = True
            with open(fx["path"], "a") as fh:
                fh.write("\n")

    monkeypatch.setattr(e, "verify_inventory", wrapper)
    with pytest.raises(RuntimeError, match="plan binding changed during verification"):
        m.verify_plan(fx["path"], fx["sha"], before_generation=True, check_budget=fx["budget"])
