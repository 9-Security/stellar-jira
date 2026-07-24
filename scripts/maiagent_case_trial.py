#!/usr/bin/env python3
"""Trial MaiAgent on a Stellar case without touching production SOC notify / Groq / systemd.

Uses separate env vars (never wired into the notify pipeline):
  MAIAGENT_API_KEY
  MAIAGENT_CHATBOT_ID
  MAIAGENT_BASE_URL          (default https://api.sungcheng.org/api)
  MAIAGENT_TIMEOUT_SECONDS   (default 60)

Does **not** send Email/LINE, does **not** write decision_events, does **not**
change SOC_NOTIFY_AI_*.

Examples:
  export MAIAGENT_API_KEY=... MAIAGENT_CHATBOT_ID=254a5b54-8920-4519-9d0c-c2b16ef4c300
  export MAIAGENT_BASE_URL=https://api.sungcheng.org/api
  ./Tools/run maiagent-trial --auth-check
  ./Tools/run maiagent-trial --from-export data/exports/case_1214.json --context soc --mode chatbot
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.groq_client import parse_json_object  # noqa: E402
from app.ai.maiagent_client import (  # noqa: E402
    MaiAgentAPIError,
    chatbot_completion,
    openai_chat_completion,
)
from app.ai.soc_notify import (  # noqa: E402
    _SYSTEM_PROMPT,
    _USER_PROMPT_PREFIX,
    _normalize_sections,
    generate_stellar_soc_ai_sections,
)
from app.ai.stellar_context import (  # noqa: E402
    stellar_causal_ai_context_json,
    stellar_soc_ai_context_json,
)
from app.config import get_notify_settings, get_stellar_settings  # noqa: E402
from app.stellar.client import StellarClient  # noqa: E402


def _load_maiagent_dotenv() -> None:
    """Load only MAIAGENT_* from repo .env into os.environ (do not override exports)."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    for k, v in (dotenv_values(env_path) or {}).items():
        if not k or not str(k).startswith("MAIAGENT_"):
            continue
        if os.environ.get(k):
            continue
        if v is None:
            continue
        os.environ[k] = str(v)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


_AGENTIC_INSTRUCTION_BRIEF = """請依你已載入的 Skill 分析「上方」Stellar case JSON。
用繁體中文。輸出 JSON：executive_summary, event_description, recommended_actions。
只根據 JSON 事實。不要再索取檔案——資料已在同一則訊息上方。
"""

_AGENTIC_INSTRUCTION_CAUSAL = """上方已附上 Stellar case 資料（JSON）。請立刻依你已載入的 Skill 做「完整因果重建」，不要再要求我提供檔案或 JSON。

【分析目標】
把 alerts 串成可驗證的因果關係：誰（host/user）→ 做了什麼（process/file/service）→ 觸發哪些 alert → 時間先後 → 同一條鏈 vs 並列雜訊 vs 推測。

【輸入】
- disposition=已阻擋 表示案內「至少一筆」Prevented/Blocked
- alerts[] 已依時間排序；每列含 host/user/process/path/action/description
- Cortex case_id 有無 ≠ 是否阻擋

【必須產出的 JSON】（鍵名固定；字串繁體中文）
{
  "executive_summary": "3–5 句主結論",
  "timeline": [
    {"t": "", "host": "", "user": "", "action": "", "what": "", "alert_ref": ""}
  ],
  "causal_chains": [
    {
      "chain_id": "C1",
      "title": "",
      "confidence": "high|medium|low",
      "steps": ["…"],
      "supporting_alerts": ["…"],
      "counter_evidence": []
    }
  ],
  "parallel_noise": ["…"],
  "entity_map": {"hosts": [], "users": [], "tools_or_malware": [], "key_paths": []},
  "hypotheses": [{"id": "H1", "claim": "", "confidence": "medium", "needs_to_confirm": ""}],
  "event_description": "主鏈敘事",
  "recommended_actions": ["…"],
  "open_questions": ["…"]
}

規則：無共同 host/user/檔案/父行程證據不可硬串一鏈；標明已阻擋 vs 僅偵測；禁止捏造。
請直接輸出上述 JSON（可包在 ```json 中），不要只回「我準備好了」。
"""

