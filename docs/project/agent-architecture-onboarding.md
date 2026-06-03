# 内网 Agent 技术架构接手导航

本文面向切换到内网开发后的 Agent 接手、定位问题和开发功能。它不是新的架构真相源，也不替代 `AGENTS.md`、ADR、Feature、Evidence 或 Harness 文档；它的职责是把“遇到一个现象后先看哪里”讲清楚。

阅读顺序建议：

1. 先读本文件，建立问题定位路径。
2. 再按问题类型跳到 `docs/project/reference.md`、`docs/rpa/录制转SKILL架构实现与数据流说明.md`、`docs/rpa/harness/README.md` 或对应 ADR/Feature/Evidence。
3. 最后回到源码和测试验证判断。源码和测试永远高于历史设计文档。

## 1. 一句话架构

RpaClaw 是 privacy-first personal research assistant，包含对话 Agent、文件/技能系统、沙箱执行、RPA 录制与 Skill 生成。当前 RPA 主方向是：

```text
Trace-first Recording + Post-hoc Skill Compilation
```

也就是：

```text
录制阶段真实操作浏览器并沉淀 accepted trace；
编译阶段消费 trace evidence，生成可回放 Skill；
Harness 只观察、治理和回归这些事实资产，不定义产品录制事实。
```

遇到 RPA 问题时，优先按这个边界定位：

```text
页面事实采集 / snapshot
  -> RecordingRuntimeAgent / 手动 recorder
  -> accepted trace timeline
  -> TraceSkillCompiler
  -> generated Skill replay
  -> Harness asset / regression
```

不要从最后的失败现象直接跳到“加规则”。先确定失败发生在哪一层。

## 2. 项目入口文档

| 场景 | 先读 |
| --- | --- |
| 了解全局技术栈、目录、端口、API、环境变量 | `docs/project/reference.md` |
| 判断设计文档是否仍然有效 | `docs/DESIGN_STATUS.md` |
| RPA 录制到 Skill 的主链路、Trace、Snapshot、Compiler | `docs/rpa/录制转SKILL架构实现与数据流说明.md` |
| TraceSkillCompiler 泛化原则 | `docs/rpa/trace-skill-compiler-generalization.md` |
| Harness 资产治理、回归、promotion、triage | `docs/rpa/harness/README.md` |
| Harness/Core 边界 | `docs/decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md` |
| 历史功能边界和验证证据 | `docs/features/`、`docs/evidence/` |
| 架构决策 | `docs/decisions/` |
| 失败教训和必须避免的重复错误 | `docs/lessons/` |

历史计划和设计主要在 `docs/superpowers/` 下。它们有调试价值，但不一定代表当前架构。引用前先看 `docs/DESIGN_STATUS.md`。

## 3. 系统模块地图

### 3.1 Backend

| 模块 | 作用 | 常看文件 |
| --- | --- | --- |
| FastAPI 入口 | 应用启动、路由挂载、健康检查 | `RpaClaw/backend/main.py` |
| 配置 | 环境变量、运行模式、路径 | `RpaClaw/backend/config.py` |
| 对话 Agent | LangGraph/DeepAgents 会话、工具、SSE、MCP | `RpaClaw/backend/deepagent/` |
| REST API | 认证、会话、聊天、文件、模型、RPA、MCP | `RpaClaw/backend/route/` |
| 存储抽象 | local / MongoDB repository | `RpaClaw/backend/storage/` |
| MongoDB | 数据库连接 | `RpaClaw/backend/mongodb/` |
| Built-in skills | 内置文档、表格、PPT、PDF 等技能 | `RpaClaw/backend/builtin_skills/` |
| RPA | 录制、执行、snapshot、trace、compiler、Harness | `RpaClaw/backend/rpa/` |

### 3.2 Frontend

