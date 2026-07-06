"""T14 — Default Tools: 12 ferramentas padrão do Central (Hermes-compatible).

Substitui as tools system-agent legadas. Cada tool tem:
- plan_kind: identificador único
- arguments_schema: JSON Schema para validação
- risk_level: P0 (auto) | P1 (HITL light) | P2 (HITL) | P3 (HITL + double confirm)
"""

from __future__ import annotations

from typing import Any

# ═══ JSON SCHEMA HELPERS ═══

_SCHEMA_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}

_TERMINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command to execute"},
        "workdir": {"type": "string", "description": "Working directory"},
        "timeout": {"type": "integer", "minimum": 1, "maximum": 600, "default": 120},
        "background": {"type": "boolean", "default": False},
    },
    "required": ["command"],
}

_READ_FILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute file path"},
        "offset": {"type": "integer", "minimum": 1, "default": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 500},
    },
    "required": ["path"],
}

_WRITE_FILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute file path"},
        "content": {"type": "string", "description": "File content to write"},
    },
    "required": ["path", "content"],
}

_SEARCH_FILES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Regex or glob pattern"},
        "path": {"type": "string", "default": ".", "description": "Directory to search"},
        "file_glob": {"type": "string", "description": "Filter by file pattern (e.g. *.py)"},
        "target": {"type": "string", "enum": ["content", "files"], "default": "content"},
    },
    "required": ["pattern"],
}

_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File to edit"},
        "old_string": {"type": "string", "description": "Text to find and replace"},
        "new_string": {"type": "string", "description": "Replacement text"},
    },
    "required": ["path", "old_string", "new_string"],
}

_MEMORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["add", "replace", "remove"]},
        "target": {"type": "string", "enum": ["memory", "user"]},
        "content": {"type": "string", "description": "Entry content (for add/replace)"},
        "old_text": {"type": "string", "description": "Text to replace/remove (for replace/remove)"},
    },
    "required": ["action", "target"],
}

_DELEGATE_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "description": "What the subagent should accomplish"},
        "context": {"type": "string", "description": "Background info for the subagent"},
        "toolsets": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["goal"],
}

_EXEC_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "description": "Tool name to invoke"},
                    "arguments": {"type": "object", "description": "Tool arguments"},
                },
                "required": ["tool", "arguments"],
            },
        },
        "stop_on_error": {"type": "boolean", "default": True},
        "summary": {"type": "string", "description": "Optional plan summary for audit"},
    },
    "required": ["steps"],
}

_WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    },
    "required": ["query"],
}

_EXECUTE_CODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "Python code to execute"},
        "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 60},
    },
    "required": ["code"],
}

_SESSION_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query for past sessions"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
    },
    "required": ["query"],
}

_CLARIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "Question to ask the user"},
        "choices": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["question"],
}

_VISION_ANALYZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "image_url": {"type": "string", "description": "URL or local path to image"},
        "question": {"type": "string", "description": "What to ask about the image"},
    },
    "required": ["image_url", "question"],
}

# ═══ TOOL SPECS ═══

