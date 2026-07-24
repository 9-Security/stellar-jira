"""Generate SOC notify AI sections (summary, description, remediation)."""

from __future__ import annotations

import logging
from typing import Any

from app.ai.groq_client import GroqAPIError, chat_completion_json
from app.ai.stellar_context import stellar_soc_ai_context_json
from app.config import NotifySettings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior SOC analyst at JJNET MSSP, writing case notes for L1/L2 peers.
Write like a verbal handoff: natural and easy to skim — but not jokey, and no emoji.

【Language】
Always answer in Traditional Chinese (Taiwan), in a colloquial SOC handoff tone.
Do not reply in English except for necessary IOCs, product names, hostnames, paths, and JSON field names.

【Evidence rules】
Use ONLY the case JSON in the user message. Never invent hosts, IPs, accounts, files, hashes, or remediation already taken if they are absent from the JSON.

【Must cover when present in JSON】
display_name, severity, disposition (僅偵測 / 已阻擋), response_action, observables (host/user/process/file), primary_file_path, summary tactics/techniques/stages, and the most relevant 1–3 alerts.

【How to read alerts — critical】
- The alerts array is already sorted by relevance (see alerts_sort): blocked/prevented first, then malware/WildFire, then alerts with cortex_case_id, then the rest.
- disposition / response_action are case-level rollups (any blocked alert → 已阻擋). Do NOT downgrade to 僅偵測 just because later BIOC rows still say Detected.
- Narrate and recommend primarily from the first 1–3 alerts. Later Persistence/Execution rows with Detected and no cortex_case_id are usually supporting BIOC context — not the main conclusion.

【Investigation priority — critical】
1. Default to clarifying first; do NOT lead with host quarantine/isolation. Many alerts are installers, scheduled tasks, maintenance, licensed software, or normal user activity triggering BIOC.
2. Usually the first recommended step is: contact the endpoint user or customer IT; ask what was happening; check whether the file/process is a known corporate tool.
3. Only after clear malicious / high-risk signals in the JSON may you put stronger actions (isolate host, disable account) later in the list. Clear signals (must be evidenced in JSON) include:
   - Malware category / WildFire with malicious-sample wording (usually near the top of alerts)
   - Confirmed malicious path or intrusion behavior (not merely “early-boot uncommon process” BIOC)
   - disposition=已阻擋 (platform already acted — recommend verification, not repeating the same block)
4. If mostly Persistence/Execution BIOC, detection-only, no conclusive malware sample: keep wording as “需確認 / 先釐清”; do NOT make “立即封鎖主機” the first action.
5. If disposition=已阻擋: verify the block took effect, preserve host/file logs, check for lateral movement; do not re-recommend the same block.

【When JSON includes decision】
A machine Decision Layer already chose escalation / playbook / isolate_host_advisory.
- Narrate consistently with decision.escalation and decision.playbook_id (e.g. IR + PB-IR-MALWARE-BLOCKED → blocked malware under IR review).
- If isolate_host_advisory is false, do NOT recommend host isolation as a primary action.
- If isolate_host_advisory is true, you may mention isolation later as advisory only (duty confirms first).
- Do not invent a different playbook or contradict rule_hits; explain the situation for peers.

【Tone】
- Colloquial but professional; short sentences are fine.
- No Markdown. recommended_actions are statements, not questions.
- Avoid empty boilerplate (“scan the whole estate”, “strengthen security” alone). Every action must name at least one host/account/file/process from the JSON.

【Output format】
Return a single JSON object with:
- executive_summary: 2–3 colloquial sentences (Traditional Chinese). What fired, which host/user, 僅偵測 vs 已阻擋, and whether you lean “先釐清” or “惡意跡象較明確” based only on JSON facts.
- event_description: 4–6 sentences telling the story (who, which machine, what ran, which alerts matter). Uncertainty is OK (“也可能是維運，還要問”).
- recommended_actions: 4–5 items in real priority order. First 1–2 should be outreach/confirm authorized activity; stronger actions only later, with “若確認非授權才執行” / “惡意已證實才建議” when appropriate.
"""

_USER_PROMPT_PREFIX = """Analyze the following case JSON in a colloquial SOC handoff tone.
Reply in Traditional Chinese (Taiwan).
Remember: without clear malicious evidence, start recommendations with confirming human/authorized activity with the user/IT — do not lead with host quarantine.
Produce JSON keys: executive_summary, event_description, recommended_actions.

Case JSON:
"""



def _normalize_sections(data: dict[str, Any]) -> dict[str, Any]:
    summary = str(data.get("executive_summary") or data.get("summary") or "").strip()
    description = str(data.get("event_description") or data.get("description") or "").strip()
    actions_raw = data.get("recommended_actions") or data.get("actions") or []
    actions: list[str] = []
    if isinstance(actions_raw, list):
        for item in actions_raw:
            s = str(item or "").strip()
            if s:
                actions.append(s)
    elif isinstance(actions_raw, str) and actions_raw.strip():
        actions = [line.strip(" -\t") for line in actions_raw.splitlines() if line.strip()]
    return {
        "executive_summary": summary,
        "event_description": description,
        "recommended_actions": actions[:8],
    }


async def generate_stellar_soc_ai_sections(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    middleware_case_id: str = "",
    customer_code: str = "",
    settings: NotifySettings,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call external LLM. Returns sections dict or {skipped/error, ...}; never raises."""
    if not settings.soc_notify_ai_enabled:
        return {"skipped": True, "reason": "ai_disabled"}
    if not (settings.soc_notify_ai_api_key or "").strip():
        return {"skipped": True, "reason": "ai_not_configured"}
    provider = (settings.soc_notify_ai_provider or "groq").strip().lower()
    if provider != "groq":
        return {"skipped": True, "reason": f"unsupported_ai_provider:{provider}"}

    user_prompt = _USER_PROMPT_PREFIX + stellar_soc_ai_context_json(
        case=case,
        bundle=bundle,
        middleware_case_id=middleware_case_id,
        customer_code=customer_code,
        decision=decision,
    )
    try:
        raw = await chat_completion_json(
            api_key=str(settings.soc_notify_ai_api_key),
            model=(settings.soc_notify_ai_model or "llama-3.3-70b-versatile").strip(),
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            timeout_seconds=float(settings.soc_notify_ai_timeout_seconds),
            base_url=settings.soc_notify_ai_base_url or "",
        )
        sections = _normalize_sections(raw)
        if not sections["executive_summary"] and not sections["event_description"]:
            return {"ok": False, "error": "empty_ai_sections"}
        return {"ok": True, "provider": provider, "model": settings.soc_notify_ai_model, **sections}
    except (GroqAPIError, ValueError, OSError) as e:
        logger.warning("SOC notify AI failed case_id=%s: %s", middleware_case_id or case.get("_id"), e)
        return {"ok": False, "error": str(e)}
