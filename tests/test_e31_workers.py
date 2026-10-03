"""tests/test_e31_workers.py – Issue17 supervisor tests for e31_shards.run_workers."""

import hashlib
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from biohub.e31_shards import run_workers


@pytest.fixture()
def env_setup(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    working = tmp_path / "working"
    working.mkdir()
    testdir = tmp_path / "testdir"
    testdir.mkdir()
    for name in ("a", "b", "c", "d"):
        (testdir / f"{name}.zarr").mkdir()
    payloadroot = tmp_path / "payload"
    (payloadroot / "scripts").mkdir(parents=True)
    (payloadroot / "src").mkdir(parents=True)
    runtime_src = textwrap.dedent(
        """\
        import os, json, sys, time
        from pathlib import Path

        stems = E31_ASSIGNED_STEMS
        tag = E31_WORKER_TAG
        cuda = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        gpu_shard = os.environ.get("BIOHUB_GPU_SHARD", "")
        pythonpath = os.environ.get("PYTHONPATH", "")
        tuple7 = (WORKING_DIR, REPO_DIR, TEST_DIR, _ps, _primary_materialized_path,
                  _deepcenter_materialized_path, SECONDARY_WEIGHTS_PATH)
        path_types = all(isinstance(v, Path) for v in tuple7)
        if os.environ.get('E31_TEST_MODE') == 'fail' and tag == '0':
            sys.exit(7)
        if os.environ.get('E31_TEST_MODE') in ('fail', 'timeout'):
            time.sleep(30)

        capture = {"stems": stems, "tag": tag, "cuda": cuda, "gpu_shard": gpu_shard,
                   "pythonpath": pythonpath, "path_types": path_types}
        (WORKING_DIR / "capture.json").write_text(json.dumps(capture))
        """
    )
    runtime_path = payloadroot / "scripts" / "e31_submission_runtime.py"
    runtime_path.write_text(runtime_src)
    fake_ps = working / "fake.py"
    fake_ps.write_text("")
    primary = working / "primary.pt"
    primary.write_text("")
    deep = working / "deep.pt"
    deep.write_text("")
    secondary = working / "secondary.pt"
    secondary.write_text("")
    runtime_sha = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    job = {
        "WORKING_DIR": working,
        "REPO_DIR": repo,
        "TEST_DIR": testdir,
        "_ps": fake_ps,
        "_primary_materialized_path": primary,
        "_deepcenter_materialized_path": deep,
        "SECONDARY_WEIGHTS_PATH": secondary,
        "E31_HASHES": {"scripts/e31_submission_runtime.py": runtime_sha},
    }
    return job, payloadroot


def _read_captures(working: Path):
    caps = []
    for p in sorted(working.glob("*/capture.json")):
        caps.append(json.loads(p.read_text()))
    return caps


def test_run_workers_success(env_setup, monkeypatch):
    job, payloadroot = env_setup
    merge_calls = []

    def fake_merge(*args, **kwargs):
        merge_calls.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setattr("biohub.e31_shards.merge_shards", fake_merge)
    run_workers(job, payloadroot, ["GPU-A", "GPU-B"], timeout_seconds=10)
    caps = _read_captures(job["WORKING_DIR"])
    groups = [sorted(c["stems"]) for c in caps]
    assert groups == [["a", "c"], ["b", "d"]]
    tags = sorted(int(c["tag"]) for c in caps)
    assert tags == [0, 1]
    gpus = {c["tag"]: c["cuda"] for c in caps}
    assert gpus["0"] == "GPU-A" and gpus["1"] == "GPU-B"
    shards = {c["tag"]: c["gpu_shard"] for c in caps}
    assert shards["0"] == "0" and shards["1"] == "1"
    expected_pp = os.pathsep.join(
        [
            str(payloadroot / "src"),
            str(job["REPO_DIR"] / "src"),
            str(job["REPO_DIR"] / "scripts"),
            str(job["REPO_DIR"]),
        ]
    )
    assert all(c["pythonpath"] == expected_pp for c in caps)
    assert all(c["path_types"] is True for c in caps)
    timing = json.loads((job["WORKING_DIR"] / "e31_parallel_timing.json").read_text())
    assert timing["worker_count"] == 2
    assert "assignments" in timing and timing["total_wall_seconds"] > 0
    assert merge_calls
    with pytest.raises(FileExistsError):
        run_workers(job, payloadroot, ["GPU-A", "GPU-B"], timeout_seconds=10)


@pytest.mark.parametrize("mode,exc", [("fail", RuntimeError), ("timeout", TimeoutError)])
def test_run_workers_failure(mode, exc, env_setup, monkeypatch):
    job, payloadroot = env_setup
    original_popen = subprocess.Popen
    children = []

    def tracking_popen(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        children.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", tracking_popen)
    monkeypatch.setenv("E31_TEST_MODE", mode)
    monkeypatch.setattr("biohub.e31_shards.merge_shards", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    with pytest.raises(exc):
        run_workers(job, payloadroot, ["GPU-A", "GPU-B"], timeout_seconds=2)
    assert children and all(c.poll() is not None for c in children)
    assert not (job["WORKING_DIR"] / "e31_parallel_timing.json").exists()
    assert not (job["WORKING_DIR"] / "e31_submission_receipt.json").exists()


@pytest.mark.parametrize(
    "mutate",
    ["geff", "bad_hash", "dup_gpu"],
)
def test_run_workers_invalid_preflight(mutate, env_setup, monkeypatch):
    job, payloadroot = env_setup
    if mutate == "geff":
        (job["TEST_DIR"] / "a.geff").mkdir()
    elif mutate == "bad_hash":
        job["E31_HASHES"]["scripts/e31_submission_runtime.py"] = "0" * 64
    else:
        tokens = ["GPU-X", "GPU-X"]
    if mutate != "dup_gpu":
        tokens = ["GPU-A", "GPU-B"]

    def boom(*a, **k):
        raise AssertionError("Popen must not be called")

    monkeypatch.setattr(subprocess, "Popen", boom)
    with pytest.raises(ValueError):
        run_workers(job, payloadroot, tokens, timeout_seconds=5)
    assert not any(job["WORKING_DIR"].glob("*/capture.json"))
