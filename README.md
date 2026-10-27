# 台风灾害社会—组织—物理异常分析与决策支持平台

前后端分离工程，位于 `code/`。用可复现的模拟数据跑通端到端流程；真实 CSV/XLSX 走同一套预检、凭证与版本化分析链路。`demo` 与 `real` 两种数据模式由服务端配置和数据集记录决定，互不串用；真实模式无数据时保持空态，不回退模拟结果。

平台功能包括观测、异常提示与核验辅助。

## 当前完成情况（2026-10-26 代码核查）

**当前交付是具备完整演示主流程的研究原型，尚不是已通过真实灾害数据验证的生产系统。** 页面、接口、规则计算、证据核验和版本化分析已有实现；真实多源数据闭环、真实模型效果及部署验收尚未完成。不能用页面数量或模拟测试通过率推算整体完成百分比。

本次核查以 `backend/app/`、`frontend/src/`、配置、迁移和现有测试为依据。


| 模块         | 已完成内容                                                          | 实现位置与完成边界                                                                                          |
| ---------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 工程与数据模型    | FastAPI API、SQLAlchemy 模型、Alembic 001/002、Vue 页面与路由、Compose 配置 | `backend/app/models.py`、`backend/alembic/`、`frontend/src/router/index.ts`；容器配置存在不等于部署验收完成          |
| 页面与上下文     | 总览、影响与行动、回放、四维度分析入口、预测、证据、数据管理与资料页；事件/省份/时刻共享、旧请求取消与迟到响应保护     | `frontend/src/views/`、`stores/context.ts`、`composables/useLoader.ts`                               |
| 数据模式与基本写权限 | demo/real 数据集隔离、real 空态、禁止真实模式 seed、API Key 写权限、操作者字段          | `backend/app/api/deps.py`、`services/bootstrap.py`；未实现独立用户登录与角色权限                                   |
| 微博文件导入     | CSV/XLSX 字段映射、逐行预检、签名凭证、严格/跳过错误策略、批次与错误行、重复提交复用                | `backend/app/services/import_service.py`；仅 `weibo` 有提交链路，其他来源未接入                                   |
| 清洗与省小时统计   | 账号分类、情绪与求助规则、地域归属、个人/官方/未知区分、缺测处理、全国去重口径                       | `backend/app/services/pipeline.py`、`domain/`；情绪和地域识别仍有演示实现限制                                       |
| 异常分析       | 社会、组织、物理单维异常，两两关系与三维联合异常，阈值/基线、证据及候选建议                         | `backend/app/domain/anomaly_rules.py`、`config/rules.yaml`；规则可运行，业务阈值未校准                            |
| 停运影响映射     | 按运行日期和时刻表版本映射区段，处理跨午夜、跨省去重，未知端点进入待核验                           | `backend/app/domain/train_mapping.py`；计算逻辑已有，真实公告/时刻表导入与复运数据尚缺                                     |
| 严格回放与分析版本  | 按 `available_at` 截断、滞后窗口待确认；成功后切换生效版本，失败保留旧结果                  | `backend/app/services/query_context.py`、`services/pipeline.py`；严格回放依赖可信到达时间                        |
| 核验、行动与导出   | 异常/建议人工核验，建议通过后建任务，负责人/期限/回执/销项；带查询上下文的 CSV 导出与公式注入防护          | `backend/app/api/v1.py`、`services/export_service.py`、`frontend/src/views/ImpactView.vue`；复盘备注缺前端入口 |
| 预测实验       | 四个目标、1/3/6/12/24 小时预测；3 小时树模型、其他提前量基线，特征契约及训练截止检查，单事件时间留出评估    | `backend/app/services/prediction_service.py`；尚无跨事件验证、校准区间与完整真实训练入口                                 |




## 验证状态（2026-10-26）

本轮重新执行后端测试、前端交互测试和构建。浏览器结果来自已有验收报告，本轮未启动浏览器端到端流程；Docker/MySQL 也未复测。前端交互测试使用 mock API，后端测试使用临时 SQLite，均不能替代真实数据和真实部署验收。


