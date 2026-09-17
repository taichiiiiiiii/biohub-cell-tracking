"""Tests for biohub.consensus_edges.reciprocal_consensus_pairs."""

import numpy as np
import pytest

from biohub.consensus_edges import (
    positive_reciprocal_consensus_pairs,
    primary_reciprocal_consensus_pairs,
    reciprocal_consensus_pairs,
)

FORWARD = np.array([[9, 0, 0], [0, 9, 9]], dtype=np.float32)
SECONDARY = np.array([[9, 0, 0], [0, 9, 9]], dtype=np.float32)
REVERSE = np.array([[9, 0, 0], [0, 0, 9]], dtype=np.float32)


def oracle(forward, reverse, secondary):
    """Return row-major consensus pairs where all three strict comparisons hold."""
    ns, nt = forward.shape
    pairs = []
    for i in range(ns):
        for j in range(nt):
            if (
                all(forward[i, j] > forward[k, j] for k in range(ns) if k != i)
                and all(secondary[i, j] > secondary[k, j] for k in range(ns) if k != i)
                and all(reverse[i, j] > reverse[i, col] for col in range(nt) if col != j)
            ):
                pairs.append((i, j))
    return pairs


@pytest.mark.parametrize("which", [0, 2])
def test_column_tie_rejects_losing_row_only(which):
    args = [np.array([[3.0, 0.0], [0.0, 3.0]], dtype=np.float32) for _ in range(3)]
    args[which][1, 0] = 3.0
    assert oracle(*args) == [(1, 1)]
    assert reciprocal_consensus_pairs(*args) == [(1, 1)]


def test_random_integer_arrays_match_oracle_and_repeatable():
    rng = np.random.default_rng(7)
    for shape in [(1, 1), (1, 4), (4, 1), (5, 4), (4, 5), (6, 6)]:
        f = rng.integers(0, 4, shape).astype(np.float32)
        r = rng.integers(0, 4, shape).astype(np.float32)
        s = rng.integers(0, 4, shape).astype(np.float32)
        snapshot = [f.copy(), r.copy(), s.copy()]
        expected = oracle(f, r, s)
        first = reciprocal_consensus_pairs(f, r, s)
        second = reciprocal_consensus_pairs(f, r, s)
        assert first == second == expected
        assert first == sorted(set(first))
        assert len({i for i, _ in first}) == len(first)
        assert len({j for _, j in first}) == len(first)
        assert all(type(i) is int and type(j) is int for i, j in first)
        for before, after in zip(snapshot, (f, r, s), strict=True):
            assert np.array_equal(before, after)


def arrays(f=FORWARD, r=REVERSE, s=SECONDARY):
    return f.copy(), r.copy(), s.copy()


def test_docstring_non_square_fixture():
    pairs = reciprocal_consensus_pairs(*arrays())
    assert pairs == [(0, 0), (1, 2)]
    assert all(type(i) is int and type(j) is int for i, j in pairs)


def test_negative_values_retain_pairs():
    shift = np.float32(20.0)
    pairs = reciprocal_consensus_pairs(FORWARD - shift, REVERSE - shift, SECONDARY - shift)
    assert pairs == [(0, 0), (1, 2)]


def test_positive_filter_keeps_only_strictly_positive_selected_logits():
    f, r, s = arrays()
    assert positive_reciprocal_consensus_pairs(f, r, s) == [(0, 0), (1, 2)]
    r[1, 2] = np.float32(-1)
    assert positive_reciprocal_consensus_pairs(f, r, s) == [(0, 0)]
    r[1, 2] = np.float32(0)
    assert positive_reciprocal_consensus_pairs(f, r, s) == [(0, 0)]


def test_positive_filter_preserves_inputs_and_validation():
    f, r, s = arrays()
    snapshot = [f.copy(), r.copy(), s.copy()]
    positive_reciprocal_consensus_pairs(f, r, s)
    for before, after in zip(snapshot, (f, r, s), strict=True):
        assert np.array_equal(before, after)
    with pytest.raises(ValueError):
        positive_reciprocal_consensus_pairs(f.astype(np.float64), r, s)


