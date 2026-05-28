# API Monitor 意图裁剪重试与状态设计

## 背景

API Monitor MCP 工具生成链路已经引入意图裁剪，用于把高置信度 API 候选按用户意图分为 `primary`、`supporting`、`adjacent`、`bootstrap`、`noise` 和 `uncertain`。其中 batch 路径和 realtime buffer 路径都会调用 LLM 完成候选裁剪。

当前问题是：意图裁剪 LLM 如果失败、超时或抛异常，候选状态不能稳定落到可解释状态。尤其 realtime flush 中，buffer 会先 `pop`，随后 pruner 异常可能让 task 退出，候选仍停留在 `pending`、`stale` 或 `failed` 等主流程状态，看起来像工具生成卡住。batch 路径也只是记录 warning，缺少明确的裁剪状态和统一重试策略。

本设计目标是让意图裁剪成为候选主状态机中的明确阶段，并配套自动重试和有界失败兜底。`pending` 不再承担“等待裁剪、等待生成、看不出卡在哪里”的宽泛语义。

## 目标

1. 裁剪失败或超时时自动重试，而不是立即进入人工确认。
2. 裁剪过程在 `GenerationStatus` 中有明确状态，避免候选长期停留在含义宽泛的 `pending`。
3. batch 与 realtime 两条路径使用同一套重试、超时、并发限制和失败兜底。
4. 前端能显示意图裁剪正在运行、重试或最终失败，避免用户误以为候选卡住。
5. 裁剪 helper 必须收敛异常，不让 flush task 因 LLM 失败而丢失候选状态。

## 非目标

- 不调整 LLM prompt 的分类标准。
- 不优化 batch/debounce 参数；本轮只保留现有批量策略。
- 不改变 `primary`、`supporting`、`adjacent`、`bootstrap`、`noise`、`uncertain` 的业务含义。
- 不把裁剪失败直接等同于接口不相关。

## 状态模型

`ApiToolGenerationCandidate.status` 已经是候选级流程状态，现有值包含 `confidence_rejected`、`intent_filtered`、`intent_review`、`running`、`generated` 等候选结果和阶段。为了直接解决 `pending` 语义过宽的问题，本轮继续扩展 `GenerationStatus`，不新增独立的 `intent_prune_status` 字段。

```python
GenerationStatus = Literal[
    "pending",
    "intent_pruning",
    "intent_prune_retrying",
    "generated",
    "failed",
    "rate_limited",
    "stale",
    "confidence_rejected",
    "intent_filtered",
    "intent_review",
]
```

`ApiToolGenerationCandidate` 新增字段：

- `intent_prune_attempts: int = 0`
- `intent_prune_error: str = ""`
- `intent_prune_retry_after: Optional[datetime] = None`

`status` 和辅助字段的职责分层：

| 字段 | 职责 |
| --- | --- |
| `status` | 候选当前处于待处理、意图裁剪、裁剪重试、生成中、已生成、被过滤、需人工确认、生成失败等候选级阶段 |
| `intent_group` / `intent_reason` | LLM 裁剪成功后给出的分类和理由，或最终失败后的人工确认理由 |
| `intent_prune_error` | 最近一次裁剪异常或超时原因 |
| `intent_prune_attempts` / `intent_prune_retry_after` | 裁剪重试次数和下一次自动重试时间 |

状态流转规则：

- 进入裁剪前：`pending -> intent_pruning`。
- 单次裁剪失败或超时但仍可重试：`intent_pruning -> intent_prune_retrying`，写入 `intent_prune_error` 和 `intent_prune_retry_after`。
- 重试时间到达后：`intent_prune_retrying -> intent_pruning`。
- 裁剪成功且分类为 `primary`：进入普通工具生成路径，随后 `running -> generated`。
- 裁剪成功且分类为 `supporting`：进入 reserve tool 生成路径，随后 `running -> generated`。
- 裁剪成功且分类为 `adjacent`、`bootstrap`、`noise`：`intent_pruning -> intent_filtered`。
- 裁剪成功且分类为 `uncertain`：`intent_pruning -> intent_review`。
- 裁剪连续失败超过上限：`intent_prune_retrying -> intent_review`。

`intent_prune_attempts`、`intent_prune_error` 和 `intent_prune_retry_after` 只描述裁剪重试细节，不单独构成状态机。

## 后端执行设计

新增统一 helper，例如：

```python
async def _prune_candidates_with_retry(
    self,
    session: ApiMonitorSession,
    candidates: list[ApiToolGenerationCandidate],
    intent: str,
    *,
    model_config: Optional[Dict] = None,
) -> IntentPruneResult:
    """Run intent pruning with timeout, bounded retries, and candidate state updates."""
```

helper 负责 batch 和 realtime 的共同语义：

1. 构造 `IntentPruneCandidate` payload。
2. 对每次 LLM 裁剪调用套 `asyncio.wait_for(prune_coro, timeout=20)`。
3. 使用独立并发限制 `self._intent_prune_semaphore = asyncio.Semaphore(2)`。
4. 最多执行 `首次 + 2 次重试`。
5. 每次失败后使用指数退避，建议 `2s -> 4s`。
6. 每次失败都把候选 `status` 设置为 `intent_prune_retrying`，并更新 `intent_prune_attempts`、`intent_prune_error` 和 `intent_prune_retry_after`。
7. 成功时清空 `intent_prune_error` 和 `intent_prune_retry_after`，并返回真实 LLM 分类结果；候选最终状态由裁剪分类和后续生成路径决定。
8. 重试耗尽后返回 synthetic `uncertain` 结果，让调用方沿用 `_apply_prune_item_to_candidate()` 把候选落到 `intent_review`。

