# Edge/Cloud Dual Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let ScienceClaw run in two modes — cloud (MongoDB) and edge (local filesystem + in-memory index) — switched by a single env var, with zero frontend changes.

**Architecture:** A Repository abstraction layer sits between business code and storage. Two implementations: `MongoRepository` wraps Motor, `FileRepository` uses JSON files + in-memory dicts. A factory function returns the right one based on `STORAGE_BACKEND` env var. Edge mode also bypasses auth (single-user, no login needed).

**Tech Stack:** Python 3.13, FastAPI, Motor (existing), aiofiles (new, for async file I/O), Pydantic v2

---

## File Structure

```
backend/storage/
├── __init__.py              # get_repository() factory, init_storage(), close_storage()
├── base.py                  # Repository ABC
├── mongo/
│   ├── __init__.py          # empty
│   └── repository.py        # MongoRepository
└── local/
    ├── __init__.py          # empty
    ├── repository.py        # FileRepository
    └── query_engine.py      # match_filter(), apply_update() — pure functions
```

**Modified files:**
- `config.py` — add `storage_backend`, `local_data_dir`
- `main.py` — conditional startup/shutdown
- `user/dependencies.py` — edge auth bypass
- `user/bootstrap.py` — use Repository
- `models.py` — use Repository
- `task_settings.py` — use Repository
- `deepagent/sessions.py` — use Repository
- `deepagent/agent.py` — use Repository
- `deepagent/mongo_skill_backend.py` — use Repository
- `mongodb/db.py` — use Repository for `get_blocked_skill_names`
- `rpa/skill_exporter.py` — use Repository
- `route/auth.py` — use Repository
- `route/models.py` — use Repository
- `route/sessions.py` — use Repository
- `route/chat.py` — use Repository
- `route/rpa.py` — use Repository
- `route/statistics.py` — use Repository
- `route/task_settings.py` — use Repository

---

### Task 1: Add storage config to Settings

**Files:**
- Modify: `backend/config.py:7-51`

- [ ] **Step 1: Add storage_backend and local_data_dir fields**

In `config.py`, add two new fields after line 35 (after `mongodb_password`):

```python
    # Storage backend: "mongo" (cloud) or "local" (edge)
    storage_backend: str = os.environ.get("STORAGE_BACKEND", "mongo")
    local_data_dir: str = os.environ.get("LOCAL_DATA_DIR", "./data")
```

---

### Task 2: Create Repository ABC

**Files:**
- Create: `backend/storage/__init__.py`
- Create: `backend/storage/base.py`

- [ ] **Step 1: Create `backend/storage/base.py`**

```python
"""Repository abstract base class — the storage contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Repository(ABC):
    """One instance per collection. All methods are async."""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name

    @abstractmethod
    async def find_one(
        self, filter: dict, projection: dict | None = None
    ) -> Optional[dict]:
        ...

    @abstractmethod
    async def find_many(
        self,
        filter: dict,
        projection: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict]:
        ...

    @abstractmethod
    async def insert_one(self, document: dict) -> str:
        """Insert document, return _id (auto-generated if missing)."""
        ...

    @abstractmethod
    async def update_one(
        self, filter: dict, update: dict, upsert: bool = False
    ) -> int:
        """Return modified_count (0 or 1). Supports $set, $push, $setOnInsert."""
        ...

    @abstractmethod
    async def update_many(self, filter: dict, update: dict) -> int:
        """Return modified_count."""
        ...

    @abstractmethod
    async def delete_one(self, filter: dict) -> int:
        """Return deleted_count (0 or 1)."""
        ...

    @abstractmethod
    async def delete_many(self, filter: dict) -> int:
        """Return deleted_count."""
        ...

    @abstractmethod
    async def count(self, filter: dict) -> int:
        ...
```

- [ ] **Step 2: Create `backend/storage/__init__.py`**

```python
"""Storage abstraction — get_repository() is the only public API."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.storage.base import Repository

_repositories: dict[str, "Repository"] = {}
_initialized = False


def get_repository(collection_name: str) -> "Repository":
    """Return a cached Repository instance for the given collection."""
    if collection_name in _repositories:
        return _repositories[collection_name]

    from backend.config import settings

    if settings.storage_backend == "local":
        from backend.storage.local.repository import FileRepository
        repo = FileRepository(collection_name)
    else:
        from backend.storage.mongo.repository import MongoRepository
        repo = MongoRepository(collection_name)

    _repositories[collection_name] = repo
    return repo


async def init_storage() -> None:
    """Called once at startup. For local backend, loads all JSON into memory."""
    global _initialized
    if _initialized:
        return

    from backend.config import settings

    if settings.storage_backend == "local":
        from backend.storage.local.repository import FileRepository
        # Pre-create repos for known collections so they load data
        for name in (
            "users", "user_sessions", "sessions", "models",
            "skills", "blocked_tools", "task_settings", "session_events",
        ):
            repo = FileRepository(name)
            await repo.load()
            _repositories[name] = repo
    else:
        from backend.mongodb.db import db
        await db.connect()

    _initialized = True


async def close_storage() -> None:
    """Called once at shutdown."""
    from backend.config import settings

    if settings.storage_backend == "mongo":
        from backend.mongodb.db import db
        await db.close()

    _repositories.clear()
    global _initialized
    _initialized = False
```

