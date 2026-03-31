# 端侧/云侧双架构存储设计

## 概述

让 ScienceClaw 同时支持两种部署模式：

- **云侧（cloud）**：依赖 MongoDB + Redis，适合多用户服务端部署（现有架构）
- **端侧（local）**：纯文件系统 + 内存索引，零外部依赖，适合单用户本地部署

通过环境变量 `STORAGE_BACKEND=local|mongo` 切换，同一份代码两种部署。前端无感知。

## 决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 端侧存储方案 | 纯文件系统 + 内存索引 | 零依赖，端侧数据量小，内存完全够用 |
| 切换方式 | 环境变量 | 一份代码，部署时决定 |
| 认证处理 | 端侧免登录，后端透明处理 | 单用户无需认证，前端零改动 |
| 迁移范围 | 全量（8 个集合） | 一步到位，避免半吊子状态 |
| 实现方案 | Repository 模式 | 接口清晰，可测试，架构最干净 |
| 端侧部署 | 只跑 backend + frontend | 去掉 MongoDB/Redis 依赖 |

## 架构设计

### 存储抽象层

在 `backend/` 下新建 `storage/` 包：

```
backend/storage/
├── __init__.py          # 导出 get_repository() 工厂函数
├── base.py              # Repository 抽象基类（ABC）
├── mongo/
│   ├── __init__.py
│   └── repository.py    # MongoRepository — 包装现有 Motor 调用
└── local/
    ├── __init__.py
    ├── repository.py    # FileRepository — JSON 文件 + 内存索引
    └── index.py         # 内存索引引擎（排序、过滤、分页）
```

### Repository 接口

```python
from abc import ABC, abstractmethod
from typing import Optional

class Repository(ABC):
    """每个 collection 对应一个 Repository 实例。"""

    @abstractmethod
    async def find_one(self, filter: dict) -> Optional[dict]:
        """按条件查找单条记录。"""

    @abstractmethod
    async def find_many(
        self,
        filter: dict,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict]:
        """按条件查找多条记录，支持排序、跳过、限制。"""

    @abstractmethod
    async def insert_one(self, document: dict) -> str:
        """插入一条记录，返回 _id。"""

    @abstractmethod
    async def update_one(
        self, filter: dict, update: dict, upsert: bool = False
    ) -> bool:
        """更新一条记录。update 支持 $set 语义。返回是否匹配到记录。"""

    @abstractmethod
    async def delete_one(self, filter: dict) -> bool:
        """删除一条记录。返回是否删除成功。"""

    @abstractmethod
    async def delete_many(self, filter: dict) -> int:
        """删除多条记录。返回删除数量。"""

    @abstractmethod
    async def count(self, filter: dict) -> int:
        """按条件计数。"""
```

### 工厂函数

```python
from config import settings

_repositories: dict[str, Repository] = {}

def get_repository(collection_name: str) -> Repository:
    if collection_name not in _repositories:
        if settings.storage_backend == "local":
            from storage.local.repository import FileRepository
            _repositories[collection_name] = FileRepository(collection_name)
        else:
            from storage.mongo.repository import MongoRepository
            _repositories[collection_name] = MongoRepository(collection_name)
    return _repositories[collection_name]
```

Repository 实例按 collection 名缓存，全局单例。

## FileRepository 实现

### 文件布局

每个 collection 一个目录，每条记录一个 JSON 文件：

```
{LOCAL_DATA_DIR}/
├── users/
│   └── admin.json
├── sessions/
│   ├── abc123.json
│   └── def456.json
├── models/
│   └── system-deepseek.json
├── user_sessions/
├── skills/
├── task_settings/
├── blocked_tools/
└── session_events/
```

文件名为 `{_id}.json`。`_id` 中的特殊字符（如 `/`）用 URL 编码处理。

### 内存索引

- 启动时扫描所有 JSON 文件，加载到内存字典 `{_id: document}`
- 写操作同时更新内存和磁盘（先写磁盘再更内存）
- `find_many` 的过滤、排序、分页全在内存完成

### 查询引擎

支持当前代码实际用到的操作符，不追求完整 MongoDB 语法。

**查询操作符**（用于 `find_one`、`find_many`、`delete_one`、`delete_many`、`count` 的 filter 参数）：

| 操作符 | 用途 | 示例 |
|--------|------|------|
| 等值匹配 | 精确查找 | `{"username": "admin"}` |
| `$or` | 或条件 | `{"$or": [{"is_system": True}, {"user_id": uid}]}` |
| `$gte` / `$lte` | 范围比较 | `{"updated_at": {"$gte": ts}}` |
| `$ne` | 不等于 | `{"source": {"$ne": "task"}}` |
| `$in` | 包含 | `{"_id": {"$in": [...]}}` |
| `$exists` | 字段存在性 | `{"blocked": {"$exists": False}}` |

**更新操作符**（用于 `update_one` 的 update 参数）：

| 操作符 | 用途 | 示例 |
|--------|------|------|
| `$set` | 部分字段更新 | `{"$set": {"title": "new"}}` |
| 整文档替换 | 无 `$` 前缀时视为整文档替换 | `{"title": "new", "status": "done"}` |

不支持的操作符在 FileRepository 中抛出 `NotImplementedError`，便于发现遗漏。

### 写入安全

- 写文件时先写 `{_id}.tmp` 再 `os.replace()` 原子重命名
- 单用户单进程，不需要文件锁或 WAL

## MongoRepository 实现

