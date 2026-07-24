"""Jira Cloud REST v3 client (minimal: create issue)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import JiraSettings
from app.jira.adf import adf_to_plain_text, plain_text_to_adf
from app.stellar.user_map import pick_account_id_from_search

logger = logging.getLogger(__name__)


class JiraAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class JiraClient:
    def __init__(self, j: JiraSettings, *, timeout: float = 60.0) -> None:
        if not j.jira_base_url or not j.jira_user_email or not j.jira_api_token:
            raise ValueError("Jira base URL, user email, and API token are required")
        self._j = j
        self._base = str(j.jira_base_url).rstrip("/")
        self._auth = (str(j.jira_user_email), str(j.jira_api_token))
        self._timeout = httpx.Timeout(timeout)
        self._http: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> JiraClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def get_issue(self, issue_key: str, *, fields: list[str] | None = None) -> dict[str, Any]:
        key = str(issue_key or "").strip()
        if not key:
            raise ValueError("issue_key is required")
        url = f"{self._base}/rest/api/3/issue/{key}"
        params: dict[str, str] = {}
        if fields:
            params["fields"] = ",".join(fields)
        r = await self._client().get(
            url,
            auth=self._auth,
            params=params or None,
            headers={"Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} fetching issue {key}",
                status_code=r.status_code,
                body=_safe_json(r),
            )
        data = r.json()
        return data if isinstance(data, dict) else {}

    async def get_comment(self, issue_key: str, comment_id: str) -> dict[str, Any]:
        key = str(issue_key or "").strip()
        cid = str(comment_id or "").strip()
        if not key or not cid:
            raise ValueError("issue_key and comment_id are required")
        url = f"{self._base}/rest/api/3/issue/{key}/comment/{cid}"
        r = await self._client().get(url, auth=self._auth, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} fetching comment {cid} on {key}",
                status_code=r.status_code,
                body=_safe_json(r),
            )
        data = r.json()
        return data if isinstance(data, dict) else {}

    async def list_comments(
        self,
        issue_key: str,
        *,
        max_results: int = 30,
    ) -> list[dict[str, Any]]:
        """List recent comments on an issue."""
        key = str(issue_key or "").strip()
        if not key:
            raise ValueError("issue_key is required")
        limit = max(1, min(int(max_results), 100))
        url = f"{self._base}/rest/api/3/issue/{key}/comment"
        r = await self._client().get(
            url,
            auth=self._auth,
            params={"maxResults": limit, "orderBy": "-created"},
            headers={"Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} listing comments on {key}",
                status_code=r.status_code,
                body=_safe_json(r),
            )
        payload = r.json()
        data = payload if isinstance(payload, dict) else {}
        comments = data.get("comments")
        if not isinstance(comments, list):
            return []
        return [c for c in comments if isinstance(c, dict)]

    @staticmethod
    def comment_plain_text(comment: dict[str, Any]) -> str:
        body = comment.get("body")
        if isinstance(body, dict):
            return adf_to_plain_text(body).strip()
        return str(body or "").strip()

    @staticmethod
    def comment_author_label(comment: dict[str, Any]) -> str:
        author = comment.get("author")
        if isinstance(author, dict):
            name = author.get("displayName") or author.get("emailAddress")
            if name and str(name).strip():
                return str(name).strip()
        return "Jira"

    async def add_comment(self, issue_key: str, body_text: str) -> dict[str, Any]:
        """POST a plain-text comment (converted to ADF) on an issue."""
        key = str(issue_key or "").strip()
        text = str(body_text or "").strip()
        if not key:
            raise ValueError("issue_key is required")
        if not text:
            raise ValueError("comment body is required")
        url = f"{self._base}/rest/api/3/issue/{key}/comment"
        payload = {"body": plain_text_to_adf(text[:32000])}
        r = await self._client().post(
            url,
            auth=self._auth,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} adding comment on {key}",
                status_code=r.status_code,
                body=_safe_json(r),
            )
        data = r.json()
        return data if isinstance(data, dict) else {}

    async def update_issue(self, issue_key: str, fields: dict[str, Any]) -> None:
        key = str(issue_key or "").strip()
        if not key:
            raise ValueError("issue_key is required")
        url = f"{self._base}/rest/api/3/issue/{key}"
        r = await self._client().put(
            url,
            auth=self._auth,
            json={"fields": fields},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} updating issue {key}",
                status_code=r.status_code,
                body=_safe_json(r),
            )

    async def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        key = str(issue_key or "").strip()
        if not key:
            raise ValueError("issue_key is required")
        url = f"{self._base}/rest/api/3/issue/{key}/transitions"
        r = await self._client().get(url, auth=self._auth, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} listing transitions for {key}",
                status_code=r.status_code,
                body=_safe_json(r),
            )
        data = r.json()
        if not isinstance(data, dict):
            return []
        batch = data.get("transitions")
        return [x for x in batch if isinstance(x, dict)] if isinstance(batch, list) else []

    async def transition_issue(self, issue_key: str, transition_id: str) -> None:
        key = str(issue_key or "").strip()
        tid = str(transition_id or "").strip()
        if not key or not tid:
            raise ValueError("issue_key and transition_id are required")
        url = f"{self._base}/rest/api/3/issue/{key}/transitions"
        r = await self._client().post(
            url,
            auth=self._auth,
            json={"transition": {"id": tid}},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} transitioning issue {key}",
                status_code=r.status_code,
                body=_safe_json(r),
            )

    async def find_user_account_id_by_email(
        self,
        email: str,
        *,
        mapped_account_id: str | None = None,
    ) -> str | None:
        if mapped_account_id and str(mapped_account_id).strip():
            return str(mapped_account_id).strip()
        needle = str(email or "").strip()
        if not needle or "@" not in needle:
            return None
        url = f"{self._base}/rest/api/3/user/search"
        params = {"query": needle, "maxResults": 10}
        r = await self._client().get(
            url,
            auth=self._auth,
            params=params,
            headers={"Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} searching user {needle}",
                status_code=r.status_code,
                body=_safe_json(r),
            )
        data = r.json()
        if not isinstance(data, list):
            return None
        return pick_account_id_from_search(needle, data)

    async def set_assignee_by_email(self, issue_key: str, email: str) -> None:
        key = str(issue_key or "").strip()
        account_id = await self.find_user_account_id_by_email(email)
        if not account_id:
            raise JiraAPIError(
                f"No Jira user accountId for email {email}",
                status_code=None,
                body=None,
            )
        await self.update_issue(key, {"assignee": {"accountId": account_id}})

    async def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/rest/api/3/issue"
        r = await self._client().post(
            url,
            auth=self._auth,
            json={"fields": fields},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise JiraAPIError(
                f"Jira HTTP {r.status_code} creating issue",
                status_code=r.status_code,
                body=_safe_json(r),
            )
        return r.json()

    @staticmethod
    def _field_errors_from_body(body: Any) -> set[str]:
        if not isinstance(body, dict):
            return set()
        errors = body.get("errors")
        if not isinstance(errors, dict):
            return set()
        return {str(k) for k in errors}

    async def _update_issue_best_effort(self, issue_key: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        try:
            await self.update_issue(issue_key, fields)
            return
        except JiraAPIError as e:
            rejected = self._field_errors_from_body(e.body)
            if e.status_code != 400 or not rejected:
                logger.warning(
                    "jira post-create field update failed issue_key=%s: %s",
                    issue_key,
                    e,
                )
                return
            retry = {k: v for k, v in fields.items() if k not in rejected}
            if not retry:
                return
            try:
                await self.update_issue(issue_key, retry)
            except JiraAPIError as e2:
                logger.warning(
                    "jira post-create field update partial fail issue_key=%s: %s",
                    issue_key,
                    e2,
                )

    async def create_issue_resilient(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create issue; on screen-restricted fields, create minimal issue then PUT deferred fields."""
        try:
            return await self.create_issue(fields)
        except JiraAPIError as e:
            rejected = self._field_errors_from_body(e.body)
            if e.status_code != 400 or not rejected or not rejected.issubset(set(fields)):
                raise
            initial = {k: v for k, v in fields.items() if k not in rejected}
            if not initial.get("project") or not initial.get("issuetype") or not initial.get("summary"):
                raise
            res = await self.create_issue(initial)
            key = str(res.get("key") or "").strip()
            deferred = {k: fields[k] for k in rejected if k in fields}
            if key and deferred:
                await self._update_issue_best_effort(key, deferred)
                res["deferred_fields"] = sorted(deferred)
            return res

    async def search_issues(
        self,
        jql: str,
        *,
        fields: list[str] | None = None,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Run JQL and return all matching issues (paginated). Uses ``/rest/api/3/search/jql``."""
        url = f"{self._base}/rest/api/3/search/jql"
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        while True:
            body: dict[str, Any] = {"jql": jql, "maxResults": max_results}
            if fields:
                body["fields"] = fields
            if next_page_token:
                body["nextPageToken"] = next_page_token
            r = await self._client().post(url, auth=self._auth, json=body, headers=headers)
            if r.status_code >= 400:
                raise JiraAPIError(
                    f"Jira HTTP {r.status_code} searching issues",
                    status_code=r.status_code,
                    body=_safe_json(r),
                )
            data = r.json()
            batch = data.get("issues")
            if isinstance(batch, list):
                issues.extend(x for x in batch if isinstance(x, dict))
            if data.get("isLast") is True:
                break
            token = data.get("nextPageToken")
            if not token or not isinstance(token, str):
                break
            next_page_token = token
        return issues

    async def find_issue_key_for_cortex_incident(self, project_key: str, incident_id: str) -> str | None:
        """Recover Jira key after a crash between create and SQLite record (description contains incident id)."""
        iid = str(incident_id).strip()
        if not iid:
            return None
        needle = f"XDR Incident ID: {iid}"
        jql = f'project = "{project_key}" AND description ~ "{_jql_escape(needle)}"'
        issues = await self.search_issues(jql, fields=["key"], max_results=5)
        for issue in issues:
            key = str(issue.get("key") or "").strip()
            if key:
                return key
        return None

    async def find_issue_key_for_stellar_case(self, project_key: str, case_id: str) -> str | None:
        """Recover Jira key after a crash between create and SQLite record."""
        cid = str(case_id).strip()
        if not cid:
            return None
        needle = f"Stellar Case ID: {cid}"
        jql = f'project = "{project_key}" AND description ~ "{_jql_escape(needle)}"'
        issues = await self.search_issues(jql, fields=["key"], max_results=5)
        for issue in issues:
            key = str(issue.get("key") or "").strip()
            if key:
                return key
        label = f"stellar-case-{cid[:12]}"
        jql_label = f'project = "{project_key}" AND labels = "{_jql_escape(label)}"'
        issues = await self.search_issues(jql_label, fields=["key"], max_results=5)
        for issue in issues:
            key = str(issue.get("key") or "").strip()
            if key:
                return key
        return None


def _jql_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
