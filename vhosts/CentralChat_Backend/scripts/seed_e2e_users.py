"""Onda A — seed users for e2e / staging RBAC tests."""

from __future__ import annotations

import os
import sys

# Allow `python scripts/seed_e2e_users.py` from repo root or container /app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth import set_user_role, upsert_user

USERS = [
    ("dev@local.test", "changeme", "developer"),
    ("approver@local.test", "changeme", "approver"),
    ("viewer@local.test", "changeme", "viewer"),
    ("auditor@local.test", "changeme", "auditor"),
]


def main() -> int:
    for email, password, role in USERS:
        upsert_user(email=email, password=password, client_id="default")
        if not set_user_role(email=email, role=role):
            print(f"warn: role not set for {email}", file=sys.stderr)
        else:
            print(f"ok: {email} ({role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
