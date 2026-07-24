"""Poll Stellar Cyber cases by modified_at and create Jira issues once per case_id."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import (
    NotifySettings,
    StellarSettings,
    get_jira_settings,
    get_notify_settings,
    get_stellar_settings,
)
from app.jira.client import JiraAPIError, JiraClient
from app.notify.ticket_created import notify_ticket_created
from app.notify.maiagent_personal import (
    maybe_notify_maiagent_personal,
    notify_maiagent_personal,
)
from app.stellar.client import StellarAPIError, StellarClient
from app.stellar.ai_summary import (
    StellarAISummaryClient,
    ai_summary_triage_state,
    extract_ai_case_triage,
    format_ai_summary_comment,
)
from app.stellar.cortex_fields import stellar_bundle_has_cortex_case_id
from app.stellar.http_errors import inbound_stellar_unreachable, stellar_error_dict
from app.stellar.jira_draft import build_jira_issue_fields
from app.stellar.jira_activity_mirror import mirror_stellar_activities_to_jira
from app.stellar.jira_assignee_update import apply_stellar_assignee_to_jira
from app.stellar.jira_mirror import mirror_stellar_case_to_jira
from app.stellar.jira_status_update import apply_stellar_status_to_jira
from app.decision.actions import (
    apply_decision_to_jira_fields,
    should_create_ticket,
    should_notify_internal,
)
from app.decision.ai_bridge import (
    extract_ai_sections_blob,
    generate_ai_aligned_with_decision,
    seed_decision_ai,
)
from app.decision.pipeline import evaluate_case_decision, get_decision_store
from app.stellar.severity_filter import case_severity_allowed, is_severity_escalation, normalize_stellar_severity
from app.stellar.tenant_code import customer_code_from_case
from app.stellar.tenant_model import StellarTenant
from app.stellar.tenants import (
    load_stellar_tenants,
    resolve_case_tenant,
    validate_tenant_registry,
)
from app.sync.case_id import commit_case_id, peek_next_case_id
from app.sync.case_snapshots import CaseSnapshotStore, archive_stellar_bundle, get_case_snapshot_store
from app.sync.lock import SyncLockError, sync_process_lock
from app.sync.run_meta import (
    append_truncation_error,
    finalize_watermark_ms,
    note_watermark_mod,
    persist_per_source_sync_meta,
    watermark_meta_key,
)
from app.sync.state import SyncState

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKOFF_MS = 120_000

logger = logging.getLogger(__name__)

# Strong references to fire-and-forget background tasks so the event loop does
# not garbage-collect them before completion.
_BG_TASKS: set[asyncio.Task] = set()


def _case_created_at_ms(case: dict[str, Any]) -> int:
    value = case.get("created_at")
    if value is None:
        return 0
    try:
        numeric = int(value)
        return numeric * 1000 if 0 < numeric < 10_000_000_000 else numeric
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


async def _schedule_maiagent_all_case(
    *,
    state: SyncState,
    source_id: str,
    case: dict[str, Any],
    customer_code: str,
    client: StellarClient,
    settings: NotifySettings,
    jira_key: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cid = str(case.get("_id") or "").strip()
    claim = state.try_claim_maiagent_case(
        source_id,
        cid,
        retry_after_seconds=settings.maiagent_all_cases_retry_seconds,
    )
    if claim != "claimed":
        return {"case_id": cid, "status": claim}, None
    try:
        bundle = await client.fetch_case_bundle(cid)
    except Exception as e:
        state.finish_maiagent_case(source_id, cid, delivered=False, error=str(e))
        logger.warning("MaiAgent all-case bundle fetch failed case_id=%s: %s", cid, e)
        return {"case_id": cid, "status": "failed", "error": str(e)}, None

    async def _run() -> None:
        try:
            result = await notify_maiagent_personal(
                jira_key=jira_key,
                case_id=str(case.get("ticket_id") or cid),
                customer_code=customer_code,
                stellar_case=case,
                stellar_bundle=bundle,
                settings=settings,
                email_to_override="",
                # Never fall back to LINE_NOTIFY_TO — that channel is SOC broadcast.
                line_to_override=(settings.maiagent_all_cases_line_to or ""),
                subject_prefix="MaiAgent 全案例因果分析",
                body_heading="MaiAgent AI 分析:",
                analysis_only=True,
                root_cause_only=True,
                line_subject_override="",
            )
            delivered = bool(
                isinstance(result.get("line"), dict)
                and result["line"].get("sent")
            )
            error = str(
                result.get("error")
                or (result.get("line") or {}).get("error")
                or result.get("reason")
                or ""
            )
            state.finish_maiagent_case(
                source_id,
                cid,
                delivered=delivered,
                error=error,
            )
            logger.info(
                "MaiAgent all-case done case_id=%s delivered=%s ok=%s",
                cid,
                delivered,
                result.get("ok"),
            )
        except Exception as e:
            state.finish_maiagent_case(source_id, cid, delivered=False, error=str(e))
            logger.warning("MaiAgent all-case task failed case_id=%s: %s", cid, e)

    task = asyncio.create_task(_run(), name=f"maiagent-all-case-{cid}")
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return {"case_id": cid, "status": "scheduled"}, bundle


async def _maybe_severity_escalation_refresh(
    *,
    st: StellarSettings,
    client: StellarClient,
    case: dict[str, Any],
    source_id: str,
    customer_code: str,
    jira_key: str,
    snapshot_store: CaseSnapshotStore | None,
    decision_store: Any,
    refreshed: list[dict[str, Any]],
) -> None:
    """Re-archive and optionally re-decide when a synced case severity rises."""
    if not getattr(st, "case_archive_on_severity_escalation", True):
        return
    if snapshot_store is None:
        return
    cid = str(case.get("_id") or "").strip()
    if not cid:
        return
    latest = snapshot_store.get_latest(source_id, cid)
    if not latest:
        return
    prev_bundle = snapshot_store.load_bundle_payload(latest)
    prev_case = prev_bundle.get("case") if isinstance(prev_bundle.get("case"), dict) else {}
    if not is_severity_escalation(prev_case.get("severity"), case.get("severity")):
        return

    bundle: dict[str, Any] | None = None
    try:
        bundle = await client.fetch_case_bundle(cid)
    except StellarAPIError as e:
        logger.warning("severity escalation bundle fetch failed case_id=%s: %s", cid, e)
        return

    snapshot_id = await archive_stellar_bundle(
        st=st,
        client=client,
        case=case,
        bundle=bundle,
        source_id=source_id,
        customer_code=customer_code,
        snapshot_store=snapshot_store,
        dry_run=False,
        force=True,
        allow_replace_on_escalation=True,
    )
    if snapshot_id and jira_key:
        try:
            snapshot_store.update_jira_key(snapshot_id, jira_key)
        except Exception as e:
            logger.warning("severity escalation snapshot jira link failed: %s", e)

    row: dict[str, Any] = {
        "source_id": source_id,
        "case_id": cid,
        "jira_key": jira_key,
        "previous_severity": normalize_stellar_severity(prev_case.get("severity")),
        "current_severity": normalize_stellar_severity(case.get("severity")),
        "snapshot_id": snapshot_id,
    }

    if (
        st.decision_enabled
        and getattr(st, "decision_reeval_on_severity_escalation", True)
        and decision_store is not None
        and snapshot_id
        and isinstance(bundle, dict)
    ):
        middleware_case_id = ""
        if jira_key:
            prev_dec = decision_store.get_latest_by_jira_key(jira_key)
            if prev_dec:
                middleware_case_id = str(prev_dec.get("middleware_case_id") or "")
        if not middleware_case_id:
            prev_dec = decision_store.get_latest_by_case(source_id, cid)
            if prev_dec:
                middleware_case_id = str(prev_dec.get("middleware_case_id") or "")
        skip_decision = bool(
            getattr(st, "decision_only_without_cortex_case_id", True)
            and stellar_bundle_has_cortex_case_id(bundle)
        )
        if skip_decision:
            row["decision_skipped"] = "cortex_case_id_present"
            logger.info(
                "severity escalation decision skipped (cortex case_id) case_id=%s",
                cid,
            )
        else:
            try:
                decision = await evaluate_case_decision(
                    case=case,
                    bundle=bundle,
                    source_id=source_id,
                    customer_code=customer_code,
                    middleware_case_id=middleware_case_id,
                    jira_key=jira_key,
                    store=decision_store,
                    run_ai=False,
                    persist=True,
                    snapshot_id=snapshot_id,
                )
                row["decision"] = {
                    "action": decision.action,
                    "escalation": decision.escalation,
                    "playbook_id": decision.playbook_id,
                    "rule_hits": list(decision.rule_hits),
                }
            except Exception as e:
                logger.warning("severity escalation decision re-eval failed case_id=%s: %s", cid, e)
                row["decision_error"] = str(e)

    refreshed.append(row)
    logger.info(
        "severity escalation refresh case_id=%s %s→%s snapshot=%s jira=%s",
        cid,
        row["previous_severity"],
        row["current_severity"],
        snapshot_id,
        jira_key,
    )


async def _inject_deferred_cases(
    cases: list[dict[str, Any]],
    *,
    source_id: str,
    state: SyncState,
    client: StellarClient,
    dry_run: bool,
    allowed_severities: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Re-fetch cases deferred for failed create / decision defer (not severity gating).

    Low/Medium (severity-gated) cases are pruned from the queue: when severity later
    rises to Critical/High, ``modified_at`` updates and the normal poll creates the ticket.
    """
    if dry_run:
        return cases
    deferred = state.list_deferred_create(source_id)
    if not deferred:
        return cases
    seen = {str(c.get("_id") or "").strip() for c in cases if isinstance(c, dict)}
    merged = list(cases)
    pruned_severity = 0
    for cid in deferred:
        if not cid or cid in seen or state.has_incident(source_id, cid):
            if state.has_incident(source_id, cid):
                state.remove_deferred_create(source_id, cid)
            continue
        try:
            case = StellarClient.extract_case_one(await client.get_case(cid))
        except StellarAPIError as e:
            logger.warning(
                "deferred stellar case fetch failed case_id=%s: %s",
                cid,
                e,
            )
            continue
        if not isinstance(case, dict):
            continue
        if not case_severity_allowed(case, allowed_severities):
            state.remove_deferred_create(source_id, cid)
            pruned_severity += 1
            continue
        merged.append(case)
        seen.add(cid)
    if pruned_severity:
        logger.info(
            "stellar deferred create pruned severity-gated source_id=%s removed=%s remaining=%s",
            source_id,
            pruned_severity,
            len(state.list_deferred_create(source_id)),
        )
    if len(merged) > len(cases):
        merged.sort(key=lambda x: int(x.get("modified_at") or 0))
        logger.info(
            "stellar deferred create retry source_id=%s added=%s total=%s",
            source_id,
            len(merged) - len(cases),
            len(merged),
        )
    return merged


