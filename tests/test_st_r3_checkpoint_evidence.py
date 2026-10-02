from __future__ import annotations

import dataclasses
import json
import math
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from biohub import st_r3_checkpoint_evidence as evidence

needs_local_evidence = pytest.mark.skipif(
    not (evidence.CANONICAL_REPO_ROOT / "outputs/kaggle/st_r3_checkpoint_recovery").is_dir(),
    reason="local ST-R3 checkpoint evidence (outputs/kaggle/st_r3_checkpoint_recovery) is not in the repository",
)


def _production_collect(monkeypatch: pytest.MonkeyPatch) -> evidence.Collected:
    root = evidence.CANONICAL_REPO_ROOT
    guard = evidence._secure._validate_checkout(root)
    git = evidence.GitState("a" * 40, "b" * 40, evidence.OFFICIAL_OID)
    monkeypatch.setattr(evidence, "_capture_git_state", lambda *_args: git)
    try:
        return evidence._collect(root, guard.root_fd, evidence.PRODUCTION_AUTHORITY, guard)
    finally:
        guard.close()


@needs_local_evidence
def test_canonical_ignored_evidence_has_exact_history_and_split_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collected = _production_collect(monkeypatch)
    assert collected.history == {
        "epochs": {"first": 1, "last": 400, "count": 400, "no_gaps": True},
        "seed": {"base": 314159, "effective": 314159, "fold": 0},
        "best": {"epoch": 381, "score": 0.9779747766406395},
        "first_loss": {
            "edge_loss": 0.003970155237044959,
            "det_loss": 0.019809366372963207,
            "validation_loss": 0.0003694080726243065,
        },
        "final_loss": {
            "edge_loss": 0.00015537457768152087,
            "det_loss": 0.0025127971824129127,
            "validation_loss": 0.00010980715391659644,
        },
    }
    assert collected.split == {
        "train_datasets": 199,
        "validation_datasets": 40,
        "train_validation_overlap": 40,
        "validation_prefixes": ["44b6"],
        "in_sample": True,
    }


@needs_local_evidence
def test_primary_last_is_not_a_pin_and_is_never_read(monkeypatch: pytest.MonkeyPatch) -> None:
    assert all(
        pin.relative != "outputs/kaggle/st_r3_checkpoint_recovery/primary/checkpoint_last.pth"
        for pin in (
            evidence.PRODUCTION_AUTHORITY.primary_manifest,
            evidence.PRODUCTION_AUTHORITY.primary_config,
            evidence.PRODUCTION_AUTHORITY.primary_best,
            *evidence.PRODUCTION_AUTHORITY.secondary_files,
        )
    )
    seen: list[str] = []
    original = evidence._read_pin

    def record(root_fd: int, pin: evidence.FilePin, *, maximum: int | None = None):
        seen.append(pin.relative)
        return original(root_fd, pin, maximum=maximum)

    monkeypatch.setattr(evidence, "_read_pin", record)
    _production_collect(monkeypatch)
    assert not any(path.endswith("primary/checkpoint_last.pth") for path in seen)


@needs_local_evidence
def test_claims_are_exact_and_do_not_promote_resume_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collected = _production_collect(monkeypatch)
    receipt = evidence._receipt("2026-09-05T00:00:00Z", collected, evidence.PRODUCTION_AUTHORITY)
    assert receipt["claims"] == {
        "inference_weight_identity_verified": True,
        "checkpoint_to_raw_causal_proof": False,
        "secondary_training_history_verified": True,
        "secondary_history_scope": "LEGACY_IN_SAMPLE_MONITORING_ONLY",
        "primary_training_history_verified": False,
        "generalization_verified": False,
        "training_gate_passed": False,
    }
    assert receipt["primary"]["checkpoint_last"]["loaded"] is False
    assert receipt["primary"]["checkpoint_last"]["exclusion_reasons"] == ["UNPINNED_BY_ARTIFACT_MANIFEST"]
    assert receipt["secondary"]["checkpoint_last_role"] == "TRAINING_RESUME_SNAPSHOT_NOT_INFERENCE_WEIGHT"
    assert receipt["remaining_holds"] == list(evidence.REMAINING_HOLDS)


