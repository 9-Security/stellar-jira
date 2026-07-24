"""SQLite audit store for decision events and outcomes (Decision Dataset seed)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionStore:
    """Persist decision records alongside (or inside) the sync state DB."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS decision_events ("
                "event_id TEXT PRIMARY KEY, "
                "source_id TEXT NOT NULL, "
                "stellar_case_id TEXT NOT NULL, "
                "middleware_case_id TEXT, "
                "jira_key TEXT, "
                "customer_code TEXT, "
                "created_at TEXT NOT NULL, "
                "action TEXT NOT NULL, "
                "escalation TEXT, "
                "notify_customer INTEGER NOT NULL DEFAULT 0, "
                "notify_internal INTEGER NOT NULL DEFAULT 1, "
                "isolate_host INTEGER NOT NULL DEFAULT 0, "
                "playbook_id TEXT, "
                "confidence REAL, "
                "rule_hits_json TEXT, "
                "knowledge_hits_json TEXT, "
                "decision_json TEXT NOT NULL, "
                "context_json TEXT, "
                "ai_json TEXT, "
                "outcome_true_positive INTEGER, "
                "outcome_root_cause TEXT, "
                "outcome_notes TEXT, "
                "outcome_at TEXT, "
                "outcome_source TEXT"
                ")"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_case "
                "ON decision_events(source_id, stellar_case_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_jira "
                "ON decision_events(jira_key)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_created "
                "ON decision_events(created_at)"
            )
            cols = {row[1] for row in c.execute("PRAGMA table_info(decision_events)")}
            if "snapshot_id" not in cols:
                c.execute("ALTER TABLE decision_events ADD COLUMN snapshot_id TEXT")
            c.commit()

    def record_decision(
        self,
        *,
        source_id: str,
        stellar_case_id: str,
        middleware_case_id: str = "",
        jira_key: str = "",
        customer_code: str = "",
        decision: dict[str, Any],
        context: dict[str, Any] | None = None,
        ai_sections: dict[str, Any] | None = None,
        event_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> str:
        eid = (event_id or "").strip() or str(uuid.uuid4())
        ts = _utc_now()
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO decision_events ("
                "event_id, source_id, stellar_case_id, middleware_case_id, jira_key, "
                "customer_code, created_at, action, escalation, notify_customer, "
                "notify_internal, isolate_host, playbook_id, confidence, "
                "rule_hits_json, knowledge_hits_json, decision_json, context_json, ai_json, "
                "snapshot_id"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    str(source_id or "").strip(),
                    str(stellar_case_id or "").strip(),
                    str(middleware_case_id or "").strip() or None,
                    str(jira_key or "").strip() or None,
                    str(customer_code or "").strip() or None,
                    ts,
                    str(decision.get("action") or "create_ticket"),
                    str(decision.get("escalation") or "L1"),
                    1 if decision.get("notify_customer") else 0,
                    0 if decision.get("notify_internal") is False else 1,
                    1 if decision.get("isolate_host") else 0,
                    str(decision.get("playbook_id") or "") or None,
                    float(decision.get("confidence") or 0.0),
                    json.dumps(decision.get("rule_hits") or [], ensure_ascii=False),
                    json.dumps(decision.get("knowledge_hits") or [], ensure_ascii=False),
                    json.dumps(decision, ensure_ascii=False),
                    json.dumps(context or {}, ensure_ascii=False),
                    json.dumps(ai_sections, ensure_ascii=False) if ai_sections is not None else None,
                    str(snapshot_id or "").strip() or None,
                ),
            )
            c.commit()
        return eid

    def update_jira_key(self, event_id: str, jira_key: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE decision_events SET jira_key=? WHERE event_id=?",
                (str(jira_key or "").strip(), str(event_id or "").strip()),
            )
            c.commit()

    def update_ai_sections(self, event_id: str, ai_sections: dict[str, Any] | None) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE decision_events SET ai_json=? WHERE event_id=?",
                (
                    json.dumps(ai_sections, ensure_ascii=False) if ai_sections is not None else None,
                    str(event_id or "").strip(),
                ),
            )
            c.commit()

    def get_by_event_id(self, event_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM decision_events WHERE event_id=?",
                (str(event_id or "").strip(),),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_latest_by_case(self, source_id: str, stellar_case_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM decision_events WHERE source_id=? AND stellar_case_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (str(source_id or "").strip(), str(stellar_case_id or "").strip()),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_latest_by_jira_key(self, jira_key: str) -> dict[str, Any] | None:
        key = str(jira_key or "").strip()
        if not key:
            return None
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM decision_events WHERE jira_key=? "
                "ORDER BY created_at DESC LIMIT 1",
                (key,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def record_outcome(
        self,
        *,
        event_id: str | None = None,
        jira_key: str = "",
        source_id: str = "",
        stellar_case_id: str = "",
        true_positive: bool | None = None,
        root_cause: str = "",
        notes: str = "",
        source: str = "jira",
        preserve_labeled: bool = False,
    ) -> bool:
        """Attach outcome to the latest matching decision event. Returns True if updated."""
        row = None
        if event_id:
            row = self.get_by_event_id(event_id)
        if row is None and jira_key:
            row = self.get_latest_by_jira_key(jira_key)
        if row is None and source_id and stellar_case_id:
            row = self.get_latest_by_case(source_id, stellar_case_id)
        if row is None:
            return False
        existing_tp = row.get("outcome_true_positive")
        if preserve_labeled and existing_tp is not None and true_positive is None:
            # Keep prior TP/FP; still allow root_cause/notes refresh if provided
            if not str(root_cause or "").strip() and not str(notes or "").strip():
                return False
            true_positive = bool(existing_tp)
        tp_val: int | None
        if true_positive is None:
            tp_val = None
        else:
            tp_val = 1 if true_positive else 0
        merged_root = str(root_cause or "").strip() or row.get("outcome_root_cause")
        merged_notes = str(notes or "").strip() or row.get("outcome_notes")
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE decision_events SET "
                "outcome_true_positive=?, outcome_root_cause=?, outcome_notes=?, "
                "outcome_at=?, outcome_source=? WHERE event_id=?",
                (
                    tp_val,
                    str(merged_root).strip() if merged_root else None,
                    str(merged_notes).strip() if merged_notes else None,
                    _utc_now(),
                    str(source or "jira").strip() or "jira",
                    row["event_id"],
                ),
            )
            c.commit()
        return True

    def list_events(
        self,
        *,
        source_id: str | None = None,
        customer_code: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("source_id=?")
            params.append(source_id)
        if customer_code:
            clauses.append("customer_code=?")
            params.append(customer_code.strip().upper())
        if since:
            clauses.append("created_at>=?")
            params.append(since)
        if until:
            clauses.append("created_at<=?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM decision_events{where} "
            f"ORDER BY created_at DESC LIMIT ?"
        )
        params.append(max(1, min(int(limit), 10000)))
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_similar_contexts(
        self,
        *,
        source_id: str,
        customer_code: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent same-tenant events with context for similarity matching."""
        clauses = ["source_id=?"]
        params: list[Any] = [source_id]
        if customer_code:
            clauses.append("customer_code=?")
            params.append(customer_code.strip().upper())
        params.append(max(1, min(int(limit), 500)))
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT event_id, stellar_case_id, middleware_case_id, jira_key, "
                "customer_code, action, escalation, playbook_id, context_json, "
                "outcome_true_positive, outcome_root_cause "
                f"FROM decision_events WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            raw = d.get("context_json")
            try:
                d["context"] = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                d["context"] = {}
            out.append(d)
        return out

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        d = dict(row)
        for key, parsed_key in (
            ("rule_hits_json", "rule_hits"),
            ("knowledge_hits_json", "knowledge_hits"),
            ("decision_json", "decision"),
            ("context_json", "context"),
            ("ai_json", "ai_sections"),
        ):
            raw = d.get(key)
            if raw is None:
                d[parsed_key] = None if key == "ai_json" else ({} if "json" in key and "hits" not in key else [])
                continue
            try:
                d[parsed_key] = json.loads(raw)
            except json.JSONDecodeError:
                d[parsed_key] = None
        if d.get("outcome_true_positive") is not None:
            d["outcome_true_positive"] = bool(d["outcome_true_positive"])
        d["notify_customer"] = bool(d.get("notify_customer"))
        d["notify_internal"] = bool(d.get("notify_internal"))
        d["isolate_host"] = bool(d.get("isolate_host"))
        d["snapshot_id"] = d.get("snapshot_id")
        return d
