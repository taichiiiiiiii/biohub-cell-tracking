from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import import_eval36_zarr_bundles as importer
from scripts import pack_eval36_zarr_bundles as packer

ROOT = "6bba_test0001"


def test_production_pins_and_expected_archive_size_gate_are_exact() -> None:
    assert len(packer.ROOTS) == 15 == len(set(packer.ROOTS))
    assert set(packer.PRODUCTION_ARCHIVE_BYTES) == set(packer.ROOTS)
    assert sum(packer.PRODUCTION_ARCHIVE_BYTES.values()) == 6_104_616_960
    assert packer.PRODUCTION_EMBEDDED_MANIFEST_BYTES == 14_458


def _tree(root: Path) -> dict[str, tuple[str, str]]:
    if not root.exists():
        return {}
    result: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            result[relative] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        elif path.is_dir():
            result[relative] = ("dir", "")
        else:
            result[relative] = ("special", "")
    return result


def _manifest(tmp_path: Path, rows: list[tuple[str, bytes]]) -> tuple[Path, packer.ManifestPins]:
    path = tmp_path / "manifest.csv"
    raw = "name,size\n" + "".join(f"{name},{len(payload)}\n" for name, payload in rows)
    path.write_text(raw)
    pins = packer.ManifestPins(
        hashlib.sha256(raw.encode()).hexdigest(), len(raw.splitlines()), (ROOT,), len(rows), "synthetic-competition"
    )
    return path, pins


@pytest.fixture
def bundle(tmp_path: Path) -> dict[str, object]:
    rows = [
        (f"train/{ROOT}.zarr/a", b"alpha"),
        (f"train/{ROOT}.zarr/nested/b", b"beta-data"),
    ]
    manifest, pins = _manifest(tmp_path, rows)
    source = tmp_path / "source"
    output = tmp_path / "output"
    data = tmp_path / "data"
    receipts = tmp_path / "receipts"
    source.mkdir()
    output.mkdir()
    data.mkdir()
    receipts.mkdir()
    for name, payload in rows:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    [result] = packer.pack_bundles(manifest, source, output, (ROOT,), pins=pins)
    return {
        "archive": Path(str(result["archive"])),
        "data": data,
        "manifest": manifest,
        "output": output,
        "pins": pins,
        "receipts": receipts,
        "rows": rows,
        "source": source,
    }


def _import(bundle: dict[str, object], archive: Path | None = None, **kwargs: object) -> dict[str, object]:
    return importer.import_bundles(
        (archive or bundle["archive"],),  # type: ignore[arg-type]
        bundle["manifest"],  # type: ignore[arg-type]
        bundle["data"],  # type: ignore[arg-type]
        receipt_dir=bundle["receipts"],  # type: ignore[arg-type]
        pins=bundle["pins"],  # type: ignore[arg-type]
        **kwargs,
    )


def _raw_archive(members: list[tuple[str, bytes]], *, typeflag: bytes = b"0") -> bytes:
    raw = bytearray()
    for index, (name, payload) in enumerate(members):
        header = bytearray(packer._header(name, len(payload)))
        if index == 0 and typeflag != b"0":
            header[156:157] = typeflag
            header[148:156] = b"        "
            header[148:156] = f"{sum(header):06o}\0 ".encode()
        raw += header
        raw += payload
        raw += b"\0" * (-len(payload) % 512)
    raw += b"\0" * 1024
    raw += b"\0" * (-len(raw) % 10240)
    return bytes(raw)


def _archive_members(archive: Path) -> list[tuple[str, bytes]]:
    fd = os.open(archive, os.O_RDONLY)
    try:
        members = importer._parse_ustar(fd, archive.stat().st_size)
        return [(name, os.pread(fd, member.size, member.offset)) for name, member in members.items()]
    finally:
        os.close(fd)


def _replace_archive(bundle: dict[str, object], members: list[tuple[str, bytes]], name: str | None = None) -> Path:
    original: Path = bundle["archive"]  # type: ignore[assignment]
    path = original.with_name(name or original.name)
    if path == original:
        path.unlink()
    path.write_bytes(_raw_archive(members))
    return path