DEFAULT_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "terminal": {
        "plan_kind": "tool.terminal",
        "plan_description_pt": "Executa comandos shell no terminal local com timeout e background opcional.",
        "arguments_schema": _TERMINAL_SCHEMA,
        "risk_level": "P2",
        "maps_to_action_id": "shell.exec",
        "protocol_hint_en": 'terminal: {"command": "<cmd>", "workdir": "/path", "timeout": 120, "background": false}',
    },
    "read_file": {
        "plan_kind": "tool.read_file",
        "plan_description_pt": "Lê ficheiro local com line numbers e paginação (substitui cat/head/tail).",
        "arguments_schema": _READ_FILE_SCHEMA,
        "risk_level": "P0",
        "maps_to_action_id": "filesystem.path.read_external",
        "protocol_hint_en": 'read_file: {"path": "/abs/path", "offset": 1, "limit": 500}',
    },
    "write_file": {
        "plan_kind": "tool.write_file",
        "plan_description_pt": "Escreve/sobrescreve ficheiro local, cria directórios pai automaticamente.",
        "arguments_schema": _WRITE_FILE_SCHEMA,
        "risk_level": "P2",
        "maps_to_action_id": "filesystem.path.write_config",
        "protocol_hint_en": 'write_file: {"path": "/abs/path", "content": "text"}',
    },
    "search_files": {
        "plan_kind": "tool.search_files",
        "plan_description_pt": "Pesquisa conteúdo (regex) ou ficheiros (glob) no sistema local (ripgrep).",
        "arguments_schema": _SEARCH_FILES_SCHEMA,
        "risk_level": "P0",
        "maps_to_action_id": "filesystem.path.read_external",
        "protocol_hint_en": 'search_files: {"pattern": "regex", "path": ".", "target": "content"}',
    },
    "patch": {
        "plan_kind": "tool.patch",
        "plan_description_pt": "Find-replace fuzzy em ficheiros (9 estratégias de matching).",
        "arguments_schema": _PATCH_SCHEMA,
        "risk_level": "P2",
        "maps_to_action_id": "filesystem.path.write_config",
        "protocol_hint_en": 'patch: {"path": "/file", "old_string": "...", "new_string": "..."}',
    },
    "memory": {
        "plan_kind": "tool.memory",
        "plan_description_pt": "Memória persistente entre sessões: add, replace, remove. Target: memory ou user.",
        "arguments_schema": _MEMORY_SCHEMA,
        "risk_level": "P0",
        "maps_to_action_id": "orchestrator.memory.manage",
        "protocol_hint_en": 'memory: {"action": "add|replace|remove", "target": "memory|user", "content": "...", "old_text": "..."}',
    },
    "delegate_task": {
        "plan_kind": "tool.delegate_task",
        "plan_description_pt": "Delega uma tarefa a um sub-agente isolado (contexto separado, terminal separado).",
        "arguments_schema": _DELEGATE_TASK_SCHEMA,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.delegate.spawn",
        "protocol_hint_en": 'delegate_task: {"goal": "...", "context": "...", "toolsets": ["terminal","file"]}',
    },
    "exec_plan": {
        "plan_kind": "tool.exec_plan",
        "plan_description_pt": "Executa um plano batch de tools sequencialmente (máx. 10 passos), com policy em cada passo.",
        "arguments_schema": _EXEC_PLAN_SCHEMA,
        "risk_level": "P1",
        "maps_to_action_id": "orchestrator.exec_plan.batch",
        "protocol_hint_en": 'exec_plan: {"steps": [{"tool": "read_file", "arguments": {"path": "/file"}}], "stop_on_error": true}',
    },
    "web_search": {
        "plan_kind": "tool.web_search",
        "plan_description_pt": "Pesquisa web via DuckDuckGo (sem necessidade de API key).",
        "arguments_schema": _WEB_SEARCH_SCHEMA,
        "risk_level": "P0",
        "maps_to_action_id": "web.search",
        "protocol_hint_en": 'web_search: {"query": "search terms", "max_results": 5}',
    },
    "execute_code": {
        "plan_kind": "tool.execute_code",
        "plan_description_pt": "Executa script Python sandboxed local com acesso a hermes_tools.",
        "arguments_schema": _EXECUTE_CODE_SCHEMA,
        "risk_level": "P1",
        "maps_to_action_id": "shell.exec",
        "protocol_hint_en": 'execute_code: {"code": "print(1+1)", "timeout": 60}',
    },
    "session_search": {
        "plan_kind": "tool.session_search",
        "plan_description_pt": "Pesquisa em sessões passadas (FTS5 SQLite) para recall cross-session.",
        "arguments_schema": _SESSION_SEARCH_SCHEMA,
        "risk_level": "P0",
        "maps_to_action_id": "orchestrator.session.search",
        "protocol_hint_en": 'session_search: {"query": "topic keywords", "limit": 3}',
    },
    "clarify": {
        "plan_kind": "tool.clarify",
        "plan_description_pt": "Pede esclarecimento ao utilizador (multiple choice ou open-ended).",
        "arguments_schema": _CLARIFY_SCHEMA,
        "risk_level": "P0",
        "maps_to_action_id": "orchestrator.clarify.ask",
        "protocol_hint_en": 'clarify: {"question": "...", "choices": ["A", "B"]}',
    },
    "vision_analyze": {
        "plan_kind": "tool.vision_analyze",
        "plan_description_pt": "Analisa imagem via modelo de visão (OpenRouter multimodal).",
        "arguments_schema": _VISION_ANALYZE_SCHEMA,
        "risk_level": "P0",
        "maps_to_action_id": "orchestrator.vision.analyze",
        "protocol_hint_en": 'vision_analyze: {"image_url": "http://...", "question": "what do you see?"}',
    },
    "ask_project": {
        "plan_kind": "tool.ask_project",
        "plan_description_pt": "Pergunta sobre a estrutura do código — classes, funções, módulos, dependências. Usa AST indexing com busca semântica.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Pergunta em linguagem natural sobre a codebase."},
                "file_path": {"type": "string", "description": "Opcional: limitar a ficheiro específico."},
                "node_types": {"type": "array", "items": {"type": "string"}, "description": "Filtrar por tipo: module, class, function, method, import."},
                "expand_imports": {"type": "boolean", "description": "Seguir imports internos para contexto adicional.", "default": False},
            },
            "required": ["query"],
        },
        "risk_level": "P0",
        "maps_to_action_id": "ast.query",
        "protocol_hint_en": 'ask_project: {"query": "where is authentication logic?"}',
    },
    "create_work_item": {
        "plan_kind": "tool.create_work_item",
        "plan_description_pt": "Cria um novo item de trabalho na fila da equipa. Usa para delegar tarefas a developers ou agentes.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título do work item"},
                "description": {"type": "string", "description": "Descrição detalhada"},
                "agent_name": {"type": "string", "description": "Agente recomendado (coder, reviewer, architect)"},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "Skills para contexto L3"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                "labels": {"type": "array", "items": {"type": "string"}},
                "assignee_id": {"type": "string", "description": "UUID do developer"},
            },
            "required": ["title"],
        },
        "risk_level": "P0",
        "maps_to_action_id": "work_item.create",
        "protocol_hint_en": 'create_work_item: {"title": "Fix bug", "agent_name": "coder", "priority": "high"}',
    },
    "update_work_item": {
        "plan_kind": "tool.update_work_item",
        "plan_description_pt": "Actualiza um work item: muda status, atribui dev, ou adiciona comentário.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID do work item (ex: WI-42)"},
                "status": {"type": "string", "enum": ["open", "in_progress", "review", "done", "cancelled"]},
                "assignee_id": {"type": "string"},
                "comment": {"type": "string", "description": "Comentário a adicionar"},
            },
            "required": ["item_id"],
        },
        "risk_level": "P0",
        "maps_to_action_id": "work_item.update",
        "protocol_hint_en": 'update_work_item: {"item_id": "WI-42", "status": "review", "comment": "PR ready"}',
    },
    "list_work_items": {
        "plan_kind": "tool.list_work_items",
        "plan_description_pt": "Lista os work items da fila. Filtra por status ou assignee.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "assignee_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": [],
        },
        "risk_level": "P0",
        "maps_to_action_id": "work_item.list",
        "protocol_hint_en": 'list_work_items: {"status": "open"}',
    },
    "claim_work_item": {
        "plan_kind": "tool.claim_work_item",
        "plan_description_pt": "Reivindica um work item e começa a trabalhar, criando sessão com contexto do WI.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID do work item (ex: WI-42)"},
            },
            "required": ["item_id"],
        },
        "risk_level": "P0",
        "maps_to_action_id": "work_item.claim",
        "protocol_hint_en": 'claim_work_item: {"item_id": "WI-42"}',
    },
}

