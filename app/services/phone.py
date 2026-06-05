import re


def normalize_ma_phone(raw: str) -> tuple[str, str]:
    """
    Normalize a Morocco mobile phone number.
    Returns (e164, digits) or raises ValueError.

    e164:   +2126xxxxxxxx or +2127xxxxxxxx
    digits: 2126xxxxxxxx (used for CAPI hashing)
    """
    cleaned = re.sub(r"[\s\-\(\)]", "", raw.strip())

    patterns = [
        r"^\+212([67])(\d{8})$",
        r"^00212([67])(\d{8})$",
        r"^212([67])(\d{8})$",
        r"^0([67])(\d{8})$",
        r"^([67])(\d{8})$",
    ]

    prefix = None
    local_8 = None
    for pattern in patterns:
        m = re.match(pattern, cleaned)
        if m:
            prefix = m.group(1)
            local_8 = m.group(2)
            break

    if local_8 is None or prefix is None:
        raise ValueError(
            "رقم الجوال يجب أن يكون رقماً مغربياً صحيحاً يبدأ بـ 06 أو 07"
        )

    digits = f"212{prefix}{local_8}"
    e164 = f"+{digits}"
    return e164, digits


# Backward-compatible alias for imports
normalize_ksa_phone = normalize_ma_phone
