import re


KSA_MOBILE_PATTERN = re.compile(
    r"^(?:\+966|00966|966)?(\s*0?5\d{8})$"
)


def normalize_ksa_phone(raw: str) -> tuple[str, str]:
    """
    Normalize a KSA mobile phone number.
    Returns (e164, digits) or raises ValueError.

    e164:   +9665xxxxxxxx
    digits: 9665xxxxxxxx  (used for CAPI hashing)
    """
    cleaned = re.sub(r"[\s\-\(\)]", "", raw.strip())

    # Accepted formats:
    # 05xxxxxxxx, 5xxxxxxxx, 9665xxxxxxxx, +9665xxxxxxxx, 009665xxxxxxxx
    patterns = [
        r"^\+9665(\d{8})$",
        r"^009665(\d{8})$",
        r"^9665(\d{8})$",
        r"^05(\d{8})$",
        r"^5(\d{8})$",
    ]

    local_8 = None
    for pattern in patterns:
        m = re.match(pattern, cleaned)
        if m:
            local_8 = m.group(1)
            break

    if local_8 is None:
        raise ValueError(
            "رقم الجوال يجب أن يكون رقماً سعودياً صحيحاً يبدأ بـ 05"
        )

    digits = f"9665{local_8}"
    e164 = f"+{digits}"
    return e164, digits
