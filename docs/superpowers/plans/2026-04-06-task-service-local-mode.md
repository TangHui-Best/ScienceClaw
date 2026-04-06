# Task-Service Local Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable task-service to run without MongoDB by implementing local JSON file storage with repository pattern and file locking.

**Architecture:** Storage abstraction layer with LocalStorage and MongoStorage implementations. Separate JSON file per task in `tasks/` directory, separate JSON file per run in `runs/{task_id}/` directory. File locking via `filelock` library prevents corruption.

**Tech Stack:** Python 3.13, FastAPI, filelock, Pydantic v2, APScheduler (in-memory state)

---

## File Structure

**New files:**
- `RpaClaw/task-service/app/core/storage.py` - Storage interface and factory
- `RpaClaw/task-service/app/repositories/__init__.py` - Repository package
- `RpaClaw/task-service/app/repositories/base.py` - Abstract repository interfaces
- `RpaClaw/task-service/app/repositories/local_task_repo.py` - Local file-based task repository
- `RpaClaw/task-service/app/repositories/local_run_repo.py` - Local file-based run repository
- `RpaClaw/task-service/app/repositories/mongo_task_repo.py` - MongoDB task repository wrapper
- `RpaClaw/task-service/app/repositories/mongo_run_repo.py` - MongoDB run repository wrapper

**Modified files:**
- `RpaClaw/task-service/app/core/config.py` - Add STORAGE_BACKEND and LOCAL_DATA_DIR settings
- `RpaClaw/task-service/app/main.py` - Replace db lifecycle with storage backend
- `RpaClaw/task-service/app/api/tasks.py` - Replace db dependency with storage
- `RpaClaw/task-service/app/scheduler.py` - Replace db calls with storage
- `RpaClaw/task-service/requirements.txt` - Add filelock dependency

---

### Task 1: Add filelock dependency

**Files:**
- Modify: `RpaClaw/task-service/requirements.txt`

- [ ] **Step 1: Add filelock to requirements**

```txt
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
motor>=3.3.0
pydantic>=2.0
pydantic-settings>=2.0
shortuuid>=1.0.0
httpx>=0.26.0
croniter>=2.0.0
loguru>=0.7.0
filelock>=3.13.0
```

---

### Task 2: Add storage configuration

**Files:**
- Modify: `RpaClaw/task-service/app/core/config.py`

- [ ] **Step 1: Add storage backend settings**

```python
"""Task service configuration."""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # API
    api_host: str = os.environ.get("TASK_API_HOST", "0.0.0.0")
    api_port: int = int(os.environ.get("TASK_API_PORT", "8001"))

    # 展示用时间（下次执行、执行记录等）的时区，默认北京时间
    display_timezone: str = os.environ.get("DISPLAY_TIMEZONE", "Asia/Shanghai")

    # Storage backend: "local" or "docker" (MongoDB)
    storage_backend: str = os.environ.get("STORAGE_BACKEND", "docker")
    local_data_dir: str = os.environ.get("LOCAL_DATA_DIR", "./data")

    # MongoDB (same as main backend or dedicated)
    mongodb_host: str = os.environ.get("MONGODB_HOST", "localhost")
    mongodb_port: int = int(os.environ.get("MONGODB_PORT", "27014"))
    mongodb_db_name: str = os.environ.get("MONGODB_DB", "ai_agent")
    mongodb_username: str = os.environ.get("MONGODB_USER", "")
    mongodb_password: str = os.environ.get("MONGODB_PASSWORD", "")

    # Chat service (main backend) - for task execution
    chat_service_url: str = os.environ.get("CHAT_SERVICE_URL", "http://backend:8000")
    chat_service_api_key: str = os.environ.get("CHAT_SERVICE_API_KEY", "")

    # LLM for natural language -> crontab (optional, can use chat service)
    llm_api_key: str = os.environ.get("DS_API_KEY", "")
    llm_base_url: str = os.environ.get("DS_URL", "https://api.deepseek.com/v1")
    llm_model: str = os.environ.get("DS_MODEL", "deepseek-chat")


settings = Settings()
```

---

### Task 3: Create repository base interfaces

