"""E27 motion-cost run: fixed one-video diagnostic child + serial supervisor."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEM = '6bba_09961292'
FRAME = 94
WALL = 1800
RAM = 8 * 1024 ** 3
CAP = 128 * 1024 ** 2
PROBE_SHA = '302ad6cd99470ce8a2b66000229d2ec2db24b71241b7826c24b282c59a43fade'
PRIOR_SHA = {
    'selected_only': '4891e86e7e6cab22ab662cd937dced1dbda549ac0e24a7395c9e4e8b98fad619',
    'recorded_prior': 'a667b969b1fad4e5b50c3e57ffd24965bd2f6f0d09137bc994570b13029de571',
}
MOVES = ('selected_only', 'recorded_prior')


def _terminate_owned_process(proc):
    """Terminate a child process that this parent started with start_new_session=True.

    The child is the leader of its own process group, so its pid doubles as the
    pgid. No getpgid() lookup and no PID-reuse probing is performed.
    """
    if proc is None:
        return

    if proc.poll() is not None:
        # Already exited: reap it and stop.
        proc.wait(timeout=5)
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        # Process (or group) vanished before the signal landed; still reap.
        pass

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # Final reap: deliberately not guarded, so a failed cleanup surfaces.
        proc.wait(timeout=5)


def _fail(output: Path, exc: BaseException) -> None:
    try:
        e.write_json_exclusive(
            output / 'ERROR.json',
            {'status': 'DIAGNOSTIC_FAILED', 'error_type': type(exc).__name__},
        )
    except Exception:
        pass


def child(output: Path, mode: str) -> Path:
    global e, g
    from biohub import e26_screen as e
    from scripts import e27_association_prior_screen as g
    if mode not in MOVES:
        raise ValueError('bad mode')
    started = time.monotonic()
    output = g._canonical_new_output_dir(output)
    fired = []

    def _alarm(signum, frame):
        fired.append(True)
        raise TimeoutError('wall')

    old_handler = signal.signal(signal.SIGALRM, _alarm)
    old_timer = signal.setitimer(signal.ITIMER_REAL, WALL)
    try:
        before = g._snapshot_source_closure()
        extra = {'self': g._binding_for_path(Path(__file__), label='self'),
                 'probe': g._binding_for_path(ROOT / 'scripts' / 'e27_motion_cost_probe.py',
                                              label='probe')}
        if extra['probe']['sha256'] != PROBE_SHA:
            raise RuntimeError('probe sha')
        reference = g._verify_reference_binding('reference')

        def check_budget():
            t = e.check_runtime_budget(started, wall_limit_seconds=WALL, ram_limit_bytes=RAM)
            if fired:
                raise TimeoutError('budget')
            if g._output_tree_bytes(output) > CAP:
                raise RuntimeError('output cap')
            return t

        check_budget()
        runtime = e.initialize_inference_runtime()
        check_budget()
        prepared = g.prepare_inputs()
        if prepared['status'] != 'INPUTS_PREPARED_NOT_GENERATED':
            raise RuntimeError('prepared status')
        cfg = g.verify_prepared_materials(prepared)
        mapping, prior = g.build_prior_inputs(prepared, mode)
        check_budget()
        if prepared['gt_read'] is not False:
            raise RuntimeError('gt read')
        if prior['sha256'] != PRIOR_SHA[mode]:
            raise RuntimeError('prior sha')
        e.write_json_exclusive(output / 'CONTROL.json', {
            'schema': 'E27_MOTION_COST_CONTROL_V1', 'mode': mode, 'dataset': STEM,
            'frame': FRAME, 'source_bindings': before, 'extra_bindings': extra,
            'reference_binding': reference, 'runtime': runtime,
            'input_metadata': prepared['metadata_bindings'],
            'input_readers': prepared['reader_bindings'],
            'config': prepared['baseline_control']['config'], 'prior': prior,
            'limits': {'wall_limit_seconds': WALL, 'ram_limit_bytes': RAM,
                       'output_cap_bytes': CAP}})
        control = g._binding_for_path(output / 'CONTROL.json', label='control')

        from biohub.public_postproc import graph_ops, pipeline
        from scripts.e27_motion_cost_probe import probe_motion
        if pipeline.motion_relink_edges is not graph_ops.motion_relink_edges:
            raise RuntimeError('relink identity')
        raw_paths = [p for p in prepared['raw_paths'] if p.stem == STEM]
        if len(raw_paths) != 1:
            raise RuntimeError('path count')
        nodes, raw_edges = pipeline._load_geff_as_dicts(raw_paths[0])

        def run():
            return pipeline.filter_output_graph_pre_linefit(
                cfg, nodes, raw_edges, dataset=STEM, association_priors=mapping[STEM])

        check_budget()
        data = probe_motion(run, pipeline.motion_relink_edges, FRAME)
        check_budget()
        e.write_json_exclusive(output / 'COSTS.json', data)
        cost = g._binding_for_path(output / 'COSTS.json', label='cost')
        if data['motion_frames'] != 99 or data['motion_edge_count'] != 28806:
            raise RuntimeError('stats mismatch')
        g.verify_prepared_materials(prepared)
        rm, rp = g.build_prior_inputs(prepared, mode)
        if rp != prior or rm != mapping:
            raise RuntimeError('prior rebuild')
        after = g._verify_source_closure(before)
        ex = {'self': g._binding_for_path(Path(__file__), label='self'),
              'probe': g._binding_for_path(ROOT / 'scripts' / 'e27_motion_cost_probe.py',
                                           label='probe')}
        if ex != extra or g._verify_reference_binding('reference') != reference:
            raise RuntimeError('post bindings')
        e.write_json_exclusive(output / 'RESULT.json', {
            'schema': 'E27_MOTION_COST_RESULT_V1',
            'status': 'DIAGNOSTIC_CAPTURE_COMPLETE_NOT_CANDIDATE',
            'gt_read': False, 'submission_allowed': False, 'mode': mode,
            'dataset': STEM, 'frame': FRAME, 'control_binding': control,
            'cost_binding': cost, 'timing': check_budget(),
            'source_bindings': after, 'extra_bindings': ex})
        check_budget()
        return output
    except BaseException as exc:
        _fail(output, exc)
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        signal.setitimer(signal.ITIMER_REAL, *old_timer)


def supervise(output: Path, mode: str) -> Path:
    from biohub import e26_screen as e
    from scripts import e27_association_prior_screen as g
    if mode not in MOVES:
        raise ValueError('bad mode')
    if not output.is_absolute() or output.parent != ROOT / 'outputs' / 'local' \
            or Path(os.path.realpath(output)) != output or output.exists() \
            or output.is_symlink():
        raise ValueError('not fresh canonical child')
    audit = g._canonical_new_output_dir(output.parent / (output.name + '_supervisor'))
    started = time.monotonic()
    before = g._snapshot_source_closure()
    extra = {'self': g._binding_for_path(Path(__file__), label='self'),
             'probe': g._binding_for_path(ROOT / 'scripts' / 'e27_motion_cost_probe.py',
                                          label='probe')}
    proc = None
    try:
        with open(audit / 'stdout.log', 'xb') as so, open(audit / 'stderr.log', 'xb') as se:
            proc = subprocess.Popen(
                [sys.executable, '-m', 'scripts.e27_motion_cost_run', '--child',
                 '--output', str(output), '--mode', mode], cwd=str(ROOT),
                env=e.generation_environment(), stdin=subprocess.DEVNULL,
                stdout=so, stderr=se, start_new_session=True)
            while proc.poll() is None:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() - started > WALL:
                    raise TimeoutError('supervisor wall')
                tree = g._output_tree_bytes(audit)
                if output.exists():
                    tree += g._output_tree_bytes(output)
                if tree > CAP:
                    raise RuntimeError('output cap')
        rc = proc.returncode
        if rc != 0 or (output / 'ERROR.json').exists() or (audit / 'ERROR.json').exists():
            raise RuntimeError('child failed')
        if g._output_tree_bytes(audit) + g._output_tree_bytes(output) > CAP \
                or time.monotonic() - started > WALL:
            raise RuntimeError('post-run budget')
        if g._verify_source_closure(before) != before or extra != {
                'self': g._binding_for_path(Path(__file__), label='self'),
                'probe': g._binding_for_path(ROOT / 'scripts' / 'e27_motion_cost_probe.py',
                                             label='probe')}:
            raise RuntimeError('source drift')
        rb = g._binding_for_path(output / 'RESULT.json', label='result')
        result = json.loads((output / 'RESULT.json').read_text())
        for key, path in (('control_binding', output / 'CONTROL.json'),
                          ('cost_binding', output / 'COSTS.json')):
            if g._binding_for_path(path, label=key) != result[key]:
                raise RuntimeError(key)
        if result['source_bindings'] != before or result['extra_bindings'] != extra:
            raise RuntimeError('child bindings')
        if (result['status'] != 'DIAGNOSTIC_CAPTURE_COMPLETE_NOT_CANDIDATE'
                or result['mode'] != mode or result['dataset'] != STEM
                or result['frame'] != FRAME or result['gt_read'] is not False
                or result['submission_allowed'] is not False):
            raise RuntimeError('result fields')
        if g._binding_for_path(output / 'RESULT.json', label='result') != rb:
            raise RuntimeError('result binding drift')
        logs = {n: g._binding_for_path(audit / n, label=n)
                for n in ('stdout.log', 'stderr.log')}
        e.write_json_exclusive(audit / 'SUPERVISOR_RESULT.json', {
            'schema': 'E27_MOTION_SUPERVISOR_RESULT_V1',
            'status': 'DIAGNOSTIC_SUPERVISED_NOT_CANDIDATE', 'returncode': rc,
            'child_pid': proc.pid, 'result_binding': rb, 'log_bindings': logs,
            'timing': e.check_runtime_budget(started, wall_limit_seconds=WALL,
                                             ram_limit_bytes=RAM),
            'elapsed_seconds': time.monotonic() - started,
            'source_bindings': before, 'extra_bindings': extra,
            'scientific_adoption': False})
        if ((g._output_tree_bytes(audit) + g._output_tree_bytes(output)) > CAP
                or (time.monotonic() - started) > WALL):
            raise RuntimeError('post-receipt budget')
        return audit
    except BaseException as exc:
        try:
            _terminate_owned_process(proc)
        finally:
            try:
                e.write_json_exclusive(
                    audit / 'ERROR.json',
                    {
                        'status': 'DIAGNOSTIC_FAILED',
                        'error_type': type(exc).__name__,
                    },
                )
            except Exception:
                pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    ap.add_argument('--mode', required=True, choices=list(MOVES))
    ap.add_argument('--child', action='store_true')
    a = ap.parse_args()
    out = Path(a.output)
    if a.child:
        child(out, a.mode)
    else:
        supervise(out, a.mode)
    return 0


if __name__ == '__main__':
    main()
