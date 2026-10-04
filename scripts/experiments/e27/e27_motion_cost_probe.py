"""E27 motion-cost probe: capture Hungarian costs at one frame, then stop."""

import math
import sys
from types import CodeType, FunctionType


class _ProbeError(RuntimeError):
    pass


def _find_assign_pass_code(motion_function):
    nested = []

    def walk(code):
        for const in code.co_consts:
            if isinstance(const, CodeType):
                if const.co_name == 'assign_pass':
                    nested.append(const)
                walk(const)

    walk(motion_function.__code__)
    if len(nested) != 1:
        raise _ProbeError('assign_pass_code_not_unique')
    return nested[0]


def _as_float(value):
    out = float(value)
    if not math.isfinite(out):
        raise _ProbeError('nonfinite_value')
    return out


def _as_int(value):
    return int(value)


def _position_rows(lookup, identifiers):
    rows = []
    for identifier in identifiers:
        array = lookup.get(identifier)
        if array is None:
            raise _ProbeError('position_missing')
        rows.append([_as_int(identifier)]
                    + [_as_float(v) for v in array])
        # position_zyx_um order as stored; not reordered
    return rows


def _capture_pass(inner_locals, parent_locals, frame_number):
    pass_name = parent_locals['pass_name']
    source_ids = list(inner_locals['source_ids'])
    target_ids = list(inner_locals['target_ids'])
    record = {'pass_name': pass_name, 'gate_um': None,
              'source_ids': [_as_int(s) for s in source_ids],
              'target_ids': [_as_int(t) for t in target_ids],
              'allowed_pairs': [], 'matches': [],
              'source_positions': [], 'predecessor_positions': []}
    record['gate_um'] = _as_float(inner_locals['gate_um'])
    position_lookup = parent_locals['position_lookup']
    predecessor = parent_locals['predecessor_position_um']
    record['source_positions'] = _position_rows(position_lookup, source_ids)
    record['predecessor_positions'] = _position_rows(predecessor, [s for s in source_ids if s in predecessor])
    if not source_ids or not target_ids:
        return record  # empty-side pass early return: no usable matrices
    big = _as_float(inner_locals['big'])
    cost = inner_locals['cost']
    raw_dist = inner_locals['raw_dist']
    motion_dist = inner_locals['motion_dist']
    prob_matrix = inner_locals['prob_matrix']
    for si, source in enumerate(source_ids):
        for ti, target in enumerate(target_ids):
            entry = _as_float(cost[si][ti])
            if entry >= big:
                continue  # finite sentinel / disallowed cell
            record['allowed_pairs'].append(
                [_as_int(source), _as_int(target), entry,
                 _as_float(raw_dist[si][ti]), _as_float(motion_dist[si][ti]),
                 _as_float(prob_matrix[si][ti])])
    for triple in inner_locals['__return__']:
        source, target, raw, motion, prob = triple
        record['matches'].append([_as_int(source), _as_int(target),
                                  _as_float(raw), _as_float(motion),
                                  _as_float(prob)])
    return record


def probe_motion(run, motion_function, frame_number):
    """Run pipeline prefix, capture assign_pass costs, stop after motion call."""
    if not callable(run):
        raise _ProbeError('run_not_callable')
    if not isinstance(motion_function, FunctionType):
        raise _ProbeError('motion_function_invalid')
    if type(frame_number) is not int or frame_number < 0:
        raise _ProbeError('frame_number_invalid')
    if sys.getprofile() is not None:
        raise _ProbeError('profile_already_set')

    motion_code = motion_function.__code__
    assign_code = _find_assign_pass_code(motion_function)
    sentinel = BaseException('e27-probe-stop')
    state = {'passes': [], 'errors': [], 'edges': None, 'frames': None,
             'motion_returned': False, 'stopped': False}

    def local(frame, event, arg):
        try:
            code = frame.f_code
            if event == 'return' and code is assign_code:
                parent = frame.f_back
                if (parent is not None and parent.f_code is motion_code
                        and parent.f_locals.get('t') == frame_number):
                    inner = dict(frame.f_locals)
                    inner['__return__'] = arg
                    state['passes'].append(_capture_pass(inner,
                                                         parent.f_locals,
                                                         frame_number))
            elif event == 'return' and code is motion_code:
                state['motion_returned'] = True
                if not isinstance(arg, list) or not arg:
                    state['errors'].append('invalid_motion_return')
                    return
                state['edges'] = len(arg)
                try:
                    stats = frame.f_locals['stats']
                    state['frames'] = _as_int(stats['motion_relink_frames'])
                except Exception:
                    state['errors'].append('stats_capture_error')
                raise sentinel
        except Exception:
            # Never trap BaseException: the private stop sentinel escapes.
            state['errors'].append('capture_error')

    original = sys.getprofile()
    sys.setprofile(local)
    try:
        run()
    except BaseException as exc:
        if exc is not sentinel:
            raise
        state['stopped'] = True  # only the exact sentinel counts as accepted
    finally:
        sys.setprofile(original)

    if not state['stopped']:
        raise _ProbeError('sentinel_swallowed_by_run')
    if not state['motion_returned']:
        raise _ProbeError('run_completed_without_stop')
    passes = state['passes']
    names = [p['pass_name'] for p in passes]
    if names != ['tight', 'relaxed']:
        raise _ProbeError('pass_order_invalid')
    if state['errors'] or not state['edges'] or not state['frames']:
        raise _ProbeError('probe_data_invalid')
    result = {'schema': 'E27_MOTION_COST_DIAGNOSTIC_V1',
              'frame': int(frame_number), 'passes': passes,
              'motion_edge_count': int(state['edges']),
              'motion_frames': int(state['frames']),
              'stopped_after_motion': True, 'submission_allowed': False}
    for record in passes:
        for row in (record['allowed_pairs'] + record['matches']
                    + record['source_positions']
                    + record['predecessor_positions']):
            for value in row:
                if isinstance(value, float) and not math.isfinite(value):
                    raise _ProbeError('nonfinite_output')
    _as_float(result['motion_frames'])
    return result
