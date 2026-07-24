"""Stellar-only settings (no Cortex). Copied to app/config.py by deploy/export_stellar_tree.sh."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.stellar.severity_filter import parse_allowed_severities

_REPO_ROOT = Path(__file__).resolve().parent.parent


class JiraSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_file_optional=True,
        extra="ignore",
    )

    jira_base_url: AnyHttpUrl | None = Field(default=None)
    jira_user_email: str | None = Field(default=None)
    jira_api_token: str | None = Field(default=None)
    jira_project_key: str | None = Field(default=None)
    jira_issue_type_name: str | None = Field(default=None)
    jira_issue_type_id: str | None = Field(default=None)
    jira_request_type_field: str = Field(default="customfield_10010")
    jira_request_type_value: str | None = Field(default=None)
    jira_service_desk_id: str | None = Field(default=None)

    @field_validator("jira_user_email", "jira_api_token", mode="before")
    @classmethod
    def _strip_jira_only(cls, v: object) -> object:
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s or None

    @field_validator(
        "jira_project_key",
        "jira_issue_type_name",
        "jira_issue_type_id",
        "jira_request_type_field",
        "jira_request_type_value",
        "jira_service_desk_id",
        mode="before",
    )
    @classmethod
    def _strip_jira_project(cls, v: object) -> object:
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s or None


@lru_cache
def get_jira_settings() -> JiraSettings:
    return JiraSettings()


class StellarSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_file_optional=True,
        extra="ignore",
    )

    stellar_base_url: AnyHttpUrl | None = Field(default=None)
    stellar_api_key: str | None = Field(default=None)
    stellar_user_email: str | None = Field(default=None)
    stellar_tenant_id: str | None = Field(default=None)
    stellar_timeout_seconds: float = 60.0
    stellar_http_max_retries: int = Field(default=1, ge=0, le=5)
    stellar_tls_verify: bool = Field(default=True)
    stellar_jira_project_key: str = Field(default="AIXSOC")
    stellar_jira_issue_type_id: str = Field(default="10092")
    stellar_jira_severity_field: str = Field(default="customfield_10057")
    stellar_jira_status_field: str = Field(default="customfield_10061")
    stellar_jira_alert_name_field: str | None = Field(
        default="customfield_10122",
        description="Jira custom field for alert name. Empty = omit (use summary/description).",
    )
    stellar_jira_resolution_tag_field: str | None = Field(default="customfield_10201")
    stellar_resolution_tag_map_path: str = Field(default="config/stellar_resolution_tag_map.json")
    stellar_sync_state_db: str = Field(default="data/stellar_sync_state.sqlite")
    stellar_case_id_prefix: str = Field(default="XSOC")
    stellar_case_id_timezone: str = Field(default="Asia/Taipei")
    stellar_case_id_jira_field: str = Field(default="customfield_10060")
    stellar_summary_template: str = Field(default="[{severity}][{event_name}][{customer_code}]")
    stellar_default_customer_code: str | None = Field(default=None)
    stellar_tenants_path: str = Field(default="config/stellar_tenants.json")
    stellar_multi_tenant_enabled: bool = Field(
        default=False,
        description="Poll all visible cases and classify them through stellar_tenants.json",
    )
    stellar_multi_tenant_strict: bool = Field(
        default=True,
        description="Quarantine unknown/mismatched tenant cases instead of creating Jira",
    )
    stellar_poll_source_id: str = Field(default="stellar")
    stellar_sync_lookback_minutes: int = Field(default=120, ge=1, le=10080)
    stellar_sync_page_size: int = Field(default=50, ge=1, le=500)
    stellar_sync_max_pages: int = Field(default=40, ge=1, le=500)
    stellar_sync_allowed_severities: str = Field(
        default="Critical,High",
        description="Comma-separated Stellar severities for Jira create + SOC notify. Empty or * = all.",
    )
    stellar_automation_interval_seconds: int | None = Field(default=30, ge=1, le=86400)
    stellar_automation_min_interval_seconds: int = Field(default=5, ge=1, le=3600)
    stellar_automation_jira_writeback: bool = Field(default=True)
    stellar_automation_jira_mirror: bool = Field(
        default=True,
        description="Enable Stellar→Jira mirror (status/assignee/activity).",
    )
    stellar_mirror_on_poll: bool = Field(
        default=True,
        description="Mirror linked cases when they appear in inbound Stellar poll (modified cases).",
    )
    stellar_mirror_full_scan: bool = Field(
        default=False,
        description="Also scan all linked tickets each cycle (slower; poll mirror is usually enough).",
    )
    stellar_writeback_max_issues_per_cycle: int = Field(default=100, ge=0, le=5000)
    stellar_mirror_max_issues_per_cycle: int = Field(default=100, ge=0, le=5000)
    stellar_mirror_case_activity_to_jira: bool = Field(
        default=True,
        description="Mirror Stellar case activities as Jira comments on linked tickets.",
    )
    stellar_mirror_case_activity_since_link: bool = Field(
        default=True,
        description="Only mirror activities at/after Jira ticket link time (avoids huge backfill).",
    )
    stellar_mirror_case_activity_max_per_ticket: int = Field(default=20, ge=0, le=500)
    stellar_sync_stellar_to_jira_status: bool = Field(default=True)
    stellar_sync_jira_workflow_status: bool = Field(default=True)
    stellar_sync_jira_custom_status: bool = Field(default=True)
    stellar_sync_stellar_to_jira_assignee: bool = Field(default=True)
    stellar_status_prefer_jira_workflow: bool = Field(default=True)
    stellar_writeback_sync_status: bool = Field(
        default=False,
        description="Jira→Stellar writeback: update Stellar status from Jira.",
    )
    stellar_writeback_sync_assignee: bool = Field(
        default=False,
        description="Jira→Stellar writeback: update Stellar assignee from Jira.",
    )
    stellar_writeback_sync_severity: bool = Field(
        default=False,
        description="Jira→Stellar writeback: update Stellar severity from Jira.",
    )
    stellar_jira_master_after_link: bool = Field(
        default=False,
        description=(
            "Legacy: after link, Jira owns status/assignee (writeback Jira→Stellar). "
            "Duty-platform mode keeps this false and mirrors Stellar→Jira instead."
        ),
    )
    stellar_jira_field_map_path: str = Field(default="config/stellar_jira_field_map.example.json")
    stellar_jira_user_map_path: str = Field(
        default="config/stellar_jira_user_map.example.json",
        description="Stellar assignee email ↔ Jira accountId when Jira API hides emailAddress.",
    )
    stellar_ai_summary_enabled: bool = Field(
        default=False,
        description="Fetch Stellar native AI Case Summary through the read-only MCP endpoint.",
    )
    stellar_ai_summary_jira_comment: bool = Field(
        default=True,
        description="Post a concise native Stellar AI Summary as a Jira comment when ready.",
    )
    stellar_ai_summary_retry_seconds: int = Field(
        default=300,
        ge=60,
        le=86400,
        description="Delay before retrying an unavailable or failed Stellar AI Summary.",
    )
    stellar_ai_summary_max_attempts: int = Field(
        default=24,
        ge=1,
        le=1000,
        description="Maximum MCP attempts per linked case before stopping automatic retries.",
    )
    ai_data_api_token: str | None = Field(
        default=None,
        description="Bearer token for read-only /v1/ai-data endpoints; required for all access.",
    )
    stellar_webhook_token: str | None = Field(default=None)
    sync_api_token: str | None = Field(default=None)
    decision_enabled: bool = Field(
        default=True,
        description="Run Decision Layer before Jira create (rules + knowledge + audit).",
    )
    decision_append_jira_description: bool = Field(
        default=False,
        description="Append AIxSOC Decision analysis block to Jira issue description (WIP).",
    )
    decision_rules_path: str = Field(default="config/decision_rules.json")
    decision_knowledge_path: str = Field(default="config/decision_knowledge.json")
    decision_assets_path: str = Field(default="config/decision_assets.json")
    decision_record_ai: bool = Field(
        default=True,
        description="Persist SOC notify AI sections onto the decision_events row after create.",
    )
    decision_run_ai_on_create: bool = Field(
        default=False,
        description=(
            "If true, call SOC notify AI during Decision evaluate before Jira create "
            "(adds latency). Prefer false: notify path runs AI once and seeds decision_events."
        ),
    )
    decision_outcome_on_writeback: bool = Field(
        default=True,
        description="When Jira→Stellar writeback sees a resolved/cancelled ticket, record outcome.",
    )
    decision_jira_comment_on_create: bool = Field(
        default=True,
        description=(
            "After Jira create, post a short AIxSOC Decision comment "
            "(keeps Description clean; reminds duty to set resolution tag)."
        ),
    )
    decision_only_without_cortex_case_id: bool = Field(
        default=True,
        description=(
            "When true, run Decision Layer only if no alert in the Stellar bundle has a "
            "Cortex XDR case_id (Stellar rule-elevated cases). Skip Decision for cases that "
            "already have Cortex case linkage (XDR blocked / detect-only)."
        ),
    )
    decision_outcome_remind_on_writeback: bool = Field(
        default=False,
        description=(
            "When a terminal Jira ticket has no TP/FP label, post one reminder comment. "
            "Default false (path C: duty UX first; enable when outcome/Dataset loop is active)."
        ),
    )
    case_archive_enabled: bool = Field(
        default=True,
        description="Persist Stellar case+alerts bundle snapshots to SQLite for Decision Dataset.",
    )
    case_archive_max_bytes: int = Field(
        default=2_097_152,
        ge=10_000,
        le=50_000_000,
        description="Max JSON bytes stored inline; larger bundles go to case_archive_dir files.",
    )
    case_archive_dir: str = Field(default="data/case_archive")
    case_archive_on_severity_escalation: bool = Field(
        default=True,
        description="When a synced case severity rises, fetch bundle again and store a new snapshot.",
    )
    case_archive_autoprune: bool = Field(
        default=True,
        description=(
            "After each snapshot write, drop non-milestone versions for that case "
            "(keeps decision-referenced, first/latest, jira-linked, first-per-severity)."
        ),
    )
    decision_reeval_on_severity_escalation: bool = Field(
        default=True,
        description="After severity-escalation snapshot, persist a new decision_events row.",
    )

    @property
    def sync_case_id_timezone(self) -> str:
        return self.stellar_case_id_timezone

    def allowed_sync_severities(self) -> frozenset[str] | None:
        return parse_allowed_severities(self.stellar_sync_allowed_severities)

    @field_validator("sync_api_token", "stellar_webhook_token", "ai_data_api_token", mode="before")
    @classmethod
    def _strip_tokens(cls, v: object) -> object:
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s or None

    @field_validator("stellar_api_key", "stellar_user_email", "stellar_tenant_id", mode="before")
    @classmethod
    def _strip_stellar(cls, v: object) -> object:
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s or None

    @field_validator(
        "stellar_jira_project_key",
        "stellar_jira_issue_type_id",
        "stellar_jira_severity_field",
        "stellar_jira_status_field",
        "stellar_jira_alert_name_field",
        "stellar_jira_resolution_tag_field",
        "stellar_resolution_tag_map_path",
        "stellar_poll_source_id",
        "stellar_jira_field_map_path",
        "stellar_sync_allowed_severities",
        "stellar_case_id_prefix",
        "stellar_case_id_jira_field",
        "stellar_default_customer_code",
        "stellar_tenants_path",
        "decision_rules_path",
        "decision_knowledge_path",
        "decision_assets_path",
        "case_archive_dir",
        mode="before",
    )
    @classmethod
    def _strip_stellar_jira(cls, v: object) -> object:
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        return s or None


@lru_cache
def get_stellar_settings() -> StellarSettings:
    return StellarSettings()


@lru_cache
def get_settings() -> StellarSettings:
    """Compat alias for shared notify module (Cortex fallback paths)."""
    return get_stellar_settings()


class NotifySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_file_optional=True,
        extra="ignore",
    )

    soc_notify_enabled: bool = Field(default=False)
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    smtp_use_ssl: bool = Field(default=False)
    smtp_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    soc_notify_from: str | None = Field(default=None)
    soc_notify_to: str | None = Field(default=None)
    soc_notify_cc: str | None = Field(default=None)
    soc_notify_bcc: str | None = Field(default=None)
    soc_notify_subject_template: str = Field(
        default="<JJNET XMDR告警> 風險等級：[{severity}] [{customer_code}] 資安事件 [{event_name}]",
        description="Email subject; keys: severity, event_name, case_id, customer_code, …",
    )
    resend_api_key: str | None = Field(default=None)
    soc_notify_ai_enabled: bool = Field(default=False)
    soc_notify_ai_provider: str = Field(default="groq", description="groq (OpenAI-compatible)")
    soc_notify_ai_api_key: str | None = Field(default=None)
    soc_notify_ai_model: str = Field(default="llama-3.3-70b-versatile")
    soc_notify_ai_base_url: str = Field(
        default="https://api.groq.com/openai/v1/chat/completions",
        description="Groq chat completions URL",
    )
    soc_notify_ai_timeout_seconds: float = Field(default=12.0, ge=3.0, le=120.0)
    soc_notify_ai_fail_open: bool = Field(
        default=True,
        description="If true, send email without AI sections when LLM fails",
    )
    # --- MaiAgent after Critical/High Jira create (does NOT replace Groq SOC notify) ---
    maiagent_notify_enabled: bool = Field(
        default=False,
        description=(
            "After Critical/High ticket create, run MaiAgent full-case analysis as an "
            "extra push alongside SOC Email/Groq/LINE"
        ),
    )
    maiagent_api_key: str | None = Field(default=None)
    maiagent_chatbot_id: str | None = Field(default=None)
    maiagent_base_url: str = Field(default="https://api.sungcheng.org/api")
    maiagent_timeout_seconds: float = Field(default=90.0, ge=10.0, le=300.0)
    maiagent_notify_email_to: str | None = Field(
        default=None,
        description="Optional extra email for MaiAgent (comma-separated). Never uses SOC_NOTIFY_TO.",
    )
    maiagent_notify_line_to: str | None = Field(
        default=None,
        description=(
            "MaiAgent LINE targets after create. Empty falls back to LINE_NOTIFY_TO "
            "(shared SOC channel). Set explicitly only to override."
        ),
    )
    maiagent_notify_async: bool = Field(
        default=True,
        description="If true, fire MaiAgent after Groq notify without blocking the automation cycle",
    )
    maiagent_notify_only_without_cortex_case_id: bool = Field(
        default=False,
        description="If true, only run MaiAgent personal notify when bundle has no Cortex case_id",
    )
    maiagent_all_cases_enabled: bool = Field(
        default=False,
        description=(
            "Legacy/optional: analyze every registry-approved case once (including "
            "Low/Medium). Keep false when SOC only wants Critical/High + post-create MaiAgent."
        ),
    )
    maiagent_all_cases_line_to: str | None = Field(
        default=None,
        description=(
            "Required LINE target for all-case results. Must be set explicitly; "
            "never falls back to LINE_NOTIFY_TO (SOC broadcast channel)."
        ),
    )
    maiagent_all_cases_retry_seconds: int = Field(
        default=600,
        ge=60,
        le=86400,
        description="Retry delay after all-case analysis or delivery failure",
    )
    line_notify_enabled: bool = Field(default=False)
    line_channel_access_token: str | None = Field(default=None)
    line_channel_secret: str | None = Field(
        default=None,
        description="LINE Channel secret for webhook X-Line-Signature verification",
    )
    line_notify_to: str | None = Field(
        default=None,
        description="Comma-separated LINE user/group/room IDs for push messages",
    )
    line_notify_timeout_seconds: float = Field(default=15.0, ge=3.0, le=120.0)
    line_webhook_reply_id: bool = Field(
        default=True,
        description="When webhook receives a message/follow/join, reply with the user/group ID",
    )

    @property
    def soc_notify_ai_configured(self) -> bool:
        return bool(self.soc_notify_ai_enabled and (self.soc_notify_ai_api_key or "").strip())

    @property
    def maiagent_notify_configured(self) -> bool:
        return bool(
            self.maiagent_notify_enabled
            and (self.maiagent_api_key or "").strip()
            and (self.maiagent_chatbot_id or "").strip()
            and (
                (self.maiagent_notify_email_to or "").strip()
                or (self.maiagent_notify_line_to or "").strip()
                or (self.line_notify_to or "").strip()
            )
        )

    @property
    def maiagent_all_cases_configured(self) -> bool:
        # Require an explicit all-cases LINE target so we never silently
        # reuse LINE_NOTIFY_TO (SOC Groq/Email companion channel).
        return bool(
            self.maiagent_all_cases_enabled
            and (self.maiagent_api_key or "").strip()
            and (self.maiagent_chatbot_id or "").strip()
            and (self.maiagent_all_cases_line_to or "").strip()
            and self.line_configured
        )

    @property
    def use_resend_api(self) -> bool:
        return bool((self.resend_api_key or "").strip())

    @property
    def is_configured(self) -> bool:
        if not (self.soc_notify_from or "").strip():
            return False
        if self.use_resend_api:
            return True
        return bool((self.smtp_host or "").strip())

    @property
    def line_configured(self) -> bool:
        return bool((self.line_channel_access_token or "").strip())

    @field_validator(
        "smtp_host",
        "smtp_user",
        "smtp_password",
        "resend_api_key",
        "soc_notify_ai_api_key",
        "soc_notify_ai_provider",
        "soc_notify_ai_model",
        "soc_notify_ai_base_url",
        "soc_notify_from",
        "soc_notify_to",
        "soc_notify_cc",
        "soc_notify_bcc",
        "maiagent_api_key",
        "maiagent_chatbot_id",
        "maiagent_base_url",
        "maiagent_notify_email_to",
        "maiagent_notify_line_to",
        "maiagent_all_cases_line_to",
        "line_channel_access_token",
        "line_channel_secret",
        "line_notify_to",
        mode="before",
    )
    @classmethod
    def _strip_notify(cls, v: object) -> object:
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s or None


@lru_cache
def get_notify_settings() -> NotifySettings:
    return NotifySettings()


class PlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_file_optional=True,
        extra="ignore",
    )

    platform_enabled: bool = Field(
        default=True,
        description="Enable platform auth API (/v1/auth/*).",
    )
    platform_db_path: str = Field(default="data/platform.db")
    platform_secret_key: str = Field(
        default="change-me-in-production",
        description="JWT signing secret; set a long random value in production.",
    )
    platform_session_ttl_hours: int = Field(default=24, ge=1, le=720)
    platform_login_token_ttl_minutes: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Short-lived token between password check and TOTP verify.",
    )
    platform_require_totp: bool = Field(
        default=True,
        description="Roles that mandate TOTP must complete setup before full API access.",
    )
    platform_totp_issuer: str = Field(
        default="Stellar SOC Platform",
        description="TOTP label shown in authenticator apps.",
    )
    platform_bootstrap_allow_password_only: bool = Field(
        default=True,
        description="Allow first login without TOTP to reach /v1/auth/totp/* setup only.",
    )
    platform_login_rate_limit_attempts: int = Field(
        default=10,
        ge=0,
        le=1000,
        description="Max failed login/TOTP attempts per IP per window; 0 disables.",
    )
    platform_login_rate_limit_window_seconds: int = Field(
        default=300,
        ge=60,
        le=86400,
        description="Sliding window for platform_login_rate_limit_attempts.",
    )
    platform_session_cookie_name: str = Field(default="soc_session")
    platform_cookie_secure: bool | None = Field(
        default=None,
        description="Secure cookie flag; None = auto from HTTPS / X-Forwarded-Proto.",
    )
    platform_cookie_samesite: str = Field(
        default="lax",
        description="SameSite for session cookie (lax|strict|none).",
    )
    platform_expose_bearer_token: bool = Field(
        default=False,
        description="Include access_token in JSON body; false uses HttpOnly cookie only.",
    )
    platform_trust_proxy_headers: bool = Field(
        default=True,
        description="Trust CF-Connecting-IP / X-Forwarded-For for audit and rate limits.",
    )

    @field_validator("platform_secret_key", mode="before")
    @classmethod
    def _strip_platform_secret(cls, v: object) -> object:
        if v is None or not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s or "change-me-in-production"

    def db_path_resolved(self) -> Path:
        path = Path(self.platform_db_path)
        return path if path.is_absolute() else _REPO_ROOT / path


@lru_cache
def get_platform_settings() -> PlatformSettings:
    return PlatformSettings()
