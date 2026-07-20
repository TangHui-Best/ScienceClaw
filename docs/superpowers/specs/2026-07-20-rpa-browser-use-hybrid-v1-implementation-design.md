# Browser-use 人工/自然语言混合录制 V1 实施规格

日期：2026-07-20
状态：Accepted for implementation
Feature：`F029`
Decision：`ADR-008`
开发分支：`codex/rpa-browser-use-hybrid-v1`
基线：`codex/rpa-browser-use-recording-runtime@3aa97568`

## 1. 权威性与开发前提

本规格是 `codex/rpa-browser-use-hybrid-v1` 的 V1 实施来源。开发前依次阅读：

1. `docs/features/F029-rpa-browser-use-hybrid-v1.md`
2. `docs/decisions/ADR-008-rpa-browser-use-staged-hybrid-recording.md`
3. `docs/decisions/ADR-005-browser-use-recording-operator-integration-boundary.md`
4. `docs/features/F025-browser-use-recording-operator-poc.md`
5. `docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`
6. `docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md`

`codex/rpa-agent-intent-first-dual-mode` 中的 F028、ADR-007 和新 `rpa_agent/**` 数据模型不属于本 V1 权威实现。不得为了复用少量代码而整体 cherry-pick 该分支。

工作目录为 `E:\Work-Project\OtherWork\ScienceClaw`。该目录存在大量本地未跟踪运行产物：

- 不删除或覆盖用户本地数据；
- 不执行 `git add .`；
- 提交前使用显式路径暂存；
- 验证报告必须区分本次 tracked 变更与既有 untracked 产物。

## 2. 原始目标

在一次 Local 录制中，用户能够按任意业务顺序交替执行：

- 人工精准操作；
- Browser-use 自然语言逻辑操作。

两者操作同一个当前浏览器页面并共享页面状态。录制完成后：

- 人工步骤按现有逻辑编译为 Playwright；
- 自然语言步骤按用户原始文本编译为 Browser-use runtime instruction；
- Skill 保持录制时的顶层顺序；
- 在新的 Local 浏览器会话中使用真实 LLM 完整重放。

## 3. V1 范围

### 3.1 必须实现

- 复用旧 `RPAAcceptedTrace` 数据模型和 `session.traces` 时间线。
- 复用现有人工监听、Trace 生成、配置、Playwright 编译与测试保存链路。
- Browser-use 通过当前录制浏览器的 CDP URL 和精确 target 附着当前 Page。
- Browser-use 执行自然语言指令时作用域暂停人工 Trace 入库。
- 一条用户自然语言指令只形成一个 `AI_OPERATION` Trace。
- Trace 保存用户原始 instruction，并可保留 Browser-use History/结果作为诊断。
- Compiler 对 Browser-use Trace 始终生成 runtime Browser-use instruction。
- Local 模式真实 UI、真实 Playwright 浏览器、真实 Browser-use、真实 LLM E2E。

### 3.2 明确不实现

- 新 CoreTrace/RecordingTimeline/AIInstructionStep 数据模型。
- Browser-use History 到 Playwright 的代码生成。
- PlaywrightSegment/AgentSegment 新 IR。
- Settlement/Candidate/Evidence ledger 新体系。
- SecretStore 与 Browser-use `sensitive_data` 的新闭环。
- DataAsset 与 Browser-use `available_file_paths` 的新闭环。
- 结构化 Agent output 契约重构。
- Docker、Kubernetes 或远程 Runtime。
- Recorder/Configure/Test UI 整体重构。
- 针对 GitHub 或单一站点的生产规则。

## 4. 不可违反的架构边界

1. Browser-use 是自然语言浏览器任务的执行主体。
2. ScienceClaw/RPA Agent 是当前页面与上下文提供者，也是旁路观察者。
3. ScienceClaw 不注入录制专用 Browser-use Tools。
4. ScienceClaw 不把 Browser-use 限制为单动作 Agent，不设置 `max_actions_per_step=1`。
5. Trace、History 完整度和 Compiler 不得控制 Browser-use 的 planner、retry 或 done。
6. Browser-use 的执行成功由其原生完成语义决定；ScienceClaw 只判断是否形成可保存的 AI Trace 和是否满足产品运行要求。
7. recorder 暂停只影响 ScienceClaw 的事实入库，不得暂停、改写或过滤 Browser-use 的实际动作。
8. `RPAAcceptedTrace` 仍是 V1 唯一 accepted timeline；不得恢复第二套 steps/recorded_actions 编译事实源。
9. Browser-use final result 和 History 在 V1 不是代码生成事实源。
10. Harness 只负责验证，不能合成或修改产品 Trace。

