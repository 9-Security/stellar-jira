"""Tests for Stellar case.name display cleaning."""

from __future__ import annotations

import unittest

from app.stellar.case_display_name import clean_stellar_case_name, stellar_case_display_name


class TestStellarCaseDisplayName(unittest.TestCase):
    def test_strip_palo_alto_prefix_and_suffix(self) -> None:
        raw = "Palo Alto Networks Cortex XDR (XDR Agent): WildFire Malware and 8 others"
        self.assertEqual(clean_stellar_case_name(raw), "WildFire Malware")

    def test_strip_carbon_black_style(self) -> None:
        raw = "Carbon Black:XDR Endpoint Indicator of Threat and 16 others"
        self.assertEqual(clean_stellar_case_name(raw), "XDR Endpoint Indicator of Threat")

    def test_strip_darktrace_prefix(self) -> None:
        raw = "darktrace:Rare binary connected to a rare external host and 5 others"
        self.assertEqual(clean_stellar_case_name(raw), "Rare binary connected to a rare external host")

    def test_no_prefix_only_suffix(self) -> None:
        raw = "Custom alert title and 2 others"
        self.assertEqual(clean_stellar_case_name(raw), "Custom alert title")

    def test_plain_name_unchanged(self) -> None:
        raw = "Microsoft Office adds a value to autostart Registry key"
        self.assertEqual(clean_stellar_case_name(raw), raw)

    def test_bundle_xdr_fallback(self) -> None:
        case = {"name": ""}
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "xdr_event": {
                                    "description": (
                                        'Palo Alto Networks Cortex XDR Agent identified "WildFire Malware" '
                                        "on endpoint host."
                                    )
                                }
                            }
                        }
                    ]
                }
            }
        }
        self.assertEqual(stellar_case_display_name(case, bundle), "WildFire Malware")


if __name__ == "__main__":
    unittest.main()