---

### Task 3: Create query engine (pure functions)

**Files:**
- Create: `backend/storage/local/__init__.py`
- Create: `backend/storage/local/query_engine.py`

- [ ] **Step 1: Create empty `backend/storage/local/__init__.py`**

```python
```

- [ ] **Step 2: Create `backend/storage/local/query_engine.py`**

```python
"""Pure-function query engine for FileRepository.

Supports the MongoDB query/update operators actually used in the codebase:
- Query: equality, $or, $gte, $lte, $ne, $in, $nin, $exists, $not
- Update: $set, $push, $setOnInsert
- Nested field access via dot notation (e.g. "events.0")
"""
from __future__ import annotations

import copy
from typing import Any


def _get_nested(doc: dict, key: str) -> tuple[bool, Any]:
    """Get a possibly-nested value. Returns (found, value)."""
    parts = key.split(".")
    current = doc
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, current


def _match_value(doc_val: Any, condition: Any) -> bool:
    """Match a single field value against a condition (scalar or operator dict)."""
    if isinstance(condition, dict) and condition:
        first_key = next(iter(condition))
        if first_key.startswith("$"):
            return _match_operators(doc_val, condition)
    return doc_val == condition


def _match_operators(doc_val: Any, ops: dict) -> bool:
    """Evaluate operator dict against a document value."""
    for op, val in ops.items():
        if op == "$gte":
            if doc_val is None or doc_val < val:
                return False
        elif op == "$lte":
            if doc_val is None or doc_val > val:
                return False
        elif op == "$gt":
            if doc_val is None or doc_val > val:
                return False
        elif op == "$lt":
            if doc_val is None or doc_val < val:
                return False
        elif op == "$ne":
            if doc_val == val:
                return False
        elif op == "$in":
            if doc_val not in val:
                return False
        elif op == "$nin":
            if doc_val in val:
                return False
        elif op == "$exists":
            exists = doc_val is not None
            if val and not exists:
                return False
            if not val and exists:
                return False
        elif op == "$not":
            if _match_value(doc_val, val):
                return False
        else:
            raise NotImplementedError(f"Query operator not supported: {op}")
    return True


def match_filter(doc: dict, filter: dict) -> bool:
    """Return True if doc matches the MongoDB-style filter."""
    for key, condition in filter.items():
        if key == "$or":
            if not any(match_filter(doc, sub) for sub in condition):
                return False
        elif key == "$and":
            if not all(match_filter(doc, sub) for sub in condition):
                return False
        else:
            found, doc_val = _get_nested(doc, key)
            # Special handling for $exists on missing fields
            if isinstance(condition, dict) and "$exists" in condition:
                exists = found
                if condition["$exists"] and not exists:
                    return False
                if not condition["$exists"] and exists:
                    return False
                # Check remaining operators if any
                remaining = {k: v for k, v in condition.items() if k != "$exists"}
                if remaining and not _match_operators(doc_val, remaining):
                    return False
            else:
                if not found:
                    # Field missing — only matches if condition is {$ne: X} or equality with None
                    if isinstance(condition, dict):
                        if not _match_operators(None, condition):
                            return False
                    elif condition is not None:
                        return False
                elif not _match_value(doc_val, condition):
                    return False
    return True


def apply_projection(doc: dict, projection: dict | None) -> dict:
    """Apply MongoDB-style projection. Only inclusion projections supported."""
    if not projection:
        return doc
    # Check if it's inclusion or exclusion
    vals = [v for k, v in projection.items() if k != "_id"]
    if not vals:
        return doc
    if vals[0]:
        # Inclusion: only keep listed fields + _id
        result = {}
        if "_id" in doc:
            result["_id"] = doc["_id"]
        for key, include in projection.items():
            if include and key in doc:
                result[key] = doc[key]
        return result
    else:
        # Exclusion: remove listed fields
        result = dict(doc)
        for key, include in projection.items():
            if not include and key in result:
                del result[key]
        return result
```

- [ ] **Step 3: Add apply_update function to query_engine.py**

Append to `backend/storage/local/query_engine.py`:

```python
def apply_update(doc: dict, update: dict, is_upsert_insert: bool = False) -> dict:
    """Apply MongoDB-style update operators to a document (mutates a copy).

    Supports: $set, $push, $setOnInsert, and whole-doc replacement.
    """
    doc = copy.deepcopy(doc)

    has_operators = any(k.startswith("$") for k in update)

    if not has_operators:
        # Whole-document replacement (preserve _id)
        _id = doc.get("_id")
        doc = copy.deepcopy(update)
        if _id is not None:
            doc["_id"] = _id
        return doc

    if "$set" in update:
        for key, val in update["$set"].items():
            doc[key] = val

    if "$push" in update:
        for key, val in update["$push"].items():
            if key not in doc:
                doc[key] = []
            if isinstance(doc[key], list):
                doc[key].append(val)

    if "$setOnInsert" in update and is_upsert_insert:
        for key, val in update["$setOnInsert"].items():
            if key not in doc:
                doc[key] = val

    return doc
```

---

### Task 4: Create FileRepository

**Files:**
- Create: `backend/storage/local/repository.py`

- [ ] **Step 1: Create FileRepository**

```python
"""FileRepository — JSON-file-backed storage with in-memory index."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from backend.config import settings
from backend.storage.base import Repository
from backend.storage.local.query_engine import (
    apply_projection,
    apply_update,
    match_filter,
)


class FileRepository(Repository):
    """Each collection is a directory; each document is {_id}.json."""

    def __init__(self, collection_name: str):
        super().__init__(collection_name)
        self._dir = Path(settings.local_data_dir) / collection_name
        self._data: dict[str, dict] = {}  # _id -> document
        self._loaded = False

    async def load(self) -> None:
        """Scan directory and load all JSON files into memory."""
        if self._loaded:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        for f in self._dir.glob("*.json"):
            try:
                raw = f.read_text(encoding="utf-8")
                doc = json.loads(raw)
                _id = doc.get("_id", f.stem)
                doc["_id"] = _id
                self._data[str(_id)] = doc
            except Exception as exc:
                logger.warning(f"Failed to load {f}: {exc}")
        self._loaded = True
        logger.info(
            f"[FileRepo] Loaded {len(self._data)} docs for '{self.collection_name}'"
        )

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._dir.mkdir(parents=True, exist_ok=True)
            for f in self._dir.glob("*.json"):
                try:
                    raw = f.read_text(encoding="utf-8")
                    doc = json.loads(raw)
                    _id = doc.get("_id", f.stem)
                    doc["_id"] = _id
                    self._data[str(_id)] = doc
                except Exception:
                    pass
            self._loaded = True

    def _safe_filename(self, _id: str) -> str:
        return _id.replace("/", "%2F").replace("\\", "%5C")

    def _write_doc(self, doc: dict) -> None:
        _id = str(doc["_id"])
        fname = self._safe_filename(_id)
        target = self._dir / f"{fname}.json"
        tmp = self._dir / f"{fname}.tmp"
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(doc, ensure_ascii=False, default=str), encoding="utf-8"
        )
        tmp.replace(target)

    def _delete_doc(self, _id: str) -> None:
        fname = self._safe_filename(_id)
        target = self._dir / f"{fname}.json"
        target.unlink(missing_ok=True)

    async def find_one(
        self, filter: dict, projection: dict | None = None
    ) -> Optional[dict]:
        self._ensure_loaded()
        for doc in self._data.values():
            if match_filter(doc, filter):
                return apply_projection(doc, projection)
        return None

    async def find_many(
        self,
        filter: dict,
        projection: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict]:
        self._ensure_loaded()
        results = [doc for doc in self._data.values() if match_filter(doc, filter)]
        if sort:
            for key, direction in reversed(sort):
                results.sort(
                    key=lambda d, k=key: (d.get(k) is None, d.get(k)),
                    reverse=(direction == -1),
                )
        if skip:
            results = results[skip:]
        if limit:
            results = results[:limit]
        if projection:
            results = [apply_projection(doc, projection) for doc in results]
        return results

    async def insert_one(self, document: dict) -> str:
        self._ensure_loaded()
        if "_id" not in document:
            document["_id"] = str(uuid.uuid4())
        _id = str(document["_id"])
        self._write_doc(document)
        self._data[_id] = document
        return _id

    async def update_one(
        self, filter: dict, update: dict, upsert: bool = False
    ) -> int:
        self._ensure_loaded()
        for _id, doc in self._data.items():
            if match_filter(doc, filter):
                updated = apply_update(doc, update)
                self._data[_id] = updated
                self._write_doc(updated)
                return 1
        if upsert:
            new_doc = {}
            for k, v in filter.items():
                if not k.startswith("$") and not isinstance(v, dict):
                    new_doc[k] = v
            if "_id" not in new_doc:
                new_doc["_id"] = str(uuid.uuid4())
            new_doc = apply_update(new_doc, update, is_upsert_insert=True)
            _id = str(new_doc["_id"])
            self._data[_id] = new_doc
            self._write_doc(new_doc)
            return 1
        return 0

    async def update_many(self, filter: dict, update: dict) -> int:
        self._ensure_loaded()
        count = 0
        for _id, doc in list(self._data.items()):
            if match_filter(doc, filter):
                updated = apply_update(doc, update)
                self._data[_id] = updated
                self._write_doc(updated)
                count += 1
        return count

    async def delete_one(self, filter: dict) -> int:
        self._ensure_loaded()
        for _id, doc in list(self._data.items()):
            if match_filter(doc, filter):
                del self._data[_id]
                self._delete_doc(_id)
                return 1
        return 0

    async def delete_many(self, filter: dict) -> int:
        self._ensure_loaded()
        to_delete = [
            _id for _id, doc in self._data.items() if match_filter(doc, filter)
        ]
        for _id in to_delete:
            del self._data[_id]
            self._delete_doc(_id)
        return len(to_delete)

    async def count(self, filter: dict) -> int:
        self._ensure_loaded()
        return sum(1 for doc in self._data.values() if match_filter(doc, filter))
```

