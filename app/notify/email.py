"""SMTP email delivery (stdlib only)."""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Sequence

from app.config import NotifySettings, get_notify_settings

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_email_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,;\s]+", raw.strip())
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        addr = p.strip()
        if not addr:
            continue
        low = addr.lower()
        if low in seen:
            continue
        if not _EMAIL_RE.match(addr):
            logger.warning("skipping invalid email address: %r", addr)
            continue
        seen.add(low)
        out.append(addr)
    return out


def _merge_recipients(*lists: Sequence[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        if not lst:
            continue
        for addr in lst:
            low = addr.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(addr)
    return out


def _send_email_sync(
    settings: NotifySettings,
    *,
    to_addrs: list[str],
    subject: str,
    body_text: str,
    cc_addrs: list[str] | None = None,
    bcc_addrs: list[str] | None = None,
) -> None:
    if not settings.smtp_host and not settings.resend_api_key:
        raise ValueError("SMTP_HOST is not set")
    host = (settings.smtp_host or "").strip() or "smtp.resend.com"
    if not settings.soc_notify_from:
        raise ValueError("SOC_NOTIFY_FROM is not set")
    if not to_addrs:
        raise ValueError("no recipients")

    msg = EmailMessage()
    msg["From"] = settings.soc_notify_from
    msg["To"] = ", ".join(to_addrs)
    cc = cc_addrs or []
    if cc:
        msg["Cc"] = ", ".join(cc)
    bcc = bcc_addrs or []
    msg["Subject"] = subject
    msg.set_content(body_text, charset="utf-8")

    all_rcpt = _merge_recipients(to_addrs, cc, bcc)
    port = int(settings.smtp_port)
    timeout = float(settings.smtp_timeout_seconds)
    user = (settings.smtp_user or "").strip() or ("resend" if settings.resend_api_key else None)
    password = (settings.smtp_password or settings.resend_api_key or "").strip() or None

    if settings.smtp_use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg, to_addrs=all_rcpt)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls(context=ssl.create_default_context())
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg, to_addrs=all_rcpt)


async def send_email(
    *,
    to_addrs: list[str],
    subject: str,
    body_text: str,
    cc_addrs: list[str] | None = None,
    bcc_addrs: list[str] | None = None,
    settings: NotifySettings | None = None,
) -> str:
    """Send email via Resend API or SMTP. Returns provider label: ``resend`` or ``smtp``."""
    st = settings or get_notify_settings()
    if st.use_resend_api:
        from app.notify.resend_api import send_email_resend

        await send_email_resend(
            st,
            to_addrs=to_addrs,
            subject=subject,
            body_text=body_text,
            cc_addrs=cc_addrs,
            bcc_addrs=bcc_addrs,
        )
        return "resend"

    await asyncio.to_thread(
        _send_email_sync,
        st,
        to_addrs=to_addrs,
        subject=subject,
        body_text=body_text,
        cc_addrs=cc_addrs,
        bcc_addrs=bcc_addrs,
    )
    return "smtp"
