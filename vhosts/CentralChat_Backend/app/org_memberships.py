"""Organization scope: groups, projects, and scoped memberships."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id
from app.shared.rbac import get_current_role
from app.shared.tenant_context import get_current_sub

ORG_ROLES = frozenset({"admin", "lead", "developer", "auditor"})
SCOPE_TYPES = frozenset({"organization", "group", "project"})
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")


def _uuid_or_none(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(UUID(str(raw).strip()))
    except ValueError:
        return None


def _current_user_id() -> str | None:
    return _uuid_or_none(get_current_sub())


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", (raw or "").strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-._")
    if not slug:
        raise ValueError("invalid_slug")
    return slug[:80]


def _normalize_slug(raw: str | None, *, fallback: str) -> str:
    slug = (raw or "").strip().lower() or _slugify(fallback)
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError("invalid_slug")
    return slug


def _normalize_role(raw: str) -> str:
    role = (raw or "").strip().lower()
    if role not in ORG_ROLES:
        raise ValueError("invalid_role")
    return role


def _normalize_scope_type(raw: str) -> str:
    scope_type = (raw or "").strip().lower()
    if scope_type not in SCOPE_TYPES:
        raise ValueError("invalid_scope_type")
    return scope_type


def ensure_org_schema() -> None:
    if not memory_db_enabled():
        return
    with connect_pg() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS groups (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                archived_at TIMESTAMPTZ,
                UNIQUE (tenant_id, slug)
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS projects (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                repository_url TEXT,
                created_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                archived_at TIMESTAMPTZ,
                UNIQUE (tenant_id, group_id, slug)
            );"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS memberships (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id TEXT NOT NULL,
                user_id UUID NOT NULL,
                scope_type TEXT NOT NULL CHECK (scope_type IN ('organization', 'group', 'project')),
                scope_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'lead', 'developer', 'auditor')),
                created_by UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (tenant_id, user_id, scope_type, scope_id)
            );"""
        )
        cur.execute("CREATE INDEX IF NOT EXISTS groups_tenant_name_idx ON groups (tenant_id, name);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS projects_tenant_group_name_idx ON projects (tenant_id, group_id, name);"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS memberships_tenant_user_idx ON memberships (tenant_id, user_id);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS memberships_tenant_scope_role_idx "
            "ON memberships (tenant_id, scope_type, scope_id, role);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS memberships_tenant_scope_user_idx "
            "ON memberships (tenant_id, scope_type, scope_id, user_id);"
        )
        for table in ("groups", "projects", "memberships"):
            cur.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            cur.execute(f"DROP POLICY IF EXISTS {table}_tenant_rls ON {table};")
            cur.execute(
                f"""CREATE POLICY {table}_tenant_rls ON {table}
                    USING (tenant_id = current_setting('app.tenant_id', true))
                    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));"""
            )


def org_enabled_or_503() -> None:
    if not memory_db_enabled():
        raise HTTPException(status_code=503, detail="memory_db_disabled")


def _is_global_admin() -> bool:
    if not get_current_sub():
        return True
    return get_current_role() == "admin"


