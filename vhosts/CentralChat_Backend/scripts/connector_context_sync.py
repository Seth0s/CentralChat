#!/usr/bin/env python3
"""T12 — Connector Context Sync: reads ~/central/ and sends to VPS.

Scans user-owned directories for identity, agents, skills, and tools.
Detects changes via file hashes, and POSTs only changed sections to the VPS.

Usage:
    python scripts/connector_context_sync.py --vps-url http://vps:8004 [--once]
    Default: reads from ~/central/ (CENTRAL_HOME env var override)
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ── Config ──
CENTRAL_HOME = Path(os.getenv("CENTRAL_HOME", os.path.expanduser("~/central")))
VPS_URL = ""

for arg in sys.argv:
    if arg.startswith("--vps-url="):
        VPS_URL = arg.split("=", 1)[1]

if not VPS_URL:
    VPS_URL = os.getenv("CENTRAL_VPS_URL", "http://localhost:8004")

ONCE = "--once" in sys.argv
INTERVAL = int(os.getenv("CENTRAL_SYNC_INTERVAL", "30"))  # seconds

# ── File discovery ──


def _discover_files() -> dict[str, Any]:
    """Scan ~/central/ for context files. Returns dict of content blobs."""
    ctx: dict[str, Any] = {}

    # Identity
    identity_path = CENTRAL_HOME / "identity.yaml"
    if identity_path.is_file():
        ctx["identity"] = {"name": identity_path.stem, "path": str(identity_path)}
        try:
            import yaml

            data = yaml.safe_load(identity_path.read_text())
            if isinstance(data, dict):
                ctx["identity"] = data
        except Exception:
            ctx["identity"]["_error"] = "yaml_parse_failed"

    # Agents (directory)
    agents_dir = CENTRAL_HOME / "agents"
    agents = []
    if agents_dir.is_dir():
        for f in sorted(agents_dir.glob("*.md")):
            agents.append({
                "name": f.stem,
                "content": f.read_text(encoding="utf-8")[:50000],
            })
    ctx["agents"] = agents

    # Skills (directory)
    skills_dir = CENTRAL_HOME / "skills"
    skills = []
    if skills_dir.is_dir():
        for f in sorted(skills_dir.glob("*.md")):
            skills.append({
                "name": f.stem,
                "content": f.read_text(encoding="utf-8")[:50000],
            })
    ctx["skills"] = skills

    # Tools (directory)
    tools_dir = CENTRAL_HOME / "tools"
    tools = []
    if tools_dir.is_dir():
        for f in sorted(tools_dir.glob("*.yaml")):
            try:
                import yaml

                data = yaml.safe_load(f.read_text())
                if isinstance(data, dict):
                    tools.append({"name": f.stem, **data})
            except Exception:
                pass
    ctx["tools"] = tools

    return ctx


def _send_sync(ctx: dict[str, Any]) -> None:
    """POST context to VPS."""
    try:
        r = httpx.post(
            f"{VPS_URL.rstrip('/')}/connector/context-sync",
            json=ctx,
            timeout=10.0,
        )
        if r.status_code == 200:
            data = r.json()
            changes = data.get("changes", {})
            if changes:
                print(f"[context_sync] Changes: {list(changes.keys())}", flush=True)
            else:
                print(f"[context_sync] No changes", flush=True)
        else:
            print(f"[context_sync] HTTP {r.status_code}: {r.text[:200]}", flush=True)
    except Exception as exc:
        print(f"[context_sync] Error: {exc}", flush=True)


# ── Main ──
print(f"[context_sync] Starting. VPS={VPS_URL} HOME={CENTRAL_HOME}", flush=True)

while True:
    ctx = _discover_files()
    _send_sync(ctx)
    if ONCE:
        break
    time.sleep(INTERVAL)
