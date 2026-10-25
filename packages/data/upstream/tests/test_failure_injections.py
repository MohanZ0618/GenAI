from __future__ import annotations

import unittest
from collections import Counter

from src.config import load_config
from src.failures.registry import FAILURE_INJECTORS
from src.ground_truth.rca_builder import validate_ground_truth
from src.pipeline import generate_benchmark
from src.validation.failure_signatures import validate_failure_signatures, verify_failure_case
from src.validation.financial_rules import validate_bank_statements, validate_gl_balance


class FailureInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config("config.yaml", scale="small")
        cls.artifacts, cls.report = generate_benchmark(cls.config, write_output=False)

    def test_all_fifteen_classes_have_exact_configured_count(self) -> None:
        failures = [case for case in self.artifacts.cases if case["failure_type"] != "NO_FAILURE"]
        counts = Counter(case["failure_type"] for case in failures)
        expected_types = {injector.failure_type for injector in FAILURE_INJECTORS}
        self.assertEqual(set(counts), expected_types)
        self.assertEqual(len(expected_types), 15)
        self.assertTrue(all(value == self.config["scale"]["cases_per_failure"] for value in counts.values()))

    def test_every_failure_signature_is_observable(self) -> None:
        failures = [case for case in self.artifacts.cases if case["failure_type"] != "NO_FAILURE"]
        for case in failures:
            with self.subTest(case_id=case["case_id"], failure_type=case["failure_type"]):
                self.assertTrue(verify_failure_case(self.artifacts.dataset, case))
        self.assertTrue(validate_failure_signatures(self.artifacts.dataset, self.artifacts.cases)["passed"])

    def test_evidence_and_primary_entities_exist(self) -> None:
        result = validate_ground_truth(self.artifacts.dataset, self.artifacts.cases)
        self.assertTrue(result.passed, result.issues[:10])

    def test_each_failure_has_mutation_provenance(self) -> None:
        mutation_case_ids = {str(row["case_id"]) for row in self.artifacts.mutation_log}
        for case in self.artifacts.cases:
            if case["failure_type"] != "NO_FAILURE":
                self.assertIn(str(case["case_id"]), mutation_case_ids)

    def test_injectors_preserve_fundamental_accounting_invariants(self) -> None:
        self.assertEqual(validate_gl_balance(self.artifacts.dataset), [])
        self.assertEqual(validate_bank_statements(self.artifacts.dataset), [])

    def test_hard_negatives_and_question_styles_exist(self) -> None:
        negatives = [case for case in self.artifacts.cases if case["failure_type"] == "NO_FAILURE"]
        self.assertEqual(len(negatives), self.config["scale"]["non_failure_cases"])
        self.assertTrue(any(case["root_cause_category"] == "LEGITIMATE_NET_FEE_ACCOUNTING" for case in negatives))
        by_case = Counter(question["case_id"] for question in self.artifacts.questions)
        self.assertTrue(all(value == 5 for value in by_case.values()))
        no_failure_ids = {case["case_id"] for case in negatives}
        detection = [question for question in self.artifacts.questions if question["case_id"] in no_failure_ids
                     and question["question_style"] == "detection"]
        self.assertTrue(all(not question["expected_answer"]["has_reconciliation_failure"] for question in detection))

    def test_quality_gate_and_leakage_checks_pass(self) -> None:
        self.assertTrue(self.report["quality_gate_passed"])
        self.assertTrue(self.report["train_test_leakage_checks"]["passed"])


if __name__ == "__main__":
    unittest.main()