@needs_local_evidence
def test_history_rejects_gap_nonfinite_and_wrong_running_best() -> None:
    path = evidence.CANONICAL_REPO_ROOT / "outputs/kaggle/st_r3_checkpoint_recovery/secondary/history.csv"
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    with pytest.raises(evidence.CheckpointEvidenceError, match="row shape"):
        evidence._parse_history(b"".join(lines[:20] + lines[21:]))
    with pytest.raises(evidence.CheckpointEvidenceError, match="non-finite"):
        evidence._parse_history(raw.replace(b"0.003970155237044959", b"nan", 1))
    with pytest.raises(evidence.CheckpointEvidenceError, match="running-best"):
        evidence._parse_history(raw.replace(b"0.9003592413566567,1", b"0.9003592413566568,1", 1))


@needs_local_evidence
def test_snapshot_manifest_requires_exact_six_file_set() -> None:
    authority = evidence.PRODUCTION_AUTHORITY
    path = evidence.CANONICAL_REPO_ROOT / authority.secondary_snapshot_manifest.relative
    value = json.loads(path.read_bytes())
    evidence._validate_snapshot(value, authority.secondary_files)
    del value["files"]["history.csv"]
    with pytest.raises(evidence.CheckpointEvidenceError, match="semantic drift"):
        evidence._validate_snapshot(value, authority.secondary_files)


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "fifo"))
def test_stable_regular_reader_rejects_links_and_fifo(tmp_path: Path, kind: str) -> None:
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    external = tmp_path / "external"
    external.write_bytes(b"bytes")
    target = tmp_path / "target"
    if kind == "symlink":
        target.symlink_to(external.name)
    elif kind == "hardlink":
        os.link(external, target)
    else:
        os.mkfifo(target)
    try:
        with pytest.raises(evidence._secure.RawProvenanceError):
            evidence._secure._read_named_regular(parent_fd, target.name, max_bytes=100)
    finally:
        os.close(parent_fd)


def test_nonblocking_flag_is_used_for_evidence_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "file").write_bytes(b"x")
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    original = evidence._secure.os.open
    flags_seen: list[int] = []

    def observe(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if path == "file":
            flags_seen.append(flags)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(evidence._secure.os, "open", observe)
    try:
        evidence._secure._read_named_regular(parent_fd, "file", max_bytes=1)
    finally:
        os.close(parent_fd)
    assert flags_seen and flags_seen[0] & os.O_NONBLOCK
    assert flags_seen[0] & getattr(os, "O_NOFOLLOW", 0)


def test_read_fault_closes_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "file").write_bytes(b"x")
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    before = len(os.listdir("/dev/fd"))
    original = evidence._secure.os.read

    def fail(_fd: int, _size: int) -> bytes:
        raise OSError("injected read fault")

    monkeypatch.setattr(evidence._secure.os, "read", fail)
    try:
        with pytest.raises(OSError, match="injected"):
            evidence._secure._read_named_regular(parent_fd, "file", max_bytes=1)
    finally:
        monkeypatch.setattr(evidence._secure.os, "read", original)
    assert len(os.listdir("/dev/fd")) == before
    os.close(parent_fd)


@needs_local_evidence
def test_receipt_is_canonical_and_mutation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    collected = _production_collect(monkeypatch)
    raw = evidence.canonical_json_bytes(
        evidence._receipt("2026-09-05T00:00:00Z", collected, evidence.PRODUCTION_AUTHORITY)
    )
    evidence._validate_receipt(raw, collected, evidence.PRODUCTION_AUTHORITY)
    value = json.loads(raw)
    value["claims"]["training_gate_passed"] = True
    with pytest.raises(evidence.CheckpointEvidenceError, match="authority drift"):
        evidence._validate_receipt(evidence.canonical_json_bytes(value), collected, evidence.PRODUCTION_AUTHORITY)


@needs_local_evidence
def test_wrong_pin_size_fails_before_semantic_parsing() -> None:
    authority = evidence.PRODUCTION_AUTHORITY
    wrong = dataclasses.replace(authority.primary_best, bytes=authority.primary_best.bytes + 1)
    root_fd = evidence._secure._open_absolute_directory(evidence.CANONICAL_REPO_ROOT)
    try:
        with pytest.raises(evidence.CheckpointEvidenceError, match="byte pin drift"):
            evidence._read_pin(root_fd, wrong)
    finally:
        os.close(root_fd)


