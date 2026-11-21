"""原文件微博导入。

已支持微博 ID（含科学计数法与 bid 核对）、发布时间、准备／响应／恢复阶段映射，并拒绝空正文。
整份约 60,333 条尚未做导入验收；正文为空的行在这里拒绝。不要为了对账放宽这条规则。
「是否政府」只采用文件中的明确字段，不根据微博官方认证推断。
"""

import hashlib
import json
from datetime import datetime

from app.importers.ids import snapshot, weibo_id
from app.importers.reader import boolean, identifier, number, value
from app.models import Account, Audit, EventPost, Weibo
from app.timeutil import TZ

STAGE_ALIASES = {"准备阶段": "灾前", "响应阶段": "灾中", "恢复阶段": "灾后"}


class WeiboImporter:
    def weibo(self, row):
        mid = weibo_id(row)
        uid = identifier(value(row, "user_id", required=True))
        text = value(row, "微博正文", "text", required=True)
        raw_time = value(row, "发布时间", "created_at", required=True)
        if "/" in raw_time:
            timestamp = datetime.strptime(raw_time, "%Y/%m/%d %H:%M")
        else:
            timestamp = datetime.fromisoformat(raw_time)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=TZ)
        stage = value(row, "阶段", "stage")
        stage = STAGE_ALIASES.get(stage, stage)
        if stage not in {None, "灾前", "灾中", "灾后"}:
            raise ValueError("阶段只能为灾前、灾中、灾后或空")
        verified = value(row, "认证类型", "verified_type")
        authority = boolean(value(row, "是否权威", "是否权威来源", "is_authoritative"))
        government = boolean(value(row, "是否政府", "is_government"))
        counts = {
            k: number(value(row, *aliases))
            for k, aliases in {
                "reposts": ("转发数", "reposts_count"),
                "comments": ("评论数", "comments_count"),
                "likes": ("点赞数", "attitudes_count"),
                "heat": ("发文热度", "heat"),
            }.items()
        }
        for field in ("reposts", "comments", "likes"):
            if counts[field] is None:
                self.issue(row, f"{field} 缺失，保留为空", warning=True)
        details = {k: v for k, v in row.items() if not k.startswith("_")}
        for field, alias in [
            ("艾特用户", "mentions"),
            ("话题", "topics"),
            ("微博图片url", "pic_urls"),
        ]:
            raw = value(row, field, alias)
            if raw:
                arr = (
                    json.loads(raw)
                    if raw.startswith("[")
                    else [x.strip() for x in raw.split(";") if x.strip()]
                )
                if not isinstance(arr, list):
                    raise ValueError(f"{field} 必须为数组")
                details[field] = arr
        account = self.db.get(Account, uid)
        old_post = self.db.get(Weibo, mid)
        if old_post and old_post.user_id != uid:
            raise ValueError("同一微博 ID 的发布账号冲突")
        new = {
            "nickname": value(row, "用户昵称", "screen_name"),
            "verified_type": verified,
            "is_authoritative": authority,
            "is_government": government,
            "profile": {
                k: row[k]
                for k in (
                    "用户认证等级",
                    "会员类型",
                    "会员等级",
                    "source_category",
                    "account_check",
                    "account_check_reason",
                )
                if k in row
            },
        }
        if account is None:
            account = Account(user_id=uid, **new)
            self.db.add(account)
            self.db.flush()
        else:
            before = snapshot(account)
            for field in ("verified_type", "is_authoritative"):
                previous, incoming = getattr(account, field), new[field]
                if previous != incoming:
                    token = hashlib.sha256(
                        json.dumps([uid, field, previous, incoming], ensure_ascii=False).encode()
                    ).hexdigest()
                    self.issue(
                        row,
                        "账号敏感属性变化，未明确同意则保留当前资料",
                        warning=True,
                        user_id=uid,
                        field=field,
                        old=previous,
                        new=incoming,
                        decision_token=token,
                    )
                    if self.decisions.get(token) is not True:
                        new[field] = previous
                        if field == "verified_type":
                            new["is_government"] = account.is_government
            for k, v in new.items():
                setattr(account, k, v)
            if before != snapshot(account):
                self.db.add(
                    Audit(
                        entity="account",
                        entity_id=uid,
                        batch_id=self.batch.id,
                        before=before,
                        after=snapshot(account),
                    )
                )
        post_data = dict(
            user_id=uid,
            text=text,
            published_at=timestamp,
            **counts,
            ip_region=value(row, "ip", "profile_ip_location", "ip_region"),
            source_url=value(row, "公告链接", "status_url"),
            details=details,
        )
        if old_post:
            before = snapshot(old_post)
            for k, v in post_data.items():
                setattr(old_post, k, v)
            self.db.add(
                Audit(
                    entity="weibo",
                    entity_id=mid,
                    batch_id=self.batch.id,
                    before=before,
                    after=snapshot(old_post),
                )
            )
            self.report["updated"] += 1
        else:
            self.db.add(Weibo(id=mid, **post_data))
            self.report["inserted"] += 1
        self.db.flush()
        key = (self.batch.typhoon_id, mid)
        event_post = self.db.get(EventPost, key)
        if event_post is not None and event_post.stage is None:
            event_post.stage = stage
        if event_post is None:
            self.db.add(
                EventPost(
                    typhoon_id=key[0],
                    weibo_id=mid,
                    stage=stage,
                    verified_type=verified,
                    is_authoritative=authority,
                    is_government=government,
                    batch_id=self.batch.id,
                )
            )