## 5. 目标数据流

```text
Recorder UI
  |
  |-- 人工操作 ---------------------------------------------|
  |                                                        |
  |    existing recorder listener                          |
  |      -> existing manual RPAAcceptedTrace                |
  |                                                        |
  |-- 自然语言 instruction --------------------------------|
       -> acquire one-instruction execution guard           |
       -> pause manual trace ingestion                      |
       -> BrowserUseRecordingOperator                       |
            task = original instruction + legacy context    |
            browser = current CDP + exact current target    |
            native Browser-use agent loop                   |
       -> save one AI_OPERATION RPAAcceptedTrace            |
            user_instruction = exact original input         |
            signals.browser_use.history = diagnostics only  |
       -> finally resume manual trace ingestion              |
       -> release execution guard                            |
  |                                                        |
  +---------------- session.traces ordered timeline --------+
                           |
                           v
                  TraceSkillCompiler
                    manual -> Playwright
                    browser_use -> original AI instruction
                           |
                           v
                    generated Skill
```

## 6. 现有 Trace 的 V1 使用方式

自然语言 Trace 继续使用旧模型，至少满足：

```python
RPAAcceptedTrace(
    trace_type=RPATraceType.AI_OPERATION,
    source="browser_use",
    user_instruction=<用户原始输入>,
    description=<用户原始输入>,
    before_page=<执行前页面>,
    after_page=<执行后页面>,
    signals={
        "runtime_ai": {
            "preserve": True,
            "reason": "browser_use_hybrid_v1",
            "provider": "browser_use",
        },
        "browser_use": {
            # History/actions/results 仅诊断，不参与 V1 codegen
        },
    },
    ai_execution=RPAAIExecution(language="browser_use", code="", ...),
)
```

不得为了加入 queued/running/evidence/compile 状态而修改 Trace 主模型。执行中的 UI 状态优先复用现有聊天/请求状态；成功后才追加可编译 Trace。失败的自然语言指令可以保留在聊天和诊断中，但不能伪装成成功 Trace。

## 7. 监听作用域暂停协议

### 7.1 语义

“关闭录制监听”在实现中必须解释为“暂停人工 Trace 入库”，不是销毁 Playwright Page、CDP Observer、BrowserContext 或 recorder 实例。

### 7.2 必要行为

- 使用显式 execution token 或计数型 guard，不能只依赖易失的全局布尔值。
- 同一录制会话一次只允许一条 Browser-use 指令处于执行态。
- 在 Browser-use 启动前暂停，在 Trace 保存完成或失败处理结束后恢复。
- 恢复必须位于 `finally`，覆盖成功、异常、超时、取消和客户端断开。
- 暂停期间人工事件不得进入新的顶层 Trace。
- Browser-use 执行结果仍通过 Browser-use History 和 before/after page 写入诊断。
- UI 在 Browser-use 执行期间不得允许用户同时进行人工录制操作；若无法禁用，后端必须明确拒绝并发人工输入，而不能静默丢失。

### 7.3 禁止行为

- 不关闭浏览器级事件总线。
- 不移除并重建所有 Page 监听器。
- 不通过限制 Browser-use action 来避免重复 Trace。
- 不在失败后遗留 paused 状态。
- 不把 Browser-use action 重新注入人工 Trace 时间线。

## 8. Browser-use 调用边界

### 8.1 Page/CDP

- 使用当前录制会话提供的 CDP URL。
- 从实际当前 Playwright Page 获取精确 target ID；不得仅依赖 URL 猜测 tab。
- Browser-use 开始前聚焦该 target。
- 一轮结束后清理 Browser-use 自己的 CDP/session/event 资源，但不得关闭 BrowserHost 所拥有的浏览器和 Page。
- 可吸收 `keep_alive=True + stop()` 语义，但必须先用现有 Browser-use 版本测试证明不会杀宿主浏览器。