**Files:**
- Create: `RpaClaw/task-service/app/repositories/__init__.py`
- Create: `RpaClaw/task-service/app/repositories/base.py`

- [ ] **Step 1: Create repositories package init**

```python
"""Repository layer for task storage."""
```

- [ ] **Step 2: Create abstract repository interfaces**

```python
"""Abstract repository interfaces."""
from abc import ABC, abstractmethod
from typing import List, Optional

from app.models.task import TaskOut, TaskRunOut


class TaskRepository(ABC):
    """Abstract interface for task storage."""

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[TaskOut]:
        """Get task by ID."""
        pass

    @abstractmethod
    async def list_tasks(self) -> List[TaskOut]:
        """List all tasks."""
        pass

    @abstractmethod
    async def create_task(self, task_data: dict) -> TaskOut:
        """Create new task."""
        pass

    @abstractmethod
    async def update_task(self, task_id: str, updates: dict) -> Optional[TaskOut]:
        """Update task. Returns None if not found."""
        pass

    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """Delete task. Returns True if deleted, False if not found."""
        pass


class TaskRunRepository(ABC):
    """Abstract interface for task run storage."""

    @abstractmethod
    async def get_run(self, run_id: str) -> Optional[TaskRunOut]:
        """Get run by ID."""
        pass

    @abstractmethod
    async def list_runs(self, task_id: str, limit: int = 100, offset: int = 0) -> tuple[List[TaskRunOut], int]:
        """List runs for task. Returns (items, total_count)."""
        pass

    @abstractmethod
    async def create_run(self, run_data: dict) -> str:
        """Create new run. Returns run_id."""
        pass

    @abstractmethod
    async def update_run(self, run_id: str, updates: dict) -> Optional[TaskRunOut]:
        """Update run. Returns None if not found."""
        pass

    @abstractmethod
    async def count_runs(self, task_id: str, status: Optional[str] = None) -> int:
        """Count runs for task, optionally filtered by status."""
        pass

    @abstractmethod
    async def get_recent_run_statuses(self, task_id: str, limit: int = 7) -> List[str]:
        """Get recent run statuses for task."""
        pass
```

---

### Task 4: Implement local task repository

**Files:**
- Create: `RpaClaw/task-service/app/repositories/local_task_repo.py`

- [ ] **Step 1: Create local task repository with file operations**

```python
"""Local file-based task repository."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from filelock import FileLock, Timeout
from loguru import logger

from app.models.task import TaskOut
from app.repositories.base import TaskRepository


class LocalTaskRepository(TaskRepository):
    """File-based task storage using separate JSON files."""

    def __init__(self, tasks_dir: Path):
        self.tasks_dir = Path(tasks_dir)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"task-{task_id}.json"

    def _lock_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"task-{task_id}.json.lock"

    async def get_task(self, task_id: str) -> Optional[TaskOut]:
        """Get task by ID."""
        path = self._task_path(task_id)
        if not path.exists():
            return None
        
        lock = FileLock(self._lock_path(task_id), timeout=5)
        try:
            with lock:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return TaskOut(**data)
        except Timeout:
            logger.error(f"Timeout acquiring lock for task {task_id}")
            raise TimeoutError(f"Could not acquire lock for task {task_id}")
        except json.JSONDecodeError:
            logger.error(f"Corrupted task file: {path}")
            return None

    async def list_tasks(self) -> List[TaskOut]:
        """List all tasks."""
        tasks = []
        for path in self.tasks_dir.glob("task-*.json"):
            if path.suffix != ".json" or ".lock" in path.name:
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                tasks.append(TaskOut(**data))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Skip corrupted task file {path}: {e}")
        return tasks

    async def create_task(self, task_data: dict) -> TaskOut:
        """Create new task."""
        task_id = task_data["id"]
        path = self._task_path(task_id)
        
        if path.exists():
            raise ValueError(f"Task {task_id} already exists")
        
        lock = FileLock(self._lock_path(task_id), timeout=5)
        try:
            with lock:
                tmp_path = path.with_suffix('.tmp')
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(task_data, f, indent=2, default=str)
                os.replace(tmp_path, path)
            return TaskOut(**task_data)
        except Timeout:
            logger.error(f"Timeout acquiring lock for task {task_id}")
            raise TimeoutError(f"Could not acquire lock for task {task_id}")

    async def update_task(self, task_id: str, updates: dict) -> Optional[TaskOut]:
        """Update task. Returns None if not found."""
        path = self._task_path(task_id)
        if not path.exists():
            return None
        
        lock = FileLock(self._lock_path(task_id), timeout=5)
        try:
            with lock:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data.update(updates)
                tmp_path = path.with_suffix('.tmp')
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, default=str)
                os.replace(tmp_path, path)
            return TaskOut(**data)
        except Timeout:
            logger.error(f"Timeout acquiring lock for task {task_id}")
            raise TimeoutError(f"Could not acquire lock for task {task_id}")
        except json.JSONDecodeError:
            logger.error(f"Corrupted task file: {path}")
            return None

    async def delete_task(self, task_id: str) -> bool:
        """Delete task. Returns True if deleted, False if not found."""
        path = self._task_path(task_id)
        if not path.exists():
            return False
        
        lock = FileLock(self._lock_path(task_id), timeout=5)
        try:
            with lock:
                path.unlink()
            # Clean up lock file
            lock_path = self._lock_path(task_id)
            if lock_path.exists():
                lock_path.unlink()
            return True
        except Timeout:
            logger.error(f"Timeout acquiring lock for task {task_id}")
            raise TimeoutError(f"Could not acquire lock for task {task_id}")
```