async def _inject_maiagent_retry_cases(
    cases: list[dict[str, Any]],
    *,
    source_id: str,
    state: SyncState,
    client: StellarClient,
    settings: NotifySettings,
    dry_run: bool,
) -> list[dict[str, Any]]:
    if dry_run or not settings.maiagent_all_cases_configured:
        return cases
    retry_ids = state.list_retryable_maiagent_cases(
        source_id,
        retry_after_seconds=settings.maiagent_all_cases_retry_seconds,
    )
    if not retry_ids:
        return cases
    seen = {
        str(case.get("_id") or "").strip()
        for case in cases
        if isinstance(case, dict)
    }
    merged = list(cases)
    for cid in retry_ids:
        if cid in seen:
            continue
        try:
            case = StellarClient.extract_case_one(await client.get_case(cid))
        except StellarAPIError as e:
            logger.warning("MaiAgent retry case fetch failed case_id=%s: %s", cid, e)
            continue
        if isinstance(case, dict):
            merged.append(case)
            seen.add(cid)
    return merged


async def _inject_ai_summary_retry_cases(
    cases: list[dict[str, Any]],
    *,
    source_id: str,
    state: SyncState,
    client: StellarClient,
    settings: StellarSettings,
    dry_run: bool,
) -> list[dict[str, Any]]:
    if dry_run or not settings.stellar_ai_summary_enabled:
        return cases
    retry_ids = state.list_retryable_stellar_ai_summary_cases(
        source_id,
        retry_after_seconds=settings.stellar_ai_summary_retry_seconds,
        max_attempts=settings.stellar_ai_summary_max_attempts,
    )
    if not retry_ids:
        return cases
    seen = {
        str(case.get("_id") or "").strip()
        for case in cases
        if isinstance(case, dict)
    }
    merged = list(cases)
    for cid in retry_ids:
        if cid in seen or not state.has_incident(source_id, cid):
            continue
        try:
            case = StellarClient.extract_case_one(await client.get_case(cid))
        except StellarAPIError as e:
            logger.warning("Stellar AI Summary retry case fetch failed case_id=%s: %s", cid, e)
            continue
        if isinstance(case, dict):
            merged.append(case)
            seen.add(cid)
    return merged


