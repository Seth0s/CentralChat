# B2.3 — Golden policy cases (path × tool × environment)

from __future__ import annotations

from typing import Any

GOLDEN_POLICY_CASES: list[dict[str, Any]] = [
    {
        "id": "env_read",
        "tool": "read_file",
        "args": {"path": ".env"},
        "allowed": False,
        "error_code": "policy_path_denied",
    },
    {
        "id": "credentials_read",
        "tool": "read_file",
        "args": {"path": "src/credentials/api.key"},
        "allowed": False,
        "error_code": "policy_path_denied",
    },
    {
        "id": "payment_write",
        "tool": "write_file",
        "args": {"path": "payment/checkout.go"},
        "allowed": True,
    },
    {
        "id": "payment_terminal",
        "tool": "terminal",
        "args": {"command": "ls", "cwd": "payment/"},
        "allowed": False,
        "error_code": "policy_tool_denied",
    },
    {
        "id": "safe_read",
        "tool": "read_file",
        "args": {"path": "src/main.py"},
        "allowed": True,
    },
    {
        "id": "safe_patch",
        "tool": "patch",
        "args": {"path": "lib/utils.py"},
        "allowed": True,
    },
    {
        "id": "api_dual_path",
        "tool": "write_file",
        "args": {"path": "api/routes.py"},
        "allowed": True,
    },
    {
        "id": "root_readme",
        "tool": "read_file",
        "args": {"path": "README.md"},
        "allowed": True,
    },
    {
        "id": "terminal_safe",
        "tool": "terminal",
        "args": {"command": "pwd"},
        "allowed": True,
    },
    {
        "id": "search_safe",
        "tool": "search_files",
        "args": {"pattern": "TODO"},
        "allowed": True,
    },
    {
        "id": "env_write",
        "tool": "write_file",
        "args": {"path": ".env.local"},
        "allowed": False,
        "error_code": "policy_path_denied",
    },
    {
        "id": "payment_read",
        "tool": "read_file",
        "args": {"path": "payment/invoice.py"},
        "allowed": True,
    },
    {
        "id": "credentials_terminal",
        "tool": "terminal",
        "args": {"command": "cat x", "cwd": "credentials/"},
        "allowed": False,
        "error_code": "policy_path_denied",
    },
    {
        "id": "lib_write",
        "tool": "patch",
        "args": {"path": "lib/helpers.ts"},
        "allowed": True,
    },
    {
        "id": "docs_read",
        "tool": "read_file",
        "args": {"path": "docs/guide.md"},
        "allowed": True,
    },
]

GOLDEN_COMPLIANCE_PACK_CASES: list[dict[str, Any]] = [
    {
        "pack_id": "pci-dss",
        "tool": "terminal",
        "args": {"command": "ls", "cwd": "payment/"},
        "allowed": False,
    },
    {
        "pack_id": "pci-dss",
        "tool": "write_file",
        "args": {"path": ".env"},
        "allowed": False,
    },
    {
        "pack_id": "lgpd-dev",
        "tool": "memory",
        "args": {"path": "pii/users.csv"},
        "allowed": False,
    },
    {
        "pack_id": "iso27001",
        "tool": "terminal",
        "args": {"command": "ls", "cwd": "secrets/"},
        "allowed": False,
    },
    {
        "pack_id": "iso27001",
        "tool": "write_file",
        "args": {"path": "lib/util.py"},
        "allowed": True,
    },
]
