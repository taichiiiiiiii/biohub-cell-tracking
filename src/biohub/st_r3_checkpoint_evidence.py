"""Produce narrowly scoped ST-R3 checkpoint-identity evidence.

The primary ``checkpoint_last.pth`` is deliberately never opened because no
retained manifest pins it.  A ``checkpoint_last`` file is a resume snapshot,
never an inference weight.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import math
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from biohub import st_r3_raw_provenance as _secure

GitState = _secure.GitState


class CheckpointEvidenceError(_secure.RawProvenanceError):
    """Checkpoint evidence cannot safely support the fixed receipt."""


class CheckpointPublicationAmbiguityError(CheckpointEvidenceError):
    """Publication or rollback could not be proven complete and durable."""


PublicationAmbiguityError = CheckpointPublicationAmbiguityError

SCHEMA_VERSION = "biohub.st_r3.checkpoint_evidence.v1"
STATUS = "CHECKPOINT_IDENTITY_VERIFIED_WITH_HOLDS"
HISTORY_SCOPE = "LEGACY_IN_SAMPLE_MONITORING_ONLY"
CANONICAL_REPO_ROOT = Path("/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking")
RECEIPT_NAME = "CHECKPOINT_EVIDENCE.json"
MAX_JSON_BYTES = 128 * 1024
MAX_HISTORY_BYTES = 256 * 1024
MAX_RECEIPT_BYTES = 128 * 1024
OFFICIAL_OID = "075fc5f5a52d11077f9dc2b074644618f26939e2"
PRIMARY_BEST_SHA256 = "12f6881ee3620a831697ca098ff8f48e687a24225f4e048b538deec3562fe771"
SECONDARY_BEST_SHA256 = "9bac2fa0dadc4a6fc1899e0caf187f4b553e0a7cd90ba1261a68b35ffe9e305f"


@dataclass(frozen=True)
class FilePin:
    relative: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Authority:
    output_parent_relative: str
    primary_root_relative: str
    secondary_root_relative: str
    runtime_integrity: FilePin
    primary_manifest: FilePin
    primary_config: FilePin
    primary_best: FilePin
    secondary_artifact_manifest: FilePin
    secondary_snapshot_manifest: FilePin
    secondary_files: tuple[FilePin, ...]
    official_oid: str
    builder_sources: tuple[str, ...]


PRODUCTION_AUTHORITY = Authority(
    output_parent_relative="outputs/local/st_r3_checkpoint_evidence",
    primary_root_relative="outputs/kaggle/st_r3_checkpoint_recovery/primary",
    secondary_root_relative="outputs/kaggle/st_r3_checkpoint_recovery/secondary",
    runtime_integrity=FilePin(
        "outputs/kaggle/e22_bidir030_eval36_reference/bidirectional_production_runtime_integrity.json",
        2387,
        "ae41130ee035d3ddcbaf2d0977f721429a52ffda8133fe1b877f51de5926278d",
    ),
    primary_manifest=FilePin(
        "outputs/kaggle/st_r3_checkpoint_recovery/primary/ARTIFACT_MANIFEST.json",
        4376,
        "bc20f1f04cfb682af3b27a836ce9a57f44a2fe27508dc59039200b2a23188103",
    ),
    primary_config=FilePin(
        "outputs/kaggle/st_r3_checkpoint_recovery/primary/config.json",
        165,
        "e9b4e396c58081bca08adf8275bd0bd1c2d3fd6eb091a1912a5116cb6de7b50a",
    ),
    primary_best=FilePin(
        "outputs/kaggle/st_r3_checkpoint_recovery/primary/edge_predictor_best.pth",
        8363159,
        PRIMARY_BEST_SHA256,
    ),
    secondary_artifact_manifest=FilePin(
        "outputs/kaggle/st_r3_checkpoint_recovery/secondary/ARTIFACT_MANIFEST.json",
        6580,
        "7f01c0b2f9491606a1b543339e072230e25317d9c70fb9a18aea59e002a995eb",
    ),
    secondary_snapshot_manifest=FilePin(
        "outputs/kaggle/st_r3_checkpoint_recovery/secondary/SNAPSHOT_MANIFEST.json",
        1291,
        "11a09cf761999695f5da2dd06d7a7ad32886dc7617d3fde3c8efe081041c9fd2",
    ),
    secondary_files=(
        FilePin(
            "outputs/kaggle/st_r3_checkpoint_recovery/secondary/checkpoint_last.pth",
            25070547,
            "ee6c123717c9f99945888b502c6301c5d769bf9647bcb0b96f0016037df42d8c",
        ),
        FilePin(
            "outputs/kaggle/st_r3_checkpoint_recovery/secondary/config.json",
            165,
            "e9b4e396c58081bca08adf8275bd0bd1c2d3fd6eb091a1912a5116cb6de7b50a",
        ),
        FilePin(
            "outputs/kaggle/st_r3_checkpoint_recovery/secondary/edge_predictor_best.pth", 8363159, SECONDARY_BEST_SHA256
        ),
        FilePin(
            "outputs/kaggle/st_r3_checkpoint_recovery/secondary/history.csv",
            89559,
            "dfc4fd06d0c32b31bb1a35944fda1457c7585134e2596583e611c41880960ba2",
        ),
        FilePin(
            "outputs/kaggle/st_r3_checkpoint_recovery/secondary/split_manifest.json",
            5359,
            "cbe8ace34ffc157172280538441454b60250f0188faa063d1a9eadfb1ac55c0b",
        ),
        FilePin(
            "outputs/kaggle/st_r3_checkpoint_recovery/secondary/training_config.json",
            899,
            "4f29349439e133ad41846dec14b30f5cdbe2b7bb20908c5d0d3d205b5d71a87b",
        ),
    ),
    official_oid=OFFICIAL_OID,
    builder_sources=(
        "src/biohub/st_r3_checkpoint_evidence.py", "scripts/experiments/st_r3/st_r3_checkpoint_evidence.py",
    ),
)

PRIMARY_MEMBERS = {"ARTIFACT_MANIFEST.json", "checkpoint_last.pth", "config.json", "edge_predictor_best.pth"}
SECONDARY_MEMBERS = {
    "ARTIFACT_MANIFEST.json",
    "SNAPSHOT_MANIFEST.json",
    "checkpoint_last.pth",
    "config.json",
    "edge_predictor_best.pth",
    "history.csv",
    "split_manifest.json",
    "training_config.json",
}
CLAIMS = {
    "inference_weight_identity_verified": True,
    "checkpoint_to_raw_causal_proof": False,
    "secondary_training_history_verified": True,
    "secondary_history_scope": HISTORY_SCOPE,
    "primary_training_history_verified": False,
    "generalization_verified": False,
    "training_gate_passed": False,
}
REMAINING_HOLDS = (
    "HOLD_CHECKPOINT_TO_RAW_CAUSAL_PROOF",
    "HOLD_PRIMARY_TRAINING_HISTORY_UNAVAILABLE",
    "HOLD_GENERALIZATION_UNVERIFIED",
    "HOLD_TRAINING_GATE_NOT_PASSED",
)
_HISTORY_HEADER = (
    "epoch",
    "recorded_at_utc",
    "edge_loss",
    "det_loss",
    "validation_loss",
    "validation_acc",
    "validation_recall",
    "validation_score",
    "best_score",
    "is_best",
    "train_seconds",
    "validation_seconds",
    "base_seed",
    "effective_seed",
    "fold",
)


def canonical_json_bytes(value: object) -> bytes:
    return _secure.canonical_json_bytes(value)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ref(pin: FilePin) -> dict[str, object]:
    return {"path": pin.relative, "bytes": pin.bytes, "sha256": pin.sha256}


def _strict_json(raw: bytes) -> Any:
    return _secure._strict_json_bytes(raw, canonical=False)


def _read_pin(root_fd: int, pin: FilePin, *, maximum: int | None = None) -> _secure.PinnedRead:
    if pin.bytes < 0 or not re.fullmatch(r"[0-9a-f]{64}", pin.sha256):
        raise CheckpointEvidenceError("invalid checkpoint evidence pin")
    item = _secure._read_repo_regular(root_fd, pin.relative, max_bytes=maximum or pin.bytes)
    if len(item.raw) != pin.bytes or _sha256(item.raw) != pin.sha256:
        raise CheckpointEvidenceError("checkpoint evidence byte pin drift")
    return item


def _directory_members(root_fd: int, relative: str, expected: set[str]) -> tuple[int, ...]:
    directory_fd = _secure._open_relative_directory(root_fd, relative)
    try:
        before = _secure._identity(os.fstat(directory_fd))
        names = os.listdir(directory_fd)
        if (
            len(names) != len(expected)
            or set(names) != expected
            or len({name.casefold() for name in names}) != len(names)
        ):
            raise CheckpointEvidenceError("checkpoint directory membership drift")
        for name in names:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CheckpointEvidenceError("checkpoint directory contains unsafe entry")
        after = _secure._identity(os.fstat(directory_fd))
        if before != after:
            raise CheckpointEvidenceError("checkpoint directory changed while listing")
        return after
    finally:
        os.close(directory_fd)


def _manifest_weight(value: object, digest: str) -> None:
    if type(value) is not dict:
        raise CheckpointEvidenceError("artifact manifest schema drift")
    for key in ("model", "models"):
        item = value.get(key)
        model = item if key == "model" else item.get("unet_transformer") if type(item) is dict else None
        if (
            type(model) is not dict
            or model.get("weight_bytes") != 8363159
            or model.get("weight_sha256") != digest
            or model.get("weight_path") != "weights/unet_transformer/split_0/edge_predictor_best.pth"
        ):
            raise CheckpointEvidenceError("artifact manifest inference-weight drift")


def _validate_snapshot(value: object, files: tuple[FilePin, ...]) -> None:
    if type(value) is not dict:
        raise CheckpointEvidenceError("snapshot manifest schema drift")
    if set(value) != {
        "base_seed",
        "best_epoch",
        "best_score",
        "captured_at_utc",
        "effective_seed",
        "epoch",
        "files",
        "fold",
        "method",
        "model_family",
        "schema_version",
        "source_live_directory",
        "split",
    }:
        raise CheckpointEvidenceError("snapshot manifest schema drift")
    expected = {Path(pin.relative).name: {"bytes": pin.bytes, "sha256": pin.sha256} for pin in files}
    if (
        value.get("schema_version") != 1
        or value.get("base_seed") != 314159
        or value.get("effective_seed") != 314159
        or value.get("fold") != 0
        or value.get("split") != 0
        or value.get("epoch") != 400
        or value.get("best_epoch") != 381
        or value.get("best_score") != 0.9779747766406395
        or value.get("method") != "unet_transformer_alltrain_seed314159_v1"
        or value.get("files") != expected
    ):
        raise CheckpointEvidenceError("snapshot manifest semantic drift")


def _float(text: str, label: str) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise CheckpointEvidenceError(f"invalid history {label}") from error
    if not math.isfinite(value):
        raise CheckpointEvidenceError(f"non-finite history {label}")
    return value


def _parse_history(raw: bytes) -> dict[str, object]:
    if b"\x00" in raw:
        raise CheckpointEvidenceError("NUL in history")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CheckpointEvidenceError("history is not UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if tuple(reader.fieldnames or ()) != _HISTORY_HEADER:
        raise CheckpointEvidenceError("history header drift")
    try:
        rows = list(reader)
    except csv.Error as error:
        raise CheckpointEvidenceError("malformed history CSV") from error
    if len(rows) != 400 or any(None in row or any(value in {None, ""} for value in row.values()) for row in rows):
        raise CheckpointEvidenceError("history row shape drift")
    running = -math.inf
    best_epoch = 0
    numeric = _HISTORY_HEADER[2:9] + _HISTORY_HEADER[10:12]
    for epoch, row in enumerate(rows, 1):
        try:
            parsed_epoch = int(row["epoch"])
            base_seed = int(row["base_seed"])
            effective_seed = int(row["effective_seed"])
            fold = int(row["fold"])
            is_best = int(row["is_best"])
        except ValueError as error:
            raise CheckpointEvidenceError("invalid integer history field") from error
        values = {name: _float(row[name], name) for name in numeric}
        improved = values["validation_score"] > running
        if (
            parsed_epoch != epoch
            or base_seed != 314159
            or effective_seed != 314159
            or fold != 0
            or is_best not in {0, 1}
            or not _secure._valid_utc(row["recorded_at_utc"])
        ):
            raise CheckpointEvidenceError("history epoch/seed/fold drift")
        if bool(is_best) != improved:
            raise CheckpointEvidenceError("history is_best semantics drift")
        if improved:
            running = values["validation_score"]
            best_epoch = epoch
        if values["best_score"] != running:
            raise CheckpointEvidenceError("history running-best semantics drift")
    if best_epoch != 381 or running != 0.9779747766406395:
        raise CheckpointEvidenceError("history best fact drift")
    first, final = rows[0], rows[-1]
    first_loss = {name: _float(first[name], name) for name in ("edge_loss", "det_loss", "validation_loss")}
    final_loss = {name: _float(final[name], name) for name in ("edge_loss", "det_loss", "validation_loss")}
    if first_loss != {
        "edge_loss": 0.003970155237044959,
        "det_loss": 0.019809366372963207,
        "validation_loss": 0.0003694080726243065,
    } or final_loss != {
        "edge_loss": 0.00015537457768152087,
        "det_loss": 0.0025127971824129127,
        "validation_loss": 0.00010980715391659644,
    }:
        raise CheckpointEvidenceError("history first/final loss fact drift")
    return {
        "epochs": {"first": 1, "last": 400, "count": 400, "no_gaps": True},
        "seed": {"base": 314159, "effective": 314159, "fold": 0},
        "best": {"epoch": 381, "score": running},
        "first_loss": first_loss,
        "final_loss": final_loss,
    }


def _parse_split(raw: bytes) -> dict[str, object]:
    value = _strict_json(raw)
    if (
        type(value) is not dict
        or value.get("base_seed") != 314159
        or value.get("effective_seed") != 314159
        or value.get("fold") != 0
    ):
        raise CheckpointEvidenceError("split manifest metadata drift")
    train, test = value.get("train"), value.get("test")
    if type(train) is not list or type(test) is not list or not all(type(item) is str for item in train + test):
        raise CheckpointEvidenceError("split manifest list drift")
    if len(train) != 199 or len(test) != 40 or len(set(train)) != 199 or len(set(test)) != 40:
        raise CheckpointEvidenceError("split manifest count drift")
    overlap = set(train) & set(test)
    if len(overlap) != 40 or overlap != set(test) or not all(item.startswith("44b6_") for item in test):
        raise CheckpointEvidenceError("split is not the exact in-sample 44b6 validation set")
    return {
        "train_datasets": 199,
        "validation_datasets": 40,
        "train_validation_overlap": 40,
        "validation_prefixes": ["44b6"],
        "in_sample": True,
    }


def _validate_runtime(raw: bytes) -> None:
    value = _strict_json(raw)
    if (
        type(value) is not dict
        or value.get("ground_truth_accessed") is not False
        or value.get("status") != "complete_label_free_runtime_integrity"
        or value.get("checkpoint_sha256", {}).get("primary") != PRIMARY_BEST_SHA256
        or value.get("checkpoint_sha256", {}).get("secondary") != SECONDARY_BEST_SHA256
    ):
        raise CheckpointEvidenceError("E22 runtime-integrity semantics drift")


@dataclass(frozen=True)
class Collected:
    git: GitState
    reads: tuple[tuple[str, _secure.PinnedRead], ...]
    history: dict[str, object]
    split: dict[str, object]


def _capture_git_state(root: Path, authority: Authority, guard: _secure.CheckoutGuard | None = None) -> GitState:
    return _secure._capture_git_state(root, authority, guard)


def _collect(root: Path, root_fd: int, authority: Authority, guard: _secure.CheckoutGuard) -> Collected:
    git_before = _capture_git_state(root, authority, guard)
    primary_identity = _directory_members(root_fd, authority.primary_root_relative, PRIMARY_MEMBERS)
    secondary_identity = _directory_members(root_fd, authority.secondary_root_relative, SECONDARY_MEMBERS)
    pins = (
        authority.runtime_integrity,
        authority.primary_manifest,
        authority.primary_config,
        authority.primary_best,
        authority.secondary_artifact_manifest,
        authority.secondary_snapshot_manifest,
        *authority.secondary_files,
    )
    first = tuple(
        (
            pin.relative,
            _read_pin(root_fd, pin, maximum=MAX_HISTORY_BYTES if pin.relative.endswith("history.csv") else pin.bytes),
        )
        for pin in pins
    )
    second = tuple(
        (
            pin.relative,
            _read_pin(root_fd, pin, maximum=MAX_HISTORY_BYTES if pin.relative.endswith("history.csv") else pin.bytes),
        )
        for pin in pins
    )
    if (
        first != second
        or primary_identity != _directory_members(root_fd, authority.primary_root_relative, PRIMARY_MEMBERS)
        or secondary_identity != _directory_members(root_fd, authority.secondary_root_relative, SECONDARY_MEMBERS)
    ):
        raise CheckpointEvidenceError("checkpoint authority changed during collection")
    by_path = dict(first)
    secondary_config = next(pin for pin in authority.secondary_files if pin.relative.endswith("secondary/config.json"))
    if by_path[authority.primary_config.relative].raw != by_path[secondary_config.relative].raw:
        raise CheckpointEvidenceError("restored primary/secondary config mismatch")
    _validate_runtime(by_path[authority.runtime_integrity.relative].raw)
    _manifest_weight(_strict_json(by_path[authority.primary_manifest.relative].raw), PRIMARY_BEST_SHA256)
    _manifest_weight(_strict_json(by_path[authority.secondary_artifact_manifest.relative].raw), SECONDARY_BEST_SHA256)
    _validate_snapshot(
        _strict_json(by_path[authority.secondary_snapshot_manifest.relative].raw), authority.secondary_files
    )
    history_pin = next(pin for pin in authority.secondary_files if pin.relative.endswith("history.csv"))
    split_pin = next(pin for pin in authority.secondary_files if pin.relative.endswith("split_manifest.json"))
    history = _parse_history(by_path[history_pin.relative].raw)
    split = _parse_split(by_path[split_pin.relative].raw)
    git_after = _capture_git_state(root, authority, guard)
    if git_before != git_after:
        raise CheckpointEvidenceError("checkout changed during collection")
    return Collected(git_before, first, history, split)


def _receipt(created_utc: str, collected: Collected, authority: Authority) -> dict[str, object]:
    secondary = {Path(pin.relative).name: _ref(pin) for pin in authority.secondary_files}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "created_utc": created_utc,
        "source": {
            "commit": collected.git.commit,
            "git_tree_oid": collected.git.tree,
            "official_gitlink": collected.git.official_oid,
        },
        "runtime_integrity": _ref(authority.runtime_integrity),
        "primary": {
            "artifact_manifest": _ref(authority.primary_manifest),
            "artifact_manifest_scope": "INFERENCE_BEST_ONLY",
            "config": _ref(authority.primary_config),
            "inference_weight": _ref(authority.primary_best),
            "checkpoint_last": {
                "loaded": False,
                "role": "EXCLUDED_UNPINNED_RESUME_SNAPSHOT",
                "exclusion_reasons": ["UNPINNED_BY_ARTIFACT_MANIFEST"],
            },
            "training_history": {"available": False},
        },
        "secondary": {
            "artifact_manifest": _ref(authority.secondary_artifact_manifest),
            "snapshot_manifest": _ref(authority.secondary_snapshot_manifest),
            "files": secondary,
            "inference_weight": _ref(
                next(pin for pin in authority.secondary_files if pin.relative.endswith("edge_predictor_best.pth"))
            ),
            "checkpoint_last_role": "TRAINING_RESUME_SNAPSHOT_NOT_INFERENCE_WEIGHT",
            "history": collected.history,
            "split": collected.split,
        },
        "claims": CLAIMS,
        "remaining_holds": list(REMAINING_HOLDS),
    }


def _validate_receipt(raw: bytes, collected: Collected, authority: Authority) -> dict[str, Any]:
    value = _secure._strict_json_bytes(raw, canonical=True)
    if value != _receipt(value.get("created_utc", "") if type(value) is dict else "", collected, authority):
        raise CheckpointEvidenceError("checkpoint receipt authority drift")
    if not _secure._valid_utc(value["created_utc"]):
        raise CheckpointEvidenceError("checkpoint receipt timestamp drift")
    return value


def _load_bundle(parent_fd: int, run_name: str) -> tuple[bytes, tuple[int, ...]]:
    run_fd = _secure._open_relative_directory(parent_fd, (run_name,))
    try:
        before = _secure._identity(os.fstat(run_fd))
        if stat.S_IMODE(before[2]) != 0o555 or os.listdir(run_fd) != [RECEIPT_NAME]:
            raise CheckpointEvidenceError("checkpoint receipt bundle membership or mode drift")
        item = _secure._read_named_regular(run_fd, RECEIPT_NAME, max_bytes=MAX_RECEIPT_BYTES)
        after = _secure._identity(os.fstat(run_fd))
        if before != after or stat.S_IMODE(item.identity[2]) != 0o444:
            raise CheckpointEvidenceError("checkpoint receipt bundle changed")
        return item.raw, after
    finally:
        os.close(run_fd)


def _assert_output_parent_rebound(
    root_fd: int,
    relative: str,
    parent_fd: int,
    expected_identity: tuple[int, ...],
) -> None:
    """Bind the held output parent back to its canonical checkout pathname."""
    if _secure._directory_handle_identity(os.fstat(parent_fd)) != expected_identity:
        raise CheckpointEvidenceError("held output parent identity drift")
    fresh_fd = _secure._open_relative_directory(root_fd, relative)
    try:
        fresh_identity = _secure._directory_handle_identity(os.fstat(fresh_fd))
        if fresh_identity != expected_identity or fresh_identity != _secure._directory_handle_identity(
            os.fstat(parent_fd)
        ):
            raise CheckpointEvidenceError("canonical output parent pathname displacement")
    finally:
        os.close(fresh_fd)


def _validate_owned_bundle(
    parent_fd: int,
    name: str,
    owned: _secure._OwnedStaging,
    expected_raw: bytes,
) -> tuple[int, ...]:
    """Re-open a staged or final bundle and validate ownership, mode, and all bytes."""
    if not _secure._owned_name(parent_fd, name, owned.identity):
        raise CheckpointEvidenceError("owned checkpoint bundle pathname identity drift")
    directory_fd = _secure._open_relative_directory(parent_fd, (name,))
    try:
        before = _secure._identity(os.fstat(directory_fd))
        path_before = _secure._identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
        names = os.listdir(directory_fd)
        if (
            _secure._ownership(os.fstat(directory_fd)) != owned.identity
            or before != path_before
            or stat.S_IMODE(before[2]) != 0o555
            or set(names) != {RECEIPT_NAME}
            or len(names) != 1
        ):
            raise CheckpointEvidenceError("owned checkpoint bundle identity or membership drift")
        expected_files = dict(owned.files)
        if set(expected_files) != {RECEIPT_NAME}:
            raise CheckpointEvidenceError("owned checkpoint bundle record drift")
        path_info = os.stat(RECEIPT_NAME, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(path_info.st_mode)
            or path_info.st_nlink != 1
            or _secure._ownership(path_info) != expected_files[RECEIPT_NAME]
        ):
            raise CheckpointEvidenceError("owned checkpoint receipt inode drift")
        item = _secure._read_named_regular(directory_fd, RECEIPT_NAME, max_bytes=MAX_RECEIPT_BYTES)
        after = _secure._identity(os.fstat(directory_fd))
        path_after = _secure._identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
        if (
            item.raw != expected_raw
            or stat.S_IMODE(item.identity[2]) != 0o444
            or before != after
            or after != path_after
        ):
            raise CheckpointEvidenceError("owned checkpoint bundle bytes or identity drift")
        return after
    finally:
        os.close(directory_fd)


def _publish_verified(
    root: Path,
    guard: _secure.CheckoutGuard,
    parent_fd: int,
    parent_identity: tuple[int, ...],
    final_name: str,
    owned: _secure._OwnedStaging,
    expected_raw: bytes,
    authority: Authority,
) -> str:
    """Publish once, then prove the canonical final name owns the exact bundle."""
    renamed = False
    try:
        _secure._assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        _validate_owned_bundle(parent_fd, owned.name, owned, expected_raw)
        primitive = _secure._rename_noreplace(parent_fd, owned.name, final_name)
        renamed = True
        os.fsync(parent_fd)
        _secure._assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        if _secure._name_info(parent_fd, owned.name) is not None:
            raise CheckpointEvidenceError("staging name remained after publication")
        _validate_owned_bundle(parent_fd, final_name, owned, expected_raw)
        _secure._assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        return primitive
    except BaseException as original:
        try:
            staging_owned = _secure._owned_name(parent_fd, owned.name, owned.identity)
            final_owned = _secure._owned_name(parent_fd, final_name, owned.identity)
            if final_owned and not staging_owned:
                _secure._rollback_publication(parent_fd, final_name, owned.name, owned)
            elif staging_owned and not final_owned:
                _secure._cleanup_owned(parent_fd, owned.name, owned)
            else:
                raise CheckpointPublicationAmbiguityError("checkpoint publication outcome has ambiguous ownership")
        except BaseException as recovery:
            raise CheckpointPublicationAmbiguityError(
                "checkpoint publication and recovery could not both be proven"
            ) from BaseExceptionGroup("publication and recovery failed", [original, recovery])
        if renamed:
            raise CheckpointEvidenceError(
                "checkpoint publication failed validation and was durably rolled back"
            ) from original
        raise


def _result(root: Path, run: Path, collected: Collected, raw: bytes) -> dict[str, object]:
    return {
        "status": STATUS,
        "remaining_holds": list(REMAINING_HOLDS),
        "source": {
            "commit": collected.git.commit,
            "git_tree_oid": collected.git.tree,
            "official_gitlink": collected.git.official_oid,
        },
        "receipt": {
            "path": (run / RECEIPT_NAME).relative_to(root).as_posix(),
            "bytes": len(raw),
            "sha256": _sha256(raw),
        },
    }


def _prepare(root: Path, run_dir: Path, authority: Authority) -> tuple[Path, str]:
    return _secure._constrain_run_dir(root, run_dir, authority)


def _build(root: Path, run_dir: Path, authority: Authority) -> dict[str, object]:
    guard = _secure._validate_checkout(root)
    parent_fd: int | None = None
    owned: _secure._OwnedStaging | None = None
    publication_attempted = False
    published = False
    try:
        run, run_name = _prepare(root, run_dir, authority)
        collected = _collect(root, guard.root_fd, authority, guard)
        parent_fd = _secure._ensure_output_parent(guard.root_fd, authority.output_parent_relative)
        parent_identity = _secure._directory_handle_identity(os.fstat(parent_fd))
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        if any(name.casefold() == run_name.casefold() for name in os.listdir(parent_fd)):
            raise FileExistsError(run_name)
        staging_name = f".staging.{run_name}.{secrets.token_hex(8)}"
        staging_fd, owned = _secure._create_owned_staging(parent_fd, staging_name)
        try:
            raw = canonical_json_bytes(_receipt(_secure._utc_now(), collected, authority))
            file_identity = _secure._write_new_regular(staging_fd, RECEIPT_NAME, raw)
            owned = _secure._OwnedStaging(owned.name, owned.identity, ((RECEIPT_NAME, file_identity),))
            os.fsync(staging_fd)
            os.fchmod(staging_fd, 0o555)
            os.fsync(staging_fd)
        finally:
            os.close(staging_fd)
        staged, bundle_identity = _load_bundle(parent_fd, staging_name)
        _validate_receipt(staged, collected, authority)
        if staged != raw or bundle_identity != _secure._identity(
            os.stat(staging_name, dir_fd=parent_fd, follow_symlinks=False)
        ):
            raise CheckpointEvidenceError("staged checkpoint receipt drift")
        collected_after = _collect(root, guard.root_fd, authority, guard)
        if collected != collected_after:
            raise CheckpointEvidenceError("authority changed before publication")
        _validate_owned_bundle(parent_fd, staging_name, owned, raw)
        _secure._assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        result = _result(root, run, collected, raw)
        publication_attempted = True
        _publish_verified(
            root,
            guard,
            parent_fd,
            parent_identity,
            run_name,
            owned,
            raw,
            authority,
        )
        published = True
        return result
    except BaseException as original:
        if owned is not None and not published and not publication_attempted and parent_fd is not None:
            try:
                _secure._cleanup_owned(parent_fd, owned.name, owned)
            except BaseException as cleanup:
                raise CheckpointPublicationAmbiguityError(
                    "checkpoint evidence rollback failed"
                ) from BaseExceptionGroup("construction and rollback failed", [original, cleanup])
        raise
    finally:
        if parent_fd is not None:
            with contextlib.suppress(OSError):
                os.close(parent_fd)
        if guard is not None:
            guard.close()


def _verify(root: Path, run_dir: Path, authority: Authority) -> dict[str, object]:
    guard = _secure._validate_checkout(root)
    parent_fd: int | None = None
    try:
        run, run_name = _prepare(root, run_dir, authority)
        parent_fd = _secure._open_relative_directory(guard.root_fd, authority.output_parent_relative)
        parent_identity = _secure._directory_handle_identity(os.fstat(parent_fd))
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        before, identity_before = _load_bundle(parent_fd, run_name)
        collected = _collect(root, guard.root_fd, authority, guard)
        _validate_receipt(before, collected, authority)
        after, identity_after = _load_bundle(parent_fd, run_name)
        if before != after or identity_before != identity_after:
            raise CheckpointEvidenceError("checkpoint receipt changed during verification")
        _secure._assert_checkout_rebound(root, guard)
        _assert_output_parent_rebound(guard.root_fd, authority.output_parent_relative, parent_fd, parent_identity)
        return _result(root, run, collected, before)
    finally:
        try:
            if parent_fd is not None:
                os.close(parent_fd)
        finally:
            guard.close()


def build_checkpoint_evidence(run_dir: Path) -> dict[str, object]:
    """Atomically publish a fresh checkpoint-evidence receipt."""
    return _build(Path(os.path.abspath(CANONICAL_REPO_ROOT)), run_dir, PRODUCTION_AUTHORITY)


def verify_checkpoint_evidence(run_dir: Path) -> dict[str, object]:
    """Re-open and fully revalidate a checkpoint-evidence receipt."""
    return _verify(Path(os.path.abspath(CANONICAL_REPO_ROOT)), run_dir, PRODUCTION_AUTHORITY)


__all__ = [
    "CANONICAL_REPO_ROOT",
    "CLAIMS",
    "CheckpointEvidenceError",
    "CheckpointPublicationAmbiguityError",
    "FilePin",
    "HISTORY_SCOPE",
    "PRODUCTION_AUTHORITY",
    "PublicationAmbiguityError",
    "RECEIPT_NAME",
    "REMAINING_HOLDS",
    "SCHEMA_VERSION",
    "STATUS",
    "build_checkpoint_evidence",
    "canonical_json_bytes",
    "verify_checkpoint_evidence",
]
