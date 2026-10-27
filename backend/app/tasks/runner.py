from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models import TaskRun


def create_task(
    db: Session,
    task_type: str,
    *,
    dataset_id: str | None = None,
    event_id: int | None = None,
    idempotency_key: str | None = None,
) -> TaskRun:
    if idempotency_key:
        existing = (
            db.query(TaskRun)
            .filter(TaskRun.task_type == task_type, TaskRun.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return existing
    task = TaskRun(
        dataset_id=dataset_id,
        event_id=event_id,
        task_type=task_type,
        status="pending",
        idempotency_key=idempotency_key,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def run_task(db: Session, task_id: int, fn: Callable[[], Any]) -> TaskRun:
    task = db.get(TaskRun, task_id)
    if not task:
        raise ValueError("task_not_found")
    if task.status == "success":
        return task
    task.status = "running"
    task.progress = 0.1
    task.updated_at = datetime.utcnow()
    db.commit()
    try:
        result = fn()
        task.status = "success"
        task.progress = 1.0
        task.result = result if isinstance(result, dict) else {"result": result}
        task.message = "ok"
    except Exception as e:
        task.status = "failed"
        task.message = str(e)
        db.commit()
        raise
    db.commit()
    db.refresh(task)
    return task