包装现有 Motor 调用，接口与 FileRepository 一致：

- `find_one` → `collection.find_one(filter)`
- `find_many` → `collection.find(filter).sort(...).skip(...).limit(...)` 然后 `to_list()`
- `insert_one` → `collection.insert_one(document)`，返回 `inserted_id`
- `update_one` → `collection.update_one(filter, update, upsert=upsert)`，直接透传 MongoDB 更新语法
- `delete_one` → `collection.delete_one(filter)`
- `delete_many` → `collection.delete_many(filter)`
- `count` → `collection.count_documents(filter)`

MongoRepository 内部持有 Motor Collection 引用，通过现有的 `db.get_collection()` 获取。

## 认证 — 端侧免登录

端侧模式下，认证层透明处理，前端零改动：

1. `config.py` 新增 `STORAGE_BACKEND: str = "mongo"`
2. 当 `STORAGE_BACKEND == "local"` 时：
   - 启动时自动创建内置管理员用户（复用 `ensure_admin_user` 逻辑，通过 Repository）
   - `get_current_user` 依赖项直接返回内置用户，跳过 token 校验
   - `/api/v1/auth/login` 无论传什么凭据都返回有效 token
3. 前端照常走登录流程，后端永远放行

实现方式：在 `user/dependencies.py` 的 `get_current_user` 函数开头加一个短路判断：

```python
async def get_current_user(...):
    if settings.storage_backend == "local":
        return {"_id": "local_admin", "username": "admin", "role": "admin"}
    # ... 现有 token 校验逻辑
```

## 业务代码迁移

### 迁移模式

所有 `db.get_collection()` 调用替换为 `get_repository()`：

```python
# 之前
from mongodb.db import db
doc = await db.get_collection("sessions").find_one({"_id": sid})

# 之后
from storage import get_repository
repo = get_repository("sessions")
doc = await repo.find_one({"_id": sid})
```

### 特殊处理

1. **`$set` 更新语义**：Repository 的 `update_one` 接受 `{"$set": {...}}` 格式。FileRepository 解析 `$set` 做部分字段更新；MongoRepository 直接透传。

2. **Cursor 链式调用**：现有 `find(q).sort(...).skip(...).limit(...)` 改为 `find_many(q, sort=..., skip=..., limit=...)`。

3. **聚合查询**：`statistics.py` 的日期范围过滤 + token 聚合改为 `find_many` + Python 端计算。端侧数据量小，性能无问题。

4. **索引创建**：MongoRepository 在初始化时创建索引；FileRepository 忽略（内存不需要）。

5. **`ScienceSession.save()`**：内部的 `db.get_collection` 调用改为通过 `get_repository("sessions")` 访问。

### 迁移文件清单

| 文件 | 涉及集合 |
|------|----------|
| `mongodb/db.py` | 改造为 storage 初始化入口 |
| `route/auth.py` | users, user_sessions |
| `route/sessions.py` | sessions, skills, blocked_tools |
| `route/chat.py` | models, sessions |
| `route/models.py` | models |
| `route/statistics.py` | sessions |
| `route/task_settings.py` | task_settings |
| `route/rpa.py` | models |
| `deepagent/sessions.py` | sessions |
| `deepagent/agent.py` | skills, blocked_tools |
| `deepagent/mongo_skill_backend.py` | skills |
| `rpa/skill_exporter.py` | skills |
| `models.py` | models |
| `task_settings.py` | task_settings |
| `user/bootstrap.py` | users |
| `user/dependencies.py` | user_sessions |
| `main.py` | 启动/关闭生命周期 |

## 部署与配置

### 新增环境变量

```bash
STORAGE_BACKEND=local|mongo    # 默认 mongo（云侧）
LOCAL_DATA_DIR=./data           # 端侧数据目录，仅 local 模式生效
```

### Docker Compose 端侧 profile

```yaml
services:
  mongodb:
    profiles: ["cloud"]    # 端侧不启动

  backend:
    environment:
      - STORAGE_BACKEND=${STORAGE_BACKEND:-mongo}
      - LOCAL_DATA_DIR=/app/data
    volumes:
      - ./data:/app/data   # 端侧数据持久化

  frontend:
    # 不变
```

端侧启动：`STORAGE_BACKEND=local docker compose up backend frontend`
云侧启动：`docker compose --profile cloud up`（或保持现有行为不变）

### 启动生命周期（main.py）

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.storage_backend == "mongo":
        await db.connect()           # MongoDB 连接 + 索引
    else:
        await init_file_storage()    # 扫描 JSON 文件，加载内存索引

    await init_system_models()       # 通过 Repository，两种模式通用
    await ensure_admin_user()        # 通过 Repository，两种模式通用

    yield

    if settings.storage_backend == "mongo":
        await db.close()
```

## 测试策略

- Repository 接口的两套实现各自有单元测试
- FileRepository 的查询引擎针对实际用到的操作符（`$set`、`$or`、`$gte`、`$ne`、`$in`、`$exists`）做测试
- 现有集成测试通过切换 `STORAGE_BACKEND` 环境变量分别跑两遍
- 写入安全测试：验证 tmp + rename 的原子写入

## 不在范围内

- 数据迁移工具（local ↔ mongo 互转）— 后续按需添加
- 端侧多用户支持 — 端侧固定单用户
- Redis 替代方案 — 当前 Redis 仅用于 Celery 任务队列，端侧模式下 task-service 不启动，无需替代
- 前端改动 — 前端完全无感知，零改动
