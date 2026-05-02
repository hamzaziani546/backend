"""Unit tests for KSA phone normalization."""
import pytest
from app.services.phone import normalize_ksa_phone


@pytest.mark.parametrize(
    "raw,expected_e164,expected_digits",
    [
        ("0512345678", "+966512345678", "966512345678"),
        ("512345678", "+966512345678", "966512345678"),
        ("966512345678", "+966512345678", "966512345678"),
        ("+966512345678", "+966512345678", "966512345678"),
        ("00966512345678", "+966512345678", "966512345678"),
        (" +966 51 234 5678 ", "+966512345678", "966512345678"),
    ],
)
def test_valid_phones(raw, expected_e164, expected_digits):
    e164, digits = normalize_ksa_phone(raw)
    assert e164 == expected_e164
    assert digits == expected_digits


@pytest.mark.parametrize(
    "raw",
    [
        "123",
        "055",
        "+9715xxxxxxxx",
        "0412345678",
        "021234567",
        "+1 800 555 1234",
        "",
    ],
)
def test_invalid_phones(raw):
    with pytest.raises(ValueError):
        normalize_ksa_phone(raw)