| 项目                                              | 结果                                                               |
| ----------------------------------------------- | ---------------------------------------------------------------- |
| 后端测试 `pytest`                                   | 50 passed（领域 14、契约 2、验收用例 14、API 集成 19、迁移 1）                     |
| 前端交互测试 `npm test`（vitest + jsdom）               | 18 passed                                                        |
| 前端构建 `npm run build`（vue-tsc + vite）            | 通过，无类型错误                                                         |
| 浏览器冒烟 `npm run e2e`（Edge headless，demo 模式）      | 历史报告 22/22 通过；本轮未重跑                                              |
| 浏览器空库检查 `scripts/e2e-real-empty.mjs`（real 模式空库） | 历史报告 15/15 通过；本轮未重跑                                              |
| Alembic 002 迁移                                  | 本轮后端测试包含旧库升级、降级、再升级数据保留检查（临时 SQLite）；开发库备份实测属于历史记录               |
| 跨事件预测验证                                         | **未完成**：没有独立真实台风验证集，界面标注“未经跨事件验证”                                |
| Docker / MySQL 全栈                               | **本轮未验证**：历史报告记载 Docker 引擎未启动；MySQL UTC 会话设置已有代码，尚无本轮 MySQL 实测结果 |




## 目录

```
code/
  backend/          FastAPI + SQLAlchemy 2 + Alembic（SQLite 开发 / MySQL 部署）
    app/api/v1.py   全部 REST 接口
    app/services/   查询上下文、流水线、导入、预测、导出
    app/domain/     异常规则、预测特征、车次映射等纯函数
    alembic/        001 初始建表；002 版本化与到达时间（只增不删）
    config/         rules.yaml 阈值、prediction_targets.yaml 预测目标
    tests/          领域、验收用例、API 集成（TestClient + 临时 SQLite）、迁移
  frontend/         Vue 3 + TypeScript + Vite + Pinia + vue-router + ECharts + Leaflet
    src/stores/context.ts      全站共享查询上下文
    src/composables/useLoader  带序号与取消的数据加载
    src/views/                 六个主页面与两个子页面
    tests/                     vitest 交互测试
    scripts/                   浏览器冒烟脚本（puppeteer-core 驱动本机 Edge/Chrome）
  docs/             数据字典、扩展说明、验收报告
  docker-compose.yml
  .env.example
```



## 启动



### 本地（SQLite）

```bash
cd code/backend
py -3 -m pip install -r requirements.txt
py -3 scripts/init_db.py          # alembic upgrade head；仅 DATA_MODE=demo 时生成模拟数据
py -3 -m uvicorn app.main:app --reload --port 8000

cd code/frontend
npm install
npm run dev                        # http://localhost:5173
```

`DATABASE_URL` 默认读 `.env`；本地可设 `sqlite:///./typhoon_platform.db`。`init_db.py` 在 real 模式下只迁移不灌数。

### Docker（MySQL）

```bash
cd code
cp .env.example .env
docker compose up -d mysql         # 等待 healthy
docker compose up -d backend frontend
docker compose exec backend python scripts/init_db.py
```

