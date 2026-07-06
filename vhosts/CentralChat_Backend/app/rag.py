"""RAG domain — document, session, product, agent-tools RAG + memory + pgvector stores.

Consolidated from 13 files: rag.py, document_rag*.py, session_rag*.py, product_rag*.py,
memory_store_pgvector.py, memory_context.py, agent_tools_rag*.py, ui_document_rag.py.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import config as cfg
from app.clients import call_llm
from app.inference import get_model_router_public_config, resolve_aux_llm_call_params
from app.playbook import _central_focus_abort, list_playbook_entries_meta
from app.shared.assistant_preferences import load_preferences
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.prompt_injection import _parse_fact_bullets, build_session_facts_extract_prompt
from app.sessions import count_session_summaries
from app.tools import (
    AGENT_TOOLS_VECTOR_DIM,
    _TOOL_SPECS,
    active_agent_tools_embedding_model_id,
    embed_agent_tools_text,
    filter_tool_names_for_llm,
    list_registered_tool_names_for_llm_prompt,
    record_agent_tools_rag_select,
)
from app.config import (
    AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW,
    AGENT_TOOLS_RAG_EMBEDDING_BACKEND,
    AGENT_TOOLS_RAG_ENABLED,
    AGENT_TOOLS_RAG_MIN_TOOLS,
    AGENT_TOOLS_RAG_TOP_K,
    CENTRAL_COMPACT_MIN_VERBATIM_TOKENS,
    CENTRAL_COMPACTION_ASYNC_ENABLED,
    CENTRAL_FOCUS_MODE,
    CENTRAL_PRODUCT_RAG_ENABLED,
    CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL,
    CENTRAL_SESSION_RAG_ENABLED,
    CENTRAL_SESSION_RAG_MAX_FACTS_PER_TURN,
    CENTRAL_SESSION_RAG_PROMPT_MAX_CHARS,
    CENTRAL_SESSION_RAG_TOP_K,
    CENTRAL_SESSION_RAG_USE_LLM_EXTRACT,
    CHAT_SESSIONS_ENABLED,
    COMPACT_SUMMARY_STORE_PATH,
    DOCUMENT_RAG_CHUNK_CHARS,
    DOCUMENT_RAG_CHUNK_OVERLAP,
    DOCUMENT_RAG_MAX_CHUNKS_PER_DOC,
    DOCUMENT_RAG_MAX_DOC_BYTES,
    DOCUMENT_RAG_PROMPT_MAX_CHARS,
    DOCUMENT_RAG_SERVER_ENABLED,
    DOCUMENT_RAG_TOP_K,
    MEMORY_DB_URL,
    MEMORY_ENABLED,
    MEMORY_MAX_BLOCK_CHARS,
    MEMORY_TOP_K,
    PLAYBOOK_FEATURE_ENABLED,
    PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED,
    SESSION_MAX_MESSAGES_NO_LONG_MEMORY,
)

_log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# DOCUMENT RAG CHUNKING
# ═══════════════════════════════════════════════════════════════════


def extract_plaintext_from_file(path: str, *, max_bytes: int) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {"source_path": os.path.basename(path), "kind": "unknown"}
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ValueError(f"document_too_large:{size}>{max_bytes}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf_not_installed") from exc
        reader = PdfReader(path)
        parts: list[str] = []
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                parts.append(f"--- page {i + 1} ---\n{t}")
        text = "\n\n".join(parts).strip()
        meta["kind"] = "pdf"
        meta["pages"] = len(reader.pages)
        return text, meta
    meta["kind"] = "text"
    with open(path, "rb") as f:
        raw = f.read(max_bytes)
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    return text.strip(), meta


def extract_plaintext_from_bytes(raw: bytes, *, filename: str, max_bytes: int) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {"source_path": os.path.basename(filename or "upload"), "kind": "unknown"}
    if len(raw) > max_bytes:
        raise ValueError(f"document_too_large:{len(raw)}>{max_bytes}")
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf_not_installed") from exc
        reader = PdfReader(io.BytesIO(raw))
        parts: list[str] = []
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                parts.append(f"--- page {i + 1} ---\n{t}")
        text = "\n\n".join(parts).strip()
        meta["kind"] = "pdf"
        meta["pages"] = len(reader.pages)
        return text, meta
    meta["kind"] = "text"
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    return text.strip(), meta


def chunk_plaintext(text: str, *, max_chunk_chars: int, overlap: int, max_chunks: int) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    max_chunk_chars = max(256, int(max_chunk_chars))
    overlap = max(0, min(int(overlap), max_chunk_chars // 2))
    max_chunks = max(1, int(max_chunks))
    out: list[str] = []
    start = 0
    n = len(t)
    while start < n and len(out) < max_chunks:
        end = min(start + max_chunk_chars, n)
        if end < n:
            window = t[start:end]
            nl = window.rfind("\n\n")
            if nl > max_chunk_chars // 3:
                end = start + nl
            else:
                sp = window.rfind(" ")
                if sp > max_chunk_chars // 3:
                    end = start + sp
        chunk = t[start:end].strip()
        if chunk:
            out.append(chunk)
        if end >= n:
            break
        start = max(0, end - overlap)
    return out


# ═══════════════════════════════════════════════════════════════════
# DOCUMENT RAG STORE PGVECTOR
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DocumentRagHit:
    chunk_index: int
    content: str
    title: str
    score: float


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _resolve_rags_tenant(*, tenant_id: str | None = None, owner_id: str | None = None) -> str:
    if tenant_id and str(tenant_id).strip():
        return str(tenant_id).strip()
    if owner_id and str(owner_id).strip() and owner_id.strip() != "local":
        return str(owner_id).strip()
    return resolve_pg_tenant_id()


def ensure_document_rag_schema(*, embedding_dim: int | None = None) -> None:
    if not memory_db_enabled():
        return
    dim = int(embedding_dim or AGENT_TOOLS_VECTOR_DIM)
    dim = max(2, dim)
    with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS document_rag_chunks (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  tenant_id TEXT NOT NULL DEFAULT 'default', owner_id TEXT NOT NULL DEFAULT 'default',
                  doc_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', chunk_index INT NOT NULL,
                  content TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                  embedding vector({dim}), embedding_model_id TEXT NOT NULL, embedding_dim INT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  UNIQUE (tenant_id, doc_id, chunk_index));"""
            )
            cur.execute("""CREATE INDEX IF NOT EXISTS document_rag_chunks_tenant_doc_idx ON document_rag_chunks (tenant_id, doc_id);""")
            try:
                cur.execute(f"""CREATE INDEX IF NOT EXISTS document_rag_chunks_ivfflat ON document_rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);""")
            except Exception:
                pass


