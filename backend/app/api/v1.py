"""场景：复用。按灾前、灾中、灾后和复用挂载路由，路径仍为 /api/v1。"""

from fastapi import APIRouter

from app.api.routes_during import router as during_router
from app.api.routes_post import router as post_router
from app.api.routes_pre import router as pre_router
from app.api.routes_shared import router as shared_router

router = APIRouter(prefix="/api/v1")
router.include_router(shared_router)
router.include_router(pre_router)
router.include_router(during_router)
router.include_router(post_router)
