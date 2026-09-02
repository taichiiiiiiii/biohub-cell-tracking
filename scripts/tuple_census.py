#!/usr/bin/env python3
"""GT-blind feasibility census for a future two-child/division head.

This tool deliberately has one production input: the immutable E22/E23-family
eval-36 raw GEFF bundle.  It never reads ground truth, image Zarrs, public-dummy
artifacts, an official metric, a network service, or Kaggle.

The frozen candidate universe is purely computational, not quality evidence:

* ``P`` is a raw selected-graph node with exactly one outgoing edge ``P -> A``;
* ``B`` is any other raw node at ``t(P)+1``;
* one tuple ``(P, A, B)`` is counted when ``d(P,B) <= 8.0 um`` and
  ``d(A,B) <= 11.0 um`` (both bounds inclusive); and
* coordinates are converted from voxels with ``(z,y,x) =
  (1.625,0.40625,0.40625) um``.

There is no score, label, candidate ranking, threshold fitting, or model
inference in this census.  Counts may be used only to falsify candidate-volume
and streaming-feasibility assumptions before a learned head is designed.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import stat
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

import numpy as np
from scipy.spatial import cKDTree

from biohub.io import load_geff_graph

SCHEMA_VERSION = "biohub.two_child_tuple_census.v2"
CANDIDATE_VERSION = "frozen_encoder_two_child_feasibility_v1"
FROZEN_RELATIVE_ROOT = Path(
    "outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/"
    "predictions/unknown/unet_transformer_val/split_0"
)

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
EXPECTED_DATASETS = EVAL12 + EVAL24

EXPECTED_ROOTS = 36
EXPECTED_DIRECTORIES = 1_224
EXPECTED_FILES = 1_188
EXPECTED_BYTES = 10_090_215
EXPECTED_TREE_SHA256 = "fa34dcf5f20054f240d750bd2225dd08fc6cf645e094cd9596ce2faf4bbf0ca2"
EXPECTED_DIRECTORY_TREE_SHA256 = "687267b8e1a886f5ef3a564422718c2014b74f5fae9e21e039ce06a15448e1c6"


class CensusError(ValueError):
    """Fail-closed input, graph, or output-contract violation."""


@dataclass(frozen=True)
class CensusConfig:
    scale_zyx_um: tuple[float, float, float] = (1.625, 0.40625, 0.40625)
    parent_radius_um: float = 8.0
    sister_radius_um: float = 11.0


FROZEN_CONFIG = CensusConfig()


@dataclass(frozen=True)
class CensusNode:
    node_id: int
    t: int
    physical_zyx_um: tuple[float, float, float]


@dataclass(frozen=True)
class DatasetCensus:
    dataset: str
    frames: int
    raw_nodes: int
    raw_edges: int
    one_child_parents: int
    active_one_child_parents: int
    candidate_tuples: int
    max_candidates_per_parent: int
    max_candidate_tuples_per_frame: int


@dataclass(frozen=True)
class TreeInventory:
    roots: int
    directories: int
    files: int
    bytes: int
    canonical_sha256sum_tree_sha256: str
    canonical_directory_tree_sha256: str


def _canonical_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise CensusError(f"canonical JSON encoding failed: {error}") from error
    return (text + "\n").encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_sort_key(path: Path) -> bytes:
    return os.fsencode(path.as_posix())


def _open_directory_no_symlinks(path: Path, *, create: bool) -> int:
    """Open an absolute directory path component-wise without following links."""
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError as error:
                if not create:
                    raise CensusError(f"missing directory path component: {absolute}") from error
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    # A concurrent creator is acceptable only if the next
                    # no-follow open proves it made a real directory.
                    pass
                except OSError as mkdir_error:
                    raise CensusError(f"cannot create output parent directory: {absolute}") from mkdir_error
                try:
                    next_descriptor = os.open(component, flags, dir_fd=descriptor)
                except OSError as open_error:
                    raise CensusError(
                        f"output parent component is not a real directory: {absolute}"
                    ) from open_error
            except OSError as error:
                raise CensusError(
                    f"symlink or non-directory path component is forbidden: {absolute}"
                ) from error
            os.close(descriptor)
            descriptor = next_descriptor
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _require_no_symlink_components(base: Path, target: Path) -> None:
    """Reject symlinks from the filesystem anchor through ``target``."""
    base_abs = Path(os.path.abspath(base))
    target_abs = Path(os.path.abspath(target))
    try:
        target_abs.relative_to(base_abs)
    except ValueError as error:
        raise CensusError(f"input root escapes repository root: {target_abs}") from error
    descriptor = _open_directory_no_symlinks(target_abs, create=False)
    os.close(descriptor)


def validate_frozen_input_root(repo_root: Path, input_root: Path) -> Path:
    """Bind a caller-supplied path to the sole allowed production location."""
    repo_abs = Path(os.path.abspath(repo_root))
    input_abs = Path(os.path.abspath(input_root))
    expected = repo_abs / FROZEN_RELATIVE_ROOT
    if input_abs != expected:
        raise CensusError(
            "prohibited input root; expected exactly "
            f"{FROZEN_RELATIVE_ROOT.as_posix()}, got {input_abs}"
        )
    _require_no_symlink_components(repo_abs, input_abs)
    mode = input_abs.lstat().st_mode
    if not stat.S_ISDIR(mode):
        raise CensusError(f"frozen input root is not a directory: {input_abs}")
    return input_abs


def validate_output_path(repo_root: Path, output: Path) -> Path:
    """Keep generated receipts away from inputs, GT, official code, and Git data."""
    repo_abs = Path(os.path.abspath(repo_root))
    output_abs = Path(os.path.abspath(output))
    protected = (
        repo_abs / FROZEN_RELATIVE_ROOT,
        repo_abs / "outputs" / "kaggle",
        repo_abs / "data",
        repo_abs / "official",
        repo_abs / ".git",
    )
    if any(output_abs == root or output_abs.is_relative_to(root) for root in protected):
        raise CensusError(f"output path is inside a protected read-only tree: {output_abs}")
    if output_abs.is_relative_to(repo_abs):
        allowed = repo_abs / "outputs" / "local" / "tuple_census"
        if output_abs != allowed and not output_abs.is_relative_to(allowed):
            raise CensusError(
                "repository-local output must be under outputs/local/tuple_census: "
                f"{output_abs}"
            )
    return output_abs


def validate_direct_membership(root: Path, expected_datasets: Sequence[str]) -> tuple[Path, ...]:
    """Require exact direct ``<dataset>.geff`` directory membership."""
    if len(expected_datasets) != len(set(expected_datasets)):
        raise CensusError("expected dataset sequence contains duplicates")
    expected_names = {f"{dataset}.geff" for dataset in expected_datasets}
    entries = sorted(root.iterdir(), key=_path_sort_key)
    actual_names = {entry.name for entry in entries}
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    if missing or extra:
        raise CensusError(f"direct GEFF membership mismatch: missing={missing} extra={extra}")
    by_name = {entry.name: entry for entry in entries}
    ordered: list[Path] = []
    for dataset in expected_datasets:
        path = by_name[f"{dataset}.geff"]
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise CensusError(f"symlink GEFF root is forbidden: {path}")
        if not stat.S_ISDIR(mode):
            raise CensusError(f"GEFF root is not a directory: {path}")
        ordered.append(path)
    return tuple(ordered)


def scan_tree(root: Path, geff_roots: Sequence[Path]) -> TreeInventory:
    """Hash every directory and regular file in a validated GEFF tree."""
    files: list[Path] = []
    directories: list[Path] = []
    pending = list(reversed(geff_roots))
    while pending:
        directory = pending.pop()
        directories.append(directory)
        entries = sorted(directory.iterdir(), key=_path_sort_key)
        child_dirs: list[Path] = []
        for entry in entries:
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise CensusError(f"symlink inside GEFF tree is forbidden: {entry}")
            if stat.S_ISDIR(mode):
                child_dirs.append(entry)
            elif stat.S_ISREG(mode):
                files.append(entry)
            else:
                raise CensusError(f"non-regular GEFF tree entry is forbidden: {entry}")
        pending.extend(reversed(child_dirs))

    files.sort(key=lambda path: _path_sort_key(path.relative_to(root)))
    directories.sort(key=lambda path: _path_sort_key(path.relative_to(root)))
    outer = hashlib.sha256()
    directory_digest = hashlib.sha256()
    total_bytes = 0
    for path in directories:
        relative = path.relative_to(root).as_posix()
        directory_digest.update(f"./{relative}/\n".encode())
    for path in files:
        relative = path.relative_to(root).as_posix()
        size = path.stat(follow_symlinks=False).st_size
        total_bytes += size
        outer.update(f"{_sha256_file(path)}  ./{relative}\n".encode())
    return TreeInventory(
        roots=len(geff_roots),
        directories=len(directories),
        files=len(files),
        bytes=total_bytes,
        canonical_sha256sum_tree_sha256=outer.hexdigest(),
        canonical_directory_tree_sha256=directory_digest.hexdigest(),
    )


def validate_frozen_inventory(inventory: TreeInventory) -> None:
    expected = TreeInventory(
        roots=EXPECTED_ROOTS,
        directories=EXPECTED_DIRECTORIES,
        files=EXPECTED_FILES,
        bytes=EXPECTED_BYTES,
        canonical_sha256sum_tree_sha256=EXPECTED_TREE_SHA256,
        canonical_directory_tree_sha256=EXPECTED_DIRECTORY_TREE_SHA256,
    )
    if inventory != expected:
        raise CensusError(f"frozen raw GEFF inventory mismatch: expected={expected} actual={inventory}")


def _strict_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise CensusError(f"{field} must be an integer, got {type(value).__name__}")
    return int(value)


def _strict_true(value: object, field: str) -> None:
    if not isinstance(value, (bool, np.bool_)) or not bool(value):
        raise CensusError(f"{field} must be true for the selected raw graph")


def _physical_node(row: Mapping[str, object], scale: np.ndarray) -> CensusNode:
    node_id = _strict_int(row.get("node_id"), "node_id")
    t = _strict_int(row.get("t"), f"node {node_id} t")
    _strict_true(row.get("solution"), f"node {node_id} solution")
    coordinates: list[float] = []
    for index, name in enumerate(("z", "y", "x")):
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise CensusError(f"node {node_id} {name} must be numeric")
        physical = float(value) * float(scale[index])
        if not math.isfinite(physical):
            raise CensusError(f"node {node_id} {name} is non-finite")
        coordinates.append(physical)
    return CensusNode(node_id=node_id, t=t, physical_zyx_um=tuple(coordinates))  # type: ignore[arg-type]


def _distance(left: CensusNode, right: CensusNode) -> float:
    return float(np.linalg.norm(np.asarray(left.physical_zyx_um) - np.asarray(right.physical_zyx_um)))


def census_rows(
    dataset: str,
    node_rows: Iterable[Mapping[str, object]],
    edge_rows: Iterable[Mapping[str, object]],
    config: CensusConfig = FROZEN_CONFIG,
) -> DatasetCensus:
    """Count the frozen tuple universe from detached node/edge rows."""
    if dataset not in EXPECTED_DATASETS and dataset != "synthetic":
        raise CensusError(f"unexpected dataset identifier: {dataset}")
    if (
        len(config.scale_zyx_um) != 3
        or any(not math.isfinite(value) or value <= 0 for value in config.scale_zyx_um)
        or not math.isfinite(config.parent_radius_um)
        or config.parent_radius_um <= 0
        or not math.isfinite(config.sister_radius_um)
        or config.sister_radius_um <= 0
    ):
        raise CensusError(f"invalid census config: {config}")

    scale = np.asarray(config.scale_zyx_um, dtype=np.float64)
    nodes: dict[int, CensusNode] = {}
    for row in node_rows:
        node = _physical_node(row, scale)
        if node.node_id in nodes:
            raise CensusError(f"duplicate node_id: {node.node_id}")
        nodes[node.node_id] = node
    if not nodes:
        raise CensusError(f"{dataset}: empty node table")

    outgoing: dict[int, list[int]] = defaultdict(list)
    seen_edges: set[tuple[int, int]] = set()
    raw_edges = 0
    for row in edge_rows:
        source = _strict_int(row.get("source_id"), "source_id")
        target = _strict_int(row.get("target_id"), "target_id")
        _strict_true(row.get("solution"), f"edge {source}->{target} solution")
        if source not in nodes or target not in nodes:
            raise CensusError(f"dangling edge: {source}->{target}")
        edge = (source, target)
        if edge in seen_edges:
            raise CensusError(f"duplicate edge: {source}->{target}")
        seen_edges.add(edge)
        if nodes[target].t != nodes[source].t + 1:
            raise CensusError(f"nonconsecutive edge: {source}->{target}")
        outgoing[source].append(target)
        raw_edges += 1
    for targets in outgoing.values():
        targets.sort()

    by_frame: dict[int, list[CensusNode]] = defaultdict(list)
    for node in nodes.values():
        by_frame[node.t].append(node)
    frame_indices: dict[int, tuple[list[CensusNode], cKDTree]] = {}
    for frame, frame_nodes in by_frame.items():
        ordered = sorted(frame_nodes, key=lambda node: node.node_id)
        coordinates = np.asarray([node.physical_zyx_um for node in ordered], dtype=np.float64)
        frame_indices[frame] = (ordered, cKDTree(coordinates))

    one_child_parents = 0
    active_parents = 0
    candidate_tuples = 0
    max_candidates_per_parent = 0
    tuples_per_frame: Counter[int] = Counter()
    query_radius = math.nextafter(config.parent_radius_um, math.inf)

    for parent_id in sorted(outgoing):
        targets = outgoing[parent_id]
        if len(targets) != 1:
            continue
        one_child_parents += 1
        parent = nodes[parent_id]
        existing_child = nodes[targets[0]]
        frame_nodes, tree = frame_indices[existing_child.t]
        nearby_indices = tree.query_ball_point(parent.physical_zyx_um, query_radius)
        local_count = 0
        for index in sorted(nearby_indices, key=lambda item: frame_nodes[item].node_id):
            candidate = frame_nodes[index]
            if candidate.node_id == existing_child.node_id:
                continue
            if _distance(parent, candidate) > config.parent_radius_um:
                continue
            if _distance(existing_child, candidate) > config.sister_radius_um:
                continue
            local_count += 1
        if local_count:
            active_parents += 1
            candidate_tuples += local_count
            tuples_per_frame[parent.t] += local_count
            max_candidates_per_parent = max(max_candidates_per_parent, local_count)

    return DatasetCensus(
        dataset=dataset,
        frames=len(by_frame),
        raw_nodes=len(nodes),
        raw_edges=raw_edges,
        one_child_parents=one_child_parents,
        active_one_child_parents=active_parents,
        candidate_tuples=candidate_tuples,
        max_candidates_per_parent=max_candidates_per_parent,
        max_candidate_tuples_per_frame=max(tuples_per_frame.values(), default=0),
    )


def census_geff(path: Path, config: CensusConfig = FROZEN_CONFIG) -> DatasetCensus:
    graph = load_geff_graph(path)
    return census_rows(
        path.stem,
        graph.node_attrs().iter_rows(named=True),
        graph.edge_attrs().iter_rows(named=True),
        config,
    )


def _linear_percentile(values: Sequence[int], quantile: float) -> float:
    if not values:
        raise CensusError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    # Inputs are integer counts and q=0.95 has a short exact decimal here.
    # Normalising the harmless binary tail keeps canonical JSON readable.
    return round(float(ordered[lower] + fraction * (ordered[upper] - ordered[lower])), 6)


def _summarise_group(rows: Sequence[DatasetCensus]) -> dict[str, object]:
    tuple_counts = [row.candidate_tuples for row in rows]
    return {
        "datasets": len(rows),
        "frames": sum(row.frames for row in rows),
        "raw_nodes": sum(row.raw_nodes for row in rows),
        "raw_edges": sum(row.raw_edges for row in rows),
        "one_child_parents": sum(row.one_child_parents for row in rows),
        "active_one_child_parents": sum(row.active_one_child_parents for row in rows),
        "candidate_tuples": sum(tuple_counts),
        "candidate_tuples_per_dataset_median": float(median(tuple_counts)),
        "candidate_tuples_per_dataset_p95_linear": _linear_percentile(tuple_counts, 0.95),
        "candidate_tuples_per_dataset_max": max(tuple_counts),
        "max_candidates_per_parent": max(row.max_candidates_per_parent for row in rows),
        "max_candidate_tuples_per_frame": max(row.max_candidate_tuples_per_frame for row in rows),
    }


def build_report(
    inventory: TreeInventory,
    rows: Sequence[DatasetCensus],
    config: CensusConfig = FROZEN_CONFIG,
) -> dict[str, object]:
    if tuple(row.dataset for row in rows) != EXPECTED_DATASETS:
        raise CensusError("dataset census rows do not follow the frozen eval12+eval24 sequence")
    config_record = {
        "candidate_universe": (
            "one selected outgoing child A per parent P; every distinct node B at t(P)+1; "
            "count (P,A,B) iff d(P,B)<=parent_radius and d(A,B)<=sister_radius"
        ),
        "bounds": "inclusive",
        "scale_zyx_um": list(config.scale_zyx_um),
        "parent_radius_um": config.parent_radius_um,
        "sister_radius_um": config.sister_radius_um,
        "uses_ground_truth": False,
        "uses_images": False,
        "uses_official_metric": False,
        "uses_network_or_kaggle": False,
    }
    lineage_rows = {
        lineage: [row for row in rows if row.dataset.startswith(f"{lineage}_")]
        for lineage in ("44b6", "6bba")
    }
    if any(len(group) != 18 for group in lineage_rows.values()):
        raise CensusError("expected exactly 18 datasets from each lineage")
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_version": CANDIDATE_VERSION,
        "interpretation": "GT-blind computational feasibility only; not score or quality evidence",
        "tool": {
            "path": "scripts/tuple_census.py",
            "sha256": _sha256_file(Path(__file__)),
        },
        "config": config_record,
        "config_sha256": hashlib.sha256(_canonical_bytes(config_record)).hexdigest(),
        "input": {
            "logical_root": FROZEN_RELATIVE_ROOT.as_posix(),
            "ordered_datasets": list(EXPECTED_DATASETS),
            "order": "eval12_then_eval24",
            **asdict(inventory),
        },
        "per_dataset": [asdict(row) for row in rows],
        "aggregate": _summarise_group(rows),
        "hidden_200_linear_extrapolation": {
            "basis": "aggregate_count_times_200_divided_by_36; feasibility estimate only",
            "candidate_tuples": round(sum(row.candidate_tuples for row in rows) * 200 / 36, 6),
            "one_child_parents": round(sum(row.one_child_parents for row in rows) * 200 / 36, 6),
        },
        "lineages": {
            lineage: _summarise_group(group)
            for lineage, group in lineage_rows.items()
        },
    }


def run_census(repo_root: Path) -> dict[str, object]:
    input_root = validate_frozen_input_root(repo_root, repo_root / FROZEN_RELATIVE_ROOT)
    geff_roots = validate_direct_membership(input_root, EXPECTED_DATASETS)
    inventory = scan_tree(input_root, geff_roots)
    validate_frozen_inventory(inventory)
    rows = [census_geff(path) for path in geff_roots]
    final_inventory = scan_tree(input_root, geff_roots)
    if final_inventory != inventory:
        raise CensusError(
            f"raw GEFF tree changed during census: before={inventory} after={final_inventory}"
        )
    return build_report(inventory, rows)


def _open_output_parent(parent: Path) -> int:
    """Create and pin an output parent without following symlink components."""
    return _open_directory_no_symlinks(parent, create=True)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while True:
        block = os.pread(descriptor, 1024 * 1024, offset)
        if not block:
            return digest.hexdigest()
        digest.update(block)
        offset += len(block)


def _linux_linkat_empty_path(source_descriptor: int, parent_descriptor: int, output_name: str) -> None:
    """Atomically link an anonymous Linux O_TMPFILE inode without replacing."""
    library = ctypes.CDLL(None, use_errno=True)
    try:
        function = library.linkat
    except AttributeError as error:
        raise CensusError("linkat is unavailable on this Linux runtime") from error
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    function.restype = ctypes.c_int
    result = function(source_descriptor, b"", parent_descriptor, os.fsencode(output_name), 0x1000)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), output_name)
    unsupported = {errno.ENOSYS, errno.EINVAL, errno.EXDEV, errno.ENOENT}
    if hasattr(errno, "ENOTSUP"):
        unsupported.add(errno.ENOTSUP)
    if hasattr(errno, "EOPNOTSUPP"):
        unsupported.add(errno.EOPNOTSUPP)
    if error_number in unsupported:
        raise CensusError(
            f"linkat(AT_EMPTY_PATH) is unsupported for the pinned output directory: errno={error_number}"
        )
    raise CensusError(f"linkat(AT_EMPTY_PATH) failed: errno={error_number} {os.strerror(error_number)}")


def _open_anonymous_staging(parent_descriptor: int) -> int:
    """Return a Linux O_TMPFILE FD with no attacker-addressable name."""
    if not sys.platform.startswith("linux"):
        raise CensusError(
            f"file publication is disabled on {sys.platform}; omit --output and use canonical stdout"
        )
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if not hasattr(os, "O_TMPFILE"):
        raise CensusError("O_TMPFILE is unavailable on this Linux runtime")
    try:
        return os.open(".", flags | os.O_TMPFILE, 0o600, dir_fd=parent_descriptor)
    except OSError as error:
        raise CensusError(
            f"O_TMPFILE is unsupported for the pinned output directory: errno={error.errno}"
        ) from error


def _publish_fd_noreplace(
    parent_descriptor: int,
    source_descriptor: int,
    output_name: str,
    expected_size: int,
    expected_sha256: str,
) -> None:
    """Atomically publish complete bytes directly from an anonymous source FD."""
    try:
        source = os.fstat(source_descriptor)
    except OSError as error:
        raise CensusError("cannot inspect anonymous staging descriptor") from error
    if (
        not stat.S_ISREG(source.st_mode)
        or source.st_size != expected_size
        or _sha256_fd(source_descriptor) != expected_sha256
    ):
        raise CensusError("anonymous staging content changed before publication")
    if sys.platform.startswith("linux"):
        _linux_linkat_empty_path(source_descriptor, parent_descriptor, output_name)
    else:
        raise CensusError(
            f"file publication is disabled on {sys.platform}; omit --output and use canonical stdout"
        )

    output_descriptor: int | None = None
    output_error: BaseException | None = None
    try:
        output_flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            output_flags |= os.O_CLOEXEC
        try:
            output_descriptor = os.open(output_name, output_flags, dir_fd=parent_descriptor)
        except OSError as error:
            raise CensusError("published output cannot be reopened without following links") from error
        output_stat = os.fstat(output_descriptor)
        named_stat = os.stat(output_name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(output_stat.st_mode)
            or not _same_inode(output_stat, named_stat)
            or output_stat.st_size != expected_size
            or _sha256_fd(output_descriptor) != expected_sha256
        ):
            raise CensusError("published output does not match the canonical payload")
        os.fsync(output_descriptor)
    except BaseException as error:
        output_error = error
        raise
    finally:
        if output_descriptor is not None:
            try:
                os.close(output_descriptor)
            except OSError as close_error:
                if output_error is None:
                    raise CensusError("could not close verified output descriptor") from close_error


def _write_output(payload: bytes, output: Path | None) -> None:
    if output is None:
        sys.stdout.buffer.write(payload)
        return
    if not sys.platform.startswith("linux"):
        raise CensusError(
            f"file publication is disabled on {sys.platform}; omit --output and use canonical stdout"
        )
    output = Path(os.path.abspath(output))
    parent_descriptor = _open_output_parent(output.parent)
    source_descriptor: int | None = None
    parent_error: BaseException | None = None
    try:
        source_error: BaseException | None = None
        try:
            source_descriptor = _open_anonymous_staging(parent_descriptor)
            with os.fdopen(source_descriptor, "wb", closefd=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                _publish_fd_noreplace(
                    parent_descriptor,
                    source_descriptor,
                    output.name,
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                )
            except FileExistsError as error:
                raise CensusError(f"refusing to overwrite output: {output}") from error
            os.fsync(parent_descriptor)
        except BaseException as error:
            source_error = error
            parent_error = error
            raise
        finally:
            if source_descriptor is not None:
                try:
                    os.close(source_descriptor)
                except OSError as close_error:
                    if source_error is None:
                        wrapped = CensusError("could not close anonymous staging descriptor")
                        parent_error = wrapped
                        raise wrapped from close_error
    finally:
        try:
            os.close(parent_descriptor)
        except OSError as close_error:
            if parent_error is None:
                raise CensusError("could not close receipt parent descriptor") from close_error


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository containing the sole allowed frozen relative input root",
    )
    parser.add_argument("--output", type=Path, help="new canonical JSON path; stdout if omitted")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.output is not None and not sys.platform.startswith("linux"):
            raise CensusError(
                f"file publication is disabled on {sys.platform}; omit --output and use canonical stdout"
            )
        output = None if args.output is None else validate_output_path(args.repo_root, args.output)
        report = run_census(args.repo_root)
        _write_output(_canonical_bytes(report), output)
    except CensusError as error:
        print(f"HOLD: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
