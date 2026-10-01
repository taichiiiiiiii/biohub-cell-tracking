import json

import pytest

from scripts import local_train_unet_transformer as adapter


def test_auto_prefers_mps_without_cuda(monkeypatch):
    monkeypatch.setattr(adapter.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(adapter.torch.backends.mps, "is_available", lambda: True)
    assert adapter.select_device("auto").type == "mps"
    assert adapter.select_device("cpu").type == "cpu"
    with pytest.raises(ValueError, match="no fallback"):
        adapter.select_device("cuda")


def test_actual_source_contract_compiles_without_mutating_torch():
    sync = adapter.torch.cuda.synchronize
    adapter.adapted_code(adapter.TRAINER.read_text(), str(adapter.TRAINER))
    assert adapter.torch.cuda.synchronize is sync


def test_adaptation_rejects_source_drift():
    source = adapter.TRAINER.read_text().replace("torch.cuda.synchronize()", "pass", 1)
    with pytest.raises(ValueError, match="contract changed"):
        adapter.adapted_code(source, "test.py")


def test_adaptation_uses_selected_device_and_barrier():
    source = '''
def train():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return device
def train_epoch():
    if False:
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    torch.cuda.synchronize()
    torch.cuda.synchronize()
    torch.cuda.synchronize()
'''
    calls = []
    namespace = {"_local_device": "selected", "_local_synchronize": lambda: calls.append(1)}
    exec(adapter.adapted_code(source, "test.py"), namespace)
    assert namespace["train"]() == "selected"
    namespace["train_epoch"]()
    assert calls == [1, 1, 1]


def test_candidate_launch_is_refused(monkeypatch):
    monkeypatch.setattr(adapter.sys, "argv", ["local_train", "--device", "cpu"])
    with pytest.raises(SystemExit) as error:
        adapter.main()
    assert error.value.code == 2


@pytest.mark.parametrize("method,epochs,iters", [
    ("production", "1", "1"),
    ("local_diagnostic_../other", "1", "1"),
    ("local_diagnostic_test", "4", "1"),
    ("local_diagnostic_test", "1", "11"),
])
def test_diagnostic_scope_is_bounded(monkeypatch, method, epochs, iters):
    monkeypatch.setattr(adapter.sys, "argv", [
        "local_train", "--device", "cpu", "--diagnostic", "--method", method,
        "--epochs", epochs, "--max-iters", iters,
        "--splits", "unused.json",
    ])
    with pytest.raises(SystemExit) as error:
        adapter.main()
    assert error.value.code == 2


def test_split_accepts_disjoint_diagnostic_videos(tmp_path):
    path = tmp_path / "split.json"
    split = {"train": ["44b6_a", "6bba_b"], "test": ["44b6_c", "6bba_d"]}
    path.write_text(json.dumps([split]))
    assert adapter.validate_split(path, 0) == split


@pytest.mark.parametrize("train,val", [
    (["44b6_a"], ["44b6_a.zarr"]),
    (["44b6_a", "44b6_a.zarr"], ["6bba_b"]),
    ([], ["6bba_b"]),
    (["../44b6_a"], ["6bba_b"]),
    (["unknown_a"], ["6bba_b"]),
])
def test_split_rejects_invalid_or_overlapping_videos(tmp_path, train, val):
    path = tmp_path / "split.json"
    path.write_text(json.dumps([{"train": train, "test": val}]))
    with pytest.raises(ValueError):
        adapter.validate_split(path, 0)


@pytest.fixture
def preserve_rng():
    python_state = adapter.random.getstate()
    numpy_state = adapter.np.random.get_state()
    torch_state = adapter.torch.random.get_rng_state()
    try:
        yield
    finally:
        adapter.random.setstate(python_state)
        adapter.np.random.set_state(numpy_state)
        adapter.torch.random.set_rng_state(torch_state)


@pytest.mark.parametrize("bad_seed", [-1, 2**32, True, False, 1.5, "0", None])
def test_seed_rng_rejects_invalid_before_mutation(monkeypatch, bad_seed):
    monkeypatch.setattr(adapter.random, "seed", lambda *_: pytest.fail("RNG mutated before validation"))
    with pytest.raises((TypeError, ValueError)):
        adapter.seed_rng(bad_seed, "cpu")


@pytest.mark.parametrize("device", ["meta", 123])
def test_seed_rng_rejects_invalid_device_before_mutation(monkeypatch, device):
    monkeypatch.setattr(adapter.random, "seed", lambda *_: pytest.fail("RNG mutated before validation"))
    with pytest.raises((TypeError, ValueError)):
        adapter.seed_rng(0, device)


@pytest.mark.parametrize("seed", [0, 12345, 2**32 - 1])
def test_cpu_seed_repeatability_without_accelerator(monkeypatch, preserve_rng, seed):
    torch = adapter.torch
    monkeypatch.setattr(torch.cuda, "manual_seed_all", lambda *_: pytest.fail("CUDA touched"))
    monkeypatch.setattr(torch.mps, "manual_seed", lambda *_: pytest.fail("MPS touched"))
    deterministic_before = torch.are_deterministic_algorithms_enabled()

    def sample():
        model = torch.nn.Sequential(torch.nn.Linear(8, 4), torch.nn.Dropout(0.5))
        assert model.training
        return adapter.random.random(), adapter.np.random.rand(), model(torch.randn(2, 8))

    policy = adapter.seed_rng(seed, "cpu")
    first = sample()
    adapter.seed_rng(seed, "cpu")
    second = sample()
    assert first[:2] == second[:2]
    assert torch.equal(first[2], second[2])
    assert policy == {"seed": seed, "python": True, "numpy": True, "torch_cpu": True,
                      "accelerator": None, "full_determinism": False}
    assert torch.are_deterministic_algorithms_enabled() == deterministic_before


@pytest.mark.parametrize("device", ["cuda", "mps"])
def test_seed_routes_only_to_selected_accelerator(monkeypatch, preserve_rng, device):
    calls = []
    monkeypatch.setattr(adapter.torch.cuda, "manual_seed_all", lambda seed: calls.append(("cuda", seed)))
    monkeypatch.setattr(adapter.torch.mps, "manual_seed", lambda seed: calls.append(("mps", seed)))
    policy = adapter.seed_rng(7, device)
    assert calls == [(device, 7)]
    assert policy["accelerator"] == device


def test_check_device_does_not_seed(monkeypatch):
    monkeypatch.setattr(adapter, "seed_rng", lambda *_: pytest.fail("check-device seeded RNG"))
    monkeypatch.setattr(adapter.sys, "argv", ["local_train", "--device", "cpu", "--check-device", "--seed", "42"])
    adapter.main()
