import copy
import random

import numpy as np
import pytest
import torch

from biohub.association_augmentation import augment_batches, flip_bits, flip_xy


def batch():
    imgs = torch.zeros(1, 2, 3, 5, 7)
    imgs[0, 0, 1, 2, 3] = 8
    imgs[0, 1, 2, 1, 4] = 9
    coords = torch.zeros(1, 2, 3, 3)
    coords[0, 0, 0] = torch.tensor([1., 2., 3.])
    coords[0, 1, 0] = torch.tensor([2., 1., 4.])
    masks = torch.tensor([[[True, True, False], [True, True, False]]])
    targets = torch.zeros(1, 1, 3, 3)
    targets[0, 0, 0, :2] = 1  # A division: node identity/order must survive.
    return {"imgs": imgs, "coords": coords, "masks": masks, "targets": targets,
            "voxel_size": torch.tensor([[2., 1., 1.]]), "downsample": torch.tensor([[1., 4., 4.]]),
            "image_shape": torch.tensor([[100, 3, 5, 7]])}


@pytest.mark.parametrize("fy,fx", [(False, False), (True, False), (False, True), (True, True)])
def test_image_coordinate_alignment_inverse_padding_and_labels(fy, fx):
    original = batch()
    snapshot = copy.deepcopy(original)
    out = flip_xy(original, flip_y=fy, flip_x=fx)
    for t, value in ((0, 8), (1, 9)):
        z, y, x = out["coords"][0, t, 0].long().tolist()
        assert out["imgs"][0, t, z, y, x] == value
    for key in ("masks", "targets", "voxel_size", "downsample", "image_shape"):
        assert torch.equal(out[key], original[key])
    assert torch.equal(out["coords"][~out["masks"]], original["coords"][~original["masks"]])
    restored = flip_xy(out, flip_y=fy, flip_x=fx)
    for key in original:
        assert torch.equal(original[key], snapshot[key])
        assert torch.equal(restored[key], original[key])


def test_fractional_border_coordinates_are_not_clipped_or_dropped():
    b = batch()
    b["coords"][0, 0, 0, 1] = 4.75
    out = flip_xy(b, flip_y=True, flip_x=False)
    assert out["coords"][0, 0, 0, 1] == -.75
    assert torch.equal(out["masks"], b["masks"])
    assert torch.equal(flip_xy(out, flip_y=True, flip_x=False)["coords"], b["coords"])


def test_stateless_schedule_and_rng_preservation():
    before = torch.random.get_rng_state().clone()
    python_before, numpy_before = random.getstate(), np.random.get_state()
    identities = [f"video:{i:03d}" for i in range(100)]
    first = [flip_bits(20260922, 1, i) for i in identities]
    assert set(first) == {(False, False), (True, False), (False, True), (True, True)}
    assert first != [flip_bits(20260922, 2, i) for i in identities]
    assert first == [flip_bits(20260922, 1, i) for i in identities]
    b = batch()
    items = [("video", i, b) for i in identities]
    full = list(augment_batches(items, seed=20260922, epoch=1))
    resumed = list(augment_batches(items[41:], seed=20260922, epoch=1))
    for a, c in zip(full[41:], resumed, strict=True):
        assert a[:2] == c[:2]
        assert torch.equal(a[2]["coords"], c[2]["coords"])
    assert torch.equal(before, torch.random.get_rng_state())
    assert random.getstate() == python_before
    numpy_after = np.random.get_state()
    assert numpy_before[0] == numpy_after[0]
    assert np.array_equal(numpy_before[1], numpy_after[1])
    assert numpy_before[2:] == numpy_after[2:]


def test_restored_sampler_reproduces_complete_next_epoch_flip_sequence():
    generator = torch.Generator().manual_seed(20260922)
    identities = [f"video:{i:03d}" for i in range(785)]
    torch.randperm(785, generator=generator)  # Completed absolute epoch 1.
    state = generator.get_state().clone()

    def sequence(rng, epoch):
        return [(identities[i], *flip_bits(20260922, epoch, identities[i]))
                for i in torch.randperm(785, generator=rng).tolist()]

    expected = sequence(generator, 2)
    restored = torch.Generator()
    restored.set_state(state)
    assert sequence(restored, 2) == expected


@pytest.mark.parametrize("args", [(True, 1, "a"), (-1, 1, "a"), (0, True, "a"),
                                 (0, 0, "a"), (0, 1, ""), (0, 1, None)])
def test_invalid_schedule(args):
    with pytest.raises(ValueError):
        flip_bits(*args)


def test_invalid_batch_and_flags():
    b = batch()
    with pytest.raises(ValueError):
        flip_xy(b, flip_y=1, flip_x=False)
    b["coords"][0, 0, 0, 0] = float("nan")
    with pytest.raises(ValueError):
        flip_xy(b, flip_y=True, flip_x=False)
