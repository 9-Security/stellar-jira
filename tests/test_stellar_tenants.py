"""Tests for multi-tenant Stellar report config."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import StellarSettings
from app.stellar.tenant_model import StellarTenant
from app.stellar.tenants import (
    load_stellar_tenants,
    resolve_case_tenant,
    resolve_report_tenant,
    validate_tenant_registry,
)


class TestStellarTenants(unittest.TestCase):
    def test_legacy_single_tenant(self) -> None:
        settings = StellarSettings(
            stellar_default_customer_code="JJ",
            stellar_tenant_id="tid-1",
            stellar_poll_source_id="stellar",
            stellar_jira_project_key="AIXSOC",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tenants = load_stellar_tenants(settings, root)
        self.assertEqual(len(tenants), 1)
        self.assertEqual(tenants[0].source_id, "stellar")
        self.assertEqual(tenants[0].customer_code, "JJ")

    def test_load_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config"
            cfg.mkdir()
            data = [
                {
                    "source_id": "a",
                    "customer_code": "AA",
                    "tenant_name": "TenantA",
                    "products": ["darktrace"],
                },
                {
                    "source_id": "b",
                    "customer_code": "BB",
                    "tenant_name": "TenantB",
                    "products": ["darktrace"],
                },
            ]
            (cfg / "stellar_tenants.json").write_text(json.dumps(data), encoding="utf-8")
            settings = StellarSettings(stellar_tenants_path="config/stellar_tenants.json")
            tenants = load_stellar_tenants(settings, root)
        self.assertEqual(len(tenants), 2)
        t = resolve_report_tenant(tenants, source_id="b")
        self.assertEqual(t.customer_code, "BB")

    def test_resolve_requires_selector_when_multiple(self) -> None:
        tenants = [
            StellarTenant(source_id="a", customer_code="AA", products=["darktrace"]),
            StellarTenant(source_id="b", customer_code="BB", products=["darktrace"]),
        ]
        with self.assertRaises(ValueError):
            resolve_report_tenant(tenants)

    def test_product_support(self) -> None:
        t = StellarTenant(source_id="x", customer_code="XX", products=["darktrace", "cortex"])
        self.assertTrue(t.supports_product("darktrace"))
        self.assertTrue(t.supports_product("cortex"))
        self.assertFalse(t.supports_product("unknown"))

    def test_case_tenant_uses_cust_id_as_authority(self) -> None:
        tenant = StellarTenant(
            source_id="a",
            customer_code="AA",
            tenant_id="id-a",
            tenant_name="TenantA",
        )
        resolved, reason = resolve_case_tenant(
            [tenant], {"cust_id": "unknown", "tenant_name": "TenantA"}
        )
        self.assertIsNone(resolved)
        self.assertEqual(reason, "unknown_tenant_id")

    def test_case_tenant_rejects_name_mismatch(self) -> None:
        tenant = StellarTenant(
            source_id="a",
            customer_code="AA",
            tenant_id="id-a",
            tenant_name="TenantA",
        )
        resolved, reason = resolve_case_tenant(
            [tenant], {"cust_id": "id-a", "tenant_name": "TenantB"}
        )
        self.assertIsNone(resolved)
        self.assertEqual(reason, "tenant_name_mismatch")

    def test_registry_validation_requires_unique_identity(self) -> None:
        tenants = [
            StellarTenant(
                source_id="a",
                customer_code="AA",
                tenant_id="same",
                tenant_name="TenantA",
            ),
            StellarTenant(
                source_id="b",
                customer_code="BB",
                tenant_id="same",
                tenant_name="TenantB",
            ),
        ]
        errors = validate_tenant_registry(tenants)
        self.assertTrue(any("duplicate tenant_id" in error for error in errors))

    def test_disabled_tenant_does_not_support_sync_or_reports(self) -> None:
        tenant = StellarTenant(
            source_id="x",
            customer_code="XX",
            enabled=False,
            products=["darktrace"],
        )
        self.assertFalse(tenant.sync_is_enabled())
        self.assertFalse(tenant.supports_product("darktrace"))


if __name__ == "__main__":
    unittest.main()
