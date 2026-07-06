"""Tools domain — loop, registry, policy, catalog, metrics, embedding, modality."""

from __future__ import annotations

from __future__ import annotations
from app.approvals import create_approval_from_tool
from app.clients import call_llm
from app.clients import call_llm, iter_assistant_llm_ndjson
from app.clients import fetch_disk_partitions_for_tool, fetch_disk_usage_for_tool, fetch_file_metadata_for_tool, fetch_hardware_sensors_for_tool, fetch_read_file_text_for_tool, fetch_host_summary_best_effort, fetch_journal_tail_for_tool, fetch_listening_sockets_for_tool, fetch_network_connections_for_tool, fetch_network_interfaces_for_tool, fetch_network_routes_for_tool, fetch_packages_query_for_tool, fetch_process_list_for_tool, fetch_process_tree_for_tool, fetch_systemd_units_for_tool, fetch_workspace_grep_for_tool
from app.config import AGENT_TOOLS_FEW_SHOT_ENABLED, AGENT_TOOLS_JSON_MODE_ENABLED, AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS, AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS, MODEL_ROUTER_URL
from app.config import AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED
from app.connector import CLIENT_AGENT_OFFLINE_MESSAGE_PT, connector_online_for_tenant, tenant_shell_uses_client_connector
from app.connector import dispatch_client_grep, dispatch_client_read_file
from app.actions import dispatch_request_shell
from app.shared.modality_models import ROLE_IMAGE_GENERATE, ROLE_SOCIAL_COPY, ROLE_WEB_RESEARCH_DEEP, ROLE_WEB_RESEARCH_DEFAULT, ROLE_WEB_RESEARCH_FAST, resolve_modality_call_params
from app.shared.redacted_thinking import RedactedThinkingStreamSplitter, assistant_message_for_history, text_for_agent_tool_json_parse
from app.shared.stack_health import collect_central_stack_health
from app.workspace import apply_canvas_patch as workspace_apply_canvas_patch
from app.workspace import manage_workspace_artifact as workspace_manage_artifact
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from prometheus_client import Counter, Histogram
from typing import Any
from typing import Final, Literal
import json
import jsonschema
import os
import re


# ═══ TOOL_CATALOG_POLICY ═══

"""ADR-017 — execution class per tool and LLM catalog filtering (cloud / client / platform)."""

ToolExecutionClass = Literal["cloud", "client", "platform", "internal_meta"]

_CLIENT_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "request_shell",
        "client_read_file",
        "client_grep",
    }
)

_CLOUD_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "manage_workspace_artifact",
        "apply_canvas_patch",
        "web_research",
        "draft_social_post",
        "generate_post_image",
    }
)

_INTERNAL_META_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "create_approval_request",
    }
)

_PLATFORM_TOOL_NAMES: Final[frozenset[str]] = frozenset(
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

def get_tool_execution_class(name: str) -> ToolExecutionClass:
    """Map a registered tool name to cloud, client, platform, or internal_meta."""
    n = name.strip()
    if n in _INTERNAL_META_TOOL_NAMES:
        return "internal_meta"
    if n in _CLIENT_TOOL_NAMES:
        return "client"
    if n in _CLOUD_TOOL_NAMES:
        return "cloud"
    # T14 — Default tools: classify as cloud (always exposed to LLM)
    from app.default_tools import _DEFAULT_TOOL_NAMES_SET  # noqa: PLC0415
    if n in _DEFAULT_TOOL_NAMES_SET:
        return "cloud"
    if n in _PLATFORM_TOOL_NAMES:
        return "platform"
    # Unknown names (future registry entries): treat as platform until classified.
    return "platform"

def is_tool_exposed_to_llm(name: str) -> bool:
    """Whether the tool may appear in [PROTOCOLO_AGENT_TOOLS] for the widget tenant."""
    from app import config as cfg  # noqa: PLC0415

    cls = get_tool_execution_class(name)
    if cls == "internal_meta":
        return bool(cfg.CENTRAL_LLM_APPROVAL_META_TOOL_ENABLED)
    if cls == "platform":
        return bool(cfg.CENTRAL_LEGACY_PLATFORM_TOOLS)
    return True

def filter_tool_names_for_llm(names: list[str]) -> list[str]:
    """Preserve order; drop tools hidden by ADR-017 catalog policy."""
    return [n for n in names if is_tool_exposed_to_llm(n)]


# ═══ TOOL_REGISTRY ═══

"""
Fase G — catálogo fechado de tools do agente: JSON Schema por nome + despacho tipado.
Deny-by-default: nomes fora do registry nunca executam.
"""

TOOL_NAME_GET_HOST_SUMMARY = "get_host_summary"

TOOL_NAME_GET_JOURNAL_TAIL = "get_journal_tail"

TOOL_NAME_LIST_PROCESSES = "list_processes"

TOOL_NAME_LIST_PROCESS_TREE = "list_process_tree"

TOOL_NAME_LIST_LISTENING_SOCKETS = "list_listening_sockets"

TOOL_NAME_GET_FILE_METADATA = "get_file_metadata"

TOOL_NAME_GET_HARDWARE_SENSORS = "get_hardware_sensors"

TOOL_NAME_LIST_DISK_USAGE = "list_disk_usage"

TOOL_NAME_LIST_DISK_PARTITIONS = "list_disk_partitions"

TOOL_NAME_GREP_WORKSPACE = "grep_workspace"

TOOL_NAME_LIST_NETWORK_INTERFACES = "list_network_interfaces"

TOOL_NAME_GET_NETWORK_ROUTES = "get_network_routes"

TOOL_NAME_GET_CENTRAL_STACK_HEALTH = "get_central_stack_health"

TOOL_NAME_LIST_NETWORK_CONNECTIONS = "list_network_connections"

TOOL_NAME_LIST_SYSTEMD_UNITS = "list_systemd_units"

TOOL_NAME_QUERY_INSTALLED_PACKAGES = "query_installed_packages"

TOOL_NAME_READ_FILE_TEXT = "read_file_text"

TOOL_NAME_CREATE_APPROVAL_REQUEST = "create_approval_request"

TOOL_NAME_REQUEST_SHELL = "request_shell"

TOOL_NAME_CLIENT_READ_FILE = "client_read_file"

TOOL_NAME_CLIENT_GREP = "client_grep"

TOOL_NAME_OPEN_BROWSER_URL = "open_browser_url"

TOOL_NAME_PROBE_NETWORK_ENDPOINT = "probe_network_endpoint"

TOOL_NAME_SEND_DESKTOP_NOTIFICATION = "send_desktop_notification"

TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT = "disable_systemd_user_unit"

TOOL_NAME_INSTALL_OS_PACKAGE = "install_os_package"

TOOL_NAME_UPGRADE_OS_PACKAGES_ALL = "upgrade_os_packages_all"

TOOL_NAME_MUTATE_EXTERNAL_FILE = "mutate_external_file"

TOOL_NAME_WRITE_CONFIG_FILE = "write_config_file"

TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT = "manage_workspace_artifact"

TOOL_NAME_APPLY_CANVAS_PATCH = "apply_canvas_patch"

_SCHEMA_EMPTY_OBJECT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}

_SCHEMA_LIST_PROCESSES: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
        }
    },
}

_SCHEMA_LIST_PROCESS_TREE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        "max_depth": {"type": "integer", "minimum": 1, "maximum": 32},
    },
}

_SCHEMA_LIST_LISTENING: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
        }
    },
}

_SCHEMA_NETWORK_ROUTES: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
}

_SCHEMA_NETWORK_CONNECTIONS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        "state": {"type": "string", "enum": ["ESTABLISHED", "ALL_ACTIVE"]},
    },
}

_SCHEMA_LIST_SYSTEMD_UNITS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
    },
}

_SCHEMA_LIST_DISK_PARTITIONS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 128},
    },
}

_SCHEMA_GREP_WORKSPACE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 4096},
        "pattern": {"type": "string", "minLength": 1, "maxLength": 400},
        "max_matches": {"type": "integer", "minimum": 1, "maximum": 500},
    },
    "required": ["path", "pattern"],
}

_JOURNAL_SINCE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["5m", "15m", "1h", "6h", "24h", "today"],
}

_JOURNAL_MAX_BYTES_SCHEMA: dict[str, Any] = {
    "type": "integer",
    "minimum": 256,
    "maximum": 65536,
}

_SCHEMA_GET_JOURNAL_TAIL: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "unit": {"type": "string", "minLength": 1, "maxLength": 256},
                "since": _JOURNAL_SINCE_SCHEMA,
                "max_bytes": _JOURNAL_MAX_BYTES_SCHEMA,
            },
            "required": ["unit"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "identifier": {"type": "string", "minLength": 1, "maxLength": 256},
                "since": _JOURNAL_SINCE_SCHEMA,
                "max_bytes": _JOURNAL_MAX_BYTES_SCHEMA,
            },
            "required": ["identifier"],
        },
    ]
}

_SCHEMA_QUERY_PACKAGES: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "package": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["package"],
}

_SCHEMA_GET_FILE_METADATA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 2048},
    },
    "required": ["path"],
}

_SCHEMA_READ_FILE_TEXT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 2048},
        "max_bytes": _JOURNAL_MAX_BYTES_SCHEMA,
    },
    "required": ["path"],
}

_SCHEMA_REQUEST_SHELL: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {"type": "string", "enum": ["argv", "sh_c"]},
        "argv": {
            "anyOf": [
                {"type": "null"},
                {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 64},
            ]
        },
        "sh_c": {
            "anyOf": [
                {"type": "null"},
                {"type": "string", "minLength": 1, "maxLength": 16384},
            ]
        },
        "cwd": {
            "anyOf": [
                {"type": "null"},
                {"type": "string", "maxLength": 2048},
            ]
        },
        "shell_session_id": {
            "anyOf": [
                {"type": "null"},
                {"type": "string", "minLength": 1, "maxLength": 256},
            ]
        },
        "intent": {"type": "string", "minLength": 1, "maxLength": 512},
        "timeout_sec": {
            "anyOf": [
                {"type": "null"},
                {"type": "integer", "minimum": 1, "maximum": 600},
            ]
        },
    },
    "required": ["mode", "intent"],
}

_SCHEMA_OPEN_BROWSER_URL: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "url": {"type": "string", "minLength": 1, "maxLength": 2048},
    },
    "required": ["url"],
}

_SCHEMA_SEND_DESKTOP_NOTIFICATION: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "body": {"type": "string", "minLength": 1, "maxLength": 512},
        "title": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["body"],
}

_SCHEMA_PROBE_NETWORK_ENDPOINT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {"type": "string", "minLength": 1, "maxLength": 253},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
        "kind": {"type": "string", "enum": ["tcp", "http"]},
        "path": {"type": "string", "maxLength": 256},
    },
    "required": ["host", "port", "kind"],
}

_USER_DISABLE_UNIT_PATTERN = r"^[a-zA-Z0-9_.@-]+\.(timer|socket)$"

_PACKAGE_INSTALL_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$"

_UNIX_SERVICE_USERNAME_PATTERN = r"^[a-z_][a-z0-9_-]{0,31}$"

_SCHEMA_ABS_PATH_POSIX: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 4096,
    "pattern": "^/",
}

_SCHEMA_MUTATE_EXTERNAL_FILE: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {"const": "delete"},
                "src_path": _SCHEMA_ABS_PATH_POSIX,
            },
            "required": ["operation", "src_path"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {"enum": ["copy", "move"]},
                "src_path": _SCHEMA_ABS_PATH_POSIX,
                "dst_path": _SCHEMA_ABS_PATH_POSIX,
            },
            "required": ["operation", "src_path", "dst_path"],
        },
    ]
}

_SCHEMA_WRITE_CONFIG_FILE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "pattern": "^/",
        },
        "content": {"type": "string", "maxLength": 32768},
        "create_backup": {"type": "boolean"},
    },
    "required": ["path", "content"],
}

_SCHEMA_WORKSPACE_ARTIFACT_CONTENT: dict[str, Any] = {
    "type": "string",
    "maxLength": 400_000,
}

_SCHEMA_MANAGE_WORKSPACE_CREATE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"const": "create"},
        "title": {"type": "string", "maxLength": 200},
        "artifact_type": {"type": "string", "enum": ["markdown", "plain", "json", "text"]},
        "content": _SCHEMA_WORKSPACE_ARTIFACT_CONTENT,
    },
    "required": ["action", "artifact_type", "content"],
}

_SCHEMA_MANAGE_WORKSPACE_REPLACE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"const": "replace"},
        "artifact_id": {"type": "string", "minLength": 8, "maxLength": 64},
        "title": {"type": "string", "maxLength": 200},
        "content": _SCHEMA_WORKSPACE_ARTIFACT_CONTENT,
    },
    "required": ["action", "artifact_id", "content"],
}

_SCHEMA_MANAGE_WORKSPACE_ARTIFACT: dict[str, Any] = {
    "oneOf": [_SCHEMA_MANAGE_WORKSPACE_CREATE, _SCHEMA_MANAGE_WORKSPACE_REPLACE]
}

_SCHEMA_APPLY_CANVAS_PATCH: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "artifact_id": {"type": "string", "minLength": 8, "maxLength": 64},
        "search_block": {"type": "string", "minLength": 1, "maxLength": 200_000},
        "replace_block": {"type": "string", "maxLength": 200_000},
    },
    "required": ["search_block", "replace_block"],
}

_SCHEMA_DISABLE_SYSTEMD_USER_UNIT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "unit": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "pattern": _USER_DISABLE_UNIT_PATTERN,
            "description": "Nome de unidade user .timer ou .socket (ex.: foo.timer)",
        },
    },
    "required": ["unit"],
}

_SCHEMA_INSTALL_OS_PACKAGE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "package": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "pattern": _PACKAGE_INSTALL_NAME_PATTERN,
        },
    },
    "required": ["package"],
}

_SCHEMA_UPGRADE_OS_PACKAGES_ALL: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}