async def _maybe_deliver_ai_summary(
    *,
    state: SyncState,
    source_id: str,
    case: dict[str, Any],
    jira_key: str,
    jira: JiraClient,
    settings: StellarSettings,
    snapshot_store: CaseSnapshotStore | None,
) -> dict[str, Any] | None:
    """Fetch/archive/comment native AI Summary without blocking the main sync on failure."""
    if not settings.stellar_ai_summary_enabled:
        return None
    cid = str(case.get("_id") or "").strip()
    key = str(jira_key or "").strip()
    if not cid or not key:
        return None
    claim = state.try_claim_stellar_ai_summary(
        source_id,
        cid,
        jira_key=key,
        retry_after_seconds=settings.stellar_ai_summary_retry_seconds,
        max_attempts=settings.stellar_ai_summary_max_attempts,
    )
    if claim != "claimed":
        return None

    try:
        async with StellarAISummaryClient(
            base_url=str(settings.stellar_base_url),
            api_key=str(settings.stellar_api_key or ""),
            timeout_seconds=settings.stellar_timeout_seconds,
            verify_tls=settings.stellar_tls_verify,
        ) as ai_client:
            payload = await ai_client.get_case_ai_summary(
                ticket_id=str(case.get("ticket_id") or ""),
                case_id=cid,
            )
        if snapshot_store is not None:
            try:
                snapshot_store.attach_ai_summary(source_id, cid, payload)
            except Exception as e:
                logger.warning("Stellar AI Summary archive attach failed case_id=%s: %s", cid, e)

        triage = extract_ai_case_triage(payload)
        if not triage:
            triage_state = ai_summary_triage_state(payload)
            state.finish_stellar_ai_summary(
                source_id,
                cid,
                status="waiting",
                payload=payload,
                error=f"ai_case_triage unavailable (state={triage_state or 'unknown'})",
            )
            return {
                "source_id": source_id,
                "case_id": cid,
                "jira_key": key,
                "status": "waiting",
                "triage_state": triage_state,
            }

        if settings.stellar_ai_summary_jira_comment:
            await jira.add_comment(key, format_ai_summary_comment(payload))
        state.finish_stellar_ai_summary(
            source_id,
            cid,
            status="delivered",
            payload=payload,
        )
        return {
            "source_id": source_id,
            "case_id": cid,
            "jira_key": key,
            "status": "delivered",
            "comment_posted": settings.stellar_ai_summary_jira_comment,
            "triage_state": ai_summary_triage_state(payload),
        }
    except Exception as e:
        state.finish_stellar_ai_summary(
            source_id,
            cid,
            status="failed",
            error=str(e),
        )
        logger.warning("Stellar AI Summary delivery failed case_id=%s jira=%s: %s", cid, key, e)
        return {
            "source_id": source_id,
            "case_id": cid,
            "jira_key": key,
            "status": "failed",
            "error": str(e),
        }


async def _reconcile_pending_jira(
    jira: JiraClient,
    *,
    project_key: str,
    source_id: str,
    case_id: str,
) -> str | None:
    project = str(project_key or "").strip()
    if not project:
        return None
    try:
        return await jira.find_issue_key_for_stellar_case(project, case_id)
    except JiraAPIError as e:
        logger.warning(
            "reconcile pending failed source_id=%s case_id=%s: %s",
            source_id,
            case_id,
            e,
        )
        return None


def _validate_stellar_jira_config(st: StellarSettings) -> None:
    if not st.stellar_base_url or not st.stellar_api_key:
        raise ValueError("Set STELLAR_BASE_URL and STELLAR_API_KEY in .env")
    jira = get_jira_settings()
    if not jira.jira_base_url or not jira.jira_user_email or not jira.jira_api_token:
        raise ValueError("Set JIRA_BASE_URL, JIRA_USER_EMAIL, and JIRA_API_TOKEN for Stellar→Jira create")
    if not (st.stellar_jira_project_key or "").strip():
        raise ValueError("Set STELLAR_JIRA_PROJECT_KEY (e.g. AIXSOC)")
    if not (st.stellar_jira_issue_type_id or "").strip():
        raise ValueError("Set STELLAR_JIRA_ISSUE_TYPE_ID")


def _prioritize_inbound_cases(
    cases: list[dict[str, Any]],
    *,
    source_id: str,
    state: SyncState,
) -> list[dict[str, Any]]:
    """Linked cases first so mirror (status/assignee) is not delayed behind deferred creates."""
    synced: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("_id") or "").strip()
        if cid and state.has_incident(source_id, cid):
            synced.append(case)
        else:
            other.append(case)
    synced.sort(key=lambda x: int(x.get("modified_at") or 0), reverse=True)
    other.sort(key=lambda x: int(x.get("modified_at") or 0))
    return synced + other


