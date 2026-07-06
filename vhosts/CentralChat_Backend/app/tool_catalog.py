"""Tool Catalog — single source of truth for tool metadata.

Eliminates duplication across context_pipeline.py, tool_selection.py,
and default_tools.py. All tool classification lives here.

Categories:
  KNOWLEDGE   — always available, read-only, server-side
  FILE_READ   — file inspection (needs connector or local FS)
  FILE_WRITE  — file mutation (needs connector)
  SHELL       — shell/exec (needs connector)
  ORCHESTRATE — multi-agent orchestration (needs connector)
  WEB         — web access (server-side or connector)
  VISION      — image analysis (server-side)

Design: This is the ONE place to add/remove tools from categories.
"""

from __future__ import annotations

from typing import Any

# ═══════════════════════════════════════════════════════════════
# Tool categories (by name)
# ═══════════════════════════════════════════════════════════════

# Tier-0: always available, server-side knowledge tools
TIER_0: set[str] = {
    "memory",
    "session_search",
    "clarify",
    "ask_project",
    "create_work_item",
    "update_work_item",
    "list_work_items",
    "claim_work_item",
}

# Knowledge tools (read-only, no connector needed)
KNOWLEDGE_TOOLS: set[str] = {
    "web_search",
    "vision_analyze",
}

# Tools that ONLY work with a connector (delegated to the user's machine)
DELEGATED_TOOLS: set[str] = {
    "terminal",
    "read_file",
    "search_files",
    "write_file",
    "patch",
    "execute_code",
    "delegate_task",
    "cronjob",
    "process",
}

# Tools ALWAYS available regardless of connector state
ALWAYS_AVAILABLE_TOOLS: set[str] = {
    "apply_canvas_patch",
    "manage_workspace_artifact",
}

# All tools aggregated
ALL_TOOLS: set[str] = TIER_0 | KNOWLEDGE_TOOLS | DELEGATED_TOOLS | ALWAYS_AVAILABLE_TOOLS


# ═══════════════════════════════════════════════════════════════
# Tool → category mapping
# ═══════════════════════════════════════════════════════════════

def derive_category(name: str) -> str:
    """Derive tool category from name."""
    if name in ("read_file", "search_files"):
        return "file_inspection"
    if name in ("write_file", "patch"):
        return "file_write"
    if name in ("terminal", "execute_code"):
        return "shell"
    if name in TIER_0 or name in KNOWLEDGE_TOOLS:
        return "knowledge"
    if name == "web_search":
        return "web"
    if name == "vision_analyze":
        return "vision"
    if name in ("delegate_task", "cronjob"):
        return "orchestration"
    return "other"


# ═══════════════════════════════════════════════════════════════
# Keyword triggers (for keyword-based tool selection)
# ═══════════════════════════════════════════════════════════════

TRIGGER_MAP: dict[str, list[str]] = {
    "terminal": [
        "executar", "comando", "shell", "bash", "run", "cmd",
        "terminal", "script", "build", "testar", "instalar",
        "compilar", "git", "npm", "pip", "docker", "podman",
    ],
    "read_file": [
        "ler", "ficheiro", "arquivo", "file", "código",
        "source", "conteúdo", "linhas", "abrir",
    ],
    "write_file": [
        "criar", "escrever", "criar ficheiro", "novo ficheiro",
        "write", "gerar", "output", "salvar",
    ],
    "search_files": [
        "procurar", "pesquisar", "buscar", "grep", "find",
        "search", "localizar", "pattern", "regex",
    ],
    "patch": [
        "editar", "alterar", "modificar", "corrigir", "patch",
        "mudar", "substituir", "replace", "update",
    ],
    "memory": [
        "lembrar", "recordar", "memória", "salvar preferência",
        "remember", "save", "nota",
    ],
    "delegate_task": [
        "delegar", "subagente", "spawn", "paralelo",
        "delegate", "task", "dividir",
    ],
    "web_search": [
        "pesquisar web", "internet", "google", "search online",
        "web", "notícias", "atual",
    ],
    "execute_code": [
        "executar código", "python", "script", "run code",
        "eval", "executar script",
    ],
    "session_search": [
        "histórico", "conversa anterior", "session", "passado",
        "última vez", "conversa passada",
    ],
    "clarify": [
        "perguntar", "esclarecer", "dúvida", "confirmar",
        "qual", "prefere",
    ],
    "vision_analyze": [
        "imagem", "foto", "screenshot", "print", "captura",
        "ver imagem", "analisar imagem",
    ],
    "ask_project": [
        "estrutura", "código", "codebase", "project", "módulo",
        "classe", "função", "onde está", "arquitetura",
        "dependency", "inherits",
    ],
    "create_work_item": [
        "criar tarefa", "criar wi", "delegar", "work item",
        "nova tarefa", "atribuir", "assign", "criar ticket",
    ],
    "update_work_item": [
        "atualizar wi", "mudar status", "fechar tarefa",
        "concluir wi", "mover tarefa", "atualizar work item",
    ],
    "list_work_items": [
        "listar tarefas", "fila", "queue", "work items",
        "tarefas pendentes", "minhas tarefas", "o que tenho",
    ],
    "claim_work_item": [
        "pegar tarefa", "reivindicar", "claim", "começar tarefa",
        "iniciar wi", "trabalhar em",
    ],
}


# ═══════════════════════════════════════════════════════════════
# Tool spec access (delegates to default_tools for actual specs)
# ═══════════════════════════════════════════════════════════════

def get_tool_spec(name: str) -> dict[str, Any] | None:
    """Get the full tool spec for a tool name."""
    from app.tools import _TOOL_SPECS

    return _TOOL_SPECS.get(name)


def get_all_tool_names() -> list[str]:
    """Get all registered tool names."""
    from app.tools import _TOOL_SPECS

    return sorted(_TOOL_SPECS.keys())


def get_available_tools(*, connector_alive: bool = False) -> set[str]:
    """Get tools available given the connector state.

    - Without connector: TIER_0 + KNOWLEDGE + ALWAYS_AVAILABLE
    - With connector: all tools
    """
    available = TIER_0 | KNOWLEDGE_TOOLS | ALWAYS_AVAILABLE_TOOLS
    if connector_alive:
        available |= DELEGATED_TOOLS
    return available
