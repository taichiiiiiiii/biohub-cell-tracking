from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import biohub.st_r3_image_view as image_view

_CAPTURE_GIT_STATE = image_view._capture_git_state
_CLONE_FILE = image_view._clone_file
_FILESYSTEM_TYPE = image_view._filesystem_type
_RENAME_NOREPLACE = image_view._rename_noreplace


@dataclass(frozen=True)
class TinyEnvironment:
    root: Path
    authority: image_view.Authority
    run_dir: Path
    source_files: tuple[Path, ...]
    git_state: image_view.GitState


def _write_json(path: Path, value: object) -> bytes:
    raw = image_view.canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _make_writable(root: Path) -> None:
    if not root.exists():
        return
    for current, directories, files in os.walk(root):
        os.chmod(current, 0o700)
        for name in directories:
            os.chmod(Path(current) / name, 0o700)
        for name in files:
            path = Path(current) / name
            if not path.is_symlink():
                os.chmod(path, 0o600)


def _fake_clone(source_fd: int, destination_parent_fd: int, destination_name: str) -> None:
    destination_fd = os.open(
        destination_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
        dir_fd=destination_parent_fd,
    )
    try:
        os.lseek(source_fd, 0, os.SEEK_SET)
        while True:
            chunk = os.read(source_fd, 8192)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                view = view[written:]
    finally:
        os.close(destination_fd)


