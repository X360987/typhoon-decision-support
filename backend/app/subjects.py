"""政务属性统计。

只统计导入时明确填写的「是否政府」。缺失是未知，不是非政府。
微博官方认证不能区分政务、社会组织与公众。若演示需要三类比较，
先把可核验分类写入账号资料，再在本模块增加计数；不要按昵称或认证编码推断。

概览接口缺数记 0。指标接口在没有任何明确标注时返回 null，避免把未知显示成零条政务微博。
"""


def _tally(posts):
    government = non_government = unknown = 0
    for _, event in posts:
        if event.is_government is True:
            government += 1
        elif event.is_government is False:
            non_government += 1
        else:
            unknown += 1
    return government, non_government, unknown


def overview_counts(posts):
    government, non_government, unknown = _tally(posts)
    return {
        "government": government,
        "non_government": non_government,
        "unknown_government": unknown,
    }


def metric_counts(posts):
    government, non_government, unknown = _tally(posts)
    classified = government + non_government > 0
    return {
        "weibo_count": len(posts) if posts else None,
        "government_weibo_count": government if classified else None,
        "non_government_weibo_count": non_government if classified else None,
        "unclassified_weibo_count": unknown if posts else None,
    }
