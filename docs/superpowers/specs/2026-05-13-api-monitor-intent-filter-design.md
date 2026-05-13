# API Monitor MCP — AI 意图二次过滤设计

## 背景与动机

当前 API Monitor 的工具生成流程中，置信度评分在 LLM 工具定义生成之后才执行，且仅有一轮基于规则的评分。这导致两个问题：

1. **Token 浪费**：所有 API 调用分组都会调用 LLM 生成工具定义，包括最终被标记为低置信度的
2. **相关性不足**：高置信度接口可能是业务接口但与用户目的无关（例如用户想"管理订单"，但高置信度接口包含"用户信息查询"）

同时，原有规则中的 `business_path`（基于 URL 路径判断是否为业务接口）是一种粗粒度启发式，应替换为更精准的 AI 意图判断。

## 设计目标

1. 移除 `business_path` 启发式，将其 +25 分预算转移给 AI 意图判断
2. 将置信度评分和意图过滤都提前到工具定义生成之前，节省 LLM token
3. AI 意图判断只做扣分（-25），不加分，保证意图不匹配时一定为非高置信度

## 评分体系

### 第一轮：规则置信度（满分 100）

| 条件 | 分值 | 说明 |
|------|------|------|
| `action_window_matched` | +35 | API 在用户动作时间窗口内触发 |
| `json_response` | +25 | 响应为 JSON 业务数据 |
| `has_source` | +15 | 有 initiator URL 或 JS 调用栈 |
| `confirmed_user_action` | +15 | 有 action_context 确认的用户操作 |
| `response_richness` | +10 | 响应体有内容 |
| `injected_source` | -40 | 来源含浏览器扩展/注入脚本标记 |
| `noise_path` | -30 | 路径含 telemetry/track/metrics 等噪声标记 |
| `no_action_window` | -20 | 不在用户动作时间窗口内 |
| `missing_source` | -10 | 缺少 initiator 和 JS 调用栈 |

**阈值**：≥80 为高置信度，40~79 为中等，<40 为低。

### 第二轮：AI 意图相关性（仅对第一轮 ≥80 且有用户意图的候选）

| AI 判断 | 分值 | 说明 |
|---------|------|------|
| 与意图相关 | +0 | 不加分，分数不变 |
| 与意图不相关 | -25 | 保证最终 ≤75 < 80，一定非高置信度 |

**核心保证**：第一轮满分 100，意图不匹配 100-25=75 < 80。

## 整体流程

```
API 调用捕获 → 分组去重 → 第一轮规则置信度评分
                              ↓
                        <80 → medium/low，不生成工具
                        ≥80 + 有意图 → 第二轮 AI 意图判断
                              ├── 相关 (+0) → 分数不变，≥80 → 生成工具
                              └── 不相关 (-25) → ≤75 → intent_filtered
                        ≥80 + 无意图 → 直接生成工具

前端候选列表：
  - medium/low：第一轮规则评分不够，不生成工具
  - intent_filtered：第一轮通过但 AI 意图判断不相关
  → 用户可点击"强制生成"触发工具定义生成并自动采用
```

## 各场景的意图来源

| 场景 | 意图来源 |
|------|---------|
| 定向分析 (directed) | 用户输入的 `instruction`（已有字段） |
| 安全分析 (safe_directed) | 用户输入的 `instruction`（已有字段） |
| 自由分析 (free) | 新增可选输入框（用户可填"目的描述"） |
| 录制模式 | 新增可选输入框（用户可填"录制目的"） |

无意图时跳过第二轮，仅使用第一轮规则评分。

## 后端变更

### 1. 修改置信度评分

**文件**：`backend/rpa/api_monitor/confidence.py`

- 移除 `business_path` 相关逻辑（`BUSINESS_PATH_MARKERS`、+25 加分）
- 调整 `action_window_matched` 从 +30 → +35
- 调整 `json_response` 从 +20 → +25
- 简化 `response_richness` 为固定 +10（移除 +5 分支）
- 移除 `_score_response_richness` 函数中的梯度逻辑

### 2. 新增意图过滤模块

**文件**：`backend/rpa/api_monitor/intent_filter.py`