def test_primary_only_reciprocal_consensus_ignores_secondary():
    f, r, s = arrays()
    s[0, 0] = np.float32(-100)
    assert primary_reciprocal_consensus_pairs(f, r) == [(0, 0), (1, 2)]


def test_primary_only_shape_and_input_validation():
    f, r, _ = arrays()
    with pytest.raises(ValueError):
        primary_reciprocal_consensus_pairs(f, r[:, :2])
    before = (f.copy(), r.copy())
    primary_reciprocal_consensus_pairs(f, r)
    assert np.array_equal(f, before[0]) and np.array_equal(r, before[1])


@pytest.mark.parametrize("which", ["forward", "reverse", "secondary"])
def test_single_directional_disagreement_rejects_all(which):
    base = np.array([[3, 0], [0, 3]], dtype=np.float32)
    swapped = base[::-1].copy()
    args = {"forward": base, "reverse": base, "secondary": base}
    args[which] = swapped
    pairs = reciprocal_consensus_pairs(args["forward"], args["reverse"], args["secondary"])
    assert pairs == []


def test_reverse_tie_rejects_losing_column_only():
    rev_tied = np.array([[3, 3], [0, 3]], dtype=np.float32)
    base = np.array([[3, 0], [0, 3]], dtype=np.float32)
    assert oracle(base, rev_tied, base) == [(1, 1)]
    assert reciprocal_consensus_pairs(base, rev_tied, base) == [(1, 1)]


@pytest.mark.parametrize("shape", [(0, 0), (0, 3), (3, 0)])
def test_empty_axes_accepted(shape):
    z = np.zeros(shape, dtype=np.float32)
    assert reciprocal_consensus_pairs(z, z, z) == []


@pytest.mark.parametrize("bad", [[1.0, 2.0], 1.0, np.zeros((2, 2), np.float64), np.zeros((2, 2), np.int32)])
def test_invalid_array_types_rejected(bad):
    good = np.zeros((2, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        reciprocal_consensus_pairs(bad, good, good)
    with pytest.raises(ValueError):
        reciprocal_consensus_pairs(good, bad, good)
    with pytest.raises(ValueError):
        reciprocal_consensus_pairs(good, good, bad)


@pytest.mark.parametrize(
    "factory", [lambda d: np.zeros((2, 2, 1), dtype=np.float32), lambda d: np.zeros((d, d + 1), dtype=np.float32)]
)
def test_ndim_and_shape_mismatch_rejected(factory):
    good = np.zeros((2, 2), dtype=np.float32)
    bad = factory(2)
    for pos in range(3):
        args = [good, good, good]
        args[pos] = bad
        with pytest.raises(ValueError):
            reciprocal_consensus_pairs(*args)


@pytest.mark.parametrize("value", [np.nan, np.inf])
def test_non_finite_rejected_in_every_position(value):
    good = np.zeros((2, 2), dtype=np.float32)
    for pos in range(3):
        bad = good.copy()
        bad[1, 1] = value
        args = [good, good, good]
        args[pos] = bad
        with pytest.raises(ValueError):
            reciprocal_consensus_pairs(*args)


@pytest.mark.parametrize("shape", [(2049, 1), (1, 2049)])
def test_axis_cap_rejected(shape):
    a = np.zeros(shape, dtype=np.float32)
    with pytest.raises(ValueError):
        reciprocal_consensus_pairs(a, a, a)


def test_product_cap_rejected_with_legal_axes():
    a = np.zeros((1001, 1000), dtype=np.float32)
    with pytest.raises(ValueError):
        reciprocal_consensus_pairs(a, a, a)


def test_subclass_input_rejected():
    class MyArray(np.ndarray):
        pass

    good = np.zeros((2, 2), dtype=np.float32)
    sub = good.view(MyArray)
    with pytest.raises(ValueError):
        reciprocal_consensus_pairs(sub, good, good)
