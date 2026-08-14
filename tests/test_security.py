from app.utils.security import parse_user_ids, redact_direct_identifiers, short_hash


def test_redact_direct_identifiers():
    text = "請寄到 parent@example.com，電話 0912-345-678，身分證 A123456789"
    result = redact_direct_identifiers(text)
    assert "parent@example.com" not in result
    assert "0912-345-678" not in result
    assert "A123456789" not in result
    assert "[EMAIL_REDACTED]" in result
    assert "[PHONE_REDACTED]" in result
    assert "[NATIONAL_ID_REDACTED]" in result


def test_parse_user_ids_removes_empty_items():
    assert parse_user_ids(" U_a, ,U_b ,, ") == {"U_a", "U_b"}


def test_short_hash_does_not_return_source_value():
    assert short_hash("U_sensitive") != "U_sensitive"
    assert len(short_hash("U_sensitive")) == 12
