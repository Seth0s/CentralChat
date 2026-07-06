"""Cliente HTTP L7 ao model-router (timeouts + erros normalizados)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.model_router_http_client import router_get_json


class TestModelRouterHttpClient(unittest.TestCase):
    @patch("app.model_router_http_client.router_base_url", return_value="")
    def test_no_url(self, _mock_base: MagicMock) -> None:
        data, err = router_get_json("/config")
        self.assertIsNone(data)
        self.assertEqual(err, "no_url")

    @patch("app.model_router_http_client.httpx.Client")
    @patch("app.model_router_http_client.router_base_url", return_value="http://mr")
    def test_success_dict(self, _mock_base: MagicMock, ClientMock: MagicMock) -> None:
        inst = ClientMock.return_value.__enter__.return_value
        inst.get.return_value = httpx.Response(200, json={"profiles": ["x"]})
        data, err = router_get_json("/config")
        self.assertIsNone(err)
        self.assertEqual(data, {"profiles": ["x"]})
        inst.get.assert_called_once()
        args, kwargs = inst.get.call_args
        self.assertTrue(args[0].endswith("/config"))

    @patch("app.model_router_http_client.httpx.Client")
    @patch("app.model_router_http_client.router_base_url", return_value="http://mr")
    def test_non_200(self, _mock_base: MagicMock, ClientMock: MagicMock) -> None:
        inst = ClientMock.return_value.__enter__.return_value
        inst.get.return_value = httpx.Response(503, text="no")
        data, err = router_get_json("/openai/models")
        self.assertIsNone(data)
        self.assertEqual(err, "http_503")

    @patch("app.model_router_http_client.httpx.Client")
    @patch("app.model_router_http_client.router_base_url", return_value="http://mr")
    def test_timeout_maps_router_timeout(self, _mock_base: MagicMock, ClientMock: MagicMock) -> None:
        inst = ClientMock.return_value.__enter__.return_value
        inst.get.side_effect = httpx.ReadTimeout("t", request=MagicMock())
        data, err = router_get_json("/config")
        self.assertIsNone(data)
        self.assertEqual(err, "router_timeout")

    @patch("app.model_router_http_client.httpx.Client")
    @patch("app.model_router_http_client.router_base_url", return_value="http://mr")
    def test_invalid_json_body(self, _mock_base: MagicMock, ClientMock: MagicMock) -> None:
        inst = ClientMock.return_value.__enter__.return_value
        inst.get.return_value = httpx.Response(200, content=b"not json")
        data, err = router_get_json("/config")
        self.assertIsNone(data)
        self.assertEqual(err, "invalid_json")

    @patch("app.model_router_http_client.httpx.Client")
    @patch("app.model_router_http_client.router_base_url", return_value="http://mr")
    def test_params_forwarded(self, _mock_base: MagicMock, ClientMock: MagicMock) -> None:
        inst = ClientMock.return_value.__enter__.return_value
        inst.get.return_value = httpx.Response(200, json={"models": []})
        _, err = router_get_json("/openai/models", params={"profile": "p", "refresh": "true"})
        self.assertIsNone(err)
        _args, kwargs = inst.get.call_args
        self.assertEqual(kwargs.get("params"), {"profile": "p", "refresh": "true"})


if __name__ == "__main__":
    unittest.main()
