"""Storage abstraction layer for task-service.

Provides a unified interface for storage backends (local file-based or MongoDB).
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.repositories.base import TaskRepository, TaskRunRepository


class Storage(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def get_task_repo(self) -> TaskRepository:
        """Return the task repository instance."""
        pass

    @abstractmethod
    def get_run_repo(self) -> TaskRunRepository:
        """Return the task run repository instance."""
        pass

    @abstractmethod
    async def connect(self) -> None:
        """Initialize storage connections and resources."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Release storage connections and resources."""
        pass


class LocalStorage(Storage):
    """File-based local storage backend."""

    def __init__(self, data_dir: str):
        """Initialize local storage.

        Args:
            data_dir: Base directory for local data storage.
                      Actual data is stored under <data_dir>/task-service/
        """
        self.base_dir = Path(data_dir) / "task-service"
        self._task_repo: Optional[TaskRepository] = None
        self._run_repo: Optional[TaskRunRepository] = None

    def get_task_repo(self) -> TaskRepository:
        """Return the local task repository, initializing lazily."""
        if self._task_repo is None:
            from app.repositories.local_task_repo import LocalTaskRepository
            self._task_repo = LocalTaskRepository(str(self.base_dir))
        return self._task_repo

    def get_run_repo(self) -> TaskRunRepository:
        """Return the local run repository, initializing lazily."""
        if self._run_repo is None:
            from app.repositories.local_run_repo import LocalRunRepository
            self._run_repo = LocalRunRepository(str(self.base_dir))
        return self._run_repo

    async def connect(self) -> None:
        """Create required directories for local storage."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        """No-op for local storage."""
        pass


class MongoStorage(Storage):
    """MongoDB-backed storage backend."""

    def __init__(self):
        self._task_repo: Optional[TaskRepository] = None
        self._run_repo: Optional[TaskRunRepository] = None

    def get_task_repo(self) -> TaskRepository:
        """Return the MongoDB task repository, initializing lazily."""
        if self._task_repo is None:
            from app.repositories.mongo_task_repo import MongoTaskRepository
            self._task_repo = MongoTaskRepository()
        return self._task_repo

    def get_run_repo(self) -> TaskRunRepository:
        """Return the MongoDB run repository, initializing lazily."""
        if self._run_repo is None:
            from app.repositories.mongo_run_repo import MongoRunRepository
            self._run_repo = MongoRunRepository()
        return self._run_repo

    async def connect(self) -> None:
        """Connect to MongoDB."""
        from app.core.db import db
        await db.connect()

    async def close(self) -> None:
        """Close MongoDB connection."""
        from app.core.db import db
        await db.close()


# Module-level singleton
storage: Optional[Storage] = None


def get_storage() -> Storage:
    """Create a new Storage instance based on current settings.

    Reads settings.storage_backend to determine which backend to use:
    - "local": LocalStorage using settings.local_data_dir
    - anything else (e.g. "docker"): MongoStorage

    Returns:
        A new Storage instance for the configured backend.
    """
    from app.core.config import settings

    if settings.storage_backend == "local":
        return LocalStorage(settings.local_data_dir)
    return MongoStorage()


def get_storage_instance() -> Storage:
    """Return the global Storage singleton, creating it if necessary.

    Returns:
        The module-level singleton Storage instance.
    """
    global storage
    if storage is None:
        storage = get_storage()
    return storage
