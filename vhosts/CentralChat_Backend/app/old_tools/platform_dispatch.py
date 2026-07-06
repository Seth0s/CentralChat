"""ADR-017 phase 8 — dispatch for legacy VPS / system-agent tools."""
from __future__ import annotations

from typing import Any

from app.approvals import create_approval_from_tool
from app.clients import (
    fetch_disk_partitions_for_tool,
    fetch_disk_usage_for_tool,
    fetch_file_metadata_for_tool,
    fetch_hardware_sensors_for_tool,
    fetch_host_summary_best_effort,
    fetch_journal_tail_for_tool,
    fetch_listening_sockets_for_tool,
    fetch_network_connections_for_tool,
    fetch_network_interfaces_for_tool,
    fetch_network_routes_for_tool,
    fetch_packages_query_for_tool,
    fetch_process_list_for_tool,
    fetch_process_tree_for_tool,
    fetch_read_file_text_for_tool,
    fetch_systemd_units_for_tool,
    fetch_workspace_grep_for_tool,
)
from app.old_tools.platform_specs import is_platform_tool
from app.shared.stack_health import collect_central_stack_health
from app.tools import (
    TOOL_NAME_CREATE_APPROVAL_REQUEST,
    TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT,
    TOOL_NAME_GET_CENTRAL_STACK_HEALTH,
    TOOL_NAME_GET_FILE_METADATA,
    TOOL_NAME_GET_HARDWARE_SENSORS,
    TOOL_NAME_GET_HOST_SUMMARY,
    TOOL_NAME_GET_JOURNAL_TAIL,
    TOOL_NAME_GET_NETWORK_ROUTES,
    TOOL_NAME_GREP_WORKSPACE,
    TOOL_NAME_INSTALL_OS_PACKAGE,
    TOOL_NAME_LIST_DISK_PARTITIONS,
    TOOL_NAME_LIST_DISK_USAGE,
    TOOL_NAME_LIST_LISTENING_SOCKETS,
    TOOL_NAME_LIST_NETWORK_CONNECTIONS,
    TOOL_NAME_LIST_NETWORK_INTERFACES,
    TOOL_NAME_LIST_PROCESSES,
    TOOL_NAME_LIST_PROCESS_TREE,
    TOOL_NAME_LIST_SYSTEMD_UNITS,
    TOOL_NAME_MUTATE_EXTERNAL_FILE,
    TOOL_NAME_OPEN_BROWSER_URL,
    TOOL_NAME_PROBE_NETWORK_ENDPOINT,
    TOOL_NAME_QUERY_INSTALLED_PACKAGES,
    TOOL_NAME_READ_FILE_TEXT,
    TOOL_NAME_SEND_DESKTOP_NOTIFICATION,
    TOOL_NAME_UPGRADE_OS_PACKAGES_ALL,
    TOOL_NAME_WRITE_CONFIG_FILE,
)