_SCHEMA_CREATE_APPROVAL_REQUEST: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["process.signal"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "pid": {"type": "integer", "minimum": 2},
                    },
                    "required": ["pid"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["systemd.unit.restart"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "unit": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    "required": ["unit"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["systemd.unit.stop"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "unit": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    "required": ["unit"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["systemd.unit.enable"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "unit": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    "required": ["unit"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["systemd.unit.disable"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "unit": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    "required": ["unit"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["systemd.user.unit.disable"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "unit": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 256,
                            "pattern": _USER_DISABLE_UNIT_PATTERN,
                        },
                    },
                    "required": ["unit"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["filesystem.path.read_external"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                            "pattern": "^/",
                        },
                    },
                    "required": ["path"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["filesystem.path.write_config"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                            "pattern": "^/",
                        },
                        "content": {"type": "string", "maxLength": 32768},
                        "create_backup": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["network.firewall.rule.apply"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                        "protocol": {"type": "string", "enum": ["tcp", "udp"]},
                        "direction": {"type": "string", "enum": ["in", "out"]},
                        "action": {"type": "string", "enum": ["allow", "deny"]},
                    },
                    "required": ["port", "protocol", "direction", "action"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["network.firewall.policy.apply"]},
                "payload": {
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"operation": {"const": "reload"}},
                            "required": ["operation"],
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "operation": {"const": "set_default_zone"},
                                "zone": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 32,
                                    "pattern": "^[a-zA-Z0-9_-]+$",
                                },
                            },
                            "required": ["operation", "zone"],
                        },
                    ],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["desktop.open_url"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "url": {"type": "string", "minLength": 1, "maxLength": 2048},
                    },
                    "required": ["url"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["desktop.notify"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "body": {"type": "string", "minLength": 1, "maxLength": 512},
                        "title": {"type": "string", "minLength": 1, "maxLength": 128},
                    },
                    "required": ["body"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["network.endpoint.probe"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "host": {"type": "string", "minLength": 1, "maxLength": 253},
                        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                        "kind": {"type": "string", "enum": ["tcp", "http"]},
                        "path": {"type": "string", "maxLength": 256},
                    },
                    "required": ["host", "port", "kind"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["os.account.unix_useradd"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "username": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 32,
                            "pattern": _UNIX_SERVICE_USERNAME_PATTERN,
                        },
                    },
                    "required": ["username"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["os.packages.install"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "package": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                            "pattern": _PACKAGE_INSTALL_NAME_PATTERN,
                        },
                    },
                    "required": ["package"],
                },
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["os.packages.upgrade_all"]},
                "payload": {"type": "object", "additionalProperties": False, "properties": {}},
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["os.power.reboot"]},
                "payload": {"type": "object", "additionalProperties": False, "properties": {}},
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["os.power.shutdown"]},
                "payload": {"type": "object", "additionalProperties": False, "properties": {}},
            },
            "required": ["action_id", "payload"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string", "enum": ["shell.exec"]},
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mode": {"type": "string", "enum": ["argv", "sh_c"]},
                        "argv": {
                            "anyOf": [
                                {"type": "null"},
                                {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 64},
                            ]
                        },
                        "sh_c": {
                            "anyOf": [
                                {"type": "null"},
                                {"type": "string", "minLength": 1, "maxLength": 16384},
                            ]
                        },
                        "cwd": {
                            "anyOf": [
                                {"type": "null"},
                                {"type": "string", "maxLength": 2048},
                            ]
                        },
                        "shell_session_id": {
                            "anyOf": [
                                {"type": "null"},
                                {"type": "string", "minLength": 1, "maxLength": 256},
                            ]
                        },
                        "intent": {"type": "string", "minLength": 1, "maxLength": 512},
                        "timeout_sec": {
                            "anyOf": [
                                {"type": "null"},
                                {"type": "integer", "minimum": 1, "maximum": 600},
                            ]
                        },
                    },
                    "required": ["mode", "intent"],
                },
            },
            "required": ["action_id", "payload"],
        },
    ]
}

def create_approval_request_json_schema() -> dict[str, Any]:
    """Schema JSON da tool `create_approval_request` (contratos, testes, docs)."""
    return _SCHEMA_CREATE_APPROVAL_REQUEST

_TOOL_SPECS: dict[str, dict[str, Any]] = {}

def _init_tool_specs() -> None:
    from app.default_tools import DEFAULT_TOOL_SPECS as _DEFAULT_TOOLS
    _TOOL_SPECS.update(_DEFAULT_TOOLS)

_init_tool_specs()

