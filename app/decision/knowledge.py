"""Knowledge retrieval for Decision Layer (MITRE, Sigma catalogue, history, CMDB)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_PATH = REPO_ROOT / "config" / "decision_knowledge.json"
DEFAULT_ASSETS_PATH = REPO_ROOT / "config" / "decision_assets.json"


def load_knowledge(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_KNOWLEDGE_PATH
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.is_file():
        return _builtin_knowledge()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("failed to load knowledge %s: %s", p, e)
        return _builtin_knowledge()
    return data if isinstance(data, dict) else _builtin_knowledge()


def load_assets(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_ASSETS_PATH
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.is_file():
        return {"hosts": {}, "default_criticality": "medium"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("failed to load assets %s: %s", p, e)
        return {"hosts": {}, "default_criticality": "medium"}
    return data if isinstance(data, dict) else {"hosts": {}, "default_criticality": "medium"}


def _builtin_knowledge() -> dict[str, Any]:
    return {
        "version": "builtin-1",
        "mitre_playbooks": {
            "malware": "PB-IR-MALWARE",
            "credential access": "PB-L2-CREDS",
            "lateral movement": "PB-L2-LATERAL",
            "persistence": "PB-L1-PERSIST",
            "execution": "PB-L1-EXEC",
            "defense evasion": "PB-L2-EVASION",
            "initial access": "PB-L2-ACCESS",
        },
        "sigma_catalogue": [
            {
                "id": "SIGMA-PS-ENCODED",
                "title": "PowerShell EncodedCommand",
                "needles": ["powershell", "-enc", "encodedcommand", "frombase64string"],
                "playbook_id": "PB-PS-003",
                "escalate_hint": "L2",
            },
            {
                "id": "SIGMA-CRED-DUMP",
                "title": "Credential Dumping Indicators",
                "needles": ["lsass", "mimikatz", "procdump", "credential dumping", "sekurlsa"],
                "playbook_id": "PB-CRED-001",
                "escalate_hint": "IR",
            },
            {
                "id": "SIGMA-RANSOMWARE",
                "title": "Ransomware Behaviour",
                "needles": ["ransomware", "ransom", "vssadmin delete", "shadow copy"],
                "playbook_id": "PB-RANSOM-001",
                "escalate_hint": "IR",
            },
            {
                "id": "SIGMA-WILDFIRE",
                "title": "WildFire / Malware Sample",
                "needles": ["wildfire", "malware"],
                "playbook_id": "PB-IR-MALWARE",
                "escalate_hint": "IR",
            },
        ],
        "industry_defaults": {
            "banking": {"notify_customer_min_severity": "High", "default_escalation": "L2"},
            "default": {"notify_customer_min_severity": "Critical", "default_escalation": "L1"},
        },
    }


def _hostnames_from_bundle(bundle: dict[str, Any] | None) -> list[str]:
    obs_payload = (bundle or {}).get("observables")
    if not isinstance(obs_payload, dict):
        return []
    obs = obs_payload.get("observables")
    if not isinstance(obs, dict):
        return []
    names: list[str] = []
    for host in obs.get("host") or []:
        if isinstance(host, dict):
            for key in ("hostname", "name", "ip"):
                val = str(host.get(key) or "").strip()
                if val and val not in names:
                    names.append(val)
        else:
            val = str(host).strip()
            if val and val not in names:
                names.append(val)
    return names


def resolve_asset_criticality(
    *,
    bundle: dict[str, Any] | None,
    assets: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Return (criticality, matched_host_keys)."""
    doc = assets if assets is not None else load_assets()
    hosts_map = doc.get("hosts") if isinstance(doc.get("hosts"), dict) else {}
    default = str(doc.get("default_criticality") or "medium").strip().lower() or "medium"
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    best = default
    matched: list[str] = []
    for name in _hostnames_from_bundle(bundle):
        key = name.lower()
        entry = hosts_map.get(name) or hosts_map.get(key)
        if entry is None:
            # partial match on hostname keys
            for hk, hv in hosts_map.items():
                if str(hk).lower() in key or key in str(hk).lower():
                    entry = hv
                    key = str(hk)
                    break
        if entry is None:
            continue
        if isinstance(entry, dict):
            crit = str(entry.get("criticality") or default).strip().lower()
        else:
            crit = str(entry).strip().lower()
        matched.append(key)
        if rank.get(crit, 1) > rank.get(best, 1):
            best = crit
    return best, matched