def _fetch_memberships(*, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
    ensure_org_schema()
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, tenant_id, user_id::text, scope_type, scope_id, role,
                      created_by::text, created_at::text, updated_at::text
               FROM memberships
               WHERE tenant_id=%s AND user_id=%s::uuid
               ORDER BY scope_type, role, created_at""",
            (tenant_id, user_id),
        )
        return [_membership_row(r) for r in cur.fetchall()]


def _current_memberships(*, tenant_id: str) -> list[dict[str, Any]]:
    uid = _current_user_id()
    if not uid:
        return []
    return _fetch_memberships(tenant_id=tenant_id, user_id=uid)


def list_user_memberships(*, user_id: str, tenant_id: str | None = None) -> list[dict[str, Any]]:
    org_enabled_or_503()
    uid = _uuid_or_none(user_id)
    if not uid:
        raise ValueError("invalid_user_id")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    target_memberships = _fetch_memberships(tenant_id=tid, user_id=uid)
    current_role = get_current_role()
    if not get_current_sub() or current_role in ("admin", "auditor"):
        return target_memberships

    current_memberships = _current_memberships(tenant_id=tid)
    if any(
        item["scope_type"] == "organization" and item["role"] in ("admin", "auditor")
        for item in current_memberships
    ):
        return target_memberships

    visible: list[dict[str, Any]] = []
    current_group_scopes = {
        item["scope_id"]
        for item in current_memberships
        if item["scope_type"] == "group" and item["role"] in ("lead", "auditor", "admin")
    }
    current_project_scopes = {
        item["scope_id"]
        for item in current_memberships
        if item["scope_type"] == "project" and item["role"] in ("lead", "auditor", "admin")
    }
    for item in target_memberships:
        if item["scope_type"] == "group" and item["scope_id"] in current_group_scopes:
            visible.append(item)
        elif item["scope_type"] == "project":
            project_id = item["scope_id"]
            group_id = _project_group_id(tenant_id=tid, project_id=project_id)
            if project_id in current_project_scopes or (group_id and group_id in current_group_scopes):
                visible.append(item)
    return visible


def can_manage_project(*, tenant_id: str, project_id: str) -> bool:
    if _is_global_admin():
        return True
    pid = _uuid_or_none(project_id)
    uid = _current_user_id()
    if not pid or not uid:
        return False
    memberships = _fetch_memberships(tenant_id=tenant_id, user_id=uid)
    if any(m["scope_type"] == "organization" and m["role"] == "admin" for m in memberships):
        return True
    if any(m["scope_type"] == "project" and m["scope_id"] == pid and m["role"] == "lead" for m in memberships):
        return True
    group_id = _project_group_id(tenant_id=tenant_id, project_id=pid)
    if not group_id:
        return False
    return any(m["scope_type"] == "group" and m["scope_id"] == group_id and m["role"] == "lead" for m in memberships)


def require_can_manage_project(*, tenant_id: str, project_id: str) -> None:
    if not can_manage_project(tenant_id=tenant_id, project_id=project_id):
        raise HTTPException(status_code=403, detail="insufficient_scope")


def find_project_lead_user_id(*, project_id: str, tenant_id: str | None = None) -> str | None:
    """Return the user_id of the first direct project lead membership, if any."""
    pid = _uuid_or_none(project_id)
    if not pid or not memory_db_enabled():
        return None
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_org_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT user_id::text FROM memberships
               WHERE tenant_id=%s AND scope_type='project' AND scope_id=%s AND role='lead'
               ORDER BY created_at LIMIT 1""",
            (tid, pid),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _project_group_id(*, tenant_id: str, project_id: str) -> str | None:
    ensure_org_schema()
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute("SELECT group_id::text FROM projects WHERE tenant_id=%s AND id=%s::uuid", (tenant_id, project_id))
        row = cur.fetchone()
        return str(row[0]) if row else None


def _group_row(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "tenant_id": str(r[1]),
        "name": str(r[2]),
        "slug": str(r[3]),
        "description": str(r[4] or ""),
        "created_by": str(r[5]) if r[5] else None,
        "created_at": str(r[6] or ""),
        "updated_at": str(r[7] or ""),
        "archived_at": str(r[8]) if r[8] else None,
    }


def _project_row(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "tenant_id": str(r[1]),
        "group_id": str(r[2]),
        "name": str(r[3]),
        "slug": str(r[4]),
        "description": str(r[5] or ""),
        "repository_url": str(r[6]) if r[6] else None,
        "created_by": str(r[7]) if r[7] else None,
        "created_at": str(r[8] or ""),
        "updated_at": str(r[9] or ""),
        "archived_at": str(r[10]) if r[10] else None,
    }


def _membership_row(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "tenant_id": str(r[1]),
        "user_id": str(r[2]),
        "scope_type": str(r[3]),
        "scope_id": str(r[4]),
        "role": str(r[5]),
        "created_by": str(r[6]) if r[6] else None,
        "created_at": str(r[7] or ""),
        "updated_at": str(r[8] or ""),
    }


def list_org_tree(*, tenant_id: str | None = None) -> dict[str, Any]:
    org_enabled_or_503()
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_org_schema()
    uid = _current_user_id()
    admin = _is_global_admin()
    memberships = _current_memberships(tenant_id=tid) if uid else []
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, name, slug, description, created_by,
                      created_at, updated_at, archived_at
               FROM groups
               WHERE tenant_id=%s AND archived_at IS NULL
               ORDER BY name""",
            (tid,),
        )
        groups = [_group_row(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT id, tenant_id, group_id, name, slug, description, repository_url,
                      created_by, created_at, updated_at, archived_at
               FROM projects
               WHERE tenant_id=%s AND archived_at IS NULL
               ORDER BY name""",
            (tid,),
        )
        projects = [_project_row(r) for r in cur.fetchall()]

    if not admin:
        group_ids = {m["scope_id"] for m in memberships if m["scope_type"] == "group"}
        project_ids = {m["scope_id"] for m in memberships if m["scope_type"] == "project"}
        org_roles = {m["role"] for m in memberships if m["scope_type"] == "organization"}
        if not org_roles:
            projects = [p for p in projects if p["id"] in project_ids or p["group_id"] in group_ids]
            visible_group_ids = group_ids | {p["group_id"] for p in projects}
            groups = [g for g in groups if g["id"] in visible_group_ids]

    return {
        "tenant_id": tid,
        "groups": groups,
        "projects": projects,
        "memberships": memberships,
        "org_enabled": True,
    }


