"""Fail-closed training-history artifacts.

This module deliberately has no torch dependency.  Checkpoints are treated as
opaque byte strings for hashing and their *safe metadata* is read either from a
real JSON envelope or from a caller supplied trusted ``checkpoint_metadata_loader``.
The default code path never unpickles a ``.pt`` file.  The explicitly selected
PyTorch loader uses ``torch.load(..., weights_only=True)`` and converts tensors
to the same strict, JSON-safe envelope before validation.

The public surface is intentionally small: :class:`HistoryWriter`,
:func:`strict_json_load`, :func:`strict_jsonl_load`, :func:`select_best`,
:func:`compute_degradation`, :func:`validate_resume_metadata`,
:func:`validate_warm_start`, :func:`verify_training_run`, and
:func:`validate_training_run`.
"""

from __future__ import annotations

import ast
import base64
import ctypes
import errno
import fcntl
import hashlib
import json
import math
import os
import secrets
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
CHECKPOINT_FORMAT = "biohub.safe_checkpoint.v1"
HEX_SHA256_LENGTH = 64
AT_FDCWD = -2
RENAME_NOREPLACE = 1
RENAME_EXCL = 4


class TrainingHistoryError(ValueError):
    """Base class for malformed or inconsistent training artifacts."""


class DuplicateKeyError(TrainingHistoryError):
    """A JSON object contained a duplicate key."""


class GateValidationError(TrainingHistoryError):
    """The fail-closed gate rejected an artifact."""

    def __init__(self, errors: str | Sequence[str]):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


def _reject_constant(value: str) -> None:
    raise TrainingHistoryError(f"non-finite JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def strict_json_loads(data: str, *, source: str = "<string>") -> Any:
    """Parse JSON while rejecting duplicate keys and NaN/Infinity tokens."""
    try:
        value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except TrainingHistoryError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TrainingHistoryError(f"invalid JSON in {source}: {exc}") from exc
    _require_finite_tree(value, source)
    return value


def strict_json_load(path: str | os.PathLike[str]) -> Any:
    source = Path(path)
    try:
        data, _digest, _size = _read_regular_snapshot(source)
        text = data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise TrainingHistoryError(f"cannot read {source}: {exc}") from exc
    return strict_json_loads(text, source=str(source))


def strict_jsonl_load(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read JSONL strictly; blank lines and non-object records are invalid."""
    source = Path(path)
    try:
        data, _digest, _size = _read_regular_snapshot(source)
        lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise TrainingHistoryError(f"cannot read {source}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise TrainingHistoryError(f"blank JSONL record at {source}:{number}")
        row = strict_json_loads(line, source=f"{source}:{number}")
        if not isinstance(row, dict):
            raise TrainingHistoryError(f"JSONL record is not an object at {source}:{number}")
        rows.append(row)
    return rows


def canonical_json_bytes(value: Any) -> bytes:
    _require_finite_tree(value, "JSON value")
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_stream(stream: Any) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    _data, digest, _size = _read_regular_snapshot(Path(path), retain_data=False)
    return digest


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_regular_snapshot(path: Path, *, retain_data: bool = True) -> tuple[bytes, str, int]:
    """Read one immutable regular-file identity through O_NOFOLLOW."""
    fd, opened = _open_regular_fd(path)
    try:
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            if retain_data:
                chunks.append(block)
        _verify_regular_fd(path, fd, opened)
        return b"".join(chunks), digest.hexdigest(), opened.st_size
    except OSError as exc:
        raise TrainingHistoryError(f"cannot securely read {path}: {exc}") from exc
    finally:
        os.close(fd)


def _open_regular_fd(path: Path) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
        fd = os.open(path, flags)
    except OSError as exc:
        raise TrainingHistoryError(f"cannot securely open {path}: {exc}") from exc
    try:
        opened = os.fstat(fd)
    except OSError as exc:
        os.close(fd)
        raise TrainingHistoryError(f"cannot inspect opened file {path}: {exc}") from exc
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or _stat_identity(before) != _stat_identity(opened):
        os.close(fd)
        raise TrainingHistoryError(f"file identity/link count is unsafe: {path}")
    return fd, opened


def _verify_regular_fd(path: Path, fd: int, opened: os.stat_result) -> None:
    after_fd = os.fstat(fd)
    after_path = path.lstat()
    if _stat_identity(opened) != _stat_identity(after_fd) or _stat_identity(opened) != _stat_identity(after_path):
        raise TrainingHistoryError(f"file changed while being read: {path}")


def canonical_sha256(value: Any) -> str:
    """SHA256 of the canonical JSON representation used by this module."""
    return sha256_bytes(canonical_json_bytes(value))


def trusted_pytorch_checkpoint_metadata_loader(path: Path) -> Mapping[str, Any]:
    """Safely load a real PyTorch checkpoint for :func:`verify_training_run`.

    PyTorch is an optional runtime dependency.  Arbitrary pickle loading is
    deliberately unavailable: production callers must opt in to weights-only
    loading and every state entry must be an actual tensor.
    """
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - depends on production environment
        raise TrainingHistoryError("trusted PyTorch checkpoint loading requires torch") from exc
    fd, opened = _open_regular_fd(path)
    try:
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            digest_before = _hash_stream(stream)
            stream.seek(0)
            loaded = torch.load(stream, map_location="cpu", weights_only=True)
            stream.seek(0)
            digest_after = _hash_stream(stream)
            _verify_regular_fd(path, stream.fileno(), opened)
    except Exception as exc:
        raise TrainingHistoryError(f"safe PyTorch checkpoint load failed: {path}: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if digest_before != digest_after:
        raise TrainingHistoryError(f"checkpoint changed during PyTorch load: {path}")
    metadata = dict(_object(loaded, f"PyTorch checkpoint {path}"))
    tensor_state = metadata.get("model_state")
    if not isinstance(tensor_state, Mapping) or not tensor_state:
        raise TrainingHistoryError(f"PyTorch model_state must be a nonempty tensor mapping: {path}")
    state_keys: list[dict[str, Any]] = []
    model_state: list[dict[str, Any]] = []
    for name in sorted(tensor_state):
        tensor = tensor_state[name]
        if not isinstance(name, str) or not name or not isinstance(tensor, torch.Tensor):
            raise TrainingHistoryError(f"PyTorch model_state contains a non-tensor entry: {path}")
        cpu = tensor.detach().cpu().contiguous()
        shape = list(cpu.shape)
        dtype = str(cpu.dtype).removeprefix("torch.")
        values = cpu.reshape(-1).tolist()
        state_keys.append({"name": name, "shape": shape, "dtype": dtype})
        model_state.append({"name": name, "shape": shape, "dtype": dtype, "values": values})
    claimed_keys = metadata.get("state_keys")
    if claimed_keys is not None and not _strict_equal(claimed_keys, state_keys):
        raise TrainingHistoryError(f"PyTorch state_keys do not match loaded tensors: {path}")
    metadata["state_keys"] = state_keys
    metadata["model_state"] = model_state
    resolved = str(path.resolve(strict=True))
    metadata["path"] = resolved
    metadata["checkpoint_sha256"] = digest_before
    metadata["load_evidence"] = {
        "trusted_safe_loader": True,
        "strict": True,
        "missing_keys": [],
        "unexpected_keys": [],
        "path": resolved,
        "checkpoint_sha256": digest_before,
        "model_state_sha256": canonical_sha256(model_state),
    }
    _require_json_tree(metadata, f"trusted PyTorch checkpoint metadata for {path}")
    return metadata


def atomic_write_json(path: str | os.PathLike[str], value: Any) -> None:
    """Publish immutable canonical JSON atomically and without clobbering."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    _atomic_publish_bytes(target, payload)


def atomic_publish_file(path: str | os.PathLike[str], data: bytes) -> None:
    """Atomically publish immutable bytes without replacing an existing path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_publish_bytes(target, data)


def _atomic_publish_bytes(target: Path, data: bytes) -> None:
    parent_fd = _secure_publish_parent(target)
    temporary = f".{target.name}.{secrets.token_hex(16)}.tmp"
    file_fd = -1
    try:
        file_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(file_fd, "wb") as stream:
            file_fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _assert_publish_parent_identity(target.parent, parent_fd)
        _publish_temp_noreplace(Path(temporary), Path(target.name), parent_fd=parent_fd, expected_parent=target.parent)
    except BaseException:
        if file_fd >= 0:
            os.close(file_fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(parent_fd)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(
    source: Path,
    target: Path,
    *,
    source_dir_fd: int = AT_FDCWD,
    target_dir_fd: int = AT_FDCWD,
) -> None:
    """Use the platform's atomic no-replace rename primitive."""
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        result = libc.renameatx_np(
            source_dir_fd,
            ctypes.c_char_p(source_bytes),
            target_dir_fd,
            ctypes.c_char_p(target_bytes),
            RENAME_EXCL,
        )
    elif hasattr(libc, "renameat2"):
        result = libc.renameat2(
            source_dir_fd,
            ctypes.c_char_p(source_bytes),
            target_dir_fd,
            ctypes.c_char_p(target_bytes),
            RENAME_NOREPLACE,
        )
    else:  # pragma: no cover - supported production platforms provide one primitive
        raise TrainingHistoryError("atomic no-replace rename is unavailable on this platform")
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), target)
        raise OSError(error, os.strerror(error), target)


