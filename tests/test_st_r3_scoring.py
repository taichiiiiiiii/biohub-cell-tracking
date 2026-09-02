from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

import biohub.st_r3_scoring as scoring
from biohub.evaluate import graph_from_rows, score_submission


def _write(path: Path, data: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": path.as_posix(), "bytes": len(data), "sha256": scoring.sha256_bytes(data)}


def _canonical(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(scoring.canonical_json_bytes(value))


def _relative_ref(run: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(run).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": scoring.sha256_file(path),
    }


def _csv_bytes(stems: tuple[str, ...] = scoring.EVAL36) -> bytes:
    lines = [b"id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\n"]
    for index, stem in enumerate(stems):
        lines.append(f"{index},{stem},node,0,0,0,0,0,-1,-1\n".encode())
    return b"".join(lines)


def _partition_records(csv_bytes: bytes) -> dict[str, dict[str, object]]:
    records = {}
    for line in csv_bytes.splitlines(keepends=True)[1:]:
        stem = line.split(b",", 2)[1].decode()
        records[stem] = {"bytes": len(line), "row_count": 1, "sha256": scoring.sha256_bytes(line)}
    return records


def _make_sealed_run(tmp_path: Path, name: str = "run") -> tuple[Path, str]:
    run = tmp_path / name
    run.mkdir()
    prereg = run / "PREREGISTRATION.json"
    _canonical(prereg, {"run_id": "immutable-test-run"})
    generation = run / "generation" / "ARTIFACT_MANIFEST.json"
    _canonical(
        generation,
        {
            "schema_version": "test-generation",
            "state": "GENERATION_SEALED",
            "preregistration_sha256": scoring.sha256_file(prereg),
        },
    )
    execution_refs = {}
    for key in scoring.EXECUTION_KEYS:
        path = run / "generation" / "receipts" / f"{key}.json"
        _canonical(path, {"arm": key})
        execution_refs[key] = _relative_ref(run, path)
    csv_bytes = _csv_bytes()
    csv_probe = run / "csv-probe.csv"
    csv_probe.write_bytes(csv_bytes)
    typed_graph_sha256 = scoring.validate_submission_csv(
        csv_probe, scoring.EVAL36, {stem: (1, 1, 1, 1) for stem in scoring.EVAL36}, full_generation=True
    ).typed_graph_sha256
    csv_probe.unlink()
    submissions = {}
    for arm in ("baseline", "candidate"):
        path = run / "generation" / "canonical" / arm / "submission.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(csv_bytes)
        submissions[arm] = {
            "ref": _relative_ref(run, path),
            "typed_graph_sha256": typed_graph_sha256,
            "partitions": _partition_records(csv_bytes),
        }
    gt = run / "inputs" / "gt"
    records = []
    root_image_meta = {
        "attributes": {
            "ome": {
                "multiscales": [
                    {
                        "datasets": [
                            {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1, 1, 1, 1]}]}
                        ]
                    }
                ]
            }
        }
    }
    for stem in scoring.EVAL36:
        geff_meta = gt / f"{stem}.geff" / "zarr.json"
        array_meta = gt / f"{stem}.zarr" / "0" / "zarr.json"
        scale_meta = gt / f"{stem}.zarr" / "zarr.json"
        _canonical(geff_meta, {"fake": True})
        _canonical(array_meta, {"shape": [1, 1, 1, 1]})
        _canonical(scale_meta, root_image_meta)
        for path in (geff_meta, array_meta, scale_meta):
            records.append(_relative_ref(run, path))
    records.sort(key=lambda item: item["path"])
    gt_inventory = run / "inputs" / "GT_INVENTORY.json"
    _canonical(
        gt_inventory,
        {"schema_version": scoring.GT_INVENTORY_SCHEMA, "stems": list(scoring.EVAL36), "records": records},
    )
    image_view = run / "inputs" / "images"
    image_view.mkdir(parents=True)
    image_inventory = run / "inputs" / "IMAGE_CONTENT_INVENTORY.json"
    _canonical(image_inventory, {"schema_version": "test-image-inventory", "records": []})
    gates = run / "feasibility" / "GATES.json"
    _canonical(gates, {"status": "FEASIBILITY_PASS"})
    repo = Path(scoring.__file__).resolve().parents[2]
    official = repo / "official"
    head = subprocess.run(
        ["git", "-C", str(official), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    superproject_commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    source_hashes = {rel: scoring.sha256_file(official / "src" / rel) for rel in scoring.OFFICIAL_SOURCE_KEYS}
    artifacts = [
        _relative_ref(run, prereg),
        _relative_ref(run, generation),
        _relative_ref(run, gates),
        _relative_ref(run, gt_inventory),
        _relative_ref(run, image_inventory),
        *execution_refs.values(),
        *(submissions[arm]["ref"] for arm in ("baseline", "candidate")),
    ]
    artifacts.sort(key=lambda item: item["path"])
    manifest = {
        "schema_version": scoring.FEASIBILITY_SCHEMA,
        "state": "FEASIBILITY_PASS",
        "run_id": "immutable-test-run",
        "preregistration": _relative_ref(run, prereg),
        "generation_manifest": {
            "ref": _relative_ref(run, generation),
            "preregistration_sha256": scoring.sha256_file(prereg),
        },
        "datasets": {
            "eval12": list(scoring.EVAL12),
            "eval24": list(scoring.EVAL24),
            "eval36": list(scoring.EVAL36),
            "digests": {
                "eval12": scoring.dataset_digest(scoring.EVAL12),
                "eval24": scoring.dataset_digest(scoring.EVAL24),
                "eval36": scoring.dataset_digest(scoring.EVAL36),
            },
        },
        "executions": execution_refs,
        "canonical_submissions": submissions,
        "sealed_hashes": {
            "full_arm_outputs_sha256": "3" * 64,
            "stats_sha256": "4" * 64,
            "plans_sha256": "5" * 64,
            "configs_sha256": "6" * 64,
            "source_inventory_sha256": "7" * 64,
            "live_artifact_inventory_sha256": "8" * 64,
            "image_content_inventory_sha256": scoring.sha256_file(image_inventory),
            "raw_inventory_sha256": "9" * 64,
        },
        "official": {"gitlink": head, "head": head, "clean": True, "source_hashes": source_hashes},
        "source_bindings": {
            "superproject_commit": superproject_commit,
            "tracked_tree_clean": True,
            "evaluate_py_sha256": scoring.sha256_file(repo / "src" / "biohub" / "evaluate.py"),
            "st_r3_scoring_py_sha256": scoring.sha256_file(Path(scoring.__file__)),
        },
        "feasibility": {
            "ref": _relative_ref(run, gates),
            "prerequisites_passed": True,
            "e23_parity": True,
            "base1_non_regression": True,
            "adapter_reviewed": True,
            "training_gate_not_applicable": True,
            "source_clean": True,
            "official_clean": True,
            "generation_sealed": True,
            "gt_nonvisibility": True,
            "deepcenter_bound": True,
            "data_ready": True,
            "image_ready": True,
            "deterministic_replay": True,
            "dry_run_identity": True,
            "conservation": True,
            "local_runtime": True,
            "local_rss": True,
            "target_runtime": True,
            "target_memory": True,
            "hidden_200": True,
        },
        "scoring_inputs": {
            "gt_view": "inputs/gt",
            "gt_inventory": _relative_ref(run, gt_inventory),
            "image_view": "inputs/images",
            "image_content_inventory": _relative_ref(run, image_inventory),
        },
        "artifacts": artifacts,
    }
    path = run / "feasibility" / "FEASIBILITY_PASS.json"
    _canonical(path, manifest)
    return run, scoring.sha256_file(path)


def _fake_scored(arm: str, stem: str) -> dict[str, object]:
    from tracking_cellmot.metrics import EvaluationResult, per_sample_metrics, summarise

    er = EvaluationResult(
        edge_tp=100,
        edge_fp=0,
        edge_fn=0,
        division_tp=1 if arm == "candidate" else 0,
        division_fp=0,
        division_fn=0 if arm == "candidate" else 1,
        num_pred_nodes=10,
    )
    row = {"dataset": stem, **per_sample_metrics(er, 10, 1.0)}
    summary = scoring._normalise_summary(
        summarise([{key: value for key, value in row.items() if key != "dataset"}]), "fake"
    )
    return {"per_sample": row, "singleton_summary": summary}


def _patch_fake_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scoring, "_validate_current_source", lambda *_args: None)
    monkeypatch.setattr(scoring, "_verify_unlocked_gt", lambda _sealed, stems: {stem: {} for stem in stems})
    monkeypatch.setattr(scoring, "_score_one", lambda _path, _sealed, stem, arm: _fake_scored(arm, stem))


def test_csv_full_and_exact_subsequence_contract(tmp_path: Path) -> None:
    path = tmp_path / "full.csv"
    path.write_bytes(_csv_bytes(scoring.EVAL12))
    bounds = {stem: (1, 1, 1, 1) for stem in scoring.EVAL12}
    full = scoring.validate_submission_csv(path, scoring.EVAL12, bounds, full_generation=True)
    subset = tmp_path / "subset.csv"
    subset.write_bytes(scoring.subset_bytes(full, scoring.EVAL12[3:5]))
    parsed = scoring.validate_submission_csv(
        subset, scoring.EVAL12[3:5], {stem: bounds[stem] for stem in scoring.EVAL12[3:5]}, full_generation=False
    )
    assert list(parsed.partitions) == list(scoring.EVAL12[3:5])
    assert subset.read_bytes().splitlines()[1].startswith(b"3,")
    renumbered = subset.read_bytes().replace(b"3,44b6_341df25f", b"0,44b6_341df25f")
    assert renumbered != scoring.subset_bytes(full, scoring.EVAL12[3:5])


@pytest.mark.parametrize(
    "body,code",
    [
        (b"0,a,node,00,0,0,0,0,-1,-1\n", "MALFORMED_CSV"),
        (b"0,a,node,0,0,0,0,0,-1,-1\n1,a,node,0,0,0,0,0,-1,-1\n", "NODE_ORDER"),
        (b"0,a,node,0,0,0,0,0,-1,-1\n1,a,edge,-1,-1,-1,-1,-1,0,2\n", "DANGLING_EDGE"),
        (
            b"0,a,node,0,0,0,0,0,-1,-1\n1,a,node,1,0,0,0,0,-1,-1\n2,a,edge,-1,-1,-1,-1,-1,0,1\n",
            "NONCONSECUTIVE_EDGE",
        ),
    ],
)
def test_csv_adversarial_graph_and_lexemes(tmp_path: Path, body: bytes, code: str) -> None:
    path = tmp_path / "bad.csv"
    path.write_bytes(b"id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\n" + body)
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring.validate_submission_csv(path, ("a",), {"a": (2, 2, 2, 2)}, full_generation=True)
    assert caught.value.code == code


def _write_metric_gt(data_dir: Path, name: str, nodes: list[tuple], edges: list[tuple[int, int]]) -> None:
    import zarr
    from geff import GeffMetadata

    graph = graph_from_rows(
        pl.DataFrame(nodes, schema=["node_id", "t", "z", "y", "x"], orient="row"),
        pl.DataFrame(edges, schema=["source_id", "target_id"], orient="row"),
    )
    path = data_dir / f"{name}.geff"
    graph.to_geff(path)
    metadata = GeffMetadata.read(path)
    metadata.extra["estimated_number_of_nodes"] = len(nodes)
    metadata.write(path)
    group = zarr.open_group(data_dir / f"{name}.zarr", mode="w", zarr_format=3)
    group.attrs["ome"] = {
        "multiscales": [
            {"datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1, 1, 1, 1]}]}]}
        ]
    }


def _write_metric_csv(path: Path, name: str, nodes: list[tuple], edges: list[tuple[int, int]]) -> None:
    lines = ["id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\n"]
    index = 0
    for node_id, t, z, y, x in nodes:
        lines.append(f"{index},{name},node,{node_id},{t},{int(z)},{int(y)},{int(x)},-1,-1\n")
        index += 1
    for source, target in edges:
        lines.append(f"{index},{name},edge,-1,-1,-1,-1,-1,{source},{target}\n")
        index += 1
    path.write_text("".join(lines))


def test_actual_official_twin_positive_and_valid_donor_cut(tmp_path: Path) -> None:
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    nodes = [
        (0, 0, 0.0, 0.0, 0.0),
        (1, 1, 0.0, 0.0, 0.0),
        (2, 1, 0.0, 20.0, 0.0),
        (3, 2, 0.0, 0.0, 0.0),
        (4, 2, 0.0, 5.0, 0.0),
        (5, 3, 0.0, 0.0, 0.0),
        (6, 3, 0.0, 5.0, 0.0),
    ]
    gt_edges = [(0, 1), (1, 3), (1, 4), (3, 5), (4, 6)]
    _write_metric_gt(gt_dir, "vid", nodes, gt_edges)
    baseline_edges = [(0, 1), (1, 3), (2, 4), (3, 5), (4, 6)]
    positive = tmp_path / "positive.csv"
    harmful = tmp_path / "harmful.csv"
    _write_metric_csv(positive, "vid", nodes, gt_edges)
    _write_metric_csv(harmful, "vid", nodes, baseline_edges)
    good_summary, good_rows = score_submission(positive, gt_dir, verbose=False)
    bad_summary, bad_rows = score_submission(harmful, gt_dir, verbose=False)
    assert (good_rows[0]["edge_tp"], good_rows[0]["edge_fp"], good_rows[0]["edge_fn"]) == (5, 0, 0)
    assert (good_rows[0]["division_tp"], good_rows[0]["division_fp"], good_rows[0]["division_fn"]) == (1, 0, 0)
    assert bad_rows[0]["edge_tp"] < good_rows[0]["edge_tp"]
    assert bad_rows[0]["division_tp"] == 0 and bad_rows[0]["division_fn"] == 1
    assert good_summary["score"] > bad_summary["score"]

    donor_gt = tmp_path / "donor_gt"
    donor_gt.mkdir()
    donor_edges = [(0, 1), (1, 3), (2, 4), (3, 5), (4, 6)]
    false_fork_edges = [(0, 1), (1, 3), (1, 4), (3, 5), (4, 6)]
    _write_metric_gt(donor_gt, "vid", nodes, donor_edges)
    donor_baseline = tmp_path / "valid_donor.csv"
    donor_cut = tmp_path / "cut_valid_donor.csv"
    _write_metric_csv(donor_baseline, "vid", nodes, donor_edges)
    _write_metric_csv(donor_cut, "vid", nodes, false_fork_edges)
    donor_summary, donor_rows = score_submission(donor_baseline, donor_gt, verbose=False)
    cut_summary, cut_rows = score_submission(donor_cut, donor_gt, verbose=False)
    assert (donor_rows[0]["edge_tp"], donor_rows[0]["edge_fp"], donor_rows[0]["edge_fn"]) == (5, 0, 0)
    assert (cut_rows[0]["edge_tp"], cut_rows[0]["edge_fp"], cut_rows[0]["edge_fn"]) == (4, 1, 1)
    assert (donor_rows[0]["division_tp"], donor_rows[0]["division_fp"], donor_rows[0]["division_fn"]) == (0, 0, 0)
    assert (cut_rows[0]["division_tp"], cut_rows[0]["division_fp"], cut_rows[0]["division_fn"]) == (0, 1, 0)
    assert cut_summary["score"] < donor_summary["score"]


def test_official_aggregate_is_not_mean_and_zero_division_null() -> None:
    from tracking_cellmot.metrics import EvaluationResult, per_sample_metrics, summarise

    rows = [
        per_sample_metrics(EvaluationResult(1, 0, 0, 0, 0, 0, 2), 2, 1.0),
        per_sample_metrics(EvaluationResult(1, 9, 0, 0, 0, 0, 2), 2, 1.0),
    ]
    summary = summarise(rows)
    assert summary["edge_jaccard"] == pytest.approx(2 / 11)
    assert summary["edge_jaccard"] != pytest.approx((1.0 + 0.1) / 2)
    normalised = scoring._normalise_summary(summary, "zero divisions")
    assert normalised["division_jaccard"] is None
    assert normalised["division_jaccard_status"] == "NO_DIVISION_DENOMINATOR"
    with pytest.raises(scoring.ScoringFailure, match="key set"):
        scoring._normalise_summary({**summary, "new_key": 1}, "drift")


def test_missing_gt_skip_is_hard_failure(tmp_path: Path) -> None:
    csv_path = tmp_path / "one.csv"
    csv_path.write_bytes(_csv_bytes(("vid",)))
    sealed = SimpleNamespace(gt_dir=tmp_path / "empty")
    sealed.gt_dir.mkdir()
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring._score_one(csv_path, sealed, "vid", "baseline")
    assert caught.value.code == "MISSING_GT_SKIP"


@pytest.mark.parametrize(
    "scale",
    [None, [1, 1], [1, 0, 1, 1], [1, math.nan, 1, 1], [1, math.inf, 1, 1]],
)
def test_scale_must_be_explicit_three_vector_finite_positive(tmp_path: Path, scale: list[float] | None) -> None:
    zarr_root = tmp_path / "vid.zarr"
    transforms = [] if scale is None else [{"type": "scale", "scale": scale}]
    value = {
        "attributes": {"ome": {"multiscales": [{"datasets": [{"path": "0", "coordinateTransformations": transforms}]}]}}
    }
    path = zarr_root / "zarr.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value, allow_nan=True))
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring._parse_explicit_scale(zarr_root, "vid")
    assert caught.value.code in {"MISSING_EXPLICIT_SCALE", "MALFORMED_SCALE"}


def test_default_scale_fallback_is_rejected(tmp_path: Path) -> None:
    zarr_root = tmp_path / "vid.zarr"
    _canonical(zarr_root / "zarr.json", {"attributes": {}})
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring._parse_explicit_scale(zarr_root, "vid")
    assert caught.value.code == "MISSING_EXPLICIT_SCALE"


def test_n_total_explicit_positive_and_helper_equal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = tmp_path / "run"
    gt = run / "inputs" / "gt"
    gt.mkdir(parents=True)
    nodes = [(1, 0, 0.0, 0.0, 0.0), (2, 1, 0.0, 0.0, 0.0)]
    _write_metric_gt(gt, "vid", nodes, [(1, 2)])
    records = []
    for path in (gt / "vid.geff" / "zarr.json", gt / "vid.zarr" / "zarr.json"):
        records.append(_relative_ref(run, path))
    sealed = SimpleNamespace(
        run_dir=run,
        gt_dir=gt,
        gt_inventory={"records": records},
    )
    valid = scoring._validate_metadata_binding(sealed, "vid")
    assert valid["n_total"] == 2.0 and valid["scale_zyx_um"] == [1.0, 1.0, 1.0]

    import biohub.io

    monkeypatch.setattr(biohub.io, "estimated_number_of_nodes", lambda _path: 3.0)
    with pytest.raises(scoring.ScoringFailure) as mismatch:
        scoring._validate_metadata_binding(sealed, "vid")
    assert mismatch.value.code == "N_TOTAL_HELPER_MISMATCH"


def test_n_total_missing_nonpositive_and_nonfinite_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import geff

    run = tmp_path / "run"
    gt = run / "inputs" / "gt"
    gt.mkdir(parents=True)
    nodes = [(1, 0, 0.0, 0.0, 0.0), (2, 1, 0.0, 0.0, 0.0)]
    _write_metric_gt(gt, "vid", nodes, [(1, 2)])
    records = [
        _relative_ref(run, gt / "vid.geff" / "zarr.json"),
        _relative_ref(run, gt / "vid.zarr" / "zarr.json"),
    ]
    sealed = SimpleNamespace(run_dir=run, gt_dir=gt, gt_inventory={"records": records})
    real_read = geff.GeffMetadata.read
    for value, code in ((None, "MISSING_N_TOTAL"), (0, "MALFORMED_N_TOTAL"), (math.nan, "MALFORMED_N_TOTAL")):

        def fake_read(path: Path, current: float | None = value):
            metadata = real_read(path)
            if current is None:
                metadata.extra.pop("estimated_number_of_nodes", None)
            else:
                metadata.extra["estimated_number_of_nodes"] = current
            return metadata

        monkeypatch.setattr(geff.GeffMetadata, "read", fake_read)
        with pytest.raises(scoring.ScoringFailure) as caught:
            scoring._validate_metadata_binding(sealed, "vid")
        assert caught.value.code == code


def test_exact_public_four_stems_are_rejected() -> None:
    for stem in scoring.PUBLIC_FOUR:
        with pytest.raises(scoring.ScoringFailure) as caught:
            scoring._reject_public_four({"dataset": stem}, "test")
        assert caught.value.code == "PUBLIC_FOUR_CONTAMINATION"


def _deltas_for(stage: str) -> dict[str, object]:
    mean = 0.005 if stage == "eval12" else 0.003
    official = {
        stage: {"division_tp": 4, "adj_edge_jaccard": -0.002, "score": 0.0, "division_jaccard": 0.0},
        "44b6": {"score": 0.0},
        "6bba": {"score": 0.0},
    }
    return {"paired": {"mean": mean, "median": 0.0, "worst": -0.002}, "official_aggregate_deltas": official}


@pytest.mark.parametrize("stage", ["eval12", "eval24", "eval36"])
def test_every_metric_gate_exact_and_nextafter(stage: str) -> None:
    values = _deltas_for(stage)
    at = scoring.evaluate_metric_gates(stage, values)
    assert all(gate["pass"] for gate in at["gates"])
    for gate in at["gates"]:
        altered = json.loads(json.dumps(values))
        name = gate["name"]
        threshold = gate["threshold"]
        below = math.nextafter(float(threshold), -math.inf)
        if name.startswith("paired_mean"):
            altered["paired"]["mean"] = below
        elif name.startswith("paired_median"):
            altered["paired"]["median"] = below
        elif name.startswith("paired_worst"):
            altered["paired"]["worst"] = below
        elif name.startswith("44b6"):
            altered["official_aggregate_deltas"]["44b6"]["score"] = below
        elif name.startswith("6bba"):
            altered["official_aggregate_deltas"]["6bba"]["score"] = below
        elif "division_tp" in name:
            altered["official_aggregate_deltas"][stage]["division_tp"] = 3
        elif "adjusted_edge" in name:
            altered["official_aggregate_deltas"][stage]["adj_edge_jaccard"] = below
        elif "division_jaccard" in name:
            altered["official_aggregate_deltas"][stage]["division_jaccard"] = below
        else:
            altered["official_aggregate_deltas"][stage]["score"] = below
        assert not scoring.evaluate_metric_gates(stage, altered)["gates"][at["gates"].index(gate)]["pass"]


def test_feasibility_boundaries_and_nextafter() -> None:
    values = {
        "candidate_wall_gate": 125.0,
        "baseline_wall_gate": 100.0,
        "candidate_rss_gate": 2_073_741_824,
        "baseline_rss_gate": 1_000_000_000,
        "target_candidate_aggregate_peak_gate": 800.0,
        "target_declared_ram_bytes": 1000.0,
        "target_eval36_charged_seconds": 36.0,
        "target_declared_wall_seconds": 250.0,
    }
    assert scoring.evaluate_feasibility_thresholds(values)["pass"]
    for key in (
        "candidate_wall_gate",
        "candidate_rss_gate",
        "target_candidate_aggregate_peak_gate",
        "target_eval36_charged_seconds",
    ):
        bad = dict(values)
        bad[key] = math.nextafter(float(values[key]), math.inf)
        assert not scoring.evaluate_feasibility_thresholds(bad)["pass"]


def test_state_machine_rollup_no_new_eval_and_terminal_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skipped_run, skipped_digest = _make_sealed_run(tmp_path, "skipped")
    _patch_fake_scoring(monkeypatch)
    with pytest.raises(scoring.ScoringFailure) as skipped:
        scoring.score_stage(skipped_run, skipped_digest, "eval24")
    assert skipped.value.code in {"MISSING_ARTIFACT", "STATE_ORDER"}
    assert json.loads((skipped_run / "final" / "VERDICT.json").read_text())["first_failure"] == skipped.value.code
    with pytest.raises(scoring.ScoringFailure, match="terminal"):
        scoring.score_stage(skipped_run, skipped_digest, "eval12")

    run, digest = _make_sealed_run(tmp_path, "ordered")
    assert scoring.score_stage(run, digest, "eval12")["status"] == "EVAL12_PASS"
    assert scoring.score_stage(run, digest, "eval24")["status"] == "EVAL24_PASS"
    monkeypatch.setattr(scoring, "_score_one", lambda *_args: pytest.fail("eval36 must make no evaluation call"))
    result = scoring.score_stage(run, digest, "eval36")
    assert result["status"] == "EVAL36_ADOPTION_CANDIDATE"
    assert (
        json.loads((run / "scores" / "eval36_rollup" / "INPUT_RECEIPT.json").read_text())["official_evaluation_calls"]
        == 0
    )
    with pytest.raises(scoring.ScoringFailure, match="terminal"):
        scoring.score_stage(run, digest, "eval36")


def test_replay_is_byte_identical_and_no_clobber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_a, digest_a = _make_sealed_run(tmp_path, "a")
    run_b, digest_b = _make_sealed_run(tmp_path, "b")
    assert digest_a == digest_b
    _patch_fake_scoring(monkeypatch)
    scoring.score_stage(run_a, digest_a, "eval12")
    scoring.score_stage(run_b, digest_b, "eval12")
    files_a = {
        p.relative_to(run_a / "scores" / "eval12").as_posix(): p.read_bytes()
        for p in (run_a / "scores" / "eval12").rglob("*")
        if p.is_file()
    }
    files_b = {
        p.relative_to(run_b / "scores" / "eval12").as_posix(): p.read_bytes()
        for p in (run_b / "scores" / "eval12").rglob("*")
        if p.is_file()
    }
    assert files_a == files_b
    with pytest.raises(scoring.ScoringFailure):
        scoring.score_stage(run_a, digest_a, "eval12")


def test_manifest_hash_drift_symlink_and_schema_extra_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, digest = _make_sealed_run(tmp_path)
    monkeypatch.setattr(scoring, "_validate_current_source", lambda *_args: None)
    with pytest.raises(scoring.ScoringFailure, match="caller-provided"):
        scoring.validate_feasibility_manifest(run, "0" * 64)
    manifest_path = run / "feasibility" / "FEASIBILITY_PASS.json"
    value = json.loads(manifest_path.read_text())
    value["unexpected"] = True
    _canonical(manifest_path, value)
    with pytest.raises(scoring.ScoringFailure) as extra:
        scoring.validate_feasibility_manifest(run, scoring.sha256_file(manifest_path))
    assert extra.value.code == "SCHEMA_MISMATCH"
    # Restore, then replace a canonical CSV by a symlink: references fail closed.
    del value["unexpected"]
    _canonical(manifest_path, value)
    csv_path = run / "generation" / "canonical" / "baseline" / "submission.csv"
    real = csv_path.with_name("real.csv")
    csv_path.rename(real)
    os.symlink(real.name, csv_path)
    with pytest.raises(scoring.ScoringFailure) as linked:
        scoring.validate_feasibility_manifest(run, scoring.sha256_file(manifest_path))
    assert linked.value.code == "SYMLINK_REFUSED"


def test_path_traversal_case_collision_and_atomic_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(scoring.ScoringFailure) as traversal:
        scoring._safe_rel("../escape", "test")
    assert traversal.value.code == "UNSAFE_PATH"
    with pytest.raises(scoring.ScoringFailure) as collision:
        scoring._check_case_collisions(["A/file", "a/file"], "test")
    assert collision.value.code == "CASE_COLLISION"
    target = tmp_path / "published.json"
    real_rename = os.rename

    def interrupted(source: object, destination: object) -> None:
        if Path(destination) == target:
            raise OSError("simulated atomic publication interruption")
        real_rename(source, destination)

    monkeypatch.setattr(os, "rename", interrupted)
    with pytest.raises(OSError, match="interruption"):
        scoring._atomic_write(target, b"payload")
    assert not target.exists()
    assert not list(tmp_path.glob(".*.tmp-*"))


def test_canonical_json_and_paired_full_precision() -> None:
    assert scoring.canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}\n'
    with pytest.raises(scoring.ScoringFailure):
        scoring.canonical_json_bytes({"x": math.nan})
    values = [0.1, 0.2, 0.3, 0.4]
    stats = scoring.paired_statistics(values)
    assert stats["mean"] == math.fsum(values) / 4
    assert stats["median"] == math.fsum((0.2, 0.3)) / 2
    assert stats["worst"] == 0.1
