"""Outcome feedback loop — map Jira resolution / tags to decision_events."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.decision.store import DecisionStore
from app.jira.adf import adf_to_plain_text
from app.stellar.resolution_tag import jira_resolution_label_from_fields, load_resolution_tag_map

logger = logging.getLogger(__name__)

_FP_RE = re.compile(
    r"\b(?:false\s*positive|fp|誤報|非資安|benign|expected\s*behavior)\b",
    re.I,
)
_TP_RE = re.compile(
    r"\b(?:true\s*positive|tp|真實攻擊|confirmed\s*malicious|確診)\b",
    re.I,
)
_ROOT_CAUSE_RE = re.compile(
    r"(?:root\s*cause|根本原因|rca)\s*[:：]\s*(.+)",
    re.I,
)

# Jira resolution-tag option labels → TP/FP (config/stellar_resolution_tag_map.json)
_TAG_FP = frozenset({"false positive", "benign", "fp", "誤報"})
_TAG_TP = frozenset({"true positive", "tp", "真實攻擊"})


def infer_outcome_from_text(text: str) -> dict[str, Any]:
    """Heuristic TP/FP + root cause extraction from free text."""
    s = str(text or "")
    true_positive: bool | None = None
    if _FP_RE.search(s):
        true_positive = False
    elif _TP_RE.search(s):
        true_positive = True
    root_cause = ""
    m = _ROOT_CAUSE_RE.search(s)
    if m:
        root_cause = m.group(1).strip()[:500]
    return {"true_positive": true_positive, "root_cause": root_cause, "raw_len": len(s)}


def infer_outcome_from_resolution_tag(
    fields: dict[str, Any],
    *,
    tag_map_path: Path | str | None = None,
) -> dict[str, Any]:
    """Map Jira resolution-tag custom field (e.g. False Positive) to TP/FP."""
    path = Path(tag_map_path) if tag_map_path else None
    tag_map = load_resolution_tag_map(path)
    label = jira_resolution_label_from_fields(fields, tag_map)
    if not label:
        return {"true_positive": None, "root_cause": "", "resolution_tag": ""}
    low = label.strip().lower()
    tp: bool | None = None
    if low in _TAG_FP or "false positive" in low or low == "benign":
        tp = False
    elif low in _TAG_TP or "true positive" in low:
        tp = True
    root = ""
    if tp is False:
        root = f"jira_resolution_tag={label}"
    elif tp is True:
        root = f"jira_resolution_tag={label}"
    return {"true_positive": tp, "root_cause": root, "resolution_tag": label}


def infer_outcome_from_jira_fields(
    fields: dict[str, Any],
    *,
    tag_map_path: Path | str | None = None,
) -> dict[str, Any]:
    """Combine resolution tag, resolution, status, description signals."""
    from_tag = infer_outcome_from_resolution_tag(fields, tag_map_path=tag_map_path)

    chunks: list[str] = []
    for key in ("resolution", "status"):
        raw = fields.get(key)
        if isinstance(raw, dict):
            chunks.append(str(raw.get("name") or raw.get("value") or ""))
        elif raw is not None:
            chunks.append(str(raw))
    if from_tag.get("resolution_tag"):
        chunks.append(str(from_tag["resolution_tag"]))
    desc = fields.get("description")
    if isinstance(desc, dict):
        chunks.append(adf_to_plain_text(desc))
    elif isinstance(desc, str):
        chunks.append(desc)
    blob = "\n".join(c for c in chunks if c)
    from_text = infer_outcome_from_text(blob)

    true_positive = from_tag.get("true_positive")
    if true_positive is None:
        true_positive = from_text.get("true_positive")
    root_cause = str(from_text.get("root_cause") or "").strip()
    if not root_cause and from_tag.get("root_cause"):
        root_cause = str(from_tag["root_cause"])

    return {
        "true_positive": true_positive,
        "root_cause": root_cause,
        "resolution_tag": from_tag.get("resolution_tag") or "",
        "raw_len": from_text.get("raw_len") or 0,
    }


def apply_outcome_from_jira(
    store: DecisionStore,
    *,
    jira_key: str,
    fields: dict[str, Any],
    source_id: str = "",
    stellar_case_id: str = "",
    comments_text: str = "",
    tag_map_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Write outcome onto the latest decision_events row for this Jira issue.

    Prefers Jira resolution-tag (False Positive / True Positive / Benign).
    Does not wipe an existing labeled TP/FP with an unknown inference.
    """
    if tag_map_path is None:
        try:
            from app.config import get_stellar_settings

            tag_map_path = get_stellar_settings().stellar_resolution_tag_map_path
        except Exception:
            tag_map_path = None

    inferred = infer_outcome_from_jira_fields(fields, tag_map_path=tag_map_path)
    if comments_text:
        from_comments = infer_outcome_from_text(comments_text)
        if inferred.get("true_positive") is None and from_comments.get("true_positive") is not None:
            inferred["true_positive"] = from_comments["true_positive"]
        if not inferred.get("root_cause") and from_comments.get("root_cause"):
            inferred["root_cause"] = from_comments["root_cause"]

    # Fall back: cancelled / won't do often implies FP in SOC practice when no TP marker
    status_name = ""
    st = fields.get("status")
    if isinstance(st, dict):
        status_name = str(st.get("name") or "").strip().lower()
    if inferred.get("true_positive") is None and status_name in ("cancelled", "canceled", "done", "resolved"):
        res = fields.get("resolution")
        res_name = ""
        if isinstance(res, dict):
            res_name = str(res.get("name") or "").lower()
        if any(x in res_name for x in ("won't", "duplicate", "cannot", "false")):
            inferred["true_positive"] = False

    notes_parts = []
    if status_name:
        notes_parts.append(f"status={status_name}")
    if inferred.get("resolution_tag"):
        notes_parts.append(f"tag={inferred['resolution_tag']}")

    ok = store.record_outcome(
        jira_key=jira_key,
        source_id=source_id,
        stellar_case_id=stellar_case_id,
        true_positive=inferred.get("true_positive"),
        root_cause=str(inferred.get("root_cause") or ""),
        notes="; ".join(notes_parts),
        source="jira",
        preserve_labeled=True,
    )
    return {
        "ok": ok,
        "jira_key": jira_key,
        "true_positive": inferred.get("true_positive"),
        "root_cause": inferred.get("root_cause") or "",
        "resolution_tag": inferred.get("resolution_tag") or "",
        "updated": ok,
    }