### 8.2 自主性

- 使用 Browser-use 原生 Agent、Tools 和 History。
- 删除旧 Prompt 中对 action schema 的逐动作教学和 evaluate fallback 规则，除非真实版本兼容测试证明 Browser-use API 存在不可规避的明确缺陷。
- 不注入 `initial_actions` 重新导航当前 URL。
- 不设置用于改变规划语义的 `max_actions_per_step`。
- 可使用宿主级请求超时和用户取消保护资源，但不得把超时实现为逐步控制 planner/done。
- `use_vision` 是否开启沿用当前已验证配置，本 V1 不为视觉能力改造上下文。

### 8.3 V1 上下文

V1 为降低回归风险，沿用旧分支已经存在的普通上下文方式：

- 用户原始 instruction；
- 当前页面/CDP 信息；
- 现有普通 `runtime_results` / 全局变量；
- 现有 `region_context` 若为空则不传，不新增区域选择适配；
- 现有上传路径行为保持不变，不纳入验收。

V1 不宣称这些上下文已完成敏感数据安全治理。验收数据不得包含密码、Token、Cookie、API Key、个人敏感信息或敏感文件路径。

## 9. Compiler 规则

### 9.1 人工 Trace

保持当前 `TraceSkillCompiler` 的人工动作、导航、下载、popup、iframe、dataflow 等逻辑，不进行顺手重构。

### 9.2 Browser-use Trace

对满足以下任一条件的 Trace：

- `trace.source == "browser_use"`；
- `trace.ai_execution.language == "browser_use"`；
- `signals.browser_use` 存在；

V1 必须：

- 忽略 `_render_browser_use_action_replay_trace()` 的结果；
- 不根据 History/actions 生成 click/input/goto Playwright；
- 读取 `trace.user_instruction`，为空时才回退 `trace.description`；
- 调用 `_execute_browser_use_instruction(...)`；
- 保持与前后人工 Trace 的原始顺序；
- 不把录制期 extracted output 写死为 runtime output。

需要架构测试证明“有 replayable History 的 Browser-use Trace 仍然编译为原始指令”。

## 10. Runtime 重放

- generated Skill 在当前 runtime Page 上调用 Browser-use。
- runtime Browser-use 仍通过当前 CDP URL 和精确 target 附着 Page。
- 运行时传入的 instruction 必须与录制用户原文一致，不得被录制期 History 或 final result 改写。
- 普通 `_results` 依赖沿用旧实现；本 V1 不新增 Secret/DataAsset 类型。
- Browser-use 完成后继续使用同一 Page 执行后续人工 Playwright 或下一条 AI 指令。
- 测试运行创建新的 Local browser/context/page，不复用录制时的页面、cookie 或 observer。

## 11. UI 约束

- 保持现有 Recorder、Configure、Test 主流程和布局。
- 不移植 F028 的新工作台或内部状态模型 UI。
- Browser-use 执行期间显示现有 loading/running 状态，并暂时禁止新的自然语言提交和人工录制输入。
- 失败后必须恢复可操作状态并显示明确错误。
- Configure 中自然语言步骤继续显示用户原始 instruction。
- 不在 UI 暴露 Browser-use History、CDP target ID 或内部诊断对象。

## 12. 测试先行与能力增量

### 增量 A：Compiler 收缩

先写失败测试，证明含 Browser-use actions 的 Trace 当前会生成 Playwright；再修改为始终生成原始 Browser-use instruction。

回滚点：只回滚 compiler 分支和对应测试，不触碰录制执行。

### 增量 B：监听作用域暂停

为成功、失败、取消、并发请求建立状态机测试，证明不会重复 Trace，也不会遗留 paused 状态。

回滚点：恢复旧监听路径，不改变 Browser-use Operator。

### 增量 C：Browser-use 原生边界

移除宿主对 action schema、`initial_actions`、`max_actions_per_step` 的干预；接入精确 Page target 和不杀宿主浏览器的 lifecycle。

回滚点：Operator 独立提交，可回滚到旧调用参数。

### 增量 D：产品链路集成

串联 Recorder UI、Trace append、Configure、Generate、Test；不得重构页面结构。

回滚点：前端/route orchestration 独立提交。

### 增量 E：Local Live UI E2E

