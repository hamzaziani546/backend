"""Unit tests for Morocco phone normalization."""
import pytest
from app.services.phone import normalize_ma_phone


@pytest.mark.parametrize(
    "raw,expected_e164,expected_digits",
    [
        ("0612345678", "+212612345678", "212612345678"),
        ("612345678", "+212612345678", "212612345678"),
        ("212612345678", "+212612345678", "212612345678"),
        ("+212612345678", "+212612345678", "212612345678"),
        ("00212612345678", "+212612345678", "212612345678"),
        ("0712345678", "+212712345678", "212712345678"),
        (" +212 6 12 34 56 78 ", "+212612345678", "212612345678"),
    ],
)
def test_valid_phones(raw, expected_e164, expected_digits):
    e164, digits = normalize_ma_phone(raw)
    assert e164 == expected_e164
    assert digits == expected_digits


@pytest.mark.parametrize(
    "raw",
    [
        "123",
        "06",
        "+966512345678",
        "0512345678",
        "+1 800 555 1234",
        "",
    ],
)
def test_invalid_phones(raw):
    with pytest.raises(ValueError):
        normalize_ma_phone(raw)
