# Local 模式去 Sandbox 容器依赖 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `STORAGE_BACKEND=local` 时 backend 完全脱离 Docker sandbox 容器，代码执行用本地 subprocess，RPA 用本地 Playwright + CDP screencast 双向交互。

**Architecture:** `agent.py` 的 `_build_backend()` 根据 `STORAGE_BACKEND` 选择 `LocalShellBackend`（deepagents 内置）或 `FullSandboxBackend`。RPA 新增 `LocalCDPConnector` 在宿主机启动 Playwright，`ScreencastService` 通过 CDP 推送画面帧并注入用户输入。前端 RecorderPage 在 local 模式下用 canvas + WebSocket 替代 noVNC iframe。

**Tech Stack:** deepagents `LocalShellBackend`、Playwright CDP Protocol（`Page.startScreencast`、`Input.dispatch*`）、FastAPI WebSocket、Vue 3 canvas

---

## File Structure

### Modified Files

| File | Responsibility |
|------|---------------|
| `backend/deepagent/agent.py` | `_build_backend()` 根据 storage_backend 选择后端；local 模式跳过 skill 注入；`deep_agent_eval()` 同理 |
| `backend/rpa/cdp_connector.py` | 新增 `LocalCDPConnector` 类；导出选择函数 |
| `backend/rpa/manager.py` | `create_session()` 根据 storage_backend 选择连接器 |
| `backend/route/rpa.py` | 新增 `/screencast/{session_id}` WebSocket endpoint；`start_rpa_session` 适配 local 模式 |
| `backend/main.py` | `client-config` 返回 `storage_backend` 字段 |
| `frontend/src/utils/sandbox.ts` | 导出 `isLocalMode()` 函数 |
| `frontend/src/pages/rpa/RecorderPage.vue` | local 模式用 canvas + WebSocket 替代 noVNC iframe |

### New Files

| File | Responsibility |
|------|---------------|
| `backend/rpa/screencast.py` | CDP screencast 帧推送 + Input.dispatch* 输入注入 |

---

## Task 1: agent.py — LocalShellBackend 切换

**Files:**
- Modify: `backend/deepagent/agent.py:31-106` (imports + `_build_backend`)
- Modify: `backend/deepagent/agent.py:348-538` (`deep_agent` + `deep_agent_eval`)

- [ ] **Step 1: 添加 LocalShellBackend import**

在 `agent.py` 第 32 行，修改 import：

```python
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.local_shell import LocalShellBackend
```

- [ ] **Step 2: 修改 `_build_backend()` 支持 local 模式**

替换 `_build_backend` 函数（第 77-105 行）。关键变化：函数签名中 `sandbox` 参数类型从 `FullSandboxBackend` 改为通用类型；local 模式下 `/skills/` 路由用 `FilesystemBackend` 而非 `MongoSkillBackend`：

```python
def _build_backend(session_id: str, sandbox,
                    user_id: str | None = None, blocked_skills: Set[str] | None = None):
    """构建 CompositeBackend（会话级隔离）。"""
    routes = {}

    if os.path.isdir(_BUILTIN_SKILLS_DIR):
        logger.info(f"[Skills] 内置 skills: {_BUILTIN_SKILLS_DIR} → {_BUILTIN_SKILLS_ROUTE}")
        routes[_BUILTIN_SKILLS_ROUTE] = FilesystemBackend(
            root_dir=_BUILTIN_SKILLS_DIR,
            virtual_mode=True,
        )

    if settings.storage_backend == "local":
        _ext_skills_dir = os.environ.get("EXTERNAL_SKILLS_DIR", "./Skills")
        if os.path.isdir(_ext_skills_dir):
            logger.info(f"[Skills] 本地 skills: {_ext_skills_dir} → {_EXTERNAL_SKILLS_ROUTE}")
            routes[_EXTERNAL_SKILLS_ROUTE] = FilesystemBackend(
                root_dir=_ext_skills_dir,
                virtual_mode=True,
            )
    elif user_id:
        logger.info(f"[Skills] MongoDB skills for user={user_id} → {_EXTERNAL_SKILLS_ROUTE}"
                     f" (blocked: {blocked_skills or set()})")
        routes[_EXTERNAL_SKILLS_ROUTE] = MongoSkillBackend(
            user_id=user_id,
            blocked_skills=blocked_skills,
        )

    if routes:
        return lambda rt: CompositeBackend(default=sandbox, routes=routes)
    else:
        return sandbox
```

