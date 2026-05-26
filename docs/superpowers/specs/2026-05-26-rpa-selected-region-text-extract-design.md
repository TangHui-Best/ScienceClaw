---
doc_kind: design
title: RPA Selected Region Text Extract Design
status: draft
date: 2026-05-26
---

# RPA 选区文本提取确定性编译设计

## 背景

用户在页面上先用区域选择功能框选一个标题，再用自然语言指示“获取标题信息”。当前系统可能出现两种结果：

1. planner / repair 将选区内容转成 `extract_snapshot.fields`，compiler 优先走 snapshot 字段提取模板，生成基于字段 label 的 `aui-form-item` XPath。
2. 没有可用 `extract_snapshot.fields` 时，compiler 保留为 runtime AI 指令。

第二种是可接受的保守兜底；第一种不可接受。因为“采购一批电脑3333”等录制现场标题值只是 evidence，不是 replay 逻辑。把它变成字段定位、文本定位或返回值，会让脚本绑定到单次录制现场，后续 replay 必然脆弱甚至直接失败。

本设计目标不是修复某一个站点的标题，而是补齐通用抽象：用户已经通过选区明确指向一个文本区域时，“获取/读取/提取”应优先读取该区域对应元素的运行时文本；如果证据不足，则保留 runtime AI；永不把 observed value 编译成最终脚本逻辑。

## 设计原则

- **Observed value 是 evidence，不是 replay 逻辑。** 录制时看到的标题、段落、字段值只能辅助判断用户选了什么，不能作为最终返回值或主要 locator。
- **AI 兜底可以接受，硬编码不可接受。** 在证据不足时保留 `_execute_runtime_ai_instruction(...)`，不要生成看似确定但实际绑定现场值的代码。
- **只补缺失抽象，不扩张经验规则。** 不引入站点模板、关键词 selector 经验库或多轮 repair。
- **Compiler 不做 selector 猜测。** Compiler 只能消费 trace 中已经明确存在的可执行证据，不能根据 bbox、文本长度、class 名称或页面局部经验重新发明“最佳标题 locator”。
- **保持 Trace-first。** 录制阶段仍记录事实和证据，泛化发生在 trace signal 与 compiler 阶段。
- **不影响已有结构化能力。** detail/form/table/list/single_value/heading_scoped_text 已有明确路径，本设计只覆盖未建模的 selected text region extraction。

## 影响面审视

### 不应影响的既有能力

1. **detail/form 字段提取**
   - 现有 `extract_snapshot` 在 `detail_views` / `form_views` 有真实字段证据时仍应编译为确定性字段读取。
   - 例如带 `data_prop` 的字段继续使用 `[data-prop="..."]`。
   - 没有 `data_prop` 但确实来自详情字段视图的场景，可以继续使用现有字段容器策略；后续如要收紧，应另起设计。

2. **表格与列表选区**
   - `table_summary`、`list_summary`、`selected_row_indexes`、`selected_item_indexes` 不进入本文本提取分支。
   - 表格/列表的主问题是集合结构和行列映射，不应被文本区域策略抢占。

3. **single_value 选区**
   - `inferred_kind == "single_value"` 已有 `_render_region_single_value_trace` 路径，继续优先用 locator `inner_text()`。
   - 新策略只覆盖 `inferred_kind == "text_region"`。

4. **heading_scoped_text_extract**
   - 已有 `region_text_extract.kind == "heading_scoped_text"` 时，compiler 可基于稳定 heading anchor 提取 bounded section text。
   - 新策略不能降低该路径优先级；它只补“用户框选的就是一个标题/短文本元素”的能力。

5. **真正语义任务**
   - “总结这里的风险点”“选择最相关条目”“判断最高优先级”等仍应 runtime AI。
   - 选区文本提取只处理“获取/读取/提取/返回选区文本或标题信息”的事实型读取。

### 需要改变的行为

1. **text_region + extraction 不再被 `extract_snapshot.fields` 无条件抢占。**
   - 当前 compiler 只要看到 usable snapshot fields 就走 `_render_snapshot_extract_trace`。
   - 调整后，若 trace 同时表明这是 selected `text_region` extraction，应先判断是否可以走 selected-region 文本读取；不满足时保留 runtime AI。

2. **selected_region.local_text / region_scoped_snapshot 的现场文本字段不能生成表单字段 XPath。**
   - `source` 为 `selected_region.local_text` 或 `region_scoped_snapshot`，且 `region_context.inferred_kind == "text_region"` 时，不应生成 `aui-form-item` ancestor XPath。
   - 这些字段更多是“选区文本 evidence”，不是详情页字段 schema。

