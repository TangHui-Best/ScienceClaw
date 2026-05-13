# API Monitor MCP — AI 意图二次过滤设计

## 背景与动机

当前 API Monitor 的工具生成流程中，置信度评分在 LLM 工具定义生成之后才执行，且仅有一轮基于规则的评分。这导致两个问题：

1. **Token 浪费**：所有 API 调用分组都会调用 LLM 生成工具定义，包括最终被标记为低置信度的
2. **相关性不足**：高置信度接口可能是业务接口但与用户目的无关（例如用户想"管理订单"，但高置信度接口包含"用户信息查询"）

## 设计目标

在规则置信度评分之后新增 AI 意图相关性判断，将两轮评分都提前到工具定义生成之前，只对通过两轮评分的候选生成工具定义。

## 整体流程

```
API 调用捕获 → 分组去重 → 规则置信度评分
                              ↓
                        ≥80 且有意图？
                        ├── 是 → AI 意图判断
                        │         ├── 相关 → 生成工具 (selected=true)
                        │         └── 不相关 → score -= 20
                        │              ├── 仍 ≥80 → 生成工具 (selected=true)
                        │              └── <80 → 候选列表 (intent_filtered)
                        ├── ≥80 无意图 → 生成工具 (selected=true)
                        └── <80 → 候选列表 (medium/low)

前端候选列表：
  - medium/low：规则评分不够
  - intent_filtered：被 AI 意图过滤
  → 用户可点击"强制生成"触发工具定义生成并自动采用
```

## 后端变更

### 1. 新增意图过滤模块

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

### 2. 数据模型变更

**文件**：`backend/rpa/api_monitor/models.py`

`ApiMonitorSession` 新增字段：
- `intent: Optional[str] = None` — 用户意图描述

`ApiToolGenerationCandidate` 状态枚举扩展：
- 新增 `intent_filtered` 状态
- 新增字段：`intent_filter_reason: Optional[str] = None`

### 3. 评分流程前置

**文件**：`backend/rpa/api_monitor/manager.py`

修改工具生成流程，将置信度评分和意图过滤都提前到 LLM 生成之前：

**修改 `_generate_tools_from_calls`**：
1. 先对每组 API 调用执行 `score_api_candidate`（规则评分）
2. <80 分：创建候选，标记为 medium/low 状态，不调用 LLM
3. ≥80 分 + 有意图：调用 `filter_by_intent`
   - 相关或扣分后仍 ≥80：调用 LLM 生成工具
   - 扣分后 <80：创建候选，标记为 `intent_filtered`，记录理由
4. ≥80 分 + 无意图：直接调用 LLM 生成工具

**修改 `_process_single_candidate`**（实时录制路径）：
同上逻辑，在现有候选处理流程中加入意图过滤步骤。

### 4. API 变更

**文件**：`backend/route/api_monitor.py`

| 端点 | 变更 |
|------|------|
| `POST /api-monitor/sessions/{id}/analyze` | 无变更，已有 `instruction` 参数 |
| `POST /api-monitor/sessions/{id}/start-recording` | 新增可选 `intent` 参数 |
| `PUT /api-monitor/sessions/{id}/intent` | **新增**，允许随时更新意图 |
| `POST /api-monitor/sessions/{id}/candidates/{id}/force-generate` | **新增**，强制生成工具定义 |

### 5. SSE 事件

新增事件类型：
- `api_candidate_intent_filtered` — AI 意图过滤结果
  - payload：候选 ID、AI 理由、调整后分数

## 前端变更

### 1. 意图输入 UI

- **自由分析模式**：在"分析"按钮附近新增可选的"目的描述"输入框（textarea）
- **录制模式**：在"开始录制"按钮附近新增可选的"录制目的"输入框
- **定向分析 / 安全分析**：复用已有的 `instruction` 输入框，无需额外 UI

### 2. 候选列表状态展示

在候选列表中新增 `intent_filtered` 状态的展示：
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

**置信度评分前置的影响**：
- 现有行为：所有 API 分组都调用 LLM 生成工具定义，然后评分决定是否选中
- 新行为：先评分，只有通过评分的才生成。低置信度分组不再消耗 LLM token，但也不会有工具定义
- 前端已有的候选列表可以展示这些未生成的候选，用户可通过"强制生成"手动触发

**意图为空时的行为**：
- 无意图时只执行规则评分，不执行 AI 意图过滤
- 效果等同于现有系统 + 置信度前置优化

**API 兼容性**：
- 现有 API 的调用方式不变，新增参数均为可选
- 前端新增的 UI 元素均为可选输入