---

### Task 5: Implement local run repository

**Files:**
- Create: `RpaClaw/task-service/app/repositories/local_run_repo.py`

- [ ] **Step 1: Create local run repository with file operations**

```python
"""Local file-based task run repository."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import shortuuid
from filelock import FileLock, Timeout
from loguru import logger

from app.models.task import TaskRunOut
from app.repositories.base import TaskRunRepository


class LocalRunRepository(TaskRunRepository):
    """File-based run storage using separate JSON files per run."""

    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _task_runs_dir(self, task_id: str) -> Path:
        return self.runs_dir / f"task-{task_id}"

    def _run_path(self, task_id: str, run_id: str) -> Path:
        return self._task_runs_dir(task_id) / f"run-{run_id}.json"

    def _lock_path(self, task_id: str, run_id: str) -> Path:
        return self._task_runs_dir(task_id) / f"run-{run_id}.json.lock"

    async def get_run(self, run_id: str) -> Optional[TaskRunOut]:
        """Get run by ID. Scans all task directories."""
        for task_dir in self.runs_dir.glob("task-*"):
            if not task_dir.is_dir():
                continue
            run_path = task_dir / f"run-{run_id}.json"
            if run_path.exists():
                try:
                    with open(run_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    return TaskRunOut(**data)
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"Skip corrupted run file {run_path}: {e}")
        return None

    async def list_runs(self, task_id: str, limit: int = 100, offset: int = 0) -> tuple[List[TaskRunOut], int]:
        """List runs for task. Returns (items, total_count)."""
        task_runs_dir = self._task_runs_dir(task_id)
        if not task_runs_dir.exists():
            return [], 0

        runs = []
        for path in task_runs_dir.glob("run-*.json"):
            if path.suffix != ".json" or ".lock" in path.name:
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                runs.append(TaskRunOut(**data))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Skip corrupted run file {path}: {e}")

        # Sort by start_time descending
        runs.sort(key=lambda r: r.start_time or datetime.min, reverse=True)
        total = len(runs)
        items = runs[offset:offset + limit]
        return items, total

    async def create_run(self, run_data: dict) -> str:
        """Create new run. Returns run_id."""
        run_id = shortuuid.uuid()
        run_data["id"] = run_id
        task_id = run_data["task_id"]
        
        task_runs_dir = self._task_runs_dir(task_id)
        task_runs_dir.mkdir(parents=True, exist_ok=True)
        
        path = self._run_path(task_id, run_id)
        lock = FileLock(self._lock_path(task_id, run_id), timeout=5)
        
        try:
            with lock:
                tmp_path = path.with_suffix('.tmp')
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(run_data, f, indent=2, default=str)
                os.replace(tmp_path, path)
            return run_id
        except Timeout:
            logger.error(f"Timeout acquiring lock for run {run_id}")
            raise TimeoutError(f"Could not acquire lock for run {run_id}")

    async def update_run(self, run_id: str, updates: dict) -> Optional[TaskRunOut]:
        """Update run. Returns None if not found."""
        # Find run across all task directories
        for task_dir in self.runs_dir.glob("task-*"):
            if not task_dir.is_dir():
                continue
            run_path = task_dir / f"run-{run_id}.json"
            if run_path.exists():
                task_id = task_dir.name.replace("task-", "")
                lock = FileLock(self._lock_path(task_id, run_id), timeout=5)
                try:
                    with lock:
                        with open(run_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        data.update(updates)
                        tmp_path = run_path.with_suffix('.tmp')
                        with open(tmp_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, default=str)
                        os.replace(tmp_path, run_path)
                    return TaskRunOut(**data)
                except Timeout:
                    logger.error(f"Timeout acquiring lock for run {run_id}")
                    raise TimeoutError(f"Could not acquire lock for run {run_id}")
                except json.JSONDecodeError:
                    logger.error(f"Corrupted run file: {run_path}")
                    return None
        return None

    async def count_runs(self, task_id: str, status: Optional[str] = None) -> int:
        """Count runs for task, optionally filtered by status."""
        task_runs_dir = self._task_runs_dir(task_id)
        if not task_runs_dir.exists():
            return 0

        count = 0
        for path in task_runs_dir.glob("run-*.json"):
            if path.suffix != ".json" or ".lock" in path.name:
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if status is None or data.get("status") == status:
                    count += 1
            except (json.JSONDecodeError, Exception):
                pass
        return count

    async def get_recent_run_statuses(self, task_id: str, limit: int = 7) -> List[str]:
        """Get recent run statuses for task."""
        task_runs_dir = self._task_runs_dir(task_id)
        if not task_runs_dir.exists():
            return []

        runs = []
        for path in task_runs_dir.glob("run-*.json"):
            if path.suffix != ".json" or ".lock" in path.name:
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                runs.append(data)
            except (json.JSONDecodeError, Exception):
                pass

        # Sort by start_time descending
        runs.sort(key=lambda r: r.get("start_time") or "", reverse=True)
        return [r.get("status", "failed") for r in runs[:limit]]
```