def test_canonical_json_rejects_nonfinite_values() -> None:
    with pytest.raises(ValueError):
        evidence.canonical_json_bytes({"value": math.nan})


def _staged_bundle(tmp_path: Path) -> tuple[int, int, tuple[int, ...], evidence._secure._OwnedStaging, bytes]:
    (tmp_path / "out").mkdir()
    root_fd = os.open(tmp_path, os.O_RDONLY)
    parent_fd = os.open(tmp_path / "out", os.O_RDONLY)
    staging_fd, owned = evidence._secure._create_owned_staging(parent_fd, ".staging.run.token")
    raw = evidence.canonical_json_bytes({"receipt": "exact"})
    identity = evidence._secure._write_new_regular(staging_fd, evidence.RECEIPT_NAME, raw)
    owned = evidence._secure._OwnedStaging(owned.name, owned.identity, ((evidence.RECEIPT_NAME, identity),))
    os.fchmod(staging_fd, 0o555)
    os.close(staging_fd)
    return root_fd, parent_fd, evidence._secure._directory_handle_identity(os.fstat(parent_fd)), owned, raw


def _test_authority() -> evidence.Authority:
    return dataclasses.replace(evidence.PRODUCTION_AUTHORITY, output_parent_relative="out")


def test_verified_publication_rechecks_final_inode_membership_and_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    monkeypatch.setattr(evidence._secure, "_rename_noreplace", lambda fd, src, dst: _rename(fd, src, dst))
    try:
        assert (
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
            == "test-no-replace"
        )
        observed, _identity = evidence._load_bundle(parent_fd, "run")
        assert observed == raw
        assert not (tmp_path / "out" / owned.name).exists()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def _rename(parent_fd: int, source: str, destination: str) -> str:
    if evidence._secure._name_info(parent_fd, destination) is not None:
        raise FileExistsError(destination)
    os.rename(source, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    return "test-no-replace"


def test_no_replace_collision_preserves_existing_and_leaves_no_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    (tmp_path / "out" / "run").mkdir()
    (tmp_path / "out" / "run" / "keep").write_bytes(b"keep")
    guard = SimpleNamespace(root_fd=root_fd)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    monkeypatch.setattr(evidence._secure, "_rename_noreplace", _rename)
    try:
        with pytest.raises(FileExistsError):
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        assert (tmp_path / "out" / "run" / "keep").read_bytes() == b"keep"
        assert not (tmp_path / "out" / owned.name).exists()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_post_rename_fsync_fault_rolls_back_without_orphan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    monkeypatch.setattr(evidence._secure, "_rename_noreplace", _rename)
    original_fsync = evidence.os.fsync
    failed = False

    def fail_once(fd: int) -> None:
        nonlocal failed
        if fd == parent_fd and not failed:
            failed = True
            raise OSError("injected post-rename fsync fault")
        original_fsync(fd)

    monkeypatch.setattr(evidence.os, "fsync", fail_once)
    try:
        with pytest.raises(evidence.CheckpointEvidenceError, match="durably rolled back"):
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        assert os.listdir(parent_fd) == []
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_output_parent_replacement_after_rename_never_returns_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)

    def rename_then_displace(fd: int, source: str, destination: str) -> str:
        nonlocal rename_calls
        rename_calls += 1
        result = _rename(fd, source, destination)
        if rename_calls == 1:
            os.rename(tmp_path / "out", tmp_path / "displaced")
            (tmp_path / "out").mkdir()
        return result

    rename_calls = 0
    monkeypatch.setattr(evidence._secure, "_rename_noreplace", rename_then_displace)
    try:
        with pytest.raises(evidence.CheckpointEvidenceError, match="durably rolled back"):
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        assert not (tmp_path / "out" / "run").exists()
        assert not (tmp_path / "displaced" / "run").exists()
        assert not (tmp_path / "displaced" / owned.name).exists()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_staging_replacement_during_second_authority_collection_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "official").mkdir()
    monkeypatch.chdir(root)
    authority = dataclasses.replace(evidence.PRODUCTION_AUTHORITY, output_parent_relative="out")
    monkeypatch.setattr(evidence, "CANONICAL_REPO_ROOT", root)
    monkeypatch.setattr(evidence, "PRODUCTION_AUTHORITY", authority)
    guard = evidence._secure.CheckoutGuard(
        root_fd=os.open(root, os.O_RDONLY),
        git_fd=os.open(root / ".git", os.O_RDONLY),
        official_fd=os.open(root / "official", os.O_RDONLY),
        root_identity=evidence._secure._directory_handle_identity(root.stat()),
        git_identity=evidence._secure._directory_handle_identity((root / ".git").stat()),
        official_identity=evidence._secure._directory_handle_identity((root / "official").stat()),
    )
    monkeypatch.setattr(evidence._secure, "_validate_checkout", lambda _root: guard)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    collected = evidence.Collected(evidence.GitState("a" * 40, "b" * 40, authority.official_oid), (), {}, {})
    calls = 0

    def collect(*_args):
        nonlocal calls
        calls += 1
        if calls == 2:
            parent = root / "out"
            staging = next(path for path in parent.iterdir() if path.name.startswith(".staging."))
            staging.rename(parent / f"{staging.name}.displaced")
            staging.mkdir()
        return collected

    monkeypatch.setattr(evidence, "_collect", collect)
    with pytest.raises(evidence.CheckpointPublicationAmbiguityError):
        evidence.build_checkpoint_evidence(root / "out" / "run")
    assert not (root / "out" / "run").exists()


