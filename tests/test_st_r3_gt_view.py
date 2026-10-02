from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

import biohub.st_r3_gt_view as gt


def _write_json(path: Path, value: object) -> bytes:
    raw = gt.canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def test_frozen_eval36_shape_is_exact() -> None:
    records = gt._expected_records(gt.PRODUCTION_AUTHORITY)
    assert len(gt.EVAL36) == 36
    assert len(gt.GEFF_SUFFIXES) == 21
    assert gt.ZARR_SUFFIXES == ("0/zarr.json", "zarr.json")
    assert len(records) == 828
    assert len({path.split("/", 1)[0] for path, _ in records}) == 72
    assert records == tuple(sorted(records, key=lambda pair: pair[0].encode()))


def test_expected_records_never_select_extra_geff_roots() -> None:
    paths = {path for path, _ in gt._expected_records(gt.PRODUCTION_AUTHORITY)}
    for extra in ("44b6_0113de3b", "44b6_0b24845f", "6bba_05b6850b", "6bba_05db0fb1", "6bba_c328f2fd"):
        assert not any(path.startswith(extra) for path in paths)


@pytest.mark.parametrize("value", ["", "../x", "x/y", "x\\y", "x\n", ".hidden", "x" * 129])
def test_run_id_is_one_safe_direct_component(value: str) -> None:
    with pytest.raises(gt.GTViewError):
        gt._require_run_id(value)


def test_import_inventory_is_exact_scorer_schema() -> None:
    records = [{"path": "aa.geff/zarr.json", "bytes": 3, "sha256": "1" * 64}]
    value = gt._inventory(records, ("aa",), "inputs/gt/GT_VIEW", gt.IMPORT_INVENTORY_SCHEMA)
    assert set(value) == {"schema_version", "stems", "records"}
    assert value["records"] == [{"path": "inputs/gt/GT_VIEW/aa.geff/zarr.json", "bytes": 3, "sha256": "1" * 64}]


def test_standalone_inventory_has_fixed_path_basis_and_digest() -> None:
    records = [{"path": "aa.zarr/zarr.json", "bytes": 0, "sha256": "2" * 64}]
    value = gt._inventory(records, ("aa",), "GT_VIEW", gt.INVENTORY_SCHEMA)
    assert value["path_basis"] == "standalone_root_relative"
    assert value["files"][0]["path"] == "GT_VIEW/aa.zarr/zarr.json"
    assert value["summary"]["records_sha256"] == gt._sha(gt.canonical_json_bytes(value["files"]))