---

### Task 6: Implement MongoDB repository wrappers

**Files:**
- Create: `RpaClaw/task-service/app/repositories/mongo_task_repo.py`
- Create: `RpaClaw/task-service/app/repositories/mongo_run_repo.py`

- [ ] **Step 1: Create MongoDB task repository wrapper**

```python
"""MongoDB task repository wrapper."""
from typing import List, Optional

from app.core.db import db
from app.models.task import TaskOut, task_doc_to_out
from app.repositories.base import TaskRepository


class MongoTaskRepository(TaskRepository):
    """MongoDB-based task storage."""

    async def get_task(self, task_id: str) -> Optional[TaskOut]:
        """Get task by ID."""
        doc = await db.get_collection("tasks").find_one({"_id": task_id})
        if not doc:
            return None
        return task_doc_to_out(doc)

    async def list_tasks(self) -> List[TaskOut]:
        """List all tasks."""
        cursor = db.get_collection("tasks").find({}).sort("created_at", -1)
        tasks = []
        async for doc in cursor:
            tasks.append(task_doc_to_out(doc))
        return tasks

    async def create_task(self, task_data: dict) -> TaskOut:
        """Create new task."""
        doc = {**task_data, "_id": task_data["id"]}
        await db.get_collection("tasks").insert_one(doc)
        return task_doc_to_out(doc)

    async def update_task(self, task_id: str, updates: dict) -> Optional[TaskOut]:
        """Update task. Returns None if not found."""
        result = await db.get_collection("tasks").update_one(
            {"_id": task_id},
            {"$set": updates}
        )
        if result.matched_count == 0:
            return None
        doc = await db.get_collection("tasks").find_one({"_id": task_id})
        return task_doc_to_out(doc)

    async def delete_task(self, task_id: str) -> bool:
        """Delete task. Returns True if deleted, False if not found."""
        result = await db.get_collection("tasks").delete_one({"_id": task_id})
        return result.deleted_count > 0
```

