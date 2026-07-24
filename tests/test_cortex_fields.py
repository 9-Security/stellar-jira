"""Tests for Cortex case_id detection on Stellar alert bundles."""

from __future__ import annotations

import unittest

from app.stellar.cortex_fields import (
    cortex_case_id_from_alert_source,
    stellar_bundle_has_cortex_case_id,
)


class TestCortexFields(unittest.TestCase):
    def test_case_id_present(self) -> None:
        src = {"palo_alto_networks": {"case_id": 3452, "category": "Malware"}}
        self.assertEqual(cortex_case_id_from_alert_source(src), "3452")

    def test_case_id_null_or_missing(self) -> None:
        self.assertEqual(
            cortex_case_id_from_alert_source({"palo_alto_networks": {"case_id": None}}),
            "",
        )
        self.assertEqual(cortex_case_id_from_alert_source({"palo_alto_networks": {}}), "")

    def test_bundle_1214_style_no_cortex(self) -> None:
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Persistence",
                                    "case_id": None,
                                    "description": "BIOC",
                                }
                            }
                        }
                    ]
                }
            }
        }
        self.assertFalse(stellar_bundle_has_cortex_case_id(bundle))

    def test_bundle_1222_style_has_cortex(self) -> None:
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Malware",
                                    "case_id": 3452,
                                }
                            }
                        }
                    ]
                }
            }
        }
        self.assertTrue(stellar_bundle_has_cortex_case_id(bundle))


if __name__ == "__main__":
    unittest.main()