---

### Task 5: Create MongoRepository

**Files:**
- Create: `backend/storage/mongo/__init__.py`
- Create: `backend/storage/mongo/repository.py`

- [ ] **Step 1: Create empty `backend/storage/mongo/__init__.py`**

```python
```

- [ ] **Step 2: Create `backend/storage/mongo/repository.py`**

```python
"""MongoRepository — thin wrapper around Motor collections."""
from __future__ import annotations

from typing import Optional

from backend.storage.base import Repository


class MongoRepository(Repository):
    """Delegates to Motor AsyncIOMotorCollection."""

    def _get_col(self):
        from backend.mongodb.db import db
        return db.get_collection(self.collection_name)

    async def find_one(
        self, filter: dict, projection: dict | None = None
    ) -> Optional[dict]:
        return await self._get_col().find_one(filter, projection)

    async def find_many(
        self,
        filter: dict,
        projection: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict]:
        cursor = self._get_col().find(filter, projection)
        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit or None)

    async def insert_one(self, document: dict) -> str:
        result = await self._get_col().insert_one(document)
        return str(result.inserted_id)

    async def update_one(
        self, filter: dict, update: dict, upsert: bool = False
    ) -> int:
        result = await self._get_col().update_one(filter, update, upsert=upsert)
        return result.modified_count

    async def update_many(self, filter: dict, update: dict) -> int:
        result = await self._get_col().update_many(filter, update)
        return result.modified_count

    async def delete_one(self, filter: dict) -> int:
        result = await self._get_col().delete_one(filter)
        return result.deleted_count

    async def delete_many(self, filter: dict) -> int:
        result = await self._get_col().delete_many(filter)
        return result.deleted_count

    async def count(self, filter: dict) -> int:
        return await self._get_col().count_documents(filter)
```

---

### Task 6: Migrate `main.py` — startup/shutdown lifecycle

**Files:**
- Modify: `backend/main.py:1-105`

- [ ] **Step 1: Replace db import with storage import**

Replace line 14 (`from backend.mongodb.db import db`) with:

```python
from backend.storage import init_storage, close_storage, get_repository
```

- [ ] **Step 2: Replace lifespan function**

Replace the entire `lifespan` function (lines 28-48) with:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_storage()
    try:
        await init_system_models()
    except Exception as e:
        logger.error(f"Failed to init system models: {e}")
    try:
        await ensure_admin_user()
    except Exception as e:
        logger.error(f"Failed to bootstrap admin user: {e}")
    try:
        await cleanup_orphaned_sessions()
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned sessions: {e}")
    yield
    try:
        await graceful_shutdown_agents()
    except Exception as e:
        logger.error(f"Failed to gracefully shutdown agents: {e}")
    await close_storage()
```

- [ ] **Step 3: Update the `/ready` endpoint**

Replace the `ready` function (lines 74-84) with:

```python
    @app.get("/ready")
    async def ready():
        try:
            repo = get_repository("sessions")
            await repo.find_one({})
            return {"status": "ready", "storage": "ok"}
        except Exception as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "storage": str(exc)},
            )
```

---

### Task 7: Migrate `user/dependencies.py` — edge auth bypass

**Files:**
- Modify: `backend/user/dependencies.py:1-60`

- [ ] **Step 1: Replace entire file**

```python
from typing import Optional
from fastapi import Request, HTTPException, Depends
from pydantic import BaseModel
from backend.config import settings
from backend.storage import get_repository


class User(BaseModel):
    id: str
    username: str
    role: str = "user"


