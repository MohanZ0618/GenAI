from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.corpus import FrozenCorpus, build_frozen_corpus


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def frozen_corpus(root: Path) -> FrozenCorpus:
    return build_frozen_corpus(root / "data/benchmark/full")