def _publish_temp_noreplace(
    temporary: Path,
    target: Path,
    *,
    parent_fd: int | None = None,
    expected_parent: Path | None = None,
) -> None:
    """Commit a complete temp file, or roll it back and report an honest failure."""
    published = False
    try:
        kwargs = {} if parent_fd is None else {"source_dir_fd": parent_fd, "target_dir_fd": parent_fd}
        _rename_noreplace(temporary, target, **kwargs)
        published = True
        if parent_fd is not None and expected_parent is not None:
            _assert_publish_parent_identity(expected_parent, parent_fd)
        if parent_fd is None:
            _fsync_directory(target.parent)
        else:
            os.fsync(parent_fd)
            if expected_parent is not None:
                _assert_publish_parent_identity(expected_parent, parent_fd)
    except BaseException as original:
        if published:
            try:
                if parent_fd is None:
                    target.unlink()
                    _fsync_directory(target.parent)
                else:
                    os.unlink(target.name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except BaseException as rollback:
                quarantine = target.with_name(f".{target.name}.failed-{secrets.token_hex(16)}")
                try:
                    _rename_noreplace(target, quarantine, **kwargs)
                    if parent_fd is None:
                        _fsync_directory(target.parent)
                    else:
                        os.fsync(parent_fd)
                except BaseException as quarantine_error:
                    raise TrainingHistoryError(
                        f"publication failed after commit and rollback failed; target MUST NOT be trusted: {target}"
                    ) from quarantine_error
                raise TrainingHistoryError(
                    f"publication failed after commit; target was quarantined as {quarantine.name}"
                ) from rollback
        raise original


def _secure_publish_parent(target: Path) -> int:
    parent = target.parent
    try:
        parent_info = parent.lstat()
    except OSError as exc:
        raise TrainingHistoryError(f"publication parent is unavailable: {parent}") from exc
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise TrainingHistoryError(f"publication parent must be a real directory: {parent}")
    if parent.resolve(strict=True) != parent.absolute():
        raise TrainingHistoryError(f"publication parent path contains a symlink: {parent}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(parent, flags)
        _assert_publish_parent_identity(parent, parent_fd)
        try:
            os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return parent_fd
        raise FileExistsError(f"immutable target already exists: {target}")
    except BaseException:
        if "parent_fd" in locals():
            os.close(parent_fd)
        raise


def _assert_publish_parent_identity(parent: Path, parent_fd: int) -> None:
    try:
        path_info = parent.lstat()
        fd_info = os.fstat(parent_fd)
    except OSError as exc:
        raise TrainingHistoryError(f"publication parent changed: {parent}") from exc
    if _stat_identity(path_info) != _stat_identity(fd_info):
        raise TrainingHistoryError(f"publication parent changed: {parent}")


def _is_regular_mode(mode: int) -> bool:
    return stat.S_ISREG(mode)


class HistoryWriter:
    """Durable append-only JSONL writer.

    Each record is completely encoded before one ``O_APPEND`` write, followed
    by ``fsync``. Existing bytes are never rewritten. The constructor validates
    an existing prefix before allowing a resumed append.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        resume: bool = False,
        expected_prefix_sha256: str | None = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.resolve(strict=True) != self.path.parent.absolute() or self.path.parent.is_symlink():
            raise TrainingHistoryError(f"history parent path contains a symlink: {self.path.parent}")
        existed = self.path.exists()
        if resume and not existed:
            raise TrainingHistoryError("resume history must already exist")
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if not existed:
            flags |= os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            self._descriptor = os.open(self.path, flags, 0o644)
        except OSError as exc:
            raise TrainingHistoryError(f"history must be a regular non-symlink file: {self.path}") from exc
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_EX)
            current = os.fstat(self._descriptor)
            if not _is_regular_mode(current.st_mode) or current.st_nlink != 1:
                raise TrainingHistoryError("history must be a regular single-link file")
            self._identity = (current.st_dev, current.st_ino)
            self._verify_path_identity(current.st_size)
            payload = _read_fd_bytes(self._descriptor, current.st_size)
            actual_prefix = sha256_bytes(payload)
            if existed and not resume and current.st_size:
                raise TrainingHistoryError(f"refusing to overwrite history: {self.path}")
            if resume and (not _is_sha256(expected_prefix_sha256) or expected_prefix_sha256 != actual_prefix):
                raise TrainingHistoryError("resume history prefix SHA256 is missing or mismatched")
            self._rows = _strict_jsonl_load_bytes(payload, source=self.path) if payload else []
        except BaseException:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            os.close(self._descriptor)
            raise
        else:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        previous_step = 0
        for expected_epoch, row in enumerate(self._rows, 1):
            if row.get("epoch") != expected_epoch:
                raise TrainingHistoryError(f"existing history epoch is not contiguous at {expected_epoch}")
            step = _strict_int(row.get("global_step"), "global_step", minimum=1)
            if step <= previous_step:
                raise TrainingHistoryError("existing history global_step is not strictly increasing")
            previous_step = step
        self._last_epoch = self._rows[-1].get("epoch", 0) if self._rows else 0
        self._last_step = self._rows[-1].get("global_step", 0) if self._rows else 0
        self._expected_size = current.st_size
        self._expected_prefix_sha256 = actual_prefix

    @property
    def prefix_sha256(self) -> str:
        current = os.fstat(self._descriptor)
        self._verify_path_identity(current.st_size)
        return sha256_bytes(_read_fd_bytes(self._descriptor, current.st_size))

    def close(self) -> None:
        descriptor = getattr(self, "_descriptor", None)
        if descriptor is not None:
            os.close(descriptor)
            self._descriptor = None

    def __del__(self) -> None:  # pragma: no cover - deterministic callers use close
        try:
            self.close()
        except OSError:
            pass

    def _verify_path_identity(self, expected_size: int) -> None:
        try:
            path_info = self.path.lstat()
        except OSError as exc:
            raise TrainingHistoryError("history path disappeared during use") from exc
        if (
            not _is_regular_mode(path_info.st_mode)
            or path_info.st_nlink != 1
            or (path_info.st_dev, path_info.st_ino) != self._identity
            or path_info.st_size != expected_size
        ):
            raise TrainingHistoryError("history path identity changed after prefix validation")

    def append(self, record: Mapping[str, Any]) -> str:
        row = dict(record)
        epoch = _strict_int(row.get("epoch"), "epoch", minimum=1)
        step = _strict_int(row.get("global_step"), "global_step", minimum=1)
        if epoch != self._last_epoch + 1:
            raise TrainingHistoryError(f"epoch must continue at {self._last_epoch + 1}, got {epoch}")
        if step <= self._last_step:
            raise TrainingHistoryError(f"global_step must increase beyond {self._last_step}, got {step}")
        payload = canonical_json_bytes(row)
        descriptor = self._descriptor
        wrote = False
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = os.fstat(descriptor)
            if (
                not _is_regular_mode(current.st_mode)
                or current.st_nlink != 1
                or (current.st_dev, current.st_ino) != self._identity
            ):
                raise TrainingHistoryError("history changed into a nonregular or hard-linked file")
            self._verify_path_identity(current.st_size)
            if current.st_size != self._expected_size:
                raise TrainingHistoryError("concurrent history append detected; reopen and validate the prefix")
            prefix_bytes = _read_fd_bytes(descriptor, current.st_size)
            if sha256_bytes(prefix_bytes) != self._expected_prefix_sha256:
                raise TrainingHistoryError("history prefix bytes changed after validation")
            expected_after_hash = sha256_bytes(prefix_bytes + payload)
            written = os.write(descriptor, payload)
            wrote = written > 0
            if written != len(payload):
                raise OSError(f"short append: {written}/{len(payload)} bytes")
            os.fsync(descriptor)
            after = os.fstat(descriptor)
            if after.st_nlink != 1 or after.st_size != self._expected_size + len(payload):
                raise TrainingHistoryError("history inode changed during append")
            self._verify_path_identity(after.st_size)
            if sha256_bytes(_read_fd_bytes(descriptor, after.st_size)) != expected_after_hash:
                raise TrainingHistoryError("history bytes changed concurrently during append")
        except BaseException:
            if wrote:
                os.ftruncate(descriptor, self._expected_size)
                os.fsync(descriptor)
            raise
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        self._last_epoch = epoch
        self._last_step = step
        self._rows.append(row)
        self._expected_size += len(payload)
        self._expected_prefix_sha256 = expected_after_hash
        return self._expected_prefix_sha256


def _read_fd_bytes(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise TrainingHistoryError("history file shortened while reading")
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _strict_jsonl_load_bytes(data: bytes, *, source: Path) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrainingHistoryError(f"cannot read {source}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise TrainingHistoryError(f"blank JSONL record at {source}:{number}")
        row = strict_json_loads(line, source=f"{source}:{number}")
        if not isinstance(row, dict):
            raise TrainingHistoryError(f"JSONL record is not an object at {source}:{number}")
        rows.append(row)
    return rows


def select_best(
    rows: Sequence[Mapping[str, Any]],
    selector: str = "selector_value",
    direction: str = "min",
) -> Mapping[str, Any]:
    """Return the primary-selector winner, retaining the earliest exact tie."""
    if direction not in {"min", "max"}:
        raise TrainingHistoryError("selector direction must be 'min' or 'max'")
    if not rows:
        raise TrainingHistoryError("cannot select from an empty history")
    winner: Mapping[str, Any] | None = None
    winner_value = 0.0
    for row in rows:
        value = _nested_value(row, selector)
        _finite_number(value, selector)
        if winner is None or (value < winner_value if direction == "min" else value > winner_value):
            winner = row
            winner_value = float(value)
    assert winner is not None
    return winner


def expected_best_flags(
    rows: Sequence[Mapping[str, Any]], selector: str = "selector_value", direction: str = "min"
) -> list[bool]:
    flags: list[bool] = []
    best: float | None = None
    for row in rows:
        value = float(_nested_value(row, selector))
        improved = best is None or (value < best if direction == "min" else value > best)
        flags.append(improved)
        if improved:
            best = value
    return flags


def compute_degradation(
    losses: Sequence[float],
    selectors: Sequence[float],
    *,
    direction: str,
    absolute_warning_threshold: float,
) -> dict[str, Any]:
    """Compute the binding loss/selector degradation fields and warnings."""
    if not losses or not selectors:
        raise TrainingHistoryError("degradation requires nonempty loss and selector series")
    for name, values in (("loss", losses), ("selector", selectors)):
        for value in values:
            _finite_number(value, name)
    if direction not in {"min", "max"}:
        raise TrainingHistoryError("selector direction must be 'min' or 'max'")
    best_loss = min(losses)
    last_loss = losses[-1]
    absolute = last_loss - best_loss
    zero_best = best_loss == 0
    if best_loss > 0:
        ratio: float | None = absolute / best_loss
    elif last_loss == 0:
        ratio = 0.0
    else:
        ratio = None
    best_selector = min(selectors) if direction == "min" else max(selectors)
    degradation = selectors[-1] - best_selector if direction == "min" else best_selector - selectors[-1]
    warnings: list[str] = []
    if ratio is None:
        if absolute > absolute_warning_threshold:
            warnings.append("OVERFIT_WARN")
    elif ratio > 0.25:
        warnings.append("STRONG_OVERFIT")
    elif ratio > 0.10:
        warnings.append("OVERFIT_WARN")
    return {
        "best_loss": best_loss,
        "last_val_loss": last_loss,
        "loss_degradation_ratio": ratio,
        "loss_degradation_absolute": absolute,
        "ZERO_BEST_LOSS": zero_best,
        "selector_degradation": degradation,
        "warnings": warnings,
    }


def validate_resume_metadata(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    resume: Mapping[str, Any],
    *,
    validation_readback: Mapping[str, Any] | None = None,
    validation_receipt: Mapping[str, Any] | None = None,
) -> None:
    """Validate a complete-state same-run resume envelope."""
    errors: list[str] = []
    required_state = {"model", "optimizer", "scheduler", "scaler", "rng", "sampler", "best_state"}
    if resume.get("kind") != "resume":
        errors.append("resume checkpoint kind must be 'resume'")
    if resume.get("run_id") != manifest.get("run_id"):
        errors.append("resume run_id mismatch")
    for field in ("epoch", "global_step"):
        try:
            _strict_int(resume.get(field), f"resume {field}", minimum=1)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
    if isinstance(resume.get("epoch"), int) and not isinstance(resume.get("epoch"), bool):
        if resume.get("next_epoch") != resume["epoch"] + 1:
            errors.append("resume next epoch is not contiguous")
    if isinstance(resume.get("global_step"), int) and not isinstance(resume.get("global_step"), bool):
        if resume.get("next_global_step") != resume["global_step"] + 1:
            errors.append("resume next global step is not contiguous")
    for field in (
        "config_sha256",
        "input_manifest_sha256",
        "split_sha256",
        "code_tree_sha256",
        "warm_start_checkpoint_sha256",
    ):
        expected = manifest.get(field)
        if resume.get(field) != expected:
            errors.append(f"resume {field} mismatch")
    state = resume.get("state")
    resume_schema_errors: list[str] = []
    resume_expected_state = _state_entries(
        manifest.get("model_state_schema"), resume_schema_errors, "resume manifest model"
    )
    errors.extend(resume_schema_errors)
    _validate_model_tensor_state(resume, resume_expected_state, "resume", errors)
    if not isinstance(state, Mapping) or set(state) != required_state:
        errors.append(f"resume state must contain {sorted(required_state)}")
    else:
        typed = {
            "model": "model_state_dict",
            "optimizer": "optimizer_state_dict",
            "scheduler": "scheduler_state_dict",
            "scaler": "amp_scaler_state",
            "sampler": "sampler_state",
        }
        for name, expected_type in typed.items():
            _validate_hashed_state_payload(state.get(name), expected_type, f"resume {name}", errors)
        model_payload = state.get("model", {}).get("payload") if isinstance(state.get("model"), Mapping) else None
        if not isinstance(model_payload, Mapping) or not _strict_equal(
            model_payload.get("state_dict"), resume.get("model_state")
        ):
            errors.append("resume model state payload does not match loaded checkpoint tensors")
        rng = state.get("rng")
        rng_fields = {"python", "numpy", "torch_cpu", "torch_cuda"}
        if not isinstance(rng, Mapping) or set(rng) != rng_fields:
            errors.append("resume RNG state must contain exact Python/NumPy/Torch CPU/CUDA payloads")
        else:
            for name in sorted(rng_fields):
                _validate_rng_payload(rng[name], f"resume RNG {name}", errors)
    if not rows:
        errors.append("resume requires a nonempty history prefix")
    else:
        last = rows[-1]
        if resume.get("epoch") != last.get("epoch") or resume.get("global_step") != last.get("global_step"):
            errors.append("resume epoch/global_step does not match history tail")
        if isinstance(state, Mapping) and isinstance(state.get("best_state"), Mapping):
            final = manifest.get("final_selection", {})
            expected_best = {
                "epoch": final.get("fixed_epoch", final.get("epoch")),
                "selector_value": final.get("selector_value"),
                "checkpoint_sha256": final.get("checkpoint_sha256"),
            }
            if not _strict_equal(state["best_state"], expected_best):
                errors.append("resume best_state does not match final selection")
    prefix = resume.get("history_prefix_sha256")
    if not _is_sha256(prefix):
        errors.append("resume history prefix must be SHA256")
    expected_prefix = manifest.get("history_prefix_sha256")
    if expected_prefix is not None and prefix != expected_prefix:
        errors.append("resume history prefix SHA256 mismatch")
    _validate_snapshot(
        manifest.get("validation_snapshot"),
        errors,
        final_refit=manifest.get("run_kind") == "final_refit",
    )
    snapshot_hash = (
        None if manifest.get("validation_snapshot") is None else canonical_sha256(manifest["validation_snapshot"])
    )
    if resume.get("validation_snapshot_sha256") != snapshot_hash:
        errors.append("resume validation snapshot hash mismatch")
    receipt = validation_receipt
    if receipt is None and validation_readback is not None:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "run_id": manifest.get("run_id"),
            "epoch": resume.get("epoch"),
            "global_step": resume.get("global_step"),
            "validation_snapshot_sha256": snapshot_hash,
            "expected": resume.get("validation_metrics"),
            "actual": validation_readback,
            "tolerances": manifest.get("validation_tolerances", {}),
        }
    _validate_validation_receipt(manifest, rows, resume, receipt, errors)
    if errors:
        raise GateValidationError(errors)


def validate_warm_start(manifest: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
    """Validate strict full-model or strict predeclared-submodule warm start."""
    warm = manifest.get("warm_start")
    if warm is None:
        if manifest.get("warm_start_checkpoint_sha256") is not None:
            raise GateValidationError("warm_start metadata missing")
        return
    if not isinstance(warm, Mapping):
        raise GateValidationError("warm_start must be an object")
    errors: list[str] = []
    mode = warm.get("mode")
    if mode not in {"full_strict", "submodule_strict"}:
        errors.append("warm-start mode must be full_strict or submodule_strict")
    if any(warm.get(field) is not True for field in ("optimizer_reset", "scheduler_reset", "scaler_reset")):
        errors.append("warm-start must explicitly reset optimizer/scheduler/scaler state")
    if metadata.get("checkpoint_sha256") != manifest.get("warm_start_checkpoint_sha256"):
        errors.append("warm-start checkpoint hash mismatch")
    if (
        metadata.get("format") != CHECKPOINT_FORMAT
        or not _is_schema_version(metadata.get("schema_version"))
        or metadata.get("run_id") != warm.get("source_run_id")
        or metadata.get("kind") != warm.get("source_kind")
    ):
        errors.append("warm-start loaded checkpoint envelope/source mismatch")
    expected_keys = warm.get("expected_keys")
    actual_entries = metadata.get("state_keys")
    if (
        not isinstance(expected_keys, list)
        or expected_keys != sorted(expected_keys)
        or len(expected_keys) != len(set(expected_keys))
    ):
        errors.append("warm-start expected_keys must be a unique sorted list")
    actual_by_name = _state_entries(actual_entries, errors, "warm-start")
    _validate_model_tensor_state(metadata, actual_by_name, "warm-start", errors)
    if isinstance(expected_keys, list):
        expected_hash = sha256_bytes(canonical_json_bytes(expected_keys))
        if warm.get("expected_keys_sha256") != expected_hash:
            errors.append("warm-start expected key-list hash mismatch")
        if set(actual_by_name) != set(expected_keys):
            errors.append("warm-start key mismatch")
    target_errors: list[str] = []
    target_by_name = _state_entries(manifest.get("model_state_schema"), target_errors, "warm-start target model")
    errors.extend(target_errors)
    expected_specs = warm.get("key_specs")
    if isinstance(expected_specs, Mapping):
        if not isinstance(expected_keys, list) or set(expected_specs) != set(expected_keys):
            errors.append("warm-start key_specs must exactly cover expected_keys")
        for key, spec in expected_specs.items():
            if actual_by_name.get(key) != spec:
                errors.append(f"warm-start shape/dtype mismatch for {key}")
            if target_by_name.get(key) != spec:
                errors.append(f"warm-start target shape/dtype mismatch for {key}")
    else:
        errors.append("warm-start key_specs missing")
    if mode == "submodule_strict":
        prefixes = warm.get("allowed_prefixes")
        if (
            not isinstance(prefixes, list)
            or not prefixes
            or prefixes != sorted(prefixes)
            or len(prefixes) != len(set(prefixes))
            or not all(isinstance(p, str) and p for p in prefixes)
        ):
            errors.append("submodule warm-start requires allowed_prefixes")
        elif isinstance(expected_keys, list) and any(
            not any(key.startswith(p) for p in prefixes) for key in expected_keys
        ):
            errors.append("warm-start key outside allowed prefix")
        new_keys = warm.get("new_keys")
        if not isinstance(new_keys, list) or new_keys != sorted(new_keys) or len(new_keys) != len(set(new_keys)):
            errors.append("submodule warm-start new_keys must be sorted")
        elif warm.get("new_keys_sha256") != sha256_bytes(canonical_json_bytes(new_keys)):
            errors.append("warm-start new key-list hash mismatch")
        if (
            isinstance(expected_keys, list)
            and isinstance(new_keys, list)
            and set(expected_keys).isdisjoint(new_keys)
            and set(expected_keys) | set(new_keys) != set(target_by_name)
        ):
            errors.append("submodule warm-start loaded/new keys do not cover the target model")
        if (
            isinstance(expected_keys, list)
            and isinstance(new_keys, list)
            and not set(expected_keys).isdisjoint(new_keys)
        ):
            errors.append("submodule warm-start loaded and new keys must be disjoint")
    elif mode == "full_strict" and warm.get("new_keys") not in (None, []):
        errors.append("full_strict warm-start cannot declare new keys")
    elif mode == "full_strict" and isinstance(expected_keys, list) and set(expected_keys) != set(target_by_name):
        errors.append("full_strict warm-start keys do not cover the complete target model")
    if mode == "full_strict" and any(field in warm for field in ("allowed_prefixes", "new_keys_sha256")):
        errors.append("full_strict warm-start must not contain submodule-only prefix/new-key hash fields")
    if errors:
        raise GateValidationError(errors)


CheckpointMetadataLoader = Callable[[Path], Mapping[str, Any]]


def _verify_training_run(
    run_dir: str | os.PathLike[str],
    *,
    checkpoint_metadata_loader: CheckpointMetadataLoader | None = None,
    parent_cv_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a canonical report. Any uncertainty becomes a ``FAIL`` error."""
    root = Path(run_dir)
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    try:
        if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root.absolute():
            raise TrainingHistoryError("run directory must be a real directory, not a symlink")
        manifest_path = _contained_regular_file(root, "run_manifest.json")
        artifacts_path = _contained_regular_file(root, "ARTIFACT_MANIFEST.json")
        manifest = _object(strict_json_load(manifest_path), "run_manifest.json")
        artifacts = _object(strict_json_load(artifacts_path), "ARTIFACT_MANIFEST.json")
        _validate_manifest(manifest, errors)
        _validate_artifacts(root, artifacts, errors, is_cv=manifest.get("run_kind") == "cv")
        if artifacts.get("run_id") != manifest.get("run_id"):
            errors.append("artifact manifest run_id mismatch")
        _validate_hash_sources(root, manifest, errors)
        kind = manifest.get("run_kind")
        if kind == "cv":
            _validate_cv_root(root, manifest, artifacts, checkpoint_metadata_loader, errors, warnings, details)
            expected = "PASS" if manifest.get("purpose") == "candidate" else "DIAGNOSTIC_ONLY"
        else:
            rows = strict_jsonl_load(_contained_regular_file(root, "history.jsonl"))
            _validate_history(root, manifest, rows, errors, warnings, details)
            _validate_checkpoints(root, manifest, rows, artifacts, checkpoint_metadata_loader, errors)
            if manifest.get("warm_start") is not None:
                warm_relative = manifest.get("hash_sources", {}).get("warm_start_checkpoint_sha256")
                if isinstance(warm_relative, str):
                    warm_path = _contained_regular_file(root, warm_relative)
                    warm_meta = _load_checkpoint_metadata(warm_path, checkpoint_metadata_loader)
                    validate_warm_start(manifest, warm_meta)
            if kind == "final_refit":
                expected = "CV_DERIVED_REFIT_ONLY"
                if parent_cv_context is not None:
                    _validate_final_refit_context(root, manifest, parent_cv_context, errors)
            elif manifest.get("purpose") == "diagnostic":
                expected = "DIAGNOSTIC_ONLY"
            else:
                expected = "PASS"
        declared = artifacts.get("verdict")
        if declared != expected:
            errors.append(f"artifact verdict mismatch: expected {expected}, got {declared!r}")
    except Exception as exc:
        if isinstance(exc, GateValidationError):
            errors.extend(exc.errors)
        else:
            errors.append(str(exc))
        manifest = locals().get("manifest", {})
        expected = "FAIL"
    verdict = "FAIL" if errors else expected
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest.get("run_id") if isinstance(manifest, Mapping) else None,
        "verdict": verdict,
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "details": details,
    }
    return report


def verify_training_run(
    run_dir: str | os.PathLike[str],
    *,
    checkpoint_metadata_loader: CheckpointMetadataLoader | None = None,
) -> dict[str, Any]:
    """Verify a run; final-refit parent authority is only established by CV-root recursion."""
    return _verify_training_run(run_dir, checkpoint_metadata_loader=checkpoint_metadata_loader)


def validate_training_run(
    run_dir: str | os.PathLike[str],
    *,
    checkpoint_metadata_loader: CheckpointMetadataLoader | None = None,
) -> dict[str, Any]:
    """Verify a run and raise :class:`GateValidationError` on ``FAIL``."""
    report = verify_training_run(
        run_dir,
        checkpoint_metadata_loader=checkpoint_metadata_loader,
    )
    if report["verdict"] != "PASS":
        errors = report["errors"] or [f"non-promotable training-run verdict: {report['verdict']}"]
        raise GateValidationError(errors)
    return report


validate_run = validate_training_run


def execution_config_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash every manifest field that can change training or gate semantics."""
    snapshot = manifest.get("validation_snapshot")
    validation_runtime = None
    if isinstance(snapshot, Mapping):
        validation_runtime = {
            field: snapshot.get(field)
            for field in (
                "preprocessing_config",
                "seed",
                "allowed_environment",
                "device",
                "dtype",
                "framework_version",
                "shuffle",
                "augmentation",
            )
        }
    fields = (
        "purpose",
        "run_kind",
        "phase",
        "cli",
        "allowed_environment",
        "model_config",
        "model_state_schema",
        "loss_config",
        "optimizer_config",
        "scheduler_config",
        "seed",
        "dependencies",
        "hardware",
        "selector",
        "loss_component_profile",
        "nullable_loss_components",
        "total_loss",
        "sampler",
        "gradient",
        "resume_validation_contract",
        "acceptance_thresholds",
        "task_type",
        "warm_start",
        "training_sources",
        "cv",
    )
    payload = {field: manifest.get(field) for field in fields}
    payload["validation_runtime"] = validation_runtime
    return canonical_sha256(payload)


def _training_semantics_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash the training semantics that must be identical across CV folds/root."""
    snapshot = manifest.get("validation_snapshot")
    validation_runtime = None
    if isinstance(snapshot, Mapping):
        validation_runtime = {
            field: snapshot.get(field)
            for field in (
                "preprocessing_config",
                "seed",
                "allowed_environment",
                "device",
                "dtype",
                "framework_version",
                "shuffle",
                "augmentation",
            )
        }
    fields = (
        "phase",
        "cli",
        "allowed_environment",
        "model_config",
        "model_state_schema",
        "loss_config",
        "optimizer_config",
        "scheduler_config",
        "seed",
        "dependencies",
        "hardware",
        "loss_component_profile",
        "nullable_loss_components",
        "total_loss",
        "sampler",
        "gradient",
        "resume_validation_contract",
        "task_type",
        "warm_start",
        "training_sources",
    )
    payload = {field: manifest.get(field) for field in fields}
    payload["validation_runtime"] = validation_runtime
    return canonical_sha256(payload)


def _validate_manifest(manifest: Mapping[str, Any], errors: list[str]) -> None:
    required = {
        "schema_version",
        "run_id",
        "purpose",
        "run_kind",
        "phase",
        "fold_id",
        "git_sha",
        "code_tree_sha256",
        "config_sha256",
        "cli",
        "allowed_environment",
        "model_config",
        "loss_config",
        "optimizer_config",
        "scheduler_config",
        "seed",
        "dependencies",
        "hardware",
        "input_manifest_sha256",
        "split_sha256",
        "warm_start_checkpoint_sha256",
        "selector",
        "loss_component_profile",
        "nullable_loss_components",
        "total_loss",
        "validation_snapshot",
        "acceptance_thresholds",
        "split",
        "final_selection",
        "degradation",
        "model_state_schema",
        "hash_sources",
        "sampler",
        "gradient",
        "resume_validation_contract",
        "checkpoint_refs",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        errors.append(f"manifest missing fields: {missing}")
    optional = {
        "task_type",
        "validation_tolerances",
        "warm_start",
        "training_sources",
        "min_val_loss_selection",
        "parent_cv",
        "cv",
        "history_prefix_sha256",
    }
    extra = sorted(set(manifest) - required - optional)
    if extra:
        errors.append(f"manifest contains unknown fields: {extra}")
    if not _is_schema_version(manifest.get("schema_version")):
        errors.append("unsupported manifest schema_version")
    if manifest.get("purpose") not in {"candidate", "diagnostic"}:
        errors.append("purpose must be candidate or diagnostic")
    if manifest.get("run_kind") not in {"single_split", "cv", "final_refit"}:
        errors.append("invalid run_kind")
    elif manifest.get("run_kind") == "cv":
        if "cv" not in manifest or "parent_cv" in manifest:
            errors.append("CV root must contain cv and must not contain parent_cv")
    elif manifest.get("run_kind") == "final_refit":
        if "parent_cv" not in manifest or "cv" in manifest:
            errors.append("final-refit must contain parent_cv and must not contain cv")
    elif manifest.get("fold_id") is None:
        if "parent_cv" in manifest or "cv" in manifest:
            errors.append("standalone single_split must not contain CV parent/root fields")
    elif "parent_cv" not in manifest or "cv" in manifest:
        errors.append("CV fold must contain parent_cv and must not contain cv")
    if manifest.get("run_kind") == "final_refit" and set(manifest.get("loss_component_profile", {})) != {"train"}:
        errors.append("final-refit loss component profile must be train-only")
    for field in ("run_id", "phase", "git_sha", "cli"):
        if not isinstance(manifest.get(field), str) or not manifest.get(field):
            errors.append(f"manifest {field} must be a nonempty string")
    try:
        _strict_int(manifest.get("seed"), "manifest seed", minimum=0)
    except TrainingHistoryError as exc:
        errors.append(str(exc))
    fold_id = manifest.get("fold_id")
    if fold_id is not None and (not isinstance(fold_id, str) or not fold_id):
        errors.append("fold_id must be null or nonempty string")
    for field in (
        "allowed_environment",
        "model_config",
        "loss_config",
        "optimizer_config",
        "scheduler_config",
        "dependencies",
        "hardware",
    ):
        if not isinstance(manifest.get(field), Mapping):
            errors.append(f"manifest {field} must be an object")
    for field in ("code_tree_sha256", "config_sha256", "input_manifest_sha256", "split_sha256"):
        if not _is_sha256(manifest.get(field)):
            errors.append(f"manifest {field} must be SHA256")
    if manifest.get("config_sha256") != execution_config_sha256(manifest):
        errors.append("config_sha256 does not match complete execution/gate semantics")
    if isinstance(manifest.get("split"), Mapping) and manifest.get("split_sha256") != canonical_sha256(
        manifest["split"]
    ):
        errors.append("split_sha256 does not match split manifest")
    warm_hash = manifest.get("warm_start_checkpoint_sha256")
    if warm_hash is not None and not _is_sha256(warm_hash):
        errors.append("warm_start_checkpoint_sha256 must be null or SHA256")
    selector = manifest.get("selector")
    if manifest.get("run_kind") == "final_refit":
        if selector is not None:
            errors.append("final-refit selector must be null")
    elif not isinstance(selector, Mapping):
        errors.append("selector must be an object")
    else:
        if selector.get("direction") not in {"min", "max"}:
            errors.append("selector direction must be min or max")
        if selector.get("tie_rule") != "earliest":
            errors.append("selector tie_rule must be earliest")
        if not isinstance(selector.get("field"), str):
            errors.append("selector field missing")
        selector_kind = selector.get("kind")
        field = selector.get("field")
        if selector_kind == "validation_loss":
            if selector.get("direction") != "min" or field != "val.losses.total_loss.value":
                errors.append("validation-loss selector must minimize val.losses.total_loss.value")
        elif selector_kind == "grouped_validation_metric":
            if not isinstance(field, str) or not field.startswith("task_metrics."):
                errors.append("grouped validation selector must reference task_metrics")
        elif selector_kind == "oof_metric" and manifest.get("run_kind") == "cv":
            if not isinstance(field, str) or not field:
                errors.append("OOF selector field missing")
        else:
            errors.append("selector kind is invalid for run kind")
    _validate_snapshot(
        manifest.get("validation_snapshot"), errors, final_refit=manifest.get("run_kind") == "final_refit"
    )
    snapshot = manifest.get("validation_snapshot")
    if isinstance(snapshot, Mapping):
        for field in ("input_manifest_sha256", "split_sha256"):
            if snapshot.get(field) != manifest.get(field):
                errors.append(f"validation_snapshot {field} mismatch")
        if snapshot.get("allowed_environment") != manifest.get("allowed_environment"):
            errors.append("validation_snapshot allowed_environment mismatch")
        if snapshot.get("seed") != manifest.get("seed"):
            errors.append("validation_snapshot seed mismatch")
    sampler = manifest.get("sampler")
    if not isinstance(sampler, Mapping) or sampler.get("mode") not in {"serialized", "epoch_derived"}:
        errors.append("sampler must use serialized or epoch_derived deterministic state")
    elif sampler.get("mode") == "epoch_derived" and (
        not sampler.get("seed_formula") or not _is_sha256(sampler.get("index_order_sha256"))
    ):
        errors.append("epoch-derived sampler requires seed formula and index-order hash")
    gradient = manifest.get("gradient")
    if (
        not isinstance(gradient, Mapping)
        or not _is_finite_number(gradient.get("clip_threshold"))
        or gradient.get("clip_threshold") <= 0
    ):
        errors.append("gradient clip_threshold must be finite and pinned")
    total_name = manifest.get("total_loss", {}).get("name") if isinstance(manifest.get("total_loss"), Mapping) else None
    profiles = manifest.get("loss_component_profile")
    expected_sides = ("train",) if manifest.get("run_kind") == "final_refit" else ("train", "val")
    if not isinstance(profiles, Mapping) or set(profiles) != set(expected_sides):
        errors.append("loss component profile side schema mismatch")
    else:
        for side in expected_sides:
            total_profile = profiles.get(side, {}).get(total_name) if isinstance(profiles.get(side), Mapping) else None
            if not isinstance(total_profile, Mapping) or total_profile.get("required") is not True:
                errors.append(f"{side} total-loss component must be required")
    total_contract = manifest.get("total_loss")
    loss_config = manifest.get("loss_config")
    if isinstance(total_contract, Mapping) and isinstance(loss_config, Mapping):
        weights = total_contract.get("weights")
        configured = loss_config.get("weights", loss_config)
        if (
            not isinstance(weights, Mapping)
            or not isinstance(configured, Mapping)
            or any(
                name not in configured or not _strict_equal(configured.get(name), value)
                for name, value in weights.items()
            )
        ):
            errors.append("total-loss weights do not exactly match loss_config")
    nullable = manifest.get("nullable_loss_components", {})
    if not isinstance(nullable, Mapping) or set(nullable) - set(expected_sides):
        errors.append("nullable_loss_components side schema invalid")
    elif isinstance(profiles, Mapping):
        for side, declarations in nullable.items():
            if not isinstance(declarations, Mapping):
                errors.append(f"nullable_loss_components.{side} must be an object")
                continue
            side_profile = profiles.get(side, {})
            for component, declaration in declarations.items():
                profile_entry = side_profile.get(component) if isinstance(side_profile, Mapping) else None
                if not isinstance(profile_entry, Mapping) or profile_entry.get("required") is not False:
                    errors.append(f"nullable declaration is not for an optional component: {side}.{component}")
                if (
                    not isinstance(declaration, Mapping)
                    or set(declaration) != {"reason", "zero_count"}
                    or not isinstance(declaration.get("reason"), str)
                    or not declaration.get("reason")
                    or not isinstance(declaration.get("zero_count"), int)
                    or isinstance(declaration.get("zero_count"), bool)
                    or declaration.get("zero_count") != 0
                ):
                    errors.append(f"nullable declaration malformed: {side}.{component}")
    _validate_split(manifest, errors)


def _validate_snapshot(snapshot: Any, errors: list[str], *, final_refit: bool = False) -> None:
    if final_refit and snapshot is None:
        return
    fields = {
        "example_ids",
        "input_manifest_sha256",
        "split_sha256",
        "preprocessing_config",
        "seed",
        "allowed_environment",
        "device",
        "dtype",
        "framework_version",
        "shuffle",
        "augmentation",
    }
    if not isinstance(snapshot, Mapping):
        errors.append("deterministic validation_snapshot required")
        return
    missing = fields - snapshot.keys()
    if missing:
        errors.append(f"validation_snapshot missing fields: {sorted(missing)}")
    if snapshot.get("shuffle") is not False or snapshot.get("augmentation") is not False:
        errors.append("validation snapshot must disable shuffle and augmentation")
    try:
        _strict_int(snapshot.get("seed"), "validation snapshot seed", minimum=0)
    except TrainingHistoryError as exc:
        errors.append(str(exc))
    for field in ("input_manifest_sha256", "split_sha256"):
        if not _is_sha256(snapshot.get(field)):
            errors.append(f"validation snapshot {field} must be SHA256")
    for field in ("device", "dtype", "framework_version"):
        if not isinstance(snapshot.get(field), str) or not snapshot.get(field):
            errors.append(f"validation snapshot {field} must be nonempty string")
    if not isinstance(snapshot.get("preprocessing_config"), Mapping) or not isinstance(
        snapshot.get("allowed_environment"), Mapping
    ):
        errors.append("validation snapshot preprocessing/environment must be objects")
    ids = snapshot.get("example_ids")
    if (
        not isinstance(ids, list)
        or not ids
        or not all(isinstance(item, str) and item for item in ids)
        or len(ids) != len(set(ids))
    ):
        errors.append("validation snapshot example_ids must be an ordered unique list")


def _validate_split(manifest: Mapping[str, Any], errors: list[str]) -> None:
    split = manifest.get("split")
    if not isinstance(split, Mapping) or set(split) != {"train", "validation"}:
        errors.append("split must contain exactly train and validation")
        return
    train, val = split.get("train"), split.get("validation")
    if manifest.get("run_kind") == "final_refit":
        if val is not None:
            errors.append("final-refit validation split must be null")
        _validate_split_side(train, "train", errors, binary=False)
        return
    _validate_split_side(train, "train", errors, binary=manifest.get("task_type") == "binary_classification")
    _validate_split_side(val, "validation", errors, binary=manifest.get("task_type") == "binary_classification")
    if isinstance(train, Mapping) and isinstance(val, Mapping):
        train_stems, val_stems = train.get("stems"), val.get("stems")
        if isinstance(train_stems, list) and isinstance(val_stems, list) and set(train_stems) & set(val_stems):
            errors.append("train/validation stem overlap")
        train_ids, val_ids = train.get("example_ids"), val.get("example_ids")
        if isinstance(train_ids, list) and isinstance(val_ids, list) and set(train_ids) & set(val_ids):
            errors.append("train/validation example ID overlap")
        snapshot = manifest.get("validation_snapshot")
        if isinstance(snapshot, Mapping) and snapshot.get("example_ids") != val.get("example_ids"):
            errors.append("validation snapshot IDs/order/count differ from split")


def _validate_split_side(side: Any, label: str, errors: list[str], *, binary: bool) -> None:
    required = {"stems", "videos", "examples", "batches", "lineages", "example_ids"}
    if not isinstance(side, Mapping) or not required.issubset(side):
        errors.append(f"split {label} summary is malformed")
        return
    stems = side.get("stems")
    ids = side.get("example_ids")
    if (
        not isinstance(stems, list)
        or not stems
        or not all(isinstance(item, str) and item for item in stems)
        or len(stems) != len(set(stems))
    ):
        errors.append(f"split {label} stems must be nonempty unique strings")
    try:
        videos = _strict_int(side.get("videos"), f"split {label} videos", minimum=1)
        examples = _strict_int(side.get("examples"), f"split {label} examples", minimum=1)
        _strict_int(side.get("batches"), f"split {label} batches", minimum=1)
    except TrainingHistoryError as exc:
        errors.append(str(exc))
        return
    if isinstance(stems, list) and videos != len(stems):
        errors.append(f"split {label} videos must equal stem count")
    if (
        not isinstance(ids, list)
        or len(ids) != examples
        or len(ids) != len(set(ids))
        or not all(isinstance(item, str) and item for item in ids)
    ):
        errors.append(f"split {label} example IDs must be unique strings matching examples")
    lineage = side.get("lineages")
    if not isinstance(lineage, Mapping) or set(lineage) != {"44b6", "6bba"}:
        errors.append(f"split {label} lineage counts malformed")
    else:
        counts = list(lineage.values())
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in counts):
            errors.append(f"split {label} lineage counts must be positive integers")
        elif sum(counts) != examples:
            errors.append(f"split {label} lineage counts must sum to examples")
    if binary:
        positive, negative = side.get("positive"), side.get("negative")
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in (positive, negative)):
            errors.append(f"binary split {label} counts must be positive integers")
        elif positive + negative != examples:
            errors.append(f"binary split {label} positive/negative counts must sum to examples")
    denominator_counts = side.get("denominator_counts")
    if denominator_counts is not None and (
        not isinstance(denominator_counts, Mapping)
        or not denominator_counts
        or any(
            not isinstance(name, str) or not name or not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for name, value in denominator_counts.items()
        )
    ):
        errors.append(f"split {label} denominator_counts must be positive named integer populations")


