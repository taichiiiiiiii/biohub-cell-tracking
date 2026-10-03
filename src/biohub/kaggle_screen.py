"""Lightweight, local-only screening loop for the frozen E23 twin candidate.

This module is deliberately separate from the ST-R3 certification state
machine.  It can emit only ``SCREEN_*`` states and never authorises adoption,
Kaggle execution, or submission.  The generation child imports no evaluator;
official scoring imports are deferred until :func:`score_screen` runs in its
own process.
"""

from __future__ import annotations

import contextlib
import csv
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import resource
import shutil
import stat
import struct
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREEN_PARENT = REPO_ROOT / "outputs" / "local" / "kaggle_screen"

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
PUBLIC4 = ("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1")

RAW36_RELATIVE = PurePosixPath(
    "outputs/kaggle/e22_bidir030_eval36_raw/tracking_repo/predictions/unknown/"
    "unet_transformer_val/split_0"
)
RAW4_RELATIVE = PurePosixPath(
    "outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/"
    "unet_transformer/split_0"
)
IMAGE_SOURCE_RELATIVE = PurePosixPath("data/train")
PUBLIC4_IMAGE_RELATIVE = PurePosixPath("data/test")
GT_RELATIVE = PurePosixPath("data/train")
DEEPCENTER_ROOT_RELATIVE = PurePosixPath(
    "outputs/kaggle/e23_artifacts/pilkwang/biohub-deepcenter-unet3d-center-prior-v1"
)
DEEPCENTER_CHECKPOINT_RELATIVE = DEEPCENTER_ROOT_RELATIVE / "weights/full_frame_center/best.pt"
DEEPCENTER_MANIFEST_RELATIVE = DEEPCENTER_ROOT_RELATIVE / "ARTIFACT_MANIFEST.json"
PUBLIC4_REFERENCE_RELATIVE = PurePosixPath("outputs/kaggle/e23_reference/submission.csv")
RAW36_MANIFEST_RELATIVE = PurePosixPath("outputs/kaggle/e22_bidir030_eval36_reference/DOWNLOAD_MANIFEST.json")
IMAGE_READY_RELATIVE = PurePosixPath(
    "outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct/READY.json"
)
IMAGE_READY_INVENTORY_RELATIVE = PurePosixPath(
    "outputs/local/eval36_image_ready/20260904T220902+0900_2877f28_direct/IMAGE_CONTENT_INVENTORY.json"
)
GT_RECOVERY_RELATIVE = PurePosixPath("outputs/local/st_r3_gt_recovery/20260905T023957Z/RECEIPT.json")

DEEPCENTER_CHECKPOINT_SHA256 = "8040999a92f6b7bbd98fa8cf458141e045c0f9ad7c936bdb3b18e1f7edafe2a0"
DEEPCENTER_MANIFEST_SHA256 = "1eedc1af72b10c464c6995013075310510b6f6e634450ff2bc170c67b89ce911"
PUBLIC4_REFERENCE_SHA256 = "33c179b0449b9cdd186f06a653cddc8cf12359f008982f6713cdf30784a52e6a"
RAW36_MANIFEST_SHA256 = "1f567e2520cc75536886296c1b88724ea2c2776cd2aa6b52ceaaac6bca8ac12b"
IMAGE_READY_SHA256 = "8a0a36d393ecc11a0532bc12011257a4c012cb7361d4346941b4d1211c58c73e"
IMAGE_READY_INVENTORY_SHA256 = "efe652bd8e8a791bd51cf3b980ae87fe0fe2205ec52d2f3639717cd2b0550714"
GT_RECOVERY_SHA256 = "b42409cdb94b9fc936a2ea4e3ba3e94be7a9246168566bab1970568e07d93899"

CONTROL_SCHEMA = "biohub.kaggle_screen.control.v1"
ARM_SCHEMA = "biohub.kaggle_screen.arm_result.v1"
GENERATION_SCHEMA = "biohub.kaggle_screen.generation_seal.v1"
SCORE_STAGE_SCHEMA = "biohub.kaggle_screen.score_stage.v1"
VERDICT_SCHEMA = "biohub.kaggle_screen.verdict.v1"
ERROR_SCHEMA = "biohub.kaggle_screen.error.v1"
PROTOCOL_VERSION = "kaggle_loop_v2"
RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+@-]{0,127}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
CSV_COLUMNS = ("id", "dataset", "row_type", "node_id", "t", "z", "y", "x", "source_id", "target_id")
ARM_ORDER = ("public4_parity", "dry_run", "baseline", "candidate")
RUNTIME_DISTRIBUTIONS = (
    "numpy",
    "pandas",
    "polars",
    "scipy",
    "scikit-image",
    "zarr",
    "blosc2",
    "geff",
    "tracksdata",
    "torch",
)

SOURCE_FILES = (
    "src/biohub/__init__.py",
    "src/biohub/kaggle_screen.py",
    "scripts/kaggle_screen.py",
    "src/biohub/io.py",
    "src/biohub/public_postproc/__init__.py",
    "src/biohub/public_postproc/config.py",
    "src/biohub/public_postproc/csv_out.py",
    "src/biohub/public_postproc/deepcenter.py",
    "src/biohub/public_postproc/divisions.py",
    "src/biohub/public_postproc/frames.py",
    "src/biohub/public_postproc/geometry.py",
    "src/biohub/public_postproc/graph_ops.py",
    "src/biohub/public_postproc/pipeline.py",
    "src/biohub/public_postproc/production_adapter.py",
    "src/biohub/evaluate.py",
    "src/biohub/st_r3_scoring.py",
    "official/src/tracking_cellmot/metrics.py",
    "official/src/tracking_cellmot/division_metrics.py",
    "official/src/tracking_cellmot/__init__.py",
    "pyproject.toml",
    "uv.lock",
    "analysis/kaggle_loop_protocol_v2.md",
)

FIXED_CHILD_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "LC_ALL": "C",
    "LANG": "C",
    "TZ": "UTC",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "CUDA_VISIBLE_DEVICES": "",
}


class ScreenError(RuntimeError):
    """The diagnostic screen failed closed."""


@dataclass(frozen=True)
class ScreenPaths:
    repo_root: Path
    screen_parent: Path
    raw36: Path
    raw4: Path
    image_source: Path
    public4_images: Path
    gt: Path
    deepcenter_checkpoint: Path
    deepcenter_manifest: Path
    public4_reference: Path
    child_script: Path


@dataclass(frozen=True)
class ScreenGenerationResult:
    status: str
    run_dir: Path
    seal_sha256: str


@dataclass(frozen=True)
class ScreenScoreResult:
    status: str
    run_dir: Path
    first_failure: str | None


def production_paths(repo_root: Path = REPO_ROOT) -> ScreenPaths:
    root = repo_root.absolute()
    return ScreenPaths(
        repo_root=root,
        screen_parent=root / "outputs/local/kaggle_screen",
        raw36=root / RAW36_RELATIVE,
        raw4=root / RAW4_RELATIVE,
        image_source=root / IMAGE_SOURCE_RELATIVE,
        public4_images=root / PUBLIC4_IMAGE_RELATIVE,
        gt=root / GT_RELATIVE,
        deepcenter_checkpoint=root / DEEPCENTER_CHECKPOINT_RELATIVE,
        deepcenter_manifest=root / DEEPCENTER_MANIFEST_RELATIVE,
        public4_reference=root / PUBLIC4_REFERENCE_RELATIVE,
        child_script=root / "scripts/kaggle_screen.py",
    )


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> tuple[int, str]:
    if path.is_symlink() or not path.is_file():
        raise ScreenError(f"expected nonsymlink regular file: {path}")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    after = path.stat()
    def signature(item: os.stat_result) -> tuple[int, int, int, int, int]:
        return item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns

    if signature(before) != signature(after):
        raise ScreenError(f"file changed while hashing: {path}")
    return before.st_size, digest.hexdigest()


