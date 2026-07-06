"""ASGI application entry (Fase 1).

Uvicorn default target remains ``app.server:app`` (see Dockerfile).
Use ``from app.server import create_app`` when a fresh app instance is needed (e.g. isolated tests).
"""

from app.server import app, create_app

__all__ = ["app", "create_app"]
