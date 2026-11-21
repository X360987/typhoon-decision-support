"""态度与异常结果。

两个查询现在都返回 not_integrated。空列表表示算法还没接入，不是“没有态度”或“没有异常”。
与算法方确定分析对象和标签之后：

- 用新迁移按微博 ID 保存一条结果，至少包含标签、规则或模型版本、写入批次。
- 汇总只写在本模块，按北京时间日期和灾害阶段计算条数、占比、已分析条数 / 微博条数。
- 路由路径保持不变，把 status 改为 available，并带上覆盖量。

约定未定之前不要写入占位标签，也不要在路由里另做一套汇总。
"""

NOT_INTEGRATED = "not_integrated"


def legacy_status():
    return {"status": NOT_INTEGRATED, "data": None, "message": "等待算法输入输出约定"}


def results_payload(context):
    return {
        "context": context,
        "status": NOT_INTEGRATED,
        "items": [],
        "message": "情感、紧急程度及耦合结果等待算法方提供，不运行旧演示算法",
    }


def anomalies_payload(context, page, page_size):
    return {
        "context": context,
        "status": NOT_INTEGRATED,
        "total": 0,
        "page": page,
        "page_size": page_size,
        "counts": {"single": 0, "pair": 0, "joint": 0, "unique_groups": 0},
        "pending_window": 0,
        "items": [],
        "message": "等待算法结果；空列表不表示没有异常",
    }
