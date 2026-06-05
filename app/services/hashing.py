import hashlib


def sha256_hex(value: str) -> str:
    """Return lowercase SHA-256 hex digest of a string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_phone(phone_digits: str) -> str:
    """
    Hash a phone number for CAPI.
    Input must be E.164 digits without '+', e.g. 9665XXXXXXXX.
    Normalization: strip whitespace, no country-code leading zeros,
    no non-numeric chars — all handled before this call.
    """
    return sha256_hex(phone_digits.strip())


def hash_email(email: str) -> str:
    """Hash an email address for CAPI (lowercase, trimmed)."""
    return sha256_hex(email.strip().lower())


def hash_external_id(value: str) -> str:
    """Hash an external identifier (e.g. order number) for CAPI."""
    return sha256_hex(value.strip().lower())
