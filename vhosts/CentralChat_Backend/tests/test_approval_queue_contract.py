"""P1-4: contrato fila HITL — schema create_approval_request alinhado a approval_via_tool."""
from __future__ import annotations

import unittest

from app.approval_via_tool import (
    ALLOWED_APPROVAL_ACTION_IDS,
    validate_and_normalize_approval_payload,
)
from app.tool_registry import create_approval_request_json_schema


def _schema_action_ids_and_payloads(schema: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    one_of = schema.get("oneOf")
    if not isinstance(one_of, list):
        return out
    for branch in one_of:
        if not isinstance(branch, dict):
            continue
        props = branch.get("properties") or {}
        aid = props.get("action_id") or {}
        enums = aid.get("enum")
        if not isinstance(enums, list) or len(enums) != 1:
            continue
        action_id = enums[0]
        pwrap = props.get("payload")
        if not isinstance(pwrap, dict):
            continue
        out.append((str(action_id), pwrap))
    return out


class TestApprovalQueueContract(unittest.TestCase):
    def test_schema_matches_allowlist(self) -> None:
        schema = create_approval_request_json_schema()
        pairs = _schema_action_ids_and_payloads(schema)
        schema_ids = {a for a, _ in pairs}
        self.assertEqual(
            schema_ids,
            ALLOWED_APPROVAL_ACTION_IDS,
            "cada action_id em ALLOWED_APPROVAL_ACTION_IDS deve ter exactamente um ramo oneOf",
        )
        self.assertEqual(len(pairs), len(ALLOWED_APPROVAL_ACTION_IDS))

    def test_schema_additional_properties_false(self) -> None:
        schema = create_approval_request_json_schema()
        for action_id, pwrap in _schema_action_ids_and_payloads(schema):
            with self.subTest(action_id=action_id):
                inner_one = pwrap.get("oneOf")
                if isinstance(inner_one, list):
                    for br in inner_one:
                        if isinstance(br, dict):
                            self.assertIs(
                                br.get("additionalProperties"),
                                False,
                                "cada ramo de payload.oneOf deve ter additionalProperties: false",
                            )
                else:
                    self.assertIs(
                        pwrap.get("additionalProperties"),
                        False,
                        "payload deve ter additionalProperties: false",
                    )
                root = schema["oneOf"]
                assert isinstance(root, list)
                for branch in root:
                    if not isinstance(branch, dict):
                        continue
                    props = branch.get("properties") or {}
                    aid = (props.get("action_id") or {}).get("enum")
                    if aid == [action_id]:
                        self.assertIs(
                            branch.get("additionalProperties"),
                            False,
                            "raiz do ramo oneOf deve ter additionalProperties: false",
                        )
                        break

    def test_validate_rejects_extra_payload_keys(self) -> None:
        bad, err = validate_and_normalize_approval_payload(
            "process.signal",
            {"pid": 42, "evil": 1},
        )
        self.assertIsNone(bad)
        self.assertEqual(err, "payload_extra_fields")

    def test_validate_accepts_minimal_process_signal(self) -> None:
        ok, err = validate_and_normalize_approval_payload("process.signal", {"pid": 3})
        self.assertIsNone(err)
        assert ok is not None
        self.assertEqual(ok, {"pid": 3, "signal": 15})

    def test_validate_os_power_empty_payload(self) -> None:
        ok_r, err_r = validate_and_normalize_approval_payload("os.power.reboot", {})
        self.assertIsNone(err_r)
        assert ok_r is not None
        self.assertEqual(ok_r, {})
        ok_s, err_s = validate_and_normalize_approval_payload("os.power.shutdown", {})
        self.assertIsNone(err_s)
        assert ok_s is not None
        self.assertEqual(ok_s, {})

    def test_validate_os_power_rejects_extra_keys(self) -> None:
        bad, err = validate_and_normalize_approval_payload("os.power.reboot", {"x": 1})
        self.assertIsNone(bad)
        self.assertEqual(err, "payload_must_be_empty")

    def test_validate_firewall_policy_reload(self) -> None:
        ok, err = validate_and_normalize_approval_payload("network.firewall.policy.apply", {"operation": "reload"})
        self.assertIsNone(err)
        assert ok is not None
        self.assertEqual(ok, {"operation": "reload"})

    def test_validate_firewall_policy_set_zone(self) -> None:
        ok, err = validate_and_normalize_approval_payload(
            "network.firewall.policy.apply",
            {"operation": "set_default_zone", "zone": "public"},
        )
        self.assertIsNone(err)
        assert ok is not None
        self.assertEqual(ok, {"operation": "set_default_zone", "zone": "public"})

    def test_validate_firewall_policy_reload_rejects_zone(self) -> None:
        bad, err = validate_and_normalize_approval_payload(
            "network.firewall.policy.apply",
            {"operation": "reload", "zone": "public"},
        )
        self.assertIsNone(bad)
        self.assertEqual(err, "payload_extra_fields")

    def test_validate_os_packages_upgrade_all_empty(self) -> None:
        ok, err = validate_and_normalize_approval_payload("os.packages.upgrade_all", {})
        self.assertIsNone(err)
        assert ok is not None
        self.assertEqual(ok, {})

    def test_validate_os_packages_upgrade_all_rejects_extra(self) -> None:
        bad, err = validate_and_normalize_approval_payload("os.packages.upgrade_all", {"x": 1})
        self.assertIsNone(bad)
        self.assertEqual(err, "payload_must_be_empty")


if __name__ == "__main__":
    unittest.main()
