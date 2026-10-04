"""Tests for biohub.appearance_cost.appearance_penalty."""

import numpy as np
import pytest

from biohub.appearance_cost import appearance_penalty

E0 = np.zeros(32, dtype=np.float32)
E0[0] = 1.0
E1 = np.zeros(32, dtype=np.float32)
E1[1] = 1.0
NE0 = -E0


def stack(rows):
    return np.asarray(rows, dtype=np.float32)


def call(src, tgt, ssrc=None, stgt=None):
    ssrc = src if ssrc is None else ssrc
    stgt = tgt if stgt is None else stgt
    return appearance_penalty(stack(src), stack(tgt), stack(ssrc), stack(stgt))


def test_identical_orthogonal_opposite():
    c = call([E0, E0, E0], [E0, E1, NE0])
    assert c.shape == (3, 3)
    assert c.dtype == np.float64
    assert np.allclose(c[0], [0.0, 1.0, 2.0])


def test_seedwise_normalization_mean():
    c = appearance_penalty(stack([E0]), stack([E0]),
                           stack([E0]), stack([NE0]))
    assert c.shape == (1, 1)
    assert np.allclose(c, [[1.0]])


def test_norm_scale_invariance():
    a = call([E0], [E1])
    b = call([5.0 * E0], [0.25 * E1])
    assert np.allclose(a, b)


def test_inputs_not_mutated():
    src, tgt = stack([E0, E1]), stack([NE0])
    s_copy, t_copy = src.copy(), tgt.copy()
    appearance_penalty(src, tgt, src, tgt)
    assert np.array_equal(src, s_copy)
    assert np.array_equal(tgt, t_copy)


@pytest.mark.parametrize("row", [
    np.zeros(32, dtype=np.float32),
    np.full(32, np.nan, dtype=np.float32),
    np.full(32, np.inf, dtype=np.float32)])
def test_zero_nan_inf_rejected(row):
    with pytest.raises(ValueError):
        call([row], [E0])


def test_dtype_and_dimension_rejected():
    with pytest.raises(ValueError):
        appearance_penalty(stack([E0]).astype(np.float64), stack([E0]),
                           stack([E0]), stack([E0]))
    with pytest.raises(ValueError):
        call([E0[:16]], [E1[:16]])


def test_mismatched_counts_rejected():
    with pytest.raises(ValueError):
        appearance_penalty(stack([E0]), stack([E0]),
                           stack([E0, E1]), stack([E0]))
    with pytest.raises(ValueError):
        appearance_penalty(stack([E0]), stack([E0, E1]),
                           stack([E0]), stack([E0]))


def test_output_range_and_empty_side():
    tgt = stack([NE0, 0.3 * E0 + 0.7 * E1])
    c = call(stack([E0, E1]), tgt)
    assert c.shape == (2, 2)
    assert np.all((c >= 0.0) & (c <= 2.0))
    empty = np.zeros((0, 32), dtype=np.float32)
    e = appearance_penalty(empty, empty, empty.copy(), empty.copy())
    assert e.shape == (0, 0)
    assert e.dtype == np.float64


def test_rectangular_readonly():
    src = np.stack([E0])
    tgt = np.stack([E0, E1, NE0])
    src.setflags(write=False)
    tgt.setflags(write=False)

    src_copy = src.copy()
    tgt_copy = tgt.copy()

    cost = appearance_penalty(src, tgt, src, tgt)

    assert isinstance(cost, np.ndarray)
    assert cost.shape == (1, 3)
    assert cost.dtype == np.float64
    np.testing.assert_allclose(cost, np.array([[0.0, 1.0, 2.0]], dtype=np.float64))

    np.testing.assert_array_equal(src, src_copy)
    np.testing.assert_array_equal(tgt, tgt_copy)


def test_empty_source_nonempty_target():
    src = np.zeros((0, 32), dtype=np.float32)
    tgt = np.stack([E1, NE0])

    cost = appearance_penalty(src, tgt, src, tgt)

    assert isinstance(cost, np.ndarray)
    assert cost.shape == (0, 2)
    assert cost.dtype == np.float64


def test_invalid_target_container():
    src = np.stack([E0])
    bad = [E0.tolist(), E1.tolist()]

    with pytest.raises(ValueError):
        appearance_penalty(src, src, bad, bad)
