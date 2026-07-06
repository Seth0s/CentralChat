"""OpenAPI tag metadata for the orchestrator ASGI app (Fase 1: shared with app factory)."""

OPENAPI_TAG_METADATA = [
    {"name": "WellKnown", "description": "Health, metrics, service metadata."},
    {
        "name": "Auth",
        "description": "JWT refresh rotation (`POST /auth/refresh`) when `CENTRAL_JWT_MODE` is not `off`.",
    },
    {
        "name": "WidgetMVP",
        "description": "Chat widget: config, preferences, UI state, inference catalog, sessions, approvals, assistant stream.",
    },
    {"name": "OpsDashboard", "description": "Operations UI: profiles, playbook, host summary, actions, diagnostics."},
    {
        "name": "DeprecatedWidget",
        "description": "Homelab A/B/C profile switching; not used by API-only widget.",
    },
]