def delete_document_chunks(*, owner_id: str | None = None, tenant_id: str | None = None, doc_id: str) -> int:
    if not memory_db_enabled():
        return 0
    tid = _resolve_rags_tenant(tenant_id=tenant_id, owner_id=owner_id)
    ensure_document_rag_schema()
    did = (doc_id or "").strip()
    if not did:
        return 0
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM document_rag_chunks WHERE tenant_id = %s AND doc_id = %s;", (tid, did))
        return int(cur.rowcount or 0)


def upsert_document_chunk(*, owner_id: str | None = None, tenant_id: str | None = None, doc_id: str, title: str,
                          chunk_index: int, content: str, metadata: dict[str, Any], embedding: list[float],
                          embedding_model_id: str) -> None:
    if not memory_db_enabled():
        return
    tid = _resolve_rags_tenant(tenant_id=tenant_id, owner_id=owner_id)
    dim = len(embedding) or AGENT_TOOLS_VECTOR_DIM
    ensure_document_rag_schema(embedding_dim=dim)
    vec = _vector_literal(embedding)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO document_rag_chunks (tenant_id,owner_id,doc_id,title,chunk_index,content,metadata,embedding,embedding_model_id,embedding_dim)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)
               ON CONFLICT (tenant_id,doc_id,chunk_index) DO UPDATE SET owner_id=EXCLUDED.owner_id,title=EXCLUDED.title,
               content=EXCLUDED.content,metadata=EXCLUDED.metadata,embedding=EXCLUDED.embedding,
               embedding_model_id=EXCLUDED.embedding_model_id,embedding_dim=EXCLUDED.embedding_dim,created_at=now();""",
            (tid, tid, doc_id.strip(), (title or "")[:512], int(chunk_index), content,
             json.dumps(metadata, ensure_ascii=False), vec, embedding_model_id, dim))


def search_document_rag_chunks(*, owner_id: str | None = None, tenant_id: str | None = None, doc_id: str,
                               query_embedding: list[float], top_k: int, embedding_model_id: str) -> list[DocumentRagHit]:
    if not memory_db_enabled() or not query_embedding or not (doc_id or "").strip():
        return []
    tid = _resolve_rags_tenant(tenant_id=tenant_id, owner_id=owner_id)
    dim = len(query_embedding)
    ensure_document_rag_schema(embedding_dim=dim)
    k = max(1, min(32, int(top_k)))
    vec = _vector_literal(query_embedding)
    mid = (embedding_model_id or "").strip()
    out: list[DocumentRagHit] = []
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT chunk_index, content, title, (1.0-(embedding<=>%s::vector)) AS score FROM document_rag_chunks
               WHERE tenant_id=%s AND doc_id=%s AND embedding_model_id=%s ORDER BY embedding<=>%s::vector ASC LIMIT %s;""",
            (vec, tid, doc_id.strip(), mid, vec, k))
        for r in cur.fetchall() or []:
            out.append(DocumentRagHit(chunk_index=int(r[0]), content=str(r[1] or ""), title=str(r[2] or ""), score=float(r[3] or 0.0)))
    return out


def list_document_catalog(*, owner_id: str | None = None, tenant_id: str | None = None) -> list[dict[str, Any]]:
    if not memory_db_enabled():
        return []
    tid = _resolve_rags_tenant(tenant_id=tenant_id, owner_id=owner_id)
    ensure_document_rag_schema()
    out: list[dict[str, Any]] = []
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute("""SELECT doc_id, MAX(title) AS title, COUNT(*)::int AS chunk_count FROM document_rag_chunks WHERE tenant_id=%s GROUP BY doc_id ORDER BY doc_id ASC;""", (tid,))
        for row in cur.fetchall() or []:
            out.append({"doc_id": str(row[0]), "title": str(row[1] or row[0]), "chunk_count": int(row[2] or 0)})
    return out


def count_document_rag_chunks(*, owner_id: str | None = None, tenant_id: str | None = None, doc_id: str | None = None) -> int:
    if not memory_db_enabled():
        return 0
    tid = _resolve_rags_tenant(tenant_id=tenant_id, owner_id=owner_id)
    ensure_document_rag_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        if doc_id and doc_id.strip():
            cur.execute("SELECT COUNT(*) FROM document_rag_chunks WHERE tenant_id=%s AND doc_id=%s;", (tid, doc_id.strip()))
        else:
            cur.execute("SELECT COUNT(*) FROM document_rag_chunks WHERE tenant_id=%s;", (tid,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


# ═══════════════════════════════════════════════════════════════════
# PRODUCT RAG STORE PGVECTOR
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProductRagHit:
    source_key: str
    title: str
    chunk_index: int
    content: str
    score: float
    kind: str


def ensure_product_rag_schema(*, embedding_dim: int | None = None) -> None:
    if not memory_db_enabled():
        return
    dim = int(embedding_dim or AGENT_TOOLS_VECTOR_DIM)
    dim = max(2, dim)
    with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""CREATE TABLE IF NOT EXISTS product_rag_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id TEXT NOT NULL DEFAULT 'default',
            source_key TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'doc', title TEXT NOT NULL DEFAULT '',
            chunk_index INT NOT NULL DEFAULT 0, content TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding vector({dim}), embedding_model_id TEXT NOT NULL, embedding_dim INT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (tenant_id, source_key, chunk_index));""")
        cur.execute("""CREATE INDEX IF NOT EXISTS product_rag_chunks_tenant_kind ON product_rag_chunks (tenant_id, kind);""")
        try:
            cur.execute(f"""CREATE INDEX IF NOT EXISTS product_rag_chunks_ivfflat ON product_rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);""")
        except Exception:
            pass


def delete_product_source(*, tenant_id: str | None, source_key: str) -> int:
    if not memory_db_enabled():
        return 0
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    sk = (source_key or "").strip()
    if not sk:
        return 0
    ensure_product_rag_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM product_rag_chunks WHERE tenant_id=%s AND source_key=%s;", (tid, sk))
        return int(cur.rowcount or 0)


def upsert_product_chunk(*, tenant_id: str | None, source_key: str, kind: str, title: str,
                         chunk_index: int, content: str, metadata: dict[str, Any], embedding: list[float],
                         embedding_model_id: str) -> None:
    if not memory_db_enabled():
        return
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    sk = (source_key or "").strip()
    if not sk:
        return
    dim = len(embedding) or AGENT_TOOLS_VECTOR_DIM
    ensure_product_rag_schema(embedding_dim=dim)
    vec = _vector_literal(embedding)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO product_rag_chunks (tenant_id,source_key,kind,title,chunk_index,content,metadata,embedding,embedding_model_id,embedding_dim)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)
               ON CONFLICT (tenant_id,source_key,chunk_index) DO UPDATE SET
               kind=EXCLUDED.kind,title=EXCLUDED.title,content=EXCLUDED.content,metadata=EXCLUDED.metadata,
               embedding=EXCLUDED.embedding,embedding_model_id=EXCLUDED.embedding_model_id,embedding_dim=EXCLUDED.embedding_dim;""",
            (tid, sk, (kind or "doc")[:32], (title or "")[:512], int(chunk_index), content,
             json.dumps(metadata, ensure_ascii=False), vec, embedding_model_id, dim))


