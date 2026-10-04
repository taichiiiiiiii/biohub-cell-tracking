import pytest
import torch

from biohub.association_step_sampler import AssociationStepSampler


def assert_state_equal(left, right):
    assert left.keys() == right.keys()
    for key in left:
        if isinstance(left[key], torch.Tensor):
            assert torch.equal(left[key], right[key])
        else:
            assert left[key] == right[key]


def test_segmented_budget_matches_continuous_and_covers_cycles():
    continuous = AssociationStepSampler(3168, 20260922)
    segmented = AssociationStepSampler(3168, 20260922)
    expected = continuous.next_indices(7850)
    actual = torch.cat([segmented.next_indices(785) for _ in range(10)])
    assert torch.equal(actual, expected)
    for start in (0, 3168):
        assert torch.equal(actual[start:start + 3168].sort().values, torch.arange(3168))
    assert_state_equal(continuous.state_dict(), segmented.state_dict())
    assert segmented.state_dict()["total_consumed"] == 7850


@pytest.mark.parametrize("consumed", [1, 784, 785, 3168, 3925])
def test_serialized_resume_crosses_cycle_exactly(consumed, tmp_path):
    original = AssociationStepSampler(3168, 42)
    original.next_indices(consumed)
    path = tmp_path / "sampler.pt"
    torch.save(original.state_dict(), path)
    resumed = AssociationStepSampler(3168, 42)
    resumed.load_state_dict(torch.load(path, weights_only=True))
    assert torch.equal(original.next_indices(6500), resumed.next_indices(6500))
    assert_state_equal(original.state_dict(), resumed.state_dict())


def test_state_and_loaded_input_are_not_aliased():
    sampler = AssociationStepSampler(8, 42)
    sampler.next_indices(3)
    original = sampler.state_dict()
    exported = sampler.state_dict()
    exported["permutation"].fill_(99)
    exported["generator_state"].zero_()
    assert_state_equal(original, sampler.state_dict())
    resumed = AssociationStepSampler(8, 42)
    resumed.load_state_dict(original)
    copied = resumed.state_dict()
    original["permutation"].fill_(99)
    original["generator_state"].zero_()
    assert_state_equal(copied, resumed.state_dict())


def test_bad_state_is_rejected_atomically():
    sampler = AssociationStepSampler(8, 42)
    sampler.next_indices(3)
    before = sampler.state_dict()
    corruptions = [
        {}, {**before, "extra": 1},
        *[{**before, key: value} for key, value in [
            ("size", True), ("size", 9), ("seed", True), ("seed", 43),
            ("cursor", -1), ("cursor", 8), ("cursor", True),
            ("cycle", -1), ("cycle", False), ("total_consumed", 4),
            ("total_consumed", True),
            ("permutation", torch.zeros(8, dtype=torch.int64)),
            ("permutation", torch.arange(8, dtype=torch.float32)),
            ("generator_state", torch.zeros(10, dtype=torch.uint8)),
            ("generator_state", torch.zeros(10)),
        ]],
    ]
    for bad in corruptions:
        with pytest.raises(ValueError):
            sampler.load_state_dict(bad)
        assert_state_equal(before, sampler.state_dict())


def test_valid_tensors_from_wrong_stream_are_rejected():
    sampler = AssociationStepSampler(8, 42)
    sampler.next_indices(3)
    before = sampler.state_dict()
    different_seed = AssociationStepSampler(8, 43).state_dict()
    different_cycle = AssociationStepSampler(8, 42)
    different_cycle.next_indices(8)
    for key, foreign in (("permutation", different_seed),
                         ("generator_state", different_cycle.state_dict())):
        with pytest.raises(ValueError, match="seeded permutation stream"):
            sampler.load_state_dict({**before, key: foreign[key]})
        assert_state_equal(before, sampler.state_dict())


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "1", None])
def test_bad_size_and_count(value):
    with pytest.raises(ValueError):
        AssociationStepSampler(value, 42)
    sampler = AssociationStepSampler(1, 42)
    before = sampler.state_dict()
    with pytest.raises(ValueError):
        sampler.next_indices(value)
    assert_state_equal(before, sampler.state_dict())


@pytest.mark.parametrize("seed", [True, -1, 2**63, "42"])
def test_bad_seed(seed):
    with pytest.raises(ValueError):
        AssociationStepSampler(1, seed)