```python
@dataclass(frozen=True)
class IntentFilterResult:
    relevant: bool
    reason: str

async def filter_by_intent(
    calls: list[CapturedApiCall],
    intent: str,
    confidence_reasons: list[str],
    *,
    model_config: dict | None = None,
) -> IntentFilterResult:
```

**LLM Prompt 要点**：
- 输入：用户意图、API 请求信息（方法、URL、请求体）、API 响应信息（状态码、内容类型、响应体前500字符）、置信度理由
- 输出：JSON `{"relevant": bool, "reason": string}`
- Prompt 强调保守判断：如果不确定相关性，判定为相关（避免误杀）

### 3. 数据模型变更

**文件**：`backend/rpa/api_monitor/models.py`

`ApiMonitorSession` 新增字段：
- `intent: Optional[str] = None`

`ApiToolGenerationCandidate` 新增：
- 状态枚举新增 `intent_filtered`
- 字段 `intent_filter_reason: Optional[str] = None`

### 4. 评分流程前置

**文件**：`backend/rpa/api_monitor/manager.py`

修改 `_generate_tools_from_calls`（批量路径）和 `_process_single_candidate`（实时录制路径）：

1. 先对每组 API 调用执行 `score_api_candidate`（第一轮规则评分）
2. <80 分：创建候选，标记为 medium/low 状态，**不调用 LLM 生成工具定义**
3. ≥80 分 + 有意图：调用 `filter_by_intent`（第二轮 AI 判断）
   - 相关（+0）：分数不变 → 调用 LLM 生成工具
   - 不相关（-25）：分数 ≤75 → 创建候选，标记 `intent_filtered`，记录理由
4. ≥80 分 + 无意图：直接调用 LLM 生成工具

### 5. API 变更

**文件**：`backend/route/api_monitor.py`

| 端点 | 变更 |
|------|------|
| `POST /api-monitor/sessions/{id}/analyze` | 无变更，已有 `instruction` 参数 |
| `POST /api-monitor/sessions/{id}/start-recording` | 新增可选 `intent` 参数 |
| `PUT /api-monitor/sessions/{id}/intent` | **新增**，允许随时更新意图 |
| `POST /api-monitor/sessions/{id}/candidates/{id}/force-generate` | **新增**，强制生成工具定义 |

### 6. SSE 事件

新增事件类型：
- `api_candidate_intent_filtered` — payload 含候选 ID、AI 理由、调整后分数

## 前端变更

### 1. 意图输入 UI

- **自由分析模式**：在"分析"按钮附近新增可选的"目的描述"输入框（textarea）
- **录制模式**：在"开始录制"按钮附近新增可选的"录制目的"输入框
- **定向分析 / 安全分析**：复用已有的 `instruction` 输入框，无需额外 UI

### 2. 候选列表状态展示

新增 `intent_filtered` 状态展示：
- 显示标签："AI 过滤"
- 显示 AI 判断理由
- 提供"强制生成"按钮

### 3. API 调用

**文件**：`frontend/src/api/apiMonitor.ts`

新增：
- `updateSessionIntent(sessionId, intent)`
- `forceGenerateCandidate(sessionId, candidateId)`

### 4. i18n

**文件**：`frontend/src/locales/zh.ts` 和 `en.ts`

新增翻译键：
- `apiMonitor.intentPlaceholder` — "描述你希望获取的 API 类型..."
- `apiMonitor.intentFiltered` — "AI 过滤"
- `apiMonitor.forceGenerate` — "强制生成"

## 行为变更与兼容性

**置信度评分前置**：
- 旧：所有分组都调用 LLM 生成工具定义，生成后评分决定是否选中
- 新：先评分，只有通过的才调用 LLM。低置信度不消耗 token，但用户可通过"强制生成"手动触发

**移除 business_path**：
- 旧：URL 含 `/api/`、`/v1/` 等标记直接 +25
- 新：路径启发式不再加分，由 AI 意图判断替代（但不加分，只扣分）

**意图为空时**：
- 仅执行第一轮规则评分，不执行 AI 意图过滤
- 效果等同于现有系统 + 置信度前置优化 + 移除 business_path

**API 兼容性**：
- 现有 API 的调用方式不变，新增参数均为可选
- 前端新增的 UI 元素均为可选输入