def _text_blob(case: dict[str, Any], bundle: dict[str, Any] | None) -> str:
    parts = [str(case.get("name") or ""), str(case.get("display_name") or "")]
    primary = ""
    try:
        from app.stellar.alert_fields import stellar_primary_file_path

        primary = stellar_primary_file_path(bundle) or ""
    except Exception:
        primary = ""
    parts.append(primary)
    alerts_payload = (bundle or {}).get("alerts")
    if isinstance(alerts_payload, dict):
        data = alerts_payload.get("data")
        docs: list[Any] = []
        if isinstance(data, dict) and isinstance(data.get("docs"), list):
            docs = data["docs"]
        elif isinstance(data, list):
            docs = data
        for doc in docs[:20]:
            if not isinstance(doc, dict):
                continue
            src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
            if not isinstance(src, dict):
                continue
            parts.append(str(src.get("name") or ""))
            pan = src.get("palo_alto_networks")
            if isinstance(pan, dict):
                parts.append(str(pan.get("description") or ""))
                parts.append(str(pan.get("name") or ""))
                parts.append(str(pan.get("category") or ""))
            xdr = src.get("xdr_event")
            if isinstance(xdr, dict):
                parts.append(str(xdr.get("description") or ""))
    summary = (bundle or {}).get("summary")
    if isinstance(summary, dict):
        inner = summary.get("data")
        if isinstance(inner, dict):
            for key in ("tactics", "techniques", "stages"):
                val = inner.get(key)
                if isinstance(val, list):
                    parts.extend(str(x) for x in val)
    return " ".join(parts).lower()


def _tactics(bundle: dict[str, Any] | None) -> list[str]:
    summary = (bundle or {}).get("summary")
    if not isinstance(summary, dict):
        return []
    inner = summary.get("data")
    if not isinstance(inner, dict):
        return []
    tactics = inner.get("tactics")
    if not isinstance(tactics, list):
        return []
    return [str(t).strip().lower() for t in tactics if str(t).strip()]


