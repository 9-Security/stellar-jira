"""Stellar report tenant (multi-tenant config)."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SOURCE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_CUSTOMER_CODE_RE = re.compile(r"^[A-Za-z0-9]{2,16}$")
_REPORT_PRODUCTS = frozenset({"darktrace", "cortex"})


class StellarTenant(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source_id: str = Field(..., description="Stable id for CLI --tenant (like cortex source_id)")
    enabled: bool = Field(default=True, description="Master tenant switch")
    sync_enabled: bool = Field(default=True, description="Allow Stellar→Jira sync")
    reporting_enabled: bool = Field(default=True, description="Allow report generation")
    customer_code: str = Field(..., min_length=2, max_length=16)
    tenant_name: str | None = Field(
        default=None,
        description="Filter cases by Stellar case tenant_name (e.g. JJNET)",
    )
    tenant_id: str | None = Field(
        default=None,
        description="Stellar API tenant_id query param for GET /cases",
    )
    products: list[str] = Field(
        default_factory=lambda: ["darktrace"],
        description="Enabled report products for this tenant",
    )
    jira_project_key: str | None = Field(
        default=None,
        description="Override JIRA project for MTTR in monthly report",
    )
    allowed_severities: list[str] | None = Field(
        default=None,
        description="Optional per-tenant Jira create severities; null inherits global setting",
    )
    jira_labels: list[str] = Field(
        default_factory=list,
        description="Extra Jira labels for this tenant",
    )
    report_title: str | None = Field(
        default=None,
        description="Display label on report cover (defaults to tenant_name or customer_code)",
    )

    @field_validator("source_id")
    @classmethod
    def _source_id_shape(cls, v: str) -> str:
        s = v.strip()
        if not _SOURCE_ID_RE.fullmatch(s):
            raise ValueError("source_id must be 1–64 alphanumeric/underscore/hyphen")
        return s

    @field_validator("customer_code")
    @classmethod
    def _customer_code_shape(cls, v: str) -> str:
        s = v.strip().upper()
        if not _CUSTOMER_CODE_RE.fullmatch(s):
            raise ValueError("customer_code must be 2–16 alphanumeric characters")
        return s

    @field_validator("products")
    @classmethod
    def _products_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("products must list at least one report product")
        out: list[str] = []
        for p in v:
            s = str(p).strip().lower()
            if s not in _REPORT_PRODUCTS:
                raise ValueError(f"Unknown product {p!r}; supported: {sorted(_REPORT_PRODUCTS)}")
            if s not in out:
                out.append(s)
        return out

    def display_label(self) -> str:
        if self.report_title and str(self.report_title).strip():
            return str(self.report_title).strip()
        if self.tenant_name and str(self.tenant_name).strip():
            return str(self.tenant_name).strip()
        return self.customer_code

    def supports_product(self, product: str) -> bool:
        return self.enabled and self.reporting_enabled and product.strip().lower() in self.products

    def sync_is_enabled(self) -> bool:
        return self.enabled and self.sync_enabled

    def tenant_label(self) -> str:
        slug = re.sub(r"[^a-z0-9_-]+", "-", self.source_id.strip().lower()).strip("-")
        return f"tenant-{slug or 'unknown'}"

    @field_validator("allowed_severities")
    @classmethod
    def _allowed_severities(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        labels = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
        out: list[str] = []
        for raw in v:
            value = labels.get(str(raw or "").strip().lower())
            if value is None:
                raise ValueError("allowed_severities supports Critical/High/Medium/Low")
            if value not in out:
                out.append(value)
        return out
