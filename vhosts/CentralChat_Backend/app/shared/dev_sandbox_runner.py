"""OC-20 MVP: subprocess sem shell com allowlist em argv[0]. Ver ADR-011."""

from __future__ import annotations

import subprocess
from typing import Any, Sequence

_STD_CAP = 8192


def _arg0_allowed(arg0: str, allowlist: Sequence[str]) -> bool:
    for ent in allowlist:
        e = ent.strip()
        if not e:
            continue
        if e.endswith("/"):
            if arg0.startswith(e):
                return True
        elif arg0 == e:
            return True
    return False


def run_dev_subprocess(
    argv: Sequence[str],
    *,
    timeout_sec: float,
    cwd: str | None,
    arg0_allowlist: Sequence[str],
) -> dict[str, Any]:
    if not argv:
        raise ValueError("argv_empty")
    if not arg0_allowlist:
        raise ValueError("allowlist_empty")
    arg0 = argv[0]
    if not _arg0_allowed(arg0, arg0_allowlist):
        raise ValueError("arg0_not_allowed")
    proc = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        cwd=cwd,
        shell=False,
    )
    out = proc.stdout or ""
    err = proc.stderr or ""
    return {
        "returncode": proc.returncode,
        "stdout": out[:_STD_CAP],
        "stderr": err[:_STD_CAP],
        "stdout_truncated": len(out) > _STD_CAP,
        "stderr_truncated": len(err) > _STD_CAP,
    }