# Legacy placeholder for backward compat — unused, kept to avoid import errors
_CORE_TOOL_SPECS: dict[str, dict[str, Any]] = {
    TOOL_NAME_GET_HOST_SUMMARY: {
        "plan_kind": "tool.host_summary",
        "plan_description_pt": "Opcional (agent tools): agregado read-only do host (system.summary + kernel-observer).",
        "arguments_schema": _SCHEMA_EMPTY_OBJECT,
        "risk_level": "P0",
        "maps_to_action_id": "system.summary",
        "protocol_hint_en": (
            f"{TOOL_NAME_GET_HOST_SUMMARY}: host summary (read-only); arguments {{}}."
        ),
    },
    TOOL_NAME_GET_JOURNAL_TAIL: {
        "plan_kind": "tool.get_journal_tail",
        "plan_description_pt": (
            "Opcional (agent tools): cauda read-only do journal systemd (journalctl); "
            "unit OU identifier allowlist no system-agent; since relativo enumerado; bytes máximos."
        ),
        "arguments_schema": _SCHEMA_GET_JOURNAL_TAIL,
        "risk_level": "P0",
        "maps_to_action_id": "systemd.journal.tail",
        "protocol_hint_en": (
            f'{TOOL_NAME_GET_JOURNAL_TAIL}: required unit OR identifier (allowlist enforced). '
            'Optional {"since":"1h"} and {"max_bytes":16384}.'
        ),
    },
    TOOL_NAME_LIST_PROCESSES: {
        "plan_kind": "tool.list_processes",
        "plan_description_pt": "Opcional (agent tools): lista truncada de processos (P0 read-only).",
        "arguments_schema": _SCHEMA_LIST_PROCESSES,
        "risk_level": "P0",
        "maps_to_action_id": "process.list",
        "protocol_hint_en": (
            f'{TOOL_NAME_LIST_PROCESSES}: optional {{"limit": N}}. Example: {{"limit":40}}.'
        ),
    },
    TOOL_NAME_LIST_PROCESS_TREE: {
        "plan_kind": "tool.list_process_tree",
        "plan_description_pt": (
            "Opcional (agent tools): processos com PPID e profundidade na árvore (read-only, truncado)."
        ),
        "arguments_schema": _SCHEMA_LIST_PROCESS_TREE,
        "risk_level": "P0",
        "maps_to_action_id": "process.tree",
        "protocol_hint_en": (
            f'{TOOL_NAME_LIST_PROCESS_TREE}: optional {{"limit": N, "max_depth": N}}.'
        ),
    },
    TOOL_NAME_LIST_LISTENING_SOCKETS: {
        "plan_kind": "tool.list_listening_sockets",
        "plan_description_pt": "Opcional (agent tools): sockets TCP/UDP em escuta (P0 read-only).",
        "arguments_schema": _SCHEMA_LIST_LISTENING,
        "risk_level": "P0",
        "maps_to_action_id": "network.listen.sockets",
        "protocol_hint_en": (
            f'{TOOL_NAME_LIST_LISTENING_SOCKETS}: optional {{"limit": N}}. Example: {{"limit":200}}.'
        ),
    },
    TOOL_NAME_GET_FILE_METADATA: {
        "plan_kind": "tool.get_file_metadata",
        "plan_description_pt": "Opcional (agent tools): metadata de ficheiro sob CENTRAL_ROOT (sem conteudo).",
        "arguments_schema": _SCHEMA_GET_FILE_METADATA,
        "risk_level": "P0",
        "maps_to_action_id": "filesystem.path.stat",
        "protocol_hint_en": (
            f'{TOOL_NAME_GET_FILE_METADATA}: required {{"path":"<CENTRAL_ROOT-relative>"}}.'
        ),
    },
    TOOL_NAME_GET_HARDWARE_SENSORS: {
        "plan_kind": "tool.get_hardware_sensors",
        "plan_description_pt": (
            "Opcional (agent tools): sensores read-only best-effort (GPU NVIDIA via nvidia-smi, bateria e "
            "temperaturas/ventoinhas via psutil); sub-blocos podem vir unavailable."
        ),
        "arguments_schema": _SCHEMA_EMPTY_OBJECT,
        "risk_level": "P0",
        "maps_to_action_id": "hardware.sensors",
        "protocol_hint_en": (
            f"{TOOL_NAME_GET_HARDWARE_SENSORS}: arguments {{}}; optional server env: "
            "NVIDIA_SMI_PATH, HARDWARE_SENSORS_TIMEOUT_SEC."
        ),
    },
    TOOL_NAME_LIST_DISK_USAGE: {
        "plan_kind": "tool.list_disk_usage",
        "plan_description_pt": (
            "Opcional (agent tools): uso de disco read-only por mountpoints permitidos no system-agent "
            "(DISK_USAGE_MOUNT_ALLOWLIST)."
        ),
        "arguments_schema": _SCHEMA_EMPTY_OBJECT,
        "risk_level": "P0",
        "maps_to_action_id": "filesystem.disk.usage",
        "protocol_hint_en": (
            f"{TOOL_NAME_LIST_DISK_USAGE}: disk usage totals (system-agent namespace); arguments {{}}."
        ),
    },
    TOOL_NAME_LIST_DISK_PARTITIONS: {
        "plan_kind": "tool.list_disk_partitions",
        "plan_description_pt": (
            "Opcional (agent tools): partições e mountpoints read-only (psutil.disk_partitions no system-agent; "
            "truncado por limite)."
        ),
        "arguments_schema": _SCHEMA_LIST_DISK_PARTITIONS,
        "risk_level": "P0",
        "maps_to_action_id": "filesystem.disk.partitions",
        "protocol_hint_en": (
            f"{TOOL_NAME_LIST_DISK_PARTITIONS}: partitions/mountpoints (system-agent namespace); "
            'optional arguments {"limit": N}.'
        ),
    },
    TOOL_NAME_GREP_WORKSPACE: {
        "plan_kind": "tool.grep_workspace",
        "plan_description_pt": (
            "Opcional (agent tools): busca textual read-only com ripgrep num directório absoluto sob "
            "WORKSPACE_GREP_ROOT_ALLOWLIST (ex.: /central ou /workspace em dev)."
        ),
        "arguments_schema": _SCHEMA_GREP_WORKSPACE,
        "risk_level": "P0",
        "maps_to_action_id": "filesystem.workspace.grep",
        "protocol_hint_en": (
            f'{TOOL_NAME_GREP_WORKSPACE}: required arguments {{"path":"/abs/dir","pattern":"regex"}}; '
            'optional {"max_matches": N}. Example: {"path":"/central","pattern":"TODO","max_matches":40}.'
        ),
    },
    TOOL_NAME_LIST_NETWORK_INTERFACES: {
        "plan_kind": "tool.list_network_interfaces",
        "plan_description_pt": (
            "Opcional (agent tools): interfaces de rede e endereços (IPv4/IPv6/MAC), up/down (read-only)."
        ),
        "arguments_schema": _SCHEMA_EMPTY_OBJECT,
        "risk_level": "P0",
        "maps_to_action_id": "network.interfaces",
        "protocol_hint_en": (f"{TOOL_NAME_LIST_NETWORK_INTERFACES}: arguments {{}}."),
    },
    TOOL_NAME_GET_NETWORK_ROUTES: {
        "plan_kind": "tool.get_network_routes",
        "plan_description_pt": (
            "Opcional (agent tools): rotas IPv4 truncadas (Linux /proc/net/route); gateway por defeito quando visível."
        ),
        "arguments_schema": _SCHEMA_NETWORK_ROUTES,
        "risk_level": "P0",
        "maps_to_action_id": "network.routes",
        "protocol_hint_en": (
            f'{TOOL_NAME_GET_NETWORK_ROUTES}: optional arguments {{"limit": N}}.'
        ),
    },
    TOOL_NAME_GET_CENTRAL_STACK_HEALTH: {
        "plan_kind": "tool.get_central_stack_health",
        "plan_description_pt": (
            "Opcional (agent tools): health read-only dos serviços (URLs por env no orquestrador); "
            "sem system-agent."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_EMPTY_OBJECT,
        "risk_level": "P0",
        "maps_to_action_id": "orchestrator.stack.health",
        "protocol_hint_en": (
            f"{TOOL_NAME_GET_CENTRAL_STACK_HEALTH}: service health aggregation; arguments {{}}."
        ),
    },
    TOOL_NAME_LIST_NETWORK_CONNECTIONS: {
        "plan_kind": "tool.list_network_connections",
        "plan_description_pt": (
            "Opcional (agent tools): conexões de rede inet (resumo truncado); filtro ESTABLISHED ou ALL_ACTIVE."
        ),
        "arguments_schema": _SCHEMA_NETWORK_CONNECTIONS,
        "risk_level": "P0",
        "maps_to_action_id": "network.connections",
        "protocol_hint_en": (
            f'{TOOL_NAME_LIST_NETWORK_CONNECTIONS}: optional {{"limit": N, "state":"ESTABLISHED"|"ALL_ACTIVE"}}.'
        ),
    },
    TOOL_NAME_LIST_SYSTEMD_UNITS: {
        "plan_kind": "tool.list_systemd_units",
        "plan_description_pt": (
            "Opcional (agent tools): unidades systemd tipo service (read-only via systemctl list-units; truncado)."
        ),
        "arguments_schema": _SCHEMA_LIST_SYSTEMD_UNITS,
        "risk_level": "P0",
        "maps_to_action_id": "systemd.units.list",
        "protocol_hint_en": (
            f"{TOOL_NAME_LIST_SYSTEMD_UNITS}: systemd units (may be unavailable in containers); "
            'optional arguments {"limit": N}.'
        ),
    },
    TOOL_NAME_QUERY_INSTALLED_PACKAGES: {
        "plan_kind": "tool.query_installed_packages",
        "plan_description_pt": (
            "Opcional (agent tools): consulta read-only rpm/dpkg; nome de pacote tem de bater com "
            "OS_PACKAGES_QUERY_ALLOWLIST no system-agent (exacto ou prefixo com * na allowlist)."
        ),
        "arguments_schema": _SCHEMA_QUERY_PACKAGES,
        "risk_level": "P0",
        "maps_to_action_id": "os.packages.query",
        "protocol_hint_en": (
            f'{TOOL_NAME_QUERY_INSTALLED_PACKAGES}: arguments {{"package":"<name>"}} (allowlist enforced).'
        ),
    },
    TOOL_NAME_READ_FILE_TEXT: {
        "plan_kind": "tool.read_file_text",
        "plan_description_pt": (
            "Opcional (agent tools): texto UTF-8 read-only de ficheiro sob CENTRAL_ROOT; path tem de "
            "começar por prefixo em FILE_READ_PREFIX_ALLOWLIST; max bytes limitado."
        ),
        "arguments_schema": _SCHEMA_READ_FILE_TEXT,
        "risk_level": "P0",
        "maps_to_action_id": "filesystem.path.read",
        "protocol_hint_en": (
            f'{TOOL_NAME_READ_FILE_TEXT}: required {{"path":"<CENTRAL_ROOT-relative>"}}; optional {{"max_bytes": N}}. '
            'Example: {"path":"state/playbook.json","max_bytes":32768}.'
        ),
    },
    TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT: {
        "plan_kind": "tool.manage_workspace_artifact",
        "plan_description_pt": (
            "T2: cria ou substitui o conteúdo do artefacto de workspace (canvas) para esta sessão de pedido "
            "(in-process; não grava disco). Tipos: markdown, plain, json, text. Usar para documentos grandes "
            "antes de `apply_canvas_patch`."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_MANAGE_WORKSPACE_ARTIFACT,
        "risk_level": "P0",
        "maps_to_action_id": "orchestrator.workspace.artifact",
        "protocol_hint_en": (
            f'{TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT}: '
            'create {{"action":"create","title":"<pt-BR short>","artifact_type":"markdown"|...,"content":"..."}} '
            '(server returns artifact_id in TOOL_RESULT); '
            'replace {{"action":"replace","artifact_id":"<from TOOL_RESULT>","content":"..."}}; '
            'optional "title" on replace to rename tab.'
        ),
    },
    TOOL_NAME_APPLY_CANVAS_PATCH: {
        "plan_kind": "tool.apply_canvas_patch",
        "plan_description_pt": (
            "T2: substitui exactamente uma ocorrência de `search_block` por `replace_block`. "
            "Com vários artefactos no pedido, `artifact_id` (do TOOL_RESULT) é obrigatório; com um só, "
            "pode omitir `artifact_id` (política de transição; ADR-013). Falhas: id inválido, vários sem id, "
            "zero correspondências ou âncora ambígua."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_APPLY_CANVAS_PATCH,
        "risk_level": "P0",
        "maps_to_action_id": "orchestrator.workspace.canvas_patch",
        "protocol_hint_en": (
            f'{TOOL_NAME_APPLY_CANVAS_PATCH}: '
            '{"artifact_id":"<optional if exactly one artifact>","search_block":"<exact substring>",'
            '"replace_block":"<new text>"} (single match; artifact_id required when multiple artifacts).'
        ),
    },
    TOOL_NAME_CLIENT_READ_FILE: {
        "plan_kind": "tool.client_read_file",
        "plan_description_pt": (
            "Leitura read-only de ficheiro de texto no teu dispositivo (agente local / connector). "
            "path absoluto no PC do utilizador; nao usa paths do servidor Central."
        ),
        "plan_target": "connector",
        "arguments_schema": _SCHEMA_READ_FILE_TEXT,
        "risk_level": "P0",
        "maps_to_action_id": "file.read",
        "protocol_hint_en": (
            f'{TOOL_NAME_CLIENT_READ_FILE}: required {{"path":"/abs/path"}}; optional {{"max_bytes": N}}. '
            "Runs on the local connector when online."
        ),
    },
    TOOL_NAME_CLIENT_GREP: {
        "plan_kind": "tool.client_grep",
        "plan_description_pt": (
            "Pesquisa textual (ripgrep) num directório do teu dispositivo via connector. "
            "path absoluto da pasta raiz da pesquisa no PC do utilizador."
        ),
        "plan_target": "connector",
        "arguments_schema": _SCHEMA_GREP_WORKSPACE,
        "risk_level": "P0",
        "maps_to_action_id": "file.grep",
        "protocol_hint_en": (
            f'{TOOL_NAME_CLIENT_GREP}: required {{"path":"/abs/dir","pattern":"regex"}}; '
            'optional {{"max_matches": N}}. Runs on the local connector when online.'
        ),
    },
    TOOL_NAME_REQUEST_SHELL: {
        "plan_kind": "tool.request_shell",
        "plan_description_pt": (
            "Carta para o shell com porteiro no orquestrador: modo argv (lista de strings) ou sh_c (string). "
            "P0 read-only mapeado executa ja; sh_c ou binario fora do mapa vao para a fila de aprovacao (shell.exec). "
            "intent obrigatorio (texto curto para UI/audit). shell_session_id e OPCIONAL: OMITIR a chave ou usar "
            "null para um comando isolado (sem PTY); usar string UUID apenas para reutilizar a mesma sessao bash "
            "entre varias chamadas request_shell."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_REQUEST_SHELL,
        "risk_level": "P2",
        "maps_to_action_id": "shell.exec",
        "protocol_hint_en": (
            f"{TOOL_NAME_REQUEST_SHELL}: required mode+intent. Use argv (array) or sh_c (string) depending on mode. "
            "Prefer omitting cwd (or use null); only send cwd as a string if you must, and it must realpath under an allowlisted prefix. "
            "Omit shell_session_id (or use null) unless you need a persistent PTY; use a UUID string to reuse a bash session. "
            'Example argv: {"mode":"argv","intent":"list","argv":["ls","-la","/central"],"cwd":"/central","timeout_sec":30}. '
            'Example sh_c: {"mode":"sh_c","intent":"pwd","sh_c":"cd /tmp && pwd","shell_session_id":"<uuid>"}.'
        ),
    },
    TOOL_NAME_CREATE_APPROVAL_REQUEST: {
        "plan_kind": "tool.create_approval_request",
        "plan_description_pt": (
            "Opcional (Opcao B): cria pendencia na fila (process.signal, systemd.unit.restart, systemd.unit.stop, "
            "systemd.unit.enable, systemd.unit.disable (P3 Onda 3 system), "
            "systemd.user.unit.disable, filesystem.path.read_external, filesystem.path.write_config (P2-3), "
            "desktop.open_url, desktop.notify, network.endpoint.probe, "
            "network.firewall.rule.apply (P2-4), network.firewall.policy.apply (P3 Onda 5 firewalld reload/zona; capability opt-in), "
            "os.packages.install (P2-5), os.account.unix_useradd (P3 Onda 6a; useradd sistema; "
            "UNIX_USERADD_ALLOWED_USERNAMES + OS_ACCOUNT_UNIX_USERADD_ENABLED; wheel/sudoers fora de alcance), "
            "os.packages.upgrade_all (P3 Onda 4; "
            "payload {{}}; dupla confirmação; OS_PACKAGES_UPGRADE_ALL_ENABLED), os.power.reboot / os.power.shutdown (P3 Onda 2; "
            "payload {{}}; capability desligada por defeito)); nao executa — requer aprovacao humana. "
            "P2-6 mutate_external: tool dedicada `mutate_external_file` ate haver `action_id` na fila/schema."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_CREATE_APPROVAL_REQUEST,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_CREATE_APPROVAL_REQUEST}: arguments {{"action_id":"...","payload":{{...}}}}. '
            'Example: {"action_id":"process.signal","payload":{"pid":1234}}.'
        ),
    },
    TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT: {
        "plan_kind": "tool.disable_systemd_user_unit",
        "plan_description_pt": (
            "Opcional (P2 Onda 2): cria pendencia para systemctl --user disable em unidade .timer ou .socket; "
            "execucao apos aprovar (allowlist SYSTEMD_USER_UNIT_DISABLE_ALLOWLIST no system-agent)."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_DISABLE_SYSTEMD_USER_UNIT,
        "risk_level": "P2",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT}: arguments {{"unit":"<name.timer|name.socket>"}} (HITL approval).'
        ),
    },
    TOOL_NAME_INSTALL_OS_PACKAGE: {
        "plan_kind": "tool.install_os_package",
        "plan_description_pt": (
            "Opcional (P2 Onda 5): cria pendencia para instalar um pacote com nome exacto na allowlist "
            "(dnf/apt/microdnf apos aprovar; Polkit + helper no host)."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_INSTALL_OS_PACKAGE,
        "risk_level": "P2",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_INSTALL_OS_PACKAGE}: arguments {{"package":"<name>"}} (allowlist + approval).'
        ),
    },
    TOOL_NAME_UPGRADE_OS_PACKAGES_ALL: {
        "plan_kind": "tool.upgrade_os_packages_all",
        "plan_description_pt": (
            "Opcional (P3 Onda 4): cria pendencia para actualização massiva de pacotes (dnf upgrade / apt-get upgrade); "
            "Polkit + helper; opt-in OS_PACKAGES_UPGRADE_ALL_ENABLED; dupla confirmação obrigatória na policy."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_UPGRADE_OS_PACKAGES_ALL,
        "risk_level": "P3",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f"{TOOL_NAME_UPGRADE_OS_PACKAGES_ALL}: arguments {{}} (requires approval; disruptive)."
        ),
    },
    TOOL_NAME_MUTATE_EXTERNAL_FILE: {
        "plan_kind": "tool.mutate_external_file",
        "plan_description_pt": (
            "Opcional (P2-6): cria pendencia para copiar, mover ou apagar um ficheiro regular fora de CENTRAL_ROOT "
            "(allowlists separadas origem/destino no system-agent; destino nao pode existir)."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_MUTATE_EXTERNAL_FILE,
        "risk_level": "P2",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_MUTATE_EXTERNAL_FILE}: '
            'delete {"operation":"delete","src_path":"/abs"}; '
            'copy/move {"operation":"copy"|"move","src_path":"/a","dst_path":"/b"} (approval required).'
        ),
    },
    TOOL_NAME_WRITE_CONFIG_FILE: {
        "plan_kind": "tool.write_config_file",
        "plan_description_pt": (
            "Opcional (P2-3): cria pendencia para gravar texto UTF-8 num ficheiro de configuracao (path absoluto "
            "sob FILE_WRITE_CONFIG_PREFIX_ALLOWLIST; sufixos; backup .bak opcional)."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_WRITE_CONFIG_FILE,
        "risk_level": "P2",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_WRITE_CONFIG_FILE}: arguments '
            '{"path":"/abs/file","content":"<utf-8>","create_backup":true} (approval required).'
        ),
    },
    TOOL_NAME_OPEN_BROWSER_URL: {
        "plan_kind": "tool.open_browser_url",
        "plan_description_pt": (
            "Opcional (P1): cria pendencia desktop.open_url; execucao no host apos aprovar "
            "(CENTRAL_DESKTOP_HELPER ou legado SOPHIA_DESKTOP_HELPER). Requer allowlist de hosts."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_OPEN_BROWSER_URL,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_OPEN_BROWSER_URL}: arguments {{"url":"https://..."}} (approval required).'
        ),
    },
    TOOL_NAME_PROBE_NETWORK_ENDPOINT: {
        "plan_kind": "tool.probe_network_endpoint",
        "plan_description_pt": (
            "Opcional (P1): cria pendencia para sondagem TCP ou HTTP a um host:port na allowlist "
            "(CENTRAL_PROBE_ALLOWLIST ou legado SOPHIA_PROBE_ALLOWLIST); execucao apos aprovar."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_PROBE_NETWORK_ENDPOINT,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_PROBE_NETWORK_ENDPOINT}: arguments '
            '{"host":"<host>","port":N,"kind":"tcp"|"http","path":"<optional>"} (allowlist + approval).'
        ),
    },
    TOOL_NAME_SEND_DESKTOP_NOTIFICATION: {
        "plan_kind": "tool.send_desktop_notification",
        "plan_description_pt": (
            "Opcional (P1): cria pendencia desktop.notify (texto curto); execucao no host apos aprovar."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_SEND_DESKTOP_NOTIFICATION,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.approval.create",
        "protocol_hint_en": (
            f'{TOOL_NAME_SEND_DESKTOP_NOTIFICATION}: arguments {{"body":"<text>","title":"<optional>"}} (approval).'
        ),
    },
}

# ═══ PRIMARY_AGENT_TOOLS ═══

"""Filtro opcional do catálogo de tools via JSON (PRIMARY_AGENT_TOOLS_PATH)."""

def _load_allowed_names(path: str) -> frozenset[str] | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    tools = raw.get("active_tools")
    if not isinstance(tools, list) or not tools:
        return None
    out: set[str] = set()
    for x in tools:
        if isinstance(x, str) and x.strip():
            out.add(x.strip())
    return frozenset(out) if out else None

def filter_tool_specs(specs: dict[str, dict[str, Any]], *, path: str) -> dict[str, dict[str, Any]]:
    allowed = _load_allowed_names(path)
    if allowed is None:
        return specs
    filtered = {k: v for k, v in specs.items() if k in allowed}
    if not filtered:
        return specs
    return filtered


_pkinds = [spec["plan_kind"] for spec in _TOOL_SPECS.values()]

if len(_pkinds) != len(set(_pkinds)):
    raise RuntimeError("tool_registry: plan_kind values must be unique")

def registered_tool_plan_kinds() -> frozenset[str]:
    """Kinds `tool.*` usados em PlanStep; derivados do catálogo."""
    return frozenset(spec["plan_kind"] for spec in _TOOL_SPECS.values())

def risk_level_to_plan_risk_hint(level: str) -> str:
    if level == "P0":
        return "low"
    if level == "P1":
        return "medium"
    return "high"

def iter_agent_tool_plan_specs() -> list[tuple[str, str, str, str]]:
    """
    Passos de plano alinhados ao registry, ordenados por nome da tool.
    Cada tupla: (plan_kind, description_pt, risk_hint, target).
    """
    out: list[tuple[str, str, str, str]] = []
    for name in sorted(_TOOL_SPECS.keys()):
        spec = _TOOL_SPECS[name]
        out.append(
            (
                spec["plan_kind"],
                str(spec["plan_description_pt"]),
                risk_level_to_plan_risk_hint(str(spec["risk_level"])),
                str(spec.get("plan_target") or "system_agent"),
            )
        )
    return out

