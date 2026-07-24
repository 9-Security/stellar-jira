"""Jira → Stellar write-back webhook."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_stellar_settings
from app.stellar.writeback import apply_jira_to_stellar_writeback
from app.sync.lock import SyncLockError, sync_process_lock

_REPO_ROOT = Path(__file__).resolve().parents[2]

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class JiraStellarWebhookBody(BaseModel):
    """Jira Automation or manual POST body."""

    issue_key: str | None = Field(default=None, alias="issueKey")
    issue: dict[str, Any] | None = None
    stellar_case_id: str | None = Field(default=None, alias="stellarCaseId")
    severity: str | None = None
    status: str | None = None
    assignee: str | None = None
    resolution_tag: str | None = Field(default=None, alias="resolutionTag")
    comment_id: str | None = Field(default=None, alias="commentId")
    comment_text: str | None = Field(default=None, alias="commentText")
    sync_fields: bool = Field(default=True, alias="syncFields")
    dry_run: bool = Field(default=False, alias="dryRun")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    def resolved_issue_key(self) -> str | None:
        if self.issue_key and str(self.issue_key).strip():
            return str(self.issue_key).strip().upper()
        if isinstance(self.issue, dict):
            key = self.issue.get("key")
            if key and str(key).strip():
                return str(key).strip().upper()
        return None

    def wants_comment(self) -> bool:
        return bool(
            (self.comment_id and str(self.comment_id).strip())
            or (self.comment_text and str(self.comment_text).strip())
        )


def require_stellar_webhook_token(
    x_stellar_webhook_token: str | None,
    x_sync_token: str | None,
) -> None:
    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    sync_token = (st.sync_api_token or "").strip()
    token = (st.stellar_webhook_token or "").strip() or sync_token
    if not token:
        raise HTTPException(
            status_code=503,
            detail="STELLAR_WEBHOOK_TOKEN or SYNC_API_TOKEN is not configured",
        )
    presented = (x_stellar_webhook_token or x_sync_token or "").strip()
    if not presented or not secrets.compare_digest(presented, token):
        raise HTTPException(status_code=403, detail="Invalid or missing webhook token")


def _sync_lock_path() -> Path:
    st = get_stellar_settings()
    lock_path = _REPO_ROOT / st.stellar_sync_state_db
    return lock_path.with_suffix(lock_path.suffix + ".lock")


def _writeback_http_status(result: dict[str, Any]) -> int:
    if result.get("ok"):
        return 200
    if result.get("error") == "sync_lock":
        return 409
    upstream = result.get("http_status")
    if isinstance(upstream, int):
        if upstream in (401, 403):
            return 502
        if upstream == 404:
            return 404
        if upstream >= 500:
            return 502
    err = str(result.get("error") or "").lower()
    if "not found" in err:
        return 404
    return 400


def _writeback_response(result: dict[str, Any]) -> JSONResponse:
    return JSONResponse(content=result, status_code=_writeback_http_status(result))


@router.post("/jira-stellar")
async def jira_stellar_webhook(
    body: JiraStellarWebhookBody,
    x_stellar_webhook_token: str | None = Header(default=None, alias="X-Stellar-Webhook-Token"),
    x_sync_token: str | None = Header(default=None, alias="X-Sync-Token"),
) -> dict[str, Any]:
    """
    Push Jira AIxSOC changes to Stellar Case.

    - Fields (default): assignee, 嚴重程度, 事件狀態, resolution tag → ``PUT /cases/{id}``
    - Comment: ``commentId`` or ``commentText`` → ``POST /cases/{id}/comments``
    """
    require_stellar_webhook_token(x_stellar_webhook_token, x_sync_token)
    issue_key = body.resolved_issue_key()
    if not issue_key:
        raise HTTPException(status_code=400, detail="issueKey or issue.key is required")

    overrides: dict[str, Any] = {}
    for key in ("severity", "status", "assignee", "resolution_tag"):
        val = getattr(body, key, None)
        if val is not None and str(val).strip():
            overrides[key] = str(val).strip()

    sync_fields = body.sync_fields
    if body.wants_comment() and not sync_fields:
        sync_fields = False
    elif body.wants_comment() and body.sync_fields:
        pass
    elif not body.wants_comment():
        sync_fields = True

    try:
        with sync_process_lock(_sync_lock_path()):
            result = await apply_jira_to_stellar_writeback(
                issue_key=issue_key,
                stellar_case_id=body.stellar_case_id,
                field_overrides=overrides or None,
                dry_run=body.dry_run,
                sync_fields=sync_fields,
                jira_comment_id=body.comment_id,
                comment_text=body.comment_text,
            )
    except SyncLockError as e:
        return _writeback_response(
            {
                "ok": False,
                "error": "sync_lock",
                "detail": str(e),
                "issue_key": issue_key,
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _writeback_response(result)
