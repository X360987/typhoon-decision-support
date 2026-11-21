"""保存原文件并做回滚预览。早期预览和前端预检共用这一步。"""

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.config import settings
from app.importers.processor import ImportProcessor
from app.importers.reader import read_rows
from app.models import ImportBatch
from app.queries import require_event


def preview_upload(kind, file, typhoon_id, catalog_year, db):
    """保存原始文件及预览；所有试写业务记录在返回前回滚。"""
    if kind in {"weibo", "rail", "rail_manual"}:
        require_event(db, typhoon_id)
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "文件超过配置的上传大小上限")
    suffix = Path(file.filename or "").suffix.lower()
    try:
        rows = read_rows(
            content,
            suffix,
            settings.max_import_rows,
            "ID_type长表" if kind == "rail_manual" else None,
        )
    except Exception as exc:
        raise HTTPException(422, f"无法解析上传文件：{exc}") from exc
    if not rows:
        raise HTTPException(422, "文件没有数据行")
    batch_id = str(uuid4())
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    path = settings.storage_dir / f"{batch_id}{suffix}"
    path.write_bytes(content)
    batch = ImportBatch(
        id=batch_id,
        kind=kind,
        typhoon_id=typhoon_id,
        catalog_year=catalog_year,
        filename=file.filename or "upload",
        file_path=str(path.resolve()),
        sha256=hashlib.sha256(content).hexdigest(),
        rows=rows,
        report={},
    )
    db.add(batch)
    db.flush()
    savepoint = db.begin_nested()
    try:
        report = ImportProcessor(db, batch).run()
    finally:
        savepoint.rollback()
    batch.report = report
    db.commit()
    return {"batch_id": batch.id, "status": batch.status, **report}
