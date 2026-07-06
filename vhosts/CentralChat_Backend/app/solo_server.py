"""SOLO server — lightweight FastAPI for local-only CentralChat.

No PostgreSQL, no tenant isolation, no RAG pgvector.
Sessions stored as JSONL in ~/.central/sessions/.
Tools execute in-process on the local filesystem.

Start: python -m app.solo_server --port 9800
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("solo")

# ═══════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════

CENTRAL_DIR = Path(os.getenv("CENTRAL_DIR", Path.home() / ".central"))
SESSIONS_DIR = CENTRAL_DIR / "sessions"
MEMORY_DB = CENTRAL_DIR / "memory.json"

app = FastAPI(title="CentralChat SOLO", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ═══════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    text: str = Field(..., min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    chat_session_id: str | None = None
    agent_name: str | None = None
    model_override: str | None = None


# ═══════════════════════════════════════════════════════════════
# Session storage (JSONL)
# ═══════════════════════════════════════════════════════════════

def _ensure_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    CENTRAL_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.jsonl"


def _load_session(session_id: str) -> list[dict[str, str]]:
    path = _session_path(session_id)
    if not path.exists():
        return []
    messages: list[dict[str, str]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    msg = json.loads(line)
                    messages.append({"role": msg["role"], "content": msg["content"]})
                except json.JSONDecodeError:
                    continue
    return messages


def _append_turn(session_id: str, user_text: str, assistant_text: str) -> None:
    _ensure_dirs()
    path = _session_path(session_id)
    with open(path, "a") as f:
        f.write(json.dumps({"role": "user", "content": user_text}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"role": "assistant", "content": assistant_text}, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════
# Memory (simple JSON file)
# ═══════════════════════════════════════════════════════════════

def _load_memory() -> dict[str, Any]:
    if MEMORY_DB.exists():
        try:
            return json.loads(MEMORY_DB.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"facts": []}


def _save_memory(data: dict[str, Any]) -> None:
    _ensure_dirs()
    MEMORY_DB.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "solo"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {"status": "ok", "db": "local"}


@app.post("/assistant/text/stream")
async def assistant_text_stream(payload: AskRequest, request: Request):
    """Stream assistant response using ContextPipeline with local adapters."""
    _ensure_dirs()

    # Resolve session history
    session_id = payload.chat_session_id or str(uuid.uuid4())
    stored_history = _load_session(session_id)

    # Use stored history if available; otherwise use payload history
    history_dicts = stored_history if stored_history else [
        {"role": m.role, "content": m.content} for m in payload.history
    ]

    # Assemble context via the pipeline
    try:
        from app.context_pipeline import ContextPipeline
        from app.shared.context_manager import ContextStats
        from types import SimpleNamespace

        pipeline = ContextPipeline()
        p = SimpleNamespace(
            text=payload.text,
            history=[SimpleNamespace(role=m["role"], content=m["content"]) for m in history_dicts],
            chat_session_id=session_id,
            request_id=str(uuid.uuid4()),
        )

        assembled = pipeline.assemble(
            p, str(uuid.uuid4()),
            agent_name=payload.agent_name,
            connector_alive=True,  # SOLO mode always has local tools
            mode="cli",
            workspace_path=str(Path.cwd()),
            tenant_id="solo",
        )
    except Exception as exc:
        logger.exception("Context assembly failed")
        raise HTTPException(status_code=500, detail=f"Context assembly failed: {exc}")

    # Call LLM
    try:
        from app.clients import call_llm
        reply = call_llm(
            payload.text,
            assembled.injected_history,
            profile="balanced",
            model_override=payload.model_override,
            tools=assembled.openai_tools if assembled.openai_tools else None,
        )
    except Exception as exc:
        logger.exception("LLM call failed")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {exc}")

    # Save turn
    _append_turn(session_id, payload.text, reply)

    # Return as SSE stream (simple, single-event)
    async def sse():
        import json as _json
        yield f"event: token\ndata: {_json.dumps({'token': reply, 'session_id': session_id}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {_json.dumps({'session_id': session_id, 'model': payload.model_override or 'default'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.post("/assistant/text")
def assistant_text(payload: AskRequest):
    """Non-streaming text endpoint (synchronous)."""
    _ensure_dirs()

    session_id = payload.chat_session_id or str(uuid.uuid4())
    stored_history = _load_session(session_id)
    history_dicts = stored_history if stored_history else [
        {"role": m.role, "content": m.content} for m in payload.history
    ]

    from app.context_pipeline import ContextPipeline
    from types import SimpleNamespace

    pipeline = ContextPipeline()
    p = SimpleNamespace(
        text=payload.text,
        history=[SimpleNamespace(role=m["role"], content=m["content"]) for m in history_dicts],
        chat_session_id=session_id,
        request_id=str(uuid.uuid4()),
    )

    assembled = pipeline.assemble(
        p, str(uuid.uuid4()),
        agent_name=payload.agent_name,
        connector_alive=True,
        mode="cli",
        workspace_path=str(Path.cwd()),
        tenant_id="solo",
    )

    from app.clients import call_llm
    reply = call_llm(
        payload.text,
        assembled.injected_history,
        profile="balanced",
        model_override=payload.model_override,
    )

    _append_turn(session_id, payload.text, reply)
    return {"reply": reply, "session_id": session_id}


@app.get("/ui/chat-sessions")
def list_sessions() -> dict[str, Any]:
    """List all local sessions."""
    _ensure_dirs()
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        sid = f.stem
        messages = _load_session(sid)
        first_msg = messages[0]["content"][:80] if messages else "(empty)"
        sessions.append({
            "id": sid,
            "title": first_msg,
            "message_count": len(messages),
            "updated_at": f.stat().st_mtime,
        })
    return {"items": sessions, "chat_sessions_enabled": True}


# ═══════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="CentralChat SOLO server")
    parser.add_argument("--port", type=int, default=9800, help="Port to listen on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    _ensure_dirs()
    logger.info("SOLO server starting on %s:%d", args.host, args.port)
    logger.info("Sessions: %s", SESSIONS_DIR)
    logger.info("Memory: %s", MEMORY_DB)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
