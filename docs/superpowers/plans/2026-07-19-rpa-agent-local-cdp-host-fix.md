# RPA Agent Local CDP Host Fix Implementation Plan

**Status:** completed（2026-07-19）；实现与验证证据见 [EV-030](../../evidence/EV-030-rpa-agent-local-cdp-host-fix.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `STORAGE_BACKEND=local` 且 `RUNTIME_MODE` 缺省的 ScienceClaw 直接使用本地 Chromium/CDP 创建新版 RPA Agent 会话，不再访问 `http://sandbox:8080`。

**Architecture:** 把本地 Chromium 启动、CDP URL 和 Playwright 安全启动参数移到 `backend.runtime` 中立宿主层，旧 RPA Connector 仅保留兼容性导出。新版 ScienceClaw Host Adapter 根据 `storage_backend` 注入 Local CDP resolver；非 local 路径继续使用现有 Session Runtime Lease。两条路径在获得 CDP URL 后共用连接、Page 注册、引用计数和清理逻辑。

**Tech Stack:** Python 3.12、FastAPI、Playwright async API、pytest/pytest-asyncio、Vue 3/Vitest、AgentMentor Feature/Evidence。

---

## 文件结构

- Create `RpaClaw/backend/runtime/playwright_security.py`：中立的 Chromium 启动参数与 Context 参数。
- Create `RpaClaw/backend/runtime/local_cdp.py`：Windows 兼容的 Local CDP 浏览器生命周期和公开 `get_cdp_url()`。
- Modify `RpaClaw/backend/rpa/playwright_security.py`：从中立模块兼容性重导出旧 API。
- Modify `RpaClaw/backend/rpa/cdp_connector.py`：保留远程 Connector；本地 Connector 和 singleton 改为中立模块重导出。
- Modify `RpaClaw/backend/rpa_agent/host/scienceclaw_browser.py`：支持注入直接 CDP resolver，跳过 Session Runtime。
- Modify `RpaClaw/backend/route/rpa_agent.py`：按 `settings.storage_backend` 选择 local/非 local resolver，并记录脱敏宿主异常。
- Create `RpaClaw/backend/tests/runtime/test_local_cdp.py`：中立 Local CDP 生命周期与旧入口兼容回归。
- Modify `RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py`：直接 CDP resolver、引用计数和清理回归。
- Modify `RpaClaw/backend/tests/rpa_agent/test_route.py`：真实默认 Provider 的 local 模式路由回归和错误日志回归。
- Create `RpaClaw/backend/tests/rpa_agent/test_local_host_live.py`：显式 opt-in 的真实 Windows Local CDP 会话冒烟。
- Create `docs/evidence/EV-030-rpa-agent-local-cdp-host-fix.md`：记录 F026.1 红绿测试、回归和真实本地冒烟证据。
- Modify `docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md`：完成 F026.1 Patch History、Evidence 链接和 Recovery Snapshot。

### Task 1: 建立中立 Local CDP 宿主层

**Files:**
- Create: `RpaClaw/backend/runtime/playwright_security.py`
- Create: `RpaClaw/backend/runtime/local_cdp.py`
- Modify: `RpaClaw/backend/rpa/playwright_security.py`
- Modify: `RpaClaw/backend/rpa/cdp_connector.py`
- Create: `RpaClaw/backend/tests/runtime/test_local_cdp.py`
- Test: `RpaClaw/backend/tests/runtime/test_cdp_connector.py`

- [ ] **Step 1: 写中立模块不存在的失败测试**

```python
def test_legacy_local_connector_reexports_neutral_singleton():
    from backend.runtime.local_cdp import LocalCDPConnector, local_cdp_connector
    from backend.rpa import cdp_connector

    assert cdp_connector.LocalCDPConnector is LocalCDPConnector
    assert cdp_connector.local_cdp_connector is local_cdp_connector


@pytest.mark.asyncio
async def test_local_connector_exposes_public_cdp_url(monkeypatch):
    connector = LocalCDPConnector()

    async def fake_ensure_browser() -> None:
        connector._cdp_url = "ws://127.0.0.1:19222/devtools/browser/local"

    monkeypatch.setattr(connector, "_ensure_browser", fake_ensure_browser)
    assert await connector.get_cdp_url() == "ws://127.0.0.1:19222/devtools/browser/local"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/runtime/test_local_cdp.py -q
```

Expected: collection fails with `ModuleNotFoundError: backend.runtime.local_cdp`.

- [ ] **Step 3: 移植安全参数和 LocalCDPConnector**

在 `backend.runtime.local_cdp` 中提供以下公开边界：

```python
class LocalCDPConnector:
    async def get_cdp_url(self) -> str:
        async with self._lock:
            await self._ensure_browser()
            if not self._cdp_url:
                raise RuntimeError("local_browser.cdp_url_unavailable")
            return self._cdp_url

local_cdp_connector = LocalCDPConnector()
```

`get_cdp_url()` 必须在同一锁内确保 Browser 已启动，并返回该 Browser 的精确 `webSocketDebuggerUrl`；不得启动第二个浏览器。旧 `backend.rpa.cdp_connector` 通过显式 import 重导出这两个名字。

- [ ] **Step 4: 运行中立与旧入口回归并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/runtime/test_local_cdp.py RpaClaw/backend/tests/runtime/test_cdp_connector.py -q
```

Expected: all selected tests pass with zero warnings introduced by the new modules.

- [ ] **Step 5: 提交宿主基础设施**

```powershell
git add RpaClaw/backend/runtime/playwright_security.py RpaClaw/backend/runtime/local_cdp.py RpaClaw/backend/rpa/playwright_security.py RpaClaw/backend/rpa/cdp_connector.py RpaClaw/backend/tests/runtime/test_local_cdp.py RpaClaw/backend/tests/runtime/test_cdp_connector.py
git commit -m "refactor: extract neutral local cdp host"
```

### Task 2: 让 Browser Runtime Lease 接受直接 CDP resolver

**Files:**
- Modify: `RpaClaw/backend/rpa_agent/host/scienceclaw_browser.py`
- Modify: `RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py`

- [ ] **Step 1: 写跳过 Session Runtime 的失败测试**

```python
@pytest.mark.asyncio
async def test_runtime_lease_uses_direct_cdp_resolver_without_session_runtime():
    calls = []

    class Registry:
        def get_active_page(self, _ref):
            return None

    async def forbidden_runtime(*_args):
        raise AssertionError("local mode must not ensure a session runtime")

    async def resolve_cdp(ref: str, owner: str) -> str:
        calls.append((ref, owner))
        return "ws://127.0.0.1:19222/devtools/browser/local"

    async def stop_after_resolve(cdp_url: str):
        assert cdp_url.endswith("/devtools/browser/local")
        raise RuntimeError("stop_after_direct_resolve")

    with pytest.raises(RuntimeError, match="stop_after_direct_resolve"):
        await acquire_browser_runtime_lease(
            owner_id="owner-1",
            browser_ref="local-session",
            preview_registry=Registry(),
            ensure_runtime=forbidden_runtime,
            resolve_cdp_url=resolve_cdp,
            connect=stop_after_resolve,
        )
    assert calls == [("local-session", "owner-1")]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py::test_runtime_lease_uses_direct_cdp_resolver_without_session_runtime -q
```

Expected: FAIL with unexpected keyword argument `resolve_cdp_url`.

- [ ] **Step 3: 增加最小 resolver 分支**

```python
CDPUrlResolver = Callable[[str, str], Awaitable[str]]
```

```diff
@@ acquire_browser_runtime_lease
-        runtime = await ensure_runtime(browser_ref, owner_id)
-        rest_base_url = getattr(runtime, "rest_base_url", None)
-        if not isinstance(rest_base_url, str) or not rest_base_url:
-            raise RuntimeError("browser_runtime.rest_base_url_invalid")
-        cdp_url = await fetch_cdp_url(rest_base_url)
+        if resolve_cdp_url is not None:
+            cdp_url = await resolve_cdp_url(browser_ref, owner_id)
+        else:
+            runtime = await ensure_runtime(browser_ref, owner_id)
+            rest_base_url = getattr(runtime, "rest_base_url", None)
+            if not isinstance(rest_base_url, str) or not rest_base_url:
+                raise RuntimeError("browser_runtime.rest_base_url_invalid")
+            cdp_url = await fetch_cdp_url(rest_base_url)

         owned = _OWNED_RESOURCES.get(key)
```

- [ ] **Step 4: 运行 Lease 全文件回归并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py -q
```

Expected: all tests pass，现有 Shared Runtime、provenance mismatch 和并发引用计数断言不变。

- [ ] **Step 5: 提交 Lease 扩展**

```powershell
git add RpaClaw/backend/rpa_agent/host/scienceclaw_browser.py RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py
git commit -m "feat: support direct cdp runtime leases"
```

### Task 3: 默认 Provider 按 local/非 local 分流

**Files:**
- Modify: `RpaClaw/backend/route/rpa_agent.py`
- Modify: `RpaClaw/backend/tests/rpa_agent/test_route.py`

- [ ] **Step 1: 写真实默认 Provider 的 local 模式失败测试**

```python
import os

import httpx
import pytest
from fastapi import FastAPI

from backend.browser_preview import browser_preview_registry
from backend.route import rpa_agent as route_module
from backend.route.rpa_agent import (
    RpaAgentApiServices,
    _scienceclaw_browser_provider,
    build_router,
)
from backend.runtime import ownership
from backend.runtime.local_cdp import local_cdp_connector
from backend.user.dependencies import User, require_user


@pytest.mark.asyncio
async def test_default_provider_uses_local_cdp_when_storage_is_local(monkeypatch):
    from backend.route import rpa_agent as route_module
    from backend.runtime import local_cdp, ownership
    from backend.rpa_agent.host import scienceclaw_browser

    local_url_value = "ws://127.0.0.1:19222/devtools/browser/local"
    captured = {}

    async def owned(_browser_ref: str, _owner_id: str) -> bool:
        return True

    async def local_url() -> str:
        return local_url_value

    async def capture_acquire(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("captured_local_resolver")

    monkeypatch.setattr(route_module.settings, "storage_backend", "local")
    monkeypatch.setattr(ownership, "user_owns_runtime_session", owned)
    monkeypatch.setattr(local_cdp.local_cdp_connector, "get_cdp_url", local_url)
    monkeypatch.setattr(scienceclaw_browser, "acquire_browser_runtime_lease", capture_acquire)

    with pytest.raises(RuntimeError, match="captured_local_resolver"):
        await _scienceclaw_browser_provider("owner-1", "local-session")

    assert captured["resolve_cdp_url"] is not None
    assert await captured["resolve_cdp_url"]("local-session", "owner-1") == local_url_value
```

同时增加一个路由断言：宿主抛错时日志包含 `storage_backend=local` 和异常类型，但 HTTP body 只包含 `rpa_agent.browser_host_unavailable`。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/rpa_agent/test_route.py::test_default_provider_uses_local_cdp_when_storage_is_local RpaClaw/backend/tests/rpa_agent/test_route.py::test_start_session_logs_browser_host_failure_without_leaking_detail -q
```

Expected: local resolver 未传入且宿主异常没有诊断日志，两个测试失败。

- [ ] **Step 3: 实现模式分流和脱敏日志**

```python
async def _local_cdp_url(_browser_ref: str, _owner_id: str) -> str:
    from backend.runtime.local_cdp import local_cdp_connector
    return await local_cdp_connector.get_cdp_url()

resolver = _local_cdp_url if settings.storage_backend == "local" else None
runtime_lease = await acquire_browser_runtime_lease(
    owner_id=owner_id,
    browser_ref=browser_ref,
    preview_registry=browser_preview_registry,
    resolve_cdp_url=resolver,
)
```

`start_session` 捕获普通异常时使用 `logger.exception` 记录安全字段，然后保持现有 503 错误码；仍需原样传播 `KeyboardInterrupt`、`SystemExit` 和 `asyncio.CancelledError`。

- [ ] **Step 4: 运行 Route/Host 回归并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/rpa_agent/test_route.py RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py -q
```

Expected: all selected tests pass；local 测试证明未调用 Session Runtime，非 local 测试保持原调用链。

- [ ] **Step 5: 提交默认 Provider 修复**

```powershell
git add RpaClaw/backend/route/rpa_agent.py RpaClaw/backend/tests/rpa_agent/test_route.py
git commit -m "fix: use local cdp host for rpa agent sessions"
```

### Task 4: 验证真实本地链路并完成 F026.1 收尾

**Files:**
- Create: `RpaClaw/backend/tests/rpa_agent/test_local_host_live.py`
- Create: `docs/evidence/EV-030-rpa-agent-local-cdp-host-fix.md`
- Modify: `docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md`

- [ ] **Step 1: 运行后端聚焦回归**

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/runtime/test_local_cdp.py RpaClaw/backend/tests/runtime/test_cdp_connector.py RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py RpaClaw/backend/tests/rpa_agent/test_route.py -q
```

Expected: zero failures.

- [ ] **Step 2: 运行新版领域和契约回归**

```powershell
Set-Location RpaClaw/backend
$env:PYTHONPATH='..'
python -m pytest tests/rpa_agent tests/contracts -q
```

Expected: zero failures；不得真实调用外部 LLM。

- [ ] **Step 3: 运行 RecorderPage 与生产构建**

```powershell
Set-Location RpaClaw/frontend
npm.cmd test -- --run src/pages/rpa/RecorderPage.test.ts src/components/SandboxPreview.test.ts
npm.cmd run build
```

Expected: target tests and build pass.

- [ ] **Step 4: 运行真实 Local CDP 冒烟**

先写 opt-in 测试。该测试只替换所有权查询，浏览器启动、CDP 获取、`connect_over_cdp`、Context/Page、Registry、默认路由和清理均使用生产实现：

```python
@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("RPA_AGENT_LOCAL_LIVE") != "1", reason="opt-in local browser smoke")
async def test_default_route_starts_real_local_cdp_session(monkeypatch, tmp_path):
    monkeypatch.setattr(route_module.settings, "storage_backend", "local")

    async def owned(_browser_ref: str, _owner_id: str) -> bool:
        return True

    monkeypatch.setattr(ownership, "user_owns_runtime_session", owned)
    services = RpaAgentApiServices(
        artifact_root=tmp_path,
        browser_provider=_scienceclaw_browser_provider,
    )
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="local-smoke-owner", username="local-smoke", role="user"
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={"browser_session_ref": "local-smoke-session"},
            )
        assert response.status_code == 201, response.text
        assert browser_preview_registry.get_active_page("local-smoke-session") is not None
        assert browser_preview_registry.get_cdp_url("local-smoke-session")
    finally:
        assert services.store is not None
        await services.store.close_all()
        await local_cdp_connector.close()