- [ ] **Step 2: Create MongoDB run repository wrapper**

```python
"""MongoDB run repository wrapper."""
from typing import List, Optional

from app.core.db import db
from app.models.task import TaskRunOut, task_run_doc_to_out
from app.repositories.base import TaskRunRepository


class MongoRunRepository(TaskRunRepository):
    """MongoDB-based run storage."""

    async def get_run(self, run_id: str) -> Optional[TaskRunOut]:
        """Get run by ID."""
        doc = await db.get_collection("task_runs").find_one({"_id": run_id})
        if not doc:
            return None
        return task_run_doc_to_out(doc)

    async def list_runs(self, task_id: str, limit: int = 100, offset: int = 0) -> tuple[List[TaskRunOut], int]:
        """List runs for task. Returns (items, total_count)."""
        coll = db.get_collection("task_runs")
        total = await coll.count_documents({"task_id": task_id})
        cursor = (
            coll.find({"task_id": task_id})
            .sort("start_time", -1)
            .skip(offset)
            .limit(limit)
        )
        items = [task_run_doc_to_out(d) async for d in cursor]
        return items, total

    async def create_run(self, run_data: dict) -> str:
        """Create new run. Returns run_id."""
        result = await db.get_collection("task_runs").insert_one(run_data)
        return str(result.inserted_id)

    async def update_run(self, run_id: str, updates: dict) -> Optional[TaskRunOut]:
        """Update run. Returns None if not found."""
        result = await db.get_collection("task_runs").update_one(
            {"_id": run_id},
            {"$set": updates}
        )
        if result.matched_count == 0:
            return None
        doc = await db.get_collection("task_runs").find_one({"_id": run_id})
        return task_run_doc_to_out(doc)

    async def count_runs(self, task_id: str, status: Optional[str] = None) -> int:
        """Count runs for task, optionally filtered by status."""
        query = {"task_id": task_id}
        if status:
            query["status"] = status
        return await db.get_collection("task_runs").count_documents(query)

    async def get_recent_run_statuses(self, task_id: str, limit: int = 7) -> List[str]:
        """Get recent run statuses for task."""
        cursor = (
            db.get_collection("task_runs")
            .find({"task_id": task_id})
            .sort("start_time", -1)
            .limit(limit)
        )
        return [doc.get("status", "failed") async for doc in cursor]
```

---

### Task 7: Create storage abstraction layer

**Files:**
- Create: `RpaClaw/task-service/app/core/storage.py`

- [ ] **Step 1: Create storage interface and factory**

```python
"""Storage abstraction layer."""
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings
from app.repositories.base import TaskRepository, TaskRunRepository


class Storage(ABC):
    """Abstract storage interface."""

    @abstractmethod
    def get_task_repo(self) -> TaskRepository:
        """Get task repository."""
        pass

    @abstractmethod
    def get_run_repo(self) -> TaskRunRepository:
        """Get run repository."""
        pass

    @abstractmethod
    async def connect(self) -> None:
        """Initialize storage connection."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close storage connection."""
        pass


class LocalStorage(Storage):
    """Local file-based storage."""

    def __init__(self, data_dir: str):
        self.base_dir = Path(data_dir) / "task-service"
        self.tasks_dir = self.base_dir / "tasks"
        self.runs_dir = self.base_dir / "runs"
        self._task_repo = None
        self._run_repo = None

    def get_task_repo(self) -> TaskRepository:
        """Get task repository."""
        if self._task_repo is None:
            from app.repositories.local_task_repo import LocalTaskRepository
            self._task_repo = LocalTaskRepository(self.tasks_dir)
        return self._task_repo

    def get_run_repo(self) -> TaskRunRepository:
        """Get run repository."""
        if self._run_repo is None:
            from app.repositories.local_run_repo import LocalRunRepository
            self._run_repo = LocalRunRepository(self.runs_dir)
        return self._run_repo

    async def connect(self) -> None:
        """Initialize storage - create directories."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        """Close storage - no-op for local files."""
        pass


class MongoStorage(Storage):
    """MongoDB-based storage."""

    def __init__(self):
        self._task_repo = None
        self._run_repo = None

    def get_task_repo(self) -> TaskRepository:
        """Get task repository."""
        if self._task_repo is None:
            from app.repositories.mongo_task_repo import MongoTaskRepository
            self._task_repo = MongoTaskRepository()
        return self._task_repo

    def get_run_repo(self) -> TaskRunRepository:
        """Get run repository."""
        if self._run_repo is None:
            from app.repositories.mongo_run_repo import MongoRunRepository
            self._run_repo = MongoRunRepository()
        return self._run_repo

    async def connect(self) -> None:
        """Initialize MongoDB connection."""
        from app.core.db import db
        await db.connect()

    async def close(self) -> None:
        """Close MongoDB connection."""
        from app.core.db import db
        await db.close()


def get_storage() -> Storage:
    """Get storage backend based on configuration."""
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalStorage(settings.local_data_dir)
    else:
        return MongoStorage()


# Global storage instance
storage: Storage = None


def get_storage_instance() -> Storage:
    """Get global storage instance."""
    global storage
    if storage is None:
        storage = get_storage()
    return storage
```