def test_final_bytes_tamper_is_detected_and_durably_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    monkeypatch.setattr(evidence._secure, "_rename_noreplace", _rename)
    original_validate = evidence._validate_owned_bundle
    calls = 0

    def tamper_on_final(fd: int, name: str, expected_owned, expected_raw: bytes):
        nonlocal calls
        calls += 1
        if name == "run":
            receipt = tmp_path / "out" / "run" / evidence.RECEIPT_NAME
            receipt.chmod(0o644)
            receipt.write_bytes(b"tampered")
            receipt.chmod(0o444)
        return original_validate(fd, name, expected_owned, expected_raw)

    monkeypatch.setattr(evidence, "_validate_owned_bundle", tamper_on_final)
    try:
        with pytest.raises(evidence.CheckpointEvidenceError, match="durably rolled back"):
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        assert calls >= 2
        assert os.listdir(parent_fd) == []
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_final_receipt_inode_replacement_is_dedicated_ambiguity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    monkeypatch.setattr(evidence._secure, "_rename_noreplace", _rename)
    original_validate = evidence._validate_owned_bundle

    def replace_on_final(fd: int, name: str, expected_owned, expected_raw: bytes):
        if name == "run":
            run = tmp_path / "out" / "run"
            run.chmod(0o755)
            receipt = tmp_path / "out" / "run" / evidence.RECEIPT_NAME
            receipt.unlink()
            receipt.write_bytes(b"foreign inode")
            receipt.chmod(0o444)
            run.chmod(0o555)
        return original_validate(fd, name, expected_owned, expected_raw)

    monkeypatch.setattr(evidence, "_validate_owned_bundle", replace_on_final)
    try:
        with pytest.raises(evidence.CheckpointPublicationAmbiguityError):
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        assert not (tmp_path / "out" / "run").exists()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def test_rollback_failure_uses_dedicated_publication_ambiguity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    monkeypatch.setattr(evidence._secure, "_rename_noreplace", _rename)
    original_fsync = evidence.os.fsync

    def fail_parent_fsync(fd: int) -> None:
        if fd == parent_fd:
            raise OSError("injected persistent parent fsync fault")
        original_fsync(fd)

    monkeypatch.setattr(evidence.os, "fsync", fail_parent_fsync)
    try:
        with pytest.raises(evidence.CheckpointPublicationAmbiguityError):
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        assert not (tmp_path / "out" / "run").exists()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


