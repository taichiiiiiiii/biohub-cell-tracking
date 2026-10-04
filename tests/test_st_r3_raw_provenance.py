from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from biohub import st_r3_raw_provenance as provenance

_REAL_CAPTURE_GIT_STATE = provenance._capture_git_state


@dataclass(frozen=True)
class TinyEnvironment:
    root: Path
    run: Path
    raw: Path
    download: Path
    runtime: Path
    log: Path
    authority: provenance.Authority
    git: provenance.GitState


def _write_json(path: Path, value: object) -> bytes:
    raw = provenance.canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _tree_values(root: Path) -> tuple[int, int, str, str]:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_file():
            raw = path.read_bytes()
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    legacy = b"".join(f"{record['sha256']}  ./{record['path']}\n".encode() for record in records)
    return (
        len(records),
        sum(int(record["bytes"]) for record in records),
        hashlib.sha256(provenance.canonical_json_bytes(records)).hexdigest(),
        hashlib.sha256(legacy).hexdigest(),
    )


def _fd_count() -> int:
    return len(os.listdir("/dev/fd"))


def _assert_base_fault_group(
    error: BaseException,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    group = error.__cause__
    assert isinstance(group, BaseExceptionGroup)
    assert len(group.exceptions) == 2
    assert isinstance(group.exceptions[0], original_type)
    assert isinstance(group.exceptions[1], recovery_type)


def _mock_clean_git(
    environment: TinyEnvironment,
    *,
    builder_index_prefix: str = "H",
    unlisted_index_prefix: str = "H",
    gitlink_index_prefix: str = "H",
    official_index_prefix: str = "H",
) -> Callable[..., bytes]:
    builder: dict[str, tuple[str, str, bytes]] = {}
    for relative in environment.authority.builder_sources:
        path = environment.root / relative
        raw = path.read_bytes()
        mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        builder[relative] = (mode, provenance._git_blob_oid(raw), raw)

    superproject: list[tuple[str, str, str, str, bytes | None]] = []
    for relative in (*environment.authority.builder_sources, "tracked/unlisted.txt", "tracked/unlisted-link"):
        path = environment.root / relative
        if path.is_symlink():
            mode = "120000"
            raw = os.fsencode(os.readlink(path))
        else:
            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            raw = path.read_bytes()
        superproject.append((mode, "blob", provenance._git_blob_oid(raw), relative, raw))
    superproject.append(("160000", "commit", environment.authority.official_oid, "official", None))
    superproject.sort(key=lambda item: item[3].encode())

    official: list[tuple[str, str, str, bytes]] = []
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
        official.append((mode, provenance._git_blob_oid(raw), relative, raw))
    blobs = {oid: raw for _mode, oid, _relative, raw in official}
    blobs.update({oid: raw for _relative, (_mode, oid, raw) in builder.items()})
    blobs.update({oid: raw for _mode, _kind, oid, _relative, raw in superproject if raw is not None})

    def run_git(root: Path, *arguments: str) -> bytes:
        if arguments[0] == "status":
            return b""
        if arguments == ("rev-parse", "--verify", "HEAD"):
            return (
                environment.authority.official_oid if root.name == "official" else environment.git.commit
            ).encode() + b"\n"
        if arguments == ("rev-parse", "--verify", "HEAD^{tree}"):
            return environment.git.tree.encode() + b"\n"
        if arguments == ("rev-parse", "--verify", "HEAD:official"):
            return environment.authority.official_oid.encode() + b"\n"
        if root.name == "official" and arguments == ("ls-tree", "-rz", "--full-tree", "HEAD"):
            return b"".join(f"{mode} blob {oid}\t{relative}".encode() + b"\0" for mode, oid, relative, _raw in official)
        if root.name == "official" and arguments == ("ls-files", "-z", "--stage", "-v"):
            return b"".join(
                f"{official_index_prefix} {mode} {oid} 0\t{relative}".encode() + b"\0"
                for mode, oid, relative, _raw in official
            )
        if root == environment.root and arguments == ("ls-tree", "-rz", "--full-tree", "HEAD"):
            return b"".join(
                f"{mode} {kind} {oid}\t{relative}".encode() + b"\0" for mode, kind, oid, relative, _raw in superproject
            )
        if root == environment.root and arguments == ("ls-files", "-z", "--stage", "-v"):
            chunks: list[bytes] = []
            for mode, _kind, oid, relative, _raw in superproject:
                if relative in environment.authority.builder_sources:
                    prefix = builder_index_prefix
                elif relative == "official":
                    prefix = gitlink_index_prefix
                else:
                    prefix = unlisted_index_prefix
                chunks.append(f"{prefix} {mode} {oid} 0\t{relative}".encode() + b"\0")
            return b"".join(chunks)
        if arguments[:5] == ("ls-tree", "-rz", "--full-tree", "HEAD", "--"):
            relative = arguments[5]
            mode, oid, _raw = builder[relative]
            return f"{mode} blob {oid}\t{relative}".encode() + b"\0"
        if arguments[:5] == ("ls-files", "-z", "--stage", "-v", "--"):
            relative = arguments[5]
            mode, oid, _raw = builder[relative]
            return f"{builder_index_prefix} {mode} {oid} 0\t{relative}".encode() + b"\0"
        if arguments[:2] == ("cat-file", "blob"):
            return blobs[arguments[2]]
        raise AssertionError((root, arguments))

    return run_git


def _fake_rename(parent_fd: int, source: str, destination: str) -> str:
    try:
        os.stat(destination, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(destination)
    os.rename(source, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    return "test-no-replace"


@pytest.fixture
def tiny_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TinyEnvironment:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "official").mkdir()
    (root / "official" / "tracked.txt").write_bytes(b"official\n")
    (root / "official" / "tracked-link").symlink_to("tracked.txt")
    for relative in ("src/biohub/st_r3_raw_provenance.py", "scripts/experiments/st_r3/st_r3_raw_provenance.py"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"fixture:{relative}\n".encode())
    (root / "tracked").mkdir()
    (root / "tracked" / "unlisted.txt").write_bytes(b"unlisted tracked bytes\n")
    (root / "tracked" / "unlisted-link").symlink_to("unlisted.txt")
    raw_root = root / "raw"
    for stem, payload in (("alpha", b"alpha"), ("beta", b"beta-data")):
        geff = raw_root / f"{stem}.geff"
        (geff / "nodes" / "c").mkdir(parents=True)
        (geff / "zarr.json").write_bytes(b"{}")
        (geff / "nodes" / "c" / "0").write_bytes(payload)
    file_count, total_bytes, records_sha, legacy_sha = _tree_values(raw_root)

    evidence = root / "evidence"
    evidence.mkdir()
    runtime = evidence / "runtime.json"
    runtime_raw = _write_json(
        runtime,
        {
            "checkpoint_sha256": {
                "deepcenter": provenance.DEEPCENTER_SHA256,
                "primary": provenance.PRIMARY_WEIGHT_SHA256,
                "secondary": provenance.SECONDARY_WEIGHT_SHA256,
            },
            "ground_truth_accessed": False,
            "status": "complete_label_free_runtime_integrity",
            "support_repo_python_file_count": 13,
            "support_repo_python_manifest_sha256": provenance.SUPPORT_MANIFEST_SHA256,
        },
    )
    log = evidence / "raw.log"
    log_raw = (
        f"Weight sha256: {provenance.PRIMARY_WEIGHT_SHA256}\n"
        f"Primary materialized SHA256: {provenance.PRIMARY_WEIGHT_SHA256}\n"
        f"Secondary SHA256: {provenance.SECONDARY_WEIGHT_SHA256}\n"
        "VALIDATOR: merged 36 prediction graphs into "
        "/kaggle/working/tracking_repo/predictions/unknown/unet_transformer_val/split_0\n"
        "VALIDATOR: prediction completed in 75.25 minutes\n"
    ).encode()
    log.write_bytes(log_raw)
    runtime_pin = provenance.FilePin("evidence/runtime.json", len(runtime_raw), hashlib.sha256(runtime_raw).hexdigest())
    log_pin = provenance.FilePin("evidence/raw.log", len(log_raw), hashlib.sha256(log_raw).hexdigest())
    raw_manifest_relative = "../frozen/raw"
    download = evidence / "download.json"
    download_raw = _write_json(
        download,
        {
            "raw_geff": {
                "bytes": total_bytes,
                "canonical_sha256sum_tree_sha256": legacy_sha,
                "files": file_count,
                "path": raw_manifest_relative,
                "resume_verification_runs": 1,
                "roots": 2,
                "zarr_semantic_validation": "passed",
            },
            "reference_files": {
                "raw.log": {"bytes": len(log_raw), "sha256": hashlib.sha256(log_raw).hexdigest()},
                "runtime.json": {
                    "bytes": len(runtime_raw),
                    "sha256": hashlib.sha256(runtime_raw).hexdigest(),
                },
            },
            "source": {
                "kernel": "taichiiiii/biohub-eval-train-raw",
                "kernel_id": 131_740_073,
                "latest_status": "KernelWorkerStatus.COMPLETE",
                "version": 11,
            },
        },
    )
    authority = provenance.Authority(
        output_parent_relative="outputs/local/st_r3_raw_provenance",
        raw_root_relative="raw",
        raw_manifest_relative=raw_manifest_relative,
        stems=("alpha", "beta"),
        raw_files=file_count,
        raw_bytes=total_bytes,
        raw_records_sha256=records_sha,
        raw_legacy_tree_sha256=legacy_sha,
        download_manifest=provenance.FilePin(
            "evidence/download.json", len(download_raw), hashlib.sha256(download_raw).hexdigest()
        ),
        runtime_integrity=runtime_pin,
        derivation_log=log_pin,
        official_oid="c" * 40,
        primary_weight_sha256=provenance.PRIMARY_WEIGHT_SHA256,
        secondary_weight_sha256=provenance.SECONDARY_WEIGHT_SHA256,
        deepcenter_sha256=provenance.DEEPCENTER_SHA256,
        support_manifest_sha256=provenance.SUPPORT_MANIFEST_SHA256,
        builder_sources=("src/biohub/st_r3_raw_provenance.py", "scripts/experiments/st_r3/st_r3_raw_provenance.py"),
    )
    git = provenance.GitState(commit="a" * 40, tree="b" * 40, official_oid=authority.official_oid)
    monkeypatch.chdir(root)
    monkeypatch.setattr(provenance, "CANONICAL_REPO_ROOT", root)
    monkeypatch.setattr(provenance, "PRODUCTION_AUTHORITY", authority)
    monkeypatch.setattr(provenance, "_capture_git_state", lambda _root, _authority, _guard=None: git)
    monkeypatch.setattr(provenance, "_rename_noreplace", _fake_rename)
    return TinyEnvironment(
        root=root,
        run=root / authority.output_parent_relative / "run-one",
        raw=raw_root,
        download=download,
        runtime=runtime,
        log=log,
        authority=authority,
        git=git,
    )


def _build(environment: TinyEnvironment) -> dict[str, object]:
    return provenance.build_raw_provenance(environment.run)


def _rewrite_receipt(
    environment: TinyEnvironment,
    name: str,
    mutate: Callable[[dict[str, object]], None],
) -> Path:
    path = environment.run / name
    os.chmod(environment.run, 0o755)
    os.chmod(path, 0o644)
    value = json.loads(path.read_bytes())
    mutate(value)
    path.write_bytes(provenance.canonical_json_bytes(value))
    os.chmod(path, 0o444)
    os.chmod(environment.run, 0o555)
    return path


def test_clean_build_and_independent_verify_remain_explicitly_unverified(
    tiny_environment: TinyEnvironment,
) -> None:
    built = _build(tiny_environment)
    verified = provenance.verify_raw_provenance(tiny_environment.run)

    assert built == verified
    assert verified["status"] == provenance.STATUS
    assert verified["remaining_hold"] == provenance.REMAINING_HOLD
    receipts = verified["receipts"]
    assert receipts["primary"]["sha256"] != receipts["secondary"]["sha256"]
    assert receipts["primary"]["path"] != receipts["secondary"]["path"]
    for name, role in (
        (provenance.PRIMARY_RECEIPT, "primary"),
        (provenance.SECONDARY_RECEIPT, "secondary"),
    ):
        value = json.loads((tiny_environment.run / name).read_bytes())
        assert value["schema_version"] == provenance.SCHEMA_VERSION
        assert value["status"] == provenance.STATUS
        assert value["role"] == role
        assert value["source"] == {
            "commit": "a" * 40,
            "git_tree_oid": "b" * 40,
            "official_gitlink": tiny_environment.authority.official_oid,
        }
        assert value["claims"] == {
            "checkpoint_bytes_verified_by_this_receipt": False,
            "checkpoint_to_raw_cryptographic_proof": False,
            "legacy_log_and_runtime_receipts_verified": True,
        }
        assert "training" not in json.dumps(value).lower()


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("raw_root", "raw-wrong"),
        ("raw_records_sha256", "0" * 64),
    ),
)
def test_wrong_raw_path_or_declared_digest_is_rejected(
    tiny_environment: TinyEnvironment,
    field: str,
    replacement: str,
) -> None:
    _build(tiny_environment)
    _rewrite_receipt(
        tiny_environment,
        provenance.PRIMARY_RECEIPT,
        lambda value: value.__setitem__(field, replacement),
    )
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


