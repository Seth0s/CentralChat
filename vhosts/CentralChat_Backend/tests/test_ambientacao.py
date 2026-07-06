import unittest

from app.ambientacao import (
    build_capability_digest_pt_br,
    build_host_context_block,
    build_pre_injection_message,
    format_host_context_for_prompt,
    get_pre_injection_body,
    truncate_session_history,
)


class TestAmbientacao(unittest.TestCase):
    def test_pre_injection_non_empty(self):
        body = get_pre_injection_body(file_path=None)
        self.assertIn("Central", body)
        self.assertIn("[SYSTEM]", body)
        self.assertIn("[SYS_ENV]", body)
        self.assertIn("Technical Guardian", body)
        self.assertIn("ID: Central", body)
        msg = build_pre_injection_message(body)
        assert msg is not None
        self.assertEqual(msg["role"], "system")

    def test_capability_digest_pt_br(self):
        d = build_capability_digest_pt_br(max_chars=8000)
        self.assertIn("[CAPABILITY_DIGEST", d)
        self.assertIn("## P0", d)
        self.assertIn("`get_host_summary`", d)
        self.assertIn("orchestrator.approval.create", d)
        self.assertIn("HITL queue", d)
        self.assertIn("process.signal", d)

    def test_capability_digest_truncates(self):
        d = build_capability_digest_pt_br(max_chars=120)
        self.assertTrue(len(d) <= 130)
        self.assertIn("truncated", d)

    def test_truncate_session_noop_when_short(self):
        h = [{"role": "user", "content": "a"}]
        out, trunc = truncate_session_history(h, max_messages=10)
        self.assertEqual(out, h)
        self.assertFalse(trunc)

    def test_truncate_session_adds_notice(self):
        h = [{"role": "user", "content": str(i)} for i in range(5)]
        out, trunc = truncate_session_history(h, max_messages=2)
        self.assertTrue(trunc)
        self.assertEqual(len(out), 3)
        self.assertIn("omitted", out[0]["content"])

    def test_build_host_context_block_text_not_json(self):
        payload = {
            "request_id": "r1",
            "system_agent": {
                "request_id": "r1",
                "data": {
                    "cpu_percent": 7.5,
                    "mem_total_bytes": 8 * 1024**3,
                    "mem_used_bytes": 4 * 1024**3,
                    "disk_total_bytes": 100 * 1024**3,
                    "disk_used_bytes": 50 * 1024**3,
                    "os": {"pretty_name": "Test OS", "release": "1.0", "container_likely": False},
                    "agent_runtime": {"implementation": "CPython", "python": "3.12.0"},
                },
            },
            "kernel_observer": {
                "request_id": "r1",
                "cpu_percent": 8.0,
                "memory": {"total": 8 * 1024**3, "available": 2 * 1024**3, "percent": 75.0},
                "loadavg": {"1m": 0.1, "5m": 0.2, "15m": 0.3},
            },
            "kernel_observer_error": None,
            "kernel_audit": {
                "request_id": "r1",
                "enabled": True,
                "readable": True,
                "lines_in_sample": 12,
                "type_counts": {"SYSCALL": 5, "PATH": 2},
            },
            "kernel_audit_error": None,
        }
        block = build_host_context_block(payload)
        self.assertNotIn("{", block)
        self.assertIn("request_id: r1", block)
        self.assertIn("system_agent (system.summary):", block)
        self.assertIn("GiB", block)
        self.assertIn("kernel_observer (snapshot):", block)
        self.assertIn("loadavg_1m_5m_15m", block)
        self.assertIn("kernel_audit (type_counts in sample):", block)
        self.assertIn("SYSCALL=5", block)

    def test_build_host_context_block_system_agent_error(self):
        payload = {
            "request_id": "r2",
            "system_agent": {"error": "connection refused"},
            "kernel_observer": None,
            "kernel_observer_error": "timeout",
        }
        block = build_host_context_block(payload)
        self.assertIn("system_agent: unavailable", block)
        self.assertIn("connection refused", block)
        self.assertIn("kernel_observer: unavailable", block)

    def test_format_host_context_for_prompt_wraps_block(self):
        payload = {"request_id": "x", "system_agent": {"error": "e"}, "kernel_observer": None}
        full = format_host_context_for_prompt(payload, max_chars=500)
        self.assertIn("[FACTUAL_HOST_CONTEXT", full)
        self.assertIn("include_host_context=true", full)
        self.assertIn("system_agent: unavailable", full)


if __name__ == "__main__":
    unittest.main()