def _validate_hash_sources(root: Path, manifest: Mapping[str, Any], errors: list[str]) -> None:
    sources = manifest.get("hash_sources")
    if not isinstance(sources, Mapping):
        errors.append("hash_sources must pin code and input source artifacts")
        return
    required = {"code_tree_sha256", "input_manifest_sha256"}
    if manifest.get("warm_start_checkpoint_sha256") is not None:
        required.add("warm_start_checkpoint_sha256")
    for field in required:
        relative = sources.get(field)
        if not isinstance(relative, str) or not _safe_relative_path(relative):
            errors.append(f"hash source path missing/unsafe for {field}")
            continue
        try:
            path = _contained_regular_file(root, relative)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
            continue
        if sha256_file(path) != manifest.get(field):
            errors.append(f"hash source mismatch for {field}")
    training_sources = manifest.get("training_sources")
    if training_sources is not None:
        if not isinstance(training_sources, Mapping):
            errors.append("training_sources must be an object")
        else:
            for name in ("wrapper", "support_trainer"):
                source = training_sources.get(name)
                if not isinstance(source, Mapping):
                    errors.append(f"training source missing: {name}")
                    continue
                relative = source.get("path")
                if not isinstance(relative, str) or not _safe_relative_path(relative):
                    errors.append(f"training source hash mismatch: {name}")
                    continue
                try:
                    source_path = _contained_regular_file(root, relative)
                except TrainingHistoryError as exc:
                    errors.append(str(exc))
                    continue
                if source.get("sha256") != sha256_file(source_path):
                    errors.append(f"training source hash mismatch: {name}")
    readout = manifest.get("acceptance_thresholds", {}).get("per_video")
    if isinstance(readout, Mapping) and isinstance(readout.get("path"), str):
        relative = readout["path"]
        if not _safe_relative_path(relative):
            errors.append("per-video readout artifact hash mismatch")
        else:
            try:
                readout_path = _contained_regular_file(root, relative)
                if readout.get("sha256") != sha256_file(readout_path):
                    errors.append("per-video readout artifact hash mismatch")
            except TrainingHistoryError as exc:
                errors.append(str(exc))