_FOLLOWUP_CAUSAL = """上一輪若尚未產出完整 JSON，請現在立刻產出。不要再索取 case JSON。
補強：更細 timeline、causal_chains（主鏈 vs parallel_noise）、證據 vs 推測、open_questions。
輸出鍵：executive_summary, timeline, causal_chains, parallel_noise, entity_map, hypotheses, event_description, recommended_actions, open_questions。
"""


def _looks_like_waiting_for_input(text: str) -> bool:
    t = (text or "").lower()
    if "```json" in t and "timeline" in t and "executive_summary" in t:
        return False
    needles = (
        "please provide",
        "to begin the analysis",
        "請提供",
        "請上傳",
        "i am ready",
        "ready to perform",
        "waiting for",
        "準備好了",
    )
    return any(n in t for n in needles)


def _build_message(
    *,
    context_mode: str,
    case_json_text: str,
    agentic: bool = False,
    depth: str = "causal",
    follow_up: bool = False,
) -> str:
    """Pack user message. Agentic: put JSON first so truncation keeps the evidence."""
    if agentic:
        if follow_up:
            return f"{case_json_text}\n\n---\n{_FOLLOWUP_CAUSAL}"
        instr = (
            _AGENTIC_INSTRUCTION_BRIEF if depth == "brief" else _AGENTIC_INSTRUCTION_CAUSAL
        )
        return (
            "【Stellar case 資料開始】\n"
            f"{case_json_text}\n"
            "【Stellar case 資料結束】\n\n"
            f"{instr}"
        )
    if context_mode == "full":
        return (
            "你是資安 SOC L1/L2 交接分析助手。請用繁體中文（台灣）口語交接語氣分析下列完整 case JSON。\n"
            "只依據 JSON 事實，不要捏造。產出單一 JSON 物件，鍵為：\n"
            "executive_summary, event_description, recommended_actions（字串陣列）。\n"
            "已阻擋 vs 僅偵測請看 disposition；alerts 若已排序則以前 1–3 則為主。\n"
            "沒有明確惡意跡象時，建議先聯絡使用者／IT 釐清，不要一開始就隔離主機。\n\n"
            f"Case JSON:\n{case_json_text}"
        )
    return f"{_SYSTEM_PROMPT}\n\n{_USER_PROMPT_PREFIX}{case_json_text}"

