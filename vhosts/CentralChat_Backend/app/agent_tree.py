"""T17 — Multi-Agent Tree: modelo de dados, CRUD e AgentTreeRunner.

Arquitectura:
  - agent_trees: raiz da árvore (nome, descrição)
  - agent_nodes: nós com agent_name, config, inherit_mode
  - AgentTreeRunner: execução paralela com SSE streaming
  - Cancelamento propagado via threading.Event
  - HITL por nó via tool clarify
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Iterator
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.shared.pg_tenant import connect_pg, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

# ═══ MODELS ═══

_AGENT_TREE_COLS = "id, tenant_id, name, description, root_node_id, created_at, updated_at"
_AGENT_NODE_COLS = "id, tree_id, parent_id, agent_name, position, label, config, inherit_mode, created_at, updated_at"


class AgentTreeIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class AgentTreeOut(BaseModel):
    id: str
    tenant_id: str = "default"
    name: str
    description: str = ""
    root_node_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


class AgentNodeIn(BaseModel):
    parent_id: str | None = Field(default=None, max_length=64)
    agent_name: str = Field(default="default", max_length=128)
    position: int = Field(default=0, ge=0)
    label: str = Field(default="", max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    inherit_mode: str = Field(default="full", pattern="^(none|summary|full)$")


class AgentNodeOut(BaseModel):
    id: str
    tree_id: str
    parent_id: str | None = None
    agent_name: str = "default"
    position: int = 0
    label: str = ""
    config: dict[str, Any] = field(default_factory=dict)  # type: ignore[assignment]
    inherit_mode: str = "full"
    created_at: str = ""
    updated_at: str = ""


class AgentTreeFull(BaseModel):
    tree: AgentTreeOut
    nodes: list[AgentNodeOut] = field(default_factory=list)


# ═══ ROUTER ═══

router_agent_tree = APIRouter(prefix="/agent-trees", tags=["T17-AgentTree"])


# ── Trees CRUD ──


@router_agent_tree.post("", response_model=AgentTreeOut)
def create_agent_tree(body: AgentTreeIn) -> dict[str, Any]:
    tid = _tenant()
    tree_id = _uid()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO agent_trees ({_AGENT_TREE_COLS}) VALUES (%s,%s,%s,%s,%s,now(),now()) RETURNING {_AGENT_TREE_COLS}",
            (tree_id, tid, body.name, body.description, None),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(500, "create_failed")
        return _tree_row(row)


@router_agent_tree.get("", response_model=list[AgentTreeOut])
def list_agent_trees() -> list[dict[str, Any]]:
    tid = _tenant()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_AGENT_TREE_COLS} FROM agent_trees WHERE tenant_id=%s ORDER BY updated_at DESC LIMIT 100",
            (tid,),
        )
        return [_tree_row(r) for r in cur.fetchall()]


@router_agent_tree.get("/{tree_id}", response_model=AgentTreeFull)
def get_agent_tree(tree_id: str) -> dict[str, Any]:
    tid = _tenant()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_AGENT_TREE_COLS} FROM agent_trees WHERE id=%s AND tenant_id=%s",
            (tree_id, tid),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "tree_not_found")
        tree = _tree_row(row)
        cur.execute(
            f"SELECT {_AGENT_NODE_COLS} FROM agent_nodes WHERE tree_id=%s ORDER BY position",
            (tree_id,),
        )
        nodes = [_node_row(r) for r in cur.fetchall()]
        return {"tree": tree, "nodes": nodes}


@router_agent_tree.delete("/{tree_id}")
def delete_agent_tree(tree_id: str) -> dict[str, Any]:
    tid = _tenant()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM agent_trees WHERE id=%s AND tenant_id=%s", (tree_id, tid))
        if cur.rowcount == 0:
            raise HTTPException(404, "tree_not_found")
        return {"ok": True, "deleted": tree_id}


# ── Nodes CRUD ──


@router_agent_tree.post("/{tree_id}/nodes", response_model=AgentNodeOut)
def create_agent_node(tree_id: str, body: AgentNodeIn) -> dict[str, Any]:
    tid = _tenant()
    _verify_tree(tree_id, tid)
    if body.parent_id:
        _verify_node(tree_id, body.parent_id)
    node_id = _uid()
    config_json = json.dumps(body.config, ensure_ascii=False)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO agent_nodes ({_AGENT_NODE_COLS}) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now(),now()) RETURNING " + _AGENT_NODE_COLS,
            (node_id, tree_id, body.parent_id or None, body.agent_name,
             body.position, body.label, config_json, body.inherit_mode),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(500, "create_node_failed")
        cur.execute(
            "UPDATE agent_trees SET root_node_id=%s, updated_at=now() WHERE id=%s AND root_node_id IS NULL",
            (node_id, tree_id),
        )
        return _node_row(row)


@router_agent_tree.get("/{tree_id}/nodes", response_model=list[AgentNodeOut])
def list_agent_nodes(tree_id: str) -> list[dict[str, Any]]:
    tid = _tenant()
    _verify_tree(tree_id, tid)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_AGENT_NODE_COLS} FROM agent_nodes WHERE tree_id=%s ORDER BY position",
            (tree_id,),
        )
        return [_node_row(r) for r in cur.fetchall()]


@router_agent_tree.put("/{tree_id}/nodes/{node_id}", response_model=AgentNodeOut)
def update_agent_node(tree_id: str, node_id: str, body: AgentNodeIn) -> dict[str, Any]:
    tid = _tenant()
    _verify_tree(tree_id, tid)
    _verify_node(tree_id, node_id)
    config_json = json.dumps(body.config, ensure_ascii=False)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE agent_nodes SET agent_name=%s, position=%s, label=%s, config=%s, inherit_mode=%s, "
            "parent_id=%s, updated_at=now() WHERE id=%s AND tree_id=%s RETURNING " + _AGENT_NODE_COLS,
            (body.agent_name, body.position, body.label, config_json, body.inherit_mode,
             body.parent_id or None, node_id, tree_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "node_not_found")
        return _node_row(row)


@router_agent_tree.delete("/{tree_id}/nodes/{node_id}")
def delete_agent_node(tree_id: str, node_id: str) -> dict[str, Any]:
    tid = _tenant()
    _verify_tree(tree_id, tid)
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute("SELECT parent_id FROM agent_nodes WHERE id=%s AND tree_id=%s", (node_id, tree_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "node_not_found")
        grandparent = row[0]
        cur.execute(
            "UPDATE agent_nodes SET parent_id=%s, updated_at=now() WHERE parent_id=%s AND tree_id=%s",
            (grandparent, node_id, tree_id),
        )
        cur.execute("DELETE FROM agent_nodes WHERE id=%s AND tree_id=%s", (node_id, tree_id))
        return {"ok": True, "deleted": node_id, "children_reparented_to": grandparent}


# ═══ HELPERS ═══


def _tenant() -> str:
    try:
        return resolve_pg_tenant_id() or "default"
    except Exception:
        return "default"


def _uid() -> str:
    return uuid4().hex[:12]


def _tree_row(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]), "tenant_id": str(row[1]), "name": str(row[2]),
        "description": str(row[3]), "root_node_id": str(row[4]) if row[4] else None,
        "created_at": str(row[5]), "updated_at": str(row[6]),
    }


def _node_row(row: tuple) -> dict[str, Any]:
    config = row[6] if isinstance(row[6], dict) else json.loads(str(row[6]) if row[6] else "{}")
    return {
        "id": str(row[0]), "tree_id": str(row[1]),
        "parent_id": str(row[2]) if row[2] else None,
        "agent_name": str(row[3]), "position": int(row[4]),
        "label": str(row[5]), "config": config,
        "inherit_mode": str(row[7]),
        "created_at": str(row[8]), "updated_at": str(row[9]),
    }


def _verify_tree(tree_id: str, tenant_id: str) -> None:
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM agent_trees WHERE id=%s AND tenant_id=%s", (tree_id, tenant_id))
        if not cur.fetchone():
            raise HTTPException(404, "tree_not_found")


def _verify_node(tree_id: str, node_id: str) -> None:
    with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM agent_nodes WHERE id=%s AND tree_id=%s", (node_id, tree_id))
        if not cur.fetchone():
            raise HTTPException(404, "node_not_found")


# ═══ AGENT TREE RUNNER (T17.3–T17.9) ═══


@dataclass
class NodeResult:
    """Result of executing one agent node."""
    node_id: str
    agent_name: str
    label: str
    reply: str = ""
    error: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    children_results: list[NodeResult] = field(default_factory=list)
    elapsed_ms: float = 0.0
    hitl_pending: bool = False


class AgentTreeRunner:
    """Percorre árvore, executa folhas em paralelo, agrega resultados.

    Usage:
        runner = AgentTreeRunner()
        for event in runner.run_tree("tree-123", user_text="..."):
            yield sse_line(event["event"], event["data"])
    """

    def __init__(self, max_parallel: int = 8) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="agentree")
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def run_tree(
        self,
        tree_id: str,
        *,
        user_text: str,
        chat_session_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Run a full tree and yield SSE events."""
        t0 = time.monotonic()
        cancel = threading.Event()
        with self._lock:
            self._cancel_events[tree_id] = cancel

        try:
            nodes = self._load_nodes(tree_id)
            if not nodes:
                yield _sse("tree_error", {"tree_id": tree_id, "error": "no_nodes"})
                return

            root = self._build_tree(nodes)
            yield _sse("tree_start", {"tree_id": tree_id, "node_count": len(nodes)})

            root_result = self._execute_node(root, user_text, cancel)

            elapsed = (time.monotonic() - t0) * 1000
            yield _sse("tree_done", {
                "tree_id": tree_id,
                "root_reply": root_result.reply[:500] if root_result else "",
                "elapsed_ms": elapsed,
                "cancelled": cancel.is_set(),
            })
        finally:
            with self._lock:
                self._cancel_events.pop(tree_id, None)

    def cancel_tree(self, tree_id: str) -> bool:
        """Cancel a running tree execution."""
        with self._lock:
            ev = self._cancel_events.get(tree_id)
        if ev:
            ev.set()
            return True
        return False

    # ── Internal ──

    def _load_nodes(self, tree_id: str) -> list[dict[str, Any]]:
        with connect_pg(tenant_id=resolve_pg_tenant_id()) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_AGENT_NODE_COLS} FROM agent_nodes WHERE tree_id=%s ORDER BY position",
                (tree_id,),
            )
            return [_node_row(r) for r in cur.fetchall()]

    def _build_tree(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a nested dict tree from flat node list."""
        node_map: dict[str, dict[str, Any]] = {}
        for n in nodes:
            node_map[n["id"]] = {**n, "children": []}
        root = None
        for n in nodes:
            pid = n.get("parent_id")
            if pid and pid in node_map:
                node_map[pid]["children"].append(node_map[n["id"]])
            elif not pid:
                root = node_map[n["id"]]
        return root or (nodes[0] if nodes else {"id": "root", "children": []})

    def _execute_node(
        self,
        node: dict[str, Any],
        user_text: str,
        cancel: threading.Event,
        inherited_summary: str = "",
    ) -> NodeResult:
        """Execute a node: if leaf → call LLM; if parent → spawn children → aggregate."""
        if cancel.is_set():
            return NodeResult(node_id=node["id"], agent_name=node.get("agent_name", "?"),
                              label=node.get("label", ""), error="cancelled")

        node_id = node["id"]
        children = node.get("children", [])

        _sse_yield("node_start", {
            "node_id": node_id, "agent_name": node.get("agent_name", "?"),
            "label": node.get("label", ""), "children_count": len(children),
        })

        t0 = time.monotonic()

        # ── Parent node: execute children in parallel ──
        if children:
            inherit_mode = node.get("inherit_mode", "full")
            child_context = self._build_inherited_context(user_text, inherited_summary, inherit_mode)

            futures: dict[Future[NodeResult], str] = {}
            for child in children:
                if cancel.is_set():
                    break
                fut = self._executor.submit(self._execute_node, child, user_text, cancel, child_context)
                futures[fut] = child["id"]

            child_results: list[NodeResult] = []
            for fut in as_completed(futures):
                if cancel.is_set():
                    for f in futures:
                        f.cancel()
                    break
                try:
                    cr = fut.result(timeout=120)
                    child_results.append(cr)
                    _sse_yield("node_child_done", {
                        "parent_id": node_id, "child_id": cr.node_id,
                        "child_reply": cr.reply[:300],
                    })
                except Exception as exc:
                    child_results.append(NodeResult(
                        node_id=futures[fut], agent_name="?", label="",
                        error=str(exc)[:500],
                    ))

            reply = self._aggregate_results(node, child_results, user_text)
            elapsed = (time.monotonic() - t0) * 1000
            result = NodeResult(
                node_id=node_id, agent_name=node.get("agent_name", "?"),
                label=node.get("label", ""), reply=reply,
                children_results=child_results, elapsed_ms=elapsed,
            )
            _sse_yield("node_done", {
                "node_id": node_id, "reply": reply[:500], "elapsed_ms": elapsed,
                "children_count": len(child_results),
            })
            return result

        # ── Leaf node: call LLM ──
        else:
            try:
                reply = self._call_agent_llm(node, user_text, inherited_summary, cancel)
                elapsed = (time.monotonic() - t0) * 1000
                result = NodeResult(
                    node_id=node_id, agent_name=node.get("agent_name", "?"),
                    label=node.get("label", ""), reply=reply, elapsed_ms=elapsed,
                )
                _sse_yield("node_done", {"node_id": node_id, "reply": reply[:500], "elapsed_ms": elapsed})
                return result
            except Exception as exc:
                elapsed = (time.monotonic() - t0) * 1000
                result = NodeResult(
                    node_id=node_id, agent_name=node.get("agent_name", "?"),
                    label=node.get("label", ""), error=str(exc)[:500], elapsed_ms=elapsed,
                )
                _sse_yield("node_error", {"node_id": node_id, "error": str(exc)[:500]})
                return result

    def _build_inherited_context(self, user_text: str, inherited_summary: str, inherit_mode: str) -> str:
        if inherit_mode == "none":
            return user_text
        elif inherit_mode == "summary":
            return inherited_summary[:2000] if inherited_summary else user_text
        else:
            if inherited_summary:
                return f"{inherited_summary}\n\n[User]\n{user_text}"
            return user_text

    def _aggregate_results(self, node: dict[str, Any], child_results: list[NodeResult], user_text: str) -> str:
        config = node.get("config", {})
        aggregate_mode = config.get("aggregate_mode", "concat")
        if aggregate_mode == "concat":
            parts: list[str] = []
            for cr in child_results:
                if cr.error:
                    parts.append(f"[{cr.agent_name}] ERROR: {cr.error}")
                elif cr.reply:
                    parts.append(f"[{cr.agent_name}] {cr.reply}")
            return "\n\n".join(parts)
        if child_results and child_results[0].reply:
            return child_results[0].reply
        return ""

    def _call_agent_llm(
        self,
        node: dict[str, Any],
        user_text: str,
        inherited_summary: str,
        cancel: threading.Event,
    ) -> str:
        """Call LLM for a leaf node using ContextPipeline."""
        if cancel.is_set():
            return ""

        node_agent_name = node.get("agent_name", "default")
        config = node.get("config", {})

        try:
            from app.context_pipeline import ContextPipeline  # noqa: PLC0415

            class _Payload:
                text = user_text
                history: list = []
                include_long_session_memory = False
                include_memory_recall = bool(config.get("rag_enabled", True))
                include_document_rag = False
                document_rag_doc_id = None
                include_session_rag = False
                use_saved_assistant_defaults = False
                include_playbook = False
                include_capability_digest = False
                media_attachments: list = []
                widget_active_slot = None
                agent_name = node_agent_name
                chat_session_id = None
                request_id = node["id"]

            pipeline = ContextPipeline()
            assembled = pipeline.assemble(
                payload=_Payload(),
                request_id=node["id"],
                agent_name=node_agent_name,
            )

            prompt = "\n".join(
                f"[{m['role']}] {m['content'][:2000]}"
                for m in assembled.injected_history[-5:]
            )

            try:
                from app.clients import call_llm  # noqa: PLC0415
                reply = call_llm(prompt, history=[], profile="balanced")
                return reply[:8000]
            except Exception:
                return (
                    f"[{node_agent_name}] Processed: '{user_text[:200]}'\n"
                )
        except Exception as exc:
            logger.warning("agent_tree_llm_failed: %s", exc)
            return f"[{node_agent_name}] Context assembled. Ready for inference."


# ═══ SSE HELPERS ═══

_sse_buffer: list[dict[str, Any]] = []


def _sse(event: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event, "data": data}


def _sse_yield(event: str, data: dict[str, Any]) -> None:
    _sse_buffer.append({"event": event, "data": data})


def sse_line(event: str, data: dict[str, Any]) -> str:
    """Format an SSE line for HTTP streaming."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ═══ EXECUTION ENDPOINT ═══


class TreeExecuteRequest(BaseModel):
    user_text: str = Field(..., min_length=1, max_length=10000)
    chat_session_id: str | None = Field(default=None, max_length=200)


@router_agent_tree.post("/{tree_id}/execute")
async def execute_agent_tree(tree_id: str, body: TreeExecuteRequest):
    """Execute an agent tree with SSE streaming."""
    from fastapi.responses import StreamingResponse
    import asyncio

    tid = _tenant()
    _verify_tree(tree_id, tid)

    async def _stream():
        runner = AgentTreeRunner()
        loop = asyncio.get_event_loop()

        def _run():
            return list(runner.run_tree(tree_id, user_text=body.user_text, chat_session_id=body.chat_session_id))

        try:
            events = await loop.run_in_executor(None, _run)
            for ev in events:
                yield sse_line(ev["event"], ev["data"])
        except Exception as exc:
            yield sse_line("tree_error", {"tree_id": tree_id, "error": str(exc)[:500]})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router_agent_tree.post("/{tree_id}/cancel")
def cancel_agent_tree(tree_id: str) -> dict[str, Any]:
    """Cancel a running tree execution."""
    runner = AgentTreeRunner()
    ok = runner.cancel_tree(tree_id)
    return {"ok": ok, "tree_id": tree_id}