def test_deterministic_two_run_bytes_and_normalized_member_set(bundle: dict[str, object], tmp_path: Path) -> None:
    second = tmp_path / "second"
    second.mkdir()
    [result] = packer.pack_bundles(
        bundle["manifest"],
        bundle["source"],
        second,
        (ROOT,),
        pins=bundle["pins"],  # type: ignore[arg-type]
    )
    first: Path = bundle["archive"]  # type: ignore[assignment]
    again = Path(str(result["archive"]))
    assert first.read_bytes() == again.read_bytes()
    assert result["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    members = _archive_members(first)
    assert [name for name, _ in members] == [
        f"train/{ROOT}.zarr/a",
        f"train/{ROOT}.zarr/nested/b",
        packer.BUNDLE_MANIFEST_NAME,
    ]


def test_import_installs_then_resumes_by_skipping_and_writes_receipt(bundle: dict[str, object]) -> None:
    first = _import(bundle)
    assert (first["installed"], first["skipped"], first["validated"]) == (2, 0, 2)
    second = _import(bundle)
    assert (second["installed"], second["skipped"]) == (0, 2)
    receipt = json.loads((bundle["receipts"] / str(second["receipt"])).read_text())  # type: ignore[operator]
    assert receipt["status"] == "PASS"
    assert {item["action"] for item in receipt["files"]} == {"skipped"}
    assert set(receipt["archives"][0]) == {"bytes", "name", "root", "sha256"}
    assert receipt["archives"][0]["name"] == f"{ROOT}.tar"
    assert receipt["data_root_identity"] == {
        "device": bundle["data"].stat().st_dev,
        "inode": bundle["data"].stat().st_ino,
    }  # type: ignore[union-attr]


def test_dry_run_is_non_mutating_including_lock_and_receipt(bundle: dict[str, object]) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    before = _tree(data)
    result = _import(bundle, dry_run=True)
    assert result["validated"] == 2 and result["installed"] == 0
    assert _tree(data) == before
    assert _tree(Path(bundle["receipts"])) == {}  # type: ignore[arg-type]


@pytest.mark.parametrize("roots", [(ROOT, ROOT), (), ("../escape",), ("unknown",)])
def test_packer_rejects_duplicate_empty_unsafe_or_unknown_roots(
    bundle: dict[str, object], tmp_path: Path, roots: tuple[str, ...]
) -> None:
    output = tmp_path / f"bad-{len(roots)}-{hash(roots)}"
    output.mkdir()
    with pytest.raises(packer.BundleError):
        packer.pack_bundles(
            bundle["manifest"],
            bundle["source"],
            output,
            roots,
            pins=bundle["pins"],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("kind", ["hash", "count", "set", "size"])
def test_manifest_pin_count_set_and_size_drift_fail_before_mutation(bundle: dict[str, object], kind: str) -> None:
    manifest: Path = bundle["manifest"]  # type: ignore[assignment]
    pins: packer.ManifestPins = bundle["pins"]  # type: ignore[assignment]
    if kind == "hash":
        bad = packer.ManifestPins("0" * 64, pins.line_count, pins.roots, pins.files_per_root, pins.competition)
    elif kind == "count":
        bad = packer.ManifestPins(pins.sha256, pins.line_count + 1, pins.roots, pins.files_per_root, pins.competition)
    elif kind == "set":
        bad = packer.ManifestPins(pins.sha256, pins.line_count, pins.roots, pins.files_per_root + 1, pins.competition)
    else:
        raw = manifest.read_text().replace(",5\n", ",6\n", 1).encode()
        manifest.write_bytes(raw)
        bad = packer.ManifestPins(
            hashlib.sha256(raw).hexdigest(), len(raw.splitlines()), pins.roots, pins.files_per_root, pins.competition
        )
    data: Path = bundle["data"]  # type: ignore[assignment]
    before = _tree(data)
    with pytest.raises(packer.BundleError):
        importer.import_bundles((bundle["archive"],), manifest, data, dry_run=True, pins=bad)  # type: ignore[arg-type]
    assert _tree(data) == before


def test_packer_rejects_existing_output_without_reuse(bundle: dict[str, object]) -> None:
    with pytest.raises(packer.BundleError, match="output already exists"):
        packer.pack_bundles(
            bundle["manifest"],
            bundle["source"],
            bundle["output"],
            (ROOT,),
            pins=bundle["pins"],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("leaf_kind", ["symlink", "fifo"])
def test_packer_rejects_symlink_or_special_source_leaf(
    bundle: dict[str, object], tmp_path: Path, leaf_kind: str
) -> None:
    leaf: Path = bundle["source"] / f"train/{ROOT}.zarr/a"  # type: ignore[operator]
    leaf.unlink()
    if leaf_kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"alpha")
        leaf.symlink_to(target)
    else:
        os.mkfifo(leaf)
    output = tmp_path / "source-bad"
    output.mkdir()
    with pytest.raises(packer.BundleError):
        packer.pack_bundles(
            bundle["manifest"],
            bundle["source"],
            output,
            (ROOT,),
            pins=bundle["pins"],  # type: ignore[arg-type]
        )


def test_packer_rejects_symlink_source_ancestor(bundle: dict[str, object], tmp_path: Path) -> None:
    source: Path = bundle["source"]  # type: ignore[assignment]
    real = source / "train"
    moved = source / "real-train"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    output = tmp_path / "ancestor-bad"
    output.mkdir()
    with pytest.raises(packer.BundleError, match="real directory"):
        packer.pack_bundles(bundle["manifest"], source, output, (ROOT,), pins=bundle["pins"])  # type: ignore[arg-type]


def test_source_mutation_is_detected_and_no_final_is_published(
    bundle: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_leaf: Path = bundle["source"] / f"train/{ROOT}.zarr/a"  # type: ignore[operator]
    original = packer._HashingReader.copy_to
    mutated = False

    def mutate(self: packer._HashingReader, target: object, size: int) -> None:
        nonlocal mutated
        original(self, target, size)  # type: ignore[arg-type]
        if not mutated:
            source_leaf.write_bytes(b"ALPHA")
            mutated = True

    monkeypatch.setattr(packer._HashingReader, "copy_to", mutate)
    output = tmp_path / "mutated-output"
    output.mkdir()
    with pytest.raises(packer.BundleError, match="changed|mismatch"):
        packer.pack_bundles(bundle["manifest"], bundle["source"], output, (ROOT,), pins=bundle["pins"])  # type: ignore[arg-type]
    assert list(output.iterdir()) == []


def test_packer_publication_failure_removes_its_claimed_final(
    bundle: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "fsync-failure"
    output.mkdir()
    original = packer.os.fsync
    calls = 0

    def fail_directory(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        original(fd)

    monkeypatch.setattr(packer.os, "fsync", fail_directory)
    with pytest.raises(OSError, match="injected"):
        packer.pack_bundles(
            bundle["manifest"],
            bundle["source"],
            output,
            (ROOT,),
            pins=bundle["pins"],  # type: ignore[arg-type]
        )
    assert list(output.iterdir()) == []


def test_output_directory_swap_cannot_redirect_publication(
    bundle: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "swapped-output"
    moved = tmp_path / "original-output"
    output.mkdir()
    original = packer.rename_noreplace
    swapped = False

    def swap_then_rename(source: str, destination: str, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped:
            output.rename(moved)
            output.mkdir()
            swapped = True
        original(source, destination, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(packer, "rename_noreplace", swap_then_rename)
    with pytest.raises(packer.BundleError, match="output directory changed"):
        packer.pack_bundles(
            bundle["manifest"],
            bundle["source"],
            output,
            (ROOT,),
            pins=bundle["pins"],  # type: ignore[arg-type]
        )
    assert list(output.iterdir()) == []
    assert list(moved.iterdir()) == []


@pytest.mark.parametrize("bad_name", ["../escape", "/absolute", "a\\b", f"train/{ROOT}.zarr/x/../a"])
def test_traversal_and_alias_members_fail_with_zero_data_mutation(bundle: dict[str, object], bad_name: str) -> None:
    members = _archive_members(bundle["archive"])  # type: ignore[arg-type]
    members[0] = (bad_name, members[0][1])
    archive = _replace_archive(bundle, members)
    data: Path = bundle["data"]  # type: ignore[assignment]
    before = _tree(data)
    with pytest.raises(packer.BundleError):
        _import(bundle, archive)
    assert _tree(data) == before


def test_duplicate_archive_members_fail(bundle: dict[str, object]) -> None:
    members = _archive_members(bundle["archive"])  # type: ignore[arg-type]
    archive = _replace_archive(bundle, [members[0], members[0], *members[1:]])
    with pytest.raises(packer.BundleError, match="duplicate"):
        _import(bundle, archive)


@pytest.mark.parametrize("typeflag", [b"1", b"2", b"3", b"4", b"5", b"6", b"x", b"g", b"L", b"S"])
def test_links_directories_devices_fifo_pax_gnu_and_sparse_fail(bundle: dict[str, object], typeflag: bytes) -> None:
    members = _archive_members(bundle["archive"])  # type: ignore[arg-type]
    archive: Path = bundle["archive"]  # type: ignore[assignment]
    archive.unlink()
    archive.write_bytes(_raw_archive(members, typeflag=typeflag))
    with pytest.raises(packer.BundleError, match="non-regular"):
        _import(bundle, archive)


def test_duplicate_manifest_key_and_nonfinite_json_fail(bundle: dict[str, object]) -> None:
    members = _archive_members(bundle["archive"])  # type: ignore[arg-type]
    manifest = members[-1][1]
    duplicate = manifest.replace(b'{"competition":', b'{"root":"x","competition":', 1)
    archive = _replace_archive(bundle, [*members[:-1], (packer.BUNDLE_MANIFEST_NAME, duplicate)])
    with pytest.raises(packer.BundleError, match="duplicate JSON key"):
        _import(bundle, archive)
    members[-1] = (packer.BUNDLE_MANIFEST_NAME, manifest.replace(b'"schema_version":1', b'"schema_version":NaN'))
    archive = _replace_archive(bundle, members)
    with pytest.raises(packer.BundleError, match="non-finite"):
        _import(bundle, archive)


@pytest.mark.parametrize("mutation", ["root", "set", "size", "hash", "noncanonical"])
def test_embedded_wrong_root_set_size_hash_or_canonical_form_fails(bundle: dict[str, object], mutation: str) -> None:
    members = _archive_members(bundle["archive"])  # type: ignore[arg-type]
    value = json.loads(members[-1][1])
    if mutation == "root":
        value["root"] = "other"
    elif mutation == "set":
        value["files"][0]["path"] += "x"
    elif mutation == "size":
        value["files"][0]["size"] += 1
    elif mutation == "hash":
        value["files"][0]["sha256"] = "0" * 64
    raw = packer.canonical_json(value)
    if mutation == "noncanonical":
        raw = json.dumps(value, indent=2).encode()
    archive = _replace_archive(bundle, [*members[:-1], (packer.BUNDLE_MANIFEST_NAME, raw)])
    with pytest.raises(packer.BundleError):
        _import(bundle, archive)


@pytest.mark.parametrize("corruption", ["truncate", "garbage", "checksum", "extra-zero-record"])
def test_corrupt_or_truncated_tar_fails(bundle: dict[str, object], corruption: str) -> None:
    archive: Path = bundle["archive"]  # type: ignore[assignment]
    raw = bytearray(archive.read_bytes())
    if corruption == "truncate":
        raw = raw[:-513]
    elif corruption == "garbage":
        raw[-1] = 1
    elif corruption == "extra-zero-record":
        raw += b"\0" * 10240
    else:
        raw[0] ^= 1
    archive.write_bytes(raw)
    with pytest.raises(packer.BundleError):
        _import(bundle, archive)


def test_archive_symlink_and_hardlink_are_rejected(bundle: dict[str, object], tmp_path: Path) -> None:
    archive: Path = bundle["archive"]  # type: ignore[assignment]
    symlink = tmp_path / f"symlink-{ROOT}.tar"
    symlink.symlink_to(archive)
    with pytest.raises(packer.BundleError):
        _import(bundle, symlink)
    hardlink = tmp_path / f"hard-{ROOT}.tar"
    os.link(archive, hardlink)
    with pytest.raises(packer.BundleError, match="single-link"):
        _import(bundle, archive)


def test_special_archive_is_rejected_without_blocking(bundle: dict[str, object]) -> None:
    archive: Path = bundle["archive"]  # type: ignore[assignment]
    archive.unlink()
    os.mkfifo(archive)
    with pytest.raises(packer.BundleError, match="regular file"):
        _import(bundle, archive)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_unsafe_existing_destination_is_hold_and_never_replaced(
    bundle: dict[str, object], tmp_path: Path, kind: str
) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    leaf = data / f"train/{ROOT}.zarr/a"
    leaf.parent.mkdir(parents=True)
    if kind == "symlink":
        target = tmp_path / "outside"
        target.write_bytes(b"alpha")
        leaf.symlink_to(target)
    elif kind == "hardlink":
        target = tmp_path / "outside"
        target.write_bytes(b"alpha")
        os.link(target, leaf)
    elif kind == "fifo":
        os.mkfifo(leaf)
    else:
        leaf.mkdir()
    before = _tree(data)
    with pytest.raises(importer.ImportHold):
        _import(bundle)
    assert _tree(data) == before


def test_wrong_existing_destination_is_hold_not_overwritten(bundle: dict[str, object]) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    leaf = data / f"train/{ROOT}.zarr/a"
    leaf.parent.mkdir(parents=True)
    leaf.write_bytes(b"WRONG")
    with pytest.raises(importer.ImportHold, match="refusing replacement"):
        _import(bundle)
    assert leaf.read_bytes() == b"WRONG"
    receipts = [json.loads(path.read_text()) for path in Path(bundle["receipts"]).glob("*.json")]  # type: ignore[arg-type]
    assert any(receipt["status"] == "HOLD" and receipt["validated"] == 2 for receipt in receipts)


def test_destination_symlink_ancestor_is_hold(bundle: dict[str, object], tmp_path: Path) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    outside = tmp_path / "outside"
    outside.mkdir()
    (data / "train").symlink_to(outside, target_is_directory=True)
    with pytest.raises(importer.ImportHold, match="ancestor"):
        _import(bundle)
    assert list(outside.iterdir()) == []


def test_lock_contention_is_hold(bundle: dict[str, object]) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    lock = data / ".download_data.lock"
    with lock.open("a+") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(importer.ImportHold, match="owns lock"):
            _import(bundle)


def test_unsafe_receipt_path_fails_before_data_mutation(bundle: dict[str, object], tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe-receipts"
    outside = tmp_path / "outside-receipts"
    outside.mkdir()
    unsafe.symlink_to(outside, target_is_directory=True)
    data: Path = bundle["data"]  # type: ignore[assignment]
    before = _tree(data)
    with pytest.raises(importer.ImportHold, match="receipt"):
        importer.import_bundles(
            (bundle["archive"],),  # type: ignore[arg-type]
            bundle["manifest"],  # type: ignore[arg-type]
            data,
            receipt_dir=unsafe,
            pins=bundle["pins"],  # type: ignore[arg-type]
        )
    assert _tree(data) == before
    assert list(outside.iterdir()) == []


def test_receipt_inside_data_is_hold_before_payload_mutation(bundle: dict[str, object]) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    receipt = data / "receipts"
    receipt.mkdir()
    before = _tree(data)
    with pytest.raises(importer.ImportHold, match="outside data"):
        importer.import_bundles(
            (bundle["archive"],),  # type: ignore[arg-type]
            bundle["manifest"],  # type: ignore[arg-type]
            data,
            receipt_dir=receipt,
            pins=bundle["pins"],  # type: ignore[arg-type]
        )
    assert _tree(data) == before


def test_no_clobber_race_is_detected_and_wrong_file_preserved(
    bundle: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    original = importer._mutation_lock

    @contextlib.contextmanager
    def race(data_fd: int, root: Path):
        with original(data_fd, root):
            leaf = data / f"train/{ROOT}.zarr/a"
            leaf.parent.mkdir(parents=True, exist_ok=True)
            leaf.write_bytes(b"WRONG")
            yield

    monkeypatch.setattr(importer, "_mutation_lock", race)
    with pytest.raises(importer.ImportHold):
        _import(bundle)
    assert (data / f"train/{ROOT}.zarr/a").read_bytes() == b"WRONG"


def test_mid_write_failure_exposes_no_unverified_final_and_resume_succeeds(
    bundle: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = importer._copy_payload
    calls = 0

    def fail_second(archive: importer.CheckedArchive, member: importer.Member, target: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            target.write(b"partial")  # type: ignore[attr-defined]
            raise OSError("injected write failure")
        return original(archive, member, target)  # type: ignore[arg-type]

    monkeypatch.setattr(importer, "_copy_payload", fail_second)
    with pytest.raises(OSError, match="injected"):
        _import(bundle)
    data: Path = bundle["data"]  # type: ignore[assignment]
    assert (data / f"train/{ROOT}.zarr/a").read_bytes() == b"alpha"
    assert not (data / f"train/{ROOT}.zarr/nested/b").exists()
    assert not list(data.rglob("*.tmp"))
    failure_receipts = [json.loads(path.read_text()) for path in Path(bundle["receipts"]).glob("*.json")]  # type: ignore[arg-type]
    assert any(
        receipt["status"] == "FAIL"
        and receipt["validated"] == 2
        and receipt["installed"] == 1
        and receipt["archives"][0]["name"] == f"{ROOT}.tar"
        for receipt in failure_receipts
    )
    monkeypatch.setattr(importer, "_copy_payload", original)
    result = _import(bundle)
    assert result["installed"] == 1 and result["skipped"] == 1


def test_temporary_readback_detects_post_copy_corruption(
    bundle: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = importer._copy_payload

    def corrupt_after_copy(archive: importer.CheckedArchive, member: importer.Member, target: object) -> str:
        digest = original(archive, member, target)  # type: ignore[arg-type]
        target.seek(0)  # type: ignore[attr-defined]
        target.write(b"X")  # type: ignore[attr-defined]
        return digest

    monkeypatch.setattr(importer, "_copy_payload", corrupt_after_copy)
    with pytest.raises(packer.BundleError, match="readback"):
        _import(bundle)
    data: Path = bundle["data"]  # type: ignore[assignment]
    assert not any(path.is_file() for path in data.rglob("*") if path.name != ".download_data.lock")
    assert not list(data.rglob("*.tmp"))


def test_post_publication_fsync_failure_leaves_exact_single_link_and_resumes(
    bundle: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = importer.os.fsync
    calls = 0

    def fail_first_parent(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected post-publication fsync failure")
        original(fd)

    monkeypatch.setattr(importer.os, "fsync", fail_first_parent)
    with pytest.raises(OSError, match="post-publication"):
        _import(bundle)
    leaf: Path = bundle["data"] / f"train/{ROOT}.zarr/a"  # type: ignore[operator]
    assert leaf.read_bytes() == b"alpha"
    assert leaf.stat().st_nlink == 1
    assert not list(Path(bundle["data"]).rglob("*.tmp"))  # type: ignore[arg-type]
    receipts = [json.loads(path.read_text()) for path in Path(bundle["receipts"]).glob("*.json")]  # type: ignore[arg-type]
    assert any(receipt["status"] == "FAIL" and receipt["installed"] == 1 for receipt in receipts)
    monkeypatch.setattr(importer.os, "fsync", original)
    result = _import(bundle)
    assert result["installed"] == 1 and result["skipped"] == 1


def test_archive_mutation_before_install_fails_before_payload_mutation(
    bundle: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive: Path = bundle["archive"]  # type: ignore[assignment]
    original = importer._mutation_lock

    @contextlib.contextmanager
    def mutate(data_fd: int, root: Path):
        raw = bytearray(archive.read_bytes())
        raw[-1] ^= 1
        archive.write_bytes(raw)
        with original(data_fd, root):
            yield

    monkeypatch.setattr(importer, "_mutation_lock", mutate)
    with pytest.raises(packer.BundleError, match="changed"):
        _import(bundle)
    data: Path = bundle["data"]  # type: ignore[assignment]
    assert not (data / "train").exists()


def test_pass_receipt_is_durably_written_while_download_lock_is_held(
    bundle: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = importer._write_receipt
    observed = False

    def assert_locked(receipt_dir: Path, value: dict[str, object]) -> Path:
        nonlocal observed
        lock: Path = bundle["data"] / ".download_data.lock"  # type: ignore[operator]
        with lock.open("a+") as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        observed = True
        return original(receipt_dir, value)

    monkeypatch.setattr(importer, "_write_receipt", assert_locked)
    assert _import(bundle)["status"] == "PASS"
    assert observed


def test_data_root_swap_is_hold_and_cannot_redirect_installation(
    bundle: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data: Path = bundle["data"]  # type: ignore[assignment]
    moved = tmp_path / "original-data"
    original = importer._mutation_lock

    @contextlib.contextmanager
    def swap(data_fd: int, root: Path):
        data.rename(moved)
        data.mkdir()
        with original(data_fd, root):
            yield

    monkeypatch.setattr(importer, "_mutation_lock", swap)
    with pytest.raises(importer.ImportHold, match="data root identity"):
        _import(bundle)
    assert _tree(data) == {}
    assert not (moved / "train").exists()


def test_existing_receipt_reuse_requires_stable_single_link_regular_file(
    bundle: dict[str, object], tmp_path: Path
) -> None:
    receipts: Path = bundle["receipts"]  # type: ignore[assignment]
    value = {"schema_version": 1, "status": "FAIL"}
    receipt = importer._write_receipt(receipts, value)
    assert importer._write_receipt(receipts, value) == receipt
    alias = tmp_path / "receipt-alias"
    os.link(receipt, alias)
    with pytest.raises(importer.ImportHold, match="unsafe existing receipt"):
        importer._write_receipt(receipts, value)
    alias.unlink()
    payload = receipt.read_bytes()
    receipt.unlink()
    target = tmp_path / "receipt-target"
    target.write_bytes(payload)
    receipt.symlink_to(target)
    with pytest.raises(importer.ImportHold, match="unsafe existing receipt"):
        importer._write_receipt(receipts, value)


def test_two_archives_claiming_same_root_fail_before_data_mutation(bundle: dict[str, object], tmp_path: Path) -> None:
    original: Path = bundle["archive"]  # type: ignore[assignment]
    second_dir = tmp_path / "other"
    second_dir.mkdir()
    second = second_dir / original.name
    second.write_bytes(original.read_bytes())
    data: Path = bundle["data"]  # type: ignore[assignment]
    before = _tree(data)
    with pytest.raises(packer.BundleError, match="duplicate archive root"):
        importer.import_bundles(
            (original, second),
            bundle["manifest"],  # type: ignore[arg-type]
            data,
            receipt_dir=bundle["receipts"],  # type: ignore[arg-type]
            pins=bundle["pins"],  # type: ignore[arg-type]
        )
    assert _tree(data) == before


def test_cli_failures_are_canonical_json_and_nonzero(
    bundle: dict[str, object], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importer, "MANIFEST_PATH", Path("missing.csv"))
    monkeypatch.setattr(importer, "DATA_ROOT", bundle["data"])
    code = importer.main([str(bundle["archive"])])
    captured = capsys.readouterr()
    assert code == 1
    value = json.loads(captured.err)
    assert value["status"] == "FAIL"
    assert captured.err == packer.canonical_json(value).decode()


def test_malformed_cli_arguments_are_canonical_failures(capsys: pytest.CaptureFixture[str]) -> None:
    assert importer.main([]) == 1
    imported = json.loads(capsys.readouterr().err)
    assert imported["status"] == "FAIL"
    assert packer.main([]) == 1
    packed = json.loads(capsys.readouterr().err)
    assert packed["status"] == "FAIL"
