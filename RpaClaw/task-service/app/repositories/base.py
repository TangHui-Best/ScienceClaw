"""Abstract base classes for task and task_run repositories."""
from abc import ABC, abstractmethod
from typing import List, Optional

from app.models.task import TaskCreate, TaskOut, TaskRunOut, TaskUpdate


class TaskRepository(ABC):
    """Abstract base class for task storage operations."""

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[TaskOut]:
        """Retrieve a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            TaskOut if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_tasks(self) -> List[TaskOut]:
        """List all tasks.

        Returns:
            List of all tasks
        """
        pass

    @abstractmethod
    async def create_task(self, task_data: TaskCreate) -> TaskOut:
        """Create a new task.

        Args:
            task_data: Task creation data

        Returns:
            The created task
        """
        pass

    @abstractmethod
    async def update_task(self, task_id: str, task_data: TaskUpdate) -> Optional[TaskOut]:
        """Update an existing task.

        Args:
            task_id: The task identifier
            task_data: Task update data

        Returns:
            The updated task if found, None otherwise
        """
        pass

    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            True if deleted, False if not found
        """
        pass


class TaskRunRepository(ABC):
    """Abstract base class for task_run storage operations."""

    @abstractmethod
    async def get_run(self, run_id: str) -> Optional[TaskRunOut]:
        """Retrieve a task run by ID.

        Args:
            run_id: The run identifier

        Returns:
            TaskRunOut if found, None otherwise
        """
        pass

    @abstractmethod
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
            List of task runs
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def count_runs(self, task_id: str, status: Optional[str] = None) -> int:
        """Count runs for a task, optionally filtered by status.

        Args:
            task_id: The task identifier
            status: Optional status filter (e.g. "success", "failed")

        Returns:
            Number of matching runs
        """
        pass

    @abstractmethod
    async def get_recent_run_statuses(self, task_id: str, limit: int = 7) -> List[str]:
        """Get recent run statuses for a task.

        Args:
            task_id: The task identifier
            limit: Number of recent runs to retrieve

        Returns:
            List of status strings (success | failed) in reverse chronological order
        """
        pass
