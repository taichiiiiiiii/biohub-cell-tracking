"""Qwen-authored persistent ordering for the preregistered step-budget run.

Parent integration tightens integer/device validation. This component neither
trains a model nor changes the historical epoch-based candidate contract.
"""
import torch


class AssociationStepSampler:
    def __init__(self, size: int, seed: int):
        if type(size) is not int or size <= 0:
            raise ValueError("size must be a positive integer")
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("seed must be a nonnegative signed 64-bit integer")
        self._size = size
        self._seed = seed
        self._generator = torch.Generator(device="cpu").manual_seed(seed)
        self._permutation = torch.randperm(size, generator=self._generator)
        self._cursor = self._cycle = self._total_consumed = 0

    def next_indices(self, count: int) -> torch.Tensor:
        if type(count) is not int or count <= 0:
            raise ValueError("count must be a positive integer")
        result = []
        remaining = count
        while remaining:
            take = min(remaining, self._size - self._cursor)
            result.append(self._permutation[self._cursor:self._cursor + take])
            self._cursor += take
            self._total_consumed += take
            remaining -= take
            if self._cursor == self._size:
                self._cursor = 0
                self._cycle += 1
                self._permutation = torch.randperm(self._size, generator=self._generator)
        return torch.cat(result)

    def state_dict(self) -> dict:
        return {
            "size": self._size, "seed": self._seed,
            "permutation": self._permutation.clone(), "cursor": self._cursor,
            "cycle": self._cycle, "total_consumed": self._total_consumed,
            "generator_state": self._generator.get_state().clone(),
        }

    def load_state_dict(self, state: dict) -> None:
        required = {"size", "seed", "permutation", "cursor", "cycle",
                    "total_consumed", "generator_state"}
        if not isinstance(state, dict) or set(state) != required:
            raise ValueError("Malformed sampler state")
        size, seed = state["size"], state["seed"]
        cursor, cycle, total = state["cursor"], state["cycle"], state["total_consumed"]
        perm, rng = state["permutation"], state["generator_state"]
        if type(size) is not int or size != self._size:
            raise ValueError("Size mismatch")
        if type(seed) is not int or seed != self._seed:
            raise ValueError("Seed mismatch")
        if (not isinstance(perm, torch.Tensor) or perm.device.type != "cpu"
                or perm.layout != torch.strided or perm.dtype != torch.int64
                or perm.shape != (size,)
                or not torch.equal(torch.sort(perm).values, torch.arange(size))):
            raise ValueError("Invalid permutation")
        if (any(type(v) is not int for v in (cursor, cycle, total))
                or not 0 <= cursor < size or cycle < 0 or total != cycle * size + cursor):
            raise ValueError("Incoherent sampler counters")
        if (not isinstance(rng, torch.Tensor) or rng.device.type != "cpu"
                or rng.layout != torch.strided or rng.dtype != torch.uint8 or rng.ndim != 1):
            raise ValueError("Invalid generator state")
        new_generator = torch.Generator(device="cpu")
        try:
            new_generator.set_state(rng.clone())
        except (RuntimeError, TypeError) as error:
            raise ValueError("Invalid generator state") from error
        expected_generator = torch.Generator(device="cpu").manual_seed(seed)
        for _ in range(cycle + 1):
            expected_permutation = torch.randperm(size, generator=expected_generator)
        if (not torch.equal(perm, expected_permutation)
                or not torch.equal(rng, expected_generator.get_state())):
            raise ValueError("State does not match the declared seeded permutation stream")
        new_permutation = perm.clone()
        self._permutation = new_permutation
        self._cursor, self._cycle, self._total_consumed = cursor, cycle, total
        self._generator = new_generator