def _validate_history(
    root: Path,
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    errors: list[str],
    warnings: list[str],
    details: dict[str, Any],
) -> None:
    purpose = manifest.get("purpose")
    kind = manifest.get("run_kind")
    if not rows:
        errors.append("history is empty")
        return
    if purpose == "candidate" and kind != "final_refit" and len(rows) < 3:
        errors.append("candidate requires at least 3 complete validation epochs")
    previous_step = 0
    identity = ("schema_version", "run_id", "purpose", "run_kind", "phase", "fold_id")
    for index, row in enumerate(rows, 1):
        missing = {
            "schema_version",
            "run_id",
            "purpose",
            "run_kind",
            "phase",
            "fold_id",
            "epoch",
            "global_step",
            "lr",
            "epoch_seconds",
            "train_batches",
            "train_examples",
            "val_batches",
            "val_examples",
            "train",
            "val",
            "val_by_lineage",
            "task_metrics",
            "grad_norm_pre_clip",
            "nonfinite_count",
            "selector_value",
            "best_so_far",
            "checkpoint_sha256",
        } - row.keys()
        if missing:
            errors.append(f"epoch {index} missing fields: {sorted(missing)}")
            continue
        for field in identity:
            if row.get(field) != manifest.get(field):
                errors.append(f"epoch {index} {field} does not match manifest")
        if not _is_schema_version(row.get("schema_version")):
            errors.append(f"epoch {index} schema_version invalid")
        if not isinstance(row.get("epoch"), int) or isinstance(row.get("epoch"), bool) or row.get("epoch") != index:
            errors.append(f"epoch sequence mismatch at record {index}")
        step = row.get("global_step")
        if not isinstance(step, int) or isinstance(step, bool) or step <= previous_step:
            errors.append(f"epoch {index} global_step is not strictly increasing")
            step_delta = None
        else:
            step_delta = step - previous_step
            previous_step = step
        for field in ("lr", "epoch_seconds"):
            _collect_finite_nonnegative(row.get(field), f"epoch {index} {field}", errors)
        for field in ("train_batches", "train_examples", "val_batches", "val_examples"):
            try:
                _strict_int(row.get(field), field, minimum=0)
            except TrainingHistoryError as exc:
                errors.append(f"epoch {index}: {exc}")
        if (
            not isinstance(row.get("nonfinite_count"), int)
            or isinstance(row.get("nonfinite_count"), bool)
            or row.get("nonfinite_count") != 0
        ):
            errors.append(f"epoch {index} nonfinite_count must be zero")
        _validate_losses(manifest, row, index, errors)
        _validate_grad(row.get("grad_norm_pre_clip"), step_delta, index, errors)
        if isinstance(row.get("grad_norm_pre_clip"), Mapping) and row["grad_norm_pre_clip"].get(
            "clip_threshold"
        ) != manifest.get("gradient", {}).get("clip_threshold"):
            errors.append(f"epoch {index} grad clip_threshold differs from manifest")
        _collect_numeric_tree(row.get("task_metrics"), f"epoch {index} task_metrics", errors)
        selector_value = row.get("selector_value")
        if kind == "final_refit":
            if selector_value is not None:
                errors.append(f"final-refit epoch {index} selector_value must be null")
            if row.get("val") is not None or row.get("val_by_lineage") is not None:
                errors.append(f"final-refit epoch {index} validation fields must be null")
            if row.get("val_batches") != 0 or row.get("val_examples") != 0:
                errors.append(f"final-refit epoch {index} validation counts must be zero")
        else:
            _collect_finite(row.get("selector_value"), f"epoch {index} selector_value", errors)
        checkpoint = row.get("checkpoint_sha256")
        if checkpoint is not None and not _is_sha256(checkpoint):
            errors.append(f"epoch {index} checkpoint_sha256 must be null or SHA256")
        if not isinstance(row.get("best_so_far"), bool):
            errors.append(f"epoch {index} best_so_far must be boolean")
        train_summary = manifest.get("split", {}).get("train", {})
        if isinstance(train_summary, Mapping) and (
            row.get("train_examples") != train_summary.get("examples")
            or row.get("train_batches") != train_summary.get("batches")
        ):
            errors.append(f"epoch {index} train batch/example coverage mismatch")
        val_summary = manifest.get("split", {}).get("validation")
        if (
            kind != "final_refit"
            and isinstance(val_summary, Mapping)
            and (
                row.get("val_examples") != val_summary.get("examples")
                or row.get("val_batches") != val_summary.get("batches")
            )
        ):
            errors.append(f"epoch {index} validation batch/example coverage mismatch")
    if kind != "final_refit":
        _validate_validation_coverage(manifest, rows, errors)
        _validate_selection(manifest, rows, errors, details)
        _validate_degradation(manifest, rows, errors, warnings, details)
        _validate_progression(root, manifest, rows, errors)
    else:
        _validate_final_refit(manifest, rows, errors, details)


def _validate_losses(manifest: Mapping[str, Any], row: Mapping[str, Any], epoch: int, errors: list[str]) -> None:
    profile = manifest.get("loss_component_profile")
    if not isinstance(profile, Mapping):
        errors.append("loss_component_profile must be an object")
        return
    kind = manifest.get("run_kind")
    for split_name in ("train", "val"):
        split = row.get(split_name)
        if kind == "final_refit" and split_name == "val":
            continue
        if not isinstance(split, Mapping) or not isinstance(split.get("losses"), Mapping):
            errors.append(f"epoch {epoch} {split_name}.losses missing")
            continue
        losses = split["losses"]
        split_profile = profile.get(split_name)
        if not isinstance(split_profile, Mapping):
            errors.append(f"loss profile missing {split_name}")
            continue
        if set(losses) != set(split_profile):
            errors.append(f"epoch {epoch} {split_name} component set differs from manifest profile")
        for component, required in split_profile.items():
            if not isinstance(required, Mapping) or set(required) != {
                "required",
                "reduction",
                "denominator_source",
            }:
                errors.append(
                    f"loss profile {split_name}.{component} must pin required, reduction, and denominator source"
                )
                continue
            is_required = required.get("required")
            expected_reduction = required.get("reduction")
            denominator_source = required.get("denominator_source")
            if (
                not isinstance(is_required, bool)
                or not isinstance(expected_reduction, str)
                or not expected_reduction
                or not isinstance(denominator_source, str)
                or not denominator_source
            ):
                errors.append(f"loss profile {split_name}.{component} required/reduction invalid")
                continue
            value = losses.get(component)
            zero = manifest.get("nullable_loss_components", {}).get(split_name, {}).get(component)
            if value is None:
                if is_required:
                    errors.append(f"epoch {epoch} required {split_name}.{component} is null")
                else:
                    if not isinstance(zero, Mapping) or not zero.get("reason") or zero.get("zero_count") != 0:
                        errors.append(f"nullable {split_name}.{component} lacks reason and zero_count=0")
                continue
            if not is_required and zero is not None:
                errors.append(f"epoch {epoch} {split_name}.{component} is present despite zero-population declaration")
            if not isinstance(value, Mapping) or set(value) != {"value", "numerator", "denominator", "reduction"}:
                errors.append(f"epoch {epoch} {split_name}.{component} has invalid component schema")
                continue
            for number in ("value", "numerator", "denominator"):
                _collect_finite_nonnegative(
                    value.get(number), f"epoch {epoch} {split_name}.{component}.{number}", errors
                )
            denominator = value.get("denominator")
            if not isinstance(denominator, int) or isinstance(denominator, bool) or denominator <= 0:
                errors.append(f"epoch {epoch} {split_name}.{component} denominator must be positive")
            elif _is_finite_number(value.get("value")) and _is_finite_number(value.get("numerator")):
                recomputed = value["numerator"] / denominator
                if not math.isclose(value["value"], recomputed, rel_tol=1e-12, abs_tol=1e-15):
                    errors.append(f"epoch {epoch} {split_name}.{component} value != numerator/denominator")
            try:
                expected_denominator = _expected_denominator(manifest, row, split_name, denominator_source)
            except TrainingHistoryError as exc:
                errors.append(f"epoch {epoch}: {exc}")
                expected_denominator = None
            if denominator != expected_denominator:
                errors.append(f"epoch {epoch} {split_name}.{component} denominator/count contract mismatch")
            if not isinstance(value.get("reduction"), str) or not value.get("reduction"):
                errors.append(f"epoch {epoch} {split_name}.{component} reduction missing")
            elif value.get("reduction") != expected_reduction:
                errors.append(f"epoch {epoch} {split_name}.{component} reduction differs from manifest")
        _validate_total_formula(manifest, losses, split_name, epoch, errors)


def _validate_total_formula(
    manifest: Mapping[str, Any], losses: Mapping[str, Any], split: str, epoch: int, errors: list[str]
) -> None:
    contract = manifest.get("total_loss")
    if not isinstance(contract, Mapping) or set(contract) != {
        "name",
        "components",
        "formula",
        "weights",
        "aggregation",
    }:
        errors.append("total_loss contract missing")
        return
    total_name = contract.get("name")
    total = losses.get(total_name)
    if total is None or not isinstance(total, Mapping):
        errors.append(f"epoch {epoch} {split} required total loss is missing/null")
        return
    components = contract.get("components")
    formula = contract.get("formula")
    weights = contract.get("weights", {})
    aggregation = contract.get("aggregation")
    if (
        not isinstance(total_name, str)
        or not total_name
        or not isinstance(components, list)
        or not components
        or len(components) != len(set(components))
        or not all(isinstance(name, str) and name and name != total_name for name in components)
        or not isinstance(formula, str)
        or not isinstance(weights, Mapping)
        or not all(isinstance(name, str) and name and _is_finite_number(value) for name, value in weights.items())
        or not isinstance(aggregation, Mapping)
        or set(aggregation) != {"denominator_source", "numerator_formula", "reduction"}
    ):
        errors.append(f"epoch {epoch} {split} total-loss aggregation contract malformed")
        return
    component_items = {name: losses.get(name) for name in components}
    if any(not isinstance(item, Mapping) for item in component_items.values()):
        errors.append(f"epoch {epoch} {split} total-loss component missing/null")
        return
    values = {name: item["value"] for name, item in component_items.items()}
    try:
        formula_names = _formula_names(formula)
        if formula_names != set(components) | set(weights):
            raise TrainingHistoryError("total-loss formula has unknown or unused component/weight names")
        if _formula_has_numeric_constants(formula):
            raise TrainingHistoryError("total-loss formula must name every numeric weight")
        expected = _safe_formula(formula, values | dict(weights))
        numerator_formula = aggregation.get("numerator_formula")
        if not isinstance(numerator_formula, str):
            raise TrainingHistoryError("total-loss numerator formula missing")
        numerator_values = {f"{name}_numerator": item["numerator"] for name, item in component_items.items()}
        if _formula_names(numerator_formula) != set(numerator_values) | set(weights):
            raise TrainingHistoryError("total-loss numerator formula has unknown or unused names")
        if _formula_has_numeric_constants(numerator_formula):
            raise TrainingHistoryError("total-loss numerator formula must name every numeric weight")
        expected_numerator = _safe_formula(numerator_formula, numerator_values | dict(weights))
    except Exception as exc:
        errors.append(f"epoch {epoch} {split} cannot recompute total-loss formula: {exc}")
        return
    if not math.isclose(total["value"], expected, rel_tol=1e-12, abs_tol=1e-15):
        errors.append(f"epoch {epoch} {split} total-loss formula/weight mismatch")
    if not math.isclose(total["numerator"], expected_numerator, rel_tol=1e-12, abs_tol=1e-15):
        errors.append(f"epoch {epoch} {split} total-loss numerator aggregation mismatch")
    denominator_source = aggregation.get("denominator_source")
    if not isinstance(denominator_source, str) or not denominator_source:
        errors.append(f"epoch {epoch} {split} total-loss denominator source invalid")
    else:
        try:
            expected_denominator = _expected_denominator(manifest, {}, split, denominator_source)
            if total["denominator"] != expected_denominator:
                errors.append(f"epoch {epoch} {split} total-loss denominator aggregation mismatch")
        except TrainingHistoryError as exc:
            errors.append(f"epoch {epoch} {split}: {exc}")
    if total.get("reduction") != aggregation.get("reduction"):
        errors.append(f"epoch {epoch} {split} total-loss aggregation reduction mismatch")


def _expected_denominator(manifest: Mapping[str, Any], row: Mapping[str, Any], split_name: str, source: str) -> Any:
    side_name = "train" if split_name == "train" else "validation"
    side = manifest.get("split", {}).get(side_name, {})
    if not isinstance(side, Mapping):
        raise TrainingHistoryError(f"split side missing for denominator source: {split_name}")
    if source in {"examples", "batches"}:
        row_prefix = "train" if split_name == "train" else "val"
        return row.get(f"{row_prefix}_{source}", side.get(source))
    counts = side.get("denominator_counts")
    if not isinstance(counts, Mapping) or source not in counts:
        raise TrainingHistoryError(f"unpinned denominator source: {split_name}.{source}")
    return counts[source]


