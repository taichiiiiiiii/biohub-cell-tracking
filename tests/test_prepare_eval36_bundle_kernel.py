from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from scripts import prepare_eval36_bundle_kernel as prepare

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKER_RAW = (REPO_ROOT / prepare.PACKER_RELATIVE).read_bytes()
MANIFEST_RAW = (REPO_ROOT / prepare.MANIFEST_RELATIVE).read_bytes()


def _source() -> bytes:
    return prepare.build_kernel_source(PACKER_RAW, MANIFEST_RAW)


def _load_generated(source: bytes | None = None) -> dict[str, object]:
    namespace: dict[str, object] = {
        "__file__": "eval36_bundle_kernel.py",
        "__name__": "eval36_bundle_kernel_test",
    }
    exec(compile(source or _source(), prepare.KERNEL_CODE_NAME, "exec"), namespace)
    return namespace


def _reseal(source: bytes) -> bytes:
    normalized, _ = prepare.normalize_kernel_source(source)
    digest = hashlib.sha256(normalized).hexdigest().encode("ascii")
    match = prepare._SELF_PATTERN.search(source)
    assert match is not None
    return source[: match.start(1)] + digest + source[match.end(1) :]


def _fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "data").mkdir()
    (repo / "outputs/local").mkdir(parents=True)
    (repo / prepare.PACKER_RELATIVE).write_bytes(PACKER_RAW)
    (repo / prepare.MANIFEST_RELATIVE).write_bytes(MANIFEST_RAW)
    return repo


def _stage(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    repo = _fixture_repo(tmp_path)
    output = repo / "outputs/local/eval36_kernel/run-1"
    receipt = prepare.stage_package(
        output,
        repo_root=repo,
        git_head="a" * 40,
        git_branch="feat/test",
        versions={"kaggle": prepare.KAGGLE_VERSION, "kagglesdk": prepare.KAGGLESDK_VERSION},
    )
    return output, receipt


def test_production_inputs_and_compression_are_exact() -> None:
    assert len(PACKER_RAW) == prepare.PACKER_BYTES
    assert hashlib.sha256(PACKER_RAW).hexdigest() == prepare.PACKER_SHA256
    assert len(MANIFEST_RAW) == prepare.MANIFEST_BYTES
    assert hashlib.sha256(MANIFEST_RAW).hexdigest() == prepare.MANIFEST_SHA256
    prepare.verify_manifest_bytes(MANIFEST_RAW)
    assert MANIFEST_RAW.count(b"\r\n") == prepare.MANIFEST_LINES
    assert MANIFEST_RAW.count(b"\r") == prepare.MANIFEST_LINES
    assert MANIFEST_RAW.count(b"\n") == prepare.MANIFEST_LINES


def test_generated_source_round_trips_exact_embedded_bytes() -> None:
    source = _source()
    hashes = prepare.verify_kernel_source(source)
    assert len(hashes["raw_sha256"]) == 64
    assert len(hashes["self_sha256"]) == 64
    namespace = _load_generated(source)
    try:
        packer, manifest = namespace["_load_inputs"]()
        assert manifest == MANIFEST_RAW
        assert packer.MANIFEST_SHA256 == prepare.MANIFEST_SHA256
        assert packer.ROOTS == prepare.ROOTS
        assert sum(packer.PRODUCTION_ARCHIVE_BYTES.values()) == prepare.TOTAL_ARCHIVE_BYTES
    finally:
        sys.modules.pop("embedded_eval36_packer", None)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda source: b"\xef\xbb\xbf" + source,
        lambda source: source.replace(b"\n", b"\r\n"),
        lambda source: source + b"# appended\n",
        lambda source: source.replace(b"SELF_SHA256 = ", b"SELF_SHA256_2 = ", 1),
        lambda source: source.replace(
            b'SELF_SHA256 = "',
            b'SELF_SHA256 = "' + (b"0" * 64) + b'"\nSELF_SHA256 = "',
            1,
        ),
    ],
)
def test_generated_source_rejects_wrapper_byte_drift(mutator) -> None:
    with pytest.raises(prepare.KernelPreparationError):
        prepare.verify_kernel_source(mutator(_source()))


