import hashlib


def sha256_hex(value: str) -> str:
    """Return lowercase SHA-256 hex digest of a string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_phone(phone_digits: str) -> str:
    """Hash the phone digits (e.g. 9665xxxxxxxx) for CAPI."""
    return sha256_hex(phone_digits.strip().lower())


def hash_external_id(value: str) -> str:
    """Hash an external identifier (e.g. order number) for CAPI."""
    return sha256_hex(value.strip().lower())
