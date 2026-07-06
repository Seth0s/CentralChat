"""
Fase H — gatilho opcional por texto para injetar contexto de host sem include_host_context=true.

Conservador: exige indicador de *intenção* (uso/carga/quantos/…) e *métrica/recurso* (cpu, ram, …).
Só ativo com HOST_CONTEXT_TEXT_TRIGGER_ENABLED=1 no servidor.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_text_for_trigger(text: str) -> str:
    nk = unicodedata.normalize("NFKD", text.strip())
    return "".join(c for c in nk if not unicodedata.combining(c)).lower()


# Palavra de recurso / métrica (host)
_RESOURCE = re.compile(
    r"\b("
    r"cpu|memoria|ram|disco|load|processo|processos|memoria virtual|swap|nucleo|nucleos|core|cores"
    r")\b",
    re.IGNORECASE,
)

# Intenção de pergunta factual sobre o sistema
_INTENT = re.compile(
    r"\b("
    r"uso|carga|quantos?|quanto|percent|por cento|nivel|livre|ocupad|disponivel|"
    r"snapshot|host|metricas|desempenho|performance|espaco|memoria usada|"
    r"sistema operativo|qual o so|versao do kernel|container|docker"
    r")\b",
    re.IGNORECASE,
)


def should_inject_host_context_from_text(text: str) -> bool:
    """
    True se o texto do usuário sugere pergunta factual sobre recursos do host.
    Não substitui include_host_context explícito; combina-se no servidor.
    """
    if len(text.strip()) < 6:
        return False
    n = normalize_text_for_trigger(text)
    return bool(_RESOURCE.search(n) and _INTENT.search(n))
