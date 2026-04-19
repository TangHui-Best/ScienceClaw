# RPA ai_script Contract Hardening Design

## Goal

解决当前 RPA ReAct 录制链路里 `ai_script` 步骤在 PR/Issue/Top-N 批量抽取场景下频繁“生成失败或 repair 后仍不收敛”的问题，并明确长期架构边界：

- 语义理解属于 Planner
- 结构化约束属于 Step Contract
- 代码生成属于 ai_script Generator
- 结果验收属于 Validator
- 本地规则只做 fallback，不再承担主语义提取职责

## Problem Statement

当前系统已经把主 ReAct 与 `ai_script generator` 拆分，这是正确方向；但拆分后仍存在一个核心断层：

1. Planner 虽然能把任务判成 `ai_script`
2. 但它产出的结构化 contract 不够稳定或不够完整
3. Generator 仍会从 `script_brief` 这类自然语言摘要二次猜任务
4. 本地 `_infer_*` 规则又会试图补语义
5. 最终形成：
   - contract 来源不唯一
   - 失败时根因不清晰
   - repair 反复围绕自然语言重新猜

这会在以下场景中集中暴露：

- “当前仓库前 10 个 PR，输出严格数组”
- “无论什么状态”
- “固定字段批量提取”
- “当前页面可见结构稳定，但列表语义复杂”

## Explicit Non-Goals

这次设计不做以下事情：

- 不把 GitHub PR/Issue 场景做成站点特判模板
- 不引入新的全局约束对象（例如 `global_constraints bag`）
- 不让 structured executor 重新理解完整用户目标
- 不继续沿“补更多关键词/中文规则”作为主路径演进

## Root Cause

根因不是“DOM 一定太复杂”，也不是“模型不够聪明”，而是职责边界出现了漂移：

### 1. Planner 没有稳定承担“显式产出完整 step contract”的职责

`ai_script` 场景需要的关键字段包括：

- `output_shape`
- `record_fields`
- `item_limit`
- `selection_scope`
- `entity_hint`
- `stable_subpage_hint`
- `result_key`

如果这些字段不是由 Planner 明确产出，而是靠后续本地逻辑或 Generator 自己再猜，系统就会回到旧问题。

### 2. Generator 仍然把自然语言摘要当成主语义来源

`script_brief` 适合做摘要，不适合承担完整协议语义。  
一旦 Generator 主要依赖 `script_brief`，就等于把已经结构化的约束重新降级成自然语言推断。

### 3. Fallback 越权

当前 `_infer_*` 逻辑的初衷是补齐缺失字段，但如果它决定了主路径行为，例如“靠规则理解 selection_scope”，那么它已经越权。

## Target Architecture

### 1. Planner is the source of truth

主 Agent / Planner 在拆出某个 `ai_script` step 时，必须显式产出完整 contract。

最小必需字段：

- `description`
- `result_key`
- `output_shape`
- `record_fields`
- `item_limit`
- `selection_scope`
- `entity_hint`
- `stable_subpage_hint`
- `value_from / url_from / target_from`（如适用）

### 2. Generator consumes contract, not semantics

`ai_script generator` 的职责不是“重新理解用户任务”，而是：

- 接收完整 `ai_script subtask contract`
- 结合当前 `page_snapshot`
- 生成一段满足该 contract 的代码

因此 Generator Prompt 必须改成：

- 完整 contract 为主输入
- `script_brief` 为补充说明
- 禁止重新定义字段语义

### 3. Validator validates against contract

Validator 的职责是验证：

- 输出是否符合 `output_shape`
- 字段是否符合 `record_fields`
- 数量是否符合 `item_limit`
- 范围是否符合 `selection_scope`

它不负责重新理解用户原始需求。

### 4. Fallback stays fallback

本地 `_infer_*` 逻辑保留，但只能：

- 当 Planner 缺字段时做轻量补位
- 对明显同义表达做规范化
- 输出诊断信息，帮助发现 Planner contract 漏项

不能再承担主语义判断职责。

## Design Decisions

### Decision 1: `selection_scope` 不再以本地规则提取为主

推荐方案：

- Planner 必须显式产出 `selection_scope`
- `_infer_ai_script_selection_scope(...)` 保留为 fallback，仅在 contract 缺失时兜底
- 当 fallback 触发时，应该尽量留下可观测信号，便于后续收敛 Planner

原因：

- 这类范围约束本质上是步骤契约，不是后处理猜测
- 如果长期靠规则提取，泛化性必然变差

### Decision 2: `script_brief` 降级为补充字段

`script_brief` 保留，但用途改为：

- 辅助模型理解子任务背景
- 补充 contract 没法优雅表达的叙述性说明

不再允许它覆盖：

- `selection_scope`
- `record_fields`
- `item_limit`
- `entity_hint`
- `stable_subpage_hint`

### Decision 3: 字段口径统一

对记录数组字段，contract 需要统一标准字段名。  
当前推荐统一为：

- `title`
- `author`

如果用户自然语言写的是“creator”，由 Planner 在结构化 contract 层完成归一化；不要让 Generator 和 Validator 分别各猜一套。

## Implementation Plan

### Part A: Contract-first generation

修改 `backend/rpa/assistant.py`：

- 调整 `AI_SCRIPT_GENERATION_SYSTEM_PROMPT`
- 调整 `AI_SCRIPT_REPAIR_SYSTEM_PROMPT`
- 明确：
  - 完整 `ai_script subtask contract` 是主输入
  - `script_brief` 只是补充说明
  - 禁止重新定义 contract 字段含义

### Part B: Planner contract hardening

修改 `backend/rpa/assistant.py` 的 Planner 输出路径：

- 强化 `ai_script plan` 的显式字段产出
- 对缺失字段做诊断
- `_infer_*` 逻辑降级成 fallback，而不是主路径

### Part C: Validator alignment

修改 `backend/rpa/assistant.py` 的 `ai_script` 结果校验逻辑：

- 以 `record_fields` 为主进行字段验收
- 不再把自然语言摘要作为主验证依据
- 为 `selection_scope` 留出后续校验接口

### Part D: Failure observability

补充 `ai_script` 失败原因分类：

- `planner_contract_incomplete`
- `generator_parse_failed`
- `generator_kind_mismatch`
- `generator_missing_code`
- `execution_failed`
- `quality_validation_failed`

目标不是增加用户可见噪音，而是让系统内部能区分“生成前失败”和“执行后失败”。

## Expected Outcome

设计落地后，系统行为应变成：

1. Planner 明确产出 `ai_script` contract
2. Generator 直接消费 contract 生成代码
3. Validator 直接用 contract 验证输出
4. Fallback 只在 contract 缺失时补位
5. 当失败发生时，系统能明确知道断点在：
   - Planner
   - Generator
   - Execution
   - Validator

## Acceptance Criteria

- “前 10 个 PR / 严格数组 / 固定字段” 这类任务，`ai_script` 生成不再主要依赖 `script_brief`
- `selection_scope` 以 Planner contract 为主来源
- 本地 `_infer_*` 逻辑不再主导主路径
- 失败时能区分生成失败与执行失败
- 代码与文档都体现“contract-first, fallback-second”的原则