def list_org_health(*, tenant_id: str | None = None) -> dict[str, Any]:
    tree = list_org_tree(tenant_id=tenant_id)
    tid = str(tree.get("tenant_id") or tenant_id or resolve_pg_tenant_id() or "default")
    groups = list(tree.get("groups") or [])
    projects = list(tree.get("projects") or [])

    project_ids_by_group: dict[str, list[dict[str, Any]]] = {}
    for project in projects:
        project_ids_by_group.setdefault(str(project.get("group_id") or ""), []).append(project)

    groups_without_projects = [
        group for group in groups if not project_ids_by_group.get(str(group.get("id") or ""))
    ]
    projects_without_direct_lead: list[dict[str, Any]] = []
    for project in projects:
        project_id = str(project.get("id") or "")
        if not project_id:
            continue
        if _project_direct_lead_count(tenant_id=tid, project_id=project_id) == 0:
            projects_without_direct_lead.append(project)

    return {
        "tenant_id": tid,
        "groups_without_projects": groups_without_projects,
        "projects_without_direct_lead": projects_without_direct_lead,
        "counts": {
            "groups": len(groups),
            "projects": len(projects),
            "groups_without_projects": len(groups_without_projects),
            "projects_without_direct_lead": len(projects_without_direct_lead),
        },
        "org_enabled": True,
    }


def create_group(*, name: str, slug: str | None = None, description: str | None = None, tenant_id: str | None = None) -> dict[str, Any]:
    org_enabled_or_503()
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    n = (name or "").strip()
    if not n:
        raise ValueError("empty_name")
    s = _normalize_slug(slug, fallback=n)
    actor = _current_user_id()
    ensure_org_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO groups (tenant_id, name, slug, description, created_by)
               VALUES (%s,%s,%s,%s,%s::uuid)
               RETURNING id, tenant_id, name, slug, description, created_by,
                         created_at, updated_at, archived_at""",
            (tid, n[:200], s, (description or "")[:2000], actor),
        )
        row = cur.fetchone()
    return _group_row(row)


def patch_group(
    group_id: str,
    *,
    name: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    org_enabled_or_503()
    gid = _uuid_or_none(group_id)
    if not gid:
        raise ValueError("invalid_group_id")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    fields: list[tuple[str, Any]] = []
    if name is not None and name.strip():
        fields.append(("name", name.strip()[:200]))
    if slug is not None:
        fields.append(("slug", _normalize_slug(slug, fallback=name or slug)))
    if description is not None:
        fields.append(("description", description[:2000]))
    if not fields:
        return get_group(gid, tenant_id=tid)
    fields.append(("updated_at", "now()"))
    set_sql_parts = []
    params: list[Any] = []
    for key, value in fields:
        if key == "updated_at":
            set_sql_parts.append("updated_at=now()")
        else:
            set_sql_parts.append(f"{key}=%s")
            params.append(value)
    params.extend([tid, gid])
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""UPDATE groups SET {', '.join(set_sql_parts)}
                WHERE tenant_id=%s AND id=%s::uuid AND archived_at IS NULL
                RETURNING id, tenant_id, name, slug, description, created_by,
                          created_at, updated_at, archived_at""",
            params,
        )
        row = cur.fetchone()
    return _group_row(row) if row else None


