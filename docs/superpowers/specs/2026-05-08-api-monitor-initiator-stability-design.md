# API Monitor Initiator 追踪稳定性修复

日期：2026-05-08

## 1. 背景

API Monitor 的 initiator 追踪（`initiator_urls` 和 `js_stack_urls`）不稳定，有时能找到，有时找不到。根因是 CDP 通道和 Playwright 通道的事件时序竞争。

### 1.1 时序竞争分析

证据追踪有三条独立通道：

| 通道 | 来源 | 提供的信息 |
|------|------|-----------|
| CDP | `context.new_cdp_session(page)` 的 `Network.requestWillBeSent` | `initiator_type`、`initiator_urls`（浏览器原生 initiator） |
| Playwright | `page.on('request')` | 请求结构化数据（URL、headers、body） |
| JS 注入 | `__apiMonitorStacks`（拦截 fetch/XHR） | `js_stack_urls`（页面上下文中的调用栈） |

CDP 通道和 Playwright 通道走不同的 WebSocket 连接。当浏览器发出网络请求时，两个通道的事件到达 Python asyncio 事件循环的顺序不确定：

- **CDP 先到**：Playwright `on_request` 调用 `_evidence_for_request` 时，`_request_evidence` 中已有数据 → 查找成功
- **Playwright 先到**：`_request_evidence` 还是空的 → 查找失败，返回空 dict → **证据永久丢失**

当前没有重试机制。`on_response` 时不会再次尝试查找 CDP evidence。

### 1.2 JS 调用栈时序

`_async_evidence_for_request` 在 `on_response` 时通过 `page.evaluate()` 查询 `__apiMonitorStacks`。极快的缓存响应场景下，JS 拦截器可能还没来得及写入调用栈记录。

### 1.3 其他问题

- `_cleanup_request_evidence` 定义了但从未被调用，`_request_evidence` 无限累积
- 关键证据查找函数无任何诊断日志，无法排查失败原因

## 2. 目标

1. CDP evidence 查找不再受时序竞争影响，无论 CDP 和 Playwright 哪个先到都能获取到 initiator 信息。
2. JS 调用栈查询在极快响应场景下也能可靠获取。
3. 所有关键证据查找环节有诊断日志，便于排查。
4. `_request_evidence` 在请求完成后及时清理，不无限累积。
5. 页面跳转场景下不会匹配到错误页面的证据。
6. 不改变 confidence 评分逻辑、工具生成逻辑、MCP 发布规则。

## 3. 非目标

- 不重写 evidence 追踪架构。
- 不改变 CDP session 的创建方式。
- 不移除任何已有的证据通道（CDP、Playwright、JS 注入三者并存）。
- 不修改前端 UI。

## 4. 设计方案

### 4.1 CDP 证据延迟重查找

在 `network_capture.py` 的 `on_response` 中，如果 `source_evidence` 缺少 `initiator_urls`，调用 manager 的新方法重查 `_request_evidence`。

#### 4.1.1 新增 `_retry_sync_evidence` 方法

```python
# manager.py
def _retry_sync_evidence(
    self,
    session_id: str,
    request_url: str,
    request_method: str,
    frame_url: str = "",
) -> Dict:
    by_cdp = self._request_evidence.get(session_id, {})
    if not by_cdp:
        return {}

    cdp_map = self._cdp_to_pw.get(session_id, {})
    for cdp_id, cdp_ev in by_cdp.items():
        if cdp_id in cdp_map:
            continue
        if (cdp_ev.get("_cdp_url") == request_url
                and cdp_ev.get("_cdp_method") == request_method.upper()):
            # frame_url 过滤：防止跨页误匹配
            if frame_url and cdp_ev.get("frame_url") != frame_url:
                continue
            cdp_map[cdp_id] = 0  # 标记为已链接
            result = dict(cdp_ev)
            result.pop("_cdp_url", None)
            result.pop("_cdp_method", None)
            return result
    return {}
```

匹配条件：URL + method + frame_url（可选）+ unlinked。

#### 4.1.2 在 `on_response` 中调用重查找

```python
# network_capture.py on_response 中
source_evidence: Dict = dict(info.get("source_evidence") or {})

# 如果缺少 initiator 信息，尝试重查找
if not source_evidence.get("initiator_urls") and self._evidence_retry_provider:
    retry = self._evidence_retry_provider(
        captured_req.url,
        captured_req.method,
        captured_req.frame_url or "",
    )
    if retry.get("initiator_urls"):
        source_evidence.update({
            k: v for k, v in retry.items()
            if k not in ("_cdp_url", "_cdp_method")
        })

# 然后继续异步证据查询和合并
async_evidence = await self._async_source_evidence(req)
...
```

`_evidence_retry_provider` 是一个新的回调，由 manager 注入到 NetworkCaptureEngine，指向 `_retry_sync_evidence`。

