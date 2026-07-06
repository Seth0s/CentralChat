"""CORS and request metrics middleware for the orchestrator."""

from __future__ import annotations

from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram

from app.config import CORS_ALLOW_ORIGINS

SERVICE_NAME = "orchestrator"

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total de requests HTTP por servico",
    ["service", "method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latencia de requests HTTP por servico",
    ["service", "method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)


def install_orchestrator_middleware(app: FastAPI) -> None:
    """Registers CORS and per-request Prometheus metrics."""
    if CORS_ALLOW_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(CORS_ALLOW_ORIGINS),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):  # type: ignore[misc]
        if request.url.path == "/metrics":
            return await call_next(request)

        start = perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration = perf_counter() - start
            path = request.url.path
            method = request.method
            status = str(response.status_code if response else 500)
            REQUEST_COUNT.labels(SERVICE_NAME, method, path, status).inc()
            REQUEST_LATENCY.labels(SERVICE_NAME, method, path).observe(duration)
