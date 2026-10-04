"""Supervisor state-machine tests with fake child handles, never a real model."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import biohub.association_supervise as supervision
from biohub.association_capture import _sha


@pytest.mark.parametrize("case", ["pass", "exit_failure", "timeout", "rss"])
def test_serial_execution_and_stop_on_first_arm_failure(tmp_path, monkeypatch, case):
    real_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda p: True if str(p) == "/kaggle/working" else real_is_dir(p))
    monkeypatch.setattr(supervision.shutil, "disk_usage", lambda path: SimpleNamespace(free=32 * 1024**3))
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"source_paths": {"off": "off.py", "on": "on.py"}, "repo_dir": str(tmp_path)}))
    calls, signals = [], []

    class Process:
        pid = 987654321

        def __init__(self, command, **kwargs):
            self.arm = command[command.index("--arm") + 1]
            calls.append(self.arm)
            self.code = 1 if case == "exit_failure" else (None if case in ("timeout", "rss") else 0)
            assert kwargs["start_new_session"] and kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "0"
            root = Path(command[command.index("--root") + 1])
            root.mkdir()
            names = [f"v{i}" for i in range(4)]
            result = {"status": "ARM_COMPLETE", "arm": self.arm, "dataset_order": names,
                      "records": [{"dataset": n, "stage": s} for n in names for s in ("returned", "pre", "post")],
                      "plan_sha256": _sha(plan_path), "observation_complete": self.arm == "on",
                      **{k: {} for k in ("input_inventory", "dependencies", "environment",
                                        "model_config", "rng_after")}}
            (root / "RESULT.json").write_text(json.dumps(result))

        def poll(self):
            return self.code

        def wait(self, timeout=None):
            if self.code is None:
                self.code = -15
            return self.code

    monkeypatch.setattr(supervision.subprocess, "Popen", Process)
    monkeypatch.setattr(supervision.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    if case == "timeout":
        counter = iter([0., 0., 5000., 5001.])
        monkeypatch.setattr(supervision.time, "monotonic", lambda: next(counter))
    if case == "rss":
        monkeypatch.setattr(supervision, "process_tree_rss", lambda pid: 25 * 1024**3)
    root = tmp_path / "run"
    if case == "pass":
        result = supervision.supervise(plan_path, root, tmp_path, float("inf"))
        assert calls == ["off", "on"] and not signals and not result["submission_authorized"]
        assert (root / "PARITY_RESULT.json").is_file()
    else:
        with pytest.raises(ValueError, match="arm failed"):
            supervision.supervise(plan_path, root, tmp_path, 8400. if case == "timeout" else float("inf"))
        assert calls == ["off"] and not (root / "on").exists()
        assert not (root / "PARITY_RESULT.json").exists()
        assert bool(signals) == (case in ("timeout", "rss"))
        assert json.loads((root / "off_PROCESS.json").read_text())["returncode"] != 0


def test_proc_sampler_counts_children_from_all_threads_once(tmp_path, monkeypatch):
    monkeypatch.setattr(supervision.os, "sysconf", lambda name: 4096)
    for pid, pages, children in ((10, 100, {10: "20", 11: "20 30"}), (20, 200, {20: ""}),
                                 (30, 300, {30: "40"})):
        folder = tmp_path / str(pid)
        folder.mkdir()
        (folder / "statm").write_text(f"1000 {pages} 0 0 0 0 0")
        for tid, text in children.items():
            task = folder / "task" / str(tid)
            task.mkdir(parents=True)
            (task / "children").write_text(text)
    assert supervision.process_tree_rss(10, tmp_path) == 600 * 4096
