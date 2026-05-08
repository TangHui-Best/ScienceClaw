# API Monitor 证据采集与操作感知统一设计

日期：2026-05-08

## 1. 背景

API Monitor 有两条核心流程——分析流程（系统驱动）和录制流程（用户驱动）。两条流程共享 `NetworkCaptureEngine` 和 confidence 评分等基础设施，但在操作感知和证据采集精度上存在显著差距：

- 分析流程是系统驱动的单页操作，天然拥有"我知道刚刚做了什么"的上下文。
- 录制流程是用户驱动的多 tab 操作，后端对用户行为完全无感知，只能用粗粒度时间窗口猜测。

这导致录制流程中两个核心问题：

1. **无法准确分辨 API 调用来源页面**：`_request_evidence` 按 URL 存储，多 tab 同 URL 互相覆盖；`_async_evidence_for_request` 始终查询活跃页面，非活跃 tab 的 JS 调用栈查不到。
2. **无法准确识别 API 是否在录制窗口内触发**：`_mark_action` 仅在录制开始时调用一次，2 秒后所有调用都被标记为窗口外；CDP 与 Playwright 事件间存在竞态。

分析流程虽然因为单页逐步操作而规避了这些问题，但也存在可优化空间：跨步骤同 URL 证据覆盖、DOM 上下文只保留首次、缺少步骤级调用分组。

## 2. 目标

本设计完成后，API Monitor 应满足：

1. 录制流程能感知用户操作（click、submit、navigate），实时更新动作时间戳。
2. 多 tab 场景下，每个 API 请求的证据不会被其他 tab 的同 URL 请求覆盖。
3. `action_window_matched` 在录制流程中能准确反映"是否由用户最近操作触发"。
4. confidence 评分能利用分析/录制中的操作上下文（"点击了什么"）作为额外信号。
5. 分析流程的 DOM 上下文累积式合并，跨步骤信息不丢失。
6. 工具生成 prompt 能感知"这个 API 是在哪个步骤/操作时触发的"。
7. 已有录制/分析/token flow 核心机制不被破坏。

## 3. 非目标

- 不重写 API Monitor 的 token flow 检测算法。
- 不改变 MCP 发布规则。
- 不把录制流程改成完整 RPA trace 编译流程。
- 不修改前端 UI（本次改动对前端透明）。

## 4. 设计方案

分三个阶段实施，每阶段独立可验证。

### Phase 1：统一证据采集层

Phase 1 修复共享基础设施，同时改善分析和录制两条流程。

#### 4.1.1 `_request_evidence` 从 URL-keyed 改为 request-id keyed

**现状**（`manager.py:2243`）：

```python
self._request_evidence.setdefault(session_id, {})[url] = evidence
```

同 URL 请求的证据互相覆盖，导致多 tab 场景下 initiator 信息指向错误页面。

**改为**：

引入 CDP request ID 与 Playwright request 的映射，用映射后的 ID 作为存储键。

```python
# 新增映射表
self._cdp_to_pw: Dict[str, Dict[str, int]] = defaultdict(dict)
# _cdp_to_pw[session_id][cdp_request_id] = id(playwright_request)

# CDP handler 中存储映射
def on_request_will_be_sent(event):
    cdp_req_id = event.get("requestId", "")
    # 存储 evidence 时用 cdp_req_id 作为 key
    self._request_evidence.setdefault(session_id, {})[cdp_req_id] = evidence

# _evidence_for_request 中通过映射查找
def _evidence_for_request(self, session_id, request):
    pw_id = id(request)
    by_cdp = self._request_evidence.get(session_id, {})
    # 反查 CDP evidence：遍历 _cdp_to_pw 找到对应的 cdp_request_id
    evidence = {}
    for cdp_id, stored_pw_id in self._cdp_to_pw.get(session_id, {}).items():
        if stored_pw_id == pw_id:
            evidence = dict(by_cdp.get(cdp_id, {}))
            break
    evidence.setdefault("frame_url", ...)
    evidence["action_window_matched"] = self._action_window_matched(session_id)
    return evidence
```

