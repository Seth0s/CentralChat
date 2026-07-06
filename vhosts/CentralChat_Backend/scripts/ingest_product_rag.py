#!/usr/bin/env python3
"""
Fase 4 — Ingere pacote Central (core/capabilities) + hints de tools em product_rag_chunks.

Uso:
  PYTHONPATH=. python scripts/ingest_product_rag.py --tenant-id default
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from app.central_product_pack import CENTRAL_CAPABILITIES_URI, CENTRAL_CORE_URI
    from app.config import CENTRAL_DEFAULT_CLIENT_ID
    from app.context.embedding_service import get_embedding_service
    from app.product_rag_store_pgvector import delete_product_source, upsert_product_chunk
    from app.tool_registry import iter_agent_tool_rag_source_rows

    ap = argparse.ArgumentParser(description="Ingest product namespace RAG")
    ap.add_argument("--tenant-id", default=CENTRAL_DEFAULT_CLIENT_ID)
    args = ap.parse_args()
    tenant = (args.tenant_id or CENTRAL_DEFAULT_CLIENT_ID).strip()
    emb = get_embedding_service()

    bundled = _ROOT / "bundled" / "central"
    pairs = [
        (CENTRAL_CORE_URI, "core@v1.md", "doc", "Central core L0"),
        (CENTRAL_CAPABILITIES_URI, "capabilities@v1.md", "doc", "Central capabilities L1"),
    ]
    for source_key, filename, kind, title in pairs:
        path = bundled / filename
        if not path.is_file():
            print(f"skip\t{source_key}\tmissing_file", file=sys.stderr)
            continue
        body = path.read_text(encoding="utf-8").strip()
        delete_product_source(tenant_id=tenant, source_key=source_key)
        vec, mid = emb.embed_tools(body)
        upsert_product_chunk(
            tenant_id=tenant,
            source_key=source_key,
            kind=kind,
            title=title,
            chunk_index=0,
            content=body,
            metadata={"ingest": "bundled/central"},
            embedding=vec,
            embedding_model_id=mid,
        )
        print(f"ok\t{source_key}\t{mid}\t{len(vec)}")

    for name, doc, schema in iter_agent_tool_rag_source_rows():
        sk = f"tool:{name}"
        delete_product_source(tenant_id=tenant, source_key=sk)
        hint = doc.strip()
        if schema:
            hint += "\n(schema_json present in registry; not duplicated in RAG chunk)"
        vec, mid = emb.embed_tools(hint)
        upsert_product_chunk(
            tenant_id=tenant,
            source_key=sk,
            kind="tool",
            title=name,
            chunk_index=0,
            content=hint,
            metadata={"tool": name},
            embedding=vec,
            embedding_model_id=mid,
        )
        print(f"ok\t{sk}\t{mid}")

    print(f"done\ttenant={tenant}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
