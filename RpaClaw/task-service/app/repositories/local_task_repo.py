"""Local file-based task repository with file locking."""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from filelock import FileLock, Timeout

from app.models.task import TaskCreate, TaskOut, TaskUpdate
from app.repositories.base import TaskRepository

logger = logging.getLogger(__name__)


class LocalTaskRepository(TaskRepository):
    """File-based task repository with atomic writes and file locking."""

    def __init__(self, data_dir: str):
        """Initialize the local task repository.

        Args:
            data_dir: Base directory for data storage
        """
        self.data_dir = Path(data_dir)
        self.tasks_dir = self.data_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.lock_timeout = 5.0

    def _task_file_path(self, task_id: str) -> Path:
        """Get the file path for a task.

        Args:
            task_id: The task identifier

        Returns:
            Path to the task JSON file
        """
        return self.tasks_dir / f"task-{task_id}.json"

    def _lock_file_path(self, task_id: str) -> Path:
        """Get the lock file path for a task.

        Args:
            task_id: The task identifier

        Returns:
            Path to the lock file
        """
        return self.tasks_dir / f"task-{task_id}.json.lock"

    def _read_task_file(self, task_id: str) -> Optional[dict]:
        """Read a task file without locking (for read operations).

        Args:
            task_id: The task identifier

        Returns:
            Task data dict or None if not found/corrupted
        """
        task_file = self._task_file_path(task_id)
        if not task_file.exists():
            return None

        try:
            with open(task_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Corrupted task file: {task_file}, skipping")
            return None
        except Exception as e:
            logger.error(f"Error reading task file {task_file}: {e}")
            return None

    def _write_task_file(self, task_id: str, data: dict) -> None:
        """Write a task file atomically with file locking.

        Args:
            task_id: The task identifier
            data: Task data to write

        Raises:
            Timeout: If lock cannot be acquired within timeout
        """
        task_file = self._task_file_path(task_id)
        lock_file = self._lock_file_path(task_id)
        tmp_file = task_file.with_suffix(".json.tmp")

        lock = FileLock(lock_file, timeout=self.lock_timeout)
        try:
            with lock:
                # Write to temporary file first
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)

                # Atomic rename
                tmp_file.replace(task_file)
        except Timeout:
            logger.error(f"Timeout acquiring lock for task {task_id}")
            raise
        finally:
            # Clean up tmp file if it still exists
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to clean up tmp file {tmp_file}: {e}")

    def _delete_task_file(self, task_id: str) -> bool:
        """Delete a task file with file locking.

        Args:
            task_id: The task identifier

        Returns:
            True if deleted, False if not found
        """
        task_file = self._task_file_path(task_id)
        if not task_file.exists():
            return False

        lock_file = self._lock_file_path(task_id)
        lock = FileLock(lock_file, timeout=self.lock_timeout)

        try:
            with lock:
                if task_file.exists():
                    task_file.unlink()
                    return True
                return False
        except Timeout:
            logger.error(f"Timeout acquiring lock for task {task_id}")
            raise
        finally:
            # Clean up lock file
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to clean up lock file {lock_file}: {e}")

    def _dict_to_task_out(self, data: dict) -> TaskOut:
        """Convert a dict to TaskOut model.

        Args:
            data: Task data dict

        Returns:
            TaskOut instance
        """
        # Parse datetime fields
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))

        return TaskOut(
            id=data["id"],
            name=data["name"],
            prompt=data["prompt"],
            schedule_desc=data["schedule_desc"],
            crontab=data["crontab"],
            webhook=data.get("webhook"),
            webhook_ids=data.get("webhook_ids", []),
            event_config=data.get("event_config", []),
            model_config_id=data.get("model_config_id"),
            status=data.get("status", "enabled"),
            created_at=created_at,
            updated_at=updated_at,
            next_run=data.get("next_run"),
            total_runs=data.get("total_runs", 0),
            success_runs=data.get("success_runs", 0),
            success_rate=data.get("success_rate", ""),
            recent_runs=data.get("recent_runs", []),
        )

    async def get_task(self, task_id: str) -> Optional[TaskOut]:
        """Retrieve a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            TaskOut if found, None otherwise
        """
        data = self._read_task_file(task_id)
        if data is None:
            return None

        return self._dict_to_task_out(data)

    async def list_tasks(self) -> List[TaskOut]:
        """List all tasks.

        Returns:
            List of all tasks
        """
        tasks = []

        # Iterate through all task files
        for task_file in self.tasks_dir.glob("task-*.json"):
            # Skip temporary and lock files
            if task_file.suffix == ".tmp" or task_file.name.endswith(".lock"):
                continue

            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    tasks.append(self._dict_to_task_out(data))
            except json.JSONDecodeError:
                logger.warning(f"Corrupted task file: {task_file}, skipping")
                continue
            except Exception as e:
                logger.error(f"Error reading task file {task_file}: {e}")
                continue

        return tasks

    async def create_task(self, task_data: TaskCreate) -> TaskOut:
        """Create a new task.

        Args:
            task_data: Task creation data

        Returns:
            The created task
        """
        # Generate new task ID
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Build task dict
        data = {
            "id": task_id,
            "name": task_data.name,
            "prompt": task_data.prompt,
            "schedule_desc": task_data.schedule_desc,
            "crontab": task_data.crontab or "",
            "webhook": task_data.webhook,
            "webhook_ids": task_data.webhook_ids or [],
            "event_config": task_data.event_config or [],
            "model_config_id": task_data.model_config_id,
            "status": task_data.status,
            "user_id": task_data.user_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "next_run": None,
            "total_runs": 0,
            "success_runs": 0,
            "success_rate": "",
            "recent_runs": [],
        }

        # Write to file
        self._write_task_file(task_id, data)

        return self._dict_to_task_out(data)

    async def update_task(self, task_id: str, task_data: TaskUpdate) -> Optional[TaskOut]:
        """Update an existing task.

        Args:
            task_id: The task identifier
            task_data: Task update data

        Returns:
            The updated task if found, None otherwise
        """
        # Read existing task
        data = self._read_task_file(task_id)
        if data is None:
            return None

        # Update fields
        now = datetime.now(timezone.utc)

        if task_data.name is not None:
            data["name"] = task_data.name
        if task_data.prompt is not None:
            data["prompt"] = task_data.prompt
        if task_data.schedule_desc is not None:
            data["schedule_desc"] = task_data.schedule_desc
        if task_data.crontab is not None:
            data["crontab"] = task_data.crontab
        if task_data.webhook is not None:
            data["webhook"] = task_data.webhook
        if task_data.webhook_ids is not None:
            data["webhook_ids"] = task_data.webhook_ids
        if task_data.event_config is not None:
            data["event_config"] = task_data.event_config
        if task_data.model_config_id is not None:
            data["model_config_id"] = task_data.model_config_id
        if task_data.status is not None:
            data["status"] = task_data.status
        if task_data.user_id is not None:
            data["user_id"] = task_data.user_id

        data["updated_at"] = now.isoformat()

        # Write updated data
        self._write_task_file(task_id, data)

        return self._dict_to_task_out(data)

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            True if deleted, False if not found
        """
        return self._delete_task_file(task_id)
