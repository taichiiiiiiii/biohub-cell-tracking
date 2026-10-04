import copy

import pytest

from biohub.consensus_edges import map_consensus_to_raw

VALID = dict(
    pairs=[(0, 1), (1, 0)],
    source_detector_indices=[10, 20],
    target_detector_indices=[30, 40],
    graph_to_detector={7: 10, 3: 20, 9: 30, 4: 40, 100: 99},
    raw_node_ids=[7, 3, 9, 4, 100],
)


def call(**over):
    kw = dict(copy.deepcopy(VALID))
    kw.update(over)
    return map_consensus_to_raw(**kw)


def test_exact_example_and_inputs_immutable():
    args = copy.deepcopy(VALID)
    before = copy.deepcopy(args)
    got = map_consensus_to_raw(**args)
    assert got == [(3, 9), (7, 4)]
    assert args == before


def test_valid_diagonal_pairs():
    assert call(pairs=[(0, 0), (1, 1)]) == [(3, 4), (7, 9)]
    with pytest.raises(ValueError):
        call(pairs=[(0, 0), (1, 0)])


def test_missing_detector_with_empty_pairs():
    with pytest.raises(ValueError):
        call(pairs=[], raw_node_ids=[], graph_to_detector={7: 10, 3: 20, 9: 30, 100: 99})


def test_missing_endpoint_dropped_and_no_fallback():
    assert call(raw_node_ids=[7, 3, 9, 100]) == [(3, 9)]
    assert call(raw_node_ids=[7, 9]) == []


def test_all_empty_accepted_and_empty_raw():
    empty = dict(
        pairs=[], source_detector_indices=[], target_detector_indices=[], graph_to_detector={}, raw_node_ids=[]
    )
    assert map_consensus_to_raw(**empty) == []
    assert call(raw_node_ids=[]) == []


def test_missing_mapping_value_raises_even_for_empty_pairs():
    with pytest.raises(ValueError):
        call(pairs=[], graph_to_detector={7: 10, 3: 20, 9: 30, 4: 40})
    with pytest.raises(ValueError):
        call(graph_to_detector={7: 10, 3: 20, 9: 30, 100: 99})


@pytest.mark.parametrize(
    "field,value",
    [
        ("pairs", [(1, 0), (0, 1)]),
        ("pairs", [(0, 1), (1, 0), (1, 0)]),
        ("pairs", [(0, 5)]),
        ("pairs", [(2, 0)]),
        ("pairs", [(0, 1), (0, 0)]),
        ("pairs", [[0, 1]]),
        ("pairs", [(True, 1)]),
        ("source_detector_indices", [True, 20]),
        ("target_detector_indices", [30, False]),
        ("raw_node_ids", [7, 3, 9, 4, 100, 8]),
        ("graph_to_detector", {7: 10, 3: 10, 9: 30, 4: 40, 100: 99}),
        ("source_detector_indices", [10, 30]),
        ("raw_node_ids", [7, 3, 9, 4, 100, True]),
    ],
)
def test_invalid_mutations_raise(field, value):
    over = {field: value}
    if field == "pairs" and value == [(0, 1), (0, 0)]:
        over["pairs"] = [(0, 0), (0, 1)]
    with pytest.raises(ValueError):
        call(**over)
