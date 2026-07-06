"""Fase 7 — pipeline híbrido: stream NDJSON com fallback e decisões auditáveis."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

from app.shared.l8_pipeline_policy import build_stream_fallback_attempts

logger = logging.getLogger(__name__)

StreamLinesFn = Callable[..., Iterator[str]]


def record_pipeline_decision(decisions_out: list[dict[str, Any]], **row: Any) -> None:
    decisions_out.append(dict(row))


def iter_ndjson_lines_with_stream_fallback(
    message: str,
    history: list[dict[str, str]],
    *,
    primary_profile: str,
    primary_model_override: str | None,
    decisions_out: list[dict[str, Any]],
    stream_lines: StreamLinesFn | None = None,
) -> Iterator[str]:
    """
    NDJSON do model-router com **fallback** entre perfis (política L8).

    Se ``e:error`` chega **antes** do primeiro ``e:token``, tenta o próximo par
    (``router_profile`` / ``model_override``) da cadeia. Erro após tokens enviados
    propaga-se sem novo perfil.
    """
    if stream_lines is None:
        from app.clients import iter_assistant_llm_ndjson as stream_lines  # noqa: PLC0415

    attempts = build_stream_fallback_attempts(primary_profile, primary_model_override)
    record_pipeline_decision(
        decisions_out,
        phase="fallback_plan",
        attempts=len(attempts),
        profiles=[a[0] for a in attempts],
    )

    for ai, (prof, mo, note) in enumerate(attempts):
        record_pipeline_decision(
            decisions_out,
            phase="stream_attempt_start",
            attempt=ai,
            router_profile=prof,
            model_override=mo,
            note=note,
        )
        sent_token = False
        try:
            gen = stream_lines(message, history, profile=prof, model_override=mo)
        except Exception as exc:
            record_pipeline_decision(
                decisions_out,
                phase="stream_open_error",
                attempt=ai,
                error=str(exc),
            )
            logger.info("hybrid_stream open fail attempt=%s profile=%s err=%s", ai, prof, exc)
            if ai + 1 >= len(attempts):
                raise
            continue

        retry_with_next_profile = False
        for line in gen:
            if not (line and str(line).strip()):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                yield line
                continue
            et = ev.get("e")
            if et == "token":
                sent_token = True
            if et == "error":
                if not sent_token and ai + 1 < len(attempts):
                    record_pipeline_decision(
                        decisions_out,
                        phase="ndjson_error_before_token",
                        attempt=ai,
                        message=str(ev.get("message") or ""),
                    )
                    retry_with_next_profile = True
                    break
                yield line
                record_pipeline_decision(
                    decisions_out,
                    phase="ndjson_error_final",
                    attempt=ai,
                    message=str(ev.get("message") or ""),
                )
                return
            yield line
            if et == "done":
                record_pipeline_decision(decisions_out, phase="stream_success", attempt=ai)
                return

        if retry_with_next_profile:
            continue

        record_pipeline_decision(decisions_out, phase="stream_exhausted_no_done", attempt=ai)
        if ai + 1 < len(attempts) and not sent_token:
            continue
        return
