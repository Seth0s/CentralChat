"""ADR-017 phase 8 — VPS / system-agent tools (legacy homelab catalog)."""
from __future__ import annotations

from typing import Any

# Tools that run on the Central deploy host (system-agent, shell-gateway), not on the tenant connector.
PLATFORM_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_host_summary",
        "get_journal_tail",
        "list_processes",
        "list_process_tree",
        "list_listening_sockets",
        "get_file_metadata",
        "get_hardware_sensors",
        "list_disk_usage",
        "list_disk_partitions",
        "grep_workspace",
        "list_network_interfaces",
        "get_network_routes",
        "get_central_stack_health",
        "list_network_connections",
        "list_systemd_units",
        "query_installed_packages",
        "read_file_text",
        "create_approval_request",
        "disable_systemd_user_unit",
        "install_os_package",
        "upgrade_os_packages_all",
        "mutate_external_file",
        "write_config_file",
        "open_browser_url",
        "probe_network_endpoint",
        "send_desktop_notification",
    }
)


def is_platform_tool(name: str) -> bool:
    return name.strip() in PLATFORM_TOOL_NAMES


def merge_legacy_platform_specs(all_specs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Subset of full registry specs enabled when ``CENTRAL_LEGACY_PLATFORM_TOOLS=1``."""
    return {k: dict(all_specs[k]) for k in PLATFORM_TOOL_NAMES if k in all_specs}


def strip_platform_specs(specs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Tenant widget catalog: cloud + client only."""
    return {k: v for k, v in specs.items() if k not in PLATFORM_TOOL_NAMES}
