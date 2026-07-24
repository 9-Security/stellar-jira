"""Jira AIxSOC → Stellar Cyber write-back (fields, resolution tag, comments)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import JiraSettings, StellarSettings, get_jira_settings, get_stellar_settings
from app.http.upstream_errors import upstream_error_detail
from app.jira.adf import adf_to_plain_text
from app.jira.client import JiraAPIError, JiraClient
from app.stellar.client import StellarAPIError, StellarClient
from app.stellar.field_map import load_stellar_jira_field_map
from app.stellar.jira_assignee_update import jira_assignee_email as _jira_assignee_email_from_fields
from app.stellar.jira_assignee_update import load_user_map_for_settings
from app.stellar.jira_draft import _severity_to_jira_option, _stellar_status_to_jira_option
from app.stellar.status_sync import jira_workflow_status_name, stellar_status_from_jira_fields
from app.stellar.resolution_tag import (
    jira_resolution_label_from_fields,
    load_resolution_tag_map,
    stellar_put_body_for_jira_resolution_tag,
    stellar_tags_from_case,
)
from app.sync.state import SyncState

REPO_ROOT = Path(__file__).resolve().parents[2]
_STELLAR_CASE_ID_RE = re.compile(r"Stellar Case ID:\s*([0-9a-f]{24})", re.I)
_COMMENT_META_PREFIX = "stellar_wb_jira_comment:"
_STELLAR_NEWER_BUFFER_MS = 3000
_JIRA_TERMINAL_WORKFLOW = frozenset({"Resolved", "Closed", "Done", "Cancelled"})
_WB_JIRA_WORKFLOW_PREFIX = "wb_jira_workflow:"
logger = logging.getLogger(__name__)


def _jira_updated_ms(fields: dict[str, Any]) -> int:
    raw = fields.get("updated")
    if not raw:
        return 0
    s = str(raw).strip()
    m = re.match(
        r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)([+-]\d{2})(\d{2})$",
        s,
    )
    if m:
        s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    try:
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except ValueError:
        return 0


def _stellar_newer_than_jira(current_case: dict[str, Any], jira_fields: dict[str, Any]) -> bool:
    """When Stellar was edited after Jira, inbound sync owns status/assignee — skip write-back."""
    stellar_mod = int(current_case.get("modified_at") or 0)
    jira_mod = _jira_updated_ms(jira_fields)
    if stellar_mod <= 0 or jira_mod <= 0:
        return False
    return stellar_mod > jira_mod + _STELLAR_NEWER_BUFFER_MS


def _jira_workflow_is_terminal(jira_fields: dict[str, Any]) -> bool:
    wf = jira_workflow_status_name(jira_fields)
    return bool(wf and wf in _JIRA_TERMINAL_WORKFLOW)


def _wb_jira_workflow_meta_key(issue_key: str) -> str:
    return f"{_WB_JIRA_WORKFLOW_PREFIX}{str(issue_key or '').strip().upper()}"


def apply_jira_workflow_change_guard(
    *,
    state: SyncState,
    issue_key: str,
    jira_fields: dict[str, Any],
    desired: dict[str, Any],
    result: dict[str, Any],
    dry_run: bool = False,
) -> None:
    """Only writeback status when Jira *workflow* status changed (not comment/assignee bumps).

    Jira ``updated`` moves on activity comments and assignee sync; using it alone made
    writeback re-apply Open/New and clobber a fresher Stellar In Progress. We remember the
    last seen workflow name per issue and skip status unless it changed. First observation
    seeds the baseline without pushing non-terminal status onto Stellar.
    """
    if not desired.get("status"):
        return
    curr = jira_workflow_status_name(jira_fields) or ""
    meta_key = _wb_jira_workflow_meta_key(issue_key)
    prev = state.get_meta(meta_key)
    if prev is not None and prev == curr:
        desired["status"] = None
        result["status_writeback_skipped"] = "jira_workflow_unchanged"
    elif prev is None and not _jira_workflow_is_terminal(jira_fields):
        desired["status"] = None
        result["status_writeback_skipped"] = "seed_workflow_baseline"
    if not dry_run and curr:
        state.set_meta(meta_key, curr)


def apply_stellar_newer_field_guard(
    *,
    st: StellarSettings | Any,
    desired: dict[str, Any],
    jira_fields: dict[str, Any],
    flags: dict[str, bool],
    result: dict[str, Any],
) -> None:
    """When Stellar ``modified_at`` is newer than Jira ``updated``, keep Stellar-led assignee.

    Status is owned by ``apply_jira_workflow_change_guard`` (only when Jira workflow changes
    or Jira is terminal on first seed). Do not clear a real Jira workflow change here.
    """
    del st, jira_fields
    if not flags.get("assignee"):
        desired["assignee"] = None

    status_kept = bool(desired.get("status"))
    assignee_kept = bool(desired.get("assignee"))
    if not status_kept and not assignee_kept:
        result["writeback_deferred"] = (
            "stellar_modified_newer_than_jira; mirror/inbound will push Stellar→Jira"
        )
    elif status_kept or assignee_kept:
        result["writeback_despite_stellar_newer"] = True
        if status_kept:
            result["writeback_terminal_status_override"] = True

_STELLAR_SEVERITIES = frozenset({"Critical", "High", "Medium", "Low"})
_STELLAR_STATUSES = frozenset({"New", "Escalated", "In Progress", "Resolved", "Cancelled"})


def _jira_select_value(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("value", "name"):
            v = raw.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None
    s = str(raw).strip()
    return s or None


def jira_severity_to_stellar(label: str | None) -> str | None:
    if not label:
        return None
    normalized = _severity_to_jira_option(label)
    if normalized in _STELLAR_SEVERITIES:
        return normalized
    return None


def jira_status_to_stellar(label: str | None) -> str | None:
    if not label:
        return None
    mapped = _stellar_status_to_jira_option(label)
    if mapped and mapped in _STELLAR_STATUSES:
        return mapped
    return None


def _effective_writeback_field_flags(st: StellarSettings) -> dict[str, bool]:
    """Duty platform: only resolution/comments by default; legacy Jira-master enables status/assignee."""
    if st.stellar_jira_master_after_link:
        return {
            "status": True,
            "assignee": True,
            "severity": st.stellar_writeback_sync_severity,
        }
    return {
        "status": st.stellar_writeback_sync_status,
        "assignee": st.stellar_writeback_sync_assignee,
        "severity": st.stellar_writeback_sync_severity,
    }


def _filter_writeback_desired(st: StellarSettings, desired: dict[str, str | None]) -> None:
    flags = _effective_writeback_field_flags(st)
    if not flags["status"]:
        desired["status"] = None
    if not flags["assignee"]:
        desired["assignee"] = None
    if not flags["severity"]:
        desired["severity"] = None


def extract_writeback_from_jira_fields(
    fields: dict[str, Any],
    *,
    severity_field_id: str,
    status_field_id: str,
    resolution_field_id: str | None = None,
    tag_map: Any = None,
    prefer_workflow: bool = True,
    sync_custom_status: bool = True,
    user_map: Any = None,
) -> dict[str, str | None]:
    """Jira Workflow + 事件狀態 + Assignee → Stellar (status / assignee); optional severity & resolution tag."""
    res_label = None
    if tag_map is not None:
        res_label = jira_resolution_label_from_fields(fields, tag_map)
    return {
        "severity": jira_severity_to_stellar(_jira_select_value(fields.get(severity_field_id))),
        "status": stellar_status_from_jira_fields(
            fields,
            status_field_id=status_field_id,
            prefer_workflow=prefer_workflow,
            sync_custom_status=sync_custom_status,
        ),
        "assignee": _jira_assignee_email_from_fields(fields, user_map=user_map),
        "resolution_tag": res_label,
    }


def _parse_stellar_case_id_from_description(fields: dict[str, Any]) -> str | None:
    desc = fields.get("description")
    text = adf_to_plain_text(desc) if isinstance(desc, dict) else str(desc or "")
    m = _STELLAR_CASE_ID_RE.search(text)
    return m.group(1) if m else None


def resolve_stellar_case_id(
    state: SyncState,
    *,
    source_id: str,
    jira_key: str,
    jira_fields: dict[str, Any] | None = None,
    override_case_id: str | None = None,
) -> str | None:
    override = str(override_case_id or "").strip() or None
    mapped = state.lookup_incident_by_jira_key(jira_key, source_id=source_id)
    from_desc = _parse_stellar_case_id_from_description(jira_fields) if jira_fields else None
    trusted = mapped or from_desc

    if override:
        if trusted and override != trusted:
            raise ValueError(
                f"stellarCaseId {override!r} conflicts with mapped case {trusted!r} for {jira_key}"
            )
        if trusted:
            return trusted
        logger.warning(
            "ignoring stellarCaseId override without SQLite/Jira mapping jira_key=%s override=%s",
            jira_key,
            override,
        )

    if mapped:
        return mapped
    if from_desc:
        return from_desc
    return None


def build_stellar_update_body(
    desired: dict[str, str | None],
    current_case: dict[str, Any],
    *,
    tag_map: Any = None,
) -> dict[str, Any]:
    """PUT body for severity / status / assignee / resolution tag (only changed keys)."""
    body: dict[str, Any] = {}
    sev = desired.get("severity")
    if sev and str(current_case.get("severity") or "") != sev:
        body["severity"] = sev

    status = desired.get("status")
    if status and str(current_case.get("status") or "") != status:
        body["status"] = status

    email = desired.get("assignee")
    if email:
        cur = str(
            current_case.get("assignee")
            or current_case.get("assignee_name")
            or ""
        ).strip()
        if cur.lower() != email.lower():
            body["assignee"] = email

    res_label = desired.get("resolution_tag")
    if res_label and tag_map is not None and tag_map.jira_to_stellar.get(res_label):
        current_tags = stellar_tags_from_case(current_case)
        mapped = tag_map.jira_to_stellar[res_label]
        known = set(tag_map.jira_to_stellar.values())
        other_resolution = [t for t in current_tags if t in known and t != mapped]
        if mapped not in current_tags or other_resolution:
            frag = stellar_put_body_for_jira_resolution_tag(
                res_label,
                tag_map,
                current_tags=current_tags,
                apply_resolve_status=not bool(status),
            )
            _merge_put_fragments(body, frag)

    return body


def _merge_put_fragments(target: dict[str, Any], fragment: dict[str, Any]) -> None:
    for key, val in fragment.items():
        if key == "tags" and isinstance(val, dict) and isinstance(target.get("tags"), dict):
            merged = dict(target["tags"])
            for op in ("add", "delete"):
                items = val.get(op)
                if isinstance(items, list):
                    existing = merged.get(op) or []
                    merged[op] = list(existing) + [x for x in items if x not in existing]
            target["tags"] = merged
        else:
            target[key] = val


def _merge_desired(
    base: dict[str, str | None],
    overrides: dict[str, Any] | None,
) -> dict[str, str | None]:
    out = dict(base)
    if not overrides:
        return out
    for key in ("severity", "status", "assignee", "resolution_tag"):
        if key not in overrides:
            continue
        val = overrides.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if not s:
            continue
        if key == "severity":
            out["severity"] = jira_severity_to_stellar(s) or s
        elif key == "status":
            out["status"] = jira_status_to_stellar(s) or s
        elif key == "resolution_tag":
            out["resolution_tag"] = s
        else:
            out["assignee"] = s
    return out


def _comment_meta_key(issue_key: str, comment_id: str) -> str:
    return f"{_COMMENT_META_PREFIX}{issue_key}:{comment_id}"


def _comment_already_synced(state: SyncState, issue_key: str, comment_id: str) -> bool:
    return state.get_meta(_comment_meta_key(issue_key, comment_id)) == "1"


def _mark_comment_synced(state: SyncState, issue_key: str, comment_id: str) -> None:
    state.set_meta(_comment_meta_key(issue_key, comment_id), "1")


def format_stellar_comment(*, jira_key: str, author: str, text: str) -> str:
    body = str(text or "").strip()
    if not body:
        raise ValueError("comment text is empty")
    author_s = str(author or "Jira").strip()
    prefix = f"[Jira {jira_key}] {author_s}: "
    max_len = 8000
    room = max_len - len(prefix)
    if room < 1:
        return prefix[:max_len]
    return prefix + body[:room]


async def _fetch_jira_comment_text(
    jira: JiraClient,
    issue_key: str,
    *,
    comment_id: str | None,
    comment_text: str | None,
) -> tuple[str, str | None, str]:
    """Return (plain_text, comment_id, author_label)."""
    if comment_text and str(comment_text).strip():
        return str(comment_text).strip(), comment_id, "Jira"
    if not comment_id or not str(comment_id).strip():
        raise ValueError("comment_id or comment_text is required for comment sync")
    cid = str(comment_id).strip()
    raw = await jira.get_comment(issue_key, cid)
    text = JiraClient.comment_plain_text(raw)
    if not text:
        raise ValueError(f"Jira comment {cid} has no text body")
    return text, cid, JiraClient.comment_author_label(raw)


def _handle_jira_fetch_error(
    state: SyncState,
    *,
    source_id: str,
    issue_key: str,
    stellar_case_id: str | None,
    exc: JiraAPIError,
) -> dict[str, Any]:
    """On Jira 404, drop stale SQLite mapping so writeback stops retrying."""
    detail = upstream_error_detail(exc)
    if exc.status_code != 404:
        return {"ok": False, "issue_key": issue_key, **detail}

    stale_case_id = (
        str(stellar_case_id or "").strip()
        or state.lookup_incident_by_jira_key(issue_key, source_id=source_id)
    )
    if stale_case_id and state.remove_incident_link(source_id, stale_case_id):
        logger.warning(
            "removed stale jira mapping after 404 issue_key=%s case_id=%s",
            issue_key,
            stale_case_id,
        )
        return {
            "ok": True,
            "skipped": True,
            "issue_key": issue_key,
            "stellar_case_id": stale_case_id,
            "reason": "jira_issue_gone",
            "stale_mapping_removed": True,
        }
    return {"ok": False, "issue_key": issue_key, **detail}


async def apply_jira_to_stellar_writeback(
    *,
    issue_key: str,
    stellar_case_id: str | None = None,
    field_overrides: dict[str, Any] | None = None,
    dry_run: bool = False,
    sync_fields: bool = True,
    jira_comment_id: str | None = None,
    comment_text: str | None = None,
    st: StellarSettings | None = None,
    jira_s: JiraSettings | None = None,
) -> dict[str, Any]:
    """
    Jira → Stellar: Ticket Status / Assignee (+ optional 嚴重程度 / resolution tag), comments (POST).
    """
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    st = st or get_stellar_settings()
    jira_s = jira_s or get_jira_settings()

    if not st.stellar_base_url or not st.stellar_api_key:
        raise ValueError("Set STELLAR_BASE_URL and STELLAR_API_KEY in .env")
    if not jira_s.jira_base_url or not jira_s.jira_user_email or not jira_s.jira_api_token:
        raise ValueError("Set JIRA_BASE_URL, JIRA_USER_EMAIL, and JIRA_API_TOKEN")

    issue_key = str(issue_key or "").strip().upper()
    if not issue_key:
        raise ValueError("issue_key is required")

    want_comment = bool(
        (jira_comment_id and str(jira_comment_id).strip())
        or (comment_text and str(comment_text).strip())
    )
    if not sync_fields and not want_comment:
        raise ValueError("nothing to sync: enable sync_fields or provide a comment")

    fmap = load_stellar_jira_field_map(REPO_ROOT, st.stellar_jira_field_map_path)
    tag_map_path = Path(st.stellar_resolution_tag_map_path)
    if not tag_map_path.is_absolute():
        tag_map_path = REPO_ROOT / tag_map_path
    tag_map = load_resolution_tag_map(tag_map_path)

    sev_fid = st.stellar_jira_severity_field or fmap.get("severity") or "customfield_10057"
    status_fid = st.stellar_jira_status_field or fmap.get("status") or "customfield_10061"
    res_fid = (
        st.stellar_jira_resolution_tag_field
        or fmap.get("resolution_tag")
        or tag_map.jira_field
    )
    jira_field_ids = ["assignee", "status", "updated", sev_fid, "description"]
    if status_fid and status_fid not in jira_field_ids:
        jira_field_ids.append(status_fid)
    if res_fid and res_fid not in jira_field_ids:
        jira_field_ids.append(res_fid)

    state_path = REPO_ROOT / st.stellar_sync_state_db
    state = SyncState(state_path)
    state.init(legacy_source_id=st.stellar_poll_source_id)
    source_id = st.stellar_poll_source_id

    jira = JiraClient(jira_s)
    fields: dict[str, Any] = {}
    case_id = stellar_case_id

    if sync_fields or not case_id:
        fetch_fields = jira_field_ids if sync_fields else ["description"]
        try:
            issue = await jira.get_issue(issue_key, fields=fetch_fields)
        except JiraAPIError as e:
            return _handle_jira_fetch_error(
                state,
                source_id=source_id,
                issue_key=issue_key,
                stellar_case_id=stellar_case_id or case_id,
                exc=e,
            )
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        case_id = resolve_stellar_case_id(
            state,
            source_id=source_id,
            jira_key=issue_key,
            jira_fields=fields,
            override_case_id=stellar_case_id or case_id,
        )
    elif stellar_case_id:
        case_id = resolve_stellar_case_id(
            state,
            source_id=source_id,
            jira_key=issue_key,
            jira_fields=None,
            override_case_id=stellar_case_id,
        )
    else:
        case_id = state.lookup_incident_by_jira_key(issue_key, source_id=source_id)

    if not case_id:
        return {
            "ok": False,
            "issue_key": issue_key,
            "error": "stellar_case_id not found (SQLite mapping or description Stellar Case ID:)",
        }

    result: dict[str, Any] = {
        "ok": True,
        "issue_key": issue_key,
        "stellar_case_id": case_id,
        "dry_run": dry_run,
    }

    client = StellarClient(
        base_url=str(st.stellar_base_url),
        api_key=st.stellar_api_key,
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
    )

    try:
        async with client:
            raw = await client.get_case(case_id)
            current = client.extract_case_one(raw) or {}

            if sync_fields:
                desired = extract_writeback_from_jira_fields(
                    fields,
                    severity_field_id=sev_fid,
                    status_field_id=status_fid,
                    resolution_field_id=res_fid,
                    tag_map=tag_map,
                    prefer_workflow=(
                        True
                        if st.stellar_jira_master_after_link
                        else st.stellar_status_prefer_jira_workflow
                    ),
                    sync_custom_status=st.stellar_sync_jira_custom_status,
                    user_map=load_user_map_for_settings(st),
                )
                desired = _merge_desired(desired, field_overrides)
                _filter_writeback_desired(st, desired)
                flags = _effective_writeback_field_flags(st)
                if flags.get("status"):
                    apply_jira_workflow_change_guard(
                        state=state,
                        issue_key=issue_key,
                        jira_fields=fields,
                        desired=desired,
                        result=result,
                        dry_run=dry_run,
                    )
                if not st.stellar_jira_master_after_link and _stellar_newer_than_jira(current, fields):
                    apply_stellar_newer_field_guard(
                        st=st,
                        desired=desired,
                        jira_fields=fields,
                        flags=flags,
                        result=result,
                    )
                elif st.stellar_jira_master_after_link and _stellar_newer_than_jira(current, fields):
                    result["jira_master_reconcile"] = (
                        "jira_is_master_after_link; applying Jira status/assignee to Stellar"
                    )
                body = build_stellar_update_body(desired, current, tag_map=tag_map)
                result["jira_values"] = {k: v for k, v in desired.items() if v}
                if not body:
                    result["fields"] = {"skipped": True, "reason": "no_changes"}
                elif dry_run:
                    result["fields"] = {"would_update": body}
                else:
                    await client.update_case(case_id, body)
                    result["fields"] = {"updated": body}

            if want_comment:
                plain, cid, author = await _fetch_jira_comment_text(
                    jira,
                    issue_key,
                    comment_id=jira_comment_id,
                    comment_text=comment_text,
                )
                if cid and _comment_already_synced(state, issue_key, cid):
                    result["comment"] = {
                        "skipped": True,
                        "reason": "already_synced",
                        "jira_comment_id": cid,
                    }
                else:
                    stellar_text = format_stellar_comment(
                        jira_key=issue_key, author=author, text=plain
                    )
                    if dry_run:
                        result["comment"] = {
                            "would_post": stellar_text[:500],
                            "jira_comment_id": cid,
                        }
                    else:
                        posted = await client.add_case_comment(case_id, stellar_text)
                        if cid:
                            _mark_comment_synced(state, issue_key, cid)
                        inner = posted.get("data") if isinstance(posted.get("data"), dict) else posted
                        result["comment"] = {
                            "posted": True,
                            "stellar_comment_id": inner.get("_id") if isinstance(inner, dict) else None,
                            "jira_comment_id": cid,
                        }
    except (JiraAPIError, StellarAPIError, ValueError) as e:
        err: dict[str, Any] = {
            "ok": False,
            "issue_key": issue_key,
            "stellar_case_id": case_id,
        }
        if isinstance(e, (JiraAPIError, StellarAPIError)):
            err.update(upstream_error_detail(e))
        else:
            err["error"] = str(e)
        return err

    if st.decision_outcome_on_writeback and sync_fields and not dry_run and fields:
        try:
            from app.decision.jira_notes import (
                OUTCOME_REMINDER_MARKER,
                format_outcome_reminder_comment,
                outcome_remind_meta_key,
            )
            from app.decision.outcome import apply_outcome_from_jira
            from app.decision.pipeline import get_decision_store

            status_raw = fields.get("status")
            status_name = ""
            if isinstance(status_raw, dict):
                status_name = str(status_raw.get("name") or "").strip().lower()
            # Only close the Dataset loop on terminal-ish Jira statuses
            if status_name in (
                "done",
                "resolved",
                "closed",
                "cancelled",
                "canceled",
                "complete",
                "completed",
            ):
                comment_blob = ""
                if isinstance(result.get("comment"), dict):
                    comment_blob = str(result["comment"].get("would_post") or "")
                try:
                    comments = await jira.list_comments(issue_key, max_results=25)
                    parts = [JiraClient.comment_plain_text(c) for c in comments]
                    joined = "\n".join(p for p in parts if p)
                    if joined:
                        comment_blob = f"{comment_blob}\n{joined}".strip()
                except Exception as e:
                    logger.warning("decision outcome comment fetch failed issue=%s: %s", issue_key, e)
                dstore = get_decision_store(REPO_ROOT / st.stellar_sync_state_db)
                outcome = apply_outcome_from_jira(
                    dstore,
                    jira_key=issue_key,
                    fields=fields,
                    source_id=source_id,
                    stellar_case_id=str(case_id or ""),
                    comments_text=comment_blob,
                )
                result["decision_outcome"] = outcome
                if (
                    getattr(st, "decision_outcome_remind_on_writeback", True)
                    and outcome.get("true_positive") is None
                    and OUTCOME_REMINDER_MARKER not in comment_blob
                ):
                    meta_key = outcome_remind_meta_key(issue_key)
                    if not state.get_meta(meta_key):
                        try:
                            await jira.add_comment(
                                issue_key,
                                format_outcome_reminder_comment(jira_key=issue_key),
                            )
                            state.set_meta(meta_key, "1")
                            result["decision_outcome_reminder"] = {"posted": True}
                        except Exception as e:
                            logger.warning(
                                "decision outcome reminder failed issue=%s: %s",
                                issue_key,
                                e,
                            )
                            result["decision_outcome_reminder"] = {
                                "posted": False,
                                "error": str(e),
                            }
        except Exception as e:
            logger.warning("decision outcome writeback failed issue=%s: %s", issue_key, e)

    if sync_fields and result.get("fields", {}).get("skipped") and not want_comment:
        result["skipped"] = True
        result["reason"] = "no_changes"
    return result
