"""北京时间。观测时间对外不带时区；系统操作时间用 UTC。"""

from datetime import UTC
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def as_beijing(value):
    """缺少时区时按北京时间理解，不改成 UTC。"""
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def format_beijing(value):
    """对外的观测与事件边界：北京时间，不带时区后缀。"""
    if not value:
        return None
    return as_beijing(value).replace(tzinfo=None).isoformat(timespec="seconds")


def format_utc(value):
    """系统操作时间统一为带 Z 的 UTC。"""
    if not value:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
