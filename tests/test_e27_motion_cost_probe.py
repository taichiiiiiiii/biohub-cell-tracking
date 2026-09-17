"""Issue9: missing predecessor identifiers must not abort the probe."""

import copy
import json
import sys

import pytest

from biohub.public_postproc import graph_ops, pipeline
from biohub.public_postproc.config import build_config
from scripts.e27_motion_cost_probe import probe_motion


def test_probe_real_graph(tmp_path):
    cfg = build_config(test_dir=tmp_path)
    nodes = {
        1: {'node_id': 1, 't': 0, 'z': 0.0, 'y': 0.0, 'x': 0.0},
        2: {'node_id': 2, 't': 0, 'z': 0.0, 'y': 3.0, 'x': 0.0},
        3: {'node_id': 3, 't': 1, 'z': 0.0, 'y': 0.5, 'x': 0.0},
    }
    expected = graph_ops.motion_relink_edges(cfg, copy.deepcopy(nodes),
                                             pipeline.new_stats())
    downstream = []

    def run():
        graph_ops.motion_relink_edges(cfg, nodes, pipeline.new_stats())
        downstream.append(True)

    p = probe_motion(run, graph_ops.motion_relink_edges, 0)
    assert downstream == []
    assert p['motion_edge_count'] == len(expected)
    assert sys.getprofile() is None
    assert [v['pass_name'] for v in p['passes']] == ['tight', 'relaxed']
    pairs = []
    for record in p['passes']:
        for row in record['matches']:
            pairs.append(tuple(row[:2]))
    assert sorted(pairs) == sorted((e['source_id'], e['target_id'])
                                   for e in expected)
    assert p['passes'][1]['target_ids'] == []
    json.dumps(p, allow_nan=False)


def test_original_exception_kept():
    boom = ValueError('original')

    def motion():
        def assign_pass():
            return []
        raise boom

    with pytest.raises(ValueError) as excinfo:
        probe_motion(lambda: motion(), motion, 0)
    assert excinfo.value is boom
    assert sys.getprofile() is None


def test_preexisting_profiler_kept():
    def motion():
        def assign_pass():
            return []
        return [{}]

    def marker(frame, event, arg):
        pass

    ran = []
    sys.setprofile(marker)
    try:
        with pytest.raises(RuntimeError):
            probe_motion(lambda: ran.append(True), motion, 0)
        assert ran == []
        assert sys.getprofile() is marker
    finally:
        sys.setprofile(None)


def test_swallowed_stop_rejected(tmp_path):
    from biohub.public_postproc import graph_ops, pipeline
    from biohub.public_postproc.config import build_config

    cfg = build_config(test_dir=tmp_path)
    nodes = {1: {'node_id': 1, 't': 0, 'z': 0., 'y': 0., 'x': 0.},
             2: {'node_id': 2, 't': 1, 'z': 0., 'y': 0., 'x': 0.}}

    def run():
        try:
            graph_ops.motion_relink_edges(cfg, nodes, pipeline.new_stats())
        except BaseException:
            pass

    with pytest.raises(RuntimeError):
        probe_motion(run, graph_ops.motion_relink_edges, 0)
    assert sys.getprofile() is None
