#!/usr/bin/env python3
"""Ensure bootstrap admin exists when auth DB is empty (manual / init container).

Idempotent: no-op when any user already exists.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from app.auth import ensure_bootstrap_admin

    user = ensure_bootstrap_admin()
    if user is None:
        print("skip\tbootstrap admin not created (disabled, DB unavailable, or users exist)")
        return 0
    print(f"ok\t{user.email}\t{user.id}\tmust_change_password={user.must_change_password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
