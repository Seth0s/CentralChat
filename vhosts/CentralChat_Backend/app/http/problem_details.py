"""RFC 9457 Problem Details (`application/problem+json`) for public API errors."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_TYPE_PREFIX = "https://api.central.invalid/problems"

_MEDIA = "application/problem+json"


def _title_for_status(status: int) -> str:
    return {
        400: "Pedido inválido",
        401: "Não autenticado",
        403: "Proibido",
        404: "Não encontrado",
        409: "Conflito",
        422: "Validação falhou",
        429: "Demasiados pedidos",
        500: "Erro interno",
        502: "Gateway inválido",
        503: "Serviço indisponível",
    }.get(status, "Erro HTTP")


def _problem_body(
    *,
    type_suffix: str,
    title: str,
    status: int,
    detail: str,
    instance: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"{PROBLEM_TYPE_PREFIX}/{type_suffix}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    if extensions:
        body.update(jsonable_encoder(extensions))
    return body


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # inclui FastAPI HTTPException
    status = int(exc.status_code)
    instance = request.url.path
    detail_raw = exc.detail
    if isinstance(detail_raw, list):
        detail_msg = "; ".join(str(x) for x in detail_raw)
        body = _problem_body(
            type_suffix="http_error",
            title=_title_for_status(status),
            status=status,
            detail=detail_msg,
            instance=instance,
        )
        return JSONResponse(status_code=status, content=body, media_type=_MEDIA)
    if isinstance(detail_raw, dict):
        err = str(detail_raw.get("error") or "http_error")
        detail_msg = str(detail_raw.get("detail") or detail_raw.get("message") or err)
        title = str(detail_raw.get("title") or _title_for_status(status))
        extensions = {k: v for k, v in detail_raw.items() if k not in ("error", "detail", "title", "message")}
        body = _problem_body(
            type_suffix=err,
            title=title,
            status=status,
            detail=detail_msg,
            instance=instance,
            extensions=extensions or None,
        )
        return JSONResponse(status_code=status, content=body, media_type=_MEDIA)
    detail_msg = str(detail_raw) if detail_raw is not None else _title_for_status(status)
    suffix = "not_found" if status == 404 else "http_error"
    body = _problem_body(
        type_suffix=suffix,
        title=_title_for_status(status),
        status=status,
        detail=detail_msg,
        instance=instance,
    )
    return JSONResponse(status_code=status, content=body, media_type=_MEDIA)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc")
        errors.append(
            {
                "loc": list(loc) if isinstance(loc, tuple) else loc,
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    body = _problem_body(
        type_suffix="validation-error",
        title="Pedido inválido",
        status=422,
        detail="Um ou mais campos falharam a validação.",
        instance=request.url.path,
        extensions={"errors": errors},
    )
    return JSONResponse(status_code=422, content=body, media_type=_MEDIA)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import asyncio

    if isinstance(exc, asyncio.CancelledError):
        raise
    logger.exception("Unhandled exception path=%s", request.url.path)
    body = _problem_body(
        type_suffix="internal-error",
        title="Erro interno",
        status=500,
        detail="Ocorreu um erro interno no servidor.",
        instance=request.url.path,
    )
    return JSONResponse(status_code=500, content=body, media_type=_MEDIA)


def problem_json_response(
    *,
    status: int,
    type_suffix: str,
    detail: str,
    instance: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    body = _problem_body(
        type_suffix=type_suffix,
        title=_title_for_status(status),
        status=status,
        detail=detail,
        instance=instance,
        extensions=extensions,
    )
    return JSONResponse(status_code=status, content=body, media_type=_MEDIA)


def register_exception_handlers(app: FastAPI) -> None:
    # Ordem: mais específicos antes do catch-all `Exception`.
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
