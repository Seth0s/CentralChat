"""
Prompts para compactacao eco. Usados apenas quando `include_long_session_memory=true`
em assistant_text (memoria longa); nao substituem a pre-injecao basal em ambientacao.py.
"""
from __future__ import annotations

from typing import Iterable


def _render_msgs_compact(old_msgs: list[dict[str, str]], *, max_chars: int) -> str:
    # Render a compact, deterministic transcript that small models can summarize.
    chunks: list[str] = []
    for m in old_msgs:
        role = str(m.get("role", "")).strip() or "unknown"
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        chunks.append(f"{role}: {content}")
    text = "\n".join(chunks)
    return text[:max_chars]


def build_eco_summary_prompt(
    old_msgs: list[dict[str, str]],
    *,
    max_input_chars: int = 120_000,
    max_total_bullets: int = 25,
    max_bullet_chars: int = 140,
) -> str:
    transcript = _render_msgs_compact(old_msgs, max_chars=max_input_chars)

    # Instruções para modelo eco (Gemma 4 instruct no homelab via llama-swap `eco`).
    return (
        "Tarefa: resumir CONVERSA_ANTIGA de forma curta e fiel.\n"
        "Regras:\n"
        "- Nao invente fatos. Use SOMENTE o que aparece na CONVERSA_ANTIGA.\n"
        "- Preserve nomes proprios, caminhos de ficheiro, comandos e valores técnicos com exactidao quando aparecerem.\n"
        "- Ignore blocos de raciocínio interno do assistente (ex. texto entre tags <thinking> ou <think>) ao extrair factos.\n"
        "- Se algo nao estiver claro, nao inclua.\n"
        "- Remova/mascare segredos, tokens, senhas, chaves: use [REDACTED].\n"
        "- Nao escreva explicacoes, so o formato abaixo.\n"
        f"- Limites: max {max_total_bullets} bullets no total; cada bullet <= {max_bullet_chars} chars.\n\n"
        "OUTPUT_FORMAT (exatamente nesta ordem):\n"
        "DECISOES:\n"
        "- ...\n"
        "CONFIGS_E_PATHS:\n"
        "- ...\n"
        "PENDENCIAS:\n"
        "- ...\n"
        "PREFERENCIAS_USUARIO:\n"
        "- ...\n\n"
        "CONVERSA_ANTIGA:\n"
        + transcript
    )


def build_recall_system_message(lines: Iterable[str], *, max_chars: int = 8000) -> dict[str, str] | None:
    payload = "\n".join([str(x).rstrip() for x in lines if str(x).strip()])
    payload = payload[:max_chars].strip()
    if not payload:
        return None
    return {"role": "system", "content": "Relevant memory (external recall):\n" + payload}


def build_session_facts_extract_prompt(
    *,
    user_text: str,
    assistant_text: str,
    max_facts: int = 2,
    max_bullet_chars: int = 220,
) -> str:
    """Phase 5 — extract durable facts from one completed turn (aux/eco model)."""
    u = (user_text or "").strip()[:4000]
    a = (assistant_text or "").strip()[:8000]
    return (
        "Tarefa: extrair factos curtos e verificáveis deste turno de chat (para memória da sessão).\n"
        "Regras:\n"
        "- Use SOMENTE o que aparece em USER e ASSISTANT abaixo.\n"
        "- Máximo "
        f"{max_facts} bullets; cada bullet <= {max_bullet_chars} caracteres.\n"
        "- Sem inventar; mascare segredos com [REDACTED].\n"
        "- Formato: uma linha por bullet começando com '- '.\n"
        "- Ignore raciocínio interno (<thinking>, etc.).\n\n"
        f"USER:\n{u}\n\nASSISTANT:\n{a}\n"
    )


def _parse_fact_bullets(raw: str, *, max_facts: int) -> list[str]:
    lines: list[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("-"):
            s = s.lstrip("-").strip()
        elif s.startswith("*"):
            s = s.lstrip("*").strip()
        if s:
            lines.append(s)
    return lines[: max(1, max_facts)]


def build_document_rag_system_message(
    *,
    doc_id: str,
    doc_title: str,
    chunks: list[tuple[int, str]],
    max_chars: int = 6000,
) -> dict[str, str] | None:
    """F5 C2 — bloco system com excertos semânticos de um documento indexado."""
    lines: list[str] = [
        "[DOCUMENT_RAG — excerpts only; do not invent facts beyond this context]",
        f"doc_id: {doc_id}",
        f"title: {doc_title}",
        "---",
    ]
    for idx, body in chunks:
        b = str(body).strip()
        if not b:
            continue
        lines.append(f"[chunk {idx}]\n{b}")
    content = "\n".join(lines).strip()
    content = content[:max_chars].strip()
    if len(content) < 64:
        return None
    return {"role": "system", "content": content}

