"""H1b — catalog lifecycle draft → review → published."""
from __future__ import annotations

import unittest

import app.memory_service as ms


class CatalogLifecycleTest(unittest.TestCase):
    def test_valid_lifecycle_set(self) -> None:
        self.assertIn("draft", ms.VALID_LIFECYCLE)
        self.assertIn("review", ms.VALID_LIFECYCLE)
        self.assertIn("published", ms.VALID_LIFECYCLE)

    def test_list_agents_empty_without_db(self) -> None:
        with unittest.mock.patch.object(ms, "memory_db_enabled", return_value=False):
            items = ms.list_team_agents_catalog(status="draft")
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