def get_group(group_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    gid = _uuid_or_none(group_id)
    if not gid:
        return None
    ensure_org_schema()
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, name, slug, description, created_by,
                      created_at, updated_at, archived_at
               FROM groups WHERE tenant_id=%s AND id=%s::uuid AND archived_at IS NULL""",
            (tenant_id, gid),
        )
        row = cur.fetchone()
    return _group_row(row) if row else None


def create_project(
    *,
    group_id: str,
    name: str,
    slug: str | None = None,
    description: str | None = None,
    repository_url: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    org_enabled_or_503()
    gid = _uuid_or_none(group_id)
    if not gid:
        raise ValueError("invalid_group_id")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    n = (name or "").strip()
    if not n:
        raise ValueError("empty_name")
    if get_group(gid, tenant_id=tid) is None:
        raise ValueError("group_not_found")
    s = _normalize_slug(slug, fallback=n)
    actor = _current_user_id()
    ensure_org_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projects (tenant_id, group_id, name, slug, description, repository_url, created_by)
               VALUES (%s,%s::uuid,%s,%s,%s,%s,%s::uuid)
               RETURNING id, tenant_id, group_id, name, slug, description, repository_url,
                         created_by, created_at, updated_at, archived_at""",
            (tid, gid, n[:200], s, (description or "")[:2000], (repository_url or "")[:1000] or None, actor),
        )
        row = cur.fetchone()
    return _project_row(row)


def patch_project(
    project_id: str,
    *,
    name: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    repository_url: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    org_enabled_or_503()
    pid = _uuid_or_none(project_id)
    if not pid:
        raise ValueError("invalid_project_id")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    fields: list[tuple[str, Any]] = []
    if name is not None and name.strip():
        fields.append(("name", name.strip()[:200]))
    if slug is not None:
        fields.append(("slug", _normalize_slug(slug, fallback=name or slug)))
    if description is not None:
        fields.append(("description", description[:2000]))
    if repository_url is not None:
        fields.append(("repository_url", repository_url[:1000] or None))
    if not fields:
        return get_project(pid, tenant_id=tid)
    set_sql = ", ".join(f"{key}=%s" for key, _ in fields) + ", updated_at=now()"
    params = [value for _, value in fields] + [tid, pid]
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            f"""UPDATE projects SET {set_sql}
                WHERE tenant_id=%s AND id=%s::uuid AND archived_at IS NULL
                RETURNING id, tenant_id, group_id, name, slug, description, repository_url,
                          created_by, created_at, updated_at, archived_at""",
            params,
        )
        row = cur.fetchone()
    return _project_row(row) if row else None


def get_project(project_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    pid = _uuid_or_none(project_id)
    if not pid:
        return None
    ensure_org_schema()
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, group_id, name, slug, description, repository_url,
                      created_by, created_at, updated_at, archived_at
               FROM projects WHERE tenant_id=%s AND id=%s::uuid AND archived_at IS NULL""",
            (tenant_id, pid),
        )
        row = cur.fetchone()
    return _project_row(row) if row else None


def list_project_members(project_id: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
    org_enabled_or_503()
    pid = _uuid_or_none(project_id)
    if not pid:
        raise ValueError("invalid_project_id")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    ensure_org_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, tenant_id, user_id::text, scope_type, scope_id, role,
                      created_by::text, created_at::text, updated_at::text
               FROM memberships
               WHERE tenant_id=%s AND scope_type='project' AND scope_id=%s
               ORDER BY role, created_at""",
            (tid, pid),
        )
        return [_membership_row(r) for r in cur.fetchall()]


