"""LINE Messaging API webhook (receive events, record user/group IDs)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_notify_settings
from app.notify.line_bot import reply_line_text
from app.notify.line_webhook import (
    extract_line_reply_actions,
    extract_line_source_ids,
    format_line_id_reply_text,
    parse_line_webhook_events,
    record_line_source_ids,
    verify_line_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/line")
async def line_webhook(
    request: Request,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
) -> dict[str, Any]:
    """
    LINE Platform webhook endpoint.

    Set in LINE Developers Console → Messaging API → Webhook URL, e.g.
    ``https://your-host/v1/webhooks/line``, then click **Verify**.
  """
    body = await request.body()
    get_notify_settings.cache_clear()
    st = get_notify_settings()
    secret = (st.line_channel_secret or "").strip()

    if secret:
        if not x_line_signature or not verify_line_signature(
            body=body,
            signature=x_line_signature,
            channel_secret=secret,
        ):
            raise HTTPException(status_code=400, detail="Invalid LINE webhook signature")
    else:
        raise HTTPException(
            status_code=503,
            detail="LINE_CHANNEL_SECRET is not configured",
        )

    events = parse_line_webhook_events(body)
    sources = extract_line_source_ids(events)
    if sources:
        ids = ", ".join(item["id"] for item in sources)
        logger.info("LINE webhook sources: %s", ids)
        record_line_source_ids(sources)

    replied = 0
    if st.line_webhook_reply_id and st.line_configured:
        for action in extract_line_reply_actions(events):
            try:
                await reply_line_text(
                    st,
                    reply_token=action["reply_token"],
                    text=format_line_id_reply_text(
                        line_id=action["id"],
                        source_type=action["type"],
                    ),
                )
                replied += 1
            except Exception as e:
                logger.warning("LINE webhook reply failed id=%s: %s", action.get("id"), e)

    return {"ok": True, "events": len(events), "replied": replied}