- [ ] **Step 3: 修改 `deep_agent()` 中 sandbox 实例化（第 387-414 行）**

```python
    is_local = settings.storage_backend == "local"

    if is_local:
        local_workspace = os.path.join(_WORKSPACE_DIR, session_id)
        os.makedirs(local_workspace, exist_ok=True)
        sandbox = LocalShellBackend(
            root_dir=local_workspace,
            virtual_mode=False,
            timeout=ts.sandbox_exec_timeout,
            inherit_env=True,
        )
        sandbox_workspace = local_workspace
        sandbox_info = None
    else:
        sandbox = FullSandboxBackend(
            session_id=session_id,
            user_id=user_id or "default_user",
            base_dir=_WORKSPACE_DIR,
            sandbox_base_dir=_SANDBOX_WORKSPACE_DIR,
            execute_timeout=ts.sandbox_exec_timeout,
            max_output_chars=ts.max_output_chars,
        )
        sandbox_workspace = sandbox.workspace
        local_workspace = os.path.join(_WORKSPACE_DIR, session_id)
        ctx = await sandbox.get_context()
        if ctx.get("success"):
            sandbox_info = ctx.get("data")

    # 1.5 将用户技能文件注入沙箱（仅云端模式）
    if not is_local and user_id:
        try:
            await _inject_skills_to_sandbox(
                sandbox, sandbox_workspace, user_id, blocked_skills,
            )
        except Exception as exc:
            logger.warning(f"[Skills] 技能注入沙箱失败: {exc}")
```

- [ ] **Step 4: 修改 `deep_agent_eval()` 中 sandbox 实例化（第 571-578 行）**

同 Step 3 的模式，local 模式用 `LocalShellBackend`，云端用 `FullSandboxBackend`。skills 路由中 local 模式用 `FilesystemBackend` 替代 `MongoSkillBackend`。

- [ ] **Step 5: 验证 import**

Run: `cd D:/code/MyScienceClaw/ScienceClaw/backend && python -c "from backend.deepagent.agent import _build_backend; print('import ok')"`
Expected: `import ok`

- [ ] **Step 6: Commit**

```bash
git add backend/deepagent/agent.py
git commit -m "feat: agent.py 支持 STORAGE_BACKEND=local 时使用 LocalShellBackend"
```

---

## Task 2: client-config 返回 storage_backend

**Files:**
- Modify: `backend/main.py:92-98`

- [ ] **Step 1: 修改 client_config endpoint**

在 `main.py` 第 92-98 行，`client_config()` 返回值中添加 `storage_backend`：

```python
    @app.get("/api/v1/client-config")
    async def client_config():
        """Return configuration needed by the frontend."""
        from backend.config import settings
        return {
            "sandbox_public_url": settings.sandbox_public_url or "",
            "storage_backend": settings.storage_backend,
        }
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat: client-config 返回 storage_backend 供前端判断模式"
```

---

## Task 3: LocalCDPConnector — 本地 Playwright 启动

**Files:**
- Modify: `backend/rpa/cdp_connector.py`

- [ ] **Step 1: 新增 LocalCDPConnector 类**

在 `cdp_connector.py` 文件末尾（第 120 行 `cdp_connector = CDPConnector()` 之前），添加 `LocalCDPConnector`：

```python
class LocalCDPConnector:
    """Local CDP connector — launches Playwright on the host machine.

    Unlike CDPConnector which connects to a remote sandbox browser,
    this launches a local headful Chromium and provides CDP session access.
    """

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()
        self._pw_loop: Optional[asyncio.AbstractEventLoop] = None
        self._pw_thread: Optional[threading.Thread] = None

    def _ensure_pw_loop(self):
        """Start a background thread with ProactorEventLoop for Playwright."""
        if self._pw_thread and self._pw_thread.is_alive():
            return
        self._pw_loop = asyncio.new_event_loop()
        import sys
        if sys.platform == "win32":
            self._pw_loop = asyncio.ProactorEventLoop()
        self._pw_thread = threading.Thread(
            target=self._pw_loop.run_forever, daemon=True, name="playwright-local-loop"
        )
        self._pw_thread.start()

    async def _run_in_pw_loop(self, coro):
        """Schedule a coroutine on the Playwright event loop and await result."""
        self._ensure_pw_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._pw_loop)
        return await asyncio.wrap_future(future)

    async def get_browser(self) -> Browser:
        """Launch or return existing local Playwright browser."""
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser

            logger.info("Launching local Playwright Chromium (headful)...")
            self._playwright, self._browser = await self._run_in_pw_loop(
                self._launch()
            )
            logger.info("Local Playwright browser launched")
            return self._browser

    @staticmethod
    async def _launch():
        """Start Playwright and launch local Chromium (runs in pw_loop)."""
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=False)
        return pw, browser

    async def close(self):
        """Clean up local browser."""
        if self._browser:
            try:
                await self._run_in_pw_loop(self._browser.close())
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                if self._pw_loop and self._pw_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._playwright.stop(), self._pw_loop
                    )
                    future.result(timeout=5)
                self._playwright = None
            except Exception:
                pass
        if self._pw_loop:
            self._pw_loop.call_soon_threadsafe(self._pw_loop.stop)
            self._pw_loop = None
```

