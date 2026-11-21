"""跨域、写入凭据和统一错误格式，避免对只读 CSV 下载施加请求头要求。"""

import logging
import secrets
from urllib.parse import unquote

from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException

from app.config import settings


def install_http_policy(app):
    """写操作统一校验，旧接口也不能绕过 API Key。"""

    @app.middleware("http")
    async def writes(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            key = request.headers.get("X-API-Key", "")
            if not settings.write_api_key:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": {
                            "error_code": "write_key_not_configured",
                            "message": "尚未配置写入 API Key",
                        }
                    },
                )
            if not secrets.compare_digest(key, settings.write_api_key):
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": {
                            "error_code": "invalid_api_key",
                            "message": "写操作需要有效 X-API-Key",
                        }
                    },
                )
            operator = unquote(request.headers.get("X-Operator", "")).strip()
            if not operator or len(operator) > 120:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "error_code": "operator_required",
                            "message": "写操作需要 1 至 120 字符的 X-Operator",
                        }
                    },
                )
            request.state.operator = operator
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"error_code": f"http_{exc.status_code}", "message": str(exc.detail)}
        )
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "error_code": "validation_error",
                    "message": "; ".join(e["msg"] for e in exc.errors()),
                }
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logging.getLogger(__name__).error("数据库请求失败：%s", type(exc).__name__)
        conflict = isinstance(exc, IntegrityError)
        return JSONResponse(
            status_code=409 if conflict else 503,
            content={
                "detail": {
                    "error_code": "database_conflict" if conflict else "database_unavailable",
                    "message": "数据约束冲突，未覆盖已有记录"
                    if conflict
                    else "数据库不可用，请检查服务与迁移",
                }
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Operator"],
        expose_headers=["Content-Disposition"],
    )
