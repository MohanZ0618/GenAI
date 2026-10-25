from __future__ import annotations

import unittest

from src.config import load_config
from src.pipeline import generate_benchmark


class ReproducibilityTests(unittest.TestCase):
    def test_same_seed_same_dataset_hash(self) -> None:
        config = load_config("config.yaml", seed=42, scale="small")
        _, first = generate_benchmark(config, write_output=False)
        _, second = generate_benchmark(config, write_output=False)
        self.assertEqual(first["dataset_hash"], second["dataset_hash"])

    def test_different_seed_changes_records(self) -> None:
        _, first = generate_benchmark(load_config("config.yaml", seed=42, scale="small"), write_output=False)
        _, second = generate_benchmark(load_config("config.yaml", seed=43, scale="small"), write_output=False)
        self.assertNotEqual(first["dataset_hash"], second["dataset_hash"])
        self.assertTrue(first["quality_gate_passed"])
        self.assertTrue(second["quality_gate_passed"])


if __name__ == "__main__":
    unittest.main()

