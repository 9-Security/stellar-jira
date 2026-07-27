"""SQLite deduplication and poll watermarks."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class EventState:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_events (
                event_key TEXT PRIMARY KEY,
                sent_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS poll_watermarks (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incident_case_map (
                incident_uuid TEXT PRIMARY KEY,
                stellar_case_id TEXT,
                sync_status TEXT NOT NULL,
                last_state TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.commit()

    def seen(self, event_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sent_events WHERE event_key = ? LIMIT 1", (event_key,)
        ).fetchone()
        return row is not None

    def mark_sent(self, event_key: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sent_events (event_key) VALUES (?)", (event_key,)
        )
        self._conn.commit()

    def clear_sent_events(self) -> None:
        self._conn.execute("DELETE FROM sent_events")
        self._conn.commit()

    def get_watermark(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM poll_watermarks WHERE key = ? LIMIT 1", (key,)
        ).fetchone()
        return row[0] if row else None

    def set_watermark(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO poll_watermarks (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._conn.commit()

    def get_incident_map(self, incident_uuid: str) -> dict[str, str] | None:
        row = self._conn.execute(
            """
            SELECT incident_uuid, stellar_case_id, sync_status, last_state
            FROM incident_case_map
            WHERE incident_uuid = ?
            LIMIT 1
            """,
            (incident_uuid,),
        ).fetchone()
        if not row:
            return None
        return {
            "incident_uuid": row[0],
            "stellar_case_id": row[1] or "",
            "sync_status": row[2],
            "last_state": row[3] or "",
        }

    def upsert_incident_map(
        self,
        incident_uuid: str,
        *,
        stellar_case_id: str | None = None,
        sync_status: str,
        last_state: str | None = None,
    ) -> None:
        existing = self.get_incident_map(incident_uuid)
        case_id = stellar_case_id
        if case_id is None and existing:
            case_id = existing.get("stellar_case_id") or None
        self._conn.execute(
            """
            INSERT INTO incident_case_map (
                incident_uuid, stellar_case_id, sync_status, last_state, updated_at
            ) VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(incident_uuid) DO UPDATE SET
                stellar_case_id = COALESCE(excluded.stellar_case_id, incident_case_map.stellar_case_id),
                sync_status = excluded.sync_status,
                last_state = COALESCE(excluded.last_state, incident_case_map.last_state),
                updated_at = datetime('now')
            """,
            (incident_uuid, case_id, sync_status, last_state),
        )
        self._conn.commit()

    def set_incident_case_id(self, incident_uuid: str, stellar_case_id: str) -> None:
        self.upsert_incident_map(
            incident_uuid,
            stellar_case_id=stellar_case_id,
            sync_status="mapped",
        )

    def close(self) -> None:
        self._conn.close()
