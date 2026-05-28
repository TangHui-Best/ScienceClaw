# API Monitor 工具卡片改进 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 API Monitor 页面的三个问题：工具卡片不显示意图裁剪原因、录制流程意图裁剪不触发、活跃操作无耗时反馈。

**Architecture:** 前后端分别独立修改。前端改动集中在 `ApiMonitorPage.vue`，后端改动集中在 `manager.py`。问题之间相互独立，可并行实现。

**Tech Stack:** Vue 3 + TypeScript（前端），Python 3.13 + FastAPI（后端）

---

### Task 1: 工具卡片非展开状态下显示意图裁剪原因

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue` — 工具卡片模板区域（~L1534-1617）

**背景：** 当前工具卡片（采用/不采用分区）只在展开后显示 `confidence_reasons`，不显示 `intent_reason`。`ApiToolDefinition` 已有 `intent_reason` 字段（后端在工具创建时从候选项复制）。

- [ ] **Step 1: 在工具卡片摘要行（非展开）添加 intent_reason 显示**

在 `ApiMonitorPage.vue` 中，找到工具卡片的摘要区域。在 `ChevronDown` 图标之前，添加一个条件渲染块，当 `tool.intent_reason` 非空时显示原因文本。

定位到工具卡片模板中 `ChevronDown` 所在行（约 L1570），在其前面插入：

```vue
<span
  v-if="tool.intent_reason"
  class="shrink-0 text-[10px] text-orange-600 dark:text-orange-400 truncate max-w-[200px]"
  :title="tool.intent_reason"
>
  {{ tool.intent_reason }}
</span>
```

- [ ] **Step 2: 在工具卡片展开详情中也添加 intent_reason**

定位到展开详情区域中 `confidence_reasons` 显示块之后（约 L1585），插入：

```vue
<div v-if="tool.intent_reason" class="mb-3">
  <span class="text-[10px] text-orange-600 dark:text-orange-400 break-words">{{ tool.intent_reason }}</span>
</div>
```

- [ ] **Step 3: 验证**

启动前端 dev server，打开 API Monitor 页面，检查采用/不采用分区的工具卡片是否在非展开和展开状态下都能看到 `intent_reason`。

- [ ] **Step 4: 提交**

```bash
git add RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue
git commit -m "feat: 工具卡片显示意图裁剪原因（非展开+展开）"
```

---

### Task 2: 候选项状态标签旁显示实时耗时

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue` — 脚本区域 + 生成候选项模板

**背景：** 生成候选项卡片在 `running`、`intent_pruning` 等活跃状态下无耗时反馈。需要在状态标签旁显示已消耗时间。

- [ ] **Step 1: 添加计时器相关的响应式数据和逻辑**

在 `ApiMonitorPage.vue` 的 `<script setup>` 区域：

首先，将 `watch` 添加到 vue 的 import 中（约 L3）：

```typescript
import { ref, reactive, onMounted, onBeforeUnmount, nextTick, computed, watch } from 'vue';
```

然后，找到 `getCandidateStatusLabel` 函数定义附近（约 L1073），在其后面添加以下代码：