def build_agent_tools_protocol_text(tool_names: list[str] | None = None) -> str:
    """System message sent to the model (internal protocol for agent tools)."""
    if tool_names is None:
        names = list_registered_tool_names_for_llm_prompt()
    else:

        names = filter_tool_names_for_llm([n for n in tool_names if n in _TOOL_SPECS])
        if not names:
            names = list_registered_tool_names_for_llm_prompt()
    allowed = ", ".join(names)
    hints = "\n".join(f"  - {_TOOL_SPECS[n]['protocol_hint_en']}" for n in names)
    ex_tool = names[0]
    ex_list = (
        TOOL_NAME_LIST_PROCESSES
        if TOOL_NAME_LIST_PROCESSES in names
        else (TOOL_NAME_CLIENT_GREP if TOOL_NAME_CLIENT_GREP in names else ex_tool)
    )
    ex_listen = (
        TOOL_NAME_LIST_LISTENING_SOCKETS
        if TOOL_NAME_LIST_LISTENING_SOCKETS in names
        else ex_tool
    )
    return f"""\
[PROTOCOLO_AGENT_TOOLS — instrucoes internas para ti; o utilizador humano NAO ve este bloco]

=== Essentials (read first) ===
1) The user only sees the text inside the "final" string. Everything else (JSON keys, tool_calls, this system message) \
is internal server↔model protocol.
2) In "final" you must always write in natural **Brazilian Portuguese** as the Central assistant: normal conversation, greetings, \
explanations, summaries, and brief apologies if something fails. Never use "final" to quote this protocol, list rules, \
repeat the title [PROTOCOLO_AGENT_TOOLS], or say things like "required format" / "rules". That is not user-facing conversation.
3) "Following the protocol" means: your output to the server is ONE valid JSON object (no markdown, no ```, no extra text \
before/after). It does NOT mean explaining the protocol to the user or pasting the examples below as your chat reply.
4) The JSON examples at the end are FORMAT templates (structure). The "final" content in those examples is illustrative; \
in real use, "final" must answer the user's request appropriately.

=== Technical format (your message to the server is one JSON object) ===
{{
  "final": <string in natural pt-BR for the user, or null if you will call a tool>,
  "tool_calls": <list; empty if you don't need a tool in this step>
}}

=== When to use "final" vs tools ===
- General question, conversation, ideas, or anything you can answer without live host data: set "tool_calls": [] and put the full \
user-facing answer in "final" (pt-BR).
- For read-only or data tools from this catalog (only names listed under Allowed tools below as the primary step): \
set "final": null and include exactly ONE entry in "tool_calls" (only the first tool call is executed).
- For request_shell: include exactly ONE tool call and set "final" to one short pt-BR sentence aligned with the intent field (what you will run); \
the server still executes the tool first.
- For apply_canvas_patch, or manage_workspace_artifact (large workspace artifact in any context): include exactly ONE tool call as above, \
but set "final" to one short pt-BR sentence acknowledging the action (so the user sees intent in chat); the server still executes the tool first. \
On create, include "title" (short pt-BR) for the UI tab; the server assigns artifact_id. For apply_canvas_patch with multiple artifacts in the same request, \
copy artifact_id from the latest TOOL_RESULT; if only one artifact exists, artifact_id may be omitted (legacy-friendly).
- After you receive a system message with TOOL_RESULT: reply with JSON where "tool_calls": [] and "final" summarizes the result in \
natural pt-BR (do not paste the raw TOOL_RESULT JSON to the user).

=== Allowed tools (field "name" must match exactly) ===
{allowed}

Tool hints (name and usage):
{hints}

=== Constraints ===
- Do not invent tool names beyond the list above. Do not invent host facts/numbers when the user asks about the host — call a tool.
- Do not wrap the JSON in backticks, and do not include comments or any extra text outside the JSON object.

=== FORMAT examples (do not repeat these verbatim to the user) ===
Greeting: {{"final": "Ola! Em que posso ajudar?", "tool_calls": []}}
Host summary (step 1): {{"final": null, "tool_calls": [{{"name": "{ex_tool}", "arguments": {{}}}}]}}
List processes with limit: {{"final": null, "tool_calls": [{{"name": "{ex_list}", "arguments": {{"limit": 20}}}}]}}
Listening ports: {{"final": null, "tool_calls": [{{"name": "{ex_listen}", "arguments": {{}}}}]}}
Request shell (step 1, short chat + tool): {{"final": "Vou executar no shell permitido: inspeccionar o Makefile.", "tool_calls": [{{"name": "request_shell", "arguments": {{"mode": "execute", "intent": "...", "command": "grep -C 1 -- -O2 Makefile", "timeout_sec": 30}}}}]}}
Workspace create: {{"final": "Crio o artefacto pedido.", "tool_calls": [{{"name": "manage_workspace_artifact", "arguments": {{"action": "create", "title": "Notas", "artifact_type": "markdown", "content": "# ..."}}}}]}}
Canvas patch (single artifact; id optional): {{"final": "Aplico o patch no artefacto.", "tool_calls": [{{"name": "apply_canvas_patch", "arguments": {{"search_block": "OLD", "replace_block": "NEW"}}}}]}}
After TOOL_RESULT (step 2): {{"final": "Aqui esta o resumo em linguagem natural com base nos dados.", "tool_calls": []}}
"""

def iter_client_tool_rag_source_rows() -> list[tuple[str, str, dict[str, Any]]]:
    """ADR-017 D7 — client-tool hints for ``client_tools`` RAG namespace (kind=client_tool)."""

    rows: list[tuple[str, str, dict[str, Any]]] = []
    for name in sorted(_TOOL_SPECS.keys()):
        if get_tool_execution_class(name) != "client":
            continue
        spec = _TOOL_SPECS[name]
        desc = str(spec.get("plan_description_pt") or "")
        hint = str(spec.get("protocol_hint_en") or "")
        doc = f"{name}\n{desc}\n{hint}".strip()
        schema = spec["arguments_schema"]
        if not isinstance(schema, dict):
            continue
        rows.append((name, doc, schema))
    return rows

def iter_agent_tool_rag_source_rows() -> list[tuple[str, str, dict[str, Any]]]:
    """Documento de texto + schema por tool registada (F4 ingest RAG)."""

    rows: list[tuple[str, str, dict[str, Any]]] = []
    for name in sorted(_TOOL_SPECS.keys()):
        if get_tool_execution_class(name) == "client":
            continue
        spec = _TOOL_SPECS[name]
        desc = str(spec.get("plan_description_pt") or "")
        hint = str(spec.get("protocol_hint_en") or "")
        doc = f"{name}\n{desc}\n{hint}".strip()
        schema = spec["arguments_schema"]
        if not isinstance(schema, dict):
            continue
        rows.append((name, doc, schema))
    return rows

def list_registered_tool_names() -> list[str]:
    return sorted(_TOOL_SPECS.keys())

def list_registered_tool_names_for_llm_prompt() -> list[str]:
    """Subset of registered tools exposed to the LLM protocol (ADR-017 catalog policy)."""

    return filter_tool_names_for_llm(list_registered_tool_names())

def get_agent_tools_catalog() -> list[dict[str, Any]]:
    """Metadados seguros para GET /config (sem handlers)."""
    return [
        {
            "name": n,
            "risk_level": _TOOL_SPECS[n]["risk_level"],
            "maps_to_action_id": _TOOL_SPECS[n]["maps_to_action_id"],
            "description": _TOOL_SPECS[n].get("plan_description_pt", ""),
        }
        for n in sorted(_TOOL_SPECS.keys())
    ]

def _resolve_tool_spec(name: str) -> dict[str, Any] | None:
    """Active catalog entry, or core spec for platform tools hidden from the LLM (ADR-017-8)."""
    n = name.strip()
    if n in _TOOL_SPECS:
        return _TOOL_SPECS[n]
    return None

def is_registered_tool(name: str) -> bool:
    return _resolve_tool_spec(name) is not None

def validate_tool_arguments(tool_name: str, arguments: Any) -> str | None:
    """
    None se valido; senao mensagem curta para audit/log (nao expor stack ao utilizador).
    """
    spec = _resolve_tool_spec(tool_name)
    if spec is None:
        return "unknown_tool"
    if not isinstance(arguments, dict):
        return "arguments_must_be_object"
    try:
        jsonschema.validate(instance=arguments, schema=spec["arguments_schema"])
    except jsonschema.ValidationError as exc:
        return str(exc.message)
    return None