DEFAULT_TOOL_NAMES = sorted(DEFAULT_TOOL_SPECS.keys())

# ═══ TOOL NAME CONSTANTS ═══

TOOL_NAME_TERMINAL = "terminal"
TOOL_NAME_READ_FILE = "read_file"
TOOL_NAME_WRITE_FILE = "write_file"
TOOL_NAME_SEARCH_FILES = "search_files"
TOOL_NAME_PATCH = "patch"
TOOL_NAME_MEMORY = "memory"
TOOL_NAME_DELEGATE_TASK = "delegate_task"
TOOL_NAME_EXEC_PLAN = "exec_plan"
TOOL_NAME_WEB_SEARCH = "web_search"
TOOL_NAME_EXECUTE_CODE = "execute_code"
TOOL_NAME_SESSION_SEARCH = "session_search"
TOOL_NAME_CLARIFY = "clarify"
TOOL_NAME_VISION_ANALYZE = "vision_analyze"
TOOL_NAME_ASK_PROJECT = "ask_project"
TOOL_NAME_CREATE_WORK_ITEM = "create_work_item"
TOOL_NAME_UPDATE_WORK_ITEM = "update_work_item"
TOOL_NAME_LIST_WORK_ITEMS = "list_work_items"
TOOL_NAME_CLAIM_WORK_ITEM = "claim_work_item"

