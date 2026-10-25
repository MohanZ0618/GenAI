"""Seeded random helpers with skewed business distributions."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Mapping, Sequence, TypeVar

import numpy as np


T = TypeVar("T")


@dataclass
class RandomSource:
    seed: int

    def __post_init__(self) -> None:
        self.py = Random(self.seed)
        self.np = np.random.default_rng(self.seed)

    def weighted_choice(self, weights: Mapping[T, float]) -> T:
        keys = list(weights)
        values = [float(weights[key]) for key in keys]
        return self.py.choices(keys, weights=values, k=1)[0]

    def choice(self, values: Sequence[T]) -> T:
        if not values:
            raise ValueError("Cannot choose from an empty sequence")
        return values[self.py.randrange(len(values))]

    def shuffled(self, values: Sequence[T]) -> list[T]:
        result = list(values)
        self.py.shuffle(result)
        return result

    def lognormal(self, median: float, sigma: float, minimum: float, maximum: float) -> float:
        value = float(self.np.lognormal(mean=np.log(median), sigma=sigma))
        return min(max(value, minimum), maximum)

    def pareto_weights(self, count: int, shape: float = 1.4) -> list[float]:
        values = self.np.pareto(shape, count) + 1.0
        return (values / values.sum()).tolist()