@pytest.mark.parametrize("phase", ("pre_rename", "post_rename"))
@pytest.mark.parametrize("failing_probe", (1, 2))
def test_publication_ownership_probe_fault_is_ambiguity_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    failing_probe: int,
) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    sentinel = tmp_path / "out" / "foreign-sentinel"
    sentinel.write_bytes(b"do-not-delete")
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    publication_failed = False

    def publication_fault(fd: int, source: str, destination: str) -> str:
        nonlocal publication_failed
        if phase == "post_rename":
            _rename(fd, source, destination)
        publication_failed = True
        raise OSError(f"injected {phase} publication fault")

    monkeypatch.setattr(evidence._secure, "_rename_noreplace", publication_fault)
    original_owned_name = evidence._secure._owned_name
    probes = 0

    def probe_fault(fd: int, name: str, identity: tuple[int, int]) -> bool:
        nonlocal probes
        if not publication_failed:
            return original_owned_name(fd, name, identity)
        probes += 1
        if probes == failing_probe:
            raise OSError(f"injected ownership probe {failing_probe} fault")
        return original_owned_name(fd, name, identity)

    monkeypatch.setattr(evidence._secure, "_owned_name", probe_fault)
    before_fds = len(os.listdir("/dev/fd"))
    try:
        with pytest.raises(evidence.CheckpointPublicationAmbiguityError) as captured:
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        assert isinstance(captured.value.__cause__, ExceptionGroup)
        causes = captured.value.__cause__.exceptions
        assert len(causes) == 2
        assert f"injected {phase} publication fault" in str(causes[0])
        assert f"injected ownership probe {failing_probe} fault" in str(causes[1])
        assert len(os.listdir("/dev/fd")) == before_fds
        assert sentinel.read_bytes() == b"do-not-delete"
        if phase == "pre_rename":
            assert (tmp_path / "out" / owned.name / evidence.RECEIPT_NAME).read_bytes() == raw
            assert not (tmp_path / "out" / "run").exists()
        else:
            assert not (tmp_path / "out" / owned.name).exists()
            assert (tmp_path / "out" / "run" / evidence.RECEIPT_NAME).read_bytes() == raw
    finally:
        os.close(parent_fd)
        os.close(root_fd)


@pytest.mark.parametrize("phase", ("pre_rename", "post_rename"))
@pytest.mark.parametrize(
    ("original_type", "recovery_type"),
    ((KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)),
)
def test_publication_base_faults_are_preserved_in_ambiguity_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    root_fd, parent_fd, parent_identity, owned, raw = _staged_bundle(tmp_path)
    guard = SimpleNamespace(root_fd=root_fd)
    sentinel = tmp_path / "out" / "foreign-sentinel"
    sentinel.write_bytes(b"keep")
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    publication_failed = False

    def publication_fault(fd: int, source: str, destination: str) -> str:
        nonlocal publication_failed
        if phase == "post_rename":
            _rename(fd, source, destination)
        publication_failed = True
        raise original_type("original publication base fault")

    monkeypatch.setattr(evidence._secure, "_rename_noreplace", publication_fault)
    original_owned_name = evidence._secure._owned_name

    def recovery_fault(fd: int, name: str, identity: tuple[int, int]) -> bool:
        if publication_failed:
            raise recovery_type("recovery ownership base fault")
        return original_owned_name(fd, name, identity)

    monkeypatch.setattr(evidence._secure, "_owned_name", recovery_fault)
    before_fds = len(os.listdir("/dev/fd"))
    try:
        with pytest.raises(evidence.CheckpointPublicationAmbiguityError) as captured:
            evidence._publish_verified(
                tmp_path, guard, parent_fd, parent_identity, "run", owned, raw, _test_authority()
            )
        group = captured.value.__cause__
        assert isinstance(group, BaseExceptionGroup)
        assert isinstance(group.exceptions[0], original_type)
        assert isinstance(group.exceptions[1], recovery_type)
        assert len(os.listdir("/dev/fd")) == before_fds
        assert sentinel.read_bytes() == b"keep"
        remaining = "run" if phase == "post_rename" else owned.name
        absent = owned.name if phase == "post_rename" else "run"
        assert (tmp_path / "out" / remaining / evidence.RECEIPT_NAME).read_bytes() == raw
        assert not (tmp_path / "out" / absent).exists()
    finally:
        os.close(parent_fd)
        os.close(root_fd)