async def get_current_user(request: Request) -> Optional[User]:
    """Dependency to get current authenticated user from session cookie."""
    if settings.storage_backend == "local":
        return User(id="local_admin", username="admin", role="admin")

    if getattr(settings, "auth_provider", "local") == "none":
        return User(id="anonymous", username="Anonymous", role="user")

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        session_id = auth.split(" ", 1)[1].strip()
    else:
        session_id = request.cookies.get(settings.session_cookie)
    if not session_id:
        return None

    repo = get_repository("user_sessions")
    session_doc = await repo.find_one({"_id": session_id})

    if not session_doc:
        return None

    import time
    if session_doc.get("expires_at", 0) < time.time():
        await repo.delete_one({"_id": session_id})
        return None

    return User(
        id=str(session_doc["user_id"]),
        username=session_doc["username"],
        role=session_doc.get("role", "user"),
    )


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
```

---

### Task 8: Migrate `user/bootstrap.py`

**Files:**
- Modify: `backend/user/bootstrap.py:1-65`

- [ ] **Step 1: Replace db import**

Replace `from backend.mongodb.db import db` (line 10) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace `db.get_collection("users")` with `get_repository("users")`**

Replace line 25 (`users = db.get_collection("users")`) with:

```python
    users = get_repository("users")
```

No other changes needed — `find_one`, `insert_one`, `update_one` with `$set` all match the Repository API.

---

### Task 9: Migrate `models.py`

**Files:**
- Modify: `backend/models.py:1-112`

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db` (line 8) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace `init_system_models`**

Replace lines 52-88 with:

```python
async def init_system_models():
    now = int(time.time())
    repo = get_repository("models")

    await repo.delete_one({"_id": "system-qwen", "is_system": True})

    if not settings.model_ds_api_key:
        await repo.delete_one({"_id": "system-default", "is_system": True})
        logger.info("DS_API_KEY not set, skipping system model creation")
        return

    system_definitions = [
        {
            "_id": "system-default",
            "name": "DeepSeek V3.2",
            "provider": "deepseek",
            "base_url": settings.model_ds_base_url,
            "api_key": settings.model_ds_api_key,
            "model_name": settings.model_ds_name,
            "context_window": settings.context_window,
            "is_system": True,
            "is_active": True,
        }
    ]

    for doc in system_definitions:
        existing = await repo.find_one({"_id": doc["_id"]})
        doc = {**doc, "updated_at": now}
        if not existing:
            doc["created_at"] = now
            await repo.insert_one(doc)
        else:
            await repo.update_one({"_id": doc["_id"]}, {"$set": doc})
```

- [ ] **Step 3: Replace `get_model_config` and `list_user_models`**

Replace lines 90-111 with:

```python
async def get_model_config(model_id: str) -> Optional[ModelConfig]:
    repo = get_repository("models")
    doc = await repo.find_one({"_id": model_id})
    if not doc:
        return None
    doc["id"] = doc["_id"]
    return ModelConfig(**doc)


async def list_user_models(user_id: str) -> List[ModelConfig]:
    repo = get_repository("models")
    docs = await repo.find_many(
        {"$or": [{"is_system": True}, {"user_id": user_id}]},
        sort=[("created_at", -1)],
    )
    models = []
    for doc in docs:
        doc["id"] = doc["_id"]
        models.append(ModelConfig(**doc))
    return models
```

---

### Task 10: Migrate `task_settings.py`

**Files:**
- Modify: `backend/task_settings.py:1-80`

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db` (line 4) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace `get_task_settings` and `update_task_settings`**

Replace lines 61-79 with:

```python
async def get_task_settings(user_id: str) -> TaskSettings:
    repo = get_repository("task_settings")
    doc = await repo.find_one({"_id": user_id})
    if not doc:
        return TaskSettings()
    doc.pop("_id", None)
    return TaskSettings(**doc)


async def update_task_settings(user_id: str, updates: UpdateTaskSettingsRequest) -> TaskSettings:
    update_data = updates.model_dump(exclude_unset=True)
    if not update_data:
        return await get_task_settings(user_id)
    repo = get_repository("task_settings")
    await repo.update_one(
        {"_id": user_id},
        {"$set": update_data},
        upsert=True,
    )
    return await get_task_settings(user_id)
```

---

### Task 11: Migrate `deepagent/sessions.py`

**Files:**
- Modify: `backend/deepagent/sessions.py:1-338`

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db` (line 11) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace `ScienceSession.save()` method**

Replace lines 115-133 with:

```python
    async def save(self):
        update_data = {
            "mode": self.mode,
            "plan": self.plan,
            "title": self.title,
            "status": self.status,
            "updated_at": int(time.time()),
            "unread_message_count": self.unread_message_count,
            "latest_message": self.latest_message,
            "latest_message_at": self.latest_message_at,
            "model_config": self.model_config,
            "events": self.events,
            "pinned": self.pinned,
        }
        repo = get_repository("sessions")
        await repo.update_one(
            {"_id": self.session_id},
            {"$set": update_data},
            upsert=True,
        )
```

- [ ] **Step 3: Replace `async_create_science_session`**

Replace `await db.get_collection("sessions").insert_one(session_doc)` (line 212) with:

```python
    repo = get_repository("sessions")
    await repo.insert_one(session_doc)
```

- [ ] **Step 4: Replace `async_get_science_session`**

Replace `doc = await db.get_collection("sessions").find_one({"_id": session_id})` (line 232) with:

```python
    repo = get_repository("sessions")
    doc = await repo.find_one({"_id": session_id})
```

- [ ] **Step 5: Replace `async_list_science_sessions`**

Replace lines 267-304 with:

```python
async def async_list_science_sessions(user_id: Optional[str] = None) -> List[ScienceSession]:
    query: Dict[str, Any] = {"source": {"$ne": "task"}}
    if user_id:
        query["user_id"] = user_id

    repo = get_repository("sessions")
    docs = await repo.find_many(query, sort=[("updated_at", -1)])
    sessions = []

    async with _sessions_lock:
        cached_snapshot = dict(_sessions)

    for doc in docs:
        cached = cached_snapshot.get(doc["_id"])
        if cached:
            sessions.append(cached)
            continue

        vm_root = Path(doc.get("vm_root_dir") or str(_session_workspace(doc["_id"])))

        s = ScienceSession(
            session_id=doc["_id"],
            thread_id=doc["thread_id"],
            vm_root_dir=vm_root,
            mode=doc.get("mode", "deep"),
            user_id=doc.get("user_id"),
            model_config=doc.get("model_config"),
            title=doc.get("title"),
            status=doc.get("status", "pending"),
            created_at=doc.get("created_at", 0),
            updated_at=doc.get("updated_at", 0),
            unread_message_count=doc.get("unread_message_count", 0),
            latest_message=doc.get("latest_message", ""),
            latest_message_at=doc.get("latest_message_at", 0),
            pinned=doc.get("pinned", False),
            source=doc.get("source"),
        )
        sessions.append(s)

    return sessions
```

- [ ] **Step 6: Replace `async_delete_science_session`**

Replace `res = await db.get_collection("sessions").delete_one({"_id": session_id})` and `if res.deleted_count == 0:` (lines 309-311) with:

```python
    repo = get_repository("sessions")
    deleted = await repo.delete_one({"_id": session_id})
    if deleted == 0:
        raise ScienceSessionNotFoundError(f"session {session_id} not found")
```

---

### Task 12: Migrate `deepagent/agent.py`

**Files:**
- Modify: `backend/deepagent/agent.py` (lines 108-150, 310-338)

- [ ] **Step 1: Replace skill injection function's MongoDB usage**

In the `_inject_skills_to_sandbox` function (around line 119-129), replace:

```python
    from backend.mongodb.db import db as _db

    col = _db.get_collection("skills")
```

with:

```python
    from backend.storage import get_repository

    col_repo = get_repository("skills")
```

Then replace the cursor iteration `async for doc in col.find(filt, {"name": 1, "files": 1}):` (line 129) with:

```python
    docs = await col_repo.find_many(filt, projection={"name": 1, "files": 1})
    for doc in docs:
```

- [ ] **Step 2: Replace `get_blocked_skills`**

Replace lines 314-321 with:

```python
async def get_blocked_skills(user_id: str) -> Set[str]:
    """Query blocked skill names for a user."""
    try:
        from backend.storage import get_repository
        repo = get_repository("skills")
        docs = await repo.find_many(
            {"user_id": user_id, "blocked": True},
            projection={"name": 1},
        )
        return {doc["name"] for doc in docs if doc.get("name")}
    except Exception as exc:
        logger.warning(f"[Skills] 查询屏蔽列表失败: {exc}")
        return set()
```

- [ ] **Step 3: Replace `get_blocked_tools`**

Replace lines 324-338 with:

```python
async def get_blocked_tools(user_id: str) -> Set[str]:
    """Query blocked tool names for a user."""
    try:
        from backend.storage import get_repository
        repo = get_repository("blocked_tools")
        docs = await repo.find_many(
            {"user_id": user_id},
            projection={"tool_name": 1},
        )
        return {doc["tool_name"] for doc in docs if doc.get("tool_name")}
    except Exception as exc:
        logger.warning(f"[Tools] 查询屏蔽列表失败: {exc}")
        return set()
```

---

### Task 13: Migrate `deepagent/mongo_skill_backend.py`

**Files:**
- Modify: `backend/deepagent/mongo_skill_backend.py:1-292`

- [ ] **Step 1: Replace `_get_col` method**

Replace lines 39-41 with:

```python
    def _get_col(self):
        from backend.storage import get_repository
        return get_repository("skills")
```

- [ ] **Step 2: Replace cursor iterations with find_many**

The `_get_col()` now returns a Repository, not a Motor Collection. All methods that use `col.find(...)` with `async for` need to change to `await col.find_many(...)` with `for`.

In `als_info` (lines 64-101), replace:

```python
            cursor = col.find(
                self._active_filter(),
                {"name": 1, "description": 1}
            )
            entries = []
            async for doc in cursor:
```

with:

```python
            docs = await col.find_many(
                self._active_filter(),
                projection={"name": 1, "description": 1},
            )
            entries = []
            for doc in docs:
```

