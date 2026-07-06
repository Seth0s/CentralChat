#!/usr/bin/env python3
"""
F5 C1 — Ingere um .pdf ou .txt/.md em document_rag_chunks (pgvector).

O backend de embedding deve coincidir com F4 (`AGENT_TOOLS_RAG_EMBEDDING_BACKEND`).

Exemplo:
  PYTHONPATH=. python scripts/ingest_document_rag.py --doc-id central_manual --title "Manual" --file ./docs/guide.pdf
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _validate_doc_id(doc_id: str) -> str:
    s = doc_id.strip()
    if not re.match(r"^[a-zA-Z0-9._:-]{1,128}$", s):
        raise ValueError("doc_id_invalid")
    return s


def main() -> int:
    from app.context.embedding_service import get_embedding_service
    from app.config import (
        DOCUMENT_RAG_CHUNK_CHARS,
        DOCUMENT_RAG_CHUNK_OVERLAP,
        DOCUMENT_RAG_MAX_CHUNKS_PER_DOC,
        DOCUMENT_RAG_MAX_DOC_BYTES,
    )
    from app.document_rag_chunking import chunk_plaintext, extract_plaintext_from_file
    from app.document_rag_store_pgvector import delete_document_chunks, upsert_document_chunk

    ap = argparse.ArgumentParser(description="Ingest document into document_rag_chunks")
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--title", default="")
    from app.config import CENTRAL_DEFAULT_CLIENT_ID

    ap.add_argument("--owner-id", default="", help="legado; usa --tenant-id")
    ap.add_argument("--tenant-id", default=CENTRAL_DEFAULT_CLIENT_ID)
    args = ap.parse_args()
    tenant = (args.tenant_id or args.owner_id or CENTRAL_DEFAULT_CLIENT_ID).strip()
    doc_id = _validate_doc_id(args.doc_id)
    path = os.path.abspath(args.file)
    text, meta = extract_plaintext_from_file(path, max_bytes=DOCUMENT_RAG_MAX_DOC_BYTES)
    chunks = chunk_plaintext(
        text,
        max_chunk_chars=DOCUMENT_RAG_CHUNK_CHARS,
        overlap=DOCUMENT_RAG_CHUNK_OVERLAP,
        max_chunks=DOCUMENT_RAG_MAX_CHUNKS_PER_DOC,
    )
    if not chunks:
        print("no_chunks_after_extract", file=sys.stderr)
        return 3
    deleted = delete_document_chunks(tenant_id=tenant, doc_id=doc_id)
    title = (args.title or meta.get("source_path") or doc_id)[:512]
    for i, body in enumerate(chunks):
        vec, mid = get_embedding_service().embed_tools(body)
        upsert_document_chunk(
            tenant_id=tenant,
            doc_id=doc_id,
            title=title,
            chunk_index=i,
            content=body,
            metadata={**meta, "path": os.path.basename(path), "chunk_of": len(chunks)},
            embedding=vec,
            embedding_model_id=mid,
        )
        print(f"ok\t{doc_id}\t{i}\t{mid}\t{len(vec)}")
    print(f"done\t{doc_id}\tchunks={len(chunks)}\treplaced_previous={deleted}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
