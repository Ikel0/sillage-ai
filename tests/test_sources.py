from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sillage.sources import github_status_snapshot


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class PublicSourceTests(unittest.TestCase):
    @patch("sillage.sources.urlopen")
    def test_parses_public_status_payload(self, mocked_urlopen: object) -> None:
        mocked_urlopen.return_value = _Response(
            {"status": {"indicator": "none", "description": "All Systems Operational"}}
        )

        snapshot = github_status_snapshot()

        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["indicator"], "none")
        self.assertEqual(snapshot["description"], "All Systems Operational")

    @patch("sillage.sources.urlopen", side_effect=TimeoutError)
    def test_degrades_gracefully_when_public_source_is_unavailable(self, _mocked_urlopen: object) -> None:
        snapshot = github_status_snapshot()

        self.assertFalse(snapshot["ok"])
        self.assertEqual(snapshot["indicator"], "unavailable")
