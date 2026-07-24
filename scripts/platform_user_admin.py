#!/usr/bin/env python3
"""Create and list platform users (PRD v0.1 P0)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_platform_settings  # noqa: E402
from app.platform.roles import UserRole, is_platform_role, is_tenant_role  # noqa: E402
from app.platform.security import hash_password  # noqa: E402
from app.platform.store import PlatformStore  # noqa: E402
from app.platform.totp_policy import VALID_TOTP_POLICIES  # noqa: E402


def _store() -> PlatformStore:
    st = get_platform_settings()
    store = PlatformStore(st.db_path_resolved())
    store.init()
    return store


def cmd_create(args: argparse.Namespace) -> int:
    role = str(args.role).strip()
    try:
        UserRole(role)
    except ValueError:
        print(f"invalid role: {role}", file=sys.stderr)
        print("valid:", ", ".join(r.value for r in UserRole), file=sys.stderr)
        return 1
    tenant = str(args.tenant or "").strip() or None
    if is_platform_role(role) and tenant:
        print("platform roles must not use --tenant", file=sys.stderr)
        return 1
    if is_tenant_role(role) and not tenant:
        print("tenant roles require --tenant <source_id>", file=sys.stderr)
        return 1
    store = _store()
    if store.get_user_by_email(args.email):
        print(f"user already exists: {args.email}", file=sys.stderr)
        return 1
    try:
        user = store.create_user(
            email=args.email,
            password_hash=hash_password(args.password),
            role=role,
            tenant_source_id=tenant,
            totp_policy=args.totp_policy,
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    public = store.public_user(user)
    print(json.dumps({"ok": True, "user": public}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = _store()
    tenant = str(args.tenant or "").strip() or None
    users = store.list_users(
        tenant_source_id=tenant,
        include_inactive=args.include_inactive,
    )
    rows = [store.public_user(u) for u in users]
    print(json.dumps({"ok": True, "users": rows}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Platform user administration")
    sub = parser.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create", help="Create a user")
    create.add_argument("email")
    create.add_argument("password")
    create.add_argument(
        "--role",
        default=UserRole.PLATFORM_ADMIN.value,
        choices=[r.value for r in UserRole],
    )
    create.add_argument("--tenant", default="", help="tenant source_id for tenant roles")
    create.add_argument(
        "--totp-policy",
        default="optional",
        choices=sorted(VALID_TOTP_POLICIES),
        help="2FA policy: off, optional, required",
    )
    create.set_defaults(func=cmd_create)

    list_p = sub.add_parser("list", help="List users")
    list_p.add_argument("--tenant", default="", help="Filter by tenant source_id")
    list_p.add_argument("--include-inactive", action="store_true")
    list_p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
