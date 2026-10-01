"""Tests for scripts.experiments.e27.e27_prior_score.read_generation_receipts (issue 9)."""

import copy
import json

import pytest

from scripts.experiments.e27 import e27_prior_score as m


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    monkeypatch.setattr(m.g, "ROOT", root)
    out = root / "outputs" / "local" / "run"
    audit = out.with_name(out.name + "_supervisor")
    out.mkdir(parents=True)
    audit.mkdir(parents=True)
    (out / "CONTROL.json").write_text(json.dumps({}), encoding="utf-8")
    (out / "RESULT.json").write_text(
        json.dumps({"control_binding": m.g._binding_for_path(out / "CONTROL.json", label="control")}),
        encoding="utf-8",
    )
    (audit / "stdout.log").write_bytes(b"")
    (audit / "stderr.log").write_bytes(b"")
    (audit / "SUPERVISOR_RESULT.json").write_text(
        json.dumps(
            {
                "result_binding": m.g._binding_for_path(out / "RESULT.json", label="result"),
                "log_bindings": {
                    name: m.g._binding_for_path(audit / name, label=name)
                    for name in ("stdout.log", "stderr.log")
                },
            }
        ),
        encoding="utf-8",
    )
    return out, audit


def test_success(run_dir):
    out, _audit = run_dir
    docs = m.read_generation_receipts(out)
    assert docs["control"] == {}
    assert docs["supervisor"]["result_binding"] == docs["bindings"]["result"]
    assert docs["result"]["control_binding"] == docs["bindings"]["control"]


@pytest.mark.parametrize("relative", ["CONTROL.json", "RESULT.json", "stdout.log", "stderr.log"])
def test_tamper(run_dir, relative):
    out, audit = run_dir
    path = out / relative if relative.endswith(".json") else audit / relative
    with path.open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(RuntimeError):
        m.read_generation_receipts(out)


@pytest.mark.parametrize("rootkind", ["out", "audit"])
@pytest.mark.parametrize("name", ["ERROR.json", "RESULT.failed.json", "nested/X.failed.json"])
def test_failure(run_dir, rootkind, name):
    out, audit = run_dir
    root = out if rootkind == "out" else audit
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError):
        m.read_generation_receipts(out)


def test_wrong_log_keys(run_dir):
    out, audit = run_dir
    parent = audit / "SUPERVISOR_RESULT.json"
    doc = json.loads(parent.read_text(encoding="utf-8"))
    del doc["log_bindings"]["stderr.log"]
    parent.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeError):
        m.read_generation_receipts(out)


@pytest.fixture
def accepted_run():
    out = m.g.ROOT / "outputs/local/e27_selected_only_parity_20260913_v1"
    result_json = out / "RESULT.json"
    if not result_json.exists():
        pytest.skip("accepted run artifacts absent")
    expected = {
        result_json: "4de09bcccda68a31adb864b2d5305f6eb76aa11386b4f580c42128ec021504e6",
        out / "CONTROL.json": "ab9a90e99e0159c90a2ee4810d44e018b89b07ca022192b365227a1a002ef535",
        out.with_name(out.name + "_supervisor") / "SUPERVISOR_RESULT.json":
            "67d6c12e88e8bf937d5df8a73c02d7cc326d22512efdb326fb7340e78427eb95",
    }
    for path, sha in expected.items():
        assert m.g._binding_for_path(path, label="test")["sha256"] == sha
    return out, m.read_generation_receipts(out)


def test_positive_parity(accepted_run):
    out, docs = accepted_run
    c = docs["control"]
    result = m.verify_generation(out, "selected_only", c["source_bindings"], c["association_priors"])
    report = result["csv_report"]
    assert report["datasets"] == list(m.g.STEMS)
    assert report["total_nodes"] == 250465
    assert report["total_edges"] == 240852
    assert report["total_rows"] == 491317
    assert len(result["shapes"]) == 12
    assert result["result"]["csv_binding"]["sha256"] == m.g._REFERENCE_SHA256


