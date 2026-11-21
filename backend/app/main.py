"""台风科研后端入口。路由在 app.api，导入规则在 app.importers。"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.attitude import router as attitude_router
from app.api.datasets import router as datasets_router
from app.api.impact import router as impact_router
from app.api.intake import router as intake_router
from app.api.legacy import router as legacy_router
from app.api.metrics import router as metrics_router
from app.http_policy import install_http_policy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(
    title="台风科研数据后端",
    version="0.2.0",
    description="真实数据 MVP：按日统计与起终点示意线，写操作要求 API Key 和操作者。",
)


@app.get("/rail-import", include_in_schema=False)
def rail_import_page():
    return FileResponse(Path(__file__).with_name("rail_import.html"))


app.include_router(legacy_router)
app.include_router(datasets_router)
app.include_router(metrics_router)
app.include_router(impact_router)
app.include_router(attitude_router)
app.include_router(intake_router)
install_http_policy(app)
