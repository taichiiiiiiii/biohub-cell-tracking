from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

import biohub.st_r3_scoring as scoring
from biohub.evaluate import graph_from_rows, score_submission

PRODUCTION_VALIDATE_FEASIBILITY = scoring.validate_feasibility_manifest

REAL_44B6_12DFB391_ZARR_JSON = b"""{
  "attributes": {
    "multiscales": [
      {
        "version": "0.5",
        "axes": [
          {
            "name": "T",
            "type": "time",
            "unit": "second"
          },
          {
            "name": "Z",
            "type": "space",
            "unit": "micrometer"
          },
          {
            "name": "Y",
            "type": "space",
            "unit": "micrometer"
          },
          {
            "name": "X",
            "type": "space",
            "unit": "micrometer"
          }
        ],
        "datasets": [
          {
            "path": "0",
            "coordinateTransformations": [
              {
                "type": "scale",
                "scale": [
                  1.0,
                  1.625,
                  0.40625,
                  0.40625
                ]
              }
            ]
          }
        ],
        "name": "0"
      }
    ],
    "image_statistics": {
      "quantiles": {
        "0.0": 50.0,
        "0.001": 70.0,
        "0.01": 133.0,
        "0.1": 306.99999999999994,
        "0.9": 1453.0,
        "0.99": 2247.0000000000123,
        "0.999": 3065.0,
        "1.0": 5262.0
      }
    }
  },
  "zarr_format": 3,
  "consolidated_metadata": null,
  "node_type": "group"
}"""


