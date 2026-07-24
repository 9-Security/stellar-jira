from app.stellar.severity_filter import (
    case_severity_allowed,
    is_severity_escalation,
    normalize_stellar_severity,
    parse_allowed_severities,
    severity_rank,
)


def test_normalize_stellar_severity() -> None:
    assert normalize_stellar_severity("high") == "High"
    assert normalize_stellar_severity("CRITICAL") == "Critical"


def test_parse_allowed_severities() -> None:
    assert parse_allowed_severities("Critical, High") == frozenset({"Critical", "High"})
    assert parse_allowed_severities("*") is None
    assert parse_allowed_severities("") is None


def test_case_severity_allowed() -> None:
    allowed = frozenset({"Critical", "High"})
    assert case_severity_allowed({"severity": "High"}, allowed)
    assert not case_severity_allowed({"severity": "Low"}, allowed)
    assert case_severity_allowed({"severity": "Low"}, None)


def test_severity_rank_and_escalation() -> None:
    assert severity_rank("Low") < severity_rank("Medium")
    assert severity_rank("Medium") < severity_rank("High")
    assert severity_rank("High") < severity_rank("Critical")
    assert is_severity_escalation("Low", "High")
    assert is_severity_escalation("Medium", "Critical")
    assert not is_severity_escalation("High", "High")
    assert not is_severity_escalation("High", "Low")
    assert not is_severity_escalation("", "High")
