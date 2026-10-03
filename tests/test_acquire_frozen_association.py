import hashlib
import json

import pytest

from scripts import acquire_frozen_association as acquisition


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    data = root / "data"
    data.mkdir()
    monkeypatch.setattr(acquisition.dd, "ROOT", root)
    monkeypatch.setattr(acquisition.dd, "DATA", data)
    stems = [f"44b6_{index:08d}" for index in range(12)]
    selected = {f"train/{stems[0]}.zarr/0/c/0": 3, f"train/{stems[1]}.geff/zarr.json": 2}
    plan = {"train": stems[:8], "selection": stems[8:], "expected_files": 2, "expected_bytes": 5,
            "path_size_inventory_sha256": hashlib.sha256(
                json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    plan_path = root / acquisition.PLAN_REL
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(json.dumps(plan))
    monkeypatch.setattr(acquisition, "PLAN_SHA", acquisition.sha256_file(plan_path))
    manifest = {**selected, "test/unrelated.zarr/0/c/0": 7, "train/other.zarr/0/c/0": 10}
    monkeypatch.setattr(acquisition.dd, "load_manifest", lambda: manifest)
    prior = root / acquisition.PRIOR_REL
    prior.parent.mkdir(parents=True)
    prior.write_text('{"failure_count":1}')
    return root, data, selected, root / "outputs/local/recovery"


def test_complete_only_selected_files_and_preserve_existing(setup, monkeypatch):
    root, data, selected, receipt = setup
    names = sorted(selected)
    existing = data / names[0]
    existing.parent.mkdir(parents=True)
    calls = []

    def fetch(name, size):
        calls.append(name)
        assert acquisition.dd.MAX_TIMEOUT_ATTEMPTS == 1
        path = data / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x" * size)
        return name, "ok"

    existing.write_bytes(b"x" * selected[names[0]])
    before = existing.stat().st_mtime_ns
    monkeypatch.setattr(acquisition.dd, "fetch", fetch)
    assert acquisition.inventory() == selected
    assert acquisition.recover(receipt) == 0
    assert calls == [names[1]]
    assert existing.stat().st_mtime_ns == before
    completed = json.loads((receipt / "completed.json").read_text())
    files = json.loads((receipt / "files.json").read_text())
    assert completed["files"] == 2 and completed["bytes"] == 5
    assert completed["files_manifest_sha256"] == acquisition.sha256_file(receipt / "files.json")
    assert {entry["path"] for entry in files} == set(selected)
    assert not completed["provider_content_hash_verified"]
    with pytest.raises(FileExistsError):
        acquisition.recover(receipt)


@pytest.mark.parametrize("failure", ["auth", "forbidden", "timeout", "rate-limit", "unknown"])
def test_failure_stops_without_retry_or_secret_output(setup, monkeypatch, capsys, failure):
    root, data, selected, receipt = setup
    calls = []

    def fetch(name, size):
        calls.append(name)
        print("SENSITIVE_SIGNED_URL")
        return name, f"FAIL class={failure} rc=1: SENSITIVE_SIGNED_URL"

    monkeypatch.setattr(acquisition.dd, "fetch", fetch)
    assert acquisition.recover(receipt) == 1
    assert len(calls) == 1
    failed = (receipt / "failed.json").read_text()
    assert json.loads(failed)["failure_class"] == failure
    assert "SENSITIVE" not in failed + capsys.readouterr().out
    assert not (receipt / "completed.json").exists()


def test_inventory_drift_prevents_requests_and_receipts(setup, monkeypatch):
    root, data, selected, receipt = setup
    monkeypatch.setattr(acquisition.dd, "load_manifest", lambda: {})
    monkeypatch.setattr(acquisition.dd, "fetch", lambda *_: pytest.fail("Unexpected request"))
    with pytest.raises(ValueError):
        acquisition.recover(receipt)
    assert not receipt.exists()


def test_symlink_parent_rejected_before_request(setup, monkeypatch):
    root, data, selected, receipt = setup
    outside = root / "outside"
    outside.mkdir()
    (data / "train").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(acquisition.dd, "fetch", lambda *_: pytest.fail("Unexpected request"))
    assert acquisition.recover(receipt) == 1
    assert not (receipt / "completed.json").exists()


def test_similarly_prefixed_receipt_is_rejected(setup):
    root, data, selected, receipt = setup
    with pytest.raises(ValueError):
        acquisition.recover(root / "outputs/local-other/recovery")
