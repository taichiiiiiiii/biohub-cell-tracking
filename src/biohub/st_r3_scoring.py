"""Sealed, staged ST-R3 official scoring state machine.

This module is intentionally independent from generation.  Its sole mutable
operation is publishing a score stage (or the first terminal failure receipt)
inside an already immutable run directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

CSV_COLUMNS = ("id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id")
EVAL12 = (
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
EVAL24 = (
    "44b6_706092f0",
    "44b6_74d0c52e",
    "44b6_7a302da0",
    "44b6_996155de",
    "44b6_9be80b04",
    "44b6_a21120c2",
    "44b6_aaf8b0ea",
    "44b6_c50204e0",
    "44b6_c8e2a523",
    "44b6_d2f34f90",
    "44b6_d5e7d891",
    "44b6_d754aa59",
    "6bba_1d0d8384",
    "6bba_207c6aaf",
    "6bba_20852818",
    "6bba_2312ac41",
    "6bba_268e1230",
    "6bba_2819ca14",
    "6bba_32db13fc",
    "6bba_337b1b3a",
    "6bba_3abfe10a",
    "6bba_3c5691b6",
    "6bba_3db54e20",
    "6bba_3fda6b25",
)
EVAL36 = EVAL12 + EVAL24
PUBLIC_FOUR = frozenset(("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1"))
MAX_DISTANCE_UM = 7.0
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
GIT_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
UINT_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
INT_RE = re.compile(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)\Z")

FEASIBILITY_SCHEMA = "biohub.st_r3.feasibility_manifest.v1"
GT_INVENTORY_SCHEMA = "biohub.st_r3.gt_inventory.v1"
STAGE_MANIFEST_SCHEMA = "biohub.st_r3.score_stage_manifest.v1"
STAGE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "run_id",
        "stage",
        "preceding_manifest",
        "feasibility_manifest_sha256",
        "artifacts",
    }
)
STAGE_ARTIFACT_KEYS = frozenset({"path", "bytes", "sha256", "media_type", "schema_type", "role"})
SUMMARY_KEYS = frozenset(
    {
        "n",
        "edge_jaccard",
        "division_jaccard",
        "division_tp",
        "division_fp",
        "division_fn",
        "node_recall",
        "adj_edge_jaccard",
        "n_adj",
        "score",
    }
)
PER_SAMPLE_KEYS = frozenset(
    {
        "dataset",
        "edge_tp",
        "edge_fp",
        "edge_fn",
        "division_tp",
        "division_fp",
        "division_fn",
        "num_pred_nodes",
        "node_recall",
        "total_node_ratio",
        "edge_jaccard",
        "adj_edge_jaccard",
    }
)
COUNT_KEYS = frozenset(
    {
        "edge_tp",
        "edge_fp",
        "edge_fn",
        "division_tp",
        "division_fp",
        "division_fn",
        "num_pred_nodes",
    }
)

FEASIBILITY_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "run_id",
        "preregistration",
        "generation_manifest",
        "datasets",
        "executions",
        "canonical_submissions",
        "sealed_hashes",
        "official",
        "source_bindings",
        "feasibility",
        "scoring_inputs",
        "artifacts",
    }
)
REF_KEYS = frozenset({"path", "bytes", "sha256"})
DATASET_KEYS = frozenset({"eval12", "eval24", "eval36", "digests"})
EXECUTION_KEYS = frozenset({"safety_dry_run", "baseline_ab", "candidate_ab", "candidate_ba", "baseline_ba"})
CANONICAL_SUBMISSION_KEYS = frozenset({"ref", "typed_graph_sha256", "partitions"})
PARTITION_KEYS = frozenset({"sha256", "bytes", "row_count"})
SEALED_HASH_KEYS = frozenset(
    {
        "full_arm_outputs_sha256",
        "stats_sha256",
        "plans_sha256",
        "configs_sha256",
        "source_inventory_sha256",
        "live_artifact_inventory_sha256",
        "image_content_inventory_sha256",
        "raw_inventory_sha256",
    }
)
OFFICIAL_KEYS = frozenset({"gitlink", "head", "clean", "source_hashes"})
OFFICIAL_SOURCE_KEYS = frozenset({"tracking_cellmot/metrics.py", "tracking_cellmot/division_metrics.py"})
SOURCE_BINDING_KEYS = frozenset(
    {"superproject_commit", "tracked_tree_clean", "evaluate_py_sha256", "st_r3_scoring_py_sha256"}
)
FEASIBILITY_GATE_KEYS = frozenset(
    {
        "ref",
        "prerequisites_passed",
        "e23_parity",
        "base1_non_regression",
        "adapter_reviewed",
        "training_gate_not_applicable",
        "source_clean",
        "official_clean",
        "generation_sealed",
        "gt_nonvisibility",
        "deepcenter_bound",
        "data_ready",
        "image_ready",
        "deterministic_replay",
        "dry_run_identity",
        "conservation",
        "local_runtime",
        "local_rss",
        "target_runtime",
        "target_memory",
        "hidden_200",
    }
)
SCORING_INPUT_KEYS = frozenset({"gt_view", "gt_inventory", "image_view", "image_content_inventory"})


class ScoringFailure(RuntimeError):
    """Fail-closed scoring or state-machine error carrying a stable code."""

    def __init__(self, code: str, message: str, *, gt_read_started: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.gt_read_started = gt_read_started


def canonical_json_bytes(value: Any) -> bytes:
    """Return the sole ST-R3 JSON representation."""
    try:
        return (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ScoringFailure("NON_CANONICAL_JSON", str(exc)) from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def dataset_digest(stems: Sequence[str]) -> str:
    return canonical_digest(list(stems))


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ScoringFailure(
            "SCHEMA_MISMATCH",
            f"{label} keys differ: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}",
        )


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScoringFailure("SCHEMA_MISMATCH", f"{label} must be an object")
    return value


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise ScoringFailure("SCHEMA_MISMATCH", f"{label} is not a lowercase SHA-256")
    return value


def _require_git_commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or GIT_COMMIT_RE.fullmatch(value) is None:
        raise ScoringFailure("SCHEMA_MISMATCH", f"{label} is not a lowercase Git object ID")
    return value


def _safe_rel(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ScoringFailure("UNSAFE_PATH", f"{label} is not a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ScoringFailure("UNSAFE_PATH", f"{label} is absolute or contains traversal")
    return path


def _resolve(run_dir: Path, value: Any, label: str, *, regular: bool = True) -> Path:
    rel = _safe_rel(value, label)
    current = run_dir
    for part in rel.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise ScoringFailure("MISSING_ARTIFACT", f"{label} missing: {rel}") from exc
        if stat.S_ISLNK(mode):
            raise ScoringFailure("SYMLINK_REFUSED", f"{label} traverses symlink: {rel}")
        if current != run_dir / rel and not stat.S_ISDIR(mode):
            raise ScoringFailure("SPECIAL_FILE_REFUSED", f"{label} has non-directory parent: {rel}")
    mode = current.lstat().st_mode
    if regular and not stat.S_ISREG(mode):
        raise ScoringFailure("SPECIAL_FILE_REFUSED", f"{label} is not a regular file: {rel}")
    if not regular and not stat.S_ISDIR(mode):
        raise ScoringFailure("SPECIAL_FILE_REFUSED", f"{label} is not a directory: {rel}")
    return current


def _validate_ref(run_dir: Path, value: Any, label: str) -> tuple[dict[str, Any], Path]:
    ref = _require_dict(value, label)
    _exact_keys(ref, REF_KEYS, label)
    path = _resolve(run_dir, ref["path"], label)
    if type(ref["bytes"]) is not int or ref["bytes"] < 0:
        raise ScoringFailure("SCHEMA_MISMATCH", f"{label}.bytes must be a nonnegative integer")
    expected = _require_sha(ref["sha256"], f"{label}.sha256")
    if path.stat().st_size != ref["bytes"] or sha256_file(path) != expected:
        raise ScoringFailure("HASH_DRIFT", f"{label} bytes/hash drift: {ref['path']}")
    return ref, path


def artifact_ref(run_dir: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(run_dir).as_posix()
    _safe_rel(rel, "artifact path")
    return {"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScoringFailure("MALFORMED_JSON", f"{label}: {exc}") from exc
    value = _require_dict(value, label)
    if canonical_json_bytes(value) != data:
        raise ScoringFailure("NON_CANONICAL_JSON", f"{label} is not canonical JSON")
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ScoringFailure("SYMLINK_REFUSED", f"output parent is not a real directory: {path.parent}")
    if path.exists() or path.is_symlink():
        raise ScoringFailure("NO_CLOBBER", f"refusing to overwrite {path}")
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise ScoringFailure("NO_CLOBBER", f"refusing to overwrite {path}")
        os.rename(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class CsvPartition:
    raw: bytes
    row_count: int

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.raw)


@dataclass(frozen=True)
class ValidatedCsv:
    header: bytes
    newline: bytes
    partitions: dict[str, CsvPartition]
    typed_graph_sha256: str


def _parse_int(text: str, label: str, *, nonnegative: bool = False) -> int:
    pattern = UINT_RE if nonnegative else INT_RE
    if pattern.fullmatch(text) is None:
        raise ScoringFailure("MALFORMED_CSV", f"{label} is not a canonical base-10 integer: {text!r}")
    return int(text)


def validate_submission_csv(
    path: Path,
    expected_stems: Sequence[str],
    bounds: Mapping[str, tuple[int, int, int, int]],
    *,
    full_generation: bool,
) -> ValidatedCsv:
    """Strictly validate the physical writer contract and graph invariants."""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ScoringFailure("MALFORMED_CSV", "UTF-8 BOM is forbidden")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ScoringFailure("MALFORMED_CSV", "CSV is not UTF-8") from exc
    if not raw or not (raw.endswith(b"\n")) or b"\x00" in raw or '"' in text:
        raise ScoringFailure("MALFORMED_CSV", "CSV requires a final newline and forbids NUL/quoting")
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    if newline == b"\r\n" and raw.replace(b"\r\n", b"").find(b"\n") >= 0:
        raise ScoringFailure("MALFORMED_CSV", "mixed line endings")
    if newline == b"\n" and b"\r" in raw:
        raise ScoringFailure("MALFORMED_CSV", "bare CR is forbidden")
    physical = raw.splitlines(keepends=True)
    header = (",".join(CSV_COLUMNS)).encode() + newline
    if not physical or physical[0] != header:
        raise ScoringFailure("MALFORMED_CSV", "exact ten-column header/order required")
    expected = tuple(expected_stems)
    if len(expected) != len(set(expected)) or set(expected) & PUBLIC_FOUR:
        raise ScoringFailure("DATASET_SET_MISMATCH", "expected stems duplicate or contain public-four")
    if set(bounds) != set(expected):
        raise ScoringFailure("DATASET_SET_MISMATCH", "bounds do not exactly cover requested stems")

    partitions_data: dict[str, bytearray] = {stem: bytearray() for stem in expected}
    rows_count = {stem: 0 for stem in expected}
    nodes: dict[str, dict[int, int]] = {stem: {} for stem in expected}
    edges: dict[str, set[tuple[int, int]]] = {stem: set() for stem in expected}
    indegree: dict[str, dict[int, int]] = {stem: {} for stem in expected}
    outdegree: dict[str, dict[int, int]] = {stem: {} for stem in expected}
    typed_nodes: dict[str, list[list[int]]] = {stem: [] for stem in expected}
    typed_edges: dict[str, list[list[int]]] = {stem: [] for stem in expected}
    seen_blocks: list[str] = []
    current: str | None = None
    edge_phase = False
    last_node_id = -1
    row_ids: list[int] = []
    for position, line in enumerate(physical[1:], start=1):
        if line in (b"\n", b"\r\n") or not line.endswith(newline):
            raise ScoringFailure("MALFORMED_CSV", f"empty/truncated physical row {position}")
        try:
            fields = next(csv.reader(io.StringIO(line.decode("utf-8"), newline=""), strict=True))
        except (csv.Error, UnicodeDecodeError) as exc:
            raise ScoringFailure("MALFORMED_CSV", f"row {position}: {exc}") from exc
        if len(fields) != len(CSV_COLUMNS) or any(field == "" for field in fields):
            raise ScoringFailure("MALFORMED_CSV", f"row {position}: exactly ten nonempty fields required")
        row_id = _parse_int(fields[0], f"row {position} id", nonnegative=True)
        dataset, row_type = fields[1], fields[2]
        if dataset not in partitions_data:
            raise ScoringFailure("DATASET_SET_MISMATCH", f"unexpected dataset {dataset!r}")
        if dataset != current:
            if dataset in seen_blocks:
                raise ScoringFailure("DATASET_ORDER", f"dataset {dataset} appears in multiple blocks")
            seen_blocks.append(dataset)
            current = dataset
            edge_phase = False
            last_node_id = -1
        vals = [_parse_int(v, f"row {position} {CSV_COLUMNS[i]}") for i, v in enumerate(fields[3:], start=3)]
        node_id, t, z, y, x, source_id, target_id = vals
        if row_type == "node":
            if edge_phase:
                raise ScoringFailure("ROW_ORDER", f"{dataset}: node follows edge")
            if node_id < 0 or any(v < 0 for v in (t, z, y, x)) or source_id != -1 or target_id != -1:
                raise ScoringFailure("ROW_SENTINEL", f"{dataset}: invalid node row sentinels/values")
            if node_id <= last_node_id or node_id in nodes[dataset]:
                raise ScoringFailure("NODE_ORDER", f"{dataset}: node IDs must be unique and increasing")
            shape = bounds[dataset]
            if len(shape) != 4 or not (t < shape[0] and z < shape[1] and y < shape[2] and x < shape[3]):
                raise ScoringFailure("COORDINATE_BOUNDS", f"{dataset}: node {node_id} outside TZYX bounds")
            nodes[dataset][node_id] = t
            typed_nodes[dataset].append([node_id, t, z, y, x])
            last_node_id = node_id
        elif row_type == "edge":
            edge_phase = True
            if (node_id, t, z, y, x) != (-1, -1, -1, -1, -1) or source_id < 0 or target_id < 0:
                raise ScoringFailure("ROW_SENTINEL", f"{dataset}: invalid edge row sentinels/values")
            pair = (source_id, target_id)
            if source_id == target_id or pair in edges[dataset]:
                raise ScoringFailure("DUPLICATE_EDGE", f"{dataset}: duplicate/self edge {pair}")
            edges[dataset].add(pair)
            typed_edges[dataset].append([source_id, target_id])
            indegree[dataset][target_id] = indegree[dataset].get(target_id, 0) + 1
            outdegree[dataset][source_id] = outdegree[dataset].get(source_id, 0) + 1
        else:
            raise ScoringFailure("MALFORMED_CSV", f"row {position}: invalid row_type {row_type!r}")
        row_ids.append(row_id)
        partitions_data[dataset].extend(line)
        rows_count[dataset] += 1
    if tuple(seen_blocks) != expected:
        raise ScoringFailure("DATASET_ORDER", f"dataset blocks {seen_blocks!r} != frozen order {list(expected)!r}")
    if full_generation and row_ids != list(range(len(row_ids))):
        raise ScoringFailure("ROW_ID_SEQUENCE", "full-generation IDs must be contiguous in physical order")
    if not full_generation and len(row_ids) != len(set(row_ids)):
        raise ScoringFailure("ROW_ID_SEQUENCE", "subset IDs must remain globally unique")
    for stem in expected:
        if not nodes[stem]:
            raise ScoringFailure("EMPTY_DATASET", f"{stem}: at least one node required")
        for source, target in edges[stem]:
            if source not in nodes[stem] or target not in nodes[stem]:
                raise ScoringFailure("DANGLING_EDGE", f"{stem}: dangling edge {(source, target)}")
            if nodes[stem][target] != nodes[stem][source] + 1:
                raise ScoringFailure("NONCONSECUTIVE_EDGE", f"{stem}: edge {(source, target)} is not t->t+1")
        if any(v > 1 for v in indegree[stem].values()) or any(v > 2 for v in outdegree[stem].values()):
            raise ScoringFailure("DEGREE_VIOLATION", f"{stem}: indegree>1 or outdegree>2")
    return ValidatedCsv(
        header=header,
        newline=newline,
        partitions={stem: CsvPartition(bytes(partitions_data[stem]), rows_count[stem]) for stem in expected},
        typed_graph_sha256=canonical_digest(
            {
                "schema_version": "biohub.st_r3.typed_submission_graph.v1",
                "datasets": [
                    {"dataset": stem, "nodes": typed_nodes[stem], "edges": typed_edges[stem]} for stem in expected
                ],
            }
        ),
    )


def subset_bytes(full: ValidatedCsv, stems: Sequence[str]) -> bytes:
    return full.header + b"".join(full.partitions[stem].raw for stem in stems)


@dataclass(frozen=True)
class SealedInputs:
    run_dir: Path
    manifest: dict[str, Any]
    manifest_path: Path
    manifest_sha256: str
    gt_dir: Path
    gt_inventory: dict[str, Any]
    csv_paths: dict[str, Path]
    csvs: dict[str, ValidatedCsv]
    feasibility_ref: dict[str, Any]


def _check_case_collisions(paths: Iterable[str], label: str) -> None:
    seen: dict[str, str] = {}
    for value in paths:
        folded = value.casefold()
        if folded in seen and seen[folded] != value:
            raise ScoringFailure("CASE_COLLISION", f"{label}: {seen[folded]!r} collides with {value!r}")
        if value in seen.values():
            raise ScoringFailure("DUPLICATE_PATH", f"{label}: duplicate {value!r}")
        seen[folded] = value


def _validate_artifact_list(run_dir: Path, value: Any) -> set[str]:
    if not isinstance(value, list):
        raise ScoringFailure("SCHEMA_MISMATCH", "artifacts must be an array")
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        ref, _ = _validate_ref(run_dir, item, f"artifacts[{index}]")
        refs.append(ref)
    paths = [ref["path"] for ref in refs]
    _check_case_collisions(paths, "artifacts")
    if paths != sorted(paths):
        raise ScoringFailure("SCHEMA_MISMATCH", "artifacts must be POSIX-path sorted")
    return set(paths)


def _reject_gt_exposure(value: Any, label: str) -> None:
    """Reject explicit GT capability/path fields from an arm receipt."""
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.casefold()
            tokens = set(re.split(r"[^a-z0-9]+", lowered))
            if "gt" in tokens or "groundtruth" in tokens or ("ground" in tokens and "truth" in tokens):
                raise ScoringFailure("GT_EXPOSED_TO_ARM", f"{label}: forbidden GT field {key!r}")
            _reject_gt_exposure(child, label)
    elif isinstance(value, list):
        for child in value:
            _reject_gt_exposure(child, label)


def _reject_public_four(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_public_four(key, label)
            _reject_public_four(child, label)
    elif isinstance(value, list):
        for child in value:
            _reject_public_four(child, label)
    elif isinstance(value, str) and any(stem in value for stem in PUBLIC_FOUR):
        raise ScoringFailure("PUBLIC_FOUR_CONTAMINATION", f"{label} contains a public-four stem")


def _validate_current_source(run_dir: Path, manifest: Mapping[str, Any]) -> None:
    repo = Path(__file__).resolve().parents[2]
    bindings = _require_dict(manifest["source_bindings"], "source_bindings")
    _exact_keys(bindings, SOURCE_BINDING_KEYS, "source_bindings")
    actual = {
        "evaluate_py_sha256": sha256_file(repo / "src" / "biohub" / "evaluate.py"),
        "st_r3_scoring_py_sha256": sha256_file(Path(__file__).resolve()),
    }
    for key, value in actual.items():
        if _require_sha(bindings[key], f"source_bindings.{key}") != value:
            raise ScoringFailure("SOURCE_HASH_DRIFT", f"{key} differs from sealed source")
    if bindings["tracked_tree_clean"] is not True:
        raise ScoringFailure("SOURCE_DIRTY", "source binding does not assert a clean tracked tree")
    expected_commit = _require_git_commit(bindings["superproject_commit"], "source_bindings.superproject_commit")
    try:
        actual_commit = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--error-unmatch", "src/biohub/st_r3_scoring.py"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScoringFailure("SOURCE_NOT_COMMITTED", f"cannot prove scorer is committed: {exc}") from exc
    if actual_commit != expected_commit or dirty:
        raise ScoringFailure("SOURCE_DIRTY", "superproject commit/tree differs from preregistration")

    official = _require_dict(manifest["official"], "official")
    _exact_keys(official, OFFICIAL_KEYS, "official")
    if official["clean"] is not True:
        raise ScoringFailure("OFFICIAL_DIRTY", "official.clean must be true")
    gitlink = _require_git_commit(official["gitlink"], "official.gitlink")
    head = _require_git_commit(official["head"], "official.head")
    source_hashes = _require_dict(official["source_hashes"], "official.source_hashes")
    _exact_keys(source_hashes, OFFICIAL_SOURCE_KEYS, "official.source_hashes")
    official_dir = repo / "official"
    try:
        actual_head = subprocess.run(
            ["git", "-C", str(official_dir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        clean_output = subprocess.run(
            ["git", "-C", str(official_dir), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        ls_tree = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "HEAD", "official"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        actual_gitlink = ls_tree[2] if len(ls_tree) == 4 and ls_tree[1] == "commit" else ""
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScoringFailure("OFFICIAL_TRUST_CHECK", f"cannot verify official git state: {exc}") from exc
    if actual_head != head or actual_gitlink != gitlink or head != gitlink:
        raise ScoringFailure("OFFICIAL_HASH_DRIFT", "official HEAD/gitlink mismatch")
    if clean_output:
        raise ScoringFailure("OFFICIAL_DIRTY", "official submodule has tracked modifications")
    for rel, expected in source_hashes.items():
        _require_sha(expected, f"official.source_hashes.{rel}")
        if sha256_file(official_dir / "src" / rel) != expected:
            raise ScoringFailure("OFFICIAL_HASH_DRIFT", f"official source hash drift: {rel}")


def _load_gt_inventory(run_dir: Path, ref_value: Any, expected_gt_dir: PurePosixPath) -> dict[str, Any]:
    _, path = _validate_ref(run_dir, ref_value, "scoring_inputs.gt_inventory")
    inventory = _read_json(path, "GT inventory")
    _exact_keys(inventory, frozenset({"schema_version", "stems", "records"}), "GT inventory")
    if inventory["schema_version"] != GT_INVENTORY_SCHEMA or inventory["stems"] != list(EVAL36):
        raise ScoringFailure("GT_INVENTORY_MISMATCH", "GT inventory schema/stems mismatch")
    if not isinstance(inventory["records"], list):
        raise ScoringFailure("GT_INVENTORY_MISMATCH", "GT inventory records must be an array")
    paths: list[str] = []
    for index, record_value in enumerate(inventory["records"]):
        record = _require_dict(record_value, f"GT inventory records[{index}]")
        _exact_keys(record, REF_KEYS, f"GT inventory records[{index}]")
        rel = _safe_rel(record["path"], f"GT inventory records[{index}].path")
        try:
            inside = rel.relative_to(expected_gt_dir)
        except ValueError as exc:
            raise ScoringFailure("GT_INVENTORY_MISMATCH", f"GT record outside gt_view: {rel}") from exc
        if len(inside.parts) < 2:
            raise ScoringFailure("GT_INVENTORY_MISMATCH", f"GT record is not below a dataset root: {rel}")
        expected_roots = {f"{stem}.geff" for stem in EVAL36} | {f"{stem}.zarr" for stem in EVAL36}
        if inside.parts[0] not in expected_roots:
            raise ScoringFailure("GT_INVENTORY_MISMATCH", f"GT record has unexpected dataset root: {rel}")
        if type(record["bytes"]) is not int or record["bytes"] < 0:
            raise ScoringFailure("GT_INVENTORY_MISMATCH", "GT record bytes must be nonnegative integer")
        _require_sha(record["sha256"], f"GT inventory records[{index}].sha256")
        paths.append(record["path"])
    _check_case_collisions(paths, "GT inventory")
    if paths != sorted(paths):
        raise ScoringFailure("GT_INVENTORY_MISMATCH", "GT records must be path sorted")
    return inventory


def _read_shape(zarr_root: Path, stem: str) -> tuple[int, int, int, int]:
    path = zarr_root / "0" / "zarr.json"
    value = _read_json_relaxed(path, f"{stem} array metadata")
    shape = value.get("shape")
    if not isinstance(shape, list) or len(shape) != 4 or any(type(v) is not int or v <= 0 for v in shape):
        raise ScoringFailure("MALFORMED_IMAGE_METADATA", f"{stem}: expected positive TZYX shape")
    return tuple(shape)  # type: ignore[return-value]


def _read_json_relaxed(path: Path, label: str) -> dict[str, Any]:
    try:
        return _require_dict(json.loads(path.read_bytes()), label)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScoringFailure("MALFORMED_JSON", f"{label}: {exc}") from exc


def validate_feasibility_manifest(run_dir: Path | str, expected_sha256: str) -> SealedInputs:
    """Validate the exact upstream handoff and the canonical full-36 CSVs."""
    supplied_run_dir = Path(run_dir)
    if supplied_run_dir.is_symlink() or not supplied_run_dir.is_dir():
        raise ScoringFailure("INVALID_RUN_DIR", "run directory must be a real directory")
    run_dir = supplied_run_dir.resolve()
    expected_sha256 = _require_sha(expected_sha256, "generation_manifest_sha256")
    manifest_path = _resolve(run_dir, "feasibility/FEASIBILITY_PASS.json", "feasibility manifest")
    if sha256_file(manifest_path) != expected_sha256:
        raise ScoringFailure("MANIFEST_HASH_MISMATCH", "caller-provided manifest SHA does not match")
    manifest = _read_json(manifest_path, "feasibility manifest")
    _exact_keys(manifest, FEASIBILITY_KEYS, "feasibility manifest")
    if manifest["schema_version"] != FEASIBILITY_SCHEMA or manifest["state"] != "FEASIBILITY_PASS":
        raise ScoringFailure("STATE_MISMATCH", "exact feasibility schema/state required")
    _reject_public_four(manifest, "feasibility manifest")
    if not isinstance(manifest["run_id"], str) or not manifest["run_id"]:
        raise ScoringFailure("SCHEMA_MISMATCH", "run_id must be nonempty")

    prereg, prereg_path = _validate_ref(run_dir, manifest["preregistration"], "preregistration")
    if prereg["path"] != "PREREGISTRATION.json":
        raise ScoringFailure("SCHEMA_MISMATCH", "preregistration path must be PREREGISTRATION.json")
    generation = _require_dict(manifest["generation_manifest"], "generation_manifest")
    _exact_keys(generation, frozenset({"ref", "preregistration_sha256"}), "generation_manifest")
    generation_ref, generation_path = _validate_ref(run_dir, generation["ref"], "generation_manifest.ref")
    if generation_ref["path"] != "generation/ARTIFACT_MANIFEST.json":
        raise ScoringFailure("SCHEMA_MISMATCH", "generation manifest path is fixed")
    if (
        _require_sha(generation["preregistration_sha256"], "generation_manifest.preregistration_sha256")
        != prereg["sha256"]
    ):
        raise ScoringFailure("MANIFEST_CHAIN_BROKEN", "generation does not chain to preregistration")
    generation_value = _read_json(generation_path, "generation manifest")
    if generation_value.get("state") != "GENERATION_SEALED":
        raise ScoringFailure("STATE_MISMATCH", "preceding generation manifest is not GENERATION_SEALED")
    if generation_value.get("preregistration_sha256") != prereg["sha256"]:
        raise ScoringFailure("MANIFEST_CHAIN_BROKEN", "generation file does not bind preregistration")
    prereg_value = _read_json(prereg_path, "preregistration")
    if prereg_value.get("run_id") != manifest["run_id"]:
        raise ScoringFailure("MANIFEST_CHAIN_BROKEN", "run_id differs from preregistration")

    datasets = _require_dict(manifest["datasets"], "datasets")
    _exact_keys(datasets, DATASET_KEYS, "datasets")
    exact_lists = {"eval12": EVAL12, "eval24": EVAL24, "eval36": EVAL36}
    for name, stems in exact_lists.items():
        if datasets[name] != list(stems):
            raise ScoringFailure("DATASET_SET_MISMATCH", f"{name} is not the frozen ordered list")
    digests = _require_dict(datasets["digests"], "datasets.digests")
    _exact_keys(digests, frozenset(exact_lists), "datasets.digests")
    for name, stems in exact_lists.items():
        if _require_sha(digests[name], f"datasets.digests.{name}") != dataset_digest(stems):
            raise ScoringFailure("DATASET_SET_MISMATCH", f"{name} digest mismatch")
    if len(set(EVAL36)) != 36 or set(EVAL12) & set(EVAL24) or set(EVAL36) & PUBLIC_FOUR:
        raise ScoringFailure("INTERNAL_CONTRACT_ERROR", "frozen dataset constants invalid")
    if sum(s.startswith("44b6_") for s in EVAL36) != 18 or sum(s.startswith("6bba_") for s in EVAL36) != 18:
        raise ScoringFailure("INTERNAL_CONTRACT_ERROR", "frozen lineage counts invalid")

    executions = _require_dict(manifest["executions"], "executions")
    _exact_keys(executions, EXECUTION_KEYS, "executions")
    for key in EXECUTION_KEYS:
        _, receipt_path = _validate_ref(run_dir, executions[key], f"executions.{key}")
        _reject_gt_exposure(_read_json(receipt_path, f"executions.{key}"), f"executions.{key}")
    sealed = _require_dict(manifest["sealed_hashes"], "sealed_hashes")
    _exact_keys(sealed, SEALED_HASH_KEYS, "sealed_hashes")
    for key, value in sealed.items():
        _require_sha(value, f"sealed_hashes.{key}")

    feasibility = _require_dict(manifest["feasibility"], "feasibility")
    _exact_keys(feasibility, FEASIBILITY_GATE_KEYS, "feasibility")
    feasibility_ref, _ = _validate_ref(run_dir, feasibility["ref"], "feasibility.ref")
    for key in FEASIBILITY_GATE_KEYS - {"ref"}:
        if feasibility[key] is not True:
            raise ScoringFailure("FEASIBILITY_NOT_PASS", f"feasibility.{key} is not true")

    scoring_inputs = _require_dict(manifest["scoring_inputs"], "scoring_inputs")
    _exact_keys(scoring_inputs, SCORING_INPUT_KEYS, "scoring_inputs")
    gt_rel = _safe_rel(scoring_inputs["gt_view"], "scoring_inputs.gt_view")
    image_rel = _safe_rel(scoring_inputs["image_view"], "scoring_inputs.image_view")
    gt_dir = _resolve(run_dir, gt_rel.as_posix(), "scoring_inputs.gt_view", regular=False)
    _resolve(run_dir, image_rel.as_posix(), "scoring_inputs.image_view", regular=False)
    gt_inventory = _load_gt_inventory(run_dir, scoring_inputs["gt_inventory"], gt_rel)
    image_ref, _ = _validate_ref(
        run_dir, scoring_inputs["image_content_inventory"], "scoring_inputs.image_content_inventory"
    )
    if image_ref["sha256"] != sealed["image_content_inventory_sha256"]:
        raise ScoringFailure("HASH_DRIFT", "image inventory binding differs from sealed hash")

    official = _require_dict(manifest["official"], "official")
    _exact_keys(official, OFFICIAL_KEYS, "official")
    _validate_current_source(run_dir, manifest)
    artifact_paths = _validate_artifact_list(run_dir, manifest["artifacts"])

    # Inspect names only: scoring bytes are read for the unlocked stage later.
    entries = list(os.scandir(gt_dir))
    if any(entry.is_symlink() or not entry.is_dir(follow_symlinks=False) for entry in entries):
        raise ScoringFailure("SPECIAL_FILE_REFUSED", "GT view may contain only real GEFF/Zarr directories")
    expected_entries = {f"{stem}.geff" for stem in EVAL36} | {f"{stem}.zarr" for stem in EVAL36}
    actual_entries = {entry.name for entry in entries}
    _check_case_collisions(actual_entries, "GT view")
    if actual_entries != expected_entries:
        raise ScoringFailure("GT_INVENTORY_MISMATCH", "GT view roots are not exactly eval36 GEFF+Zarr")

    bounds = {stem: _read_shape(gt_dir / f"{stem}.zarr", stem) for stem in EVAL36}
    canonical = _require_dict(manifest["canonical_submissions"], "canonical_submissions")
    _exact_keys(canonical, frozenset({"baseline", "candidate"}), "canonical_submissions")
    csv_paths: dict[str, Path] = {}
    csvs: dict[str, ValidatedCsv] = {}
    for arm in ("baseline", "candidate"):
        item = _require_dict(canonical[arm], f"canonical_submissions.{arm}")
        _exact_keys(item, CANONICAL_SUBMISSION_KEYS, f"canonical_submissions.{arm}")
        ref, path = _validate_ref(run_dir, item["ref"], f"canonical_submissions.{arm}.ref")
        if ref["path"] != f"generation/canonical/{arm}/submission.csv":
            raise ScoringFailure("SCHEMA_MISMATCH", f"canonical {arm} path is fixed")
        parsed = validate_submission_csv(path, EVAL36, bounds, full_generation=True)
        if (
            _require_sha(item["typed_graph_sha256"], f"canonical_submissions.{arm}.typed_graph_sha256")
            != parsed.typed_graph_sha256
        ):
            raise ScoringFailure("TYPED_GRAPH_HASH_MISMATCH", f"canonical {arm} typed graph hash drift")
        partitions = _require_dict(item["partitions"], f"canonical_submissions.{arm}.partitions")
        if set(partitions) != set(EVAL36):
            raise ScoringFailure("DATASET_SET_MISMATCH", f"canonical {arm} partitions differ from eval36")
        for stem in EVAL36:
            record = _require_dict(partitions[stem], f"canonical_submissions.{arm}.partitions.{stem}")
            _exact_keys(record, PARTITION_KEYS, f"canonical_submissions.{arm}.partitions.{stem}")
            part = parsed.partitions[stem]
            if (
                _require_sha(record["sha256"], f"partition {stem} sha") != part.sha256
                or record["bytes"] != len(part.raw)
                or record["row_count"] != part.row_count
                or type(record["bytes"]) is not int
                or type(record["row_count"]) is not int
            ):
                raise ScoringFailure("PARTITION_HASH_MISMATCH", f"{arm}/{stem} partition differs from full CSV")
        csv_paths[arm] = path
        csvs[arm] = parsed

    required_refs = {
        prereg["path"],
        generation_ref["path"],
        feasibility_ref["path"],
        scoring_inputs["gt_inventory"]["path"],
        scoring_inputs["image_content_inventory"]["path"],
        *(executions[key]["path"] for key in EXECUTION_KEYS),
        *(canonical[arm]["ref"]["path"] for arm in ("baseline", "candidate")),
    }
    if not required_refs <= artifact_paths:
        raise ScoringFailure("ARTIFACT_SET_MISMATCH", "feasibility artifacts omit a required referenced file")

    return SealedInputs(
        run_dir=run_dir,
        manifest=manifest,
        manifest_path=manifest_path,
        manifest_sha256=expected_sha256,
        gt_dir=gt_dir,
        gt_inventory=gt_inventory,
        csv_paths=csv_paths,
        csvs=csvs,
        feasibility_ref=feasibility_ref,
    )


def _inventory_records(inventory: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["path"]: record for record in inventory["records"]}


def _walk_regular_tree(root: Path, run_dir: Path) -> list[Path]:
    files: list[Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        for entry in os.scandir(directory):
            path = Path(entry.path)
            if entry.is_symlink():
                raise ScoringFailure("SYMLINK_REFUSED", f"symlink in GT tree: {path.relative_to(run_dir)}")
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                stack.append(path)
            elif stat.S_ISREG(mode):
                files.append(path)
            else:
                raise ScoringFailure("SPECIAL_FILE_REFUSED", f"special file in GT tree: {path.relative_to(run_dir)}")
    return sorted(files, key=lambda p: p.relative_to(run_dir).as_posix())


def _verify_unlocked_gt(sealed: SealedInputs, stems: Sequence[str]) -> dict[str, dict[str, Any]]:
    records = _inventory_records(sealed.gt_inventory)
    receipt: dict[str, dict[str, Any]] = {}
    for stem in stems:
        geff = sealed.gt_dir / f"{stem}.geff"
        zarr_root = sealed.gt_dir / f"{stem}.zarr"
        actual_files = _walk_regular_tree(geff, sealed.run_dir) + _walk_regular_tree(zarr_root, sealed.run_dir)
        actual_paths = sorted(path.relative_to(sealed.run_dir).as_posix() for path in actual_files)
        prefix_geff = geff.relative_to(sealed.run_dir).as_posix() + "/"
        prefix_zarr = zarr_root.relative_to(sealed.run_dir).as_posix() + "/"
        expected_paths = sorted(
            path for path in records if path.startswith(prefix_geff) or path.startswith(prefix_zarr)
        )
        if actual_paths != expected_paths:
            raise ScoringFailure("GT_INVENTORY_MISMATCH", f"{stem}: GT tree paths differ from inventory")
        for path in actual_files:
            rel = path.relative_to(sealed.run_dir).as_posix()
            record = records[rel]
            if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
                raise ScoringFailure("GT_HASH_DRIFT", f"{stem}: hash drift at {rel}")
        receipt[stem] = _validate_metadata_binding(sealed, stem)
    return receipt


def _parse_explicit_scale(zarr_root: Path, stem: str) -> tuple[tuple[float, float, float], Any, Path]:
    root_meta = zarr_root / "zarr.json"
    value = _read_json_relaxed(root_meta, f"{stem} root Zarr metadata")
    attrs = value.get("attributes")
    if not isinstance(attrs, dict):
        raise ScoringFailure("MISSING_EXPLICIT_SCALE", f"{stem}: attributes missing")
    ngff = attrs.get("ome", attrs)
    if not isinstance(ngff, dict) or not isinstance(ngff.get("multiscales"), list) or len(ngff["multiscales"]) != 1:
        raise ScoringFailure("MISSING_EXPLICIT_SCALE", f"{stem}: exactly one multiscales entry required")
    multiscale = _require_dict(ngff["multiscales"][0], f"{stem} multiscales[0]")
    datasets = multiscale.get("datasets")
    if not isinstance(datasets, list):
        raise ScoringFailure("MISSING_EXPLICIT_SCALE", f"{stem}: datasets missing")
    matches = [item for item in datasets if isinstance(item, dict) and str(item.get("path", "")).strip("/") == "0"]
    if len(matches) != 1:
        raise ScoringFailure("MISSING_EXPLICIT_SCALE", f"{stem}: scored array path 0 is ambiguous/missing")
    transforms = matches[0].get("coordinateTransformations")
    if not isinstance(transforms, list):
        raise ScoringFailure("MISSING_EXPLICIT_SCALE", f"{stem}: coordinateTransformations missing")
    scale_transforms = [item for item in transforms if isinstance(item, dict) and item.get("type") == "scale"]
    if len(scale_transforms) != 1:
        raise ScoringFailure("MISSING_EXPLICIT_SCALE", f"{stem}: exactly one scale transform required")
    raw_scale = scale_transforms[0].get("scale")
    if not isinstance(raw_scale, list) or len(raw_scale) not in (3, 4):
        raise ScoringFailure("MALFORMED_SCALE", f"{stem}: scale must have three spatial values plus optional time")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw_scale):
        raise ScoringFailure("MALFORMED_SCALE", f"{stem}: scale values must be numeric")
    if len(raw_scale) == 4:
        axes = multiscale.get("axes")
        if axes is not None:
            if not isinstance(axes, list) or len(axes) != 4:
                raise ScoringFailure("MALFORMED_SCALE", f"{stem}: axes do not match scale")
            axis_names = [axis.get("name") if isinstance(axis, dict) else axis for axis in axes]
            if axis_names[0] not in ("t", "time") or tuple(axis_names[-3:]) != ("z", "y", "x"):
                raise ScoringFailure("MALFORMED_SCALE", f"{stem}: axes are not TZYX")
        spatial_raw = raw_scale[-3:]
    else:
        spatial_raw = raw_scale
    scale = tuple(float(item) for item in spatial_raw)
    if len(scale) != 3 or any(not math.isfinite(item) or item <= 0 for item in scale):
        raise ScoringFailure("MALFORMED_SCALE", f"{stem}: scale must be finite and positive")
    return scale, raw_scale, root_meta


def _validate_metadata_binding(sealed: SealedInputs, stem: str) -> dict[str, Any]:
    from geff import GeffMetadata

    from biohub.io import estimated_number_of_nodes, read_scale

    geff = sealed.gt_dir / f"{stem}.geff"
    scale, raw_scale, scale_path = _parse_explicit_scale(sealed.gt_dir / f"{stem}.zarr", stem)
    try:
        helper_scale = tuple(read_scale(sealed.gt_dir / f"{stem}.zarr"))
    except Exception as exc:
        raise ScoringFailure("SCALE_HELPER_MISMATCH", f"{stem}: read_scale failed: {exc}") from exc
    if helper_scale != scale:
        raise ScoringFailure("SCALE_HELPER_MISMATCH", f"{stem}: strict scale != read_scale result")
    try:
        metadata = GeffMetadata.read(geff)
    except Exception as exc:
        raise ScoringFailure("MALFORMED_N_TOTAL", f"{stem}: GEFF metadata unreadable: {exc}") from exc
    extra = metadata.extra or {}
    if "estimated_number_of_nodes" not in extra:
        raise ScoringFailure("MISSING_N_TOTAL", f"{stem}: estimated_number_of_nodes absent")
    raw_n_total = extra["estimated_number_of_nodes"]
    if isinstance(raw_n_total, bool) or not isinstance(raw_n_total, (int, float)):
        raise ScoringFailure("MALFORMED_N_TOTAL", f"{stem}: n_total must be explicitly numeric")
    n_total = float(raw_n_total)
    if not math.isfinite(n_total) or n_total <= 0:
        raise ScoringFailure("MALFORMED_N_TOTAL", f"{stem}: n_total must be finite and positive")
    helper_n_total = estimated_number_of_nodes(geff)
    if helper_n_total != raw_n_total:
        raise ScoringFailure("N_TOTAL_HELPER_MISMATCH", f"{stem}: helper n_total differs")
    geff_meta_path = geff / "zarr.json"
    records = _inventory_records(sealed.gt_inventory)
    scale_rel = scale_path.relative_to(sealed.run_dir).as_posix()
    geff_rel = geff_meta_path.relative_to(sealed.run_dir).as_posix()
    if scale_rel not in records or geff_rel not in records:
        raise ScoringFailure("GT_INVENTORY_MISMATCH", f"{stem}: metadata paths absent from inventory")
    return {
        "geff_metadata": {"path": geff_rel, "sha256": records[geff_rel]["sha256"]},
        "n_total_raw": raw_n_total,
        "n_total": n_total,
        "scale_metadata": {"path": scale_rel, "sha256": records[scale_rel]["sha256"]},
        "scale_raw": raw_scale,
        "scale_zyx_um": list(scale),
    }


def _normalise_summary(summary: Mapping[str, Any], label: str) -> dict[str, Any]:
    if frozenset(summary) != SUMMARY_KEYS:
        raise ScoringFailure("OFFICIAL_KEY_DRIFT", f"{label}: official summarise key set changed")
    result: dict[str, Any] = {}
    for key in sorted(SUMMARY_KEYS):
        value = summary[key]
        if key in {"n", "division_tp", "division_fp", "division_fn", "n_adj"}:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ScoringFailure("OFFICIAL_TYPE_DRIFT", f"{label}.{key} is not int")
            result[key] = value
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ScoringFailure("OFFICIAL_TYPE_DRIFT", f"{label}.{key} is not numeric")
            number = float(value)
            if not math.isfinite(number):
                if (
                    key == "division_jaccard"
                    and summary["division_tp"] + summary["division_fp"] + summary["division_fn"] == 0
                ):
                    result[key] = None
                    result["division_jaccard_status"] = "NO_DIVISION_DENOMINATOR"
                    continue
                raise ScoringFailure("NONFINITE_OFFICIAL_METRIC", f"{label}.{key} is nonfinite", gt_read_started=True)
            result[key] = number
    if "division_jaccard_status" not in result:
        result["division_jaccard_status"] = "FINITE"
    return result


def _validate_per_sample(row: Mapping[str, Any], stem: str, label: str) -> dict[str, Any]:
    if frozenset(row) != PER_SAMPLE_KEYS or row.get("dataset") != stem:
        raise ScoringFailure("OFFICIAL_KEY_DRIFT", f"{label}: per-sample key/dataset drift", gt_read_started=True)
    result: dict[str, Any] = {"dataset": stem}
    for key in sorted(PER_SAMPLE_KEYS - {"dataset"}):
        value = row[key]
        if key in COUNT_KEYS:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ScoringFailure("OFFICIAL_TYPE_DRIFT", f"{label}.{key} is not int", gt_read_started=True)
            result[key] = value
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ScoringFailure("NONFINITE_OFFICIAL_METRIC", f"{label}.{key} invalid", gt_read_started=True)
            result[key] = float(value)
    return result


def _official_summarise(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    from biohub.evaluate import summarise

    return _normalise_summary(summarise(rows), label)


def _raw_for_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "dataset"}


def _score_one(csv_path: Path, sealed: SealedInputs, stem: str, arm: str) -> dict[str, Any]:
    from biohub.evaluate import score_submission

    try:
        wrapper_summary, returned = score_submission(
            csv_path, sealed.gt_dir, max_distance=MAX_DISTANCE_UM, verbose=False
        )
    except Exception as exc:
        raise ScoringFailure("OFFICIAL_EVALUATION_ERROR", f"{arm}/{stem}: {exc}", gt_read_started=True) from exc
    if len(returned) != 1 or returned[0].get("dataset") != stem:
        raise ScoringFailure(
            "MISSING_GT_SKIP", f"{arm}/{stem}: wrapper did not return exact singleton", gt_read_started=True
        )
    per_sample = _validate_per_sample(returned[0], stem, f"{arm}/{stem}")
    singleton = _official_summarise([_raw_for_summary(per_sample)], f"{arm}/{stem} singleton")
    wrapper = _normalise_summary(wrapper_summary, f"{arm}/{stem} wrapper")
    if canonical_json_bytes(singleton) != canonical_json_bytes(wrapper):
        raise ScoringFailure(
            "OFFICIAL_SUMMARY_MISMATCH", f"{arm}/{stem}: wrapper/singleton summary differ", gt_read_started=True
        )
    return {"per_sample": per_sample, "singleton_summary": singleton}


def paired_statistics(values: Sequence[float]) -> dict[str, float | int]:
    if not values or any(not math.isfinite(value) for value in values):
        raise ScoringFailure("NONFINITE_GATE_INPUT", "paired deltas must be nonempty and finite")
    ordered = sorted(values)
    n = len(ordered)
    middle = n // 2
    median = ordered[middle] if n % 2 else math.fsum((ordered[middle - 1], ordered[middle])) / 2
    return {"n": n, "mean": math.fsum(values) / n, "median": median, "worst": min(values)}


def _summary_delta(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(SUMMARY_KEYS):
        left, right = candidate[key], baseline[key]
        if left is None or right is None:
            result[key] = None
            result[f"{key}_status"] = "UNAVAILABLE_ZERO_DENOMINATOR"
        else:
            delta = left - right
            if isinstance(delta, float) and not math.isfinite(delta):
                raise ScoringFailure("NONFINITE_GATE_INPUT", f"nonfinite summary delta {key}", gt_read_started=True)
            result[key] = delta
    return result


def _group_aggregate(rows: Sequence[dict[str, Any]], stems: Sequence[str], group: str) -> dict[str, Any]:
    all_rows = {item["dataset"]: item for item in rows}
    if len(all_rows) != len(rows) or any(stem not in all_rows for stem in stems):
        raise ScoringFailure("DATASET_SET_MISMATCH", f"{group}: rows do not exactly match stems", gt_read_started=True)
    by_stem = {stem: all_rows[stem] for stem in stems}
    arm_summaries: dict[str, Any] = {}
    diagnostic_sums: dict[str, Any] = {}
    for arm in ("baseline", "candidate"):
        official_rows = [by_stem[stem][arm]["per_sample"] for stem in stems]
        arm_summaries[arm] = _official_summarise(
            [_raw_for_summary(row) for row in official_rows],
            f"{group}/{arm}",
        )
        diagnostic_sums[arm] = {key: sum(row[key] for row in official_rows) for key in sorted(COUNT_KEYS)}
    return {
        "baseline": arm_summaries["baseline"],
        "candidate": arm_summaries["candidate"],
        "delta": _summary_delta(arm_summaries["candidate"], arm_summaries["baseline"]),
        "diagnostic_sums": diagnostic_sums,
    }


def build_aggregates(rows: Sequence[dict[str, Any]], stems: Sequence[str], stage: str) -> dict[str, Any]:
    groups = {
        stage: tuple(stems),
        "44b6": tuple(stem for stem in stems if stem.startswith("44b6_")),
        "6bba": tuple(stem for stem in stems if stem.startswith("6bba_")),
    }
    return {
        "schema_version": "biohub.st_r3.official_aggregates.v1",
        "stage": stage,
        "groups": {name: _group_aggregate(rows, members, name) for name, members in groups.items()},
    }


def build_deltas(
    rows: Sequence[dict[str, Any]], aggregates: Mapping[str, Any], stems: Sequence[str], stage: str
) -> dict[str, Any]:
    by_stem = {item["dataset"]: item for item in rows}
    values: list[float] = []
    per_video: list[dict[str, Any]] = []
    for stem in stems:
        baseline = by_stem[stem]["baseline"]["singleton_summary"]["score"]
        candidate = by_stem[stem]["candidate"]["singleton_summary"]["score"]
        if not isinstance(baseline, (int, float)) or not isinstance(candidate, (int, float)):
            raise ScoringFailure("NONFINITE_GATE_INPUT", f"{stem}: combined score unavailable", gt_read_started=True)
        delta = float(candidate) - float(baseline)
        if not math.isfinite(delta):
            raise ScoringFailure("NONFINITE_GATE_INPUT", f"{stem}: nonfinite paired delta", gt_read_started=True)
        values.append(delta)
        per_video.append({"dataset": stem, "combined_score_delta": delta})
    return {
        "schema_version": "biohub.st_r3.paired_deltas.v1",
        "stage": stage,
        "per_video": per_video,
        "paired": paired_statistics(values),
        "official_aggregate_deltas": {name: group["delta"] for name, group in aggregates["groups"].items()},
    }


def _gate(name: str, value: Any, threshold: int | float) -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ScoringFailure("NONFINITE_GATE_INPUT", f"gate {name} input unavailable/nonfinite", gt_read_started=True)
    return {"name": name, "comparison": ">=", "threshold": threshold, "value": value, "pass": value >= threshold}


def evaluate_metric_gates(stage: str, deltas: Mapping[str, Any]) -> dict[str, Any]:
    paired = deltas["paired"]
    official = deltas["official_aggregate_deltas"]
    if stage == "eval12":
        gates = [
            _gate("paired_mean_combined_score_delta", paired["mean"], 0.005),
            _gate("paired_median_combined_score_delta", paired["median"], 0.0),
            _gate("paired_worst_combined_score_delta", paired["worst"], -0.002),
            _gate("official_aggregate_adjusted_edge_delta", official[stage]["adj_edge_jaccard"], -0.002),
            _gate("44b6_official_aggregate_combined_score_delta", official["44b6"]["score"], 0.0),
            _gate("6bba_official_aggregate_combined_score_delta", official["6bba"]["score"], 0.0),
        ]
        passed_state, failed_state = "EVAL12_PASS", "REJECT_EVAL12"
    elif stage == "eval24":
        gates = [
            _gate("paired_mean_combined_score_delta", paired["mean"], 0.003),
            _gate("paired_median_combined_score_delta", paired["median"], 0.0),
            _gate("paired_worst_combined_score_delta", paired["worst"], -0.002),
            _gate("official_aggregate_adjusted_edge_delta", official[stage]["adj_edge_jaccard"], -0.002),
            _gate("44b6_official_aggregate_combined_score_delta", official["44b6"]["score"], 0.0),
            _gate("6bba_official_aggregate_combined_score_delta", official["6bba"]["score"], 0.0),
        ]
        passed_state, failed_state = "EVAL24_PASS", "REJECT_EVAL24"
    elif stage == "eval36":
        gates = [
            _gate("official_aggregate_division_tp_delta", official[stage]["division_tp"], 4),
            _gate("official_aggregate_adjusted_edge_delta", official[stage]["adj_edge_jaccard"], -0.002),
            _gate("official_aggregate_combined_score_delta", official[stage]["score"], 0.0),
            _gate("official_aggregate_division_jaccard_delta", official[stage]["division_jaccard"], 0.0),
            _gate("paired_median_combined_score_delta", paired["median"], 0.0),
            _gate("paired_worst_combined_score_delta", paired["worst"], -0.002),
            _gate("44b6_official_aggregate_combined_score_delta", official["44b6"]["score"], 0.0),
            _gate("6bba_official_aggregate_combined_score_delta", official["6bba"]["score"], 0.0),
        ]
        passed_state, failed_state = "EVAL36_ADOPTION_CANDIDATE", "REJECT_EVAL36"
    else:
        raise ScoringFailure("INVALID_STAGE", f"unknown stage {stage!r}")
    first_failure = next((gate["name"] for gate in gates if not gate["pass"]), None)
    return {
        "schema_version": "biohub.st_r3.metric_gate.v1",
        "stage": stage,
        "gates": gates,
        "first_failure": first_failure,
        "status": passed_state if first_failure is None else failed_state,
    }


def evaluate_feasibility_thresholds(values: Mapping[str, Any]) -> dict[str, Any]:
    """Pure exact-boundary evaluator used by the upstream feasibility phase."""
    expected = frozenset(
        {
            "candidate_wall_gate",
            "baseline_wall_gate",
            "candidate_rss_gate",
            "baseline_rss_gate",
            "target_candidate_aggregate_peak_gate",
            "target_declared_ram_bytes",
            "target_eval36_charged_seconds",
            "target_declared_wall_seconds",
        }
    )
    if frozenset(values) != expected:
        raise ScoringFailure("SCHEMA_MISMATCH", "feasibility threshold inputs differ")
    numeric: dict[str, float] = {}
    for key, value in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise ScoringFailure("NONFINITE_GATE_INPUT", f"{key} must be finite and positive")
        numeric[key] = float(value)
    hidden_200 = numeric["target_eval36_charged_seconds"] * 200 / 36
    gates = [
        {"name": "local_runtime", "pass": numeric["candidate_wall_gate"] <= 1.25 * numeric["baseline_wall_gate"]},
        {"name": "local_rss", "pass": numeric["candidate_rss_gate"] <= numeric["baseline_rss_gate"] + 1_073_741_824},
        {
            "name": "target_memory",
            "pass": numeric["target_candidate_aggregate_peak_gate"] <= 0.80 * numeric["target_declared_ram_bytes"],
        },
        {"name": "hidden_200", "pass": hidden_200 <= 0.80 * numeric["target_declared_wall_seconds"]},
    ]
    return {"gates": gates, "hidden_200_seconds": hidden_200, "pass": all(gate["pass"] for gate in gates)}


def _stage_name(stage: str) -> str:
    if stage == "eval36":
        return "eval36_rollup"
    if stage in ("eval12", "eval24"):
        return stage
    raise ScoringFailure("INVALID_STAGE", f"stage must be eval12, eval24, or eval36, got {stage!r}")


def _score_dir(run_dir: Path, stage: str) -> Path:
    return run_dir / "scores" / _stage_name(stage)


def _verify_stage_manifest(
    run_dir: Path, stage: str, expected_state: str, feasibility_sha256: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    directory = _score_dir(run_dir, stage)
    path = _resolve(
        run_dir, (directory / "ARTIFACT_MANIFEST.json").relative_to(run_dir).as_posix(), f"{stage} manifest"
    )
    manifest = _read_json(path, f"{stage} manifest")
    _exact_keys(manifest, STAGE_MANIFEST_KEYS, f"{stage} manifest")
    if (
        manifest["schema_version"] != STAGE_MANIFEST_SCHEMA
        or manifest["stage"] != stage
        or manifest["state"] != expected_state
    ):
        raise ScoringFailure("STATE_MISMATCH", f"{stage}: prior state differs")
    if feasibility_sha256 is not None and manifest["feasibility_manifest_sha256"] != feasibility_sha256:
        raise ScoringFailure("MANIFEST_CHAIN_BROKEN", f"{stage}: feasibility hash differs")
    _require_sha(manifest["feasibility_manifest_sha256"], f"{stage}.feasibility_manifest_sha256")
    preceding = _require_dict(manifest["preceding_manifest"], f"{stage}.preceding_manifest")
    _exact_keys(preceding, REF_KEYS, f"{stage}.preceding_manifest")
    _validate_ref(run_dir, preceding, f"{stage}.preceding_manifest")
    if stage == "eval12":
        if preceding["path"] != "feasibility/FEASIBILITY_PASS.json":
            raise ScoringFailure("MANIFEST_CHAIN_BROKEN", "eval12 must chain to feasibility")
    elif stage == "eval24":
        prior_path = _score_dir(run_dir, "eval12") / "ARTIFACT_MANIFEST.json"
        if preceding != artifact_ref(run_dir, prior_path):
            raise ScoringFailure("MANIFEST_CHAIN_BROKEN", "eval24 must chain to eval12")
    elif stage == "eval36":
        prior_path = _score_dir(run_dir, "eval24") / "ARTIFACT_MANIFEST.json"
        if preceding != artifact_ref(run_dir, prior_path):
            raise ScoringFailure("MANIFEST_CHAIN_BROKEN", "eval36 must chain to eval24")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise ScoringFailure("SCHEMA_MISMATCH", f"{stage}: artifacts must be array")
    paths: list[str] = []
    for index, item_value in enumerate(artifacts):
        item = _require_dict(item_value, f"{stage}.artifacts[{index}]")
        _exact_keys(item, STAGE_ARTIFACT_KEYS, f"{stage}.artifacts[{index}]")
        ref = {key: item[key] for key in REF_KEYS}
        _validate_ref(run_dir, ref, f"{stage}.artifacts[{index}]")
        if not all(isinstance(item[key], str) and item[key] for key in ("media_type", "schema_type", "role")):
            raise ScoringFailure("SCHEMA_MISMATCH", f"{stage}: artifact metadata invalid")
        paths.append(item["path"])
    _check_case_collisions(paths, f"{stage} artifacts")
    if paths != sorted(paths):
        raise ScoringFailure("SCHEMA_MISMATCH", f"{stage}: artifact list not sorted")
    expected_files = set(paths) | {(path.relative_to(run_dir)).as_posix()}
    actual_files: set[str] = set()
    for file_path in _walk_regular_tree(directory, run_dir):
        actual_files.add(file_path.relative_to(run_dir).as_posix())
    if actual_files != expected_files:
        raise ScoringFailure("ARTIFACT_SET_MISMATCH", f"{stage}: unmanifested/missing stage files")
    gate_path = directory / "GATE.json"
    gate = _read_json(gate_path, f"{stage} gate")
    if gate.get("status") != expected_state:
        raise ScoringFailure("STATE_MISMATCH", f"{stage}: gate state differs")
    return manifest, gate, path


def _state_prerequisite(sealed: SealedInputs, stage: str) -> dict[str, Any]:
    final = sealed.run_dir / "final" / "VERDICT.json"
    if final.exists() or final.is_symlink():
        raise ScoringFailure("TERMINAL_RUN", "final verdict already exists; run is terminal")
    scores = sealed.run_dir / "scores"
    if scores.is_symlink():
        raise ScoringFailure("SYMLINK_REFUSED", "scores path is a symlink")
    target = _score_dir(sealed.run_dir, stage)
    if target.exists() or target.is_symlink():
        gate_path = target / "GATE.json"
        manifest_path = target / "ARTIFACT_MANIFEST.json"
        if gate_path.is_file() and manifest_path.is_file():
            gate = _read_json(gate_path, f"existing {stage} gate")
            terminal_states = {"REJECT_EVAL12", "REJECT_EVAL24", "REJECT_EVAL36", "EVAL36_ADOPTION_CANDIDATE"}
            if gate.get("status") in terminal_states:
                _terminal_verdict(sealed, stage, gate["status"], gate.get("first_failure"), manifest_path)
                raise ScoringFailure("TERMINAL_RUN", f"{stage} already reached terminal state")
        raise ScoringFailure("NO_CLOBBER", f"score stage already exists: {stage}")
    if stage == "eval12":
        if any(_score_dir(sealed.run_dir, later).exists() for later in ("eval24", "eval36")):
            raise ScoringFailure("STATE_ORDER", "later score stage already exists")
        return {
            "path": sealed.manifest_path.relative_to(sealed.run_dir).as_posix(),
            "bytes": sealed.manifest_path.stat().st_size,
            "sha256": sealed.manifest_sha256,
        }
    if stage == "eval24":
        if _score_dir(sealed.run_dir, "eval36").exists():
            raise ScoringFailure("STATE_ORDER", "eval36 already exists")
        _, _, path = _verify_stage_manifest(sealed.run_dir, "eval12", "EVAL12_PASS", sealed.manifest_sha256)
        return artifact_ref(sealed.run_dir, path)
    if stage == "eval36":
        _verify_stage_manifest(sealed.run_dir, "eval12", "EVAL12_PASS", sealed.manifest_sha256)
        _, _, path = _verify_stage_manifest(sealed.run_dir, "eval24", "EVAL24_PASS", sealed.manifest_sha256)
        return artifact_ref(sealed.run_dir, path)
    raise ScoringFailure("INVALID_STAGE", stage)


def _temp_stage_dir(run_dir: Path, stage: str) -> Path:
    scores = run_dir / "scores"
    scores.mkdir(parents=True, exist_ok=True)
    if scores.is_symlink():
        raise ScoringFailure("SYMLINK_REFUSED", "scores path is a symlink")
    path = scores / f".{_stage_name(stage)}.tmp-{uuid.uuid4().hex}"
    path.mkdir(mode=0o700)
    return path


def _temp_write(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ScoringFailure("NO_CLOBBER", f"temporary output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ScoringFailure("SYMLINK_REFUSED", f"temporary parent is not a real directory: {path.parent}")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _artifact_item(run_dir: Path, temp_path: Path, final_path: Path, role: str, schema_type: str) -> dict[str, Any]:
    return {
        "path": final_path.relative_to(run_dir).as_posix(),
        "bytes": temp_path.stat().st_size,
        "sha256": sha256_file(temp_path),
        "media_type": "text/csv" if temp_path.suffix == ".csv" else "application/json",
        "schema_type": schema_type,
        "role": role,
    }


def _source_hashes(sealed: SealedInputs, subset_paths: Mapping[str, Path]) -> dict[str, Any]:
    bindings = sealed.manifest["source_bindings"]
    official = sealed.manifest["official"]
    return {
        "baseline_full_csv_sha256": sha256_file(sealed.csv_paths["baseline"]),
        "baseline_subset_sha256": sha256_file(subset_paths["baseline"]),
        "candidate_full_csv_sha256": sha256_file(sealed.csv_paths["candidate"]),
        "candidate_subset_sha256": sha256_file(subset_paths["candidate"]),
        "evaluate_py_sha256": bindings["evaluate_py_sha256"],
        "st_r3_scoring_py_sha256": bindings["st_r3_scoring_py_sha256"],
        "official_gitlink": official["gitlink"],
        "official_metrics_sha256": official["source_hashes"]["tracking_cellmot/metrics.py"],
        "official_division_metrics_sha256": official["source_hashes"]["tracking_cellmot/division_metrics.py"],
        "gt_inventory_sha256": sealed.manifest["scoring_inputs"]["gt_inventory"]["sha256"],
    }


def _score_unlocked_stage(
    sealed: SealedInputs, stage: str, stems: Sequence[str], temp: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # All metadata/inventory validation completes before the first official call.
    metadata = _verify_unlocked_gt(sealed, stems)
    bounds = {stem: _read_shape(sealed.gt_dir / f"{stem}.zarr", stem) for stem in stems}
    subset_paths: dict[str, Path] = {}
    for arm in ("baseline", "candidate"):
        path = temp / f"{arm}.csv"
        expected_bytes = subset_bytes(sealed.csvs[arm], stems)
        _temp_write(path, expected_bytes)
        parsed = validate_submission_csv(path, stems, bounds, full_generation=False)
        for stem in stems:
            if parsed.partitions[stem].raw != sealed.csvs[arm].partitions[stem].raw:
                raise ScoringFailure("SUBSET_NOT_EXACT", f"{arm}/{stem}: subset is not exact source row bytes")
        subset_paths[arm] = path

    hashes = _source_hashes(sealed, subset_paths)
    rows: list[dict[str, Any]] = []
    for stem in stems:
        item: dict[str, Any] = {"dataset": stem}
        for arm in ("baseline", "candidate"):
            singleton = temp / "singletons" / arm / f"{stem}.csv"
            _temp_write(singleton, sealed.csvs[arm].header + sealed.csvs[arm].partitions[stem].raw)
            validate_submission_csv(singleton, (stem,), {stem: bounds[stem]}, full_generation=False)
            scored = _score_one(singleton, sealed, stem, arm)
            geff_prefix = (sealed.gt_dir / f"{stem}.geff").relative_to(sealed.run_dir).as_posix() + "/"
            zarr_prefix = (sealed.gt_dir / f"{stem}.zarr").relative_to(sealed.run_dir).as_posix() + "/"
            scored["source_hashes"] = {
                **hashes,
                "singleton_csv_sha256": sha256_file(singleton),
                "gt_geff_partition_sha256": canonical_digest(
                    [record for record in sealed.gt_inventory["records"] if record["path"].startswith(geff_prefix)]
                ),
                "gt_zarr_partition_sha256": canonical_digest(
                    [record for record in sealed.gt_inventory["records"] if record["path"].startswith(zarr_prefix)]
                ),
            }
            item[arm] = scored
        rows.append(item)
    return rows, {
        "schema_version": "biohub.st_r3.score_input_receipt.v1",
        "stage": stage,
        "stems": list(stems),
        "metadata": metadata,
        "source_hashes": hashes,
    }


def _load_rollup_rows(sealed: SealedInputs) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage, stems in (("eval12", EVAL12), ("eval24", EVAL24)):
        _, _, _ = _verify_stage_manifest(sealed.run_dir, stage, f"{stage.upper()}_PASS", sealed.manifest_sha256)
        path = _score_dir(sealed.run_dir, stage) / "PER_VIDEO.json"
        value = _read_json(path, f"{stage} per-video")
        _exact_keys(value, frozenset({"schema_version", "stage", "rows"}), f"{stage} per-video")
        if value["schema_version"] != "biohub.st_r3.per_video_official.v1" or value["stage"] != stage:
            raise ScoringFailure("SCHEMA_MISMATCH", f"{stage}: per-video schema mismatch")
        if [item.get("dataset") for item in value["rows"]] != list(stems):
            raise ScoringFailure("DATASET_SET_MISMATCH", f"{stage}: stored rows differ from frozen stems")
        rows.extend(value["rows"])
    if [item["dataset"] for item in rows] != list(EVAL36):
        raise ScoringFailure("DATASET_SET_MISMATCH", "eval36 is not exact stored eval12+eval24 union")
    return rows


def _publish_stage(
    sealed: SealedInputs,
    stage: str,
    preceding: dict[str, Any],
    temp: Path,
    state: str,
) -> tuple[Path, dict[str, Any]]:
    target = _score_dir(sealed.run_dir, stage)
    artifacts: list[dict[str, Any]] = []
    for path in sorted(_walk_regular_tree(temp, sealed.run_dir), key=lambda item: item.relative_to(temp).as_posix()):
        rel = path.relative_to(temp)
        final_path = target / rel
        name = rel.name
        role = {
            "INPUT_RECEIPT.json": "stage_input_binding",
            "PER_VIDEO.json": "official_per_video_rows",
            "AGGREGATES.json": "official_group_aggregates",
            "DELTAS.json": "paired_deltas",
            "GATE.json": "mechanical_gate",
            "baseline.csv": "baseline_stage_subset",
            "candidate.csv": "candidate_stage_subset",
        }.get(name, "official_singleton_submission" if path.suffix == ".csv" else "stage_artifact")
        schema_type = "csv.physical-subsequence.v1" if path.suffix == ".csv" else f"biohub.st_r3.{name.lower()}.v1"
        artifacts.append(_artifact_item(sealed.run_dir, path, final_path, role, schema_type))
    artifacts.sort(key=lambda item: item["path"])
    manifest = {
        "schema_version": STAGE_MANIFEST_SCHEMA,
        "state": state,
        "run_id": sealed.manifest["run_id"],
        "stage": stage,
        "preceding_manifest": preceding,
        "feasibility_manifest_sha256": sealed.manifest_sha256,
        "artifacts": artifacts,
    }
    _temp_write(temp / "ARTIFACT_MANIFEST.json", canonical_json_bytes(manifest))
    if target.exists() or target.is_symlink():
        raise ScoringFailure("NO_CLOBBER", f"refusing to overwrite {target}")
    os.rename(temp, target)
    return target / "ARTIFACT_MANIFEST.json", manifest


def _terminal_verdict(
    sealed: SealedInputs, stage: str, status: str, first_failure: str | None, stage_manifest: Path | None
) -> dict[str, Any]:
    partial_dir = sealed.run_dir / "scores" / f"failed_{_stage_name(stage)}"
    partial_inventory = []
    if partial_dir.exists() and partial_dir.is_dir() and not partial_dir.is_symlink():
        for path in _walk_regular_tree(partial_dir, sealed.run_dir):
            partial_inventory.append(artifact_ref(sealed.run_dir, path))
    score_artifacts = None
    gates = None
    if stage_manifest is not None:
        stage_dir = stage_manifest.parent
        score_artifacts = {
            name: artifact_ref(sealed.run_dir, stage_dir / name)
            for name in ("PER_VIDEO.json", "AGGREGATES.json", "DELTAS.json", "GATE.json")
        }
        gates = _read_json(stage_dir / "GATE.json", f"{stage} terminal gate")["gates"]
    verdict = {
        "schema_version": "biohub.st_r3.terminal_verdict.v1",
        "run_id": sealed.manifest["run_id"],
        "stage": stage,
        "status": status,
        "first_failure": first_failure,
        "feasibility_manifest_sha256": sealed.manifest_sha256,
        "stage_manifest": artifact_ref(sealed.run_dir, stage_manifest) if stage_manifest else None,
        "score_artifacts": score_artifacts,
        "gates": gates,
        "feasibility_artifact": sealed.manifest["feasibility"]["ref"],
        "partial_score_inventory": partial_inventory,
        "command": [
            "scripts/st_r3_score_stage.py",
            "--run-dir",
            ".",
            "--generation-manifest-sha256",
            sealed.manifest_sha256,
            "--stage",
            stage,
        ],
        "allowed_next_action": "retain exact E23 fallback; do not continue or regenerate this run",
    }
    _atomic_write(sealed.run_dir / "final" / "VERDICT.json", canonical_json_bytes(verdict))
    return verdict


def score_stage(run_dir: Path | str, generation_manifest_sha256: str, stage: str) -> dict[str, Any]:
    """Execute exactly one legal ST-R3 score transition."""
    stage = stage.lower()
    _stage_name(stage)
    sealed: SealedInputs | None = None
    temp: Path | None = None
    try:
        sealed = validate_feasibility_manifest(run_dir, generation_manifest_sha256)
        preceding = _state_prerequisite(sealed, stage)
        temp = _temp_stage_dir(sealed.run_dir, stage)
        if stage in ("eval12", "eval24"):
            stems = EVAL12 if stage == "eval12" else EVAL24
            rows, input_receipt = _score_unlocked_stage(sealed, stage, stems, temp)
        else:
            stems = EVAL36
            rows = _load_rollup_rows(sealed)
            input_receipt = {
                "schema_version": "biohub.st_r3.score_input_receipt.v1",
                "stage": stage,
                "stems": list(EVAL36),
                "metadata": None,
                "source_hashes": {
                    "eval12_manifest_sha256": sha256_file(
                        _score_dir(sealed.run_dir, "eval12") / "ARTIFACT_MANIFEST.json"
                    ),
                    "eval24_manifest_sha256": sha256_file(
                        _score_dir(sealed.run_dir, "eval24") / "ARTIFACT_MANIFEST.json"
                    ),
                    "feasibility_manifest_sha256": sealed.manifest_sha256,
                },
                "official_evaluation_calls": 0,
            }
        per_video = {"schema_version": "biohub.st_r3.per_video_official.v1", "stage": stage, "rows": rows}
        aggregates = build_aggregates(rows, stems, stage)
        deltas = build_deltas(rows, aggregates, stems, stage)
        gate = evaluate_metric_gates(stage, deltas)
        for name, value in (
            ("INPUT_RECEIPT.json", input_receipt),
            ("PER_VIDEO.json", per_video),
            ("AGGREGATES.json", aggregates),
            ("DELTAS.json", deltas),
            ("GATE.json", gate),
        ):
            _temp_write(temp / name, canonical_json_bytes(value))
        manifest_path, _ = _publish_stage(sealed, stage, preceding, temp, gate["status"])
        temp = None
        if gate["first_failure"] is not None or stage == "eval36":
            verdict = _terminal_verdict(sealed, stage, gate["status"], gate["first_failure"], manifest_path)
            return verdict
        return {
            "schema_version": "biohub.st_r3.stage_result.v1",
            "run_id": sealed.manifest["run_id"],
            "stage": stage,
            "status": gate["status"],
            "first_failure": None,
            "stage_manifest": artifact_ref(sealed.run_dir, manifest_path),
        }
    except ScoringFailure as exc:
        if sealed is not None and not (sealed.run_dir / "final" / "VERDICT.json").exists():
            if temp is not None and temp.exists():
                failed = sealed.run_dir / "scores" / f"failed_{_stage_name(stage)}"
                if not failed.exists() and not failed.is_symlink():
                    os.rename(temp, failed)
                    temp = None
            status = "ERROR_AFTER_GT_READ" if exc.gt_read_started else "ERROR_BEFORE_GT_READ"
            _terminal_verdict(sealed, stage, status, exc.code, None)
        raise
    finally:
        if temp is not None and temp.exists():
            shutil.rmtree(temp)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score one immutable ST-R3 stage")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--generation-manifest-sha256", required=True)
    parser.add_argument("--stage", required=True, choices=("eval12", "eval24", "eval36"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = score_stage(args.run_dir, args.generation_manifest_sha256, args.stage)
    except ScoringFailure as exc:
        result = {
            "schema_version": "biohub.st_r3.cli_result.v1",
            "status": "ERROR",
            "code": exc.code,
            "message": str(exc),
        }
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 2
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0 if result["status"] in {"EVAL12_PASS", "EVAL24_PASS", "EVAL36_ADOPTION_CANDIDATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
