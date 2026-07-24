"""Atlassian Document Format (Jira Cloud description)."""

from __future__ import annotations

from typing import Any


def plain_text_to_adf(text: str) -> dict:
    lines = (text or "").strip().split("\n") or [""]
    content: list[dict] = []
    for line in lines:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line if line else " "}],
            }
        )
    return {"type": "doc", "version": 1, "content": content}


def adf_to_plain_text(node: Any) -> str:
    """Best-effort plain text from Jira ADF (description)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return str(node.get("text") or "")
    parts: list[str] = []
    for child in node.get("content") or []:
        parts.append(adf_to_plain_text(child))
    if t in ("paragraph", "heading", "listItem", "blockquote"):
        return "".join(parts) + "\n"
    return "".join(parts)
