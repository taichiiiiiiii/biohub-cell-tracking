#!/usr/bin/env python3
"""Verify and stage the immutable external 0.933 reproduction source.

This command is deliberately offline.  It never invokes Kaggle, runs the
notebook, or submits a prediction.  A successful result only means that the
locally archived public provenance and the staged notebook package match the
pinned bytes and executable AST.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class ReplayPreparationError(ValueError):
    """The archived source or requested staging target is not trustworthy."""


@dataclass(frozen=True)
class ReplaySpec:
    reference_manifest_sha256: str
    notebook_name: str
    notebook_sha256: str
    canonical_ast_sha256: str
    ast_python_major_minor: tuple[int, int]
    code_cells: int
    view_model_name: str
    view_model_sha256: str
    source_kernel_ref: str
    source_kernel_version: int
    source_session_id: int
    source_submission_id: int
    source_score: str
    data_source_tuples: tuple[tuple[int, int | None, str], ...]


PINNED_REFERENCE_RELATIVE = Path("outputs/kaggle/external_933_reference")
PINNED_SPEC = ReplaySpec(
    reference_manifest_sha256="37886a0fd659cd71300ae442c7f35dc1912f1d9a5ba0dd9f80bc3975a06eb43e",
    notebook_name="rishabh_v4_latest_pull_ast_equivalent.ipynb",
    notebook_sha256="c7cdda0acf9dc704865165feae06d933fc85748dd4d8e9454734b91a65f0eb10",
    canonical_ast_sha256="0d1809e9e71ec410664ade0204b1a17896dc95954a721ea0bc46773f6fbb221d",
    ast_python_major_minor=(3, 14),
    code_cells=10,
    view_model_name="rishabh_v2_public_view_model.json",
    view_model_sha256="cb224d82c51b5a5549a153fb6901596f7b6099bbcbc248255daacaa8e63eefdb",
    source_kernel_ref="rishabhr0y/933-biohub-bidir30",
    source_kernel_version=2,
    source_session_id=345883663,
    source_submission_id=55877457,
    source_score="0.933",
    data_source_tuples=(
        (136605, 18327164, "competitions/biohub-cell-tracking-during-development"),
        (17751825, None, "datasets/pilkwang/biohub-deepcenter-unet3d-center-prior-v1"),
        (17804310, None, "datasets/pilkwang/biohub-tracking-support-pack-50ep-v1"),
        (18187037, None, "datasets/pilkwang/biohub-temporal-unet3d-seed314159-v1"),
    ),
)


def _reject_constant(token: str) -> None:
    raise ReplayPreparationError(f"non-finite JSON token is forbidden: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayPreparationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def strict_json_bytes(payload: bytes, source: str) -> Any:
    try:
        text = payload.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayPreparationError(f"invalid JSON in {source}: {exc}") from exc
    _require_finite(value, source)
    return value


def _require_finite(value: Any, source: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ReplayPreparationError(f"non-finite value in {source}")
    if isinstance(value, dict):
        for child in value.values():
            _require_finite(child, source)
    elif isinstance(value, list):
        for child in value:
            _require_finite(child, source)


def canonical_json_bytes(value: Any) -> bytes:
    _require_finite(value, "canonical JSON")
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file_no_symlink(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReplayPreparationError(f"cannot inspect {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ReplayPreparationError(f"expected a regular non-symlink file: {path}")


def _safe_filename(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayPreparationError("manifest filename must be a nonempty string")
    pure = PurePosixPath(value)
    if pure.is_absolute() or len(pure.parts) != 1 or pure.name != value or value in {".", ".."}:
        raise ReplayPreparationError(f"unsafe manifest filename: {value!r}")
    return value


def canonical_ast_sha256(notebook: dict[str, Any]) -> tuple[str, int]:
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise ReplayPreparationError("notebook cells must be an array")
    dumps: list[bytes] = []
    count = 0
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source")
        if isinstance(source, list) and all(isinstance(item, str) for item in source):
            text = "".join(source)
        elif isinstance(source, str):
            text = source
        else:
            raise ReplayPreparationError("code-cell source must be a string or string array")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            raise ReplayPreparationError(f"notebook code cell is not valid Python: {exc}") from exc
        dumps.append(ast.dump(tree, include_attributes=False).encode("utf-8"))
        count += 1
    return sha256_bytes(b"\0".join(dumps)), count


def canonical_ast_with_interpreter(notebook_path: Path, interpreter: Path) -> tuple[str, int, dict[str, Any]]:
    """Recompute the version-sensitive provenance AST with a pinned-version Python."""
    interpreter = interpreter.absolute()
    _regular_file_no_symlink(interpreter.resolve())
    program = (
        "import ast,hashlib,json,pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);n=json.loads(p.read_text(encoding='utf-8'));"
        "cells=[''.join(c['source']) if isinstance(c['source'],list) else c['source'] "
        "for c in n['cells'] if c.get('cell_type')=='code'];"
        "payload=b'\\0'.join(ast.dump(ast.parse(c),include_attributes=False).encode('utf-8') for c in cells);"
        "print(json.dumps({'sha256':hashlib.sha256(payload).hexdigest(),'cells':len(cells),"
        "'version':[sys.version_info.major,sys.version_info.minor,sys.version_info.micro]},"
        "sort_keys=True,separators=(',',':')))"
    )
    try:
        completed = subprocess.run(
            [str(interpreter), "-I", "-c", program, str(notebook_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReplayPreparationError(f"cannot run AST interpreter: {exc}") from exc
    if completed.returncode != 0 or completed.stderr or not completed.stdout.endswith("\n"):
        raise ReplayPreparationError("AST interpreter did not return one clean result")
    value = strict_json_bytes(completed.stdout.encode(), "AST interpreter stdout")
    if not isinstance(value, dict):
        raise ReplayPreparationError("AST interpreter result must be an object")
    version = value.get("version")
    digest = value.get("sha256")
    count = value.get("cells")
    if (
        not isinstance(version, list)
        or len(version) != 3
        or any(not isinstance(part, int) or isinstance(part, bool) for part in version)
        or not isinstance(digest, str)
        or len(digest) != 64
        or not isinstance(count, int)
        or isinstance(count, bool)
    ):
        raise ReplayPreparationError("AST interpreter result schema is invalid")
    resolved = interpreter.resolve()
    return (
        digest,
        count,
        {
            "path": str(resolved),
            "sha256": sha256_file(resolved),
            "version": version,
        },
    )


def _data_source_tuple(item: Any) -> tuple[int, int | None, str]:
    if not isinstance(item, dict):
        raise ReplayPreparationError("view-model data source must be an object")
    source_id = item.get("sourceId")
    version_id = item.get("databundleVersionId")
    mount = item.get("mountSlug")
    if not isinstance(source_id, int) or isinstance(source_id, bool):
        raise ReplayPreparationError("view-model sourceId must be an integer")
    if version_id is not None and (not isinstance(version_id, int) or isinstance(version_id, bool)):
        raise ReplayPreparationError("view-model databundleVersionId must be null or integer")
    if not isinstance(mount, str) or not mount:
        raise ReplayPreparationError("view-model mountSlug must be a nonempty string")
    return source_id, version_id, mount


def verify_reference(
    reference_dir: Path,
    spec: ReplaySpec = PINNED_SPEC,
    *,
    ast_python: Path | None = None,
) -> dict[str, Any]:
    reference_dir = reference_dir.absolute()
    if reference_dir.is_symlink() or not reference_dir.is_dir():
        raise ReplayPreparationError(f"reference directory is missing or a symlink: {reference_dir}")
    manifest_path = reference_dir / "ARTIFACT_MANIFEST.json"
    _regular_file_no_symlink(manifest_path)
    if sha256_file(manifest_path) != spec.reference_manifest_sha256:
        raise ReplayPreparationError("reference manifest SHA256 mismatch")
    manifest = strict_json_bytes(manifest_path.read_bytes(), str(manifest_path))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ReplayPreparationError("reference manifest schema is invalid")

    declared: dict[str, dict[str, Any]] = {}
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise ReplayPreparationError("reference file entry must be an object")
        name = _safe_filename(entry.get("filename"))
        if name in declared:
            raise ReplayPreparationError(f"duplicate reference filename: {name}")
        path = reference_dir / name
        _regular_file_no_symlink(path)
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ReplayPreparationError(f"invalid byte count for {name}")
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise ReplayPreparationError(f"reference file identity mismatch: {name}")
        declared[name] = entry
    actual = {path.name for path in reference_dir.iterdir() if path.name != "ARTIFACT_MANIFEST.json"}
    if actual != set(declared):
        raise ReplayPreparationError(
            f"reference file set mismatch: missing={sorted(set(declared) - actual)} "
            f"extra={sorted(actual - set(declared))}"
        )

    notebook_path = reference_dir / spec.notebook_name
    view_path = reference_dir / spec.view_model_name
    if declared.get(spec.notebook_name, {}).get("sha256") != spec.notebook_sha256:
        raise ReplayPreparationError("notebook is not pinned by the reference manifest")
    if declared.get(spec.view_model_name, {}).get("sha256") != spec.view_model_sha256:
        raise ReplayPreparationError("view model is not pinned by the reference manifest")
    if sha256_file(notebook_path) != spec.notebook_sha256 or sha256_file(view_path) != spec.view_model_sha256:
        raise ReplayPreparationError("pinned replay source bytes drifted")

    notebook = strict_json_bytes(notebook_path.read_bytes(), str(notebook_path))
    if not isinstance(notebook, dict):
        raise ReplayPreparationError("notebook root must be an object")
    if ast_python is None:
        ast_python = Path(sys.executable)
    ast_digest, cell_count, ast_runtime = canonical_ast_with_interpreter(notebook_path, ast_python)
    if tuple(ast_runtime["version"][:2]) != spec.ast_python_major_minor:
        raise ReplayPreparationError(
            f"AST interpreter version mismatch: expected {spec.ast_python_major_minor}, "
            f"got {tuple(ast_runtime['version'][:2])}"
        )
    if ast_digest != spec.canonical_ast_sha256 or cell_count != spec.code_cells:
        raise ReplayPreparationError("notebook executable AST or code-cell count mismatch")

    view = strict_json_bytes(view_path.read_bytes(), str(view_path))
    if not isinstance(view, dict):
        raise ReplayPreparationError("view-model root must be an object")
    run = view.get("kernelRun")
    submission = view.get("submission")
    kernel = view.get("kernel")
    if not all(isinstance(item, dict) for item in (run, submission, kernel)):
        raise ReplayPreparationError("view-model kernel/run/submission binding is incomplete")
    if (
        kernel.get("url") != f"/code/{spec.source_kernel_ref}"
        or run.get("kernelVersionNumber") != spec.source_kernel_version
        or run.get("id") != spec.source_session_id
        or run.get("status") != "COMPLETE"
        or submission.get("id") != spec.source_submission_id
        or submission.get("sourceScriptVersionId") != spec.source_session_id
        or submission.get("scoreFormatted") != spec.source_score
    ):
        raise ReplayPreparationError("view-model immutable run/submission/score binding mismatch")
    sources = run.get("dataSources")
    if not isinstance(sources, list) or tuple(_data_source_tuple(item) for item in sources) != spec.data_source_tuples:
        raise ReplayPreparationError("view-model data-source identity/order mismatch")

    return {
        "schema_version": "biohub.external_933_reference_verification.v1",
        "status": "VERIFIED_SOURCE_ONLY",
        "reference_manifest_sha256": spec.reference_manifest_sha256,
        "notebook_sha256": spec.notebook_sha256,
        "canonical_ast_sha256": ast_digest,
        "ast_runtime": ast_runtime,
        "code_cells": cell_count,
        "source_kernel_ref": spec.source_kernel_ref,
        "source_kernel_version": spec.source_kernel_version,
        "source_session_id": spec.source_session_id,
        "source_submission_id": spec.source_submission_id,
        "source_public_score": spec.source_score,
        "data_sources": [list(item) for item in spec.data_source_tuples],
        "claims": {
            "hidden_submission_bytes_available": False,
            "account_replay_executed": False,
            "account_score_observed": False,
            "kernel_metadata_dataset_versions_resolved": False,
        },
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_kernel_id(kernel_id: str) -> None:
    parts = kernel_id.split("/")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if len(parts) != 2 or any(not part or any(char not in allowed for char in part) for part in parts):
        raise ReplayPreparationError("kernel id must be lowercase owner/slug")


def stage_replay(
    reference_dir: Path,
    output_dir: Path,
    *,
    allowed_root: Path,
    kernel_id: str,
    spec: ReplaySpec = PINNED_SPEC,
    ast_python: Path | None = None,
) -> dict[str, Any]:
    verification = verify_reference(reference_dir, spec, ast_python=ast_python)
    _validate_kernel_id(kernel_id)
    allowed_root = allowed_root.absolute()
    allowed_root.mkdir(parents=True, exist_ok=True)
    if allowed_root.is_symlink() or not allowed_root.is_dir():
        raise ReplayPreparationError("allowed staging root must be a real directory")
    output_dir = output_dir.absolute()
    if output_dir == allowed_root or not output_dir.is_relative_to(allowed_root):
        raise ReplayPreparationError("output directory must be a child of the pinned staging root")
    if output_dir.exists() or output_dir.is_symlink():
        raise ReplayPreparationError(f"refusing to reuse staging directory: {output_dir}")

    output_dir.mkdir(mode=0o700)
    package_dir = output_dir / "package"
    package_dir.mkdir(mode=0o700)
    marker = output_dir / "INCOMPLETE"
    _write_exclusive(marker, b"staging\n")
    try:
        notebook_name = "external_933_replay.ipynb"
        notebook_payload = (reference_dir / spec.notebook_name).read_bytes()
        notebook_out = package_dir / notebook_name
        _write_exclusive(notebook_out, notebook_payload)
        metadata = {
            "id": kernel_id,
            "title": "biohub external 0.933 immutable replay",
            "code_file": notebook_name,
            "language": "python",
            "kernel_type": "notebook",
            "is_private": "true",
            "enable_gpu": "true",
            "enable_tpu": "false",
            "enable_internet": "false",
            "machine_shape": "NvidiaTeslaT4",
            "competition_sources": ["biohub-cell-tracking-during-development"],
            "dataset_sources": [
                "pilkwang/biohub-deepcenter-unet3d-center-prior-v1",
                "pilkwang/biohub-tracking-support-pack-50ep-v1",
                "pilkwang/biohub-temporal-unet3d-seed314159-v1",
            ],
            "kernel_sources": [],
            "model_sources": [],
        }
        metadata_out = package_dir / "kernel-metadata.json"
        _write_exclusive(metadata_out, canonical_json_bytes(metadata))
        receipt = {
            **verification,
            "schema_version": "biohub.external_933_replay_staging.v1",
            "status": "STAGED_NOT_AUTHORIZED_TO_PUSH",
            "kernel_id": kernel_id,
            "package": {
                notebook_name: {
                    "bytes": notebook_out.stat().st_size,
                    "sha256": sha256_file(notebook_out),
                },
                "kernel-metadata.json": {
                    "bytes": metadata_out.stat().st_size,
                    "sha256": sha256_file(metadata_out),
                },
            },
            "required_before_push": [
                "Kaggle HTTP 429 not-before has elapsed and fresh preflight passes",
                "each dataset slug resolves to the pinned source version ID",
                "source reuse/license and attribution review is recorded",
                "operator confirms this is portability replay, not a new 0.933 claim",
            ],
            "allowed_next_action": "OFFLINE_REVIEW_ONLY",
        }
        receipt_path = output_dir / "REPLAY_RECEIPT.json"
        _write_exclusive(receipt_path, canonical_json_bytes(receipt))
        os.unlink(marker)
        ready = {
            "schema_version": "biohub.external_933_replay_ready.v1",
            "receipt_sha256": sha256_file(receipt_path),
            "package_notebook_sha256": sha256_file(notebook_out),
            "allowed_next_action": "OFFLINE_REVIEW_ONLY",
        }
        _write_exclusive(output_dir / "READY.json", canonical_json_bytes(ready))
        _fsync_directory(package_dir)
        _fsync_directory(output_dir)
        _fsync_directory(allowed_root)
        return receipt
    except BaseException:
        # Preserve the claimed directory and INCOMPLETE marker as failure evidence.
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--kernel-id", default="taichiiiii/biohub-external-933-replay")
    parser.add_argument(
        "--ast-python",
        type=Path,
        default=Path(shutil.which("python3") or sys.executable),
        help="Python interpreter matching the pinned AST provenance version",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.absolute()
    reference_dir = repo_root / PINNED_REFERENCE_RELATIVE
    allowed_root = repo_root / "outputs/local/external_933_replay"
    try:
        if args.verify_only:
            result = verify_reference(reference_dir, ast_python=args.ast_python)
        else:
            if args.output_dir is None:
                raise ReplayPreparationError("--output-dir is required unless --verify-only is used")
            result = stage_replay(
                reference_dir,
                args.output_dir,
                allowed_root=allowed_root,
                kernel_id=args.kernel_id,
                ast_python=args.ast_python,
            )
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except (OSError, ReplayPreparationError, ValueError, TypeError) as exc:
        failure = {
            "schema_version": "biohub.external_933_replay_failure.v1",
            "status": "FAIL",
            "error": str(exc),
        }
        sys.stdout.buffer.write(canonical_json_bytes(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
