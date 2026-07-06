"""H2/C2 — GitHub App + GitLab PR-only integration after approval."""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import httpx
import jwt as pyjwt

from app.config import (
    CENTRAL_GITHUB_APP_ID,
    CENTRAL_GITHUB_APP_INSTALLATION_ID,
    CENTRAL_GITHUB_APP_PRIVATE_KEY,
    CENTRAL_GITHUB_REPO,
    CENTRAL_GITHUB_TOKEN,
    CENTRAL_GITLAB_BASE_URL,
    CENTRAL_GITLAB_PROJECT_ID,
    CENTRAL_GITLAB_TOKEN,
    CENTRAL_WRITE_MODE_DEFAULT,
)
from app.shared.policy_engine import resolve_write_mode
from app.shared.pg_tenant import connect_pg, memory_db_enabled, resolve_pg_tenant_id

logger = logging.getLogger(__name__)

_BRANCH_PREFIX = "central/approval-"


def _tenant_git_config(tenant_id: str) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "write_mode_default": CENTRAL_WRITE_MODE_DEFAULT,
        "github": {
            "token": CENTRAL_GITHUB_TOKEN,
            "repo": CENTRAL_GITHUB_REPO,
            "app_id": CENTRAL_GITHUB_APP_ID,
            "installation_id": CENTRAL_GITHUB_APP_INSTALLATION_ID,
            "private_key": CENTRAL_GITHUB_APP_PRIVATE_KEY,
        },
        "gitlab": {
            "token": CENTRAL_GITLAB_TOKEN,
            "project_id": CENTRAL_GITLAB_PROJECT_ID,
            "base_url": CENTRAL_GITLAB_BASE_URL,
        },
    }
    if not memory_db_enabled():
        return cfg
    try:
        with connect_pg(tenant_id=tenant_id) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT features_json FROM tenant_config WHERE tenant_id=%s LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                fj = row[0]
                if isinstance(fj, str):
                    fj = json.loads(fj)
                if isinstance(fj, dict):
                    integrations = fj.get("integrations")
                    if isinstance(integrations, dict):
                        if isinstance(integrations.get("github"), dict):
                            cfg["github"] = {**cfg["github"], **integrations["github"]}
                        if isinstance(integrations.get("gitlab"), dict):
                            cfg["gitlab"] = {**cfg["gitlab"], **integrations["gitlab"]}
                    wm = fj.get("write_mode_default")
                    if isinstance(wm, str) and wm in ("direct_write", "pr_only"):
                        cfg["write_mode_default"] = wm
    except Exception:
        logger.debug("tenant git config load failed", exc_info=True)
    return cfg


def resolve_write_mode_for_path(path: str, *, tenant_id: str | None = None) -> str:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    mode = resolve_write_mode(path, tenant_id=tid)
    if mode in ("direct_write", "pr_only"):
        return mode
    cfg = _tenant_git_config(tid)
    return str(cfg.get("write_mode_default") or CENTRAL_WRITE_MODE_DEFAULT)


def _pr_body_from_approval(rec: dict[str, Any]) -> str:
    body = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    lines = [
        f"Central-Approval: {rec.get('approval_id')}",
        f"Central-Session: {rec.get('session_id') or 'n/a'}",
        f"Action: {rec.get('action_id')}",
        "",
        str(body.get("summary") or "Approved change via CentralChat"),
        "",
        "```diff",
        str(body.get("diff") or "")[:12000],
        "```",
    ]
    return "\n".join(lines)


def _commit_message(rec: dict[str, Any]) -> str:
    approval_id = str(rec.get("approval_id") or "")
    body = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    path = str(body.get("path") or "change")
    name = path.split("/")[-1] or "change"
    return f"central(approval:{approval_id[:8]}): {name}"


def _branch_name(approval_id: str) -> str:
    return f"{_BRANCH_PREFIX}{approval_id[:8]}"


def _github_app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}
    return pyjwt.encode(payload, private_key_pem, algorithm="RS256")


def _github_installation_token(
    app_id: str,
    installation_id: str,
    private_key_pem: str,
    client: httpx.Client,
) -> str | None:
    app_jwt = _github_app_jwt(app_id, private_key_pem)
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = client.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers=headers,
    )
    if resp.status_code >= 400:
        logger.warning("github app token failed status=%s", resp.status_code)
        return None
    return str(resp.json().get("token") or "") or None