def _formula_names(expression: str) -> set[str]:
    tree = ast.parse(expression, mode="eval")
    allowed_nodes = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.UnaryOp,
        ast.UAdd,
        ast.USub,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Load,
    )
    if any(not isinstance(node, allowed_nodes) for node in ast.walk(tree)):
        raise TrainingHistoryError("formula uses forbidden syntax")
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _formula_has_numeric_constants(expression: str) -> bool:
    tree = ast.parse(expression, mode="eval")
    return any(isinstance(node, ast.Constant) for node in ast.walk(tree))


def _safe_formula(expression: str, names: Mapping[str, Any]) -> float:
    tree = ast.parse(expression, mode="eval")

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            value = names[node.id]
            _finite_number(value, node.id)
            return float(value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = evaluate(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise TrainingHistoryError("formula uses forbidden syntax")

    return evaluate(tree)


def _validate_grad(value: Any, step_delta: int | None, epoch: int, errors: list[str]) -> None:
    fields = {"max", "mean", "last", "checked_steps", "clip_threshold"}
    if not isinstance(value, Mapping) or set(value) != fields:
        errors.append(f"epoch {epoch} grad_norm_pre_clip schema invalid")
        return
    for field in ("max", "mean", "last", "clip_threshold"):
        _collect_finite_nonnegative(value.get(field), f"epoch {epoch} grad {field}", errors)
    checked = value.get("checked_steps")
    if not isinstance(checked, int) or isinstance(checked, bool) or checked <= 0:
        errors.append(f"epoch {epoch} grad checked_steps must be positive integer")
    elif step_delta is not None and checked != step_delta:
        errors.append(f"epoch {epoch} grad checked_steps != optimizer-step delta")
    if all(_is_finite_number(value.get(k)) for k in ("max", "mean", "last")):
        if value["max"] < value["mean"] or value["max"] < value["last"]:
            errors.append(f"epoch {epoch} grad max is inconsistent")


def _validate_validation_coverage(
    manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], errors: list[str]
) -> None:
    if manifest.get("purpose") != "candidate":
        return
    val = manifest.get("split", {}).get("validation", {})
    if not isinstance(val, Mapping) or val.get("examples", 0) <= 0 or val.get("videos", 0) <= 0:
        errors.append("candidate validation is empty")
    lineage = val.get("lineages") if isinstance(val, Mapping) else None
    if not isinstance(lineage, Mapping) or any(lineage.get(key, 0) <= 0 for key in ("44b6", "6bba")):
        errors.append("candidate validation must cover both lineages")
    if manifest.get("task_type") == "binary_classification":
        if val.get("positive", 0) <= 0 or val.get("negative", 0) <= 0:
            errors.append("binary validation must contain positive and negative examples")
    for row in rows:
        if row.get("val_examples", 0) <= 0 or row.get("val_batches", 0) <= 0:
            errors.append(f"epoch {row.get('epoch')} has empty validation")
        train_summary = manifest.get("split", {}).get("train", {})
        if row.get("train_examples") != train_summary.get("examples"):
            errors.append(f"epoch {row.get('epoch')} train example coverage mismatch")
        if row.get("val_examples") != val.get("examples"):
            errors.append(f"epoch {row.get('epoch')} validation example coverage mismatch")
        by_lineage = row.get("val_by_lineage")
        if not isinstance(by_lineage, Mapping) or set(by_lineage) != {"44b6", "6bba"}:
            errors.append(f"epoch {row.get('epoch')} lacks both lineage readouts")
        else:
            _collect_numeric_tree(by_lineage, f"epoch {row.get('epoch')} val_by_lineage", errors)
            for lineage_id in ("44b6", "6bba"):
                item = by_lineage.get(lineage_id)
                if not isinstance(item, Mapping) or item.get("examples") != lineage.get(lineage_id):
                    errors.append(f"epoch {row.get('epoch')} lineage {lineage_id} coverage mismatch")


def _validate_selection(
    manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], errors: list[str], details: dict[str, Any]
) -> None:
    selector = manifest.get("selector", {})
    field = selector.get("field", "selector_value")
    direction = selector.get("direction", "min")
    try:
        winner = select_best(rows, field, direction)
        flags = expected_best_flags(rows, field, direction)
    except TrainingHistoryError as exc:
        errors.append(str(exc))
        return
    for row in rows:
        try:
            if row.get("selector_value") != _nested_value(row, field):
                errors.append(f"epoch {row.get('epoch')} selector_value differs from preregistered selector field")
        except TrainingHistoryError as exc:
            errors.append(str(exc))
    actual_flags = [row.get("best_so_far") for row in rows]
    if actual_flags != flags:
        errors.append("best_so_far flags do not match strict-improvement/earliest-tie semantics")
    final = manifest.get("final_selection")
    if not isinstance(final, Mapping) or set(final) != {"epoch", "selector_value", "checkpoint_sha256"}:
        errors.append("final_selection missing")
        return
    checkpoint = winner.get("checkpoint_sha256")
    if checkpoint is None:
        errors.append("selected history row has null checkpoint_sha256")
    expected_value = _nested_value(winner, field)
    if not isinstance(final.get("epoch"), int) or isinstance(final.get("epoch"), bool):
        errors.append("final_selection epoch must be a strict integer")
    if not _is_finite_number(final.get("selector_value")):
        errors.append("final_selection selector_value must be finite numeric")
    if (
        final.get("epoch") != winner.get("epoch")
        or final.get("selector_value") != expected_value
        or final.get("checkpoint_sha256") != checkpoint
    ):
        errors.append("final_selection does not match earliest primary-selector winner")
    details.update(
        best_epoch=winner.get("epoch"),
        best_selector_value=expected_value,
        checkpoint_sha256=checkpoint,
    )
    if selector.get("kind") == "grouped_validation_metric" and direction == "max":
        loss_winner = select_best(rows, "val.losses.total_loss.value", "min")
        loss_selection = manifest.get("min_val_loss_selection")
        if not isinstance(loss_selection, Mapping) or set(loss_selection) != {
            "epoch",
            "value",
            "checkpoint_sha256",
            "path",
        }:
            errors.append("maximized classifier selector requires bound min-val-loss checkpoint selection")
        elif (
            loss_selection.get("epoch") != loss_winner.get("epoch")
            or loss_selection.get("value") != _nested_value(loss_winner, "val.losses.total_loss.value")
            or not _is_sha256(loss_selection.get("checkpoint_sha256"))
            or loss_selection.get("path") != "checkpoints/min_val_loss.pt"
        ):
            errors.append("min-val-loss checkpoint selection mismatch")


def _validate_degradation(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    errors: list[str],
    warnings: list[str],
    details: dict[str, Any],
) -> None:
    selector = manifest.get("selector", {})
    field = selector.get("field", "selector_value")
    try:
        losses = [float(_nested_value(row, "val.losses.total_loss.value")) for row in rows]
        selectors = [float(_nested_value(row, field)) for row in rows]
        threshold = float(manifest.get("acceptance_thresholds", {}).get("zero_best_absolute_degradation", 0.0))
        computed = compute_degradation(
            losses, selectors, direction=selector.get("direction"), absolute_warning_threshold=threshold
        )
    except (TrainingHistoryError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"cannot compute degradation: {exc}")
        return
    declared = manifest.get("degradation")
    for key in ("loss_degradation_ratio", "loss_degradation_absolute", "ZERO_BEST_LOSS", "selector_degradation"):
        if not isinstance(declared, Mapping) or declared.get(key) != computed[key]:
            errors.append(f"degradation field mismatch: {key}")
    if computed["loss_degradation_ratio"] is None:
        if not isinstance(declared, Mapping) or declared.get("reason") != "ZERO_BEST_LOSS":
            errors.append("null loss_degradation_ratio requires ZERO_BEST_LOSS reason")
    if not isinstance(declared, Mapping) or declared.get("flags") != computed["warnings"]:
        errors.append("degradation warning flags mismatch")
    warnings.extend(computed["warnings"])
    details.update({key: value for key, value in computed.items() if key != "warnings"})


def _validate_progression(
    root: Path, manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], errors: list[str]
) -> None:
    if manifest.get("purpose") != "candidate":
        return
    threshold = manifest.get("acceptance_thresholds")
    if not isinstance(threshold, Mapping):
        errors.append("acceptance_thresholds missing")
        return
    selector = manifest.get("selector", {})
    primary = threshold.get("primary")
    if not isinstance(primary, Mapping) or set(primary) != {
        "field",
        "direction",
        "baseline",
        "margin",
        "observed_source",
    }:
        errors.append("literal primary acceptance specification missing")
    else:
        if (
            primary.get("field") != selector.get("field")
            or primary.get("direction") != selector.get("direction")
            or primary.get("observed_source") != "history_best"
        ):
            errors.append("primary acceptance spec is not bound to selector/history_best")
        _check_threshold(
            _observed_history(rows, primary.get("field"), "history_best", primary.get("direction"), errors),
            primary,
            "primary selector",
            errors,
            improvement=True,
        )
    noninferiority = threshold.get("noninferiority")
    if not isinstance(noninferiority, Mapping) or not noninferiority:
        errors.append("literal orthogonal noninferiority specs missing")
    else:
        for name, spec in noninferiority.items():
            _validate_history_threshold_spec(rows, spec, f"noninferiority {name}", errors)
    lineage = threshold.get("lineage_noninferiority")
    if not isinstance(lineage, Mapping) or set(lineage) != {"44b6", "6bba"}:
        errors.append("literal lineage noninferiority specs missing")
    else:
        for lineage_id, spec in lineage.items():
            if not isinstance(spec, Mapping) or not str(spec.get("field", "")).startswith(
                f"val_by_lineage.{lineage_id}."
            ):
                errors.append(f"lineage {lineage_id} acceptance field mismatch")
            else:
                _validate_history_threshold_spec(rows, spec, f"lineage {lineage_id}", errors)
    _validate_per_video_acceptance(root, manifest, threshold.get("per_video"), errors)


def _validate_final_refit(
    manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], errors: list[str], details: dict[str, Any]
) -> None:
    degradation = manifest.get("degradation")
    fields = ("loss_degradation_ratio", "loss_degradation_absolute", "ZERO_BEST_LOSS", "selector_degradation")
    if not isinstance(degradation, Mapping) or any(degradation.get(field, object()) is not None for field in fields):
        errors.append("final-refit degradation fields must all be null")
    if not isinstance(degradation, Mapping) or degradation.get("reason") != "CV_DERIVED_REFIT_NO_VALIDATION":
        errors.append("final-refit degradation reason mismatch")
    parent = manifest.get("parent_cv")
    if not isinstance(parent, Mapping) or not parent.get("run_id") or not _is_sha256(parent.get("degradation_sha256")):
        errors.append("final-refit must reference parent CV degradation artifact")
    elif parent.get("fixed_epoch") != len(rows):
        errors.append("final-refit epoch count differs from parent CV fixed-epoch pin")
    final = manifest.get("final_selection")
    if (
        not isinstance(final, Mapping)
        or set(final) != {"fixed_epoch", "checkpoint_sha256"}
        or not isinstance(final.get("fixed_epoch"), int)
        or isinstance(final.get("fixed_epoch"), bool)
        or final.get("fixed_epoch") != len(rows)
        or not _is_sha256(final.get("checkpoint_sha256"))
    ):
        errors.append("final-refit fixed-epoch selection mismatch")
    details.update(
        best_epoch=len(rows), checkpoint_sha256=final.get("checkpoint_sha256") if isinstance(final, Mapping) else None
    )
    train_examples = manifest.get("split", {}).get("train", {}).get("examples")
    for row in rows:
        if row.get("train_examples") != train_examples or row.get("train_batches", 0) <= 0:
            errors.append(f"final-refit epoch {row.get('epoch')} train coverage mismatch")


def _validate_final_refit_context(
    root: Path, manifest: Mapping[str, Any], context: Mapping[str, Any], errors: list[str]
) -> None:
    parent_root_value = context.get("root")
    parent_manifest = context.get("manifest")
    cv = context.get("cv")
    ref = context.get("ref")
    if (
        not isinstance(parent_root_value, str)
        or not isinstance(parent_manifest, Mapping)
        or not isinstance(cv, Mapping)
        or not isinstance(ref, Mapping)
    ):
        errors.append("final-refit actual parent CV context missing")
        return
    parent_root = Path(parent_root_value)
    parent = manifest.get("parent_cv")
    required_parent = {
        "run_id",
        "fixed_epoch",
        "config_sha256",
        "input_manifest_sha256",
        "code_tree_sha256",
        "warm_start_checkpoint_sha256",
        "split_sha256",
        "degradation_path",
        "degradation_sha256",
    }
    if not isinstance(parent, Mapping) or set(parent) != required_parent:
        errors.append("final-refit parent CV pins malformed")
        return
    expected = {
        "run_id": parent_manifest.get("run_id"),
        "fixed_epoch": ref.get("fixed_epoch"),
        "config_sha256": parent_manifest.get("config_sha256"),
        "input_manifest_sha256": parent_manifest.get("input_manifest_sha256"),
        "code_tree_sha256": parent_manifest.get("code_tree_sha256"),
        "warm_start_checkpoint_sha256": parent_manifest.get("warm_start_checkpoint_sha256"),
        "split_sha256": manifest.get("split_sha256"),
        "degradation_path": cv.get("degradation_artifact", {}).get("path"),
        "degradation_sha256": cv.get("degradation_artifact", {}).get("sha256"),
    }
    if any(parent.get(field) != value for field, value in expected.items()):
        errors.append("final-refit parent CV pin mismatch")
    try:
        degradation = _contained_regular_file(parent_root, parent.get("degradation_path"))
        if parent.get("degradation_sha256") != sha256_file(degradation):
            errors.append("final-refit parent degradation artifact hash mismatch")
    except TrainingHistoryError as exc:
        errors.append(str(exc))
    if ref.get("run_manifest_sha256") != sha256_file(root / "run_manifest.json"):
        errors.append("final-refit run manifest artifact pin mismatch")
    if ref.get("artifact_manifest_sha256") != sha256_file(root / "ARTIFACT_MANIFEST.json"):
        errors.append("final-refit artifact manifest pin mismatch")
    if ref.get("split_sha256") != manifest.get("split_sha256"):
        errors.append("final-refit split artifact pin mismatch")
    parent_split = parent_manifest.get("split")
    child_train = manifest.get("split", {}).get("train")
    if isinstance(parent_split, Mapping) and isinstance(child_train, Mapping):
        parent_train, parent_val = parent_split.get("train"), parent_split.get("validation")
        if isinstance(parent_train, Mapping) and isinstance(parent_val, Mapping):
            expected_stems = list(parent_train.get("stems", [])) + list(parent_val.get("stems", []))
            expected_ids = list(parent_train.get("example_ids", [])) + list(parent_val.get("example_ids", []))
            expected_lineages = {
                lineage: parent_train.get("lineages", {}).get(lineage, 0)
                + parent_val.get("lineages", {}).get(lineage, 0)
                for lineage in ("44b6", "6bba")
            }
            if (
                child_train.get("stems") != expected_stems
                or child_train.get("example_ids") != expected_ids
                or child_train.get("videos") != len(expected_stems)
                or child_train.get("examples") != len(expected_ids)
                or child_train.get("batches") != parent_train.get("batches", 0) + parent_val.get("batches", 0)
                or child_train.get("lineages") != expected_lineages
            ):
                errors.append("final-refit train split is not the exact pinned full CV dataset")


def _validate_history_threshold_spec(
    rows: Sequence[Mapping[str, Any]], spec: Any, label: str, errors: list[str]
) -> None:
    required = {"field", "direction", "baseline", "limit", "observed_source"}
    if not isinstance(spec, Mapping) or set(spec) != required:
        errors.append(f"{label} literal acceptance spec malformed")
        return
    source = spec.get("observed_source")
    if source not in {"best_epoch", "last_epoch", "history_min", "history_max"}:
        errors.append(f"{label} observed_source invalid")
        return
    observed = _observed_history(rows, spec.get("field"), source, spec.get("direction"), errors)
    _check_threshold(observed, spec, label, errors, improvement=False)


