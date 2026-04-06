"""MongoDB-backed task repository."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import shortuuid
from loguru import logger

from app.core.db import db
from app.models.task import TaskCreate, TaskOut, TaskUpdate, task_doc_to_out
from app.repositories.base import TaskRepository


class MongoTaskRepository(TaskRepository):
    """MongoDB implementation of TaskRepository, delegating to the shared db object."""

    async def get_task(self, task_id: str) -> Optional[TaskOut]:
        """Retrieve a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            TaskOut if found, None otherwise
        """
        doc = await db.get_collection("tasks").find_one({"_id": task_id})
        if not doc:
            return None
        return task_doc_to_out(doc)

    async def list_tasks(self) -> List[TaskOut]:
        """List all tasks sorted by created_at descending.

        Returns:
            List of all tasks
        """
        cursor = db.get_collection("tasks").find({}).sort("created_at", -1)
        result = []
        async for doc in cursor:
            result.append(task_doc_to_out(doc))
        return result

    async def create_task(self, task_data: TaskCreate) -> TaskOut:
        """Create a new task.

        Args:
            task_data: Task creation data

        Returns:
            The created task
        """
        now = datetime.now(timezone.utc)
        task_id = shortuuid.uuid()
        doc: Dict[str, Any] = {
            "_id": task_id,
            "name": task_data.name,
            "prompt": task_data.prompt,
            "schedule_desc": task_data.schedule_desc,
            "crontab": task_data.crontab or "",
            "webhook": task_data.webhook,
            "webhook_ids": task_data.webhook_ids or [],
            "event_config": task_data.event_config or [],
            "model_config_id": (task_data.model_config_id or "").strip() or None,
            "status": task_data.status or "enabled",
            "user_id": (task_data.user_id or "").strip() or None,
            "created_at": now,
            "updated_at": now,
        }
        await db.get_collection("tasks").insert_one(doc)
        logger.info(f"MongoTaskRepository: task created {task_id}")
        return task_doc_to_out(doc)

    async def update_task(self, task_id: str, task_data: TaskUpdate) -> Optional[TaskOut]:
        """Update an existing task.

        Args:
            task_id: The task identifier
            task_data: Task update data

        Returns:
            The updated task if found, None otherwise
        """
        doc = await db.get_collection("tasks").find_one({"_id": task_id})
        if not doc:
            return None

        now = datetime.now(timezone.utc)
        updates: Dict[str, Any] = {"updated_at": now}

        if task_data.name is not None:
            updates["name"] = task_data.name
        if task_data.prompt is not None:
            updates["prompt"] = task_data.prompt
        if task_data.schedule_desc is not None:
            updates["schedule_desc"] = task_data.schedule_desc
        if task_data.crontab is not None:
            updates["crontab"] = task_data.crontab
        if task_data.webhook is not None:
            updates["webhook"] = task_data.webhook
        if task_data.webhook_ids is not None:
            updates["webhook_ids"] = task_data.webhook_ids
        if task_data.event_config is not None:
            updates["event_config"] = task_data.event_config
        if task_data.model_config_id is not None:
            updates["model_config_id"] = (task_data.model_config_id or "").strip() or None
        if task_data.status is not None:
            updates["status"] = task_data.status
        if task_data.user_id is not None:
            updates["user_id"] = (task_data.user_id or "").strip() or None

        await db.get_collection("tasks").update_one({"_id": task_id}, {"$set": updates})
        updated_doc = await db.get_collection("tasks").find_one({"_id": task_id})
        return task_doc_to_out(updated_doc)

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            True if deleted, False if not found
        """
        result = await db.get_collection("tasks").delete_one({"_id": task_id})
        return result.deleted_count > 0
