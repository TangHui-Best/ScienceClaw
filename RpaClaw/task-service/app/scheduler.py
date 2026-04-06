"""
Asyncio-based task scheduler — replaces Celery beat + worker.

Runs inside the FastAPI process: a background loop checks storage every 60s
for tasks whose crontab matches the current minute, then executes them
concurrently via asyncio tasks.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import asyncio
import httpx
from croniter import croniter
from loguru import logger

from app.core.config import settings
from app.core.storage import get_storage_instance
from app.services.chat_client import run_task_chat
from app.services.feishu import notify_task_failed, notify_task_success, notify_task_started
from app.services.webhook_sender import send_webhook


def _display_tz() -> ZoneInfo:
    tz_name = (settings.display_timezone or "").strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _fmt_time(dt: Optional[datetime]) -> str:
    if dt is None:
        return "-"
    tz = _display_tz()
    if hasattr(dt, "astimezone"):
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class TaskScheduler:
    """Single-process asyncio scheduler for cron-based tasks."""

    def __init__(self, interval: float = 60.0):
        self._interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running_tasks: set[str] = set()

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("TaskScheduler started (interval={}s)", self._interval)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
            logger.info("TaskScheduler stopped")

    async def _loop(self) -> None:
        # Wait a few seconds on startup so storage is ready
        await asyncio.sleep(3)
        while True:
            try:
                await self._check_due_tasks()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler loop error")
            await asyncio.sleep(self._interval)

    async def _check_due_tasks(self) -> None:
        now = datetime.now(_display_tz()).replace(second=0, microsecond=0)
        storage = get_storage_instance()
        task_repo = storage.get_task_repo()
        tasks = await task_repo.list_tasks()
        for task in tasks:
            if task.status != "enabled":
                continue
            crontab_str = task.crontab or ""
            if not crontab_str:
                continue
            task_id = task.id
            try:
                if croniter.match(crontab_str, now):
                    if task_id in self._running_tasks:
                        logger.debug("Task {} still running, skip", task_id)
                        continue
                    asyncio.create_task(self._run_task(task_id))
                    logger.info("Dispatched task {}", task_id)
            except Exception as e:
                logger.warning("Crontab check failed for {}: {}", task_id, e)

    async def _run_task(self, task_id: str) -> None:
        self._running_tasks.add(task_id)
        try:
            await self._execute_task(task_id)
        finally:
            self._running_tasks.discard(task_id)

    async def _execute_task(self, task_id: str) -> None:
        storage = get_storage_instance()
        task_repo = storage.get_task_repo()
        run_repo = storage.get_run_repo()

        task = await task_repo.get_task(task_id)
        if not task:
            logger.warning("run_task: task {} not found", task_id)
            return

        name = task.name or "未命名"
        prompt = task.prompt or ""
        webhook = task.webhook or ""
        webhook_ids = task.webhook_ids or []
        event_config = task.event_config or []
        model_config_id = task.model_config_id
        notify_start = "notify_on_start" in event_config
        user_id = task.user_id

        start_time = datetime.now(timezone.utc)

        run = await run_repo.create_run(
            task_id=task_id,
            status="running",
        )
        run_id = run.id

        try:
            if notify_start:
                await self._notify_start(webhook, webhook_ids, name, start_time)

            result = await run_task_chat(
                task_id, prompt, user_id=user_id, model_config_id=model_config_id
            )
            end_time = datetime.now(timezone.utc)

            if "error" in result:
                await run_repo.update_run(
                    run_id, status="failed", error=result["error"]
                )
                await self._notify_finish(webhook, webhook_ids, name, start_time, end_time, False, result["error"])
                return

            await run_repo.update_run(
                run_id,
                status="success",
                chat_id=result.get("chat_id"),
                result=result.get("output", ""),
            )
            await self._notify_finish(webhook, webhook_ids, name, start_time, end_time, True, result.get("output", ""))

        except Exception as e:
            logger.exception("run_task failed for {}", task_id)
            end_time = datetime.now(timezone.utc)
            await run_repo.update_run(
                run_id, status="failed", error=str(e)
            )
            await self._notify_finish(webhook, webhook_ids, name, start_time, end_time, False, str(e))

    # ── Notification helpers ──

    async def _notify_start(
        self, webhook: str, webhook_ids: list, task_name: str, start_time: datetime
    ) -> None:
        start_str = _fmt_time(start_time)
        if webhook and webhook.strip():
            await notify_task_started(webhook, task_name, start_str)
        # Managed webhooks only available in docker (MongoDB) mode
        if not webhook_ids or settings.storage_backend == "local":
            return
        from app.core.db import db
        for wid in webhook_ids:
            try:
                wh_doc = await db.get_collection("webhooks").find_one({"_id": wid})
                if not wh_doc:
                    continue
                title = f"🚀 任务开始执行：{task_name}"
                content = f"**⏱ 开始时间**\n{start_str}"
                await send_webhook(wh_doc.get("type", "feishu"), wh_doc.get("url", ""), title, content)
            except Exception as e:
                logger.warning("Failed to notify start webhook {}: {}", wid, e)

    async def _notify_finish(
        self, webhook: str, webhook_ids: list, task_name: str,
        start_time: datetime, end_time: datetime, success: bool, result_or_error: str,
    ) -> None:
        start_str = _fmt_time(start_time)
        end_str = _fmt_time(end_time)
        # Legacy single webhook (Feishu)
        if webhook and webhook.strip():
            if success:
                await notify_task_success(webhook, task_name, start_str, end_str, result_or_error)
            else:
                await notify_task_failed(webhook, task_name, start_str, end_str, result_or_error)
        # Managed webhooks only available in docker (MongoDB) mode
        if not webhook_ids or settings.storage_backend == "local":
            return
        from app.core.db import db
        truncated = result_or_error[:500] + "..." if len(result_or_error) > 500 else result_or_error
        label = "执行结果" if success else "错误信息"
        title = f"{'✅ 任务执行成功' if success else '❌ 任务执行失败'}：{task_name}"
        content = f"**⏱ 开始时间**\n{start_str}\n\n**⏱ 结束时间**\n{end_str}\n\n**📋 {label}**\n\n{truncated}"
        for wid in webhook_ids:
            try:
                wh_doc = await db.get_collection("webhooks").find_one({"_id": wid})
                if not wh_doc:
                    continue
                await send_webhook(wh_doc.get("type", "feishu"), wh_doc.get("url", ""), title, content)
            except Exception as e:
                logger.warning("Failed to notify webhook {}: {}", wid, e)


scheduler = TaskScheduler()
