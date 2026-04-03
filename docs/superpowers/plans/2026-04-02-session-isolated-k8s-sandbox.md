# Session-Isolated Sandbox Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shared AIO sandbox with session-isolated sandbox runtimes while keeping the frontend on a single backend domain, preserving live browser/VNC preview, and supporting both local Docker verification and Kubernetes beta deployment.

**Architecture:** Introduce a backend runtime domain that owns `session_id -> sandbox runtime` mapping and delegates runtime creation to a provider interface. DeepAgent execution and RPA browser access must resolve a per-session sandbox endpoint instead of using the global sandbox URL. Browser, VNC, shell, and file access stay behind backend-owned proxy routes so the frontend never sees container or pod addresses. Implement the provider abstraction first, verify isolation locally with Docker-backed per-session containers, then add the Kubernetes provider for beta rollout.

**Tech Stack:** FastAPI, MongoDB repository abstraction, Docker SDK or CLI wrapper for local runtime creation, Kubernetes Python client, httpx reverse proxying, WebSocket pass-through, Vue 3 frontend, existing sandbox image.

---

## File Map

**Create**
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\__init__.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\models.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\repository.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\provider.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\shared_runtime_provider.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\docker_runtime_provider.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\k8s_runtime_provider.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\session_runtime_manager.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\route\runtime_proxy.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_manager.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_proxy.py`

**Modify**
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\config.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\main.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\deepagent\agent.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\deepagent\full_sandbox_backend.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\rpa\cdp_connector.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\route\sessions.py`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\frontend\src\utils\sandbox.ts`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\frontend\src\components\SandboxPreview.vue`
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\frontend\src\components\VNCViewer.vue`
- `E:\Work-Project\OtherWork\ScienceClaw\docker-compose-china.yml`

**Deferred**
- `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\task-service\...`
  Task service stays on the old model for beta phase 1 unless explicitly expanded.

---

### Task 1: Add Runtime Domain And Persistence

**Files:**
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\__init__.py`
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\models.py`
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\repository.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\storage\__init__.py`
- Test: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_manager.py`

- [ ] **Step 1: Write the failing repository/model test**

```python
from backend.runtime.models import SessionRuntimeRecord


def test_runtime_record_roundtrip_defaults():
    record = SessionRuntimeRecord(
        session_id="sess-1",
        user_id="user-1",
        namespace="beta",
        pod_name="scienceclaw-sess-sess1",
        service_name="scienceclaw-sess-sess1-svc",
        rest_base_url="http://scienceclaw-sess-sess1-svc:8080",
        status="creating",
    )

    payload = record.model_dump()

    assert payload["session_id"] == "sess-1"
    assert payload["service_name"].endswith("-svc")
    assert payload["status"] == "creating"
    assert "created_at" in payload
    assert "last_used_at" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py::test_runtime_record_roundtrip_defaults -v`

Expected: FAIL with `ModuleNotFoundError` or missing runtime model class.

- [ ] **Step 3: Add runtime record model and repository helpers**

```python
# backend/runtime/models.py
from pydantic import BaseModel, Field
import time


class SessionRuntimeRecord(BaseModel):
    session_id: str
    user_id: str
    namespace: str
    pod_name: str
    service_name: str
    rest_base_url: str
    status: str
    created_at: int = Field(default_factory=lambda: int(time.time()))
    last_used_at: int = Field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None
```

```python
# backend/runtime/repository.py
from backend.storage import get_repository


def get_runtime_repository():
    return get_repository("session_runtimes")
```

- [ ] **Step 4: Register runtime collection in local storage bootstrap**

```python
# backend/storage/__init__.py
for name in (
    "users", "user_sessions", "sessions", "models",
    "skills", "blocked_tools", "task_settings", "session_events",
    "session_runtimes",
):
    ...
```

- [ ] **Step 5: Run tests to verify the model layer passes**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py -v`

Expected: PASS for the new model/repository tests.

- [ ] **Step 6: Commit**

```bash
git add ScienceClaw/backend/runtime ScienceClaw/backend/storage/__init__.py ScienceClaw/backend/tests/runtime/test_runtime_manager.py
git commit -m "feat: add session runtime persistence layer"
```

---

### Task 2: Add Runtime Provider Interface And Session Runtime Manager

**Files:**
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\provider.py`
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\shared_runtime_provider.py`
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\docker_runtime_provider.py`
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\k8s_runtime_provider.py`
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\session_runtime_manager.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\config.py`
- Test: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_manager.py`

- [ ] **Step 1: Write failing manager tests for create/reuse behavior**

