# 导入模板与旧接口说明

现场铁路口径是 `rail_manual`：只读工作簿里的 `ID_type长表`，经 `/import/precheck` 与 `/import/commit` 入库。人工长表不补站名。

新版 HTTP 导入使用 `/import/precheck` 与 `/import/commit`。下面保留各类文件的字段规则。第 5 节是早期按台风编号的导入接口，仍然可用。

### 年度列车目录

通过 `POST /api/v1/imports/preview` 上传 `kind=trains`。现有 `2018-2024铁路列车车次表.xlsx` 可直接读取，年份取工作表名，列名为 `车次、ID、type`；`type` 无业务意义，不入列车分类。CSV 需传 `catalog_year` 或包含 `年份` 列。

### 微博

上传 `kind=weibo` 并选择 `typhoon_id`。必要字段：`id`（兼容 `mid`）、`user_id`、`微博正文`（`text`）、`发布时间`（`created_at`，完整 ISO 日期时间）。无时区时按北京时间处理。

兼容原中文模板和采集输出：昵称对应 `screen_name`，互动数对应 `reposts_count/comments_count/attitudes_count`，认证类型对应 `verified_type`，IP 属地对应 `profile_ip_location`。其他字段原值保存在 `details/profile` 和原文件中。

- `阶段` 支持灾前、灾中、灾后或空。原文件的准备阶段、响应阶段、恢复阶段依次映射为灾前、灾中、灾后；原始标签保存在微博详情中。
- 正文缺失或仅有空白字符的行拒绝入库。发布时间也支持北京时间的 `2023/7/25 9:05` 格式。
- 微博数字 ID 显示为科学计数法时，从同一行的 bid 解码，并与原值按其显示精度核对；缺少有效 bid 或核对失败会报错。
- 热度仅保存上传值，不重算，不验证与互动数之和是否一致。
- 互动数缺失留空并提醒，不能用零替代。
- `艾特用户/话题/微博图片url` 接受 JSON 数组，或分号分隔值；不按逗号拆分 URL。
- `是否权威`/`is_authoritative` 和 `是否政府`/`is_government` 可为是/否、true/false、1/0。缺失为未知，绝不根据名称或未确认的认证编码推断。
- Excel ID 列请使用文本格式，已经由 Excel 截断精度的 ID 无法还原。

账号敏感变化在预览的 `warnings` 中带有 `decision_token`。提交体可逐项选择：

```json
{"decisions": {"预览返回的令牌": true}}
```

未提供或为 false 时保留账号旧认证/权威值，微博及该次来源身份仍可导入。令牌绑定旧值与新值；预览后状态改变时旧令牌不会批准另一项变化。历史 `event_posts` 身份快照不随账号当前资料更新。重复微博内容允许更新并审计；同一微博 ID 对应不同发布账号报错。

### 铁路停运

先完成车次目录及来源微博导入，再上传 `kind=rail` 与 `typhoon_id`。

必填：`标准车次`、`停运日期`、`停运范围`（全程/全程停运）、`公告微博ID`。可选：`始发站`（兼容区段起点）、`终到站`（兼容区段终点）、`列车数据库ID` 及原有追溯字段。

日期为始发日期，匹配该年度车次。原表 ID 若提供必须匹配目录。**原图中的“公告微博ID/公告链接”组合列仅在单元格是微博 ID 时可用；链接不能冒充 ID。**建议实际明细拆成独立列，链接由微博内容保存。

- G2690/87 拆成 G2690、G2687，各自参与目录匹配，按两条统计；一条失败不影响另一条。
- 同一台风、始发日期、标准车次为同一停运对象。重复保留首条及首个有效来源，不补齐空字段。
- 同批非空始发站/终到站/原列车 ID 相互矛盾时整组拒绝。可修改异常值重新上传；旧批次提交幂等，不会重试错误行。
- 与已有停运记录冲突不覆盖。缺来源微博、缺年度车次或 ID 不符均跳过并返回错误。
- 缺站名允许入库统计。所有原列（证据原文、置信度、匹配方式等）保存在 `evidence`，待最终明细稳定后再细化类型列。

### 站点坐标

可选 `kind=stations`，列为 `站名、经度、纬度、坐标系`；目前坐标系仅接受 WGS84，需在来源端先转换。相同站名不同坐标报错，不自动替换。缺坐标不产生虚构点位。

## 5. 调用步骤与接口

在 `/docs` 展开预览接口，选文件、kind 和事件，执行后保存 `batch_id`。检查错误与提醒后调用 `/imports/{batch_id}/commit`，无身份确认时 body 为 `{}`。提交后可查询结果、下载错误 CSV。文件需修改时创建新批次。

所有接口以 `/api/v1` 开头：

| 方法与路径 | 功能 |
|---|---|
| POST `/imports/preview` | 校验与试写预览；业务记录回滚 |
| POST `/imports/{id}/commit` | 重新校验并提交，重复请求返回原结果 |
| GET `/imports/{id}` | 批次状态及错误 |
| GET `/imports/{id}/errors` | Excel 可打开的错误 CSV |
| GET `/typhoons` | 已核对目录与数据可用性 |
| GET `/typhoons/{id}/filters` | 有记录的日期、阶段及范围 |
| GET `/typhoons/{id}/overview` | 微博、主体、停运概览 |
| GET `/typhoons/{id}/social/statistics` | 发文趋势及已有热度汇总 |
| GET `/typhoons/{id}/rail/statistics` | 车次日、起终点分布、定位覆盖 |
| GET `/typhoons/{id}/rail/map` | 站点及按方向合并的示意线 |
| GET `/typhoons/{id}/social/analysis` | 尚未接入状态 |

统计日期参数 `start_date/end_date` 含首尾，不传为全部；两者相同为单日。微博按北京时间发布时间，铁路按始发日期。`stage` 只过滤微博，overview 明确返回 `stage_applies_to=weibo_only`。铁路单位为车次日，同车次两天算两条。客户端可按日切换查询，不需要独立后端播放任务。

数据状态包括 `not_imported`、`no_records_in_selection`、`available`；`coverage=not_verified` 表示尚无“数据覆盖完整”的证据。未生成分析返回 null，不伪装为零。地图 `geometry_kind=schematic`，不代表真实线路；返回总数、可定位数和未定位数。
