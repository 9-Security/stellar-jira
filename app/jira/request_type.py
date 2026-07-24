"""Jira Service Management Request Type (customfield_10010) helpers."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import JiraSettings
from app.jira.client import JiraAPIError, JiraClient


def request_type_field_value(portal_key: str, request_type_key: str) -> str:
    """Value for Request Type on POST /rest/api/3/issue (JSM Cloud)."""
    return f"{portal_key.strip()}/{request_type_key.strip()}"


async def _portal_key_and_type_key_for_request_type(
    jira: JiraSettings,
    *,
    service_desk_id: str,
    request_type_id: str,
    issue_type_id: str,
) -> tuple[str, str] | None:
    """Resolve portalKey + requestTypeKey via agent API (list endpoint omits ``key``)."""
    if not jira.jira_project_key:
        return None
    base = str(jira.jira_base_url).rstrip("/")
    auth = (str(jira.jira_user_email), str(jira.jira_api_token))
    jql = f'project = {jira.jira_project_key} AND issuetype = {issue_type_id} ORDER BY created DESC'
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{base}/rest/api/3/search/jql",
            auth=auth,
            json={"jql": jql, "maxResults": 1, "fields": ["issuetype"]},
        )
        if r.status_code >= 400:
            return None
        issues = r.json().get("issues") or []
        if not issues:
            return None
        internal_id = str(issues[0].get("id") or "")
        if not internal_id:
            return None
        r2 = await client.get(
            f"{base}/rest/servicedesk/1/servicedesk/request/{internal_id}/request-types",
            auth=auth,
        )
    if r2.status_code >= 400:
        return None
    for rt in r2.json().get("validRequestTypes") or []:
        if not isinstance(rt, dict):
            continue
        if str(rt.get("id") or "") != str(request_type_id):
            continue
        portal = str(rt.get("portalKey") or "").strip()
        key = str(rt.get("key") or "").strip()
        if portal and key:
            return portal, key
    return None


async def service_desk_id_for_project(jira: JiraSettings) -> str | None:
    """Resolve service desk id from env or by matching ``jira_project_key``."""
    explicit = (jira.jira_service_desk_id or "").strip()
    if explicit:
        return explicit
    pkey = (jira.jira_project_key or "").strip().upper()
    if not pkey or not jira.jira_base_url:
        return None
    base = str(jira.jira_base_url).rstrip("/")
    auth = (str(jira.jira_user_email), str(jira.jira_api_token))
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(
            f"{base}/rest/servicedeskapi/servicedesk",
            auth=auth,
            headers={"Accept": "application/json"},
        )
    if r.status_code >= 400:
        return None
    for sd in r.json().get("values") or []:
        if not isinstance(sd, dict):
            continue
        if str(sd.get("projectKey") or "").strip().upper() == pkey:
            sid = str(sd.get("id") or "").strip()
            return sid or None
    return None


async def list_request_types_for_service_desk(
    jira: JiraSettings,
    service_desk_id: str,
) -> list[dict[str, Any]]:
    if not jira.jira_base_url:
        return []
    base = str(jira.jira_base_url).rstrip("/")
    url = f"{base}/rest/servicedeskapi/servicedesk/{service_desk_id}/requesttype"
    auth = (str(jira.jira_user_email), str(jira.jira_api_token))
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, auth=auth, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise JiraAPIError(
            f"Jira HTTP {r.status_code} listing request types",
            status_code=r.status_code,
            body=r.text,
        )
    data = r.json()
    values = data.get("values")
    return values if isinstance(values, list) else []


async def resolve_request_type_value(
    jira: JiraSettings,
    *,
    issue_type_id: str,
) -> str | None:
    """
    Return ``portalKey/requestTypeKey`` for JSM Request Type field, or None.

    Uses ``JIRA_REQUEST_TYPE_VALUE`` when set; otherwise matches ``issue_type_id``
    against ``JIRA_SERVICE_DESK_ID`` request types from the Service Desk API.
    """
    explicit = (jira.jira_request_type_value or "").strip()
    if explicit:
        return explicit

    desk_id = await service_desk_id_for_project(jira)
    tid = str(issue_type_id or "").strip()
    if not desk_id or not tid:
        return None

    for rt in await list_request_types_for_service_desk(jira, desk_id):
        if not isinstance(rt, dict):
            continue
        if str(rt.get("issueTypeId") or "") != tid:
            continue
        portal = str(rt.get("portalKey") or rt.get("_portalKey") or "").strip()
        key = str(rt.get("key") or "").strip()
        if portal and key:
            return request_type_field_value(portal, key)
        rt_id = str(rt.get("id") or "").strip()
        if rt_id:
            pair = await _portal_key_and_type_key_for_request_type(
                jira,
                service_desk_id=desk_id,
                request_type_id=rt_id,
                issue_type_id=tid,
            )
            if pair:
                return request_type_field_value(pair[0], pair[1])
    return None