def _observed_history(
    rows: Sequence[Mapping[str, Any]], field: Any, source: str, direction: Any, errors: list[str]
) -> float | None:
    if not isinstance(field, str) or direction not in {"min", "max"}:
        errors.append("acceptance metric field/direction malformed")
        return None
    try:
        values = [_nested_value(row, field) for row in rows]
        if not all(_is_finite_number(value) for value in values):
            raise TrainingHistoryError(f"acceptance field is not finite numeric: {field}")
        if source == "history_best":
            return min(values) if direction == "min" else max(values)
        if source == "best_epoch":
            flagged = [row for row in rows if row.get("best_so_far") is True]
            if not flagged:
                raise TrainingHistoryError("history has no best_so_far row")
            return _nested_value(flagged[-1], field)
        if source == "last_epoch":
            return values[-1]
        if source == "history_min":
            return min(values)
        if source == "history_max":
            return max(values)
    except TrainingHistoryError as exc:
        errors.append(str(exc))
    return None


def _check_threshold(
    observed: float | None,
    spec: Mapping[str, Any],
    label: str,
    errors: list[str],
    *,
    improvement: bool,
) -> None:
    baseline = spec.get("baseline")
    amount = spec.get("margin" if improvement else "limit")
    direction = spec.get("direction")
    if (
        observed is None
        or not _is_finite_number(baseline)
        or not _is_finite_number(amount)
        or amount < 0
        or direction not in {"min", "max"}
    ):
        errors.append(f"{label} threshold values must be finite/nonnegative")
        return
    boundary = baseline - amount if direction == "min" and improvement else baseline + amount
    if direction == "max" and improvement:
        boundary = baseline + amount
    elif direction == "min" and not improvement:
        boundary = baseline + amount
    elif direction == "max" and not improvement:
        boundary = baseline - amount
    passed = observed <= boundary if direction == "min" else observed >= boundary
    if not passed:
        errors.append(f"{label} failed recomputed threshold")


def _validate_per_video_acceptance(root: Path, manifest: Mapping[str, Any], spec: Any, errors: list[str]) -> None:
    required = {
        "path",
        "sha256",
        "direction",
        "baseline",
        "limit",
        "observed_source",
        "uncertainty_field",
        "uncertainty_limit",
        "min_qualifying_videos",
    }
    if not isinstance(spec, Mapping) or set(spec) != required or spec.get("observed_source") != "artifact_values":
        errors.append("literal per-video acceptance specification malformed")
        return
    try:
        path = _contained_regular_file(root, spec.get("path"))
        if spec.get("sha256") != sha256_file(path):
            raise TrainingHistoryError("per-video numeric artifact hash mismatch")
        payload = _object(strict_json_load(path), "per-video artifact")
        if set(payload) != {"values", "uncertainty"}:
            raise TrainingHistoryError("per-video artifact schema invalid")
        values = payload.get("values")
        expected_stems = set(manifest.get("split", {}).get("validation", {}).get("stems", []))
        if not isinstance(values, Mapping) or set(values) != expected_stems or not values:
            raise TrainingHistoryError("per-video values do not exactly cover validation videos")
        if not all(_is_finite_number(value) for value in values.values()):
            raise TrainingHistoryError("per-video values must be finite numeric")
        direction = spec.get("direction")
        observed = max(values.values()) if direction == "min" else min(values.values())
        _check_threshold(observed, spec, "per-video concentration", errors, improvement=False)
        qualifying = sum(
            value <= spec.get("baseline") + spec.get("limit")
            if direction == "min"
            else value >= spec.get("baseline") - spec.get("limit")
            for value in values.values()
        )
        minimum = spec.get("min_qualifying_videos")
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2 or qualifying < minimum:
            errors.append("per-video improvement is concentrated or minimum count is invalid")
        uncertainty = _nested_value(payload, spec.get("uncertainty_field"))
        if not _is_finite_number(uncertainty) or not _is_finite_number(spec.get("uncertainty_limit")):
            errors.append("per-video uncertainty values must be finite numeric")
        elif uncertainty > spec.get("uncertainty_limit"):
            errors.append("per-video uncertainty limit failed")
    except Exception as exc:
        errors.append(str(exc))


def _validate_checkpoints(
    root: Path,
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    artifacts: Mapping[str, Any],
    loader: CheckpointMetadataLoader | None,
    errors: list[str],
) -> None:
    for sidecar in root.rglob("*.pt.metadata.json"):
        try:
            relative = sidecar.relative_to(root).as_posix()
            safe_sidecar = _contained_regular_file(root, relative)
            binding = _object(strict_json_load(safe_sidecar), relative)
            checkpoint_relative = relative.removesuffix(".metadata.json")
            checkpoint_path = _contained_regular_file(root, checkpoint_relative)
            if binding.get("checkpoint_path") != checkpoint_relative or binding.get("checkpoint_sha256") != sha256_file(
                checkpoint_path
            ):
                errors.append(f"checkpoint sidecar does not bind exact checkpoint bytes: {relative}")
        except TrainingHistoryError as exc:
            errors.append(str(exc))
    kind = manifest.get("run_kind")
    required = ["checkpoints/last.pt", "checkpoints/resume.pt"]
    if kind == "final_refit":
        required.append("checkpoints/fixed_epoch.pt")
        checkpoint_dir = root / "checkpoints"
        if checkpoint_dir.is_dir() and {path.name for path in checkpoint_dir.iterdir()} != {
            "last.pt",
            "resume.pt",
            "fixed_epoch.pt",
        }:
            errors.append("final-refit checkpoint directory contains forbidden/extra files")
    else:
        required.append("checkpoints/best.pt")
        if (
            manifest.get("selector", {}).get("kind") == "grouped_validation_metric"
            and manifest.get("selector", {}).get("direction") == "max"
        ):
            required.append("checkpoints/min_val_loss.pt")
    expected_refs = {
        relative: sha256_file(_contained_regular_file(root, relative))
        for relative in required
        if (root / relative).exists() and not (root / relative).is_symlink()
    }
    if manifest.get("checkpoint_refs") != expected_refs:
        errors.append("manifest checkpoint_refs do not exactly pin required checkpoint bytes")
    metadata_by_path: dict[str, Mapping[str, Any]] = {}
    expected_state = manifest.get("model_state_schema")
    schema_errors: list[str] = []
    expected_state_by_name = _state_entries(expected_state, schema_errors, "manifest model")
    errors.extend(schema_errors)
    for relative in required:
        try:
            path = _contained_regular_file(root, relative)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
            continue
        try:
            metadata = _load_checkpoint_metadata(path, loader)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
            continue
        metadata_by_path[relative] = metadata
        expected_kind = "fixed_epoch" if relative.endswith("fixed_epoch.pt") else Path(relative).stem
        if relative.endswith("min_val_loss.pt"):
            expected_kind = "min_val_loss"
        if metadata.get("format") != CHECKPOINT_FORMAT or not _is_schema_version(metadata.get("schema_version")):
            errors.append(f"checkpoint envelope/schema invalid: {relative}")
        _validate_checkpoint_envelope_schema(metadata, expected_kind, relative, errors)
        if metadata.get("checkpoint_sha256") != sha256_file(path) or metadata.get("path") != str(
            path.resolve(strict=True)
        ):
            errors.append(f"checkpoint loaded path/hash mismatch: {relative}")
        if metadata.get("kind") != expected_kind:
            errors.append(f"checkpoint kind mismatch: {relative}")
        if metadata.get("run_id") != manifest.get("run_id"):
            errors.append(f"checkpoint run_id mismatch: {relative}")
        state_errors: list[str] = []
        actual_state = _state_entries(metadata.get("state_keys"), state_errors, relative)
        errors.extend(state_errors)
        if actual_state != expected_state_by_name:
            errors.append(f"checkpoint strict key/shape/dtype mismatch: {relative}")
        _validate_model_tensor_state(metadata, expected_state_by_name, relative, errors)
        expected_epoch = rows[-1].get("epoch")
        if relative.endswith("best.pt"):
            expected_epoch = manifest.get("final_selection", {}).get("epoch")
        elif relative.endswith("min_val_loss.pt"):
            expected_epoch = manifest.get("min_val_loss_selection", {}).get("epoch")
        elif relative.endswith("fixed_epoch.pt"):
            expected_epoch = manifest.get("final_selection", {}).get("fixed_epoch")
        if (
            not isinstance(metadata.get("epoch"), int)
            or isinstance(metadata.get("epoch"), bool)
            or metadata.get("epoch") != expected_epoch
        ):
            errors.append(f"checkpoint epoch mismatch: {relative}")
        expected_row = next((row for row in rows if row.get("epoch") == expected_epoch), None)
        if not isinstance(metadata.get("global_step"), int) or isinstance(metadata.get("global_step"), bool):
            errors.append(f"checkpoint global_step type invalid: {relative}")
        elif expected_row is not None and metadata.get("global_step") != expected_row.get("global_step"):
            errors.append(f"checkpoint global_step mismatch: {relative}")
    final = manifest.get("final_selection", {})
    selected = "checkpoints/fixed_epoch.pt" if kind == "final_refit" else "checkpoints/best.pt"
    try:
        selected_path = _contained_regular_file(root, selected)
        if final.get("checkpoint_sha256") != sha256_file(selected_path):
            errors.append("selected checkpoint file hash differs from final_selection")
    except TrainingHistoryError:
        pass
    if "checkpoints/min_val_loss.pt" in required:
        try:
            min_path = _contained_regular_file(root, "checkpoints/min_val_loss.pt")
            if manifest.get("min_val_loss_selection", {}).get("checkpoint_sha256") != sha256_file(min_path):
                errors.append("min-val-loss checkpoint file hash differs from bound selection")
        except TrainingHistoryError:
            pass
    try:
        last_path = _contained_regular_file(root, "checkpoints/last.pt")
        last_hash = sha256_file(last_path)
        selected_epoch = final.get("fixed_epoch") if kind == "final_refit" else final.get("epoch")
        if rows and rows[-1].get("epoch") == selected_epoch:
            selected_metadata = metadata_by_path.get(selected)
            last_metadata = metadata_by_path.get("checkpoints/last.pt")
            if (
                selected_metadata is None
                or last_metadata is None
                or not all(
                    _strict_equal(selected_metadata.get(field), last_metadata.get(field))
                    for field in ("epoch", "global_step", "state_keys", "model_state")
                )
            ):
                errors.append("selected/last checkpoints at the same epoch do not contain identical model state")
        elif rows and rows[-1].get("checkpoint_sha256") != last_hash:
            errors.append("last checkpoint hash differs from final history row")
    except TrainingHistoryError:
        pass
    hash_paths: dict[str, list[str]] = {}
    for entry in artifacts.get("files", []):
        if isinstance(entry, Mapping) and isinstance(entry.get("sha256"), str):
            hash_paths.setdefault(entry["sha256"], []).append(entry.get("path"))
    for row in rows:
        digest = row.get("checkpoint_sha256")
        if digest is None:
            continue
        paths = [
            path for path in hash_paths.get(digest, []) if isinstance(path, str) and path.startswith("checkpoints/")
        ]
        if not paths:
            errors.append(f"epoch {row.get('epoch')} checkpoint SHA is orphaned")
            continue
        matched = False
        load_errors: list[str] = []
        for relative in paths:
            try:
                metadata = _load_checkpoint_metadata(_contained_regular_file(root, relative), loader)
                metadata_epoch = metadata.get("epoch")
                row_errors: list[str] = []
                actual_state = _state_entries(metadata.get("state_keys"), row_errors, relative)
                _validate_model_tensor_state(metadata, expected_state_by_name, relative, row_errors)
                is_required = relative in required
                expected_kind = Path(relative).stem if is_required else "epoch"
                if relative.endswith("fixed_epoch.pt"):
                    expected_kind = "fixed_epoch"
                elif relative.endswith("min_val_loss.pt"):
                    expected_kind = "min_val_loss"
                _validate_checkpoint_envelope_schema(metadata, expected_kind, relative, row_errors)
                valid = (
                    isinstance(metadata_epoch, int)
                    and not isinstance(metadata_epoch, bool)
                    and metadata_epoch == row.get("epoch")
                    and metadata.get("run_id") == manifest.get("run_id")
                    and metadata.get("format") == CHECKPOINT_FORMAT
                    and _is_schema_version(metadata.get("schema_version"))
                    and metadata.get("kind") == expected_kind
                    and metadata.get("global_step") == row.get("global_step")
                    and actual_state == expected_state_by_name
                    and not row_errors
                )
                matched |= valid
                if not valid:
                    load_errors.extend(row_errors or [f"strict checkpoint envelope mismatch: {relative}"])
            except TrainingHistoryError as exc:
                load_errors.append(str(exc))
        if not matched:
            errors.append(f"epoch {row.get('epoch')} checkpoint metadata mismatch: {load_errors}")
    resume = metadata_by_path.get("checkpoints/resume.pt")
    if resume is not None:
        if resume.get("history_prefix_sha256") != sha256_file(root / "history.jsonl"):
            errors.append("resume history prefix SHA256 does not match history.jsonl")
        receipt = None
        receipt_ref = resume.get("validation_receipt")
        if not isinstance(receipt_ref, Mapping) or set(receipt_ref) != {"path", "sha256"}:
            errors.append("resume validation receipt path/hash reference missing")
        else:
            try:
                receipt_path = _contained_regular_file(root, receipt_ref.get("path"))
                if receipt_ref.get("sha256") != sha256_file(receipt_path):
                    errors.append("resume validation receipt hash mismatch")
                else:
                    receipt = strict_json_load(receipt_path)
            except TrainingHistoryError as exc:
                errors.append(str(exc))
        try:
            validate_resume_metadata(manifest, rows, resume, validation_receipt=receipt)
        except GateValidationError as exc:
            errors.extend(exc.errors)


def _load_checkpoint_metadata(path: Path, loader: CheckpointMetadataLoader | None) -> Mapping[str, Any]:
    raw, actual_hash, _size = _read_regular_snapshot(path)
    resolved = str(path.resolve(strict=True))
    if loader is not None:
        metadata = dict(_object(loader(path), f"metadata for {path}"))
        _raw_after, hash_after, _size_after = _read_regular_snapshot(path, retain_data=False)
        if hash_after != actual_hash:
            raise TrainingHistoryError(f"checkpoint changed while trusted loader was reading it: {path}")
        _require_json_tree(metadata, f"trusted checkpoint metadata for {path}")
        if metadata.get("path") != resolved or metadata.get("checkpoint_sha256") != actual_hash:
            raise TrainingHistoryError(f"trusted checkpoint loader path/hash binding mismatch: {path}")
        evidence = metadata.pop("load_evidence", None)
        expected_evidence = {
            "trusted_safe_loader": True,
            "strict": True,
            "missing_keys": [],
            "unexpected_keys": [],
            "path": resolved,
            "checkpoint_sha256": actual_hash,
            "model_state_sha256": canonical_sha256(metadata.get("model_state")),
        }
        if not _strict_equal(evidence, expected_evidence):
            raise TrainingHistoryError(f"trusted checkpoint loader success evidence invalid: {path}")
        return metadata
    try:
        metadata = dict(_object(strict_json_loads(raw.decode("utf-8"), source=str(path)), str(path)))
    except TrainingHistoryError as exc:
        raise TrainingHistoryError(f"opaque checkpoint requires an injected trusted safe loader: {path}") from exc
    claimed_hash = metadata.pop("checkpoint_sha256", None)
    claimed_path = metadata.pop("path", None)
    if claimed_hash not in (None, actual_hash) or claimed_path not in (None, resolved):
        raise TrainingHistoryError(f"JSON checkpoint envelope path/hash binding mismatch: {path}")
    metadata["checkpoint_sha256"] = actual_hash
    metadata["path"] = resolved
    return metadata


