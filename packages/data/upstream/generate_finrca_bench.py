#!/usr/bin/env python3
"""Command-line entry point for reproducible FinRCA-Bench generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import load_config
from src.pipeline import generate_benchmark


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the FinRCA-Bench v1 synthetic benchmark")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML configuration")
    parser.add_argument("--seed", type=int, help="Override the configured deterministic seed")
    parser.add_argument("--scale", choices=["small"], help="Use a development scale preset")
    parser.add_argument("--output-dir", help="Override the configured output directory")
    parser.add_argument("--validate-only", action="store_true", help="Generate and validate in memory without writing data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config, seed=args.seed, scale=args.scale)
    if args.output_dir:
        config["output_dir"] = args.output_dir
    _, report = generate_benchmark(config, write_output=not args.validate_only)
    summary = {
        "quality_gate_passed": report["quality_gate_passed"],
        "dataset_hash": report["dataset_hash"],
        "cases": report["number_of_cases"],
        "output_dir": None if args.validate_only else str(Path(config["output_dir"]).resolve()),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["quality_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