- API 文档：[http://localhost:8000/docs](http://localhost:8000/docs)
- 健康检查：[http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- 前端：[http://localhost:5173](http://localhost:5173)



## 数据模式与写权限


| 配置                | 作用                                                               |
| ----------------- | ---------------------------------------------------------------- |
| `DATA_MODE=demo`  | 允许生成模拟数据；页面标注“模拟数据”                                              |
| `DATA_MODE=real`  | 禁止 seed；空库保持空态；只读写 `data_mode=real` 的数据集                         |
| `API_KEY`         | 设置后，导入、重跑、预测、核验、事件登记、行动任务都需要请求头 `X-API-Key`；real 模式未配置密钥时拒绝所有写操作 |
| `X-Operator`      | 可选请求头，记录在核验与行动任务中                                                |
| `PRECHECK_SECRET` | 预检凭证的 HMAC 密钥                                                    |
| `MAX_UPLOAD_MB`   | 上传大小上限（默认 20）                                                    |


前端不内置任何密钥。操作者在“数据管理 › 写操作凭证”里填写 API Key 与操作者，只存在当前标签页的 `sessionStorage`。

## 页面入口（hash 路由）


| 路由                                              | 页面      | 主要内容                                                                    |
| ----------------------------------------------- | ------- | ----------------------------------------------------------------------- |
| `#/overview`                                    | 事件总览    | 灾前/灾中/灾后阶段提示、指标行、省级地图（约 68%）与待核查列表、来源新鲜度、三维趋势（点击可移动分析时刻）                |
| `#/overview/impact`                             | 影响事件与行动 | 停运范围（映射状态筛选、分页）、车次运行实例、恢复数据状态、候选建议人工核验后形成行动任务（责任人、期限、回执、销项）             |
| `#/replay`                                      | 历史回放    | 社会/组织/物理三泳道共享时间轴、播放/单步/倍速、定位小图、游标前后时间窗的事件记录                             |
| `#/analysis/social` `org` `physical` `coupling` | 分析中心    | 各维度曲线、基线与阈值、判定依据窄栏、话题、组织覆盖、停运区段、耦合任务矩阵与关系异常                             |
| `#/prediction`                                  | 预测中心    | 目标、起点、提前量、运行；一条横轴同时画起点前已知观测（实线）与未来预测（虚线）；区间不可用时写明原因                     |
| `#/evidence/:id?`                               | 异常与证据   | 左 32% 列表（筛选、分页、方向键）、右 68% 证据（判定依据、原始证据脱敏、核验记录）、底部核验栏                    |
| `#/data`                                        | 数据管理    | 四步导入（选文件、字段映射、预检、确认）、质量窄栏、导入历史与错误行、覆盖矩阵、分析版本与重跑、写操作凭证、事件登记、模拟数据（仅 demo） |
| `#/data/glossary`                               | 资料与口径   | 带当前上下文的 CSV 导出、指标口径（单位、分子分母、去重键、全国口径）、阈值、模型特征契约、证据边界                    |


顶栏的事件、省份、回放模式和分析时刻是全站共享的查询上下文。切换事件会清空旧事件的数据和详情；过期请求会被取消，迟到的响应不会覆盖新结果。

## 查询上下文与回放

所有上下文相关接口接受同一组参数：`dataset_id`、`event_id`、`province_code`、`start`、`end`、`as_of`、`replay_mode`、`data_version`，异常接口另有 `analysis_scope`（`single`/`pair`/`joint`，可逗号组合）和 `dimension`。

- `replay_mode=as_known`（当时已知）：必须给 `as_of`，只返回 `available_at <= as_of` 的指标、异常、证据与事件记录；到达时间未知的记录不参与严格回放并单独计数。需要未来窗口的滞后关系在窗口成熟前计为待确认。
- `replay_mode=retrospective`（事后复盘）：可见全部数据，前端把游标之后才获知的记录标为“游标后获知”。
- 时间：事件与观测时间是北京时间（无时区存储）；系统时间（核验、导入、运行完成时间）以 UTC 存储，接口带 `Z` 返回，前端换算为北京时间显示。



## 主要 API（`/api/v1`）


| 方法与路径                                                               | 说明                                               |
| ------------------------------------------------------------------- | ------------------------------------------------ |
| `GET /health`                                                       | 状态、数据模式、是否要求密钥、是否允许 seed                         |
| `GET /datasets` `GET /events` `POST /events`                        | 数据集与事件；登记事件会按需创建数据集                              |
| `POST /admin/seed`                                                  | 仅 demo 模式：生成模拟数据、训练演示模型、运行一次预测                   |
| `GET /metrics/registry`                                             | 指标口径与规则阈值                                        |
| `GET /metrics/series`                                               | 省小时指标；`province_code=ALL` 为全国去重口径                |
| `GET /dashboard/summary`                                            | 总览卡片、阶段、待核查、来源新鲜度                                |
| `GET /anomalies` `GET /anomalies/{id}`                              | 分页列表（`page`、`page_size`）与证据详情                    |
| `POST /review` `GET /reviews`                                       | 核验（`approve`/`reject`/`need_evidence`），校验目标归属    |
| `GET /suggestions` `GET/POST/PATCH /actions`                        | 候选建议与业务行动任务；任务需已核验的建议，销项需回执                      |
| `GET /timeline`                                                     | 事件记录；`known_from`/`known_to` 按获知时间取窗             |
| `GET /impact` `GET /coverage`                                       | 停运映射与运行实例；覆盖矩阵、任务状态、待核验、代理值                      |
| `GET /predictions` `POST /predictions/run` `GET /models`            | 预测结果与元信息（目标、提前量、ML 提前量、区间原因）；模型特征契约              |
| `GET /import/sources` `POST /import/precheck` `POST /import/commit` | 导入来源、预检（返回凭证）、提交（`error_policy=strict            |
| `GET /import/batches` `GET /import/errors/{batch_id}`               | 批次与错误行                                           |
| `POST /pipeline/rerun` `GET /analysis/runs`                         | 版本化重跑与运行记录                                       |
| `GET /export/anomalies` `GET /export/metrics`                       | CSV（UTF-8 BOM、防公式注入），每行带数据集、事件、数据版本、回放模式、截止时刻和时区 |


错误统一返回 `{"detail": {"error_code": ..., "message": ...}}`。

## 导入与版本

1. 预检：服务端校验格式、大小、必填字段、时间与数值，返回质量检查、预览、错误行和凭证。凭证绑定文件哈希、实体、数据集、事件与字段映射。
2. 提交：再次校验凭证与文件。严格模式有阻断错误则拒绝；跳过错误行需要显式确认，错误行写入批次。同一文件重复提交复用原批次。
3. 分析：每次导入或重跑生成新的 `analysis_run` 与数据版本 `r{run_id}`，全部阶段成功后才切换生效指针；失败时继续使用原版本，旧版本仍可按 `data_version` 查询。
4. 账号身份分为个人、官方、未知；未知不计入个人或官方统计。

模板：`backend/data/templates/weibo_template.csv`。

## 测试与验收

```bash
cd code/backend && py -3 -m pytest -q -p no:cacheprovider
cd code/frontend && npm test && npm run build

# 浏览器冒烟：先启动后端（demo）与 npm run dev
npm run e2e
# real 模式空库检查：后端以 DATA_MODE=real、API_KEY=e2e-real-key、空库启动
node scripts/e2e-real-empty.mjs
```

浏览器脚本会写入核验记录和一次导入，请对数据库副本运行。截图输出到 `frontend/e2e-shots/`（已忽略）。

### 验收用例对照


| #   | 用例                                                          | 覆盖                                                                                                                                                                                  |
| --- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 只有社会数据仍保存社会异常；组织缺失不出组织确定性异常                                 | `test_case1_*`                                                                                                                                                                      |
| 2   | 两维触发不称三维同步；joint 要求三维                                       | `test_case2_*`；耦合页只列 pair/joint                                                                                                                                                     |
| 3   | `as_known(T)` 不受之后到达的数据影响；滞后结果待确认                           | `test_case3_*`、`test_as_known_*`、`test_timeline_window_and_as_known_cut`；前端 `replay.spec.ts`；浏览器回放检查                                                                                |
| 4   | 窗口按时间；缺测不当零发布                                               | `test_case4_*`                                                                                                                                                                      |
| 5   | 训练/推理特征一致；仅 h3 标 ML；训练晚于起点拒用；预测轴含未来                         | `test_case5_*`、`test_predictions_mark_ml_only_on_h3_and_never_fake_intervals`；前端 `prediction.spec.ts`                                                                               |
| 6   | 南京 22:10—上海次日 01:20—杭州次日 03:40，仅上海至杭州停运时为次日；未知端点待核验；时刻表版本不串 | `test_case6_*`                                                                                                                                                                      |
| 7   | 两省计数、加权比例、跨省同车去重；站点数用真实站点集合                                 | `test_national_counts_are_deduplicated_and_stations_are_real_sets`                                                                                                                  |
| 8   | 预检失败不能提交；伪造凭证、超限、非法值、重复提交、分析失败均有明确结果                        | `test_import_*`、`test_failed_rerun_keeps_previous_version_serving`；前端 `import.spec.ts`；浏览器导入检查                                                                                      |
| 9   | 重跑失败旧看板可用；成功后旧版本可查；迁移保留原数据                                  | `test_failed_rerun_*`、`test_successful_rerun_*`、`test_migration.py`                                                                                                                 |
| 10  | real 空库不 seed、不回退 demo；跨数据集核验与未授权写被拒                        | `test_real_mode_never_seeds_or_falls_back_to_demo`、`test_writes_require_api_key_and_record_operator`、`test_review_rejects_bad_action_and_cross_dataset_target`；`e2e-real-empty.mjs` |
| 11  | 快速切换不串上下文；导出与列表一致；分页过第 101 条                                | `test_pagination_reaches_past_first_hundred_and_export_matches`；前端 `context.spec.ts`、`evidence.spec.ts`；浏览器快速切换检查                                                                   |
| 12  | TestClient + 临时库的 API 集成测试与前端交互测试                           | `tests/test_api_integration.py`（19 项）、`frontend/tests/`（18 项）                                                                                                                       |




## 未完成内容、原因与解决方法

优先级为后续开发建议：P0 优先解决真实数据分析的前置条件，P1 完成研究验证与部署闭环，P2 完善体验和扩展能力；不表示本次已经修改这些功能。


| 优先级 / 项目           | 当前状态与未完成原因（代码依据）                                                                                          | 解决方法与验收标准                                                                                                |
| ------------------ | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| P0 多源真实数据接入        | `import_service.py` 的 `IMPORT_SOURCES` 将账号清单、停运公告、时刻表、实况与预报标为 `not_connected`；校验与提交只实现微博。已有数据表不代表已有导入功能   | 为各实体补字段模板、校验、预检凭证、幂等提交与来源追踪；复用分析版本切换。使用真实样本验证导入、错误行、重复提交和跨事件隔离，确认组织/物理指标来自真实来源                           |
| P0 情绪识别与地域归属       | `sentiment.py` 始终返回 `DemoRuleSentiment`，真实模式也沿用关键词规则；`geo.py` 只覆盖 FJ/GD/ZJ/JS/SH/TW 六地区别名和模拟 IP 前缀，未按模式隔离 | 用标注语料评估并替换 `SentimentModel`，记录模型版本；扩充行政区与地名消歧，真实模式禁用模拟 IP 映射或接入可信归属来源。报告分类精确率/召回率及地区匹配、未知比例；不能只以流程运行成功验收 |
| P0 严格回放的数据前提       | 截断逻辑已有，但上传数据可缺少 `available_at`，早于发布时间的到达时间不可信；`_parse_time` 会去掉时区而不先换算北京时间                                | 在采集/导入时保留真实到达时间，明确源时区并先换算；拒绝或明确标记歧义时间，不能用发布时间伪造到达时间。补带时区输入、迟到/修订、未知到达时间测试，验证 `as_known(T)` 结果不被未来数据污染    |
| P1 跨事件预测验证         | `train_models` 仅执行单事件全局时间留出，返回 `cross_event_validated=False`；现有演示模型不能证明真实泛化能力                             | 收集多场独立真实台风，按事件划分训练/验证/最终测试集；只使用预测起点已知特征，逐目标、逐提前量报告 MAE/RMSE 与朴素基线对比，并保留切分与数据版本                           |
| P1 多提前量模型及预测区间     | 树模型仅 h3；其余提前量为基线；`run_predictions` 始终把上下界设为 `None`，没有区间校准程序                                               | 视研究目标训练各提前量模型；用独立校准集计算预测区间，在保留测试集报告覆盖率与区间宽度。不达标时继续显示基线/无区间及原因                                            |
| P1 真实模型训练与准入闭环     | 服务层有 `train_models`，但没有独立训练 API/CLI 或训练管理页面；演示初始化负责训练。训练函数主要检查标签数及切分，而 readiness 报告还列出缺失率、省小时数等门槛         | 增加可复现训练命令或受写权限保护的任务入口，统一 readiness 与实际训练准入检查，保存事件清单、参数、数据/模型版本；验证准入失败不产出或替换模型                            |
| P1 恢复/复运分析         | `/impact` 的 `recovery` 固定返回 `not_connected`；尚无恢复数据处理链路                                                    | 接入复运公告或运行状态，建立与原停运车次、运行日、区段的关联，记录发布/到达时间；补部分恢复、跨日恢复与重复公告测试，再展示恢复时间和进度                                    |
| P1 行动任务复盘          | 模型与 PATCH 接口支持 `review_note`，`ImpactView.vue` 仅提交状态和回执，没有复盘编辑入口                                           | 增加备注输入、保存及回读展示，补前端提交与接口持久化验证；已销项任务应能查看复盘记录                                                               |
| P1 Docker/MySQL 验收 | Compose、Dockerfile、MySQL 连接和 UTC 会话设置已存在；历史验收受 Docker 引擎未运行限制，本轮测试仅 SQLite                                | 启动 Docker 后，用独立 MySQL 测试库验证迁移、导入、事务回滚、版本切换、时区与备份恢复，再跑 demo/real 浏览器脚本；记录版本、命令与结果                         |
| P1 规则业务校准          | `rules.yaml` 与 `prediction_targets.yaml` 已配置窗口、阈值、最小样本等，但没有真实标注集上的业务验收结论                                  | 与业务人员确定异常定义，建立标注事件窗口，统计误报/漏报并调参；冻结规则版本，在独立事件复核，保存校准依据                                                    |
| P2 后台任务与规模验证       | `tasks/runner.py` 直接调用 `fn()`，预测与重跑接口同步等待；不是持久化异步队列，也没有完整自动重试/重启恢复机制                                      | 大数据场景引入独立 worker 和持久化队列，接口返回 task_id；补超时、重试、幂等、并发版本切换与中断恢复测试，并按目标数据量压测                                   |
| P2 多用户身份权限         | 当前为共享 API Key，`X-Operator` 是调用方提供的文本；没有可验证的独立人员身份和角色授权                                                    | 若需要多人正式使用，增加登录与角色/数据集权限，操作者由服务端身份生成；验证越权读取、写入和审计追踪                                                       |
| P2 地图与人工体验验收       | 本地省界和图层切换已实现；外部影像需要网络，天地图需要 `VITE_TIANDITU_TK`；自动化截图不能替代真人体验                                              | 配置可用底图并检查断网降级、坐标与数据省码一致性；在 1680 宽屏、触屏和键盘操作下人工走通导入、回放、核验、预测，记录问题并复测                                       |


建议顺序：先补真实多源接入、分类/地域和到达时间口径，再完成真实事件分析与业务标注，之后做跨事件模型验证、区间校准和 MySQL 部署验收，最后按实际使用规模补任务队列与多人权限。页面上的“未接入”“未经跨事件验证”等提示应在对应验收通过后才移除。

## 模拟实现与替换点


| 能力     | 当前位置                                          | 替换方式                                        |
| ------ | --------------------------------------------- | ------------------------------------------- |
| 情绪分类   | `app/domain/sentiment.py` `DemoRuleSentiment` | 实现 `SentimentModel` 并注入                     |
| 预报源    | `SeedForecastProvider`                        | 新 `ForecastProvider` 适配器                    |
| 树模型    | `artifacts/demo_*_h3.joblib`                  | 真实数据训练后登记 `model_registry`，`data_mode=real` |
| 账号分类清单 | seed checklist                                | 导入核验清单表                                     |




## 声明

模拟数据使用 `SIM-` 前缀，页面标注“模拟”，不冒充真实微博或官方公告。原始内容在证据面板中脱敏，用户标识截断。