def test_generation_held_and_hash_chain_are_rejected(tmp_path: Path) -> None:
    run = tmp_path / "run1"
    prereg = {"inputs": {}}
    prereg_raw = _write_json(run / "PREREGISTRATION.json", prereg)
    manifest = {
        "schema_version": gt.GENERATION_SCHEMA,
        "state": "GENERATION_HELD",
        "run_id": "run1",
        "preregistration_sha256": gt._sha(prereg_raw),
    }
    manifest_raw = _write_json(run / "generation/ARTIFACT_MANIFEST.json", manifest)
    fd = os.open(run, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(gt.GTViewError, match="not sealed"):
            gt._load_generation(fd, gt._sha(prereg_raw), gt._sha(manifest_raw))
        with pytest.raises(gt.GTViewError, match="preregistration hash"):
            gt._load_generation(fd, "0" * 64, gt._sha(manifest_raw))
    finally:
        os.close(fd)


def test_generation_sealed_exact_chain_passes(tmp_path: Path) -> None:
    run = tmp_path / "run2"
    prereg_raw = _write_json(run / "PREREGISTRATION.json", {"inputs": {}})
    manifest_raw = _write_json(
        run / "generation/ARTIFACT_MANIFEST.json",
        {
            "schema_version": gt.GENERATION_SCHEMA,
            "state": "GENERATION_SEALED",
            "run_id": "run2",
            "preregistration_sha256": gt._sha(prereg_raw),
        },
    )
    fd = os.open(run, os.O_RDONLY | os.O_DIRECTORY)
    try:
        manifest, observed_raw, prereg = gt._load_generation(fd, gt._sha(prereg_raw), gt._sha(manifest_raw))
    finally:
        os.close(fd)
    assert manifest["state"] == "GENERATION_SEALED"
    assert observed_raw == manifest_raw
    assert prereg == {"inputs": {}}


def test_opaque_inventory_normalizes_only_suffix_after_fixed_root(tmp_path: Path) -> None:
    authority = gt.Authority(root=tmp_path, stems=("aa",), geff_suffixes=("zarr.json",), zarr_suffixes=())
    expected = gt._expected_records(authority)
    value = {
        "schema_version": gt.IMPORT_INVENTORY_SCHEMA,
        "stems": ["aa"],
        "records": [{"path": "authority/prefix/aa.geff/zarr.json", "bytes": 4, "sha256": "3" * 64}],
    }
    raw = _write_json(tmp_path / "inventory.json", value)
    prereg = {
        "inputs": {
            "opaque_gt_inventory": {
                "path": "inventory.json",
                "bytes": len(raw),
                "sha256": gt._sha(raw),
                "verdict": "SCHEMA_AND_MEMBERSHIP_VERIFIED_WITHOUT_GT_READ",
            }
        }
    }
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        records, digest = gt._opaque_inventory_records(fd, prereg, expected, authority.stems)
    finally:
        os.close(fd)
    assert records == [{"path": "aa.geff/zarr.json", "bytes": 4, "sha256": "3" * 64}]
    assert digest == gt._sha(raw)


def test_cli_has_closed_fixed_argument_surface() -> None:
    path = Path(__file__).parents[1] / "scripts/experiments/st_r3/st_r3_gt_view.py"
    spec = importlib.util.spec_from_file_location("st_r3_gt_view_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module._parser()
    with pytest.raises(gt.GTViewError):
        parser.parse_args(["build", "--source", "/tmp/x"])
    args = parser.parse_args(
        [
            "import",
            "--run-id",
            "r1",
            "--generation-manifest-sha256",
            "0" * 64,
            "--source-receipt-sha256",
            "1" * 64,
        ]
    )
    assert set(vars(args)) == {
        "command",
        "run_id",
        "generation_manifest_sha256",
        "source_receipt_sha256",
    }


@pytest.mark.skipif(sys.platform != "darwin", reason="APFS clones require macOS")
def test_real_apfs_clone_isolated_inode_and_bidirectional_cow(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination_dir = tmp_path / "out"
    destination_dir.mkdir()
    source.write_bytes(b"abcdef")
    source_fd = os.open(source, os.O_RDONLY)
    destination_fd = os.open(destination_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if gt._sealed._filesystem_type(tmp_path, destination_fd) != "apfs":
            pytest.skip("APFS required")
        gt._sealed._clone_file(source_fd, destination_fd, "clone.bin")
    finally:
        os.close(destination_fd)
        os.close(source_fd)
    clone = destination_dir / "clone.bin"
    assert source.stat().st_ino != clone.stat().st_ino
    assert source.stat().st_nlink == clone.stat().st_nlink == 1
    clone.write_bytes(b"ABCDEF")
    assert source.read_bytes() == b"abcdef"
    source.write_bytes(b"123456")
    assert clone.read_bytes() == b"ABCDEF"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_open_regular_refuses_links_and_fifo_without_blocking(tmp_path: Path, kind: str) -> None:
    ordinary = tmp_path / "ordinary"
    ordinary.write_bytes(b"x")
    unsafe = tmp_path / "unsafe"
    if kind == "symlink":
        unsafe.symlink_to(ordinary.name)
    elif kind == "hardlink":
        os.link(ordinary, unsafe)
    else:
        os.mkfifo(unsafe)
        assert stat.S_ISFIFO(unsafe.lstat().st_mode)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises((OSError, gt._sealed.ImageViewError)):
            gt._sealed._open_relative_regular(root_fd, "unsafe")
    finally:
        os.close(root_fd)


@pytest.mark.skipif(sys.platform != "darwin", reason="APFS clones require macOS")
def test_build_verify_import_end_to_end_on_synthetic_apfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if gt._sealed._filesystem_type(tmp_path, probe_fd) != "apfs":
            pytest.skip("APFS required")
    finally:
        os.close(probe_fd)
    authority = gt.Authority(
        root=tmp_path,
        stems=("aa",),
        geff_suffixes=("zarr.json",),
        zarr_suffixes=("0/zarr.json", "zarr.json"),
        builder_sources=(),
        official_oid="4" * 40,
    )
    expected = gt._expected_records(authority)
    source_records = []
    for index, (relative, _source) in enumerate(expected):
        raw = f"opaque-{index}".encode()
        path = tmp_path / "data/train" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        source_records.append({"path": f"sealed-authority/{relative}", "bytes": len(raw), "sha256": gt._sha(raw)})
    (tmp_path / "data/train/extra.geff").mkdir()
    (tmp_path / "data/train/extra.geff/secret").write_bytes(b"ignored")
    opaque_raw = _write_json(
        tmp_path / "authority/GT_INVENTORY.json",
        {"schema_version": gt.IMPORT_INVENTORY_SCHEMA, "stems": ["aa"], "records": source_records},
    )
    run = tmp_path / "outputs/local/steal_twin/run1"
    (run / "inputs").mkdir(parents=True)
    prereg_raw = _write_json(
        run / "PREREGISTRATION.json",
        {
            "inputs": {
                "opaque_gt_inventory": {
                    "path": "authority/GT_INVENTORY.json",
                    "bytes": len(opaque_raw),
                    "sha256": gt._sha(opaque_raw),
                    "verdict": "SCHEMA_AND_MEMBERSHIP_VERIFIED_WITHOUT_GT_READ",
                }
            }
        },
    )
    generation_raw = _write_json(
        run / "generation/ARTIFACT_MANIFEST.json",
        {
            "schema_version": gt.GENERATION_SCHEMA,
            "state": "GENERATION_SEALED",
            "run_id": "run1",
            "preregistration_sha256": gt._sha(prereg_raw),
            "datasets": {"eval36": ["aa"]},
        },
    )

    def fake_checkout(_authority: gt.Authority):
        root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        git_fd = os.dup(root_fd)
        official_fd = os.dup(root_fd)
        root_identity = gt._sealed._directory_handle_identity(os.fstat(root_fd))
        guard = gt._sealed.CheckoutGuard(
            root_fd,
            git_fd,
            official_fd,
            root_identity,
            gt._sealed._directory_handle_identity(os.fstat(git_fd)),
            gt._sealed._directory_handle_identity(os.fstat(official_fd)),
        )
        return guard, gt._sealed.GitState("1" * 40, "2" * 40, "4" * 40), ()

    monkeypatch.setattr(gt, "PRODUCTION_AUTHORITY", authority)
    monkeypatch.setattr(gt, "_checkout", fake_checkout)
    monkeypatch.setattr(gt, "_rebind", lambda _authority, _guard: None)
    monkeypatch.setattr(gt, "_audit_inherited_fds", lambda: None)
    built = gt.build_gt_view("run1", gt._sha(prereg_raw), gt._sha(generation_raw))
    assert built.status == "GT_VIEW_SEALED" and built.files == 3
    verified = gt.verify_gt_view("run1", built.receipt_sha256)
    assert verified.status == "GT_VIEW_VERIFIED" and verified.files == 3
    imported = gt.import_gt_view("run1", gt._sha(generation_raw), built.receipt_sha256)
    assert imported.status == "GT_VIEW_IMPORTED" and imported.files == 3
    inventory = gt._strict_json((run / "inputs/gt/GT_CONTENT_INVENTORY.json").read_bytes(), "test")
    assert set(inventory) == {"schema_version", "stems", "records"}
    assert all(record["path"].startswith("inputs/gt/GT_VIEW/") for record in inventory["records"])
