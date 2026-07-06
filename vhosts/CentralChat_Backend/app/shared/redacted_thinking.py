"""
Strip e fan-out de blocos de raciocínio (DeepSeek-R1 / variantes) para parse de JSON e SSE.

Formatos suportados:
- Abertura/fecho com nome de elemento **redacted_thinking** (oficial HF nos distilados R1 / Qwen)
- Abertura/fecho com nome de elemento **think** (forma curta; testes e variantes)
- Abertura/fecho com nome de elemento **thinking** (sem prefixo redacted)
"""
from __future__ import annotations

# Oficial nos checkpoints DeepSeek-R1-Distill (Qwen/Llama), cf. model card / discussões HF.
TAG_OPEN_DEEPSEEK_R1 = "<" + "redacted" + "_" + "thinking" + ">"
TAG_CLOSE_DEEPSEEK_R1 = "</" + "redacted" + "_" + "thinking" + ">"

# Forma curta usada em variantes / testes (não confundir com a oficial acima).
TAG_OPEN_THINK_SHORT = "<" + "think" + ">"
TAG_CLOSE_THINK_SHORT = "</" + "think" + ">"

TAG_OPEN_PLAIN = "<thinking>"
TAG_CLOSE_PLAIN = "</thinking>"

_THINK_TAG_PAIRS: tuple[tuple[str, str], ...] = (
    (TAG_OPEN_DEEPSEEK_R1, TAG_CLOSE_DEEPSEEK_R1),
    (TAG_OPEN_THINK_SHORT, TAG_CLOSE_THINK_SHORT),
    (TAG_OPEN_PLAIN, TAG_CLOSE_PLAIN),
)

# Nomes estáveis para o splitter (fases internas).
_THINK_PHASE_BY_OPEN: dict[str, str] = {
    TAG_OPEN_DEEPSEEK_R1: "deepseek_r1",
    TAG_OPEN_THINK_SHORT: "think_short",
    TAG_OPEN_PLAIN: "plain",
}

_CLOSE_BY_PHASE: dict[str, str] = {
    "deepseek_r1": TAG_CLOSE_DEEPSEEK_R1,
    "think_short": TAG_CLOSE_THINK_SHORT,
    "plain": TAG_CLOSE_PLAIN,
}

_ALL_THINK_TAGS: tuple[str, ...] = tuple(t for pair in _THINK_TAG_PAIRS for t in pair)

# Reserva no buffer para não partir tags ao meio
_MAX_TAG_TAIL = max(len(t) for t in _ALL_THINK_TAGS) + 4


def split_redacted_thinking_body(text: str) -> tuple[str, str | None]:
    """
    Devolve (resto_para_parse_json, conteúdo_interno_do_thinking_ou_None).

    Se a tag de abertura existir sem fecho, devolve (text, None) — parse conservador.
    """
    best_o = -1
    chosen: tuple[str, str] | None = None
    for open_t, close_t in _THINK_TAG_PAIRS:
        o = text.find(open_t)
        if o >= 0 and (best_o < 0 or o < best_o):
            best_o = o
            chosen = (open_t, close_t)
    if chosen is None:
        return text, None
    open_t, close_t = chosen
    o = text.find(open_t)
    c = text.find(close_t, o + len(open_t))
    if o >= 0 and c > o:
        inner = text[o + len(open_t) : c]
        remainder = text[c + len(close_t) :].lstrip()
        return remainder, inner.strip() or None
    if o >= 0 and c < 0:
        return text, None
    return text, None


def text_for_agent_tool_json_parse(text: str) -> str:
    """Remove bloco de thinking antes de extrair o envelope JSON das agent tools."""
    remainder, _ = split_redacted_thinking_body(text)
    return remainder


def assistant_message_for_history(raw_assistant: str) -> str:
    """Conteúdo a gravar no histórico após turno com tools (evita repetição enorme de CoT)."""
    remainder, think = split_redacted_thinking_body(raw_assistant)
    if think is not None:
        return remainder
    return raw_assistant


class RedactedThinkingStreamSplitter:
    """
    Parte chunks NDJSON do LLM em eventos lógicos `thinking` vs `token` (conteúdo público).
    Emite `thinking_done` após fechar o bloco (payload vazio).
    """

    def __init__(self) -> None:
        self._buf = ""
        self._phase: str = "out"  # out | deepseek_r1 | think_short | plain
        self._openers: list[tuple[str, str, str]] = [
            (ph, o, c)
            for o, c in _THINK_TAG_PAIRS
            if (ph := _THINK_PHASE_BY_OPEN.get(o))
        ]

    def _suffix_might_be_tag_prefix(self, s: str) -> bool:
        if not s:
            return False
        tail = s[-_MAX_TAG_TAIL:]
        for tag in _ALL_THINK_TAGS:
            for i in range(1, min(len(tag), len(tail)) + 1):
                if tail.endswith(tag[:i]):
                    return True
        return False

    def feed(self, chunk: str) -> list[tuple[str, dict[str, str]]]:
        self._buf += chunk
        events: list[tuple[str, dict[str, str]]] = []

        while True:
            if self._phase == "out":
                opts: list[tuple[int, str, str, str]] = []
                for ph, open_t, close_t in self._openers:
                    i = self._buf.find(open_t)
                    if i >= 0:
                        opts.append((i, ph, open_t, close_t))
                if not opts:
                    if not self._buf:
                        break
                    if self._suffix_might_be_tag_prefix(self._buf):
                        break
                    piece = self._buf
                    self._buf = ""
                    if piece:
                        events.append(("token", {"d": piece}))
                    break
                idx, ph, open_tag, _close_unused = min(opts, key=lambda x: x[0])
                if idx > 0:
                    events.append(("token", {"d": self._buf[:idx]}))
                self._buf = self._buf[idx + len(open_tag) :]
                self._phase = ph
                continue

            if self._phase in _CLOSE_BY_PHASE:
                close_tag = _CLOSE_BY_PHASE[self._phase]
                c = self._buf.find(close_tag)
                if c < 0:
                    if not self._buf:
                        break
                    if self._suffix_might_be_tag_prefix(self._buf):
                        break
                    take = len(self._buf)
                    piece = self._buf[:take]
                    self._buf = ""
                    if piece:
                        events.append(("thinking", {"d": piece}))
                    break
                if c > 0:
                    events.append(("thinking", {"d": self._buf[:c]}))
                self._buf = self._buf[c + len(close_tag) :]
                self._phase = "out"
                events.append(("thinking_done", {}))
                continue

        return events

    def flush(self) -> list[tuple[str, dict[str, str]]]:
        events: list[tuple[str, dict[str, str]]] = []
        if self._phase == "out":
            if self._buf:
                events.append(("token", {"d": self._buf}))
                self._buf = ""
            return events
        if self._buf:
            events.append(("thinking", {"d": self._buf}))
            self._buf = ""
        events.append(("thinking_done", {}))
        self._phase = "out"
        return events
