#!/usr/bin/env python3
"""Local webhook sink for staging alert tests (D2.3)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {"raw": raw.decode("utf-8", errors="replace")[:2000]}
        line = json.dumps({"ts": ts, "path": self.path, "body": body}, ensure_ascii=False)
        print(line, flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args: object) -> None:
        return


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9080
    host = "0.0.0.0"
    print(f"alert_webhook_sink listening on {host}:{port}", flush=True)
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
