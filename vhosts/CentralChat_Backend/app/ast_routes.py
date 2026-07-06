"""AST API routes — semantic codebase queries.

POST /ast/query  — Natural language query over code structure
POST /ast/index  — Index a Python file or directory

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §10 (AST-C)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.ast_parser import parse_file, parse_directory, ParseResult
from app.ast_store import query_ast_nodes, upsert_ast_nodes

logger = logging.getLogger(__name__)

router_ast = APIRouter(prefix="/ast", tags=["AST"])


# ═══════════════════════════════════════════════════════════════
# Request/Response models
# ═══════════════════════════════════════════════════════════════

class AstQueryRequest(BaseModel):
    """Natural language query over code structure."""

    query: str = Field(..., min_length=3, description="Natural language question about the codebase")
    tenant_id: str = Field(default="default")
    file_path: str | None = Field(default=None, description="Optional file path filter")
    node_types: list[str] | None = Field(default=None, description="Filter: module, class, function, method, import")
    top_k: int = Field(default=10, ge=1, le=50)
    expand_imports: bool = Field(default=False, description="Follow internal imports for context")


class AstIndexRequest(BaseModel):
    """Index a Python file or directory."""

    path: str = Field(..., description="Absolute path to .py file or directory")
    tenant_id: str = Field(default="default")
    recursive: bool = Field(default=True, description="If directory, walk recursively")
    max_files: int = Field(default=200, ge=1, le=500)


class AstNodeResponse(BaseModel):
    """Single AST node in query response."""

    node_type: str
    name: str
    qualified_name: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    docstring: str | None = None
    signature: str | None = None
    parent_name: str | None = None
    similarity: float = 0.0


class AstQueryResponse(BaseModel):
    """Response from /ast/query."""

    results: list[AstNodeResponse]
    query: str
    count: int


class AstIndexResponse(BaseModel):
    """Response from /ast/index."""

    files_processed: int
    nodes_indexed: int
    errors: list[str] = []


# ═══════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════

@router_ast.post("/query", response_model=AstQueryResponse)
async def ast_query(req: AstQueryRequest) -> AstQueryResponse:
    """Query code structure using natural language.

    Example queries:
    - "Where is authentication logic?"
    - "Show me all database models"
    - "What functions call send_email?"
    - "Find classes that inherit from BaseModel"
    """
    results = query_ast_nodes(
        query=req.query,
        tenant_id=req.tenant_id,
        file_path=req.file_path,
        node_types=req.node_types,
        top_k=req.top_k,
        expand_imports=req.expand_imports,
    )

    return AstQueryResponse(
        results=[
            AstNodeResponse(
                node_type=r["node_type"],
                name=r["name"],
                qualified_name=r["qualified_name"],
                file_path=r["file_path"],
                line_start=r.get("line_start"),
                line_end=r.get("line_end"),
                docstring=r.get("docstring"),
                signature=r.get("signature"),
                parent_name=r.get("parent_name"),
                similarity=r.get("similarity", 0.0),
            )
            for r in results
        ],
        query=req.query,
        count=len(results),
    )


@router_ast.post("/index", response_model=AstIndexResponse)
async def ast_index(req: AstIndexRequest) -> AstIndexResponse:
    """Index a Python file or directory into AST store."""
    import os
    from pathlib import Path

    path = Path(req.path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    total_nodes = 0
    all_errors: list[str] = []

    if path.is_file():
        result = parse_file(path)
        if result.nodes:
            total_nodes += upsert_ast_nodes(
                result.nodes, tenant_id=req.tenant_id,
            )
        all_errors.extend(result.errors)
        files_count = 1
    elif path.is_dir():
        results = parse_directory(
            path, max_files=req.max_files,
        )
        for result in results:
            if result.nodes:
                total_nodes += upsert_ast_nodes(
                    result.nodes, tenant_id=req.tenant_id,
                )
            all_errors.extend(
                f"{result.file_path}: {e}" for e in result.errors
            )
        files_count = len(results)
    else:
        raise HTTPException(status_code=400, detail="Path is not a file or directory")

    return AstIndexResponse(
        files_processed=files_count,
        nodes_indexed=total_nodes,
        errors=all_errors[:20],  # Cap at 20 errors
    )