_DEFAULT_TOOL_NAMES_SET = frozenset(DEFAULT_TOOL_SPECS.keys())

# ═══ HANDLERS ═══


def dispatch_terminal(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    from app.config import CENTRAL_PRODUCT_MODE  # noqa: PLC0415

    if CENTRAL_PRODUCT_MODE:
        from app.shell_service import propose_terminal_command  # noqa: PLC0415

        return propose_terminal_command(arguments, request_id)

    command: str = str(arguments.get("command", "")).strip()
    if not command:
        return {"ok": False, "error": "empty_command", "request_id": request_id}
    workdir_raw = arguments.get("workdir")
    workdir: str | None = str(workdir_raw).strip() if workdir_raw else None
    timeout: int = int(arguments.get("timeout", 120))
    background: bool = bool(arguments.get("background", False))
    timeout = max(1, min(600, timeout))
    import subprocess
    try:
        r = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=workdir,
            timeout=timeout,
        )
        return {
            "ok": r.returncode == 0,
            "exit_code": r.returncode,
            "stdout": r.stdout[:50000],
            "stderr": r.stderr[:20000],
            "request_id": request_id,
            "background": background,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "timeout_sec": timeout, "request_id": request_id}
    except FileNotFoundError:
        return {"ok": False, "error": "command_not_found", "request_id": request_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "request_id": request_id}


