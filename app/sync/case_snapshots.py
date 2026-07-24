"""Persist Stellar case + alert bundles (platform-normalized raw layer for Decision Dataset)."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.stellar.severity_filter import is_severity_escalation, normalize_stellar_severity

REPO_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _split_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "case": bundle.get("case"),
        "alerts": bundle.get("alerts"),
        "observables": bundle.get("observables"),
        "summary": bundle.get("summary"),
        "activities": bundle.get("activities"),
        "ai_summary": bundle.get("ai_summary"),
    }


def _severity_from_case(case: dict[str, Any] | None) -> str:
    if not isinstance(case, dict):
        return ""
    return normalize_stellar_severity(case.get("severity"))


def select_milestone_keep_ids(
    rows: list[dict[str, Any]],
    *,
    protected_ids: set[str] | frozenset[str] | None = None,
) -> set[str]:
    """
    Keep full-fidelity evidence milestones only:

    - snapshots referenced by ``decision_events``
    - earliest + latest ``modified_at``
    - any row with ``jira_key`` (create/link evidence)
    - first row for each distinct severity (Low→…→Critical ladder)
    """
    if not rows:
        return set()
    protected = {str(x).strip() for x in (protected_ids or set()) if str(x).strip()}
    ordered = sorted(
        rows,
        key=lambda r: (int(r.get("modified_at_ms") or 0), str(r.get("captured_at") or "")),
    )
    keep: set[str] = set(protected)
    keep.add(str(ordered[0]["snapshot_id"]))
    keep.add(str(ordered[-1]["snapshot_id"]))
    for row in ordered:
        if str(row.get("jira_key") or "").strip():
            keep.add(str(row["snapshot_id"]))
    seen_sev: set[str] = set()
    for row in ordered:
        sev = normalize_stellar_severity(row.get("severity") or "")
        if not sev or sev in seen_sev:
            continue
        seen_sev.add(sev)
        keep.add(str(row["snapshot_id"]))
    return keep


class CaseSnapshotStore:
    """SQLite store for Stellar case snapshots (same DB as sync state)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS stellar_case_snapshots ("
                "snapshot_id TEXT PRIMARY KEY, "
                "source_id TEXT NOT NULL, "
                "stellar_case_id TEXT NOT NULL, "
                "modified_at_ms INTEGER NOT NULL, "
                "captured_at TEXT NOT NULL, "
                "customer_code TEXT, "
                "jira_key TEXT, "
                "storage_mode TEXT NOT NULL DEFAULT 'inline', "
                "bundle_path TEXT, "
                "content_sha256 TEXT, "
                "bytes_size INTEGER NOT NULL DEFAULT 0, "
                "case_json TEXT, "
                "alerts_json TEXT, "
                "observables_json TEXT, "
                "summary_json TEXT, "
                "activities_json TEXT, "
                "ai_summary_json TEXT"
                ")"
            )
            cols = {str(r[1]) for r in c.execute("PRAGMA table_info(stellar_case_snapshots)")}
            if "severity" not in cols:
                c.execute("ALTER TABLE stellar_case_snapshots ADD COLUMN severity TEXT")
            if "ai_summary_json" not in cols:
                c.execute("ALTER TABLE stellar_case_snapshots ADD COLUMN ai_summary_json TEXT")
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_case_mod "
                "ON stellar_case_snapshots(source_id, stellar_case_id, modified_at_ms)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshot_case "
                "ON stellar_case_snapshots(source_id, stellar_case_id)"
            )
            c.commit()

    def get_by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        sid = str(snapshot_id or "").strip()
        if not sid:
            return None
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM stellar_case_snapshots WHERE snapshot_id=?",
                (sid,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_latest(
        self,
        source_id: str,
        stellar_case_id: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM stellar_case_snapshots WHERE source_id=? AND stellar_case_id=? "
                "ORDER BY modified_at_ms DESC, captured_at DESC LIMIT 1",
                (str(source_id or "").strip(), str(stellar_case_id or "").strip()),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_for_case(
        self,
        source_id: str,
        stellar_case_id: str,
        *,
        resolve_severity: bool = True,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM stellar_case_snapshots WHERE source_id=? AND stellar_case_id=? "
                "ORDER BY modified_at_ms ASC, captured_at ASC",
                (str(source_id or "").strip(), str(stellar_case_id or "").strip()),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            row = self._row_to_dict(r)
            if resolve_severity:
                row = self._resolve_severity(row, persist=True)
            else:
                row = self._enrich_row(row)
            out.append(row)
        return out

    def list_case_keys(self, source_id: str | None = None) -> list[tuple[str, str]]:
        with sqlite3.connect(self.path) as c:
            if source_id:
                rows = c.execute(
                    "SELECT DISTINCT source_id, stellar_case_id FROM stellar_case_snapshots "
                    "WHERE source_id=? ORDER BY 1, 2",
                    (str(source_id).strip(),),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT DISTINCT source_id, stellar_case_id FROM stellar_case_snapshots "
                    "ORDER BY 1, 2"
                ).fetchall()
        return [(str(a), str(b)) for a, b in rows]

    def find_existing(
        self,
        *,
        source_id: str,
        stellar_case_id: str,
        modified_at_ms: int,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM stellar_case_snapshots "
                "WHERE source_id=? AND stellar_case_id=? AND modified_at_ms=?",
                (str(source_id or "").strip(), str(stellar_case_id or "").strip(), int(modified_at_ms)),
            ).fetchone()
        return self._enrich_row(self._row_to_dict(row)) if row else None

    def protected_snapshot_ids(self) -> set[str]:
        """Snapshot IDs referenced by decision_events (must not GC)."""
        with sqlite3.connect(self.path) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "decision_events" not in tables:
                return set()
            cols = {str(r[1]) for r in c.execute("PRAGMA table_info(decision_events)")}
            if "snapshot_id" not in cols:
                return set()
            rows = c.execute(
                "SELECT DISTINCT snapshot_id FROM decision_events "
                "WHERE snapshot_id IS NOT NULL AND TRIM(snapshot_id) != ''"
            ).fetchall()
        return {str(r[0]).strip() for r in rows if r and r[0]}

    def delete_snapshot(self, snapshot_id: str) -> None:
        sid = str(snapshot_id or "").strip()
        if not sid:
            return
        row = self.get_by_id(sid)
        if row and row.get("storage_mode") == "file" and row.get("bundle_path"):
            path = Path(str(row["bundle_path"]))
            if not path.is_absolute():
                path = REPO_ROOT / path
            try:
                if path.is_file():
                    path.unlink()
            except OSError as e:
                logger.warning("case snapshot file delete failed path=%s: %s", path, e)
            # Best-effort: remove empty parent dirs under case_archive
            try:
                parent = path.parent
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
        with sqlite3.connect(self.path) as c:
            c.execute("DELETE FROM stellar_case_snapshots WHERE snapshot_id=?", (sid,))
            c.commit()

    def plan_prune_case(
        self,
        source_id: str,
        stellar_case_id: str,
        *,
        protected_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        rows = self.list_for_case(source_id, stellar_case_id)
        protected = protected_ids if protected_ids is not None else self.protected_snapshot_ids()
        keep = select_milestone_keep_ids(rows, protected_ids=protected)
        drop = [r for r in rows if str(r.get("snapshot_id")) not in keep]
        keep_rows = [r for r in rows if str(r.get("snapshot_id")) in keep]
        return {
            "source_id": source_id,
            "stellar_case_id": stellar_case_id,
            "total": len(rows),
            "keep": len(keep_rows),
            "drop": len(drop),
            "keep_ids": [str(r["snapshot_id"]) for r in keep_rows],
            "drop_ids": [str(r["snapshot_id"]) for r in drop],
            "drop_bytes": sum(int(r.get("bytes_size") or 0) for r in drop),
        }

    def prune_case(
        self,
        source_id: str,
        stellar_case_id: str,
        *,
        dry_run: bool = True,
        protected_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        plan = self.plan_prune_case(
            source_id, stellar_case_id, protected_ids=protected_ids
        )
        if dry_run or not plan["drop_ids"]:
            plan["deleted"] = 0
            return plan
        for sid in plan["drop_ids"]:
            self.delete_snapshot(sid)
        plan["deleted"] = len(plan["drop_ids"])
        return plan

    def prune_all(
        self,
        *,
        source_id: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        protected = self.protected_snapshot_ids()
        cases = self.list_case_keys(source_id)
        plans: list[dict[str, Any]] = []
        drop_total = 0
        deleted = 0
        drop_bytes = 0
        for sid, cid in cases:
            plan = self.prune_case(
                sid, cid, dry_run=dry_run, protected_ids=protected
            )
            if plan["drop"]:
                plans.append(plan)
            drop_total += int(plan["drop"])
            deleted += int(plan.get("deleted") or 0)
            drop_bytes += int(plan.get("drop_bytes") or 0)
        return {
            "cases": len(cases),
            "cases_with_drops": len(plans),
            "drop_total": drop_total,
            "deleted": deleted,
            "drop_bytes": drop_bytes,
            "dry_run": dry_run,
            "protected_snapshot_ids": len(protected),
            "plans": plans,
        }

    def upsert_bundle(
        self,
        *,
        source_id: str,
        stellar_case_id: str,
        bundle: dict[str, Any],
        customer_code: str = "",
        modified_at_ms: int | None = None,
        archive_dir: Path | str | None = None,
        max_inline_bytes: int = 2_097_152,
        allow_replace_on_escalation: bool = False,
        autoprune: bool = False,
    ) -> str | None:
        """
        Insert snapshot when ``modified_at_ms`` is new for this case.

        Returns existing or new ``snapshot_id``, or None when bundle is empty / skipped.
        """
        cid = str(stellar_case_id or "").strip()
        if not cid:
            return None
        case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
        mod = int(modified_at_ms if modified_at_ms is not None else case.get("modified_at") or 0)
        existing = self.find_existing(source_id=source_id, stellar_case_id=cid, modified_at_ms=mod)
        if existing:
            if allow_replace_on_escalation:
                old_bundle = self.load_bundle_payload(existing)
                old_case = old_bundle.get("case") if isinstance(old_bundle.get("case"), dict) else {}
                old_sev = old_case.get("severity")
                new_sev = case.get("severity")
                if is_severity_escalation(old_sev, new_sev):
                    self.delete_snapshot(str(existing["snapshot_id"]))
                else:
                    return str(existing["snapshot_id"])
            else:
                return str(existing["snapshot_id"])

        parts = _split_bundle(bundle)
        severity = _severity_from_case(case if isinstance(case, dict) else None)
        full_payload = {"case_id": cid, **parts}
        raw = _json_bytes(full_payload)
        sha = hashlib.sha256(raw).hexdigest()
        size = len(raw)

        storage_mode = "inline"
        bundle_path: str | None = None
        case_json = alerts_json = observables_json = summary_json = activities_json = None
        ai_summary_json = None

        if size > max_inline_bytes and archive_dir:
            base = Path(archive_dir)
            if not base.is_absolute():
                base = REPO_ROOT / base
            rel_dir = base / str(source_id or "stellar") / cid
            rel_dir.mkdir(parents=True, exist_ok=True)
            file_path = rel_dir / f"{mod}.json"
            file_path.write_bytes(raw)
            storage_mode = "file"
            try:
                bundle_path = str(file_path.relative_to(REPO_ROOT))
            except ValueError:
                bundle_path = str(file_path)
            logger.info(
                "case snapshot stored as file case_id=%s bytes=%s path=%s",
                cid,
                size,
                bundle_path,
            )
        else:
            if size > max_inline_bytes:
                logger.warning(
                    "case snapshot large inline case_id=%s bytes=%s max=%s",
                    cid,
                    size,
                    max_inline_bytes,
                )
            case_json = json.dumps(parts.get("case"), ensure_ascii=False) if parts.get("case") else None
            alerts_json = json.dumps(parts.get("alerts"), ensure_ascii=False) if parts.get("alerts") else None
            observables_json = (
                json.dumps(parts.get("observables"), ensure_ascii=False) if parts.get("observables") else None
            )
            summary_json = json.dumps(parts.get("summary"), ensure_ascii=False) if parts.get("summary") else None
            activities_json = (
                json.dumps(parts.get("activities"), ensure_ascii=False) if parts.get("activities") else None
            )
            ai_summary_json = (
                json.dumps(parts.get("ai_summary"), ensure_ascii=False)
                if parts.get("ai_summary")
                else None
            )

        snapshot_id = str(uuid.uuid4())
        ts = _utc_now()
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO stellar_case_snapshots ("
                "snapshot_id, source_id, stellar_case_id, modified_at_ms, captured_at, "
                "customer_code, storage_mode, bundle_path, content_sha256, bytes_size, "
                "case_json, alerts_json, observables_json, summary_json, activities_json, "
                "severity, ai_summary_json"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    snapshot_id,
                    str(source_id or "").strip(),
                    cid,
                    mod,
                    ts,
                    str(customer_code or "").strip().upper() or None,
                    storage_mode,
                    bundle_path,
                    sha,
                    size,
                    case_json,
                    alerts_json,
                    observables_json,
                    summary_json,
                    activities_json,
                    severity or None,
                    ai_summary_json,
                ),
            )
            c.commit()

        if autoprune:
            try:
                plan = self.prune_case(source_id, cid, dry_run=False)
                if plan.get("deleted"):
                    logger.info(
                        "case snapshot autoprune case_id=%s deleted=%s kept=%s",
                        cid,
                        plan["deleted"],
                        plan["keep"],
                    )
            except Exception as e:
                logger.warning("case snapshot autoprune failed case_id=%s: %s", cid, e)

        return snapshot_id

    def update_jira_key(self, snapshot_id: str, jira_key: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE stellar_case_snapshots SET jira_key=? WHERE snapshot_id=?",
                (str(jira_key or "").strip(), str(snapshot_id or "").strip()),
            )
            c.commit()

    def attach_ai_summary(
        self,
        source_id: str,
        stellar_case_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Attach native Stellar AI Summary to the latest raw snapshot."""
        row = self.get_latest(source_id, stellar_case_id)
        if row is None or not isinstance(payload, dict):
            return False
        raw_ai = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        snapshot_id = str(row.get("snapshot_id") or "")
        if row.get("storage_mode") == "file" and row.get("bundle_path"):
            path = Path(str(row["bundle_path"]))
            if not path.is_absolute():
                path = REPO_ROOT / path
            if not path.is_file():
                logger.warning("case snapshot file missing path=%s", path)
                return False
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(bundle, dict):
                return False
            bundle["ai_summary"] = payload
            raw = _json_bytes(bundle)
            path.write_bytes(raw)
            with sqlite3.connect(self.path) as c:
                c.execute(
                    "UPDATE stellar_case_snapshots SET ai_summary_json=?, "
                    "content_sha256=?, bytes_size=? WHERE snapshot_id=?",
                    (raw_ai, hashlib.sha256(raw).hexdigest(), len(raw), snapshot_id),
                )
                c.commit()
            return True
        bundle = self.load_bundle_payload(row)
        bundle["ai_summary"] = payload
        raw = _json_bytes(bundle)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE stellar_case_snapshots SET ai_summary_json=?, "
                "content_sha256=?, bytes_size=? WHERE snapshot_id=?",
                (raw_ai, hashlib.sha256(raw).hexdigest(), len(raw), snapshot_id),
            )
            c.commit()
        return True

    def load_bundle_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        """Reconstruct bundle dict from inline columns or external file."""
        if row.get("storage_mode") == "file" and row.get("bundle_path"):
            path = Path(str(row["bundle_path"]))
            if not path.is_absolute():
                path = REPO_ROOT / path
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
            logger.warning("case snapshot file missing path=%s", path)
            return {}
        out: dict[str, Any] = {"case_id": row.get("stellar_case_id")}
        for key, col in (
            ("case", "case"),
            ("alerts", "alerts"),
            ("observables", "observables"),
            ("summary", "summary"),
            ("activities", "activities"),
            ("ai_summary", "ai_summary"),
        ):
            raw = row.get(f"{col}_json") or row.get(col)
            if raw is None:
                continue
            if isinstance(raw, str):
                try:
                    out[key] = json.loads(raw)
                except json.JSONDecodeError:
                    out[key] = raw
            else:
                out[key] = raw
        return out

    def _enrich_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Fill severity from metadata / case_json when the column is empty."""
        if not row:
            return row
        if normalize_stellar_severity(row.get("severity") or ""):
            return row
        raw = row.get("case_json")
        if isinstance(raw, str) and raw.strip():
            try:
                case = json.loads(raw)
            except json.JSONDecodeError:
                case = None
            sev = _severity_from_case(case if isinstance(case, dict) else None)
            if sev:
                row = dict(row)
                row["severity"] = sev
        return row

    def _resolve_severity(self, row: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
        """Resolve severity from inline JSON or file payload; optionally backfill column."""
        row = self._enrich_row(row)
        sev = normalize_stellar_severity(row.get("severity") or "")
        if not sev and row.get("storage_mode") == "file":
            bundle = self.load_bundle_payload(row)
            case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
            sev = _severity_from_case(case)
            if sev:
                row = dict(row)
                row["severity"] = sev
        if persist and sev:
            sid = str(row.get("snapshot_id") or "").strip()
            if sid:
                with sqlite3.connect(self.path) as c:
                    c.execute(
                        "UPDATE stellar_case_snapshots SET severity=? "
                        "WHERE snapshot_id=? AND (severity IS NULL OR TRIM(severity)='')",
                        (sev, sid),
                    )
                    c.commit()
        return row

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        return dict(row)


def get_case_snapshot_store(state_db_path: Path | str | None = None) -> CaseSnapshotStore:
    from app.config import get_stellar_settings

    st = get_stellar_settings()
    if state_db_path:
        path = Path(state_db_path)
    else:
        path = REPO_ROOT / st.stellar_sync_state_db
    store = CaseSnapshotStore(path)
    store.init()
    return store


async def archive_stellar_bundle(
    *,
    st: Any,
    client: Any,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    source_id: str,
    customer_code: str,
    snapshot_store: CaseSnapshotStore | None,
    dry_run: bool,
    force: bool = False,
    allow_replace_on_escalation: bool = False,
) -> str | None:
    """Fetch (if needed) and persist a case bundle snapshot. Returns snapshot_id."""
    if dry_run or not (force or getattr(st, "case_archive_enabled", False)):
        return None
    if snapshot_store is None:
        return None
    cid = str(case.get("_id") or "").strip()
    if not cid:
        return None
    data = bundle
    if data is None or not data.get("alerts"):
        try:
            data = await client.fetch_case_bundle(cid)
        except Exception as e:
            logger.warning("case archive fetch failed case_id=%s: %s", cid, e)
            return None
    if not isinstance(data, dict):
        return None
    try:
        return snapshot_store.upsert_bundle(
            source_id=source_id,
            stellar_case_id=cid,
            bundle=data,
            customer_code=customer_code,
            modified_at_ms=int(case.get("modified_at") or 0),
            archive_dir=getattr(st, "case_archive_dir", "data/case_archive"),
            max_inline_bytes=int(getattr(st, "case_archive_max_bytes", 2_097_152)),
            allow_replace_on_escalation=allow_replace_on_escalation,
            autoprune=bool(getattr(st, "case_archive_autoprune", True)),
        )
    except Exception as e:
        logger.warning("case archive upsert failed case_id=%s: %s", cid, e)
        return None
