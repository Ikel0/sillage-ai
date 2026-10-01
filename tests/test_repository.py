from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from sillage import repository


class RegistryValidationTests(unittest.TestCase):
    def test_registry_exposes_a_stable_readiness_fingerprint(self) -> None:
        outcome = repository.validate_registry()

        self.assertEqual(outcome["status"], "ready")
        self.assertEqual(outcome["contracts"], 3)
        self.assertEqual(len(outcome["registry_fingerprint"]), 64)

    def test_contract_without_an_owner_is_rejected_before_triage(self) -> None:
        invalid_contracts = deepcopy(repository.contracts())
        invalid_contracts[0]["owner"] = ""

        with patch("sillage.repository.contracts", return_value=invalid_contracts):
            with self.assertRaises(repository.RegistryValidationError):
                repository.validate_registry()