---

### Task 8: Update main.py to use storage abstraction

**Files:**
- Modify: `RpaClaw/task-service/app/main.py`

- [ ] **Step 1: Replace db lifecycle with storage**

```python
"""Task Service FastAPI application."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.tasks import router as tasks_router
from app.api.webhooks import router as webhooks_router
from app.core.storage import get_storage_instance
from app.scheduler import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = get_storage_instance()
    await storage.connect()
    logger.info(f"Storage backend initialized: {storage.__class__.__name__}")
    scheduler.start()
    yield
    scheduler.stop()
    await storage.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Task Scheduler Service", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(tasks_router)
    app.include_router(webhooks_router)
    logger.info("Task service API ready")
    return app


app = create_app()
```

---

### Task 9: Update tasks.py API routes (Part 1 - CRUD operations)

**Files:**
- Modify: `RpaClaw/task-service/app/api/tasks.py`

- [ ] **Step 1: Update imports and create_task endpoint**

Replace the imports section and create_task function:

```python
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
    now = datetime.now(timezone.utc)
    task_id = shortuuid.uuid()
    task_data: Dict[str, Any] = {
        "id": task_id,
        "name": body.name,
        "prompt": body.prompt,
        "schedule_desc": body.schedule_desc,
        "crontab": crontab or "",
        "webhook": body.webhook,
        "webhook_ids": body.webhook_ids or [],
        "event_config": body.event_config or [],
        "model_config_id": (body.model_config_id or "").strip() or None,
        "status": body.status or "enabled",
        "user_id": (body.user_id or "").strip() or None,
        "created_at": now,
        "updated_at": now,
    }
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    task = await task_repo.create_task(task_data)
    logger.info(f"Task created: {task_id} crontab={crontab}")
    return task
```

---

### Task 10: Update tasks.py API routes (Part 2 - list/get/update/delete)

**Files:**
- Modify: `RpaClaw/task-service/app/api/tasks.py`

- [ ] **Step 1: Update list_tasks endpoint**

Replace the list_tasks function:

