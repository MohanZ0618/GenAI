"""Frozen, one-shot Standard RAG baseline for FinRCA-Bench."""

from __future__ import annotations

import os

# The frozen exact-flat numerical policy must be established before NumPy loads.
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    # This is a frozen index setting, not a caller-tunable performance option.
    os.environ[_name] = "1"