def search_product_rag(*, tenant_id: str | None, query_embedding: list[float], top_k: int,
                       embedding_model_id: str, kinds: tuple[str, ...] | None = None) -> list[ProductRagHit]:
    if not memory_db_enabled() or not query_embedding:
        return []
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    dim = len(query_embedding)
    ensure_product_rag_schema(embedding_dim=dim)
    k = max(1, min(32, int(top_k)))
    vec = _vector_literal(query_embedding)
    mid = (embedding_model_id or "").strip()
    kind_filter = ""
    params: list[Any] = [vec, tid, mid]
    if kinds:
        kind_filter = " AND kind = ANY(%s)"
        params.append(list(kinds))
    params.extend([vec, k])
    out: list[ProductRagHit] = []
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT source_key,title,chunk_index,content,kind,(1.0-(embedding<=>%s::vector)) AS score
                FROM product_rag_chunks WHERE tenant_id=%s AND embedding_model_id=%s {kind_filter}
                ORDER BY embedding<=>%s::vector ASC LIMIT %s;""", params)
        for r in cur.fetchall() or []:
            out.append(ProductRagHit(source_key=str(r[0]), title=str(r[1] or ""), chunk_index=int(r[2]),
                                     content=str(r[3] or ""), kind=str(r[4] or "doc"), score=float(r[5] or 0.0)))
    return out


def search_session_rag(*, tenant_id: str | None, chat_session_id: str, query_embedding: list[float],
                       top_k: int, embedding_model_id: str) -> list[ProductRagHit]:
    if not memory_db_enabled() or not query_embedding:
        return []
    sid = (chat_session_id or "").strip()
    if len(sid) < 8:
        return []
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    dim = len(query_embedding)
    ensure_product_rag_schema(embedding_dim=dim)
    k = max(1, min(32, int(top_k)))
    vec = _vector_literal(query_embedding)
    mid = (embedding_model_id or "").strip()
    out: list[ProductRagHit] = []
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT source_key,title,chunk_index,content,kind,(1.0-(embedding<=>%s::vector)) AS score
               FROM product_rag_chunks WHERE tenant_id=%s AND embedding_model_id=%s
               AND kind='session' AND metadata->>'chat_session_id'=%s
               ORDER BY embedding<=>%s::vector ASC LIMIT %s;""",
            (vec, tid, mid, sid, vec, k))
        for r in cur.fetchall() or []:
            out.append(ProductRagHit(source_key=str(r[0]), title=str(r[1] or ""), chunk_index=int(r[2]),
                                     content=str(r[3] or ""), kind=str(r[4] or "session"), score=float(r[5] or 0.0)))
    return out


def count_product_rag_rows(*, tenant_id: str | None = None, kind: str | None = None) -> int:
    if not memory_db_enabled():
        return 0
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    ensure_product_rag_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        if kind:
            cur.execute("SELECT COUNT(*) FROM product_rag_chunks WHERE tenant_id=%s AND kind=%s;", (tid, kind))
        else:
            cur.execute("SELECT COUNT(*) FROM product_rag_chunks WHERE tenant_id=%s;", (tid,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


# ═══════════════════════════════════════════════════════════════════
# AGENT TOOLS STORE PGVECTOR
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AgentToolHit:
    name: str
    score: float


def ensure_agent_tools_schema(*, embedding_dim: int) -> None:
    if not memory_db_enabled():
        return
    dim = max(2, int(embedding_dim))
    with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""CREATE TABLE IF NOT EXISTS agent_tools_embeddings (
            tenant_id TEXT NOT NULL DEFAULT 'default', name TEXT NOT NULL, description_doc TEXT NOT NULL,
            schema_json JSONB NOT NULL, embedding vector({dim}), embedding_model_id TEXT NOT NULL,
            embedding_dim INT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, name));""")
        try:
            cur.execute(f"""CREATE INDEX IF NOT EXISTS agent_tools_embeddings_ivfflat ON agent_tools_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);""")
        except Exception:
            pass


def count_agent_tools_rows(*, embedding_model_id: str, tenant_id: str | None = None) -> int:
    if not memory_db_enabled():
        return 0
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    ensure_agent_tools_schema(embedding_dim=AGENT_TOOLS_VECTOR_DIM)
    mid = (embedding_model_id or "").strip() or "x"
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM agent_tools_embeddings WHERE tenant_id=%s AND embedding_model_id=%s;", (tid, mid))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def upsert_agent_tool_row(*, name: str, description_doc: str, schema_json: dict[str, Any],
                          embedding: list[float], embedding_model_id: str, tenant_id: str | None = None) -> None:
    if not memory_db_enabled():
        return
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    dim = len(embedding) or AGENT_TOOLS_VECTOR_DIM
    ensure_agent_tools_schema(embedding_dim=dim)
    vec = _vector_literal(embedding)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agent_tools_embeddings (tenant_id,name,description_doc,schema_json,embedding,embedding_model_id,embedding_dim,updated_at)
               VALUES (%s,%s,%s,%s,%s::vector,%s,%s,now())
               ON CONFLICT (tenant_id,name) DO UPDATE SET description_doc=EXCLUDED.description_doc,
               schema_json=EXCLUDED.schema_json,embedding=EXCLUDED.embedding,
               embedding_model_id=EXCLUDED.embedding_model_id,embedding_dim=EXCLUDED.embedding_dim,updated_at=now();""",
            (tid, name.strip(), description_doc.strip(), json.dumps(schema_json, ensure_ascii=False), vec, embedding_model_id, dim))


def search_agent_tools(*, query_embedding: list[float], top_k: int, embedding_model_id: str,
                       tenant_id: str | None = None) -> list[AgentToolHit]:
    if not memory_db_enabled() or not query_embedding:
        return []
    tid = _resolve_rags_tenant(tenant_id=tenant_id)
    dim = len(query_embedding) or AGENT_TOOLS_VECTOR_DIM
    ensure_agent_tools_schema(embedding_dim=dim)
    k = max(1, min(64, int(top_k)))
    vec = _vector_literal(query_embedding)
    mid = (embedding_model_id or "").strip()
    out: list[AgentToolHit] = []
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, (1.0-(embedding<=>%s::vector)) AS score FROM agent_tools_embeddings WHERE tenant_id=%s AND embedding_model_id=%s ORDER BY embedding<=>%s::vector ASC LIMIT %s;",
            (vec, tid, mid, vec, k))
        for r in cur.fetchall() or []:
            out.append(AgentToolHit(name=str(r[0]), score=float(r[1] or 0.0)))
    return out


