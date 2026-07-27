"""Tests for live overview tenant filtering."""

from __future__ import annotations

import unittest

from app.demo.tenant_access import filter_live_cases_for_tenant, live_case_matches_tenant
from app.stellar.tenant_model import StellarTenant


class TestLiveTenantFilter(unittest.TestCase):
  def _jjnet(self) -> StellarTenant:
    return StellarTenant(
      source_id="jjnet",
      customer_code="JJNET",
      tenant_name="JJNET",
      tenant_id="tenant-jjnet-uuid",
    )

  def _jjnet_edr(self) -> StellarTenant:
    return StellarTenant(
      source_id="jjnet-edr",
      customer_code="JJEDR",
      tenant_name="JJNET-EDR",
      tenant_id="0798c4e937864bc1b5d3d6940856ca6f",
    )

  def test_jjnet_does_not_match_jjnet_edr_name(self) -> None:
    case = {"tenant_name": "JJNET-EDR", "cust_id": "0798c4e937864bc1b5d3d6940856ca6f"}
    self.assertFalse(live_case_matches_tenant(case, self._jjnet()))
    self.assertTrue(live_case_matches_tenant(case, self._jjnet_edr()))

  def test_jjnet_matches_by_tenant_id(self) -> None:
    case = {"tenant_name": "JJNET", "cust_id": "tenant-jjnet-uuid"}
    self.assertTrue(live_case_matches_tenant(case, self._jjnet()))

  def test_filter_live_cases_for_tenant(self) -> None:
    from unittest.mock import patch

    from app.config import StellarSettings

    st = StellarSettings()
    cases = [
      {"tenant_name": "JJNET", "cust_id": "tenant-jjnet-uuid", "_id": "a"},
      {"tenant_name": "JJNET-EDR", "cust_id": "0798c4e937864bc1b5d3d6940856ca6f", "_id": "b"},
    ]
    with patch("app.demo.tenant_access.load_stellar_tenants", return_value=[self._jjnet(), self._jjnet_edr()]):
      filtered = filter_live_cases_for_tenant(st, "jjnet", cases)
    self.assertEqual(len(filtered), 1)
    self.assertEqual(filtered[0]["_id"], "a")


if __name__ == "__main__":
  unittest.main()