- [ ] **Step 2: 添加 connector 选择函数和全局实例**

替换文件末尾的全局实例（第 119-120 行）：

```python
# Global singletons
cdp_connector = CDPConnector()
local_cdp_connector = LocalCDPConnector()


def get_cdp_connector():
    """Return the appropriate CDP connector based on storage_backend."""
    if settings.storage_backend == "local":
        return local_cdp_connector
    return cdp_connector
```

- [ ] **Step 3: Commit**

```bash
git add backend/rpa/cdp_connector.py
git commit -m "feat: 新增 LocalCDPConnector，本地启动 Playwright 浏览器"
```

---

## Task 4: ScreencastService — CDP 画面推送 + 输入注入

**Files:**
- Create: `backend/rpa/screencast.py`

- [ ] **Step 1: 创建 screencast.py**

```python
"""CDP Screencast service: pushes browser frames to frontend via WebSocket,
injects user input events back into the browser via CDP Input.dispatch*."""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ScreencastService:
    """Bidirectional bridge between frontend WebSocket and CDP browser.

    - Browser → Frontend: Page.startScreencast → screencastFrame events → WS send
    - Frontend → Browser: WS receive → Input.dispatchMouseEvent / dispatchKeyEvent
    """

    def __init__(self, cdp_session):
        self._cdp = cdp_session
        self._viewport_width = 1280
        self._viewport_height = 720
        self._running = False
        self._websocket = None

    async def start(self, websocket):
        """Start screencast and run bidirectional message loop.

        This method blocks until the WebSocket disconnects or stop() is called.
        """
        self._websocket = websocket
        self._running = True

        # Listen for screencast frames from CDP
        self._cdp.on("Page.screencastFrame", self._on_frame)

        await self._cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 60,
            "maxWidth": self._viewport_width,
            "maxHeight": self._viewport_height,
        })

        try:
            # Read input events from frontend
            while self._running:
                try:
                    raw = await asyncio.wait_for(
                        websocket.receive_text(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        break
                    continue

                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                evt_type = event.get("type")
                if evt_type == "mouse":
                    await self._dispatch_mouse(event)
                elif evt_type == "keyboard":
                    await self._dispatch_key(event)
                elif evt_type == "wheel":
                    await self._dispatch_wheel(event)
                elif evt_type == "pong":
                    pass  # keepalive response
        except Exception as e:
            logger.debug(f"Screencast loop ended: {e}")
        finally:
            await self.stop()

    async def _on_frame(self, params: dict):
        """Handle CDP Page.screencastFrame event."""
        if not self._running or not self._websocket:
            return

        # Ack the frame to keep receiving
        session_id = params.get("sessionId", 0)
        try:
            await self._cdp.send("Page.screencastFrameAck", {
                "sessionId": session_id,
            })
        except Exception:
            pass

        # Update viewport from metadata
        metadata = params.get("metadata", {})
        if metadata.get("deviceWidth"):
            self._viewport_width = metadata["deviceWidth"]
        if metadata.get("deviceHeight"):
            self._viewport_height = metadata["deviceHeight"]

        # Push frame to frontend
        try:
            await self._websocket.send_json({
                "type": "frame",
                "data": params.get("data", ""),
                "metadata": {
                    "width": self._viewport_width,
                    "height": self._viewport_height,
                    "timestamp": metadata.get("timestamp", 0),
                },
            })
        except Exception:
            self._running = False

    async def _dispatch_mouse(self, event: dict):
        """Convert normalized mouse event to CDP Input.dispatchMouseEvent."""
        x = event.get("x", 0) * self._viewport_width
        y = event.get("y", 0) * self._viewport_height
        try:
            await self._cdp.send("Input.dispatchMouseEvent", {
                "type": event.get("action", "mouseMoved"),
                "x": x,
                "y": y,
                "button": event.get("button", "left"),
                "clickCount": event.get("clickCount", 0),
                "modifiers": event.get("modifiers", 0),
            })
        except Exception as e:
            logger.debug(f"Mouse dispatch error: {e}")

    async def _dispatch_key(self, event: dict):
        """Convert keyboard event to CDP Input.dispatchKeyEvent."""
        try:
            params: dict[str, Any] = {
                "type": event.get("action", "keyDown"),
                "modifiers": event.get("modifiers", 0),
            }
            if event.get("key"):
                params["key"] = event["key"]
            if event.get("code"):
                params["code"] = event["code"]
            if event.get("text"):
                params["text"] = event["text"]
            if event.get("windowsVirtualKeyCode"):
                params["windowsVirtualKeyCode"] = event["windowsVirtualKeyCode"]
            await self._cdp.send("Input.dispatchKeyEvent", params)
        except Exception as e:
            logger.debug(f"Key dispatch error: {e}")

    async def _dispatch_wheel(self, event: dict):
        """Convert wheel event to CDP Input.dispatchMouseEvent with mouseWheel type."""
        x = event.get("x", 0) * self._viewport_width
        y = event.get("y", 0) * self._viewport_height
        try:
            await self._cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": event.get("deltaX", 0),
                "deltaY": event.get("deltaY", 0),
                "modifiers": event.get("modifiers", 0),
            })
        except Exception as e:
            logger.debug(f"Wheel dispatch error: {e}")

    async def stop(self):
        """Stop screencast."""
        self._running = False
        try:
            await self._cdp.send("Page.stopScreencast")
        except Exception:
            pass
```