async def _apply_cases_to_jira(
    cases: list[dict[str, Any]],
    *,
    source_id: str,
    window_start_ms: int,
    state: SyncState,
    st: StellarSettings,
    dry_run: bool,
    jira: JiraClient | None,
    client: StellarClient,
    update_watermark: bool,
    tenant_registry: list[StellarTenant] | None = None,
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    would_create: list[dict[str, Any]] = []
    status_updated: list[dict[str, Any]] = []
    assignee_updated: list[dict[str, Any]] = []
    activity_posted: list[dict[str, Any]] = []
    poll_mirror_updated: list[dict[str, Any]] = []
    deferred_decision: list[dict[str, Any]] = []
    severity_escalation_refreshed: list[dict[str, Any]] = []
    skipped = 0
    skipped_severity = 0
    errors: list[dict[str, Any]] = []
    watermark_mod_ms = 0
    failed_modified_at_ms: list[int] = []
    tenant_stats: dict[str, dict[str, int]] = {}
    quarantined: list[dict[str, Any]] = []
    maiagent_all_cases: list[dict[str, Any]] = []
    ai_summary_deliveries: list[dict[str, Any]] = []
    notify_settings = get_notify_settings()
    all_cases_configured = bool(
        notify_settings.maiagent_all_cases_configured and not dry_run
    )
    all_cases_started_ms = 0
    all_cases_initializing = False
    if all_cases_configured:
        init_key = state.maiagent_all_cases_initialized_key(source_id)
        raw_started = state.get_meta(init_key)
        if raw_started:
            all_cases_started_ms = int(raw_started)
        else:
            all_cases_started_ms = int(time.time() * 1000)
            state.set_meta(init_key, str(all_cases_started_ms))
            all_cases_initializing = True
    dry_preview_seq = 0
    global_allowed_severities = st.allowed_sync_severities()
    decision_store = None
    snapshot_store = None
    if not dry_run:
        if st.decision_enabled:
            try:
                decision_store = get_decision_store(REPO_ROOT / st.stellar_sync_state_db)
            except Exception as e:
                logger.warning("decision store unavailable: %s", e)
        if st.case_archive_enabled or st.case_archive_on_severity_escalation:
            try:
                snapshot_store = get_case_snapshot_store(REPO_ROOT / st.stellar_sync_state_db)
            except Exception as e:
                logger.warning("case snapshot store unavailable: %s", e)

    default_proj = st.stellar_jira_project_key or "AIXSOC"
    itype_id = st.stellar_jira_issue_type_id or "10092"
    sev_field = st.stellar_jira_severity_field or "customfield_10057"
    status_field = st.stellar_jira_status_field or "customfield_10061"
    alert_field = st.stellar_jira_alert_name_field
    res_tag_field = (st.stellar_jira_resolution_tag_field or "").strip() or None
    case_field = st.stellar_case_id_jira_field or "customfield_10060"

    if tenant_registry:
        seen_case_ids = {
            str(case.get("_id") or "").strip()
            for case in cases
            if isinstance(case, dict)
        }
        for item in state.list_quarantined_cases(source_id):
            qcase = item.get("case")
            if not isinstance(qcase, dict):
                continue
            qid = str(qcase.get("_id") or "").strip()
            tenant, _ = resolve_case_tenant(tenant_registry, qcase)
            if qid and qid not in seen_case_ids and tenant is not None and tenant.sync_is_enabled():
                cases.append(qcase)
                seen_case_ids.add(qid)

    cases = _prioritize_inbound_cases(cases, source_id=source_id, state=state)

    for case in cases:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("_id") or "").strip()
        if not cid:
            continue
        mid = int(case.get("modified_at") or 0)
        tenant: StellarTenant | None = None
        tenant_reason = "legacy"
        if tenant_registry:
            tenant, tenant_reason = resolve_case_tenant(tenant_registry, case)
            tenant_key = tenant.source_id if tenant is not None else "(unknown)"
            stats = tenant_stats.setdefault(
                tenant_key,
                {
                    "fetched": 0,
                    "created": 0,
                    "would_create": 0,
                    "skipped": 0,
                    "skipped_severity": 0,
                    "quarantined": 0,
                },
            )
            stats["fetched"] += 1
            if (tenant is None and st.stellar_multi_tenant_strict) or (
                tenant is not None and not tenant.sync_is_enabled()
            ):
                reason = tenant_reason if tenant is None else "tenant_disabled"
                stats["quarantined"] += 1
                row = {
                    "source_id": source_id,
                    "case_id": cid,
                    "tenant_id": str(case.get("cust_id") or ""),
                    "tenant_name": str(case.get("tenant_name") or ""),
                    "reason": reason,
                }
                quarantined.append(row)
                if not dry_run:
                    state.quarantine_case(source_id, case, reason=reason)
                watermark_mod_ms = note_watermark_mod(watermark_mod_ms, mid)
                continue
        else:
            tenant_key = "(legacy)"
            stats = tenant_stats.setdefault(
                tenant_key,
                {
                    "fetched": 0,
                    "created": 0,
                    "would_create": 0,
                    "skipped": 0,
                    "skipped_severity": 0,
                    "quarantined": 0,
                },
            )
            stats["fetched"] += 1

        customer_code = (
            tenant.customer_code
            if tenant is not None
            else customer_code_from_case(case, default=st.stellar_default_customer_code)
        )
        allowed_severities = (
            set(tenant.allowed_severities)
            if tenant is not None and tenant.allowed_severities is not None
            else global_allowed_severities
        )
        proj = (
            tenant.jira_project_key
            if tenant is not None and tenant.jira_project_key
            else default_proj
        )
        maiagent_prefetched_bundle: dict[str, Any] | None = None
        if all_cases_configured:
            created_ms = _case_created_at_ms(case)
            prior_delivery_status = state.get_maiagent_case_status(source_id, cid)
            is_retry = prior_delivery_status in ("pending", "failed")
            if (
                not is_retry
                and (
                    all_cases_initializing
                    or created_ms <= 0
                    or created_ms < all_cases_started_ms
                )
            ):
                state.mark_maiagent_case_baseline(source_id, cid)
                maiagent_all_cases.append({"case_id": cid, "status": "baseline"})
            else:
                existing_jira = (
                    state.get_jira_key(source_id, cid)
                    if state.has_incident(source_id, cid)
                    else ""
                )
                all_case_row, maiagent_prefetched_bundle = (
                    await _schedule_maiagent_all_case(
                        state=state,
                        source_id=source_id,
                        case=case,
                        customer_code=customer_code,
                        client=client,
                        settings=notify_settings,
                        jira_key=str(existing_jira or ""),
                    )
                )
                maiagent_all_cases.append(all_case_row)

        if not state.has_incident(source_id, cid) and not case_severity_allowed(case, allowed_severities):
            # Do not queue Low/Medium forever: escalation bumps modified_at → next poll creates.
            # Do not archive full alert bundles here (noise + DB bloat); escalate→create archives then.
            skipped_severity += 1
            stats["skipped_severity"] += 1
            if not dry_run:
                state.remove_deferred_create(source_id, cid)
                state.remove_quarantined_case(source_id, cid)
            continue

        if dry_run:
            if state.has_incident(source_id, cid):
                skipped += 1
                stats["skipped"] += 1
                watermark_mod_ms = note_watermark_mod(watermark_mod_ms, mid)
                continue
        else:
            claim = state.try_claim(source_id, cid)
            if claim == "synced":
                if tenant is not None and not dry_run:
                    state.update_incident_tenant(
                        source_id,
                        cid,
                        tenant_source_id=tenant.source_id,
                        tenant_id=str(tenant.tenant_id or ""),
                        tenant_name=str(tenant.tenant_name or ""),
                        customer_code=customer_code,
                    )
                    state.remove_quarantined_case(source_id, cid)
                watermark_mod_ms = note_watermark_mod(watermark_mod_ms, mid)
                jkey = state.get_jira_key(source_id, cid) if jira is not None else None
                if jira is not None and jkey:
                    use_poll_mirror = (
                        st.stellar_automation_jira_mirror
                        and st.stellar_mirror_on_poll
                        and not st.stellar_jira_master_after_link
                    )
                    if use_poll_mirror:
                        try:
                            m = await mirror_stellar_case_to_jira(
                                jira=jira,
                                issue_key=jkey,
                                case=case,
                                st=st,
                                dry_run=dry_run,
                            )
                            if m.get("updated"):
                                poll_mirror_updated.append(
                                    {
                                        "source_id": source_id,
                                        "case_id": cid,
                                        "jira_key": jkey,
                                        "status": (m.get("status") or {}).get("updated"),
                                        "assignee": (m.get("assignee") or {}).get("updated"),
                                    }
                                )
                            status_out = m.get("status") if isinstance(m.get("status"), dict) else {}
                            if status_out.get("updated"):
                                status_updated.append(
                                    {
                                        "source_id": source_id,
                                        "case_id": cid,
                                        "jira_key": jkey,
                                        "stellar_status": status_out.get("actions", {}).get("stellar_status"),
                                        "actions": status_out.get("actions"),
                                    }
                                )
                            elif status_out.get("skipped") and status_out.get("reason") == "no_transition":
                                logger.warning(
                                    "stellar→jira status: no workflow transition case_id=%s jira=%s stellar_status=%s %s",
                                    cid,
                                    jkey,
                                    case.get("status"),
                                    status_out.get("actions"),
                                )
                            assignee_out = m.get("assignee") if isinstance(m.get("assignee"), dict) else {}
                            if assignee_out.get("updated"):
                                assignee_updated.append(
                                    {
                                        "source_id": source_id,
                                        "case_id": cid,
                                        "jira_key": jkey,
                                        "assignee": assignee_out.get("assignee"),
                                    }
                                )
                            act = await mirror_stellar_activities_to_jira(
                                jira=jira,
                                issue_key=jkey,
                                case_id=cid,
                                client=client,
                                st=st,
                                state=state,
                                synced_at=state.get_link_synced_at(source_id, cid),
                                dry_run=dry_run,
                            )
                            if int(act.get("posted") or 0) > 0:
                                activity_posted.append(
                                    {
                                        "source_id": source_id,
                                        "case_id": cid,
                                        "jira_key": jkey,
                                        "posted": act.get("posted"),
                                    }
                                )
                            if not act.get("ok", True):
                                errors.append(
                                    {
                                        "source_id": source_id,
                                        "case_id": cid,
                                        "jira_key": jkey,
                                        "scope": "stellar_to_jira_activity",
                                        "error": act.get("error"),
                                        "http_status": act.get("http_status"),
                                    }
                                )
                        except JiraAPIError as e:
                            errors.append(
                                {
                                    "source_id": source_id,
                                    "case_id": cid,
                                    "jira_key": jkey,
                                    "scope": "stellar_to_jira_mirror",
                                    "error": str(e),
                                    "http_status": e.status_code,
                                    "body": e.body,
                                }
                            )
                    else:
                        push_status_to_jira = (
                            st.stellar_sync_stellar_to_jira_status
                            and not st.stellar_jira_master_after_link
                        )
                        if push_status_to_jira and str(case.get("status") or "").strip():
                            try:
                                one = await apply_stellar_status_to_jira(
                                    jira=jira,
                                    issue_key=jkey,
                                    stellar_status=str(case.get("status") or ""),
                                    st=st,
                                    dry_run=False,
                                )
                                if one.get("updated"):
                                    status_updated.append(
                                        {
                                            "source_id": source_id,
                                            "case_id": cid,
                                            "jira_key": jkey,
                                            "stellar_status": one.get("actions", {}).get("stellar_status"),
                                            "actions": one.get("actions"),
                                        }
                                    )
                                elif one.get("skipped") and one.get("reason") == "no_transition":
                                    logger.warning(
                                        "stellar→jira status: no workflow transition case_id=%s jira=%s stellar_status=%s %s",
                                        cid,
                                        jkey,
                                        case.get("status"),
                                        one.get("actions"),
                                    )
                                elif one.get("skipped") and one.get("reason") not in (
                                    "already_in_sync",
                                    "status_sync_disabled",
                                    "workflow_sync_disabled",
                                    "unmapped_stellar_status",
                                ):
                                    logger.info(
                                        "stellar→jira status skipped case_id=%s jira=%s reason=%s",
                                        cid,
                                        jkey,
                                        one.get("reason"),
                                    )
                            except JiraAPIError as e:
                                errors.append(
                                    {
                                        "source_id": source_id,
                                        "case_id": cid,
                                        "jira_key": jkey,
                                        "scope": "stellar_to_jira_status",
                                        "error": str(e),
                                        "http_status": e.status_code,
                                        "body": e.body,
                                    }
                                )
                        push_assignee_to_jira = (
                            st.stellar_sync_stellar_to_jira_assignee
                            and not st.stellar_jira_master_after_link
                        )
                        if push_assignee_to_jira:
                            try:
                                aone = await apply_stellar_assignee_to_jira(
                                    jira=jira,
                                    issue_key=jkey,
                                    case=case,
                                    dry_run=False,
                                )
                                if aone.get("updated"):
                                    assignee_updated.append(
                                        {
                                            "source_id": source_id,
                                            "case_id": cid,
                                            "jira_key": jkey,
                                            "assignee": aone.get("assignee"),
                                        }
                                    )
                                elif aone.get("skipped") and aone.get("reason") not in (
                                    "already_in_sync",
                                    "stellar_unassigned",
                                ):
                                    logger.info(
                                        "stellar→jira assignee skipped case_id=%s jira=%s reason=%s",
                                        cid,
                                        jkey,
                                        aone.get("reason"),
                                    )
                            except JiraAPIError as e:
                                errors.append(
                                    {
                                        "source_id": source_id,
                                        "case_id": cid,
                                        "jira_key": jkey,
                                        "scope": "stellar_to_jira_assignee",
                                        "error": str(e),
                                        "http_status": e.status_code,
                                        "body": e.body,
                                    }
                                )
                    if (
                        st.stellar_ai_summary_enabled
                        and case_severity_allowed(case, allowed_severities)
                    ):
                        ai_delivery = await _maybe_deliver_ai_summary(
                            state=state,
                            source_id=source_id,
                            case=case,
                            jira_key=jkey,
                            jira=jira,
                            settings=st,
                            snapshot_store=snapshot_store,
                        )
                        if ai_delivery is not None:
                            ai_summary_deliveries.append(ai_delivery)
                await _maybe_severity_escalation_refresh(
                    st=st,
                    client=client,
                    case=case,
                    source_id=source_id,
                    customer_code=customer_code,
                    jira_key=jkey or "",
                    snapshot_store=snapshot_store,
                    decision_store=decision_store,
                    refreshed=severity_escalation_refreshed,
                )
                skipped += 1
                stats["skipped"] += 1
                continue
            if claim == "pending" and jira is not None:
                recovered = await _reconcile_pending_jira(
                    jira,
                    project_key=proj,
                    source_id=source_id,
                    case_id=cid,
                )
                if recovered:
                    state.record(
                        source_id,
                        cid,
                        recovered,
                        tenant_source_id=tenant.source_id if tenant is not None else "",
                        tenant_id=str(tenant.tenant_id or "") if tenant is not None else str(case.get("cust_id") or ""),
                        tenant_name=str(tenant.tenant_name or "") if tenant is not None else str(case.get("tenant_name") or ""),
                        customer_code=customer_code,
                    )
                    state.remove_quarantined_case(source_id, cid)
                    skipped += 1
                    stats["skipped"] += 1
                    watermark_mod_ms = note_watermark_mod(watermark_mod_ms, mid)
                    continue

        try:
            bundle: dict[str, Any] = {"case_id": cid, "case": case}
            if not dry_run:
                bundle = (
                    maiagent_prefetched_bundle
                    if isinstance(maiagent_prefetched_bundle, dict)
                    else await client.fetch_case_bundle(cid)
                )

            snapshot_id: str | None = None
            if not dry_run:
                snapshot_id = await archive_stellar_bundle(
                    st=st,
                    client=client,
                    case=case,
                    bundle=bundle,
                    source_id=source_id,
                    customer_code=customer_code,
                    snapshot_store=snapshot_store,
                    dry_run=dry_run,
                )

            if dry_run:
                dry_preview_seq += 1
                middleware_case_id = peek_next_case_id(
                    state,
                    prefix=st.stellar_case_id_prefix,
                    customer_code=customer_code,
                    timezone_name=st.stellar_case_id_timezone,
                    seq_offset=dry_preview_seq,
                )
            else:
                middleware_case_id = peek_next_case_id(
                    state,
                    prefix=st.stellar_case_id_prefix,
                    customer_code=customer_code,
                    timezone_name=st.stellar_case_id_timezone,
                )

            decision = None
            if st.decision_enabled:
                skip_decision = bool(
                    getattr(st, "decision_only_without_cortex_case_id", True)
                    and stellar_bundle_has_cortex_case_id(bundle)
                )
                if skip_decision:
                    logger.info(
                        "decision skipped (cortex case_id present) case_id=%s ticket_id=%s",
                        cid,
                        case.get("ticket_id"),
                    )
                else:
                    decision = await evaluate_case_decision(
                        case=case,
                        bundle=bundle,
                        source_id=source_id,
                        customer_code=customer_code,
                        middleware_case_id=middleware_case_id,
                        store=decision_store,
                        run_ai=bool(getattr(st, "decision_run_ai_on_create", False)),
                        persist=not dry_run,
                        snapshot_id=snapshot_id,
                    )
                    if decision is not None and not should_create_ticket(decision):
                        if not dry_run:
                            state.release_claim(source_id, cid)
                            state.add_deferred_create(source_id, cid)
                        deferred_decision.append(
                            {
                                "source_id": source_id,
                                "case_id": cid,
                                "action": decision.action,
                                "escalation": decision.escalation,
                                "playbook_id": decision.playbook_id,
                                "rule_hits": list(decision.rule_hits),
                                "summary": decision.summary,
                            }
                        )
                        continue

            fields = build_jira_issue_fields(
                project_key=proj,
                issue_type_id=itype_id,
                severity_field_id=sev_field,
                status_field_id=status_field,
                alert_name_field_id=alert_field,
                resolution_tag_field_id=res_tag_field,
                case_id_jira_field=case_field,
                summary_template=st.stellar_summary_template,
                customer_code=customer_code,
                tenant_source_id=tenant.source_id if tenant is not None else "",
                tenant_name=str(tenant.tenant_name or "") if tenant is not None else str(case.get("tenant_name") or ""),
                tenant_id=str(tenant.tenant_id or "") if tenant is not None else str(case.get("cust_id") or ""),
                tenant_labels=list(tenant.jira_labels) if tenant is not None else None,
                middleware_case_id=middleware_case_id,
                case=case,
                bundle=bundle,
            )
            if decision is not None:
                fields = apply_decision_to_jira_fields(fields, decision)

            if dry_run:
                row = {
                    "source_id": source_id,
                    "case_id": cid,
                    "middleware_case_id": middleware_case_id,
                    "summary": str(fields.get("summary") or "")[:200],
                }
                if decision is not None:
                    row["decision"] = {
                        "action": decision.action,
                        "escalation": decision.escalation,
                        "playbook_id": decision.playbook_id,
                        "notify_customer": decision.notify_customer,
                        "rule_hits": list(decision.rule_hits),
                    }
                would_create.append(row)
                stats["would_create"] += 1
                continue

            assert jira is not None
            res = await jira.create_issue_resilient(fields)
            key = str(res.get("key") or "")
            if not key:
                state.release_claim(source_id, cid)
                state.add_deferred_create(source_id, cid)
                if mid > 0:
                    failed_modified_at_ms.append(mid)
                errors.append({"source_id": source_id, "case_id": cid, "error": "no key in Jira response"})
                continue

            middleware_case_id = commit_case_id(
                state,
                prefix=st.stellar_case_id_prefix,
                customer_code=customer_code,
                timezone_name=st.stellar_case_id_timezone,
            )
            state.record(
                source_id,
                cid,
                key,
                tenant_source_id=tenant.source_id if tenant is not None else "",
                tenant_id=str(tenant.tenant_id or "") if tenant is not None else str(case.get("cust_id") or ""),
                tenant_name=str(tenant.tenant_name or "") if tenant is not None else str(case.get("tenant_name") or ""),
                customer_code=customer_code,
            )
            state.remove_deferred_create(source_id, cid)
            state.remove_quarantined_case(source_id, cid)
            stats["created"] += 1
            if (
                not dry_run
                and jira is not None
                and (st.stellar_sync_stellar_to_jira_status or st.stellar_sync_stellar_to_jira_assignee)
            ):
                try:
                    await mirror_stellar_case_to_jira(
                        jira=jira,
                        issue_key=key,
                        case=case,
                        st=st,
                        dry_run=False,
                    )
                except Exception as e:
                    logger.warning("post-create jira mirror failed case_id=%s jira=%s: %s", cid, key, e)
            if decision is not None and decision_store is not None:
                event_id = str((decision.context_snapshot or {}).get("decision_event_id") or "")
                if event_id:
                    try:
                        decision_store.update_jira_key(event_id, key)
                    except Exception as e:
                        logger.warning("decision jira_key update failed: %s", e)
            decision_comment_ok: bool | None = None
            if (
                decision is not None
                and jira is not None
                and getattr(st, "decision_jira_comment_on_create", True)
            ):
                try:
                    from app.decision.jira_notes import format_decision_create_comment

                    await jira.add_comment(
                        key,
                        format_decision_create_comment(
                            decision,
                            middleware_case_id=middleware_case_id,
                            case=case,
                            bundle=bundle,
                        ),
                    )
                    decision_comment_ok = True
                except Exception as e:
                    logger.warning("decision create comment failed jira=%s: %s", key, e)
                    decision_comment_ok = False
            if snapshot_id and snapshot_store is not None:
                try:
                    snapshot_store.update_jira_key(snapshot_id, key)
                except Exception as e:
                    logger.warning("snapshot jira_key update failed: %s", e)
            jira_s = get_jira_settings()
            created_row: dict[str, Any] = {
                "source_id": source_id,
                "case_id": cid,
                "middleware_case_id": middleware_case_id,
                "jira_key": key,
            }
            ai_delivery = await _maybe_deliver_ai_summary(
                state=state,
                source_id=source_id,
                case=case,
                jira_key=key,
                jira=jira,
                settings=st,
                snapshot_store=snapshot_store,
            )
            if ai_delivery is not None:
                ai_summary_deliveries.append(ai_delivery)
                created_row["stellar_ai_summary"] = {
                    "status": ai_delivery.get("status"),
                    "comment_posted": ai_delivery.get("comment_posted", False),
                    "triage_state": ai_delivery.get("triage_state", ""),
                }
            if decision_comment_ok is not None:
                created_row["decision_comment"] = {"posted": decision_comment_ok}
            if decision is not None:
                created_row["decision"] = {
                    "action": decision.action,
                    "escalation": decision.escalation,
                    "playbook_id": decision.playbook_id,
                    "notify_customer": decision.notify_customer,
                    "isolate_host_advisory": decision.isolate_host,
                    "rule_hits": list(decision.rule_hits),
                    "knowledge_hits": list(decision.knowledge_hits)[:12],
                    "event_id": (decision.context_snapshot or {}).get("decision_event_id"),
                }
            do_notify = decision is None or should_notify_internal(decision)
            if do_notify:
                notify_status = await notify_ticket_created(
                    jira_key=key,
                    case_id=middleware_case_id,
                    summary=str(fields.get("summary") or ""),
                    customer_code=customer_code,
                    source_id=source_id,
                    external_id=cid,
                    severity=str(case.get("severity") or ""),
                    event_name=str(case.get("name") or ""),
                    platform="stellar",
                    jira_base_url=str(jira_s.jira_base_url) if jira_s.jira_base_url else None,
                    stellar_case=case,
                    stellar_bundle=bundle,
                    decision=decision.to_dict() if decision is not None else None,
                    ai_sections=decision.ai_sections if decision is not None else None,
                )
                if notify_status:
                    created_row["notify"] = notify_status
            elif decision is not None:
                created_row["notify"] = {
                    "skipped": True,
                    "reason": f"decision_action={decision.action}",
                }

            # Extra MaiAgent full-case push after Critical/High create (shared LINE channel)
            try:
                from app.config import get_notify_settings as _get_ns

                ns = _get_ns()
                if ns.maiagent_notify_enabled:
                    mai = await maybe_notify_maiagent_personal(
                        jira_key=key,
                        case_id=middleware_case_id,
                        customer_code=customer_code,
                        stellar_case=case,
                        stellar_bundle=bundle,
                        decision=decision.to_dict() if decision is not None else None,
                        settings=ns,
                    )
                    if mai is not None:
                        created_row["maiagent_personal"] = mai
            except Exception as e:
                logger.warning("MaiAgent personal notify hook failed: %s", e)
                created_row["maiagent_personal"] = {"ok": False, "error": str(e)}

            # Decision↔AI merge: one LLM (prefer notify), then seed decision_events.
            if st.decision_record_ai and decision_store is not None and decision is not None:
                event_id = str((decision.context_snapshot or {}).get("decision_event_id") or "")
                ai_blob = extract_ai_sections_blob(created_row.get("notify"))
                if not ai_blob and isinstance(decision.ai_sections, dict):
                    ai_blob = {"ok": True, **decision.ai_sections}
                if not ai_blob:
                    try:
                        ns = get_notify_settings()
                        if ns.soc_notify_ai_configured:
                            ai_blob = await generate_ai_aligned_with_decision(
                                case=case,
                                bundle=bundle,
                                middleware_case_id=middleware_case_id,
                                customer_code=customer_code,
                                decision=decision,
                                settings=ns,
                            )
                            created_row["decision_ai"] = {
                                "ok": bool(ai_blob.get("ok")),
                                "source": "post_create_seed",
                            }
                    except Exception as e:
                        logger.warning("decision AI post-create seed failed: %s", e)
                if event_id and seed_decision_ai(decision_store, event_id=event_id, ai_blob=ai_blob):
                    created_row.setdefault("decision", {})
                    if isinstance(created_row.get("decision"), dict):
                        created_row["decision"]["ai_seeded"] = True
            created.append(created_row)
            watermark_mod_ms = note_watermark_mod(watermark_mod_ms, mid)
        except (JiraAPIError, StellarAPIError, ValueError) as e:
            if not dry_run:
                state.release_claim(source_id, cid)
                state.add_deferred_create(source_id, cid)
                if mid > 0:
                    failed_modified_at_ms.append(mid)
            extra: dict[str, Any] = {"source_id": source_id, "case_id": cid, "error": str(e)}
            if isinstance(e, JiraAPIError):
                extra["http_status"] = e.status_code
                extra["body"] = e.body
            errors.append(extra)

    if not dry_run and update_watermark:
        existing_wm = int(state.get_meta(watermark_meta_key(source_id)) or 0)
        new_wm = finalize_watermark_ms(
            watermark_mod_ms,
            failed_modified_at_ms=failed_modified_at_ms,
            existing_watermark_ms=existing_wm,
        )
        if failed_modified_at_ms and new_wm < max(watermark_mod_ms, existing_wm):
            logger.info(
                "stellar watermark capped for retry source_id=%s wm=%s cap=%s failed=%s",
                source_id,
                max(watermark_mod_ms, existing_wm),
                new_wm,
                len(failed_modified_at_ms),
            )
        if new_wm > 0:
            state.set_meta(watermark_meta_key(source_id), str(new_wm))

    out: dict[str, Any] = {
        "ok": not errors,
        "source_id": source_id,
        "dry_run": dry_run,
        "watermark_start_ms": window_start_ms,
        "fetched": len(cases),
        "created": created,
        "skipped_already_synced": skipped,
        "skipped_severity": skipped_severity,
        "deferred_decision": deferred_decision,
        "status_updated": status_updated,
        "assignee_updated": assignee_updated,
        "activity_posted": activity_posted,
        "poll_mirror_updated": poll_mirror_updated,
        "severity_escalation_refreshed": severity_escalation_refreshed,
        "tenant_stats": tenant_stats,
        "tenant_quarantined": quarantined,
        "maiagent_all_cases": maiagent_all_cases,
        "stellar_ai_summary": ai_summary_deliveries,
        "errors": errors,
    }
    if dry_run:
        out["would_create"] = would_create
    persist_per_source_sync_meta(state, source_id, dry_run=dry_run, skipped=skipped, out=out)
    if not dry_run:
        import json

        for tenant_key, stats in tenant_stats.items():
            state.set_meta(
                f"last_tenant_stats:{tenant_key}",
                json.dumps(stats, ensure_ascii=False, sort_keys=True),
            )
    return out