Replace `doc = await col.find_one(...)` calls — these stay the same since Repository has `find_one`.

In `awrite` (lines 137-183), replace `await col.update_one(...)` and `await col.insert_one(...)` — these stay the same.

In `_update_description_from_frontmatter` (lines 185-199), replace:

```python
                col = self._get_col()
                await col.update_one(
```

This stays the same — Repository has `update_one`.

In `aglob_info` (lines 237-253), replace:

```python
        cursor = col.find(self._active_filter(), {"name": 1, "files": 1})
        results = []
        async for doc in cursor:
```

with:

```python
        docs = await col.find_many(
            self._active_filter(), projection={"name": 1, "files": 1}
        )
        results = []
        for doc in docs:
```

In `agrep_raw` (lines 261-291), replace:

```python
        cursor = col.find(filt, {"name": 1, "files": 1})
        ...
        async for doc in cursor:
```

with:

```python
        docs = await col.find_many(filt, projection={"name": 1, "files": 1})
        ...
        for doc in docs:
```

---

### Task 14: Migrate `mongodb/db.py` — update `get_blocked_skill_names`

**Files:**
- Modify: `backend/mongodb/db.py:85-96`

- [ ] **Step 1: Replace `get_blocked_skill_names`**

Replace lines 85-96 with:

```python
async def get_blocked_skill_names(user_id: str) -> set[str]:
    """Query blocked skill names for a user from the skills collection."""
    from backend.storage import get_repository
    repo = get_repository("skills")
    docs = await repo.find_many(
        {"user_id": user_id, "blocked": True},
        projection={"name": 1},
    )
    return {doc["name"] for doc in docs if doc.get("name")}
```

---

### Task 15: Migrate `rpa/skill_exporter.py`

**Files:**
- Modify: `backend/rpa/skill_exporter.py:1-87`

- [ ] **Step 1: Replace import and usage**

Replace `from backend.mongodb.db import db` (line 6) with:

```python
from backend.storage import get_repository
```

Replace `col = db.get_collection("skills")` (line 61) with:

```python
        col = get_repository("skills")
```

The `await col.update_one(...)` call with `$set` and `$setOnInsert` (lines 62-83) stays the same — both Repository implementations handle these operators.

---

### Task 16: Migrate `route/auth.py`

**Files:**
- Modify: `backend/route/auth.py`

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db` (line 13) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace all `db.get_collection(...)` calls**

This file has ~15 calls to `db.get_collection("users")` and `db.get_collection("user_sessions")`. Replace each with the repository pattern:

At the top of each function that uses them, add:

```python
    users_repo = get_repository("users")
    sessions_repo = get_repository("user_sessions")
```

Then replace every `db.get_collection("users")` with `users_repo` and every `db.get_collection("user_sessions")` with `sessions_repo`.

The method calls (`find_one`, `insert_one`, `update_one`, `delete_one`) all match the Repository API. The `$set` update syntax is preserved.

---

### Task 17: Migrate `route/models.py`

**Files:**
- Modify: `backend/route/models.py`

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db` (line 10) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace all `db.get_collection("models")` calls**

There are 6 calls. Replace each with `get_repository("models")`:

```python
    repo = get_repository("models")
```

Then use `repo.find_one(...)`, `repo.insert_one(...)`, `repo.update_one(...)`, `repo.delete_one(...)` — all match the Repository API.

---

### Task 18: Migrate `route/sessions.py`

**Files:**
- Modify: `backend/route/sessions.py`

This is the largest file. It uses `_db.get_collection(...)` for `skills`, `blocked_tools`, and `sessions`.

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db as _db` (line 682) with:

```python
from backend.storage import get_repository as _get_repo
```

- [ ] **Step 2: Replace all `_db.get_collection("skills")` calls**

There are 6 occurrences (lines 735, 768, 790, 835, 915, 950, 1600). Replace each:

```python
col = _db.get_collection("skills")
```

with:

```python
col = _get_repo("skills")
```

For cursor iterations like `async for doc in col.find(...)`, replace with:

```python
docs = await col.find_many(filter, projection=projection)
for doc in docs:
```

- [ ] **Step 3: Replace all `_db.get_collection("blocked_tools")` calls**

There are 3 occurrences (lines 1013, 1036, 1063). Replace each:

```python
col = _db.get_collection("blocked_tools")
```

with:

```python
col = _get_repo("blocked_tools")
```

Same cursor-to-find_many conversion for `col.find(...)`.

- [ ] **Step 4: Replace `_db.get_collection("sessions")` calls**

There are 2 occurrences in `cleanup_orphaned_sessions` (line 1398) and `graceful_shutdown_agents` (line 1445). Both use `update_many`:

```python
result = await _db.get_collection("sessions").update_many(...)
```

Replace with:

```python
repo = _get_repo("sessions")
modified = await repo.update_many(...)
```

Note: `update_many` returns `int` (modified_count) in Repository, not a result object. Update the check from `result.modified_count` to just `modified`:

```python
    repo = _get_repo("sessions")
    modified = await repo.update_many(
        {"$or": [
            {"status": SessionStatus.RUNNING},
            {"status": SessionStatus.PENDING, "events.0": {"$exists": True}},
        ]},
        {
            "$set": {"status": SessionStatus.COMPLETED, "updated_at": now},
            "$push": {"events": {
                "event": "done",
                "data": {
                    "event_id": shortuuid.uuid(),
                    "timestamp": now,
                    "statistics": {},
                    "interrupted": True,
                },
            }},
        },
    )
    if modified:
        logger.info(
            f"[Startup] Cleaned up {modified} orphaned session(s) "
            "(running/pending → completed)"
        )
    return modified