| 模块 | 作用 | 常看文件 |
| --- | --- | --- |
| API client | 前端请求入口，已包含 `/api/v1` 前缀 | `RpaClaw/frontend/src/api/client.ts` |
| 页面 | Chat、Skills、Tools、Tasks、RPA 等页面 | `RpaClaw/frontend/src/pages/` |
| RPA 页面 | 录制、配置、测试、MCP 转换、API Monitor | `RpaClaw/frontend/src/pages/rpa/` |
| RPA 工具函数 | timeline、assistant、region、screencast、configure | `RpaClaw/frontend/src/utils/rpa*.ts` |
| i18n | 英文/中文文案 | `RpaClaw/frontend/src/locales/en.ts`、`RpaClaw/frontend/src/locales/zh.ts` |

前端 API 调用不要再手写 `/api/v1`，否则会出现双前缀。

### 3.3 RPA Core

| 层 | 责任 | 关键文件 |
| --- | --- | --- |
| Browser/runtime | CDP、screencast、Playwright 上下文 | `cdp_connector.py`、`screencast.py`、`runtime_context.py`、`manager.py` |
| Snapshot | raw snapshot 到 compact snapshot / structured facts | `snapshot_compression.py` |
| 自然语言执行 | 只执行当前用户指令，不重新规划整套 SOP | `recording_runtime_agent.py` |
| 手动录制归一化 | recorder action / manual step 转 accepted trace | `trace_recorder.py`、`manual_recording_normalizer.py` |
| Trace 模型 | accepted trace、runtime result、diagnostics | `trace_models.py` |
| Timeline/order | accepted trace 排序和展示 | `trace_timeline.py`、`trace_ordering.py` |
| 编译 | trace evidence 到 `skill.py` | `trace_skill_compiler.py`、`skill_exporter.py` |
| RPA API | 录制、配置、测试、导出接口 | `RpaClaw/backend/route/rpa.py` |

### 3.4 Harness

Harness 是 RPA 录制资产治理与回归验证层。它观察事实、生成报告、支持人工审查和 promotion，但不能改变 Core 录制事实。

| 功能 | 常看文件 / 命令模块 |
| --- | --- |
| capture / asset store | `RpaClaw/backend/rpa/harness/capture.py`、`store.py` |
| 资产结构校验 | `run_asset_validation.py`、`asset_validation.py` |
| 敏感信息扫描 | `run_asset_sensitivity_scan.py`、`sensitivity_scan.py` |
| 人工审查包 | `run_asset_review.py`、`asset_review.py` |
| promotion | `run_asset_promote.py`、`asset_promotion.py` |
| asset pool doctor | `run_asset_pool_doctor.py`、`asset_pool_doctor.py` |
| deterministic / full-live profile | `run_harness_profile.py`、`profile_runner.py`、`full_live_profile.py` |
| Core SOP -> Skill 验证 | `run_asset_core_chain.py`、`asset_core_chain.py` |
| governed regression | `run_governed_regression.py`、`governed_regression.py` |

Harness 入口必须先读 `docs/rpa/harness/README.md`，再按任务跳到更细文档。

## 4. 关键数据流

### 4.1 RPA 录制到 Skill

```text
用户操作 / AI 指令
  -> 浏览器真实执行
  -> raw snapshot / compact snapshot
  -> RPAAcceptedTrace
  -> session.traces
  -> runtime_results
  -> TraceSkillCompiler
  -> SKILL.md + skill.py
  -> replay 时通过 _results 恢复跨步骤数据流
```

定位时先问三个问题：

1. `raw_snapshot` 是否有目标信息？
2. `compact_snapshot` 是否保留了目标信息？
3. `trace` 是否沉淀了足够 evidence 给 compiler？

如果 raw 有、compact 没有，优先查 snapshot 压缩；不要先改 prompt 或 compiler。

### 4.2 Harness 资产流

```text
产品录制完成
  -> 写出 Harness asset
  -> validation / sensitivity scan / review
  -> 人工确认 expected signals 和 sensitivity
  -> promote candidate / golden
  -> deterministic / full-live / governed regression
  -> reports / Evidence
```

注意：

```text
runtime_status=success 不代表 baseline 可接受；
candidate-lite 不阻塞回归；
candidate / golden 必须有人审 expected signals 和 sensitivity；
Harness asset 不能反过来定义 Core 录制事实。
```

## 5. 问题定位决策树

### 5.1 AI 操作错元素、选错区域、提取错数据

优先顺序：

