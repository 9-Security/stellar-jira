"""Tests for platform user store validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.platform.security import hash_password
from app.platform.store import PlatformStore


class TestPlatformStoreUsers(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "platform.db"
        self.store = PlatformStore(self.db)
        self.store.init()
        self.viewer = self.store.create_user(
            email="viewer@jjnet.test",
            password_hash=hash_password("password123"),
            role="tenant_viewer",
            tenant_source_id="jjnet",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_update_to_tenant_role_without_tenant_rejected(self) -> None:
        platform_user = self.store.create_user(
            email="soc@demo.test",
            password_hash=hash_password("password123"),
            role="soc_analyst",
        )
        with self.assertRaises(ValueError) as ctx:
            self.store.update_user(platform_user["id"], role="tenant_admin")
        self.assertIn("tenant_source_id", str(ctx.exception))

    def test_promote_to_platform_role_clears_tenant(self) -> None:
        updated = self.store.update_user(self.viewer["id"], role="platform_admin")
        self.assertEqual(updated["role"], "platform_admin")
        self.assertIsNone(updated["tenant_source_id"])

    def test_patch_role_only_keeps_tenant_for_tenant_roles(self) -> None:
        updated = self.store.update_user(self.viewer["id"], role="tenant_admin")
        self.assertEqual(updated["role"], "tenant_admin")
        self.assertEqual(updated["tenant_source_id"], "jjnet")


if __name__ == "__main__":
    unittest.main()