async def _run_stellar_to_jira_sync_locked(*, dry_run: bool = False) -> dict[str, Any]:
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    get_notify_settings.cache_clear()
    st = get_stellar_settings()
    _validate_stellar_jira_config(st)

    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"
    tenant_registry: list[StellarTenant] | None = None
    if st.stellar_multi_tenant_enabled:
        tenant_registry = load_stellar_tenants(st, REPO_ROOT)
        registry_errors = validate_tenant_registry(tenant_registry)
        if registry_errors:
            raise ValueError(
                "Invalid multi-tenant registry: " + "; ".join(registry_errors)
            )
    state_path = REPO_ROOT / st.stellar_sync_state_db
    state = SyncState(state_path)
    state.init(legacy_source_id=source_id)

    now_ms = int(time.time() * 1000)
    raw_watermark = state.get_meta(watermark_meta_key(source_id))
    if raw_watermark:
        start_ms = int(raw_watermark) - BACKOFF_MS
    else:
        start_ms = now_ms - st.stellar_sync_lookback_minutes * 60 * 1000

    jira: JiraClient | None = None if dry_run else JiraClient(get_jira_settings())
    max_pages = st.stellar_sync_max_pages
    truncated = False

    async with StellarClient(
        base_url=str(st.stellar_base_url).rstrip("/"),
        api_key=st.stellar_api_key or "",
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=None if st.stellar_multi_tenant_enabled else st.stellar_tenant_id,
        http_max_retries=st.stellar_http_max_retries,
    ) as client:
        try:
            cases, truncated = await client.fetch_cases_modified_since(
                start_ms,
                page_size=st.stellar_sync_page_size,
                max_pages=max_pages,
            )
        except StellarAPIError as e:
            err_entry = stellar_error_dict(e, source_id=source_id)
            out_err: dict[str, Any] = {
                "ok": False,
                "source_id": source_id,
                "error": "stellar",
                "detail": str(e),
                "http_status": e.status_code,
                "error_type": e.error_type,
                "dry_run": dry_run,
                "watermark_start_ms": start_ms,
                "fetched": 0,
                "created": [],
                "skipped_already_synced": 0,
                "errors": [err_entry],
            }
            persist_per_source_sync_meta(state, source_id, dry_run=dry_run, skipped=0, out=out_err)
            return out_err

        cases = await _inject_maiagent_retry_cases(
            cases,
            source_id=source_id,
            state=state,
            client=client,
            settings=get_notify_settings(),
            dry_run=dry_run,
        )
        cases = await _inject_ai_summary_retry_cases(
            cases,
            source_id=source_id,
            state=state,
            client=client,
            settings=st,
            dry_run=dry_run,
        )
        cases = await _inject_deferred_cases(
            cases,
            source_id=source_id,
            state=state,
            client=client,
            dry_run=dry_run,
            allowed_severities=st.allowed_sync_severities(),
        )
        out = await _apply_cases_to_jira(
            cases,
            source_id=source_id,
            window_start_ms=start_ms,
            state=state,
            st=st,
            dry_run=dry_run,
            jira=jira,
            client=client,
            update_watermark=not dry_run,
            tenant_registry=tenant_registry,
        )

    if truncated:
        append_truncation_error(
            out,
            source_id=source_id,
            scope="stellar",
            max_pages=max_pages,
            page_size_env_hint="STELLAR_SYNC_PAGE_SIZE",
        )
    return out


async def run_stellar_to_jira_sync(*, dry_run: bool = False) -> dict[str, Any]:
    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    lock_path = REPO_ROOT / st.stellar_sync_state_db
    lock_path = lock_path.with_suffix(lock_path.suffix + ".lock")
    try:
        with sync_process_lock(lock_path):
            return await _run_stellar_to_jira_sync_locked(dry_run=dry_run)
    except SyncLockError as e:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error": "sync_lock",
            "detail": str(e),
            "source_id": st.stellar_poll_source_id or "stellar",
            "fetched": 0,
            "created": [],
            "skipped_already_synced": 0,
            "errors": [{"scope": "sync_lock", "detail": str(e)}],
        }