```python
import pytest


@pytest.mark.asyncio
async def test_ensure_runtime_reuses_ready_record(fake_runtime_manager, ready_record):
    runtime = await fake_runtime_manager.ensure_runtime("sess-1", "user-1")
    again = await fake_runtime_manager.ensure_runtime("sess-1", "user-1")

    assert runtime.session_id == "sess-1"
    assert again.service_name == runtime.service_name
    assert fake_runtime_manager.provider.create_calls == 0


@pytest.mark.asyncio
async def test_ensure_runtime_creates_when_missing(fake_runtime_manager):
    runtime = await fake_runtime_manager.ensure_runtime("sess-2", "user-2")

    assert runtime.status == "ready"
    assert runtime.rest_base_url.startswith("http://scienceclaw-sess-")


def test_provider_factory_returns_docker_provider_when_requested(settings):
    settings.runtime_mode = "docker"
    provider = build_runtime_provider(settings)
    assert provider.__class__.__name__ == "DockerRuntimeProvider"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py::test_ensure_runtime_reuses_ready_record -v`

Expected: FAIL because runtime manager/provider factory do not exist yet.

- [ ] **Step 3: Add new runtime settings**

```python
# backend/config.py
runtime_mode: str = os.environ.get("RUNTIME_MODE", "shared")
runtime_idle_ttl_seconds: int = int(os.environ.get("RUNTIME_IDLE_TTL_SECONDS", "3600"))
runtime_image: str = os.environ.get("SESSION_SANDBOX_IMAGE", "scienceclaw-sandbox:local")
runtime_service_port: int = int(os.environ.get("SESSION_SANDBOX_PORT", "8080"))
docker_runtime_network: str = os.environ.get("DOCKER_RUNTIME_NETWORK", "scienceclaw_default")
k8s_namespace: str = os.environ.get("K8S_RUNTIME_NAMESPACE", "default")
```

- [ ] **Step 4: Add runtime provider interface and shared/docker/k8s provider skeletons**

```python
class RuntimeProvider(Protocol):
    async def create_runtime(self, session_id: str, user_id: str) -> SessionRuntimeRecord: ...
    async def delete_runtime(self, record: SessionRuntimeRecord) -> None: ...
    async def refresh_runtime(self, record: SessionRuntimeRecord) -> SessionRuntimeRecord: ...


def build_runtime_provider(settings) -> RuntimeProvider:
    if settings.runtime_mode == "docker":
        return DockerRuntimeProvider(settings)
    if settings.runtime_mode == "session_pod":
        return K8sRuntimeProvider(settings)
    return SharedRuntimeProvider(settings)
```

- [ ] **Step 5: Implement Docker provider first, then manager orchestration**

```python
class DockerRuntimeProvider:
    async def create_runtime(self, session_id: str, user_id: str) -> SessionRuntimeRecord:
        container_name = f"scienceclaw-sess-{session_id[:8]}"
        rest_base_url = f"http://{container_name}:{settings.runtime_service_port}"
        ...
        return SessionRuntimeRecord(...)


class SessionRuntimeManager:
    async def ensure_runtime(self, session_id: str, user_id: str) -> SessionRuntimeRecord:
        existing = await self.repo.find_one({"session_id": session_id, "status": "ready"})
        if existing:
            ...
            return SessionRuntimeRecord(**existing)
        created = await self.provider.create_runtime(session_id, user_id)
        ...
        return created
```

- [ ] **Step 6: Run manager tests**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py -v`

Expected: PASS with fake provider fixtures and provider factory coverage.

- [ ] **Step 7: Commit**

```bash
git add ScienceClaw/backend/runtime ScienceClaw/backend/config.py ScienceClaw/backend/tests/runtime/test_runtime_manager.py
git commit -m "feat: add runtime provider abstraction and manager"
```

---

### Task 3: Inject Session Runtime Into DeepAgent Execution

**Files:**
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\deepagent\agent.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\deepagent\full_sandbox_backend.py`
- Test: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_manager.py`

- [ ] **Step 1: Write failing execution wiring test**

```python
@pytest.mark.asyncio
async def test_deep_agent_uses_session_runtime_endpoint(monkeypatch):
    captured = {}

    class FakeSandboxBackend:
        def __init__(self, *args, sandbox_url=None, **kwargs):
            captured["sandbox_url"] = sandbox_url

    monkeypatch.setattr("backend.deepagent.agent.FullSandboxBackend", FakeSandboxBackend)
    ...
    await deep_agent(session_id="sess-1", user_id="user-1")

    assert captured["sandbox_url"] == "http://scienceclaw-sess-sess1-svc:8080"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py::test_deep_agent_uses_session_runtime_endpoint -v`

Expected: FAIL because `deep_agent()` still uses the global sandbox URL.

- [ ] **Step 3: Update FullSandboxBackend to accept explicit runtime endpoint**

```python
class FullSandboxBackend(SandboxBackendProtocol):
    def __init__(..., sandbox_url: str, ...):
        self._sandbox_url = sandbox_url.rstrip("/")
