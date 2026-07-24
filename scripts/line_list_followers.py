#!/usr/bin/env python3
"""List LINE bot follower user IDs (for LINE_NOTIFY_TO)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import get_notify_settings
from app.notify.line_bot import get_line_user_profile, list_line_follower_ids

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RECIPIENTS_FILE = _REPO_ROOT / "data" / "line_recipients.json"


async def _run(*, with_profile: bool, from_webhook_file: bool) -> int:
    st = get_notify_settings()
    if not st.line_configured:
        print("Set LINE_CHANNEL_ACCESS_TOKEN in .env", file=sys.stderr)
        return 2

    rows: list[dict[str, str]] = []

    if from_webhook_file and _RECIPIENTS_FILE.is_file():
        try:
            raw = json.loads(_RECIPIENTS_FILE.read_text(encoding="utf-8"))
            for item in raw.get("recipients") or []:
                if isinstance(item, dict) and item.get("id"):
                    rows.append(
                        {
                            "user_id": str(item["id"]),
                            "type": str(item.get("type") or ""),
                            "source": "webhook",
                        }
                    )
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read {_RECIPIENTS_FILE}: {e}", file=sys.stderr)

    try:
        follower_ids = await list_line_follower_ids(st)
    except ValueError as e:
        err = str(e)
        if "403" in err and "not available for your account" in err:
            print(
                "LINE followers API 不可用（免費/輕量方案常見）。"
                "請改用 Webhook：讓使用者傳訊息給 Bot，Bot 會回覆 User ID。",
                file=sys.stderr,
            )
        else:
            print(f"LINE followers API failed: {e}", file=sys.stderr)
        follower_ids = []

    seen = {row["user_id"] for row in rows}
    for user_id in follower_ids:
        if user_id in seen:
            continue
        rows.append({"user_id": user_id, "type": "user", "source": "followers_api"})
        seen.add(user_id)

    if with_profile:
        for row in rows:
            if not row["user_id"].startswith("U"):
                continue
            try:
                profile = await get_line_user_profile(row["user_id"], st)
            except ValueError:
                row["display_name"] = ""
            else:
                row["display_name"] = str(profile.get("displayName") or "")

    if not rows:
        print("No user IDs found.", file=sys.stderr)
        print("免費方案請用 Webhook 查 ID：", file=sys.stderr)
        print("  1) ./serve_api + HTTPS（或 ngrok http 8000）", file=sys.stderr)
        print("  2) LINE Console 設 Webhook URL → .../v1/webhooks/line，開啟 Use webhook", file=sys.stderr)
        print("  3) 用手機加 Bot 好友，傳任意訊息 → Bot 會回覆您的 User ID", file=sys.stderr)
        print("  4) 或查看 data/line_recipients.json", file=sys.stderr)
        return 1

    print("Copy user_id into LINE_NOTIFY_TO in .env:\n")
    for row in rows:
        parts = [row["user_id"]]
        if row.get("display_name"):
            parts.append(f"({row['display_name']})")
        if row.get("type"):
            parts.append(f"[{row['type']}]")
        if row.get("source"):
            parts.append(f"<{row['source']}>")
        print("  " + " ".join(parts))

    user_ids = [row["user_id"] for row in rows if row["user_id"].startswith("U")]
    if user_ids:
        print(f"\nLINE_NOTIFY_TO={','.join(user_ids)}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="List LINE user/group IDs for LINE_NOTIFY_TO")
    p.add_argument(
        "--profile",
        action="store_true",
        help="Fetch display name for each user ID (extra API calls)",
    )
    p.add_argument(
        "--include-webhook",
        action="store_true",
        default=True,
        help="Include IDs recorded in data/line_recipients.json (default: on)",
    )
    p.add_argument(
        "--no-webhook",
        action="store_true",
        help="Do not read data/line_recipients.json",
    )
    args = p.parse_args()
    raise SystemExit(
        asyncio.run(
            _run(
                with_profile=args.profile,
                from_webhook_file=args.include_webhook and not args.no_webhook,
            )
        )
    )


if __name__ == "__main__":
    main()
