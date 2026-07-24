"""Multi-tenant Stellar report generation (Darktrace / Cortex CSV/JSON + monthly Word)."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import StellarSettings, get_jira_settings, get_stellar_settings
from app.dates import previous_period_dates
from app.jira.client import JiraClient
from app.report.monthly_docx import build_monthly_report, make_kpi_chart, setup_cjk_font
from app.report.stellar_cortex_charts import make_cortex_alert_stats_panel
from app.report.stellar_cortex_summary import (
    build_mitre_summary_from_cortex_rows,
    process_cortex_report_data,
)
from app.report.stellar_darktrace_charts import make_model_alerts_stats_panel
from app.report.stellar_darktrace_summary import (
    build_mitre_summary_from_darktrace_rows,
    overall_risk_level,
    process_darktrace_report_data,
)
from app.stellar.client import StellarAPIError, StellarClient
from app.stellar.cortex_report import fetch_cortex_events
from app.stellar.darktrace_report import fetch_darktrace_events
from app.stellar.tenant_model import StellarTenant
from app.stellar.tenants import load_stellar_tenants

CSV_COLUMNS = [
    "case_ticket_id",
    "case_id",
    "case_name",
    "case_status",
    "case_severity",
    "case_created_at",
    "case_modified_at",
    "tenant_name",
    "assignee_name",
    "alert_doc_id",
    "anomaly_id",
    "alert_name",
    "cef_severity",
    "event_score",
    "event_source",
    "dev_class",
    "msg_class",
    "hostip",
    "hostip_host",
    "hostname",
    "write_time",
    "darktrace_external_id",
    "darktrace_mitre_id",
    "darktrace_url",
]

CORTEX_CSV_COLUMNS = [
    "case_ticket_id",
    "case_id",
    "case_name",
    "case_status",
    "case_severity",
    "case_created_at",
    "case_modified_at",
    "tenant_name",
    "assignee_name",
    "alert_doc_id",
    "alert_name",
    "alert_category",
    "response_action",
    "cef_severity",
    "hostname",
    "hostip",
    "write_time",
    "mitre_tactics",
]


def _event_count_key(product: str) -> str:
    return "cortex_event_count" if product == "cortex" else "darktrace_event_count"


def _monthly_docx_basename(product: str, period_short: str, safe_tenant: str) -> str:
    if product == "cortex":
        return f"Cortex_Monthly_{period_short}_{safe_tenant}.docx"
    return f"Darktrace_Monthly_{period_short}_{safe_tenant}.docx"


@dataclass(frozen=True)
class ReportRunContext:
    repo_root: Path
    settings: StellarSettings
    tenant: StellarTenant
    product: str
    timezone_name: str
    page_size: int
    max_pages: int


def make_stellar_client(settings: StellarSettings, tenant: StellarTenant) -> StellarClient:
    if not settings.stellar_base_url or not settings.stellar_api_key:
        raise ValueError("Set STELLAR_BASE_URL and STELLAR_API_KEY in .env")
    return StellarClient(
        base_url=str(settings.stellar_base_url).rstrip("/"),
        api_key=settings.stellar_api_key,
        timeout_seconds=settings.stellar_timeout_seconds,
        verify_tls=settings.stellar_tls_verify,
        tenant_id=tenant.tenant_id or settings.stellar_tenant_id,
        http_max_retries=settings.stellar_http_max_retries,
    )


async def fetch_darktrace_for_tenant(
    ctx: ReportRunContext,
    *,
    since_date: date | None,
    until_date: date | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    async with make_stellar_client(ctx.settings, ctx.tenant) as client:
        return await fetch_darktrace_events(
            client,
            since_date=since_date,
            until_date=until_date,
            timezone_name=ctx.timezone_name,
            page_size=ctx.page_size,
            max_pages=ctx.max_pages,
            fetch_alerts_mode="all_cases",
            tenant_name_filter=ctx.tenant.tenant_name,
        )


async def fetch_cortex_for_tenant(
    ctx: ReportRunContext,
    *,
    since_date: date | None,
    until_date: date | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    async with make_stellar_client(ctx.settings, ctx.tenant) as client:
        return await fetch_cortex_events(
            client,
            since_date=since_date,
            until_date=until_date,
            timezone_name=ctx.timezone_name,
            page_size=ctx.page_size,
            max_pages=ctx.max_pages,
            fetch_alerts_mode="all_cases",
            tenant_name_filter=ctx.tenant.tenant_name,
        )


async def _fetch_product_rows(
    ctx: ReportRunContext,
    product: str,
    *,
    since_date: date | None,
    until_date: date | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if product == "cortex":
        return await fetch_cortex_for_tenant(ctx, since_date=since_date, until_date=until_date)
    return await fetch_darktrace_for_tenant(ctx, since_date=since_date, until_date=until_date)


def _csv_columns_for_product(product: str) -> list[str]:
    if product == "cortex":
        return CORTEX_CSV_COLUMNS
    return CSV_COLUMNS


async def fetch_mttr_minutes(
    *,
    project_key: str,
    start_d: date,
    end_d: date,
    tenant_label: str | None = None,
) -> str:
    j = get_jira_settings()
    if not j.jira_base_url:
        return "N/A"
    try:
        client = JiraClient(j)
        tenant_clause = (
            f' AND labels = "{tenant_label}"'
            if str(tenant_label or "").strip()
            else ""
        )
        jql = (
            f"project = {project_key}{tenant_clause} AND created >= '{start_d}' "
            f"AND created <= '{end_d}' AND resolutiondate IS NOT EMPTY"
        )
        issues = await client.search_issues(jql, fields=["created", "resolutiondate"])
    except Exception as exc:
        print(f"Warning: Jira MTTR fetch failed: {exc}", file=sys.stderr)
        return "N/A"

    total_minutes = 0.0
    count = 0
    for issue in issues:
        fields = issue.get("fields", {})
        created_str = fields.get("created")
        resolved_str = fields.get("resolutiondate")
        if not created_str or not resolved_str:
            continue
        try:
            t_c = datetime.fromisoformat(str(created_str).replace("+0000", "+00:00"))
            t_r = datetime.fromisoformat(str(resolved_str).replace("+0000", "+00:00"))
            diff = (t_r - t_c).total_seconds() / 60.0
            if diff >= 0:
                total_minutes += diff
                count += 1
        except Exception:
            pass
    if count > 0:
        return f"{total_minutes / count:.1f}"
    return "N/A"


def tenant_label_from_rows(tenant: StellarTenant, rows: list[dict[str, Any]]) -> str:
    if rows:
        tn = str(rows[0].get("tenant_name") or "").strip()
        if tn:
            return tn
    return tenant.display_label()


def resolve_out_dir(repo_root: Path, path: str | None, default: Path) -> Path:
    if path:
        out = Path(path).expanduser()
        if not out.is_absolute():
            out = repo_root / out
    else:
        out = default
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()


def write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if "mitre_tactics" in fieldnames and isinstance(out.get("mitre_tactics"), list):
                out["mitre_tactics"] = "; ".join(str(x) for x in out["mitre_tactics"])
            writer.writerow(out)


def write_json_export(path: Path, *, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    payload = {"summary": summary, "events": rows}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def stamp(*, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).strftime("%Y%m%d_%H%M%S")


def monthly_run_dir_name(tenant: StellarTenant, product: str, *, timezone_name: str) -> str:
    """``{source_id}_{product}_YYYYMMDDHHMMSS`` for one monthly report run."""
    tz = ZoneInfo(timezone_name)
    ts = datetime.now(tz).strftime("%Y%m%d%H%M%S")
    safe_tenant = "".join(c if c.isalnum() or c in "-_" else "_" for c in tenant.source_id)[:64]
    safe_product = "".join(c if c.isalnum() or c in "-_" else "_" for c in product)[:32]
    return f"{safe_tenant}_{safe_product}_{ts}"


def resolve_monthly_run_dir(
    out_dir: Path,
    tenant: StellarTenant,
    product: str,
    *,
    timezone_name: str,
) -> Path:
    run_dir = out_dir / monthly_run_dir_name(tenant, product, timezone_name=timezone_name)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir.resolve()


async def run_product_export(
    *,
    repo_root: Path,
    tenant: StellarTenant,
    product: str,
    since_date: date | None,
    until_date: date | None,
    timezone_name: str = "Asia/Taipei",
    out_dir: Path,
    fmt: str = "both",
    page_size: int = 500,
    max_pages: int = 200,
) -> dict[str, Any]:
    get_stellar_settings.cache_clear()
    settings = get_stellar_settings()
    ctx = ReportRunContext(
        repo_root=repo_root,
        settings=settings,
        tenant=tenant,
        product=product,
        timezone_name=timezone_name,
        page_size=page_size,
        max_pages=max_pages,
    )
    try:
        rows, summary = await _fetch_product_rows(
            ctx, product, since_date=since_date, until_date=until_date
        )
    except StellarAPIError as exc:
        raise RuntimeError(str(exc)) from exc

    summary = {
        **summary,
        "tenant_source_id": tenant.source_id,
        "customer_code": tenant.customer_code,
        "product": product,
    }
    safe_tenant = "".join(c if c.isalnum() or c in "-_" else "_" for c in tenant.display_label())[:32]
    base_name = f"stellar_{product}_{safe_tenant}_{stamp(tz_name=timezone_name)}"
    columns = _csv_columns_for_product(product)
    written: list[str] = []
    if fmt in ("csv", "both"):
        csv_path = out_dir / f"{base_name}.csv"
        write_csv(csv_path, rows, fieldnames=columns)
        written.append(str(csv_path))
    if fmt in ("json", "both"):
        json_path = out_dir / f"{base_name}.json"
        write_json_export(json_path, summary=summary, rows=rows)
        written.append(str(json_path))
    return {"summary": summary, "output_files": written}


async def run_darktrace_export(
    *,
    repo_root: Path,
    tenant: StellarTenant,
    product: str,
    since_date: date | None,
    until_date: date | None,
    timezone_name: str = "Asia/Taipei",
    out_dir: Path,
    fmt: str = "both",
    page_size: int = 500,
    max_pages: int = 200,
) -> dict[str, Any]:
    return await run_product_export(
        repo_root=repo_root,
        tenant=tenant,
        product=product,
        since_date=since_date,
        until_date=until_date,
        timezone_name=timezone_name,
        out_dir=out_dir,
        fmt=fmt,
        page_size=page_size,
        max_pages=max_pages,
    )


async def run_product_monthly(
    *,
    repo_root: Path,
    tenant: StellarTenant,
    product: str,
    start_d: date,
    end_d: date,
    timezone_name: str = "Asia/Taipei",
    out_dir: Path,
    logo_path: Path | None = None,
    page_size: int = 500,
    max_pages: int = 200,
) -> Path:
    get_stellar_settings.cache_clear()
    settings = get_stellar_settings()
    ctx = ReportRunContext(
        repo_root=repo_root,
        settings=settings,
        tenant=tenant,
        product=product,
        timezone_name=timezone_name,
        page_size=page_size,
        max_pages=max_pages,
    )

    print(f"Fetching {product} events for tenant {tenant.source_id} ({start_d} – {end_d})...")
    try:
        rows, summary = await _fetch_product_rows(ctx, product, since_date=start_d, until_date=end_d)
    except StellarAPIError as exc:
        raise RuntimeError(str(exc)) from exc

    count_key = _event_count_key(product)
    print(
        f"Fetched {summary.get(count_key, len(rows))} alerts "
        f"from {summary.get('cases_scanned', '?')} cases."
    )

    tenant_label = tenant_label_from_rows(tenant, rows)
    prev_alerts: int | str = "N/A"
    prev_cases: int | str = "N/A"
    prev_overall_risk: str | None = None
    prev_start, prev_end = previous_period_dates(start_d, end_d)
    print(f"Fetching prior period {prev_start} – {prev_end} for MoM...")
    try:
        prev_rows, _prev_summary = await _fetch_product_rows(
            ctx, product, since_date=prev_start, until_date=prev_end
        )
        prev_alerts = len(prev_rows)
        prev_case_ids = {str(r.get("case_id") or "") for r in prev_rows if r.get("case_id")}
        prev_cases = len(prev_case_ids)
        prev_critical = 0
        seen_critical: set[str] = set()
        for r in prev_rows:
            cid = str(r.get("case_id") or "")
            if not cid or cid in seen_critical:
                continue
            seen_critical.add(cid)
            if str(r.get("case_severity") or "").strip().lower() == "critical":
                prev_critical += 1
        prev_overall_risk = overall_risk_level(prev_rows, critical_cases=prev_critical)
        print(
            f"  Prior period: alerts={prev_alerts}, cases={prev_cases}, "
            f"overall risk={prev_overall_risk}"
        )
    except StellarAPIError as exc:
        print(f"Warning: prior period fetch failed: {exc}", file=sys.stderr)

    project_key = tenant.jira_project_key or settings.stellar_jira_project_key
    mttr_str = await fetch_mttr_minutes(
        project_key=project_key,
        start_d=start_d,
        end_d=end_d,
        tenant_label=tenant.tenant_label(),
    )
    if mttr_str != "N/A":
        print(f"Calculated MTTR from Jira {project_key}: {mttr_str} min")

    if product == "cortex":
        mitre_summary = build_mitre_summary_from_cortex_rows(rows)
        data = process_cortex_report_data(
            rows,
            start_d,
            end_d,
            tenant_label=f"客戶: {tenant_label}",
            mttr_val=mttr_str,
            prev_alerts=prev_alerts,
            prev_cases=prev_cases,
            prev_overall_risk=prev_overall_risk,
            mitre_summary=mitre_summary,
        )
        chart_stats_name = f"chart_alert_stats_{product}_{tenant.source_id}.png"
    else:
        mitre_summary = build_mitre_summary_from_darktrace_rows(rows)
        data = process_darktrace_report_data(
            rows,
            start_d,
            end_d,
            tenant_label=f"客戶: {tenant_label}",
            mttr_val=mttr_str,
            prev_alerts=prev_alerts,
            prev_cases=prev_cases,
            prev_overall_risk=prev_overall_risk,
            mitre_summary=mitre_summary,
        )
        chart_stats_name = f"chart_model_alerts_{product}_{tenant.source_id}.png"

    run_dir = resolve_monthly_run_dir(
        out_dir, tenant, product, timezone_name=timezone_name
    )
    print(f"Report run directory: {run_dir}")

    chart_kpi = run_dir / f"chart_kpi_{product}_{tenant.source_id}.png"
    chart_stats = run_dir / chart_stats_name

    print("Generating Word report...")
    setup_cjk_font()
    make_kpi_chart(data["kpi"], chart_kpi)
    stats = data.get("model_alerts_stats") or {}
    if stats:
        if product == "cortex":
            make_cortex_alert_stats_panel(stats, chart_stats)
        else:
            make_model_alerts_stats_panel(stats, chart_stats)
        data["model_alerts_panel_chart"] = chart_stats

    safe_tenant = "".join(c if c.isalnum() or c in "-_" else "_" for c in tenant_label)[:32]
    out_docx = run_dir / _monthly_docx_basename(product, data["period_short"], safe_tenant)
    build_monthly_report(data, chart_kpi, None, out_docx, logo_path=logo_path, repo_root=repo_root)
    return out_docx


async def run_darktrace_monthly(
    *,
    repo_root: Path,
    tenant: StellarTenant,
    product: str,
    start_d: date,
    end_d: date,
    timezone_name: str = "Asia/Taipei",
    out_dir: Path,
    logo_path: Path | None = None,
    page_size: int = 500,
    max_pages: int = 200,
) -> Path:
    return await run_product_monthly(
        repo_root=repo_root,
        tenant=tenant,
        product=product,
        start_d=start_d,
        end_d=end_d,
        timezone_name=timezone_name,
        out_dir=out_dir,
        logo_path=logo_path,
        page_size=page_size,
        max_pages=max_pages,
    )


def load_tenants_for_repo(repo_root: Path) -> list[StellarTenant]:
    get_stellar_settings.cache_clear()
    return load_stellar_tenants(get_stellar_settings(), repo_root)