def _write_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ScreenError(f"refusing symlink output parent: {path.parent}")
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _require_sha(value: object, label: str) -> str:
    if type(value) is not str or SHA_RE.fullmatch(value) is None:
        raise ScreenError(f"invalid {label} SHA-256")
    return value


def resolve_run_dir(run_id: str, paths: ScreenPaths | None = None) -> Path:
    selected = paths or production_paths()
    if type(run_id) is not str or RUN_RE.fullmatch(run_id) is None:
        raise ScreenError("run_id is not a safe direct-child name")
    parent = selected.screen_parent.absolute()
    run_dir = parent / run_id
    if run_dir.parent != parent:
        raise ScreenError("run directory escaped the canonical screen parent")
    return run_dir


def _reject_production_test_hook(paths: ScreenPaths, hook: object | None, label: str) -> None:
    if hook is None:
        return
    if paths.repo_root.absolute() == REPO_ROOT.absolute() or paths.screen_parent.absolute() == SCREEN_PARENT.absolute():
        raise ScreenError(f"{label} test hook is forbidden for canonical production paths")


def _relative_tree_records(root: Path, selected_roots: Sequence[str] | None = None) -> list[dict[str, object]]:
    if root.is_symlink() or not root.is_dir():
        raise ScreenError(f"tree root must be a nonsymlink directory: {root}")
    bases = [root / name for name in selected_roots] if selected_roots is not None else [root]
    records: list[dict[str, object]] = []
    for base in bases:
        if base.is_symlink() or not base.is_dir():
            raise ScreenError(f"selected tree root must be a nonsymlink directory: {base}")
        entries = [base, *base.rglob("*")]
        for path in entries:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ScreenError(f"symlink in input tree: {path}")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ScreenError(f"special file in input tree: {path}")
            size, digest = _sha_file(path)
            records.append({"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": digest})
    records.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    if len({item["path"] for item in records}) != len(records):
        raise ScreenError("duplicate path in input inventory")
    return records