1. 查 raw snapshot 是否包含目标信息。
2. 查 compact snapshot 是否丢失目标区域、候选摘要、表格/详情结构。
3. 查 trace 的 `signals`、`region_context`、`locator_candidates` 是否保留了正确 evidence。
4. 再看 `RecordingRuntimeAgent` prompt / planner 行为。
5. 最后才考虑 compiler 或 selector fallback。

常看文件：

- `RpaClaw/backend/rpa/snapshot_compression.py`
- `RpaClaw/backend/rpa/recording_runtime_agent.py`
- `RpaClaw/backend/rpa/trace_recorder.py`
- `RpaClaw/backend/rpa/trace_models.py`

### 5.2 Skill 回放失败

优先区分：

```text
trace 本身事实错了？
compiler 消费 trace 的方式错了？
generated skill 在 replay 环境里错了？
```

常看文件：

- `RpaClaw/backend/rpa/trace_skill_compiler.py`
- `RpaClaw/backend/rpa/skill_exporter.py`
- `RpaClaw/backend/rpa/executor.py`
- `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`
- `RpaClaw/backend/tests/test_rpa_trace_e2e.py`

判断原则：

- 录制现场值只能作为 evidence，不能随便硬编码成 replay 逻辑。
- 后一步依赖前一步结果时，优先用 `_results` / `output_key`。
- 语义判断步骤应保留 runtime AI，不要把录制时的答案伪装成确定性规则。

### 5.3 手动录制 timeline 或 Configure 页面不一致

先查 accepted trace timeline，不要只看 UI 展示。

常看文件：

- `RpaClaw/backend/rpa/trace_timeline.py`
- `RpaClaw/backend/rpa/trace_ordering.py`
- `RpaClaw/backend/route/rpa.py`
- `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- `RpaClaw/frontend/src/pages/rpa/ConfigurePage.vue`
- `RpaClaw/frontend/src/utils/rpaConfigureTimeline.ts`
- `RpaClaw/frontend/src/components/rpa/RpaStepTimeline.vue`

### 5.4 Harness 回归失败

先分层：

```text
资产结构坏了 -> validation / asset schema
expected signals 不可信 -> review / human correction
Core SOP->Skill 不一致 -> core-chain / compiler / trace
profile 报告失败 -> profile runner / governed regression
```

常用命令：

```powershell
$env:PYTHONPATH='RpaClaw'
$assetRoot = 'data\rpa_harness_assets_internal'
$assetId = '<asset_id>'

