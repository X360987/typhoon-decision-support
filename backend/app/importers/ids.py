"""微博 ID、车次拆分和审计快照。"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.importers.reader import identifier, value


def weibo_id(row):
    raw = value(row, "id", "mid", required=True)
    if not re.fullmatch(r"\d+(?:\.\d+)?[eE]\+?\d{1,2}", raw):
        return identifier(raw)
    bid = value(row, "bid", required=True)
    if not re.fullmatch(r"[0-9A-Za-z]{1,12}", bid):
        raise ValueError("科学计数法微博 ID 需要有效的 bid")
    chunks = []
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for end in range(len(bid), 0, -4):
        chunk = 0
        for char in bid[max(0, end - 4) : end]:
            chunk = chunk * 62 + alphabet.index(char)
        if chunk >= 10_000_000:
            raise ValueError("bid 分段超出微博 ID 范围")
        chunks.append(str(chunk).zfill(7) if end > 4 else str(chunk))
    mid = "".join(reversed(chunks))
    rounded = Decimal(raw)
    try:
        matches = Decimal(mid).quantize(rounded) == rounded
    except InvalidOperation:
        matches = False
    if not matches:
        raise ValueError("bid 与原微博 ID 不一致")
    return mid


def split_train(raw):
    """G2690/87 -> G2690、G2687；显式完整车次也可以独立匹配。"""
    parts = raw.upper().replace("／", "/").split("/")
    first = parts[0].strip()
    if not re.fullmatch(r"[A-Z]?\d{1,5}", first):
        raise ValueError(f"无效车次：{raw}")
    result = [first]
    for part in parts[1:]:
        part = part.strip()
        if re.fullmatch(r"[A-Z]\d{1,5}", part):
            result.append(part)
        elif part.isdigit():
            match = re.fullmatch(r"([A-Z]?)(\d+)", first)
            digits = match[2]
            if len(part) > len(digits):
                raise ValueError(f"无法补全车次：{raw}")
            result.append(match[1] + digits[: len(digits) - len(part)] + part)
        else:
            raise ValueError(f"无法拆分车次：{raw}")
    return result


def snapshot(obj):
    """把模型值转换为可保存的审计 JSON。"""
    return {
        c.name: (v.isoformat() if isinstance(v, (date, datetime)) else v)
        for c in obj.__table__.columns
        if (v := getattr(obj, c.name)) is not None
    }