- [ ] **Step 2: Commit**

```bash
git add backend/rpa/screencast.py
git commit -m "feat: 新增 ScreencastService，CDP 画面推送 + 输入注入"
```

---

## Task 5: RPA Manager — 适配 local 模式

**Files:**
- Modify: `backend/rpa/manager.py:1-12,446-501`

- [ ] **Step 1: 修改 import 和 create_session**

在 `manager.py` 顶部，将 `from .cdp_connector import cdp_connector` 改为：

```python
from .cdp_connector import get_cdp_connector
```

修改 `create_session()` 方法（第 446 行），将 `cdp_connector.get_browser()` 改为 `get_cdp_connector().get_browser()`：

```python
    async def create_session(self, user_id: str, sandbox_session_id: str) -> RPASession:
        session_id = str(uuid.uuid4())
        session = RPASession(
            id=session_id,
            user_id=user_id,
            sandbox_session_id=sandbox_session_id,
        )
        self.sessions[session_id] = session

        connector = get_cdp_connector()
        browser = await connector.get_browser()
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()
        # ... rest unchanged
```

- [ ] **Step 2: Commit**

```bash
git add backend/rpa/manager.py
git commit -m "feat: RPA manager 使用 get_cdp_connector() 适配 local 模式"
```

---

## Task 6: RPA Route — screencast WebSocket endpoint

**Files:**
- Modify: `backend/route/rpa.py`

- [ ] **Step 1: 修改 import**

在 `rpa.py` 顶部 imports 中，将 `from backend.rpa.cdp_connector import cdp_connector` 改为：

```python
from backend.rpa.cdp_connector import get_cdp_connector
from backend.rpa.screencast import ScreencastService
from backend.config import settings
```

- [ ] **Step 2: 修改 test_script endpoint**

在 `test_script()` 函数（第 143 行），将 `cdp_connector.get_browser()` 改为 `get_cdp_connector().get_browser()`：

```python
    browser = await get_cdp_connector().get_browser()
```

- [ ] **Step 3: 新增 screencast WebSocket endpoint**

在 `rpa.py` 文件末尾（`steps_stream` 之后），添加：