# ═══════════════════════════════════════════════════════════════════
# MEMORY STORE PGVECTOR
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MemoryItem:
    id: str
    namespace: str
    kind: str
    content: str
    tags: list[str]
    score: float
    created_at: str
    embedding_model_id: str
    embedding_dim: int


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def embed_local_hash(text: str, *, dim: int = 256) -> list[float]:
    if dim <= 0:
        return []
    vec = [0.0] * dim
    for tok in (text or "").lower().split():
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16], 16)
        idx = h % dim
        sign = -1.0 if (h >> 63) & 1 else 1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def ensure_memory_schema(*, embedding_dim: int = 256) -> None:
    if not memory_db_enabled():
        return
    dim = max(1, min(4096, int(embedding_dim or 256)))
    with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""CREATE TABLE IF NOT EXISTS memory_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id TEXT NOT NULL DEFAULT 'default',
            owner_id TEXT NOT NULL DEFAULT 'default', namespace TEXT NOT NULL, kind TEXT NOT NULL,
            content TEXT NOT NULL, content_hash TEXT NOT NULL, tags TEXT[] NOT NULL DEFAULT '{{}}',
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb, score_boost DOUBLE PRECISION NOT NULL DEFAULT 0,
            embedding vector({dim}), embedding_model_id TEXT NOT NULL DEFAULT 'local_hash_v1',
            embedding_dim INT NOT NULL DEFAULT {dim}, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NULL,
            last_accessed_at TIMESTAMPTZ NULL, is_deleted BOOLEAN NOT NULL DEFAULT false);""")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS memory_items_tenant_dedupe ON memory_items (tenant_id,namespace,kind,content_hash);""")
        cur.execute("""CREATE INDEX IF NOT EXISTS memory_items_tenant_ns_created ON memory_items (tenant_id,namespace,created_at DESC) WHERE is_deleted=false;""")
        try:
            cur.execute(f"""CREATE INDEX IF NOT EXISTS memory_items_embedding_ivfflat ON memory_items USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50) WHERE is_deleted=false;""")
        except Exception:
            pass


def upsert_memory_item(*, namespace: str, kind: str, content: str, tags: list[str] | None,
                       request_id: str, embedding: list[float], embedding_model_id: str,
                       owner_id: str | None = None, tenant_id: str | None = None,
                       metadata: dict[str, Any] | None = None) -> str | None:
    if not memory_db_enabled():
        return None
    tid = _resolve_rags_tenant(tenant_id=tenant_id, owner_id=owner_id)
    ensure_memory_schema(embedding_dim=len(embedding) or 256)
    ns = (namespace or "").strip()[:64] or "project"
    kd = (kind or "").strip()[:64] or "turn_summary"
    body = (content or "").strip()
    if not body:
        return None
    ch = _sha256(body)
    md = dict(metadata or {})
    md.setdefault("request_id", request_id)
    md.setdefault("source", "orchestrator")
    md.setdefault("ts_unix", int(time.time()))
    vec = _vector_literal(embedding)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memory_items (tenant_id,owner_id,namespace,kind,content,content_hash,tags,metadata,embedding,embedding_model_id,embedding_dim)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)
               ON CONFLICT (tenant_id,namespace,kind,content_hash) DO UPDATE SET updated_at=now(),last_accessed_at=now(),
               owner_id=EXCLUDED.owner_id,tags=EXCLUDED.tags,metadata=memory_items.metadata||EXCLUDED.metadata,
               embedding=EXCLUDED.embedding,embedding_model_id=EXCLUDED.embedding_model_id,embedding_dim=EXCLUDED.embedding_dim
               RETURNING id::text;""",
            (tid, tid, ns, kd, body, ch, tags or [], json.dumps(md, ensure_ascii=False), vec, embedding_model_id, int(len(embedding) or 0)))
        row = cur.fetchone()
        return str(row[0]) if row else None


def search_memory(*, namespace: str, query_embedding: list[float], top_k: int = 8,
                  owner_id: str | None = None, tenant_id: str | None = None,
                  embedding_model_id: str | None = None) -> list[MemoryItem]:
    if not memory_db_enabled():
        return []
    tid = _resolve_rags_tenant(tenant_id=tenant_id, owner_id=owner_id)
    ensure_memory_schema(embedding_dim=len(query_embedding) or 256)
    ns = (namespace or "").strip()[:64] or "project"
    k = max(1, min(20, int(top_k)))
    vec = _vector_literal(query_embedding)
    where_extra = ""
    params: list[Any] = [vec, tid, ns]
    if embedding_model_id:
        where_extra = " AND embedding_model_id = %s"
        params.append(embedding_model_id)
    params.extend([vec, k])
    out: list[MemoryItem] = []
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT id::text,namespace,kind,content,tags,(1.0-(embedding<=>%s::vector))+score_boost AS score,
                created_at::text,embedding_model_id,embedding_dim FROM memory_items
                WHERE tenant_id=%s AND namespace=%s AND is_deleted=false
                AND (expires_at IS NULL OR expires_at>now()) {where_extra}
                ORDER BY (embedding<=>%s::vector) ASC LIMIT %s;""", params)
        for r in cur.fetchall() or []:
            out.append(MemoryItem(id=str(r[0]), namespace=str(r[1]), kind=str(r[2]), content=str(r[3]),
                                  tags=list(r[4] or []), score=float(r[5] or 0.0), created_at=str(r[6]),
                                  embedding_model_id=str(r[7] or ""), embedding_dim=int(r[8] or 0)))
    return out


# ═══════════════════════════════════════════════════════════════════
# UI DOCUMENT RAG (list + ingest helpers)
# ═══════════════════════════════════════════════════════════════════

_DOC_ID_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,128}$")


def document_rag_ui_available() -> bool:
    return bool(DOCUMENT_RAG_SERVER_ENABLED and not CENTRAL_FOCUS_MODE and memory_db_enabled())


def _validate_doc_id(doc_id: str) -> str:
    s = (doc_id or "").strip()
    if not _DOC_ID_RE.match(s):
        raise ValueError("doc_id_invalid")
    return s


def list_documents_for_ui() -> list[dict[str, Any]]:
    if not document_rag_ui_available():
        return []
    return list_document_catalog(tenant_id=resolve_pg_tenant_id())


