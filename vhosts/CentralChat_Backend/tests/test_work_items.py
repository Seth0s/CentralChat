"""H1 — work_items CRUD helpers."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app.work_queue as wq


class WorkQueueTest(unittest.TestCase):
    def test_create_requires_db(self) -> None:
        with patch.object(wq, "memory_db_enabled", return_value=False):
            with self.assertRaises(RuntimeError):
                wq.create_work_item(title="Fix login bug")

    def test_list_empty_when_db_disabled(self) -> None:
        with patch.object(wq, "memory_db_enabled", return_value=False):
            items = wq.list_work_items()
        self.assertEqual(items, [])

    def test_next_work_item_id_format(self) -> None:
        with patch.object(wq, "memory_db_enabled", return_value=True):
            with patch.object(wq, "ensure_work_items_schema"):
                mock_conn = MagicMock()
                mock_cur = MagicMock()
                mock_cur.fetchone.return_value = (3,)
                mock_conn.cursor.return_value.__enter__.return_value = mock_cur
                with patch.object(wq, "connect_pg") as mock_pg:
                    mock_pg.return_value.__enter__.return_value = mock_conn
                    wid = wq._next_work_item_id(tenant_id="acme")
        self.assertEqual(wid, "WI-3")

    def test_record_work_item_event_inserts_tenant_scoped_row(self) -> None:
        with patch.object(wq, "memory_db_enabled", return_value=True):
            with patch.object(wq, "ensure_work_items_schema"):
                with patch.object(wq, "get_current_sub", return_value="00000000-0000-4000-8000-000000000001"):
                    mock_conn = MagicMock()
                    mock_cur = MagicMock()
                    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
                    with patch.object(wq, "connect_pg") as mock_pg:
                        mock_pg.return_value.__enter__.return_value = mock_conn
                        wq._record_work_item_event(
                            tenant_id="acme",
                            work_item_id="WI-1",
                            event_type="status_changed",
                            from_status="open",
                            to_status="review",
                        )

        mock_pg.assert_called_with(tenant_id="acme")
        sql, params = mock_cur.execute.call_args.args
        self.assertIn("INSERT INTO work_item_events", sql)
        self.assertEqual(params[0], "acme")
        self.assertEqual(params[1], "WI-1")
        self.assertEqual(params[3], "status_changed")

    def test_row_to_item_maps_fields(self) -> None:
        row = (
            "WI-default-1",
            "default",
            "Title",
            "Desc",
            "open",
            "normal",
            None,
            "00000000-0000-4000-8000-000000000099",
            "/ws",
            "repo",
            "sess12345678",
            "[]",
            ["bug"],
            "manual",
            None,
            None,
            "2026-06-14T12:00:00+00:00",
            "2026-06-14T12:00:00+00:00",
            None,
        )
        item = wq._row_to_item(row)
        self.assertEqual(item["id"], "WI-default-1")
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["labels"], ["bug"])


if __name__ == "__main__":
    unittest.main()
