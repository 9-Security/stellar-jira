"""SQLite state: which Cortex incidents already have a Jira issue (per XDR source_id)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# Row exists but Jira create may not have finished (crash between API call and record).
PENDING_JIRA_KEY = "__pending__"

ClaimStatus = Literal["synced", "claimed", "pending"]


class SyncState:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self, *, legacy_source_id: str = "default") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            cur = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='incident_jira'")
            if cur.fetchone() is None:
                c.execute(
                    "CREATE TABLE incident_jira ("
                    "source_id TEXT NOT NULL, incident_id TEXT NOT NULL, "
                    "jira_key TEXT NOT NULL, synced_at TEXT NOT NULL, "
                    "PRIMARY KEY (source_id, incident_id))"
                )
            cols = {row[1] for row in c.execute("PRAGMA table_info(incident_jira)")}
            if "source_id" not in cols:
                c.execute("ALTER TABLE incident_jira RENAME TO incident_jira_legacy_mig")
                c.execute(
                    "CREATE TABLE incident_jira ("
                    "source_id TEXT NOT NULL, incident_id TEXT NOT NULL, "
                    "jira_key TEXT NOT NULL, synced_at TEXT NOT NULL, "
                    "PRIMARY KEY (source_id, incident_id))"
                )
                c.execute(
                    "INSERT INTO incident_jira (source_id, incident_id, jira_key, synced_at) "
                    "SELECT ?, incident_id, jira_key, synced_at FROM incident_jira_legacy_mig",
                    (legacy_source_id,),
                )
                c.execute("DROP TABLE incident_jira_legacy_mig")
                row = c.execute("SELECT v FROM meta WHERE k='last_max_mod_ms'").fetchone()
                if row and row[0] is not None:
                    c.execute(
                        "INSERT OR REPLACE INTO meta (k,v) VALUES (?,?)",
                        (f"last_max_mod_ms:{legacy_source_id}", str(row[0])),
                    )
                    c.execute("DELETE FROM meta WHERE k='last_max_mod_ms'")
                cols = {row[1] for row in c.execute("PRAGMA table_info(incident_jira)")}
            for name in ("tenant_source_id", "tenant_id", "tenant_name", "customer_code"):
                if name not in cols:
                    c.execute(f"ALTER TABLE incident_jira ADD COLUMN {name} TEXT")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_incident_tenant "
                "ON incident_jira(tenant_source_id, synced_at)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS tenant_case_quarantine ("
                "source_id TEXT NOT NULL, incident_id TEXT NOT NULL, "
                "tenant_id TEXT, tenant_name TEXT, modified_at_ms INTEGER NOT NULL DEFAULT 0, "
                "reason TEXT NOT NULL, case_json TEXT NOT NULL, "
                "first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, "
                "PRIMARY KEY(source_id, incident_id))"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_quarantine_tenant "
                "ON tenant_case_quarantine(tenant_id, tenant_name)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS maiagent_case_delivery ("
                "source_id TEXT NOT NULL, incident_id TEXT NOT NULL, "
                "status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
                "claimed_at_ms INTEGER NOT NULL DEFAULT 0, completed_at TEXT, "
                "last_error TEXT, "
                "PRIMARY KEY(source_id, incident_id))"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_maiagent_delivery_status "
                "ON maiagent_case_delivery(status, claimed_at_ms)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS stellar_ai_summary_delivery ("
                "source_id TEXT NOT NULL, incident_id TEXT NOT NULL, jira_key TEXT, "
                "status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, "
                "last_attempt_at_ms INTEGER NOT NULL DEFAULT 0, completed_at TEXT, "
                "payload_json TEXT, last_error TEXT, "
                "PRIMARY KEY(source_id, incident_id))"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_stellar_ai_summary_delivery_status "
                "ON stellar_ai_summary_delivery(status, last_attempt_at_ms)"
            )
            c.commit()

    def has_incident(self, source_id: str, incident_id: str) -> bool:
        """True if incident is fully synced (not ``PENDING_JIRA_KEY``)."""
        key = self.get_jira_key(source_id, incident_id)
        return key is not None and key != PENDING_JIRA_KEY

    def get_jira_key(self, source_id: str, incident_id: str) -> str | None:
        with sqlite3.connect(self.path) as c:
            r = c.execute(
                "SELECT jira_key FROM incident_jira WHERE source_id=? AND incident_id=?",
                (source_id, incident_id),
            ).fetchone()
            return str(r[0]) if r and r[0] is not None else None

    def lookup_incident_by_jira_key(self, jira_key: str, *, source_id: str) -> str | None:
        """Return Stellar/Cortex incident_id for a synced Jira key, or None."""
        key = str(jira_key or "").strip()
        if not key or key == PENDING_JIRA_KEY:
            return None
        with sqlite3.connect(self.path) as c:
            r = c.execute(
                "SELECT incident_id FROM incident_jira "
                "WHERE source_id=? AND jira_key=? AND jira_key!=?",
                (source_id, key, PENDING_JIRA_KEY),
            ).fetchone()
            return str(r[0]) if r and r[0] is not None else None

    def try_claim(self, source_id: str, incident_id: str) -> ClaimStatus:
        """Reserve an incident for create: ``claimed`` (new), ``synced``, or ``pending`` (in-flight)."""
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT jira_key FROM incident_jira WHERE source_id=? AND incident_id=?",
                (source_id, incident_id),
            ).fetchone()
            if row and row[0] is not None:
                key = str(row[0])
                if key != PENDING_JIRA_KEY:
                    c.commit()
                    return "synced"
                c.commit()
                return "pending"
            c.execute(
                "INSERT INTO incident_jira (source_id, incident_id, jira_key, synced_at) "
                "VALUES (?,?,?,?)",
                (source_id, incident_id, PENDING_JIRA_KEY, ts),
            )
            c.commit()
            return "claimed"

    def release_claim(self, source_id: str, incident_id: str) -> None:
        """Drop a pending row so a failed create can be retried."""
        with sqlite3.connect(self.path) as c:
            c.execute(
                "DELETE FROM incident_jira WHERE source_id=? AND incident_id=? AND jira_key=?",
                (source_id, incident_id, PENDING_JIRA_KEY),
            )
            c.commit()

    def record(
        self,
        source_id: str,
        incident_id: str,
        jira_key: str,
        *,
        tenant_source_id: str = "",
        tenant_id: str = "",
        tenant_name: str = "",
        customer_code: str = "",
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT OR REPLACE INTO incident_jira ("
                "source_id, incident_id, jira_key, synced_at, tenant_source_id, "
                "tenant_id, tenant_name, customer_code"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    incident_id,
                    jira_key,
                    ts,
                    str(tenant_source_id or "").strip() or None,
                    str(tenant_id or "").strip() or None,
                    str(tenant_name or "").strip() or None,
                    str(customer_code or "").strip().upper() or None,
                ),
            )
            c.commit()

    def quarantine_case(
        self,
        source_id: str,
        case: dict,
        *,
        reason: str,
    ) -> None:
        incident_id = str(case.get("_id") or "").strip()
        if not incident_id:
            return
        ts = datetime.now(timezone.utc).isoformat()
        tenant_id = str(case.get("cust_id") or "").strip() or None
        tenant_name = str(case.get("tenant_name") or "").strip() or None
        modified_at_ms = int(case.get("modified_at") or 0)
        payload = json.dumps(case, ensure_ascii=False, default=str)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO tenant_case_quarantine ("
                "source_id, incident_id, tenant_id, tenant_name, modified_at_ms, reason, "
                "case_json, first_seen_at, last_seen_at"
                ") VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(source_id, incident_id) DO UPDATE SET "
                "tenant_id=excluded.tenant_id, tenant_name=excluded.tenant_name, "
                "modified_at_ms=excluded.modified_at_ms, reason=excluded.reason, "
                "case_json=excluded.case_json, last_seen_at=excluded.last_seen_at",
                (
                    source_id,
                    incident_id,
                    tenant_id,
                    tenant_name,
                    modified_at_ms,
                    str(reason or "unknown_tenant"),
                    payload,
                    ts,
                    ts,
                ),
            )
            c.commit()

    def list_quarantined_cases(self, source_id: str) -> list[dict]:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM tenant_case_quarantine WHERE source_id=? "
                "ORDER BY modified_at_ms ASC",
                (source_id,),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            item = dict(row)
            try:
                item["case"] = json.loads(str(item.pop("case_json") or "{}"))
            except json.JSONDecodeError:
                item["case"] = {}
            out.append(item)
        return out

    def remove_quarantined_case(self, source_id: str, incident_id: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "DELETE FROM tenant_case_quarantine WHERE source_id=? AND incident_id=?",
                (source_id, str(incident_id or "").strip()),
            )
            c.commit()

    def tenant_link_counts(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as c:
            rows = c.execute(
                "SELECT COALESCE(NULLIF(tenant_source_id,''),'(legacy)'), COUNT(*) "
                "FROM incident_jira WHERE jira_key!=? GROUP BY 1 ORDER BY 1",
                (PENDING_JIRA_KEY,),
            ).fetchall()
        return {str(key): int(count) for key, count in rows}

    def update_incident_tenant(
        self,
        source_id: str,
        incident_id: str,
        *,
        tenant_source_id: str,
        tenant_id: str,
        tenant_name: str,
        customer_code: str,
    ) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE incident_jira SET tenant_source_id=?, tenant_id=?, "
                "tenant_name=?, customer_code=? WHERE source_id=? AND incident_id=?",
                (
                    str(tenant_source_id or "").strip() or None,
                    str(tenant_id or "").strip() or None,
                    str(tenant_name or "").strip() or None,
                    str(customer_code or "").strip().upper() or None,
                    source_id,
                    str(incident_id or "").strip(),
                ),
            )
            c.commit()

    @staticmethod
    def maiagent_all_cases_initialized_key(source_id: str) -> str:
        return f"maiagent_all_cases_initialized:{source_id}"

    def mark_maiagent_case_baseline(self, source_id: str, incident_id: str) -> None:
        cid = str(incident_id or "").strip()
        if not cid:
            return
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT OR IGNORE INTO maiagent_case_delivery "
                "(source_id, incident_id, status) VALUES (?,?,?)",
                (source_id, cid, "baseline"),
            )
            c.commit()

    def try_claim_maiagent_case(
        self,
        source_id: str,
        incident_id: str,
        *,
        retry_after_seconds: int,
    ) -> str:
        """Return claimed, done, pending, or retry_wait for one-case delivery."""
        cid = str(incident_id or "").strip()
        if not cid:
            return "done"
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        retry_ms = max(60, int(retry_after_seconds)) * 1000
        with sqlite3.connect(self.path) as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT status, claimed_at_ms FROM maiagent_case_delivery "
                "WHERE source_id=? AND incident_id=?",
                (source_id, cid),
            ).fetchone()
            if row:
                status = str(row[0] or "")
                claimed_at_ms = int(row[1] or 0)
                if status in ("baseline", "delivered"):
                    c.commit()
                    return "done"
                if now_ms - claimed_at_ms < retry_ms:
                    c.commit()
                    return "pending" if status == "pending" else "retry_wait"
                c.execute(
                    "UPDATE maiagent_case_delivery SET status='pending', "
                    "attempts=attempts+1, claimed_at_ms=?, last_error=NULL "
                    "WHERE source_id=? AND incident_id=?",
                    (now_ms, source_id, cid),
                )
            else:
                c.execute(
                    "INSERT INTO maiagent_case_delivery "
                    "(source_id, incident_id, status, attempts, claimed_at_ms) "
                    "VALUES (?,?,?,?,?)",
                    (source_id, cid, "pending", 1, now_ms),
                )
            c.commit()
            return "claimed"

    def finish_maiagent_case(
        self,
        source_id: str,
        incident_id: str,
        *,
        delivered: bool,
        error: str = "",
    ) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE maiagent_case_delivery SET status=?, completed_at=?, "
                "last_error=? WHERE source_id=? AND incident_id=?",
                (
                    "delivered" if delivered else "failed",
                    datetime.now(timezone.utc).isoformat(),
                    str(error or "").strip() or None,
                    source_id,
                    str(incident_id or "").strip(),
                ),
            )
            c.commit()

    def maiagent_delivery_counts(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as c:
            rows = c.execute(
                "SELECT status, COUNT(*) FROM maiagent_case_delivery "
                "GROUP BY status ORDER BY status"
            ).fetchall()
        return {str(status): int(count) for status, count in rows}

    def get_maiagent_case_status(self, source_id: str, incident_id: str) -> str | None:
        with sqlite3.connect(self.path) as c:
            row = c.execute(
                "SELECT status FROM maiagent_case_delivery "
                "WHERE source_id=? AND incident_id=?",
                (source_id, str(incident_id or "").strip()),
            ).fetchone()
        return str(row[0]) if row else None

    def list_retryable_maiagent_cases(
        self,
        source_id: str,
        *,
        retry_after_seconds: int,
    ) -> list[str]:
        cutoff_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - (
            max(60, int(retry_after_seconds)) * 1000
        )
        with sqlite3.connect(self.path) as c:
            rows = c.execute(
                "SELECT incident_id FROM maiagent_case_delivery "
                "WHERE source_id=? AND status IN ('pending','failed') "
                "AND claimed_at_ms<=? ORDER BY claimed_at_ms ASC",
                (source_id, cutoff_ms),
            ).fetchall()
        return [str(row[0]) for row in rows if str(row[0] or "").strip()]

    def try_claim_stellar_ai_summary(
        self,
        source_id: str,
        incident_id: str,
        *,
        jira_key: str,
        retry_after_seconds: int,
        max_attempts: int,
    ) -> str:
        """Return claimed, delivered, retry_wait, or exhausted for native AI Summary."""
        cid = str(incident_id or "").strip()
        if not cid:
            return "exhausted"
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        retry_ms = max(60, int(retry_after_seconds)) * 1000
        attempt_limit = max(1, int(max_attempts))
        with sqlite3.connect(self.path) as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "INSERT OR IGNORE INTO stellar_ai_summary_delivery "
                "(source_id, incident_id, jira_key, status) VALUES (?,?,?,'queued')",
                (source_id, cid, str(jira_key or "").strip() or None),
            )
            row = c.execute(
                "SELECT status, attempts, last_attempt_at_ms "
                "FROM stellar_ai_summary_delivery WHERE source_id=? AND incident_id=?",
                (source_id, cid),
            ).fetchone()
            status = str(row[0] or "") if row else "queued"
            attempts = int(row[1] or 0) if row else 0
            last_attempt_ms = int(row[2] or 0) if row else 0
            if status == "delivered":
                c.commit()
                return "delivered"
            if status == "exhausted" or attempts >= attempt_limit:
                c.execute(
                    "UPDATE stellar_ai_summary_delivery SET status='exhausted' "
                    "WHERE source_id=? AND incident_id=?",
                    (source_id, cid),
                )
                c.commit()
                return "exhausted"
            if status != "queued" and now_ms - last_attempt_ms < retry_ms:
                c.commit()
                return "retry_wait"
            c.execute(
                "UPDATE stellar_ai_summary_delivery SET status='pending', "
                "attempts=attempts+1, last_attempt_at_ms=?, jira_key=?, last_error=NULL "
                "WHERE source_id=? AND incident_id=?",
                (now_ms, str(jira_key or "").strip() or None, source_id, cid),
            )
            c.commit()
            return "claimed"

    def finish_stellar_ai_summary(
        self,
        source_id: str,
        incident_id: str,
        *,
        status: str,
        payload: dict | None = None,
        error: str = "",
    ) -> None:
        normalized = str(status or "").strip().lower()
        if normalized not in ("waiting", "failed", "delivered", "exhausted"):
            raise ValueError(f"invalid Stellar AI Summary status: {status}")
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE stellar_ai_summary_delivery SET status=?, completed_at=?, "
                "payload_json=COALESCE(?, payload_json), last_error=? "
                "WHERE source_id=? AND incident_id=?",
                (
                    normalized,
                    datetime.now(timezone.utc).isoformat()
                    if normalized in ("delivered", "exhausted")
                    else None,
                    json.dumps(payload, ensure_ascii=False, default=str)
                    if isinstance(payload, dict)
                    else None,
                    str(error or "").strip() or None,
                    source_id,
                    str(incident_id or "").strip(),
                ),
            )
            c.commit()

    def list_retryable_stellar_ai_summary_cases(
        self,
        source_id: str,
        *,
        retry_after_seconds: int,
        max_attempts: int,
    ) -> list[str]:
        cutoff_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - (
            max(60, int(retry_after_seconds)) * 1000
        )
        with sqlite3.connect(self.path) as c:
            rows = c.execute(
                "SELECT incident_id FROM stellar_ai_summary_delivery "
                "WHERE source_id=? AND status IN ('queued','waiting','failed','pending') "
                "AND attempts<? AND (status='queued' OR last_attempt_at_ms<=?) "
                "ORDER BY last_attempt_at_ms ASC",
                (source_id, max(1, int(max_attempts)), cutoff_ms),
            ).fetchall()
        return [str(row[0]) for row in rows if str(row[0] or "").strip()]

    def get_stellar_ai_summary_delivery(
        self,
        source_id: str,
        incident_id: str,
    ) -> dict | None:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM stellar_ai_summary_delivery "
                "WHERE source_id=? AND incident_id=?",
                (source_id, str(incident_id or "").strip()),
            ).fetchone()
        return dict(row) if row else None

    def remove_incident_link(self, source_id: str, incident_id: str) -> bool:
        """Drop a synced case↔Jira mapping. Returns True if a row was deleted."""
        iid = str(incident_id or "").strip()
        if not iid:
            return False
        with sqlite3.connect(self.path) as c:
            cur = c.execute(
                "DELETE FROM incident_jira WHERE source_id=? AND incident_id=?",
                (source_id, iid),
            )
            c.commit()
            return cur.rowcount > 0

    def get_meta(self, key: str) -> str | None:
        with sqlite3.connect(self.path) as c:
            r = c.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
            return str(r[0]) if r else None

    def set_meta(self, key: str, value: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO meta (k,v) VALUES (?,?)", (key, value))
            c.commit()

    def delete_meta(self, key: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("DELETE FROM meta WHERE k=?", (key,))
            c.commit()

    @staticmethod
    def deferred_create_meta_key(source_id: str) -> str:
        return f"deferred_create:{source_id}"

    def list_deferred_create(self, source_id: str) -> list[str]:
        """Cases deferred for failed Jira create / decision defer — re-fetched each poll.

        Severity-gated (Low/Medium) cases are not kept here; escalation is picked up via poll.
        """
        raw = self.get_meta(self.deferred_create_meta_key(source_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if str(x).strip()]

    def add_deferred_create(self, source_id: str, incident_id: str) -> None:
        cid = str(incident_id or "").strip()
        if not cid:
            return
        ids = self.list_deferred_create(source_id)
        if cid in ids:
            return
        ids.append(cid)
        self.set_meta(self.deferred_create_meta_key(source_id), json.dumps(ids))

    def remove_deferred_create(self, source_id: str, incident_id: str) -> None:
        cid = str(incident_id or "").strip()
        ids = [x for x in self.list_deferred_create(source_id) if x != cid]
        key = self.deferred_create_meta_key(source_id)
        if ids:
            self.set_meta(key, json.dumps(ids))
        else:
            self.delete_meta(key)

    def increment_case_sequence(self, customer_code: str, date_ymd: str) -> int:
        """Atomically bump daily sequence for ``customer_code`` (1-based)."""
        from app.sync.case_id import case_seq_meta_key

        key = case_seq_meta_key(customer_code, date_ymd)
        with sqlite3.connect(self.path) as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
            n = (int(row[0]) if row and row[0] is not None else 0) + 1
            c.execute("INSERT OR REPLACE INTO meta (k,v) VALUES (?,?)", (key, str(n)))
            c.commit()
            return n

    def linked_incident_count(self, *, source_id: str | None = None) -> int:
        with sqlite3.connect(self.path) as c:
            if source_id is None:
                r = c.execute("SELECT COUNT(*) FROM incident_jira").fetchone()
            else:
                r = c.execute(
                    "SELECT COUNT(*) FROM incident_jira WHERE source_id=?",
                    (source_id,),
                ).fetchone()
            return int(r[0]) if r and r[0] is not None else 0

    def linked_incident_counts_by_source(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as c:
            rows = c.execute(
                "SELECT source_id, COUNT(*) FROM incident_jira GROUP BY source_id ORDER BY source_id"
            ).fetchall()
        return {str(sid): int(n) for sid, n in rows}

    def list_linked_jira_keys(self, source_id: str) -> list[tuple[str, str]]:
        """Return ``(incident_id, jira_key)`` rows that finished sync (not pending)."""
        with sqlite3.connect(self.path) as c:
            rows = c.execute(
                "SELECT incident_id, jira_key FROM incident_jira "
                "WHERE source_id=? AND jira_key!=? ORDER BY synced_at DESC",
                (source_id, PENDING_JIRA_KEY),
            ).fetchall()
        out: list[tuple[str, str]] = []
        for iid, key in rows:
            ik = str(iid or "").strip()
            jk = str(key or "").strip()
            if ik and jk:
                out.append((ik, jk))
        return out

    def get_link_synced_at(self, source_id: str, incident_id: str) -> str | None:
        with sqlite3.connect(self.path) as c:
            r = c.execute(
                "SELECT synced_at FROM incident_jira WHERE source_id=? AND incident_id=?",
                (source_id, incident_id),
            ).fetchone()
        if not r or r[0] is None:
            return None
        s = str(r[0]).strip()
        return s or None
