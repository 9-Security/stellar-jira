"""Tests for Stellar response action / notify disposition."""

from __future__ import annotations

import unittest

from app.stellar.response_action import (
    stellar_notify_disposition_label,
    stellar_response_action_is_blocked,
    stellar_subject_detection_phrase,
)


class TestStellarResponseAction(unittest.TestCase):
    def test_blocked_prevented(self) -> None:
        self.assertTrue(stellar_response_action_is_blocked("Prevented (Blocked)"))

    def test_detect_only(self) -> None:
        self.assertFalse(stellar_response_action_is_blocked("Detected"))

    def test_disposition_labels(self) -> None:
        blocked_bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {"_source": {"palo_alto_networks": {"action_pretty": "Prevented (Blocked)"}}}
                    ]
                }
            }
        }
        detect_bundle = {
            "alerts": {
                "data": {
                    "docs": [{"_source": {"palo_alto_networks": {"action_pretty": "Detected"}}}]
                }
            }
        }
        self.assertEqual(stellar_notify_disposition_label(blocked_bundle), "已阻擋")
        self.assertEqual(stellar_notify_disposition_label(detect_bundle), "僅偵測")
        self.assertEqual(stellar_subject_detection_phrase(blocked_bundle), "已成功偵測並遏止")
        self.assertEqual(stellar_subject_detection_phrase(detect_bundle), "偵測到")

    def test_blocked_wins_over_earlier_detected(self) -> None:
        """Case 1220-style: Persistence Detected first, Malware Prevented later."""
        mixed = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Persistence",
                                    "action_pretty": "Detected",
                                    "case_id": None,
                                }
                            }
                        },
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Malware",
                                    "action_pretty": "Prevented (Blocked)",
                                    "case_id": 3363,
                                }
                            }
                        },
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Execution",
                                    "action_pretty": "Detected",
                                }
                            }
                        },
                    ]
                }
            }
        }
        from app.stellar.response_action import stellar_response_action_text

        self.assertEqual(stellar_response_action_text(mixed), "Prevented (Blocked)")
        self.assertEqual(stellar_notify_disposition_label(mixed), "已阻擋")
        self.assertEqual(stellar_subject_detection_phrase(mixed), "已成功偵測並遏止")


if __name__ == "__main__":
    unittest.main()