def _resolve_github_token(cfg: dict[str, Any], client: httpx.Client) -> tuple[str, str]:
    """Returns (token, auth_mode: pat|app)."""
    pat = str(cfg.get("token") or "").strip()
    app_id = str(cfg.get("app_id") or "").strip()
    inst = str(cfg.get("installation_id") or "").strip()
    pem = str(cfg.get("private_key") or "").strip()
    if pem and "\\n" in pem:
        pem = pem.replace("\\n", "\n")
    if app_id and inst and pem:
        app_tok = _github_installation_token(app_id, inst, pem, client)
        if app_tok:
            return app_tok, "app"
    if pat:
        return pat, "pat"
    return "", ""


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_push_file(
    client: httpx.Client,
    *,
    repo: str,
    branch: str,
    path: str,
    content: str,
    message: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    rel_path = path.lstrip("/")
    if not rel_path:
        return {"ok": False, "error": "empty_path"}
    url = f"https://api.github.com/repos/{repo}/contents/{rel_path}"
    sha: str | None = None
    get_resp = client.get(url, headers=headers, params={"ref": branch})
    if get_resp.status_code == 200:
        sha = str(get_resp.json().get("sha") or "") or None
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    put_body: dict[str, Any] = {
        "message": message[:500],
        "content": encoded,
        "branch": branch,
    }
    if sha:
        put_body["sha"] = sha
    put_resp = client.put(url, headers=headers, json=put_body)
    if put_resp.status_code >= 400:
        return {"ok": False, "error": "github_push_failed", "detail": put_resp.text[:500]}
    return {"ok": True, "path": rel_path}


def create_github_pr(
    *,
    approval_rec: dict[str, Any],
    tenant_id: str | None = None,
    base_branch: str = "main",
) -> dict[str, Any]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    cfg = _tenant_git_config(tid)["github"]
    repo = str(cfg.get("repo") or "").strip()
    if not repo or "/" not in repo:
        return {"ok": False, "error": "github_not_configured"}
    approval_id = str(approval_rec.get("approval_id") or "")
    branch = _branch_name(approval_id)
    payload_body = approval_rec.get("payload") if isinstance(approval_rec.get("payload"), dict) else {}
    path = str(payload_body.get("path") or "")
    new_content = payload_body.get("new_content")
    title = _commit_message(approval_rec)[:200]
    pr_body = _pr_body_from_approval(approval_rec)
    headers: dict[str, str] = {}
    try:
        with httpx.Client(timeout=45.0) as client:
            token, auth_mode = _resolve_github_token(cfg, client)
            if not token:
                return {"ok": False, "error": "github_not_configured"}
            headers = _github_headers(token)
            ref_resp = client.get(
                f"https://api.github.com/repos/{repo}/git/ref/heads/{base_branch}",
                headers=headers,
            )
            if ref_resp.status_code >= 400:
                return {"ok": False, "error": "github_base_ref_missing", "status": ref_resp.status_code}
            sha = ref_resp.json().get("object", {}).get("sha")
            create_ref = client.post(
                f"https://api.github.com/repos/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch}", "sha": sha},
            )
            if create_ref.status_code not in (201, 422):
                return {"ok": False, "error": "github_branch_failed", "detail": create_ref.text[:500]}
            if isinstance(new_content, str) and path:
                push = _github_push_file(
                    client,
                    repo=repo,
                    branch=branch,
                    path=path,
                    content=new_content,
                    message=_commit_message(approval_rec),
                    headers=headers,
                )
                if not push.get("ok"):
                    return push
            pr_resp = client.post(
                f"https://api.github.com/repos/{repo}/pulls",
                headers=headers,
                json={
                    "title": title,
                    "head": branch,
                    "base": base_branch,
                    "body": pr_body[:65000],
                },
            )
            if pr_resp.status_code >= 400:
                return {"ok": False, "error": "github_pr_failed", "detail": pr_resp.text[:500]}
            data = pr_resp.json()
            return {
                "ok": True,
                "provider": "github",
                "auth_mode": auth_mode,
                "pr_url": data.get("html_url"),
                "pr_number": data.get("number"),
                "branch": branch,
            }
    except httpx.HTTPError as exc:
        return {"ok": False, "error": "github_http_error", "detail": str(exc)[:300]}