使用真实 UI、真实 Playwright、真实 Browser-use 和真实 LLM 验收。自动化测试通过不等于产品能力通过。

## 13. 自动化验证要求

至少覆盖：

- Browser-use Trace 即使含 replayable actions 也编译为原始 instruction。
- 人工 Trace 仍编译为原 Playwright。
- 人工/AI/人工混合顺序不变。
- Browser-use 成功只追加一个 AI Trace。
- Browser-use action 不形成独立人工 Trace。
- Browser-use 异常、超时、取消后监听恢复。
- 并发自然语言请求被拒绝或串行化。
- Browser-use 结束后宿主 Page 仍可操作。
- exact target 与当前 Playwright Page 一致。
- 普通前序 `_results` 可进入后续 Browser-use 上下文。
- 现有 Core SOP->Skill focused regression 无回归。

## 14. Local Live UI E2E

最小验收流程：

1. 在 `E:\Work-Project\OtherWork\ScienceClaw` 本地启动后端和前端，不使用 Docker。
2. 从真实 Recorder UI 创建新录制会话。
3. 人工导航到一个公开网页，验证产生现有手工 Trace。
4. 输入一条需要语义判断的自然语言指令，验证 Browser-use 操作同一页面。
5. Browser-use 完成后再执行一项人工点击或输入，验证监听已经恢复。
6. 再输入一条自然语言指令，验证仍使用当前页面状态。
7. 检查 Trace：每条自然语言只有一个 AI Trace，没有重复 Browser-use 低层动作。
8. 完成录制并进入 Configure，确认步骤顺序和原始 instruction。
9. 生成 Skill，检查人工步骤为 Playwright，自然语言步骤为 `_execute_browser_use_instruction`。
10. 在新的 Local 测试会话中使用真实 LLM 重放。
11. 验证最终页面和一个普通非敏感变量结果。
12. 退出测试并新建录制，确认没有复用旧 Page 或监听暂停状态。

验收必须保存：

- 启动命令；
- provider/model 名称，不保存 API Key；
- 关键 API 状态；
- Browser-use 日志的脱敏摘要；
- Recorder/Configure/Test 截图；
- Trace 脱敏摘要；
- 生成 Skill 关键片段；
- 重放结果；
- 新旧会话隔离证据。

## 15. V2 进入条件

只有 V1 Local E2E 稳定通过后，才开始 History-to-Playwright。V2 必须按单条自然语言 Trace 分类：

- 稳定、确定性、具有可靠 locator 的动作可以编译 Playwright；
- “最相关、最佳、推荐、风险最高”等运行时语义判断继续保留 AI；
- 无法证明稳定性的 History 回退原始 AI instruction；
- 禁止“部分 Playwright + 完整原始 AI instruction”重复执行同一顶层步骤。

Browser-use 0.13.2 中历史 Playwright 导出 API 已非稳定公开能力，因此 V2 必须建立自有的受测 normalizer/compiler，而不是依赖被注释或私有实现。

## 16. V3 进入条件

Trace 重构不是既定工作，只在下列证据至少一项成立时启动：

- 旧 Trace 无法区分 AI 执行状态和可编译状态；
- 无法表达 Browser-use History 作为诊断子证据；
- V2 无法在单条顶层步骤上稳定选择 Playwright 或 AI；
- 现有 `signals` 扩展产生不可维护的字段冲突；
- 会话/副作用/输出契约无法在旧模型中可靠验证。

在这些证据出现前，禁止以“模型更干净”为由重构 CoreTrace。

## 17. 完成声明边界

只有以下全部成立才能声明 F029 V1 完成：

- 自动化测试与 Core focused regressions 通过；
- Local 真实 UI/浏览器/LLM E2E 通过；
- 人工/自然语言交替录制与重放通过；
- 无重复顶层 Trace；
- 自然语言编译保留用户原文；
- Browser-use 不杀宿主浏览器；
- 失败后监听可靠恢复；
- Evidence 写明 provider/model、命令、截图、Trace、Skill 和重放结果；
- Feature、ADR、Evidence、Recovery Snapshot 与实际结果一致；
- 提交只包含显式 tracked 变更，未误提交本地运行数据。

规格建立、代码合并或自动化测试通过，均不能单独替代真实 Local 产品验收。