```python
@router.get("", response_model=List[TaskOut])
async def list_tasks() -> List[TaskOut]:
    """List all tasks with stats: next_run, total_runs, success_rate, recent_runs."""
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    run_repo = storage.get_run_repo()
    
    tasks = await task_repo.list_tasks()
    
    # For MongoDB mode, filter out deleted webhook_ids
    if settings.storage_backend.lower() == "docker":
        from app.core.db import db
        webhooks_coll = db.get_collection("webhooks")
        valid_wh_ids = {doc["_id"] async for doc in webhooks_coll.find({}, {"_id": 1})}
    else:
        valid_wh_ids = None
    
    result = []
    for task in tasks:
        data = task.model_dump()
        tid = task.id
        
        # Filter webhook_ids if in MongoDB mode
        if valid_wh_ids is not None:
            raw_wh_ids = data.get("webhook_ids") or []
            if raw_wh_ids:
                data["webhook_ids"] = [wid for wid in raw_wh_ids if wid in valid_wh_ids]
        
        data["next_run"] = _compute_next_run_str(task.crontab)
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
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=TaskOut)
async def update_task(task_id: str, body: TaskUpdate) -> TaskOut:
    """Update a task."""
    storage = get_storage_instance()
    task_repo = storage.get_task_repo()
    task = await task_repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    now = datetime.now(timezone.utc)
    update: Dict[str, Any] = {"updated_at": now}
    if body.name is not None:
        update["name"] = body.name
    if body.prompt is not None:
        update["prompt"] = body.prompt
    if body.schedule_desc is not None:
        update["schedule_desc"] = body.schedule_desc
        if body.crontab is not None:
            update["crontab"] = body.crontab
        else:
            try:
                mid = body.model_config_id or task.model_config_id
                crontab = await parse_schedule_to_crontab(body.schedule_desc, model_config_id=mid)
                if crontab:
                    update["crontab"] = crontab
            except ScheduleParseError as e:
                detail = {"message": e.message, "suggestions": e.suggestions} if e.suggestions else e.message
                raise HTTPException(status_code=400, detail=detail)
    elif body.crontab is not None:
        update["crontab"] = body.crontab
    if body.webhook is not None:
        update["webhook"] = body.webhook
    if body.webhook_ids is not None:
        update["webhook_ids"] = body.webhook_ids
    if body.event_config is not None:
        update["event_config"] = body.event_config
    if body.model_config_id is not None:
        update["model_config_id"] = (body.model_config_id or "").strip() or None
    if body.status is not None:
        update["status"] = body.status
    if body.user_id is not None:
        update["user_id"] = (body.user_id or "").strip() or None
    
    updated_task = await task_repo.update_task(task_id, update)
    return updated_task


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
    items, total = await run_repo.list_runs(task_id, limit=limit, offset=offset)
    return TaskRunsPage(items=items, total=total)
```

---

### Task 11: Update scheduler.py to use storage abstraction

**Files:**
- Modify: `RpaClaw/task-service/app/scheduler.py`

- [ ] **Step 1: Replace db calls with storage in scheduler**

Replace the entire file content with storage-based implementation. Key changes:
- Import `get_storage_instance` instead of `db`
- In `_check_due_tasks`: Use `task_repo.list_tasks()` instead of MongoDB cursor
- In `_execute_task`: Use `task_repo.get_task()` and `run_repo.create_run()`/`update_run()`
- In notification helpers: Only access MongoDB webhooks collection when `storage_backend == "docker"`

---

### Task 12: Test local mode functionality

**Files:**
- Test: Manual testing with local mode

- [ ] **Step 1: Set environment variables for local mode**

Set STORAGE_BACKEND=local and LOCAL_DATA_DIR=./test_data

- [ ] **Step 2: Start task-service**

Run: `cd RpaClaw/task-service && uv run uvicorn app.main:app --host 127.0.0.1 --port 12002`
Expected: Service starts without MongoDB connection errors

- [ ] **Step 3: Create a test task via API**

Use curl POST to create task with disabled status
Expected: Task created, JSON file appears in ./test_data/task-service/tasks/

- [ ] **Step 4: List tasks**

Use curl GET /tasks
Expected: Returns task list with stats

- [ ] **Step 5: Verify file structure**

Check directories exist with task JSON files

- [ ] **Step 6: Update task**

Use curl PUT to update task name
Expected: Task updated, file modified

- [ ] **Step 7: Delete task**

Use curl DELETE
Expected: Task deleted, file removed

- [ ] **Step 8: Test MongoDB mode still works**

Set STORAGE_BACKEND=docker and restart
Expected: Service starts with MongoDB connection

---

## Success Criteria

1. Task-service starts without MongoDB when STORAGE_BACKEND=local
2. All CRUD operations work via API in local mode
3. Tasks persist as JSON files in correct directory structure
4. File locking prevents corruption during concurrent access
5. MongoDB mode continues working unchanged
6. Scheduler executes tasks correctly in both modes
7. API responses match existing format
