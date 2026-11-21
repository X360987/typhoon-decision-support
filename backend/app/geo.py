"""始发站与终到站。

人工长表只有日期和车次，两端目前为空，统计和地图都算未定位。
下一步只改 `endpoints`：用适用于 2023 年的车次起终站对照补站名，坐标仍查 `stations` 表的 WGS84。
不要在导入人工长表时猜测站名，也不要在各个接口里各写一遍对照。

对照接入后，在 `app.api.impact` 按日期补充各站始发数、终到数和未定位数。
有站名但没有坐标的记录仍然算未定位，不生成示意线。
"""

from collections import Counter


def endpoints(record):
    """返回 (始发站, 终到站)。缺名为 None。"""
    return record.origin, record.destination


def count_endpoints(records):
    """只统计已经有站名的一端。人工长表目前得到两个空字典。"""
    origins, destinations = Counter(), Counter()
    for record in records:
        origin, destination = endpoints(record)
        if origin:
            origins[origin] += 1
        if destination:
            destinations[destination] += 1
    return dict(origins), dict(destinations)