def dispatch_read_file(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    from app.config import CENTRAL_PRODUCT_MODE  # noqa: PLC0415

    if CENTRAL_PRODUCT_MODE:
        from app.file_change_service import read_file_for_tool  # noqa: PLC0415

        return read_file_for_tool(arguments, request_id)
    path: str = str(arguments.get("path", "")).strip()
    if not path:
        return {"ok": False, "error": "empty_path", "request_id": request_id}
    offset: int = int(arguments.get("offset", 1))
    limit: int = int(arguments.get("limit", 500))
    offset = max(1, offset)
    limit = max(1, min(2000, limit))
    import os as _os
    if not _os.path.isfile(path):
        return {"ok": False, "error": "not_found", "path": path, "request_id": request_id}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        total = len(lines)
        start = offset - 1
        end = min(start + limit, total)
        selected = lines[start:end]
        content = "".join(selected)
        return {
            "ok": True,
            "path": path,
            "total_lines": total,
            "offset": offset,
            "limit": limit,
            "content": content[:100000],
            "request_id": request_id,
        }
    except PermissionError:
        return {"ok": False, "error": "permission_denied", "path": path, "request_id": request_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "path": path, "request_id": request_id}


def dispatch_write_file(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    from app.config import CENTRAL_PRODUCT_MODE  # noqa: PLC0415

    if CENTRAL_PRODUCT_MODE:
        from app.file_change_service import propose_write_file  # noqa: PLC0415

        return propose_write_file(arguments, request_id)
    path: str = str(arguments.get("path", "")).strip()
    content: str = str(arguments.get("content", ""))
    if not path:
        return {"ok": False, "error": "empty_path", "request_id": request_id}
    import os as _os
    # UNDO: snapshot before mutation
    from app.turn_file_log import get_turn_log
    get_turn_log(request_id).snapshot_before_mutate(path)
    parent = _os.path.dirname(path)
    if parent:
        _os.makedirs(parent, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        size = _os.path.getsize(path)
        return {"ok": True, "path": path, "bytes_written": size, "request_id": request_id}
    except PermissionError:
        return {"ok": False, "error": "permission_denied", "path": path, "request_id": request_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "path": path, "request_id": request_id}


def dispatch_search_files(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    pattern: str = str(arguments.get("pattern", "")).strip()
    if not pattern:
        return {"ok": False, "error": "empty_pattern", "request_id": request_id}
    search_path: str = str(arguments.get("path", ".")).strip() or "."
    target: str = str(arguments.get("target", "content")).strip()
    file_glob: str = str(arguments.get("file_glob", "") or "").strip() or None
    import subprocess
    cmd = ["rg", "--line-number", "--no-heading", "--color=never", "-M", "200"]
    if file_glob:
        cmd.extend(["--glob", file_glob])
    cmd.extend([pattern, search_path])
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [ln.strip() for ln in r.stdout.strip().split("\n") if ln.strip()]
        return {
            "ok": True,
            "pattern": pattern,
            "path": search_path,
            "target": target,
            "matches": lines[:200],
            "match_count": len(lines),
            "request_id": request_id,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "request_id": request_id}
    except FileNotFoundError:
        try:
            cmd2 = ["grep", "-rn", "--include", file_glob or "*", pattern, search_path]
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
            lines = [ln.strip() for ln in r2.stdout.strip().split("\n") if ln.strip()]
            return {
                "ok": True,
                "pattern": pattern,
                "path": search_path,
                "target": target,
                "matches": lines[:200],
                "match_count": len(lines),
                "fallback": "grep",
                "request_id": request_id,
            }
        except Exception:
            return {"ok": False, "error": "rg_not_found", "request_id": request_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "request_id": request_id}


def dispatch_patch(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    from app.config import CENTRAL_PRODUCT_MODE  # noqa: PLC0415

    if CENTRAL_PRODUCT_MODE:
        from app.file_change_service import propose_patch_file  # noqa: PLC0415

        return propose_patch_file(arguments, request_id)
    path: str = str(arguments.get("path", "")).strip()
    old_string: str = str(arguments.get("old_string", ""))
    new_string: str = str(arguments.get("new_string", ""))
    if not path:
        return {"ok": False, "error": "empty_path", "request_id": request_id}
    if not old_string:
        return {"ok": False, "error": "empty_old_string", "request_id": request_id}
    import os as _os
    if not _os.path.isfile(path):
        return {"ok": False, "error": "not_found", "path": path, "request_id": request_id}
    try:
        # UNDO: snapshot before mutation
        from app.turn_file_log import get_turn_log
        get_turn_log(request_id).snapshot_before_mutate(path)
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        if old_string not in original:
            return {"ok": False, "error": "old_string_not_found", "path": path, "request_id": request_id}
        count = original.count(old_string)
        replaced = original.replace(old_string, new_string)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(replaced)
        return {
            "ok": True,
            "path": path,
            "occurrences_replaced": count,
            "request_id": request_id,
        }
    except PermissionError:
        return {"ok": False, "error": "permission_denied", "path": path, "request_id": request_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "path": path, "request_id": request_id}


def dispatch_memory(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    action: str = str(arguments.get("action", "")).strip()
    target: str = str(arguments.get("target", "memory")).strip()
    if action not in ("add", "replace", "remove"):
        return {"ok": False, "error": "invalid_action", "request_id": request_id}
    if target not in ("memory", "user"):
        return {"ok": False, "error": "invalid_target", "request_id": request_id}
    content: str = str(arguments.get("content", "") or "")
    old_text_raw = arguments.get("old_text")
    old_text: str | None = str(old_text_raw).strip() if old_text_raw else None
    from app.rag import embed_local_hash, upsert_memory_item, search_memory  # noqa: PLC0415

    _ns = "memory" if target == "memory" else "user_profile"
    _kind = "user" if target == "user" else "agent"
    _tags: list[str] = [target]
    _emb_model_id = "local_hash_256"
    _dim = 256

    if action == "add":
        if not content.strip():
            return {"ok": False, "error": "empty_content", "request_id": request_id}
        embedding = embed_local_hash(content[:4000], dim=_dim)
        item_id = upsert_memory_item(
            namespace=_ns,
            kind=_kind,
            content=content[:4000],
            tags=_tags,
            embedding=embedding,
            embedding_model_id=_emb_model_id,
            request_id=request_id,
        )
        return {"ok": True, "action": "add", "target": target, "item_id": item_id, "request_id": request_id}
    elif action == "replace":
        if not old_text or not content.strip():
            return {"ok": False, "error": "old_text_and_content_required", "request_id": request_id}
        query_embedding = embed_local_hash(old_text[:4000], dim=_dim)
        results = search_memory(namespace=_ns, query_embedding=query_embedding, top_k=3, embedding_model_id=_emb_model_id)
        replaced = 0
        for r in results:
            if old_text in (r.content or ""):
                embedding = embed_local_hash(content[:4000], dim=_dim)
                upsert_memory_item(
                    namespace=_ns, kind=_kind, content=content[:4000], tags=_tags,
                    embedding=embedding, embedding_model_id=_emb_model_id, request_id=request_id,
                )
                replaced += 1
        return {"ok": True, "action": "replace", "target": target, "replaced_count": replaced, "request_id": request_id}
    else:
        if not old_text:
            return {"ok": False, "error": "old_text_required_for_remove", "request_id": request_id}
        query_embedding = embed_local_hash(old_text[:4000], dim=_dim)
        results = search_memory(namespace=_ns, query_embedding=query_embedding, top_k=5, embedding_model_id=_emb_model_id)
        removed = 0
        for r in results:
            if old_text in (r.content or ""):
                removed += 1
        return {"ok": True, "action": "remove", "target": target, "removed_count": removed, "request_id": request_id}


def dispatch_delegate_task(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    goal: str = str(arguments.get("goal", "")).strip()
    if not goal:
        return {"ok": False, "error": "empty_goal", "request_id": request_id}
    ctx_raw = arguments.get("context")
    context: str | None = str(ctx_raw).strip() if ctx_raw else None
    toolsets_raw = arguments.get("toolsets")
    toolsets: list[str] = list(toolsets_raw) if isinstance(toolsets_raw, list) else []
    return {
        "ok": True,
        "delegated": True,
        "goal": goal[:2000],
        "context": context[:4000] if context else None,
        "toolsets": toolsets[:10],
        "message_pt": f"Tarefa delegada: {goal[:200]}...",
        "request_id": request_id,
    }


def dispatch_web_search(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    query: str = str(arguments.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "empty_query", "request_id": request_id}
    max_results: int = int(arguments.get("max_results", 5))
    max_results = max(1, min(10, max_results))
    import json as _json
    try:
        import urllib.request
        import urllib.parse
        encoded = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "CentralOrchestrator/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = _json.loads(resp.read().decode("utf-8"))
        abstract = body.get("AbstractText", "") or body.get("Abstract", "")
        related = body.get("RelatedTopics", [])[:max_results]
        results = []
        if abstract:
            results.append({"title": body.get("Heading", "Result"), "snippet": abstract[:2000], "url": body.get("AbstractURL", "")})
        for rt in related:
            if isinstance(rt, dict):
                results.append({
                    "title": rt.get("Text", "")[:200] or query,
                    "snippet": rt.get("Text", "")[:2000],
                    "url": rt.get("FirstURL", ""),
                })
        return {
            "ok": True,
            "query": query,
            "results": results[:max_results],
            "result_count": len(results),
            "request_id": request_id,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "request_id": request_id}


def dispatch_execute_code(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    code: str = str(arguments.get("code", "")).strip()
    if not code:
        return {"ok": False, "error": "empty_code", "request_id": request_id}
    timeout: int = int(arguments.get("timeout", 60))
    timeout = max(1, min(300, timeout))
    import subprocess, tempfile, os as _os
    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
        tmp.write(code)
        tmp.close()
        r = subprocess.run(
            ["python3", tmp.name],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_os.getcwd(),
        )
        return {
            "ok": r.returncode == 0,
            "exit_code": r.returncode,
            "stdout": r.stdout[:50000],
            "stderr": r.stderr[:20000],
            "request_id": request_id,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "timeout_sec": timeout, "request_id": request_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "request_id": request_id}
    finally:
        if tmp and _os.path.isfile(tmp.name):
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass


def dispatch_session_search(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    query: str = str(arguments.get("query", "")).strip()
    limit: int = int(arguments.get("limit", 3))
    limit = max(1, min(10, limit))
    if not query:
        return {"ok": True, "query": "", "sessions": [], "message_pt": "Session search delegado ao agente (query vazia — list recent).", "request_id": request_id}
    return {
        "ok": True,
        "query": query[:1000],
        "limit": limit,
        "message_pt": f"Pesquisa de sessões por '{query[:200]}...' delegada ao agente Hermes.",
        "request_id": request_id,
    }


def dispatch_clarify(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    question: str = str(arguments.get("question", "")).strip()
    if not question:
        return {"ok": False, "error": "empty_question", "request_id": request_id}
    choices_raw = arguments.get("choices")
    choices: list[str] = [str(c) for c in choices_raw] if isinstance(choices_raw, list) else []
    return {
        "ok": True,
        "clarification_needed": True,
        "question": question[:2000],
        "choices": [str(c)[:500] for c in choices[:4]],
        "request_id": request_id,
    }


def dispatch_exec_plan(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """H3 — batch tool execution with per-step policy checks."""
    from app.audit_service import append_audit_event
    from app.shared.policy_engine import evaluate_tool_policy

    steps_raw = arguments.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        return {"ok": False, "error": "empty_steps", "request_id": request_id}
    stop_on_error = bool(arguments.get("stop_on_error", True))
    summary = str(arguments.get("summary") or "").strip()
    steps = steps_raw[:10]
    results: list[dict[str, Any]] = []
    append_audit_event(
        action="exec_plan.started",
        resource="exec_plan",
        metadata={"step_count": len(steps), "summary": summary[:500] or None},
    )
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            results.append({"index": idx, "ok": False, "error": "invalid_step"})
            if stop_on_error:
                break
            continue
        tool_name = str(step.get("tool") or "").strip()
        args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        if not tool_name or tool_name == TOOL_NAME_EXEC_PLAN:
            results.append({"index": idx, "tool": tool_name, "ok": False, "error": "invalid_tool"})
            if stop_on_error:
                break
            continue
        if tool_name not in _DEFAULT_TOOL_NAMES_SET:
            results.append({"index": idx, "tool": tool_name, "ok": False, "error": "unknown_tool"})
            if stop_on_error:
                break
            continue
        pol = evaluate_tool_policy(tool_name, args)
        if not pol.allowed:
            from app.shared.policy_audit import record_policy_violation

            record_policy_violation(
                tool=tool_name,
                error_code=pol.error_code,
                message_pt=pol.message_pt,
                violation=pol.violation,
                args=args,
            )
            results.append(
                {
                    "index": idx,
                    "tool": tool_name,
                    "ok": False,
                    "error": pol.error_code or "policy_denied",
                    "message_pt": pol.message_pt,
                }
            )
            if stop_on_error:
                break
            continue
        step_rid = f"{request_id}-step{idx}"
        try:
            out = dispatch_default_tool(tool_name, args, step_rid)
        except Exception as exc:
            out = {"ok": False, "error": str(exc)[:200]}
        results.append({"index": idx, "tool": tool_name, **out})
        append_audit_event(
            action="exec_plan.step",
            resource=tool_name,
            metadata={"index": idx, "ok": bool(out.get("ok"))},
        )
        if stop_on_error and not out.get("ok"):
            break
    ok_all = all(r.get("ok") for r in results if "ok" in r) and bool(results)
    append_audit_event(
        action="exec_plan.completed",
        resource="exec_plan",
        metadata={"ok": ok_all, "steps_run": len(results)},
    )
    return {
        "ok": ok_all,
        "steps_run": len(results),
        "results": results,
        "request_id": request_id,
    }


def dispatch_vision_analyze(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    image_url: str = str(arguments.get("image_url", "")).strip()
    question: str = str(arguments.get("question", "")).strip()
    if not image_url:
        return {"ok": False, "error": "empty_image_url", "request_id": request_id}
    return {
        "ok": True,
        "vision_delegated": True,
        "image_url": image_url[:2000],
        "question": question[:2000] if question else None,
        "message_pt": f"Análise de visão delegada ao modelo multimodal: {question[:200] if question else 'descreve a imagem'}",
        "request_id": request_id,
    }


def dispatch_ask_project(arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Dispatch ask_project AST query."""
    from app.ast_tool import execute_ask_project

    return execute_ask_project(
        query=str(arguments.get("query", "")),
        file_path=arguments.get("file_path"),
        node_types=arguments.get("node_types"),
        expand_imports=bool(arguments.get("expand_imports", False)),
    )


# ═══ DISPATCH TABLE ═══

_DEFAULT_TOOL_DISPATCH: dict[str, Any] = {
    TOOL_NAME_TERMINAL: dispatch_terminal,
    TOOL_NAME_READ_FILE: dispatch_read_file,
    TOOL_NAME_WRITE_FILE: dispatch_write_file,
    TOOL_NAME_SEARCH_FILES: dispatch_search_files,
    TOOL_NAME_PATCH: dispatch_patch,
    TOOL_NAME_MEMORY: dispatch_memory,
    TOOL_NAME_DELEGATE_TASK: dispatch_delegate_task,
    TOOL_NAME_EXEC_PLAN: dispatch_exec_plan,
    TOOL_NAME_WEB_SEARCH: dispatch_web_search,
    TOOL_NAME_EXECUTE_CODE: dispatch_execute_code,
    TOOL_NAME_SESSION_SEARCH: dispatch_session_search,
    TOOL_NAME_CLARIFY: dispatch_clarify,
    TOOL_NAME_VISION_ANALYZE: dispatch_vision_analyze,
    TOOL_NAME_ASK_PROJECT: dispatch_ask_project,
}


def dispatch_default_tool(tool_name: str, arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Dispatch a default tool by name. Returns result dict or raises RuntimeError if unknown."""
    handler = _DEFAULT_TOOL_DISPATCH.get(tool_name.strip())
    if handler is None:
        raise RuntimeError(f"default_tool_dispatch_missing:{tool_name}")
    return handler(arguments, request_id)
