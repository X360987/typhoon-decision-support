from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Dataset

DbSession = Annotated[Session, Depends(get_db)]


def request_id_header(x_request_id: str | None = Header(default=None)) -> str:
    return x_request_id or str(uuid.uuid4())


def _deny(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message})


def require_write(
    x_api_key: str | None = Header(default=None),
    x_operator: str | None = Header(default=None),
) -> str:
    """Gate for every write. Returns the operator name recorded on audit rows.

    With API_KEY configured the header must match. Without it, writes are only
    open in demo mode; real mode refuses writes until a key is configured.
    """
    settings = get_settings()
    if settings.api_key:
        if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
            raise _deny(401, "unauthorized", "需要有效 X-API-Key")
    elif settings.data_mode == "real":
        raise _deny(403, "write_disabled", "真实模式未配置 API_KEY，写操作已禁用")
    return (x_operator or "anonymous")[:64]


WriteOperator = Annotated[str, Depends(require_write)]


def writable_dataset(db: Session, dataset_id: str, allow_create: bool = False) -> Dataset | None:
    """Dataset must exist (unless creation is allowed) and match the server's trusted data mode."""
    settings = get_settings()
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        if allow_create:
            return None
        raise _deny(404, "dataset_not_found", "数据集不存在")
    if ds.data_mode != settings.data_mode:
        raise _deny(403, "mode_mismatch", f"数据集为 {ds.data_mode} 模式，服务端为 {settings.data_mode} 模式，拒绝写入")
    return ds


def readable_dataset(db: Session, dataset_id: str) -> Dataset:
    settings = get_settings()
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise _deny(404, "dataset_not_found", "数据集不存在")
    if ds.data_mode != settings.data_mode:
        raise _deny(403, "mode_mismatch", "当前服务模式不提供该数据集，避免 demo 与 real 混用")
    return ds
