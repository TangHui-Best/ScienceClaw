"""Local file-based task run repository with file locking."""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import shortuuid
from filelock import FileLock, Timeout

from app.models.task import TaskRunOut
from app.repositories.base import TaskRunRepository

logger = logging.getLogger(__name__)


class LocalRunRepository(TaskRunRepository):
    """File-based task run repository with atomic writes and file locking."""

    def __init__(self, data_dir: str):
        """Initialize the local run repository.

        Args:
            data_dir: Base directory for data storage
        """
        self.data_dir = Path(data_dir)
        self.runs_dir = self.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.lock_timeout = 5.0

    def _task_runs_dir(self, task_id: str) -> Path:
        """Get the directory for a task's runs.

        Args:
            task_id: The task identifier

        Returns:
            Path to the task's runs directory
        """
        return self.runs_dir / f"task-{task_id}"

    def _run_file_path(self, task_id: str, run_id: str) -> Path:
        """Get the file path for a run.

        Args:
            task_id: The task identifier
            run_id: The run identifier

        Returns:
            Path to the run JSON file
        """
        return self._task_runs_dir(task_id) / f"run-{run_id}.json"

    def _lock_file_path(self, task_id: str, run_id: str) -> Path:
        """Get the lock file path for a run.

        Args:
            task_id: The task identifier
            run_id: The run identifier

        Returns:
            Path to the lock file
        """
        return self._task_runs_dir(task_id) / f"run-{run_id}.json.lock"

    def _find_run_file(self, run_id: str) -> Optional[Path]:
        """Find a run file by searching all task directories.

        Args:
            run_id: The run identifier

        Returns:
            Path to the run file if found, None otherwise
        """
        # Search all task-* directories for the run file
        for task_dir in self.runs_dir.glob("task-*"):
            if not task_dir.is_dir():
                continue

            run_file = task_dir / f"run-{run_id}.json"
            if run_file.exists():
                return run_file

        return None

    def _read_run_file(self, run_file: Path) -> Optional[dict]:
        """Read a run file without locking (for read operations).

        Args:
            run_file: Path to the run file

        Returns:
            Run data dict or None if not found/corrupted
        """
        if not run_file.exists():
            return None

        try:
            with open(run_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Corrupted run file: {run_file}, skipping")
            return None
        except Exception as e:
            logger.error(f"Error reading run file {run_file}: {e}")
            return None

    def _write_run_file(self, task_id: str, run_id: str, data: dict) -> None:
        """Write a run file atomically with file locking.

        Args:
            task_id: The task identifier
            run_id: The run identifier
            data: Run data to write

        Raises:
            Timeout: If lock cannot be acquired within timeout
        """
        # Ensure task runs directory exists
        task_runs_dir = self._task_runs_dir(task_id)
        task_runs_dir.mkdir(parents=True, exist_ok=True)

        run_file = self._run_file_path(task_id, run_id)
        lock_file = self._lock_file_path(task_id, run_id)
        tmp_file = run_file.with_suffix(".json.tmp")

        lock = FileLock(lock_file, timeout=self.lock_timeout)
        try:
            with lock:
                # Write to temporary file first
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)

                # Atomic rename
                tmp_file.replace(run_file)
        except Timeout:
            logger.error(f"Timeout acquiring lock for run {run_id}")
            raise
        finally:
            # Clean up tmp file if it still exists
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to clean up tmp file {tmp_file}: {e}")

    def _dict_to_run_out(self, data: dict) -> TaskRunOut:
        """Convert a dict to TaskRunOut model.

        Args:
            data: Run data dict

        Returns:
            TaskRunOut instance
        """
        # Parse datetime fields
        start_time = data.get("start_time")
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))

        end_time = data.get("end_time")
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

        return TaskRunOut(
            id=data["id"],
            task_id=data["task_id"],
            status=data["status"],
            chat_id=data.get("chat_id"),
            start_time=start_time,
            end_time=end_time,
            result=data.get("result"),
            error=data.get("error"),
        )

    async def get_run(self, run_id: str) -> Optional[TaskRunOut]:
        """Retrieve a task run by ID.

        Args:
            run_id: The run identifier

        Returns:
            TaskRunOut if found, None otherwise
        """
        run_file = self._find_run_file(run_id)
        if run_file is None:
            return None

        data = self._read_run_file(run_file)
        if data is None:
            return None

        return self._dict_to_run_out(data)

    async def list_runs(
        self,
        task_id: str,
        skip: int = 0,
        limit: int = 20
    ) -> List[TaskRunOut]:
        """List task runs for a specific task with pagination.

        Args:
            task_id: The task identifier
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of task runs sorted by start_time descending
        """
        task_runs_dir = self._task_runs_dir(task_id)
        if not task_runs_dir.exists():
            return []

        runs = []

        # Read all run files for this task
        for run_file in task_runs_dir.glob("run-*.json"):
            # Skip temporary and lock files
            if run_file.suffix == ".tmp" or run_file.name.endswith(".lock"):
                continue

            data = self._read_run_file(run_file)
            if data is not None:
                runs.append(self._dict_to_run_out(data))

        # Sort by start_time descending (most recent first)
        runs.sort(
            key=lambda r: r.start_time if r.start_time else datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )

        # Apply pagination
        return runs[skip:skip + limit]

    async def create_run(
        self,
        task_id: str,
        status: str,
        chat_id: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None
    ) -> TaskRunOut:
        """Create a new task run record.

        Args:
            task_id: The task identifier
            status: Run status (success | failed)
            chat_id: Associated chat session ID
            result: Run result message
            error: Error message if failed

        Returns:
            The created task run
        """
        # Generate new run ID using shortuuid
        run_id = shortuuid.uuid()
        now = datetime.now(timezone.utc)

        # Build run dict
        data = {
            "id": run_id,
            "task_id": task_id,
            "status": status,
            "chat_id": chat_id,
            "start_time": now.isoformat(),
            "end_time": None,
            "result": result,
            "error": error,
        }

        # Write to file
        self._write_run_file(task_id, run_id, data)

        return self._dict_to_run_out(data)

    async def update_run(
        self,
        run_id: str,
        status: Optional[str] = None,
        chat_id: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None
    ) -> Optional[TaskRunOut]:
        """Update an existing task run.

        Args:
            run_id: The run identifier
            status: New status
            chat_id: Associated chat session ID
            result: Run result message
            error: Error message

        Returns:
            The updated task run if found, None otherwise
        """
        # Find the run file
        run_file = self._find_run_file(run_id)
        if run_file is None:
            return None

        # Read existing run
        data = self._read_run_file(run_file)
        if data is None:
            return None

        # Update fields
        now = datetime.now(timezone.utc)

        if status is not None:
            data["status"] = status
        if chat_id is not None:
            data["chat_id"] = chat_id
        if result is not None:
            data["result"] = result
        if error is not None:
            data["error"] = error

        # Set end_time if status is being updated to a final state
        if status in ("success", "failed"):
            data["end_time"] = now.isoformat()

        # Extract task_id from data
        task_id = data["task_id"]

        # Write updated data
        self._write_run_file(task_id, run_id, data)

        return self._dict_to_run_out(data)

    async def count_runs(self, task_id: str, status: Optional[str] = None) -> int:
        """Count runs for a task, optionally filtered by status.

        Args:
            task_id: The task identifier
            status: Optional status filter

        Returns:
            Number of matching runs
        """
        task_runs_dir = self._task_runs_dir(task_id)
        if not task_runs_dir.exists():
            return 0

        count = 0
        for run_file in task_runs_dir.glob("run-*.json"):
            # Skip temporary and lock files
            if run_file.suffix == ".tmp" or run_file.name.endswith(".lock"):
                continue

            data = self._read_run_file(run_file)
            if data is not None:
                if status is None or data.get("status") == status:
                    count += 1

        return count

    async def get_recent_run_statuses(self, task_id: str, limit: int = 7) -> List[str]:
        """Get recent run statuses for a task.

        Args:
            task_id: The task identifier
            limit: Number of recent runs to retrieve

        Returns:
            List of status strings (success | failed) in reverse chronological order
        """
        task_runs_dir = self._task_runs_dir(task_id)
        if not task_runs_dir.exists():
            return []

        runs = []

        # Read all run files for this task
        for run_file in task_runs_dir.glob("run-*.json"):
            # Skip temporary and lock files
            if run_file.suffix == ".tmp" or run_file.name.endswith(".lock"):
                continue

            data = self._read_run_file(run_file)
            if data is not None:
                runs.append(self._dict_to_run_out(data))

        # Sort by start_time descending (most recent first)
        runs.sort(
            key=lambda r: r.start_time if r.start_time else datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )

        # Return only the statuses of the most recent runs
        return [run.status for run in runs[:limit]]