```

- [ ] **Step 4: Resolve runtime before backend creation**

```python
# backend/deepagent/agent.py
from backend.runtime import get_session_runtime_manager

runtime = await get_session_runtime_manager().ensure_runtime(session_id, user_id or "default_user")
sandbox = FullSandboxBackend(
    session_id=session_id,
    user_id=user_id or "default_user",
    sandbox_url=runtime.rest_base_url,
    ...
)
```

- [ ] **Step 5: Run the wiring tests**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py -k runtime_endpoint -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ScienceClaw/backend/deepagent/agent.py ScienceClaw/backend/deepagent/full_sandbox_backend.py ScienceClaw/backend/tests/runtime/test_runtime_manager.py
git commit -m "feat: route deepagent execution to session runtime"
```

---

### Task 4: Add Backend Runtime Proxy Routes For HTTP And WebSocket Access

**Files:**
- Create: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\route\runtime_proxy.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\main.py`
- Test: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_proxy.py`

- [ ] **Step 1: Write failing proxy route tests**

```python
def test_runtime_proxy_path_includes_session_id(test_client, fake_runtime_lookup):
    response = test_client.get("/api/v1/runtime/session/sess-1/http/v1/browser/info")
    assert response.status_code == 200
    assert response.json()["proxied_to"] == "http://scienceclaw-sess-sess1-svc:8080/v1/browser/info"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_proxy.py -v`

Expected: FAIL with missing route.

- [ ] **Step 3: Add HTTP proxy route**

```python
@router.api_route("/runtime/session/{session_id}/http/{path:path}", methods=["GET", "POST"])
async def proxy_runtime_http(session_id: str, path: str, request: Request):
    runtime = await manager.ensure_runtime(session_id, current_user.id)
    upstream = f"{runtime.rest_base_url}/{path}"
    ...
```

- [ ] **Step 4: Add WebSocket proxy route for shell/VNC pass-through**

```python
@router.websocket("/runtime/session/{session_id}/ws/{path:path}")
async def proxy_runtime_ws(websocket: WebSocket, session_id: str, path: str):
    runtime = await manager.ensure_runtime(session_id, current_user.id)
    ...
```

- [ ] **Step 5: Register router in app startup**

```python
# backend/main.py
from backend.route.runtime_proxy import router as runtime_proxy_router
app.include_router(runtime_proxy_router, prefix="/api/v1")
```

- [ ] **Step 6: Run proxy tests**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_proxy.py -v`

Expected: PASS for path resolution and authorization behavior.

- [ ] **Step 7: Commit**

```bash
git add ScienceClaw/backend/route/runtime_proxy.py ScienceClaw/backend/main.py ScienceClaw/backend/tests/runtime/test_runtime_proxy.py
git commit -m "feat: add session runtime proxy routes"
```

---

### Task 5: Move Browser/CDP/VNC Access To Session Proxy URLs

**Files:**
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\rpa\cdp_connector.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\frontend\src\utils\sandbox.ts`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\frontend\src\components\SandboxPreview.vue`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\frontend\src\components\VNCViewer.vue`

- [ ] **Step 1: Write failing frontend utility test or snapshot for session-aware URLs**

```ts
it('builds session-scoped VNC URL', () => {
  expect(getSandboxVncUrl('sess-1')).toContain('/api/v1/runtime/session/sess-1/http/vnc/index.html')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- sandbox`

Expected: FAIL because the current URL builder uses the shared sandbox base URL.

- [ ] **Step 3: Make sandbox URL helpers session-aware**

```ts
export function getSandboxVncUrl(sessionId: string): string {
  return `/api/v1/runtime/session/${sessionId}/http/vnc/index.html?autoconnect=true&resize=scale&view_only=true`
}
```

- [ ] **Step 4: Change VNC and preview components to require sessionId**

```vue
const vncUrl = computed(() => props.sessionId ? getSandboxVncUrl(props.sessionId) : '')
```

- [ ] **Step 5: Replace global CDP connector with session-aware lookup**