@pytest.fixture(autouse=True)
def _reviewed_interface_test_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic tests exercise the scorer below the production interface HOLD."""
    monkeypatch.setattr(scoring, "validate_feasibility_manifest", scoring._validate_fixture_feasibility_manifest)


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
                        "axes": [
                            {"name": "t", "type": "time", "unit": "second"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1, 1, 1, 1]}]}
                        ],
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
            {
                "axes": [
                    {"name": "t", "type": "time", "unit": "second"},
                    {"name": "z", "type": "space", "unit": "micrometer"},
                    {"name": "y", "type": "space", "unit": "micrometer"},
                    {"name": "x", "type": "space", "unit": "micrometer"},
                ],
                "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1, 1, 1, 1]}]}],
            }
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


def test_missing_gt_skip_is_hard_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "one.csv"
    csv_path.write_bytes(_csv_bytes(("vid",)))
    sealed = SimpleNamespace(gt_dir=tmp_path / "empty")
    sealed.gt_dir.mkdir()
    monkeypatch.setattr(scoring, "_validate_official_runtime_binding", lambda _sealed: None)
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
    assert caught.value.code in {"MISSING_EXPLICIT_SCALE", "MALFORMED_SCALE", "NONFINITE_JSON"}


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
    assert skipped.value.code in {"MISSING_ARTIFACT", "STATE_ORDER", "MISSING_PRIOR_ANCHOR"}
    assert json.loads((skipped_run / "final" / "VERDICT.json").read_text())["first_failure"] == skipped.value.code
    with pytest.raises(scoring.ScoringFailure, match="terminal"):
        scoring.score_stage(skipped_run, skipped_digest, "eval12")

    run, digest = _make_sealed_run(tmp_path, "ordered")
    eval12 = scoring.score_stage(run, digest, "eval12")
    assert eval12["status"] == "EVAL12_PASS"
    eval24 = scoring.score_stage(run, digest, "eval24", prior_manifest_sha256=eval12["stage_manifest"]["sha256"])
    assert eval24["status"] == "EVAL24_PASS"
    monkeypatch.setattr(scoring, "_score_one", lambda *_args: pytest.fail("eval36 must make no evaluation call"))
    result = scoring.score_stage(run, digest, "eval36", prior_manifest_sha256=eval24["stage_manifest"]["sha256"])
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
    real_rename = scoring._rename_noreplace

    def interrupted(source: Path, destination: Path) -> None:
        if Path(destination) == target:
            raise OSError("simulated atomic publication interruption")
        real_rename(source, destination)

    monkeypatch.setattr(scoring, "_rename_noreplace", interrupted)
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


def test_production_interface_hold_precedes_any_gt_or_manifest_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scoring, "validate_feasibility_manifest", PRODUCTION_VALIDATE_FEASIBILITY)
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring.score_stage(tmp_path / "missing-run", "not-even-a-sha", "eval12")
    assert caught.value.code == "HOLD_INTERFACE_INCOMPLETE"
    assert not (tmp_path / "missing-run").exists()


def test_fake_feasibility_self_report_cannot_unlock_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, digest = _make_sealed_run(tmp_path)
    gate_path = run / "feasibility" / "GATES.json"
    _canonical(gate_path, {"status": "REJECT_RUNTIME", "runtime": None, "rss": None})
    monkeypatch.setattr(scoring, "validate_feasibility_manifest", PRODUCTION_VALIDATE_FEASIBILITY)
    monkeypatch.setattr(scoring, "_read_json", lambda *_args: pytest.fail("production HOLD must read no JSON"))
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring.score_stage(run, digest, "eval12")
    assert caught.value.code == "HOLD_INTERFACE_INCOMPLETE"


def test_five_arm_alias_and_nested_public_four_are_rejected(tmp_path: Path) -> None:
    run, _ = _make_sealed_run(tmp_path)
    manifest_path = run / "feasibility" / "FEASIBILITY_PASS.json"
    value = json.loads(manifest_path.read_text())
    same = value["executions"]["safety_dry_run"]
    value["executions"] = {key: same for key in scoring.EXECUTION_KEYS}
    _canonical(manifest_path, value)
    with pytest.raises(scoring.ScoringFailure) as alias:
        scoring.validate_feasibility_manifest(run, scoring.sha256_file(manifest_path))
    assert alias.value.code == "FIVE_ARM_INCOMPLETE"

    run, _ = _make_sealed_run(tmp_path, "public")
    manifest_path = run / "feasibility" / "FEASIBILITY_PASS.json"
    value = json.loads(manifest_path.read_text())
    generation_path = run / "generation" / "ARTIFACT_MANIFEST.json"
    generation = json.loads(generation_path.read_text())
    generation["diagnostic"] = next(iter(scoring.PUBLIC_FOUR))
    _canonical(generation_path, generation)
    replacement = _relative_ref(run, generation_path)
    value["generation_manifest"]["ref"] = replacement
    value["artifacts"] = [replacement if item["path"] == replacement["path"] else item for item in value["artifacts"]]
    _canonical(manifest_path, value)
    with pytest.raises(scoring.ScoringFailure) as public:
        scoring.validate_feasibility_manifest(run, scoring.sha256_file(manifest_path))
    assert public.value.code == "PUBLIC_FOUR_CONTAMINATION"


def test_gt_path_value_hardlink_duplicate_json_and_path_aliases_fail(tmp_path: Path) -> None:
    with pytest.raises(scoring.ScoringFailure) as leaked:
        scoring._reject_gt_exposure({"input_path": "/private/gt/secret.geff"}, "arm")
    assert leaked.value.code == "GT_EXPOSED_TO_ARM"

    root = tmp_path / "refs"
    root.mkdir()
    first = root / "first"
    first.write_bytes(b"sealed")
    os.link(first, root / "alias")
    ref = {"path": "first", "bytes": 6, "sha256": scoring.sha256_file(first)}
    with pytest.raises(scoring.ScoringFailure) as linked:
        scoring._validate_ref(root, ref, "hardlink")
    assert linked.value.code == "HARDLINK_REFUSED"

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"shape":[1,1,1,1],"shape":[2,2,2,2]}')
    with pytest.raises(scoring.ScoringFailure) as duplicated:
        scoring._read_json_relaxed(duplicate, "duplicate")
    assert duplicated.value.code == "DUPLICATE_JSON_KEY"
    for alias in ("a/./b", "a//b", "a/b/"):
        with pytest.raises(scoring.ScoringFailure) as unsafe:
            scoring._safe_rel(alias, "alias")
        assert unsafe.value.code == "UNSAFE_PATH"


def test_scale_requires_explicit_axes_and_micrometer_units(tmp_path: Path) -> None:
    root = tmp_path / "v.zarr"
    metadata = {
        "attributes": {
            "ome": {
                "multiscales": [
                    {
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [{"type": "scale", "scale": [9, 2, 3, 4]}],
                            }
                        ]
                    }
                ]
            }
        }
    }
    _canonical(root / "zarr.json", metadata)
    with pytest.raises(scoring.ScoringFailure) as missing_axes:
        scoring._parse_explicit_scale(root, "v")
    assert missing_axes.value.code == "MALFORMED_SCALE"
    metadata["attributes"]["ome"]["multiscales"][0]["axes"] = [
        {"name": "t", "type": "time", "unit": "second"},
        {"name": "z", "type": "space", "unit": "millimeter"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ]
    _canonical(root / "zarr.json", metadata)
    with pytest.raises(scoring.ScoringFailure) as wrong_unit:
        scoring._parse_explicit_scale(root, "v")
    assert wrong_unit.value.code == "MALFORMED_SCALE"


def test_real_pinned_zarr_v3_uppercase_axes_are_accepted(tmp_path: Path) -> None:
    assert len(REAL_44B6_12DFB391_ZARR_JSON) == 1282
    assert scoring.sha256_bytes(REAL_44B6_12DFB391_ZARR_JSON) == (
        "22c3273ffc11029659e5647a62c2bfb1576d358c37d31d70e2735d6f48f2a4cc"
    )
    root = tmp_path / "44b6_12dfb391.zarr"
    _write(root / "zarr.json", REAL_44B6_12DFB391_ZARR_JSON)
    scale, raw, metadata_path = scoring._parse_explicit_scale(root, "44b6_12dfb391")
    assert scale == (1.625, 0.40625, 0.40625)
    assert raw == [1.0, 1.625, 0.40625, 0.40625]
    assert metadata_path == root / "zarr.json"


def test_scale_case_contract_v2_and_ambiguous_metadata_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "v.zarr"
    value = json.loads(REAL_44B6_12DFB391_ZARR_JSON)
    axes = value["attributes"]["multiscales"][0]["axes"]
    for axis in axes:
        axis["name"] = axis["name"].lower()
    _canonical(root / ".zattrs", value["attributes"])
    assert scoring._parse_explicit_scale(root, "v")[0] == (1.625, 0.40625, 0.40625)

    axes[1]["name"] = "Z"
    _canonical(root / ".zattrs", value["attributes"])
    with pytest.raises(scoring.ScoringFailure) as mixed_case:
        scoring._parse_explicit_scale(root, "v")
    assert mixed_case.value.code == "MALFORMED_SCALE"

    axes[1]["name"] = "z"
    _canonical(root / ".zattrs", value["attributes"])
    _write(root / "zarr.json", REAL_44B6_12DFB391_ZARR_JSON)
    with pytest.raises(scoring.ScoringFailure) as ambiguous:
        scoring._parse_explicit_scale(root, "v")
    assert ambiguous.value.code == "MISSING_EXPLICIT_SCALE"


def test_atomic_file_and_directory_publication_are_race_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.json"
    real = scoring._rename_noreplace

    def inject_file(source: Path, destination: Path) -> None:
        destination.write_bytes(b"attacker")
        real(source, destination)

    monkeypatch.setattr(scoring, "_rename_noreplace", inject_file)
    with pytest.raises(scoring.ScoringFailure) as raced_file:
        scoring._atomic_write(target, b"trusted")
    assert raced_file.value.code == "NO_CLOBBER"
    assert target.read_bytes() == b"attacker"

    monkeypatch.setattr(scoring, "_rename_noreplace", real)
    run = tmp_path / "run"
    temp = scoring._temp_stage_dir(run, "eval12")
    scoring._temp_write(temp / "GATE.json", scoring.canonical_json_bytes({"status": "EVAL12_PASS"}))
    stage_target = run / "scores" / "eval12"

    def inject_directory(source: Path, destination: Path) -> None:
        destination.mkdir()
        real(source, destination)

    monkeypatch.setattr(scoring, "_rename_noreplace", inject_directory)
    sealed = SimpleNamespace(run_dir=run, manifest={"run_id": "x"}, manifest_sha256="0" * 64)
    with pytest.raises(scoring.ScoringFailure) as raced_directory:
        scoring._publish_stage(
            sealed,
            "eval12",
            {"path": "x", "bytes": 0, "sha256": "0" * 64},
            temp,
            "EVAL12_PASS",
        )
    assert raced_directory.value.code == "NO_CLOBBER"
    assert stage_target.is_dir() and not any(stage_target.iterdir())


def test_fsync_failure_retracts_file_and_quarantines_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_fsync = scoring._fsync_directory
    calls = 0

    def fail_first(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise scoring.ScoringFailure("FSYNC_FAILED", "injected")
        real_fsync(path)

    monkeypatch.setattr(scoring, "_fsync_directory", fail_first)
    target = tmp_path / "result.json"
    with pytest.raises(scoring.ScoringFailure) as file_failure:
        scoring._atomic_write(target, b"result")
    assert file_failure.value.code == "FSYNC_FAILED"
    assert not target.exists()

    calls = 0
    run = tmp_path / "run"
    temp = scoring._temp_stage_dir(run, "eval12")
    scoring._temp_write(temp / "GATE.json", scoring.canonical_json_bytes({"status": "EVAL12_PASS"}))
    sealed = SimpleNamespace(run_dir=run, manifest={"run_id": "x"}, manifest_sha256="0" * 64)
    with pytest.raises(scoring.ScoringFailure) as stage_failure:
        scoring._publish_stage(
            sealed,
            "eval12",
            {"path": "x", "bytes": 0, "sha256": "0" * 64},
            temp,
            "EVAL12_PASS",
        )
    assert stage_failure.value.code == "STAGE_DURABILITY_FAILED"
    assert not (run / "scores" / "eval12").exists()
    quarantines = list((run / "scores").glob("failed_eval12-publish-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "ARTIFACT_MANIFEST.json").is_file()


def test_stage_fsync_failure_emits_terminal_evidence_without_success_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, digest = _make_sealed_run(tmp_path)
    _patch_fake_scoring(monkeypatch)
    real_fsync = scoring._fsync_directory
    injected = False

    def fail_score_publication(path: Path) -> None:
        nonlocal injected
        if path == run / "scores" and not injected:
            injected = True
            raise scoring.ScoringFailure("FSYNC_FAILED", "injected stage durability failure")
        real_fsync(path)

    monkeypatch.setattr(scoring, "_fsync_directory", fail_score_publication)
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring.score_stage(run, digest, "eval12")
    assert caught.value.code == "STAGE_DURABILITY_FAILED"
    assert not (run / "scores" / "eval12").exists()
    verdict = json.loads((run / "final" / "VERDICT.json").read_text())
    assert verdict["status"] == "ERROR_AFTER_GT_READ"
    assert verdict["first_failure"] == "STAGE_DURABILITY_FAILED"
    assert verdict["partial_score_inventory"]


def test_secure_read_detects_same_inode_mode_ctime_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "sealed.bin"
    payload = b"immutable" * 1024
    path.write_bytes(payload)
    original_mode = path.stat().st_mode & 0o777
    real_read = scoring.os.read
    changed = False

    def mutate_after_read(fd: int, count: int) -> bytes:
        nonlocal changed
        chunk = real_read(fd, count)
        if chunk and not changed:
            changed = True
            path.chmod(0o400 if original_mode != 0o400 else 0o600)
            path.chmod(original_mode)
        return chunk

    monkeypatch.setattr(scoring.os, "read", mutate_after_read)
    with pytest.raises(scoring.ScoringFailure) as drift:
        scoring._secure_file_identity(path, "same-UID mutation")
    assert drift.value.code == "HASH_DRIFT"


def test_prior_stage_tamper_is_rejected_by_in_memory_anchor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, digest = _make_sealed_run(tmp_path)
    _patch_fake_scoring(monkeypatch)
    eval12 = scoring.score_stage(run, digest, "eval12")
    original_anchor = eval12["stage_manifest"]["sha256"]
    per_video = run / "scores" / "eval12" / "PER_VIDEO.json"
    value = json.loads(per_video.read_text())
    value["rows"][0]["candidate"]["source_hashes"] = {"tampered": True}
    _canonical(per_video, value)
    stage_manifest = run / "scores" / "eval12" / "ARTIFACT_MANIFEST.json"
    manifest = json.loads(stage_manifest.read_text())
    for item in manifest["artifacts"]:
        if item["path"].endswith("/PER_VIDEO.json"):
            item["bytes"] = per_video.stat().st_size
            item["sha256"] = scoring.sha256_file(per_video)
    _canonical(stage_manifest, manifest)
    with pytest.raises(scoring.ScoringFailure) as tampered:
        scoring.score_stage(run, digest, "eval24", prior_manifest_sha256=original_anchor)
    assert tampered.value.code == "PRIOR_STAGE_TAMPERED"


def test_authoritative_all_invocation_completes_stages_without_control_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, digest = _make_sealed_run(tmp_path)
    _patch_fake_scoring(monkeypatch)
    result = scoring.score_all(run, digest, invocation_argv=["scorer", "--stage", "all"])
    assert result["status"] == "EVAL36_ADOPTION_CANDIDATE"
    assert (run / "scores/eval12/ARTIFACT_MANIFEST.json").is_file()
    assert (run / "scores/eval24/ARTIFACT_MANIFEST.json").is_file()
    assert (run / "scores/eval36_rollup/ARTIFACT_MANIFEST.json").is_file()
    assert result["scorer_execution"]["argv"] == ["scorer", "--stage", "all"]


def test_unexpected_error_retains_partial_and_terminal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, digest = _make_sealed_run(tmp_path)
    monkeypatch.setattr(scoring, "_validate_current_source", lambda *_args: None)
    monkeypatch.setattr(scoring, "_verify_unlocked_gt", lambda _sealed, stems: {stem: {} for stem in stems})

    def fail(*_args: object) -> object:
        raise OSError("disk I/O")

    monkeypatch.setattr(scoring, "_score_one", fail)
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring.score_stage(run, digest, "eval12", invocation_argv=["scorer", "--stage", "all"])
    assert caught.value.code == "UNEXPECTED_SCORER_ERROR"
    assert (run / "scores" / "failed_eval12").is_dir()
    verdict = json.loads((run / "final" / "VERDICT.json").read_text())
    assert verdict["status"] == "ERROR_AFTER_GT_READ"
    assert verdict["scorer_execution"]["argv"] == ["scorer", "--stage", "all"]
    assert verdict["scorer_execution"]["scorer_wall_seconds"] >= 0


def test_resource_integer_precision_and_non_nan_division_nonfinite_rejection() -> None:
    baseline = 2**54
    values = {
        "candidate_wall_gate": 1,
        "baseline_wall_gate": 1,
        "candidate_rss_gate": baseline + 1_073_741_824 + 1,
        "baseline_rss_gate": baseline,
        "target_candidate_aggregate_peak_gate": 8,
        "target_declared_ram_bytes": 10,
        "target_eval36_charged_seconds": 1,
        "target_declared_wall_seconds": 10,
    }
    gates = scoring.evaluate_feasibility_thresholds(values)
    assert not next(gate for gate in gates["gates"] if gate["name"] == "local_rss")["pass"]
    summary = {
        "n": 1,
        "edge_jaccard": 1.0,
        "division_jaccard": math.inf,
        "division_tp": 0,
        "division_fp": 0,
        "division_fn": 0,
        "node_recall": 1.0,
        "adj_edge_jaccard": 1.0,
        "n_adj": 1,
        "score": 1.0,
    }
    with pytest.raises(scoring.ScoringFailure) as nonfinite:
        scoring._normalise_summary(summary, "inf")
    assert nonfinite.value.code == "NONFINITE_OFFICIAL_METRIC"


@pytest.mark.parametrize("bad", [True, False, "1", None, math.nan, math.inf, -math.inf, 0, -1])
def test_feasibility_threshold_malformed_values_fail_with_stable_code(bad: object) -> None:
    values: dict[str, object] = {
        "candidate_wall_gate": 1,
        "baseline_wall_gate": 1,
        "candidate_rss_gate": 1,
        "baseline_rss_gate": 1,
        "target_candidate_aggregate_peak_gate": 1,
        "target_declared_ram_bytes": 1,
        "target_eval36_charged_seconds": 36,
        "target_declared_wall_seconds": 1,
    }
    values["candidate_wall_gate"] = bad
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring.evaluate_feasibility_thresholds(values)
    assert caught.value.code == "NONFINITE_GATE_INPUT"


def test_feasibility_threshold_giant_integer_comparisons_remain_exact() -> None:
    huge = 2**20000
    values = {
        "candidate_wall_gate": huge * 5 + 1,
        "baseline_wall_gate": huge * 4,
        "candidate_rss_gate": huge + 1_073_741_825,
        "baseline_rss_gate": huge,
        "target_candidate_aggregate_peak_gate": huge * 4 + 1,
        "target_declared_ram_bytes": huge * 5,
        "target_eval36_charged_seconds": huge * 36,
        "target_declared_wall_seconds": huge * 250,
    }
    result = scoring.evaluate_feasibility_thresholds(values)
    by_name = {gate["name"]: gate["pass"] for gate in result["gates"]}
    assert by_name == {"local_runtime": False, "local_rss": False, "target_memory": False, "hidden_200": True}
    assert result["hidden_200_seconds"] == huge * 200


def test_nonintegral_giant_hidden_projection_fails_canonically() -> None:
    values = {
        "candidate_wall_gate": 1,
        "baseline_wall_gate": 1,
        "candidate_rss_gate": 1,
        "baseline_rss_gate": 1,
        "target_candidate_aggregate_peak_gate": 1,
        "target_declared_ram_bytes": 1,
        "target_eval36_charged_seconds": 2**20000 + 1,
        "target_declared_wall_seconds": 1,
    }
    with pytest.raises(scoring.ScoringFailure) as caught:
        scoring.evaluate_feasibility_thresholds(values)
    assert caught.value.code == "NONFINITE_GATE_INPUT"


def test_cli_production_hold_is_canonical_and_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(scoring, "validate_feasibility_manifest", PRODUCTION_VALIDATE_FEASIBILITY)
    code = scoring.main(
        [
            "--run-dir",
            str(tmp_path / "never-read"),
            "--generation-manifest-sha256",
            "not-read",
            "--stage",
            "all",
        ]
    )
    assert code == 3
    raw = capsys.readouterr().out.encode()
    value = json.loads(raw)
    assert raw == scoring.canonical_json_bytes(value)
    assert value["status"] == "HOLD"
    assert value["code"] == "HOLD_INTERFACE_INCOMPLETE"
    assert not (tmp_path / "never-read").exists()


def test_evaluate_prefers_official_module_over_rogue_pythonpath(tmp_path: Path) -> None:
    rogue = tmp_path / "rogue" / "tracking_cellmot"
    rogue.mkdir(parents=True)
    (rogue / "__init__.py").write_text("")
    (rogue / "metrics.py").write_text(
        "def evaluate(*a,**k): return None\n"
        "def node_recall(*a,**k): return 0.0\n"
        "def per_sample_metrics(*a,**k): return {}\n"
        "def summarise(*a,**k): return {'rogue':True}\n"
    )
    repo = Path(scoring.__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(tmp_path / "rogue"), str(repo / "src"), str(repo / "official/src")))
    result = subprocess.run(
        [sys.executable, "-c", "import biohub.evaluate as e; print(e.summarise.__code__.co_filename)"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert Path(result.stdout.strip()).resolve() == (repo / "official/src/tracking_cellmot/metrics.py").resolve()
    (tmp_path / "rogue" / "sitecustomize.py").write_text("import tracking_cellmot.metrics\n")
    preloaded = subprocess.run(
        [sys.executable, "-c", "import biohub.evaluate"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert preloaded.returncode != 0
    assert "refusing preloaded non-official module" in preloaded.stderr


def test_runtime_official_function_origins_and_hashes_are_bound() -> None:
    repo = Path(scoring.__file__).resolve().parents[2]
    sealed = SimpleNamespace(
        manifest={
            "official": {
                "source_hashes": {
                    rel: scoring.sha256_file(repo / "official/src" / rel) for rel in scoring.OFFICIAL_SOURCE_KEYS
                }
            },
            "source_bindings": {"evaluate_py_sha256": scoring.sha256_file(repo / "src/biohub/evaluate.py")},
        }
    )
    scoring._validate_official_runtime_binding(sealed)
    sealed.manifest["official"]["source_hashes"]["tracking_cellmot/metrics.py"] = "0" * 64
    with pytest.raises(scoring.ScoringFailure) as drifted:
        scoring._validate_official_runtime_binding(sealed)
    assert drifted.value.code == "OFFICIAL_IMPORT_DRIFT"
