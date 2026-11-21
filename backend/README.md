# 后端

部署、当前进度和接口见上级 [README](../README.md)。字段见 [IMPORT_GUIDE](IMPORT_GUIDE.md)。

从本目录执行 `../.venv/Scripts/python.exe -m alembic upgrade head`，再启动 uvicorn。配置读取本目录 `.env`。

路由在 `app/api/`，导入规则在 `app/importers/`。起终站只改 `app/geo.py`，态度汇总只改 `app/attitude.py`，主体计数只改 `app/subjects.py`。

## PostgreSQL 后端启动

从仓库根目录复制 `backend/.env.example` 为 `backend/.env`，将 POSTGRES_PASSWORD 和 WRITE_API_KEY 改为随机值。运行：

```sh
docker compose --env-file backend/.env -f docker-compose.backend.yml up --build
```

接口说明在 http://127.0.0.1:8000/docs ，人工停运工作簿导入页在 http://127.0.0.1:8000/rail-import 。首次运行需准备官方台风目录，使用 app.cli 导入，再创建数据集和事件。