```python
async def get_browser(self, session_id: str) -> Browser:
    cdp_url = await self._fetch_cdp_url(session_id)
```

```python
url = f"/api/v1/runtime/session/{session_id}/http/v1/browser/info"
```

- [ ] **Step 6: Run frontend and backend smoke checks**

Run: `npm run build`

Run: `pytest ScienceClaw/backend/tests/runtime -v`

Expected: both pass; frontend no longer references the shared VNC root for cloud mode.

- [ ] **Step 7: Commit**

```bash
git add ScienceClaw/backend/rpa/cdp_connector.py ScienceClaw/frontend/src/utils/sandbox.ts ScienceClaw/frontend/src/components/SandboxPreview.vue ScienceClaw/frontend/src/components/VNCViewer.vue
git commit -m "feat: scope browser and vnc access to session runtime"
```

---

### Task 6: Bind Runtime Lifecycle To Session Lifecycle

**Files:**
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\route\sessions.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\main.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\runtime\session_runtime_manager.py`
- Test: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_manager.py`

- [ ] **Step 1: Write failing cleanup tests**

```python
@pytest.mark.asyncio
async def test_delete_session_destroys_runtime(fake_runtime_manager, saved_session):
    await delete_session(saved_session.session_id, current_user=...)
    assert fake_runtime_manager.provider.delete_calls == [saved_session.session_id]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py -k destroys_runtime -v`

Expected: FAIL because session deletion does not touch runtime state.

- [ ] **Step 3: Destroy runtime on session delete/stop**

```python
await get_session_runtime_manager().destroy_runtime(session_id)
```

- [ ] **Step 4: Add orphan cleanup on app startup/shutdown**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    await get_session_runtime_manager().cleanup_orphans()
```

- [ ] **Step 5: Add idle TTL cleanup worker**

```python
async def cleanup_expired(self) -> int:
    expired = await self.repo.find_many({"expires_at": {"$lte": int(time.time())}})
    ...
```

- [ ] **Step 6: Run cleanup tests**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py -v`

Expected: PASS for delete, orphan cleanup, and idle TTL logic.

- [ ] **Step 7: Commit**

```bash
git add ScienceClaw/backend/route/sessions.py ScienceClaw/backend/main.py ScienceClaw/backend/runtime/session_runtime_manager.py ScienceClaw/backend/tests/runtime/test_runtime_manager.py
git commit -m "feat: bind session lifecycle to runtime cleanup"
```

---

### Task 7: Add Runtime Mode Toggle And Local Docker Verification Path

**Files:**
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\config.py`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\docker-compose-china.yml`
- Modify: `E:\Work-Project\OtherWork\ScienceClaw\docs\superpowers\plans\2026-04-02-session-isolated-k8s-sandbox.md`
- Test: `E:\Work-Project\OtherWork\ScienceClaw\ScienceClaw\backend\tests\runtime\test_runtime_manager.py`

- [ ] **Step 1: Write failing config test**

```python
def test_runtime_mode_defaults_to_shared_in_local_dev(settings):
    assert settings.runtime_mode in {"shared", "docker", "session_pod"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py -k runtime_mode -v`

Expected: FAIL because the runtime mode and provider switching do not exist yet.

- [ ] **Step 3: Add runtime mode setting**

```python
runtime_mode: str = os.environ.get("RUNTIME_MODE", "shared")
```

- [ ] **Step 4: Update compose to support shared by default and docker mode for local isolation tests**

```yaml
environment:
  RUNTIME_MODE: shared
  DOCKER_RUNTIME_NETWORK: scienceclaw_default
```

- [ ] **Step 5: Gate provider selection and add local verification commands**

```python
provider = build_runtime_provider(settings)
```

- [ ] **Step 6: Document local verification commands**

Run: `docker ps --format "{{.Names}}" | findstr scienceclaw-sess-`

Run: `pytest ScienceClaw/backend/tests/runtime -v`

Expected: in `RUNTIME_MODE=docker`, two concurrent sessions create two `scienceclaw-sess-*` containers locally.

- [ ] **Step 6: Run config regression tests**

Run: `pytest ScienceClaw/backend/tests/runtime/test_runtime_manager.py -v`

Expected: PASS, and local docker dev remains functional until the k8s beta deployment is used.

- [ ] **Step 7: Commit**

```bash
git add ScienceClaw/backend/config.py docker-compose-china.yml ScienceClaw/backend/tests/runtime/test_runtime_manager.py
git commit -m "chore: add runtime mode switch for session pod rollout"
```

---

## Verification Checklist