python -m backend.rpa.harness.run_asset_validation --assets $assetRoot --asset-id $assetId
python -m backend.rpa.harness.run_asset_review --assets $assetRoot --asset-id $assetId
python -m backend.rpa.harness.run_asset_core_chain --assets $assetRoot --asset-id $assetId
python -m backend.rpa.harness.run_harness_profile --assets $assetRoot --profile deterministic --output tmp-harness-profile-deterministic.json
```

如果 Core 文件也被改了，必须跑 focused Core SOP->SKILL regression，不能只跑 Harness。

### 5.5 前端请求失败或接口路径异常

先查：

1. `apiClient` 是否已经带 `/api/v1`。
2. 后端路由是否实际挂载到 `/api/v1/<path>`。
3. 本地 `BACKEND_URL` 是否正确。

常看文件：

- `RpaClaw/frontend/src/api/client.ts`
- `RpaClaw/frontend/src/api/*.ts`
- `RpaClaw/backend/route/*.py`
- `RpaClaw/backend/main.py`

### 5.6 本地模式 / Docker 模式差异

关键区别：

| 模式 | 环境变量 | 浏览器呈现 |
| --- | --- | --- |
| local desktop | `STORAGE_BACKEND=local` | host Playwright + CDP screencast |
| Docker/VNC | 非 local storage backend / sandbox mode | noVNC，经常通过 `18080` |

不要把 Docker noVNC 问题归因到 local CDP screencast，也不要用 raw VNC `16080` 当 noVNC 入口。

## 6. 修改类型与最小验证

| 修改类型 | 最小验证方向 |
| --- | --- |
| 只改文档 | 检查链接、术语、是否与 `AGENTS.md` 和现有 ADR 冲突 |
| 改 RPA Core trace / compiler / recorder | 跑相关 `test_rpa_trace_*`、`test_rpa_recording_runtime_agent.py`、必要时跑 Core SOP->SKILL regression |
| 改 snapshot compression | 跑 `test_rpa_snapshot_compression*.py`，并检查 raw/compact 信息保留路径 |
| 改 RPA UI | 跑对应 Vue test，如 `RecorderPage.test.ts`、`ConfigurePage.test.ts`、`TestPage.test.ts` |
| 改 Harness asset / promotion / profile | 跑对应 `test_rpa_harness_*`，并用 README 中 CLI 命令做 focused 验证 |
| 改 API Monitor / RPA MCP | 跑 `test_rpa_mcp_*` 或 `test_api_monitor_*`，同时确认不是污染 RPA Core 主链路 |
| 改存储 / 会话 / 文件 | 跑 storage、sessions、route 相关测试，并检查 local / MongoDB 分支 |
| 改前端 API 调用 | 跑对应 util/api tests，确认没有 `/api/v1` 双前缀 |

Windows / PowerShell 常用后端测试前置：

```powershell
$env:PYTHONPATH='RpaClaw'
```

前端通常在：

```powershell
cd .\RpaClaw\frontend
npm run test -- <target>
```

## 7. 开发前必须避免的误判

### 7.1 不要把 Harness 当 Core

Harness 可以证明资产是否健康、expected 是否可信、回归是否通过；它不能参与或改变 recorder 事实捕获、trace 排序、dataflow 推断、compiler 动作分支。

如果开启或关闭 Harness 导致 SOP -> Skill 主链路不同，优先查 Core 边界问题。

### 7.2 不要用站点特例塑造架构

GitHub、百度、内部系统都只能作为验证案例。新增 compiler、snapshot、repair、dataflow 逻辑时，先说明它解决的通用问题，再说明站点案例如何落入该抽象。

### 7.3 不要用空值硬拦截代替 root cause

空字符串、空列表、空表格可能是合法结果。遇到空提取先查 selector、snapshot、planner、compiler 或数据流，不要全局新增“空值失败”。

### 7.4 不要让 fallback 反客为主

`_infer_*`、关键词匹配、站点模板、selector 经验只能救局部失败。如果它们开始主导主路径，应回到架构边界重新判断。

### 7.5 不要把历史 design plan 当当前真相

历史设计有价值，但当前真相顺序是：

```text
源码和测试
  -> README / AGENTS / CLAUDE
  -> DESIGN_STATUS 和当前专项文档
  -> docs/superpowers 历史 specs / plans
```

## 8. 本地启动速查

Backend：

```powershell
$env:PYTHONPATH="RpaClaw"
python -m uvicorn backend.main:app --app-dir .\RpaClaw --host 0.0.0.0 --port 8000 --reload --reload-dir .\RpaClaw\backend
```

Frontend：

```powershell
cd .\RpaClaw\frontend
$env:BACKEND_URL = "http://localhost:8000"
npm run dev
```

默认 local / desktop 模式会以 bootstrap admin 进入，不需要登录。设置 `AUTH_PROVIDER=local` 后启用登录；默认 bootstrap admin 是 `admin` / `admin123`，除非被环境变量覆盖。

## 9. 给内网 Agent 的接手 checklist

开始一个非平凡任务前：

1. 读 `AGENTS.md`，确认项目军规。
2. 如果涉及 RPA/Harness，读 `docs/rpa/harness/README.md` 和对应 ADR。
3. 如果涉及历史设计，先读 `docs/DESIGN_STATUS.md`。
4. 明确问题层级：snapshot、agent、trace、compiler、skill replay、Harness、UI、API、storage。
5. 找到最小相关文件，不要跨模块大改。
6. 先写或选定最小验证命令，再改代码。
7. 结束时说明验证结果；若涉及 Harness/RPA 非平凡工作，保留 Feature/Evidence closeout 或明确说明 closeout pending。

这份 checklist 的核心目标不是让 Agent 多写文档，而是让它少走错层、少加规则、少把 Harness 和 Core 的职责混在一起。