def test_wrong_raw_file_count_is_rejected(tiny_environment: TinyEnvironment) -> None:
    _build(tiny_environment)
    (tiny_environment.raw / "alpha.geff" / "extra").write_bytes(b"")
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


def test_wrong_raw_byte_count_and_content_digest_are_rejected(tiny_environment: TinyEnvironment) -> None:
    _build(tiny_environment)
    target = tiny_environment.raw / "alpha.geff" / "zarr.json"
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


@pytest.mark.parametrize(
    ("name", "field", "replacement"),
    (
        (provenance.SECONDARY_RECEIPT, "role", "primary"),
        (provenance.PRIMARY_RECEIPT, "known_weight_sha256", "0" * 64),
    ),
)
def test_same_role_or_dummy_weight_hash_is_rejected(
    tiny_environment: TinyEnvironment,
    name: str,
    field: str,
    replacement: str,
) -> None:
    _build(tiny_environment)
    _rewrite_receipt(tiny_environment, name, lambda value: value.__setitem__(field, replacement))
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


@pytest.mark.parametrize("artifact", ("download", "runtime", "log"))
def test_modified_pinned_evidence_is_rejected(
    tiny_environment: TinyEnvironment,
    artifact: str,
) -> None:
    _build(tiny_environment)
    path = getattr(tiny_environment, artifact)
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "special"))
def test_pinned_evidence_symlink_hardlink_and_special_are_rejected_without_blocking(
    tiny_environment: TinyEnvironment,
    kind: str,
) -> None:
    _build(tiny_environment)
    target = tiny_environment.download
    original = target.read_bytes()
    target.unlink()
    external = tiny_environment.root / "external-evidence"
    external.write_bytes(original)
    if kind == "symlink":
        target.symlink_to(external)
    elif kind == "hardlink":
        os.link(external, target)
    else:
        os.mkfifo(target)
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


