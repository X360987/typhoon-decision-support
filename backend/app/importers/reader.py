"""读取上传的 CSV 或 Excel，并解析单元格。不改变上传模板。"""

import csv
import io
import re
from datetime import date, datetime

from openpyxl import load_workbook


def read_rows(content: bytes, suffix: str, max_rows: int, sheet_name=None) -> list[dict]:
    """读取 UTF-8 CSV 或 Excel；Excel 年份工作表自动携带目录年份。"""
    rows = []
    if sheet_name and suffix != ".xlsx":
        raise ValueError("人工停运长表须上传 .xlsx 工作簿")
    if suffix == ".csv":
        stream = io.StringIO(content.decode("utf-8-sig"), newline="")
        reader = csv.reader(stream)
        sources = [("", reader)]
        workbook = None
    elif suffix == ".xlsx":
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        if sheet_name and sheet_name not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f"缺少工作表 {sheet_name}")
        sheets = [workbook[sheet_name]] if sheet_name else workbook
        sources = [(s.title, s.iter_rows(values_only=True)) for s in sheets]
    else:
        raise ValueError("仅支持 .xlsx 和 UTF-8 编码 .csv")
    try:
        for sheet, source in sources:
            header = next(source, None)
            if not header:
                continue
            names = [str(x).strip() if x is not None else "" for x in header]
            if sheet_name and not {"日期", "车次"}.issubset(names):
                raise ValueError("人工长表缺少日期或车次列")
            if len([x for x in names if x]) != len({x for x in names if x}):
                raise ValueError(f"工作表 {sheet} 包含重复列名")
            for line, values in enumerate(source, 2):
                if all(v is None or str(v).strip() == "" for v in values):
                    continue
                row = {
                    k: (v.isoformat() if isinstance(v, (date, datetime)) else str(v).strip())
                    for k, v in zip(names, values)
                    if k and v is not None
                }
                if any(k.startswith("_") for k in row):
                    raise ValueError("列名不得以下划线开头")
                row.update(_row=line, _sheet=sheet)
                rows.append(row)
                if len(rows) > max_rows:
                    raise ValueError(f"最多允许 {max_rows} 条原始记录")
    finally:
        if workbook:
            workbook.close()
    return rows


def value(row, *keys, required=False):
    """兼容原模板与采集输出列名，不改变上传模板。"""
    result = next((str(row[k]).strip() for k in keys if row.get(k) not in (None, "")), None)
    if required and result is None:
        raise ValueError(f"缺少必填字段：{' / '.join(keys)}")
    return result


def identifier(raw):
    """平台标识拒绝科学计数法，防止将精度丢失值当作真实 ID。"""
    if not raw or len(raw) > 64 or not re.fullmatch(r"[0-9A-Za-z_-]+", raw):
        raise ValueError(f"无效 ID：{raw}；请将 Excel ID 列设为文本")
    return raw


def boolean(raw):
    """缺失表示未知，不等同于否。"""
    if raw is None:
        return None
    if raw.lower() in {"1", "true", "是", "权威", "政府"}:
        return True
    if raw.lower() in {"0", "false", "否", "非权威", "非政府"}:
        return False
    raise ValueError(f"无法识别布尔标注：{raw}")


def number(raw):
    """只接收明确的非负整数，不估算含万等单位的显示值。"""
    if raw is None:
        return None
    if not re.fullmatch(r"\d+", raw):
        raise ValueError(f"计数必须为非负整数：{raw}")
    result = int(raw)
    if result > 2147483647:
        raise ValueError("计数超出本版整数存储范围")
    return result