def dispatch_tool(
    tool_name: str,
    arguments: dict[str, Any],
    request_id: str,
    *,
    workspace_store_key: str | None = None,
    canvas_write_ctx: dict[str, Any] | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Executa tool registada apos validacao externa. Levanta RuntimeError se nome invalido
    (defesa em profundidade — o loop so deve chamar apos is_registered_tool + validate).

    ``workspace_store_key`` (F1/A1): chave estável do store de canvas entre POSTs; omissão usa
    ``request_id``. Demais tools ignoram e continuam a usar ``request_id`` para correlação.

    ``canvas_write_ctx`` (Fase 10 / G6): slot activo, grafo e enforcement multi-slot; só usado
    por ferramentas de canvas.

    ``tenant_id`` (ADR-017): scope for policy and downstream client jobs (optional; uses JWT context).
    """
    from app.shared.approvals_store import resolve_tenant_id_for_store  # noqa: PLC0415

    name = tool_name.strip()
    tid = resolve_tenant_id_for_store(tenant_id)
    policy = classify_tool_call(name, arguments, tid)
    if not policy.allowed:
        out: dict[str, Any] = {
            "ok": False,
            "error": policy.error_code or "policy_denied",
            "request_id": request_id,
        }
        if policy.message_pt:
            out["message_pt"] = policy.message_pt
        return out
    ws_key = request_id if workspace_store_key is None else workspace_store_key
    from app.old_tools.platform_dispatch import dispatch_legacy_platform_tool  # noqa: PLC0415

    legacy_out = dispatch_legacy_platform_tool(name, arguments, request_id)
    if legacy_out is not None:
        return legacy_out
    if name == TOOL_NAME_CLIENT_READ_FILE:
        return dispatch_client_read_file(
            arguments=arguments,
            request_id=request_id,
            canvas_write_ctx=canvas_write_ctx,
        )
    if name == TOOL_NAME_CLIENT_GREP:
        return dispatch_client_grep(
            arguments=arguments,
            request_id=request_id,
            canvas_write_ctx=canvas_write_ctx,
        )
    if name == TOOL_NAME_REQUEST_SHELL:
        return dispatch_request_shell(
            arguments=arguments,
            request_id=request_id,
            canvas_write_ctx=canvas_write_ctx,
        )
    if name == TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT:
        return workspace_manage_artifact(ws_key, arguments, write_ctx=canvas_write_ctx)
    if name == TOOL_NAME_APPLY_CANVAS_PATCH:
        return workspace_apply_canvas_patch(ws_key, arguments, write_ctx=canvas_write_ctx)
    if name == TOOL_NAME_WEB_RESEARCH:
        q = str(arguments.get("query", "")).strip()
        tier = arguments.get("tier", "default")
        if not isinstance(tier, str):
            tier = "default"
        return run_web_research(request_id, query=q, tier=tier.strip() or "default")
    if name == TOOL_NAME_DRAFT_SOCIAL_POST:
        platform = str(arguments.get("platform", "")).strip()
        topic = str(arguments.get("topic", "")).strip()
        tone_raw = arguments.get("tone")
        tone = tone_raw.strip() if isinstance(tone_raw, str) and tone_raw.strip() else None
        mc = arguments.get("max_chars")
        max_chars = mc if isinstance(mc, int) else None
        return run_draft_social_post(
            request_id,
            platform=platform,
            topic=topic,
            tone=tone,
            max_chars=max_chars,
        )
    if name == TOOL_NAME_GENERATE_POST_IMAGE:
        pr = str(arguments.get("prompt", "")).strip()
        asp = arguments.get("aspect")
        aspect = asp.strip() if isinstance(asp, str) and asp.strip() else None
        return run_generate_post_image(request_id, prompt=pr, aspect=aspect)

    # T14 — Default tools: route 12 standard tools
    from app.default_tools import _DEFAULT_TOOL_NAMES_SET, dispatch_default_tool  # noqa: PLC0415
    if name.strip() in _DEFAULT_TOOL_NAMES_SET:
        return dispatch_default_tool(name, arguments, request_id)

    raise RuntimeError(f"dispatch_missing_for_tool:{name}")


# ═══ TOOL_POLICY ═══

"""ADR-017 — server-side tool policy before dispatch (catalog class, tenant)."""

@dataclass
class PolicyResult:
    allowed: bool
    error_code: str | None = None
    message_pt: str | None = None

def classify_tool_call(
    tool: str,
    args: dict[str, Any],
    tenant_id: str | None,
) -> PolicyResult:
    """
    Policy gate between parsed tool JSON and execution.

    ``tenant_id`` is reserved for connector-online / quota checks in later ADR-017 phases.
    """
    name = tool.strip()
    tid = (tenant_id or "").strip() or None
    if not is_registered_tool(name):
        return PolicyResult(
            allowed=False,
            error_code="unknown_tool",
            message_pt="Ferramenta desconhecida.",
        )
    if not is_tool_exposed_to_llm(name):
        cls = get_tool_execution_class(name)
        if cls == "platform":
            return PolicyResult(
                allowed=False,
                error_code="platform_tool_disabled",
                message_pt=(
                    "Esta acao corre no servidor Central (ops) e nao esta disponivel "
                    "no assistente do tenant. Use o connector local quando disponivel."
                ),
            )
        if cls == "internal_meta":
            return PolicyResult(
                allowed=False,
                error_code="approval_meta_tool_disabled",
                message_pt=(
                    "Pedidos de aprovacao sao criados pelo orquestrador; "
                    "nao chames a meta-tool de aprovacao."
                ),
            )
        return PolicyResult(
            allowed=False,
            error_code="tool_not_exposed",
            message_pt="Ferramenta nao disponivel neste perfil.",
        )
    if get_tool_execution_class(name) == "client":
        if not tenant_shell_uses_client_connector():
            return PolicyResult(
                allowed=False,
                error_code="client_execution_disabled",
                message_pt=(
                    "Esta ferramenta corre no teu dispositivo; nao esta disponivel "
                    "no modo legado do servidor."
                ),
            )
        if not connector_online_for_tenant(tenant_id=tid):
            return PolicyResult(
                allowed=False,
                error_code="client_agent_offline",
                message_pt=CLIENT_AGENT_OFFLINE_MESSAGE_PT,
            )
    try:
        from app.shared.policy_engine import evaluate_tool_policy

        args_map = arguments if isinstance(arguments, dict) else {}
        wp = None
        for key in ("cwd", "path", "workspace_path"):
            v = args_map.get(key)
            if isinstance(v, str) and v.strip():
                wp = v.strip()
                break
        eng = evaluate_tool_policy(
            name,
            args_map,
            tenant_id=tid,
            workspace_path=wp,
        )
        if not eng.allowed:
            try:
                from app.shared.policy_audit import record_policy_violation
                from app.shared.tenant_context import get_current_sub

                policies = {}
                try:
                    from app.shared.policy_engine import _load_tenant_policies

                    policies = _load_tenant_policies(tid or "default")
                except Exception:
                    pass
                record_policy_violation(
                    tool=name,
                    tenant_id=tid,
                    user_id=get_current_sub(),
                    path=wp,
                    error_code=eng.error_code,
                    message_pt=eng.message_pt,
                    violation=eng.violation,
                    bundle_id=str(policies.get("_bundle_id") or "") or None,
                    bundle_version=policies.get("_bundle_version"),
                    args=args_map,
                )
            except Exception:
                pass
            return PolicyResult(
                allowed=False,
                error_code=eng.error_code or "policy_denied",
                message_pt=eng.message_pt,
            )
    except Exception:
        logger.warning("policy_engine_unavailable tool=%s", name, exc_info=True)
        return PolicyResult(
            allowed=False,
            error_code="policy_engine_unavailable",
            message_pt="Política temporariamente indisponível; operação bloqueada.",
        )
    return PolicyResult(allowed=True)


# ═══ AGENT_TOOL_METRICS ═══

"""
Fase I — métricas Prometheus para o canal tool-use (deny-by-default + execuções OK).
Prioridade #6 — digest L0-2 no prompt: contagens e correlação tool_denied (campo audit capability_digest_in_prompt).
"""

TOOL_DENIED_TOTAL = Counter(
    "central_orchestrator_tool_denied_total",
    "Tool rejeitada antes de despacho (nome fora do registry ou schema)",
    ["reason"],
)

TOOL_INVOKED_TOTAL = Counter(
    "central_orchestrator_tool_invoked_total",
    "Tool aceite para execucao apos validacao de nome e argumentos",
    ["tool"],
)

TOOL_EXECUTION_OK_TOTAL = Counter(
    "central_orchestrator_tool_execution_ok_total",
    "Execucao de tool concluida sem excepcao no despacho",
    ["tool"],
)

AGENT_TOOLS_JSON_REPAIR_LLM_CALLS_TOTAL = Counter(
    "central_orchestrator_agent_tools_json_repair_llm_calls_total",
    "Chamadas extra ao LLM apos falha de parse JSON (Fase L)",
)

AGENT_TOOLS_JSON_SCHEMA_REPAIR_LLM_CALLS_TOTAL = Counter(
    "central_orchestrator_agent_tools_json_schema_repair_llm_calls_total",
    "Chamadas extra ao LLM apos falha de validate_tool_arguments (L1-4)",
)

CAPABILITY_DIGEST_INJECTIONS_TOTAL = Counter(
    "central_orchestrator_capability_digest_injections_total",
    "Vezes que o digest de capacidades foi injectado no prefixo system do assistente",
    ["endpoint"],
)

CAPABILITY_DIGEST_PROMPT_CHARS = Histogram(
    "central_orchestrator_capability_digest_prompt_chars",
    "Comprimento em caracteres (UTF-8 len do content) do digest injectado",
    buckets=(0.0, 256.0, 512.0, 1024.0, 1536.0, 2048.0, 2600.0, 4000.0, 12000.0),
)

TOOL_DENIED_DIGEST_CONTEXT_TOTAL = Counter(
    "central_orchestrator_tool_denied_digest_context_total",
    "tool_denied com etiqueta digest_in_prompt (correlacao L0-2 vs invalid_arguments)",
    ["reason", "digest_in_prompt"],
)

AGENT_TOOLS_RAG_SELECT_SECONDS = Histogram(
    "central_orchestrator_agent_tools_rag_select_seconds",
    "Tempo para escolher subset de tools (embed + pgvector)",
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)

AGENT_TOOLS_RAG_PROMPT_TOOL_COUNT = Histogram(
    "central_orchestrator_agent_tools_rag_prompt_tool_count",
    "Numero de tools no bloco PROTOCOLO_AGENT_TOOLS apos RAG",
    buckets=(0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 24.0, 32.0, 48.0),
)

AGENT_TOOLS_RAG_DEGRADED_TOTAL = Counter(
    "central_orchestrator_agent_tools_rag_degraded_total",
    "RAG degradado para catalogo completo",
    ["reason"],
)

def record_capability_digest_injected(endpoint: str, char_len: int) -> None:
    ep = (endpoint or "unknown")[:64]
    CAPABILITY_DIGEST_INJECTIONS_TOTAL.labels(endpoint=ep).inc()
    if char_len > 0:
        CAPABILITY_DIGEST_PROMPT_CHARS.observe(float(char_len))

def record_json_repair_llm_calls(n: int) -> None:
    if n > 0:
        AGENT_TOOLS_JSON_REPAIR_LLM_CALLS_TOTAL.inc(n)

def record_json_schema_repair_llm_calls(n: int) -> None:
    if n > 0:
        AGENT_TOOLS_JSON_SCHEMA_REPAIR_LLM_CALLS_TOTAL.inc(n)

def record_agent_tools_rag_select(
    *,
    seconds: float,
    n_tools: int,
    degraded_reason: str | None,
) -> None:
    if seconds >= 0.0:
        AGENT_TOOLS_RAG_SELECT_SECONDS.observe(seconds)
    if n_tools >= 0:
        AGENT_TOOLS_RAG_PROMPT_TOOL_COUNT.observe(float(n_tools))
    if degraded_reason:
        AGENT_TOOLS_RAG_DEGRADED_TOTAL.labels(reason=(degraded_reason or "unknown")[:48]).inc()

def record_agent_tool_audit_event(ev: dict[str, Any]) -> None:
    """
    Espelha eventos de audit do tool_loop em métricas (idempotente por evento).
    Chamado pelo servidor junto a write_orchestrator_audit.
    """
    event = ev.get("event")
    if event == "tool_denied":
        reason = ev.get("reason", "")
        if reason == "unknown_or_disallowed_tool":
            TOOL_DENIED_TOTAL.labels(reason="unknown_tool").inc()
            mapped = "unknown_tool"
        elif reason == "invalid_arguments":
            TOOL_DENIED_TOTAL.labels(reason="invalid_arguments").inc()
            mapped = "invalid_arguments"
        else:
            TOOL_DENIED_TOTAL.labels(reason="other").inc()
            mapped = "other"
        dflag = "true" if bool(ev.get("capability_digest_in_prompt")) else "false"
        TOOL_DENIED_DIGEST_CONTEXT_TOTAL.labels(reason=mapped, digest_in_prompt=dflag).inc()
    elif event == "tool_invoked":
        tool = str(ev.get("tool") or "unknown")[:128]
        TOOL_INVOKED_TOTAL.labels(tool=tool).inc()
    elif event == "tool_result_ok":
        tool = str(ev.get("tool") or "unknown")[:128]
        TOOL_EXECUTION_OK_TOTAL.labels(tool=tool).inc()

LLM_USAGE_REPORTS_TOTAL = Counter(
    "central_orchestrator_llm_usage_reports_total",
    "Respostas LLM com campo usage preenchido (model-router)",
    ["profile"],
)

LLM_PROMPT_TOKENS_OBSERVED = Histogram(
    "central_orchestrator_llm_prompt_tokens",
    "Tokens de prompt quando o backend reporta usage",
    ["profile"],
    buckets=(0.0, 64.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0, 8192.0, 16384.0, 32768.0, 65536.0),
)

LLM_COMPLETION_TOKENS_OBSERVED = Histogram(
    "central_orchestrator_llm_completion_tokens",
    "Tokens de conclusão quando o backend reporta usage",
    ["profile"],
    buckets=(0.0, 32.0, 128.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0, 8192.0, 16384.0),
)

def record_llm_usage_from_payload(profile: str, payload: dict[str, Any] | None) -> None:
    """Extrai usage típico OpenAI de uma resposta JSON já parseada (ex. POST model-router/infer)."""
    if not payload or not isinstance(payload, dict):
        return
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return
    prof = (profile or "unknown").strip()[:64] or "unknown"
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    if pt is None and ct is None:
        return
    LLM_USAGE_REPORTS_TOTAL.labels(profile=prof).inc()
    if isinstance(pt, (int, float)) and pt >= 0:
        LLM_PROMPT_TOKENS_OBSERVED.labels(profile=prof).observe(float(pt))
    if isinstance(ct, (int, float)) and ct >= 0:
        LLM_COMPLETION_TOKENS_OBSERVED.labels(profile=prof).observe(float(ct))


# ═══ AGENT_TOOLS_EMBEDDING ═══

"""F4 — embeddings para RAG do catálogo de agent tools (delegates to EmbeddingService)."""

AGENT_TOOLS_VECTOR_DIM = 384  # from context.TOOLS_VECTOR_DIM

def active_agent_tools_embedding_model_id() -> str:
    from app.config import AGENT_TOOLS_RAG_EMBEDDING_BACKEND

    if AGENT_TOOLS_RAG_EMBEDDING_BACKEND == "hash":
        from app.context import HASH_MODEL_ID_TOOLS
        return HASH_MODEL_ID_TOOLS
    from app.context import MINILM_MODEL_ID
    return MINILM_MODEL_ID

def embed_agent_tools_text(text: str) -> tuple[list[float], str]:
    """
    Retorna (vetor 384d, embedding_model_id) para gravar ou comparar em agent_tools_embeddings.
    """
    from app.context import get_embedding_service
    return get_embedding_service().embed_tools(text or "")


# ═══ AGENT_TOOLS_PHASE_L ═══

"""
Fase L — fiabilidade do assistente local: few-shots curtos + prompt de reparacao de JSON.

Textos em PT para alinhar com modelos locais; identificadores JSON alinhados ao tool_registry.
"""

_JSON_REPAIR_BAD_SNIPPET_MAX = 3500

_SCHEMA_REPAIR_ENVELOPE_MAX = 2800

def _pick_first_available(preferred: list[str]) -> str:
    """
    Pick a tool name that exists in the *filtered* registry (PRIMARY_AGENT_TOOLS_PATH may shrink the set).
    Falls back to the first registered tool name.
    """
    names = list_registered_tool_names_for_llm_prompt()
    if not names:
        # Defense in depth: registry should never be empty in runtime.
        return TOOL_NAME_REQUEST_SHELL
    for p in preferred:
        if p in names:
            return p
    return names[0]

def _family_few_shot_messages() -> list[dict[str, str]]:
    """L1-3: exemplos por familia (read-only / fila HITL / recusa de tool inexistente)."""
    ro_tool = _pick_first_available(
        [TOOL_NAME_LIST_PROCESSES, TOOL_NAME_GET_HOST_SUMMARY, TOOL_NAME_REQUEST_SHELL]
    )
    hit_tool = _pick_first_available([TOOL_NAME_REQUEST_SHELL, TOOL_NAME_CREATE_APPROVAL_REQUEST])
    if hit_tool == TOOL_NAME_REQUEST_SHELL:
        hit_args: dict[str, Any] = {
            "mode": "argv",
            "argv": ["true"],
            "intent": "exemplo few-shot HITL",
        }
    else:
        hit_args = {"action_id": "process.signal", "payload": {"pid": 1234}}
    hit_json = json.dumps(
        {"final": None, "tool_calls": [{"name": hit_tool, "arguments": hit_args}]},
        ensure_ascii=False,
    )
    ro_args: dict[str, Any] = {"limit": 10} if ro_tool == TOOL_NAME_LIST_PROCESSES else {}
    ro_json = json.dumps({"final": None, "tool_calls": [{"name": ro_tool, "arguments": ro_args}]}, ensure_ascii=False)
    return [
        {
            "role": "user",
            "content": (
                "Lista uns processos. Responde so com JSON (final + tool_calls), sem markdown."
            ),
        },
        {"role": "assistant", "content": ro_json},
        {
            "role": "user",
            "content": (
                "Preciso de um comando shell que exija aprovacao humana. "
                "So JSON valido com request_shell (ou a tool HITL do catalogo)."
            ),
        },
        {"role": "assistant", "content": hit_json},
        {
            "role": "user",
            "content": (
                "Executa a tool run_shell_command com curl. Responde so com JSON; "
                "nao inventes ferramentas fora do catalogo."
            ),
        },
        {
            "role": "assistant",
            "content": (
                '{"final": "Nao existe run_shell_command no catalogo. So posso usar nomes do bloco '
                '[PROTOCOLO_AGENT_TOOLS] desta sessao.", "tool_calls": []}'
            ),
        },
    ]

def build_few_shot_messages(*, enabled: bool) -> list[dict[str, str]]:
    """
    Exemplos canonicos user/assistant (so JSON valido) inseridos apos o protocolo [PROTOCOLO_AGENT_TOOLS].
    Com AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED, acrescenta turnos por familia (L1-3).
    """
    if not enabled:
        return []
    ex_tool = _pick_first_available(
        [TOOL_NAME_GET_HOST_SUMMARY, TOOL_NAME_LIST_PROCESSES, TOOL_NAME_REQUEST_SHELL]
    )
    base: list[dict[str, str]] = [
        {
            "role": "user",
            "content": (
                "Qual a carga media do sistema? Responde apenas com o JSON acordado "
                "(final + tool_calls), sem markdown."
            ),
        },
        {
            "role": "assistant",
            "content": (
                '{"final": null, "tool_calls": [{"name": "%s", "arguments": %s}]}'
                % (ex_tool, '{"limit": 10}' if ex_tool == TOOL_NAME_LIST_PROCESSES else "{}")
            ),
        },
        {
            "role": "user",
            "content": "Ola. Responde apenas com o JSON acordado (podes usar final com texto em portugues).",
        },
        {
            "role": "assistant",
            "content": (
                '{"final": "Ola! Posso ajudar com informacoes sobre o teu sistema ou com ferramentas '
                'do catalogo [PROTOCOLO_AGENT_TOOLS] se precisares.", "tool_calls": []}'
            ),
        },
    ]
    if AGENT_TOOLS_FEW_SHOT_FAMILIES_ENABLED:
        base.extend(_family_few_shot_messages())
    return base

def build_json_repair_user_prompt(bad_raw: str) -> str:
    """
    Segunda chamada ao LLM: pede apenas um objecto JSON corrigido, sem texto extra.
    """
    snippet = (bad_raw or "").strip()
    if len(snippet) > _JSON_REPAIR_BAD_SNIPPET_MAX:
        snippet = snippet[: _JSON_REPAIR_BAD_SNIPPET_MAX] + "\n…(truncado)"
    return (
        "A tua resposta anterior nao foi um unico objecto JSON valido com as chaves exatas "
        '`"final"` (string ou null) e `"tool_calls"` (lista, possivelmente vazia).\n'
        "Responde APENAS com um objecto JSON — sem markdown, sem crases, sem texto antes ou depois.\n"
        "Cada elemento de tool_calls deve ser {\"name\": \"...\", \"arguments\": { ... }}.\n"
        "Reutiliza a intencao da resposta errada abaixo.\n\n"
        f"<BAD>\n{snippet}\n</BAD>"
    )

def build_json_schema_repair_user_prompt(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    schema_error: str,
    prior_envelope_raw: str,
) -> str:
    """
    L1-4: o JSON tinha formato valido (final + tool_calls) mas os argumentos falharam jsonschema.
    """
    try:
        args_s = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        args_s = str(arguments)
    env = (prior_envelope_raw or "").strip()
    if len(env) > _SCHEMA_REPAIR_ENVELOPE_MAX:
        env = env[: _SCHEMA_REPAIR_ENVELOPE_MAX] + "\n…(truncado)"
    return (
        "O teu ultimo output era JSON parseavel com chaves final e tool_calls, mas os argumentos da "
        f'primeira tool `{tool_name}` violam o schema registado no servidor.\n'
        f"Erro de validacao (servidor): {schema_error}\n"
        f"Argumentos recebidos (JSON): {args_s}\n\n"
        "Responde APENAS com um unico objecto JSON com a mesma estrutura (final + tool_calls). "
        f"Corrige os argumentos de `{tool_name}` para cumprirem o schema, ou usa final com texto ao "
        "utilizador e tool_calls vazia se nao conseguires cumprir o schema sem inventar campos.\n"
        "Sem markdown, sem crases, sem texto fora do JSON.\n\n"
        f"<ENVELOPE_ANTERIOR>\n{env}\n</ENVELOPE_ANTERIOR>"
    )




# ═══ MODALITY_AGENT_TOOLS ═══

"""ADR-016 phase 6 — agent tools for web research, social copy, and image generation."""

TOOL_NAME_WEB_RESEARCH = "web_research"

TOOL_NAME_DRAFT_SOCIAL_POST = "draft_social_post"

TOOL_NAME_GENERATE_POST_IMAGE = "generate_post_image"

_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")

_TIER_TO_ROLE: dict[str, str] = {
    "fast": ROLE_WEB_RESEARCH_FAST,
    "default": ROLE_WEB_RESEARCH_DEFAULT,
    "deep": ROLE_WEB_RESEARCH_DEEP,
}

_SCHEMA_WEB_RESEARCH: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 4000},
        "tier": {"type": "string", "enum": ["fast", "default", "deep"]},
    },
    "required": ["query"],
}

_SCHEMA_DRAFT_SOCIAL_POST: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "platform": {
            "type": "string",
            "enum": ["x", "instagram", "facebook", "linkedin", "generic"],
        },
        "topic": {"type": "string", "minLength": 1, "maxLength": 4000},
        "tone": {"type": "string", "minLength": 1, "maxLength": 256},
        "max_chars": {"type": "integer", "minimum": 40, "maximum": 5000},
    },
    "required": ["platform", "topic"],
}

_SCHEMA_GENERATE_POST_IMAGE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
        "aspect": {"type": "string", "enum": ["1:1", "4:5", "16:9", "9:16"]},
    },
    "required": ["prompt"],
}

MODALITY_TOOL_SPECS: dict[str, dict[str, Any]] = {
    TOOL_NAME_WEB_RESEARCH: {
        "plan_kind": "tool.web_research",
        "plan_description_pt": (
            "Opcional (ADR-016): pesquisa web com modelo Sonar (servidor); resultado em markdown "
            "com fontes para o cérebro redigir a resposta final. Não expõe Sonar no picker UI."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_WEB_RESEARCH,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.modality.web_research",
        "protocol_hint_en": (
            f'{TOOL_NAME_WEB_RESEARCH}: {{"query":"<text>","tier":"fast"|"default"|"deep"}} '
            "(modality gate; result is markdown + sources for the brain)."
        ),
    },
    TOOL_NAME_DRAFT_SOCIAL_POST: {
        "plan_kind": "tool.draft_social_post",
        "plan_description_pt": (
            "Opcional (ADR-016): rascunho de post para rede social (tom, hashtags, limite de caracteres); "
            "usa papel social_copy no servidor."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_DRAFT_SOCIAL_POST,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.modality.social_copy",
        "protocol_hint_en": (
            f'{TOOL_NAME_DRAFT_SOCIAL_POST}: '
            '{{"platform":"x"|"instagram"|"facebook"|"linkedin"|"generic",'
            '"topic":"<text>","tone":"<optional>","max_chars":<optional>}}.'
        ),
    },
    TOOL_NAME_GENERATE_POST_IMAGE: {
        "plan_kind": "tool.generate_post_image",
        "plan_description_pt": (
            "Opcional (ADR-016): prepara geração de imagem para post (modelo image_generate); "
            "HITL por defeito antes de publicar."
        ),
        "plan_target": "orchestrator",
        "arguments_schema": _SCHEMA_GENERATE_POST_IMAGE,
        "risk_level": "P2",
        "maps_to_action_id": "orchestrator.modality.image_generate",
        "protocol_hint_en": (
            f'{TOOL_NAME_GENERATE_POST_IMAGE}: '
            '{{"prompt":"<visual description>","aspect":"1:1"|"4:5"|"16:9"|"9:16"}} '
            "(HITL may apply; not a UI picker model)."
        ),
    },
}

def modality_tool_specs_for_registry(path: str) -> dict[str, dict[str, Any]]:
    """Filter modality tools via ``modality_agent_tools.json`` when path is set."""
    return filter_tool_specs(MODALITY_TOOL_SPECS, path=path)

def _extract_sources(markdown: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in _URL_RE.findall(markdown or ""):
        u = url.rstrip(".,;")
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= 50:
            break
    return out

def _web_research_role(tier: str) -> str:
    key = (tier or "default").strip().lower()
    return _TIER_TO_ROLE.get(key, ROLE_WEB_RESEARCH_DEFAULT)

def run_web_research(request_id: str, *, query: str, tier: str = "default") -> dict[str, Any]:
    role = _web_research_role(tier)
    profile, model_id = resolve_modality_call_params(role)
    prompt = (
        f"Pesquisa na web sobre o seguinte tema (informação actualizada):\n{query}\n\n"
        "Responde em markdown com secções ## Resumo e ## Fontes (URLs quando disponíveis)."
    )
    out: dict[str, Any] = {
        "request_id": request_id,
        "ok": False,
        "query": query,
        "tier": tier if tier in _TIER_TO_ROLE else "default",
        "modality_role": role,
        "model_id": model_id,
        "markdown": "",
        "sources": [],
    }
    try:
        markdown = call_llm(prompt, [], profile=profile, model_override=model_id, allowlist_mode="modality")
        out["ok"] = True
        out["markdown"] = markdown
        out["sources"] = _extract_sources(markdown)
    except Exception as exc:
        out["error"] = str(exc)[:500]
    return out

def run_draft_social_post(
    request_id: str,
    *,
    platform: str,
    topic: str,
    tone: str | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    profile, model_id = resolve_modality_call_params(ROLE_SOCIAL_COPY)
    lines = [
        f"Plataforma: {platform}",
        f"Tema: {topic}",
        "Escreve um rascunho de post em português (Brasil), pronto para revisão humana.",
        "Inclui hashtags relevantes quando fizer sentido.",
    ]
    if tone:
        lines.append(f"Tom: {tone}")
    if max_chars is not None:
        lines.append(f"Limite máximo de caracteres: {max_chars}")
    prompt = "\n".join(lines)
    out: dict[str, Any] = {
        "request_id": request_id,
        "ok": False,
        "platform": platform,
        "topic": topic,
        "modality_role": ROLE_SOCIAL_COPY,
        "model_id": model_id,
        "draft": "",
    }
    if tone:
        out["tone"] = tone
    if max_chars is not None:
        out["max_chars"] = max_chars
    try:
        out["draft"] = call_llm(prompt, [], profile=profile, model_override=model_id, allowlist_mode="modality")
        out["ok"] = True
    except Exception as exc:
        out["error"] = str(exc)[:500]
    return out

def run_generate_post_image(
    request_id: str,
    *,
    prompt: str,
    aspect: str | None = None,
) -> dict[str, Any]:
    from app import config as cfg

    profile, model_id = resolve_modality_call_params(ROLE_IMAGE_GENERATE)
    ratio = aspect or "1:1"
    out: dict[str, Any] = {
        "request_id": request_id,
        "ok": True,
        "prompt": prompt,
        "aspect": ratio,
        "modality_role": ROLE_IMAGE_GENERATE,
        "model_id": model_id,
    }
    if cfg.CENTRAL_IMAGE_GENERATE_HITL:
        out["status"] = "hitl_pending"
        out["message_pt"] = (
            "Geração de imagem pendente de revisão humana antes de publicar (política ADR-016)."
        )
        return out

    img_prompt = (
        "Gera uma imagem para publicação em rede social.\n"
        f"Descrição visual: {prompt}\n"
        f"Proporção: {ratio}\n"
        "Descreve o resultado visual em markdown (sem inventar URLs de ficheiros)."
    )
    try:
        out["description_md"] = call_llm(
            img_prompt,
            [],
            profile=profile,
            model_override=model_id,
            allowlist_mode="modality",
        )
        out["status"] = "completed"
    except Exception as exc:
        out["ok"] = False
        out["status"] = "error"
        out["error"] = str(exc)[:500]
    return out


# ═══ POST_TOOL_BRIDGE ═══

"""
F3/A5 — ponte ``user`` após cada TOOL_RESULT, por família de ferramenta.

O texto substitui o ``user`` na volta seguinte ao LLM (``run_agent_tool_flow`` e ``iter_agent_tool_stream``).
"""

_READ_HOST_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_NAME_GET_HOST_SUMMARY,
        TOOL_NAME_GET_JOURNAL_TAIL,
        TOOL_NAME_LIST_PROCESSES,
        TOOL_NAME_LIST_PROCESS_TREE,
        TOOL_NAME_LIST_LISTENING_SOCKETS,
        TOOL_NAME_GET_FILE_METADATA,
        TOOL_NAME_GET_HARDWARE_SENSORS,
        TOOL_NAME_LIST_DISK_USAGE,
        TOOL_NAME_LIST_DISK_PARTITIONS,
        TOOL_NAME_GREP_WORKSPACE,
        TOOL_NAME_LIST_NETWORK_INTERFACES,
        TOOL_NAME_GET_NETWORK_ROUTES,
        TOOL_NAME_GET_CENTRAL_STACK_HEALTH,
        TOOL_NAME_LIST_NETWORK_CONNECTIONS,
        TOOL_NAME_LIST_SYSTEMD_UNITS,
        TOOL_NAME_QUERY_INSTALLED_PACKAGES,
        TOOL_NAME_READ_FILE_TEXT,
    }
)

_CANVAS_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_NAME_MANAGE_WORKSPACE_ARTIFACT,
        TOOL_NAME_APPLY_CANVAS_PATCH,
    }
)

_GENERIC_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_NAME_CREATE_APPROVAL_REQUEST,
        TOOL_NAME_OPEN_BROWSER_URL,
        TOOL_NAME_PROBE_NETWORK_ENDPOINT,
        TOOL_NAME_SEND_DESKTOP_NOTIFICATION,
        TOOL_NAME_DISABLE_SYSTEMD_USER_UNIT,
        TOOL_NAME_INSTALL_OS_PACKAGE,
        TOOL_NAME_UPGRADE_OS_PACKAGES_ALL,
        TOOL_NAME_MUTATE_EXTERNAL_FILE,
        TOOL_NAME_WRITE_CONFIG_FILE,
    }
)

_BRIDGE_READ_HOST_PT = (
    "Responde ao utilizador em portugues de forma clara. Usa apenas numeros e factos "
    "presentes em TOOL_RESULT para afirmacoes sobre CPU, memoria, disco, carga, SO, "
    "processos (PID/nome) ou portas em escuta. Se a lista estiver truncada, indica isso. "
    "Se houver erro no system_agent ou kernel_observer, explica que a leitura falhou."
)

_BRIDGE_CANVAS_PT = (
    "Responde ao utilizador em portugues de forma clara. O TOOL_RESULT contem o JSON do "
    "canvas ou artefacto de workspace (ex.: ok, artifact_id, title, revision, content, error, message). "
    "Para o texto do ficheiro ou alteracoes, baseia-te apenas nesses campos. "
    "Se ok for false ou houver erro, explica sem inventar detalhes que nao estejam no JSON."
)

_BRIDGE_SHELL_PT = (
    "Responde ao utilizador em portugues de forma clara. O TOOL_RESULT contem o resultado do "
    "comando shell (stdout, stderr, codigo de saida, ok) ou erro do gateway. "
    "Resume usando apenas esses campos; nao inventes saida ou comandos nao mostrados. "
    "Se a saida parecer truncada no JSON, indica isso."
)

_BRIDGE_GENERIC_PT = (
    "Responde ao utilizador em portugues de forma clara. Usa apenas informacao explicita no "
    "TOOL_RESULT (JSON): ok/error, ids (ex.: approval_id), mensagens e payloads devolvidos. "
    "Nao inventes confirmacoes de accoes externas que o JSON nao mostre. "
    "Se houver erro, explica em linguagem simples."
)

_MODALITY_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_NAME_WEB_RESEARCH,
        TOOL_NAME_DRAFT_SOCIAL_POST,
        TOOL_NAME_GENERATE_POST_IMAGE,
    }
)

_BRIDGE_MODALITY_PT = (
    "Responde ao utilizador em portugues de forma clara. O TOOL_RESULT veio de uma capacidade "
    "de modalidade (pesquisa web, copy social ou imagem). Usa apenas campos como markdown, "
    "sources, draft, description_md, message_pt e model_id presentes no JSON. "
    "O modelo de pesquisa/copy/imagem nao e o cérebro — sintetiza para o utilizador sem "
    "inventar URLs ou factos que nao estejam no resultado. Se ok for false ou status hitl_pending, "
    "explica em linguagem simples."
)

def post_tool_user_prompt(tool_name: str) -> str:
    """Texto da mensagem ``user`` na volta seguinte ao modelo, após ``TOOL_RESULT``."""
    n = (tool_name or "").strip()
    if n in _CANVAS_TOOLS:
        return _BRIDGE_CANVAS_PT
    if n == TOOL_NAME_REQUEST_SHELL:
        return _BRIDGE_SHELL_PT
    if n in _READ_HOST_TOOLS:
        return _BRIDGE_READ_HOST_PT
    if n in _MODALITY_TOOLS:
        return _BRIDGE_MODALITY_PT
    if n in _GENERIC_TOOLS:
        return _BRIDGE_GENERIC_PT
    return _BRIDGE_GENERIC_PT


# ═══ TOOL_LOOP ═══

"""
Tool-use no orquestrador: JSON no output do LLM + registry (Fase G) + despacho tipado.
Sem shell livre; deny-by-default para nomes fora do catálogo.
"""

TOOL_NAME_P0 = TOOL_NAME_GET_HOST_SUMMARY

AGENT_TOOLS_PROTOCOL_PT = build_agent_tools_protocol_text()

def build_agent_tools_protocol_message(
    *, user_text: str | None = None
) -> tuple[dict[str, str], dict[str, Any]]:
    """Mensagem system do protocolo; com F4 opcional reduz o catálogo via RAG."""
    from app.rag import resolve_registered_tool_names_for_prompt

    names, rag_info = resolve_registered_tool_names_for_prompt(user_text=user_text)
    return (
        {"role": "system", "content": build_agent_tools_protocol_text(names).strip()},
        rag_info,
    )

def _tool_running_arguments_for_sse(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Subconjunto curto para SSE tool_running (pré-visualização na UI)."""
    if tool == "request_shell":
        out: dict[str, Any] = {}
        for k in ("sh_c", "cwd", "argv", "shell_session_id", "timeout_sec"):
            if k not in args:
                continue
            v = args[k]
            if k == "sh_c" and isinstance(v, str):
                out[k] = v[:320]
            elif k == "argv" and isinstance(v, list):
                out[k] = v[:48]
            else:
                out[k] = v
        return out
    if tool == "grep_workspace":
        return {k: args[k] for k in ("path", "pattern", "max_matches") if k in args}
    if tool == "manage_workspace_artifact":
        out_ma: dict[str, Any] = {}
        if "action" in args:
            out_ma["action"] = args["action"]
        if "artifact_type" in args:
            out_ma["artifact_type"] = args["artifact_type"]
        if "artifact_id" in args:
            out_ma["artifact_id"] = str(args["artifact_id"])[:48]
        tit = args.get("title")
        if isinstance(tit, str) and tit.strip():
            out_ma["title"] = tit.strip()[:80] + ("…" if len(tit.strip()) > 80 else "")
        c = args.get("content")
        if isinstance(c, str):
            out_ma["content_length"] = len(c)
        return out_ma
    if tool == "apply_canvas_patch":
        sb = args.get("search_block")
        rb = args.get("replace_block")
        out_p: dict[str, Any] = {}
        if "artifact_id" in args:
            out_p["artifact_id"] = str(args["artifact_id"])[:48]
        if isinstance(sb, str):
            out_p["search_preview"] = sb[:120] + ("…" if len(sb) > 120 else "")
        if isinstance(rb, str):
            out_p["replace_length"] = len(rb)
        return out_p
    return {}

def _sse_tool_ok_from_result(result: object) -> bool:
    """True se o resultado não nega explícito (dict com ok: false)."""
    if isinstance(result, dict) and "ok" in result:
        return bool(result["ok"])
    return True

def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()

def extract_json_object(text: str) -> dict[str, Any] | None:
    text = text_for_agent_tool_json_parse(text)
    t = _strip_code_fence(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    end = t.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None

def parse_agent_tool_response(text: str) -> tuple[str | None, list[dict[str, Any]], bool]:
    """
    Returns (final_text_or_none, tool_calls, json_ok).
    Se json_ok False, o chamador deve usar o texto cru como resposta (sem executar tools).
    """
    d = extract_json_object(text)
    if d is None or not isinstance(d, dict):
        return None, [], False
    final = d.get("final")
    if final is None:
        f_out: str | None = None
    elif isinstance(final, str):
        f_out = final.strip() or None
    else:
        f_out = str(final).strip() or None
    raw_calls = d.get("tool_calls")
    if raw_calls is None:
        calls: list[dict[str, Any]] = []
    elif isinstance(raw_calls, list):
        calls = [x for x in raw_calls if isinstance(x, dict)]
    else:
        calls = []
    return f_out, calls, True

def _agent_tools_json_response_format() -> dict[str, str] | None:
    """json_object mode — OpenRouter suporta nativamente (já não requer model-router)."""
    if not AGENT_TOOLS_JSON_MODE_ENABLED:
        return None
    return {"type": "json_object"}

def _call_llm_with_json_repair(
    *,
    user_text: str,
    hist: list[dict[str, str]],
    tail: list[dict[str, str]],
    profile: str,
    meta: dict[str, Any],
    response_format: dict[str, str] | None = None,
    model_override: str | None = None,
) -> str:
    """
    Primeira chamada + ate N chamadas extra com prompt de reparacao se o JSON nao for objecto valido.
    """
    raw = call_llm(
        user_text,
        hist + tail,
        profile=profile,
        response_format=response_format,
        model_override=model_override,
    ).strip()
    extra_max = max(0, AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS)
    repairs_done = 0
    while True:
        _, _, ok = parse_agent_tool_response(raw)
        if ok or repairs_done >= extra_max:
            break
        repairs_done += 1
        raw = call_llm(
            build_json_repair_user_prompt(raw),
            hist + tail,
            profile=profile,
            response_format=response_format,
            model_override=model_override,
        ).strip()
    prev_repairs = int(meta.get("json_repair_extra_calls") or 0)
    meta["json_repair_extra_calls"] = prev_repairs + repairs_done
    if repairs_done:
        try:

            record_json_repair_llm_calls(repairs_done)
        except Exception:
            pass
    return raw

def _repair_agent_json_if_needed(
    raw: str,
    *,
    hist: list[dict[str, str]],
    tail: list[dict[str, str]],
    profile: str,
    meta: dict[str, Any],
    response_format: dict[str, str] | None,
    model_override: str | None = None,
) -> str:
    """Reparacao JSON sync (apos stream); nao re-invoca o prompt original."""
    extra_max = max(0, AGENT_TOOLS_JSON_REPAIR_MAX_EXTRA_CALLS)
    repairs_done = 0
    cur = raw
    while True:
        _, _, ok = parse_agent_tool_response(cur)
        if ok or repairs_done >= extra_max:
            break
        repairs_done += 1
        cur = call_llm(
            build_json_repair_user_prompt(cur),
            hist + tail,
            profile=profile,
            response_format=response_format,
            model_override=model_override,
        ).strip()
    prev_repairs = int(meta.get("json_repair_extra_calls") or 0)
    meta["json_repair_extra_calls"] = prev_repairs + repairs_done
    if repairs_done:
        try:

            record_json_repair_llm_calls(repairs_done)
        except Exception:
            pass
    return cur

def iter_thinking_events_collect_raw(
    *,
    user_text: str,
    messages: list[dict[str, str]],
    profile: str,
    response_format: dict[str, str] | None,
    raw_holder: list[str],
    model_override: str | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """
    Stream NDJSON do LLM; emite (thinking|thinking_done, payload). Não emite tokens públicos
    (evita vazar JSON de tools no SSE). No fim, define raw_holder[0] = texto acumulado completo.
    """
    acc: list[str] = []
    splitter = RedactedThinkingStreamSplitter()
    for line in iter_assistant_llm_ndjson(
        user_text,
        messages,
        profile=profile,
        response_format=response_format,
        model_override=model_override,
    ):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("e")
        if et == "token":
            d = str(ev.get("d", ""))
            acc.append(d)
            for kind, payload in splitter.feed(d):
                if kind == "thinking":
                    yield ("thinking", dict(payload))
                elif kind == "thinking_done":
                    yield ("thinking_done", {})
        elif et == "error":
            raise RuntimeError(str(ev.get("message", "llm_stream_error")))
        elif et == "done":
            break
    for kind, payload in splitter.flush():
        if kind == "thinking":
            yield ("thinking", dict(payload))
        elif kind == "thinking_done":
            yield ("thinking_done", {})
    raw_holder.clear()
    raw_holder.append("".join(acc))

def _attempt_schema_repairs(
    *,
    final: str | None,
    name: str,
    args: dict[str, Any],
    raw: str,
    hist: list[dict[str, str]],
    tail: list[dict[str, str]],
    profile: str,
    meta: dict[str, Any],
    response_format: dict[str, str] | None,
    model_override: str | None = None,
) -> tuple[str | None, str, dict[str, Any], str, bool, str | None]:
    """
    L1-4: tenta corrigir argumentos da primeira tool quando validate_tool_arguments falha.
    Devolve (final, name, args, raw, json_ok, validation_error); validation_error None = valido.
    """
    cur_raw = raw
    cur_final = final
    cur_name = name
    cur_args = args
    v_err: str | None = validate_tool_arguments(cur_name, cur_args)
    json_ok = True
    repairs = 0
    max_r = max(0, AGENT_TOOLS_JSON_SCHEMA_REPAIR_MAX_EXTRA_CALLS)
    while v_err and repairs < max_r:
        repairs += 1
        repair_text = build_json_schema_repair_user_prompt(
            tool_name=cur_name,
            arguments=cur_args,
            schema_error=v_err,
            prior_envelope_raw=cur_raw,
        )
        cur_raw = _call_llm_with_json_repair(
            user_text=repair_text,
            hist=hist,
            tail=tail,
            profile=profile,
            meta=meta,
            response_format=response_format,
            model_override=model_override,
        )
        cur_final, tool_calls, json_ok = parse_agent_tool_response(cur_raw)
        if not json_ok:
            v_err = "json_unparseable_after_schema_repair"
            break
        if not tool_calls:
            v_err = "schema_repair_missing_tool_calls"
            continue
        tc = tool_calls[0]
        cur_name = str(tc.get("name", "")).strip()
        cur_args = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
        if not is_registered_tool(cur_name):
            v_err = "schema_repair_unknown_tool_name"
            continue
        v_err = validate_tool_arguments(cur_name, cur_args)

    prev = int(meta.get("json_schema_repair_extra_calls") or 0)
    meta["json_schema_repair_extra_calls"] = prev + repairs
    if repairs:
        try:

            record_json_schema_repair_llm_calls(repairs)
        except Exception:
            pass
    return cur_final, cur_name, cur_args, cur_raw, json_ok, v_err

def run_agent_tool_flow(
    *,
    user_text: str,
    base_history: list[dict[str, str]],
    request_id: str,
    profile: str,
    max_tool_executions: int,
    audit: Callable[[dict[str, Any]], None] | None,
    model_override: str | None = None,
    workspace_store_key: str | None = None,
    canvas_write_ctx: dict[str, Any] | None = None,
    modality_invocations_out: list[dict[str, str]] | None = None,
    chat_session_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Executa ate max_tool_executions tools permitidas, depois uma passagem final do LLM.
    Retorna (reply_text, meta).

    ``workspace_store_key``: chave do canvas in-process (F1); omissão = ``request_id``.
    ``canvas_write_ctx``: Fase 10 / G6 — passado a ``dispatch_tool`` para canvas.
    """
    ws_key = workspace_store_key if workspace_store_key is not None else request_id
    protocol, rag_info = build_agent_tools_protocol_message(user_text=user_text)
    few = build_few_shot_messages(enabled=AGENT_TOOLS_FEW_SHOT_ENABLED)
    hist = [*base_history, protocol, *few]
    rf = _agent_tools_json_response_format()
    meta: dict[str, Any] = {
        "agent_tools": True,
        "tools_run": 0,
        "json_parse_ok": True,
        "denied_tool": None,
        "json_repair_extra_calls": 0,
        "json_schema_repair_extra_calls": 0,
        "agent_tools_rag": rag_info,
    }
    current_user = user_text
    tail: list[dict[str, str]] = []
    reply_prefix: list[str] = []

    for _ in range(max_tool_executions + 1):
        raw = _call_llm_with_json_repair(
            user_text=current_user,
            hist=hist,
            tail=tail,
            profile=profile,
            meta=meta,
            response_format=rf,
            model_override=model_override,
        )
        final, tool_calls, json_ok = parse_agent_tool_response(raw)
        meta["json_parse_ok"] = json_ok

        if not json_ok:
            meta["mode"] = "plain_text_no_json"
            body = raw
            if reply_prefix:
                body = "".join(reply_prefix) + body
            return body, meta

        if tool_calls and meta["tools_run"] < max_tool_executions:
            tc = tool_calls[0]
            name = str(tc.get("name", "")).strip()
            args = tc.get("arguments")
            if not isinstance(args, dict):
                args = {}

            if not is_registered_tool(name):
                meta["denied_tool"] = name
                meta["mode"] = "tool_denied"
                if audit:
                    audit(
                        {
                            "event": "tool_denied",
                            "request_id": request_id,
                            "tool": name,
                            "reason": "unknown_or_disallowed_tool",
                        }
                    )
                if final:
                    return final, meta
                return (
                    "O nome de ferramenta pedido nao esta no catalogo desta sessao. Usa apenas os nomes "
                    "listados no bloco [PROTOCOLO_AGENT_TOOLS] desta conversa (correspondencia exacta).",
                    meta,
                )

            v_err = validate_tool_arguments(name, args)
            if v_err:
                final, name, args, raw, json_ok, v_err = _attempt_schema_repairs(
                    final=final,
                    name=name,
                    args=args,
                    raw=raw,
                    hist=hist,
                    tail=tail,
                    profile=profile,
                    meta=meta,
                    response_format=rf,
                    model_override=model_override,
                )
                meta["json_parse_ok"] = json_ok
                if not json_ok:
                    meta["mode"] = "plain_text_no_json"
                    body = raw
                    if reply_prefix:
                        body = "".join(reply_prefix) + body
                    return body, meta

            if v_err:
                meta["denied_tool"] = name
                meta["mode"] = "tool_arguments_invalid"
                if audit:
                    audit(
                        {
                            "event": "tool_denied",
                            "request_id": request_id,
                            "tool": name,
                            "reason": "invalid_arguments",
                            "detail": v_err,
                        }
                    )
                if final:
                    return final, meta
                return (
                    "Os argumentos JSON desta ferramenta nao sao validos para o schema registado. "
                    "Reformula o pedido ou tenta sem tool_calls.",
                    meta,
                )

            if final:
                reply_prefix.append(final.rstrip() + "\n\n")

            if audit:
                audit({"event": "tool_invoked", "request_id": request_id, "tool": name, "arguments": args})

            from app.context import record_tool_invocation, record_tool_result_event

            record_tool_invocation(
                canvas_write_ctx=canvas_write_ctx,
                tool=name,
                arguments=args if isinstance(args, dict) else {},
            )
            from app.shared.approvals_store import resolve_tenant_id_for_store

            result = dispatch_tool(
                name,
                args,
                request_id,
                workspace_store_key=ws_key,
                canvas_write_ctx=canvas_write_ctx,
                tenant_id=resolve_tenant_id_for_store(),
            )
            record_tool_result_event(
                canvas_write_ctx=canvas_write_ctx,
                tool=name,
                result=result if isinstance(result, dict) else {"raw": result},
            )
            if modality_invocations_out is not None:
                from app.shared.modality_models import record_modality_invocation_from_tool_result

                record_modality_invocation_from_tool_result(
                    modality_invocations_out,
                    tool_name=name,
                    result=result,
                )
            meta["tools_run"] = meta["tools_run"] + 1
            try:
                result_str = json.dumps(result, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                result_str = str(result)
            result_str = result_str[:14_000]

            if audit:
                audit(
                    {
                        "event": (
                            "tool_result_ok"
                            if _sse_tool_ok_from_result(result)
                            else "tool_result_error"
                        ),
                        "request_id": request_id,
                        "tool": name,
                    }
                )

            tail.append({"role": "assistant", "content": assistant_message_for_history(raw)})
            tail.append(
                {
                    "role": "system",
                    "content": f"TOOL_RESULT {name} (JSON read-only):\n{result_str}",
                }
            )
            current_user = post_tool_user_prompt(name)
            continue

        if final:
            meta["mode"] = "final_direct"
            body = final
            if reply_prefix:
                body = "".join(reply_prefix) + body
            return body, meta

        meta["mode"] = "raw_fallback"
        body = raw
        if reply_prefix:
            body = "".join(reply_prefix) + body
        return body, meta

    meta["mode"] = "exhausted"
    body = "".join(reply_prefix) if reply_prefix else ""
    return body, meta

def _iter_text_as_token_events(text: str, *, chunk_chars: int = 48) -> Iterator[tuple[str, dict[str, Any]]]:
    """Emite eventos SSE `token` a partir de texto ja conhecido (LLM nao-stream)."""
    if not text:
        return
    for i in range(0, len(text), max(1, chunk_chars)):
        yield ("token", {"d": text[i : i + chunk_chars]})

def iter_agent_tool_stream(
    *,
    user_text: str,
    base_history: list[dict[str, str]],
    request_id: str,
    profile: str,
    max_tool_executions: int,
    audit: Callable[[dict[str, Any]], None] | None,
    meta_holder: dict[str, Any],
    chunk_chars: int = 48,
    model_override: str | None = None,
    workspace_store_key: str | None = None,
    canvas_write_ctx: dict[str, Any] | None = None,
    modality_invocations_out: list[dict[str, str]] | None = None,
    chat_session_id: str | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """
    Fluxo agent tools com eventos para SSE: tool_proposed, tool_running, tool_result, tool_denied, token.
    Preenche meta_holder com a mesma meta que run_agent_tool_flow + chave reply (texto completo).

    ``workspace_store_key``: F1 — chave do canvas in-process; omissão = ``request_id``.
    ``canvas_write_ctx``: Fase 10 / G6 — canvas.
    """
    ws_key = workspace_store_key if workspace_store_key is not None else request_id
    protocol, rag_info = build_agent_tools_protocol_message(user_text=user_text)
    few = build_few_shot_messages(enabled=AGENT_TOOLS_FEW_SHOT_ENABLED)
    hist = [*base_history, protocol, *few]
    rf = _agent_tools_json_response_format()
    meta: dict[str, Any] = {
        "agent_tools": True,
        "tools_run": 0,
        "json_parse_ok": True,
        "denied_tool": None,
        "json_repair_extra_calls": 0,
        "json_schema_repair_extra_calls": 0,
        "agent_tools_rag": rag_info,
    }
    current_user = user_text
    tail: list[dict[str, str]] = []
    full_reply: list[str] = []

    def _commit_meta() -> None:
        meta_holder.clear()
        meta_holder.update(meta)
        meta_holder["reply"] = "".join(full_reply)

    for _ in range(max_tool_executions + 1):
        raw_holder: list[str] = []
        try:
            for ev_name, ev_data in iter_thinking_events_collect_raw(
                user_text=current_user,
                messages=hist + tail,
                profile=profile,
                response_format=rf,
                raw_holder=raw_holder,
                model_override=model_override,
            ):
                yield (ev_name, ev_data)
        except RuntimeError as exc:
            meta["mode"] = "llm_stream_error"
            meta["json_parse_ok"] = False
            msg = str(exc)
            full_reply.append(msg)
            yield from _iter_text_as_token_events(msg, chunk_chars=chunk_chars)
            _commit_meta()
            return

        raw = raw_holder[0] if raw_holder else ""
        raw = _repair_agent_json_if_needed(
            raw,
            hist=hist,
            tail=tail,
            profile=profile,
            meta=meta,
            response_format=rf,
            model_override=model_override,
        )
        final, tool_calls, json_ok = parse_agent_tool_response(raw)
        meta["json_parse_ok"] = json_ok

        if not json_ok:
            meta["mode"] = "plain_text_no_json"
            full_reply.append(raw)
            yield from _iter_text_as_token_events(raw, chunk_chars=chunk_chars)
            _commit_meta()
            return

        if tool_calls and meta["tools_run"] < max_tool_executions:
            tc = tool_calls[0]
            name = str(tc.get("name", "")).strip()
            args = tc.get("arguments")
            if not isinstance(args, dict):
                args = {}

            if not is_registered_tool(name):
                meta["denied_tool"] = name
                meta["mode"] = "tool_denied"
                if audit:
                    audit(
                        {
                            "event": "tool_denied",
                            "request_id": request_id,
                            "tool": name,
                            "reason": "unknown_or_disallowed_tool",
                        }
                    )
                if final:
                    chunk = final.rstrip() + "\n\n"
                    full_reply.append(chunk)
                    yield from _iter_text_as_token_events(chunk, chunk_chars=chunk_chars)
                yield (
                    "tool_denied",
                    {"tool": name, "reason": "unknown_or_disallowed_tool"},
                )
                if not final:
                    msg = (
                        "O nome de ferramenta pedido nao esta no catalogo desta sessao. Usa apenas os nomes "
                        "listados no bloco [PROTOCOLO_AGENT_TOOLS] desta conversa (correspondencia exacta)."
                    )
                    full_reply.append(msg)
                    yield from _iter_text_as_token_events(msg, chunk_chars=chunk_chars)
                _commit_meta()
                return

            v_err = validate_tool_arguments(name, args)
            if v_err:
                final, name, args, raw, json_ok, v_err = _attempt_schema_repairs(
                    final=final,
                    name=name,
                    args=args,
                    raw=raw,
                    hist=hist,
                    tail=tail,
                    profile=profile,
                    meta=meta,
                    response_format=rf,
                    model_override=model_override,
                )
                meta["json_parse_ok"] = json_ok
                if not json_ok:
                    meta["mode"] = "plain_text_no_json"
                    full_reply.append(raw)
                    yield from _iter_text_as_token_events(raw, chunk_chars=chunk_chars)
                    _commit_meta()
                    return

            if v_err:
                meta["denied_tool"] = name
                meta["mode"] = "tool_denied"
                if audit:
                    audit(
                        {
                            "event": "tool_denied",
                            "request_id": request_id,
                            "tool": name,
                            "reason": "invalid_arguments",
                            "detail": v_err,
                        }
                    )
                if final:
                    chunk = final.rstrip() + "\n\n"
                    full_reply.append(chunk)
                    yield from _iter_text_as_token_events(chunk, chunk_chars=chunk_chars)
                yield (
                    "tool_denied",
                    {"tool": name, "reason": "invalid_arguments", "detail": v_err},
                )
                if not final:
                    msg = (
                        "Os argumentos JSON desta ferramenta nao sao validos para o schema registado. "
                        "Reformula o pedido ou tenta sem tool_calls."
                    )
                    full_reply.append(msg)
                    yield from _iter_text_as_token_events(msg, chunk_chars=chunk_chars)
                _commit_meta()
                return

            from app.shared.approvals_store import resolve_tenant_id_for_store

            pol = classify_tool_call(name, args, resolve_tenant_id_for_store())
            if not pol.allowed:
                meta["denied_tool"] = name
                meta["mode"] = "tool_denied"
                reason = pol.error_code or "policy_denied"
                if audit:
                    audit(
                        {
                            "event": "tool_denied",
                            "request_id": request_id,
                            "tool": name,
                            "reason": reason,
                            "message_pt": pol.message_pt,
                        }
                    )
                if final:
                    chunk = final.rstrip() + "\n\n"
                    full_reply.append(chunk)
                    yield from _iter_text_as_token_events(chunk, chunk_chars=chunk_chars)
                yield (
                    "tool_denied",
                    {
                        "tool": name,
                        "reason": reason,
                        "message_pt": pol.message_pt,
                    },
                )
                if not final:
                    msg = pol.message_pt or "Ferramenta bloqueada pela política da equipa."
                    full_reply.append(msg)
                    yield from _iter_text_as_token_events(msg, chunk_chars=chunk_chars)
                _commit_meta()
                return

            if final:
                chunk = final.rstrip() + "\n\n"
                full_reply.append(chunk)
                yield from _iter_text_as_token_events(chunk, chunk_chars=chunk_chars)

            yield ("tool_proposed", {"tool": name, "arguments": args})

            if audit:
                audit({"event": "tool_invoked", "request_id": request_id, "tool": name, "arguments": args})

            yield (
                "tool_running",
                {"tool": name, "arguments": _tool_running_arguments_for_sse(name, args)},
            )

            from app.context import record_tool_invocation, record_tool_result_event

            record_tool_invocation(
                canvas_write_ctx=canvas_write_ctx,
                tool=name,
                arguments=args if isinstance(args, dict) else {},
            )
            from app.shared.approvals_store import resolve_tenant_id_for_store

            result = dispatch_tool(
                name,
                args,
                request_id,
                workspace_store_key=ws_key,
                canvas_write_ctx=canvas_write_ctx,
                tenant_id=resolve_tenant_id_for_store(),
            )
            record_tool_result_event(
                canvas_write_ctx=canvas_write_ctx,
                tool=name,
                result=result if isinstance(result, dict) else {"raw": result},
            )
            if modality_invocations_out is not None:
                from app.shared.modality_models import record_modality_invocation_from_tool_result

                record_modality_invocation_from_tool_result(
                    modality_invocations_out,
                    tool_name=name,
                    result=result,
                )
            meta["tools_run"] = meta["tools_run"] + 1
            try:
                result_str = json.dumps(result, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                result_str = str(result)
            result_str = result_str[:14_000]
            preview = result_str[:800] + ("…" if len(result_str) > 800 else "")
            ok_ev = _sse_tool_ok_from_result(result)

            tr_payload: dict[str, Any] = {"tool": name, "ok": ok_ev, "preview": preview}
            if isinstance(result, dict):
                mp = result.get("message_pt")
                if isinstance(mp, str) and mp.strip():
                    tr_payload["message_pt"] = mp.strip()
                err = result.get("error")
                if isinstance(err, str) and err.strip():
                    tr_payload["error_code"] = err.strip()
                st = result.get("status")
                if isinstance(st, str) and st.strip():
                    tr_payload["status"] = st.strip()
                if st == "approval_required":
                    ar_payload: dict[str, Any] = {
                        "approval_id": result.get("approval_id"),
                        "action_id": result.get("action_id"),
                        "path": result.get("path"),
                        "diff": result.get("diff"),
                        "summary": result.get("summary"),
                    }
                    if result.get("command"):
                        ar_payload["command"] = result.get("command")
                    if result.get("preview"):
                        ar_payload["preview"] = result.get("preview")
                    if result.get("cwd"):
                        ar_payload["cwd"] = result.get("cwd")
                    yield ("approval_required", ar_payload)
                    sid = (chat_session_id or "").strip()
                    if sid:
                        from app.session_surface_service import register_pending_approval

                        register_pending_approval(
                            session_id=sid,
                            approval_id=str(result.get("approval_id") or ""),
                            summary=str(result.get("summary") or result.get("preview") or ""),
                        )
                    yield ("status", {"phase": "waiting_approval", "label": "aguarda aprovação"})
                    meta["mode"] = "waiting_approval"
                    _commit_meta()
                    return
                if name == "clarify" and result.get("clarification_needed"):
                    interrupt_id: str | None = None
                    sid = (chat_session_id or "").strip()
                    if sid:
                        from app.session_surface_service import register_clarify_interrupt

                        reg = register_clarify_interrupt(
                            session_id=sid,
                            question=str(result.get("question") or ""),
                            choices=list(result.get("choices") or []),
                            request_id=request_id,
                        )
                        interrupt_id = str(reg.get("interrupt_id") or "")
                    yield (
                        "clarify_required",
                        {
                            "interrupt_id": interrupt_id,
                            "question": result.get("question"),
                            "choices": result.get("choices") or [],
                        },
                    )
                    yield ("status", {"phase": "waiting_clarify", "label": "aguarda a tua escolha"})
                    meta["mode"] = "waiting_clarify"
                    _commit_meta()
                    return
            if name in ("manage_workspace_artifact", "apply_canvas_patch") and isinstance(result, dict):
                canv = result.get("canvas")
                if isinstance(canv, dict) and isinstance(canv.get("content"), str):
                    aid = canv.get("artifact_id")
                    tr_payload["canvas"] = {
                        "artifact_id": str(aid) if aid is not None else "",
                        "title": str(canv.get("title", "Artefacto")),
                        "artifact_type": str(canv.get("artifact_type", "plain")),
                        "content": canv["content"],
                        "revision": int(canv.get("revision", 0)),
                    }
                    sv = canv.get("schema_version")
                    if isinstance(sv, int):
                        tr_payload["canvas"]["schema_version"] = sv
                    sl = canv.get("slot")
                    if isinstance(sl, int):
                        tr_payload["canvas"]["slot"] = sl
                    gid = canv.get("group_id")
                    if isinstance(gid, str) and gid:
                        tr_payload["canvas"]["group_id"] = gid

            yield ("tool_result", tr_payload)

            if audit:
                audit(
                    {
                        "event": "tool_result_ok" if ok_ev else "tool_result_error",
                        "request_id": request_id,
                        "tool": name,
                    }
                )

            tail.append({"role": "assistant", "content": assistant_message_for_history(raw)})
            tail.append(
                {
                    "role": "system",
                    "content": f"TOOL_RESULT {name} (JSON read-only):\n{result_str}",
                }
            )
            current_user = post_tool_user_prompt(name)
            continue

        if final:
            meta["mode"] = "final_direct"
            full_reply.append(final)
            yield from _iter_text_as_token_events(final, chunk_chars=chunk_chars)
            _commit_meta()
            return

        meta["mode"] = "raw_fallback"
        full_reply.append(raw)
        yield from _iter_text_as_token_events(raw, chunk_chars=chunk_chars)
        _commit_meta()
        return

    meta["mode"] = "exhausted"
    _commit_meta()
