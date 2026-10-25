"""Frozen token accounting for embedding safety and request preflight."""

from __future__ import annotations

import math
import statistics
from functools import lru_cache
from typing import Iterable


@lru_cache(maxsize=1)
def _embedding_encoding():
    try:
        import tiktoken
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError(
            "tiktoken is required for frozen cl100k_base corpus token auditing; install requirements.txt"
        ) from exc
    return tiktoken.get_encoding("cl100k_base")


def embedding_token_count(text: str) -> int:
    return len(_embedding_encoding().encode(text))


def conservative_generation_tokens(*texts: str) -> int:
    return math.ceil(sum(len(text) for text in texts) / 3)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def token_summary(values: Iterable[int]) -> dict[str, float | int]:
    observed = list(values)
    return {
        "minimum_tokens": min(observed, default=0),
        "median_tokens": statistics.median(observed) if observed else 0,
        "p95_tokens": percentile([float(value) for value in observed], 0.95),
        "maximum_tokens": max(observed, default=0),
        "total_tokens": sum(observed),
    }

