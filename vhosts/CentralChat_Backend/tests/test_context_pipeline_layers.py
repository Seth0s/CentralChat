"""ContextPipeline layer assembly (L1–L5)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.context_pipeline import ContextPipeline, ContextWindowManager


def _payload(*, text: str = "hello", history: list | None = None, session_id: str = "") -> SimpleNamespace:
    hist = history or []
    return SimpleNamespace(
        text=text,
        history=[SimpleNamespace(role=m["role"], content=m["content"]) for m in hist],
        chat_session_id=session_id,
        request_id="req-test",
    )


class TestContextPipelineLayers(unittest.TestCase):
    def test_l5_compacts_long_history(self) -> None:
        pipeline = ContextPipeline()
        history = [{"role": "user", "content": f"msg-{i}"} for i in range(80)]
        payload = _payload(history=history, text="next")

        with patch.object(pipeline, "_compose_system_layers") as mock_layers:
            from app.context_pipeline import SystemLayers

            mock_layers.return_value = SystemLayers(messages=[], layers_applied=["L3"])
            assembled = pipeline.assemble(payload, "rid-1")

        self.assertIn("L5", assembled.injection_meta["layers"])
        self.assertTrue(assembled.session_truncated or assembled.ctx_stats.compacted)
        self.assertEqual(assembled.injection_meta["pipeline"], "context_pipeline")

    def test_l2_workspace_injected_when_path_set(self) -> None:
        pipeline = ContextPipeline()
        layers = pipeline._compose_system_layers(
            agent_name=None,
            connector_alive=True,
            mode="cli",
            workspace_path="/tmp/my-repo",
            tenant_id="acme",
        )
        self.assertIn("L2", layers.layers_applied)
        ws_msgs = [m for m in layers.messages if "[WORKSPACE L2]" in m.get("content", "")]
        self.assertEqual(len(ws_msgs), 1)
        self.assertIn("/tmp/my-repo", ws_msgs[0]["content"])

    def test_l4_skipped_when_team_rules_table_missing(self) -> None:
        pipeline = ContextPipeline()
        with patch("app.shared.pg_tenant.connect_pg", side_effect=RuntimeError("no db")):
            msg, meta = pipeline._layer_l4_team_rules("default")
        self.assertIsNone(msg)
        self.assertTrue(meta.get("skipped") or meta.get("rule_count") == 0)

    @patch("app.context_pipeline.ContextPipeline._layer_l1_system_anchor", return_value=([], {"skipped": True}))
    @patch("app.context_pipeline.ContextPipeline._layer_l4_team_rules", return_value=(None, {"rule_count": 0}))
    @patch("app.context_pipeline.ContextPipeline._load_agent_prompt", return_value="")
    @patch("app.context_pipeline.ContextPipeline._load_skills", return_value=([], []))
    def test_assemble_single_build_meta(self, *_m: object) -> None:
        pipeline = ContextPipeline()
        payload = _payload(text="fix bug", history=[{"role": "user", "content": "hi"}])
        assembled = pipeline.assemble(
            payload,
            "rid-2",
            mode="cli",
            workspace_path="/work",
            tenant_id="tenant-a",
        )
        self.assertEqual(assembled.injection_meta["workspace_path"], "/work")
        self.assertEqual(assembled.injection_meta["tenant_id"], "tenant-a")
        self.assertIn("L5", assembled.injection_meta["layers"])
        roles = [m["role"] for m in assembled.injected_history]
        self.assertEqual(roles[-1], "user")
        self.assertEqual(assembled.injected_history[-1]["content"], "fix bug")

    def test_context_window_manager_under_limit(self) -> None:
        mgr = ContextWindowManager()
        hist = [{"role": "user", "content": "a"}]
        result = mgr.compact(hist)
        self.assertFalse(result.truncated)
        self.assertEqual(len(result.messages), 1)


class TestOpenapiCliFilter(unittest.TestCase):
    def test_excludes_agent_trees_and_ops_dashboard(self) -> None:
        from app.shared.openapi_cli_filter import filter_openapi_for_cli

        schema = {
            "paths": {
                "/agent-trees": {"get": {"tags": ["T17-AgentTree"]}},
                "/assistant/text/stream": {"post": {"tags": ["WidgetMVP"]}},
                "/assistant/text": {"post": {"tags": ["OpsDashboard"]}},
                "/playbook/x": {"get": {"tags": ["OpsDashboard"]}},
            },
            "tags": [{"name": "WidgetMVP"}, {"name": "T17-AgentTree"}, {"name": "OpsDashboard"}],
        }
        out = filter_openapi_for_cli(schema)
        self.assertNotIn("/agent-trees", out["paths"])
        self.assertNotIn("/assistant/text", out["paths"])
        self.assertIn("/assistant/text/stream", out["paths"])
        tag_names = {t["name"] for t in out["tags"]}
        self.assertIn("WidgetMVP", tag_names)
        self.assertNotIn("T17-AgentTree", tag_names)


if __name__ == "__main__":
    unittest.main()
