#!/usr/bin/env python3
"""Cria ou actualiza um utilizador para POST /auth/login (dev/VPS).

Uso (na raiz do serviço orchestrator):
  AUTH_USERS_DB_URL=postgresql://... PYTHONPATH=. python scripts/seed_auth_user.py \\
    --email admin@example.com --password 'changeme' [--client-id default]
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    p = argparse.ArgumentParser(description="Seed auth user for Central login")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--client-id", default=None)
    p.add_argument("--display-name", default=None)
    args = p.parse_args()
    from app.auth import upsert_user

    row = upsert_user(
        email=args.email,
        password=args.password,
        client_id=args.client_id,
        display_name=args.display_name,
    )
    print(f"ok\t{row.email}\t{row.id}\tclient_id={row.client_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