映射关系的建立：利用 Playwright 的 `page.on('request')` 回调中 request 对象的 `_guid` 属性（或 `id(request)` 作为唯一标识），以及 CDP `Network.requestWillBeSent` 事件的 `requestId`。在 CDP handler 中同时记录 URL 和 requestId，在 Playwright `on_request` 回调中按 URL + method 查找最近的未匹配 CDP evidence 并建立映射。如果匹配失败，fallback 到当前逻辑（从 `session.target_url` 取 frame_url），不引入硬依赖。

**清理策略**：`_request_evidence[session_id]` 和 `_cdp_to_pw[session_id]` 中的条目在 `on_response` 完成后立即清理对应映射。超时未匹配的条目（超过 30 秒）在 `_recording_drain_loop` 每轮清理。

#### 4.1.2 `_async_evidence_for_request` 定位正确页面

**现状**（`manager.py:2255`）：

```python
page = self._pages.get(session_id)  # 始终查活跃页面
```

非活跃 tab 的请求查不到 `__apiMonitorStacks`。

**改为**：从 request 的 frame 反查所属 page。

```python
# 新增映射
self._frame_to_page: Dict[int, Page] = {}

# 在 _adopt_page 中维护
def _adopt_page(self, session_id, page, *, make_active):
    ...
    # 主 frame
    self._frame_to_page[id(page.main_frame)] = page
    # 子 frame 通过 page.frames 追踪
    for frame in page.frames:
        self._frame_to_page[id(frame)] = page

# 在 _async_evidence_for_request 中使用
async def _async_evidence_for_request(self, session_id, request):
    frame = getattr(request, 'frame', None)
    page = self._frame_to_page.get(id(frame)) if frame else None
    page = page or self._pages.get(session_id)  # fallback
    ...
```

#### 4.1.3 在 `on_request` 中固化 frame URL

`network_capture.py` 的 `_current_page_url` 已经从 `request.frame.url` 获取 frame URL。确保这个值直接写入 `CapturedRequest`，不再依赖后续异步查询可能过时的 `_request_evidence`。

```python
# NetworkCaptureEngine.on_request 中
captured_req = CapturedRequest(
    ...
    frame_url=frame_url,  # 新增字段，在请求时固化
)
```

`CapturedRequest` 模型新增 `frame_url: Optional[str] = None` 字段。

### Phase 2：录制流程操作感知

Phase 2 为录制流程添加用户操作感知能力，使其接近分析流程的精确度。

#### 4.2.1 操作感知 JS 注入

为避免与 RPA 录制系统的 `__rpa_emit` binding 冲突，API Monitor 使用独立的 binding 名称 `__apiMonitorAction`，并注入一个轻量版 JS，只捕获 click/submit/navigate 事件，不做 locator 生成：

```python
# 在 create_session 中
async def _install_user_action_capture(self, session_id: str, context: BrowserContext) -> None:
    async def on_user_action(source, event_json: str):
        evt = json.loads(event_json)
        await self._handle_user_action(session_id, evt)

    await context.expose_binding("__apiMonitorAction", on_user_action, handle=False)
    await context.add_init_script(_USER_ACTION_CAPTURE_JS)
```

轻量版 JS 捕获逻辑：监听 click（排除 checkbox/radio 的重复触发）、submit、popstate/hashchange 事件，捕获元素基本信息（tag、text、role）和 frame URL，通过 binding 推送。

#### 4.2.2 用户操作处理

后端收到用户操作事件后：

```python
async def _handle_user_action(self, session_id: str, evt: Dict) -> None:
    action_type = evt.get("action", "")
    if action_type not in ("click", "fill", "press", "navigate", "submit"):
        return

    # 更新动作时间戳
    self._mark_action(session_id)

    # 记录操作锚点
    self._action_anchors.setdefault(session_id, []).append({
        "action": action_type,
        "description": evt.get("element_snapshot", {}).get("text", "")[:80],
        "timestamp": time.monotonic(),
        "page_url": evt.get("url", ""),
        "frame_path": evt.get("frame_path", []),
        "call_ids": [],  # 后续由 drain loop 填充
    })

    # 通过 screencast 转发到前端（可选）
    ctrl = self._screencasts.get(session_id)
    if ctrl:
        await ctrl.send_monitor_log("ACTION", f"用户操作: {action_type}")
```

