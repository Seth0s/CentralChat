#!/usr/bin/env python3
"""
F4 B3 — Ingere embeddings do catálogo actual (tool_registry) em agent_tools_embeddings.

Uso (na raiz do serviço orchestrator, com MEMORY_DB_URL acessível):
  AGENT_TOOLS_RAG_EMBEDDING_BACKEND=hash PYTHONPATH=. python scripts/ingest_agent_tools_rag.py

Para MiniLM (CPU por defeito; primeiro arranque pode descarregar o modelo):
  pip install sentence-transformers
  PYTHONPATH=. python scripts/ingest_agent_tools_rag.py

O backend de embedding deve ser o mesmo em ingest e em runtime (env AGENT_TOOLS_RAG_EMBEDDING_BACKEND).
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    import argparse

    from app.agent_tools_embedding import embed_agent_tools_text
    from app.agent_tools_store_pgvector import upsert_agent_tool_row
    from app.config import CENTRAL_DEFAULT_CLIENT_ID
    from app.tool_registry import iter_agent_tool_rag_source_rows

    ap = argparse.ArgumentParser(description="Ingest agent tools into pgvector (per-tenant)")
    ap.add_argument("--tenant-id", default=CENTRAL_DEFAULT_CLIENT_ID)
    args = ap.parse_args()
    tenant_id = (args.tenant_id or CENTRAL_DEFAULT_CLIENT_ID).strip()

    rows = iter_agent_tool_rag_source_rows()
    if not rows:
        print("no tools in registry", file=sys.stderr)
        return 2
    for name, doc, schema in rows:
        vec, mid = embed_agent_tools_text(doc)
        upsert_agent_tool_row(
            name=name,
            description_doc=doc,
            schema_json=schema,
            embedding=vec,
            embedding_model_id=mid,
            tenant_id=tenant_id,
        )
        print(f"ok\t{name}\t{mid}\t{len(vec)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
