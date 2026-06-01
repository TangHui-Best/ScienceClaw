# API Monitor 工具卡片改进

## 背景

在 API Monitor 页面进行工具录制时，发现了三个影响可用性和可靠性的问题。

## 问题 1：工具卡片未显示意图裁剪原因

### 问题描述
当工具被采用或进入不采用队列时，系统生成的原因（来自意图裁剪或置信度评分）在工具卡片上不可见。数据已存在于 `ApiToolDefinition.intent_reason`（工具创建时从生成候选项复制），但前端没有展示。

### 解决方案
**仅前端改动。** 在工具卡片（采用/不采用分区）**非展开状态**下，当 `intent_reason` 非空时直接在卡片上显示。

- 位置：`ApiMonitorPage.vue`，工具卡片的摘要区域（URL 下方）
- 展示：小字文本，显示意图裁剪原因（类似生成候选项卡片上的 reason 展示方式）
- 仅在 `intent_reason` 非空时显示
- 同时在展开详情区域也显示（保持信息一致性）

### 涉及文件
- `frontend/src/pages/ApiMonitorPage.vue` — 在工具卡片摘要区域和展开区域添加 `intent_reason` 显示

## 问题 2：录制流程中意图裁剪不触发

### 问题描述
在录制流程中，用户在开始录制前填写了意图，但生成候选项有时会跳过意图裁剪步骤，直接进入工具生成。这导致本应被意图相关性过滤掉的工具被生成了。

### 根因分析
`_process_captured_calls_for_generation`（manager.py ~L2883-2892）中的代码路径在将候选项加入意图裁剪缓冲区之前，会检查 `candidate.status in ("pending", "stale", "failed")`。如果 `_upsert_generation_candidate` 返回的候选项状态不是这三个之一，意图裁剪检查就会被跳过。

其他可能原因：
- `_schedule_intent_prune_flush` 的 3 秒防抖可能延迟处理
- `_flush_intent_prune_buffer` 在 `session is None` 时会丢弃整个缓冲区
- 上一次录制会话中更新的候选项可能保留非 pending 状态

### 解决方案
**后端改动：**

1. **确保有意图时裁剪始终运行**：在 `_upsert_generation_candidate` 之后，如果候选项是新的或有新数据，在意图裁剪检查前确保其状态为 "pending"，或将意图裁剪检查移到状态保证可用的位置。

2. **在 stop_recording 中增加防御性 flush**：在 `_stop_recording_once` 中，确保 `_flush_intent_prune_buffer` 处理所有缓冲的候选项。

3. **增加日志**：记录候选项进入意图裁剪缓冲区 vs 直接进入生成队列的情况，便于排查。

### 涉及文件
- `backend/rpa/api_monitor/manager.py` — 修复 `_process_captured_calls_for_generation` 中的意图裁剪触发逻辑，增加日志

## 问题 3：活跃操作无耗时显示

### 问题描述
当生成候选项处于活跃状态（生成中、意图裁剪中、重试中）较长时间时，用户看不到任何关于操作运行时长的反馈，页面显得无响应。

### 解决方案
**仅前端改动。** 在生成候选项卡片的状态标签旁添加实时计时器。

- 使用 `updated_at` 时间戳记录候选项进入活跃状态的时间
- 在状态标签中显示耗时：如 "生成中 (12s)"、"意图裁剪中 (5s)"
- 每秒通过 `setInterval` 更新显示
- 候选项变为非活跃状态时停止计时
- 活跃状态：`running`、`pending`、`intent_pruning`、`intent_prune_retrying`、`rate_limited`
- 格式：< 60s 显示秒数，>= 60s 显示 "Xm Ys"

### 实现方式
- 添加响应式 Map `candidateTimers: Map<string, number>` 跟踪起始时间戳
- 监听候选项状态变化，更新计时起点
- 使用 `setInterval`（1 秒）刷新显示的已耗时
- 组件卸载时清理定时器

### 涉及文件
- `frontend/src/pages/ApiMonitorPage.vue` — 在候选项卡片状态标签旁添加计时显示逻辑

## 问题 4：i18n 重复 Key 警告

### 问题描述
Vite 构建时报告 `en.ts` 和 `zh.ts` 中存在重复 key 的警告。

### 分析
经检查，当前文件中未发现实际重复的 key。Vite 报的行号与当前文件内容不匹配，可能是 dev server 缓存了旧版本。需要用户重启 dev server 确认。如果重启后警告仍然存在，再行排查修复。

### 涉及文件
- `frontend/src/locales/en.ts`
- `frontend/src/locales/zh.ts`

## 范围

- 前端改动：`ApiMonitorPage.vue`、`en.ts`、`zh.ts`（如确认有重复）
- 后端改动：仅 `manager.py`
- 不新增 API 端点
- 不修改数据库 Schema
