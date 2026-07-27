"""Runtime configuration from environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PollMode = Literal["alerts", "incidents", "both"]


def _env_set(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and str(value).strip() != ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    stellar_base_url: str = Field(default="", alias="STELLAR_BASE_URL")
    stellar_xdr_api_key: str = Field(default="", alias="STELLAR_XDR_API_KEY")
    stellar_xdr_ingest_path: str = Field(default="", alias="STELLAR_XDR_INGEST_PATH")
    stellar_xdr_auth_path: str = Field(default="", alias="STELLAR_XDR_AUTH_PATH")

    stellar_xdr_vendor: str = Field(default="CyCraft", alias="STELLAR_XDR_VENDOR")
    stellar_xdr_source: str = Field(default="XCockpit_EDR", alias="STELLAR_XDR_SOURCE")
    stellar_xdr_timestamp_path: str = Field(default="event_time", alias="STELLAR_XDR_TIMESTAMP_PATH")
    stellar_xdr_timestamp_format: str = Field(
        default="ISO8601_EXTENDED", alias="STELLAR_XDR_TIMESTAMP_FORMAT"
    )

    # XCockpit API v2.1.0 (CyCraft EDR)
    xcockpit_base_url: str = Field(default="https://xcockpit.cycraft.ai", alias="XCOCKPIT_BASE_URL")
    xcockpit_api_key: str = Field(default="", alias="XCOCKPIT_API_KEY")
    xcockpit_customer_key: str = Field(default="", alias="XCOCKPIT_CUSTOMER_KEY")
    xcockpit_poll_mode: PollMode = Field(default="alerts", alias="XCOCKPIT_POLL_MODE")
    xcockpit_poll_interval_seconds: int = Field(default=60, alias="XCOCKPIT_POLL_INTERVAL_SECONDS")
    xcockpit_poll_lookback_minutes: int = Field(default=15, alias="XCOCKPIT_POLL_LOOKBACK_MINUTES")
    xcockpit_incident_page_size: int = Field(default=50, alias="XCOCKPIT_INCIDENT_PAGE_SIZE")
    xcockpit_include_cycraft_c: bool = Field(default=True, alias="XCOCKPIT_INCLUDE_CYCRAFT_C")

    # L3: XCockpit Incident → Stellar Case (update only; 6.5.x has no POST /cases)
    incident_case_sync_enabled: bool = Field(default=False, alias="INCIDENT_CASE_SYNC_ENABLED")
    incident_maltrace_ingest: bool = Field(default=False, alias="INCIDENT_MALTRACE_INGEST")
    stellar_cases_api_key: str = Field(default="", alias="STELLAR_CASES_API_KEY")
    stellar_tenant_id: str = Field(default="", alias="STELLAR_TENANT_ID")

    # Legacy aliases (mapped in __init__ if new vars empty)
    cycraft_api_base_url: str = Field(default="", alias="CYCRAFT_API_BASE_URL")
    cycraft_api_key: str = Field(default="", alias="CYCRAFT_API_KEY")
    cycraft_poll_interval_seconds: int = Field(default=60, alias="CYCRAFT_POLL_INTERVAL_SECONDS")
    cycraft_poll_lookback_minutes: int = Field(default=15, alias="CYCRAFT_POLL_LOOKBACK_MINUTES")

    connector_listen_host: str = Field(default="127.0.0.1", alias="CONNECTOR_LISTEN_HOST")
    connector_listen_port: int = Field(default=8787, alias="CONNECTOR_LISTEN_PORT")
    cycraft_webhook_secret: str = Field(default="", alias="CYCRAFT_WEBHOOK_SECRET")
    connector_tls_verify: bool = Field(default=True, alias="CONNECTOR_TLS_VERIFY")
    connector_http_timeout_seconds: float = Field(default=30.0, alias="CONNECTOR_HTTP_TIMEOUT_SECONDS")
    connector_state_db: Path = Field(
        default=Path("data/cycraft_connector_state.sqlite"),
        alias="CONNECTOR_STATE_DB",
    )
    cycraft_connector_enabled: bool = Field(default=False, alias="CYCRAFT_CONNECTOR_ENABLED")

    def model_post_init(self, __context: object) -> None:
        if not self.xcockpit_api_key and self.cycraft_api_key:
            object.__setattr__(self, "xcockpit_api_key", self.cycraft_api_key)
        if self.cycraft_api_base_url and self.xcockpit_base_url == "https://xcockpit.cycraft.ai":
            object.__setattr__(self, "xcockpit_base_url", self.cycraft_api_base_url)
        if not _env_set("XCOCKPIT_POLL_INTERVAL_SECONDS"):
            object.__setattr__(
                self, "xcockpit_poll_interval_seconds", self.cycraft_poll_interval_seconds
            )
        if not _env_set("XCOCKPIT_POLL_LOOKBACK_MINUTES"):
            object.__setattr__(
                self, "xcockpit_poll_lookback_minutes", self.cycraft_poll_lookback_minutes
            )

    def stellar_ingest_url(self) -> str:
        return f"{self.stellar_base_url.rstrip('/')}{self.stellar_xdr_ingest_path}"

    def stellar_auth_url(self) -> str:
        return f"{self.stellar_base_url.rstrip('/')}{self.stellar_xdr_auth_path}"


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def validate_settings(settings: Settings) -> None:
    if settings.incident_case_sync_enabled and not settings.stellar_cases_api_key.strip():
        raise ValueError(
            "INCIDENT_CASE_SYNC_ENABLED=true requires STELLAR_CASES_API_KEY "
            "(Stellar Platform API key for Cases API)"
        )
    if not settings.cycraft_connector_enabled:
        return
    missing: list[str] = []
    if not str(settings.stellar_base_url or "").strip():
        missing.append("STELLAR_BASE_URL")
    if not settings.stellar_xdr_api_key.strip():
        missing.append("STELLAR_XDR_API_KEY")
    if not settings.stellar_xdr_ingest_path.strip():
        missing.append("STELLAR_XDR_INGEST_PATH")
    if not settings.xcockpit_api_key.strip():
        missing.append("XCOCKPIT_API_KEY")
    if not settings.xcockpit_customer_key.strip():
        missing.append("XCOCKPIT_CUSTOMER_KEY")
    if missing:
        raise ValueError(
            "CYCRAFT_CONNECTOR_ENABLED=true requires: " + ", ".join(missing)
        )


def env_configured(settings: Settings) -> bool:
    """True when required CyCraft / XDR env vars are present (ignores DB tenant toggles)."""
    return bool(
        str(settings.stellar_base_url or "").strip()
        and settings.stellar_xdr_api_key.strip()
        and settings.stellar_xdr_ingest_path.strip()
        and settings.xcockpit_api_key.strip()
        and settings.xcockpit_customer_key.strip()
    )