@pytest.mark.parametrize("tamper", ["source", "sha", "novel", "boolcount"])
def test_negative_tamper(accepted_run, tamper):
    out, docs = accepted_run
    c = docs["control"]
    sources = copy.deepcopy(c["source_bindings"])
    priors = copy.deepcopy(c["association_priors"])
    stem = m.g.STEMS[0]
    if tamper == "source":
        sources = {"files": {}, "count": 0}
    elif tamper == "sha":
        priors["sha256"] = "0" * 64
    elif tamper == "novel":
        priors["eligible_unselected_by_dataset"][stem] = 1
    else:
        priors["entries_by_dataset"][stem] = True
    with pytest.raises((ValueError, RuntimeError)):
        m.verify_generation(out, "selected_only", sources, priors)


def test_plan_preflight_known12_without_semantic_gt(monkeypatch):
    from biohub import e26_screen as e
    from biohub import io
    path = m.g.ROOT / "outputs/local/e27_scoring_preflight_20260913_v1/PLAN.json"
    if not path.exists():
        pytest.skip("preflight PLAN absent")
    orig = e.verify_inventory
    seen = []
    def track(binding):
        seen.append(binding["selected_path"])
        return orig(binding)
    monkeypatch.setattr(e, "verify_inventory", track)
    def forbidden(*args, **kwargs):
        raise AssertionError("semantic GT read forbidden")
    monkeypatch.setattr(io, "estimated_number_of_nodes", forbidden)
    monkeypatch.setattr(io, "load_geff_graph", forbidden)
    plan = json.loads(path.read_text())
    expected = plan["score_sources"]["scripts/e27_prior_score.py"]
    current = m.g._binding_for_path(m.g.ROOT / "scripts/experiments/e27/e27_prior_score.py", label="score")
    if current != expected:
        with pytest.raises(RuntimeError, match="score source drift"):
            m.verify_plan(
                path, "a914f4c4f583aa3f2252afe9076aa2f4b3fd4b0fca91fd2bb4e6f5112a384691",
                before_generation=True,
            )
        assert seen == []
        return
    r = m.verify_plan(path, "a914f4c4f583aa3f2252afe9076aa2f4b3fd4b0fca91fd2bb4e6f5112a384691", before_generation=True)
    assert r["plan_binding"]["sha256"] == "a914f4c4f583aa3f2252afe9076aa2f4b3fd4b0fca91fd2bb4e6f5112a384691"
    assert [row["dataset"] for row in r["gt_inputs"]["private"]["videos"]] == list(m.g.STEMS)
    gt_seen = {p for p in seen if p.endswith(".geff") and "/data/train/" in p}
    assert gt_seen == {str(m.g.ROOT / "data/train" / (s + ".geff")) for s in m.g.STEMS}
    assert r["plan"]["submission_allowed"] is False


def test_plan_wrong_digest_rejected():
    path = m.g.ROOT / "outputs/local/e27_scoring_preflight_20260913_v1/PLAN.json"
    if not path.exists():
        pytest.skip("preflight PLAN absent")
    with pytest.raises(RuntimeError, match="sha256"):
        m.verify_plan(path, "0" * 64, before_generation=True)


def test_verify_generation_shapes_are_json_lists(accepted_run):
    """Issue9: verify_generation must return JSON-serializable `shapes`.

    The run_registered_generation guard calls e._json_bytes(checked) after the
    second plan verify. `shapes` leaves were tuples, which strict JSON rejects.
    This pins the boundary normalization only: no dimension/scoring/threshold
    or input math changes.
    """
    from biohub import e26_screen as e

    out, docs = accepted_run

    result = m.verify_generation(
        out,
        "selected_only",
        docs["control"]["source_bindings"],
        docs["control"]["association_priors"],
    )

    videos = docs["control"]["generation_input_binding"]["eval36"]["videos"]
    expected_shapes = {
        g["dataset"]: g["metadata"]["shape_tzyx"]
        for g in videos
        if g["dataset"] in m.g.STEMS
    }

    assert set(result["shapes"]) == set(expected_shapes)
    for stem, shape in result["shapes"].items():
        assert type(shape) is list
        assert shape == list(expected_shapes[stem])

    encoded = e._json_bytes(result)
    assert json.loads(encoded) == result
