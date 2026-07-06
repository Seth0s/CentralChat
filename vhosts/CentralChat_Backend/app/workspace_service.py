"""Workspace bindings per user + git metadata (multi-workspace §5.4)."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import CENTRAL_ROOT
from app.shared.pg_tenant import resolve_pg_tenant_id
from app.shared.repo_context import collect_git_metadata
from app.shared.tenant_context import get_current_sub
from app.shared.workspace_guard import (
    WorkspaceGuardError,
    normalize_workspace_path_for_bind,
    normalize_workspace_root,
)

logger = logging.getLogger(__name__)

router_workspace_bind = APIRouter(tags=["WidgetMVP"])

_WORKSPACE_ID_MAX = 64
_WORKSPACE_LIST_MAX = 32


def _store_path() -> Path:
    root = (CENTRAL_ROOT or "/tmp/central").strip()
    return Path(root) / "state" / "workspace_bindings.json"


def _load_store() -> dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.debug("workspace store read failed", exc_info=True)
        return {}


def _save_store(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _binding_key(*, tenant_id: str, user_id: str) -> str:
    return f"{tenant_id}:{user_id}"


def _workspace_label(path: str) -> str:
    base = Path(path).name
    return base if base and base not in (".", "/") else path


def _stable_workspace_id(path: str) -> str:
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
    return f"ws-{digest[:16]}"


def _normalize_user_record(raw: Any) -> dict[str, Any]:
    """Migrate legacy single-path binding to multi-workspace record."""
    if not isinstance(raw, dict):
        return {"active_workspace_id": "", "workspaces": []}
    if isinstance(raw.get("workspaces"), list):
        active = str(raw.get("active_workspace_id") or "").strip()
        workspaces: list[dict[str, Any]] = []
        for item in raw["workspaces"]:
            if not isinstance(item, dict):
                continue
            wid = str(item.get("id") or "").strip()
            path = str(item.get("path") or "").strip()
            if not wid or not path:
                continue
            workspaces.append(
                {
                    "id": wid[:_WORKSPACE_ID_MAX],
                    "path": str(item.get("path") or ""),
                    "label": str(item.get("label") or _workspace_label(str(item.get("path") or "")))[:128],
                    "connector_id": str(item.get("connector_id") or "")[:128] or None,
                    "updated_at": item.get("updated_at"),
                }
            )
        if active and not any(w["id"] == active for w in workspaces) and workspaces:
            active = workspaces[-1]["id"]
        return {"active_workspace_id": active, "workspaces": workspaces}
    path = str(raw.get("path") or "").strip()
    if not path:
        return {"active_workspace_id": "", "workspaces": []}
    wid = _stable_workspace_id(path)
    ws = {
        "id": wid,
        "path": path,
        "label": _workspace_label(path),
        "updated_at": raw.get("updated_at") or datetime.now(timezone.utc).isoformat(),
    }
    return {"active_workspace_id": wid, "workspaces": [ws]}


def _load_user_record(*, tenant_id: str, user_id: str) -> dict[str, Any]:
    raw = _load_store().get(_binding_key(tenant_id=tenant_id, user_id=user_id))
    return _normalize_user_record(raw)


def _save_user_record(*, tenant_id: str, user_id: str, record: dict[str, Any]) -> None:
    store = _load_store()
    store[_binding_key(tenant_id=tenant_id, user_id=user_id)] = record
    _save_store(store)


def get_workspace_binding(*, tenant_id: str | None = None, user_id: str | None = None) -> dict[str, Any] | None:
    tid = (tenant_id or resolve_pg_tenant_id()).strip()
    uid = (user_id or get_current_sub() or "").strip()
    if not uid:
        return None
    rec = _load_user_record(tenant_id=tid, user_id=uid)
    active_id = str(rec.get("active_workspace_id") or "").strip()
    workspaces = rec.get("workspaces") if isinstance(rec.get("workspaces"), list) else []
    chosen: dict[str, Any] | None = None
    for item in workspaces:
        if isinstance(item, dict) and str(item.get("id") or "") == active_id:
            chosen = item
            break
    if chosen is None and workspaces:
        chosen = workspaces[-1] if isinstance(workspaces[-1], dict) else None
    if not chosen:
        return None
    return {
        "id": chosen.get("id"),
        "path": chosen.get("path") or None,
        "label": chosen.get("label"),
        "connector_id": chosen.get("connector_id"),
        "tenant_id": tid,
        "user_id": uid,
        "updated_at": chosen.get("updated_at"),
    }


def get_workspace_by_id(
    workspace_id: str,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    wid = (workspace_id or "").strip()
    if not wid:
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip()
    uid = (user_id or get_current_sub() or "").strip()
    if not uid:
        return None
    rec = _load_user_record(tenant_id=tid, user_id=uid)
    for item in rec.get("workspaces") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == wid:
            return item
    return None


def git_metadata(workspace_root: str) -> dict[str, Any]:
    return collect_git_metadata(workspace_root)


def resolve_effective_workspace_root(
    header_path: str | None = None,
    *,
    header_workspace_id: str | None = None,
) -> str | None:
    hp = (header_path or "").strip()
    if hp:
        try:
            return normalize_workspace_root(hp)
        except WorkspaceGuardError:
            try:
                return normalize_workspace_path_for_bind(hp)
            except WorkspaceGuardError:
                return None
    hid = (header_workspace_id or "").strip()
    if hid:
        item = get_workspace_by_id(hid)
        if item and item.get("path"):
            p = str(item["path"])
            try:
                return normalize_workspace_root(p)
            except WorkspaceGuardError:
                try:
                    return normalize_workspace_path_for_bind(p)
                except WorkspaceGuardError:
                    return None
    binding = get_workspace_binding()
    if binding and binding.get("path"):
        p = str(binding["path"])
        try:
            return normalize_workspace_root(p)
        except WorkspaceGuardError:
            try:
                return normalize_workspace_path_for_bind(p)
            except WorkspaceGuardError:
                return None
    if binding and binding.get("connector_id"):
        # connector-only workspace — no local filesystem root
        return None
    return None


class WorkspaceBindRequest(BaseModel):
    path: str | None = Field(default=None, max_length=4096)
    connector_id: str | None = Field(default=None, max_length=128)

    def model_post_init(self, __context: Any) -> None:
        if not self.path and not self.connector_id:
            raise ValueError("path or connector_id required")


class WorkspaceEntry(BaseModel):
    id: str = Field(..., min_length=1, max_length=_WORKSPACE_ID_MAX)
    path: str | None = Field(default=None, max_length=4096)
    label: str | None = Field(default=None, max_length=128)
    connector_id: str | None = Field(default=None, max_length=128)


class WorkspacesPutRequest(BaseModel):
    workspaces: list[WorkspaceEntry] = Field(default_factory=list, max_length=_WORKSPACE_LIST_MAX)
    active_workspace_id: str | None = Field(default=None, max_length=_WORKSPACE_ID_MAX)


def _serialize_workspace_item(item: dict[str, Any], *, include_git: bool = False) -> dict[str, Any]:
    path = str(item.get("path") or "")
    connector_id = str(item.get("connector_id") or "") or None
    out: dict[str, Any] = {
        "id": item.get("id"),
        "path": path or None,
        "label": item.get("label") or (_workspace_label(path) if path else ""),
        "connector_id": connector_id,
        "updated_at": item.get("updated_at"),
    }
    if include_git and path:
        try:
            out["git"] = git_metadata(path)
        except Exception:
            out["git"] = {}
    return out


@router_workspace_bind.get("/ui/workspaces")
def ui_workspaces_list() -> dict[str, Any]:
    uid = get_current_sub()
    if not uid:
        raise HTTPException(status_code=401, detail="auth_required")
    tid = resolve_pg_tenant_id()
    rec = _load_user_record(tenant_id=tid, user_id=uid)
    items = [
        _serialize_workspace_item(w, include_git=False)
        for w in rec.get("workspaces") or []
        if isinstance(w, dict)
    ]
    active_id = str(rec.get("active_workspace_id") or "").strip()
    active = next((i for i in items if i.get("id") == active_id), None)
    if active is None and items:
        active = items[-1]
        active_id = str(active.get("id") or "")
    return {
        "tenant_id": tid,
        "user_id": uid,
        "active_workspace_id": active_id,
        "items": items,
        "active": _serialize_workspace_item(active, include_git=True) if active else None,
    }


@router_workspace_bind.post("/ui/workspaces")
def ui_workspaces_put(payload: WorkspacesPutRequest) -> dict[str, Any]:
    uid = get_current_sub()
    if not uid:
        raise HTTPException(status_code=401, detail="auth_required")
    tid = resolve_pg_tenant_id()
    now = datetime.now(timezone.utc).isoformat()
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in payload.workspaces:
        wid = entry.id.strip()
        if wid in seen_ids:
            raise HTTPException(status_code=400, detail="workspace_id_duplicado")
        seen_ids.add(wid)
        root = ""
        connector = (entry.connector_id or "").strip()[:128] or None
        if entry.path:
            try:
                root = normalize_workspace_path_for_bind(entry.path)
            except WorkspaceGuardError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        elif not connector:
            raise HTTPException(status_code=400, detail="path or connector_id required")
        label = (entry.label or "").strip() or (_workspace_label(root) if root else connector or wid[:8])
        normalized.append(
            {
                "id": wid[:_WORKSPACE_ID_MAX],
                "path": root or "",
                "label": label[:128],
                "connector_id": connector,
                "updated_at": now,
            }
        )
    active_id = (payload.active_workspace_id or "").strip()
    if active_id and not any(w["id"] == active_id for w in normalized):
        raise HTTPException(status_code=400, detail="active_workspace_id_invalido")
    if not active_id and normalized:
        active_id = normalized[-1]["id"]
    record = {"active_workspace_id": active_id, "workspaces": normalized}
    _save_user_record(tenant_id=tid, user_id=uid, record=record)
    items = [_serialize_workspace_item(w) for w in normalized]
    active = next((i for i in items if i.get("id") == active_id), None)
    return {
        "ok": True,
        "active_workspace_id": active_id,
        "items": items,
        "active": _serialize_workspace_item(active, include_git=True) if active else None,
    }


@router_workspace_bind.get("/ui/workspace")
def ui_workspace_get() -> dict[str, Any]:
    uid = get_current_sub()
    if not uid:
        raise HTTPException(status_code=401, detail="auth_required")
    tid = resolve_pg_tenant_id()
    binding = get_workspace_binding(tenant_id=tid, user_id=uid)
    if not binding:
        return {"bound": False, "tenant_id": tid, "user_id": uid}
    path = str(binding.get("path") or "")
    return {
        "bound": True,
        "id": binding.get("id"),
        "tenant_id": tid,
        "user_id": uid,
        "path": path,
        "git": git_metadata(path) if path else {},
        "updated_at": binding.get("updated_at"),
    }


@router_workspace_bind.post("/ui/workspace")
def ui_workspace_post(payload: WorkspaceBindRequest) -> dict[str, Any]:
    uid = get_current_sub()
    if not uid:
        raise HTTPException(status_code=401, detail="auth_required")
    tid = resolve_pg_tenant_id()
    root = ""
    connector = (payload.connector_id or "").strip()[:128] or None
    if payload.path:
        try:
            root = normalize_workspace_path_for_bind(payload.path)
        except WorkspaceGuardError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif not connector:
        raise HTTPException(status_code=400, detail="path or connector_id required")
    git = {}
    if root:
        try:
            git = git_metadata(root)
        except Exception:
            git = {}
    now = datetime.now(timezone.utc).isoformat()
    user_rec = _load_user_record(tenant_id=tid, user_id=uid)
    workspaces = list(user_rec.get("workspaces") or [])
    wid = _stable_workspace_id(root or f"connector:{connector}")
    replaced = False
    for i, item in enumerate(workspaces):
        if not isinstance(item, dict):
            continue
        item_path = str(item.get("path") or "")
        item_cid = str(item.get("connector_id") or "")
        if (root and item_path == root) or str(item.get("id") or "") == wid or (connector and item_cid == connector):
            workspaces[i] = {
                "id": wid,
                "path": root or "",
                "label": (payload.path and _workspace_label(root)) or connector or wid[:8],
                "connector_id": connector,
                "updated_at": now,
            }
            replaced = True
            break
    if not replaced:
        workspaces.append(
            {
                "id": wid,
                "path": root or "",
                "label": (payload.path and _workspace_label(root)) or connector or wid[:8],
                "connector_id": connector,
                "updated_at": now,
            }
        )
    if len(workspaces) > _WORKSPACE_LIST_MAX:
        workspaces = workspaces[-_WORKSPACE_LIST_MAX:]
    _save_user_record(
        tenant_id=tid,
        user_id=uid,
        record={"active_workspace_id": wid, "workspaces": workspaces},
    )
    return {
        "bound": True,
        "id": wid,
        "path": root or None,
        "connector_id": connector,
        "git": git,
        "updated_at": now,
    }
