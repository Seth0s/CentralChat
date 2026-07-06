#!/usr/bin/env python3
"""C3 — SIEM outbox worker (retry + dead-letter)."""

from __future__ import annotations

import sys
import time

from app.shared.siem_outbox import process_siem_outbox

ONCE = "--once" in sys.argv


def main() -> None:
    if ONCE:
        counts = process_siem_outbox()
        print(f"siem_worker: {counts}")
        return
    while True:
        counts = process_siem_outbox()
        if any(counts.values()):
            print(f"siem_worker: {counts}")
        time.sleep(30)


if __name__ == "__main__":
    main()