```typescript
// --- 候选项计时器 ---
const candidateTimerStarts = ref<Record<string, number>>({})
const candidateTimerNow = ref(Date.now())
let candidateTimerInterval: ReturnType<typeof setInterval> | null = null

const ACTIVE_CANDIDATE_STATUSES = new Set([
  'pending', 'running', 'intent_pruning', 'intent_prune_retrying', 'rate_limited',
])

function updateCandidateTimers() {
  const starts: Record<string, number> = {}
  for (const c of generationCandidates.value) {
    if (ACTIVE_CANDIDATE_STATUSES.has(c.status)) {
      // 使用 updated_at 作为起始时间（秒级时间戳），如果已有记录则保留
      const existing = candidateTimerStarts.value[c.id]
      const fromUpdated = c.updated_at ? new Date(c.updated_at).getTime() : Date.now()
      starts[c.id] = existing || fromUpdated
    }
  }
  candidateTimerStarts.value = starts
  // 每秒刷新
  if (Object.keys(starts).length > 0 && !candidateTimerInterval) {
    candidateTimerInterval = setInterval(() => {
      candidateTimerNow.value = Date.now()
    }, 1000)
  } else if (Object.keys(starts).length === 0 && candidateTimerInterval) {
    clearInterval(candidateTimerInterval)
    candidateTimerInterval = null
  }
}

watch(generationCandidates, updateCandidateTimers, { deep: true, immediate: true })

onBeforeUnmount(() => {
  if (candidateTimerInterval) {
    clearInterval(candidateTimerInterval)
    candidateTimerInterval = null
  }
})

function getCandidateElapsedLabel(candidate: ApiToolGenerationCandidate): string {
  const start = candidateTimerStarts.value[candidate.id]
  if (!start || !ACTIVE_CANDIDATE_STATUSES.has(candidate.status)) return ''
  const elapsed = Math.max(0, Math.floor((candidateTimerNow.value - start) / 1000))
  if (elapsed < 60) return `${elapsed}s`
  const m = Math.floor(elapsed / 60)
  const s = elapsed % 60
  return `${m}m ${s}s`
}
```

- [ ] **Step 2: 在候选项状态标签旁显示耗时**

定位到生成候选项卡片模板中状态标签 `<span>` 所在行（约 L1432）：

```vue
<span class="shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-bold" :class="getCandidateStatusClass(candidate.status)">
  {{ getCandidateStatusLabel(candidate.status) }}
</span>
```

替换为：

```vue
<span class="shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-bold" :class="getCandidateStatusClass(candidate.status)">
  {{ getCandidateStatusLabel(candidate.status) }}<template v-if="getCandidateElapsedLabel(candidate)"> ({{ getCandidateElapsedLabel(candidate) }})</template>
</span>
```

- [ ] **Step 3: 验证**

启动前端 dev server，打开 API Monitor 页面，开始录制，观察生成候选项卡片在 `pending`、`running`、`intent_pruning` 等状态下是否显示实时更新的耗时。

- [ ] **Step 4: 提交**

```bash
git add RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue
git commit -m "feat: 候选项状态标签旁显示实时耗时"
```

---

### Task 3: 修复录制流程中意图裁剪不触发的 Bug

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py` — `_process_captured_calls_for_generation` 方法（~L2838-2893）、`_flush_intent_prune_buffer` 方法（~L2520-2610）

**背景：** `_process_captured_calls_for_generation` 中，候选项通过 `_upsert_generation_candidate` 创建/更新后，只有当 `candidate.status in ("pending", "stale", "failed")` 时才进入意图裁剪缓冲区。新建候选项默认 status 为 `"pending"`，理论上有意图时应正确进入缓冲区。但由于此 Bug 是间歇性的，需要先增加诊断日志定位根因，同时增加防御性逻辑。

- [ ] **Step 1: 在 `_process_captured_calls_for_generation` 中增加诊断日志**

定位到 `_process_captured_calls_for_generation` 方法（约 L2883-2892），当前的代码：

```python
        if candidate.status in ("pending", "stale", "failed"):
            if (session.intent or "").strip():
                self._intent_prune_buffers[session_id].add(candidate.id)
                self._schedule_intent_prune_flush(
                    session_id,
                    model_config=model_config,
                    immediate=len(self._intent_prune_buffers[session_id]) >= INTENT_PRUNE_MAX_BATCH_SIZE,
                )
            else:
                self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
