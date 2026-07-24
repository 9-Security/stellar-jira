#!/usr/bin/env python3
"""Verify LINE_NOTIFY_TO recipients (profile lookup + optional test push)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_notify_settings
from app.notify.line_bot import (
    get_line_user_profile,
    line_recipient_id_hint,
    parse_line_recipient_list,
    push_line_text,
)


def _is_line_user_id(recipient: str) -> bool:
    return str(recipient or "").startswith("U")


async def _run(*, send_test: bool) -> int:
    st = get_notify_settings()
    if not st.line_configured:
        print("Set LINE_CHANNEL_ACCESS_TOKEN in .env", file=sys.stderr)
        return 2

    recipients = parse_line_recipient_list(st.line_notify_to)
    if not recipients:
        raw = (st.line_notify_to or "").strip()
        hint = line_recipient_id_hint(raw) if raw else "LINE_NOTIFY_TO is empty"
        print(f"No valid recipients: {hint}", file=sys.stderr)
        return 2

    exit_code = 0
    for recipient in recipients:
        hint = line_recipient_id_hint(recipient)
        if hint:
            print(f"[INVALID] {recipient}: {hint}")
            exit_code = 1
            continue

        if _is_line_user_id(recipient):
            try:
                profile = await get_line_user_profile(recipient, st)
            except ValueError as e:
                err = str(e)
                print(f"[FAIL] {recipient}")
                print(f"  {err}")
                if "404" in err:
                    print("  → User is not a friend of this bot, or this is not your real userId.")
                    print("  → Copy events[0].source.userId from webhook.site (not destination).")
                exit_code = 1
                continue

            name = str(profile.get("displayName") or "").strip()
            print(f"[OK] {recipient}" + (f" ({name})" if name else ""))
        else:
            kind = "group" if recipient.startswith("C") else "room" if recipient.startswith("R") else "recipient"
            print(f"[OK] {recipient} ({kind}; profile API N/A — use --push to verify)")

        if send_test:
            try:
                await push_line_text(
                    st,
                    to_id=recipient,
                    text="stellar-jira LINE 推播測試成功。",
                )
                print("  test push: sent")
            except ValueError as e:
                print(f"  test push failed: {e}")
                exit_code = 1

    return exit_code


def main() -> None:
    p = argparse.ArgumentParser(description="Verify LINE_NOTIFY_TO recipient IDs")
    p.add_argument(
        "--push",
        action="store_true",
        help="Send a short test message after profile check",
    )
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(send_test=args.push)))


if __name__ == "__main__":
    main()
