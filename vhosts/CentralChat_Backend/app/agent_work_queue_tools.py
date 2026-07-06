"""Agent tools for Work Queue — TIER_0 tools for agent-driven delegation.

Tools:
  create_work_item — Create a new work item
  update_work_item — Update status, assignee, or add comment
  list_work_items — Query the work queue
  claim_work_item — Claim an open WI and start working

These tools close the loop between the Agent Platform and Work Queue,
enabling agent-driven delegation with persistent audit trail and RBAC.

Design: docs/WORK_QUEUE_PLAN.md — Bloco I
"""

from __future__ import annotations

from typing import Any


# ═══════════════════════════════════════════════════════════════
# Tool specs (for default_tools.py DEFAULT_TOOL_SPECS)
# ═══════════════════════════════════════════════════════════════

WORK_QUEUE_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "create_work_item": {
        "plan_kind": "tool.create_work_item",
        "plan_description_pt": (
            "Cria um novo item de trabalho (work item) na fila da equipa. "
            "Usa para delegar tarefas a developers humanos ou a outros agentes."
        ),
        "protocol_hint_en": 'create_work_item: {"title": "...", "agent_name": "coder", "skills": ["debug"], "priority": "high"}',
        "arguments_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título do work item (obrigatório)"},
                "description": {"type": "string", "description": "Descrição detalhada da tarefa"},
                "agent_name": {"type": "string", "description": "Agente recomendado (coder, reviewer, architect)"},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "Skills a injectar no contexto"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "Prioridade"},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "Etiquetas de categorização"},
                "assignee_id": {"type": "string", "description": "UUID do developer atribuído (opcional)"},
            },
            "required": ["title"],
        },
        "risk_level": "low",
        "maps_to_action_id": "work_item.create",
    },
    "update_work_item": {
        "plan_kind": "tool.update_work_item",
        "plan_description_pt": (
            "Actualiza um work item existente: muda status, atribui a um dev, ou adiciona comentário. "
            "Usa para reportar progresso ou transferir tarefas."
        ),
        "protocol_hint_en": 'update_work_item: {"item_id": "WI-42", "status": "in_progress", "comment": "A trabalhar nisto"}',
        "arguments_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID do work item (ex: WI-42)"},
                "status": {"type": "string", "enum": ["open", "in_progress", "review", "done", "cancelled"]},
                "assignee_id": {"type": "string", "description": "Novo assignee (UUID)"},
                "comment": {"type": "string", "description": "Comentário a adicionar ao WI"},
            },
            "required": ["item_id"],
        },
        "risk_level": "low",
        "maps_to_action_id": "work_item.update",
    },
    "list_work_items": {
        "plan_kind": "tool.list_work_items",
        "plan_description_pt": (
            "Lista os work items da fila. Filtra por assignee ou status. "
            "Usa para descobrir que tarefas existem ou estão atribuídas a ti."
        ),
        "protocol_hint_en": 'list_work_items: {"status": "open", "assignee_id": null}',
        "arguments_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "in_progress", "review", "done", "cancelled"]},
                "assignee_id": {"type": "string", "description": "Filtrar por developer (UUID)"},
                "limit": {"type": "integer", "description": "Máximo de resultados (default 20)"},
            },
            "required": [],
        },
        "risk_level": "low",
        "maps_to_action_id": "work_item.list",
    },
    "claim_work_item": {
        "plan_kind": "tool.claim_work_item",
        "plan_description_pt": (
            "Reivindica um work item aberto e começa a trabalhar nele. "
            "Cria uma sessão nova com o contexto do WI (agente, skills, workspace)."
        ),
        "protocol_hint_en": 'claim_work_item: {"item_id": "WI-42"}',
        "arguments_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID do work item a reivindicar (ex: WI-42)"},
            },
            "required": ["item_id"],
        },
        "risk_level": "low",
        "maps_to_action_id": "work_item.claim",
    },
}


# ═══════════════════════════════════════════════════════════════
# Dispatch functions
# ═══════════════════════════════════════════════════════════════

def dispatch_create_work_item(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Create a work item from agent tool call."""
    from app.work_queue import create_work_item

    title = str(arguments.get("title", "")).strip()
    if not title:
        return {"ok": False, "error": "title_required", "request_id": request_id}

    try:
        item = create_work_item(
            title=title,
            description=arguments.get("description"),
            priority=arguments.get("priority", "normal"),
            labels=arguments.get("labels"),
            agent_name=arguments.get("agent_name"),
            skills=arguments.get("skills"),
            source="agent",
        )
        return {
            "ok": True,
            "request_id": request_id,
            "work_item": {"id": item["id"], "title": item["title"], "status": item["status"]},
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "request_id": request_id}


def dispatch_update_work_item(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Update a work item from agent tool call."""
    from app.work_queue import patch_work_item, add_work_item_comment, get_work_item

    item_id = str(arguments.get("item_id", "")).strip()
    if not item_id:
        return {"ok": False, "error": "item_id_required", "request_id": request_id}

    wi = get_work_item(item_id)
    if not wi:
        return {"ok": False, "error": "work_item_not_found", "request_id": request_id}

    try:
        status = arguments.get("status")
        assignee = arguments.get("assignee_id")
        if status or assignee:
            patch_work_item(item_id, status=status, assignee_id=assignee)

        comment = arguments.get("comment")
        if comment:
            add_work_item_comment(item_id, body=str(comment))

        updated = get_work_item(item_id)
        return {
            "ok": True,
            "request_id": request_id,
            "work_item": updated,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "request_id": request_id}


def dispatch_list_work_items(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """List work items from agent tool call."""
    from app.work_queue import list_work_items

    try:
        items = list_work_items(
            status=arguments.get("status"),
            assignee_id=arguments.get("assignee_id"),
            limit=arguments.get("limit", 20),
        )
        summary = [
            {"id": i["id"], "title": i["title"], "status": i["status"],
             "priority": i["priority"], "assignee_id": i["assignee_id"]}
            for i in items
        ]
        return {
            "ok": True,
            "request_id": request_id,
            "items": summary,
            "total": len(summary),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "request_id": request_id}


def dispatch_claim_work_item(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Claim a work item — mark in_progress and create session."""
    from app.work_queue import get_work_item, patch_work_item

    item_id = str(arguments.get("item_id", "")).strip()
    if not item_id:
        return {"ok": False, "error": "item_id_required", "request_id": request_id}

    wi = get_work_item(item_id)
    if not wi:
        return {"ok": False, "error": "work_item_not_found", "request_id": request_id}

    if wi.get("status") not in ("open",):
        return {"ok": False, "error": f"cannot_claim_status_{wi.get('status')}", "request_id": request_id}

    try:
        from app.sessions import create_session

        sid = wi.get("session_id")
        if not sid:
            sess = create_session(title=wi.get("title"))
            sid = str(sess.get("id", ""))

        patch_work_item(item_id, status="in_progress", session_id=sid)
        updated = get_work_item(item_id)

        return {
            "ok": True,
            "request_id": request_id,
            "work_item": updated,
            "session_id": sid,
            "hint": f"Sessão {sid} criada com contexto do WI {item_id}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "request_id": request_id}