def _inventory(kind: str, root: Path, records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    plain = [dict(item) for item in records]
    return {
        "kind": kind,
        "root_name": root.name,
        "file_count": len(plain),
        "total_bytes": sum(int(item["bytes"]) for item in plain),
        "records_sha256": sha256_bytes(canonical_json_bytes(plain)),
        "records": plain,
    }


def _pinned_evidence(paths: ScreenPaths) -> dict[str, object]:
    pins = {
        "raw36_manifest": (RAW36_MANIFEST_RELATIVE, RAW36_MANIFEST_SHA256),
        "image_ready": (IMAGE_READY_RELATIVE, IMAGE_READY_SHA256),
        "image_ready_inventory": (IMAGE_READY_INVENTORY_RELATIVE, IMAGE_READY_INVENTORY_SHA256),
        "gt_recovery": (GT_RECOVERY_RELATIVE, GT_RECOVERY_SHA256),
    }
    result: dict[str, object] = {}
    for name, (relative, expected) in pins.items():
        size, digest = _sha_file(paths.repo_root / relative)
        if digest != expected:
            raise ScreenError(f"pinned evidence drifted: {name}")
        result[name] = {"path": relative.as_posix(), "bytes": size, "sha256": digest}
    return result


def _geff_inventory(kind: str, root: Path, stems: Sequence[str]) -> dict[str, object]:
    expected = tuple(f"{stem}.geff" for stem in stems)
    actual = tuple(sorted(item.name for item in root.iterdir())) if root.is_dir() and not root.is_symlink() else ()
    if set(actual) != set(expected) or len(actual) != len(expected):
        raise ScreenError(f"{kind} direct GEFF membership differs from the frozen set")
    return _inventory(kind, root, _relative_tree_records(root, expected))


def _explicit_scale_and_shape(zarr_root: Path) -> tuple[list[float], list[int], dict[str, str]]:
    root_meta = zarr_root / "zarr.json"
    array_meta = zarr_root / "0/zarr.json"
    root_size, root_sha = _sha_file(root_meta)
    array_size, array_sha = _sha_file(array_meta)
    try:
        root_value = json.loads(root_meta.read_bytes())
        array_value = json.loads(array_meta.read_bytes())
        attrs = root_value["attributes"]
        attrs = attrs.get("ome", attrs)
        transform = attrs["multiscales"][0]["datasets"][0]["coordinateTransformations"][0]
        if transform.get("type") != "scale":
            raise ValueError("first transform is not scale")
        scale = [float(item) for item in transform["scale"][-3:]]
        shape = list(array_value["shape"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ScreenError(f"missing or malformed explicit scale/shape metadata: {zarr_root.name}") from exc
    if (
        len(scale) != 3
        or any(not math.isfinite(item) or item <= 0 for item in scale)
        or len(shape) != 4
        or any(type(item) is not int or item <= 0 for item in shape)
    ):
        raise ScreenError(f"invalid explicit scale/shape metadata: {zarr_root.name}")
    return scale, shape, {
        "root_metadata_sha256": root_sha,
        "root_metadata_bytes": str(root_size),
        "array_metadata_sha256": array_sha,
        "array_metadata_bytes": str(array_size),
    }


def _gt_inventory(root: Path) -> dict[str, object]:
    selected = tuple([*(f"{stem}.geff" for stem in EVAL36), *(f"{stem}.zarr" for stem in EVAL36)])
    records: list[dict[str, object]] = []
    metadata: list[dict[str, object]] = []
    for stem in EVAL36:
        geff = root / f"{stem}.geff"
        records.extend(_relative_tree_records(root, (geff.name,)))
        zarr = root / f"{stem}.zarr"
        scale, shape, refs = _explicit_scale_and_shape(zarr)
        for relative in (f"{stem}.zarr/zarr.json", f"{stem}.zarr/0/zarr.json"):
            size, digest = _sha_file(root / relative)
            records.append({"path": relative, "bytes": size, "sha256": digest})
        metadata.append({"dataset": stem, "scale_zyx_um": scale, "shape_tzyx": shape, **refs})
    records.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    if len(set(selected)) != 72 or len(metadata) != 36:
        raise ScreenError("internal GT inventory set is invalid")
    value = _inventory("opaque_gt_and_scale_metadata", root, records)
    value["metadata"] = metadata
    return value


def _source_inventory(paths: ScreenPaths) -> dict[str, object]:
    records = []
    for relative in SOURCE_FILES:
        path = paths.repo_root / relative
        size, digest = _sha_file(path)
        records.append({"path": relative, "bytes": size, "sha256": digest})
    try:
        commit = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=paths.repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ("git", "status", "--porcelain", "--untracked-files=all"),
                cwd=paths.repo_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        official_head = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=paths.repo_root / "official",
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        official_dirty = bool(
            subprocess.run(
                ("git", "status", "--porcelain"),
                cwd=paths.repo_root / "official",
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScreenError("cannot bind current git/source state") from exc
    if official_head != "075fc5f5a52d11077f9dc2b074644618f26939e2" or official_dirty:
        raise ScreenError("official scorer checkout is not the frozen clean gitlink")
    return {
        "commit": commit,
        "dirty": dirty,
        "official_head": official_head,
        "official_clean": True,
        "records_sha256": sha256_bytes(canonical_json_bytes(records)),
        "records": records,
    }


def _dependency_inventory() -> dict[str, object]:
    versions: dict[str, str] = {}
    for name in RUNTIME_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ScreenError(f"required runtime distribution is absent: {name}") from exc
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "distributions": versions,
        "sha256": sha256_bytes(canonical_json_bytes(versions)),
    }


def _config_plain(config: object) -> dict[str, object]:
    values: dict[str, object] = {}
    for field in fields(config):  # type: ignore[arg-type]
        item = getattr(config, field.name)
        if isinstance(item, Path):
            values[field.name] = {"type": "path", "value": str(item)}
        elif type(item) is float:
            if not math.isfinite(item):
                raise ScreenError(f"nonfinite config field {field.name}")
            values[field.name] = {"type": "float64", "bits": struct.pack(">d", item).hex()}
        elif type(item) in (bool, int, str):
            values[field.name] = item
        else:
            raise ScreenError(f"unsupported config field {field.name}")
    return {"fields": values}


def _build_config(arm_name: str, image_root: Path, paths: ScreenPaths):
    from biohub.public_postproc.config import build_config

    overrides = {
        "BIOHUB_DEEPCENTER_CHECKPOINT": str(paths.deepcenter_checkpoint),
        "BIOHUB_DEEPCENTER_CHECKPOINT_DEFAULT": str(paths.deepcenter_checkpoint),
        "BIOHUB_DEEPCENTER_MANIFEST": str(paths.deepcenter_manifest),
        "BIOHUB_DEEPCENTER_MANIFEST_DEFAULT": str(paths.deepcenter_manifest),
    }
    profile = "e23"
    if arm_name in {"dry_run", "candidate"}:
        profile = "e23_twin_only_v1"
        overrides["BIOHUB_STEAL_TWIN_DRY_RUN"] = "1" if arm_name == "dry_run" else "0"
    elif arm_name not in {"baseline", "public4_parity"}:
        raise ScreenError("unknown frozen screen arm")
    config = build_config(overrides, test_dir=image_root, profile=profile)
    expected = {
        "public4_parity": (False, False, "e23_pub923_parity"),
        "baseline": (False, False, "e23_pub923_parity"),
        "dry_run": (True, True, "e23_twin_only_v1"),
        "candidate": (True, False, "e23_twin_only_v1"),
    }[arm_name]
    actual = (config.OUTPUT_STEAL_TWIN_REWIRE, config.STEAL_TWIN_DRY_RUN, config.EXPERIMENT_TAG)
    if actual != expected:
        raise ScreenError("frozen arm-to-config mapping drifted")
    return config


def _validate_profile_diffs(image_root: Path, paths: ScreenPaths) -> dict[str, dict[str, object]]:
    configs = {name: _build_config(name, image_root, paths) for name in ("baseline", "dry_run", "candidate")}
    baseline = configs["baseline"]
    allowed = {"OUTPUT_STEAL_TWIN_REWIRE", "STEAL_TWIN_DRY_RUN", "EXPERIMENT_TAG"}
    for name in ("dry_run", "candidate"):
        different = {
            field.name
            for field in fields(baseline)
            if getattr(baseline, field.name) != getattr(configs[name], field.name)
        }
        if not different <= allowed or "OUTPUT_STEAL_TWIN_REWIRE" not in different:
            raise ScreenError(f"{name} differs from exact E23 outside the frozen screen controls")
    return {
        name: {"sha256": sha256_bytes(canonical_json_bytes(_config_plain(config))), "value": _config_plain(config)}
        for name, config in configs.items()
    }


def _clone_file(source: Path, destination: Path) -> tuple[int, str]:
    if source.is_symlink() or not source.is_file():
        raise ScreenError(f"image snapshot source is not a regular file: {source}")
    before = source.stat()
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    current = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
    ):
        raise ScreenError(f"image source changed before clone: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    cloned = False
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        if hasattr(libc, "clonefile"):
            function = libc.clonefile
            function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
            function.restype = ctypes.c_int
            if function(os.fsencode(source), os.fsencode(destination), 0) == 0:
                cloned = True
            else:
                number = ctypes.get_errno()
                if number not in {18, 22, 45, 95}:
                    raise OSError(number, os.strerror(number), str(destination))
    if not cloned:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copystat(source, destination, follow_symlinks=False)
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ScreenError(f"image source changed during clone: {source}")
    if destination.is_symlink() or not destination.is_file() or destination.stat().st_size != before.st_size:
        raise ScreenError(f"image snapshot clone postcondition failed: {destination}")
    return before.st_size, digest.hexdigest()


def _build_image_snapshot(run_dir: Path, paths: ScreenPaths) -> dict[str, object]:
    source = paths.image_source
    staging = run_dir / "inputs/.image36.partial"
    final = run_dir / "inputs/image36"
    if staging.exists() or final.exists():
        raise ScreenError("image snapshot output already exists")
    source_paths: list[Path] = []
    required = 0
    for stem in EVAL36:
        base = source / f"{stem}.zarr"
        if base.is_symlink() or not base.is_dir():
            raise ScreenError(f"image source root is missing or symlinked: {base.name}")
        for item in [base, *base.rglob("*")]:
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode)):
                raise ScreenError(f"invalid image source entry: {item}")
            if stat.S_ISREG(info.st_mode):
                source_paths.append(item)
                required += info.st_size
    run_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(run_dir).free < required + 5 * 1024**3:
        raise ScreenError("insufficient free space for a safe image snapshot fallback copy")
    staging.mkdir(parents=True)
    cloned_records: list[dict[str, object]] = []
    for source_path in sorted(source_paths, key=lambda item: item.relative_to(source).as_posix().encode("utf-8")):
        relative = source_path.relative_to(source).as_posix()
        size, digest = _clone_file(source / relative, staging / relative)
        cloned_records.append({"path": relative, "bytes": size, "sha256": digest})
    os.rename(staging, final)
    return _inventory("image36", final, cloned_records)


def _arm_datasets(arm_name: str) -> tuple[str, ...]:
    return PUBLIC4 if arm_name == "public4_parity" else EVAL36


def _arm_inputs(arm_name: str, run_dir: Path, paths: ScreenPaths) -> tuple[Path, Path]:
    if arm_name == "public4_parity":
        return paths.raw4, paths.public4_images
    return paths.raw36, run_dir / "inputs/image36"


def _child_revalidate_inputs(
    arm_name: str,
    run_dir: Path,
    paths: ScreenPaths,
    initial: Mapping[str, object],
) -> None:
    raw_key, stems = ("raw4", PUBLIC4) if arm_name == "public4_parity" else ("raw36", EVAL36)
    raw_root, image_root = _arm_inputs(arm_name, run_dir, paths)
    if _inventory_identity(_geff_inventory(raw_key, raw_root, stems)) != _inventory_identity(initial[raw_key]):
        raise ScreenError(f"{arm_name}: raw input differs from control")
    if _inventory_identity(_source_inventory(paths)) != _inventory_identity(initial["source"]):
        raise ScreenError(f"{arm_name}: source differs from control")
    if _inventory_identity(_dependency_inventory()) != _inventory_identity(initial["dependencies"]):
        raise ScreenError(f"{arm_name}: runtime dependencies differ from control")
    if _inventory_identity(_pinned_evidence(paths)) != _inventory_identity(initial["pinned_evidence"]):
        raise ScreenError(f"{arm_name}: pinned evidence differs from control")
    for name, path in (
        ("checkpoint", paths.deepcenter_checkpoint),
        ("manifest", paths.deepcenter_manifest),
    ):
        current = dict(zip(("bytes", "sha256"), _sha_file(path), strict=True))
        if current != initial["deepcenter"][name]:  # type: ignore[index]
            raise ScreenError(f"{arm_name}: DeepCenter {name} differs from control")
    expected_names = {f"{stem}.zarr" for stem in stems}
    if image_root.is_symlink() or not image_root.is_dir():
        raise ScreenError(f"{arm_name}: image root is absent or symlinked")
    actual_names = {entry.name for entry in image_root.iterdir()}
    if actual_names != expected_names:
        raise ScreenError(f"{arm_name}: image root membership differs from the frozen set")
    if any(entry.is_symlink() or not entry.is_dir() for entry in image_root.iterdir()):
        raise ScreenError(f"{arm_name}: image root contains a symlink or non-directory")


def _arm_bindings(arm_name: str, initial: Mapping[str, object]) -> dict[str, object]:
    raw_key = "raw4" if arm_name == "public4_parity" else "raw36"
    image_key = "public4_images" if arm_name == "public4_parity" else "image36"
    return {
        "raw_inventory_sha256": _inventory_identity(initial[raw_key]),  # type: ignore[arg-type]
        "image_inventory_control_sha256": _inventory_identity(initial[image_key]),  # type: ignore[arg-type]
        "source_inventory_sha256": _inventory_identity(initial["source"]),  # type: ignore[arg-type]
        "dependency_inventory_sha256": _inventory_identity(initial["dependencies"]),  # type: ignore[arg-type]
        "pinned_evidence_sha256": _inventory_identity(initial["pinned_evidence"]),  # type: ignore[arg-type]
        "deepcenter_inventory_sha256": _inventory_identity(initial["deepcenter"]),  # type: ignore[arg-type]
        "image_content_check": "membership_in_child_full_hash_at_generation_end",
    }


def _validate_submission(path: Path, datasets: Sequence[str]) -> dict[str, object]:
    expected = tuple(datasets)
    node_times: dict[str, dict[int, int]] = {name: {} for name in expected}
    edges: dict[str, list[tuple[int, int]]] = {name: [] for name in expected}
    observed_blocks: list[str] = []
    rows = 0
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise ScreenError("submission CSV header drifted")
        previous_dataset: str | None = None
        for expected_id, row in enumerate(reader):
            if set(row) != set(CSV_COLUMNS) or any(value is None for value in row.values()):
                raise ScreenError("submission CSV row width drifted")
            try:
                values = {name: int(row[name]) for name in CSV_COLUMNS if name not in {"dataset", "row_type"}}
            except ValueError as exc:
                raise ScreenError("submission CSV contains a non-integer field") from exc
            if values["id"] != expected_id:
                raise ScreenError("submission CSV id is not globally contiguous")
            dataset = row["dataset"]
            if dataset not in node_times:
                raise ScreenError("submission CSV contains an unexpected dataset")
            if dataset != previous_dataset:
                if dataset in observed_blocks:
                    raise ScreenError("submission CSV dataset block is split")
                observed_blocks.append(dataset)
                previous_dataset = dataset
            if row["row_type"] == "node":
                node_id = values["node_id"]
                if node_id < 0 or values["t"] < 0 or min(values["z"], values["y"], values["x"]) < 0:
                    raise ScreenError("submission node fields are invalid")
                if values["source_id"] != -1 or values["target_id"] != -1 or node_id in node_times[dataset]:
                    raise ScreenError("submission node sentinel/id is invalid")
                node_times[dataset][node_id] = values["t"]
            elif row["row_type"] == "edge":
                if any(values[name] != -1 for name in ("node_id", "t", "z", "y", "x")):
                    raise ScreenError("submission edge sentinel is invalid")
                edges[dataset].append((values["source_id"], values["target_id"]))
            else:
                raise ScreenError("submission row_type is invalid")
            rows += 1
    if tuple(observed_blocks) != expected:
        raise ScreenError("submission dataset order/set differs from the frozen order")
    counts: dict[str, object] = {}
    for dataset in expected:
        pairs = edges[dataset]
        if len(set(pairs)) != len(pairs):
            raise ScreenError(f"{dataset}: duplicate edge")
        indegree = Counter(target for _, target in pairs)
        outdegree = Counter(source for source, _ in pairs)
        for source, target in pairs:
            if source not in node_times[dataset] or target not in node_times[dataset]:
                raise ScreenError(f"{dataset}: dangling edge")
            if node_times[dataset][target] != node_times[dataset][source] + 1:
                raise ScreenError(f"{dataset}: nonconsecutive edge")
        if max(indegree.values(), default=0) > 1 or max(outdegree.values(), default=0) > 2:
            raise ScreenError(f"{dataset}: degree invariant failed")
        counts[dataset] = {"nodes": len(node_times[dataset]), "edges": len(pairs)}
    size, digest = _sha_file(path)
    return {"bytes": size, "sha256": digest, "rows": rows, "datasets": list(expected), "counts": counts}


def _rss_bytes() -> int:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw) if sys.platform == "darwin" else int(raw * 1024)


def _current_pid() -> int:
    return os.getpid()


def execute_arm(run_id: str, arm_name: str, control_sha256: str, paths: ScreenPaths | None = None) -> dict[str, object]:
    """Execute one child arm.  This function never seals or scores a run."""
    selected = paths or production_paths()
    run_dir = resolve_run_dir(run_id, selected)
    control_path = run_dir / "CONTROL.json"
    size, digest = _sha_file(control_path)
    if digest != _require_sha(control_sha256, "control"):
        raise ScreenError("control hash mismatch")
    control = json.loads(control_path.read_bytes())
    if control.get("schema_version") != CONTROL_SCHEMA or control.get("run_id") != run_id:
        raise ScreenError("control schema/run mismatch")
    if arm_name not in ARM_ORDER or control.get("arm_order") != list(ARM_ORDER):
        raise ScreenError("arm is not in the frozen execution order")
    _child_revalidate_inputs(arm_name, run_dir, selected, control["initial_inventories"])
    arm_dir = run_dir / "generation" / arm_name
    arm_dir.mkdir(parents=True, exist_ok=False)
    raw_root, image_root = _arm_inputs(arm_name, run_dir, selected)
    datasets = _arm_datasets(arm_name)
    config = _build_config(arm_name, image_root, selected)
    config_value = _config_plain(config)
    config_sha = sha256_bytes(canonical_json_bytes(config_value))
    if control["configs"].get(arm_name, {}).get("sha256") != config_sha:
        raise ScreenError("child effective config differs from control")

    from biohub.public_postproc.deepcenter import load_deepcenter_veto_detector_strict
    from biohub.public_postproc.pipeline import run_postproc_core, twin_plan_plain

    bundle, deepcenter_receipt = load_deepcenter_veto_detector_strict(
        config, selected.deepcenter_checkpoint, selected.deepcenter_manifest
    )
    plans: list[dict[str, object]] = []
    raw_stats: list[dict[str, object]] = []

    def strict_loader(actual: object) -> dict[str, object]:
        if actual is not config:
            raise ScreenError("pipeline replaced the validated config")
        return bundle

    def plan_hook(dataset: str, plan: object | None) -> None:
        plans.append(
            {
                "dataset": dataset,
                "planner_active": plan is not None,
                "plan": None if plan is None else twin_plan_plain(plan),
            }
        )

    def stats_hook(row: Mapping[str, object]) -> None:
        raw_stats.append(dict(row))

    started = time.perf_counter_ns()
    result = run_postproc_core(
        tuple(raw_root / f"{dataset}.geff" for dataset in datasets),
        arm_dir / "submission.csv",
        config,
        run_stats_path=arm_dir / "run_stats.csv",
        deepcenter_loader=strict_loader,
        twin_plan_hook=plan_hook,
        raw_stats_hook=stats_hook,
        exclusive_output=True,
    )
    duration = time.perf_counter_ns() - started
    if tuple(result["datasets"]) != datasets or [item["dataset"] for item in raw_stats] != list(datasets):
        raise ScreenError("pipeline execution order drifted")
    if [item["dataset"] for item in plans] != list(datasets):
        raise ScreenError("pipeline plan order drifted")
    submission = _validate_submission(arm_dir / "submission.csv", datasets)
    _write_new(arm_dir / "effective_config.json", canonical_json_bytes(config_value))
    _write_new(arm_dir / "deepcenter_receipt.json", canonical_json_bytes(deepcenter_receipt))
    _write_new(arm_dir / "plans.json", canonical_json_bytes(plans))
    _write_new(arm_dir / "raw_stats.json", canonical_json_bytes(raw_stats))
    artifacts = {}
    for name in (
        "submission.csv",
        "run_stats.csv",
        "effective_config.json",
        "deepcenter_receipt.json",
        "plans.json",
        "raw_stats.json",
    ):
        artifact_size, artifact_sha = _sha_file(arm_dir / name)
        artifacts[name] = {"bytes": artifact_size, "sha256": artifact_sha}
    value = {
        "schema_version": ARM_SCHEMA,
        "status": "SCREEN_ARM_COMPLETE_NOT_SEALED",
        "run_id": run_id,
        "arm_name": arm_name,
        "datasets": list(datasets),
        "control_sha256": digest,
        "control_bytes": size,
        "config_sha256": config_sha,
        "input_bindings": _arm_bindings(arm_name, control["initial_inventories"]),
        "process": {"pid": _current_pid(), "parent_pid": os.getppid()},
        "submission": submission,
        "artifacts": artifacts,
        "duration_ns": duration,
        "process_peak_rss_bytes": _rss_bytes(),
        "claims": {"scored": False, "sealed": False, "submission_permitted": False},
    }
    _write_new(arm_dir / "ARM_RESULT.json", canonical_json_bytes(value))
    return value


ArmRunner = Callable[[str, str, str, ScreenPaths], int]


def _spawn_arm(run_id: str, arm_name: str, control_sha256: str, paths: ScreenPaths) -> int:
    argv = (
        str(Path(sys.executable).absolute()),
        str(paths.child_script),
        "_arm",
        "--run-id",
        run_id,
        "--arm-name",
        arm_name,
        "--control-sha256",
        control_sha256,
    )
    completed = subprocess.run(
        argv,
        cwd=paths.repo_root,
        env=FIXED_CHILD_ENVIRONMENT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    arm_dir = resolve_run_dir(run_id, paths) / "generation" / arm_name
    with contextlib.suppress(Exception):
        _write_new(arm_dir / "stdout.log", completed.stdout)
        _write_new(arm_dir / "stderr.log", completed.stderr)
    return completed.returncode


def _read_arm_result(
    run_dir: Path,
    arm_name: str,
    control_sha: str,
    control: Mapping[str, object],
    generation_pid: int,
) -> dict[str, object]:
    path = run_dir / "generation" / arm_name / "ARM_RESULT.json"
    _, digest = _sha_file(path)
    value = json.loads(path.read_bytes())
    if (
        value.get("schema_version") != ARM_SCHEMA
        or value.get("status") != "SCREEN_ARM_COMPLETE_NOT_SEALED"
        or value.get("arm_name") != arm_name
        or value.get("datasets") != list(_arm_datasets(arm_name))
        or value.get("control_sha256") != control_sha
        or value.get("config_sha256") != control["configs"][arm_name]["sha256"]  # type: ignore[index]
        or value.get("input_bindings") != _arm_bindings(arm_name, control["initial_inventories"])  # type: ignore[arg-type]
    ):
        raise ScreenError(f"invalid child arm result: {arm_name}")
    process = value.get("process")
    if (
        not isinstance(process, dict)
        or type(process.get("pid")) is not int
        or process["pid"] <= 0
        or process["pid"] == generation_pid
        or process.get("parent_pid") != generation_pid
    ):
        raise ScreenError(f"arm was not a direct fresh child process: {arm_name}")
    arm_dir = path.parent
    expected_artifacts = {
        "submission.csv",
        "run_stats.csv",
        "effective_config.json",
        "deepcenter_receipt.json",
        "plans.json",
        "raw_stats.json",
    }
    if set(value.get("artifacts", {})) != expected_artifacts:
        raise ScreenError(f"child artifact set differs: {arm_name}")
    for name, reference in value["artifacts"].items():
        size, artifact_sha = _sha_file(arm_dir / name)
        if reference != {"bytes": size, "sha256": artifact_sha}:
            raise ScreenError(f"child artifact changed: {arm_name}/{name}")
    value["arm_result_sha256"] = digest
    return value


def _common_stats_equal(first: Path, second: Path) -> bool:
    left = json.loads(first.read_bytes())
    right = json.loads(second.read_bytes())
    if [item.get("dataset") for item in left] != [item.get("dataset") for item in right]:
        return False
    def strip(row: Mapping[str, object]) -> dict[str, object]:
        return {key: value for key, value in row.items() if not key.startswith("steal_twin_")}

    return [strip(item) for item in left] == [strip(item) for item in right]


def _validate_arm_telemetry(run_dir: Path, arm_name: str, paths: ScreenPaths) -> None:
    from biohub.public_postproc.production_adapter import _RAW_STATS_COLUMNS, _validate_raw_stats_row

    arm_dir = run_dir / "generation" / arm_name
    plans = json.loads((arm_dir / "plans.json").read_bytes())
    rows = json.loads((arm_dir / "raw_stats.json").read_bytes())
    datasets = _arm_datasets(arm_name)
    if (
        not isinstance(plans, list)
        or not isinstance(rows, list)
        or [item.get("dataset") for item in plans] != list(datasets)
        or [item.get("dataset") for item in rows] != list(datasets)
    ):
        raise ScreenError(f"{arm_name}: telemetry order/set differs")
    active = arm_name in {"dry_run", "candidate"}
    image_root = paths.public4_images if arm_name == "public4_parity" else run_dir / "inputs/image36"
    for dataset, plan_envelope, row in zip(datasets, plans, rows, strict=True):
        if type(plan_envelope.get("planner_active")) is not bool or plan_envelope["planner_active"] is not active:
            raise ScreenError(f"{arm_name}/{dataset}: planner activity differs from the frozen arm")
        plan = plan_envelope.get("plan")
        if active:
            if not isinstance(plan, dict) or plan.get("validation_reason") is not None:
                raise ScreenError(f"{arm_name}/{dataset}: twin planner validation failed")
        elif plan is not None:
            raise ScreenError(f"{arm_name}/{dataset}: inactive planner emitted a plan")
        _scale, shape, _refs = _explicit_scale_and_shape(image_root / f"{dataset}.zarr")
        try:
            allowed = set(_RAW_STATS_COLUMNS) | {"gap_close_effective_max_gap"}
            if set(row) not in (set(_RAW_STATS_COLUMNS), allowed):
                raise ValueError("raw stats keys are missing or extra")
            ordered = {name: row[name] for name in _RAW_STATS_COLUMNS}
            if "gap_close_effective_max_gap" in row:
                ordered["gap_close_effective_max_gap"] = row["gap_close_effective_max_gap"]
            _validate_raw_stats_row(ordered, dataset, shape[0])
        except (TypeError, ValueError) as exc:
            raise ScreenError(f"{arm_name}/{dataset}: invalid counter conservation: {exc}") from exc
        if arm_name == "dry_run" and any(
            row[name] != 0
            for name in ("steal_twin_edges_removed", "steal_twin_edges_added", "steal_twin_mutations_applied")
        ):
            raise ScreenError(f"{arm_name}/{dataset}: dry-run mutated the graph")
        if arm_name == "candidate" and row["steal_twin_mutations_applied"] != row["steal_twin_accepted"]:
            raise ScreenError(f"{arm_name}/{dataset}: candidate silently skipped an accepted mutation")


def _post_inventories(run_dir: Path, paths: ScreenPaths) -> dict[str, object]:
    image36 = _inventory(
        "image36",
        run_dir / "inputs/image36",
        _relative_tree_records(run_dir / "inputs/image36", tuple(f"{stem}.zarr" for stem in EVAL36)),
    )
    public4_images = _inventory(
        "public4_images",
        paths.public4_images,
        _relative_tree_records(paths.public4_images, tuple(f"{stem}.zarr" for stem in PUBLIC4)),
    )
    return {
        "raw36": _geff_inventory("raw36", paths.raw36, EVAL36),
        "raw4": _geff_inventory("raw4", paths.raw4, PUBLIC4),
        "image36": image36,
        "public4_images": public4_images,
        "opaque_gt": _gt_inventory(paths.gt),
        "deepcenter": {
            "checkpoint": dict(zip(("bytes", "sha256"), _sha_file(paths.deepcenter_checkpoint), strict=True)),
            "manifest": dict(zip(("bytes", "sha256"), _sha_file(paths.deepcenter_manifest), strict=True)),
        },
        "source": _source_inventory(paths),
        "dependencies": _dependency_inventory(),
        "pinned_evidence": _pinned_evidence(paths),
    }


def _inventory_identity(value: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _publish_error(run_dir: Path, operation: str, exc: BaseException) -> None:
    payload = {
        "schema_version": ERROR_SCHEMA,
        "status": "SCREEN_ERROR",
        "operation": operation,
        "error_type": type(exc).__name__,
        "message": str(exc)[:512],
        "submission_permitted": False,
        "adoption_permitted": False,
    }
    with contextlib.suppress(Exception):
        _write_new(run_dir / f"{operation.upper()}_ERROR.json", canonical_json_bytes(payload))


def generate_screen(
    run_id: str,
    *,
    paths: ScreenPaths | None = None,
    arm_runner: ArmRunner | None = None,
) -> ScreenGenerationResult:
    selected = paths or production_paths()
    _reject_production_test_hook(selected, arm_runner, "arm runner")
    run_dir = resolve_run_dir(run_id, selected)
    if run_dir.exists() or run_dir.is_symlink():
        raise ScreenError("screen run already exists; resume/overwrite is forbidden")
    selected.screen_parent.mkdir(parents=True, exist_ok=True)
    if selected.screen_parent.is_symlink():
        raise ScreenError("screen parent may not be a symlink")
    run_dir.mkdir(mode=0o700)
    try:
        initial_image36 = _build_image_snapshot(run_dir, selected)
        initial = {
            "raw36": _geff_inventory("raw36", selected.raw36, EVAL36),
            "raw4": _geff_inventory("raw4", selected.raw4, PUBLIC4),
            "image36": initial_image36,
            "public4_images": _inventory(
                "public4_images",
                selected.public4_images,
                _relative_tree_records(selected.public4_images, tuple(f"{stem}.zarr" for stem in PUBLIC4)),
            ),
            "opaque_gt": _gt_inventory(selected.gt),
            "deepcenter": {
                "checkpoint": dict(
                    zip(("bytes", "sha256"), _sha_file(selected.deepcenter_checkpoint), strict=True)
                ),
                "manifest": dict(zip(("bytes", "sha256"), _sha_file(selected.deepcenter_manifest), strict=True)),
            },
            "source": _source_inventory(selected),
            "dependencies": _dependency_inventory(),
            "pinned_evidence": _pinned_evidence(selected),
        }
        if initial["deepcenter"]["checkpoint"]["sha256"] != DEEPCENTER_CHECKPOINT_SHA256:
            raise ScreenError("DeepCenter checkpoint pin mismatch")
        if initial["deepcenter"]["manifest"]["sha256"] != DEEPCENTER_MANIFEST_SHA256:
            raise ScreenError("DeepCenter manifest pin mismatch")
        _, reference_sha = _sha_file(selected.public4_reference)
        if reference_sha != PUBLIC4_REFERENCE_SHA256:
            raise ScreenError("public-four reference pin mismatch")
        configs = _validate_profile_diffs(run_dir / "inputs/image36", selected)
        public4_config = _config_plain(_build_config("public4_parity", selected.public4_images, selected))
        configs["public4_parity"] = {
            "sha256": sha256_bytes(canonical_json_bytes(public4_config)),
            "value": public4_config,
        }
        control = {
            "schema_version": CONTROL_SCHEMA,
            "protocol_version": PROTOCOL_VERSION,
            "run_id": run_id,
            "candidate_id": "e23_twin_only_v1",
            "parent": "exact_e23",
            "datasets": {"eval12": list(EVAL12), "eval24": list(EVAL24), "eval36": list(EVAL36)},
            "arm_order": list(ARM_ORDER),
            "configs": configs,
            "initial_inventories": initial,
            "platform": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "system": platform.system(),
                "machine": platform.machine(),
            },
            "generation_process": {"pid": _current_pid()},
            "claims": {
                "screen_only": True,
                "production_certified": False,
                "submission_permitted": False,
                "adoption_permitted": False,
            },
        }
        control_bytes = canonical_json_bytes(control)
        control_sha = sha256_bytes(control_bytes)
        _write_new(run_dir / "CONTROL.json", control_bytes)
        runner = arm_runner or _spawn_arm
        arm_results: dict[str, object] = {}
        child_pids: set[int] = set()
        for arm_name in ARM_ORDER:
            if runner(run_id, arm_name, control_sha, selected) != 0:
                raise ScreenError(f"fresh child failed: {arm_name}")
            arm_result = _read_arm_result(run_dir, arm_name, control_sha, control, _current_pid())
            child_pid = arm_result["process"]["pid"]  # type: ignore[index]
            if child_pid in child_pids:
                raise ScreenError("screen arms did not use distinct fresh child processes")
            child_pids.add(child_pid)
            arm_results[arm_name] = arm_result
            _validate_arm_telemetry(run_dir, arm_name, selected)

            if arm_name == "public4_parity":
                parity = run_dir / "generation/public4_parity/submission.csv"
                if (
                    _sha_file(parity)[1] != PUBLIC4_REFERENCE_SHA256
                    or parity.read_bytes() != selected.public4_reference.read_bytes()
                ):
                    raise ScreenError("fresh current-source public-four E23 parity failed")

        dry_dir = run_dir / "generation/dry_run"
        base_dir = run_dir / "generation/baseline"
        candidate_dir = run_dir / "generation/candidate"
        if (dry_dir / "submission.csv").read_bytes() != (base_dir / "submission.csv").read_bytes():
            raise ScreenError("exact E23/off and twin dry-run submissions differ")
        if not _common_stats_equal(dry_dir / "raw_stats.json", base_dir / "raw_stats.json"):
            raise ScreenError("exact E23/off and twin dry-run common telemetry differ")
        if (dry_dir / "plans.json").read_bytes() != (candidate_dir / "plans.json").read_bytes():
            raise ScreenError("dry-run and candidate pre-mutation plans differ")

        final = _post_inventories(run_dir, selected)
        for key in initial:
            if _inventory_identity(initial[key]) != _inventory_identity(final[key]):
                raise ScreenError(f"input/source changed during screen generation: {key}")
        seal = {
            "schema_version": GENERATION_SCHEMA,
            "status": "SCREEN_GENERATION_SEALED",
            "protocol_version": PROTOCOL_VERSION,
            "run_id": run_id,
            "control_sha256": control_sha,
            "candidate_id": "e23_twin_only_v1",
            "parent": "exact_e23",
            "datasets": control["datasets"],
            "execution_order": list(ARM_ORDER),
            "generation_process": control["generation_process"],
            "arms": arm_results,
            "input_inventories": final,
            "checks": {
                "public4_current_source_parity": True,
                "off_dry_submission_identity": True,
                "off_dry_common_telemetry_identity": True,
                "dry_candidate_plan_identity": True,
                "inputs_stable": True,
            },
            "claims": {
                "screen_only": True,
                "production_certified": False,
                "target_runtime_verified": False,
                "whole_process_tree_rss_verified": False,
                "network_unavailable_proven": False,
                "submission_permitted": False,
                "adoption_permitted": False,
            },
        }
        seal_bytes = canonical_json_bytes(seal)
        seal_sha = sha256_bytes(seal_bytes)
        _write_new(run_dir / "SCREEN_GENERATION_SEALED.json", seal_bytes)
        return ScreenGenerationResult("SCREEN_GENERATION_SEALED", run_dir, seal_sha)
    except BaseException as exc:
        _publish_error(run_dir, "generation", exc)
        raise


def _subset_csv(source: Path, destination: Path, stems: Sequence[str]) -> None:
    wanted = set(stems)
    if len(wanted) != len(stems):
        raise ScreenError("duplicate dataset in score stage")
    with source.open(newline="") as reader_handle, destination.open("x", newline="") as writer_handle:
        reader = csv.DictReader(reader_handle)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise ScreenError("source CSV header drifted before scoring")
        writer = csv.DictWriter(writer_handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        seen: set[str] = set()
        next_id = 0
        for row in reader:
            if row["dataset"] in wanted:
                row["id"] = str(next_id)
                writer.writerow(row)
                seen.add(row["dataset"])
                next_id += 1
        writer_handle.flush()
        os.fsync(writer_handle.fileno())
    if seen != wanted:
        raise ScreenError("score subset omitted a frozen dataset")


def _screen_gate(stage: str, gate: Mapping[str, object]) -> dict[str, object]:
    first = gate.get("first_failure")
    if first is not None and type(first) is not str:
        raise ScreenError("metric gate returned an invalid first failure")
    if first is None:
        status = "SCREEN_PASS_REQUIRES_CONFIRMATION" if stage == "eval36" else f"SCREEN_{stage.upper()}_PASS"
    else:
        status = f"SCREEN_REJECT_{stage.upper()}"
    return {
        "schema_version": "biohub.kaggle_screen.metric_gate.v1",
        "stage": stage,
        "status": status,
        "first_failure": first,
        "gates": gate.get("gates"),
        "submission_permitted": False,
        "adoption_permitted": False,
    }


def _diagnostics(deltas: Mapping[str, object]) -> dict[str, object]:
    values = [float(item["combined_score_delta"]) for item in deltas["per_video"]]  # type: ignore[index]
    changed = [value for value in values if value != 0.0]
    return {
        "changed_videos": len(changed),
        "strictly_positive_videos": sum(value > 0 for value in values),
        "strictly_negative_videos": sum(value < 0 for value in values),
        "unchanged_videos": sum(value == 0 for value in values),
        "max_absolute_single_video_delta": max((abs(value) for value in values), default=0.0),
    }


ScoreFunction = Callable[[Path, Path, float, bool], tuple[dict[str, Any], list[dict[str, Any]]]]


def _verify_sealed_predictions(run_dir: Path, seal: Mapping[str, object]) -> None:
    arms = seal.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(ARM_ORDER):
        raise ScreenError("generation seal arm set is incomplete")
    for arm in ("baseline", "candidate"):
        source = run_dir / "generation" / arm / "submission.csv"
        expected = arms[arm].get("artifacts", {}).get("submission.csv")
        size, digest = _sha_file(source)
        if expected != {"bytes": size, "sha256": digest}:
            raise ScreenError(f"sealed {arm} submission changed before scoring")
        _validate_submission(source, EVAL36)


def _score_stage(
    run_dir: Path,
    seal: Mapping[str, object],
    stage: str,
    stems: Sequence[str],
    paths: ScreenPaths,
    score_function: ScoreFunction,
) -> tuple[dict[str, object], list[dict[str, Any]]]:
    from biohub.evaluate import summarise
    from biohub.st_r3_scoring import build_aggregates, build_deltas, evaluate_metric_gates

    stage_dir = run_dir / "scores" / stage
    stage_dir.mkdir(parents=True, exist_ok=False)
    arm_rows: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in ("baseline", "candidate"):
        source = run_dir / "generation" / arm / "submission.csv"
        expected = seal["arms"][arm]["artifacts"]["submission.csv"]  # type: ignore[index]
        size, digest = _sha_file(source)
        if expected != {"bytes": size, "sha256": digest}:
            raise ScreenError(f"sealed {arm} submission changed before scoring")
        subset = stage_dir / f"{arm}.csv"
        _subset_csv(source, subset, stems)
        _validate_submission(subset, stems)
        _summary, rows = score_function(subset, paths.gt, 7.0, False)
        if len(rows) != len(stems) or {item.get("dataset") for item in rows} != set(stems):
            raise ScreenError(f"official wrapper skipped/duplicated GT in {stage}/{arm}")
        by_dataset = {str(item["dataset"]): item for item in rows}
        if len(by_dataset) != len(rows):
            raise ScreenError(f"official wrapper duplicated a dataset in {stage}/{arm}")
        arm_rows[arm] = {}
        for stem in stems:
            row = by_dataset[stem]
            raw = {key: value for key, value in row.items() if key != "dataset"}
            arm_rows[arm][stem] = {"per_sample": row, "singleton_summary": summarise([raw])}
    rows = [
        {"dataset": stem, "baseline": arm_rows["baseline"][stem], "candidate": arm_rows["candidate"][stem]}
        for stem in stems
    ]
    aggregates = build_aggregates(rows, stems, stage)
    aggregates["schema_version"] = "biohub.kaggle_screen.official_aggregates.v1"
    deltas = build_deltas(rows, aggregates, stems, stage)
    deltas["schema_version"] = "biohub.kaggle_screen.paired_deltas.v1"
    gate = _screen_gate(stage, evaluate_metric_gates(stage, deltas))
    result = {
        "schema_version": SCORE_STAGE_SCHEMA,
        "stage": stage,
        "status": gate["status"],
        "rows": rows,
        "aggregates": aggregates,
        "deltas": deltas,
        "gate": gate,
        "diagnostics": _diagnostics(deltas),
        "claims": {"screen_only": True, "submission_permitted": False, "adoption_permitted": False},
    }
    _write_new(stage_dir / "RESULT.json", canonical_json_bytes(result))
    return result, rows


def score_screen(
    run_id: str,
    generation_seal_sha256: str,
    *,
    paths: ScreenPaths | None = None,
    score_function: ScoreFunction | None = None,
) -> ScreenScoreResult:
    selected = paths or production_paths()
    _reject_production_test_hook(selected, score_function, "score function")
    run_dir = resolve_run_dir(run_id, selected)
    seal_path = run_dir / "SCREEN_GENERATION_SEALED.json"
    _, seal_sha = _sha_file(seal_path)
    if seal_sha != _require_sha(generation_seal_sha256, "generation seal"):
        raise ScreenError("generation seal hash mismatch")
    seal = json.loads(seal_path.read_bytes())
    if (
        seal.get("schema_version") != GENERATION_SCHEMA
        or seal.get("status") != "SCREEN_GENERATION_SEALED"
        or seal.get("run_id") != run_id
        or seal.get("datasets") != {"eval12": list(EVAL12), "eval24": list(EVAL24), "eval36": list(EVAL36)}
    ):
        raise ScreenError("generation seal schema/state/datasets mismatch")
    generation_process = seal.get("generation_process")
    if (
        not isinstance(generation_process, dict)
        or type(generation_process.get("pid")) is not int
        or generation_process["pid"] <= 0
        or generation_process["pid"] == _current_pid()
    ):
        raise ScreenError("scoring must run in a process separate from generation")
    sealed_inputs = seal.get("input_inventories")
    if not isinstance(sealed_inputs, dict):
        raise ScreenError("generation seal input inventories are missing")
    for name, current in (
        ("source", _source_inventory(selected)),
        ("dependencies", _dependency_inventory()),
    ):
        sealed = sealed_inputs.get(name)
        if not isinstance(sealed, dict) or _inventory_identity(current) != _inventory_identity(sealed):
            raise ScreenError(f"sealed {name} changed before scoring")
    if (run_dir / "scores").exists() or (run_dir / "VERDICT.json").exists():
        raise ScreenError("screen scoring is single-use and cannot resume/overwrite")
    _verify_sealed_predictions(run_dir, seal)
    function = score_function
    if function is None:
        from biohub.evaluate import score_submission

        function = score_submission
    try:
        current_gt = _gt_inventory(selected.gt)
        if _inventory_identity(current_gt) != _inventory_identity(seal["input_inventories"]["opaque_gt"]):  # type: ignore[index]
            raise ScreenError("opaque GT/explicit scale metadata changed before scoring")
        eval12, rows12 = _score_stage(run_dir, seal, "eval12", EVAL12, selected, function)
        if eval12["gate"]["first_failure"] is not None:  # type: ignore[index]
            status = "SCREEN_REJECT_EVAL12"
            first_failure = str(eval12["gate"]["first_failure"])  # type: ignore[index]
        else:
            eval24, rows24 = _score_stage(run_dir, seal, "eval24", EVAL24, selected, function)
            if eval24["gate"]["first_failure"] is not None:  # type: ignore[index]
                status = "SCREEN_REJECT_EVAL24"
                first_failure = str(eval24["gate"]["first_failure"])  # type: ignore[index]
            else:
                from biohub.st_r3_scoring import build_aggregates, build_deltas, evaluate_metric_gates

                rows36 = rows12 + rows24
                if [item["dataset"] for item in rows36] != list(EVAL36):
                    raise ScreenError("stored eval12+eval24 row order differs from EVAL36")
                aggregates = build_aggregates(rows36, EVAL36, "eval36")
                aggregates["schema_version"] = "biohub.kaggle_screen.official_aggregates.v1"
                deltas = build_deltas(rows36, aggregates, EVAL36, "eval36")
                deltas["schema_version"] = "biohub.kaggle_screen.paired_deltas.v1"
                gate = _screen_gate("eval36", evaluate_metric_gates("eval36", deltas))
                rollup = {
                    "schema_version": SCORE_STAGE_SCHEMA,
                    "stage": "eval36",
                    "status": gate["status"],
                    "source_stages": ["eval12", "eval24"],
                    "aggregates": aggregates,
                    "deltas": deltas,
                    "gate": gate,
                    "diagnostics": _diagnostics(deltas),
                }
                rollup_dir = run_dir / "scores/eval36"
                rollup_dir.mkdir(parents=True, exist_ok=False)
                _write_new(rollup_dir / "RESULT.json", canonical_json_bytes(rollup))
                status = str(gate["status"])
                first_failure = None if gate["first_failure"] is None else str(gate["first_failure"])
        verdict = {
            "schema_version": VERDICT_SCHEMA,
            "status": status,
            "run_id": run_id,
            "candidate_id": "e23_twin_only_v1",
            "parent": "exact_e23",
            "generation_seal_sha256": seal_sha,
            "score_process": {"pid": _current_pid()},
            "score_artifacts": _inventory(
                "score_artifacts",
                run_dir / "scores",
                _relative_tree_records(run_dir / "scores"),
            ),
            "first_failure": first_failure,
            "screen_only": True,
            "confirmation_required": status == "SCREEN_PASS_REQUIRES_CONFIRMATION",
            "submission_permitted": False,
            "adoption_permitted": False,
            "kaggle_action_permitted": False,
        }
        _write_new(run_dir / "VERDICT.json", canonical_json_bytes(verdict))
        return ScreenScoreResult(status, run_dir, first_failure)
    except BaseException as exc:
        _publish_error(run_dir, "score", exc)
        raise


__all__ = [
    "ARM_ORDER",
    "EVAL12",
    "EVAL24",
    "EVAL36",
    "PUBLIC4",
    "ScreenError",
    "ScreenGenerationResult",
    "ScreenPaths",
    "ScreenScoreResult",
    "canonical_json_bytes",
    "execute_arm",
    "generate_screen",
    "production_paths",
    "resolve_run_dir",
    "score_screen",
]