裁剪失败的最终理由统一为中文用户可见文案，例如：

`意图裁剪多次失败，需人工确认：<最近一次错误>`

这个结果代表系统无法可靠判断相关性，不代表 API 与用户意图无关。

## Batch 路径

`_generate_tools_from_calls()` 的 Phase 2 不再直接调用 `prune_candidates_by_intent()`，改为调用 `_prune_candidates_with_retry()`。

成功或最终失败后：

1. 根据返回的 `IntentPruneResult.items` 调用 `_apply_prune_item_to_candidate()`。
2. 对 `intent_filtered` 和 `intent_review` 候选跳过生成。
3. 对 `primary` 和 `supporting` 继续进入 Phase 3 生成工具。

batch 路径中 helper 不能把异常抛回主流程。即使裁剪最终失败，也应以 `intent_review` 的形式稳定结束，而不是让候选继续无解释地生成或停在 `pending`。

## Realtime 路径

`_flush_intent_prune_buffer()` 仍从 `_intent_prune_buffers` 中取出候选，但在 pruner 失败时不能丢失状态。

流程调整为：

1. 候选通过置信度评分后，进入统一裁剪 helper。
2. helper 负责重试期间的候选状态更新和事件发送。
3. helper 返回后，对每个候选应用裁剪结果。
4. `primary` 和 `supporting` 继续 `_enqueue_generation_candidate()`。
5. `intent_filtered` 和 `intent_review` 不进入工具生成。

如果 helper 最终失败，候选 `status` 进入 `intent_review`，并保留 `intent_prune_error`。这样前端轮询可以停止等待，并显示明确原因。

## 事件与前端展示

候选事件 payload 需要包含新增字段：

- `intent_prune_attempts`
- `intent_prune_error`
- `intent_prune_retry_after`

新增或复用事件：

| 事件 | 场景 |
| --- | --- |
| `api_candidate_intent_prune_started` | 一批候选开始裁剪 |
| `api_candidate_intent_prune_retrying` | 单次裁剪失败并准备自动重试 |
| `api_candidate_intent_pruned` | 裁剪成功或最终失败后已经落到候选状态 |

前端候选列表继续基于 `status` 展示候选阶段：

- `intent_pruning`：显示“意图裁剪中”。
- `intent_prune_retrying`：显示“意图裁剪重试中”，可显示最近错误或下一次重试时间。
- `intent_review` 且存在 `intent_prune_error`：显示“意图裁剪失败，已转人工确认”。
- `pending`：只表示候选尚未进入裁剪或生成，不再覆盖裁剪运行中和重试中。

已有的 `intent_filtered`、`intent_review`、`generated` 等标签继续保留。新增状态只补足裁剪过程中的可观察性。

## 参数

首版采用固定常量：

- `INTENT_PRUNE_TIMEOUT_S = 60`
- `INTENT_PRUNE_MAX_RETRIES = 2`
- `INTENT_PRUNE_RETRY_BASE_DELAY_S = 2`
- `INTENT_PRUNE_CONCURRENCY = 2`

后续如果需要产品化配置，再移动到 settings 或环境变量。本轮不暴露配置入口，避免增加无关复杂度。

## 错误处理原则

1. LLM 裁剪异常、JSON 解析失败、超时都属于裁剪失败，可自动重试。
2. 单次失败把候选 `status` 设置为 `intent_prune_retrying`，但不进入 `intent_review`。
3. 重试耗尽后才修改 `status = "intent_review"`。
4. 最终失败必须记录最近错误，便于日志和前端解释。
5. helper 不向 batch/realtime 主流程抛出裁剪异常。

## 测试计划

后端测试：

1. pruner 第一次超时、第二次成功：候选经历 `intent_prune_retrying` 后继续生成，不进入 `intent_review`。
2. pruner 连续失败超过上限：候选 `status = "intent_review"`，错误原因可见。
3. realtime flush 中 pruner 抛异常：task 不崩溃，候选不会永久停在 `pending` 且会发状态事件。
4. batch 路径使用同一 retry helper，最终失败时不会继续生成普通工具。
5. `supporting` 分类成功后仍生成 reserve tool，不受裁剪重试状态影响。

前端测试：

1. candidate payload 带 `status = "intent_prune_retrying"` 时展示“意图裁剪重试中”。
2. `status = "intent_review"` 且存在 `intent_prune_error` 时展示“意图裁剪失败，已转人工确认”。
3. `pending` 不再被前端解释为裁剪中或裁剪重试中。

## 实施顺序

1. 扩展 `GenerationStatus`、裁剪重试辅助字段和 candidate event payload。
2. 增加裁剪 retry helper、timeout 和 semaphore。
3. 改造 batch 路径使用 helper。
4. 改造 realtime flush 路径使用 helper。
5. 补后端单测和集成测试。
6. 更新前端类型、状态文案和候选卡片展示。
7. 补前端展示测试。
