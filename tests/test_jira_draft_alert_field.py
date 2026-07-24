"""Jira create payload: optional alert name custom field."""

from __future__ import annotations

import unittest

from app.stellar.jira_draft import build_jira_issue_fields


class TestJiraDraftAlertField(unittest.TestCase):
    def test_omits_alert_field_when_disabled(self) -> None:
        case = {
            "_id": "abc123",
            "name": "Test alert name",
            "severity": "High",
            "status": "New",
        }
        fields = build_jira_issue_fields(
            project_key="AIXSOC",
            issue_type_id="10092",
            alert_name_field_id=None,
            customer_code="JJNET",
            middleware_case_id="XSOC-JJNET-260707-001",
            case=case,
            bundle={},
        )
        self.assertNotIn("customfield_10122", fields)
        self.assertIn("Test alert name", str(fields.get("summary")))

    def test_adds_tenant_labels(self) -> None:
        fields = build_jira_issue_fields(
            project_key="AIXSOC",
            issue_type_id="10092",
            customer_code="JJ",
            tenant_source_id="JJNET EDR",
            tenant_name="JJNET-EDR",
            tenant_id="tenant-id",
            tenant_labels=["customer-managed"],
            case={"_id": "abc123", "name": "Test", "severity": "High"},
            bundle={},
        )
        self.assertIn("tenant-jjnet-edr", fields["labels"])
        self.assertIn("customer-managed", fields["labels"])
        self.assertIn("JJNET-EDR", str(fields["description"]))


if __name__ == "__main__":
    unittest.main()