### 4.2 JS 调用栈重试

`_async_evidence_for_request` 增加一次重试（最多 2 次查询，间隔 50ms）：

```python
async def _async_evidence_for_request(self, session_id: str, request) -> Dict:
    ...
    for attempt in range(2):
        stack_record = await page.evaluate(...)
        if stack_record:
            break
        if attempt == 0:
            await asyncio.sleep(0.05)  # 50ms 重试间隔
    if not stack_record:
        return {}
    ...
```

仅在第一次查询失败时重试一次。正常情况下第一次就成功，不增加延迟。

### 4.3 诊断日志

在以下关键点增加 `logger.debug` 日志：

| 位置 | 日志内容 |
|------|---------|
| `_install_source_evidence_capture` | CDP session 建立成功（改为 warning 级别记录失败） |
| CDP `on_request_will_be_sent` | 每条证据存储：session、cdp_id、URL、initiator_type |
| `_evidence_for_request` | 查找路径结果：linked / fallback / miss，以及可用证据条数 |
| `_retry_sync_evidence` | 重查找命中/未命中：URL、frame_url |
| `_async_evidence_for_request` | 页面解析结果（frame-based / fallback）、JS 栈查询结果 |
| `on_response` | 最终 evidence 合并结果摘要（initiator_urls 数量、js_stack_urls 数量） |

### 4.4 证据清理

#### 4.4.1 `on_response` 后清理

在 `on_response` 完成证据合并后，通过回调通知 manager 清理对应的 CDP evidence：

```python
# network_capture.py on_response 末尾
if self._evidence_cleanup_provider:
    try:
        self._evidence_cleanup_provider(captured_req.request_id)
    except Exception:
        pass
```

manager 侧的回调遍历 `_cdp_to_pw[session_id]` 找到对应的 cdp_id 并清理。

#### 4.4.2 超时清理

在 `_recording_drain_loop` 每轮清理超过 30 秒的孤立证据：

```python
# _recording_drain_loop 中
self._cleanup_stale_evidence(session_id, max_age_seconds=30)
```

```python
def _cleanup_stale_evidence(self, session_id: str, max_age_seconds: float = 30) -> int:
    # 清理 _request_evidence 中超过 max_age 的条目
    # 返回清理数量用于日志
```

为实现超时判断，CDP evidence 存储时附带 `_stored_at` 时间戳。

## 5. 文件变更清单

| 文件 | 变更 |
|------|------|
| `backend/rpa/api_monitor/manager.py` | 新增 `_retry_sync_evidence`；`_async_evidence_for_request` 增加重试；`_install_source_evidence_capture` 改 warning 级日志；`_evidence_for_request` 增加诊断日志；`_recording_drain_loop` 增加超时清理；CDP handler 存储时附带 `_stored_at`；新增 `_cleanup_stale_evidence` |
| `backend/rpa/api_monitor/network_capture.py` | `NetworkCaptureEngine.__init__` 新增 `_evidence_retry_provider` 和 `_evidence_cleanup_provider` 回调参数；`on_response` 增加重查找和清理调用 |

## 6. 风险与缓解

### 6.1 重查找误匹配

多个同 URL + method 的请求在 `_request_evidence` 中可能匹配到错误的证据。

缓解：使用 `frame_url` 过滤 + unlinked 条件限制匹配范围。极端场景（同页面同 URL 并发请求）下仍可能匹配到先到的证据，但这类场景中 initiator 信息通常是相同的（同一个 JS 函数发起的）。

### 6.2 JS 重试增加延迟

50ms 重试间隔在最坏情况下增加 50ms 延迟。

缓解：仅在第一次查询失败时重试。正常请求响应时间远大于 50ms，感知不到。可考虑将重试间隔降到 20ms。

### 6.3 清理时机过早

`on_response` 后立即清理可能导致同一请求的异步证据查询失败。

缓解：`_async_evidence_for_request` 在 `on_response` 中先于清理调用执行。证据合并完成后才清理，不存在时序问题。

## 7. 验收标准

1. 连续录制 10 次，每次 initiator_urls 和 js_stack_urls 的获取成功率 ≥ 95%。
2. 页面跳转场景（录制中从页面 A 跳到页面 B），两个页面的 API 证据不互相污染。
3. 日志中能看到每条请求的证据查找路径（linked / fallback / retry / miss）。
4. 长时间录制（>5 分钟）后 `_request_evidence` 不无限增长，保持在合理范围。
5. 已有 47 个测试全部通过。

## 8. 与现有设计的关系

本设计是对 `2026-05-08-api-monitor-evidence-awareness-design.md` 的补充修复：

- Phase 1 的 CDP-request-ID keyed evidence 存储是本设计的基础
- 本设计解决的是 Phase 1 实施后暴露的时序竞争问题
- 不改变 Phase 2（操作感知）和 Phase 3（confidence 增强）的任何逻辑