#### 4.2.3 操作锚点与 API 调用关联

在 `_recording_drain_loop` 中 drain 到新调用时，将它们关联到最近的操作锚点：

```python
# _recording_drain_loop 中
calls = capture.drain_new_calls()
if calls:
    anchors = self._action_anchors.get(session_id, [])
    if anchors:
        last_anchor = anchors[-1]
        last_anchor["call_ids"].extend(call.id for call in calls)
    await self._process_captured_calls_for_generation(
        session_id, calls,
        action_context=self._last_action_context(session_id),
        model_config=model_config,
    )
```

#### 4.2.4 未来优化：完整复用 RPA capture JS

当前 Phase 2 使用独立 binding 和轻量版 JS，与 RPA 系统完全解耦。未来如果确认两者不会同时运行，可以切换为直接复用 RPA 的 `__rpa_emit` 和完整的 `playwright_recorder_capture.js`，获得更丰富的 locator 和 element snapshot 信息，进一步丰富 confidence 评分信号。

### Phase 3：Confidence 与分析流程优化

#### 4.3.1 操作上下文传递给 confidence 评分

`_process_captured_calls_for_generation` 新增 `action_context` 参数：

```python
async def _process_captured_calls_for_generation(
    self,
    session_id: str,
    calls: list[CapturedApiCall],
    *,
    action_context: Optional[Dict] = None,  # 新增
    ...
) -> list[ApiToolGenerationCandidate]:
```

`action_context` 结构：

```python
{
    "action": "click",           # 操作类型
    "description": "点击搜索按钮",  # 操作描述
    "page_url": "https://...",   # 操作发生页面
}
```

在 confidence 评分中使用：

```python
# confidence.py 新增
if action_context:
    score += 15
    breakdown["confirmed_user_action"] = 15
    reasons.append(f"由用户操作确认触发: {action_context.get('description', '')}")
```

传递路径：
- 分析流程：`analyze_directed_page` 在 step 执行后传入 `allowed_action.description` 和 `observation["url"]`
- 录制流程：`_recording_drain_loop` 通过操作锚点传入
- 自由分析：`_probe_element` 传入 probed element 描述

#### 4.3.2 DOM 上下文累积式合并

**现状**（`manager.py:1830-1834`）：同一 candidate 只保留首次 DOM 上下文。

**改为**：合并多次观察的 DOM 信息：

```python
if dom_context:
    candidate.capture_dom_context = _merge_dom_context(
        candidate.capture_dom_context or {},
        dom_context,
    )
    # 更新 page_url 和 title 为最新的非空值
    if page_url:
        candidate.capture_page_url = page_url
    if title:
        candidate.capture_title = title
    if dom_digest:
        candidate.capture_dom_digest = dom_digest
```

`_merge_dom_context` 策略：
- forms：按 action URL 去重合并，保留所有不同的表单结构
- inputs：按 name 去重合并
- buttons：按 text 去重合并

#### 4.3.3 步骤级调用分组

在 `ApiToolGenerationCandidate` 中新增 `step_metadata` 字段：

```python
# models.py
class ApiToolGenerationCandidate(BaseModel):
    ...
    step_metadata: List[Dict] = Field(default_factory=list)
```

每条 step_metadata 记录：

```python
{
    "step": 3,
    "action_description": "点击搜索按钮",
    "page_url": "https://...",
    "call_count": 2,
    "call_ids": ["uuid-1", "uuid-2"],
}
```

在工具生成 prompt 中加入步骤上下文：

```
此 API 在以下操作中被观察到：
- 步骤 3: 点击搜索按钮，页面 https://...，触发 2 次调用
- 步骤 5: 点击下一页，页面 https://...，触发 1 次调用
```

## 5. 文件变更清单

### Phase 1