def ingest_document_bytes(*, doc_id: str, title: str, filename: str, raw: bytes) -> dict[str, Any]:
    if not document_rag_ui_available():
        raise RuntimeError("document_rag_unavailable")
    did = _validate_doc_id(doc_id)
    text, meta = extract_plaintext_from_bytes(raw, filename=filename, max_bytes=DOCUMENT_RAG_MAX_DOC_BYTES)
    chunks = chunk_plaintext(text, max_chunk_chars=DOCUMENT_RAG_CHUNK_CHARS, overlap=DOCUMENT_RAG_CHUNK_OVERLAP,
                             max_chunks=DOCUMENT_RAG_MAX_CHUNKS_PER_DOC)
    if not chunks:
        raise ValueError("no_chunks_after_extract")
    tid = resolve_pg_tenant_id()
    deleted = delete_document_chunks(tenant_id=tid, doc_id=did)
    doc_title = (title or meta.get("source_path") or did)[:512]
    from app.context import get_embedding_service

    for i, body in enumerate(chunks):
        vec, mid = get_embedding_service().embed_tools(body)
        upsert_document_chunk(tenant_id=tid, doc_id=did, title=doc_title, chunk_index=i, content=body,
                              metadata={**meta, "filename": filename, "chunk_of": len(chunks)}, embedding=vec, embedding_model_id=mid)
    return {"ok": True, "doc_id": did, "chunk_count": len(chunks), "replaced_previous_chunks": deleted}


# ═══════════════════════════════════════════════════════════════════
# DOCUMENT RAG (search)
# ═══════════════════════════════════════════════════════════════════


def search_document_context(*, doc_id: str, query: str, tenant_id: str | None = None,
                            top_k: int | None = None) -> tuple[list[DocumentRagHit], dict[str, Any]]:
    tid = tenant_id or resolve_pg_tenant_id()
    meta: dict[str, Any] = {"enabled": bool(cfg.DOCUMENT_RAG_SERVER_ENABLED), "tenant_id": tid,
                            "doc_id": (doc_id or "").strip(), "hit_count": 0, "embedding_model_id": None}
    if not cfg.DOCUMENT_RAG_SERVER_ENABLED or not meta["doc_id"]:
        return [], meta
    k = top_k if top_k is not None else cfg.DOCUMENT_RAG_TOP_K
    try:
        from app.context import get_embedding_service

        vec, mid = get_embedding_service().embed_tools(query or "")
        meta["embedding_model_id"] = mid
        hits = search_document_rag_chunks(tenant_id=tid, doc_id=meta["doc_id"], query_embedding=vec, top_k=k, embedding_model_id=mid)
        meta["hit_count"] = len(hits)
        meta["indexed_chunks"] = count_document_rag_chunks(tenant_id=tid, doc_id=meta["doc_id"])
        return hits, meta
    except Exception as exc:
        meta["error"] = str(exc)[:200]
        return [], meta


# ═══════════════════════════════════════════════════════════════════
# SESSION RAG
# ═══════════════════════════════════════════════════════════════════


def build_session_rag_system_message(hits: list[ProductRagHit], *, chat_session_id: str, max_chars: int) -> dict[str, str] | None:
    if not hits:
        return None
    lines = ["[CONTEXT_RETRIEVED — session namespace; prior turns in this chat only]", f"chat_session_id: {chat_session_id}"]
    used = len(lines[0])
    for h in hits:
        block = f"\n--- fact (score={h.score:.3f}) ---\n{h.content.strip()}"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    body = "\n".join(lines).strip()
    if len(body) < 32:
        return None
    return {"role": "system", "content": body}


def search_session_context(query: str, *, chat_session_id: str, tenant_id: str | None = None,
                           top_k: int | None = None) -> tuple[list[ProductRagHit], dict[str, Any]]:
    sid = (chat_session_id or "").strip()
    tid = tenant_id or resolve_pg_tenant_id()
    meta: dict[str, Any] = {"enabled": bool(cfg.CENTRAL_SESSION_RAG_ENABLED), "tenant_id": tid,
                            "chat_session_id": sid, "hit_count": 0, "embedding_model_id": None}
    if not cfg.CENTRAL_SESSION_RAG_ENABLED or len(sid) < 8:
        return [], meta
    k = top_k if top_k is not None else cfg.CENTRAL_SESSION_RAG_TOP_K
    try:
        from app.context import get_embedding_service

        vec, mid = get_embedding_service().embed_tools(query or "")
        meta["embedding_model_id"] = mid
        hits = search_session_rag(tenant_id=tid, chat_session_id=sid, query_embedding=vec, top_k=k, embedding_model_id=mid)
        meta["hit_count"] = len(hits)
        meta["indexed_rows"] = count_product_rag_rows(tenant_id=tid, kind="session")
        return hits, meta
    except Exception as exc:
        meta["error"] = str(exc)[:200]
        return [], meta


def ingest_session_facts(*, chat_session_id: str, facts: list[str], tenant_id: str | None = None) -> int:
    if not cfg.CENTRAL_SESSION_RAG_ENABLED or cfg.CENTRAL_FOCUS_MODE:
        return 0
    sid = (chat_session_id or "").strip()
    if len(sid) < 8:
        return 0
    cleaned = [str(f).strip() for f in facts if str(f).strip()]
    if not cleaned:
        return 0
    cap = max(1, min(8, cfg.CENTRAL_SESSION_RAG_MAX_FACTS_PER_TURN))
    cleaned = cleaned[:cap]
    tid = tenant_id or resolve_pg_tenant_id()
    from app.context import get_embedding_service

    emb = get_embedding_service()
    turn_id = uuid.uuid4().hex[:12]
    written = 0
    for i, fact in enumerate(cleaned):
        vec, mid = emb.embed_tools(fact)
        source_key = f"session:{sid}:turn:{turn_id}:{i}"
        upsert_product_chunk(tenant_id=tid, source_key=source_key, kind="session", title=f"session:{sid}",
                             chunk_index=0, content=fact, metadata={"chat_session_id": sid, "turn_id": turn_id, "fact_index": i},
                             embedding=vec, embedding_model_id=mid)
        written += 1
    return written


# ═══════════════════════════════════════════════════════════════════
# SESSION RAG WORKER
# ═══════════════════════════════════════════════════════════════════


def extract_session_facts_heuristic(*, user_text: str, assistant_text: str) -> list[str]:
    u = (user_text or "").strip()
    a = (assistant_text or "").strip()
    if not u:
        return []
    cap = max(1, cfg.CENTRAL_SESSION_RAG_MAX_FACTS_PER_TURN)
    facts: list[str] = []
    facts.append(f"User: {u}" if len(u) <= 500 else f"User (excerpt): {u[:500]}…")
    if a:
        facts.append(f"Assistant: {a}" if len(a) <= 700 else f"Assistant (excerpt): {a[:700]}…")
    return facts[:cap]


def extract_session_facts_llm(*, user_text: str, assistant_text: str) -> list[str]:
    cap = max(1, cfg.CENTRAL_SESSION_RAG_MAX_FACTS_PER_TURN)
    prompt = build_session_facts_extract_prompt(user_text=user_text, assistant_text=assistant_text, max_facts=cap)
    prefs = load_preferences()
    pub = get_model_router_public_config()
    prof, mo = resolve_aux_llm_call_params(prefs=prefs, router_public=pub)
    raw = call_llm(prompt, history=[], profile=prof, model_override=mo, allowlist_mode="modality")
    parsed = _parse_fact_bullets(raw, max_facts=cap)
    return parsed if parsed else extract_session_facts_heuristic(user_text=user_text, assistant_text=assistant_text)