def test_true_only_or_overstated_claim_is_rejected(tiny_environment: TinyEnvironment) -> None:
    _build(tiny_environment)

    def mutate(value: dict[str, object]) -> None:
        value["claims"] = {"checkpoint_to_raw_cryptographic_proof": True}

    _rewrite_receipt(tiny_environment, provenance.PRIMARY_RECEIPT, mutate)
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


@pytest.mark.parametrize(
    "raw",
    (
        b'{"role":"primary","role":"secondary"}\n',
        b'{"value":1e999}\n',
        b'{"value":NaN}\n',
    ),
)
def test_duplicate_and_nonfinite_json_are_rejected(raw: bytes) -> None:
    with pytest.raises(provenance.RawProvenanceError):
        provenance._strict_json_bytes(raw, canonical=True)


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "special"))
def test_raw_symlink_hardlink_and_special_entries_are_rejected(
    tiny_environment: TinyEnvironment,
    kind: str,
) -> None:
    _build(tiny_environment)
    target = tiny_environment.raw / "alpha.geff" / "zarr.json"
    target.unlink()
    external = tiny_environment.root / "external"
    external.write_bytes(b"{}")
    if kind == "symlink":
        target.symlink_to(external)
    elif kind == "hardlink":
        os.link(external, target)
    else:
        os.mkfifo(target)
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


