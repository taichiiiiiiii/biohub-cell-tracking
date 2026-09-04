from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path

import blosc2
import pytest

from scripts import verify_eval36_images as verifier


def _array_metadata(profile: verifier.Profile) -> dict[str, object]:
    return verifier._expected_array_metadata(profile)


def _group_metadata() -> dict[str, object]:
    return {
        "attributes": {
            "image_statistics": {
                "quantiles": {
                    "0.0": 0.0,
                    "0.001": 1.0,
                    "0.01": 2.0,
                    "0.1": 3.0,
                    "0.9": 4.0,
                    "0.99": 5.0,
                    "0.999": 6.0,
                    "1.0": 7.0,
                }
            },
            "multiscales": [
                {
                    "axes": [
                        {"name": "T", "type": "time", "unit": "second"},
                        {"name": "Z", "type": "space", "unit": "micrometer"},
                        {"name": "Y", "type": "space", "unit": "micrometer"},
                        {"name": "X", "type": "space", "unit": "micrometer"},
                    ],
                    "datasets": [
                        {
                            "coordinateTransformations": [{"scale": [1.0, 1.625, 0.40625, 0.40625], "type": "scale"}],
                            "path": "0",
                        }
                    ],
                    "name": "0",
                    "version": "0.5",
                }
            ],
        },
        "consolidated_metadata": None,
        "node_type": "group",
        "zarr_format": 3,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(verifier.canonical_json(value))


def _tree_records(data: Path, root: str) -> list[dict[str, object]]:
    records = []
    for path in sorted((data / "train" / f"{root}.zarr").rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            records.append(
                {
                    "path": path.relative_to(data).as_posix(),
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    return records


def _refresh_manifest(data: Path, base: verifier.Profile) -> verifier.Profile:
    rows: list[tuple[str, int]] = []
    for stem in base.stems:
        for path in sorted((data / "train" / f"{stem}.zarr").rglob("*")):
            if path.is_file():
                rows.append((path.relative_to(data).as_posix(), path.stat().st_size))
    raw = b"name,size\r\n" + b"".join(f"{name},{size}\r\n".encode() for name, size in rows)
    (data / "manifest.csv").write_bytes(raw)
    return dataclasses.replace(
        base,
        manifest_bytes=len(raw),
        manifest_lines=raw.count(b"\n"),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        stored_bytes=sum(size for _, size in rows),
    )


def _write_receipt(data: Path, receipt_dir: Path, profile: verifier.Profile) -> tuple[Path, dict[str, object]]:
    records = _tree_records(data, profile.import_roots[0])
    files = []
    for index, item in enumerate(records):
        files.append(
            {
                "action": "skipped" if index == 0 else "installed",
                "path": item["path"],
                "sha256": item["sha256"],
                "size": item["size"],
            }
        )
    info = data.stat()
    value = {
        "archives": [
            {
                "bytes": profile.archive_bytes[0],
                "name": f"{profile.import_roots[0]}.tar",
                "root": profile.import_roots[0],
                "sha256": "a" * 64,
            }
        ],
        "data_root_identity": {"device": info.st_dev, "inode": info.st_ino},
        "files": files,
        "installed": len(files) - 1,
        "manifest_csv_sha256": profile.manifest_sha256,
        "schema_version": 1,
        "skipped": 1,
        "status": "PASS",
        "validated": len(files),
    }
    raw = verifier.canonical_json(value)
    receipt = receipt_dir / f"eval36-import-{hashlib.sha256(raw).hexdigest()}.json"
    receipt.write_bytes(raw)
    return receipt, value


@pytest.fixture
def layout(tmp_path: Path) -> dict[str, object]:
    data = tmp_path / "data"
    output = tmp_path / "sealed"
    source = tmp_path / "verifier.py"
    data.mkdir()
    output.mkdir()
    source.write_text("# fixed verifier source\n")
    (data / ".download_data.lock").touch()
    base = verifier.Profile(
        stems=("44b6_fixture1", "6bba_fixture2"),
        import_roots=("6bba_fixture2",),
        archive_bytes=(12_345,),
        archive_sha256=("a" * 64,),
        manifest_bytes=0,
        manifest_lines=0,
        manifest_sha256="",
        files_per_root=4,
        stored_bytes=0,
        chunks_per_root=2,
        chunk_shape=(1, 1, 2, 2),
        decoded_shape=(1, 2, 2),
        decoded_chunk_bytes=8,
        decoded_bytes=32,
        decoded_sha256="",
        import_installed=3,
        import_skipped=1,
        import_validated=4,
    )
    for root_index, stem in enumerate(base.stems):
        zarr_root = data / "train" / f"{stem}.zarr"
        _write_json(zarr_root / "zarr.json", _group_metadata())
        _write_json(zarr_root / "0/zarr.json", _array_metadata(base))
        for chunk_index in range(base.chunks_per_root):
            decoded = bytes([root_index * 10 + chunk_index]) * base.decoded_chunk_bytes
            chunk = zarr_root / "0/c" / str(chunk_index) / "0/0/0"
            chunk.parent.mkdir(parents=True)
            chunk.write_bytes(blosc2.compress(decoded, typesize=2, codec=blosc2.Codec.ZSTD, clevel=1))
    decoded_digest = hashlib.sha256()
    for root_index, stem in enumerate(base.stems):
        for chunk_index in range(base.chunks_per_root):
            decoded = bytes([root_index * 10 + chunk_index]) * base.decoded_chunk_bytes
            decoded_digest.update(stem.encode("ascii"))
            decoded_digest.update(chunk_index.to_bytes(2, "big"))
            decoded_digest.update(decoded)
    profile = dataclasses.replace(_refresh_manifest(data, base), decoded_sha256=decoded_digest.hexdigest())
    receipt, receipt_value = _write_receipt(data, tmp_path, profile)
    return {
        "data": data,
        "output": output,
        "profile": profile,
        "receipt": receipt,
        "receipt_value": receipt_value,
        "source": source,
    }


def _run(layout: dict[str, object], **kwargs: object) -> dict[str, object]:
    return verifier.verify_images(
        layout["data"],
        layout["receipt"],
        layout["output"],
        profile=layout["profile"],
        verifier_path=layout["source"],
        now=lambda: "2026-09-04T00:00:00Z",
        **kwargs,
    )


def test_production_profile_is_frozen_exactly() -> None:
    profile = verifier.PRODUCTION_PROFILE
    assert profile.stems == (
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
    assert len(profile.stems) == 36
    assert len(set(profile.stems)) == 36
    assert profile.stems[:3] == ("44b6_12dfb391", "44b6_267148e4", "44b6_2a2eff9f")
    assert profile.stems[-3:] == ("6bba_3c5691b6", "6bba_3db54e20", "6bba_3fda6b25")
    assert profile.manifest_bytes == 1_187_624
    assert profile.manifest_lines == 24_887
    assert profile.manifest_sha256 == "6c1c59644daf7fe59458dc860f2e1783d1217be389a791ea54e1f611f5f848f4"
    assert profile.stored_bytes == 15_932_872_938
    assert profile.decoded_bytes == 30_198_988_800
    assert profile.decoded_sha256 == "635a326ff78526a3d43952b94950e6d97d07db14cd53bc056517ea70d5b49646"


def test_happy_path_publishes_canonical_single_link_ready_last(layout: dict[str, object], monkeypatch) -> None:
    events: list[str] = []
    original = verifier.rename_noreplace

    def recording(source: str, destination: str, *, directory_fd: int) -> None:
        events.append(destination)
        original(source, destination, directory_fd=directory_fd)

    monkeypatch.setattr(verifier, "rename_noreplace", recording)
    before = {
        path.relative_to(layout["data"]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path(layout["data"]).rglob("*")
        if path.is_file()
    }
    result = _run(layout)
    assert result["status"] == "PASS"
    assert events == ["IMAGE_CONTENT_INVENTORY.json", "READY.json"]
    inventory_path = Path(layout["output"]) / "IMAGE_CONTENT_INVENTORY.json"
    ready_path = Path(layout["output"]) / "READY.json"
    inventory_raw = inventory_path.read_bytes()
    ready_raw = ready_path.read_bytes()
    inventory = verifier.strict_json(inventory_raw)
    ready = verifier.strict_json(ready_raw)
    assert verifier.canonical_json(inventory) == inventory_raw
    assert verifier.canonical_json(ready) == ready_raw
    assert inventory_path.stat().st_nlink == ready_path.stat().st_nlink == 1
    assert ready["inventory"]["sha256"] == hashlib.sha256(inventory_raw).hexdigest()
    ready_core = {key: value for key, value in ready.items() if key not in {"created_utc", "ready_content_sha256"}}
    assert ready["ready_content_sha256"] == hashlib.sha256(verifier.canonical_json(ready_core)).hexdigest()
    assert ready["created_utc"] == "2026-09-04T00:00:00Z"
    assert ready["status"] == "READY"
    assert ready["import_receipt"]["reference"] == Path(layout["receipt"]).name
    assert ready["verifier"]["reference"] == Path(layout["source"]).name
    assert ready["decoded"]["chunks"] == 4
    assert ready["decoded"]["bytes"] == 32
    assert len(inventory["files"]) == 8
    assert {record["stem"] for record in inventory["files"]} == set(layout["profile"].stems)
    assert set(ready) == {
        "created_utc",
        "data_root_identity",
        "decoded",
        "digest_scope",
        "import_receipt",
        "inventory",
        "manifest",
        "ready_content_sha256",
        "schema_version",
        "status",
        "verifier",
    }
    image_view = Path(layout["data"]) / "train"
    image_info = image_view.stat(follow_symlinks=False)
    assert ready["data_root_identity"] == {"device": image_info.st_dev, "inode": image_info.st_ino}
    current_by_path = {}
    for path in sorted(image_view.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            current_by_path[path.relative_to(image_view).as_posix()] = (len(raw), hashlib.sha256(raw).hexdigest())
    ready_by_path = {record["path"]: (record["bytes"], record["sha256"]) for record in inventory["files"]}
    assert ready_by_path == current_by_path
    assert all(not path.startswith("train/") for path in ready_by_path)
    import_receipt = verifier.strict_json(Path(layout["receipt"]).read_bytes())
    dataset_info = Path(layout["data"]).stat(follow_symlinks=False)
    assert import_receipt["data_root_identity"] == {
        "device": dataset_info.st_dev,
        "inode": dataset_info.st_ino,
    }
    after = {
        path.relative_to(layout["data"]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path(layout["data"]).rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("kind", ["bytes", "lines", "sha256"])
def test_manifest_pin_drift_fails_without_ready(layout: dict[str, object], kind: str) -> None:
    profile = layout["profile"]
    replacement = {
        "bytes": dataclasses.replace(profile, manifest_bytes=profile.manifest_bytes + 1),
        "lines": dataclasses.replace(profile, manifest_lines=profile.manifest_lines + 1),
        "sha256": dataclasses.replace(profile, manifest_sha256="0" * 64),
    }[kind]
    layout["profile"] = replacement
    with pytest.raises(verifier.VerificationError):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


def test_root_and_member_set_drift_fail(layout: dict[str, object]) -> None:
    extra_root = Path(layout["data"]) / "train/44b6_extra.zarr"
    extra_root.mkdir()
    with pytest.raises(verifier.VerificationError, match="root set"):
        _run(layout)
    extra_root.rmdir()
    member = Path(layout["data"]) / "train/44b6_fixture1.zarr/extra"
    member.write_bytes(b"extra")
    with pytest.raises(verifier.VerificationError, match="member set"):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


def test_safe_geff_ground_truth_tree_is_ignored_without_reading_bytes(layout: dict[str, object], monkeypatch) -> None:
    geff = Path(layout["data"]) / "train/44b6_ground_truth.geff"
    (geff / "nodes/c/0").mkdir(parents=True)
    (geff / "zarr.json").write_bytes(b'{"ground_truth":"must not be parsed"}\n')
    (geff / "nodes/c/0/0").write_bytes(b"opaque GT bytes\x00\xff")
    original = verifier._read_data_file
    reads: list[str] = []

    def record(data_fd: int, relative: str):
        reads.append(relative)
        return original(data_fd, relative)

    monkeypatch.setattr(verifier, "_read_data_file", record)
    _run(layout)
    inventory = verifier.strict_json((Path(layout["output"]) / "IMAGE_CONTENT_INVENTORY.json").read_bytes())
    assert len(inventory["files"]) == 8
    assert all(".geff" not in record["path"] for record in inventory["files"])
    assert all(".geff" not in path for path in reads)
    assert {record["path"].split("/", 1)[0] for record in inventory["files"]} == {
        "44b6_fixture1.zarr",
        "6bba_fixture2.zarr",
    }


def test_manifest_size_drift_fails_at_current_file(layout: dict[str, object]) -> None:
    chunk = Path(layout["data"]) / "train/44b6_fixture1.zarr/0/c/0/0/0/0"
    chunk.write_bytes(chunk.read_bytes() + b"x")
    profile = _refresh_manifest(Path(layout["data"]), layout["profile"])
    layout["profile"] = dataclasses.replace(profile, stored_bytes=profile.stored_bytes - 1)
    with pytest.raises(verifier.VerificationError, match="selected-byte"):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


@pytest.mark.parametrize("target", ["group", "array", "codec", "decode"])
def test_metadata_codec_and_decode_drift_fail(layout: dict[str, object], target: str) -> None:
    root = Path(layout["data"]) / "train/44b6_fixture1.zarr"
    kwargs = {}
    if target == "group":
        value = _group_metadata()
        value["node_type"] = "array"
        _write_json(root / "zarr.json", value)
        layout["profile"] = _refresh_manifest(Path(layout["data"]), layout["profile"])
    elif target in {"array", "codec"}:
        value = _array_metadata(layout["profile"])
        if target == "array":
            value["shape"] = [3, 1, 2, 2]
        else:
            value["codecs"][1]["configuration"]["clevel"] = 2
        _write_json(root / "0/zarr.json", value)
        layout["profile"] = _refresh_manifest(Path(layout["data"]), layout["profile"])
    else:
        kwargs["decoder"] = lambda _raw: b"short"
    with pytest.raises(verifier.VerificationError):
        _run(layout, **kwargs)
    assert not (Path(layout["output"]) / "READY.json").exists()


def test_ome_axes_and_scale_are_strict(layout: dict[str, object]) -> None:
    root = Path(layout["data"]) / "train/44b6_fixture1.zarr/zarr.json"
    value = _group_metadata()
    value["attributes"]["multiscales"][0]["axes"][0]["name"] = "t"
    _write_json(root, value)
    layout["profile"] = _refresh_manifest(Path(layout["data"]), layout["profile"])
    with pytest.raises(verifier.VerificationError, match="TZYX"):
        _run(layout)


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_symlink_and_hardlink_are_rejected(layout: dict[str, object], link_kind: str) -> None:
    target = Path(layout["data"]) / "train/44b6_fixture1.zarr/zarr.json"
    saved = target.read_bytes()
    target.unlink()
    backing = Path(layout["data"]).parent / "backing.json"
    backing.write_bytes(saved)
    if link_kind == "symlink":
        target.symlink_to(backing)
    else:
        os.link(backing, target)
    with pytest.raises(verifier.VerificationError):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


@pytest.mark.parametrize("invalid", [b'{"status":"PASS","status":"PASS"}\n', b'{"status":NaN}\n'])
def test_duplicate_and_nonfinite_receipt_json_are_rejected(layout: dict[str, object], invalid: bytes) -> None:
    Path(layout["receipt"]).write_bytes(invalid)
    with pytest.raises(verifier.VerificationError):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


@pytest.mark.parametrize("literal", [b"1e999", b"-1e999"])
def test_overflowing_receipt_float_is_rejected_globally(layout: dict[str, object], literal: bytes) -> None:
    raw = Path(layout["receipt"]).read_bytes().replace(b'"installed":3', b'"installed":' + literal)
    Path(layout["receipt"]).write_bytes(raw)
    with pytest.raises(verifier.VerificationError, match="non-finite JSON float"):
        _run(layout)


@pytest.mark.parametrize("literal", [b"1e999", b"-1e999"])
def test_overflowing_group_metadata_float_is_rejected(layout: dict[str, object], literal: bytes) -> None:
    path = Path(layout["data"]) / "train/44b6_fixture1.zarr/zarr.json"
    raw = path.read_bytes().replace(b'"0.0":0.0', b'"0.0":' + literal)
    path.write_bytes(raw)
    layout["profile"] = _refresh_manifest(Path(layout["data"]), layout["profile"])
    with pytest.raises(verifier.VerificationError, match="non-finite JSON float"):
        _run(layout)


def test_lock_contention_is_fail_closed(layout: dict[str, object]) -> None:
    with (Path(layout["data"]) / ".download_data.lock").open("rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(verifier.VerificationError, match="lock is held"):
            _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


@pytest.mark.parametrize("field", ["status", "count", "hash", "data_identity", "archive"])
def test_import_receipt_drift_is_rejected(layout: dict[str, object], field: str) -> None:
    value = layout["receipt_value"]
    if field == "status":
        value["status"] = "FAIL"
    elif field == "count":
        value["installed"] += 1
    elif field == "hash":
        value["files"][0]["sha256"] = "0" * 64
    elif field == "data_identity":
        value["data_root_identity"]["inode"] += 1
    else:
        value["archives"][0]["bytes"] += 1
    Path(layout["receipt"]).write_bytes(verifier.canonical_json(value))
    with pytest.raises(verifier.VerificationError, match="import receipt"):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


def test_import_receipt_must_be_canonical(layout: dict[str, object]) -> None:
    value = layout["receipt_value"]
    Path(layout["receipt"]).write_text(json.dumps(value, indent=2) + "\n")
    with pytest.raises(verifier.VerificationError, match="not canonical"):
        _run(layout)


def test_import_receipt_filename_must_embed_content_hash(layout: dict[str, object]) -> None:
    wrong = Path(layout["receipt"]).with_name(f"eval36-import-{'0' * 64}.json")
    Path(layout["receipt"]).rename(wrong)
    layout["receipt"] = wrong
    with pytest.raises(verifier.VerificationError, match="filename/content"):
        _run(layout)


def test_each_image_file_is_read_once(layout: dict[str, object], monkeypatch) -> None:
    original = verifier._read_data_file
    counts: dict[str, int] = {}

    def counted(data_fd: int, relative: str):
        counts[relative] = counts.get(relative, 0) + 1
        return original(data_fd, relative)

    monkeypatch.setattr(verifier, "_read_data_file", counted)
    _run(layout)
    assert counts["manifest.csv"] == 1
    image_counts = {path: count for path, count in counts.items() if path != "manifest.csv"}
    assert len(image_counts) == 8
    assert set(image_counts.values()) == {1}


def test_same_size_mutation_is_caught_by_identity_restat(layout: dict[str, object], monkeypatch) -> None:
    original = verifier._stat_data_file
    target = "train/44b6_fixture1.zarr/0/c/0/0/0/0"
    attacked = False

    def mutate_then_stat(data_fd: int, relative: str):
        nonlocal attacked
        if relative == target and not attacked:
            attacked = True
            path = Path(layout["data"]) / relative
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            assert path.stat().st_size == len(raw)
        return original(data_fd, relative)

    monkeypatch.setattr(verifier, "_stat_data_file", mutate_then_stat)
    with pytest.raises(verifier.VerificationError, match="identity changed"):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_late_extra_zarr_symlink_or_special_is_rejected(layout: dict[str, object], monkeypatch, kind: str) -> None:
    original = verifier._assert_exact_tree
    calls = 0

    def inject(data_fd: int, expected: dict[str, int], profile: verifier.Profile) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            late = Path(layout["data"]) / "train/late.zarr"
            if kind == "symlink":
                late.symlink_to(Path(layout["data"]) / "train/44b6_fixture1.zarr", target_is_directory=True)
            else:
                os.mkfifo(late)
        return original(data_fd, expected, profile)

    monkeypatch.setattr(verifier, "_assert_exact_tree", inject)
    with pytest.raises(verifier.VerificationError, match="symlink or special"):
        _run(layout)
    assert calls == 2
    assert not (Path(layout["output"]) / "READY.json").exists()


def test_nonempty_and_symlink_output_are_rejected(layout: dict[str, object], tmp_path: Path) -> None:
    (Path(layout["output"]) / "occupied").touch()
    with pytest.raises(verifier.VerificationError, match="empty"):
        _run(layout)
    real = tmp_path / "real-output"
    real.mkdir()
    link = tmp_path / "linked-output"
    link.symlink_to(real, target_is_directory=True)
    layout["output"] = link
    with pytest.raises((verifier.VerificationError, OSError)):
        _run(layout)
    assert not (real / "READY.json").exists()


def test_mid_verification_failure_leaves_no_outputs(layout: dict[str, object]) -> None:
    calls = 0

    def failing(raw: bytes) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("injected decode failure")
        return bytes(blosc2.decompress(raw))

    with pytest.raises(verifier.VerificationError, match="decode failed"):
        _run(layout, decoder=failing)
    assert list(Path(layout["output"]).iterdir()) == []


def test_publication_collision_never_overwrites_and_ready_is_last(layout: dict[str, object], monkeypatch) -> None:
    original = verifier.rename_noreplace
    calls = 0

    def collide(source: str, destination: str, *, directory_fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise verifier.VerificationError("publication collision: READY.json")
        original(source, destination, directory_fd=directory_fd)

    monkeypatch.setattr(verifier, "rename_noreplace", collide)
    with pytest.raises(verifier.VerificationError, match="collision"):
        _run(layout)
    assert not (Path(layout["output"]) / "IMAGE_CONTENT_INVENTORY.json").exists()
    assert not (Path(layout["output"]) / "READY.json").exists()
    assert not list(Path(layout["output"]).glob("*.tmp"))


@pytest.mark.parametrize("rename_number", [1, 2])
def test_each_publication_rename_failure_rolls_back_durably(
    layout: dict[str, object], monkeypatch, rename_number: int
) -> None:
    original = verifier.rename_noreplace
    calls = 0

    def fail_selected(source: str, destination: str, *, directory_fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == rename_number:
            raise OSError("injected rename failure")
        original(source, destination, directory_fd=directory_fd)

    monkeypatch.setattr(verifier, "rename_noreplace", fail_selected)
    with pytest.raises(OSError, match="injected rename"):
        _run(layout)
    assert list(Path(layout["output"]).iterdir()) == []


@pytest.mark.parametrize("file_fsync_number", [1, 2])
def test_each_temp_file_fsync_failure_rolls_back_durably(
    layout: dict[str, object], monkeypatch, file_fsync_number: int
) -> None:
    original = os.fsync
    calls = 0

    def fail_selected(fd: int) -> None:
        nonlocal calls
        if stat.S_ISREG(os.fstat(fd).st_mode):
            calls += 1
            if calls == file_fsync_number:
                raise OSError("injected file fsync failure")
        original(fd)

    monkeypatch.setattr(verifier.os, "fsync", fail_selected)
    with pytest.raises(OSError, match="file fsync"):
        _run(layout)
    assert list(Path(layout["output"]).iterdir()) == []


@pytest.mark.parametrize("directory_fsync_number", [1, 2])
def test_each_publication_directory_fsync_failure_rolls_back_durably(
    layout: dict[str, object], monkeypatch, directory_fsync_number: int
) -> None:
    original = os.fsync
    calls = 0

    def fail_selected(fd: int) -> None:
        nonlocal calls
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            calls += 1
            if calls == directory_fsync_number:
                raise OSError("injected publication directory fsync failure")
        original(fd)

    monkeypatch.setattr(verifier.os, "fsync", fail_selected)
    with pytest.raises(OSError, match="publication directory fsync"):
        _run(layout)
    assert list(Path(layout["output"]).iterdir()) == []


@pytest.mark.parametrize("target", ["inventory", "ready"])
def test_final_precommit_reread_failure_rolls_back(layout: dict[str, object], monkeypatch, target: str) -> None:
    original = verifier._read_named_file
    ready_reads = 0

    def fail_final(parent_fd: int, name: str, logical: str):
        nonlocal ready_reads
        if name.startswith(".READY.json"):
            ready_reads += 1
        if (target == "inventory" and logical == "IMAGE_CONTENT_INVENTORY.json") or (
            target == "ready" and name.startswith(".READY.json") and ready_reads == 2
        ):
            raise OSError("injected final reread failure")
        return original(parent_fd, name, logical)

    monkeypatch.setattr(verifier, "_read_named_file", fail_final)
    with pytest.raises(OSError, match="final reread"):
        _run(layout)
    assert list(Path(layout["output"]).iterdir()) == []


def test_rollback_unlink_failure_is_explicitly_ambiguous(layout: dict[str, object], monkeypatch) -> None:
    monkeypatch.setattr(
        verifier,
        "rename_noreplace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("trigger rollback")),
    )
    monkeypatch.setattr(
        verifier.os,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected unlink failure")),
    )
    with pytest.raises(verifier.PublicationAmbiguityError, match="unlink"):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


def test_rollback_directory_fsync_failure_is_explicitly_ambiguous(layout: dict[str, object], monkeypatch) -> None:
    original = os.fsync

    monkeypatch.setattr(
        verifier,
        "rename_noreplace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("trigger rollback")),
    )

    def fail_directory(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected rollback fsync failure")
        original(fd)

    monkeypatch.setattr(verifier.os, "fsync", fail_directory)
    with pytest.raises(verifier.PublicationAmbiguityError, match="rollback directory fsync"):
        _run(layout)
    assert not (Path(layout["output"]) / "READY.json").exists()


def test_ready_rename_and_directory_fsync_are_final_commit_point(layout: dict[str, object], monkeypatch) -> None:
    events: list[str] = []
    original_rename = verifier.rename_noreplace
    original_fsync = os.fsync
    original_read = verifier._read_named_file

    def record_rename(source: str, destination: str, *, directory_fd: int) -> None:
        events.append(f"rename:{destination}")
        original_rename(source, destination, directory_fd=directory_fd)

    def record_fsync(fd: int) -> None:
        events.append("fsync:dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync:file")
        original_fsync(fd)

    def record_read(parent_fd: int, name: str, logical: str):
        events.append(f"read:{logical}")
        return original_read(parent_fd, name, logical)

    monkeypatch.setattr(verifier, "rename_noreplace", record_rename)
    monkeypatch.setattr(verifier.os, "fsync", record_fsync)
    monkeypatch.setattr(verifier, "_read_named_file", record_read)
    _run(layout)
    commit_index = events.index("rename:READY.json")
    assert events[commit_index:] == ["rename:READY.json", "fsync:dir"]


def test_cli_requires_all_three_explicit_paths() -> None:
    with pytest.raises(verifier.VerificationError, match="invalid arguments"):
        verifier._parser().parse_args([])
