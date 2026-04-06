# Task-Service Local Mode Design

## Goal

Enable task-service to run without MongoDB dependency by implementing local file system storage, matching backend's local mode architecture.

## Architecture

Task-service will support two storage backends via `STORAGE_BACKEND` environment variable:
- **docker mode**: Existing MongoDB implementation (unchanged)
- **local mode**: New JSON file-based storage with separate files per task

Storage abstraction layer with repository pattern ensures API routes remain unchanged. File locking prevents corruption during concurrent access.

## Tech Stack

- **Storage**: JSON files with separate file per task
- **Locking**: `filelock` library (cross-platform)
- **Pattern**: Repository pattern with abstract Storage interface
- **Atomic writes**: Temp file + rename strategy

---

## Directory Structure

Local storage uses `{LOCAL_DATA_DIR}/task-service/` directory:

```
task-service/
├── tasks/
│   ├── task-{uuid}.json          # Task definition
│   ├── task-{uuid}.json
│   └── ...
└── runs/
    ├── task-{uuid}/               # Runs for specific task
    │   ├── run-{timestamp}.json
    │   ├── run-{timestamp}.json
    │   └── ...
    └── task-{uuid}/
        └── ...
```

**Task file format** (`task-{uuid}.json`):
```json
{
  "id": "uuid",
  "name": "Task name",
  "description": "Description",
  "schedule": "0 9 * * *",
  "action": {
    "type": "http",
    "config": {...}
  },
  "enabled": true,
  "created_at": "2026-04-06T10:00:00Z",
  "updated_at": "2026-04-06T10:00:00Z"
}
```

**Run file format** (`run-{timestamp}.json`):
```json
{
  "id": "uuid",
  "task_id": "task-uuid",
  "status": "success",
  "started_at": "2026-04-06T09:00:00Z",
  "finished_at": "2026-04-06T09:05:00Z",
  "result": {...},
  "error": null
}
```

## Repository Classes

### TaskRepository

Manages task definition files in `tasks/` directory.

**Methods:**
- `get_task(task_id: str) -> Optional[Task]` - Read single task file
- `list_tasks() -> List[Task]` - Scan directory, read all task files
- `create_task(task: Task) -> Task` - Write new task file with lock
- `update_task(task_id: str, updates: dict) -> Task` - Read, modify, write with lock
- `delete_task(task_id: str) -> bool` - Delete task file with lock

**File operations:**
1. Acquire lock on `{file_path}.lock`
2. Read existing file (if update/delete)
3. Write to `{file_path}.tmp`
4. Rename `.tmp` to actual file (atomic)
5. Release lock

**Error handling:**
- Lock timeout (5s) → raise `TimeoutError`
- File not found → return `None` for get, skip for list
- JSON decode error → log warning, skip file

### TaskRunRepository

Manages execution history files in `runs/{task_id}/` directories.

**Methods:**
- `get_run(task_id: str, run_id: str) -> Optional[TaskRun]` - Read specific run file
- `list_runs(task_id: str, limit: int = 100) -> List[TaskRun]` - List runs for task, sorted by timestamp descending
- `create_run(run: TaskRun) -> TaskRun` - Write new run file with lock
- `update_run(task_id: str, run_id: str, updates: dict) -> TaskRun` - Update run status/result with lock

**File naming:**
- Use ISO timestamp for sorting: `run-{started_at_iso}.json`
- Example: `run-2026-04-06T09:00:00.123456.json`

**Directory creation:**
- Auto-create `runs/{task_id}/` on first run for task

## Storage Abstraction

### Storage Interface

Abstract base class defining storage contract:

```python
class Storage(ABC):
    @abstractmethod
    async def get_task_repo(self) -> TaskRepository:
        pass
    
    @abstractmethod
    async def get_run_repo(self) -> TaskRunRepository:
        pass
```

### LocalStorage Implementation

```python
class LocalStorage(Storage):
    def __init__(self, data_dir: str):
        self.base_dir = Path(data_dir) / "task-service"
        self.tasks_dir = self.base_dir / "tasks"
        self.runs_dir = self.base_dir / "runs"
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
    
    async def get_task_repo(self) -> TaskRepository:
        return TaskRepository(self.tasks_dir)
    
    async def get_run_repo(self) -> TaskRunRepository:
        return TaskRunRepository(self.runs_dir)
```

### MongoStorage Implementation

Wraps existing MongoDB implementation:

```python
class MongoStorage(Storage):
    def __init__(self, db: MongoDB):
        self.db = db
    
    async def get_task_repo(self) -> TaskRepository:
        return MongoTaskRepository(self.db)
    
    async def get_run_repo(self) -> TaskRunRepository:
        return MongoRunRepository(self.db)
```

## Configuration

**Environment variables:**
- `STORAGE_BACKEND`: "local" or "docker" (default: "docker")
- `LOCAL_DATA_DIR`: Base directory for local storage (default: "./data")

**Dependency injection:**