def test_case_colliding_raw_paths_are_rejected(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tiny_environment.raw / "alpha.geff"
    (directory / "Case").write_bytes(b"a")
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    original_listdir = os.listdir

    def colliding_listdir(path: int | str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> list[str]:
        if path == directory_fd:
            return ["Case", "case"]
        return original_listdir(path)

    monkeypatch.setattr(os, "listdir", colliding_listdir)
    try:
        with pytest.raises(provenance.RawProvenanceError, match="case collision"):
            provenance._walk_directory(directory_fd, "alpha.geff", [], [])
    finally:
        os.close(directory_fd)


def test_raw_mutation_between_two_scans_is_a_toctou_failure(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = provenance._scan_raw_tree
    calls = 0

    def mutate_after_scan(root_fd: int, authority: provenance.Authority) -> provenance.RawSnapshot:
        nonlocal calls
        result = original(root_fd, authority)
        calls += 1
        if calls == 1:
            target = tiny_environment.raw / "alpha.geff" / "zarr.json"
            target.write_bytes(b"changed")
        return result

    monkeypatch.setattr(provenance, "_scan_raw_tree", mutate_after_scan)
    with pytest.raises(provenance.RawProvenanceError):
        _build(tiny_environment)
    parent = tiny_environment.root / tiny_environment.authority.output_parent_relative
    assert not tiny_environment.run.exists()
    assert not parent.exists() or not any(path.name.startswith(".staging.") for path in parent.iterdir())


@pytest.mark.parametrize("status", (b" M tracked.py\n", b"?? untracked.py\n"))
def test_complete_git_status_rejects_dirty_and_untracked(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    status: bytes,
) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_git(root: Path, *arguments: str) -> bytes:
        calls.append((root, arguments))
        if arguments[0] == "status" and root == tiny_environment.root:
            return status
        raise AssertionError("dirty status must stop source capture")

    monkeypatch.setattr(provenance, "_run_git", fake_git)
    with pytest.raises(provenance.RawProvenanceError, match="completely clean"):
        _REAL_CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)
    assert calls[0][1] == (
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )


def test_gitfile_worktree_is_rejected_before_authority_read(tiny_environment: TinyEnvironment) -> None:
    (tiny_environment.root / ".git").rmdir()
    (tiny_environment.root / ".git").write_text("gitdir: elsewhere\n")
    with pytest.raises(provenance.RawProvenanceError, match="worktrees"):
        _build(tiny_environment)


def test_existing_target_is_never_overwritten_or_deleted(tiny_environment: TinyEnvironment) -> None:
    _build(tiny_environment)
    before = {path.name: path.read_bytes() for path in tiny_environment.run.iterdir()}
    with pytest.raises(FileExistsError):
        _build(tiny_environment)
    after = {path.name: path.read_bytes() for path in tiny_environment.run.iterdir()}
    assert after == before


def test_casefold_output_collision_is_rejected_without_touching_existing(
    tiny_environment: TinyEnvironment,
) -> None:
    existing = tiny_environment.run.parent / "RUN-ONE"
    existing.mkdir(parents=True)
    marker = existing / "marker"
    marker.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        _build(tiny_environment)
    assert marker.read_bytes() == b"keep"


def test_publication_ambiguity_is_explicit_and_never_returns_a_verdict(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def ambiguous_rename(parent_fd: int, source: str, destination: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            os.rename(source, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            raise OSError("uncertain return after rename")
        raise OSError("rollback unavailable")

    monkeypatch.setattr(provenance, "_rename_noreplace", ambiguous_rename)
    with pytest.raises(provenance.PublicationAmbiguityError):
        _build(tiny_environment)
    assert tiny_environment.run.is_dir()


def test_public_build_rejects_staging_displacement_and_preserves_foreign_bytes(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_collect = provenance._collect_authority
    calls = 0

    def displace_after_second_collection(*args: object, **kwargs: object) -> provenance.CollectedAuthority:
        nonlocal calls
        collected = original_collect(*args, **kwargs)
        calls += 1
        if calls == 2:
            parent = tiny_environment.root / tiny_environment.authority.output_parent_relative
            staging = next(path for path in parent.iterdir() if path.name.startswith(".staging."))
            staging.rename(parent / f"{staging.name}.owned-displaced")
            staging.mkdir()
            (staging / "foreign-sentinel").write_bytes(b"foreign")
        return collected

    monkeypatch.setattr(provenance, "_collect_authority", displace_after_second_collection)
    before = _fd_count()
    with pytest.raises(provenance.PublicationAmbiguityError):
        _build(tiny_environment)
    assert _fd_count() == before
    parent = tiny_environment.root / tiny_environment.authority.output_parent_relative
    foreign = next(path for path in parent.iterdir() if (path / "foreign-sentinel").is_file())
    assert (foreign / "foreign-sentinel").read_bytes() == b"foreign"
    assert any(path.name.endswith(".owned-displaced") for path in parent.iterdir())
    assert not tiny_environment.run.exists()


def test_public_build_parent_displacement_never_succeeds_and_preserves_foreign(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tiny_environment.root / tiny_environment.authority.output_parent_relative
    displaced = parent.with_name("st_r3_raw_provenance.displaced")
    calls = 0

    def rename_then_displace(parent_fd: int, source: str, destination: str) -> str:
        nonlocal calls
        calls += 1
        result = _fake_rename(parent_fd, source, destination)
        if calls == 1:
            parent.rename(displaced)
            parent.mkdir()
            (parent / "foreign-sentinel").write_bytes(b"foreign")
        return result

    monkeypatch.setattr(provenance, "_rename_noreplace", rename_then_displace)
    before = _fd_count()
    with pytest.raises(provenance.RawProvenanceError, match="durably rolled back"):
        _build(tiny_environment)
    assert _fd_count() == before
    assert (parent / "foreign-sentinel").read_bytes() == b"foreign"
    assert not tiny_environment.run.exists()
    assert not (displaced / tiny_environment.run.name).exists()
    assert not [path for path in displaced.iterdir() if path.name.startswith(".staging.")]


@pytest.mark.skipif(sys.platform != "darwin", reason="new_inode case relies on macOS inode-replacement behaviour")
@pytest.mark.parametrize("replacement", ("same_inode_bytes", "new_inode"))
def test_public_build_final_receipt_tamper_is_never_a_success(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    original_validate = provenance._validate_owned_bundle

    def tamper_final(
        parent_fd: int,
        name: str,
        owned: provenance._OwnedStaging,
        primary: bytes,
        secondary: bytes,
    ) -> tuple[int, int, int, int, int, int, int]:
        if name == tiny_environment.run.name:
            run = tiny_environment.run
            run.chmod(0o755)
            receipt = run / provenance.PRIMARY_RECEIPT
            receipt.chmod(0o644)
            if replacement == "new_inode":
                receipt.unlink()
                receipt.write_bytes(b"foreign replacement")
            else:
                receipt.write_bytes(b"same inode tamper")
            receipt.chmod(0o444)
            run.chmod(0o555)
        return original_validate(parent_fd, name, owned, primary, secondary)

    monkeypatch.setattr(provenance, "_validate_owned_bundle", tamper_final)
    before = _fd_count()
    expected = provenance.PublicationAmbiguityError if replacement == "new_inode" else provenance.RawProvenanceError
    with pytest.raises(expected):
        _build(tiny_environment)
    assert _fd_count() == before
    assert not tiny_environment.run.exists()
    parent = tiny_environment.root / tiny_environment.authority.output_parent_relative
    staging = [path for path in parent.iterdir() if path.name.startswith(".staging.")]
    if replacement == "same_inode_bytes":
        assert staging == []
    else:
        assert len(staging) == 1
        assert (staging[0] / provenance.PRIMARY_RECEIPT).read_bytes() == b"foreign replacement"


def test_public_build_collision_preserves_existing_without_staging(
    tiny_environment: TinyEnvironment,
) -> None:
    tiny_environment.run.mkdir(parents=True)
    marker = tiny_environment.run / "foreign-sentinel"
    marker.write_bytes(b"foreign")
    before = _fd_count()
    with pytest.raises(FileExistsError):
        _build(tiny_environment)
    assert _fd_count() == before
    assert marker.read_bytes() == b"foreign"
    assert not [path for path in tiny_environment.run.parent.iterdir() if path.name.startswith(".staging.")]


@pytest.mark.parametrize("persistent", (False, True))
def test_public_build_post_rename_fsync_fault_rolls_back_or_reports_ambiguity(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    persistent: bool,
) -> None:
    original_fsync = provenance.os.fsync
    publication_parent_fd: int | None = None
    fail_enabled = False
    failures = 0

    def mark_publication(parent_fd: int, source: str, destination: str) -> str:
        nonlocal publication_parent_fd, fail_enabled
        result = _fake_rename(parent_fd, source, destination)
        if source.startswith(".staging.") and destination == tiny_environment.run.name:
            publication_parent_fd = parent_fd
            fail_enabled = True
        return result

    def fail_fsync(fd: int) -> None:
        nonlocal failures
        if fail_enabled and fd == publication_parent_fd and (persistent or failures == 0):
            failures += 1
            raise OSError("injected post-rename parent fsync fault")
        original_fsync(fd)

    monkeypatch.setattr(provenance, "_rename_noreplace", mark_publication)
    monkeypatch.setattr(provenance.os, "fsync", fail_fsync)
    before = _fd_count()
    expected = provenance.PublicationAmbiguityError if persistent else provenance.RawProvenanceError
    with pytest.raises(expected):
        _build(tiny_environment)
    assert _fd_count() == before
    assert not tiny_environment.run.exists()
    staging = [path for path in tiny_environment.run.parent.iterdir() if path.name.startswith(".staging.")]
    if persistent:
        assert len(staging) == 1
    else:
        assert staging == []


def test_public_verify_rejects_output_parent_displacement_and_preserves_foreign(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build(tiny_environment)
    parent = tiny_environment.run.parent
    displaced = parent.with_name("st_r3_raw_provenance.verify-displaced")
    original_collect = provenance._collect_authority
    displaced_once = False

    def displace_during_verify(*args: object, **kwargs: object) -> provenance.CollectedAuthority:
        nonlocal displaced_once
        result = original_collect(*args, **kwargs)
        if not displaced_once:
            displaced_once = True
            parent.rename(displaced)
            parent.mkdir()
            (parent / "foreign-sentinel").write_bytes(b"foreign")
        return result

    monkeypatch.setattr(provenance, "_collect_authority", displace_during_verify)
    before = _fd_count()
    with pytest.raises(provenance.RawProvenanceError, match="pathname displacement"):
        provenance.verify_raw_provenance(tiny_environment.run)
    assert _fd_count() == before
    assert (parent / "foreign-sentinel").read_bytes() == b"foreign"
    assert (displaced / tiny_environment.run.name / provenance.PRIMARY_RECEIPT).is_file()


def test_receipt_mutation_is_rejected_even_when_reencoded_canonically(
    tiny_environment: TinyEnvironment,
) -> None:
    _build(tiny_environment)
    _rewrite_receipt(
        tiny_environment,
        provenance.PRIMARY_RECEIPT,
        lambda value: value["source"].__setitem__("commit", "c" * 40),
    )
    with pytest.raises(provenance.RawProvenanceError):
        provenance.verify_raw_provenance(tiny_environment.run)


def test_download_runtime_and_log_semantics_are_authoritative_after_byte_pin(
    tiny_environment: TinyEnvironment,
) -> None:
    download = tiny_environment.download.read_bytes()
    runtime = tiny_environment.runtime.read_bytes()
    log = tiny_environment.log.read_bytes()
    provenance._validate_evidence_semantics(download, runtime, log, tiny_environment.authority)

    bad_download = json.loads(download)
    bad_download["source"]["version"] = 12
    with pytest.raises(provenance.RawProvenanceError, match="kernel identity"):
        provenance._validate_evidence_semantics(
            provenance.canonical_json_bytes(bad_download), runtime, log, tiny_environment.authority
        )
    bad_runtime = json.loads(runtime)
    bad_runtime["ground_truth_accessed"] = True
    with pytest.raises(provenance.RawProvenanceError, match="runtime-integrity"):
        provenance._validate_evidence_semantics(
            download, provenance.canonical_json_bytes(bad_runtime), log, tiny_environment.authority
        )
    with pytest.raises(provenance.RawProvenanceError, match="unique frozen"):
        provenance._validate_evidence_semantics(download, runtime, log + log, tiny_environment.authority)


def test_receipt_bundle_rejects_extra_member_and_hardlinked_receipt(
    tiny_environment: TinyEnvironment,
) -> None:
    _build(tiny_environment)
    os.chmod(tiny_environment.run, 0o755)
    (tiny_environment.run / "EXTRA").write_bytes(b"x")
    os.chmod(tiny_environment.run, 0o555)
    with pytest.raises(provenance.RawProvenanceError, match="membership"):
        provenance.verify_raw_provenance(tiny_environment.run)
    os.chmod(tiny_environment.run, 0o755)
    (tiny_environment.run / "EXTRA").unlink()
    receipt = tiny_environment.run / provenance.PRIMARY_RECEIPT
    raw = receipt.read_bytes()
    receipt.unlink()
    external = tiny_environment.root / "receipt-copy"
    external.write_bytes(raw)
    os.link(external, receipt)
    os.chmod(tiny_environment.run, 0o555)
    with pytest.raises(provenance.RawProvenanceError, match="isolated regular"):
        provenance.verify_raw_provenance(tiny_environment.run)


def test_fixed_output_parent_and_fresh_id_are_mandatory(tiny_environment: TinyEnvironment) -> None:
    wrong_parent = tiny_environment.root / "elsewhere" / "run"
    with pytest.raises(provenance.RawProvenanceError, match="fixed output parent"):
        provenance.build_raw_provenance(wrong_parent)
    traversal = tiny_environment.root / "outputs" / "local" / "st_r3_raw_provenance" / ".." / "escaped"
    with pytest.raises(provenance.RawProvenanceError, match="traversal"):
        provenance.build_raw_provenance(traversal)


def test_authority_dataclass_cannot_silently_accept_wrong_counts(tiny_environment: TinyEnvironment) -> None:
    wrong = dataclasses.replace(tiny_environment.authority, raw_files=tiny_environment.authority.raw_files + 1)
    checkout = provenance._validate_checkout(tiny_environment.root)
    try:
        with pytest.raises(provenance.RawProvenanceError, match="inventory"):
            provenance._scan_raw_tree(checkout.root_fd, wrong)
    finally:
        checkout.close()


@pytest.mark.parametrize("walker", ("absolute", "relative", "output"))
@pytest.mark.parametrize("fault", ("fstat", "stat"))
def test_directory_walkers_close_new_descriptor_on_identity_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    walker: str,
    fault: str,
) -> None:
    leaf = tmp_path / "fd-leaf"
    leaf.mkdir()
    original_open = provenance.os.open
    original_fstat = provenance.os.fstat
    original_stat = provenance.os.stat
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

    def fail_path(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if fault == "stat" and path == leaf.name:
            raise OSError("injected directory identity fault")
        return original_stat(path, *args, **kwargs)

    root_fd: int | None = None
    if walker != "absolute":
        root_fd = os.open(tmp_path, os.O_RDONLY)
    before = _fd_count()
    monkeypatch.setattr(provenance.os, "open", remember_leaf)
    monkeypatch.setattr(provenance.os, "fstat", fail_descriptor)
    monkeypatch.setattr(provenance.os, "stat", fail_path)
    try:
        with pytest.raises(OSError, match="directory identity fault"):
            if walker == "absolute":
                provenance._open_absolute_directory(leaf)
            elif walker == "relative":
                assert root_fd is not None
                provenance._open_relative_directory(root_fd, (leaf.name,))
            else:
                assert root_fd is not None
                provenance._ensure_output_parent(root_fd, leaf.name)
    finally:
        monkeypatch.setattr(provenance.os, "open", original_open)
        monkeypatch.setattr(provenance.os, "fstat", original_fstat)
        monkeypatch.setattr(provenance.os, "stat", original_stat)
    assert _fd_count() == before
    if root_fd is not None:
        os.close(root_fd)


def test_new_receipt_initial_fstat_fault_closes_fd_and_durably_removes_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    original_open = provenance.os.open
    original_fstat = provenance.os.fstat
    original_fsync = provenance.os.fsync
    created_fd: int | None = None
    failed = False
    parent_fsyncs = 0

    def remember_created(path: object, *args: object, **kwargs: object) -> int:
        nonlocal created_fd
        fd = original_open(path, *args, **kwargs)
        if path == "receipt.json":
            created_fd = fd
        return fd

    def fail_initial_fstat(fd: int) -> os.stat_result:
        nonlocal failed
        if fd == created_fd and not failed:
            failed = True
            raise OSError("injected initial receipt fstat failure")
        return original_fstat(fd)

    def count_parent_fsync(fd: int) -> None:
        nonlocal parent_fsyncs
        if fd == parent_fd:
            parent_fsyncs += 1
        original_fsync(fd)

    before = _fd_count()
    monkeypatch.setattr(provenance.os, "open", remember_created)
    monkeypatch.setattr(provenance.os, "fstat", fail_initial_fstat)
    monkeypatch.setattr(provenance.os, "fsync", count_parent_fsync)
    try:
        with pytest.raises(OSError, match="initial receipt fstat"):
            provenance._write_new_regular(parent_fd, "receipt.json", b"payload")
    finally:
        monkeypatch.setattr(provenance.os, "open", original_open)
        monkeypatch.setattr(provenance.os, "fstat", original_fstat)
        monkeypatch.setattr(provenance.os, "fsync", original_fsync)
    assert failed
    assert parent_fsyncs == 1
    assert not (tmp_path / "receipt.json").exists()
    assert _fd_count() == before
    os.close(parent_fd)


@pytest.mark.parametrize(
    ("original_type", "recovery_type"),
    ((KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)),
)
def test_new_receipt_base_write_and_cleanup_faults_are_grouped_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    sentinel = tmp_path / "foreign-sentinel"
    sentinel.write_bytes(b"keep")
    monkeypatch.setattr(
        provenance.os,
        "write",
        lambda *_args: (_ for _ in ()).throw(original_type("original write base fault")),
    )
    monkeypatch.setattr(
        provenance.os,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(recovery_type("cleanup unlink base fault")),
    )
    before = _fd_count()
    try:
        with pytest.raises(provenance.PublicationAmbiguityError) as captured:
            provenance._write_new_regular(parent_fd, "receipt.json", b"payload")
        _assert_base_fault_group(captured.value, original_type, recovery_type)
        assert _fd_count() == before
        assert (tmp_path / "receipt.json").is_file()
        assert sentinel.read_bytes() == b"keep"
    finally:
        os.close(parent_fd)


@pytest.mark.parametrize(
    ("original_type", "recovery_type"),
    ((KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)),
)
def test_initial_staging_recovery_base_faults_are_grouped_without_foreign_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    staging = tmp_path / ".staging.run.token"
    staging.mkdir()
    sentinel = staging / "foreign-sentinel"
    sentinel.write_bytes(b"keep")
    monkeypatch.setattr(
        provenance,
        "_bind_empty_staging",
        lambda *_args: (_ for _ in ()).throw(recovery_type("identity recovery base fault")),
    )
    before = _fd_count()
    try:
        with pytest.raises(provenance.PublicationAmbiguityError) as captured:
            provenance._recover_initial_staging_fault(
                parent_fd, staging.name, original_type("initial staging base fault")
            )
        _assert_base_fault_group(captured.value, original_type, recovery_type)
        assert _fd_count() == before
        assert sentinel.read_bytes() == b"keep"
    finally:
        os.close(parent_fd)


@pytest.mark.parametrize(
    ("original_type", "recovery_type"),
    ((KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)),
)
def test_owned_staging_creation_base_faults_are_grouped_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    sentinel = tmp_path / "foreign-sentinel"
    sentinel.write_bytes(b"keep")
    monkeypatch.setattr(
        provenance.os,
        "fsync",
        lambda *_args: (_ for _ in ()).throw(original_type("staging fsync base fault")),
    )
    monkeypatch.setattr(
        provenance,
        "_cleanup_owned",
        lambda *_args: (_ for _ in ()).throw(recovery_type("staging cleanup base fault")),
    )
    before = _fd_count()
    try:
        with pytest.raises(provenance.PublicationAmbiguityError) as captured:
            provenance._create_owned_staging(parent_fd, ".staging.run.token")
        _assert_base_fault_group(captured.value, original_type, recovery_type)
        assert _fd_count() == before
        assert (tmp_path / ".staging.run.token").is_dir()
        assert sentinel.read_bytes() == b"keep"
    finally:
        os.close(parent_fd)


def test_staging_open_fault_has_zero_fd_delta_and_zero_orphan(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = provenance._open_relative_directory
    injected = False

    def fail_new_staging(root_fd: int, relative: str | tuple[str, ...]) -> int:
        nonlocal injected
        parts = (relative,) if isinstance(relative, str) else relative
        if not injected and len(parts) == 1 and parts[0].startswith(".staging.run-one."):
            injected = True
            raise OSError("injected staging open fault")
        return original(root_fd, relative)

    monkeypatch.setattr(provenance, "_open_relative_directory", fail_new_staging)
    before = _fd_count()
    with pytest.raises(OSError, match="staging open fault"):
        _build(tiny_environment)
    assert injected
    assert _fd_count() == before
    assert not tiny_environment.run.exists()
    parent = tiny_environment.root / tiny_environment.authority.output_parent_relative
    assert not [path for path in parent.iterdir() if path.name.startswith(".staging.run-one.")]


@pytest.mark.parametrize("phase", ("pre_rename", "post_rename"))
@pytest.mark.parametrize(
    ("original_type", "recovery_type"),
    ((KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)),
)
def test_raw_publication_base_faults_are_grouped_without_unknown_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    staging_fd, owned = provenance._create_owned_staging(parent_fd, ".staging.run.token")
    os.close(staging_fd)
    sentinel = tmp_path / "foreign-sentinel"
    sentinel.write_bytes(b"keep")
    publication_failed = False

    def publication_fault(fd: int, source: str, destination: str) -> str:
        nonlocal publication_failed
        if phase == "post_rename":
            os.rename(source, destination, src_dir_fd=fd, dst_dir_fd=fd)
        publication_failed = True
        raise original_type("raw publication base fault")

    monkeypatch.setattr(provenance, "_rename_noreplace", publication_fault)
    original_owned_name = provenance._owned_name

    def recovery_fault(fd: int, name: str, identity: tuple[int, int]) -> bool:
        if publication_failed:
            raise recovery_type("raw ownership recovery base fault")
        return original_owned_name(fd, name, identity)

    monkeypatch.setattr(provenance, "_owned_name", recovery_fault)
    before = _fd_count()
    try:
        with pytest.raises(provenance.PublicationAmbiguityError) as captured:
            provenance._publish_staging(parent_fd, "run", owned)
        _assert_base_fault_group(captured.value, original_type, recovery_type)
        assert _fd_count() == before
        assert sentinel.read_bytes() == b"keep"
        remaining = "run" if phase == "post_rename" else owned.name
        absent = owned.name if phase == "post_rename" else "run"
        assert (tmp_path / remaining).is_dir()
        assert not (tmp_path / absent).exists()
    finally:
        os.close(parent_fd)


@pytest.mark.parametrize(
    ("original_type", "recovery_type"),
    ((KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)),
)
def test_raw_build_outer_base_faults_are_grouped_without_staging_deletion(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    parent = tiny_environment.root / tiny_environment.authority.output_parent_relative

    def construction_fault(*_args: object) -> tuple[bytes, bytes, tuple[int, ...]]:
        (parent / "foreign-sentinel").write_bytes(b"keep")
        raise original_type("raw construction base fault")

    monkeypatch.setattr(provenance, "_load_bundle", construction_fault)
    monkeypatch.setattr(
        provenance,
        "_cleanup_owned",
        lambda *_args: (_ for _ in ()).throw(recovery_type("raw outer cleanup base fault")),
    )
    before = _fd_count()
    with pytest.raises(provenance.PublicationAmbiguityError) as captured:
        _build(tiny_environment)
    _assert_base_fault_group(captured.value, original_type, recovery_type)
    assert _fd_count() == before
    assert (parent / "foreign-sentinel").read_bytes() == b"keep"
    assert len([path for path in parent.iterdir() if path.name.startswith(".staging.")]) == 1
    assert not tiny_environment.run.exists()


@pytest.mark.parametrize("fault", ("stat", "fstat"))
def test_first_staging_identity_fault_is_recovered_without_fd_or_orphan(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    original_open = provenance.os.open
    original_stat = provenance.os.stat
    original_fstat = provenance.os.fstat
    staging_fd: int | None = None
    failed = False

    def remember_staging(path: object, *args: object, **kwargs: object) -> int:
        nonlocal staging_fd
        fd = original_open(path, *args, **kwargs)
        if isinstance(path, str) and path.startswith(".staging.run-one."):
            staging_fd = fd
        return fd

    def fail_first_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal failed
        if fault == "stat" and not failed and isinstance(path, str) and path.startswith(".staging.run-one."):
            failed = True
            raise OSError("injected first staging identity fault")
        return original_stat(path, *args, **kwargs)

    def fail_first_fstat(fd: int) -> os.stat_result:
        nonlocal failed
        if fault == "fstat" and not failed and fd == staging_fd:
            failed = True
            raise OSError("injected first staging identity fault")
        return original_fstat(fd)

    before = _fd_count()
    monkeypatch.setattr(provenance.os, "open", remember_staging)
    monkeypatch.setattr(provenance.os, "stat", fail_first_stat)
    monkeypatch.setattr(provenance.os, "fstat", fail_first_fstat)
    try:
        with pytest.raises(OSError, match="first staging identity fault"):
            _build(tiny_environment)
    finally:
        monkeypatch.setattr(provenance.os, "open", original_open)
        monkeypatch.setattr(provenance.os, "stat", original_stat)
        monkeypatch.setattr(provenance.os, "fstat", original_fstat)
    assert failed
    assert _fd_count() == before
    assert not tiny_environment.run.exists()
    parent = tiny_environment.root / tiny_environment.authority.output_parent_relative
    assert not [path for path in parent.iterdir() if path.name.startswith(".staging.run-one.")]


def test_fifo_swap_is_rejected_without_blocking_in_subprocess(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"regular-before-swap")
    project_root = Path(__file__).resolve().parents[1]
    program = """
import os
import sys
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from biohub import st_r3_raw_provenance as provenance

root = sys.argv[1]
root_fd = os.open(root, os.O_RDONLY)
original_open = provenance.os.open
swapped = False

def swap_then_open(path, flags, *args, **kwargs):
    global swapped
    if path == "victim" and not swapped:
        swapped = True
        os.unlink(os.path.join(root, "victim"))
        os.mkfifo(os.path.join(root, "victim"))
    return original_open(path, flags, *args, **kwargs)

provenance.os.open = swap_then_open
try:
    provenance._read_named_regular(root_fd, "victim")
except provenance.RawProvenanceError:
    print("REJECTED")
else:
    raise SystemExit("FIFO was accepted")
finally:
    os.close(root_fd)
"""
    process = subprocess.run(
        (sys.executable, "-c", program, str(tmp_path)),
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"REJECTED\n"


@pytest.mark.parametrize("prefix", ("h", "S"))
@pytest.mark.parametrize("checkout", ("builder", "unlisted", "gitlink", "official"))
def test_git_capture_rejects_assume_unchanged_and_skip_worktree_flags(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    checkout: str,
) -> None:
    options = {
        "builder": {"builder_index_prefix": prefix},
        "unlisted": {"unlisted_index_prefix": prefix},
        "gitlink": {"gitlink_index_prefix": prefix},
        "official": {"official_index_prefix": prefix},
    }[checkout]
    monkeypatch.setattr(provenance, "_run_git", _mock_clean_git(tiny_environment, **options))
    with pytest.raises(provenance.RawProvenanceError, match="unsafe index flags"):
        _REAL_CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


def test_git_capture_validates_entire_superproject_and_official_checkout(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "_run_git", _mock_clean_git(tiny_environment))
    assert _REAL_CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority) == tiny_environment.git


@pytest.mark.parametrize(
    "artifact",
    ("builder-bytes", "builder-mode", "official-bytes", "official-mode", "official-symlink"),
)
def test_git_capture_rejects_hidden_tracked_worktree_drift(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    monkeypatch.setattr(provenance, "_run_git", _mock_clean_git(tiny_environment))
    if artifact == "builder-bytes":
        path = tiny_environment.root / tiny_environment.authority.builder_sources[0]
        path.write_bytes(b"forged builder bytes\n")
    elif artifact == "builder-mode":
        path = tiny_environment.root / tiny_environment.authority.builder_sources[0]
        path.chmod(0o600)
    elif artifact == "official-bytes":
        (tiny_environment.root / "official/tracked.txt").write_bytes(b"forged official bytes\n")
    elif artifact == "official-mode":
        (tiny_environment.root / "official/tracked.txt").chmod(0o600)
    else:
        link = tiny_environment.root / "official/tracked-link"
        link.unlink()
        link.symlink_to("forged.txt")
    with pytest.raises(provenance.RawProvenanceError, match="builder|official|superproject"):
        _REAL_CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


@pytest.mark.parametrize("artifact", ("bytes", "mode", "symlink"))
def test_unlisted_tracked_hidden_modification_is_rejected(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    monkeypatch.setattr(provenance, "_run_git", _mock_clean_git(tiny_environment))
    if artifact == "bytes":
        (tiny_environment.root / "tracked/unlisted.txt").write_bytes(b"hidden unlisted drift\n")
    elif artifact == "mode":
        (tiny_environment.root / "tracked/unlisted.txt").chmod(0o600)
    else:
        link = tiny_environment.root / "tracked/unlisted-link"
        link.unlink()
        link.symlink_to("forged.txt")
    with pytest.raises(provenance.RawProvenanceError, match="superproject"):
        _REAL_CAPTURE_GIT_STATE(tiny_environment.root, tiny_environment.authority)


@pytest.mark.parametrize("name", (".git", "official"))
def test_checkout_guard_rejects_git_or_official_path_swap(
    tiny_environment: TinyEnvironment,
    name: str,
) -> None:
    guard = provenance._validate_checkout(tiny_environment.root)
    original = tiny_environment.root / name
    displaced = tiny_environment.root / f"{name}.held"
    original.rename(displaced)
    original.mkdir()
    try:
        with pytest.raises(provenance.RawProvenanceError, match="identity drift"):
            provenance._assert_checkout_rebound(tiny_environment.root, guard)
    finally:
        original.rmdir()
        displaced.rename(original)
        guard.close()


def test_checkout_guard_rejects_held_root_identity_drift(tiny_environment: TinyEnvironment) -> None:
    guard = provenance._validate_checkout(tiny_environment.root)
    forged = dataclasses.replace(
        guard,
        root_identity=(guard.root_identity[0], guard.root_identity[1] + 1, guard.root_identity[2]),
    )
    try:
        with pytest.raises(provenance.RawProvenanceError, match="descriptor drift"):
            provenance._assert_checkout_rebound(tiny_environment.root, forged)
    finally:
        guard.close()


def test_build_holds_checkout_through_verified_publication_and_never_postverifies(
    tiny_environment: TinyEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_validate = provenance._validate_checkout
    original_result = provenance._result
    original_publish = provenance._publish_verified
    captured: dict[str, object] = {"result_ready": False}

    def capture_guard(root: Path) -> provenance.CheckoutGuard:
        guard = original_validate(root)
        captured["guard"] = guard
        return guard

    def capture_result(*args: object, **kwargs: object) -> dict[str, object]:
        result = original_result(*args, **kwargs)
        captured["result_ready"] = True
        return result

    def assert_commit_boundary(
        root: Path,
        guard: provenance.CheckoutGuard,
        parent_fd: int,
        parent_identity: tuple[int, int, int],
        final_name: str,
        owned: provenance._OwnedStaging,
        primary_raw: bytes,
        secondary_raw: bytes,
        authority: provenance.Authority,
    ) -> str:
        assert captured["result_ready"] is True
        assert guard is captured["guard"]
        assert isinstance(guard, provenance.CheckoutGuard)
        for fd in (guard.root_fd, guard.git_fd, guard.official_fd):
            os.fstat(fd)
        return original_publish(
            root,
            guard,
            parent_fd,
            parent_identity,
            final_name,
            owned,
            primary_raw,
            secondary_raw,
            authority,
        )

    monkeypatch.setattr(provenance, "_validate_checkout", capture_guard)
    monkeypatch.setattr(provenance, "_result", capture_result)
    monkeypatch.setattr(provenance, "_publish_verified", assert_commit_boundary)
    monkeypatch.setattr(
        provenance,
        "_verify",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("post-publication verify called")),
    )
    built = _build(tiny_environment)
    assert built["status"] == provenance.STATUS
    guard = captured["guard"]
    assert isinstance(guard, provenance.CheckoutGuard)
    for fd in (guard.root_fd, guard.git_fd, guard.official_fd):
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize(
    ("target", "mode"),
    (
        ("run", 0o755),
        ("run", 0o500),
        ("primary", 0o644),
        ("primary", 0o400),
        ("secondary", 0o644),
        ("secondary", 0o400),
    ),
)
def test_verify_rejects_noncanonical_bundle_or_receipt_mode(
    tiny_environment: TinyEnvironment,
    target: str,
    mode: int,
) -> None:
    _build(tiny_environment)
    path = {
        "run": tiny_environment.run,
        "primary": tiny_environment.run / provenance.PRIMARY_RECEIPT,
        "secondary": tiny_environment.run / provenance.SECONDARY_RECEIPT,
    }[target]
    path.chmod(mode)
    with pytest.raises(provenance.RawProvenanceError, match="mode"):
        provenance.verify_raw_provenance(tiny_environment.run)
