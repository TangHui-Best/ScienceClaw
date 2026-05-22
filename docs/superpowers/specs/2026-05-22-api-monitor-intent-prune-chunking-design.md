# API Monitor 意图裁剪分块设计

日期：2026-05-22

## 1. 问题

当 API Monitor 捕获的高置信候选较多时（12-20+），意图裁剪全部超过 20s 超时，导致所有候选卡死在重试循环。

根因：`_flush_intent_prune_buffer` 将 buffer 中的**全部候选**打包成一个 LLM 调用发送给 `prune_candidates_by_intent`。`INTENT_PRUNE_MAX_BATCH_SIZE=8` 只控制 debounce 触发时机，不限制单次 LLM 调用的候选数。

实际场景：20 个候选在 3 秒内到达 → 首批 8 个触发立即 flush → flush 运行期间剩余 12 个进入 buffer → 第二次 flush 处理 12 个候选 → prompt 达 30,000+ 字符 → LLM 响应超 20s → 超时 → 重试 3 次全部超时 → 60s+ 全部卡死。

## 2. 目标

1. 意图裁剪在大批量候选下不超时。
2. 每个候选独立承担超时风险，一个 chunk 失败不影响其他 chunk。
3. 保持 LLM 在 chunk 内的相对比较能力。
4. 不改变 LLM prompt、分类定义或前端展示。

## 3. 非目标

- 不改变 `IntentGroup` 分类定义或 prompt 内容。
- 不调整 debounce 窗口或 `INTENT_PRUNE_MAX_BATCH_SIZE`。
- 不引入按 token 数动态分块（首版用固定 chunk size）。

## 4. 设计

### 4.1 新增常量

```python
INTENT_PRUNE_CHUNK_SIZE = 6  # 每个 chunk 的候选数上限
```

选择 6 的理由：
- 每个候选 payload 约 2000 字符，6 个约 12,000 字符 + prompt 模板约 1000 字符 = 总 prompt 约 13,000 字符。LLM 在 20s 内可稳定响应。
- 6 个候选仍有足够的对比上下文做相对分类。
- 即使某个 chunk 响应慢，只影响 6 个候选。

### 4.2 分块处理流程

改造 `_flush_intent_prune_buffer`（manager.py:2519）：

```
flush_buffer(candidate_ids):
    candidates = 筛选有效候选
    prune_candidates = 构造 IntentPruneCandidate 列表

    if len(prune_candidates) <= CHUNK_SIZE:
        单次裁剪（现有逻辑）
    else:
        按 CHUNK_SIZE 分块
        对每个 chunk 调用 _prune_candidates_with_retry
        合并所有 chunk 的 IntentPruneResult
```

分块处理的关键变更：

1. `_flush_intent_prune_buffer` 将 `prune_candidates` 按 `INTENT_PRUNE_CHUNK_SIZE` 切分为多个 chunk。
2. 每个 chunk 独立调用 `_prune_candidates_with_retry`，获得独立的超时、重试和信号量控制。
3. 各 chunk **串行**处理（不是并行），原因：
   - 信号量 `_intent_prune_semaphore` 已限制全局并发为 2，并行 chunk 会争抢信号量。
   - 串行更简单，且每个 chunk 只需 ~5-10s，总延迟仍远优于当前全卡死。
   - 如果未来需要并行，可以调整，但首版串行更安全。
4. 合并所有 chunk 结果后，统一对 candidates 应用裁剪结果。

### 4.3 _prune_candidates_with_retry 签名调整

当前签名接收完整 `candidates` 列表用于状态更新和事件发送。分块后，每次调用只传入对应 chunk 的候选子集。

```python
async def _prune_candidates_with_retry(
    self,
    session: ApiMonitorSession,
    candidates: list[ApiToolGenerationCandidate],  # 该 chunk 的候选
    prune_candidates: list[IntentPruneCandidate],   # 该 chunk 的裁剪输入
    intent: str,
    *,
    model_config: Optional[Dict] = None,
) -> IntentPruneResult:
```

签名不变，但调用方保证 `candidates` 和 `prune_candidates` 是同一 chunk 的子集。状态更新和事件发送只影响该 chunk 的候选。

### 4.4 _flush_intent_prune_buffer 改造

```python
async def _flush_intent_prune_buffer(self, session_id, *, model_config=None):
    # ... 现有筛选逻辑不变 ...

    if not prune_candidates:
        return

    # 分块
    chunks = [
        (prune_candidates[i:i+CHUNK_SIZE], matching_candidates_for_chunk)
        for i in range(0, len(prune_candidates), CHUNK_SIZE)
    ]

    all_items = []
    for prune_chunk, candidate_chunk in chunks:
        result = await self._prune_candidates_with_retry(
            session, candidate_chunk, prune_chunk, intent, model_config=model_config
        )
        all_items.extend(result.items)

    # 统一应用结果
    by_key = {item.candidate_key: item for item in all_items}
    for candidate in candidates:
        item = by_key.get(self._candidate_key_for_prune(candidate))
        if item is None:
            continue
        self._apply_prune_item_to_candidate(session, candidate, item, batch_id=...)
        self._emit_analysis_event(...)
        if candidate.status not in ("intent_filtered",):
            self._enqueue_generation_candidate(...)
```

`matching_candidates_for_chunk` 的构造方式：按 prune_candidates 在原始 `candidates` 列表中的对应关系切分。由于 `_candidate_key_for_prune` 是一对一映射，可以用 candidate_key 关联。

### 4.5 超时与重试

每个 chunk 独立享有：
- 20s 超时
- 最多 2 次重试
- 信号量并发限制

一个 chunk 超时/失败后，其候选进入 `intent_review`，不影响其他 chunk 继续处理。

### 4.6 日志

每个 chunk 记录：
- chunk 索引和候选数
- LLM 响应时间
- 各 group 数量

## 5. 修改文件

| 文件 | 变更 |
|------|------|
| `manager.py` | 新增 `INTENT_PRUNE_CHUNK_SIZE` 常量；改造 `_flush_intent_prune_buffer` 增加分块逻辑 |
| `intent_pruner.py` | 无变更 |

## 6. 测试计划

1. 单 chunk（候选数 <= 6）：行为与现有逻辑一致。
2. 多 chunk（候选数 = 12）：分为 2 个 chunk，各 6 个。两个 chunk 独立裁剪，结果正确合并。
3. 不均分（候选数 = 14）：分为 3 个 chunk（6+6+2）。最后一个 chunk 只有 2 个候选，正常处理。
4. 部分失败：第 1 个 chunk 成功，第 2 个 chunk 超时 3 次 → 第 2 个 chunk 的候选进入 `intent_review`，第 1 个 chunk 的候选正常生成工具。
5. 大批量（候选数 = 30）：分为 5 个 chunk 串行处理，全部在合理时间内完成。

## 7. 风险

### 7.1 跨 chunk 无法比较

chunk 内 6 个候选可以互相对比，但不同 chunk 之间无法比较。理论上，同属 `primary` 的两个接口可能被分到不同 chunk，各自获得 `rank=1`。

缓解：`rank` 仅用于展示排序，不影响功能。如果未来需要全局排序，可以在所有 chunk 完成后对 primary 候选做二次排序（纯本地排序，无 LLM 调用）。

### 7.2 串行延迟

30 个候选 = 5 个 chunk × ~8s/chunk = ~40s 总延迟。虽然比当前的 60s+ 全卡死好得多，但仍不算快。

缓解：首版串行足够。如果需要优化，后续可将 chunk 改为并行（受信号量限制最多 2 个并行）。