3. **录制现场值不得进入最终脚本文本定位。**
   - 不生成 `page.get_by_text("采购一批电脑3333")` 作为主定位。
   - 不生成 `_result = {"标题": "采购一批电脑3333"}`。
   - 不把 `local_text_preview`、`section_title`、`field.value` 写成 replay 逻辑。

## 新增抽象：selected_region_text_extract

新增或等价表达一个 trace signal：

```json
{
  "selected_region_text_extract": {
    "source": "region_context",
    "region_id": "region-...",
    "output_key": "title_info",
    "label": "标题",
    "locator": { "method": "css", "value": ".titlePanel-left" },
    "frame_path": [],
    "observed_text": "采购一批电脑3333"
  }
}
```

其中：

- `locator` 是可执行证据，必须来自录制/快照阶段已经明确选定或明确标记可用的 region target locator。
- `observed_text` 只用于诊断和测试断言，不进入最终 replay 逻辑。
- `label` 可由用户指令或结构证据推断；不可靠时可以省略，输出直接为字符串。

该 signal 的核心不是让 compiler 重新选择 locator，而是把录制阶段已经确认的“用户选区目标文本元素”显式传给 compiler。若 trace 里没有这样的明确 locator，compiler 不应自行推断，应回退 runtime AI。

### Producer 边界

真实录制链路中，`selected_region_text_extract` 应由 recording runtime 在接受 trace 前生成，而不是由 compiler 从候选列表中临时猜测。

允许生成该 signal 的条件：

- 当前 region 是 `text_region`。
- 当前步骤是 extraction，且有 `output_key`。
- 选区没有 table/list/action controls 等更强结构证据。
- `local_text` 中存在一个最小文本片段，且 `intersecting_elements` 中有元素文本与该片段完全一致。
- 该元素存在稳定、可执行、非 observed-value 驱动 locator。

不允许生成该 signal 的情况：

- 只能得到 `get_by_text(observed_text)`、`get_by_title(observed_text)` 或 `get_by_role(..., name=observed_text)`。
- 只能得到大容器、rect、local_text 或现场输出值。
- 选区更像表格、列表或操作控件。

这个 producer 逻辑是证据提升，不是 compiler 规则化 selector 选择：它只把录制阶段已经足够明确的目标写入 trace；证据不足仍回 runtime AI。

## 触发条件

只有同时满足以下条件时，才进入 selected-region 文本读取路径：

```text
trace.trace_type == AI_OPERATION
AND region_context.inferred_kind == "text_region"
AND region_context_decision.used_as == "extraction"
AND action_type in {"run_python", "extract_snapshot", ""}
AND output_key 存在
AND 没有 table/list/form 控件主证据
AND trace 已携带明确可执行、非现场值驱动的 region target locator
```

如果没有稳定 locator，保留 runtime AI。

## Locator 证据边界

本设计不要求 compiler 引入一套 locator 评分器。以下内容是证据边界，不是 selector 经验规则：

1. Compiler 可以使用 trace 中明确标记为 selected target 的 locator。
2. Compiler 可以使用已存在的强结构 signal，例如 `region_text_extract.kind == "heading_scoped_text"`。
3. Compiler 不应在多个候选中基于 bbox、文本长度、class 名称或站点经验自行排序。
4. Compiler 不应把 observed text 转成 `get_by_text(observed_text)` 主定位。
5. 若 trace 只有大容器、现场文本、rect、local_text 等弱证据，则回退 runtime AI。

因此，本例是否能生成 `.titlePanel-left.inner_text()`，取决于录制/快照阶段是否已经把 `.titlePanel-left` 作为明确 target locator 写入 trace。若 trace 只包含候选列表而没有明确 target，compiler 不做猜测，保留 runtime AI。

## Compiler 优先级

建议将 AI operation 编译策略调整为：

1. selected-region 文本提取：仅当存在明确 `selected_region_text_extract.locator`
2. 结构化 snapshot 字段提取：仅限真实 detail/form 字段证据
3. heading-scoped text：已有 `region_text_extract.kind == "heading_scoped_text"`
4. single_value / table / list 区域确定性提取
5. side-effect evidence / embedded code
6. runtime AI 兜底

关键点：selected `text_region` extraction 不应被 `extract_snapshot.fields` 过早抢占。

更准确地说，优先级调整的目的不是“让 text_region 一定确定性编译”，而是“阻止 text_region 被误编译成 detail/form 字段提取”。当 text_region 没有强 locator 证据时，正确结果是 runtime AI，而不是硬编码 XPath。

## 输出形态

当字段名可靠时：

