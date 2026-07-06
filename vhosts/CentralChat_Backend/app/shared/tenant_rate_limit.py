"""Fase 12 — rate limit por tenant (janela deslizante in-process)."""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import Request
from prometheus_client import Counter
from starlette.responses import Response

from app import config as _cfg
from app.http.problem_details import problem_json_response

_lock = threading.Lock()
# tenant_key -> monotonic timestamps of accepted requests
_windows: dict[str, deque[float]] = {}

RATE_LIMIT_REJECTS = Counter(
    "central_orchestrator_rate_limit_rejects_total",
    "Pedidos HTTP 429 por rate limit (tenant agregado)",
    ["tenant_class"],
)


def _tenant_class(tenant_key: str) -> str:
    return "anonymous" if tenant_key == "_anonymous" else "authenticated"


def _path_matches_rate_limit(path: str) -> bool:
    for prefix in _cfg.CENTRAL_RATE_LIMIT_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def path_is_rate_limited(method: str, path: str) -> bool:
    if not bool(_cfg.CENTRAL_RATE_LIMIT_ENABLED):
        return False
    if method.upper() != "POST":
        return False
    return _path_matches_rate_limit(path)


def allow_tenant_request(*, tenant_key: str) -> tuple[bool, int | None]:
    """
    Sliding window: no máximo ``CENTRAL_RATE_LIMIT_PER_WINDOW`` aceites por
    ``CENTRAL_RATE_LIMIT_WINDOW_SECONDS`` por chave de tenant.

    Retorna (permitido?, retry_after_seconds se negado).
    """
    window = float(_cfg.CENTRAL_RATE_LIMIT_WINDOW_SECONDS)
    limit = int(_cfg.CENTRAL_RATE_LIMIT_PER_WINDOW)
    max_keys = int(_cfg.CENTRAL_RATE_LIMIT_MAX_TENANTS)
    key = (tenant_key or "_anonymous")[:128]
    now = time.monotonic()

    with _lock:
        if key not in _windows and len(_windows) >= max_keys:
            _windows.pop(next(iter(_windows)))

        dq = _windows.setdefault(key, deque())
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()

        if len(dq) >= limit:
            oldest = dq[0]
            retry_after = int(window - (now - oldest)) + 1
            RATE_LIMIT_REJECTS.labels(_tenant_class(key)).inc()
            return False, max(1, retry_after)

        dq.append(now)
        return True, None


def reset_rate_limit_state_for_tests() -> None:
    with _lock:
        _windows.clear()


def maybe_rate_limit_response(request: Request) -> Response | None:
    """429 Problem Details + ``Retry-After`` se o path estiver sujeito a limite e a cota esgotar."""
    method = request.method.upper()
    path = request.url.path
    if not path_is_rate_limited(method, path):
        return None
    from app.shared.tenant_context import get_current_client_id

    tk = get_current_client_id() or "_anonymous"
    ok, ra = allow_tenant_request(tenant_key=tk)
    if ok:
        return None
    resp = problem_json_response(
        status=429,
        type_suffix="tenant_rate_limited",
        detail="Limite de pedidos por tenant excedido; tente mais tarde.",
        instance=path,
        extensions={"retry_after_seconds": ra},
    )
    if ra is not None:
        resp.headers["Retry-After"] = str(int(ra))
    return resp
