"""
T19.5 — Context AST models (sem integração).

Modelos de dados para a árvore de sintaxe abstracta do contexto
de injecção. Representam a estrutura hierárquica das 7 camadas
de injecção (L6 anchor → user message).

Estes modelos são definidos mas NÃO integrados no pipeline de
injecção actual. A integração será feita quando o Context AST
substituir o sistema de injecção baseado em strings.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── AST Node Types ──────────────────────────

class ASTNodeKind(str, Enum):
    """Tipo de nó na árvore de contexto."""
    ROOT = "root"
    ANCHOR = "anchor"          # L6 — política global
    IDENTITY = "identity"      # User identity + preferences
    AGENT = "agent"            # Agent .md persona
    SKILL = "skill"            # Skill .md knowledge
    TOOL_DIGEST = "tool_digest"  # Tool capability summary
    RAG_RESULT = "rag_result"  # RAG lookup result
    HISTORY = "history"        # Inherited context + session history
    MESSAGE = "message"        # Current user message + attachments


# ── AST Node ────────────────────────────────

class ContextASTNode(BaseModel):
    """Nó na árvore de contexto de injecção.

    Representa uma camada do sistema de injecção hierárquico.
    Cada nó tem um tipo, conteúdo textual, e metadados de proveniência.
    """
    node_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    kind: ASTNodeKind
    label: str = ""
    content: str = ""
    token_count: int = 0
    children: list[ContextASTNode] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_hash: str | None = None  # para cache invalidation
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_tokens(self) -> int:
        """Soma de tokens deste nó + todos os filhos."""
        return self.token_count + sum(c.total_tokens for c in self.children)

    def flatten(self) -> list[ContextASTNode]:
        """Achata a árvore em lista (depth-first)."""
        nodes: list[ContextASTNode] = [self]
        for child in self.children:
            nodes.extend(child.flatten())
        return nodes


# ── Atena Observation ───────────────────────

class AtenaObservation(BaseModel):
    """Observação registada pelo meta-agente Atena.

    Cada observação captura um padrão de uso, correcção do utilizador,
    ou sugestão de melhoria. Armazenada em `atena_observations` (Postgres).
    """
    observation_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    tenant_id: str = "default"
    user_id: str | None = None
    kind: str = "usage_pattern"  # usage_pattern | correction | suggestion
    category: str = "general"    # agent, skill, tool, preference, context
    summary: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0     # 0.0–1.0
    applied: bool = False       # se a sugestão já foi aplicada
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
