"""Outbound notifications (SOC email + LINE push on new Jira tickets)."""

from app.notify.ticket_created import notify_ticket_created

__all__ = ["notify_ticket_created"]