def _project_membership_role(*, tenant_id: str, project_id: str, user_id: str) -> str | None:
    ensure_org_schema()
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT role
               FROM memberships
               WHERE tenant_id=%s AND user_id=%s::uuid AND scope_type='project' AND scope_id=%s
               LIMIT 1""",
            (tenant_id, user_id, project_id),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _project_direct_lead_count(*, tenant_id: str, project_id: str) -> int:
    ensure_org_schema()
    with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM memberships
               WHERE tenant_id=%s AND scope_type='project' AND scope_id=%s AND role='lead'""",
            (tenant_id, project_id),
        )
        row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _assert_not_removing_last_project_lead(
    *,
    tenant_id: str,
    project_id: str,
    user_id: str,
    next_role: str | None,
) -> None:
    current_role = _project_membership_role(tenant_id=tenant_id, project_id=project_id, user_id=user_id)
    if current_role != "lead":
        return
    if next_role == "lead":
        return
    if _project_direct_lead_count(tenant_id=tenant_id, project_id=project_id) <= 1:
        raise ValueError("last_project_lead")


def upsert_membership(
    *,
    user_id: str,
    scope_type: str,
    scope_id: str,
    role: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    org_enabled_or_503()
    uid = _uuid_or_none(user_id)
    if not uid:
        raise ValueError("invalid_user_id")
    st = _normalize_scope_type(scope_type)
    sid = (scope_id or "").strip()
    if st in ("group", "project") and not _uuid_or_none(sid):
        raise ValueError("invalid_scope_id")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    if st == "organization":
        sid = tid
    elif st == "group" and get_group(sid, tenant_id=tid) is None:
        raise ValueError("group_not_found")
    elif st == "project" and get_project(sid, tenant_id=tid) is None:
        raise ValueError("project_not_found")
    r = _normalize_role(role)
    if st == "project":
        _assert_not_removing_last_project_lead(
            tenant_id=tid,
            project_id=sid,
            user_id=uid,
            next_role=r,
        )
    actor = _current_user_id()
    ensure_org_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memberships (tenant_id, user_id, scope_type, scope_id, role, created_by)
               VALUES (%s,%s::uuid,%s,%s,%s,%s::uuid)
               ON CONFLICT (tenant_id, user_id, scope_type, scope_id)
               DO UPDATE SET role=EXCLUDED.role, updated_at=now()
               RETURNING id::text, tenant_id, user_id::text, scope_type, scope_id, role,
                         created_by::text, created_at::text, updated_at::text""",
            (tid, uid, st, sid, r, actor),
        )
        row = cur.fetchone()
    return _membership_row(row)


def delete_membership(
    *,
    user_id: str,
    scope_type: str,
    scope_id: str,
    tenant_id: str | None = None,
) -> bool:
    org_enabled_or_503()
    uid = _uuid_or_none(user_id)
    if not uid:
        raise ValueError("invalid_user_id")
    st = _normalize_scope_type(scope_type)
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    sid = tid if st == "organization" else (scope_id or "").strip()
    if st == "project":
        if not _uuid_or_none(sid):
            raise ValueError("invalid_scope_id")
        _assert_not_removing_last_project_lead(
            tenant_id=tid,
            project_id=sid,
            user_id=uid,
            next_role=None,
        )
    ensure_org_schema()
    with connect_pg(tenant_id=tid) as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM memberships
               WHERE tenant_id=%s AND user_id=%s::uuid AND scope_type=%s AND scope_id=%s
               RETURNING id""",
            (tid, uid, st, sid),
        )
        return cur.fetchone() is not None
