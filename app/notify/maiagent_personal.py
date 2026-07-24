"""MaiAgent causal analysis notifications.

Personal delivery uses ``MAIAGENT_NOTIFY_*``. All-case delivery can override
the LINE recipient while remaining fail-open and independent from SOC pushes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.ai.groq_client import parse_json_object
from app.ai.maiagent_client import MaiAgentAPIError, chatbot_completion
from app.ai.stellar_context import stellar_causal_ai_context_json
from app.config import NotifySettings, get_notify_settings
from app.notify.email import parse_email_list, send_email
from app.notify.line_bot import parse_line_recipient_list, send_line_notify
from app.stellar.case_display_name import stellar_case_display_name
from app.stellar.cortex_fields import stellar_bundle_has_cortex_case_id

logger = logging.getLogger(__name__)

# Strong references to fire-and-forget async pushes so the event loop does not
# garbage-collect them before delivery completes.
_BG_TASKS: set[asyncio.Task] = set()

_CAUSAL_INSTRUCTION = """上方已附上 Stellar case 資料（JSON）。請立刻做完整因果重建，不要再索取檔案。

輸出 JSON（繁體中文；鍵名固定）：
executive_summary, timeline, causal_chains, parallel_noise, entity_map,
hypotheses, event_description, recommended_actions, open_questions。

規則：無共同 host/user/檔案證據不可硬串一鏈；標明已阻擋 vs 僅偵測；禁止捏造。
直接輸出 JSON。
"""

_ROOT_CAUSE_INSTRUCTION = """上方已附上完整 Stellar case 與其 alerts 資料（JSON）。
請綜合整個 case 內的所有 alerts、時間、主機、帳號、程序、檔案、網路與偵測結果，
直接說明這個 case 最可能的 Root Cause，以及各 alerts 如何支持或不支持這個判斷。
證據不足時必須明確說明無法確認，不可捏造。

