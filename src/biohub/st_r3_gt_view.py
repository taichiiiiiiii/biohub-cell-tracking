"""Sealed, opaque-byte EVAL36 ground-truth view for ST-R3.

Only the fixed ``data/train`` authority is addressable.  GEFF and the two
scoring-relevant Zarr metadata files are cloned with ``fclonefileat``; this
module never interprets ground-truth JSON or array payloads.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from biohub import st_r3_image_view as _sealed

CANONICAL_REPO_ROOT = Path("/Users/taichi/コンペティション/Kaggle/biohub-cell-tracking")
SOURCE_RELATIVE = "data/train"
STANDALONE_PARENT_RELATIVE = "outputs/local/st_r3_gt_views"
RUN_PARENT_RELATIVE = "outputs/local/steal_twin"
INVENTORY_SCHEMA = "biohub.st_r3.gt_view_inventory.v1"
RECEIPT_SCHEMA = "biohub.st_r3.gt_view_receipt.v1"
IMPORT_INVENTORY_SCHEMA = "biohub.st_r3.gt_inventory.v1"
IMPORT_RECEIPT_SCHEMA = "biohub.st_r3.gt_view_import_receipt.v1"
GENERATION_SCHEMA = "biohub.st_r3.generation_manifest.v1"
OFFICIAL_OID = "075fc5f5a52d11077f9dc2b074644618f26939e2"
MAX_JSON_BYTES = 16 * 1024 * 1024

EVAL36 = _sealed.EVAL36_STEMS
GEFF_SUFFIXES = (
    "edges/ids/c/0/0",
    "edges/ids/zarr.json",
    "edges/props/zarr.json",
    "edges/zarr.json",
    "nodes/ids/c/0",
    "nodes/ids/zarr.json",
    "nodes/props/t/values/c/0",
    "nodes/props/t/values/zarr.json",
    "nodes/props/t/zarr.json",
    "nodes/props/x/values/c/0",
    "nodes/props/x/values/zarr.json",
    "nodes/props/x/zarr.json",
    "nodes/props/y/values/c/0",
    "nodes/props/y/values/zarr.json",
    "nodes/props/y/zarr.json",
    "nodes/props/z/values/c/0",
    "nodes/props/z/values/zarr.json",
    "nodes/props/z/zarr.json",
    "nodes/props/zarr.json",
    "nodes/zarr.json",
    "zarr.json",
)
ZARR_SUFFIXES = ("0/zarr.json", "zarr.json")
BUILDER_SOURCES = (
    "src/biohub/st_r3_gt_view.py",
    "scripts/experiments/st_r3/st_r3_gt_view.py",
    "src/biohub/st_r3_image_view.py",
)

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+@-]{0,127}\Z")


class GTViewError(RuntimeError):
    """The requested GT view operation failed closed."""


class PublicationAmbiguityError(GTViewError):
    """Publication or durable rollback could not be established."""


@dataclass(frozen=True)
class Authority:
    root: Path = CANONICAL_REPO_ROOT
    stems: tuple[str, ...] = EVAL36
    geff_suffixes: tuple[str, ...] = GEFF_SUFFIXES
    zarr_suffixes: tuple[str, ...] = ZARR_SUFFIXES
    source_relative: str = SOURCE_RELATIVE
    standalone_parent_relative: str = STANDALONE_PARENT_RELATIVE
    run_parent_relative: str = RUN_PARENT_RELATIVE
    official_oid: str = OFFICIAL_OID
    builder_sources: tuple[str, ...] = BUILDER_SOURCES


PRODUCTION_AUTHORITY = Authority()


@dataclass(frozen=True)
class BuildResult:
    status: str
    run_id: str
    gt_view: str
    inventory_sha256: str
    receipt_sha256: str
    files: int
    bytes: int


@dataclass(frozen=True)
class VerifyResult:
    status: str
    run_id: str
    receipt_sha256: str
    files: int
    bytes: int


@dataclass(frozen=True)
class ImportResult:
    status: str
    run_id: str
    gt_view: str
    inventory_sha256: str
    receipt_sha256: str
    files: int
    bytes: int


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise GTViewError(f"invalid {label}")
    return value


def _require_run_id(value: str) -> str:
    if type(value) is not str or _RUN_RE.fullmatch(value) is None:
        raise GTViewError("invalid run_id")
    return value


def _safe_relative(value: object) -> str:
    try:
        result = _sealed._safe_relative(value)
    except _sealed.ImageViewError as exc:
        raise GTViewError("unsafe path") from exc
    if any(ord(character) < 32 or ord(character) == 127 for character in result):
        raise GTViewError("control character in path")
    return result


def _strict_json(raw: bytes, label: str) -> dict[str, object]:
    try:
        value = _sealed._strict_json_bytes(raw)
    except _sealed.ImageViewError as exc:
        raise GTViewError(f"invalid {label}") from exc
    if type(value) is not dict:
        raise GTViewError(f"{label} must be an object")
    return value


def _read(root_fd: int, relative: str) -> tuple[bytes, os.stat_result]:
    try:
        return _sealed._read_relative_regular(root_fd, relative, max_bytes=MAX_JSON_BYTES)
    except _sealed.ImageViewError as exc:
        raise GTViewError(f"cannot safely read {relative}") from exc


def _audit_inherited_fds() -> None:
    fd_root = Path("/dev/fd")
    if not fd_root.is_dir():
        raise GTViewError("inherited descriptor audit unavailable")
    for entry in fd_root.iterdir():
        try:
            number = int(entry.name)
        except ValueError:
            continue
        if number <= 2:
            continue
        try:
            target = os.readlink(entry).casefold()
        except OSError:
            continue
        if "/data/train/" in target or ".geff/" in target or "/inputs/gt/" in target:
            raise GTViewError("inherited sensitive descriptor")


def _checkout(authority: Authority) -> tuple[_sealed.CheckoutGuard, _sealed.GitState, tuple[dict[str, object], ...]]:
    guard: _sealed.CheckoutGuard | None = None
    try:
        guard = _sealed._validate_checkout(authority.root)
        git_authority = _sealed.Authority(
            stems=authority.stems,
            file_suffixes=(),
            files_per_root=0,
            stored_bytes=0,
            source_relative=authority.source_relative,
            output_parent_relative=authority.standalone_parent_relative,
            ready_relative="unused",
            ready_sha256="0" * 64,
            ready_content_sha256="0" * 64,
            inventory_sha256="0" * 64,
            import_receipt_relative="unused",
            import_receipt_sha256="0" * 64,
            official_oid=authority.official_oid,
            builder_sources=authority.builder_sources,
        )
        git = _sealed._capture_git_state(authority.root, git_authority, guard)
        _validate_superproject_all(authority.root, guard.root_fd, authority.official_oid)
        bindings = tuple(
            {"path": path, "bytes": len(raw), "sha256": _sha(raw)}
            for path in authority.builder_sources
            for raw, _info in [_read(guard.root_fd, path)]
        )
        return guard, git, bindings
    except BaseException as exc:
        if guard is not None:
            guard.close()
        if isinstance(exc, _sealed.ImageViewError):
            raise GTViewError(str(exc)) from exc
        raise


def _validate_superproject_all(root: Path, root_fd: int, official_oid: str) -> None:
    """Hash every tracked HEAD/index/worktree entry, including index flags."""
    try:
        head = _sealed._parse_official_head(_sealed._run_git(root, "ls-tree", "-rz", "--full-tree", "HEAD"))
        index = _sealed._parse_official_index(_sealed._run_git(root, "ls-files", "-z", "--stage", "-v"))
        if head != index:
            raise GTViewError("superproject HEAD/index drift")
        for mode, kind, oid, relative in head:
            if mode == "160000":
                if relative != "official" or kind != "commit" or oid != official_oid:
                    raise GTViewError("unexpected superproject gitlink")
                continue
            expected = _sealed._run_git(root, "cat-file", "blob", oid)
            if _sealed._git_blob_oid(expected) != oid:
                raise GTViewError("tracked blob OID drift")
            if mode == "120000":
                observed, info = _sealed._read_relative_symlink(root_fd, relative)
                if not stat.S_ISLNK(info.st_mode):
                    raise GTViewError("tracked symlink mode drift")
            else:
                observed, info = _sealed._read_relative_regular(root_fd, relative)
                expected_mode = 0o755 if mode == "100755" else 0o644
                if stat.S_IMODE(info.st_mode) != expected_mode:
                    raise GTViewError("tracked worktree mode drift")
            if observed != expected:
                raise GTViewError("tracked worktree bytes drift")
    except _sealed.ImageViewError as exc:
        raise GTViewError("full superproject binding failed") from exc


def _rebind(authority: Authority, guard: _sealed.CheckoutGuard) -> None:
    try:
        _sealed._assert_checkout_rebound(authority.root, guard)
    except _sealed.ImageViewError as exc:
        raise GTViewError("checkout binding drift") from exc


def _rebind_directory(root_fd: int, relative: str, held_fd: int) -> None:
    try:
        fresh = _sealed._open_relative_directory(root_fd, relative)
    except (OSError, _sealed.ImageViewError) as exc:
        raise GTViewError(f"directory pathname drift: {relative}") from exc
    try:
        if _sealed._directory_handle_identity(os.fstat(fresh)) != _sealed._directory_handle_identity(os.fstat(held_fd)):
            raise GTViewError(f"directory identity drift: {relative}")
    finally:
        os.close(fresh)


def _run_fd(guard: _sealed.CheckoutGuard, authority: Authority, run_id: str) -> int:
    try:
        return _sealed._open_relative_directory(guard.root_fd, f"{authority.run_parent_relative}/{run_id}")
    except (OSError, _sealed.ImageViewError) as exc:
        raise GTViewError("run directory is unavailable or unsafe") from exc


def _load_generation(
    run_fd: int,
    preregistration_sha256: str,
    generation_manifest_sha256: str,
    run_id: str | None = None,
) -> tuple[dict[str, object], bytes, dict[str, object]]:
    prereg_raw, _ = _read(run_fd, "PREREGISTRATION.json")
    if _sha(prereg_raw) != preregistration_sha256:
        raise GTViewError("preregistration hash-chain mismatch")
    prereg = _strict_json(prereg_raw, "preregistration")
    raw, _ = _read(run_fd, "generation/ARTIFACT_MANIFEST.json")
    if _sha(raw) != generation_manifest_sha256:
        raise GTViewError("generation manifest hash mismatch")
    value = _strict_json(raw, "generation manifest")
    if value.get("schema_version") != GENERATION_SCHEMA or value.get("state") != "GENERATION_SEALED":
        raise GTViewError("generation is not sealed")
    if run_id is not None and value.get("run_id") != run_id:
        raise GTViewError("generation run binding mismatch")
    if value.get("preregistration_sha256") != preregistration_sha256:
        raise GTViewError("generation preregistration chain mismatch")
    return value, raw, prereg


def _opaque_inventory_records(
    root_fd: int,
    prereg: dict[str, object],
    expected: tuple[tuple[str, str], ...],
    stems: tuple[str, ...],
) -> tuple[list[dict[str, object]], str]:
    inputs = prereg.get("inputs")
    ref = inputs.get("opaque_gt_inventory") if type(inputs) is dict else None
    if type(ref) is not dict or set(ref) != {"path", "bytes", "sha256", "verdict"}:
        raise GTViewError("opaque GT inventory preregistration binding missing")
    raw, _ = _read(root_fd, _safe_relative(ref["path"]))
    if len(raw) != ref["bytes"] or _sha(raw) != _require_sha(ref["sha256"], "opaque inventory hash"):
        raise GTViewError("opaque GT inventory drift")
    value = _strict_json(raw, "opaque GT inventory")
    records_value = value.get("records")
    if (
        set(value) != {"schema_version", "stems", "records"}
        or value.get("schema_version") != IMPORT_INVENTORY_SCHEMA
        or value.get("stems") != list(stems)
        or type(records_value) is not list
        or len(records_value) != len(expected)
    ):
        raise GTViewError("opaque GT inventory schema/dataset drift")
    normalized: list[dict[str, object]] = []
    for item, (expected_path, _source) in zip(records_value, expected, strict=True):
        if type(item) is not dict or set(item) != {"path", "bytes", "sha256"}:
            raise GTViewError("opaque GT inventory record drift")
        path = _safe_relative(item["path"])
        parts = PurePosixPath(path).parts
        roots = [index for index, part in enumerate(parts) if part.endswith((".geff", ".zarr"))]
        if len(roots) != 1 or PurePosixPath(*parts[roots[0] :]).as_posix() != expected_path:
            raise GTViewError("opaque GT inventory path layout drift")
        if type(item["bytes"]) is not int or item["bytes"] < 0:
            raise GTViewError("opaque GT inventory byte count drift")
        normalized.append(
            {
                "path": expected_path,
                "bytes": item["bytes"],
                "sha256": _require_sha(item["sha256"], "opaque record hash"),
            }
        )
    return normalized, _sha(raw)


def _assert_run_preconditions(run_fd: int, *, importing: bool) -> None:
    forbidden = ("feasibility", "scores", "final")
    for name in forbidden:
        try:
            os.stat(name, dir_fd=run_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise GTViewError(f"run is already terminal: {name}")
    try:
        inputs_fd = _sealed._open_relative_directory(run_fd, "inputs")
    except (FileNotFoundError, _sealed.ImageViewError) as exc:
        if importing:
            raise GTViewError("fixed run inputs parent is missing") from exc
        return
    try:
        if _sealed._name_info(inputs_fd, "gt") is not None:
            raise GTViewError("run GT target already exists")
    finally:
        os.close(inputs_fd)


def _expected_records(authority: Authority) -> tuple[tuple[str, str], ...]:
    records: list[tuple[str, str]] = []
    for stem in authority.stems:
        records.extend((f"{stem}.geff/{suffix}", f"{stem}.geff/{suffix}") for suffix in authority.geff_suffixes)
        records.extend((f"{stem}.zarr/{suffix}", f"{stem}.zarr/{suffix}") for suffix in authority.zarr_suffixes)
    return tuple(sorted(records, key=lambda pair: pair[0].encode()))


def _expected_dirs(records: tuple[tuple[str, str], ...], prefix: str = "GT_VIEW") -> tuple[str, ...]:
    result = {prefix}
    for destination, _source in records:
        parts = PurePosixPath(destination).parts[:-1]
        for depth in range(1, len(parts) + 1):
            result.add(PurePosixPath(prefix, *parts[:depth]).as_posix())
    return tuple(sorted(result, key=lambda path: (len(PurePosixPath(path).parts), path.encode())))


def _scan_exact_source(train_fd: int, authority: Authority, expected: tuple[tuple[str, str], ...]) -> None:
    names = os.listdir(train_fd)
    if len({name.casefold() for name in names}) != len(names):
        raise GTViewError("case-colliding source roots")
    expected_by_root: dict[str, set[str]] = {}
    for _destination, source in expected:
        root, suffix = source.split("/", 1)
        expected_by_root.setdefault(root, set()).add(suffix)
    for root_name, suffixes in expected_by_root.items():
        root_fd = _sealed._open_relative_directory(train_fd, (root_name,))
        try:
            files, directories = _sealed._walk_tree(root_fd)
            observed = {str(item["path"]) for item in files}
            expected_directories = {
                PurePosixPath(suffix).parent.as_posix()
                for suffix in suffixes
                if PurePosixPath(suffix).parent.as_posix() != "."
            }
            expanded: set[str] = set()
            for directory in expected_directories:
                parts = PurePosixPath(directory).parts
                expanded.update(PurePosixPath(*parts[:depth]).as_posix() for depth in range(1, len(parts) + 1))
            observed_dirs = {str(item["path"]) for item in directories}
            if observed != suffixes or observed_dirs != expanded:
                raise GTViewError(f"fixed source layout drift: {root_name}")
        except _sealed.ImageViewError as exc:
            raise GTViewError(f"unsafe source root: {root_name}") from exc
        finally:
            os.close(root_fd)


def _identity(info: os.stat_result) -> dict[str, int]:
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": info.st_mode,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _normalized(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{"path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in records]


def _digest_records(records: list[dict[str, object]]) -> str:
    return _sha(canonical_json_bytes(_normalized(records)))


def _clone_payload(
    source_root_fd: int,
    staging_fd: int,
    ownership: _sealed._StagingOwnership,
    expected: tuple[tuple[str, str], ...],
) -> list[dict[str, object]]:
    for directory in _expected_dirs(expected):
        _sealed._create_directory(staging_fd, directory, ownership)
    records: list[dict[str, object]] = []
    for destination, source in expected:
        source_fd: int | None = None
        source_parent_fd: int | None = None
        destination_parent_fd: int | None = None
        try:
            source_fd, source_parent_fd = _sealed._open_relative_regular(source_root_fd, source)
            before = os.fstat(source_fd)
            if before.st_nlink != 1 or not stat.S_ISREG(before.st_mode):
                raise GTViewError("source is not an isolated regular file")
            before_hash = _sealed._hash_open_file(source_fd, before.st_size)
            output = f"GT_VIEW/{destination}"
            parts = PurePosixPath(output).parts
            destination_parent_fd = _sealed._open_relative_directory(staging_fd, tuple(parts[:-1]))
            _sealed._clone_file(source_fd, destination_parent_fd, parts[-1])
            destination_info = os.stat(parts[-1], dir_fd=destination_parent_fd, follow_symlinks=False)
            ownership.files[output] = _sealed._ownership(destination_info)
            destination_fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=destination_parent_fd,
            )
            try:
                destination_hash = _sealed._hash_open_file(destination_fd, before.st_size)
                destination_after = os.fstat(destination_fd)
            finally:
                os.close(destination_fd)
            after_hash = _sealed._hash_open_file(source_fd, before.st_size)
            after = os.fstat(source_fd)
            if before_hash != destination_hash or destination_hash != after_hash:
                raise GTViewError("source/destination content mismatch")
            if _sealed._identity(before) != _sealed._identity(after):
                raise GTViewError("source changed during clone")
            if before.st_dev != destination_after.st_dev or before.st_ino == destination_after.st_ino:
                raise GTViewError("clone inode/device postcondition failed")
            if before.st_nlink != 1 or destination_after.st_nlink != 1:
                raise GTViewError("hardlink postcondition failed")
            chmod_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=destination_parent_fd)
            try:
                os.fchmod(chmod_fd, 0o400)
                os.fsync(chmod_fd)
                destination_after = os.fstat(chmod_fd)
            finally:
                os.close(chmod_fd)
            records.append(
                {
                    "path": destination,
                    "bytes": before.st_size,
                    "sha256": before_hash,
                    "source_before": _identity(before),
                    "source_after": _identity(after),
                    "destination": _identity(destination_after),
                }
            )
        except (OSError, _sealed.ImageViewError) as exc:
            raise GTViewError(str(exc)) from exc
        finally:
            for fd in (destination_parent_fd, source_fd, source_parent_fd):
                if fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(fd)
    return records


def _write_artifact(staging_fd: int, name: str, raw: bytes, ownership: _sealed._StagingOwnership) -> None:
    try:
        info = _sealed._write_new_regular(staging_fd, name, raw, mode=0o400)
    except _sealed.ImageViewError as exc:
        raise GTViewError(f"cannot write {name}") from exc
    ownership.files[name] = _sealed._ownership(info)


def _seal_directories(staging_fd: int, ownership: _sealed._StagingOwnership) -> None:
    for relative in sorted(
        ownership.directories,
        key=lambda path: (-len(PurePosixPath(path).parts), path.encode()),
    ):
        fd = _sealed._open_relative_directory(staging_fd, relative)
        try:
            if _sealed._ownership(os.fstat(fd)) != ownership.directories[relative]:
                raise GTViewError("created directory identity drift")
            os.fchmod(fd, 0o500)
            os.fsync(fd)
        finally:
            os.close(fd)


def _publish(
    parent_fd: int,
    final_name: str,
    build: callable,
) -> object:
    if _sealed._name_info(parent_fd, final_name) is not None:
        raise GTViewError("publication target already exists")
    staging_name = f".{final_name}.staging.{os.getpid()}.{secrets.token_hex(12)}"
    old_umask = os.umask(0o077)
    staging_fd: int | None = None
    ownership: _sealed._StagingOwnership | None = None
    published = False
    try:
        os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
        info = os.stat(staging_name, dir_fd=parent_fd, follow_symlinks=False)
        ownership = _sealed._StagingOwnership(staging_name, _sealed._ownership(info), {}, {})
        staging_fd = _sealed._open_relative_directory(parent_fd, (staging_name,))
        result = build(staging_fd, ownership)
        _seal_directories(staging_fd, ownership)
        os.fchmod(staging_fd, 0o500)
        os.fsync(staging_fd)
        try:
            primitive = _sealed._rename_noreplace(parent_fd, staging_name, final_name)
            if primitive != "renameatx_np(RENAME_EXCL)":
                raise GTViewError("Darwin RENAME_EXCL was not used")
            published = True
            os.fsync(parent_fd)
        except BaseException as exc:
            try:
                _sealed._recover_publication(parent_fd, staging_fd, ownership, final_name, exc)
            except BaseException as cleanup:
                raise PublicationAmbiguityError(
                    "publication ownership/durability is ambiguous"
                ) from BaseExceptionGroup("publication and recovery failed", [exc, cleanup])
            if isinstance(exc, FileExistsError):
                raise GTViewError("publication target won a concurrent race") from exc
            raise PublicationAmbiguityError("publication failed after an ambiguous durability point") from exc
        return result
    except BaseException as exc:
        if staging_fd is not None and ownership is not None and not published:
            try:
                if _sealed._name_info(parent_fd, staging_name) is not None:
                    _sealed._cleanup_staging(parent_fd, staging_fd, ownership)
            except BaseException as cleanup:
                raise PublicationAmbiguityError("staging cleanup is ambiguous") from BaseExceptionGroup(
                    "operation and cleanup failed", [exc, cleanup]
                )
        raise
    finally:
        os.umask(old_umask)
        if staging_fd is not None:
            with contextlib.suppress(OSError):
                os.close(staging_fd)


def _ensure_existing_parent(root_fd: int, relative: str) -> int:
    try:
        return _sealed._open_relative_directory(root_fd, relative)
    except (OSError, _sealed.ImageViewError) as exc:
        raise GTViewError(f"fixed parent missing or unsafe: {relative}") from exc


def _inventory(records: list[dict[str, object]], stems: tuple[str, ...], prefix: str, schema: str) -> dict[str, object]:
    refs = [{"path": f"{prefix}/{item['path']}", "bytes": item["bytes"], "sha256": item["sha256"]} for item in records]
    refs.sort(key=lambda item: str(item["path"]).encode())
    if schema == IMPORT_INVENTORY_SCHEMA:
        return {"schema_version": schema, "stems": list(stems), "records": refs}
    return {
        "schema_version": schema,
        "path_basis": "standalone_root_relative" if prefix == "GT_VIEW" else "run_root_relative",
        "roots": list(stems),
        "files": refs,
        "summary": {
            "roots": len(stems) * 2,
            "files": len(refs),
            "bytes": sum(int(item["bytes"]) for item in refs),
            "records_sha256": _sha(canonical_json_bytes(refs)),
        },
    }


def build_gt_view(run_id: str, preregistration_sha256: str, generation_manifest_sha256: str) -> BuildResult:
    """Build and seal the sole fixed standalone GT view."""
    authority = PRODUCTION_AUTHORITY
    run_id = _require_run_id(run_id)
    preregistration_sha256 = _require_sha(preregistration_sha256, "preregistration_sha256")
    generation_manifest_sha256 = _require_sha(generation_manifest_sha256, "generation_manifest_sha256")
    _audit_inherited_fds()
    guard, git, bindings = _checkout(authority)
    run_fd = train_fd = parent_fd = None
    try:
        run_fd = _run_fd(guard, authority, run_id)
        generation, generation_raw, prereg = _load_generation(
            run_fd, preregistration_sha256, generation_manifest_sha256, run_id
        )
        _assert_run_preconditions(run_fd, importing=False)
        try:
            parent_fd = _sealed._ensure_output_parent(guard.root_fd, authority.standalone_parent_relative)
        except _sealed.ImageViewError as exc:
            raise GTViewError("fixed standalone parent is unsafe") from exc
        if _sealed._name_info(parent_fd, run_id) is not None:
            raise GTViewError("standalone target already exists")
        train_fd = _ensure_existing_parent(guard.root_fd, authority.source_relative)
        if os.fstat(train_fd).st_dev != os.fstat(parent_fd).st_dev:
            raise GTViewError("source and destination are on different devices")
        if _sealed._filesystem_type(authority.root / authority.source_relative, train_fd) != "apfs":
            raise GTViewError("source is not APFS")
        if _sealed._filesystem_type(authority.root / authority.standalone_parent_relative, parent_fd) != "apfs":
            raise GTViewError("destination is not APFS")
        expected = _expected_records(authority)
        opaque_records, opaque_inventory_sha256 = _opaque_inventory_records(
            guard.root_fd, prereg, expected, authority.stems
        )
        _scan_exact_source(train_fd, authority, expected)
        train_identity = _sealed._identity(os.fstat(train_fd))
        run_identity = _sealed._identity(os.fstat(run_fd))
        parent_identity = _sealed._directory_handle_identity(os.fstat(parent_fd))

        def create(staging_fd: int, ownership: _sealed._StagingOwnership) -> BuildResult:
            records = _clone_payload(train_fd, staging_fd, ownership, expected)
            if _digest_records(records) != _digest_records(opaque_records):
                raise GTViewError("source content disagrees with preregistered opaque inventory")
            inventory = _inventory(records, authority.stems, "GT_VIEW", INVENTORY_SCHEMA)
            inventory_raw = canonical_json_bytes(inventory)
            _write_artifact(staging_fd, "GT_VIEW_INVENTORY.json", inventory_raw, ownership)
            view_fd = _sealed._open_relative_directory(staging_fd, "GT_VIEW")
            try:
                view_info = os.fstat(view_fd)
                view_identity = {"device": view_info.st_dev, "inode": view_info.st_ino}
            finally:
                os.close(view_fd)
            core = {
                "schema_version": RECEIPT_SCHEMA,
                "state": "GT_VIEW_SEALED",
                "run_id": run_id,
                "preregistration_sha256": preregistration_sha256,
                "generation_manifest_sha256": generation_manifest_sha256,
                "generation_manifest_bytes": len(generation_raw),
                "datasets": generation.get("datasets"),
                "checkout": dataclasses.asdict(git),
                "builder": {
                    "sources": list(bindings),
                    "clone_method": "fclonefileat(APFS_CLONEFILE)",
                    "publication": "renameatx_np(RENAME_EXCL)",
                },
                "source": {
                    "path": authority.source_relative,
                    "identity": _identity(os.fstat(train_fd)),
                    "pre_records_sha256": _sha(canonical_json_bytes([item["source_before"] for item in records])),
                    "post_records_sha256": _sha(canonical_json_bytes([item["source_after"] for item in records])),
                },
                "view": {
                    "path": "GT_VIEW",
                    "identity": view_identity,
                    "roots": [f"{stem}{suffix}" for stem in authority.stems for suffix in (".geff", ".zarr")],
                },
                "inventory": {
                    "path": "GT_VIEW_INVENTORY.json",
                    "bytes": len(inventory_raw),
                    "sha256": _sha(inventory_raw),
                    "normalized_records_sha256": _digest_records(records),
                    "preregistered_opaque_inventory_sha256": opaque_inventory_sha256,
                },
                "isolation": {
                    "same_device": True,
                    "distinct_inodes": True,
                    "nlink_one": True,
                    "read_only": True,
                    "payload_semantics_parsed": False,
                },
                "process": {
                    "pid": os.getpid(),
                    "network_used": False,
                    "payload_child_processes_spawned": False,
                    "double_fork_used": False,
                    "orphan_processes_created": False,
                    "inherited_sensitive_fds": False,
                },
                "records": records,
            }
            receipt = {**core, "receipt_content_sha256": _sha(canonical_json_bytes(core))}
            receipt_raw = canonical_json_bytes(receipt)
            _write_artifact(staging_fd, "GT_VIEW_RECEIPT.json", receipt_raw, ownership)
            if (
                _sealed._identity(os.fstat(train_fd)) != train_identity
                or _sealed._identity(os.fstat(run_fd)) != run_identity
                or _sealed._directory_handle_identity(os.fstat(parent_fd)) != parent_identity
            ):
                raise GTViewError("held directory identity drift")
            _rebind_directory(guard.root_fd, authority.source_relative, train_fd)
            _rebind_directory(guard.root_fd, f"{authority.run_parent_relative}/{run_id}", run_fd)
            _rebind_directory(guard.root_fd, authority.standalone_parent_relative, parent_fd)
            _rebind(authority, guard)
            return BuildResult(
                "GT_VIEW_SEALED",
                run_id,
                f"{authority.standalone_parent_relative}/{run_id}/GT_VIEW",
                _sha(inventory_raw),
                _sha(receipt_raw),
                len(records),
                sum(int(item["bytes"]) for item in records),
            )

        result = _publish(parent_fd, run_id, create)
        _rebind_directory(guard.root_fd, authority.source_relative, train_fd)
        _rebind_directory(guard.root_fd, f"{authority.run_parent_relative}/{run_id}", run_fd)
        _rebind_directory(guard.root_fd, authority.standalone_parent_relative, parent_fd)
        _rebind(authority, guard)
        return result  # type: ignore[return-value]
    finally:
        for fd in (parent_fd, train_fd, run_fd):
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        guard.close()


def _load_standalone(
    run_id: str, receipt_sha256: str | None = None
) -> tuple[int, dict[str, object], bytes, dict[str, object], bytes]:
    authority = PRODUCTION_AUTHORITY
    root_fd = _sealed._open_absolute_directory(authority.root)
    try:
        run_fd = _sealed._open_relative_directory(root_fd, f"{authority.standalone_parent_relative}/{run_id}")
    finally:
        os.close(root_fd)
    try:
        if set(os.listdir(run_fd)) != {"GT_VIEW", "GT_VIEW_INVENTORY.json", "GT_VIEW_RECEIPT.json"}:
            raise GTViewError("standalone membership drift")
        receipt_raw, receipt_info = _sealed._read_named_regular(
            run_fd, "GT_VIEW_RECEIPT.json", max_bytes=MAX_JSON_BYTES
        )
        inventory_raw, inventory_info = _sealed._read_named_regular(
            run_fd, "GT_VIEW_INVENTORY.json", max_bytes=MAX_JSON_BYTES
        )
        if (
            stat.S_IMODE(os.fstat(run_fd).st_mode) != 0o500
            or stat.S_IMODE(receipt_info.st_mode) != 0o400
            or stat.S_IMODE(inventory_info.st_mode) != 0o400
        ):
            raise GTViewError("standalone modes drift")
        if receipt_sha256 is not None and _sha(receipt_raw) != receipt_sha256:
            raise GTViewError("receipt digest mismatch")
        receipt = _strict_json(receipt_raw, "GT view receipt")
        inventory = _strict_json(inventory_raw, "GT view inventory")
        if (
            receipt.get("schema_version") != RECEIPT_SCHEMA
            or receipt.get("state") != "GT_VIEW_SEALED"
            or receipt.get("run_id") != run_id
        ):
            raise GTViewError("receipt binding drift")
        inv_ref = receipt.get("inventory")
        if type(inv_ref) is not dict or inv_ref.get("sha256") != _sha(inventory_raw):
            raise GTViewError("inventory receipt binding drift")
        return run_fd, receipt, receipt_raw, inventory, inventory_raw
    except BaseException:
        os.close(run_fd)
        raise


def _verify_inventory_and_view(
    run_fd: int, inventory: dict[str, object], authority: Authority
) -> list[dict[str, object]]:
    if (
        inventory.get("schema_version") != INVENTORY_SCHEMA
        or inventory.get("path_basis") != "standalone_root_relative"
        or inventory.get("roots") != list(authority.stems)
    ):
        raise GTViewError("inventory schema/root drift")
    refs = inventory.get("files")
    if type(refs) is not list:
        raise GTViewError("inventory records missing")
    expected = _expected_records(authority)
    if len(refs) != len(expected):
        raise GTViewError("inventory file count drift")
    view_fd = _sealed._open_relative_directory(run_fd, "GT_VIEW")
    try:
        if stat.S_IMODE(os.fstat(view_fd).st_mode) != 0o500:
            raise GTViewError("GT_VIEW mode drift")
        records: list[dict[str, object]] = []
        for ref, (relative, _source) in zip(refs, expected, strict=True):
            if type(ref) is not dict or set(ref) != {"path", "bytes", "sha256"} or ref["path"] != f"GT_VIEW/{relative}":
                raise GTViewError("inventory path/order drift")
            size = ref["bytes"]
            digest = ref["sha256"]
            if type(size) is not int or size < 0:
                raise GTViewError("invalid inventory byte count")
            _require_sha(digest, "inventory hash")
            fd, parent = _sealed._open_relative_regular(view_fd, relative)
            try:
                info = os.fstat(fd)
                if (
                    stat.S_IMODE(info.st_mode) != 0o400
                    or info.st_nlink != 1
                    or _sealed._hash_open_file(fd, size) != digest
                ):
                    raise GTViewError("view content/mode drift")
                records.append({"path": relative, "bytes": size, "sha256": digest})
            finally:
                os.close(fd)
                os.close(parent)
        files, directories = _sealed._walk_tree(view_fd)
        if {item["path"] for item in files} != {relative for relative, _ in expected}:
            raise GTViewError("view membership drift")
        expected_directories = {path.removeprefix("GT_VIEW/") for path in _expected_dirs(expected) if path != "GT_VIEW"}
        if {str(item["path"]) for item in directories} != expected_directories:
            raise GTViewError("view directory membership drift")
        if any(stat.S_IMODE(int(item["identity"]["mode"])) != 0o500 for item in directories):
            raise GTViewError("view directory mode drift")
        return records
    finally:
        os.close(view_fd)


def _validate_receipt_records(
    receipt: dict[str, object], content_records: list[dict[str, object]]
) -> list[dict[str, object]]:
    values = receipt.get("records")
    if type(values) is not list or len(values) != len(content_records):
        raise GTViewError("receipt record count drift")
    result: list[dict[str, object]] = []
    identity_keys = {"device", "inode", "mode", "nlink", "size", "mtime_ns", "ctime_ns"}
    for value, content in zip(values, content_records, strict=True):
        if type(value) is not dict or set(value) != {
            "path",
            "bytes",
            "sha256",
            "source_before",
            "source_after",
            "destination",
        }:
            raise GTViewError("receipt record schema drift")
        if any(
            type(value[key]) is not dict or set(value[key]) != identity_keys
            for key in ("source_before", "source_after", "destination")
        ):
            raise GTViewError("receipt identity schema drift")
        if {key: value[key] for key in ("path", "bytes", "sha256")} != content:
            raise GTViewError("receipt/inventory content drift")
        before = value["source_before"]
        after = value["source_after"]
        destination = value["destination"]
        if before != after:
            raise GTViewError("receipt records source mutation")
        if (
            before["device"] != destination["device"]
            or before["inode"] == destination["inode"]
            or before["nlink"] != 1
            or destination["nlink"] != 1
            or stat.S_IMODE(int(destination["mode"])) != 0o400
        ):
            raise GTViewError("receipt isolation evidence drift")
        result.append(value)
    return result


def _reverify_build_source(
    guard: _sealed.CheckoutGuard,
    authority: Authority,
    receipt_records: list[dict[str, object]],
) -> None:
    train_fd = _ensure_existing_parent(guard.root_fd, authority.source_relative)
    try:
        expected = _expected_records(authority)
        _scan_exact_source(train_fd, authority, expected)
        for record, (_destination, source) in zip(receipt_records, expected, strict=True):
            fd, parent_fd = _sealed._open_relative_regular(train_fd, source)
            try:
                info = os.fstat(fd)
                if _identity(info) != record["source_after"]:
                    raise GTViewError("source identity drift after publication")
                if _sealed._hash_open_file(fd, int(record["bytes"])) != record["sha256"]:
                    raise GTViewError("source content drift after publication")
            finally:
                os.close(fd)
                os.close(parent_fd)
    except (OSError, _sealed.ImageViewError) as exc:
        raise GTViewError("source reverification failed") from exc
    finally:
        os.close(train_fd)


def verify_gt_view(run_id: str, receipt_sha256: str) -> VerifyResult:
    """Reopen and fully hash a sealed standalone view."""
    authority = PRODUCTION_AUTHORITY
    run_id = _require_run_id(run_id)
    receipt_sha256 = _require_sha(receipt_sha256, "receipt_sha256")
    _audit_inherited_fds()
    guard, git, bindings = _checkout(authority)
    standalone_fd = None
    try:
        standalone_fd, receipt, receipt_raw, inventory, inventory_raw = _load_standalone(run_id, receipt_sha256)
        if (
            receipt.get("checkout") != dataclasses.asdict(git)
            or not isinstance(receipt.get("builder"), dict)
            or receipt["builder"].get("sources") != list(bindings)
        ):
            raise GTViewError("checkout/builder binding drift")
        records = _verify_inventory_and_view(standalone_fd, inventory, authority)
        view_value = receipt.get("view")
        if type(view_value) is not dict or set(view_value) != {"path", "identity", "roots"}:
            raise GTViewError("receipt view binding drift")
        current_view_fd = _sealed._open_relative_directory(standalone_fd, "GT_VIEW")
        try:
            current_view_info = os.fstat(current_view_fd)
            current_view_identity = {"device": current_view_info.st_dev, "inode": current_view_info.st_ino}
        finally:
            os.close(current_view_fd)
        if view_value != {
            "path": "GT_VIEW",
            "identity": current_view_identity,
            "roots": [f"{stem}{suffix}" for stem in authority.stems for suffix in (".geff", ".zarr")],
        }:
            raise GTViewError("receipt view identity/root drift")
        receipt_records = _validate_receipt_records(receipt, records)
        _reverify_build_source(guard, authority, receipt_records)
        _rebind_directory(
            guard.root_fd,
            f"{authority.standalone_parent_relative}/{run_id}",
            standalone_fd,
        )
        if receipt["inventory"].get("normalized_records_sha256") != _digest_records(records):
            raise GTViewError("normalized content digest drift")
        core = dict(receipt)
        digest = core.pop("receipt_content_sha256", None)
        if digest != _sha(canonical_json_bytes(core)) or receipt["inventory"].get("sha256") != _sha(inventory_raw):
            raise GTViewError("receipt content digest drift")
        _rebind(authority, guard)
        return VerifyResult(
            "GT_VIEW_VERIFIED", run_id, _sha(receipt_raw), len(records), sum(int(item["bytes"]) for item in records)
        )
    finally:
        if standalone_fd is not None:
            os.close(standalone_fd)
        guard.close()


def import_gt_view(run_id: str, generation_manifest_sha256: str, source_receipt_sha256: str) -> ImportResult:
    """Clone a verified standalone view into the fixed run ``inputs/gt``."""
    authority = PRODUCTION_AUTHORITY
    run_id = _require_run_id(run_id)
    generation_manifest_sha256 = _require_sha(generation_manifest_sha256, "generation_manifest_sha256")
    source_receipt_sha256 = _require_sha(source_receipt_sha256, "source_receipt_sha256")
    _audit_inherited_fds()
    guard, git, bindings = _checkout(authority)
    standalone_fd = run_fd = inputs_fd = None
    try:
        standalone_fd, source_receipt, source_receipt_raw, source_inventory, _ = _load_standalone(
            run_id, source_receipt_sha256
        )
        source_records = _verify_inventory_and_view(standalone_fd, source_inventory, authority)
        prereg_sha = _require_sha(source_receipt.get("preregistration_sha256"), "source preregistration")
        if source_receipt.get("generation_manifest_sha256") != generation_manifest_sha256:
            raise GTViewError("source generation binding mismatch")
        run_fd = _run_fd(guard, authority, run_id)
        generation, _generation_raw, _prereg = _load_generation(run_fd, prereg_sha, generation_manifest_sha256, run_id)
        _assert_run_preconditions(run_fd, importing=True)
        inputs_fd = _sealed._open_relative_directory(run_fd, "inputs")
        source_view_fd = _sealed._open_relative_directory(standalone_fd, "GT_VIEW")
        try:
            if os.fstat(source_view_fd).st_dev != os.fstat(inputs_fd).st_dev:
                raise GTViewError("import crosses devices")
            expected = tuple((str(item["path"]), str(item["path"])) for item in source_records)

            def create(staging_fd: int, ownership: _sealed._StagingOwnership) -> ImportResult:
                records = _clone_payload(source_view_fd, staging_fd, ownership, expected)
                if _digest_records(records) != _digest_records(source_records):
                    raise GTViewError("import normalized digest mismatch")
                inventory = _inventory(records, authority.stems, "inputs/gt/GT_VIEW", IMPORT_INVENTORY_SCHEMA)
                inventory_raw = canonical_json_bytes(inventory)
                _write_artifact(staging_fd, "GT_CONTENT_INVENTORY.json", inventory_raw, ownership)
                core = {
                    "schema_version": IMPORT_RECEIPT_SCHEMA,
                    "state": "GT_VIEW_IMPORTED",
                    "run_id": run_id,
                    "generation_manifest_sha256": generation_manifest_sha256,
                    "source_receipt_sha256": source_receipt_sha256,
                    "source_receipt_bytes": len(source_receipt_raw),
                    "datasets": generation.get("datasets"),
                    "checkout": dataclasses.asdict(git),
                    "builder": {
                        "sources": list(bindings),
                        "clone_method": "fclonefileat(APFS_CLONEFILE)",
                        "publication": "renameatx_np(RENAME_EXCL)",
                    },
                    "inventory": {
                        "path": "inputs/gt/GT_CONTENT_INVENTORY.json",
                        "bytes": len(inventory_raw),
                        "sha256": _sha(inventory_raw),
                        "normalized_records_sha256": _digest_records(records),
                    },
                    "view": {"path": "inputs/gt/GT_VIEW", "files": len(records)},
                    "isolation": {"same_device": True, "distinct_inodes": True, "nlink_one": True, "read_only": True},
                    "records": records,
                }
                receipt = {**core, "receipt_content_sha256": _sha(canonical_json_bytes(core))}
                receipt_raw = canonical_json_bytes(receipt)
                _write_artifact(staging_fd, "GT_VIEW_IMPORT_RECEIPT.json", receipt_raw, ownership)
                _rebind_directory(
                    guard.root_fd,
                    f"{authority.standalone_parent_relative}/{run_id}",
                    standalone_fd,
                )
                _rebind_directory(guard.root_fd, f"{authority.run_parent_relative}/{run_id}", run_fd)
                _rebind_directory(run_fd, "inputs", inputs_fd)
                _rebind(authority, guard)
                return ImportResult(
                    "GT_VIEW_IMPORTED",
                    run_id,
                    f"{authority.run_parent_relative}/{run_id}/inputs/gt/GT_VIEW",
                    _sha(inventory_raw),
                    _sha(receipt_raw),
                    len(records),
                    sum(int(item["bytes"]) for item in records),
                )

            result = _publish(inputs_fd, "gt", create)
            _rebind_directory(
                guard.root_fd,
                f"{authority.standalone_parent_relative}/{run_id}",
                standalone_fd,
            )
            _rebind_directory(guard.root_fd, f"{authority.run_parent_relative}/{run_id}", run_fd)
            _rebind_directory(run_fd, "inputs", inputs_fd)
            _rebind(authority, guard)
            return result  # type: ignore[return-value]
        finally:
            os.close(source_view_fd)
    finally:
        for fd in (inputs_fd, run_fd, standalone_fd):
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        guard.close()


__all__ = [
    "BuildResult",
    "GTViewError",
    "ImportResult",
    "PublicationAmbiguityError",
    "VerifyResult",
    "build_gt_view",
    "import_gt_view",
    "verify_gt_view",
]