- [ ] Shared cloud-mode VNC URLs no longer appear in frontend code paths.
- [ ] `deep_agent()` no longer hardcodes the global sandbox endpoint when `RUNTIME_MODE=session_pod`.
- [ ] A session with active browser automation gets a dedicated runtime record in Mongo.
- [ ] Deleting a session removes its runtime record and triggers pod cleanup.
- [ ] Two concurrent sessions produce two different runtime records and two different browser preview routes.
- [ ] Local Docker development still works with `RUNTIME_MODE=shared`.
- [ ] Local Docker isolation can be verified with `RUNTIME_MODE=docker`.
- [ ] Kubernetes beta rollout can be enabled with `RUNTIME_MODE=session_pod`.

## Rollout Order

1. Runtime domain and provider abstraction
2. Docker provider and local verification path
3. DeepAgent runtime injection
4. Backend proxy routes
5. Browser/VNC session scoping
6. Session lifecycle cleanup
7. Kubernetes provider and beta rollout

## Beta Exit Criteria

- Two concurrent local test sessions can open browser previews without seeing each other's page state.
- The same runtime logic can switch from Docker to Kubernetes by changing `RUNTIME_MODE`.
- Session A shell commands do not affect Session B filesystem or browser state.
- Runtime cleanup leaves no leaked pods after session deletion or TTL expiry.
- Frontend still works behind one backend domain without direct sandbox exposure.

## Beta Config Notes

For Kubernetes beta rollout, the backend now supports these runtime settings:

- `RUNTIME_MODE=session_pod`
- `K8S_RUNTIME_NAMESPACE`
- `K8S_RUNTIME_SERVICE_ACCOUNT`
- `K8S_RUNTIME_IMAGE_PULL_POLICY`
- `K8S_RUNTIME_IMAGE_PULL_SECRETS`
- `K8S_RUNTIME_NODE_SELECTOR`
- `K8S_RUNTIME_ENV`
- `K8S_RUNTIME_LABELS`
- `K8S_RUNTIME_ANNOTATIONS`
- `K8S_RUNTIME_CPU_REQUEST`
- `K8S_RUNTIME_CPU_LIMIT`
- `K8S_RUNTIME_MEMORY_REQUEST`
- `K8S_RUNTIME_MEMORY_LIMIT`
- `K8S_RUNTIME_TOLERATIONS_JSON`
- `K8S_RUNTIME_WORKSPACE_VOLUME_NAME`
- `K8S_RUNTIME_WORKSPACE_MOUNT_PATH`
- `K8S_RUNTIME_WORKSPACE_PVC_CLAIM`
- `K8S_RUNTIME_EXTRA_VOLUMES_JSON`
- `K8S_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON`

Recommended minimal beta example:

```env
RUNTIME_MODE=session_pod
SESSION_SANDBOX_IMAGE=registry.example.com/scienceclaw-sandbox:beta
K8S_RUNTIME_NAMESPACE=scienceclaw-beta
K8S_RUNTIME_SERVICE_ACCOUNT=scienceclaw-runtime
K8S_RUNTIME_IMAGE_PULL_POLICY=IfNotPresent
K8S_RUNTIME_IMAGE_PULL_SECRETS=regcred
K8S_RUNTIME_NODE_SELECTOR=pool:runtime
K8S_RUNTIME_CPU_REQUEST=500m
K8S_RUNTIME_CPU_LIMIT=2
K8S_RUNTIME_MEMORY_REQUEST=1Gi
K8S_RUNTIME_MEMORY_LIMIT=4Gi
K8S_RUNTIME_WORKSPACE_VOLUME_NAME=workspace
K8S_RUNTIME_WORKSPACE_MOUNT_PATH=/home/scienceclaw
K8S_RUNTIME_WORKSPACE_PVC_CLAIM=scienceclaw-workspace
K8S_RUNTIME_EXTRA_VOLUMES_JSON=[{"name":"tools","persistentVolumeClaim":{"claimName":"scienceclaw-tools"}}]
K8S_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON=[{"name":"tools","mountPath":"/app/Tools","readOnly":true}]
```

Notes:

- If `K8S_RUNTIME_WORKSPACE_PVC_CLAIM` is empty, each session pod falls back to `emptyDir` workspace storage.
- `K8S_RUNTIME_EXTRA_VOLUMES_JSON` and `K8S_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON` should be used for any cluster-specific mounts such as `/app/Tools`, `/skills`, or custom assets.
- The workspace mount must remain aligned with `WORKSPACE_DIR` / `SANDBOX_WORKSPACE_DIR` assumptions in backend runtime code.
