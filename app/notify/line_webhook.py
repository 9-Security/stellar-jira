"""LINE Platform webhook signature verification and event helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def verify_line_signature(*, body: bytes, signature: str, channel_secret: str) -> bool:
    secret = str(channel_secret or "").strip()
    sig = str(signature or "").strip()
    if not secret or not sig:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, sig)


def parse_line_webhook_events(body: bytes) -> list[dict[str, Any]]:
    if not body:
        return []
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def extract_line_reply_actions(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Events that can receive an ID reply (one replyToken per event)."""
    out: list[dict[str, str]] = []
    for event in events:
        reply_token = str(event.get("replyToken") or "").strip()
        if not reply_token:
            continue
        source = event.get("source")
        if not isinstance(source, dict):
            continue
        source_type = str(source.get("type") or "").strip()
        id_keys = (
            [("groupId", "group"), ("userId", "user"), ("roomId", "room")]
            if source_type == "group"
            else [("userId", "user"), ("groupId", "group"), ("roomId", "room")]
        )
        for key, label in id_keys:
            value = str(source.get(key) or "").strip()
            if not value:
                continue
            out.append(
                {
                    "reply_token": reply_token,
                    "id": value,
                    "type": source_type or label,
                }
            )
            break
    return out


def format_line_id_reply_text(*, line_id: str, source_type: str) -> str:
    kind = {"user": "User ID", "group": "Group ID", "room": "Room ID"}.get(source_type, "ID")
    return (
        f"您的 LINE {kind}：\n{line_id}\n\n"
        "請將此值填入伺服器 .env 的 LINE_NOTIFY_TO。\n"
        "（此 ID 已記錄，SOC 建票通知會推播到此帳號/群組。）"
    )


def extract_line_source_ids(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for event in events:
        source = event.get("source")
        if not isinstance(source, dict):
            continue
        source_type = str(source.get("type") or "").strip()
        for key in ("userId", "groupId", "roomId"):
            value = str(source.get(key) or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append({"id": value, "type": source_type or key.replace("Id", "")})
    return out


def record_line_source_ids(
    sources: list[dict[str, str]],
    *,
    store_path: Path | None = None,
) -> None:
    if not sources:
        return
    path = store_path or (_REPO_ROOT / "data" / "line_recipients.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict[str, str]] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for item in raw.get("recipients") or []:
                    if isinstance(item, dict) and item.get("id"):
                        existing[str(item["id"])] = {
                            "id": str(item["id"]),
                            "type": str(item.get("type") or ""),
                            "last_seen": str(item.get("last_seen") or ""),
                        }
        except (OSError, json.JSONDecodeError):
            logger.warning("could not read LINE recipients store: %s", path)

    now = datetime.now(timezone.utc).isoformat()
    for source in sources:
        rid = source["id"]
        existing[rid] = {
            "id": rid,
            "type": source.get("type") or "",
            "last_seen": now,
        }

    payload = {
        "recipients": sorted(existing.values(), key=lambda item: item["id"]),
        "hint": "Copy id values into LINE_NOTIFY_TO in .env",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("LINE webhook recorded %s recipient(s) to %s", len(sources), path)