def _load_from_export(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Export is not a JSON object: {path}")
    if isinstance(data.get("bundle"), dict):
        bundle = data["bundle"]
    else:
        bundle = data
    case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
    if not case and isinstance(data.get("case"), dict):
        case = data["case"]
    # stellar-case-export puts ticket_id on meta; case object may omit it
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if meta.get("ticket_id") is not None and case.get("ticket_id") is None:
        case = {**case, "ticket_id": meta["ticket_id"]}
    if meta.get("stellar_case_id") and not case.get("_id"):
        case = {**case, "_id": meta["stellar_case_id"]}
    return case, bundle, data


async def _resolve_case_id(client: StellarClient, *, case_id: str, ticket_id: int | None) -> str:
    cid = str(case_id or "").strip()
    if cid:
        return cid
    if ticket_id is None:
        return ""
    try:
        raw = await client.list_cases(limit=20, search=str(ticket_id))
        for c in StellarClient.extract_cases_list(raw):
            if c.get("ticket_id") == ticket_id or str(c.get("ticket_id")) == str(ticket_id):
                return str(c.get("_id") or "")
    except Exception:
        pass
    for skip in range(0, 500, 50):
        raw = await client.list_cases(limit=50, skip=skip, sort="modified_at", order="desc")
        for c in StellarClient.extract_cases_list(raw):
            if c.get("ticket_id") == ticket_id or str(c.get("ticket_id")) == str(ticket_id):
                return str(c.get("_id") or "")
    return ""


async def _maybe_groq_compare(*, case: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    ns = get_notify_settings()
    if not ns.soc_notify_ai_configured:
        return {"skipped": True, "reason": "soc_notify_ai_not_configured"}
    t0 = time.perf_counter()
    out = await generate_stellar_soc_ai_sections(
        case=case,
        bundle=bundle,
        middleware_case_id=str(case.get("ticket_id") or case.get("_id") or ""),
        settings=ns,
    )
    out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


async def _auth_check(args: argparse.Namespace) -> int:
    """Probe MaiAgent auth without sending case content."""
    import httpx
    from app.ai.maiagent_client import _auth_headers

    api_key = (args.api_key or _env("MAIAGENT_API_KEY")).strip()
    chatbot_id = (args.chatbot_id or _env("MAIAGENT_CHATBOT_ID")).strip()
    base_url = (args.base_url or _env("MAIAGENT_BASE_URL", "https://api.sungcheng.org/api")).rstrip(
        "/"
    )
    timeout = float(args.timeout or _env("MAIAGENT_TIMEOUT_SECONDS", "30") or 30)
    out: dict[str, Any] = {
        "ok": False,
        "api_key_len": len(api_key),
        "api_key_prefix": (api_key.split(".", 1)[0] if api_key else ""),
        "looks_like_jwt": api_key.startswith("eyJ"),
        "base_url": base_url,
        "probes": [],
    }
    if not api_key:
        out["error"] = "MAIAGENT_API_KEY empty — paste full key (prefix.secret), not only prefix"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 2

    probes = [
        ("openai_models_bearer", "GET", f"{base_url}/models", "bearer"),
        ("chatbots_list_apikey", "GET", f"{base_url}/chatbots/", "api-key"),
    ]
    if chatbot_id:
        probes.append(
            ("chatbot_get_apikey", "GET", f"{base_url}/chatbots/{chatbot_id}/", "api-key")
        )
        probes.append(
            ("chatbot_get_bearer", "GET", f"{base_url}/chatbots/{chatbot_id}/", "bearer")
        )

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        for name, method, url, scheme in probes:
            try:
                resp = await client.request(
                    method, url, headers=_auth_headers(api_key, scheme=scheme)
                )
                body = (resp.text or "")[:180].replace("\n", " ")
                out["probes"].append(
                    {
                        "name": name,
                        "scheme": scheme,
                        "status": resp.status_code,
                        "www_authenticate": resp.headers.get("www-authenticate"),
                        "body": body,
                    }
                )
            except OSError as e:
                out["probes"].append({"name": name, "error": str(e)})

    # Success heuristic
    ok_any = any(int(p.get("status") or 0) in {200, 201} for p in out["probes"] if "status" in p)
    out["ok"] = ok_any
    if not ok_any:
        out["hint"] = (
            "Profile API Key 入口正確，但此內容線上無效。"
            "請到「組織 → API Keys」新建一把（建立當下才看得到完整 key），"
            "確認複製的是 prefix.secret 全字串、無空白；"
            "Gateway 用 Bearer，Chatbot 官方範例用 Api-Key。"
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok_any else 1


async def main() -> int:
    p = argparse.ArgumentParser(description="MaiAgent side-path trial (no production notify)")
    p.add_argument("--ticket", type=int, default=None)
    p.add_argument("--case-id", default="")
    p.add_argument("--from-export", type=Path, default=None, help="Use stellar-case-export JSON")
    p.add_argument(
        "--context",
        choices=("soc", "full", "causal"),
        default="",
        help="soc=通知精簡；causal=全量 alerts 壓縮（因果用，預設）；full=原始 export（易截斷）",
    )
    p.add_argument(
        "--agentic",
        action="store_true",
        help="交給 bot 已上傳的 Skill 主導分析：不注入 Groq system prompt；建議搭配完整 export",
    )
    p.add_argument(
        "--depth",
        choices=("brief", "causal"),
        default="causal",
        help="agentic 輸出深度：brief=摘要向；causal=強制 timeline+因果鏈（預設）",
    )
    p.add_argument(
        "--conversation-id",
        default="",
        help="接續同一 MaiAgent 對話（可用上一輪 conversation_id 做因果 follow-up）",
    )
    p.add_argument(
        "--follow-up",
        action="store_true",
        help="在既有 conversation 上要求補強因果／timeline（建議搭配 --conversation-id）",
    )
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--api-key", default="", help="Override MAIAGENT_API_KEY")
    p.add_argument("--chatbot-id", default="", help="Override MAIAGENT_CHATBOT_ID (chatbot mode)")
    p.add_argument("--base-url", default="", help="Override MAIAGENT_BASE_URL")
    p.add_argument(
        "--mode",
        choices=("chatbot", "openai"),
        default="",
        help="chatbot=助手 completions；openai=AI Gateway /chat/completions（Bearer）。預設看 MAIAGENT_MODE 或 chatbot",
    )
    p.add_argument(
        "--model",
        default="",
        help="openai mode model id（預設 MAIAGENT_MODEL 或 gpt-4o-mini）",
    )
    p.add_argument("--timeout", type=float, default=0.0)
    p.add_argument(
        "--compare-groq",
        action="store_true",
        help="Also call production Groq path for side-by-side (still no email/LINE)",
    )
    p.add_argument(
        "--auth-check",
        action="store_true",
        help="只驗 API Key（打 /models 或 /chatbots/{id}/），不送 case",
    )
    p.add_argument("--dry-run", action="store_true", help="Build prompt only; do not call MaiAgent")
    args = p.parse_args()
    _load_maiagent_dotenv()

    if args.auth_check:
        return await _auth_check(args)

    # Default context: agentic causal → compact all-alerts pack (raw full often truncates)
    if args.context:
        context_mode = args.context.strip().lower()
    elif args.agentic:
        context_mode = "causal"
    else:
        context_mode = "soc"

    export_meta: dict[str, Any] = {}
    if args.from_export:
        case, bundle, export_meta = _load_from_export(args.from_export)
    else:
        get_stellar_settings.cache_clear()
        st = get_stellar_settings()
        async with StellarClient(
            base_url=str(st.stellar_base_url).rstrip("/"),
            api_key=st.stellar_api_key or "",
            timeout_seconds=st.stellar_timeout_seconds,
            verify_tls=st.stellar_tls_verify,
            tenant_id=st.stellar_tenant_id,
            http_max_retries=st.stellar_http_max_retries,
        ) as client:
            cid = await _resolve_case_id(client, case_id=args.case_id, ticket_id=args.ticket)
            if not cid:
                print(
                    json.dumps(
                        {"ok": False, "error": "resolve_case_id_failed"},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1
            bundle = await client.fetch_case_bundle(cid)
            case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}

    meta = export_meta.get("meta") if isinstance(export_meta.get("meta"), dict) else {}
    if context_mode == "full":
        if export_meta:
            case_json_text = json.dumps(export_meta, ensure_ascii=False, indent=2)
        else:
            case_json_text = json.dumps(
                {
                    "case": case,
                    "alerts": bundle.get("alerts"),
                    "observables": bundle.get("observables"),
                },
                ensure_ascii=False,
                indent=2,
            )
    elif context_mode == "causal":
        case_json_text = stellar_causal_ai_context_json(
            case=case,
            bundle=bundle,
            middleware_case_id=str(case.get("ticket_id") or case.get("_id") or ""),
            customer_code=str(meta.get("customer_code") or ""),
            decision=meta.get("decision_preview") if isinstance(meta.get("decision_preview"), dict) else None,
            meta=meta or None,
        )
    else:
        case_json_text = stellar_soc_ai_context_json(
            case=case,
            bundle=bundle,
            middleware_case_id=str(case.get("ticket_id") or case.get("_id") or ""),
            customer_code="",
            decision=None,
        )

    message = _build_message(
        context_mode=context_mode,
        case_json_text=case_json_text,
        agentic=bool(args.agentic),
        depth=str(args.depth or "causal"),
        follow_up=bool(args.follow_up),
    )
    api_key = (args.api_key or _env("MAIAGENT_API_KEY")).strip()
    chatbot_id = (args.chatbot_id or _env("MAIAGENT_CHATBOT_ID")).strip()
    base_url = (args.base_url or _env("MAIAGENT_BASE_URL", "https://api.sungcheng.org/api")).strip()
    timeout = float(args.timeout or _env("MAIAGENT_TIMEOUT_SECONDS", "180") or 180)
    mode = (args.mode or _env("MAIAGENT_MODE", "chatbot")).strip().lower() or "chatbot"
    model = (args.model or _env("MAIAGENT_MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini"
    conversation_id = (args.conversation_id or "").strip() or None

    result: dict[str, Any] = {
        "ok": False,
        "provider": "maiagent",
        "mode": mode,
        "agentic": bool(args.agentic),
        "depth": args.depth,
        "follow_up": bool(args.follow_up),
        "context_mode": context_mode,
        "stellar_case_id": str(case.get("_id") or ""),
        "ticket_id": case.get("ticket_id"),
        "prompt_chars": len(message),
        "api_key_len": len(api_key),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "note": "side-path trial only; production still uses Groq via SOC_NOTIFY_AI_*",
    }

    if args.dry_run:
        result["ok"] = True
        result["dry_run"] = True
        result["message_preview"] = message[:2000]
        if args.compare_groq:
            result["groq"] = await _maybe_groq_compare(case=case, bundle=bundle)
    else:
        if not api_key:
            result["error"] = "set MAIAGENT_API_KEY (or --api-key)"
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        if mode == "chatbot" and not chatbot_id:
            result["error"] = "chatbot mode needs MAIAGENT_CHATBOT_ID (or --chatbot-id); or use --mode openai"
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        t0 = time.perf_counter()
        try:
            if mode == "openai":
                # openai gateway: agentic = user message only (bot/skill N/A); else System+User
                resp = await openai_chat_completion(
                    api_key=api_key,
                    system_prompt="" if args.agentic else (_SYSTEM_PROMPT if context_mode == "soc" else ""),
                    message=(
                        message
                        if args.agentic or context_mode == "full"
                        else (_USER_PROMPT_PREFIX + case_json_text)
                    ),
                    model=model,
                    base_url=base_url,
                    timeout_seconds=timeout,
                )
            else:
                resp = await chatbot_completion(
                    api_key=api_key,
                    chatbot_id=chatbot_id,
                    message=message,
                    base_url=base_url,
                    timeout_seconds=timeout,
                    conversation_id=conversation_id,
                    is_streaming=False,
                )
            elapsed = int((time.perf_counter() - t0) * 1000)
            content = resp.get("content") or ""
            parsed: dict[str, Any] | None = None
            sections: dict[str, Any] | None = None
            try:
                parsed = parse_json_object(content)
                sections = _normalize_sections(parsed) if isinstance(parsed, dict) else None
            except (ValueError, json.JSONDecodeError):
                parsed = None
                sections = None
            waiting = _looks_like_waiting_for_input(content)
            ok_result = bool(parsed) and not waiting
            result.update(
                {
                    "ok": ok_result,
                    "elapsed_ms": elapsed,
                    "chatbot_id": chatbot_id if mode == "chatbot" else None,
                    "model": resp.get("model") or (model if mode == "openai" else None),
                    "conversation_id": resp.get("conversation_id") or "",
                    "raw_content": content,
                    "parsed": parsed,
                    "sections": sections,
                }
            )
            if waiting:
                result["error"] = (
                    "model_asked_for_input_without_analysis — case JSON likely truncated; "
                    "retry with --context causal (default) or --follow-up"
                )
            elif not parsed:
                result["error"] = "response_not_json_object"
        except (MaiAgentAPIError, ValueError, OSError) as e:
            result["error"] = str(e)
            result["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            return 1
        if args.compare_groq:
            result["groq"] = await _maybe_groq_compare(case=case, bundle=bundle)

    out = args.out
    if out is None:
        tid = case.get("ticket_id") or case.get("_id") or "unknown"
        out = ROOT / "data" / "exports" / f"maiagent_{tid}.json"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary: dict[str, Any] = {
        "ok": result.get("ok"),
        "out": str(out),
        "bytes": out.stat().st_size,
        "stellar_case_id": result.get("stellar_case_id"),
        "ticket_id": result.get("ticket_id"),
        "agentic": bool(args.agentic),
        "depth": args.depth,
        "context_mode": context_mode,
        "prompt_chars": result.get("prompt_chars"),
        "elapsed_ms": result.get("elapsed_ms"),
        "has_sections": bool(result.get("sections")),
        "conversation_id": result.get("conversation_id"),
        "has_timeline": isinstance(result.get("parsed"), dict)
        and isinstance((result.get("parsed") or {}).get("timeline"), list),
        "has_causal_chains": isinstance(result.get("parsed"), dict)
        and isinstance((result.get("parsed") or {}).get("causal_chains"), list),
        "error": result.get("error"),
    }
    if result.get("sections"):
        summary["executive_summary"] = (result["sections"].get("executive_summary") or "")[:200]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
