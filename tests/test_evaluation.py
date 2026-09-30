from __future__ import annotations

import unittest

from sillage.evaluation import evaluate_grounded_triage


class EvaluationSuiteTests(unittest.TestCase):
    def test_golden_suite_is_green(self) -> None:
        outcome = evaluate_grounded_triage()

        self.assertEqual(outcome["passed"], outcome["total"])
        self.assertEqual(outcome["score"], 1.0)
        self.assertEqual(len(outcome["cases"]), 3)