def ingest_session_turn_facts(*, chat_session_id: str, user_text: str, assistant_text: str,
                              tenant_id: str | None = None) -> int:
    if cfg.CENTRAL_FOCUS_MODE or not cfg.CENTRAL_SESSION_RAG_ENABLED:
        return 0
    if not (assistant_text or "").strip():
        return 0
    try:
        if cfg.CENTRAL_SESSION_RAG_USE_LLM_EXTRACT:
            facts = extract_session_facts_llm(user_text=user_text, assistant_text=assistant_text)
        else:
            facts = extract_session_facts_heuristic(user_text=user_text, assistant_text=assistant_text)
        return ingest_session_facts(chat_session_id=chat_session_id, facts=facts,
                                    tenant_id=tenant_id or resolve_pg_tenant_id())
    except Exception as exc:
        _log.debug("session_rag_ingest_failed session=%s err=%s", chat_session_id, exc)
        return 0


# ═══════════════════════════════════════════════════════════════════
# PRODUCT RAG
# ═══════════════════════════════════════════════════════════════════


def _parse_always_include(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def build_product_rag_system_message(hits: list[ProductRagHit], *, max_chars: int) -> dict[str, str] | None:
    if not hits:
        return None
    lines = ["[CONTEXT_RETRIEVED — product namespace]"]
    used = len(lines[0])
    for h in hits:
        block = f"\n--- {h.source_key} (score={h.score:.3f}) ---\n{h.content.strip()}"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    body = "\n".join(lines).strip()
    if len(body) < 20:
        return None
    return {"role": "system", "content": body}


def search_product_context(query: str, *, tenant_id: str | None = None,
                           top_k: int | None = None) -> tuple[list[ProductRagHit], dict[str, Any]]:
    tid = tenant_id or resolve_pg_tenant_id()
    meta: dict[str, Any] = {"enabled": bool(cfg.CENTRAL_PRODUCT_RAG_ENABLED), "tenant_id": tid, "hit_count": 0, "embedding_model_id": None}
    if not cfg.CENTRAL_PRODUCT_RAG_ENABLED:
        return [], meta
    k = top_k if top_k is not None else cfg.CENTRAL_PRODUCT_RAG_TOP_K
    try:
        from app.context import get_embedding_service

        vec, mid = get_embedding_service().embed_tools(query or "")
        meta["embedding_model_id"] = mid
        hits = search_product_rag(tenant_id=tid, query_embedding=vec, top_k=k, embedding_model_id=mid)
        meta["hit_count"] = len(hits)
        meta["indexed_rows"] = count_product_rag_rows(tenant_id=tid)
        return hits, meta
    except Exception as exc:
        meta["error"] = str(exc)[:200]
        return [], meta


def tool_names_from_product_hits(hits: list[ProductRagHit]) -> list[str]:
    allowed = frozenset(list_registered_tool_names_for_llm_prompt())
    names: list[str] = []
    seen: set[str] = set()
    for h in hits:
        if h.kind not in ("tool", "client_tool"):
            continue
        sk = h.source_key
        name = sk[5:].strip() if sk.startswith("tool:") else sk[12:].strip() if sk.startswith("client_tool:") else sk.strip()
        if name in allowed and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def resolve_tool_names_product_rag(*, user_text: str | None, tenant_id: str | None = None) -> tuple[list[str], dict[str, Any]]:
    all_names = list_registered_tool_names_for_llm_prompt()
    allowed = frozenset(all_names)
    always = [x for x in _parse_always_include(cfg.AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW) if x in allowed]
    info: dict[str, Any] = {"enabled": bool(cfg.CENTRAL_PRODUCT_RAG_ENABLED), "mode": "product_rag",
                            "tools_only_via_retrieval": bool(cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL), "count": 0}
    if not cfg.CENTRAL_PRODUCT_RAG_ENABLED:
        out = list(always) if cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL else all_names
        info["mode"] = "always_include_only" if cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL else "full_catalog"
        info["count"] = len(out)
        return out, info
    hits, search_meta = search_product_context(user_text or "", tenant_id=tenant_id, top_k=cfg.CENTRAL_PRODUCT_RAG_TOP_K)
    info.update(search_meta)
    ordered = tool_names_from_product_hits(hits)
    seen = set(ordered)
    for name in always:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    if cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL:
        info["mode"] = "product_rag_retrieval_only"
        info["count"] = len(ordered)
        info["ordered_sample"] = ordered[:12]
        return ordered, info
    need = min(max(1, cfg.AGENT_TOOLS_RAG_MIN_TOOLS), len(all_names))
    if len(ordered) < need:
        info["mode"] = "degraded_too_few_hits"
        info["count"] = len(all_names)
        return all_names, info
    info["count"] = len(ordered)
    info["ordered_sample"] = ordered[:12]
    return ordered, info


# ═══════════════════════════════════════════════════════════════════
# AGENT TOOLS RAG
# ═══════════════════════════════════════════════════════════════════


def resolve_registered_tool_names_for_prompt(*, user_text: str | None) -> tuple[list[str], dict[str, Any]]:
    if cfg.CENTRAL_PRODUCT_RAG_ENABLED:
        return resolve_tool_names_product_rag(user_text=user_text)

    all_names = list_registered_tool_names_for_llm_prompt()
    allowed = frozenset(all_names)
    rag_effective = bool(cfg.AGENT_TOOLS_RAG_ENABLED) and (not cfg.CENTRAL_FOCUS_MODE)
    base_info: dict[str, Any] = {"enabled": rag_effective, "mode": "full_catalog", "count": len(all_names),
                                  "embedding_model_id": None, "top_k": cfg.AGENT_TOOLS_RAG_TOP_K}
    if cfg.CENTRAL_FOCUS_MODE and cfg.AGENT_TOOLS_RAG_ENABLED:
        base_info["suppressed_by"] = "central_focus_mode"
    if not rag_effective:
        return all_names, base_info

    t0 = time.perf_counter()
    degraded: str | None = None
    info = dict(base_info)
    info["mode"] = "rag"

    try:
        vec, mid = embed_agent_tools_text(user_text or "")
        info["embedding_model_id"] = mid
        n_rows = count_agent_tools_rows(embedding_model_id=mid)
        if n_rows < 1:
            degraded = "empty_store"
            info["mode"] = "degraded_empty_store"
            if cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL:
                out = filter_tool_names_for_llm([x for x in _parse_always_include(cfg.AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW) if x in allowed])
                info["mode"] = "always_include_only"
            else:
                out = filter_tool_names_for_llm(all_names)
            info["count"] = len(out)
            record_agent_tools_rag_select(seconds=time.perf_counter() - t0, n_tools=len(out), degraded_reason=degraded)
            return out, info
        always = [x for x in _parse_always_include(cfg.AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW) if x in allowed]
        hits = search_agent_tools(query_embedding=vec, top_k=cfg.AGENT_TOOLS_RAG_TOP_K, embedding_model_id=mid)
        ordered: list[str] = []
        seen: set[str] = set()
        for h in hits:
            if h.name in allowed and h.name not in seen:
                ordered.append(h.name)
                seen.add(h.name)
        for name in always:
            if name in allowed and name not in seen:
                ordered.append(name)
                seen.add(name)
        need = min(max(1, cfg.AGENT_TOOLS_RAG_MIN_TOOLS), len(all_names))
        if len(ordered) < need:
            degraded = "too_few_hits"
            if cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL:
                info["mode"] = "retrieval_only_too_few"
                out = ordered if ordered else always
            else:
                info["mode"] = "degraded_too_few_hits"
                out = all_names
        else:
            out = ordered
            info["ordered_sample"] = out[:12]
        out = filter_tool_names_for_llm(out)
        info["count"] = len(out)
        record_agent_tools_rag_select(seconds=time.perf_counter() - t0, n_tools=len(out), degraded_reason=degraded)
        return out, info
    except Exception:
        degraded = "error"
        allowed = frozenset(all_names)
        always = [x for x in _parse_always_include(cfg.AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW) if x in allowed]
        if cfg.CENTRAL_RAG_TOOLS_ONLY_VIA_RETRIEVAL:
            info["mode"] = "always_include_only"
            always_f = filter_tool_names_for_llm(always)
            info["count"] = len(always_f)
            record_agent_tools_rag_select(seconds=time.perf_counter() - t0, n_tools=len(always_f), degraded_reason=degraded)
            return always_f, info
        info["mode"] = "degraded_error"
        all_f = filter_tool_names_for_llm(all_names)
        info["count"] = len(all_f)
        record_agent_tools_rag_select(seconds=time.perf_counter() - t0, n_tools=len(all_f), degraded_reason=degraded)
        return all_f, info


# ═══════════════════════════════════════════════════════════════════
# MEMORY CONTEXT (OC-14 — metrics snapshot)
# ═══════════════════════════════════════════════════════════════════


def _rag_namespace_counts() -> dict[str, Any]:
    if CENTRAL_FOCUS_MODE or not memory_db_enabled():
        return {"product": {"enabled": False, "indexed_rows": None}, "document": {"enabled": False, "indexed_chunks": None},
                "session": {"enabled": False, "indexed_rows": None}}
    tid = resolve_pg_tenant_id()
    out: dict[str, Any] = {"tenant_id": tid, "product": {"enabled": CENTRAL_PRODUCT_RAG_ENABLED, "indexed_rows": None},
                           "document": {"enabled": DOCUMENT_RAG_SERVER_ENABLED, "indexed_chunks": None},
                           "session": {"enabled": CENTRAL_SESSION_RAG_ENABLED, "indexed_rows": None}}
    try:
        if CENTRAL_PRODUCT_RAG_ENABLED:
            out["product"]["indexed_rows"] = count_product_rag_rows(tenant_id=tid)
        if DOCUMENT_RAG_SERVER_ENABLED:
            out["document"]["indexed_chunks"] = count_document_rag_chunks(tenant_id=tid)
        if CENTRAL_SESSION_RAG_ENABLED:
            out["session"]["indexed_rows"] = count_product_rag_rows(tenant_id=tid, kind="session")
    except Exception:
        out["counts_error"] = True
    return out


def build_ui_memory_context() -> dict[str, Any]:
    prefs = load_preferences()
    playbook_on = bool(PLAYBOOK_FEATURE_ENABLED) and (not CENTRAL_FOCUS_MODE)
    playbook_count = len(list_playbook_entries_meta()) if playbook_on else 0
    rag_ns = _rag_namespace_counts()
    from app.context import load_context_settings

    ctx_settings = load_context_settings()
    compaction_snapshot: dict[str, Any] = {"token_trigger_enabled": not CENTRAL_FOCUS_MODE,
        "compact_threshold_tokens": ctx_settings.compact_threshold_tokens,
        "context_window_cap": ctx_settings.context_window_cap, "min_verbatim_tokens": CENTRAL_COMPACT_MIN_VERBATIM_TOKENS,
        "async_jobs_enabled": CENTRAL_COMPACTION_ASYNC_ENABLED, "legacy_summary_file": COMPACT_SUMMARY_STORE_PATH,
        "session_summaries_in_db": memory_db_enabled()}
    if memory_db_enabled():
        try:
            compaction_snapshot["indexed_summaries"] = count_session_summaries(tenant_id=resolve_pg_tenant_id())
        except Exception:
            compaction_snapshot["indexed_summaries"] = None
    return {"schema_version": 2, "documentation_pt": "Ver docs/guides/ambientacao-pre-pos-injecao.md",
        "central_focus_mode": bool(CENTRAL_FOCUS_MODE),
        "memory_db": {"enabled": False if CENTRAL_FOCUS_MODE else bool(MEMORY_ENABLED),
                      "db_configured": False if CENTRAL_FOCUS_MODE else bool(MEMORY_DB_URL.strip()),
                      "top_k": MEMORY_TOP_K, "max_block_chars": MEMORY_MAX_BLOCK_CHARS},
        "defaults_from_preferences": {"inference_destination": str(prefs.get("inference_destination") or "local"),
            "llm_model_id": str(prefs.get("llm_model_id") or ""),
            "aux_llm_destination": str(prefs.get("aux_llm_destination") or "local"),
            "aux_llm_model_id": str(prefs.get("aux_llm_model_id") or ""),
            "embedding_destination": str(prefs.get("embedding_destination") or "local"),
            "embedding_model_id": str(prefs.get("embedding_model_id") or ""),
            "default_include_long_session_memory": bool(prefs.get("default_include_long_session_memory")),
            "default_include_memory_recall": bool(prefs.get("default_include_memory_recall", False)),
            "default_include_playbook": bool(prefs.get("default_include_playbook")),
            "default_include_host_context": bool(prefs.get("default_include_host_context")),
            "default_include_capability_digest": bool(prefs.get("default_include_capability_digest")),
            "default_use_agent_tools": bool(prefs.get("default_use_agent_tools")),
            "verbosity": str(prefs.get("verbosity") or "normal")},
        "playbook": {"feature_enabled": playbook_on, "entry_count": playbook_count,
                     "governed_promotion_candidates_enabled": bool(PLAYBOOK_GOVERNED_PROMOTION_CANDIDATES_ENABLED) and playbook_on},
        "session": {"session_max_messages_no_long_memory": SESSION_MAX_MESSAGES_NO_LONG_MEMORY},
        "compaction": compaction_snapshot,
        "embeddings_and_vector_rag": {"in_use": not CENTRAL_FOCUS_MODE,
            "note_pt": "Modo Central: sem embeddings nem RAG vectorial." if CENTRAL_FOCUS_MODE else "RAG/recall vectorial só quando activo."},
        "rag_namespaces": {**rag_ns, "request_flags_pt": {
            "include_document_rag": "POST assistant: excertos de document_rag_doc_id",
            "document_rag_doc_id": "id lógico do documento",
            "include_session_rag": "POST assistant: recall namespace session (requer chat_session_id)",
            "chat_session_id": "histórico servidor; pós-turno indexa factos em session"},
            "top_k": {"document": DOCUMENT_RAG_TOP_K, "session": CENTRAL_SESSION_RAG_TOP_K}},
        "chat_sessions": {"server_store_enabled": CHAT_SESSIONS_ENABLED}, "note_pt": (
            "Modo Central: sem recall/playbook/embeddings." if CENTRAL_FOCUS_MODE
            else "Este resumo não inclui conteúdo de mensagens nem texto bruto de recall/snippets.")}


# ═══════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════

router_rag = APIRouter()


def _document_rag_public_snapshot() -> dict[str, Any]:
    if CENTRAL_FOCUS_MODE:
        return {"server_enabled": False, "suppressed_by": "central_focus_mode", "top_k": DOCUMENT_RAG_TOP_K,
                "chunk_chars": DOCUMENT_RAG_CHUNK_CHARS, "chunk_overlap": DOCUMENT_RAG_CHUNK_OVERLAP,
                "max_doc_bytes": DOCUMENT_RAG_MAX_DOC_BYTES, "max_chunks_per_doc": DOCUMENT_RAG_MAX_CHUNKS_PER_DOC,
                "prompt_max_chars": DOCUMENT_RAG_PROMPT_MAX_CHARS, "indexed_chunks": None}
    snap: dict[str, Any] = {"server_enabled": DOCUMENT_RAG_SERVER_ENABLED, "top_k": DOCUMENT_RAG_TOP_K,
                            "chunk_chars": DOCUMENT_RAG_CHUNK_CHARS, "chunk_overlap": DOCUMENT_RAG_CHUNK_OVERLAP,
                            "max_doc_bytes": DOCUMENT_RAG_MAX_DOC_BYTES,
                            "max_chunks_per_doc": DOCUMENT_RAG_MAX_CHUNKS_PER_DOC,
                            "prompt_max_chars": DOCUMENT_RAG_PROMPT_MAX_CHARS, "indexed_chunks": None}
    try:
        snap["indexed_chunks"] = count_document_rag_chunks(tenant_id=resolve_pg_tenant_id())
    except Exception:
        snap["indexed_chunks"] = None
        snap["indexed_chunks_error"] = True
    snap["tenant_scoped"] = True
    return snap


def _session_rag_public_snapshot() -> dict[str, Any]:
    if CENTRAL_FOCUS_MODE:
        return {"server_enabled": False, "suppressed_by": "central_focus_mode", "top_k": CENTRAL_SESSION_RAG_TOP_K,
                "prompt_max_chars": CENTRAL_SESSION_RAG_PROMPT_MAX_CHARS, "indexed_rows": None}
    snap: dict[str, Any] = {"server_enabled": CENTRAL_SESSION_RAG_ENABLED, "top_k": CENTRAL_SESSION_RAG_TOP_K,
                            "prompt_max_chars": CENTRAL_SESSION_RAG_PROMPT_MAX_CHARS,
                            "namespace": "session", "indexed_rows": None}
    try:
        snap["indexed_rows"] = count_product_rag_rows(tenant_id=resolve_pg_tenant_id(), kind="session")
    except Exception:
        snap["indexed_rows"] = None
        snap["indexed_rows_error"] = True
    return snap


def _agent_tools_rag_public_snapshot() -> dict[str, Any]:
    if CENTRAL_FOCUS_MODE:
        return {"enabled": False, "suppressed_by": "central_focus_mode", "top_k": AGENT_TOOLS_RAG_TOP_K,
                "min_tools": AGENT_TOOLS_RAG_MIN_TOOLS, "embedding_backend": AGENT_TOOLS_RAG_EMBEDDING_BACKEND,
                "always_include_raw": AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW, "active_embedding_model_id": None, "indexed_rows": None}
    mid = active_agent_tools_embedding_model_id()
    snap: dict[str, Any] = {"enabled": AGENT_TOOLS_RAG_ENABLED, "top_k": AGENT_TOOLS_RAG_TOP_K,
                            "min_tools": AGENT_TOOLS_RAG_MIN_TOOLS,
                            "embedding_backend": AGENT_TOOLS_RAG_EMBEDDING_BACKEND,
                            "always_include_raw": AGENT_TOOLS_RAG_ALWAYS_INCLUDE_RAW,
                            "active_embedding_model_id": mid, "indexed_rows": None}
    try:
        snap["indexed_rows"] = count_agent_tools_rows(embedding_model_id=mid)
    except Exception:
        snap["indexed_rows"] = None
        snap["indexed_rows_error"] = True
    return snap


@router_rag.get("/ui/document-rag", tags=["WidgetMVP"])
def ui_document_rag_list() -> dict[str, Any]:
    enabled = document_rag_ui_available()
    return {"document_rag_enabled": enabled, "items": list_documents_for_ui() if enabled else []}


@router_rag.post("/ui/document-rag/ingest", tags=["WidgetMVP"])
async def ui_document_rag_ingest(doc_id: str = Form(...), file: UploadFile = File(...), title: str = Form("")) -> dict[str, Any]:
    if not document_rag_ui_available():
        raise HTTPException(status_code=503, detail={"type": "about:blank", "title": "Document RAG unavailable", "status": 503, "detail": "document_rag_disabled"})
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="empty_file")
    try:
        return ingest_document_bytes(doc_id=doc_id, title=title, filename=file.filename or "upload", raw=raw)
    except ValueError as exc:
        code = str(exc)
        if code in ("doc_id_invalid", "no_chunks_after_extract"):
            raise HTTPException(status_code=422, detail=code) from exc
        if code.startswith("document_too_large"):
            raise HTTPException(status_code=413, detail=code) from exc
        raise HTTPException(status_code=422, detail=code) from exc
    except RuntimeError as exc:
        if str(exc) == "pypdf_not_installed":
            raise HTTPException(status_code=503, detail="pypdf_not_installed") from exc
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router_rag.get("/ui/memory-context", tags=["OpsDashboard"])
def ui_memory_context() -> dict[str, Any]:
    _central_focus_abort()
    return build_ui_memory_context()