```

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
$env:RPA_AGENT_LOCAL_LIVE='1'
python -m pytest RpaClaw/backend/tests/rpa_agent/test_local_host_live.py -q -s
Remove-Item Env:RPA_AGENT_LOCAL_LIVE
```

Expected:

```text
storage_backend=local
http_status=201
preview_registered=true
cdp_provenance_match=true
cleanup_ok=true
sandbox_runtime_calls=0
```

- [ ] **Step 5: 记录 Incident Learning 和标准 Evidence**

EV-030 必须记录：根因是模式组合缺失而非 Sandbox 偶发不可用；触发器是 Windows local 配置；保护机制是 local-mode 产品启动测试与真实冒烟；回滚路径是不改变数据，仅恢复旧 Connector 委托。F026.1 Patch History 的 Commit、Protection 和 Status 更新为实际值，并链接 EV-030。

- [ ] **Step 6: 运行知识和差异校验**

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\RPA-Agent\ScienceClaw --docs-path docs --strict
git diff --check
git status --short
```

Expected: 本次 F026/EV-030 不新增知识结构错误；全仓 validator 若仍失败，只允许报告与本补丁无关且已存在的历史文档错误。

- [ ] **Step 7: 提交 Evidence 和 Feature 收尾**

```powershell
git add docs/evidence/EV-030-rpa-agent-local-cdp-host-fix.md docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
git commit -m "docs: close local cdp host incident"
```