def _validate_model_tensor_state(
    metadata: Mapping[str, Any],
    expected_schema: Mapping[str, Any],
    label: str,
    errors: list[str],
) -> None:
    state = metadata.get("model_state")
    if not isinstance(state, list) or not state:
        errors.append(f"checkpoint model tensor state missing: {label}")
        return
    names: list[str] = []
    actual_schema: dict[str, Any] = {}
    for tensor in state:
        if not isinstance(tensor, Mapping) or set(tensor) != {"name", "shape", "dtype", "values"}:
            errors.append(f"checkpoint tensor schema invalid: {label}")
            continue
        name = tensor.get("name")
        shape = tensor.get("shape")
        dtype = tensor.get("dtype")
        values = tensor.get("values")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(shape, list)
            or not all(isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in shape)
            or not isinstance(dtype, str)
            or not dtype
            or not isinstance(values, list)
        ):
            errors.append(f"checkpoint tensor value/schema invalid: {label}")
            continue
        element_count = math.prod(shape) if shape else 1
        if len(values) != element_count:
            errors.append(f"checkpoint tensor element count mismatch: {label}:{name}")
        dtype_lower = dtype.lower()
        if "bool" in dtype_lower and any(not isinstance(item, bool) for item in values):
            errors.append(f"checkpoint tensor values do not match bool dtype: {label}:{name}")
        elif (
            "int" in dtype_lower
            and "float" not in dtype_lower
            and any(not isinstance(item, int) or isinstance(item, bool) for item in values)
        ):
            errors.append(f"checkpoint tensor values do not match integer dtype: {label}:{name}")
        elif "bool" not in dtype_lower and not all(_is_finite_number(item) for item in values):
            errors.append(f"checkpoint tensor values must be finite numeric: {label}:{name}")
        names.append(name)
        actual_schema[name] = {"shape": shape, "dtype": dtype}
    if names != sorted(names) or len(names) != len(set(names)):
        errors.append(f"checkpoint tensor names must be sorted and unique: {label}")
    if actual_schema != expected_schema:
        errors.append(f"checkpoint tensor state differs from model schema: {label}")


def _validate_checkpoint_envelope_schema(
    metadata: Mapping[str, Any], expected_kind: str, label: str, errors: list[str]
) -> None:
    fields = {
        "format",
        "schema_version",
        "kind",
        "run_id",
        "epoch",
        "global_step",
        "state_keys",
        "model_state",
        "checkpoint_sha256",
        "path",
    }
    if expected_kind == "resume":
        fields |= {
            "config_sha256",
            "input_manifest_sha256",
            "split_sha256",
            "code_tree_sha256",
            "warm_start_checkpoint_sha256",
            "history_prefix_sha256",
            "next_epoch",
            "next_global_step",
            "validation_snapshot_sha256",
            "validation_receipt",
            "state",
        }
    if set(metadata) != fields:
        errors.append(f"checkpoint envelope fields are not exact: {label}")


def _validate_artifacts(root: Path, manifest: Mapping[str, Any], errors: list[str], *, is_cv: bool) -> None:
    if set(manifest) != {"schema_version", "run_id", "verdict", "files"}:
        errors.append("artifact manifest schema must contain exactly schema_version/run_id/verdict/files")
    if not _is_schema_version(manifest.get("schema_version")):
        errors.append("artifact manifest schema_version invalid")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        errors.append("artifact manifest files must be a nonempty list")
        return
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "bytes", "sha256"}:
            errors.append("artifact file entry must be an object")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not _safe_relative_path(relative):
            errors.append(f"unsafe artifact path: {relative!r}")
            continue
        if relative in seen:
            errors.append(f"duplicate artifact path: {relative}")
            continue
        seen.add(relative)
        try:
            path = _contained_regular_file(root, relative)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
            continue
        try:
            _data, actual_hash, actual_size = _read_regular_snapshot(path, retain_data=False)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
            continue
        size = entry.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size != actual_size:
            errors.append(f"artifact byte-size mismatch: {relative}")
        if entry.get("sha256") != actual_hash:
            errors.append(f"artifact SHA256 mismatch: {relative}")
    required = {"run_manifest.json"}
    if not is_cv:
        required |= {"history.jsonl", "checkpoints/last.pt", "checkpoints/resume.pt"}
    if not required.issubset(seen):
        errors.append(f"artifact manifest lacks required files: {sorted(required - seen)}")
    actual: set[str] = set()
    for path in root.rglob("*"):
        try:
            info = path.lstat()
        except OSError as exc:
            errors.append(f"cannot inspect artifact path {path}: {exc}")
            continue
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            errors.append(f"artifact tree contains a symlink: {relative}")
            continue
        if stat.S_ISDIR(info.st_mode):
            continue
        if path == root / "ARTIFACT_MANIFEST.json":
            continue
        if not stat.S_ISREG(info.st_mode):
            errors.append(f"artifact tree contains a special file: {relative}")
            continue
        try:
            _contained_regular_file(root, relative)
            actual.add(relative)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
    if seen != actual:
        errors.append(
            f"artifact manifest file coverage mismatch: missing={sorted(actual - seen)}, extra={sorted(seen - actual)}"
        )