```python
@router.websocket("/screencast/{session_id}")
async def rpa_screencast(websocket: WebSocket, session_id: str):
    """CDP screencast: push browser frames + receive input events.

    Only used in local mode (STORAGE_BACKEND=local).
    """
    await websocket.accept()

    session = await rpa_manager.get_session(session_id)
    if not session:
        await websocket.close(code=1008, reason="Session not found")
        return

    page = rpa_manager.get_page(session_id)
    if not page:
        await websocket.close(code=1008, reason="No active page")
        return

    # Get CDP session from the page
    try:
        cdp_session = await page.context.new_cdp_session(page)
    except Exception as e:
        logger.error(f"Failed to create CDP session: {e}")
        await websocket.close(code=1011, reason="CDP session failed")
        return

    screencast = ScreencastService(cdp_session)
    try:
        await screencast.start(websocket)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Screencast error: {e}")
    finally:
        await screencast.stop()
        try:
            await cdp_session.detach()
        except Exception:
            pass
```

- [ ] **Step 4: Commit**

```bash
git add backend/route/rpa.py
git commit -m "feat: 新增 /rpa/screencast WebSocket endpoint"
```

---

## Task 7: 前端 — sandbox.ts 添加 storage_backend 检测

**Files:**
- Modify: `frontend/src/utils/sandbox.ts`

- [ ] **Step 1: 添加 storage_backend 缓存和获取函数**

在 `sandbox.ts` 中，`_fetchPromise` 变量之后（第 15 行），添加：

```typescript
let _storageBackend: string | null = null;
```

修改 `fetchSandboxPublicUrl()` 函数，同时缓存 `storage_backend`：

```typescript
async function fetchSandboxPublicUrl(): Promise<string> {
  if (_sandboxBaseUrl !== null) return _sandboxBaseUrl;
  if (_fetchPromise) return _fetchPromise;

  _fetchPromise = apiClient
    .get('/client-config')
    .then((res) => {
      _sandboxBaseUrl = res.data?.sandbox_public_url || '';
      _storageBackend = res.data?.storage_backend || 'mongo';
      return _sandboxBaseUrl;
    })
    .catch(() => {
      _sandboxBaseUrl = '';
      _storageBackend = 'mongo';
      return '';
    });

  return _fetchPromise;
}
```

在文件导出区域添加：

```typescript
export function isLocalMode(): boolean {
  return _storageBackend === 'local';
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/utils/sandbox.ts
git commit -m "feat: sandbox.ts 添加 isLocalMode() 检测"
```

---

## Task 8: 前端 — RecorderPage 支持 CDP screencast

**Files:**
- Modify: `frontend/src/pages/rpa/RecorderPage.vue`

- [ ] **Step 1: 添加 import 和 screencast 状态**

在 `RecorderPage.vue` 的 `<script setup>` 中（第 6 行），添加 import：

```typescript
import { getRpaVncUrl, isLocalMode } from '@/utils/sandbox';
```

在状态变量区域（第 16 行附近），添加：

```typescript
const localMode = ref(isLocalMode());
const canvasRef = ref<HTMLCanvasElement | null>(null);
let screencastWs: WebSocket | null = null;
```

- [ ] **Step 2: 添加 screencast 连接逻辑**

在 `initSession()` 函数的 `if (resp.data.status === 'success')` 块内（第 56 行附近），添加 screencast 连接：

```typescript
      if (localMode.value) {
        connectScreencast(resp.data.session.id);
      }
```

在 `startPollingSteps` 函数之后，添加 screencast 函数：

```typescript
const connectScreencast = (sid: string) => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${proto}//${window.location.host}/api/v1/rpa/screencast/${sid}`;
  screencastWs = new WebSocket(wsUrl);

  screencastWs.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === 'frame') {
      drawFrame(msg.data, msg.metadata);
    }
  };

  screencastWs.onclose = () => {
    screencastWs = null;
  };
};

const drawFrame = (base64Data: string, metadata: { width: number; height: number }) => {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const img = new Image();
  img.onload = () => {
    canvas.width = metadata.width;
    canvas.height = metadata.height;
    ctx.drawImage(img, 0, 0);
  };
  img.src = `data:image/jpeg;base64,${base64Data}`;
};

