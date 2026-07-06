"""
Atena — Meta-agente reservado (T19).

Atena é o único agente fornecido pelo sistema (não user-owned).
Observa padrões de uso, sugere melhorias a agentes/skills, e
auto-ajusta preferências com base em correcções do utilizador.

ESTADO ACTUAL (T19): Infra-estrutura preparada. Lógica do agente
será implementada em fase futura. Ver docs/T19_ATENA.md.

Flags:
    CENTRAL_ATENA_ENABLED=0  — desligado por defeito
"""

# T19.5 — Context AST models (sem integração)
from .models import AtenaObservation, ContextASTNode

__all__ = ["AtenaObservation", "ContextASTNode"]
