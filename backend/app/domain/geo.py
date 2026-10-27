"""Province attribution helpers."""

from __future__ import annotations

PROVINCE_ALIASES: dict[str, str] = {
    "福建": "FJ",
    "福建省": "FJ",
    "广东": "GD",
    "广东省": "GD",
    "浙江": "ZJ",
    "浙江省": "ZJ",
    "江苏": "JS",
    "江苏省": "JS",
    "上海": "SH",
    "上海市": "SH",
    "台湾": "TW",
    "台湾省": "TW",
    "FJ": "FJ",
    "GD": "GD",
    "ZJ": "ZJ",
    "JS": "JS",
    "SH": "SH",
    "TW": "TW",
}

# Simplified IP -> province for demo seed only
IP_PROVINCE: dict[str, str] = {
    "1.1.1.": "FJ",
    "2.2.2.": "GD",
    "3.3.3.": "ZJ",
    "4.4.4.": "JS",
    "5.5.5.": "SH",
    "6.6.6.": "TW",
}


def normalize_province(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip()
    if t in PROVINCE_ALIASES:
        return PROVINCE_ALIASES[t]
    for name, code in PROVINCE_ALIASES.items():
        if name in t:
            return code
    return None


def extract_provinces_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for name, code in PROVINCE_ALIASES.items():
        if len(name) >= 2 and name in text and code not in found:
            found.append(code)
    return found


def province_from_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    for prefix, code in IP_PROVINCE.items():
        if ip.startswith(prefix):
            return code
    return None


def attribute_provinces(
    content: str | None,
    publish_location: str | None,
    ip: str | None,
) -> list[tuple[str, str]]:
    """Return list of (province_code, method). Unknown is not forced."""
    from_text = extract_provinces_from_text(content)
    if from_text:
        return [(c, "content_place") for c in from_text]
    loc = normalize_province(publish_location)
    if loc:
        return [(loc, "publish_location")]
    ip_p = province_from_ip(ip)
    if ip_p:
        return [(ip_p, "ip")]
    return []