只輸出一段連貫的繁體中文 Root Cause 分析正文。不要輸出 JSON，不要加入標題，
不要使用「摘要」、「Timeline」、「Causal chains」、「建議處置」或其他分段欄位。
"""


def _format_personal_body(
    *,
    jira_key: str,
    case_id: str,
    event_name: str,
    parsed: dict[str, Any] | None,
    raw_content: str,
    display_label: str = "MaiAgent 個人因果分析",
    analysis_heading: str = "",
    analysis_only: bool = False,
) -> str:
    if analysis_only:
        lines = [analysis_heading or "MaiAgent AI 分析:", ""]
    else:
        lines = [f"【{display_label}｜非正式 SOC 廣播】"]
        if analysis_heading:
            lines.extend([analysis_heading, ""])
        lines.extend(
            [
                f"Jira: {jira_key or '尚未建票'}",
                f"Case: {case_id}",
                f"事件: {event_name}",
                "",
            ]
        )
    if not isinstance(parsed, dict):
        if not analysis_only:
            lines.append("（未解析成 JSON，原始回覆摘要）")
        lines.append((raw_content or "")[:3500])
        return "\n".join(lines)

    summary = parsed.get("executive_summary")
    if isinstance(summary, dict):
        summary = summary.get("conclusion") or json.dumps(summary, ensure_ascii=False)
    lines.append(f"摘要：{str(summary or '').strip()}")
    lines.append("")

    timeline = parsed.get("timeline")
    if isinstance(timeline, list) and timeline:
        lines.append("【Timeline】")
        for row in timeline[:20]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {row.get('t') or '?'} | {row.get('host') or ''} | "
                f"{row.get('action') or ''} | {row.get('what') or ''}"
            )
        lines.append("")

    chains = parsed.get("causal_chains")
    if isinstance(chains, list) and chains:
        lines.append("【Causal chains】")
        for ch in chains[:8]:
            if not isinstance(ch, dict):
                continue
            lines.append(
                f"- {ch.get('chain_id') or '?'}: {ch.get('title') or ''} "
                f"(confidence={ch.get('confidence') or '?'})"
            )
            steps = ch.get("steps")
            if isinstance(steps, list):
                for s in steps[:8]:
                    lines.append(f"    → {s}")
        lines.append("")

    noise = parsed.get("parallel_noise")
    if isinstance(noise, list) and noise:
        lines.append("【並列雜訊】")
        for n in noise[:8]:
            lines.append(f"- {n}")
        lines.append("")

    actions = parsed.get("recommended_actions")
    if isinstance(actions, list) and actions:
        lines.append("【建議處置】")
        for a in actions[:8]:
            lines.append(f"- {a}")
        lines.append("")
    elif isinstance(actions, dict):
        lines.append("【建議處置】")
        lines.append(json.dumps(actions, ensure_ascii=False, indent=2)[:2000])
        lines.append("")

    questions = parsed.get("open_questions")
    if isinstance(questions, list) and questions:
        lines.append("【待釐清】")
        for q in questions[:8]:
            lines.append(f"- {q}")

    if not analysis_only:
        lines.extend(["", "（此訊息僅送 MAIAGENT_NOTIFY_* 收件人；SOC 廣播仍走 Groq。）"])
    return "\n".join(lines)


async def notify_maiagent_personal(
    *,
    jira_key: str,
    case_id: str,
    customer_code: str = "",
    stellar_case: dict[str, Any] | None = None,
    stellar_bundle: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    settings: NotifySettings | None = None,
    email_to_override: str | None = None,
    line_to_override: str | None = None,
    subject_prefix: str = "MaiAgent 個人",
    body_heading: str = "",
    analysis_only: bool = False,
    root_cause_only: bool = False,
    line_subject_override: str | None = None,
) -> dict[str, Any]:
    """Run MaiAgent full-case analysis and push. Never raises.

    Post-create path (``line_to_override is None``): LINE falls back to
    ``LINE_NOTIFY_TO`` when ``MAIAGENT_NOTIFY_LINE_TO`` is empty so SOC and
    MaiAgent share the same channel. Email stays on ``MAIAGENT_NOTIFY_*`` only.
    """
    st = settings or get_notify_settings()
    if not st.maiagent_notify_enabled and not st.maiagent_all_cases_enabled:
        return {"skipped": True, "reason": "maiagent_notify_disabled"}
    if not (st.maiagent_api_key or "").strip() or not (st.maiagent_chatbot_id or "").strip():
        return {"skipped": True, "reason": "maiagent_not_configured"}

    email_to = parse_email_list(
        st.maiagent_notify_email_to if email_to_override is None else email_to_override
    )
    if line_to_override is None:
        line_raw = (st.maiagent_notify_line_to or "").strip() or (st.line_notify_to or "")
    else:
        line_raw = line_to_override
    line_to = parse_line_recipient_list(line_raw)
    if not email_to and not line_to:
        return {"skipped": True, "reason": "no_personal_recipients"}

    case = stellar_case if isinstance(stellar_case, dict) else {}
    bundle = stellar_bundle if isinstance(stellar_bundle, dict) else {}
    if st.maiagent_notify_only_without_cortex_case_id and stellar_bundle_has_cortex_case_id(bundle):
        return {"skipped": True, "reason": "has_cortex_case_id"}

    event_name = stellar_case_display_name(case, bundle) if case else str(case_id)
    subject = f"[{subject_prefix}] [{jira_key or 'NO-JIRA'}] {event_name}"[:180]

    try:
        case_json = stellar_causal_ai_context_json(
            case=case,
            bundle=bundle,
            middleware_case_id=case_id,
            customer_code=customer_code,
            decision=decision if isinstance(decision, dict) else None,
        )
        message = (
            "【Stellar case 資料開始】\n"
            f"{case_json}\n"
            "【Stellar case 資料結束】\n\n"
            f"{_ROOT_CAUSE_INSTRUCTION if root_cause_only else _CAUSAL_INSTRUCTION}"
        )
        resp = await chatbot_completion(
            api_key=str(st.maiagent_api_key),
            chatbot_id=str(st.maiagent_chatbot_id),
            message=message,
            base_url=st.maiagent_base_url or "https://api.sungcheng.org/api",
            timeout_seconds=float(st.maiagent_timeout_seconds),
            is_streaming=False,
        )
        raw = str(resp.get("content") or "")
        parsed: dict[str, Any] | None = None
        if not root_cause_only:
            try:
                parsed = parse_json_object(raw)
            except (ValueError, json.JSONDecodeError):
                parsed = None
    except (MaiAgentAPIError, ValueError, OSError) as e:
        logger.warning("MaiAgent personal analysis failed jira=%s: %s", jira_key, e)
        return {"ok": False, "error": str(e), "jira_key": jira_key}

    if root_cause_only:
        body = "\n".join(
            [
                body_heading or "MaiAgent AI 分析:",
                "",
                raw.strip(),
            ]
        ).strip()
    else:
        body = _format_personal_body(
            jira_key=jira_key,
            case_id=case_id,
            event_name=event_name,
            parsed=parsed,
            raw_content=raw,
            display_label=subject_prefix,
            analysis_heading=body_heading,
            analysis_only=analysis_only,
        )
    out: dict[str, Any] = {
        "ok": True,
        "jira_key": jira_key,
        "conversation_id": resp.get("conversation_id") or "",
        "has_timeline": isinstance(parsed, dict) and isinstance(parsed.get("timeline"), list),
        "has_causal_chains": isinstance(parsed, dict)
        and isinstance(parsed.get("causal_chains"), list),
    }

    if email_to:
        if not st.is_configured:
            out["email"] = {"skipped": True, "reason": "smtp_or_resend_not_configured"}
        else:
            try:
                provider = await send_email(
                    to_addrs=email_to,
                    subject=subject,
                    body_text=body,
                    settings=st,
                )
                out["email"] = {"sent": True, "provider": provider, "recipients": email_to}
                logger.info(
                    "MaiAgent personal email sent jira_key=%s to=%s", jira_key, email_to
                )
            except Exception as e:
                logger.warning("MaiAgent personal email failed: %s", e)
                out["email"] = {"sent": False, "error": str(e)}

    if line_to:
        if not st.line_configured:
            out["line"] = {"skipped": True, "reason": "line_token_not_configured"}
        else:
            line_result = await send_line_notify(
                to_ids=line_to,
                subject=(
                    subject
                    if line_subject_override is None
                    else line_subject_override
                ),
                body_text=body,
                settings=st,
            )
            out["line"] = line_result
            if line_result.get("sent"):
                logger.info(
                    "MaiAgent personal LINE sent jira_key=%s to=%s",
                    jira_key,
                    line_result.get("recipients"),
                )

    email_sent = bool(out.get("email", {}).get("sent"))
    line_sent = bool(out.get("line", {}).get("sent"))
    out["sent"] = email_sent or line_sent
    if not out["sent"]:
        out["ok"] = bool(parsed)  # analysis ok even if delivery skipped
        if not out.get("email") and not out.get("line"):
            out["reason"] = "no_channel_attempted"
    return out


async def maybe_notify_maiagent_personal(
    *,
    jira_key: str,
    case_id: str,
    customer_code: str = "",
    stellar_case: dict[str, Any] | None = None,
    stellar_bundle: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    settings: NotifySettings | None = None,
) -> dict[str, Any] | None:
    """Entry used by sync runner after Critical/High create. Never raises.

    Runs full-case Root Cause analysis and pushes to the shared SOC LINE channel
    when ``MAIAGENT_NOTIFY_LINE_TO`` is empty (falls back to ``LINE_NOTIFY_TO``).
    """
    st = settings or get_notify_settings()
    if not st.maiagent_notify_enabled:
        return None

    async def _run() -> dict[str, Any]:
        try:
            return await notify_maiagent_personal(
                jira_key=jira_key,
                case_id=case_id,
                customer_code=customer_code,
                stellar_case=stellar_case,
                stellar_bundle=stellar_bundle,
                decision=decision,
                settings=st,
                subject_prefix="MaiAgent AI 分析",
                body_heading="MaiAgent AI 分析:",
                analysis_only=True,
                root_cause_only=True,
                line_subject_override="",
            )
        except Exception as e:
            logger.warning("MaiAgent personal notify crashed: %s", e)
            return {"ok": False, "error": str(e)}

    if st.maiagent_notify_async:
        task = asyncio.create_task(_run(), name=f"maiagent-personal-{jira_key}")
        _BG_TASKS.add(task)

        def _done(t: asyncio.Task) -> None:
            _BG_TASKS.discard(t)
            try:
                res = t.result()
                logger.info(
                    "MaiAgent personal async done jira=%s sent=%s ok=%s",
                    jira_key,
                    res.get("sent"),
                    res.get("ok"),
                )
            except Exception as e:
                logger.warning("MaiAgent personal async task error: %s", e)

        task.add_done_callback(_done)
        return {"scheduled": True, "async": True, "jira_key": jira_key}

    return await _run()