```python
_result = {}
_value = (await current_page.locator(".titlePanel-left").inner_text()).strip()
_result["标题"] = _value
_results["title_info"] = _result
```

当字段名不可靠时：

```python
_result = (await current_page.locator(".titlePanel-left").inner_text()).strip()
_results["title_info"] = _result
```

证据不足时：

```python
_result = await _execute_runtime_ai_instruction(current_page, _results, kwargs, "获取标题信息", "title_info")
```

不允许：

```python
_result = {"标题": "采购一批电脑3333"}
await current_page.get_by_text("采购一批电脑3333").inner_text()
current_page.locator("xpath=//*[normalize-space()='标题']/ancestor::*[contains(..., ' aui-form-item ')]")
```

## 测试与验收

实现前应先补回归测试：

1. **标题文本选区**
   - 输入：`text_region + used_as extraction + selected_region_text_extract.locator + observed title value`
   - 期望：生成 `locator(".titlePanel-left").inner_text()`。
   - 期望：脚本不包含 observed title value。
   - 期望：不包含 `aui-form-item` XPath。

2. **text_region 但无稳定 locator**
   - 输入：只有 `local_text` / `rect` / locator candidates，没有明确 selected target locator。
   - 期望：保留 runtime AI。
   - 期望：脚本不包含 `local_text` / `rect` / observed value。

3. **detail_views 字段提取不回退**
   - 输入：`source == detail_views` 且字段有 `data_prop`。
   - 期望：仍生成 `[data-prop="..."]` 字段提取。

4. **表格/列表/单值区域不受影响**
   - 输入：已有 `table_region`、`list_region`、`single_value` trace。
   - 期望：仍走现有 deterministic renderer。

5. **heading_scoped_text 不受影响**
   - 输入：已有 `region_text_extract.kind == heading_scoped_text`。
   - 期望：仍生成 `_extract_bounded_section_text(...)`。

### 需要调整的既有测试预期

这不是“完全零影响”变更。它会有意改变当前 selected text region extraction 的一类旧预期：

- `test_selected_region_local_text_extract_with_fields_uses_snapshot_extract_not_runtime_ai`
  - 旧预期：`selected_region.local_text` 带 fields 时走 snapshot extract。
  - 新预期：如果这是 `text_region + extraction`，且存在稳定 region locator，应走 selected-region 文本读取；如果没有稳定 locator，应回退 runtime AI。
  - 原因：`selected_region.local_text` 的 fields 是选区文本 evidence，不等同于 detail/form 字段 schema，不能再触发 `aui-form-item` 字段模板。

其它既有测试应保持通过，尤其是：

- detail/form snapshot extraction with `data_prop`
- empty snapshot fields fallback to runtime AI
- output-only evidence 不生成字段 locator
- single_value/table/list deterministic renderer
- heading_scoped_text deterministic renderer

## 回滚路径

该变更应集中在 signal 分类与 compiler 分支选择，避免改动 snapshot 主采集链路。

如果实现后出现非预期影响，可以先关闭 selected-region 确定性文本读取分支，让相关 trace 回到 runtime AI。由于底线是不生成硬编码，runtime AI 回退是可接受的安全状态。

## 后置 Harness 方向：AI 审查 trace 到 skill 的合理性

用户提出的“生成 SKILL 脚本后，用 AI 判断 trace 到 SKILL 的过程是否合理，不合理则基于 trace + 脚本做优化和泛化”是合理的 Harness 方向，但不进入本次主路径实现。

它适合作为后置审查层，而不是 compiler 主逻辑：

- 输入：accepted trace、生成的 skill 脚本、compiler strategy metadata、关键禁止项。
- 输出：审查结论、风险分类、建议修复点；默认不自动改写脚本。
- 硬性检查仍应由确定性规则完成，例如“不包含 observed output value”“不包含 selected local_text”“text_region 不生成 aui-form-item XPath”。
- AI 审查只处理语义合理性，例如“这个 trace 是选区标题读取，但脚本却在读表单字段，策略不匹配”。

该 Harness 可以提升可验收性和可追溯性，但不能替代本设计中的边界约束。否则 AI 审查会变成另一个不可控的主路径 Agent。

## 决策结论

本方案对其它功能的影响可控，原因是触发条件严格限定在 selected `text_region` extraction，并明确排除 detail/form/table/list/single_value/heading_scoped_text 等已有强结构路径。

实施顺序应是：

1. 文档落地。
2. 写失败测试，锁定“不能硬编码 observed value”和“证据不足回 runtime AI”。
3. 实现 selected-region 文本提取信号/分类。
4. 调整 compiler 优先级。
5. 跑 RPA compiler 与 recording runtime 相关测试。
