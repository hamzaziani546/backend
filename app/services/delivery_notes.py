import re
from typing import Optional


def parse_city_address(admin_notes: Optional[str]) -> tuple[str, str]:
    """Extract city and address from order admin_notes (المدينة / العنوان lines)."""
    if not admin_notes:
        return "", ""
    city_match = re.search(r"المدينة:\s*(.+)", admin_notes)
    addr_match = re.search(r"العنوان:\s*(.+)", admin_notes)
    city = city_match.group(1).strip() if city_match else ""
    address = addr_match.group(1).strip() if addr_match else ""
    return city, address