```

替换为：

```python
        intent_str = (session.intent or "").strip()
        logger.debug(
            "[ApiMonitor] session=%s candidate=%s status=%s has_intent=%s _created=%s",
            session_id, candidate.id, candidate.status, bool(intent_str), _created,
        )
        if candidate.status in ("pending", "stale", "failed"):
            if intent_str:
                self._intent_prune_buffers[session_id].add(candidate.id)
                self._schedule_intent_prune_flush(
                    session_id,
                    model_config=model_config,
                    immediate=len(self._intent_prune_buffers[session_id]) >= INTENT_PRUNE_MAX_BATCH_SIZE,
                )
            else:
                self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
        elif intent_str:
            logger.info(
                "[ApiMonitor] session=%s candidate=%s skipping intent prune (status=%s)",
                session_id, candidate.id, candidate.status,
            )
```

- [ ] **Step 2: 在 `_stop_recording_once` 中增加防御性 flush**

定位到 `_stop_recording_once` 方法（约 L928-959），当前的 flush 调用：

```python
    await self._flush_intent_prune_buffer(session_id, model_config=model_config)
```

在这行之后，添加一个二次检查，确保没有候选项遗漏：

```python
    # 防御性检查：确保所有 pending/stale/failed 候选项在有意图时都经过了裁剪
    session_after = self.sessions.get(session_id)
    if session_after and (session_after.intent or "").strip():
        missed = [
            c for c in session_after.generation_candidates
            if c.status in ("pending", "stale", "failed")
        ]
        if missed:
            logger.warning(
                "[ApiMonitor] session=%s %d candidates missed intent prune after stop, re-flushing",
                session_id, len(missed),
            )
            for c in missed:
                self._intent_prune_buffers.setdefault(session_id, set()).add(c.id)
            await self._flush_intent_prune_buffer(session_id, model_config=model_config)
```

- [ ] **Step 3: 在 `_flush_intent_prune_buffer` 中增加日志**

在 `_flush_intent_prune_buffer` 方法的 `candidate_ids` 提取之后（约 L2530），添加日志：

```python
    logger.info(
        "[IntentPrune] session=%s flushing %d buffered candidates (of %d ids)",
        session_id, len(candidates), len(candidate_ids),
    )
```

- [ ] **Step 4: 验证**

启动后端服务，打开 API Monitor 页面，填写意图后开始录制，观察后端日志确认意图裁剪是否触发。然后停止录制，检查是否所有候选项都经过了裁剪。

- [ ] **Step 5: 提交**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py
git commit -m "fix: 修复录制流程意图裁剪不触发 + 增加诊断日志"
```

---

### Task 4: i18n 重复 key 警告（待确认）

**Files:**
- Possibly modify: `RpaClaw/frontend/src/locales/en.ts`
- Possibly modify: `RpaClaw/frontend/src/locales/zh.ts`

**背景：** 用户报告 Vite 构建 warning 提示重复 key。经检查，当前文件中未发现实际重复。可能是 dev server 缓存问题。

- [ ] **Step 1: 确认问题是否存在**

重启 Vite dev server，观察是否仍有重复 key 警告。如果没有，此 Task 关闭。

```bash
cd RpaClaw/frontend && npx vite --clearScreen false 2>&1 | head -50
```

- [ ] **Step 2: 如果仍有警告，定位并修复重复 key**

使用脚本扫描重复：

```bash
python3 << 'PYEOF'
import re
for fname in ['en.ts', 'zh.ts']:
    path = f'RpaClaw/frontend/src/locales/{fname}'
    with open(path) as f:
        lines = f.readlines()
    keys = {}
    for i, line in enumerate(lines, 1):
        m = re.match(r"  ['\"](.+?)['\"]:\s*['\"]", line)
        if m:
            key = m.group(1)
            if key in keys:
                print(f'{fname}: dup "{key}" at lines {keys[key]} and {i}')
                # 保留后出现的版本（通常更新），删除先出现的
            else:
                keys[key] = i
PYEOF
```

删除先出现的重复行。

- [ ] **Step 3: 提交（如有改动）**

```bash
git add RpaClaw/frontend/src/locales/en.ts RpaClaw/frontend/src/locales/zh.ts
git commit -m "fix: 修复 i18n 文件重复 key 警告"
```