def _contained_regular_file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not _safe_relative_path(relative):
        raise TrainingHistoryError(f"unsafe artifact path: {relative!r}")
    root_resolved = root.resolve(strict=True)
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise TrainingHistoryError(f"artifact path missing/unreadable: {relative}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise TrainingHistoryError(f"symlink artifact path forbidden: {relative}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise TrainingHistoryError(f"artifact parent is not a directory: {relative}")
    info = current.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise TrainingHistoryError(f"special/nonregular artifact forbidden: {relative}")
    if info.st_nlink != 1:
        raise TrainingHistoryError(f"hard-linked artifact forbidden: {relative}")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise TrainingHistoryError(f"artifact escapes run directory: {relative}") from exc
    return current


def _validate_cv_root(
    root: Path,
    manifest: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    loader: CheckpointMetadataLoader | None,
    errors: list[str],
    warnings: list[str],
    details: dict[str, Any],
) -> None:
    cv = manifest.get("cv")
    final = manifest.get("final_selection")
    if manifest.get("checkpoint_refs") != {}:
        errors.append("CV root must not carry leaf checkpoint_refs")
    cv_keys = {"fold_ids", "fold_paths", "fold_pins", "oof", "require_final_refit", "degradation_artifact"}
    final_keys = {"oof_selector_value", "fold_selections", "final_refit_ref"}
    if not isinstance(cv, Mapping) or set(cv) != cv_keys or not isinstance(final, Mapping) or set(final) != final_keys:
        errors.append("CV root requires cv and final_selection objects")
        return
    fold_ids = cv.get("fold_ids")
    fold_paths = cv.get("fold_paths")
    fold_pins = cv.get("fold_pins")
    selections = final.get("fold_selections")
    if (
        not isinstance(fold_ids, list)
        or not fold_ids
        or not all(isinstance(item, str) and item for item in fold_ids)
        or len(fold_ids) != len(set(fold_ids))
    ):
        errors.append("CV fold_ids must be a nonempty unique list")
        return
    if (
        not isinstance(fold_paths, Mapping)
        or set(fold_paths) != set(fold_ids)
        or not isinstance(fold_pins, Mapping)
        or set(fold_pins) != set(fold_ids)
    ):
        errors.append("CV fold path/pin maps must exactly cover fold IDs")
        return
    fold_dir = root / "fold"
    if fold_dir.is_symlink() or not fold_dir.is_dir() or {path.name for path in fold_dir.iterdir()} != set(fold_ids):
        errors.append("CV fold directory must exactly match declared fold IDs")
        return
    selection_keys = {"fold_id", "epoch", "selector_value", "checkpoint_sha256"}
    if (
        not isinstance(selections, list)
        or len(selections) != len(fold_ids)
        or any(not isinstance(item, Mapping) or set(item) != selection_keys for item in selections)
        or any(
            not isinstance(item.get("epoch"), int)
            or isinstance(item.get("epoch"), bool)
            or not _is_finite_number(item.get("selector_value"))
            or not _is_sha256(item.get("checkpoint_sha256"))
            for item in selections
            if isinstance(item, Mapping)
        )
        or {item.get("fold_id") for item in selections if isinstance(item, Mapping)} != set(fold_ids)
        or len({item.get("fold_id") for item in selections if isinstance(item, Mapping)}) != len(selections)
    ):
        errors.append("CV fold selections do not match fold IDs")
    child_reports = {}
    validation_ids: set[str] = set()
    validation_assignments: dict[str, str] = {}
    validation_stems: set[str] = set()
    validation_lineages = {"44b6": 0, "6bba": 0}
    child_run_ids: set[str] = set()
    root_split = manifest.get("split", {})
    root_train = root_split.get("train", {}) if isinstance(root_split, Mapping) else {}
    root_validation = root_split.get("validation", {}) if isinstance(root_split, Mapping) else {}
    root_all_ids = set(root_train.get("example_ids", [])) | set(root_validation.get("example_ids", []))
    root_all_stems = set(root_train.get("stems", [])) | set(root_validation.get("stems", []))
    for fold_id in fold_ids:
        expected_path = f"fold/{fold_id}"
        if fold_paths.get(fold_id) != expected_path:
            errors.append(f"CV fold {fold_id} path mismatch")
            continue
        fold_root = root / expected_path
        if fold_root.is_symlink() or not fold_root.is_dir():
            errors.append(f"CV fold {fold_id} directory missing/unsafe")
            continue
        report = verify_training_run(fold_root, checkpoint_metadata_loader=loader)
        child_reports[str(fold_id)] = report
        if report["verdict"] != "PASS":
            errors.append(f"CV fold {fold_id} failed: {report['errors']}")
            continue
        child_manifest = strict_json_load(_contained_regular_file(fold_root, "run_manifest.json"))
        child_run_id = child_manifest.get("run_id")
        if child_run_id == manifest.get("run_id") or child_run_id in child_run_ids:
            errors.append(f"CV fold {fold_id} run_id is not independent/unique")
        elif isinstance(child_run_id, str):
            child_run_ids.add(child_run_id)
        pin = fold_pins.get(fold_id)
        pin_fields = {
            "run_id",
            "config_sha256",
            "input_manifest_sha256",
            "code_tree_sha256",
            "warm_start_checkpoint_sha256",
            "split_sha256",
        }
        if (
            not isinstance(pin, Mapping)
            or set(pin) != pin_fields
            or any(pin.get(field) != child_manifest.get(field) for field in pin_fields)
        ):
            errors.append(f"CV fold {fold_id} parent pin mismatch")
        for shared_field in ("input_manifest_sha256", "code_tree_sha256", "warm_start_checkpoint_sha256"):
            if child_manifest.get(shared_field) != manifest.get(shared_field):
                errors.append(f"CV fold {fold_id} {shared_field} drifts from root")
        if _training_semantics_sha256(child_manifest) != _training_semantics_sha256(manifest):
            errors.append(f"CV fold {fold_id} training semantics drift from root")
        parent = child_manifest.get("parent_cv")
        if (
            not isinstance(parent, Mapping)
            or parent.get("run_id") != manifest.get("run_id")
            or parent.get("fold_id") != fold_id
        ):
            errors.append(f"CV fold {fold_id} parent identity mismatch")
        child_val = child_manifest.get("split", {}).get("validation", {})
        child_train = child_manifest.get("split", {}).get("train", {})
        child_ids = child_val.get("example_ids", []) if isinstance(child_val, Mapping) else []
        child_stems = child_val.get("stems", []) if isinstance(child_val, Mapping) else []
        if isinstance(child_train, Mapping) and isinstance(child_val, Mapping):
            child_all_ids = set(child_train.get("example_ids", [])) | set(child_ids)
            child_all_stems = set(child_train.get("stems", [])) | set(child_stems)
            if child_all_ids != root_all_ids or child_all_stems != root_all_stems:
                errors.append(f"CV fold {fold_id} train/validation membership differs from root dataset")
        if validation_ids & set(child_ids) or validation_stems & set(child_stems):
            errors.append(f"CV fold {fold_id} validation IDs/stems overlap another fold")
        validation_ids.update(child_ids)
        validation_assignments.update({example_id: fold_id for example_id in child_ids})
        validation_stems.update(child_stems)
        if isinstance(child_val, Mapping) and isinstance(child_val.get("lineages"), Mapping):
            for lineage_id in validation_lineages:
                validation_lineages[lineage_id] += child_val["lineages"].get(lineage_id, 0)
        selection = next(
            (item for item in selections if isinstance(item, Mapping) and item.get("fold_id") == fold_id), None
        )
        if not isinstance(selection, Mapping) or any(
            selection.get(key) != report["details"].get(report_key)
            for key, report_key in (
                ("epoch", "best_epoch"),
                ("selector_value", "best_selector_value"),
                ("checkpoint_sha256", "checkpoint_sha256"),
            )
        ):
            errors.append(f"CV fold {fold_id} selection pin mismatch")
    if (
        validation_ids != set(root_validation.get("example_ids", []))
        or validation_stems != set(root_validation.get("stems", []))
        or validation_lineages != root_validation.get("lineages")
    ):
        errors.append("CV root validation membership/counts differ from exact fold-validation union")
    oof = cv.get("oof")
    oof_keys = {
        "predictions_path",
        "predictions_sha256",
        "example_ids_path",
        "example_ids_sha256",
        "fold_ids_path",
        "fold_ids_sha256",
        "metrics_path",
        "metrics_sha256",
        "selector_value",
    }
    recomputed_selector: Any = None
    if not isinstance(oof, Mapping) or set(oof) != oof_keys:
        errors.append("CV OOF metadata missing")
    else:
        for field in ("predictions_path", "example_ids_path", "fold_ids_path", "metrics_path"):
            relative = oof.get(field)
            digest = oof.get(field.removesuffix("_path") + "_sha256")
            try:
                path = _contained_regular_file(root, relative)
            except TrainingHistoryError:
                errors.append(f"CV OOF file missing/unsafe: {field}")
                continue
            if digest != sha256_file(path):
                errors.append(f"CV OOF hash mismatch: {field}")
        contents = _validate_oof_contents(root, oof, fold_ids, validation_assignments, errors)
        metrics = contents.get("metrics", {})
        selector_field = manifest.get("selector", {}).get("field")
        try:
            recomputed_selector = _nested_value(metrics, selector_field)
        except TrainingHistoryError as exc:
            errors.append(str(exc))
            recomputed_selector = None
        if not _is_finite_number(recomputed_selector) or oof.get("selector_value") != recomputed_selector:
            errors.append("CV OOF selector is not recomputed from finite metrics")
        if final.get("oof_selector_value") != recomputed_selector:
            errors.append("CV OOF selector pin mismatch")
        _validate_cv_acceptance(root, manifest, metrics, errors)
    degradation_ref = cv.get("degradation_artifact")
    if not isinstance(degradation_ref, Mapping) or set(degradation_ref) != {"path", "sha256"}:
        errors.append("CV degradation artifact reference malformed")
    else:
        try:
            degradation_path = _contained_regular_file(root, degradation_ref.get("path"))
            if degradation_ref.get("sha256") != sha256_file(degradation_path):
                errors.append("CV degradation artifact hash mismatch")
            else:
                degradation_payload = strict_json_load(degradation_path)
                expected_degradation = None
                fold_degradation = {}
                for fold_id in fold_ids:
                    report = child_reports.get(str(fold_id))
                    report_details = report.get("details", {}) if isinstance(report, Mapping) else {}
                    item = {
                        key: report_details.get(key)
                        for key in (
                            "loss_degradation_ratio",
                            "loss_degradation_absolute",
                            "ZERO_BEST_LOSS",
                            "selector_degradation",
                        )
                    }
                    if report and report.get("verdict") == "PASS":
                        fold_degradation[fold_id] = item
                if len(fold_degradation) == len(fold_ids):
                    ratios = [
                        item["loss_degradation_ratio"]
                        for item in fold_degradation.values()
                        if item["loss_degradation_ratio"] is not None
                    ]
                    absolutes = [item["loss_degradation_absolute"] for item in fold_degradation.values()]
                    selectors = [item["selector_degradation"] for item in fold_degradation.values()]
                    expected_degradation = {
                        "folds": fold_degradation,
                        "aggregate": {
                            "finite_loss_degradation_ratio_mean": (sum(ratios) / len(ratios) if ratios else None),
                            "loss_degradation_absolute_mean": sum(absolutes) / len(absolutes),
                            "selector_degradation_mean": sum(selectors) / len(selectors),
                            "zero_best_loss_folds": [
                                fold_id for fold_id in fold_ids if fold_degradation[fold_id]["ZERO_BEST_LOSS"] is True
                            ],
                        },
                        "oof_selector_value": recomputed_selector,
                    }
                if expected_degradation is None or not _strict_equal(degradation_payload, expected_degradation):
                    errors.append("CV degradation artifact is not exactly recomputed from folds/OOF")
                if not _strict_equal(manifest.get("degradation"), degradation_payload):
                    errors.append("CV manifest degradation differs from bound degradation artifact")
        except TrainingHistoryError as exc:
            errors.append(str(exc))
    ref = final.get("final_refit_ref")
    if manifest.get("purpose") == "candidate" and (cv.get("require_final_refit") is not True or ref is None):
        errors.append("candidate CV deployment contract requires final_refit_ref")
    elif not isinstance(cv.get("require_final_refit"), bool):
        errors.append("CV require_final_refit must be boolean")
    if ref is not None:
        refit_root = root / "final_refit"
        context = {"root": str(root.resolve()), "manifest": manifest, "cv": cv, "ref": ref}
        report = _verify_training_run(
            refit_root,
            checkpoint_metadata_loader=loader,
            parent_cv_context=context,
        )
        if report["verdict"] != "CV_DERIVED_REFIT_ONLY":
            errors.append(f"CV final-refit failed: {report['errors']}")
        elif (
            not isinstance(ref, Mapping)
            or set(ref)
            != {
                "run_id",
                "fixed_epoch",
                "checkpoint_sha256",
                "run_manifest_sha256",
                "artifact_manifest_sha256",
                "split_sha256",
            }
            or not isinstance(ref.get("fixed_epoch"), int)
            or isinstance(ref.get("fixed_epoch"), bool)
            or not all(
                _is_sha256(ref.get(field))
                for field in (
                    "checkpoint_sha256",
                    "run_manifest_sha256",
                    "artifact_manifest_sha256",
                    "split_sha256",
                )
            )
            or (
                ref.get("run_id") != report.get("run_id")
                or ref.get("fixed_epoch") != report["details"].get("best_epoch")
                or ref.get("checkpoint_sha256") != report["details"].get("checkpoint_sha256")
            )
        ):
            errors.append("CV final-refit reference mismatch")
    details["folds"] = child_reports
    details["oof_selector_value"] = final.get("oof_selector_value")
    declared_paths = {entry.get("path") for entry in artifacts.get("files", []) if isinstance(entry, Mapping)}
    for prefix in ("fold/", "oof/"):
        if not any(isinstance(path, str) and path.startswith(prefix) for path in declared_paths):
            errors.append(f"CV artifact manifest does not cover {prefix}")


def _validate_oof_contents(
    root: Path,
    oof: Mapping[str, Any],
    fold_ids: Sequence[Any],
    expected_assignments: Mapping[str, str],
    errors: list[str],
) -> dict[str, Any]:
    try:
        predictions = strict_json_load(_contained_regular_file(root, oof["predictions_path"]))
        example_ids = strict_json_load(_contained_regular_file(root, oof["example_ids_path"]))
        assignments = strict_json_load(_contained_regular_file(root, oof["fold_ids_path"]))
        metrics = strict_json_load(_contained_regular_file(root, oof["metrics_path"]))
    except (KeyError, TrainingHistoryError) as exc:
        errors.append(f"CV OOF content parse failed: {exc}")
        return {}
    if not all(isinstance(value, list) for value in (predictions, example_ids, assignments)):
        errors.append("CV OOF predictions/example IDs/fold IDs must be arrays")
        return {}
    if not predictions or len(predictions) != len(example_ids) or len(predictions) != len(assignments):
        errors.append("CV OOF arrays are empty or length-mismatched")
    if (
        not all(isinstance(value, str) and value for value in example_ids)
        or len(example_ids) != len(set(example_ids))
        or set(example_ids) != set(expected_assignments)
    ):
        errors.append("CV OOF example IDs must exactly cover fold validation IDs once")
    if not all(isinstance(value, str) and value in fold_ids for value in assignments):
        errors.append("CV OOF fold assignments must be declared string fold IDs")
    if set(assignments) - set(fold_ids) or set(assignments) != set(fold_ids):
        errors.append("CV OOF assignments do not cover exactly the declared folds")
    if len(example_ids) == len(assignments) and any(
        expected_assignments.get(example_id) != assignment
        for example_id, assignment in zip(example_ids, assignments, strict=True)
    ):
        errors.append("CV OOF example-to-fold assignments differ from fold validation splits")
    if not all(_is_finite_number(value) for value in predictions):
        errors.append("CV OOF predictions must be finite numeric scalars")
    _collect_numeric_tree(metrics, "CV OOF metrics", errors)
    return {"predictions": predictions, "example_ids": example_ids, "assignments": assignments, "metrics": metrics}


def _validate_cv_acceptance(root: Path, manifest: Mapping[str, Any], metrics: Any, errors: list[str]) -> None:
    if manifest.get("purpose") != "candidate":
        return
    if not isinstance(metrics, Mapping) or not metrics:
        errors.append("CV OOF numeric metrics missing")
        return
    thresholds = manifest.get("acceptance_thresholds")
    if not isinstance(thresholds, Mapping):
        errors.append("CV acceptance thresholds missing")
        return
    primary = thresholds.get("primary")
    selector = manifest.get("selector", {})
    if not isinstance(primary, Mapping) or set(primary) != {
        "field",
        "direction",
        "baseline",
        "margin",
        "observed_source",
    }:
        errors.append("CV literal primary acceptance spec malformed")
    else:
        try:
            observed = _nested_value(metrics, primary.get("field"))
        except TrainingHistoryError as exc:
            errors.append(str(exc))
            observed = None
        if (
            primary.get("observed_source") != "oof_metrics"
            or primary.get("field") != selector.get("field")
            or primary.get("direction") != selector.get("direction")
        ):
            errors.append("CV primary acceptance is not bound to OOF selector")
        _check_threshold(observed, primary, "CV primary", errors, improvement=True)
    for group_name in ("noninferiority", "lineage_noninferiority"):
        group = thresholds.get(group_name)
        required_names = {"44b6", "6bba"} if group_name == "lineage_noninferiority" else None
        if not isinstance(group, Mapping) or not group or (required_names is not None and set(group) != required_names):
            errors.append(f"CV {group_name} specs missing")
            continue
        for name, spec in group.items():
            if not isinstance(spec, Mapping) or set(spec) != {
                "field",
                "direction",
                "baseline",
                "limit",
                "observed_source",
            }:
                errors.append(f"CV {group_name} {name} spec malformed")
                continue
            try:
                observed = _nested_value(metrics, spec.get("field"))
            except TrainingHistoryError as exc:
                errors.append(str(exc))
                observed = None
            if spec.get("observed_source") != "oof_metrics":
                errors.append(f"CV {group_name} {name} source must be OOF metrics")
            _check_threshold(observed, spec, f"CV {group_name} {name}", errors, improvement=False)
    _validate_per_video_acceptance(root, manifest, thresholds.get("per_video"), errors)


def _validate_metric_readback(
    manifest: Mapping[str, Any],
    expected: Any,
    actual: Mapping[str, Any],
    errors: list[str],
    tolerances_override: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(expected, Mapping):
        errors.append("resume validation_metrics missing")
        return
    tolerances = tolerances_override if tolerances_override is not None else manifest.get("validation_tolerances", {})
    if not isinstance(tolerances, Mapping):
        errors.append("validation tolerances must be an object")
        return
    if set(tolerances) - set(expected):
        errors.append("validation tolerances contain unknown metric keys")
    for key, tolerance in tolerances.items():
        if (
            not isinstance(tolerance, Mapping)
            or set(tolerance) != {"rtol", "atol"}
            or not _is_finite_number(tolerance.get("rtol"))
            or not _is_finite_number(tolerance.get("atol"))
            or tolerance.get("rtol") < 0
            or tolerance.get("atol") < 0
        ):
            errors.append(f"validation tolerance must be finite and nonnegative: {key}")
    for key, expected_value in expected.items():
        if key not in actual:
            errors.append(f"validation readback metric missing: {key}")
            continue
        actual_value = actual[key]
        if isinstance(expected_value, (int, str, list)) and not isinstance(expected_value, bool):
            if not _strict_equal(actual_value, expected_value):
                errors.append(f"validation readback exact mismatch: {key}")
            continue
        tolerance = tolerances.get(key, {})
        if not isinstance(tolerance, Mapping):
            errors.append(f"validation tolerance must be an object: {key}")
            continue
        default_atol = 1e-8 if "auc" in key.lower() else 1e-7
        default_rtol = 0.0 if "auc" in key.lower() else 1e-5
        rtol = tolerance.get("rtol", default_rtol)
        atol = tolerance.get("atol", default_atol)
        if not _is_finite_number(rtol) or not _is_finite_number(atol) or rtol < 0 or atol < 0:
            errors.append(f"validation tolerance must be finite and nonnegative: {key}")
            continue
        if (
            not _is_finite_number(expected_value)
            or not _is_finite_number(actual_value)
            or not math.isclose(
                expected_value,
                actual_value,
                rel_tol=rtol,
                abs_tol=atol,
            )
        ):
            errors.append(f"validation readback tolerance mismatch: {key}")


def _validate_validation_receipt(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    resume: Mapping[str, Any],
    receipt: Any,
    errors: list[str],
) -> None:
    required = {
        "schema_version",
        "run_id",
        "epoch",
        "global_step",
        "validation_snapshot_sha256",
        "expected",
        "actual",
        "tolerances",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        errors.append("resume validation-only readback receipt is mandatory and has invalid schema")
        return
    if not _is_schema_version(receipt.get("schema_version")):
        errors.append("resume validation receipt schema_version invalid")
    expected_identity = {
        "run_id": manifest.get("run_id"),
        "epoch": resume.get("epoch"),
        "global_step": resume.get("global_step"),
        "validation_snapshot_sha256": resume.get("validation_snapshot_sha256"),
    }
    for field, expected in expected_identity.items():
        if receipt.get(field) != expected:
            errors.append(f"resume validation receipt {field} mismatch")
    expected_metrics = receipt.get("expected")
    actual_metrics = receipt.get("actual")
    if not isinstance(expected_metrics, Mapping) or not expected_metrics:
        errors.append("resume validation receipt expected metrics must be nonempty")
        return
    contract = manifest.get("resume_validation_contract")
    if not isinstance(contract, Mapping) or not contract or set(contract) != set(expected_metrics):
        errors.append("resume validation contract must exactly bind receipt metric keys")
    elif rows:
        recomputed: dict[str, Any] = {}
        for name, source in contract.items():
            try:
                if source == "$validation_snapshot_ids":
                    recomputed[name] = manifest.get("validation_snapshot", {}).get("example_ids")
                elif source == "$train_example_ids":
                    recomputed[name] = manifest.get("split", {}).get("train", {}).get("example_ids")
                elif isinstance(source, str):
                    recomputed[name] = _nested_value(rows[-1], source)
                else:
                    raise TrainingHistoryError("resume validation contract source must be a string")
            except (AttributeError, TrainingHistoryError) as exc:
                errors.append(f"resume validation contract cannot be recomputed: {exc}")
        if not _strict_equal(recomputed, expected_metrics):
            errors.append("resume validation expected metrics differ from saved history/snapshot")
    if not isinstance(actual_metrics, Mapping) or set(actual_metrics) != set(expected_metrics):
        errors.append("resume validation receipt actual metrics must exactly match expected keys")
        return
    _validate_metric_readback(manifest, expected_metrics, actual_metrics, errors, receipt.get("tolerances"))


def _nonempty_payload(value: Any) -> bool:
    if isinstance(value, (Mapping, list, tuple, str, bytes)):
        return bool(value)
    return value is not None and not isinstance(value, bool)


def _validate_hashed_state_payload(value: Any, expected_type: str, label: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != {"type", "payload"} or value.get("type") != expected_type:
        errors.append(f"{label} state must be a typed {expected_type} object")
        return
    payload = value.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != {"state_dict", "sha256"}:
        errors.append(f"{label} payload schema invalid")
        return
    state_dict = payload.get("state_dict")
    if not _nonempty_payload(state_dict):
        errors.append(f"{label} state_dict must be nonempty")
        return
    try:
        expected_hash = canonical_sha256(state_dict)
    except TrainingHistoryError as exc:
        errors.append(f"{label} state_dict invalid: {exc}")
        return
    if payload.get("sha256") != expected_hash:
        errors.append(f"{label} state_dict hash mismatch")


def _validate_rng_payload(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != {"encoding", "value", "sha256"}:
        errors.append(f"{label} payload schema invalid")
        return
    encoded = value.get("value")
    if value.get("encoding") != "base64" or not isinstance(encoded, str) or not encoded:
        errors.append(f"{label} must be nonempty base64")
        return
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        errors.append(f"{label} base64 is invalid")
        return
    if not decoded or value.get("sha256") != sha256_bytes(decoded):
        errors.append(f"{label} bytes/hash mismatch")


def _state_entries(value: Any, errors: list[str], label: str) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        errors.append(f"{label} state_keys must be a nonempty list")
        return {}
    names: list[str] = []
    result = {}
    for entry in value:
        if not isinstance(entry, Mapping) or set(entry) != {"name", "shape", "dtype"}:
            errors.append(f"{label} state key schema invalid")
            continue
        name, shape, dtype = entry.get("name"), entry.get("shape"), entry.get("dtype")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(shape, list)
            or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in shape)
            or not isinstance(dtype, str)
            or not dtype
        ):
            errors.append(f"{label} state key name/shape/dtype invalid")
            continue
        names.append(name)
        result[name] = {"shape": shape, "dtype": dtype}
    if names != sorted(names) or len(names) != len(set(names)):
        errors.append(f"{label} state keys must be sorted and unique")
    return result


def _nested_value(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise TrainingHistoryError(f"selector field not found: {path}")
        current = current[part]
    return current


def _safe_relative_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return bool(path) and not pure.is_absolute() and ".." not in pure.parts and str(pure) == path


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == HEX_SHA256_LENGTH and all(c in "0123456789abcdef" for c in value)


def _is_schema_version(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == SCHEMA_VERSION


def _strict_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return set(left) == set(right) and all(_strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_strict_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _strict_int(value: Any, name: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise TrainingHistoryError(f"{name} must be an integer >= {minimum}")
    return value


def _is_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _finite_number(value: Any, name: str) -> None:
    if not _is_finite_number(value):
        raise TrainingHistoryError(f"{name} must be finite")


def _require_finite_tree(value: Any, source: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise TrainingHistoryError(f"non-finite value in {source}")
    if isinstance(value, Mapping):
        for child in value.values():
            _require_finite_tree(child, source)
    elif isinstance(value, list):
        for child in value:
            _require_finite_tree(child, source)


def _require_json_tree(value: Any, source: str) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TrainingHistoryError(f"non-finite value in {source}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TrainingHistoryError(f"non-string object key in {source}")
            _require_json_tree(child, source)
        return
    if isinstance(value, list):
        for child in value:
            _require_json_tree(child, source)
        return
    raise TrainingHistoryError(f"non-JSON value in {source}")


def _collect_finite(value: Any, name: str, errors: list[str]) -> None:
    if not _is_finite_number(value):
        errors.append(f"{name} must be finite")


def _collect_finite_nonnegative(value: Any, name: str, errors: list[str]) -> None:
    if not _is_finite_number(value) or value < 0:
        errors.append(f"{name} must be finite and nonnegative")


def _collect_finite_tree(value: Any, name: str, errors: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, bool) or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        _collect_finite(value, name, errors)
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _collect_finite_tree(child, f"{name}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_finite_tree(child, f"{name}[{index}]", errors)
    else:
        errors.append(f"{name} contains unsupported value")


def _collect_numeric_tree(value: Any, name: str, errors: list[str]) -> None:
    if isinstance(value, Mapping):
        if not value:
            errors.append(f"{name} must not be empty")
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                errors.append(f"{name} has invalid key")
            _collect_numeric_tree(child, f"{name}.{key}", errors)
    elif isinstance(value, list):
        if not value:
            errors.append(f"{name} must not be empty")
        for index, child in enumerate(value):
            _collect_numeric_tree(child, f"{name}[{index}]", errors)
    elif not _is_finite_number(value):
        errors.append(f"{name} must contain finite numeric values only")


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrainingHistoryError(f"{name} must contain a JSON object")
    return value


__all__ = [
    "CHECKPOINT_FORMAT",
    "SCHEMA_VERSION",
    "DuplicateKeyError",
    "GateValidationError",
    "HistoryWriter",
    "TrainingHistoryError",
    "atomic_publish_file",
    "atomic_write_json",
    "canonical_sha256",
    "canonical_json_bytes",
    "compute_degradation",
    "execution_config_sha256",
    "expected_best_flags",
    "select_best",
    "sha256_bytes",
    "sha256_file",
    "strict_json_load",
    "strict_json_loads",
    "strict_jsonl_load",
    "validate_resume_metadata",
    "validate_run",
    "validate_training_run",
    "validate_warm_start",
    "verify_training_run",
]