def match_sigma_catalogue(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    knowledge: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from app.stellar.response_action import stellar_notify_disposition_label

    doc = knowledge if knowledge is not None else load_knowledge()
    catalogue = doc.get("sigma_catalogue") or []
    blob = _text_blob(case, bundle)
    blocked = stellar_notify_disposition_label(bundle) == "已阻擋"
    hits: list[dict[str, Any]] = []
    for entry in catalogue:
        if not isinstance(entry, dict):
            continue
        if entry.get("require_blocked") and not blocked:
            continue
        if entry.get("require_not_blocked") and blocked:
            continue
        needles = [str(n).strip().lower() for n in (entry.get("needles") or []) if str(n).strip()]
        if needles and any(n in blob for n in needles):
            hits.append(entry)
    # Prefer blocked-specific / IR hints when ranking suggested playbook
    def _rank(entry: dict[str, Any]) -> tuple[int, int]:
        blocked_pref = 0 if entry.get("require_blocked") else 1
        ir_pref = 0 if str(entry.get("escalate_hint") or "").upper() == "IR" else 1
        return (blocked_pref, ir_pref)

    hits.sort(key=_rank)
    return hits


def mitre_playbook_hints(
    *,
    bundle: dict[str, Any] | None,
    knowledge: dict[str, Any] | None = None,
) -> list[str]:
    doc = knowledge if knowledge is not None else load_knowledge()
    mapping = doc.get("mitre_playbooks") if isinstance(doc.get("mitre_playbooks"), dict) else {}
    hints: list[str] = []
    for tactic in _tactics(bundle):
        for key, pb in mapping.items():
            if str(key).lower() in tactic or tactic in str(key).lower():
                s = str(pb).strip()
                if s and s not in hints:
                    hints.append(s)
    return hints


def find_similar_cases(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    history: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Token overlap against prior decisions; boost rows that already have TP/FP outcome."""
    sev = str(case.get("severity") or "").strip().lower()
    tactics = set(_tactics(bundle))
    blob_tokens = set(_text_blob(case, bundle).split())
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in history:
        ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
        other_sev = str(ctx.get("severity") or "").strip().lower()
        other_tactics = {
            str(t).strip().lower()
            for t in (ctx.get("summary", {}) or {}).get("tactics") or []
            if str(t).strip()
        }
        other_name = str(ctx.get("display_name") or ctx.get("name") or "").lower()
        other_tokens = set(other_name.split())
        score = 0.0
        if sev and sev == other_sev:
            score += 2.0
        overlap_t = tactics & other_tactics
        score += 1.5 * len(overlap_t)
        score += 0.1 * len(blob_tokens & other_tokens)
        # Closed-loop value: prefer peers with labeled outcomes
        if row.get("outcome_true_positive") is True:
            score += 1.25
        elif row.get("outcome_true_positive") is False:
            score += 1.5  # FP peers help suppress mis-escalation
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "event_id": row.get("event_id"),
                    "stellar_case_id": row.get("stellar_case_id"),
                    "jira_key": row.get("jira_key"),
                    "playbook_id": row.get("playbook_id") or ctx.get("playbook_id"),
                    "action": row.get("action"),
                    "escalation": row.get("escalation"),
                    "outcome_true_positive": row.get("outcome_true_positive"),
                    "outcome_root_cause": row.get("outcome_root_cause"),
                    "score": round(score, 2),
                },
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def enrich_knowledge(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    customer_code: str = "",
    history: list[dict[str, Any]] | None = None,
    knowledge: dict[str, Any] | None = None,
    assets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate knowledge hits for the decision pipeline."""
    kn = knowledge if knowledge is not None else load_knowledge()
    criticality, matched_hosts = resolve_asset_criticality(bundle=bundle, assets=assets)
    sigma_hits = match_sigma_catalogue(case=case, bundle=bundle, knowledge=kn)
    mitre_pbs = mitre_playbook_hints(bundle=bundle, knowledge=kn)
    similar = find_similar_cases(
        case=case,
        bundle=bundle,
        history=history or [],
        limit=5,
    )
    knowledge_hit_ids = [str(s.get("id") or "") for s in sigma_hits if s.get("id")]
    knowledge_hit_ids.extend(f"mitre:{pb}" for pb in mitre_pbs)
    knowledge_hit_ids.extend(
        f"similar:{s.get('stellar_case_id') or s.get('event_id')}" for s in similar[:3]
    )
    if matched_hosts:
        knowledge_hit_ids.append(f"asset:{criticality}")

    suggested_playbook = ""
    escalate_hint = ""
    if sigma_hits:
        suggested_playbook = str(sigma_hits[0].get("playbook_id") or "")
        escalate_hint = str(sigma_hits[0].get("escalate_hint") or "")
    if not suggested_playbook and mitre_pbs:
        suggested_playbook = mitre_pbs[0]
    if not suggested_playbook and similar:
        # Prefer similar with outcome when suggesting playbook
        for peer in similar:
            pb = str(peer.get("playbook_id") or "").strip()
            if pb:
                suggested_playbook = pb
                break

    return {
        "asset_criticality": criticality,
        "matched_hosts": matched_hosts,
        "sigma_hits": sigma_hits,
        "mitre_playbooks": mitre_pbs,
        "similar_cases": similar,
        "knowledge_hits": knowledge_hit_ids,
        "suggested_playbook": suggested_playbook,
        "escalate_hint": escalate_hint,
        "customer_code": customer_code.strip().upper(),
    }