| 文件 | 变更 |
|------|------|
| `backend/rpa/api_monitor/manager.py` | `_request_evidence` 改为 request-id keyed；新增 `_cdp_to_pw`、`_frame_to_page` 映射；`_async_evidence_for_request` 定位正确页面；`_adopt_page` 维护 frame 映射；`_install_source_evidence_capture` 存储 CDP request ID 映射 |
| `backend/rpa/api_monitor/network_capture.py` | `on_request` 中固化 frame URL；`CapturedRequest` 新增可选清理回调 |
| `backend/rpa/api_monitor/models.py` | `CapturedRequest` 新增 `frame_url` 字段 |

### Phase 2

| 文件 | 变更 |
|------|------|
| `backend/rpa/api_monitor/manager.py` | 新增 `_install_user_action_capture`、`_handle_user_action`、`_USER_ACTION_CAPTURE_JS`；`create_session` 中安装 action capture；新增 `_action_anchors` 状态；`_recording_drain_loop` 关联操作锚点 |

### Phase 3

| 文件 | 变更 |
|------|------|
| `backend/rpa/api_monitor/manager.py` | `_process_captured_calls_for_generation` 新增 `action_context` 参数；`_upsert_generation_candidate` 改为累积 DOM 上下文；分析流程中传入 action_context |
| `backend/rpa/api_monitor/models.py` | `ApiToolGenerationCandidate` 新增 `step_metadata` 字段 |
| `backend/rpa/api_monitor/confidence.py` | `score_api_candidate` 支持 `action_context` 参数；新增 confirmed_user_action 评分项 |
| `backend/rpa/api_monitor/llm_analyzer.py` | 工具生成 prompt 加入步骤上下文 |

## 6. 风险与缓解

### 6.1 Phase 1 映射匹配失败

CDP requestId 与 Playwright request 的关联可能因时序差异匹配失败。

缓解：fallback 到当前逻辑（从 `session.target_url` 取 frame_url），不引入硬依赖。映射成功率可在日志中监控。

### 6.2 RPA capture JS 与 API Monitor 冲突

如果同一 context 同时挂载 RPA 和 API Monitor 的 binding，名称冲突。

缓解：Phase 2 使用独立 binding 名称 `__apiMonitorAction` 和轻量版 JS，与 RPA 的 `__rpa_emit` 完全解耦，不会冲突。

### 6.3 操作锚点内存增长

长时间录制会累积大量操作锚点。

缓解：设置上限（如保留最近 100 个锚点），超出时丢弃最旧的。操作锚点仅在录制期间维护，停止录制时清理。

### 6.4 Phase 1 回归风险

证据采集层变更可能影响分析流程的稳定性。

缓解：Phase 1 完成后需运行完整的分析流程回归测试，确认 confidence 评分、工具生成、token flow 均不受影响。

## 7. 验收标准

### Phase 1 验收

1. 多 tab 场景：打开两个 tab，分别请求不同 API，两个 API 的 `source_evidence.initiator_urls` 不互相覆盖。
2. 同 URL 场景：两个 tab 请求同一 API，各自保留独立的 initiator 信息。
3. 分析流程回归：自由分析和定向分析的 confidence 评分、工具生成结果与改动前一致。

### Phase 2 验收

1. 录制期间点击按钮，后端收到用户操作事件并调用 `_mark_action`。
2. 点击后 2 秒内捕获的 API 调用 `action_window_matched` 为 True。
3. 多 tab 操作：在非活跃 tab 点击后触发的 API 也能正确关联到操作锚点。

### Phase 3 验收

1. 有 `action_context` 的调用比无 `action_context` 的同质量调用 confidence 评分高 15 分。
2. 同一 API 在不同步骤被调用时，DOM 上下文包含所有步骤的表单信息。
3. 工具生成 prompt 中包含步骤上下文描述。

## 8. 与现有设计的关系

本设计是对以下设计的补充和增强：

- `2026-05-06-api-monitor-capture-window-boundary-design.md` — Phase 1 修复了窗口判断的证据精度问题
- `2026-04-30-api-monitor-realtime-tool-generation-design.md` — Phase 2 增强了录制流程的操作感知
- `2026-04-25-api-monitor-numerical-scoring-dedup-design.md` — Phase 3 扩展了 confidence 评分信号