def create_gitlab_mr(
    *,
    approval_rec: dict[str, Any],
    tenant_id: str | None = None,
    target_branch: str = "main",
) -> dict[str, Any]:
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or "default"
    cfg = _tenant_git_config(tid)["gitlab"]
    token = str(cfg.get("token") or "").strip()
    project_id = str(cfg.get("project_id") or "").strip()
    base_url = str(cfg.get("base_url") or CENTRAL_GITLAB_BASE_URL).rstrip("/")
    if not token or not project_id:
        return {"ok": False, "error": "gitlab_not_configured"}
    approval_id = str(approval_rec.get("approval_id") or "")
    branch = _branch_name(approval_id)
    payload_body = approval_rec.get("payload") if isinstance(approval_rec.get("payload"), dict) else {}
    path = str(payload_body.get("path") or "").lstrip("/")
    new_content = payload_body.get("new_content")
    title = _commit_message(approval_rec)[:200]
    headers = {"PRIVATE-TOKEN": token}
    try:
        with httpx.Client(timeout=45.0) as client:
            branch_resp = client.post(
                f"{base_url}/api/v4/projects/{project_id}/repository/branches",
                headers=headers,
                data={"branch": branch, "ref": target_branch},
            )
            if branch_resp.status_code >= 400 and branch_resp.status_code != 409:
                return {"ok": False, "error": "gitlab_branch_failed", "detail": branch_resp.text[:500]}
            if isinstance(new_content, str) and path:
                commit_resp = client.post(
                    f"{base_url}/api/v4/projects/{project_id}/repository/commits",
                    headers=headers,
                    data={
                        "branch": branch,
                        "commit_message": _commit_message(approval_rec)[:500],
                        "actions": json.dumps(
                            [{"action": "create", "file_path": path, "content": new_content}]
                        ),
                    },
                )
                if commit_resp.status_code == 400:
                    commit_resp = client.post(
                        f"{base_url}/api/v4/projects/{project_id}/repository/commits",
                        headers=headers,
                        data={
                            "branch": branch,
                            "commit_message": _commit_message(approval_rec)[:500],
                            "actions": json.dumps(
                                [{"action": "update", "file_path": path, "content": new_content}]
                            ),
                        },
                    )
                if commit_resp.status_code >= 400:
                    return {"ok": False, "error": "gitlab_push_failed", "detail": commit_resp.text[:500]}
            mr_resp = client.post(
                f"{base_url}/api/v4/projects/{project_id}/merge_requests",
                headers=headers,
                data={
                    "title": title,
                    "description": _pr_body_from_approval(approval_rec)[:65000],
                    "source_branch": branch,
                    "target_branch": target_branch,
                },
            )
            if mr_resp.status_code >= 400:
                return {"ok": False, "error": "gitlab_mr_failed", "detail": mr_resp.text[:500]}
            data = mr_resp.json()
            return {
                "ok": True,
                "provider": "gitlab",
                "mr_url": data.get("web_url"),
                "mr_iid": data.get("iid"),
                "branch": branch,
            }
    except httpx.HTTPError as exc:
        return {"ok": False, "error": "gitlab_http_error", "detail": str(exc)[:300]}


def maybe_create_pr_after_approval(
    rec: dict[str, Any],
    *,
    provider: str = "github",
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    if rec.get("status") != "approved":
        return None
    body = rec.get("payload")
    if not isinstance(body, dict):
        return None
    path = str(body.get("path") or "")
    if resolve_write_mode_for_path(path, tenant_id=tenant_id) != "pr_only":
        return None
    if provider == "gitlab":
        out = create_gitlab_mr(approval_rec=rec, tenant_id=tenant_id)
    else:
        out = create_github_pr(approval_rec=rec, tenant_id=tenant_id)
    if out.get("ok"):
        from uuid import uuid4

        out["job_id"] = f"pr-{uuid4().hex[:12]}"
        out["mode"] = "pr_only"
    return out