const sendInputEvent = (event: MouseEvent | KeyboardEvent | WheelEvent) => {
  if (!screencastWs || screencastWs.readyState !== WebSocket.OPEN) return;
  const canvas = canvasRef.value;
  if (!canvas) return;

  if (event instanceof MouseEvent && !(event instanceof WheelEvent)) {
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;

    let action = 'mouseMoved';
    let clickCount = 0;
    if (event.type === 'mousedown') { action = 'mousePressed'; clickCount = 1; }
    else if (event.type === 'mouseup') { action = 'mouseReleased'; clickCount = 1; }

    const buttonMap: Record<number, string> = { 0: 'left', 1: 'middle', 2: 'right' };
    screencastWs.send(JSON.stringify({
      type: 'mouse', action, x, y,
      button: buttonMap[event.button] || 'left',
      clickCount,
      modifiers: getModifiers(event),
    }));
  } else if (event instanceof WheelEvent) {
    const rect = canvas.getBoundingClientRect();
    screencastWs.send(JSON.stringify({
      type: 'wheel',
      x: (event.clientX - rect.left) / rect.width,
      y: (event.clientY - rect.top) / rect.height,
      deltaX: event.deltaX,
      deltaY: event.deltaY,
      modifiers: getModifiers(event),
    }));
  } else if (event instanceof KeyboardEvent) {
    const action = event.type === 'keydown' ? 'keyDown' : 'keyUp';
    screencastWs.send(JSON.stringify({
      type: 'keyboard', action,
      key: event.key,
      code: event.code,
      text: event.type === 'keydown' && event.key.length === 1 ? event.key : '',
      modifiers: getModifiers(event),
    }));
  }
};

const getModifiers = (e: MouseEvent | KeyboardEvent): number => {
  let m = 0;
  if (e.altKey) m |= 1;
  if (e.ctrlKey) m |= 2;
  if (e.metaKey) m |= 4;
  if (e.shiftKey) m |= 8;
  return m;
};
```

- [ ] **Step 3: 修改 onBeforeUnmount 清理 WebSocket**

在 `onBeforeUnmount` 中（第 105 行），添加 screencast 清理：

```typescript
onBeforeUnmount(() => {
  if (timerInterval.value) clearInterval(timerInterval.value);
  if (pollInterval) clearInterval(pollInterval);
  if (screencastWs) { screencastWs.close(); screencastWs = null; }
});
```

- [ ] **Step 4: 修改 template — 条件渲染 iframe 或 canvas**

替换 VNC iframe 区域（第 285-291 行）：

```html
            <!-- Remote mode: noVNC iframe -->
            <iframe
              v-if="sessionId && !localMode"
              :src="vncUrl"
              class="w-full h-full border-0"
              allow="clipboard-read; clipboard-write"
            />
            <!-- Local mode: CDP screencast canvas -->
            <canvas
              v-if="sessionId && localMode"
              ref="canvasRef"
              class="w-full h-full object-contain cursor-default"
              tabindex="0"
              @mousedown="sendInputEvent"
              @mouseup="sendInputEvent"
              @mousemove="sendInputEvent"
              @wheel.prevent="sendInputEvent"
              @keydown.prevent="sendInputEvent"
              @keyup.prevent="sendInputEvent"
              @contextmenu.prevent
            />
```

同时修改底部状态栏（第 298-301 行），根据模式显示不同文字：

```html
            <div v-if="sessionId" class="absolute bottom-6 left-1/2 -translate-x-1/2 bg-white/10 backdrop-blur-md border border-white/20 px-4 py-2 rounded-full flex items-center gap-3">
              <Radio class="text-red-400 animate-pulse" :size="14" />
              <span class="text-white text-[10px] font-bold tracking-wider uppercase">
                {{ localMode ? '实时 CDP 串流' : '实时 VNC 串流' }}
              </span>
            </div>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/rpa/RecorderPage.vue
git commit -m "feat: RecorderPage 支持 local 模式 CDP screencast 双向交互"
```

---

## Task 9: 集成验证

- [ ] **Step 1: 设置 .env 为 local 模式**

确认 `backend/.env` 中 `STORAGE_BACKEND=local`。

- [ ] **Step 2: 启动 backend**

Run: `cd D:/code/MyScienceClaw/ScienceClaw/backend && uv run uvicorn main:app --host 0.0.0.0 --port 8000`

验证启动日志中无 sandbox 连接错误。

- [ ] **Step 3: 验证 agent 代码执行**

通过前端 chat 发送 "执行 `echo hello`"，确认 `LocalShellBackend` 正确执行并返回结果。

- [ ] **Step 4: 验证 RPA 录制**

打开 `/rpa/recorder`，确认：
- 本地 Playwright 浏览器启动
- canvas 显示 screencast 画面
- 鼠标点击/键盘输入能注入到浏览器
- 步骤自动记录到左侧面板

- [ ] **Step 5: 验证云端模式不受影响**

将 `STORAGE_BACKEND=mongo` 后重启，确认原有 sandbox 流程正常。
