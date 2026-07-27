"""Tests for per-tenant secret env resolution."""

from __future__ import annotations

import os
import unittest

from app.platform.tenant_secrets import (
    encrypt_cycraft_secrets,
    read_cycraft_secret,
    read_tenant_env_secret,
    tenant_env_var,
    tenant_secret_configured,
)


class TestTenantSecrets(unittest.TestCase):
    def test_env_var_suffix(self) -> None:
        self.assertEqual(tenant_env_var("jjnet-edr", "XCOCKPIT_API_KEY"), "XCOCKPIT_API_KEY__JJNET_EDR")

    def test_no_cross_tenant_env_fallback(self) -> None:
        os.environ["XCOCKPIT_API_KEY__JJNET"] = "secret-jjnet"
        os.environ["XCOCKPIT_API_KEY__JJNET_EDR"] = "secret-edr"
        self.assertEqual(read_tenant_env_secret("jjnet", "XCOCKPIT_API_KEY"), "secret-jjnet")
        self.assertEqual(read_tenant_env_secret("jjnet-edr", "XCOCKPIT_API_KEY"), "secret-edr")
        self.assertEqual(read_tenant_env_secret("other", "XCOCKPIT_API_KEY"), "")
        del os.environ["XCOCKPIT_API_KEY__JJNET"]
        del os.environ["XCOCKPIT_API_KEY__JJNET_EDR"]

    def test_db_secret_over_env(self) -> None:
        os.environ["STELLAR_XDR_API_KEY__JJNET"] = "from-env"
        enc = encrypt_cycraft_secrets({"stellar_xdr_api_key": "from-db"})
        cfg = {"secrets_enc": enc}
        self.assertEqual(read_cycraft_secret("jjnet", "STELLAR_XDR_API_KEY", cfg), "from-db")
        del os.environ["STELLAR_XDR_API_KEY__JJNET"]

    def test_configured_flag(self) -> None:
        enc = encrypt_cycraft_secrets({"stellar_xdr_api_key": "xdr-key"})
        cfg = {"secrets_enc": enc}
        self.assertTrue(tenant_secret_configured("jjnet", "STELLAR_XDR_API_KEY", cfg))
        self.assertFalse(tenant_secret_configured("jjnet-edr", "STELLAR_XDR_API_KEY", {}))


if __name__ == "__main__":
    unittest.main()
