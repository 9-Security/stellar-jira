"""Sample Stellar case/bundle for notify-test (matches Jira description format)."""

from __future__ import annotations

from typing import Any

SAMPLE_STELLAR_CASE_ID = "abcdef0123456789abcdef01"
SAMPLE_MIDDLEWARE_CASE_ID = "XSOC-JJNET-260707-001"
SAMPLE_JIRA_KEY = "AIXSOC-TEST"


def sample_stellar_notify_case() -> dict[str, Any]:
    return {
        "_id": SAMPLE_STELLAR_CASE_ID,
        "ticket_id": 1123,
        "name": "LOLBIN process executed with a high integrity level",
        "status": "New",
        "severity": "High",
        "created_at": 1780000000000,
        "modified_at": 1780001000000,
        "assignee_name": "Unassigned",
        "tenant_name": "JJNET",
    }


def sample_stellar_notify_bundle() -> dict[str, Any]:
    return {
        "case_id": SAMPLE_STELLAR_CASE_ID,
        "observables": {
            "observables": {
                "host": [
                    {"hostname": "Gary-Kuei", "ip": "192.168.0.98"},
                    {"hostname": "Gary-Kuei", "ip": "192.168.233.222"},
                ],
                "user": [
                    {"username": r"GARY-KUEI\Gary Kuei"},
                    {"username": r"NT AUTHORITY\SYSTEM"},
                    {"username": r"GARY-KUEI\Gary Kuei"},
                ],
                "file": [
                    {
                        "file_name": (
                            r"C:\Users\Gary Kuei\AppData\Roaming\Microsoft\SystemCertificates"
                            r"\Request\Certificates\AAEA9F96"
                        )
                    }
                ],
            }
        },
        "alerts": {
            "data": {
                "docs": [
                    {
                        "_source": {
                            "process_list": [
                                {"parent": {"executable": r"C:\Windows\explorer.exe"}},
                            ]
                        }
                    },
                    {
                        "_source": {
                            "palo_alto_networks": {"action_pretty": "Prevented (Blocked)"},
                            "process_list": [
                                {
                                    "parent": {
                                        "executable": (
                                            "C:\\Users\\Gary Kuei\\Downloads\\"
                                            "YuantaCAPIServiSignAdapterSetup (2).exe"
                                        )
                                    }
                                }
                            ],
                        }
                    },
                ]
            }
        },
        "summary": {"data": {"tactics": ["Privilege Escalation"]}},
    }


def sample_stellar_notify_kwargs(*, jira_key: str | None = None) -> dict[str, Any]:
    case = sample_stellar_notify_case()
    bundle = sample_stellar_notify_bundle()
    event_name = str(case.get("name") or "")
    return {
        "jira_key": jira_key or SAMPLE_JIRA_KEY,
        "case_id": SAMPLE_MIDDLEWARE_CASE_ID,
        "summary": f"[High][{event_name[:80]}][JJNET]",
        "customer_code": "JJNET",
        "source_id": "test",
        "external_id": SAMPLE_STELLAR_CASE_ID,
        "severity": "High",
        "event_name": event_name,
        "platform": "stellar",
        "stellar_case": case,
        "stellar_bundle": bundle,
    }
