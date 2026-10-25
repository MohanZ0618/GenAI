"""Configuration loading and scale preset handling."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


SMALL_SCALE: dict[str, int] = {
    "vendors": 40,
    "employees": 24,
    "purchase_orders": 160,
    "invoices": 240,
    "payments": 180,
    "cases_per_failure": 2,
    "non_failure_cases": 20,
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path, seed: int | None = None, scale: str | None = None) -> dict[str, Any]:
    """Load YAML configuration and apply CLI overrides."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file does not exist: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Configuration root must be a mapping")
    config = _deep_merge({}, loaded)
    if seed is not None:
        config["seed"] = seed
    if scale is not None:
        if scale != "small":
            raise ValueError(f"Unsupported scale preset: {scale!r}; expected 'small'")
        config["scale"] = _deep_merge(config.get("scale", {}), SMALL_SCALE)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    """Fail early for configuration values that cannot produce a valid benchmark."""
    required = {"seed", "output_dir", "date_range", "scale", "generation", "splits"}
    missing = sorted(required - config.keys())
    if missing:
        raise ValueError(f"Missing configuration sections: {missing}")
    start = str(config["date_range"].get("start", ""))
    end = str(config["date_range"].get("end", ""))
    if not start or not end or start >= end:
        raise ValueError("date_range.start must be earlier than date_range.end")
    for name, count in config["scale"].items():
        if not isinstance(count, int) or count < 0:
            raise ValueError(f"scale.{name} must be a non-negative integer")
    for section in ("currencies", "payment_methods"):
        weights = config["generation"].get(section, {})
        if not weights or abs(sum(float(v) for v in weights.values()) - 1.0) > 1e-6:
            raise ValueError(f"generation.{section} weights must sum to 1")
    split_sum = sum(float(config["splits"][key]) for key in ("train", "validation", "test"))
    if abs(split_sum - 1.0) > 1e-6:
        raise ValueError("train/validation/test split weights must sum to 1")

