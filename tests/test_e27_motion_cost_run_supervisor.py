"""Authoring-only unit tests for e27_motion_cost_run.supervise (no real children)."""

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from biohub import e26_screen as e
    from scripts.experiments.e27 import e27_association_prior_screen as g
    from scripts.experiments.e27 import e27_motion_cost_run as m

    root = tmp_path.resolve()
    (root / 'outputs' / 'local').mkdir(parents=True)
    (root / 'scripts').mkdir()
    self_py = root / 'scripts' / 'e27_motion_cost_run.py'
    self_py.write_text('synthetic supervisor source\n')
    probe_py = root / 'scripts' / 'e27_motion_cost_probe.py'
    probe_py.write_text('synthetic probe source\n')

    monkeypatch.setattr(m, '__file__', str(self_py), raising=False)
    monkeypatch.setattr(m, 'ROOT', root, raising=False)
    monkeypatch.setattr(g, 'ROOT', root, raising=False)
    monkeypatch.setattr(e, 'ROOT', root, raising=False)
    monkeypatch.setattr(g, '_snapshot_source_closure', lambda *a, **k: {})
    monkeypatch.setattr(g, '_verify_source_closure', lambda arg: arg)
    monkeypatch.setattr(e, 'generation_environment', lambda *a, **k: {})
    monkeypatch.setattr(
        e, 'check_runtime_budget',
        lambda *a, **k: {'wall_seconds': 0., 'peak_rss_bytes': 1,
                         'ram_scope': 'self_process'})

    def bind(path, label=None):
        return g._binding_for_path(path, label=label or 'test')

    class FakeProc:
        pid = 424242
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    spawns = []

    def fake_popen(argv, **kwargs):
        spawns.append((list(argv), dict(kwargs)))
        out = Path(argv[argv.index('--output') + 1])
        out.mkdir(parents=True)
        mode = argv[argv.index('--mode') + 1]
        e.write_json_exclusive(out / 'CONTROL.json', {})
        e.write_json_exclusive(out / 'COSTS.json', {})
        result = {
            'status': 'DIAGNOSTIC_CAPTURE_COMPLETE_NOT_CANDIDATE',
            'mode': mode, 'dataset': m.STEM, 'frame': m.FRAME,
            'gt_read': False, 'submission_allowed': False,
            'control_binding': bind(out / 'CONTROL.json', 'control_binding'),
            'cost_binding': bind(out / 'COSTS.json', 'cost_binding'),
            'source_bindings': {},
            'extra_bindings': {
                'self': bind(self_py, 'self'),
                'probe': bind(probe_py, 'probe')},
        }
        e.write_json_exclusive(out / 'RESULT.json', result)
        return FakeProc()

    kills = []
    monkeypatch.setattr(m.subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(m.os, 'killpg', lambda *a, **k: kills.append(a))

    outputs = root / 'outputs' / 'local'
    return type('Env', (), dict(root=root, m=m, g=g, e=e, outputs=outputs,
                                spawns=spawns, kills=kills, bind=bind))


def test_success_binds_receipt(env):
    out = env.outputs / 'run_ok'
    audit = env.m.supervise(out, next(iter(env.m.MOVES)))
    assert len(env.spawns) == 1
    argv, kwargs = env.spawns[0]
    assert argv[:5] == [sys.executable, '-m', 'scripts.experiments.e27.e27_motion_cost_run',
                        '--child', '--output']
    assert kwargs['cwd'] == str(env.root)
    assert kwargs['start_new_session'] is True
    assert env.kills == []
    receipt = json.loads((audit / 'SUPERVISOR_RESULT.json').read_text())
    assert receipt['status'] == 'DIAGNOSTIC_SUPERVISED_NOT_CANDIDATE'
    assert receipt['scientific_adoption'] is False
    assert receipt['returncode'] == 0
    assert receipt['child_pid'] == 424242
    assert receipt['result_binding'] == env.bind(out / 'RESULT.json')
    for name, bound in receipt['log_bindings'].items():
        assert bound == env.bind(audit / name)
    assert not list(env.outputs.glob('*_supervisor/ERROR.json'))
    assert not (audit / 'ERROR.json').exists()


def test_result_changed_during_read_is_rejected(env, monkeypatch):
    real_read = Path.read_text
    target = env.outputs / "run_drift" / "RESULT.json"
    state = {"mutated": False}

    def wrapped(self, *args, **kwargs):
        text = real_read(self, *args, **kwargs)
        if self == target and not state["mutated"]:
            state["mutated"] = True
            self.write_text(text + " ")
        return text

    monkeypatch.setattr(Path, "read_text", wrapped)
    out = env.outputs / 'run_drift'
    with pytest.raises(RuntimeError, match='result binding drift'):
        env.m.supervise(out, next(iter(env.m.MOVES)))
    audit = env.outputs / 'run_drift_supervisor'
    err = json.loads(real_read(audit / 'ERROR.json'))
    assert err['error_type'] == 'RuntimeError'
    assert not (audit / 'SUPERVISOR_RESULT.json').exists()


def test_cap_exceeded_by_parent_receipt_is_rejected(env, monkeypatch):
    from biohub import e26_screen as e
    real_write = e.write_json_exclusive

    def guarded(path, payload):
        real_write(path, payload)
        if Path(path).name == 'SUPERVISOR_RESULT.json':
            monkeypatch.setattr(env.m, 'CAP', 1)

    monkeypatch.setattr(e, 'write_json_exclusive', guarded)
    out = env.outputs / 'run_cap'
    with pytest.raises(RuntimeError, match='post-receipt budget'):
        env.m.supervise(out, next(iter(env.m.MOVES)))
    audit = env.outputs / 'run_cap_supervisor'
    err = json.loads((audit / 'ERROR.json').read_text())
    assert err['error_type'] == 'RuntimeError'
    assert (audit / 'SUPERVISOR_RESULT.json').exists()
