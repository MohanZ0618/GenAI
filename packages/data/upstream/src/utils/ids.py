"""Deterministic synthetic identifiers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class IDFactory:
    """Issue stable, non-semantic IDs with per-prefix counters."""

    seed: int
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def next(self, prefix: str, width: int = 7) -> str:
        self.counters[prefix] += 1
        # The seed-derived offset avoids identical IDs across different seeds without encoding labels.
        offset = (abs(self.seed) % 1000) * (10 ** max(width - 3, 1))
        return f"{prefix}_{offset + self.counters[prefix]:0{width}d}"

