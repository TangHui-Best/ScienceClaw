"""Task CRUD and runs API."""
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import shortuuid
from croniter import croniter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from loguru import logger

from app.core.config import settings
from app.core.storage import get_storage_instance
from app.models.task import (
    TaskCreate,
    TaskOut,
    TaskRunOut,
    TaskRunsPage,
    TaskUpdate,
)
from app.services.feishu import send_webhook_test
from app.services.schedule_parser import parse_schedule_to_crontab, ScheduleParseError

router = APIRouter(prefix="/tasks", tags=["tasks"])

# 常用时区展示名（API 返回给前端的 next_run 后缀）
_TZ_DISPLAY_NAMES = {"Asia/Shanghai": "北京时间", "UTC": "UTC"}


def _tz_display_name(tz_name: str) -> str:
    return _TZ_DISPLAY_NAMES.get(tz_name, tz_name)


def _compute_next_run_str(crontab_str: str) -> Optional[str]:
    """根据 crontab 计算下次执行时间（展示时区），失败返回 None。

    crontab 中的小时/分钟按展示时区解释，即用户输入"每天7点"生成的
    ``0 7 * * *`` 表示展示时区的 07:00，而非 UTC 07:00。
    """
    if not (crontab_str and crontab_str.strip()):
        return None
    try:
        tz_name = settings.display_timezone.strip() or "Asia/Shanghai"
        try:
            zi = ZoneInfo(tz_name)
        except Exception:
            zi = timezone.utc
            tz_name = "UTC"
        base = datetime.now(zi)
        it = croniter(crontab_str.strip(), base)
        next_run = it.get_next(datetime)
        return next_run.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logger.debug(f"next_run compute failed for crontab {crontab_str!r}: {e}")
        return None


class VerifyWebhookBody(BaseModel):
    webhook_url: str
    task_name: str = ""


class ValidateScheduleBody(BaseModel):
    schedule_desc: str = ""
    model_config_id: Optional[str] = None


@router.post("/validate-schedule")
async def validate_schedule(body: ValidateScheduleBody) -> dict:
    """Validate schedule description and return crontab + next run time."""
    desc = (body.schedule_desc or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="schedule_desc is required")
    try:
        crontab = await parse_schedule_to_crontab(desc, model_config_id=body.model_config_id)
    except ScheduleParseError as e:
        detail = {"message": e.message, "suggestions": e.suggestions} if e.suggestions else e.message
        raise HTTPException(status_code=400, detail=detail)
    if not crontab:
        raise HTTPException(status_code=400, detail="Could not parse schedule description to crontab")
    try:
        tz_name = settings.display_timezone.strip() or "Asia/Shanghai"
        try:
            zi = ZoneInfo(tz_name)
        except Exception:
            zi = timezone.utc
            tz_name = "UTC"
        base = datetime.now(zi)
        it = croniter(crontab, base)
        next_run = it.get_next(datetime)
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logger.warning(f"croniter next run failed: {e}")
        next_run_str = ""
    return {"valid": True, "crontab": crontab, "next_run": next_run_str}


@router.post("/verify-webhook")
async def verify_webhook(body: VerifyWebhookBody) -> dict:
    """Send a test message to the given Feishu webhook URL."""
    ok, message = await send_webhook_test(body.webhook_url, (body.task_name or "").strip())
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.post("", response_model=TaskOut)
async def create_task(body: TaskCreate) -> TaskOut:
    """Create a new scheduled task. Converts schedule_desc to crontab if needed."""
    crontab = body.crontab
    if not crontab and body.schedule_desc:
        try:
            crontab = await parse_schedule_to_crontab(body.schedule_desc, model_config_id=body.model_config_id)
        except ScheduleParseError as e:
            detail = {"message": e.message, "suggestions": e.suggestions} if e.suggestions else e.message
            raise HTTPException(status_code=400, detail=detail)
        if not crontab:
            raise HTTPException(status_code=400, detail="Could not parse schedule description to crontab")
    # Inject resolved crontab back into body before delegating to repo
    body_with_crontab = body.model_copy(update={"crontab": crontab or ""})
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    task = await task_repo.create_task(body_with_crontab)
    logger.info(f"Task created: {task.id} crontab={crontab}")
    return task


@router.get("", response_model=List[TaskOut])
async def list_tasks() -> List[TaskOut]:
    """List all tasks with stats: next_run, total_runs, success_rate, recent_runs."""
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    run_repo = storage.get_run_repo()
    # Webhook filtering is only relevant for docker (MongoDB) backend
    valid_wh_ids: set | None = None
    if settings.storage_backend != "local":
        from app.core.db import db
        webhooks_coll = db.get_collection("webhooks")
        valid_wh_ids = {doc["_id"] async for doc in webhooks_coll.find({}, {"_id": 1})}
    tasks = await task_repo.list_tasks()
    result = []
    for task in tasks:
        data = task.model_dump()
        tid = task.id
        # Filter out deleted webhook_ids when running in docker mode
        raw_wh_ids = data.get("webhook_ids") or []
        if raw_wh_ids and valid_wh_ids is not None:
            data["webhook_ids"] = [wid for wid in raw_wh_ids if wid in valid_wh_ids]
        data["next_run"] = _compute_next_run_str(task.crontab or "")
        total = await run_repo.count_runs(tid)
        success = await run_repo.count_runs(tid, status="success")
        data["total_runs"] = total
        data["success_runs"] = success
        data["success_rate"] = f"{round(success * 100 / total)}%" if total > 0 else ""
        data["recent_runs"] = await run_repo.get_recent_run_statuses(tid, limit=7)
        result.append(TaskOut(**data))
    return result


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str) -> TaskOut:
    """Get a task by id."""
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    task = await task_repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=TaskOut)
async def update_task(task_id: str, body: TaskUpdate) -> TaskOut:
    """Update a task."""
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    existing = await task_repo.get_task(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Resolve crontab from schedule_desc when needed
    resolved_crontab = body.crontab
    if body.schedule_desc is not None:
        if body.crontab is None:
            try:
                mid = body.model_config_id or existing.model_config_id
                resolved_crontab = await parse_schedule_to_crontab(body.schedule_desc, model_config_id=mid)
            except ScheduleParseError as e:
                detail = {"message": e.message, "suggestions": e.suggestions} if e.suggestions else e.message
                raise HTTPException(status_code=400, detail=detail)
    update_model = body.model_copy(update={"crontab": resolved_crontab})
    updated = await task_repo.update_task(task_id, update_model)
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return updated


@router.delete("/{task_id}")
async def delete_task(task_id: str) -> None:
    """Delete a task."""
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    deleted = await task_repo.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    logger.info(f"Task deleted: {task_id}")


@router.get("/{task_id}/runs", response_model=TaskRunsPage)
async def list_task_runs(
    task_id: str,
    limit: int = 20,
    offset: int = 0,
) -> TaskRunsPage:
    """Get execution history for a task with pagination. Default 20 per page."""
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    storage = get_storage_instance()
    run_repo = storage.get_run_repo()
    total = await run_repo.count_runs(task_id)
    items = await run_repo.list_runs(task_id, skip=offset, limit=limit)
    return TaskRunsPage(items=items, total=total)