```python
# app/core/storage.py
def get_storage_backend() -> Storage:
    backend = os.getenv("STORAGE_BACKEND", "docker")
    if backend == "local":
        data_dir = os.getenv("LOCAL_DATA_DIR", "./data")
        return LocalStorage(data_dir)
    else:
        db = get_db()  # Existing MongoDB connection
        return MongoStorage(db)
```

**Route changes:**

```python
# Before
@router.get("/tasks")
async def list_tasks(db: MongoDB = Depends(get_db)):
    ...

# After
@router.get("/tasks")
async def list_tasks(storage: Storage = Depends(get_storage_backend)):
    task_repo = await storage.get_task_repo()
    tasks = await task_repo.list_tasks()
    return tasks
```

## File Locking Strategy

**Library:** `filelock` (cross-platform, works on Windows/Unix)

**Lock files:** `{file_path}.lock` for each JSON file

**Timeout:** 5 seconds - fail if can't acquire lock

**Usage pattern:**

```python
from filelock import FileLock, Timeout

lock = FileLock(f"{file_path}.lock", timeout=5)
try:
    with lock:
        # Read/write operations
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
except Timeout:
    raise TimeoutError(f"Could not acquire lock for {file_path}")
```

**Atomic writes:**
1. Write to `{file_path}.tmp`
2. `os.replace(tmp_path, file_path)` - atomic on all platforms
3. Ensures no partial writes visible to readers

## API Layer Changes

**Error mapping:**
- `FileNotFoundError` → 404 Not Found
- `TimeoutError` (lock timeout) → 503 Service Unavailable
- `PermissionError` → 500 Internal Server Error
- `json.JSONDecodeError` → 500 Internal Server Error (log as corrupted file)

**No route signature changes** - Only dependency injection:
- Replace `db: MongoDB = Depends(get_db)`
- With `storage: Storage = Depends(get_storage_backend)`

**Pydantic model usage:**
- Repository methods return Pydantic `Task` and `TaskRun` objects directly
- No conversion functions needed (unlike MongoDB's `task_doc_to_out()`)

## APScheduler Integration

**Startup behavior:**
1. Get all tasks from storage
2. For each enabled task, add job to APScheduler
3. APScheduler state stays in memory (no persistence)

**Runtime behavior:**
- Task create → add job to scheduler
- Task update → reschedule job (remove old, add new)
- Task delete → remove job from scheduler
- Task enable/disable → add/remove job

**On restart:**
- APScheduler state rebuilt from task files
- In-flight jobs lost (acceptable - next scheduled run will execute)

**Why no APScheduler persistence:**
- Task definitions are source of truth
- Simpler implementation
- Matches how backend handles scheduled operations

## Migration Strategy

**No migration needed:**
- Docker mode continues using MongoDB
- Local mode starts with empty directory
- No data migration between modes (different use cases)

**Development workflow:**
- Set `STORAGE_BACKEND=local` in `.env`
- Task-service creates directories on first run
- No MongoDB dependency required

**Production (packaged app):**
- Electron sets `STORAGE_BACKEND=local` in environment
- Uses `{RPA_CLAW_HOME}/data/task-service/` for storage
- Survives app restarts

## Testing Strategy

**Unit tests:**
- Test TaskRepository CRUD operations
- Test TaskRunRepository CRUD operations
- Test file locking (concurrent access simulation)
- Test atomic writes (interrupt during write)
- Test corrupted file handling

**Integration tests:**
- Test API routes with LocalStorage
- Test APScheduler integration (task execution)
- Test storage backend switching (env var)

**Manual testing:**
- Create/update/delete tasks via API
- Verify JSON files created correctly
- Test concurrent API calls (multiple requests)
- Test app restart (APScheduler rebuilds state)

## Files to Modify

**New files:**
- `app/core/storage.py` - Storage abstraction and LocalStorage implementation
- `app/repositories/task_repository.py` - TaskRepository for local storage
- `app/repositories/run_repository.py` - TaskRunRepository for local storage
- `app/repositories/mongo_task_repository.py` - MongoTaskRepository wrapper
- `app/repositories/mongo_run_repository.py` - MongoRunRepository wrapper

**Modified files:**
- `app/main.py` - Update startup to use storage abstraction
- `app/api/tasks.py` - Replace db dependency with storage dependency
- `app/core/config.py` - Add LOCAL_DATA_DIR setting
- `requirements.txt` - Add `filelock` dependency

**Unchanged files:**
- `app/models/task.py` - Pydantic models stay the same
- `app/core/scheduler.py` - APScheduler logic unchanged
- `app/core/db.py` - MongoDB connection logic unchanged (still used in docker mode)

## Success Criteria

1. Task-service starts without MongoDB when `STORAGE_BACKEND=local`
2. All CRUD operations work via API
3. Tasks persist across restarts
4. APScheduler executes scheduled tasks correctly
5. Concurrent API calls don't corrupt files
6. Docker mode (MongoDB) continues working unchanged
7. Packaged Electron app runs task-service successfully