def test_resealed_embedded_payload_tamper_is_still_rejected() -> None:
    source = _source()
    marker = b'PACKER_B64 = (\n    "'
    index = source.index(marker) + len(marker)
    replacement = b"A" if source[index : index + 1] != b"A" else b"B"
    tampered = _reseal(source[:index] + replacement + source[index + 1 :])
    prepare.verify_kernel_source(tampered)
    namespace = _load_generated(tampered)
    with pytest.raises(namespace["KernelFailure"]):
        namespace["_load_inputs"]()


def test_metadata_is_exact_private_cpu_closed_schema() -> None:
    assert prepare.kernel_metadata() == {
        "id": "taichiiiii/biohub-eval36-bundle-packer",
        "title": "biohub-eval36-bundle-packer",
        "code_file": "eval36_bundle_kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "false",
        "enable_tpu": "false",
        "enable_internet": "false",
        "dataset_sources": [],
        "competition_sources": [prepare.COMPETITION],
        "kernel_sources": [],
        "model_sources": [],
    }
    assert "machine_shape" not in prepare.kernel_metadata()


def test_stage_is_fresh_canonical_and_binds_two_file_package(tmp_path: Path) -> None:
    output, receipt = _stage(tmp_path)
    package = output / "package"
    assert {item.name for item in package.iterdir()} == {prepare.KERNEL_CODE_NAME, prepare.METADATA_NAME}
    assert not (output / "INCOMPLETE").exists()
    assert (output / "READY.json").is_file()
    assert receipt["status"] == "STAGED_READY_FOR_PRIVATE_CPU_REVIEW"
    assert receipt["allowed_next_action"] == "PRIVATE_CPU_PUSH_AFTER_INDEPENDENT_HASH_REVIEW"
    code = (package / prepare.KERNEL_CODE_NAME).read_bytes()
    metadata = (package / prepare.METADATA_NAME).read_bytes()
    assert receipt["package"][prepare.KERNEL_CODE_NAME]["raw_sha256"] == hashlib.sha256(code).hexdigest()
    assert receipt["package"][prepare.METADATA_NAME]["sha256"] == hashlib.sha256(metadata).hexdigest()
    assert json.loads(metadata) == prepare.kernel_metadata()
    ready = json.loads((output / "READY.json").read_bytes())
    receipt_raw = (output / "STAGING_RECEIPT.json").read_bytes()
    assert ready["receipt_sha256"] == hashlib.sha256(receipt_raw).hexdigest()
    assert receipt_raw == prepare.canonical_json_bytes(json.loads(receipt_raw))
    assert (output / "READY.json").read_bytes() == prepare.canonical_json_bytes(ready)
    with pytest.raises(prepare.KernelPreparationError, match="reuse"):
        prepare.stage_package(
            output,
            repo_root=output.parents[3],
            git_head="a" * 40,
            git_branch="feat/test",
            versions={"kaggle": prepare.KAGGLE_VERSION, "kagglesdk": prepare.KAGGLESDK_VERSION},
        )


