#!/usr/bin/env python3
"""
ADR-017 phase 7 — Ingest client tool schemas into product_rag_chunks (kind=client_tool).

Uso:
  PYTHONPATH=. python scripts/ingest_client_tools_rag.py --tenant-id default
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from app.config import CENTRAL_DEFAULT_CLIENT_ID
    from app.context.embedding_service import get_embedding_service
    from app.product_rag_store_pgvector import delete_product_source, upsert_product_chunk
    from app.tool_registry import iter_client_tool_rag_source_rows

    ap = argparse.ArgumentParser(description="Ingest client_tools namespace RAG")
    ap.add_argument("--tenant-id", default=CENTRAL_DEFAULT_CLIENT_ID)
    args = ap.parse_args()
    tenant = (args.tenant_id or CENTRAL_DEFAULT_CLIENT_ID).strip()
    emb = get_embedding_service()

    for name, doc, _schema in iter_client_tool_rag_source_rows():
        sk = f"client_tool:{name}"
        delete_product_source(tenant_id=tenant, source_key=sk)
        vec, mid = emb.embed_tools(doc)
        upsert_product_chunk(
            tenant_id=tenant,
            source_key=sk,
            kind="client_tool",
            title=name,
            chunk_index=0,
            content=doc,
            metadata={"tool": name, "namespace": "client_tools"},
            embedding=vec,
            embedding_model_id=mid,
        )
        print(f"ok\t{sk}\t{mid}")

    print(f"done\ttenant={tenant}\tcount={len(list(iter_client_tool_rag_source_rows()))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
