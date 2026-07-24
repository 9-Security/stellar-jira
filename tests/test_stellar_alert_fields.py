"""Tests for Stellar alert field extraction."""

from __future__ import annotations

import unittest

from app.stellar.alert_fields import stellar_primary_file_path


class TestStellarAlertFields(unittest.TestCase):
    def test_xdr_process_list_and_events(self) -> None:
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "process_list": [
                                    {
                                        "parent": {
                                            "executable": "C:\\Windows\\System32\\runonce.exe",
                                            "name": "runonce.exe",
                                        }
                                    }
                                ]
                            }
                        },
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Malware",
                                    "name": "WildFire Malware",
                                    "events": [
                                        {
                                            "actor_process_image_path": (
                                                "C:\\Program Files (x86)\\Windows MailX\\mailx.exe"
                                            )
                                        }
                                    ],
                                },
                                "process_list": [
                                    {
                                        "parent": {
                                            "executable": "C:\\Program Files (x86)\\Windows MailX\\mailx.exe",
                                        }
                                    }
                                ],
                            }
                        },
                    ]
                }
            }
        }
        self.assertEqual(
            stellar_primary_file_path(bundle),
            "C:\\Program Files (x86)\\Windows MailX\\mailx.exe",
        )

    def test_deprioritizes_system32_explorer_over_userland(self) -> None:
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "process_list": [
                                    {"parent": {"executable": "C:\\Windows\\explorer.exe"}},
                                ]
                            }
                        },
                        {
                            "_source": {
                                "process_list": [
                                    {
                                        "parent": {
                                            "executable": (
                                                "C:\\Users\\Gary Kuei\\Downloads\\"
                                                "YuantaCAPIServiSignAdapterSetup (2).exe"
                                            )
                                        }
                                    }
                                ]
                            }
                        },
                    ]
                }
            }
        }
        self.assertEqual(
            stellar_primary_file_path(bundle),
            "C:\\Users\\Gary Kuei\\Downloads\\YuantaCAPIServiSignAdapterSetup (2).exe",
        )


if __name__ == "__main__":
    unittest.main()
