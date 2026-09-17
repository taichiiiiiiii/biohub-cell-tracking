"""Synthetic nine-group terminal tree; model source must never execute."""

import copy
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pytest

from biohub.association_capture import FEATURES, MATRICES, PairCapture, _sha
from biohub.association_collection_audit import WORKING, Reader, audit_collection, file_listing_summary
from biohub.association_collection_supervise import check_cumulative
from biohub.association_parity import CFG, E23_ENV, array_signatures, semantic_graph_signature


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return _sha(path)


def graph_fixture():
    coords = np.array([[0, 1, 4, 0], [0, 1, 4, 8], [1, 1, 4, 0], [1, 1, 4, 8]], dtype=np.int16)
    ids = np.array([101, 205, 308, 999], dtype=np.int64)
    graph = {
        "node_node_id": ids,
        **{f"node_{k}": coords[:, i] for i, k in enumerate(("t", "z", "y", "x"))},
        "edge_edge_id": np.array([2, 3], dtype=np.int64),
        "edge_source_id": ids[:2],
        "edge_target_id": ids[2:],
        "edge_edge_prob": np.array([0.75, 0.75], dtype=np.float32),
        "edge_edge_dist": np.zeros(2),
    }
    observed = {**graph, "detector_indices": np.arange(4, dtype=np.int64), "graph_node_ids": ids}
    returned = {"coords": coords, "edges": np.array([[0, 2, 0.75, 0], [1, 3, 0.75, 0]], dtype=np.float64)}
    return returned, graph, observed


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    root = tmp_path_factory.mktemp("collection_terminal")
    returned, graph, observed = graph_fixture()
    counts = [2, 2] + [0] * 98
    source_paths = ["tracking_repo/scripts/e23_observer_on.py"] + [
        f"collection_payload/source{i:02d}.py" for i in range(24)
    ]
    pins = {}
    for relative in source_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raise RuntimeError('synthetic model source must never execute')\n")
        pins[str(WORKING / relative)] = _sha(path)
    groups = [
        {"group_id": f"group{g:02d}", "datasets": [f"video{g * 4 + i:02d}" for i in range(4)], "dense_pairs": 16}
        for g in range(9)
    ]
    expected = {
        "frame_counts": counts,
        "coordinate_sha256": hashlib.sha256(returned["coords"].tobytes()).hexdigest(),
        "raw_graph_signature": semantic_graph_signature(graph),
    }
    reference = {
        "groups": groups,
        "datasets": {n: expected for g in groups for n in g["datasets"]},
        "source_sha256": {"on": pins[str(WORKING / source_paths[0])]},
        "expected_pair_packets": 3564,
        "expected_dense_pairs": 144,
        "limits": {
            "group_wall_seconds": 3600,
            "whole_job_wall_seconds": 14400,
            "rss_bytes": 24 * 1024**3,
            "whole_writer_seconds": 1200,
            "whole_observer_seconds": 1200,
            "dense_pairs_per_run": 450000000,
            "whole_output_bytes": 12 * 1024**3,
        },
    }
    ref_sha = save_json(root / "association_collection_reference.json", reference)
    shared = {str(WORKING / "association_collection_reference.json"): ref_sha}
    deps = {"synthetic": "1"}
    bindings, plans = [], []
    for group in groups:
        gid, names = group["group_id"], group["datasets"]
        split = f"association_collection_plans/{gid}_splits.json"
        split_sha = save_json(root / split, [{"split": 0, "train": [], "test": names}])
        plan = {
            "schema_version": "biohub.association.collection36.group.v1",
            "group_id": gid,
            "reference_path": str(WORKING / "association_collection_reference.json"),
            "datasets": {n: expected for n in names},
            "data_dir": str(WORKING / "association_collection_images" / gid),
            "source_path": str(WORKING / source_paths[0]),
            "source_sha256": reference["source_sha256"]["on"],
            "source_inventory": [{"path": n, "sha256": sha} for n, sha in pins.items()],
            "splits_file": str(WORKING / split),
            "runtime_file_sha256": {**shared, str(WORKING / split): split_sha},
            "primary_weights": str(WORKING / "tracking_repo/weights/unet_transformer/split_0/edge_predictor_best.pth"),
            "submission_authorized": False,
        }
        relative = f"association_collection_plans/{gid}.json"
        sha = save_json(root / relative, plan)
        bindings.append({"group_id": gid, "path": str(WORKING / relative), "sha256": sha})
        plans.append(plan)
    master = {
        "schema_version": "biohub.association.collection36.master.v1",
        "reference_path": str(WORKING / "association_collection_reference.json"),
        "repo_dir": str(WORKING / "tracking_repo"),
        "expected_dependencies": deps,
        "group_plans": bindings,
        "submission_authorized": False,
    }
    master_sha = save_json(root / "association_collection_master.json", master)
    completed, results = [], []
    for group, plan_binding in zip(groups, bindings, strict=True):
        gid, names = group["group_id"], group["datasets"]
        group_root = root / "association_collection_run" / gid
        writer = PairCapture(group_root / "observation/pairs", {n: counts for n in names})
        trace, observer_graphs = [], []
        for name in names:
            for t in range(99):
                ns, nt = counts[t : t + 2]
                arrays = {}
                for side, frame, n in (("source", t, ns), ("target", t + 1, nt)):
                    offset = sum(counts[:frame])
                    arrays[f"{side}_indices"] = np.arange(offset, offset + n, dtype=np.int64)
                    arrays[f"{side}_coords_grid"] = np.array(
                        [[frame, 1, 1, i * 2] for i in range(n)], dtype=np.int16
                    ).reshape(n, 4)
                if ns and nt:
                    for key in MATRICES:
                        arrays[key] = np.array([[0.75, 0.25], [0.25, 0.75]], dtype=np.float32)
                    for key in FEATURES:
                        arrays[key] = np.zeros((ns if "source" in key else nt, 32), dtype=np.float32)
                writer.write_pair(name, t, arrays)
            for stage, arrays in (("returned", returned), ("pre", graph), ("post", graph)):
                np.savez_compressed(group_root / f"{name}_{stage}.npz", **arrays)
                trace.append({"dataset": name, "stage": stage, "arrays": array_signatures(arrays)})
            for stage, arrays in (("pre_ilp", observed), ("post_ilp", graph)):
                path = group_root / "observation" / f"{name}_{stage}.npz"
                np.savez_compressed(path, **arrays)
                observer_graphs.append(
                    {
                        "dataset": name,
                        "stage": stage,
                        "path": path.name,
                        "sha256": _sha(path),
                        "bytes": path.stat().st_size,
                    }
                )
        pair = writer.finish()
        pair_sha = _sha(writer.root / "MANIFEST.json")
        observer = {
            "status": "ASSOCIATION_OBSERVATION_COMPLETE_NOT_PARITY",
            "datasets": names,
            "graph_ID_mapping_complete": True,
            "candidate_threshold": 0.48,
            "candidate_limits": {"parents": None, "children": None},
            "pair_manifest_sha256": pair_sha,
            "observer_seconds_excluding_final_manifest": 1.0,
            "graphs": observer_graphs,
        }
        observer_sha = save_json(group_root / "observation/MANIFEST.json", observer)
        result = {
            "status": "COLLECTION_GROUP_COMPLETE",
            "group_id": gid,
            "plan_sha256": plan_binding["sha256"],
            "source_sha256": reference["source_sha256"]["on"],
            "dataset_order": names,
            "observation_complete": True,
            "records": trace,
            "pair_count": 396,
            "dense_pairs": 16,
            "environment": E23_ENV,
            "model_config": CFG,
            "submission_authorized": False,
            "generalization_evidence": False,
            "reference_sha256": ref_sha,
            "reference_raw_matched": True,
            "dependencies": deps,
            "paired_off_on_this_group": False,
            "wall_seconds": 1.0,
            "writer_seconds": pair["writer_seconds"],
            "observer_seconds": 1.0,
            "peak_self_rss_bytes": 1,
            "packet_bytes": pair["packet_bytes"],
            "observer_manifest_sha256": observer_sha,
            "pair_manifest_sha256": pair_sha,
            "input_inventory": [
                {"path": f"{n}.zarr/{p}", "bytes": 1, "sha256": "0" * 64}
                for n in names
                for p in ("zarr.json", "0/c/0/0/0/0")
            ],
        }
        result_sha = save_json(group_root / "RESULT.json", result)
        process = {"returncode": 0, "error": None, "wall_seconds": 1.0, "peak_sampled_tree_rss_bytes": 1}
        save_json(root / f"association_collection_run/{gid}_PROCESS.json", process)
        results.append(result)
        completed.append({"group_id": gid, "datasets": names, "result_sha256": result_sha, "process": process})
        totals = check_cumulative(results, reference["limits"])
        save_json(
            root / f"association_collection_run/{gid}_PROGRESS.json",
            {
                "status": "COLLECTION_PARTIAL",
                "completed_groups": completed,
                "totals": totals,
                "submission_authorized": False,
            },
        )
    terminal = {
        "status": "COLLECTION36_COMPLETE_REFERENCE_MATCHED",
        "master_sha256": master_sha,
        "reference_sha256": ref_sha,
        "submission_authorized": False,
        "generalization_evidence": False,
        "paired_off_on_all36": False,
        "gt_scored": False,
        "training_started": False,
        "completed_groups": completed,
        "totals": totals,
        "wall_seconds_including_setup": 10.0,
    }
    save_json(root / "association_collection_run/RESULT.json", terminal)
    lines = [f"D3 COLLECTION MASTER SEALED {master_sha}\n"]
    for group in groups:
        lines += [
            f"D3 COLLECTION_STARTED {group['group_id']} PID 1\n",
            f"D3 COLLECTION_FINISHED {group['group_id']} exit=0\n",
        ]
    lines.append("COLLECTION36_COMPLETE_REFERENCE_MATCHED\n")
    save_json(root / "biohub-e23-association-collection36.log", [{"data": s, "time": i} for i, s in enumerate(lines)])
    listing = [
        {"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size}
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "biohub-e23-association-collection36.log"
    ]
    return SimpleNamespace(
        root=root,
        reference=reference,
        ref_sha=ref_sha,
        master_sha=master_sha,
        pins=pins,
        deps=deps,
        shared=shared,
        listing=listing,
        log_sha=_sha(root / "biohub-e23-association-collection36.log"),
    )


def run(tree, listing=None):
    return audit_collection(
        tree.root,
        tree.reference,
        tree.ref_sha,
        tree.master_sha,
        tree.pins,
        tree.deps,
        tree.shared,
        tree.listing if listing is None else listing,
        tree.log_sha,
    )


def test_complete_actual_synthetic_nine_group_tree(tree):
    result = run(tree)
    assert result["status"] == "COLLECTION36_ARTIFACT_AUDIT_PASS" and len(result["videos"]) == 36
    assert result["totals"]["pair_count"] == result["output_inventory"]["matrix_packet_file_count"] == 3564
    assert result["totals"]["dense_pairs"] == 144 and result["matrix_packets_reloaded_locally"] == 0
    assert not result["weights_images_rehashed_locally"] and not result["submission_authorized"]


@contextmanager
def changed_json(path, change):
    original = path.read_bytes()
    value = json.loads(original)
    change(value)
    path.write_text(json.dumps(value))
    try:
        yield
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize(
    "case",
    [
        "master",
        "partial",
        "final_total",
        "process",
        "progress",
        "dependency",
        "trace",
        "log",
        "packet_missing",
        "packet_size",
        "error_file",
        "extra_source",
    ],
)
def test_incomplete_or_changed_collection_rejected(tree, case):
    listing = copy.deepcopy(tree.listing)
    if case in ("packet_missing", "packet_size"):
        index = next(
            i for i, r in enumerate(listing) if "/observation/pairs/" in r["path"] and r["path"].endswith(".npz")
        )
        if case == "packet_missing":
            listing.pop(index)
        else:
            listing[index]["bytes"] += 1
        with pytest.raises(ValueError):
            run(tree, listing)
        return
    if case in ("error_file", "extra_source"):
        path = tree.root / (
            "association_collection_run/ERROR.json" if case == "error_file" else "collection_payload/extra.py"
        )
        path.write_text("{}")
        try:
            listing.append({"path": path.relative_to(tree.root).as_posix(), "bytes": 2})
            with pytest.raises(ValueError):
                run(tree, listing)
        finally:
            path.unlink()
        return
    path, change = {
        "master": ("association_collection_master.json", lambda d: d.update(submission_authorized=True)),
        "partial": ("association_collection_run/RESULT.json", lambda d: d.update(status="COLLECTION_PARTIAL")),
        "final_total": ("association_collection_run/RESULT.json", lambda d: d["totals"].update(dense_pairs=145)),
        "process": ("association_collection_run/group00_PROCESS.json", lambda d: d.update(returncode=1)),
        "progress": ("association_collection_run/group00_PROGRESS.json", lambda d: d.update(completed_groups=[])),
        "dependency": ("association_collection_run/group00/RESULT.json", lambda d: d.update(dependencies={})),
        "trace": ("association_collection_run/group00/RESULT.json", lambda d: d["records"][0].update(arrays={})),
        "log": ("biohub-e23-association-collection36.log", lambda d: d.pop()),
    }[case]
    with changed_json(tree.root / path, change), pytest.raises(ValueError):
        run(tree, listing)


def test_changed_runtime_file_is_not_imported(tree):
    path = tree.root / "collection_payload/source00.py"
    original = path.read_bytes()
    path.write_text("raise RuntimeError('changed source must not execute')")
    try:
        with pytest.raises(ValueError, match="hash mismatch"):
            run(tree)
    finally:
        path.write_bytes(original)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../../escape"])
def test_reader_refuses_unsafe_paths(tmp_path, name):
    with pytest.raises(ValueError):
        Reader(tmp_path).path(name)


def test_inventory_does_not_hide_noncollection_output_capacity():
    packets = {"association_collection_run/group00/observation/pairs/v/pair_0000.npz": 100}
    listing = [{"path": k, "bytes": v} for k, v in packets.items()] + [{"path": "image_view/chunk", "bytes": 900}]
    r = file_listing_summary(listing, packets, 100)
    assert r["collection_root_bytes"] == 100 and r["all_working_output_bytes"] == 1000
    with pytest.raises(ValueError, match="budget"):
        file_listing_summary(listing, packets, 99)
