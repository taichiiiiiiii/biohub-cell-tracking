import copy

import pytest

from biohub.public_postproc.graph_ops import prepare_consensus_reservations


def _nodes():
    return {
        1: {"node_id": 1, "t": 0, "z": 0.0, "y": 0.0, "x": 0.0},
        2: {"node_id": 2, "t": 1, "z": 0.0, "y": 0.0, "x": 1.0},
        3: {"node_id": 3, "t": 1, "z": 0.0, "y": 0.0, "x": 1.5},
    }


def _edge(source, target):
    return {"source_id": source, "target_id": target}


def test_valid_pair_is_reserved_and_inputs_unchanged():
    nodes = _nodes()
    raw = [_edge(1, 2)]
    filtered = [dict(raw[0])]
    before = (copy.deepcopy(nodes), copy.deepcopy(raw), copy.deepcopy(filtered))
    assert prepare_consensus_reservations({0: [(1, 2)]}, nodes, raw, filtered, 2.0) == {0: [(1, 2)]}
    assert (nodes, raw, filtered) == before


@pytest.mark.parametrize("raw,filtered", [([], [_edge(1, 2)]), ([_edge(1, 2)], [])])
def test_pair_missing_from_either_is_excluded(raw, filtered):
    assert prepare_consensus_reservations({0: [(1, 2)]}, _nodes(), raw, filtered, 2.0) == {}


def test_degree_conflict_and_gate_fail_are_excluded():
    nodes = _nodes()
    assert prepare_consensus_reservations({0: [(1, 2)]}, nodes,
                                          [_edge(1, 2), _edge(1, 3)],
                                          [_edge(1, 2), _edge(1, 3)], 2.0) == {}
    far = {**nodes, 2: {**nodes[2], "x": 10.0}}
    assert prepare_consensus_reservations({0: [(1, 2)]}, far, [_edge(1, 2)], [_edge(1, 2)], 2.0) == {}


def test_time_and_competing_pairs_fail():
    bad_time = {**_nodes(), 2: {**_nodes()[2], "t": 2}}
    assert prepare_consensus_reservations({0: [(1, 2)]}, bad_time, [_edge(1, 2)], [_edge(1, 2)], 2.0) == {}
    with pytest.raises(ValueError):
        prepare_consensus_reservations({0: [(1, 2), (1, 3)]}, _nodes(),
                                       [_edge(1, 2), _edge(1, 3)],
                                       [_edge(1, 2), _edge(1, 3)], 2.0)


def test_empty_mapping_and_malformed_inputs_fail_closed():
    assert prepare_consensus_reservations({}, _nodes(), [], [], 2.0) == {}
    with pytest.raises(ValueError):
        prepare_consensus_reservations({0: [(1, 2)]}, _nodes(), [_edge(1, 2)], [_edge(1, 2)], True)