def dispatch_legacy_platform_tool(
    tool_name: str,
    arguments: dict[str, Any],
    request_id: str,
) -> dict[str, Any] | None:
    """
    Run a platform tool. Returns ``None`` if ``tool_name`` is not a legacy platform tool.
    """
    name = tool_name.strip()
    if not is_platform_tool(name):
        return None

    if name == TOOL_NAME_GET_HOST_SUMMARY:
        return fetch_host_summary_best_effort(request_id)
    if name == TOOL_NAME_GET_JOURNAL_TAIL:
        u = arguments.get("unit")
        i = arguments.get("identifier")
        us = u.strip() if isinstance(u, str) else None
        ids = i.strip() if isinstance(i, str) else None
        us = us or None
        ids = ids or None
        since = arguments.get("since", "1h")
        if not isinstance(since, str):
            since = "1h"
        mb = arguments.get("max_bytes", 16384)
        if not isinstance(mb, int):
            mb = 16384
        return fetch_journal_tail_for_tool(
            request_id,
            unit=us,
            identifier=ids,
            since=since,
            max_bytes=mb,
        )
    if name == TOOL_NAME_LIST_PROCESSES:
        lim = arguments.get("limit", 40)
        if not isinstance(lim, int):
            lim = 40
        return fetch_process_list_for_tool(request_id, limit=lim)
    if name == TOOL_NAME_LIST_PROCESS_TREE:
        lim = arguments.get("limit", 80)
        if not isinstance(lim, int):
            lim = 80
        md = arguments.get("max_depth", 12)
        if not isinstance(md, int):
            md = 12
        return fetch_process_tree_for_tool(request_id, limit=lim, max_depth=md)
    if name == TOOL_NAME_LIST_LISTENING_SOCKETS:
        lim = arguments.get("limit", 200)
        if not isinstance(lim, int):
            lim = 200
        return fetch_listening_sockets_for_tool(request_id, limit=lim)
    if name == TOOL_NAME_GET_FILE_METADATA:
        p = str(arguments.get("path", "")).strip()
        return fetch_file_metadata_for_tool(request_id, rel_path=p)
    if name == TOOL_NAME_GET_HARDWARE_SENSORS:
        return fetch_hardware_sensors_for_tool(request_id)
    if name == TOOL_NAME_LIST_DISK_USAGE:
        return fetch_disk_usage_for_tool(request_id)
    if name == TOOL_NAME_LIST_DISK_PARTITIONS:
        lim = arguments.get("limit", 64)
        if not isinstance(lim, int):
            lim = 64
        return fetch_disk_partitions_for_tool(request_id, limit=lim)
    if name == TOOL_NAME_GREP_WORKSPACE:
        p = str(arguments.get("path", "")).strip()
        pat = str(arguments.get("pattern", "")).strip()
        mm = arguments.get("max_matches", 80)
        if not isinstance(mm, int):
            mm = 80
        return fetch_workspace_grep_for_tool(request_id, path=p, pattern=pat, max_matches=mm)
    if name == TOOL_NAME_LIST_NETWORK_INTERFACES:
        return fetch_network_interfaces_for_tool(request_id)
    if name == TOOL_NAME_GET_NETWORK_ROUTES:
        lim = arguments.get("limit", 32)
        if not isinstance(lim, int):
            lim = 32
        return fetch_network_routes_for_tool(request_id, limit=lim)
    if name == TOOL_NAME_GET_CENTRAL_STACK_HEALTH or name == "get_sophia_stack_health":
        return collect_central_stack_health(request_id)
    if name == TOOL_NAME_LIST_NETWORK_CONNECTIONS:
        lim = arguments.get("limit", 100)
        if not isinstance(lim, int):
            lim = 100
        st = arguments.get("state", "ESTABLISHED")
        if not isinstance(st, str):
            st = "ESTABLISHED"
        return fetch_network_connections_for_tool(request_id, limit=lim, state=st)
    if name == TOOL_NAME_LIST_SYSTEMD_UNITS:
        lim = arguments.get("limit", 80)
        if not isinstance(lim, int):
            lim = 80
        return fetch_systemd_units_for_tool(request_id, limit=lim)
    if name == TOOL_NAME_QUERY_INSTALLED_PACKAGES:
        pkg = str(arguments.get("package", "")).strip()
        return fetch_packages_query_for_tool(request_id, package=pkg)
    if name == TOOL_NAME_READ_FILE_TEXT:
        p = str(arguments.get("path", "")).strip()
        mb = arguments.get("max_bytes", 32768)
        if not isinstance(mb, int):
            mb = 32768
        return fetch_read_file_text_for_tool(request_id, rel_path=p, max_bytes=mb)
    if name == TOOL_NAME_CREATE_APPROVAL_REQUEST:
        return create_approval_from_tool(arguments=arguments, request_id=request_id)
    if name == TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT:
        u = str(arguments.get("unit", "")).strip()
        return create_approval_from_tool(
            arguments={"action_id": "systemd.user.unit.disable", "payload": {"unit": u}},
            request_id=request_id,
        )
    if name == TOOL_NAME_INSTALL_OS_PACKAGE:
        pkg = str(arguments.get("package", "")).strip()
        return create_approval_from_tool(
            arguments={"action_id": "os.packages.install", "payload": {"package": pkg}},
            request_id=request_id,
        )
    if name == TOOL_NAME_UPGRADE_OS_PACKAGES_ALL:
        return create_approval_from_tool(
            arguments={"action_id": "os.packages.upgrade_all", "payload": {}},
            request_id=request_id,
        )
    if name == TOOL_NAME_WRITE_CONFIG_FILE:
        p = str(arguments.get("path", "")).strip()
        content = arguments.get("content")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        pay: dict[str, Any] = {"path": p, "content": content}
        cb = arguments.get("create_backup")
        if cb is not None:
            pay["create_backup"] = bool(cb)
        return create_approval_from_tool(
            arguments={"action_id": "filesystem.path.write_config", "payload": pay},
            request_id=request_id,
        )
    if name == TOOL_NAME_MUTATE_EXTERNAL_FILE:
        op = str(arguments.get("operation", "")).strip().lower()
        src_p = str(arguments.get("src_path", "")).strip()
        pay_m: dict[str, Any] = {"operation": op, "src_path": src_p}
        if op in ("copy", "move"):
            pay_m["dst_path"] = str(arguments.get("dst_path", "")).strip()
        return create_approval_from_tool(
            arguments={"action_id": "filesystem.path.mutate_external", "payload": pay_m},
            request_id=request_id,
        )
    if name == TOOL_NAME_OPEN_BROWSER_URL:
        u = str(arguments.get("url", "")).strip()
        return create_approval_from_tool(
            arguments={"action_id": "desktop.open_url", "payload": {"url": u}},
            request_id=request_id,
        )
    if name == TOOL_NAME_PROBE_NETWORK_ENDPOINT:
        pay: dict[str, Any] = {
            "host": str(arguments.get("host", "")).strip(),
            "port": arguments.get("port"),
            "kind": str(arguments.get("kind", "")).strip().lower(),
        }
        pt = arguments.get("path")
        if pt is not None and str(pt).strip() != "":
            pay["path"] = str(pt).strip()
        return create_approval_from_tool(
            arguments={"action_id": "network.endpoint.probe", "payload": pay},
            request_id=request_id,
        )
    if name == TOOL_NAME_SEND_DESKTOP_NOTIFICATION:
        body = arguments.get("body")
        if not isinstance(body, str):
            body = str(body)
        pay_n: dict[str, Any] = {"body": body}
        t = arguments.get("title")
        if t is not None:
            pay_n["title"] = str(t)
        return create_approval_from_tool(
            arguments={"action_id": "desktop.notify", "payload": pay_n},
            request_id=request_id,
        )
    return None
