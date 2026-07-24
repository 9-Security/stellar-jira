"""SQLite store for platform users and audit."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.platform.roles import TENANT_ROLES, UserRole, is_platform_role, is_tenant_role
from app.platform.totp_policy import VALID_TOTP_POLICIES, normalize_totp_policy


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class PlatformStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "id TEXT PRIMARY KEY, "
                "email TEXT NOT NULL UNIQUE COLLATE NOCASE, "
                "password_hash TEXT NOT NULL, "
                "role TEXT NOT NULL, "
                "tenant_source_id TEXT, "
                "totp_secret TEXT, "
                "totp_enabled INTEGER NOT NULL DEFAULT 0, "
                "is_active INTEGER NOT NULL DEFAULT 1, "
                "created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_source_id)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS audit_log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id TEXT, "
                "action TEXT NOT NULL, "
                "resource_type TEXT, "
                "resource_id TEXT, "
                "tenant_source_id TEXT, "
                "ip_address TEXT, "
                "detail_json TEXT, "
                "created_at TEXT NOT NULL)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)"
            )
            cols = {row[1] for row in c.execute("PRAGMA table_info(users)")}
            if "totp_policy" not in cols:
                c.execute(
                    "ALTER TABLE users ADD COLUMN totp_policy TEXT NOT NULL DEFAULT 'optional'"
                )
            c.commit()

    def _row_to_user(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "role": row["role"],
            "tenant_source_id": row["tenant_source_id"],
            "totp_secret": row["totp_secret"],
            "totp_enabled": bool(row["totp_enabled"]),
            "totp_policy": normalize_totp_policy(
                row["totp_policy"] if "totp_policy" in row.keys() else "optional"
            ),
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._row_to_user(row)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        normalized = str(email or "").strip().lower()
        if not normalized:
            return None
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM users WHERE email=? COLLATE NOCASE",
                (normalized,),
            ).fetchone()
        return self._row_to_user(row)

    def list_users(
        self,
        *,
        tenant_source_id: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_source_id is not None:
            clauses.append("tenant_source_id=?")
            params.append(tenant_source_id)
        if not include_inactive:
            clauses.append("is_active=1")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                f"SELECT * FROM users{where} ORDER BY email",
                params,
            ).fetchall()
        return [u for u in (self._row_to_user(r) for r in rows) if u is not None]

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        role: str,
        tenant_source_id: str | None = None,
        totp_policy: str = "optional",
    ) -> dict[str, Any]:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email or "@" not in normalized_email:
            raise ValueError("invalid email")
        try:
            parsed_role = UserRole(role)
        except ValueError as e:
            raise ValueError(f"invalid role: {role}") from e
        tenant = str(tenant_source_id or "").strip() or None
        if is_platform_role(parsed_role) and tenant:
            raise ValueError("platform roles must not have tenant_source_id")
        if is_tenant_role(parsed_role) and not tenant:
            raise ValueError("tenant roles require tenant_source_id")
        if parsed_role in TENANT_ROLES and not tenant:
            raise ValueError("tenant roles require tenant_source_id")
        policy = normalize_totp_policy(totp_policy)

        user_id = str(uuid.uuid4())
        now = _utc_now()
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO users ("
                "id, email, password_hash, role, tenant_source_id, "
                "totp_secret, totp_enabled, totp_policy, is_active, created_at, updated_at"
                ") VALUES (?,?,?,?,?,NULL,0,?,1,?,?)",
                (
                    user_id,
                    normalized_email,
                    password_hash,
                    parsed_role.value,
                    tenant,
                    policy,
                    now,
                    now,
                ),
            )
            c.commit()
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("failed to create user")
        return user

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        tenant_source_id: str | None = None,
        totp_policy: str | None = None,
        is_active: bool | None = None,
        clear_totp: bool = False,
    ) -> dict[str, Any]:
        user = self.get_user_by_id(user_id)
        if user is None:
            raise ValueError("user not found")
        fields: list[str] = []
        params: list[Any] = []
        if role is not None:
            try:
                parsed_role = UserRole(role)
            except ValueError as e:
                raise ValueError(f"invalid role: {role}") from e
            fields.append("role=?")
            params.append(parsed_role.value)
        if tenant_source_id is not None:
            fields.append("tenant_source_id=?")
            params.append(str(tenant_source_id).strip() or None)
        if totp_policy is not None:
            policy = normalize_totp_policy(totp_policy)
            fields.append("totp_policy=?")
            params.append(policy)
        if is_active is not None:
            fields.append("is_active=?")
            params.append(1 if is_active else 0)
        if clear_totp:
            fields.extend(["totp_secret=NULL", "totp_enabled=0"])
        if not fields:
            return user
        now = _utc_now()
        fields.append("updated_at=?")
        params.append(now)
        params.append(user_id)
        with sqlite3.connect(self.path) as c:
            c.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", params)
            c.commit()
        updated = self.get_user_by_id(user_id)
        if updated is None:
            raise RuntimeError("failed to update user")
        return updated

    def set_totp_secret(self, user_id: str, secret: str, *, enabled: bool) -> None:
        now = _utc_now()
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE users SET totp_secret=?, totp_enabled=?, updated_at=? WHERE id=?",
                (secret, 1 if enabled else 0, now, user_id),
            )
            c.commit()

    def clear_totp(self, user_id: str) -> None:
        now = _utc_now()
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE users SET totp_secret=NULL, totp_enabled=0, updated_at=? WHERE id=?",
                (now, user_id),
            )
            c.commit()

    def set_active(self, user_id: str, *, is_active: bool) -> None:
        now = _utc_now()
        with sqlite3.connect(self.path) as c:
            c.execute(
                "UPDATE users SET is_active=?, updated_at=? WHERE id=?",
                (1 if is_active else 0, now, user_id),
            )
            c.commit()

    def record_audit(
        self,
        *,
        user_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        tenant_source_id: str | None = None,
        ip_address: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        import json

        now = _utc_now()
        detail_json = json.dumps(detail, ensure_ascii=False) if detail else None
        with sqlite3.connect(self.path) as c:
            c.execute(
                "INSERT INTO audit_log ("
                "user_id, action, resource_type, resource_id, tenant_source_id, "
                "ip_address, detail_json, created_at"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    tenant_source_id,
                    ip_address,
                    detail_json,
                    now,
                ),
            )
            c.commit()

    def public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "tenant_source_id": user.get("tenant_source_id"),
            "totp_enabled": bool(user.get("totp_enabled")),
            "totp_policy": normalize_totp_policy(user.get("totp_policy")),
            "is_active": bool(user.get("is_active")),
            "created_at": user.get("created_at"),
        }
