"""Cache do catálogo vendor no orquestrador."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app import vendor_catalog_cache as vcc


class TestVendorCatalogCache(unittest.TestCase):
    def tearDown(self) -> None:
        vcc._cache.clear()

    @patch("app.vendor_catalog_cache.fetch_vendor_catalog_from_router")
    def test_refresh_bypasses_cache(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = ([{"id": "a", "label": "A"}], None)
        r1, e1 = vcc.get_vendor_catalog_cached("p1", refresh=True)
        self.assertEqual(e1, None)
        self.assertEqual(len(r1 or []), 1)
        mock_fetch.return_value = ([{"id": "b", "label": "B"}], None)
        r2, e2 = vcc.get_vendor_catalog_cached("p1", refresh=True)
        self.assertEqual(r2[0]["id"], "b")
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("app.vendor_catalog_cache.fetch_vendor_catalog_from_router")
    @patch("app.vendor_catalog_cache.VENDOR_CATALOG_CACHE_TTL_SECONDS", 3600)
    def test_second_call_same_profile_uses_cache(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = ([{"id": "a", "label": "A"}], None)
        vcc.get_vendor_catalog_cached("p2", refresh=False)
        vcc.get_vendor_catalog_cached("p2", refresh=False)
        self.assertEqual(mock_fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