```

Apply the same pattern to `graceful_shutdown_agents`.

---

### Task 19: Migrate `route/chat.py`

**Files:**
- Modify: `backend/route/chat.py`

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db` (line 23) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace the single `db.get_collection("models")` call**

Replace line 220:

```python
    doc = await db.get_collection("models").find_one(
```

with:

```python
    repo = get_repository("models")
    doc = await repo.find_one(
```

---

### Task 20: Migrate `route/rpa.py`

**Files:**
- Modify: `backend/route/rpa.py`

- [ ] **Step 1: Replace import**

Replace `from backend.mongodb.db import db` (line 15) with:

```python
from backend.storage import get_repository
```

- [ ] **Step 2: Replace the single `db.get_collection("models")` call**

Replace line 50:

```python
    doc = await db.get_collection("models").find_one(
```

with:

```python
    repo = get_repository("models")
    doc = await repo.find_one(
```

---

### Task 21: Migrate `route/statistics.py`

**Files:**
- Modify: `backend/route/statistics.py`

- [ ] **Step 1: Replace import and alias**

Replace line 19 (`from backend.mongodb.db import db`) and line 24 (`_db = db`) with:

```python
from backend.storage import get_repository
```

Remove the `_db = db` alias line entirely.

- [ ] **Step 2: Replace `_aggregate_statistics` function query**

Replace line 394:

```python
    sessions = await _db.get_collection("sessions").find(query).to_list(length=None)
```

with:

```python
    repo = get_repository("sessions")
    sessions = await repo.find_many(query)
```

- [ ] **Step 3: Replace session detail endpoint queries**

Replace `count_documents` (line 628):

```python
        total = await _db.get_collection("sessions").count_documents(query)
```

with:

```python
        repo = get_repository("sessions")
        total = await repo.count(query)
```

Replace the paginated find (line 632):

```python
        sessions = await _db.get_collection("sessions").find(query).sort("updated_at", -1).skip(skip).limit(page_size).to_list(length=page_size)
```

with:

```python
        sessions = await repo.find_many(
            query,
            sort=[("updated_at", -1)],
            skip=skip,
            limit=page_size,
        )
```

---

### Task 22: Migrate `route/task_settings.py` — NO-OP

This file only imports from `backend.task_settings` (already migrated in Task 10). No direct `db` usage. Skip.

---

### Task 23: Verification — run the app in both modes

- [ ] **Step 1: Verify no remaining direct MongoDB imports in business code**

Run:

```bash
cd ScienceClaw/backend
grep -rn "from backend.mongodb.db import" --include="*.py" | grep -v "storage/mongo/" | grep -v "__pycache__"
```

Expected: Only `storage/mongo/repository.py` and `mongodb/db.py` itself should reference `backend.mongodb.db`. All route/deepagent/model files should be clean.

- [ ] **Step 2: Verify cloud mode (MongoDB) still works**

```bash
# Ensure STORAGE_BACKEND is unset or "mongo"
cd ScienceClaw
docker compose up -d --build
# Test health and ready endpoints
curl http://localhost:12001/health
curl http://localhost:12001/ready
# Test login
curl -X POST http://localhost:12001/api/v1/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}'
```

Expected: All return 200 OK.

- [ ] **Step 3: Verify edge mode (local filesystem) works**

```bash
STORAGE_BACKEND=local docker compose up backend frontend -d --build
curl http://localhost:12001/health
curl http://localhost:12001/ready
# Login should auto-succeed
curl -X POST http://localhost:12001/api/v1/auth/login -H "Content-Type: application/json" -d '{"username":"any","password":"any"}'
```

Expected: All return 200 OK. Data directory `./data/` should contain JSON files after startup.

- [ ] **Step 4: Verify data persistence in edge mode**

```bash
# Create a session, restart, verify it persists
curl -X PUT http://localhost:12001/api/v1/sessions -H "Content-Type: application/json" -d '{"mode":"deep"}'
# Note the session_id
docker compose restart backend
curl http://localhost:12001/api/v1/sessions
```

Expected: Session list includes the previously created session.
