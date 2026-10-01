"""Preparation-only input screen for the E27 association prior experiment."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

REFERENCE = "outputs/local/e23_association_collection_20260908/REFERENCE_PLAN.json"
REFERENCE_SHA = "08395ca8615b6eeaaaeec521cd937c62d2212b7a20cf18be1a27478afd4af7ac"
AUDIT = "outputs/local/e23_association_collection_audit_20260908/REAL_COLLECTION_AUDIT_20260912.json"
AUDIT_SHA = "e56db2ab1d9a79a94d8ed97d1b02d9d6391713caf842a2672a0777419391e70a"
BASELINE = (
    "outputs/local/e26_screen/"
    "e26_motion_off_screen_v2_20260908073709Z/generation/baseline/CHILD_CONTROL.json"
)
BASELINE_SHA = "f3b6d4ef13d8d2a22cc97474a77235c7287fd0bf1881dd60a66a406767d91aa4"
COLLECTION_ROOT = ROOT / "outputs/local/e23_collection_verified_20260912"

STEMS = (
    "44b6_12dfb391",
    "44b6_267148e4",
    "44b6_2a2eff9f",
    "44b6_341df25f",
    "44b6_587a1e22",
    "44b6_5f15d135",
    "6bba_062c8d37",
    "6bba_07e24132",
    "6bba_085bf656",
    "6bba_09961292",
    "6bba_0e7c0d07",
    "6bba_12665c0e",
)


def build_prior_inputs(prepared, mode):
    """Return (mapping, receipt) for the requested prior-injection mode."""
    if type(mode) is not str or mode not in (
        "baseline_none",
        "selected_only",
        "recorded_prior",
    ):
        raise ValueError(f"invalid mode: {mode!r}")

    datasets = prepared["datasets"]
    raw_paths = prepared["raw_paths"]
    priors_by_dataset = prepared["priors_by_dataset"]

    if type(datasets) is not list or datasets != list(STEMS):
        raise ValueError("prepared datasets must equal STEMS")
    if type(raw_paths) is not list or len(raw_paths) != len(STEMS):
        raise ValueError("prepared raw_paths must match STEMS length")
    if [p.stem for p in raw_paths] != list(STEMS):
        raise ValueError("prepared raw_paths stems must match STEMS order")
    if type(priors_by_dataset) is not dict:
        raise ValueError("priors_by_dataset must be a dict")
    if set(priors_by_dataset) != set(STEMS):
        raise ValueError("priors_by_dataset keys must exactly match STEMS")
    for stem in STEMS:
        pre = priors_by_dataset[stem]
        if type(pre) is not dict:
            raise ValueError(f"priors for {stem} must be a dict")
        for pair, prob in pre.items():
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError(f"prior key for {stem} must be a 2-tuple")
            if type(pair[0]) is not int or type(pair[1]) is not int:
                raise ValueError(f"prior ids for {stem} must be builtin ints")
            if type(prob) not in (int, float) or not 0.0 <= prob <= 1.0:
                raise ValueError(f"prior probability for {stem} invalid")

    mapping = None
    counts = {stem: 0 for stem in STEMS}
    novel_counts = {stem: 0 for stem in STEMS}
    entries = []

    if mode != "baseline_none":
        from biohub.public_postproc.pipeline import (
            _load_geff_as_dicts,
            _unselected_association_priors,
        )

        mapping = {}
        total_novel = 0
        for stem, path in zip(STEMS, raw_paths, strict=True):
            pre = priors_by_dataset[stem]
            nodes, edges = _load_geff_as_dicts(path)
            _unselected_association_priors(pre, edges, nodes)
            selected = {}
            for edge in edges:
                pair = (edge["source_id"], edge["target_id"])
                if pair in selected:
                    raise ValueError(f"duplicate edge pair in {stem}: {pair}")
                prob = edge["edge_prob"]
                if prob is None or pair not in pre or prob != pre[pair]:
                    raise ValueError(f"edge prior mismatch in {stem}: {pair}")
                selected[pair] = prob
            dataset_map = selected.copy() if mode == "selected_only" else pre.copy()
            novel = _unselected_association_priors(dataset_map, edges, nodes)
            total_novel += len(novel)
            inner = {}
            for pair, prob in sorted(dataset_map.items()):
                inner[pair] = prob
                entries.append([stem, pair[0], pair[1], prob])
            mapping[stem] = inner
            counts[stem] = len(inner)
            novel_counts[stem] = len(novel)
            if mode == "selected_only" and novel:
                raise ValueError(f"selected_only left unselected pairs in {stem}")
        if mode == "recorded_prior" and total_novel == 0:
            raise ValueError("recorded_prior produced no eligible unselected pairs")

    envelope = {"mode": mode, "datasets": list(STEMS), "entries": entries}
    payload = json.dumps(
        envelope, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    receipt = {
        "mode": mode,
        "datasets": list(STEMS),
        "entries_by_dataset": counts,
        "eligible_unselected_by_dataset": novel_counts,
        "sha256": digest,
    }
    return mapping, receipt


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(name: str, sha: str) -> dict:
    path = ROOT / name
    if _sha(path) != sha:
        raise ValueError(f"hash mismatch for {name}")
    payload = json.loads(path.read_text())
    if _sha(path) != sha:
        raise ValueError(f"hash drift for {name}")
    return payload


def prepare_inputs() -> dict:
    from biohub.association_artifact_audit import _canonical_graph, _edge_values
    from biohub.association_collection_audit import Reader
    from biohub.association_parity import semantic_graph_signature
    from scripts.experiments.e23.prepare_e23_association_parity import raw_signature

    reference = _load(REFERENCE, REFERENCE_SHA)
    audit = _load(AUDIT, AUDIT_SHA)
    baseline = _load(BASELINE, BASELINE_SHA)

    if audit["status"] != "COLLECTION36_ARTIFACT_AUDIT_PASS":
        raise ValueError("audit status is not a pass")
    if baseline["arm"] != "baseline" or baseline["config"]["OUTPUT_MOTION_RELINK"] is not True:
        raise ValueError("baseline control identity/config rejected")
    bindings = audit["bindings"]

    groups = {}
    for group in reference["groups"]:
        for stem in group["datasets"]:
            if stem in groups:
                raise ValueError(f"dataset {stem} appears in multiple groups")
            groups[stem] = group
    diagnostic = set(reference["diagnostic12"])
    if diagnostic != set(STEMS):
        raise ValueError("reference diagnostic12 does not match the fixed STEM set")
    by_group = {}
    for group in reference["groups"]:
        by_group[group["group_id"]] = group
    for stage in ("group00", "group01", "group02"):
        found = by_group.get(stage)
        if found is None or found["stage"] != "diagnostic12":
            raise ValueError(f"missing diagnostic12 group {stage}")

    inv_root = (ROOT / reference["raw_inventory"]["root"]).resolve()
    eval36 = baseline["generation_input_binding"]["eval36"]
    if inv_root != Path(eval36["raw_inventory"]["selected_path"]).resolve():
        raise ValueError("raw inventory root disagrees with baseline binding")
    if ROOT not in inv_root.parents:
        raise ValueError("raw inventory root must be strictly below repository")

    videos = {}
    for video in eval36["videos"]:
        stem = video["dataset"]
        if stem in videos:
            raise ValueError(f"duplicate baseline video for {stem}")
        videos[stem] = video

    reader = Reader(COLLECTION_ROOT)
    datasets, priors_by_dataset, raw_paths, shapes = [], {}, [], {}
    for stem in STEMS:
        owner = groups[stem]
        if owner["stage"] != "diagnostic12":
            raise ValueError(f"{stem} belongs to non-diagnostic12 group {owner['group_id']}")
        group = owner["group_id"]
        video = videos[stem]
        rel = {
            kind: f"association_collection_run/{group}/observation/{stem}_{kind}_ilp.npz"
            for kind in ("pre", "post")
        }
        arrays = {}
        for kind, path in rel.items():
            recorded = bindings[path]["sha256"]
            size = bindings[path]["bytes"]
            actual = COLLECTION_ROOT / path
            if actual.stat().st_size != size:
                raise ValueError(f"size mismatch for {path}")
            arrays[kind] = reader.arrays(path, recorded)
        canonical = {kind: _canonical_graph(arrays[kind]) for kind in ("pre", "post")}

        raw = inv_root / f"{stem}.geff"
        post_sig = semantic_graph_signature(canonical["post"])
        if post_sig != reference["datasets"][stem]["raw_graph_signature"]:
            raise ValueError(f"post graph signature mismatch for {stem}")
        if post_sig != raw_signature(raw):
            raise ValueError(f"raw geff signature mismatch for {stem}")

        pre, post = canonical["pre"], canonical["post"]
        positions = {}
        for t, z, y, x, node in zip(
            pre["node_t"], pre["node_z"], pre["node_y"], pre["node_x"], pre["node_node_id"], strict=True
        ):
            key = int(node)
            pos = (int(t), float(z), float(y), float(x))
            if positions.setdefault(key, pos) != pos:
                raise ValueError(f"inconsistent node map for {stem}")
        for t, z, y, x, node in zip(
            post["node_t"], post["node_z"], post["node_y"], post["node_x"], post["node_node_id"], strict=True
        ):
            pos = (int(t), float(z), float(y), float(x))
            if positions.get(int(node)) != pos:
                raise ValueError(f"post node moved outside pre positions for {stem}")

        pre_edges = _edge_values(pre)
        for (source, target), (prob, distance) in pre_edges.items():
            if source not in positions or target not in positions:
                raise ValueError(f"unknown edge endpoint in pre graph for {stem}")
            if positions[source][0] + 1 != positions[target][0]:
                raise ValueError(f"non-adjacent pre edge for {stem}")
            if not 0.48 < prob <= 1.0 or distance < 0:
                raise ValueError(f"invalid pre edge value for {stem}")
        post_edges = _edge_values(post)
        for pair, post_value in post_edges.items():
            if pair not in pre_edges:
                raise ValueError(f"post edge {pair} absent from pre edges for {stem}")
            if pre_edges[pair] != post_value:
                raise ValueError(f"post edge value differs from pre for {stem}")

        priors_by_dataset[stem] = {pair: float(prob) for pair, (prob, _) in pre_edges.items()}
        shapes[stem] = tuple(video["metadata"]["shape_tzyx"])
        datasets.append(stem)
        raw_paths.append(raw)

    reader.recheck()
    metadata_bindings = {
        name: {
            "path": str((ROOT / name).resolve()),
            "bytes": (ROOT / name).stat().st_size,
            "sha256": sha,
        }
        for name, sha in ((REFERENCE, REFERENCE_SHA), (AUDIT, AUDIT_SHA), (BASELINE, BASELINE_SHA))
    }
    for name, record in metadata_bindings.items():
        path = Path(record["path"])
        if path.stat().st_size != record["bytes"] or _sha(path) != record["sha256"]:
            raise ValueError(f"final binding mismatch for {name}")

    return {
        "datasets": datasets,
        "priors_by_dataset": priors_by_dataset,
        "raw_paths": raw_paths,
        "shapes": shapes,
        "baseline_control": baseline,
        "reader_bindings": dict(reader.bindings),
        "metadata_bindings": metadata_bindings,
        "status": "INPUTS_PREPARED_NOT_GENERATED",
        "image_payloads_verified": False,
        "weights_loaded": False,
        "gt_read": False,
    }


def verify_prepared_materials(prepared):
    """Verify prepared materials without opening remaining images or GT."""
    import dataclasses

    import biohub.e26_screen as e
    from biohub.io import open_volume

    c = prepared["baseline_control"]
    if c["arm"] != "baseline":
        raise ValueError("baseline_control arm is not baseline")
    if tuple(prepared["datasets"]) != STEMS:
        raise ValueError("prepared datasets do not match STEMS")
    shapes = prepared["shapes"]
    if set(shapes) != set(STEMS):
        raise ValueError("prepared shapes keys do not match STEMS")

    e.verify_dependency_binding(c["dependency_binding"])

    gib = c["generation_input_binding"]
    for key in ("checkpoint", "manifest"):
        e.verify_inventory(gib[key])

    eval36 = gib["eval36"]
    e.verify_inventory(eval36["raw_inventory"])

    seen = set()
    for video in eval36["videos"]:
        stem = video["dataset"]
        if stem not in STEMS:
            continue
        if stem in seen:
            raise ValueError(f"duplicate eval36 dataset {stem}")
        seen.add(stem)
        inv = video["image_inventory"]
        path = Path(inv["selected_path"])
        e.verify_inventory(inv)
        meta = video["metadata"]
        vol = open_volume(path)
        got_shape = tuple(vol.shape)
        want_shape = tuple(meta["shape_tzyx"])
        if got_shape != want_shape:
            raise ValueError(f"{path} shape {got_shape} != {want_shape}")
        if tuple(vol.scale) != tuple(meta["scale_zyx"]):
            raise ValueError(f"{path} scale {vol.scale} != {meta['scale_zyx']}")
        if str(vol.dtype) != meta["dtype"]:
            raise ValueError(f"{path} dtype {vol.dtype} != {meta['dtype']}")
        if tuple(shapes[stem]) != want_shape:
            raise ValueError(f"prepared.shapes[{stem}] inconsistent with {want_shape}")
    if seen != set(STEMS):
        missing = sorted(set(STEMS) - seen)
        raise ValueError(f"eval36 videos missing datasets {missing}")

    cfg = e._child_config(c)
    fields = {f.name: f for f in dataclasses.fields(cfg)}
    serialized = {}
    for name, _field in fields.items():
        value = getattr(cfg, name)
        serialized[name] = str(value) if isinstance(value, Path) else value
    if serialized != c["config"]:
        raise ValueError("baseline_control config does not round-trip")
    if cfg.OUTPUT_MOTION_RELINK is not True:
        raise ValueError("OUTPUT_MOTION_RELINK is not True")

    for rel, binding in prepared["metadata_bindings"].items():
        p = Path(binding["path"])
        if not p.is_absolute():
            raise ValueError(f"metadata binding {rel} is not absolute")
        size = p.stat().st_size
        if size != int(binding["bytes"]):
            raise ValueError(f"{p} bytes {size} != {binding['bytes']}")
        digest = _sha(p)
        if digest != binding["sha256"]:
            raise ValueError(f"{p} sha256 {digest} != {binding['sha256']}")

    for rel, binding in prepared["reader_bindings"].items():
        p = (COLLECTION_ROOT / rel).resolve(strict=True)
        root = COLLECTION_ROOT.resolve()
        if root != p.parent and root not in p.parents:
            raise ValueError(f"reader binding {rel} resolves outside COLLECTION_ROOT")
        size = p.stat().st_size
        if size != int(binding["bytes"]):
            raise ValueError(f"{p} bytes {size} != {binding['bytes']}")
        digest = _sha(p)
        if digest != binding["sha256"]:
            raise ValueError(f"{p} sha256 {digest} != {binding['sha256']}")

    return cfg


def validate_known12_statistics(raw_rows: list[dict], *, arm: str, csv_report: dict) -> list[dict]:
    """Validate E27 baseline raw telemetry for the fixed known-12 STEMS subset.

    Frozen E26 `validate_raw_statistics` is deliberately not edited or reused: it
    requires a full 36-dataset arm, whereas this screen's baseline arm finished on
    exactly the 12 physical STEMS videos whose CSV bytes match the baseline. Every
    structural, type, count, ratio and motion check from E26 is preserved; only the
    arm gate and the dataset cardinality are corrected for this local use.

    The caller must retain the original raw mappings as well as this normalized
    result. No pandas conversion, GT access or graph-size equality between arms.
    """
    from biohub.e26_screen import (
        _RAW_RATIO_KEYS,
        _RAW_REQUIRED_KEYS,
        E26Error,
        _require_count,
        _require_finite_number,
        _require_keys,
    )

    if type(arm) is not str or arm not in ("baseline", "e29"):
        raise E26Error("known12 validation accepts baseline arm only")
    datasets = STEMS
    _require_keys(csv_report, {"datasets", "total_rows", "total_nodes", "total_edges", "per_dataset"}, "csv_report")
    if (
        type(csv_report["datasets"]) is not list
        or any(type(name) is not str for name in csv_report["datasets"])
        or csv_report["datasets"] != list(datasets)
    ):
        raise E26Error("CSV report dataset order differs from the known-12 STEMS")
    counts = csv_report["per_dataset"]
    if type(counts) is not list or len(counts) != len(datasets):
        raise E26Error("CSV report per_dataset count mismatch")
    for index, (row, name) in enumerate(zip(counts, datasets, strict=True)):
        _require_keys(row, {"dataset", "nodes", "edges", "forks"}, f"csv_report[{index}]")
        if type(row["dataset"]) is not str or row["dataset"] != name:
            raise E26Error("CSV report per_dataset order mismatch")
        for key in ("nodes", "edges", "forks"):
            _require_count(row[key], f"{name}.{key}")
        if row["nodes"] == 0:
            raise E26Error(f"{name}: CSV report has no nodes")
    for total, field in (("total_nodes", "nodes"), ("total_edges", "edges")):
        _require_count(csv_report[total], total)
        if csv_report[total] != sum(row[field] for row in counts):
            raise E26Error(f"CSV report {total} is inconsistent")
    _require_count(csv_report["total_rows"], "total_rows")
    if csv_report["total_rows"] != csv_report["total_nodes"] + csv_report["total_edges"]:
        raise E26Error("CSV report total_rows is inconsistent")
    if type(raw_rows) is not list or len(raw_rows) != len(datasets):
        raise E26Error("raw statistics must contain exactly one row per STEMS dataset")

    normalized = []
    optional = "gap_close_effective_max_gap"
    allowed = {_RAW_REQUIRED_KEYS, _RAW_REQUIRED_KEYS | {optional}}
    e34_optional = {"motion_relink_bidirectional_kept", "motion_relink_bidirectional_rejected"}
    allowed |= {
        _RAW_REQUIRED_KEYS | e34_optional,
        _RAW_REQUIRED_KEYS | {optional} | e34_optional,
        _RAW_REQUIRED_KEYS | e34_optional | {"motion_relink_consensus_reserved_edges"},
        _RAW_REQUIRED_KEYS | {optional} | e34_optional | {"motion_relink_consensus_reserved_edges"},
    }
    if arm == "e29":
        allowed |= {
            _RAW_REQUIRED_KEYS | {"motion_relink_consensus_reserved_edges"},
            _RAW_REQUIRED_KEYS | {optional, "motion_relink_consensus_reserved_edges"},
        }
    for index, (row, dataset, count) in enumerate(zip(raw_rows, datasets, counts, strict=True)):
        if type(row) is not dict or set(row) not in allowed:
            raise E26Error(f"raw statistics[{index}]: missing or unexpected keys")
        if type(row["dataset"]) is not str or row["dataset"] != dataset:
            raise E26Error("raw statistics dataset order mismatch")
        for key, value in row.items():
            if key == "dataset":
                continue
            if key in _RAW_RATIO_KEYS:
                _require_finite_number(value, f"{dataset}.{key}", json_number=True)
                if value < 0:
                    raise E26Error(f"{dataset}.{key} must be nonnegative")
            else:
                _require_count(value, f"{dataset}.{key}", signed=key == "gap_density_step_delta_milli_sum")
        for raw_key, csv_key in (("nodes", "nodes"), ("edges", "edges"), ("division_like_sources", "forks")):
            if row[raw_key] != count[csv_key]:
                raise E26Error(f"{dataset}: {raw_key} differs from reparsed CSV")
        motion_components = row["motion_relink_tight_edges"] + row["motion_relink_relaxed_edges"]
        if arm == "e29":
            motion_components += row.get("motion_relink_consensus_reserved_edges", 0)
        if motion_components != row["motion_relink_edges"]:
            raise E26Error(f"{dataset}: motion edge component counts differ")
        fallback = row["motion_relink_fallback_raw"]
        skipped = row["motion_relink_skipped_large_frame"]
        motion_edges = row["motion_relink_edges"]
        replaced = row["motion_relink_replaced_raw_edges"]
        if fallback not in (0, 1) or skipped not in (0, 1):
            raise E26Error(f"{dataset}: motion fallback/skip must be binary")
        if fallback != int(motion_edges == 0):
            raise E26Error(f"{dataset}: enabled motion fallback inconsistent with edge count")
        if skipped and (motion_edges != 0 or fallback != 1):
            raise E26Error(f"{dataset}: skipped-large motion must fall back with zero motion edges")
        if fallback and replaced != 0:
            raise E26Error(f"{dataset}: fallback cannot replace raw edges")
        if replaced > row["raw_edges"]:
            raise E26Error(f"{dataset}: motion replacement exceeds raw edges")
        output = dict(row)
        output["gap_close_effective_max_gap_absence_reason"] = None if optional in row else "not_emitted_by_core"
        if optional not in row:
            output[optional] = None
        normalized.append(output)
    return normalized


def prepare_appearance_plan():
    from biohub.association_capture import COORDINATES, FEATURES
    from biohub.association_collection_audit import Reader

    ref = _load(REFERENCE, REFERENCE_SHA)
    audit = _load(AUDIT, AUDIT_SHA)
    if audit.get("status") != "COLLECTION36_ARTIFACT_AUDIT_PASS":
        raise ValueError("audit status not COLLECTION36_ARTIFACT_AUDIT_PASS")
    diag12 = ref["diagnostic12"]
    if set(diag12) != set(STEMS):
        raise ValueError("reference diagnostic12 does not match STEMS")

    groups = ref["groups"]
    if type(groups) is not list:
        raise ValueError("reference groups must be a list")
    groups_selected = {}
    seen_datasets = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError(f"group entry not a dict: {group!r}")
        group_id = group["group_id"]
        stage = group["stage"]
        datasets = group["datasets"]
        if type(datasets) is not list:
            raise ValueError(f"{group_id}: datasets must be a list")
        for stem in datasets:
            if stem in seen_datasets:
                raise ValueError(f"duplicate dataset {stem}")
            seen_datasets.append(stem)
        selected_here = [stem for stem in datasets if stem in diag12]
        if group_id not in ("group00", "group01", "group02"):
            if selected_here:
                raise ValueError(f"{group_id}: diagnostic12 dataset in non-selected group")
            continue
        if stage != "diagnostic12":
            raise ValueError(f"{group_id}: selected group stage {stage} != diagnostic12")
        for stem in datasets:
            if stem in diag12:
                groups_selected[stem] = group_id
    if set(groups_selected) != set(STEMS):
        missing = sorted(set(STEMS) - set(groups_selected))
        raise ValueError(f"diagnostic12 datasets without group00..02 assignment: {missing}")

    reader = Reader(COLLECTION_ROOT)
    bindings_by_dataset = {}
    original_signatures = {}
    for stem in STEMS:
        base = f"association_collection_run/{groups_selected[stem]}"
        paths = {
            "returned": f"{base}/{stem}_returned.npz",
            "pre_ilp": f"{base}/observation/{stem}_pre_ilp.npz",
            "observer": f"{base}/observation/MANIFEST.json",
            "pairs": f"{base}/observation/pairs/MANIFEST.json",
        }
        bindings = {}
        for key, rel in paths.items():
            entry = audit["bindings"].get(rel)
            if not isinstance(entry, dict):
                raise ValueError(f"{stem}: missing audit binding {rel}")
            sha = entry["sha256"]
            path = reader.bind(rel, sha)
            size = path.stat().st_size
            if size != entry["bytes"]:
                raise ValueError(f"{stem}: {key} bytes {size} != audit {entry['bytes']}")
            bindings[rel] = {"bytes": entry["bytes"], "sha256": sha}

        obs = reader.json(paths["observer"], bindings[paths["observer"]]["sha256"])
        pairs = reader.json(paths["pairs"], bindings[paths["pairs"]]["sha256"])
        if obs["pair_manifest_sha256"] != bindings[paths["pairs"]]["sha256"]:
            raise ValueError(f"{stem}: observer pair_manifest_sha256 mismatch")
        if (pairs.get("schema_version") != "biohub.e23.association_capture.v1"
                or pairs.get("status") != "PAIR_CAPTURE_COMPLETE"
                or pairs.get("submission_authorized") is not False):
            raise ValueError(f"{stem}: pair manifest schema_version/status/authorization mismatch")

        records = [r for r in pairs["records"] if r["dataset"] == stem]
        sources = [r["t_source"] for r in records]
        if len(records) != 99 or len(set(sources)) != 99:
            raise ValueError(f"{stem}: expected 99 unique records")
        by_source = {}
        for rec in records:
            t = rec["t_source"]
            if type(t) is not int or not 0 <= t <= 98:
                raise ValueError(f"{stem}: bad t_source {t}")
            if type(rec["t_target"]) is not int or rec["t_target"] != t + 1:
                raise ValueError(f"{stem}: bad t_target for t_source {t}")
            expect = f"{stem}/pair_{t:04d}.npz"
            if rec["path"] != expect:
                raise ValueError(f"{stem}: record path {rec['path']} != {expect}")
            nbytes = rec["bytes"]
            rsha = rec["sha256"]
            if type(nbytes) is not int or nbytes <= 0:
                raise ValueError(f"{stem}: bad record bytes for {expect}")
            if (not isinstance(rsha, str) or len(rsha) != 64
                    or any(c not in "0123456789abcdef" for c in rsha)):
                raise ValueError(f"{stem}: bad record sha256 for {expect}")
            status = rec["status"]
            n_source = rec["n_source"]
            n_target = rec["n_target"]
            arrays = rec["arrays"]
            if status == "SKIPPED_EMPTY":
                if (type(n_source) is not int or type(n_target) is not int
                        or n_source < 0 or n_target < 0
                        or (n_source != 0 and n_target != 0)):
                    raise ValueError(f"{stem}: empty packet counts {expect} inconsistent")
                if not isinstance(arrays, dict) or set(arrays) != set(COORDINATES):
                    raise ValueError(f"{stem}: empty packet arrays {expect} keys")
                by_source[t] = rec
                continue
            if status != "OBSERVED":
                raise ValueError(f"{stem}: bad record status {status!r} for {expect}")
            for name, count in (("n_source", n_source), ("n_target", n_target)):
                if type(count) is not int or count <= 0:
                    raise ValueError(f"{stem}: bad {name} {count!r} for {expect}")
            if not isinstance(arrays, dict) or not set(FEATURES).issubset(arrays):
                raise ValueError(f"{stem}: record arrays missing canonical features")
            by_source[t] = rec
        if sorted(by_source) != list(range(99)):
            raise ValueError(f"{stem}: t_source coverage not 0..98")

        for t in range(99):
            rec = by_source[t]
            rel = base + "/observation/pairs/" + rec["path"]
            bindings[rel] = {"bytes": rec["bytes"], "sha256": rec["sha256"]}
        bindings_by_dataset[stem] = bindings
        original_signatures[stem] = [
            None if by_source[t]["status"] == "SKIPPED_EMPTY"
            else {k: by_source[t]["arrays"][k] for k in FEATURES}
            for t in range(99)]

    reader.recheck()
    return {
        "schema": "E28_APPEARANCE_PLAN_V1",
        "candidate_id": "E28_APPEARANCE_COST_V1",
        "coefficient_um": 1.0,
        "datasets": list(STEMS),
        "dataset_groups": groups_selected,
        "bindings_by_dataset": bindings_by_dataset,
        "original_signatures": original_signatures,
        "reference_sha256": REFERENCE_SHA,
        "audit_sha256": AUDIT_SHA,
        "collection_root": str(COLLECTION_ROOT.resolve()),
    }


def verify_appearance_receipts(plan, receipts, check_budget):
    from biohub.association_capture import FEATURES, _require
    from biohub.association_collection_audit import Reader

    check_budget()
    if (isinstance(receipts, list) and receipts and
            isinstance(receipts[0], dict) and
            receipts[0].get("schema") in (
                "E29_CONSENSUS_INPUT_RECEIPT_V1",
                "E30_POSITIVE_CONSENSUS_INPUT_RECEIPT_V1",
                "E31_PRIMARY_CONSENSUS_INPUT_RECEIPT_V1",
                "E33_SHORT_TRACK_CONSENSUS_INPUT_RECEIPT_V1",
            )):
        return verify_consensus_receipts(plan, receipts, check_budget)
    fresh = prepare_appearance_plan()
    if plan != fresh:
        raise ValueError("plan does not match freshly prepared appearance plan")

    _require(type(receipts) is list and len(receipts) == len(STEMS),
             f"receipts must be a list of {len(STEMS)}")
    for receipt, stem in zip(receipts, STEMS, strict=True):
        _require(type(receipt) is dict, f"{stem}: receipt not a dict")
        _require(receipt["dataset"] == stem, f"{stem}: receipt dataset mismatch")
        _require(receipt["group"] == plan["dataset_groups"][stem],
                 f"{stem}: receipt group mismatch")
        _require(type(receipt["packet_count"]) is int
                 and receipt["packet_count"] == 99, f"{stem}: packet_count != 99")
        _require(receipt["gt_read"] is False, f"{stem}: gt_read must be False")
        _require(receipt["weights_loaded"] is False,
                 f"{stem}: weights_loaded must be False")

    for receipt, stem in zip(receipts, STEMS, strict=True):
        reader = Reader(COLLECTION_ROOT)
        want = plan["bindings_by_dataset"][stem]
        got = receipt.get("bindings")
        _require(type(got) is dict and got == want,
                 f"{stem}: bindings differ from plan")
        for rel, meta in want.items():
            path = reader.bind(rel, meta["sha256"])
            _require(path.is_file() and path.stat().st_size == meta["bytes"],
                     f"{stem}: bound file bytes mismatch {rel}")
        reader.recheck()
        check_budget()

    for receipt, stem in zip(receipts, STEMS, strict=True):
        frames = receipt["frames"]
        _require(type(frames) is list and frames, f"{stem}: frames empty")
        originals = plan["original_signatures"][stem]
        _require(all(type(e) is dict for e in frames), f"{stem}: frame entry not a dict")
        times = [entry["t_source"] for entry in frames]
        _require(all(type(t) is int and 0 <= t <= 98 for t in times),
                 f"{stem}: frame t_source outside 0..98")
        _require(times == sorted(set(times)), f"{stem}: frame times duplicated or reordered")
        for entry in frames:
            t = entry["t_source"]
            _require(type(t) is int and 0 <= t <= 98,
                     f"{stem}: bad frame t_source {t!r}")
            _require(originals[t] is not None,
                     f"{stem}/{t}: active frame has no original signature")
            _require(entry["original_feature_signatures"] == originals[t],
                     f"{stem}/{t}: original_feature_signatures mismatch")
            src_ids, tgt_ids = entry["source_ids"], entry["target_ids"]
            for name, ids in (("source_ids", src_ids), ("target_ids", tgt_ids)):
                _require(type(ids) is list and ids
                         and all(type(i) is int for i in ids)
                         and ids == sorted(set(ids)),
                         f"{stem}/{t}: {name} not sorted unique ints")
            _require(not set(src_ids) & set(tgt_ids),
                     f"{stem}/{t}: source/target ids intersect")
            mapped = entry["mapped_feature_signatures"]
            _require(type(mapped) is dict and set(mapped) == set(FEATURES),
                     f"{stem}/{t}: mapped signature keys")
            for key in FEATURES:
                sig = mapped[key]
                _require(type(sig) is dict
                         and set(sig) == {"dtype", "shape", "sha256"},
                         f"{stem}/{t}/{key}: signature keys")
                _require(sig["dtype"] == "<f4", f"{stem}/{t}/{key}: dtype")
                _require(isinstance(sig["sha256"], str)
                         and len(sig["sha256"]) == 64
                         and all(c in "0123456789abcdef" for c in sig["sha256"]),
                         f"{stem}/{t}/{key}: sha256")
                n_ids = len(src_ids) if "source" in key else len(tgt_ids)
                _require(type(sig["shape"]) is list
                         and sig["shape"] == [n_ids, 32],
                         f"{stem}/{t}/{key}: shape")
                _require(n_ids <= originals[t][key]["shape"][0],
                         f"{stem}/{t}/{key}: raw subset exceeded")


def verify_consensus_receipts(plan, receipts, check_budget):
    """Validate E29 packet bindings and consensus receipt structure."""
    from biohub.association_capture import _require
    from biohub.association_collection_audit import Reader

    check_budget()
    fresh = prepare_appearance_plan()
    _require(plan == fresh, "plan does not match freshly prepared appearance plan")
    _require(type(receipts) is list and len(receipts) == len(STEMS),
             f"consensus receipts must be a list of {len(STEMS)}")
    for receipt, stem in zip(receipts, STEMS, strict=True):
        _require(type(receipt) is dict and receipt.get("schema") in (
            "E29_CONSENSUS_INPUT_RECEIPT_V1",
            "E30_POSITIVE_CONSENSUS_INPUT_RECEIPT_V1",
            "E31_PRIMARY_CONSENSUS_INPUT_RECEIPT_V1",
            "E33_SHORT_TRACK_CONSENSUS_INPUT_RECEIPT_V1",
        ),
                 f"{stem}: consensus schema mismatch")
        _require(receipt.get("dataset") == stem and receipt.get("group") == plan["dataset_groups"][stem],
                 f"{stem}: receipt dataset/group mismatch")
        _require(receipt.get("packet_count") == 99 and receipt.get("gt_read") is False
                 and receipt.get("weights_loaded") is False, f"{stem}: receipt metadata mismatch")
        reader = Reader(COLLECTION_ROOT)
        want = plan["bindings_by_dataset"][stem]
        _require(receipt.get("bindings") == want, f"{stem}: bindings differ from plan")
        for rel, meta in want.items():
            path = reader.bind(rel, meta["sha256"])
            _require(path.is_file() and path.stat().st_size == meta["bytes"],
                     f"{stem}: bound file bytes mismatch {rel}")
        reader.recheck()
        frames = receipt.get("frames")
        _require(type(frames) is list and frames, f"{stem}: consensus frames empty")
        times = []
        for entry in frames:
            _require(type(entry) is dict, f"{stem}: frame entry malformed")
            t = entry.get("t_source")
            _require(type(t) is int and 0 <= t <= 98 and t not in times,
                     f"{stem}: frame time malformed")
            times.append(t)
            _require(type(entry.get("detector_consensus_count")) is int
                     and entry["detector_consensus_count"] >= 0,
                     f"{stem}/{t}: consensus count malformed")
            pairs = entry.get("raw_pairs")
            _require(type(pairs) is list and pairs == sorted(pairs),
                     f"{stem}/{t}: raw pairs malformed")
            for pair in pairs:
                _require(type(pair) is list and len(pair) == 2
                         and all(type(x) is int and x >= 0 for x in pair),
                         f"{stem}/{t}: raw pair malformed")
            sigs = entry.get("original_logit_signatures")
            _require(type(sigs) is dict and set(sigs) == {
                "primary_forward_logits", "primary_reverse_logits", "secondary_forward_logits"
            }, f"{stem}/{t}: logit signatures malformed")
        _require(times == sorted(times), f"{stem}: frame times not ordered")
        check_budget()
    return None


def execute_baseline_core(prepared, cfg, bundle, output, check_budget, *,
                         association_priors_by_dataset=None,
                         appearance_loader=None,
                         consensus_loader=None,
                         consensus_soft_loader=None,
                         short_track_consensus_loader=None,
                         bidirectional_motion_consistency=False):
    if appearance_loader is not None and (
            not callable(appearance_loader)
            or association_priors_by_dataset is not None):
        raise ValueError(
            "appearance_loader must be callable and cannot be combined with "
            "association_priors_by_dataset")
    if consensus_loader is not None and (
            not callable(consensus_loader)
            or association_priors_by_dataset is not None
            or appearance_loader is not None):
        raise ValueError(
            "consensus_loader must be callable and cannot be combined with "
            "association_priors_by_dataset or appearance_loader")
    if consensus_soft_loader is not None and (
            not callable(consensus_soft_loader)
            or association_priors_by_dataset is not None
            or appearance_loader is not None
            or consensus_loader is not None):
        raise ValueError(
            "consensus_soft_loader must be callable and cannot be combined with "
            "association_priors_by_dataset, appearance_loader, or consensus_loader")
    if short_track_consensus_loader is not None and (
            not callable(short_track_consensus_loader)
            or association_priors_by_dataset is not None
            or appearance_loader is not None
            or consensus_loader is not None
            or consensus_soft_loader is not None):
        raise ValueError("short_track_consensus_loader is mutually exclusive")

    from biohub.e26_screen import (
        _validate_screen_bounds,
        validate_generated_csv,
        write_json_exclusive,
    )
    from biohub.public_postproc.pipeline import run_postproc_core
    from biohub.screen_output_bounds import ScreenNodeSerializer

    datasets = prepared["datasets"]
    if list(datasets) != list(STEMS):
        raise ValueError("prepared datasets must match STEMS")

    events = []
    raw_rows = []
    counter = 0

    def loader(actual_cfg):
        nonlocal counter
        if actual_cfg is not cfg:
            raise ValueError("loader received unexpected config")
        if counter != 0:
            raise RuntimeError("model loaded more than once")
        counter += 1
        return bundle

    def event(kind, seq, name):
        if type(seq) is not int:
            raise TypeError("event sequence must be int")
        if seq != len(events) // 3:
            raise ValueError("event sequence out of order")
        if name != STEMS[seq]:
            raise ValueError("event dataset mismatch")
        if kind != ("start", "raw_stats", "finish")[len(events) % 3]:
            raise ValueError("unexpected event kind ordering")
        events.append({
            "event": kind,
            "sequence": seq,
            "dataset": name,
            "timing": check_budget(),
        })
        if kind == "finish":
            print(f"[baseline] {name} done", flush=True)

    def start_hook(seq, name):
        event("start", seq, name)

    def finish_hook(seq, name):
        event("finish", seq, name)

    def raw_stats_hook(row):
        raw_rows.append(dict(row))
        event("raw_stats", len(raw_rows) - 1, raw_rows[-1]["dataset"])

    serializer = ScreenNodeSerializer(prepared["shapes"])
    if association_priors_by_dataset is None:
        kwargs = {}
    else:
        kwargs = {"association_priors_by_dataset": association_priors_by_dataset}
    if appearance_loader is not None:
        kwargs["appearance_loader"] = appearance_loader
    if consensus_loader is not None:
        kwargs["consensus_loader"] = consensus_loader
    if consensus_soft_loader is not None:
        kwargs["consensus_soft_loader"] = consensus_soft_loader
    if short_track_consensus_loader is not None:
        kwargs["short_track_consensus_loader"] = short_track_consensus_loader
    if bidirectional_motion_consistency:
        kwargs["bidirectional_motion_consistency"] = True
    csv_path = output / "submission.csv"
    try:
        core_result = run_postproc_core(
            tuple(prepared["raw_paths"]),
            csv_path,
            cfg,
            deepcenter_loader=loader,
            dataset_start_hook=lambda seq, name: start_hook(seq, name),
            dataset_finish_hook=lambda seq, name: finish_hook(seq, name),
            raw_stats_hook=raw_stats_hook,
            write_run_stats_output=False,
            exclusive_output=True,
            node_serializer=serializer,
            **kwargs,
        )
    finally:
        write_json_exclusive(output / "events.json", events)
        write_json_exclusive(output / "raw_statistics.json", raw_rows)
        write_json_exclusive(output / "output_bounds.json", serializer.snapshot())

    if len(events) != 36:
        raise RuntimeError(f"expected 36 events, got {len(events)}")
    if counter != 1:
        raise RuntimeError(f"expected exactly one model load, got {counter}")
    check_budget()

    report = validate_generated_csv(csv_path, datasets=STEMS, shapes=prepared["shapes"])
    _validate_screen_bounds(serializer.snapshot(), csv_path, prepared["shapes"])
    if consensus_loader is None and consensus_soft_loader is None:
        validate_known12_statistics(raw_rows, arm="baseline", csv_report=report)
    else:
        validate_known12_statistics(raw_rows, arm="e29", csv_report=report)
    for key in ("datasets", "total_nodes", "total_edges", "total_rows"):
        if core_result[key] != report[key]:
            raise ValueError(f"core/report mismatch for {key}")

    return {
        "csv_path": csv_path,
        "report": report,
        "events": events,
        "raw_rows": raw_rows,
        "bounds": serializer.snapshot(),
        "loader_calls": counter,
    }

_SOURCE_PATTERNS = ("**/*.py",)
_EXTRA_SOURCES = (
    Path("scripts/experiments/e23/prepare_e23_association_parity.py"),
    Path("analysis/e27_association_prior_design.md"),
    Path("analysis/e26_scoring_contract.md"),
    Path("analysis/e28_appearance_cost_design.md"),
)
_REFERENCE_RELATIVE = Path(
    "outputs/local/e26_screen/e26_motion_off_screen_v2_20260908073709Z"
    "/scoring/eval12_baseline.csv"
)
_REFERENCE_BYTES = 25549191
_REFERENCE_SHA256 = (
    "d4c976c69f850f3f1738523482a272d3468eaf8c99082e128069b9f690ff42a9"
)

_WALL_LIMIT_SECONDS = 1800.0
_RAM_LIMIT_BYTES = 8 * 1024**3
_OUTPUT_LIMIT_BYTES = 256 * 1024**2


def _utc_stamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime(
        "%Y%m%d%H%M%S%z"
    )


def _canonical_new_output_dir(output: Path) -> Path:
    """Validate ``output`` as a new absolute direct child of ROOT/outputs/local."""
    requested = Path(output)
    if not requested.is_absolute():
        raise ValueError("output must be an absolute path")
    resolved = Path(os.path.realpath(requested))
    if resolved != requested:
        raise ValueError("output resolves through a symlink or alias")
    for component in requested.parts:
        if component in (".", ".."):
            raise ValueError("output may not contain dot or parent traversal")
    parent = requested.parent
    expected_parent = ROOT / "outputs" / "local"
    if parent != expected_parent:
        raise ValueError("output must be a direct child of ROOT/outputs/local")
    if not expected_parent.is_dir():
        raise ValueError("ROOT/outputs/local does not exist")
    if os.path.realpath(expected_parent) != str(expected_parent):
        raise ValueError("ROOT/outputs/local resolves through a symlink")
    if requested.exists() or requested.is_symlink():
        raise ValueError("output directory already exists; WIP is never reused")
    try:
        requested.mkdir(mode=0o755)
    except FileExistsError as exc:
        raise ValueError("output directory already exists") from exc
    if any(p.is_symlink() for p in requested.iterdir()):
        raise ValueError("output directory contains symlinks")
    return requested


def _source_closure_paths() -> list[Path]:
    paths: list[Path] = []
    src_root = ROOT / "src" / "biohub"
    if not src_root.is_dir():
        raise RuntimeError("missing source root: src/biohub")
    for pattern in _SOURCE_PATTERNS:
        paths.extend(sorted(src_root.glob(pattern)))
    script = Path(__file__).resolve()
    paths.append(script)
    for rel in _EXTRA_SOURCES:
        paths.append(ROOT / rel)
    unique: dict[str, Path] = {}
    for path in paths:
        key = str(path)
        if key not in unique:
            unique[key] = path
    return [unique[k] for k in sorted(unique)]


def _snapshot_source_closure() -> dict:
    """Byte/hash binding for the fixed source closure; rejects aliases."""
    binding: dict[str, dict] = {}
    root_resolved = os.path.realpath(ROOT)
    for path in _source_closure_paths():
        resolved = os.path.realpath(path)
        if (
            path.is_symlink()
            or resolved != str(path)
            or not resolved.startswith(root_resolved + os.sep)
        ):
            raise RuntimeError(f"aliased source file rejected: {path}")
        if not path.is_file():
            raise RuntimeError(f"missing source file: {path}")
        try:
            relative = str(path.relative_to(ROOT))
        except ValueError as exc:
            raise RuntimeError(f"source outside ROOT rejected: {path}") from exc
        binding[relative] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    return {"files": binding, "count": len(binding)}


def _pre_reorg_alias(relative: str) -> str:
    """Collapse the 2026-09 scripts/experiments/<id>/ move for frozen pre-move records."""
    parts = relative.split("/")
    if len(parts) >= 3 and parts[0] == "scripts" and parts[1] == "experiments":
        return "scripts/" + parts[-1]
    return relative


def _verify_source_closure(before: dict) -> dict:
    after = _snapshot_source_closure()
    after_keyed = {_pre_reorg_alias(rel): meta for rel, meta in after["files"].items()}
    before_keyed = {_pre_reorg_alias(rel): meta for rel, meta in before["files"].items()}
    if set(after_keyed) != set(before_keyed):
        raise RuntimeError("source file-set drifted during run")
    changed = [
        rel
        for rel, meta in after_keyed.items()
        if before_keyed[rel]["sha256"] != meta["sha256"]
        or before_keyed[rel]["bytes"] != meta["bytes"]
    ]
    if changed:
        raise RuntimeError(f"source content drift detected: {sorted(changed)}")
    return after


def _binding_for_path(path: Path, *, label: str) -> dict:
    if path.is_symlink() or os.path.realpath(path) != str(path):
        raise RuntimeError(f"aliased {label} rejected: {path}")
    if not path.is_file():
        raise RuntimeError(f"missing {label}: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}


def _verify_reference_binding(label: str) -> dict:
    ref = ROOT / _REFERENCE_RELATIVE
    binding = _binding_for_path(ref, label=label)
    if binding["bytes"] != _REFERENCE_BYTES:
        raise RuntimeError(
            f"{label} byte mismatch: {binding['bytes']} != {_REFERENCE_BYTES}"
        )
    if binding["sha256"] != _REFERENCE_SHA256:
        raise RuntimeError(f"{label} sha256 mismatch: {binding['sha256']}")
    return binding


def _output_tree_bytes(root: Path) -> int:
    """Recursive regular-file byte total; rejects symlinks and non-regular files."""
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise RuntimeError(f"symlink inside output rejected: {entry.path}")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                else:
                    raise RuntimeError(
                        f"non-regular file inside output rejected: {entry.path}"
                    )
    return total


def run_baseline(output: Path, *, mode="baseline_none") -> dict:
    if type(mode) is not str or mode not in (
        "baseline_none", "selected_only", "recorded_prior",
        "e28_none", "e28_appearance", "e29_consensus", "e30_positive_consensus",
        "e31_primary_consensus", "e32_consensus_soft", "e33_consensus_short_rescue", "e34_bidirectional_motion",
    ):
        raise ValueError(f"unsupported mode: {mode!r}")
    started = time.monotonic()
    from biohub import e26_screen as e

    out = _canonical_new_output_dir(output)

    previous_handler = signal.getsignal(signal.SIGALRM)
    owned = False

    def on_timeout(signum, frame):
        raise TimeoutError("wall-clock budget exceeded")

    try:
        existing = signal.getitimer(signal.ITIMER_REAL)
        if existing[0] or existing[1]:
            raise RuntimeError("ITIMER_REAL already armed; refusing to steal active timer")

        signal.signal(signal.SIGALRM, on_timeout)
        owned = True
        remaining = _WALL_LIMIT_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("wall-clock budget exhausted before arming")
        signal.setitimer(signal.ITIMER_REAL, remaining)

        def check_budget() -> dict:
            timing = e.check_runtime_budget(
                started, wall_limit_seconds=_WALL_LIMIT_SECONDS, ram_limit_bytes=_RAM_LIMIT_BYTES
            )
            used = _output_tree_bytes(out)
            if used > _OUTPUT_LIMIT_BYTES:
                raise RuntimeError(f"output byte cap exceeded: {used}")
            timing["output_bytes"] = used
            return timing

        source_before = _snapshot_source_closure()
        ref_before = _verify_reference_binding("reference")
        check_budget()

        runtime = e.initialize_inference_runtime()
        check_budget()

        prepared = prepare_inputs()
        cfg = verify_prepared_materials(prepared)
        c = prepared["baseline_control"]
        check_budget()

        if prepared["status"] != "INPUTS_PREPARED_NOT_GENERATED":
            raise RuntimeError("unexpected prepared status")
        if prepared["gt_read"] is not False:
            raise RuntimeError("gt_read must be False")
        if list(prepared["datasets"]) != list(STEMS):
            raise RuntimeError("dataset mismatch")

        expected_raw = [
            Path(c["generation_input_binding"]["eval36"]["raw_inventory"]["selected_path"]) / f"{s}.geff"
            for s in STEMS
        ]
        if [Path(p) for p in prepared["raw_paths"]] != expected_raw:
            raise RuntimeError("raw path mismatch")

        is_e28 = mode in ("e28_none", "e28_appearance")
        is_e29 = mode == "e29_consensus"
        is_e30 = mode == "e30_positive_consensus"
        is_e31 = mode == "e31_primary_consensus"
        is_e32 = mode == "e32_consensus_soft"
        is_e33 = mode == "e33_consensus_short_rescue"
        is_e34 = mode == "e34_bidirectional_motion"
        appearance_plan = (
            prepare_appearance_plan()
            if (is_e28 or is_e29 or is_e30 or is_e31 or is_e32 or is_e33)
            else None
        )
        feature_receipts = []
        feature_receipts_binding = None
        appearance_loader = None
        consensus_loader = None

        prior_mapping = prior_receipt = None
        if mode in ("selected_only", "recorded_prior"):
            prior_mapping, prior_receipt = build_prior_inputs(prepared, mode)

        if mode == "e28_appearance":
            from biohub.appearance_inputs import load_appearance_frames

            def appearance_loader(dataset, raw_nodes):
                check_budget()
                if len(feature_receipts) >= len(STEMS) or dataset != STEMS[len(feature_receipts)]:
                    raise ValueError("appearance loader called out of order")
                frames, receipt = load_appearance_frames(
                    COLLECTION_ROOT,
                    appearance_plan["dataset_groups"][dataset],
                    dataset,
                    appearance_plan["bindings_by_dataset"][dataset],
                    raw_nodes,
                )
                feature_receipts.append(receipt)
                check_budget()
                return frames

        elif is_e29 or is_e30 or is_e31 or is_e32 or is_e33:
            from biohub.appearance_inputs import (
                load_consensus_frames,
                load_positive_consensus_frames,
                load_primary_consensus_frames,
                load_short_track_consensus_frames,
            )

            def consensus_loader(dataset, raw_nodes):
                check_budget()
                if len(feature_receipts) >= len(STEMS) or dataset != STEMS[len(feature_receipts)]:
                    raise ValueError("consensus loader called out of order")
                loader = (
                    load_short_track_consensus_frames if is_e33
                    else load_primary_consensus_frames if (is_e31 or is_e32)
                    else load_positive_consensus_frames if is_e30
                    else load_consensus_frames
                )
                frames, receipt = loader(
                    COLLECTION_ROOT,
                    appearance_plan["dataset_groups"][dataset],
                    dataset,
                    appearance_plan["bindings_by_dataset"][dataset],
                    raw_nodes,
                )
                feature_receipts.append(receipt)
                check_budget()
                return frames

        control = {
            "schema": (
                "E28_GENERATION_CONTROL_V1" if is_e28
                else "E29_GENERATION_CONTROL_V1" if is_e29
                else "E30_GENERATION_CONTROL_V1" if is_e30
                else "E31_GENERATION_CONTROL_V1" if is_e31
                else "E32_GENERATION_CONTROL_V1" if is_e32
                else "E33_GENERATION_CONTROL_V1" if is_e33
                else "E34_GENERATION_CONTROL_V1" if is_e34
                else "E27_BASELINE_CONTROL_V1"
            ),
            "run_id": out.name,
            "arm": mode,
            "datasets": list(STEMS),
            "association_priors": prior_receipt,
            "submission_allowed": False,
            "output": str(out),
            "source_bindings": source_before,
            "reference_binding": ref_before,
            "metadata_bindings": prepared["metadata_bindings"],
            "reader_bindings": prepared["reader_bindings"],
            "config": c["config"],
            "dependency_binding": c["dependency_binding"],
            "generation_input_binding": c["generation_input_binding"],
            "limits": {
                "wall_seconds": 1800,
                "ram_limit_bytes": _RAM_LIMIT_BYTES,
                "output_limit_bytes": _OUTPUT_LIMIT_BYTES,
            },
        }
        if is_e28:
            control.update({
                "candidate_id": "E28_APPEARANCE_COST_V1",
                "appearance_plan": appearance_plan,
            })
        elif is_e29:
            control.update({
                "candidate_id": "E29_CONSENSUS_PROTECTION_V1",
                "consensus_loader_schema": "E29_CONSENSUS_INPUT_RECEIPT_V1",
                "consensus_receipt_count_expected": len(STEMS),
            })
        elif is_e30:
            control.update({
                "candidate_id": "E30_POSITIVE_CONSENSUS_V1",
                "consensus_loader_schema": "E30_POSITIVE_CONSENSUS_INPUT_RECEIPT_V1",
                "consensus_receipt_count_expected": len(STEMS),
            })
        elif is_e31:
            control.update({
                "candidate_id": "E31_PRIMARY_CONSENSUS_V1",
                "consensus_loader_schema": "E31_PRIMARY_CONSENSUS_INPUT_RECEIPT_V1",
                "consensus_receipt_count_expected": len(STEMS),
            })
        elif is_e32:
            control.update({
                "candidate_id": "E32_CONSENSUS_SOFT_PREFERENCE_V1",
                "consensus_loader_schema": "E31_PRIMARY_CONSENSUS_INPUT_RECEIPT_V1",
                "consensus_receipt_count_expected": len(STEMS),
            })
        elif is_e33:
            control.update({
                "candidate_id": "E33_CONSENSUS_SHORT_TRACK_RESCUE_V1",
                "consensus_loader_schema": "E33_SHORT_TRACK_CONSENSUS_INPUT_RECEIPT_V1",
                "consensus_receipt_count_expected": len(STEMS),
            })
        elif is_e34:
            control.update({
                "candidate_id": "E34_BIDIRECTIONAL_MOTION_V1",
                "motion_consistency": "bidirectional_same_gate_v1",
            })
        e.write_json_exclusive(out / "CONTROL.json", control)
        pinned = _binding_for_path(out / "CONTROL.json", label="control")

        e.write_json_exclusive(
            out / "STARTED.json",
            {
                "pid": os.getpid(),
                "argv": list(sys.argv),
                "utc": _utc_stamp(),
            },
        )
        e.write_json_exclusive(out / "inference.json", runtime)

        bundle, receipt = e._load_child_model(cfg, c["generation_input_binding"])
        e.write_json_exclusive(out / "deepcenter.json", receipt)
        check_budget()

        core = execute_baseline_core(
            prepared, cfg, bundle, out, check_budget,
            **({} if prior_mapping is None else
               {"association_priors_by_dataset": prior_mapping}),
            **({"appearance_loader": appearance_loader}
               if mode == "e28_appearance" else {}),
            **({"consensus_loader": consensus_loader}
               if (is_e29 or is_e30 or is_e31) else {}),
            **({"consensus_soft_loader": consensus_loader} if is_e32 else {}),
            **({"short_track_consensus_loader": consensus_loader} if is_e33 else {}),
            **({"bidirectional_motion_consistency": True} if is_e34 else {}),
        )
        check_budget()

        if mode in ("selected_only", "recorded_prior"):
            rebuilt_mapping, rebuilt_receipt = build_prior_inputs(prepared, mode)
            if rebuilt_receipt != prior_receipt:
                raise RuntimeError("prior receipt drift after core")
            if rebuilt_mapping != prior_mapping:
                raise RuntimeError("prior mapping drift after core")

        if mode == "e28_appearance":
            verify_appearance_receipts(appearance_plan, feature_receipts, check_budget)
            e.write_json_exclusive(out / "FEATURE_RECEIPTS.json", feature_receipts)
            feature_receipts_binding = _binding_for_path(
                out / "FEATURE_RECEIPTS.json", label="feature_receipts"
            )
        if mode in (
            "e29_consensus", "e30_positive_consensus", "e31_primary_consensus",
            "e32_consensus_soft",
            "e33_consensus_short_rescue",
        ):
            verify_appearance_receipts(appearance_plan, feature_receipts, check_budget)
            e.write_json_exclusive(out / "CONSENSUS_RECEIPTS.json", feature_receipts)
        if mode == "e28_none" and (out / "FEATURE_RECEIPTS.json").exists():
            raise RuntimeError("unexpected FEATURE_RECEIPTS.json on e28_none arm")

        verify_prepared_materials(prepared)
        _verify_source_closure(source_before)
        ref_after = _verify_reference_binding("reference")
        if ref_after != ref_before:
            raise RuntimeError("reference binding drift")
        if _binding_for_path(out / "CONTROL.json", label="control") != pinned:
            raise RuntimeError("CONTROL.json binding drift")

        generated = _binding_for_path(core["csv_path"], label="csv")
        reference = _verify_reference_binding("generated")
        if mode not in (
            "recorded_prior", "e28_appearance", "e29_consensus",
            "e30_positive_consensus", "e31_primary_consensus", "e32_consensus_soft",
            "e33_consensus_short_rescue",
            "e34_bidirectional_motion",
            "e33_consensus_short_rescue",
            "e33_consensus_short_rescue",
            "e33_consensus_short_rescue",
            "e33_consensus_short_rescue",
        ):
            if generated["bytes"] != reference["bytes"] or generated["sha256"] != reference["sha256"]:
                raise RuntimeError("csv does not match reference binding")
        check_budget()

        def artifact_snapshot() -> dict:
            for name in ("RESULT.json", "ERROR.json", "RESULT.failed.json"):
                if (out / name).exists():
                    raise RuntimeError(f"terminal artifact already present: {name}")
            total = _output_tree_bytes(out)
            snap = {}
            for path in sorted(out.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    rel = str(path.relative_to(out))
                    snap[rel] = _binding_for_path(path, label="artifact")
            if total != sum(v["bytes"] for v in snap.values()):
                raise RuntimeError("output tree contains aliased or special files")
            return snap

        snap_a = artifact_snapshot()
        snap_b = artifact_snapshot()
        if snap_a != snap_b:
            raise RuntimeError("output artifacts are unstable")

        status = {
            "baseline_none": "E27_BASELINE_PARITY_PASS_NOT_CANDIDATE",
            "selected_only": "E27_SELECTED_ONLY_PARITY_PASS_NOT_CANDIDATE",
            "recorded_prior": "E27_RECORDED_PRIOR_GENERATED_UNSCORED",
            "e28_none": "E28_APPEARANCE_NONE_PARITY_PASS_NOT_CANDIDATE",
            "e28_appearance": "E28_APPEARANCE_COST_V1_GENERATED_UNSCORED",
            "e29_consensus": "E29_CONSENSUS_PROTECTION_GENERATED_UNSCORED",
            "e30_positive_consensus": "E30_POSITIVE_CONSENSUS_GENERATED_UNSCORED",
            "e31_primary_consensus": "E31_PRIMARY_CONSENSUS_GENERATED_UNSCORED",
            "e32_consensus_soft": "E32_CONSENSUS_SOFT_GENERATED_UNSCORED",
            "e33_consensus_short_rescue": "E33_CONSENSUS_SHORT_TRACK_RESCUE_GENERATED_UNSCORED",
            "e34_bidirectional_motion": "E34_BIDIRECTIONAL_MOTION_GENERATED_UNSCORED",
        }[mode]
        result = {
            "status": status,
            "arm": mode,
            "association_priors": prior_receipt,
            "run_id": out.name,
            "gt_read": False,
            "submission_allowed": False,
            "counts": core["report"],
            "csv_binding": generated,
            "control_binding": pinned,
            "source_bindings": source_before,
            "artifact_bindings": snap_a,
            "timing": check_budget(),
        }
        if is_e28:
            result.update({
                "candidate_id": "E28_APPEARANCE_COST_V1",
                "feature_receipts_binding": feature_receipts_binding,
            })
        if is_e29 or is_e30 or is_e31 or is_e32 or is_e33:
            result.update({
                "candidate_id": (
                    "E29_CONSENSUS_PROTECTION_V1" if is_e29
                    else "E30_POSITIVE_CONSENSUS_V1" if is_e30
                    else "E31_PRIMARY_CONSENSUS_V1" if is_e31
                    else "E32_CONSENSUS_SOFT_PREFERENCE_V1" if is_e32
                    else "E33_CONSENSUS_SHORT_TRACK_RESCUE_V1"
                ),
                "consensus_receipts_binding": _binding_for_path(
                    out / "CONSENSUS_RECEIPTS.json", label="consensus_receipts"
                ),
            })
        if is_e34:
            result.update({"candidate_id": "E34_BIDIRECTIONAL_MOTION_V1"})
        e.write_json_exclusive(out / "RESULT.json", result)
        check_budget()
        return result

    except BaseException as exc:
        failed = out / "RESULT.json"
        if failed.exists():
            failed.rename(out / "RESULT.failed.json")
        e.write_json_exclusive(
            out / "ERROR.json",
            {
                "exception_type": type(exc).__name__,
                "submission_allowed": False,
                "partial_outputs_preserved": True,
            },
        )
        raise

    finally:
        if owned:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)


def supervise_baseline(output: Path, *, mode="baseline_none") -> dict:
    """Parent-process supervisor for a single serial E27 baseline child run.

    The child is launched exactly once as a new direct process with the strict
    allowlisted generation environment.  ``mode`` is validated before any side
    effect and appended to the child argv only for non-baseline arms.  All supervision bookkeeping lives in a
    sibling audit directory so that mutable supervisor logs can never change the
    hashes of artifacts inside the child output tree.

    Any failure after the audit directory exists is recorded as an ERROR.json in
    the audit directory, revokes the child RESULT.json (and any supervisor
    SUCCESS already written) to ``*.failed.json``, and re-raises the original
    exception.  Failures are never swallowed.
    """
    if type(mode) is not str or mode not in (
        "baseline_none",
        "selected_only",
        "recorded_prior",
        "e28_none",
        "e28_appearance",
        "e29_consensus",
        "e30_positive_consensus",
        "e31_primary_consensus",
        "e32_consensus_soft",
        "e33_consensus_short_rescue", "e34_bidirectional_motion",
    ):
        raise ValueError(f"unsupported mode: {mode!r}")

    import subprocess

    from biohub import e26_screen as e

    started_monotonic = time.monotonic()
    start_utc = _utc_stamp()

    # --- validate the requested child output dir WITHOUT creating it ---------
    given = Path(output)
    if not given.is_absolute():
        raise ValueError("output must be an absolute path")
    output = given
    expected_parent = (ROOT / "outputs" / "local")
    if output.parent != expected_parent:
        raise ValueError(f"output must be a direct child of {expected_parent}")
    if output.is_symlink():
        raise ValueError("output must not be a symlink")
    if os.path.realpath(output) != str(output):
        raise ValueError("output must be its own canonical realpath")
    if output.exists():
        raise ValueError(f"output already exists: {output}")

    # Audit directory is a separate, exclusively created sibling.
    audit_dir = _canonical_new_output_dir(output.with_name(output.name + "_supervisor"))

    argv = [
        sys.executable,
        "-m",
        "scripts.experiments.e27.e27_association_prior_screen",
        "--output",
        str(output),
    ]
    if mode != "baseline_none":
        argv += ["--mode", mode]
    env = e.generation_environment()

    stdout_path = audit_dir / "stdout.log"
    stderr_path = audit_dir / "stderr.log"

    state = {"process": None}
    killpg_signals = []

    def stop_and_reap(proc):
        """Terminate then kill the child's whole process group; always reap.

        A failed final wait propagates so the caller can never claim a PASS while
        the child is still live.
        """
        if proc.poll() is not None:
            proc.wait(timeout=5)
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            killpg_signals.append(int(signal.SIGTERM))
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        else:
            killpg_signals.append(int(signal.SIGKILL))
        proc.wait(timeout=5)

    def _revoke(path: Path, label: str):
        """Move a mutable success artifact to a terminal .failed.json name."""
        if not path.exists():
            return
        target = path.with_name(f"{path.stem}.failed{path.suffix}")
        if target.exists():
            raise RuntimeError(f"cannot revoke {label}: {target} already exists")
        path.rename(target)

    try:
        with open(stdout_path, "xb") as stdout_handle, open(stderr_path, "xb") as stderr_handle:
            # Exactly one launch; no retry, no polling busy-loop.
            launch_sources = _snapshot_source_closure()
            process = subprocess.Popen(
                argv,
                cwd=str(ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
            )
            state["process"] = process
            try:
                returncode = process.wait(timeout=_WALL_LIMIT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(
                    f"baseline child exceeded {_WALL_LIMIT_SECONDS}s wall limit"
                ) from exc
            if returncode != 0:
                raise RuntimeError(f"baseline child failed with returncode {returncode}")

        elapsed = time.monotonic() - started_monotonic

        # --- validate the child terminal PASS before writing any supervisor file --
        result_path = output / "RESULT.json"
        if not result_path.is_file():
            raise RuntimeError("child produced no RESULT.json")

        result_binding_before = _binding_for_path(result_path, label="RESULT")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        expected_status = {
            "baseline_none": "E27_BASELINE_PARITY_PASS_NOT_CANDIDATE",
            "selected_only": "E27_SELECTED_ONLY_PARITY_PASS_NOT_CANDIDATE",
            "recorded_prior": "E27_RECORDED_PRIOR_GENERATED_UNSCORED",
            "e28_none": "E28_APPEARANCE_NONE_PARITY_PASS_NOT_CANDIDATE",
            "e28_appearance": "E28_APPEARANCE_COST_V1_GENERATED_UNSCORED",
            "e29_consensus": "E29_CONSENSUS_PROTECTION_GENERATED_UNSCORED",
            "e30_positive_consensus": "E30_POSITIVE_CONSENSUS_GENERATED_UNSCORED",
            "e31_primary_consensus": "E31_PRIMARY_CONSENSUS_GENERATED_UNSCORED",
            "e32_consensus_soft": "E32_CONSENSUS_SOFT_GENERATED_UNSCORED",
            "e33_consensus_short_rescue": "E33_CONSENSUS_SHORT_TRACK_RESCUE_GENERATED_UNSCORED",
            "e34_bidirectional_motion": "E34_BIDIRECTIONAL_MOTION_GENERATED_UNSCORED",
        }[mode]
        parent_status = {
            "baseline_none": "E27_BASELINE_SUPERVISED_PASS_NOT_CANDIDATE",
            "selected_only": "E27_SELECTED_ONLY_SUPERVISED_PASS_NOT_CANDIDATE",
            "recorded_prior": "E27_RECORDED_PRIOR_SUPERVISED_UNSCORED",
            "e28_none": "E28_APPEARANCE_NONE_SUPERVISED_PASS_NOT_CANDIDATE",
            "e28_appearance": "E28_APPEARANCE_COST_V1_SUPERVISED_UNSCORED",
            "e29_consensus": "E29_CONSENSUS_PROTECTION_SUPERVISED_UNSCORED",
            "e30_positive_consensus": "E30_POSITIVE_CONSENSUS_SUPERVISED_UNSCORED",
            "e31_primary_consensus": "E31_PRIMARY_CONSENSUS_SUPERVISED_UNSCORED",
            "e32_consensus_soft": "E32_CONSENSUS_SOFT_SUPERVISED_UNSCORED",
            "e33_consensus_short_rescue": "E33_CONSENSUS_SHORT_TRACK_RESCUE_SUPERVISED_UNSCORED",
            "e34_bidirectional_motion": "E34_BIDIRECTIONAL_MOTION_SUPERVISED_UNSCORED",
        }[mode]
        if result.get("status") != expected_status:
            raise RuntimeError("child RESULT status mismatch")
        if result.get("arm") != mode:
            raise RuntimeError("child RESULT arm mismatch")
        if result.get("gt_read") is not False:
            raise RuntimeError("child RESULT gt_read must be False")
        if result.get("submission_allowed") is not False:
            raise RuntimeError("child RESULT submission_allowed must be False")

        if result["source_bindings"] != launch_sources:
            raise RuntimeError("source closure changed between prelaunch and child record")
        _verify_source_closure(launch_sources)

        control_binding = result["control_binding"]
        if _binding_for_path(output / "CONTROL.json", label="CONTROL") != control_binding:
            raise RuntimeError("CONTROL binding drifted")

        csv_binding = result["csv_binding"]
        if _binding_for_path(output / "submission.csv", label="submission.csv") != csv_binding:
            raise RuntimeError("submission.csv binding drifted")

        control = json.loads((output / "CONTROL.json").read_text(encoding="utf-8"))
        if control.get("arm") != mode:
            raise RuntimeError("control arm mismatch")
        if control.get("association_priors") != result.get("association_priors"):
            raise RuntimeError("control/RESULT association_priors mismatch")

        receipt = result.get("association_priors")
        if mode in (
            "baseline_none", "e28_none", "e28_appearance", "e29_consensus",
            "e30_positive_consensus", "e31_primary_consensus", "e32_consensus_soft",
            "e33_consensus_short_rescue", "e34_bidirectional_motion",
        ):
            if receipt is not None:
                raise RuntimeError("baseline arm must not record association priors")
        else:
            if type(receipt) is not dict:
                raise RuntimeError("association_priors receipt must be a dict")
            if receipt.get("mode") != mode:
                raise RuntimeError("receipt mode mismatch")
            if receipt.get("datasets") != list(STEMS):
                raise RuntimeError("receipt datasets mismatch")
            sha = receipt.get("sha256")
            if type(sha) is not str or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise RuntimeError("receipt sha256 malformed")
            for field in ("entries_by_dataset", "eligible_unselected_by_dataset"):
                counts = receipt.get(field)
                if type(counts) is not dict or set(counts) != set(STEMS):
                    raise RuntimeError(f"receipt {field} keys malformed")
                for stem in STEMS:
                    value = counts[stem]
                    if type(value) is not int or value < 0:
                        raise RuntimeError(f"receipt {field}[{stem}] malformed")
            novel = [
                receipt["eligible_unselected_by_dataset"][stem]
                for stem in STEMS
            ]
            if mode == "selected_only" and sum(novel) != 0:
                raise RuntimeError("selected_only receipt must have no eligible unselected entries")
            if mode == "recorded_prior" and sum(novel) <= 0:
                raise RuntimeError("recorded_prior receipt requires eligible unselected entries")

        reference = _verify_reference_binding("reference")
        if mode not in (
            "recorded_prior", "e28_appearance", "e29_consensus",
            "e30_positive_consensus", "e31_primary_consensus", "e32_consensus_soft",
            "e33_consensus_short_rescue", "e34_bidirectional_motion",
        ):
            if reference["sha256"] != csv_binding["sha256"] or reference["bytes"] != csv_binding["bytes"]:
                raise RuntimeError("reference does not match generated CSV")

        artifacts = result["artifact_bindings"]
        forbidden = {"ERROR.json", "RESULT.failed.json"}
        for rel in artifacts:
            if Path(rel).name in forbidden:
                raise RuntimeError(f"child may not bind supervisory artifact: {rel}")

        actual = {
            p.relative_to(output).as_posix()
            for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "RESULT.json"
        }
        if set(artifacts) != actual:
            raise RuntimeError("artifact_bindings membership mismatch")
        for rel, binding in artifacts.items():
            candidate = output / rel
            if output not in candidate.resolve().parents:
                raise RuntimeError(f"artifact escapes output tree: {rel}")
            if _binding_for_path(candidate, label=rel) != binding:
                raise RuntimeError(f"artifact binding drifted: {rel}")

        if _binding_for_path(result_path, label="RESULT") != result_binding_before:
            raise RuntimeError("RESULT.json changed during supervision")

        total_bytes = _output_tree_bytes(output) + _output_tree_bytes(audit_dir)
        if total_bytes > _OUTPUT_LIMIT_BYTES:
            raise RuntimeError("output tree plus supervisor logs exceed byte budget")

        record = {
            "status": parent_status,
            "arm": mode,
            "association_priors": receipt,
            "pid": process.pid,
            "argv": argv,
            "environment": env,
            "start_utc": start_utc,
            "elapsed_seconds": elapsed,
            "returncode": returncode,
            "wall_limit_seconds": _WALL_LIMIT_SECONDS,
            "cleanup_wait_seconds": 5,
            "memory_scope": "child_self_peak_rss_only_not_process_group_cap",
            "killpg_signals": killpg_signals,
            "reap_error": None,
            "output": str(output),
            "audit_dir": str(audit_dir),
            "total_output_bytes": total_bytes,
            "log_bindings": {
                "stdout.log": _binding_for_path(stdout_path, label="stdout.log"),
                "stderr.log": _binding_for_path(stderr_path, label="stderr.log"),
            },
            "result_binding": result_binding_before,
            "child_status": result["status"],
            "counts": result.get("counts"),
            "gt_read": False,
            "submission_allowed": False,
        }
        def check_final_budget():
            if time.monotonic() - started_monotonic > _WALL_LIMIT_SECONDS:
                raise RuntimeError("supervisor exceeded wall budget during verification")
            late_total = _output_tree_bytes(output) + _output_tree_bytes(audit_dir)
            if late_total > _OUTPUT_LIMIT_BYTES:
                raise RuntimeError("output tree plus supervisor logs exceed byte budget")
            return late_total

        if mode in ("e28_none", "e28_appearance"):
            if control.get("schema") != "E28_GENERATION_CONTROL_V1":
                raise RuntimeError("control schema mismatch")
            if control.get("candidate_id") != "E28_APPEARANCE_COST_V1":
                raise RuntimeError("control candidate_id mismatch")
            if result.get("candidate_id") != "E28_APPEARANCE_COST_V1":
                raise RuntimeError("RESULT candidate_id mismatch")

            check_final_budget()
            appearance_plan = prepare_appearance_plan()
            if control.get("appearance_plan") != appearance_plan:
                raise RuntimeError("control appearance_plan mismatch")
            check_final_budget()
            if mode == "e28_none":
                if result.get("feature_receipts_binding") is not None:
                    raise RuntimeError("e28_none RESULT feature_receipts_binding must be None")
                if (output / "FEATURE_RECEIPTS.json").exists():
                    raise RuntimeError("e28_none must not emit FEATURE_RECEIPTS.json")
            else:
                receipts_path = output / "FEATURE_RECEIPTS.json"
                receipts_binding = _binding_for_path(receipts_path, label="feature_receipts")
                if receipts_binding != result.get("feature_receipts_binding"):
                    raise RuntimeError("feature_receipts binding mismatch")
                receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
                verify_appearance_receipts(
                    control["appearance_plan"], receipts, check_final_budget
                )
            check_final_budget()
            record["elapsed_seconds"] = time.monotonic() - started_monotonic
            record.update({
                "candidate_id": "E28_APPEARANCE_COST_V1",
                "feature_receipts_binding": result.get("feature_receipts_binding"),
            })

        if mode in (
            "e29_consensus", "e30_positive_consensus", "e31_primary_consensus",
            "e32_consensus_soft", "e33_consensus_short_rescue",
        ):
            expected_schema = (
                "E29_GENERATION_CONTROL_V1" if mode == "e29_consensus"
                else "E30_GENERATION_CONTROL_V1" if mode == "e30_positive_consensus"
                else "E31_GENERATION_CONTROL_V1" if mode == "e31_primary_consensus"
                else "E32_GENERATION_CONTROL_V1" if mode == "e32_consensus_soft"
                else "E33_GENERATION_CONTROL_V1" if mode == "e33_consensus_short_rescue"
                else "E34_GENERATION_CONTROL_V1"
            )
            expected_candidate = (
                "E29_CONSENSUS_PROTECTION_V1" if mode == "e29_consensus"
                else "E30_POSITIVE_CONSENSUS_V1" if mode == "e30_positive_consensus"
                else "E31_PRIMARY_CONSENSUS_V1" if mode == "e31_primary_consensus"
                else "E32_CONSENSUS_SOFT_PREFERENCE_V1" if mode == "e32_consensus_soft"
                else "E33_CONSENSUS_SHORT_TRACK_RESCUE_V1" if mode == "e33_consensus_short_rescue"
                else "E34_BIDIRECTIONAL_MOTION_V1"
            )
            if control.get("schema") != expected_schema:
                raise RuntimeError("control schema mismatch")
            if control.get("candidate_id") != expected_candidate:
                raise RuntimeError("control candidate_id mismatch")
            if result.get("candidate_id") != expected_candidate:
                raise RuntimeError("RESULT candidate_id mismatch")
            receipts_path = output / "CONSENSUS_RECEIPTS.json"
            receipts_binding = _binding_for_path(receipts_path, label="consensus_receipts")
            if receipts_binding != result.get("consensus_receipts_binding"):
                raise RuntimeError("consensus_receipts binding mismatch")
            receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
            verify_appearance_receipts(
                prepare_appearance_plan(), receipts, check_final_budget
            )
            record["elapsed_seconds"] = time.monotonic() - started_monotonic
            record.update({
                "candidate_id": expected_candidate,
                "consensus_receipts_binding": receipts_binding,
            })

        e.write_json_exclusive(audit_dir / "SUPERVISOR_RESULT.json", record)
        late_bytes = _output_tree_bytes(output) + _output_tree_bytes(audit_dir)
        if late_bytes > _OUTPUT_LIMIT_BYTES:
            raise RuntimeError("output tree plus supervisor logs exceed byte budget")
        if mode.startswith("e28_") or mode in (
            "e29_consensus", "e30_positive_consensus", "e31_primary_consensus",
            "e32_consensus_soft",
        ):
            check_final_budget()
        return record
    except BaseException as exc:
        process = state["process"]
        if process is not None:
            stop_and_reap(process)
        _revoke(output / "RESULT.json", "RESULT")
        _revoke(audit_dir / "SUPERVISOR_RESULT.json", "SUPERVISOR_RESULT")
        e.write_json_exclusive(
            audit_dir / "ERROR.json",
            {
                "status": (
                    "E28_APPEARANCE_SUPERVISED_FAIL_NOT_CANDIDATE"
                    if mode in (
                        "e28_none", "e28_appearance", "e29_consensus",
                        "e30_positive_consensus", "e31_primary_consensus",
                        "e32_consensus_soft", "e33_consensus_short_rescue", "e34_bidirectional_motion",
                    )
                    else "E27_BASELINE_SUPERVISED_FAIL_NOT_CANDIDATE"
                ),
                "arm": mode,
                "exception_type": type(exc).__name__,
                "pid": process.pid if process is not None else None,
                "killpg_signals": killpg_signals,
                "reap_error": None,
                "start_utc": start_utc,
                "elapsed_seconds": time.monotonic() - started_monotonic,
                "output": str(output),
                "audit_dir": str(audit_dir),
                "gt_read": False,
                "submission_allowed": False,
            },
        )
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supervise", action="store_true")
    parser.add_argument("--mode", choices=(
        "baseline_none", "selected_only", "recorded_prior", "e28_none",
        "e28_appearance", "e29_consensus", "e30_positive_consensus",
        "e31_primary_consensus", "e32_consensus_soft", "e33_consensus_short_rescue", "e34_bidirectional_motion",
    ),
                        default="baseline_none")
    args = parser.parse_args(argv)
    kwargs = {} if args.mode == "baseline_none" else {"mode": args.mode}
    if args.supervise:
        result = supervise_baseline(args.output, **kwargs)
    else:
        result = run_baseline(args.output, **kwargs)
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
