from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from biohub import kaggle_screen as screen


def _write(path: Path, data: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _zarr(root: Path, stem: str) -> None:
    value = {
        "attributes": {
            "ome": {
                "multiscales": [
                    {
                        "datasets": [
                            {"coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.625, 0.40625, 0.40625]}]}
                        ]
                    }
                ]
            }
        }
    }
    _write(root / f"{stem}.zarr/zarr.json", json.dumps(value).encode())
    _write(
        root / f"{stem}.zarr/0/zarr.json",
        json.dumps({"shape": [2, 2, 3, 4], "data_type": "uint16"}).encode(),
    )
    _write(root / f"{stem}.zarr/0/c/0/0/0/0", b"chunk")


def _submission(path: Path, datasets: tuple[str, ...], *, dangling: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=screen.CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        next_id = 0
        for dataset in datasets:
            writer.writerow(
                {
                    "id": next_id,
                    "dataset": dataset,
                    "row_type": "node",
                    "node_id": 1,
                    "t": 0,
                    "z": 0,
                    "y": 0,
                    "x": 0,
                    "source_id": -1,
                    "target_id": -1,
                }
            )
            next_id += 1
            if dangling:
                writer.writerow(
                    {
                        "id": next_id,
                        "dataset": dataset,
                        "row_type": "edge",
                        "node_id": -1,
                        "t": -1,
                        "z": -1,
                        "y": -1,
                        "x": -1,
                        "source_id": 1,
                        "target_id": 2,
                    }
                )
                next_id += 1


def _paths(tmp_path: Path) -> screen.ScreenPaths:
    root = tmp_path / "repo"
    return screen.ScreenPaths(
        repo_root=root,
        screen_parent=root / "outputs/local/kaggle_screen",
        raw36=root / "raw36",
        raw4=root / "raw4",
        image_source=root / "train",
        public4_images=root / "test",
        gt=root / "train",
        deepcenter_checkpoint=root / "deep/best.pt",
        deepcenter_manifest=root / "deep/ARTIFACT_MANIFEST.json",
        public4_reference=root / "reference.csv",
        child_script=root / "scripts/kaggle_screen.py",
    )


def _fixture_assets(paths: screen.ScreenPaths) -> None:
    paths.raw36.mkdir(parents=True)
    paths.raw4.mkdir(parents=True)
    for stem in screen.EVAL36:
        _write(paths.raw36 / f"{stem}.geff/payload")
        _write(paths.gt / f"{stem}.geff/payload")
        _zarr(paths.image_source, stem)
    for stem in screen.PUBLIC4:
        _write(paths.raw4 / f"{stem}.geff/payload")
        _zarr(paths.public4_images, stem)
    _write(paths.deepcenter_checkpoint, b"checkpoint")
    _write(paths.deepcenter_manifest, b"manifest")
    _submission(paths.public4_reference, screen.PUBLIC4)


def _artifact(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_constants_and_cli_are_frozen_and_generation_has_no_top_level_official_import():
    assert screen.EVAL36 == screen.EVAL12 + screen.EVAL24
    assert len(screen.EVAL36) == len(set(screen.EVAL36)) == 36
    assert screen.EVAL36 != tuple(sorted(screen.EVAL36))
    assert screen.ARM_ORDER == ("public4_parity", "dry_run", "baseline", "candidate")
    assert "src/biohub/io.py" in screen.SOURCE_FILES
    source = Path(screen.__file__).read_text()
    tree = ast.parse(source)
    top_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all("biohub.evaluate" not in ast.unparse(node) for node in top_imports)
    cli = Path(__file__).resolve().parents[1] / "scripts/kaggle_screen.py"
    help_text = cli.read_text()
    assert "--gt-dir" not in help_text
    assert "--profile" not in help_text
    assert "--set" not in help_text


def test_exact_e23_dry_and_candidate_config_mapping_and_unknown_arm(tmp_path: Path):
    paths = _paths(tmp_path)
    image = tmp_path / "images"
    baseline = screen._build_config("baseline", image, paths)
    dry = screen._build_config("dry_run", image, paths)
    candidate = screen._build_config("candidate", image, paths)
    assert (baseline.OUTPUT_STEAL_TWIN_REWIRE, baseline.STEAL_TWIN_DRY_RUN) == (False, False)
    assert (dry.OUTPUT_STEAL_TWIN_REWIRE, dry.STEAL_TWIN_DRY_RUN) == (True, True)
    assert (candidate.OUTPUT_STEAL_TWIN_REWIRE, candidate.STEAL_TWIN_DRY_RUN) == (True, False)
    screen._validate_profile_diffs(image, paths)
    with pytest.raises(screen.ScreenError, match="unknown"):
        screen._build_config("invented", image, paths)


@pytest.mark.parametrize("canonical_field", ["repo_root", "screen_parent"])
def test_production_paths_reject_test_only_execution_hooks(tmp_path: Path, canonical_field: str):
    paths = _paths(tmp_path)
    canonical_value = screen.REPO_ROOT if canonical_field == "repo_root" else screen.SCREEN_PARENT
    selected = replace(paths, **{canonical_field: canonical_value})
    with pytest.raises(screen.ScreenError, match="test hook is forbidden"):
        screen.generate_screen("must-not-run", paths=selected, arm_runner=lambda *_: 0)
    with pytest.raises(screen.ScreenError, match="test hook is forbidden"):
        screen.score_screen("must-not-run", "0" * 64, paths=selected, score_function=lambda *_: ({}, []))


def test_submission_validator_checks_order_dangling_and_nonconsecutive(tmp_path: Path):
    good = tmp_path / "good.csv"
    _submission(good, ("a", "b"))
    assert screen._validate_submission(good, ("a", "b"))["rows"] == 2
    with pytest.raises(screen.ScreenError, match="order/set"):
        screen._validate_submission(good, ("b", "a"))
    bad = tmp_path / "bad.csv"
    _submission(bad, ("a",), dangling=True)
    with pytest.raises(screen.ScreenError, match="dangling"):
        screen._validate_submission(bad, ("a",))


def test_explicit_scale_never_falls_back_and_snapshot_rejects_symlink(tmp_path: Path):
    paths = _paths(tmp_path)
    _fixture_assets(paths)
    scale, shape, _ = screen._explicit_scale_and_shape(paths.image_source / f"{screen.EVAL36[0]}.zarr")
    assert scale == [1.625, 0.40625, 0.40625]
    assert shape == [2, 2, 3, 4]
    malformed = tmp_path / "malformed.zarr"
    _write(malformed / "zarr.json", b"{}")
    _write(malformed / "0/zarr.json", b'{"shape":[1,1,1,1]}')
    with pytest.raises(screen.ScreenError, match="explicit scale"):
        screen._explicit_scale_and_shape(malformed)
    target = paths.image_source / f"{screen.EVAL36[0]}.zarr/linked"
    target.symlink_to(paths.deepcenter_checkpoint)
    run_dir = screen.resolve_run_dir("snapshot", paths)
    with pytest.raises(screen.ScreenError, match="invalid image source"):
        screen._build_image_snapshot(run_dir, paths)


def _fake_arm_runner(order: list[str]):
    def run(run_id: str, arm_name: str, control_sha: str, paths: screen.ScreenPaths) -> int:
        from biohub.public_postproc.pipeline import new_stats

        order.append(arm_name)
        run_dir = screen.resolve_run_dir(run_id, paths)
        control = json.loads((run_dir / "CONTROL.json").read_bytes())
        arm_dir = run_dir / "generation" / arm_name
        arm_dir.mkdir(parents=True)
        datasets = screen.PUBLIC4 if arm_name == "public4_parity" else screen.EVAL36
        _submission(arm_dir / "submission.csv", datasets)
        _write(arm_dir / "run_stats.csv", b"dataset\n")
        _write(arm_dir / "effective_config.json", b"{}\n")
        _write(arm_dir / "deepcenter_receipt.json", b"{}\n")
        active = arm_name in {"dry_run", "candidate"}
        plans = [
            {"dataset": stem, "planner_active": active, "plan": {"validation_reason": None} if active else None}
            for stem in datasets
        ]
        _write(arm_dir / "plans.json", screen.canonical_json_bytes(plans))
        common = []
        for stem in datasets:
            row = {
                "dataset": stem,
                "raw_nodes": 1,
                "nodes": 1,
                "raw_edges": 0,
                "edges": 0,
                "division_like_sources": 0,
                "edge_to_node_ratio": 0.0,
                "gap_added_nodes_frac": 0.0,
                **new_stats(),
            }
            common.append(row)
        _write(arm_dir / "raw_stats.json", screen.canonical_json_bytes(common))
        names = {
            "submission.csv",
            "run_stats.csv",
            "effective_config.json",
            "deepcenter_receipt.json",
            "plans.json",
            "raw_stats.json",
        }
        result = {
            "schema_version": screen.ARM_SCHEMA,
            "status": "SCREEN_ARM_COMPLETE_NOT_SEALED",
            "run_id": run_id,
            "arm_name": arm_name,
            "datasets": list(datasets),
            "control_sha256": control_sha,
            "config_sha256": control["configs"][arm_name]["sha256"],
            "input_bindings": screen._arm_bindings(arm_name, control["initial_inventories"]),
            "process": {
                "pid": control["generation_process"]["pid"] + len(order),
                "parent_pid": control["generation_process"]["pid"],
            },
            "artifacts": {name: _artifact(arm_dir / name) for name in names},
        }
        _write(arm_dir / "ARM_RESULT.json", screen.canonical_json_bytes(result))
        return 0

    return run


def test_generate_runs_fresh_children_in_order_seals_only_screen_and_refuses_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = _paths(tmp_path)
    _fixture_assets(paths)
    monkeypatch.setattr(screen, "DEEPCENTER_CHECKPOINT_SHA256", _artifact(paths.deepcenter_checkpoint)["sha256"])
    monkeypatch.setattr(screen, "DEEPCENTER_MANIFEST_SHA256", _artifact(paths.deepcenter_manifest)["sha256"])
    monkeypatch.setattr(screen, "PUBLIC4_REFERENCE_SHA256", _artifact(paths.public4_reference)["sha256"])
    monkeypatch.setattr(screen, "_source_inventory", lambda _paths: {"records_sha256": "source"})
    monkeypatch.setattr(screen, "_pinned_evidence", lambda _paths: {"pins": "fixed"})
    order: list[str] = []
    result = screen.generate_screen("run-one", paths=paths, arm_runner=_fake_arm_runner(order))
    assert order == list(screen.ARM_ORDER)
    assert result.status == "SCREEN_GENERATION_SEALED"
    seal = json.loads((result.run_dir / "SCREEN_GENERATION_SEALED.json").read_bytes())
    assert seal["status"] == "SCREEN_GENERATION_SEALED"
    assert seal["claims"]["submission_permitted"] is False
    assert "ADOPTION_CANDIDATE" not in json.dumps(seal)
    dry_dir = result.run_dir / "generation/dry_run"
    plans_path = dry_dir / "plans.json"
    plans = json.loads(plans_path.read_bytes())
    plans[0]["planner_active"] = False
    plans_path.write_bytes(screen.canonical_json_bytes(plans))
    with pytest.raises(screen.ScreenError, match="planner activity"):
        screen._validate_arm_telemetry(result.run_dir, "dry_run", paths)
    plans[0]["planner_active"] = True
    plans_path.write_bytes(screen.canonical_json_bytes(plans))
    stats_path = dry_dir / "raw_stats.json"
    stats = json.loads(stats_path.read_bytes())
    stats[0]["steal_twin_validation_failed"] = 1
    stats_path.write_bytes(screen.canonical_json_bytes(stats))
    with pytest.raises(screen.ScreenError, match="counter conservation"):
        screen._validate_arm_telemetry(result.run_dir, "dry_run", paths)
    with pytest.raises(screen.ScreenError, match="resume/overwrite"):
        screen.generate_screen("run-one", paths=paths, arm_runner=_fake_arm_runner([]))


def test_generate_detects_input_change_and_preserves_error_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = _paths(tmp_path)
    _fixture_assets(paths)
    monkeypatch.setattr(screen, "DEEPCENTER_CHECKPOINT_SHA256", _artifact(paths.deepcenter_checkpoint)["sha256"])
    monkeypatch.setattr(screen, "DEEPCENTER_MANIFEST_SHA256", _artifact(paths.deepcenter_manifest)["sha256"])
    monkeypatch.setattr(screen, "PUBLIC4_REFERENCE_SHA256", _artifact(paths.public4_reference)["sha256"])
    monkeypatch.setattr(screen, "_source_inventory", lambda _paths: {"records_sha256": "source"})
    monkeypatch.setattr(screen, "_pinned_evidence", lambda _paths: {"pins": "fixed"})
    base_runner = _fake_arm_runner([])

    def mutating_runner(run_id: str, arm_name: str, control_sha: str, selected: screen.ScreenPaths) -> int:
        result = base_runner(run_id, arm_name, control_sha, selected)
        if arm_name == "candidate":
            _write(selected.raw36 / f"{screen.EVAL36[0]}.geff/payload", b"changed")
        return result

    with pytest.raises(screen.ScreenError, match="input/source changed"):
        screen.generate_screen("mutated", paths=paths, arm_runner=mutating_runner)
    run_dir = screen.resolve_run_dir("mutated", paths)
    assert (run_dir / "GENERATION_ERROR.json").is_file()
    assert not (run_dir / "SCREEN_GENERATION_SEALED.json").exists()


def test_public4_parity_failure_stops_before_any_eval36_arm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = _paths(tmp_path)
    _fixture_assets(paths)
    monkeypatch.setattr(screen, "DEEPCENTER_CHECKPOINT_SHA256", _artifact(paths.deepcenter_checkpoint)["sha256"])
    monkeypatch.setattr(screen, "DEEPCENTER_MANIFEST_SHA256", _artifact(paths.deepcenter_manifest)["sha256"])
    monkeypatch.setattr(screen, "PUBLIC4_REFERENCE_SHA256", _artifact(paths.public4_reference)["sha256"])
    monkeypatch.setattr(screen, "_source_inventory", lambda _paths: {"records_sha256": "source"})
    monkeypatch.setattr(screen, "_pinned_evidence", lambda _paths: {"pins": "fixed"})
    order: list[str] = []
    base_runner = _fake_arm_runner(order)

    def wrong_parity_runner(run_id: str, arm_name: str, control_sha: str, selected: screen.ScreenPaths) -> int:
        result = base_runner(run_id, arm_name, control_sha, selected)
        if arm_name == "public4_parity":
            arm_dir = screen.resolve_run_dir(run_id, selected) / "generation/public4_parity"
            submission = arm_dir / "submission.csv"
            submission.write_text(submission.read_text().replace(",0,-1,-1\n", ",9,-1,-1\n", 1))
            result_path = arm_dir / "ARM_RESULT.json"
            receipt = json.loads(result_path.read_bytes())
            receipt["artifacts"]["submission.csv"] = _artifact(submission)
            result_path.write_bytes(screen.canonical_json_bytes(receipt))
        return result

    with pytest.raises(screen.ScreenError, match="public-four E23 parity failed"):
        screen.generate_screen("bad-parity", paths=paths, arm_runner=wrong_parity_runner)
    assert order == ["public4_parity"]
    run_dir = screen.resolve_run_dir("bad-parity", paths)
    assert not (run_dir / "generation/dry_run").exists()


def _scoring_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[screen.ScreenPaths, str, str]:
    paths = _paths(tmp_path)
    _fixture_assets(paths)
    source = {"records_sha256": "source"}
    dependencies = {"sha256": "dependencies"}
    monkeypatch.setattr(screen, "_source_inventory", lambda _paths: source)
    monkeypatch.setattr(screen, "_dependency_inventory", lambda: dependencies)
    run_id = "score-run"
    run_dir = screen.resolve_run_dir(run_id, paths)
    for arm in ("baseline", "candidate"):
        _submission(run_dir / "generation" / arm / "submission.csv", screen.EVAL36)
    arms = {arm: {"artifacts": {}} for arm in screen.ARM_ORDER}
    for arm in ("baseline", "candidate"):
        arms[arm]["artifacts"]["submission.csv"] = _artifact(run_dir / "generation" / arm / "submission.csv")
    seal = {
        "schema_version": screen.GENERATION_SCHEMA,
        "status": "SCREEN_GENERATION_SEALED",
        "run_id": run_id,
        "datasets": {"eval12": list(screen.EVAL12), "eval24": list(screen.EVAL24), "eval36": list(screen.EVAL36)},
        "arms": arms,
        "input_inventories": {
            "opaque_gt": screen._gt_inventory(paths.gt),
            "source": source,
            "dependencies": dependencies,
        },
        "generation_process": {"pid": os.getpid() + 100_000},
    }
    raw = screen.canonical_json_bytes(seal)
    _write(run_dir / "SCREEN_GENERATION_SEALED.json", raw)
    return paths, run_id, hashlib.sha256(raw).hexdigest()


def _metric_row(dataset: str, improved: bool) -> dict[str, object]:
    if improved:
        edge_tp, edge_fp, edge_fn, division_tp, division_fp, division_fn, adjusted = 95, 5, 5, 2, 0, 0, 0.9
    else:
        edge_tp, edge_fp, edge_fn, division_tp, division_fp, division_fn, adjusted = 90, 10, 10, 1, 1, 1, 0.8
    return {
        "dataset": dataset,
        "edge_tp": edge_tp,
        "edge_fp": edge_fp,
        "edge_fn": edge_fn,
        "division_tp": division_tp,
        "division_fp": division_fp,
        "division_fn": division_fn,
        "num_pred_nodes": 1,
        "node_recall": 1.0,
        "total_node_ratio": 0.0,
        "edge_jaccard": edge_tp / (edge_tp + edge_fp + edge_fn),
        "adj_edge_jaccard": adjusted,
    }


def _datasets_in_csv(path: Path) -> list[str]:
    with path.open(newline="") as handle:
        return list(dict.fromkeys(row["dataset"] for row in csv.DictReader(handle)))


def test_score_stops_after_eval12_failure_without_touching_eval24(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths, run_id, seal_sha = _scoring_run(tmp_path, monkeypatch)
    calls: list[tuple[str, ...]] = []

    def equal_score(csv_path: Path, _gt: Path, _distance: float, _verbose: bool):
        datasets = tuple(_datasets_in_csv(csv_path))
        calls.append(datasets)
        return {}, [_metric_row(stem, False) for stem in datasets]

    result = screen.score_screen(run_id, seal_sha, paths=paths, score_function=equal_score)
    assert result.status == "SCREEN_REJECT_EVAL12"
    assert calls == [screen.EVAL12, screen.EVAL12]
    assert not (result.run_dir / "scores/eval24").exists()
    verdict = json.loads((result.run_dir / "VERDICT.json").read_bytes())
    assert verdict["submission_permitted"] is False


def test_score_rejects_old_schema_and_changed_prediction_before_gt_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths, run_id, _seal_sha = _scoring_run(tmp_path, monkeypatch)
    seal_path = screen.resolve_run_dir(run_id, paths) / "SCREEN_GENERATION_SEALED.json"
    old = json.loads(seal_path.read_bytes())
    old["schema_version"] = "biohub.st_r3.generation_seal.v1"
    seal_path.write_bytes(screen.canonical_json_bytes(old))
    with pytest.raises(screen.ScreenError, match="schema/state"):
        screen.score_screen(run_id, _artifact(seal_path)["sha256"], paths=paths, score_function=lambda *_: ({}, []))

    paths, run_id, seal_sha = _scoring_run(tmp_path / "tamper", monkeypatch)
    candidate = screen.resolve_run_dir(run_id, paths) / "generation/candidate/submission.csv"
    candidate.write_bytes(candidate.read_bytes() + b"\n")
    calls = 0

    def must_not_score(*_args):
        nonlocal calls
        calls += 1
        return {}, []

    with pytest.raises(screen.ScreenError, match="changed before scoring"):
        screen.score_screen(run_id, seal_sha, paths=paths, score_function=must_not_score)
    assert calls == 0


def test_score_rechecks_source_and_requires_a_separate_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths, run_id, seal_sha = _scoring_run(tmp_path, monkeypatch)
    monkeypatch.setattr(screen, "_source_inventory", lambda _paths: {"records_sha256": "changed"})
    with pytest.raises(screen.ScreenError, match="sealed source changed"):
        screen.score_screen(run_id, seal_sha, paths=paths, score_function=lambda *_: ({}, []))

    paths, run_id, _seal_sha = _scoring_run(tmp_path / "same-process", monkeypatch)
    seal_path = screen.resolve_run_dir(run_id, paths) / "SCREEN_GENERATION_SEALED.json"
    seal = json.loads(seal_path.read_bytes())
    seal["generation_process"] = {"pid": os.getpid()}
    seal_path.write_bytes(screen.canonical_json_bytes(seal))
    with pytest.raises(screen.ScreenError, match="separate from generation"):
        screen.score_screen(run_id, _artifact(seal_path)["sha256"], paths=paths, score_function=lambda *_: ({}, []))


def test_score_pass_is_confirmation_only_and_uses_stored_rollup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths, run_id, seal_sha = _scoring_run(tmp_path, monkeypatch)
    calls: list[tuple[str, ...]] = []

    def improved_score(csv_path: Path, _gt: Path, _distance: float, _verbose: bool):
        datasets = tuple(_datasets_in_csv(csv_path))
        calls.append(datasets)
        improved = csv_path.stem == "candidate"
        return {}, [_metric_row(stem, improved) for stem in datasets]

    result = screen.score_screen(run_id, seal_sha, paths=paths, score_function=improved_score)
    assert result.status == "SCREEN_PASS_REQUIRES_CONFIRMATION"
    assert calls == [screen.EVAL12, screen.EVAL12, screen.EVAL24, screen.EVAL24]
    verdict = json.loads((result.run_dir / "VERDICT.json").read_bytes())
    assert verdict["confirmation_required"] is True
    assert verdict["submission_permitted"] is verdict["adoption_permitted"] is False
    assert "ADOPTION_CANDIDATE" not in json.dumps(verdict)


def test_screen_gate_preserves_exact_boundaries_but_never_old_status():
    passing = screen._screen_gate("eval36", {"first_failure": None, "gates": []})
    rejected = screen._screen_gate("eval24", {"first_failure": "paired_worst", "gates": []})
    assert passing["status"] == "SCREEN_PASS_REQUIRES_CONFIRMATION"
    assert rejected["status"] == "SCREEN_REJECT_EVAL24"
    assert passing["submission_permitted"] is False