@pytest.mark.parametrize(
    ("original_type", "recovery_type"),
    ((KeyboardInterrupt, SystemExit), (SystemExit, KeyboardInterrupt)),
)
def test_build_outer_rollback_base_faults_are_grouped_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_type: type[BaseException],
    recovery_type: type[BaseException],
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "official").mkdir()
    monkeypatch.chdir(root)
    authority = dataclasses.replace(evidence.PRODUCTION_AUTHORITY, output_parent_relative="out")

    def new_guard(_root: Path) -> evidence._secure.CheckoutGuard:
        return evidence._secure.CheckoutGuard(
            root_fd=os.open(root, os.O_RDONLY),
            git_fd=os.open(root / ".git", os.O_RDONLY),
            official_fd=os.open(root / "official", os.O_RDONLY),
            root_identity=evidence._secure._directory_handle_identity(root.stat()),
            git_identity=evidence._secure._directory_handle_identity((root / ".git").stat()),
            official_identity=evidence._secure._directory_handle_identity((root / "official").stat()),
        )

    monkeypatch.setattr(evidence._secure, "_validate_checkout", new_guard)
    monkeypatch.setattr(evidence._secure, "_assert_checkout_rebound", lambda *_args: None)
    collected = evidence.Collected(evidence.GitState("a" * 40, "b" * 40, authority.official_oid), (), {}, {})
    monkeypatch.setattr(evidence, "_collect", lambda *_args: collected)

    def construction_fault(*_args):
        parent = root / "out"
        (parent / "foreign-sentinel").write_bytes(b"keep")
        raise original_type("original construction base fault")

    monkeypatch.setattr(evidence, "_load_bundle", construction_fault)
    monkeypatch.setattr(
        evidence._secure,
        "_cleanup_owned",
        lambda *_args: (_ for _ in ()).throw(recovery_type("rollback cleanup base fault")),
    )
    before_fds = len(os.listdir("/dev/fd"))
    with pytest.raises(evidence.CheckpointPublicationAmbiguityError) as captured:
        evidence._build(root, root / "out" / "run", authority)
    group = captured.value.__cause__
    assert isinstance(group, BaseExceptionGroup)
    assert isinstance(group.exceptions[0], original_type)
    assert isinstance(group.exceptions[1], recovery_type)
    assert len(os.listdir("/dev/fd")) == before_fds
    assert (root / "out" / "foreign-sentinel").read_bytes() == b"keep"
    assert len([path for path in (root / "out").iterdir() if path.name.startswith(".staging.")]) == 1
    assert not (root / "out" / "run").exists()


def test_verify_parent_close_fault_still_closes_checkout_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_fd = os.open(tmp_path, os.O_RDONLY)
    parent_fd = os.dup(root_fd)
    closed = False

    class Guard:
        def __init__(self, descriptor: int) -> None:
            self.root_fd = descriptor

        def close(self) -> None:
            nonlocal closed
            closed = True
            os.close(root_fd)

    monkeypatch.setattr(evidence._secure, "_validate_checkout", lambda _root: Guard(root_fd))
    monkeypatch.setattr(evidence, "_prepare", lambda *_args: (tmp_path / "run", "run"))
    monkeypatch.setattr(evidence._secure, "_open_relative_directory", lambda *_args: parent_fd)
    monkeypatch.setattr(
        evidence, "_assert_output_parent_rebound", lambda *_args: (_ for _ in ()).throw(ValueError("stop"))
    )
    original_close = evidence.os.close

    def close_with_fault(fd: int) -> None:
        if fd == parent_fd:
            original_close(fd)
            raise OSError("injected parent close fault")
        original_close(fd)

    monkeypatch.setattr(evidence.os, "close", close_with_fault)
    with pytest.raises(OSError, match="parent close fault"):
        evidence._verify(tmp_path, tmp_path / "run", _test_authority())
    assert closed


def test_real_git_official_and_builder_source_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    official = root / "official"
    official.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=official, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=official, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=official, check=True)
    (official / "metric.py").write_text("metric = 1\n")
    subprocess.run(["git", "add", "metric.py"], cwd=official, check=True)
    subprocess.run(["git", "commit", "-qm", "official"], cwd=official, check=True)
    official_oid = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=official, text=True).strip()

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    for relative in evidence.PRODUCTION_AUTHORITY.builder_sources:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture for {relative}\n")
    subprocess.run(["git", "add", "official", *evidence.PRODUCTION_AUTHORITY.builder_sources], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "superproject"], cwd=root, check=True)
    authority = dataclasses.replace(evidence.PRODUCTION_AUTHORITY, official_oid=official_oid)
    monkeypatch.chdir(root)
    monkeypatch.setattr(evidence._secure, "CANONICAL_REPO_ROOT", root)
    state = evidence._capture_git_state(root, authority)
    assert state.official_oid == official_oid
    assert len(state.commit) == 40
    assert len(state.tree) == 40
