"""ask_project tool — semantic codebase query via AST.

Registered as a Tier-0 tool (always available for knowledge queries).
Uses the AST pgvector store to answer natural language questions about
the codebase structure.

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §10 (D-AST-1)
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Tool specification (OpenAI function calling format)
ASK_PROJECT_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_project",
        "description": (
            "Ask a natural language question about the codebase structure. "
            "Uses AST indexing to find classes, functions, modules, and their relationships. "
            "Use this to understand how the project is organized, find where specific "
            "logic lives, or explore dependencies between modules."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language question about the codebase. "
                    "Examples: 'Where is authentication handled?', "
                    "'What classes inherit from BaseModel?', "
                    "'Show me all database repository functions.'",
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional: limit search to a specific file path.",
                },
                "node_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: filter by node types (module, class, function, method, import).",
                },
                "expand_imports": {
                    "type": "boolean",
                    "description": "If true, follow internal imports for additional context.",
                    "default": False,
                },
            },
            "required": ["query"],
        },
    },
}

# Tool description for keyword matching / RAG selection
ASK_PROJECT_DESCRIPTION_PT = (
    "ask_project: Pergunta sobre a estrutura do código-fonte — classes, funções, "
    "módulos, dependências. Usa indexação AST com busca semântica."
)

# Trigger keywords for keyword-based tool selection
ASK_PROJECT_TRIGGERS = [
    "estrutura", "código", "codebase", "project", "projeto",
    "módulo", "module", "classe", "class", "função", "function",
    "onde está", "where is", "como está organizado", "how is organized",
    "dependência", "dependency", "import", "herda", "inherits",
    "arquitetura", "architecture", "design pattern",
]


def execute_ask_project(
    query: str,
    *,
    tenant_id: str = "default",
    file_path: str | None = None,
    node_types: list[str] | None = None,
    expand_imports: bool = False,
    top_k: int = 10,
) -> dict[str, Any]:
    """Execute an ask_project query against the AST store.

    Returns structured results for the LLM to interpret.
    """
    from app.ast_store import query_ast_nodes

    results = query_ast_nodes(
        query=query,
        tenant_id=tenant_id,
        file_path=file_path,
        node_types=node_types,
        top_k=top_k,
        expand_imports=expand_imports,
    )

    if not results:
        return {
            "answer": "No matching code elements found. Try a different query or index the project first with POST /ast/index.",
            "results": [],
            "count": 0,
        }

    # Format results for LLM consumption
    formatted = []
    for r in results:
        entry = {
            "name": r["qualified_name"],
            "type": r["node_type"],
            "file": r["file_path"],
            "line": f"{r.get('line_start', '?')}-{r.get('line_end', '?')}",
            "similarity": r.get("similarity", 0),
        }
        if r.get("docstring"):
            entry["docstring"] = r["docstring"][:300]
        if r.get("signature"):
            entry["signature"] = r["signature"]
        formatted.append(entry)

    # Build a concise summary
    top = formatted[:5]
    summary_parts = [f"Found {len(results)} matching code elements. Top matches:"]
    for t in top:
        summary_parts.append(
            f"  - {t['type']} {t['name']} in {t['file']} "
            f"(similarity: {t['similarity']:.2f})"
        )

    return {
        "answer": "\n".join(summary_parts),
        "results": formatted[:top_k],
        "count": len(results),
        "query": query,
    }
