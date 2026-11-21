"""导出单元格。以公式字符开头时加前缀，避免 Excel 执行。"""


def excel_safe(value):
    if str(value).startswith(("=", "+", "-", "@")):
        return "'" + str(value)
    return value
