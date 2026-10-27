from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Typhoon SOP Anomaly Platform", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(v1_router)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    rid = request.headers.get("X-Request-Id", "unknown")
    return JSONResponse(
        status_code=500,
        content={"error_code": "internal_error", "message": str(exc), "request_id": rid},
    )


@app.get("/")
def root():
    return {
        "name": "typhoon-sop-platform",
        "docs": "/docs",
        "health": "/api/v1/health",
        "data_mode": settings.data_mode,
    }