def test_stage_rejects_outside_and_symlink_or_hardlink_input(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    injected = {
        "git_head": "a" * 40,
        "git_branch": "feat/test",
        "versions": {"kaggle": prepare.KAGGLE_VERSION, "kagglesdk": prepare.KAGGLESDK_VERSION},
    }
    with pytest.raises(prepare.KernelPreparationError, match="child"):
        prepare.stage_package(tmp_path / "outside", repo_root=repo, **injected)

    packer = repo / prepare.PACKER_RELATIVE
    outside = tmp_path / "packer"
    outside.write_bytes(packer.read_bytes())
    packer.unlink()
    packer.symlink_to(outside)
    with pytest.raises(prepare.KernelPreparationError, match="input"):
        prepare.stage_package(repo / "outputs/local/eval36_kernel/symlink", repo_root=repo, **injected)

    packer.unlink()
    os.link(outside, packer)
    with pytest.raises(prepare.KernelPreparationError, match="input"):
        prepare.stage_package(repo / "outputs/local/eval36_kernel/hardlink", repo_root=repo, **injected)


@pytest.mark.parametrize("target", [prepare.METADATA_NAME, "STAGING_RECEIPT.json"])
def test_stage_rejects_package_or_receipt_replacement(tmp_path: Path, monkeypatch, target: str) -> None:
    repo = _fixture_repo(tmp_path)
    output = repo / "outputs/local/eval36_kernel/replaced"
    outside = tmp_path / "outside"
    original_write = prepare._write_exclusive_at

    def write_then_replace(directory_fd: int, name: str, payload: bytes) -> None:
        original_write(directory_fd, name, payload)
        if name == target:
            outside.write_bytes(payload)
            os.unlink(name, dir_fd=directory_fd)
            os.symlink(outside, name, dir_fd=directory_fd)

    monkeypatch.setattr(prepare, "_write_exclusive_at", write_then_replace)
    with pytest.raises(prepare.KernelPreparationError, match="staged file"):
        prepare.stage_package(
            output,
            repo_root=repo,
            git_head="a" * 40,
            git_branch="feat/test",
            versions={"kaggle": prepare.KAGGLE_VERSION, "kagglesdk": prepare.KAGGLESDK_VERSION},
        )
    assert not (output / "READY.json").exists()
    assert (output / "INCOMPLETE").is_file()


def test_stage_rejects_output_membership_replacement(tmp_path: Path, monkeypatch) -> None:
    repo = _fixture_repo(tmp_path)
    output = repo / "outputs/local/eval36_kernel/path-swap"
    displaced = output.parent / "displaced"
    original_read = prepare._read_stable_at
    swapped = False

    def read_then_swap(directory_fd: int, name: str, expected: bytes) -> bytes:
        nonlocal swapped
        payload = original_read(directory_fd, name, expected)
        if name == "STAGING_RECEIPT.json" and not swapped:
            swapped = True
            output.rename(displaced)
            output.mkdir()
        return payload

    monkeypatch.setattr(prepare, "_read_stable_at", read_then_swap)
    with pytest.raises(prepare.KernelPreparationError, match="membership"):
        prepare.stage_package(
            output,
            repo_root=repo,
            git_head="a" * 40,
            git_branch="feat/test",
            versions={"kaggle": prepare.KAGGLE_VERSION, "kagglesdk": prepare.KAGGLESDK_VERSION},
        )
    assert not (output / "READY.json").exists()
    assert not (displaced / "READY.json").exists()


def test_stage_ready_rename_failure_leaves_no_ready(tmp_path: Path, monkeypatch) -> None:
    repo = _fixture_repo(tmp_path)
    output = repo / "outputs/local/eval36_kernel/rename-failure"

    def fail_rename(_directory_fd: int, _source: str, _destination: str) -> None:
        raise prepare.KernelPreparationError("injected publication failure")

    monkeypatch.setattr(prepare, "_rename_noreplace_at", fail_rename)
    with pytest.raises(prepare.KernelPreparationError, match="injected"):
        prepare.stage_package(
            output,
            repo_root=repo,
            git_head="a" * 40,
            git_branch="feat/test",
            versions={"kaggle": prepare.KAGGLE_VERSION, "kagglesdk": prepare.KAGGLESDK_VERSION},
        )
    assert not (output / "READY.json").exists()
    assert (output / ".READY.pending").is_file()


def test_generated_kernel_rejects_argv_without_leaking_it(tmp_path: Path) -> None:
    script = tmp_path / prepare.KERNEL_CODE_NAME
    script.write_bytes(_source())
    secret = "TOP-SECRET-VALUE"
    result = subprocess.run([sys.executable, script, secret], check=False, capture_output=True)
    assert result.returncode == 1
    assert result.stdout == b""
    assert secret.encode() not in result.stderr
    assert str(script).encode() not in result.stderr
    assert result.stderr == b'{"failure_class":"ARGUMENTS","status":"FAIL"}\n'
    assert result.stderr.count(b"\n") == 1
    assert len(result.stderr) < 128


def test_generated_kernel_has_fixed_paths_and_no_override_parser() -> None:
    source = _source().decode("utf-8")
    assert 'SOURCE_ROOT = Path("/kaggle/input/competitions/biohub-cell-tracking-during-development")' in source
    assert 'OUTPUT_ROOT = Path("/kaggle/working/eval36-bundles")' in source
    assert "argparse" not in source
    assert "rglob(" not in source
    assert "glob(" not in source
    assert "len(sys.argv) != 1" in source


def test_generated_output_seal_rejects_extra_and_bool_size(tmp_path: Path) -> None:
    namespace = _load_generated()
    namespace["ROOTS"] = ("a", "b")
    namespace["ARCHIVE_BYTES"] = (3, 4)
    namespace["TOTAL_ARCHIVE_BYTES"] = 7
    (tmp_path / "a.tar").write_bytes(b"aaa")
    (tmp_path / "b.tar").write_bytes(b"bbbb")
    directory_fd = os.open(tmp_path, os.O_RDONLY)
    try:
        identity = namespace["_directory_identity"](os.fstat(directory_fd))
        results = [
            {
                "archive": "a.tar",
                "bytes": 3,
                "root": "a",
                "sha256": hashlib.sha256(b"aaa").hexdigest(),
            },
            {
                "archive": "b.tar",
                "bytes": 4,
                "root": "b",
                "sha256": hashlib.sha256(b"bbbb").hexdigest(),
            },
        ]
        sealed = namespace["_validate_results"](results, directory_fd, identity)
        assert sealed == results
        results[0]["bytes"] = True
        with pytest.raises(namespace["KernelFailure"]):
            namespace["_validate_results"](results, directory_fd, identity)
        results[0]["bytes"] = 3
        (tmp_path / "extra.tmp").write_bytes(b"")
        with pytest.raises(namespace["KernelFailure"]):
            namespace["_validate_results"](results, directory_fd, identity)
    finally:
        os.close(directory_fd)


def _tiny_generated_run(
    tmp_path: Path,
    monkeypatch,
    *,
    fail_result_rename: bool = False,
    replace_output_path: bool = False,
) -> tuple[dict[str, object], Path]:
    namespace = _load_generated()
    source_root = tmp_path / "source"
    working_root = tmp_path / "working"
    runtime_parent = tmp_path / "runtime-parent"
    source_root.mkdir()
    working_root.mkdir()
    runtime_parent.mkdir()
    namespace["SOURCE_ROOT"] = source_root
    namespace["WORKING_ROOT"] = working_root
    namespace["RUNTIME_ROOT"] = Path("/tmp/tiny-runtime")
    namespace["OUTPUT_ROOT"] = working_root / "tiny-output"
    namespace["ROOTS"] = ("a", "b")
    namespace["ARCHIVE_BYTES"] = (3, 4)
    namespace["TOTAL_ARCHIVE_BYTES"] = 7
    namespace["MIN_FREE_BYTES"] = 0
    namespace["PACKER_BYTES"] = 1
    namespace["PACKER_SHA256"] = "1" * 64
    namespace["MANIFEST_BYTES"] = 2
    namespace["MANIFEST_LINES"] = 1
    namespace["MANIFEST_SHA256"] = "2" * 64

    class FakePacker:
        @staticmethod
        def pack_bundles(_manifest: Path, seen_source: Path, output: Path):
            assert seen_source == source_root
            payloads = {"a": b"aaa", "b": b"bbbb"}
            results = []
            for root, payload in payloads.items():
                (output / f"{root}.tar").write_bytes(payload)
                results.append(
                    {
                        "archive": f"{root}.tar",
                        "bytes": len(payload),
                        "root": root,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
            return results

        @staticmethod
        def rename_noreplace(source: str, destination: str, *, source_dir_fd: int, destination_dir_fd: int):
            if fail_result_rename:
                raise OSError("injected rename failure")
            os.rename(source, destination, src_dir_fd=source_dir_fd, dst_dir_fd=destination_dir_fd)

    self_fd = os.open(__file__, os.O_RDONLY)
    parent_fd = os.open(Path(__file__).parent, os.O_RDONLY)
    namespace["_open_verified_self"] = lambda: {
        "descriptor": self_fd,
        "parent_fd": parent_fd,
        "name": Path(__file__).name,
        "identity": (),
        "normalized_sha256": "3" * 64,
        "raw_sha256": "4" * 64,
    }
    namespace["_reverify_self"] = lambda _handle: None
    namespace["_load_inputs"] = lambda: (FakePacker(), b"x\n")
    original_create = namespace["_create_fresh_child"]

    def create_fresh(parent: Path, name: str):
        if parent == Path("/tmp"):
            parent = runtime_parent
        return original_create(parent, name)

    namespace["_create_fresh_child"] = create_fresh
    if replace_output_path:
        original_validate = namespace["_validate_results"]

        def validate_then_replace(results, output_fd, output_identity):
            sealed = original_validate(results, output_fd, output_identity)
            output = working_root / "tiny-output"
            output.rename(working_root / "displaced-output")
            output.mkdir()
            return sealed

        namespace["_validate_results"] = validate_then_replace
    monkeypatch.setattr(sys, "argv", [prepare.KERNEL_CODE_NAME])
    return namespace, working_root / "tiny-output"


def test_generated_run_success_writes_result_last(tmp_path: Path, monkeypatch) -> None:
    namespace, output = _tiny_generated_run(tmp_path, monkeypatch)
    receipt_raw = namespace["_run"]()
    receipt = json.loads(receipt_raw)
    assert receipt["status"] == "PASS"
    assert receipt["total_archive_bytes"] == 7
    assert receipt_raw == prepare.canonical_json_bytes(receipt)
    assert (output / "KERNEL_RESULT.json").read_bytes() == receipt_raw
    assert {item.name for item in output.iterdir()} == {"a.tar", "b.tar", "KERNEL_RESULT.json"}


def test_generated_run_rename_failure_leaves_no_pass_result(tmp_path: Path, monkeypatch) -> None:
    namespace, output = _tiny_generated_run(tmp_path, monkeypatch, fail_result_rename=True)
    with pytest.raises(namespace["KernelFailure"], match="PUBLICATION"):
        namespace["_run"]()
    assert not (output / "KERNEL_RESULT.json").exists()
    assert (output / ".KERNEL_RESULT.pending").is_file()


def test_generated_run_rejects_output_path_replacement_before_pass(tmp_path: Path, monkeypatch) -> None:
    namespace, replacement = _tiny_generated_run(tmp_path, monkeypatch, replace_output_path=True)
    with pytest.raises(namespace["KernelFailure"], match="PUBLICATION"):
        namespace["_run"]()
    displaced = replacement.parent / "displaced-output"
    assert not (replacement / "KERNEL_RESULT.json").exists()
    assert not (displaced / "KERNEL_RESULT.json").exists()


def test_kaggle_cli_request_uses_exact_script_and_cpu_metadata(tmp_path: Path, monkeypatch) -> None:
    output, _ = _stage(tmp_path)
    package = output / "package"
    captured: dict[str, object] = {}

    class FakeKernelApi:
        def save_kernel(self, request):
            captured["request"] = request
            return types.SimpleNamespace(error=None)

    class FakeClient:
        kernels = types.SimpleNamespace(kernels_api_client=FakeKernelApi())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    monkeypatch.setattr(api, "build_kaggle_client", lambda: FakeClient())
    api.kernels_push(str(package))
    request = captured["request"]
    script = (package / prepare.KERNEL_CODE_NAME).read_bytes()
    assert request.text.encode("utf-8") == script
    assert request.slug == prepare.KERNEL_ID
    assert request.kernel_type == "script"
    assert request.is_private is True
    assert request.enable_gpu is False
    assert request.enable_tpu is False
    assert request.enable_internet is False
    assert not request.machine_shape
    assert request.competition_data_sources == [prepare.COMPETITION]
    assert request.dataset_data_sources == []
    assert request.kernel_data_sources == []
    assert request.model_data_sources == []