def _fake_rename(parent_fd: int, source: str, destination: str) -> str:
    try:
        os.stat(destination, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(destination)
    os.rename(source, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    return "renameat2(RENAME_NOREPLACE)"


def _fd_count() -> int:
    return len(os.listdir("/dev/fd"))


def _mock_clean_git(
    environment: TinyEnvironment,
    *,
    index_prefix: str = "H",
    official_index_prefix: str = "H",
    blob_override: str | None = None,
) -> Callable[..., bytes]:
    head_sources = {
        relative: (environment.root / relative).read_bytes() for relative in environment.authority.builder_sources
    }
    official_entries: list[tuple[str, str, str, bytes]] = []
    official_blobs: dict[str, bytes] = {}
    for path in sorted((environment.root / "official").rglob("*"), key=lambda item: item.as_posix().encode()):
        if path.is_symlink():
            mode = "120000"
            raw = os.fsencode(os.readlink(path))
        elif path.is_file():
            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            raw = path.read_bytes()
        else:
            continue
        relative = path.relative_to(environment.root / "official").as_posix()
        oid = image_view._git_blob_oid(raw)
        official_entries.append((mode, oid, relative, raw))
        official_blobs[oid] = raw
    official_tree = b"".join(
        f"{mode} blob {oid}\t{relative}".encode() + b"\0" for mode, oid, relative, _raw in official_entries
    )
    official_index = b"".join(
        f"{official_index_prefix} {mode} {oid} 0\t{relative}".encode() + b"\0"
        for mode, oid, relative, _raw in official_entries
    )

    def run_git(root: Path, *arguments: str) -> bytes:
        if arguments[0] == "status":
            return b""
        if root == environment.root / "official":
            if arguments == ("rev-parse", "--verify", "HEAD"):
                return f"{environment.authority.official_oid}\n".encode()
            if arguments == ("ls-tree", "-rz", "--full-tree", "HEAD"):
                return official_tree
            if arguments == ("ls-files", "-z", "--stage", "-v"):
                return official_index
            if arguments[:2] == ("cat-file", "blob"):
                return official_blobs[arguments[2]]
            raise AssertionError((root, arguments))
        if arguments == ("rev-parse", "--verify", "HEAD"):
            return f"{environment.git_state.commit}\n".encode()
        if arguments == ("rev-parse", "--verify", "HEAD^{tree}"):
            return f"{environment.git_state.tree}\n".encode()
        if arguments == ("rev-parse", "--verify", "HEAD:official"):
            return f"{environment.authority.official_oid}\n".encode()
        if arguments[0] == "show":
            relative = arguments[1].removeprefix("HEAD:")
            return head_sources[relative]
        if arguments[:2] == ("rev-parse", "--verify") and arguments[2].startswith("HEAD:"):
            relative = arguments[2].removeprefix("HEAD:")
            raw = head_sources[relative]
            return f"{blob_override or image_view._git_blob_oid(raw)}\n".encode()
        if arguments[:3] == ("ls-files", "-v", "--"):
            return f"{index_prefix} {arguments[3]}\n".encode()
        raise AssertionError((root, arguments))

    return run_git


@pytest.fixture
def tiny_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TinyEnvironment:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "official").mkdir()
    (root / "official/tracked.txt").write_bytes(b"official-tracked-bytes\n")
    (root / "official/tracked-link").symlink_to("tracked.txt")
    train = root / "data/train"
    train.mkdir(parents=True)
    (train / "never-touch.geff").mkdir()
    (train / "never-touch.geff/secret.bin").write_bytes(b"ground-truth-canary")
    stems = ("aa_00000001", "bb_00000002")
    payloads = {
        f"{stems[0]}.zarr/0.bin": b"alpha-image-bytes",
        f"{stems[0]}.zarr/zarr.json": b'{"zarr_format":3}\n',
        f"{stems[1]}.zarr/0.bin": b"beta-image-bytes",
        f"{stems[1]}.zarr/zarr.json": b'{"zarr_format":3}\n',
    }
    source_files: list[Path] = []
    records: list[dict[str, object]] = []
    for relative, raw in payloads.items():
        path = train / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        source_files.append(path)
        records.append(
            {
                "bytes": len(raw),
                "path": relative,
                "sha256": image_view._sha256(raw),
                "stem": relative.split(".zarr/", 1)[0],
            }
        )
    records.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    total_bytes = sum(int(record["bytes"]) for record in records)
    summary = {"chunks": 0, "files": len(records), "roots": len(stems), "stored_bytes": total_bytes}
    inventory = {
        "files": records,
        "roots": list(stems),
        "schema_version": image_view.INVENTORY_SCHEMA,
        "summary": summary,
    }
    authority_dir = root / "authority"
    inventory_raw = _write_json(authority_dir / "IMAGE_CONTENT_INVENTORY.json", inventory)
    import_value = {"schema_version": "test.import.v1", "status": "PASS"}
    import_raw = _write_json(authority_dir / "import.json", import_value)
    ready_core = {
        "data_root_identity": {"device": train.stat().st_dev, "inode": train.stat().st_ino},
        "decoded": {"aggregate_sha256": "0" * 64, "bytes": 0, "chunks": 0, "order": "not decoded"},
        "digest_scope": "test",
        "import_receipt": {
            "bytes": len(import_raw),
            "installed": 0,
            "reference": "import.json",
            "sha256": image_view._sha256(import_raw),
            "skipped": 0,
            "status": "PASS",
            "validated": 0,
        },
        "inventory": {
            "bytes": len(inventory_raw),
            "path": "IMAGE_CONTENT_INVENTORY.json",
            "sha256": image_view._sha256(inventory_raw),
            "summary": summary,
        },
        "manifest": {"bytes": 0, "lines": 0, "path": "manifest.csv", "sha256": "0" * 64},
        "schema_version": image_view.READY_SCHEMA,
        "status": "READY",
        "verifier": {"bytes": 1, "reference": "test", "sha256": "0" * 64},
    }
    ready_content = image_view._sha256(image_view.canonical_json_bytes(ready_core))
    ready = {
        **ready_core,
        "created_utc": "2026-09-04T00:00:00Z",
        "ready_content_sha256": ready_content,
    }
    ready_raw = _write_json(authority_dir / "READY.json", ready)
    builder_sources = ("src/biohub/st_r3_image_view.py", "scripts/experiments/st_r3/st_r3_image_view.py")
    for relative in builder_sources:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    official_oid = "3" * 40
    authority = image_view.Authority(
        stems=stems,
        file_suffixes=("0.bin", "zarr.json"),
        files_per_root=2,
        stored_bytes=total_bytes,
        source_relative="data/train",
        output_parent_relative="outputs/local/st_r3_image_views",
        ready_relative="authority/READY.json",
        ready_sha256=image_view._sha256(ready_raw),
        ready_content_sha256=ready_content,
        inventory_sha256=image_view._sha256(inventory_raw),
        import_receipt_relative="authority/import.json",
        import_receipt_sha256=image_view._sha256(import_raw),
        official_oid=official_oid,
        builder_sources=builder_sources,
    )
    git_state = image_view.GitState(commit="1" * 40, tree="2" * 40, official_oid=official_oid)
    monkeypatch.setattr(image_view, "CANONICAL_REPO_ROOT", root)
    monkeypatch.setattr(image_view, "PRODUCTION_AUTHORITY", authority)
    monkeypatch.setattr(image_view, "_capture_git_state", lambda _root, _authority, _guard=None: git_state)
    monkeypatch.setattr(image_view, "_filesystem_type", lambda _path, _fd: "apfs")
    monkeypatch.setattr(image_view, "_clone_method", lambda: "fclonefileat(APFS_CLONEFILE)")
    monkeypatch.setattr(image_view, "_clone_file", _fake_clone)
    monkeypatch.setattr(image_view, "_publication_primitive", lambda: "renameat2(RENAME_NOREPLACE)")
    monkeypatch.setattr(image_view, "_rename_noreplace", _fake_rename)
    monkeypatch.chdir(root)
    environment = TinyEnvironment(
        root=root,
        authority=authority,
        run_dir=root / authority.output_parent_relative / "tiny-run",
        source_files=tuple(source_files),
        git_state=git_state,
    )
    try:
        yield environment
    finally:
        _make_writable(root)


def _published_file(environment: TinyEnvironment) -> Path:
    return environment.run_dir / "IMAGE_VIEW" / f"{environment.authority.stems[0]}.zarr/0.bin"


def _rewrite_receipt(environment: TinyEnvironment, mutate: object) -> None:
    receipt_path = environment.run_dir / "IMAGE_VIEW_RECEIPT.json"
    os.chmod(environment.run_dir, 0o700)
    os.chmod(receipt_path, 0o600)
    value = json.loads(receipt_path.read_bytes())
    mutate(value)
    core = dict(value)
    del core["created_utc"]
    core.pop("receipt_content_sha256", None)
    value["receipt_content_sha256"] = image_view._sha256(image_view.canonical_json_bytes(core))
    receipt_path.write_bytes(image_view.canonical_json_bytes(value))
    os.chmod(receipt_path, 0o444)
    os.chmod(environment.run_dir, 0o555)


def test_build_and_independent_verify_never_enumerate_train_or_touch_geff(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    train = tiny_environment.root / tiny_environment.authority.source_relative
    train_identity = (train.stat().st_dev, train.stat().st_ino)
    original_listdir = image_view.os.listdir

    def guarded_listdir(path: int | str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> list[str]:
        if isinstance(path, int):
            info = os.fstat(path)
            if (info.st_dev, info.st_ino) == train_identity:
                raise AssertionError("data/train must never be enumerated")
        return original_listdir(path)

    monkeypatch.setattr(image_view.os, "listdir", guarded_listdir)
    before = (train / "never-touch.geff/secret.bin").read_bytes()
    built = image_view.build_image_view(tiny_environment.run_dir, now=lambda: "2026-09-04T01:02:03Z")
    assert built["status"] == "PASS"
    assert built["files"] == 4
    assert set(path.name for path in tiny_environment.run_dir.iterdir()) == {
        "IMAGE_VIEW",
        "IMAGE_VIEW_RECEIPT.json",
    }
    assert not any(path.suffix == ".geff" for path in (tiny_environment.run_dir / "IMAGE_VIEW").iterdir())
    assert image_view.verify_image_view(tiny_environment.run_dir)["status"] == "PASS"
    assert (train / "never-touch.geff/secret.bin").read_bytes() == before


def test_build_rejects_existing_target_without_modifying_it(tiny_environment: TinyEnvironment) -> None:
    tiny_environment.run_dir.mkdir(parents=True)
    marker = tiny_environment.run_dir / "owner.txt"
    marker.write_text("keep")
    with pytest.raises(FileExistsError):
        image_view.build_image_view(tiny_environment.run_dir)
    assert marker.read_text() == "keep"


def test_partial_clone_failure_removes_only_owned_staging(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def partial(source_fd: int, destination_parent_fd: int, destination_name: str) -> None:
        nonlocal calls
        calls += 1
        _fake_clone(source_fd, destination_parent_fd, destination_name)
        if calls == 2:
            raise OSError("injected clone failure")

    monkeypatch.setattr(image_view, "_clone_file", partial)
    with pytest.raises(OSError, match="injected clone failure"):
        image_view.build_image_view(tiny_environment.run_dir)
    parent = tiny_environment.run_dir.parent
    assert not tiny_environment.run_dir.exists()
    assert not [path for path in parent.iterdir() if path.name.startswith(".tiny-run.staging")]


def test_staging_open_failure_durably_removes_parent_recorded_directory(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = image_view._open_relative_directory
    injected = False

    def fail_just_created_staging(root_fd: int, relative: str | tuple[str, ...]) -> int:
        nonlocal injected
        parts = (relative,) if isinstance(relative, str) else relative
        if not injected and len(parts) == 1 and parts[0].startswith(".tiny-run.staging."):
            injected = True
            raise OSError("injected staging open failure")
        return original(root_fd, relative)

    monkeypatch.setattr(image_view, "_open_relative_directory", fail_just_created_staging)
    before = _fd_count()
    with pytest.raises(OSError, match="staging open failure"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert injected
    assert _fd_count() == before
    assert not tiny_environment.run_dir.exists()
    assert not [path for path in tiny_environment.run_dir.parent.iterdir() if path.name.startswith(".tiny-run.staging")]


def test_source_mutation_after_clone_is_a_toctou_failure(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutated = False

    def mutate_source(source_fd: int, destination_parent_fd: int, destination_name: str) -> None:
        nonlocal mutated
        _fake_clone(source_fd, destination_parent_fd, destination_name)
        if not mutated:
            source_info = os.fstat(source_fd)
            source_path = next(
                path for path in tiny_environment.source_files if path.stat().st_ino == source_info.st_ino
            )
            raw = source_path.read_bytes()
            source_path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            mutated = True

    monkeypatch.setattr(image_view, "_clone_file", mutate_source)
    with pytest.raises(image_view.ImageViewError, match="source changed after clone"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert not tiny_environment.run_dir.exists()


def test_clone_hardlink_or_same_inode_is_rejected_and_rolled_back(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def hardlink(source_fd: int, destination_parent_fd: int, destination_name: str) -> None:
        source_info = os.fstat(source_fd)
        source_path = next(path for path in tiny_environment.source_files if path.stat().st_ino == source_info.st_ino)
        os.link(source_path, destination_name, dst_dir_fd=destination_parent_fd)

    monkeypatch.setattr(image_view, "_clone_file", hardlink)
    with pytest.raises(image_view.ImageViewError):
        image_view.build_image_view(tiny_environment.run_dir)
    assert not tiny_environment.run_dir.exists()
    assert all(path.stat().st_nlink == 1 for path in tiny_environment.source_files)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_source_symlink_or_special_is_rejected(
    tiny_environment: TinyEnvironment,
    kind: str,
) -> None:
    source = tiny_environment.source_files[0]
    source.unlink()
    if kind == "symlink":
        source.symlink_to(tiny_environment.source_files[1])
    else:
        os.mkfifo(source)
    with pytest.raises(image_view.ImageViewError):
        image_view.build_image_view(tiny_environment.run_dir)
    assert not tiny_environment.run_dir.exists()


def test_source_extra_empty_directory_is_rejected(tiny_environment: TinyEnvironment) -> None:
    root = tiny_environment.root / tiny_environment.authority.source_relative
    (root / f"{tiny_environment.authority.stems[0]}.zarr/extra-empty").mkdir()
    with pytest.raises(image_view.ImageViewError, match="directory set drift"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert not tiny_environment.run_dir.exists()


@pytest.mark.parametrize("walker", ["absolute", "relative"])
@pytest.mark.parametrize("fault", ["fstat", "stat"])
def test_directory_open_fault_does_not_leak_new_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    walker: str,
    fault: str,
) -> None:
    leaf = tmp_path / "fd-leaf"
    leaf.mkdir()
    original_open = image_view.os.open
    original_fstat = image_view.os.fstat
    original_stat = image_view.os.stat
    leaf_fd: int | None = None

    def remember_leaf(path: object, *args: object, **kwargs: object) -> int:
        nonlocal leaf_fd
        fd = original_open(path, *args, **kwargs)
        if path == leaf.name:
            leaf_fd = fd
        return fd

    def fail_descriptor(fd: int) -> os.stat_result:
        if fault == "fstat" and fd == leaf_fd:
            raise OSError("injected directory identity fault")
        return original_fstat(fd)

    def fail_after_open(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if fault == "stat" and path == leaf.name:
            raise OSError("injected directory identity fault")
        return original_stat(path, *args, **kwargs)

    root_fd: int | None = None
    if walker == "relative":
        root_fd = os.open(tmp_path, os.O_RDONLY)
    before = _fd_count()
    monkeypatch.setattr(image_view.os, "open", remember_leaf)
    monkeypatch.setattr(image_view.os, "fstat", fail_descriptor)
    monkeypatch.setattr(image_view.os, "stat", fail_after_open)
    try:
        with pytest.raises(OSError, match="directory identity fault"):
            if walker == "absolute":
                image_view._open_absolute_directory(leaf)
            else:
                assert root_fd is not None
                image_view._open_relative_directory(root_fd, (leaf.name,))
    finally:
        monkeypatch.setattr(image_view.os, "open", original_open)
        monkeypatch.setattr(image_view.os, "fstat", original_fstat)
        monkeypatch.setattr(image_view.os, "stat", original_stat)
    assert _fd_count() == before
    if root_fd is not None:
        os.close(root_fd)


@pytest.mark.parametrize("fault", ["fstat", "stat"])
def test_regular_open_fault_does_not_leak_file_or_parent_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    directory = tmp_path / "source"
    directory.mkdir()
    (directory / "payload.bin").write_bytes(b"payload")
    root_fd = os.open(tmp_path, os.O_RDONLY)
    original_open = image_view.os.open
    original_fstat = image_view.os.fstat
    original_stat = image_view.os.stat
    payload_fd: int | None = None

    def remember_payload(path: object, *args: object, **kwargs: object) -> int:
        nonlocal payload_fd
        fd = original_open(path, *args, **kwargs)
        if path == "payload.bin":
            payload_fd = fd
        return fd

    def fail_descriptor(fd: int) -> os.stat_result:
        if fault == "fstat" and fd == payload_fd:
            raise OSError("injected regular identity fault")
        return original_fstat(fd)

    def fail_after_open(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if fault == "stat" and path == "payload.bin":
            raise OSError("injected regular identity fault")
        return original_stat(path, *args, **kwargs)

    before = _fd_count()
    monkeypatch.setattr(image_view.os, "open", remember_payload)
    monkeypatch.setattr(image_view.os, "fstat", fail_descriptor)
    monkeypatch.setattr(image_view.os, "stat", fail_after_open)
    try:
        with pytest.raises(OSError, match="regular identity fault"):
            image_view._open_relative_regular(root_fd, "source/payload.bin")
    finally:
        monkeypatch.setattr(image_view.os, "open", original_open)
        monkeypatch.setattr(image_view.os, "fstat", original_fstat)
        monkeypatch.setattr(image_view.os, "stat", original_stat)
    assert _fd_count() == before
    os.close(root_fd)


@pytest.mark.parametrize("helper", ["read", "open"])
def test_fifo_swap_is_rejected_without_blocking_in_subprocess(tmp_path: Path, helper: str) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"regular-before-swap")
    project_root = Path(__file__).resolve().parents[1]
    program = """
import os
import sys
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
import biohub.st_r3_image_view as image_view

root = sys.argv[1]
helper = sys.argv[2]
root_fd = os.open(root, os.O_RDONLY)
original_open = image_view.os.open
swapped = False

def swap_then_open(path, flags, *args, **kwargs):
    global swapped
    if path == "victim" and not swapped:
        swapped = True
        os.unlink(os.path.join(root, "victim"))
        os.mkfifo(os.path.join(root, "victim"))
    return original_open(path, flags, *args, **kwargs)

image_view.os.open = swap_then_open
try:
    if helper == "read":
        image_view._read_named_regular(root_fd, "victim")
    else:
        image_view._open_relative_regular(root_fd, "victim")
except image_view.ImageViewError:
    print("REJECTED")
else:
    raise SystemExit("FIFO was accepted")
finally:
    os.close(root_fd)
"""
    process = subprocess.run(
        (sys.executable, "-c", program, str(tmp_path), helper),
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"REJECTED\n"


def test_checkout_open_fault_closes_root_git_and_official_descriptors(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_open = image_view.os.open
    original_fstat = image_view.os.fstat
    official_fd: int | None = None

    def remember_official(path: object, *args: object, **kwargs: object) -> int:
        nonlocal official_fd
        fd = original_open(path, *args, **kwargs)
        if path == "official":
            official_fd = fd
        return fd

    def fail_official(fd: int) -> os.stat_result:
        if fd == official_fd:
            raise OSError("injected official fstat fault")
        return original_fstat(fd)

    before = _fd_count()
    monkeypatch.setattr(image_view.os, "open", remember_official)
    monkeypatch.setattr(image_view.os, "fstat", fail_official)
    with pytest.raises(OSError, match="official fstat fault"):
        image_view._validate_checkout(tiny_environment.root)
    monkeypatch.setattr(image_view.os, "open", original_open)
    monkeypatch.setattr(image_view.os, "fstat", original_fstat)
    assert _fd_count() == before


def test_build_closes_source_pair_when_destination_parent_open_fails(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_regular = image_view._open_relative_regular
    original_directory = image_view._open_relative_directory
    armed = False

    def arm_after_source(root_fd: int, relative: str) -> tuple[int, int]:
        nonlocal armed
        result = original_regular(root_fd, relative)
        armed = True
        return result

    def fail_destination(root_fd: int, relative: str | tuple[str, ...]) -> int:
        nonlocal armed
        if armed:
            armed = False
            raise OSError("injected destination-parent open failure")
        return original_directory(root_fd, relative)

    monkeypatch.setattr(image_view, "_open_relative_regular", arm_after_source)
    monkeypatch.setattr(image_view, "_open_relative_directory", fail_destination)
    before = _fd_count()
    with pytest.raises(OSError, match="destination-parent open failure"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert _fd_count() == before


def test_verify_closes_source_pair_when_destination_pair_open_fails(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_view.build_image_view(tiny_environment.run_dir)
    original_regular = image_view._open_relative_regular
    calls = 0

    def fail_second(root_fd: int, relative: str) -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected destination-pair open failure")
        return original_regular(root_fd, relative)

    monkeypatch.setattr(image_view, "_open_relative_regular", fail_second)
    before = _fd_count()
    with pytest.raises(OSError, match="destination-pair open failure"):
        image_view.verify_image_view(tiny_environment.run_dir)
    assert _fd_count() == before


def test_publication_failure_rolls_back_without_final_receipt(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        image_view,
        "_rename_noreplace",
        lambda _parent, _source, _destination: (_ for _ in ()).throw(OSError("publication failed")),
    )
    with pytest.raises(OSError, match="publication failed"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert not tiny_environment.run_dir.exists()
    assert not list(tiny_environment.run_dir.parent.iterdir())


def test_partial_receipt_write_is_removed_with_owned_staging(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def partial_write(parent_fd: int, name: str, raw: bytes, mode: int = 0o444) -> os.stat_result:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, dir_fd=parent_fd)
        try:
            os.write(fd, raw[: max(1, len(raw) // 2)])
            os.fsync(fd)
        finally:
            os.close(fd)
        raise OSError("injected receipt write failure")

    monkeypatch.setattr(image_view, "_write_new_regular", partial_write)
    with pytest.raises(OSError, match="receipt write failure"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert not tiny_environment.run_dir.exists()
    assert not list(tiny_environment.run_dir.parent.iterdir())


def test_parent_fsync_failure_after_rename_is_durably_rolled_back(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_fsync = image_view.os.fsync
    failed = False

    def fail_post_rename(fd: int) -> None:
        nonlocal failed
        if not failed and tiny_environment.run_dir.exists():
            parent_info = tiny_environment.run_dir.parent.stat()
            descriptor_info = os.fstat(fd)
            if (parent_info.st_dev, parent_info.st_ino) == (descriptor_info.st_dev, descriptor_info.st_ino):
                failed = True
                raise OSError("injected post-rename fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(image_view.os, "fsync", fail_post_rename)
    with pytest.raises(OSError, match="post-rename fsync failure"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert failed
    assert not tiny_environment.run_dir.exists()
    assert not list(tiny_environment.run_dir.parent.iterdir())


def test_success_has_no_fallible_construction_or_filesystem_probe_after_commit_fsync(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_fsync = image_view.os.fsync
    original_sha256 = image_view._sha256
    original_canonical = image_view.canonical_json_bytes
    original_name_info = image_view._name_info
    original_snapshot = image_view._assert_destination_snapshot
    committed = False

    def mark_commit(fd: int) -> None:
        nonlocal committed
        original_fsync(fd)
        if tiny_environment.run_dir.exists():
            parent_info = tiny_environment.run_dir.parent.stat()
            descriptor_info = os.fstat(fd)
            if (parent_info.st_dev, parent_info.st_ino) == (descriptor_info.st_dev, descriptor_info.st_ino):
                committed = True

    def reject_after_commit(function: Callable[..., object]) -> Callable[..., object]:
        def wrapped(*args: object, **kwargs: object) -> object:
            if committed:
                raise AssertionError("fallible work occurred after durable publication")
            return function(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(image_view.os, "fsync", mark_commit)
    monkeypatch.setattr(image_view, "_sha256", reject_after_commit(original_sha256))
    monkeypatch.setattr(image_view, "canonical_json_bytes", reject_after_commit(original_canonical))
    monkeypatch.setattr(image_view, "_name_info", reject_after_commit(original_name_info))
    monkeypatch.setattr(image_view, "_assert_destination_snapshot", reject_after_commit(original_snapshot))
    result = image_view.build_image_view(tiny_environment.run_dir)
    assert committed
    assert result["status"] == "PASS"
    assert result["receipt_sha256"]


def test_racing_external_target_is_never_overwritten_or_removed(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def race_target(source_fd: int, destination_parent_fd: int, destination_name: str) -> None:
        nonlocal calls
        _fake_clone(source_fd, destination_parent_fd, destination_name)
        calls += 1
        if calls == len(tiny_environment.source_files):
            tiny_environment.run_dir.mkdir()
            (tiny_environment.run_dir / "external-owner.txt").write_text("keep")

    monkeypatch.setattr(image_view, "_clone_file", race_target)
    with pytest.raises(FileExistsError):
        image_view.build_image_view(tiny_environment.run_dir)
    assert (tiny_environment.run_dir / "external-owner.txt").read_text() == "keep"
    assert not [path for path in tiny_environment.run_dir.parent.iterdir() if path.name.startswith(".tiny-run.staging")]


def test_publication_rollback_ambiguity_is_explicit_and_never_reports_pass(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def ambiguous(parent_fd: int, source: str, destination: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            os.rename(source, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        raise OSError("ambiguous publication")

    monkeypatch.setattr(image_view, "_rename_noreplace", ambiguous)
    with pytest.raises(image_view.PublicationAmbiguityError):
        image_view.build_image_view(tiny_environment.run_dir)
    assert tiny_environment.run_dir.exists()


def test_verify_rehash_rejects_equal_size_destination_drift(tiny_environment: TinyEnvironment) -> None:
    image_view.build_image_view(tiny_environment.run_dir)
    path = _published_file(tiny_environment)
    original = path.read_bytes()
    os.chmod(path, 0o600)
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    os.chmod(path, 0o444)
    with pytest.raises(image_view.ImageViewError):
        image_view.verify_image_view(tiny_environment.run_dir)


def test_verify_rejects_destination_hardlink_and_extra_path(tiny_environment: TinyEnvironment) -> None:
    image_view.build_image_view(tiny_environment.run_dir)
    path = _published_file(tiny_environment)
    os.chmod(path.parent, 0o700)
    os.link(path, path.parent / "extra.bin")
    os.chmod(path.parent, 0o555)
    with pytest.raises(image_view.ImageViewError):
        image_view.verify_image_view(tiny_environment.run_dir)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "empty_directory"])
def test_verify_rejects_extra_symlink_special_and_case_collision(
    tiny_environment: TinyEnvironment,
    kind: str,
) -> None:
    image_view.build_image_view(tiny_environment.run_dir)
    view = tiny_environment.run_dir / "IMAGE_VIEW"
    os.chmod(view, 0o700)
    if kind == "symlink":
        (view / "extra").symlink_to(_published_file(tiny_environment))
    elif kind == "fifo":
        os.mkfifo(view / "extra")
    else:
        (view / "extra").mkdir()
    os.chmod(view, 0o555)
    with pytest.raises(image_view.ImageViewError):
        image_view.verify_image_view(tiny_environment.run_dir)


def test_case_colliding_inventory_paths_are_rejected() -> None:
    with pytest.raises(image_view.ImageViewError, match="case-colliding"):
        image_view._assert_no_case_collisions(("root.zarr/Data/a", "root.zarr/data/b"))


def test_forged_receipt_identity_is_rejected_even_with_recomputed_content_hash(
    tiny_environment: TinyEnvironment,
) -> None:
    image_view.build_image_view(tiny_environment.run_dir)

    def forge(value: dict[str, object]) -> None:
        records = value["records"]
        assert isinstance(records, list)
        first = records[0]
        assert isinstance(first, dict)
        first["destination"] = first["source_after"]
        evidence = value["evidence"]
        assert isinstance(evidence, dict)
        evidence["destination_records_sha256"] = image_view._record_digest(records, "destination")

    _rewrite_receipt(tiny_environment, forge)
    with pytest.raises(image_view.ImageViewError, match="hardlink"):
        image_view.verify_image_view(tiny_environment.run_dir)


def test_receipt_cannot_redirect_to_an_alternate_authority_path(tiny_environment: TinyEnvironment) -> None:
    image_view.build_image_view(tiny_environment.run_dir)

    def redirect(value: dict[str, object]) -> None:
        authority = value["authority"]
        assert isinstance(authority, dict)
        ready = authority["ready"]
        assert isinstance(ready, dict)
        ready["path"] = "authority/alternate.json"

    _rewrite_receipt(tiny_environment, redirect)
    with pytest.raises(image_view.ImageViewError, match="authority binding"):
        image_view.verify_image_view(tiny_environment.run_dir)


def test_forged_ready_is_rejected_before_source_clone(tiny_environment: TinyEnvironment) -> None:
    ready_path = tiny_environment.root / tiny_environment.authority.ready_relative
    value = json.loads(ready_path.read_bytes())
    value["status"] = "FORGED"
    ready_path.write_bytes(image_view.canonical_json_bytes(value))
    with pytest.raises(image_view.ImageViewError, match="READY hash drift"):
        image_view.build_image_view(tiny_environment.run_dir)
    assert not tiny_environment.run_dir.exists()


@pytest.mark.parametrize("artifact", ["ready", "receipt"])
def test_noncanonical_json_is_rejected(tiny_environment: TinyEnvironment, artifact: str) -> None:
    if artifact == "receipt":
        image_view.build_image_view(tiny_environment.run_dir)
        path = tiny_environment.run_dir / "IMAGE_VIEW_RECEIPT.json"
        value = json.loads(path.read_bytes())
        os.chmod(tiny_environment.run_dir, 0o700)
        os.chmod(path, 0o600)
        path.write_text(json.dumps(value, indent=2) + "\n")
        os.chmod(path, 0o444)
        os.chmod(tiny_environment.run_dir, 0o555)
        with pytest.raises(image_view.ImageViewError, match="noncanonical JSON"):
            image_view.verify_image_view(tiny_environment.run_dir)
    else:
        path = tiny_environment.root / tiny_environment.authority.ready_relative
        value = json.loads(path.read_bytes())
        raw = (json.dumps(value, indent=2) + "\n").encode()
        path.write_bytes(raw)
        replacement = image_view.dataclasses.replace(tiny_environment.authority, ready_sha256=image_view._sha256(raw))
        image_view.PRODUCTION_AUTHORITY = replacement
        with pytest.raises(image_view.ImageViewError, match="noncanonical JSON"):
            image_view.build_image_view(tiny_environment.run_dir)


def test_git_capture_binds_descriptor_bytes_to_exact_head_blobs(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_view, "_run_git", _mock_clean_git(tiny_environment))
    assert _CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority) == tiny_environment.git_state

    builder = tiny_environment.root / tiny_environment.authority.builder_sources[0]
    builder.write_bytes(builder.read_bytes() + b"-hidden-drift")
    with pytest.raises(image_view.ImageViewError, match="differ from HEAD"):
        _CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


@pytest.mark.parametrize("index_prefix", ["h", "S"])
def test_git_capture_rejects_assume_unchanged_and_skip_worktree(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    index_prefix: str,
) -> None:
    monkeypatch.setattr(
        image_view,
        "_run_git",
        _mock_clean_git(tiny_environment, index_prefix=index_prefix),
    )
    with pytest.raises(image_view.ImageViewError, match="index flags"):
        _CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


def test_git_capture_rejects_forged_head_blob_oid(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        image_view,
        "_run_git",
        _mock_clean_git(tiny_environment, blob_override="f" * 40),
    )
    with pytest.raises(image_view.ImageViewError, match="blob identity"):
        _CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


@pytest.mark.parametrize("index_prefix", ["h", "S"])
def test_git_capture_rejects_unsafe_official_index_flags(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    index_prefix: str,
) -> None:
    monkeypatch.setattr(
        image_view,
        "_run_git",
        _mock_clean_git(tiny_environment, official_index_prefix=index_prefix),
    )
    with pytest.raises(image_view.ImageViewError, match="official index has unsafe flags"):
        _CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


@pytest.mark.parametrize("artifact", ["regular-bytes", "regular-mode", "symlink-target"])
def test_git_capture_rejects_official_worktree_drift_hidden_from_status(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    monkeypatch.setattr(image_view, "_run_git", _mock_clean_git(tiny_environment))
    if artifact == "regular-bytes":
        (tiny_environment.root / "official/tracked.txt").write_bytes(b"official-forged-bytes\n")
    elif artifact == "regular-mode":
        (tiny_environment.root / "official/tracked.txt").chmod(0o600)
    else:
        link = tiny_environment.root / "official/tracked-link"
        link.unlink()
        link.symlink_to("forged.txt")
    with pytest.raises(image_view.ImageViewError, match="official"):
        _CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


def test_official_head_parser_rejects_case_collision_and_gitlink_contract(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_oid = "a" * 40
    second_oid = "b" * 40
    case_collision = (
        f"100644 blob {first_oid}\tPath.txt".encode() + b"\0" + f"100644 blob {second_oid}\tpath.txt".encode() + b"\0"
    )
    with pytest.raises(image_view.ImageViewError, match="case-colliding"):
        image_view._parse_official_head(case_collision)

    gitlink = f"160000 commit {'c' * 40}\tnested".encode() + b"\0"
    parsed = image_view._parse_official_head(gitlink)
    index = f"H 160000 {'c' * 40} 0\tnested".encode() + b"\0"

    def gitlink_git(root: Path, *arguments: str) -> bytes:
        if arguments[0] == "ls-tree":
            return gitlink
        if arguments[0] == "ls-files":
            return index
        raise AssertionError((root, arguments))

    assert parsed[0][0] == "160000"
    monkeypatch.setattr(image_view, "_run_git", gitlink_git)
    official_fd = os.open(tiny_environment.root / "official", os.O_RDONLY)
    try:
        with pytest.raises(image_view.ImageViewError, match="gitlinks are forbidden"):
            image_view._validate_official_checkout(
                tiny_environment.root,
                official_fd,
                tiny_environment.authority.official_oid,
            )
    finally:
        os.close(official_fd)


@pytest.mark.parametrize("name", [".git", "official"])
def test_checkout_guard_rejects_git_or_official_path_identity_swap(
    tiny_environment: TinyEnvironment,
    name: str,
) -> None:
    guard = image_view._validate_checkout(tiny_environment.root)
    original = tiny_environment.root / name
    displaced = tiny_environment.root / f"{name}.held"
    original.rename(displaced)
    original.mkdir()
    try:
        with pytest.raises(image_view.ImageViewError, match="identity drift"):
            image_view._assert_checkout_rebound(tiny_environment.root, guard)
    finally:
        original.rmdir()
        displaced.rename(original)
        guard.close()


def test_checkout_guard_rejects_held_root_identity_drift(tiny_environment: TinyEnvironment) -> None:
    guard = image_view._validate_checkout(tiny_environment.root)
    forged = image_view.dataclasses.replace(
        guard,
        root_identity=(guard.root_identity[0], guard.root_identity[1] + 1, guard.root_identity[2]),
    )
    try:
        with pytest.raises(image_view.ImageViewError, match="descriptor drift"):
            image_view._assert_checkout_rebound(tiny_environment.root, forged)
    finally:
        guard.close()


def test_dirty_checkout_and_worktree_gitfile_are_rejected(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        image_view,
        "_run_git",
        lambda _root, *arguments: b"?? dirty.py\n" if arguments and arguments[0] == "status" else b"",
    )
    with pytest.raises(image_view.ImageViewError, match="not clean"):
        _CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere\n")
    monkeypatch.chdir(worktree)
    with pytest.raises(image_view.ImageViewError, match="linked worktrees"):
        image_view._validate_checkout(worktree)


def test_run_directory_must_be_directly_below_fixed_parent(tiny_environment: TinyEnvironment) -> None:
    outside = tiny_environment.root / "elsewhere/run"
    with pytest.raises(image_view.ImageViewError, match="fixed output parent"):
        image_view.build_image_view(outside)


def test_duplicate_and_nonfinite_json_are_rejected() -> None:
    with pytest.raises(image_view.ImageViewError, match="duplicate"):
        image_view._strict_json_bytes(b'{"x":1,"x":2}\n')
    with pytest.raises(image_view.ImageViewError, match="non-finite"):
        image_view._strict_json_bytes(b'{"x":1e999}\n')


@pytest.mark.skipif(sys.platform != "darwin", reason="production clone primitive is macOS-only")
def test_real_apfs_fclonefileat_creates_an_independent_inode(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination"
    source.write_bytes(b"real-clone-canary" * 64)
    source.chmod(0o640)
    os.utime(source, ns=(1_700_000_000_123_456_789, 1_700_000_000_987_654_321))
    destination.mkdir()
    source_fd = os.open(source, os.O_RDONLY)
    destination_fd = os.open(destination, os.O_RDONLY)
    try:
        if _FILESYSTEM_TYPE(destination, destination_fd) != "apfs":
            pytest.skip("Darwin test filesystem is not APFS")
        source_before = os.fstat(source_fd)
        _CLONE_FILE(source_fd, destination_fd, "clone.bin")
        source_after = os.fstat(source_fd)
    finally:
        os.close(destination_fd)
        os.close(source_fd)
    clone = destination / "clone.bin"
    clone_info = clone.stat()
    assert clone.read_bytes() == source.read_bytes()
    assert (clone_info.st_dev, clone_info.st_ino) != (source_after.st_dev, source_after.st_ino)
    assert clone_info.st_nlink == source_after.st_nlink == 1
    assert (source_after.st_mode, source_after.st_mtime_ns, source_after.st_ctime_ns) == (
        source_before.st_mode,
        source_before.st_mtime_ns,
        source_before.st_ctime_ns,
    )
    assert (stat.S_IMODE(clone_info.st_mode), clone_info.st_mtime_ns) == (
        stat.S_IMODE(source_after.st_mode),
        source_after.st_mtime_ns,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="production publication primitive is macOS-only")
def test_real_renameatx_np_excl_preserves_both_directories_on_collision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "source-owner").write_bytes(b"source")
    (destination / "destination-owner").write_bytes(b"destination")
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    try:
        with pytest.raises(FileExistsError):
            _RENAME_NOREPLACE(parent_fd, source.name, destination.name)
    finally:
        os.close(parent_fd)
    assert (source / "source-owner").read_bytes() == b"source"
    assert (destination / "destination-owner").read_bytes() == b"destination"


def test_cli_argument_failures_are_concise_canonical_json() -> None:
    project_root = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        (sys.executable, str(project_root / "scripts/experiments/st_r3/st_r3_image_view.py"), "unknown"),
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert process.returncode == 1
    value = json.loads(process.stderr)
    assert value == {"error": "ImageViewError", "status": "FAIL"}
    assert process.stderr == image_view.canonical_json_bytes(value)
    assert process.stdout == b""
