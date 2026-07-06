"""Trim OpenAPI /docs to the CLI-facing contract (product mode)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

CLI_OPENAPI_EXCLUDE_PATH_PREFIXES: tuple[str, ...] = (
    "/agent-trees",
    "/playbook",
    "/dev/",
    "/rag/",
    "/host/",
    "/actions/",
    "/atena/",
    "/context-sync/",
    "/observability/",
)

CLI_OPENAPI_EXCLUDE_TAGS: frozenset[str] = frozenset(
    {"T17-AgentTree", "DeprecatedWidget", "OpsDashboard"}
)


def filter_openapi_for_cli(schema: dict[str, Any]) -> dict[str, Any]:
    paths = schema.get("paths") or {}
    filtered_paths: dict[str, Any] = {}
    for path, item in paths.items():
        if any(path.startswith(p) for p in CLI_OPENAPI_EXCLUDE_PATH_PREFIXES):
            continue
        kept_ops: dict[str, Any] = {}
        for method, op in (item or {}).items():
            if method.startswith("x-"):
                kept_ops[method] = op
                continue
            tags = op.get("tags") or []
            if any(t in CLI_OPENAPI_EXCLUDE_TAGS for t in tags):
                continue
            kept_ops[method] = op
        if kept_ops:
            filtered_paths[path] = kept_ops
    schema["paths"] = filtered_paths

    tags = schema.get("tags") or []
    schema["tags"] = [t for t in tags if t.get("name") not in CLI_OPENAPI_EXCLUDE_TAGS]
    return schema


def install_openapi_cli_filter(application: FastAPI) -> None:
    """Replace OpenAPI generator to hide admin / homelab routes in product mode."""

    def _custom_openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=getattr(application, "version", "0.1.0"),
            openapi_version=application.openapi_version,
            description=application.description,
            routes=application.routes,
        )
        application.openapi_schema = filter_openapi_for_cli(schema)
        return application.openapi_schema

    application.openapi = _custom_openapi  # type: ignore[method-assign]
