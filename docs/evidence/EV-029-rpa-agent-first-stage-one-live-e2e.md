---
id: EV-029
doc_kind: evidence
scope: feature
feature_refs:
  - F026
created: 2026-07-18
---

# EV-029：新版 RPA Agent 首个阶段一纵向 Live E2E

## Supports Claim

本 Evidence 支撑以下声明：新版 `backend/rpa_agent` 已从真实人工浏览器事件和 `browser-use==0.13.2` 的自然语言 Agent/Tools 调用开始，依次形成 TraceCandidate、BrowserFact、SettlementResult、CoreTrace Timeline、SkillConfigurationDraft、SkillDefinition 与确定性四文件 SKILL；同一次编译的同一产物随后使用两组不同运行数据完成 Replay A、Replay B，并分别通过 eval-app 隐藏后端 Oracle。

本次 E2E 使用可复现的 scripted model 驱动真实 `browser_use.Agent.run`。scripted model 只从 Agent 消息决定下一项 Tools Action，不直接访问 DOM；浏览器动作仍由生产 `RecordingBrowserUseTools.act`、共享 CDP BrowserContext 与 Playwright Runtime 执行。因此本 Evidence 证明 Browser-use Agent/Tools、录制、编译和回放的生产集成边界，不声称证明任意外部 LLM 的业务理解质量。

## Verification Scope

验证范围包括真实双通道创建、逐 Action 记账与结算、依赖就绪、录制后配置、确定性编译、四文件产物、默认 Runtime、两组不同数据回放、隐藏 Oracle、产物硬编码扫描、既有四组契约、目标前端及 eval-app 回归。阶段二、通知、自愈、多 popup 并发及外部 LLM 质量不在范围内。

## Live Chain

```text
Playwright 人工输入/点击
→ Manual Interaction Aggregator + BrowserFact Observer
→ browser_use.Agent.run + RecordingBrowserUseTools.act
→ SettlementResult
→ 22 条 accepted CoreTrace
→ SkillConfigurationDraft / SkillDefinition v0.1
→ DeterministicCompiler（1 次）
→ SKILL.md + skill.manifest.json + skill.py + browser_segment.py
→ Replay A / Replay B（同一 artifact hash）
→ eval-app 隐藏后端 Oracle
```

生产调用边界记录为：

- manual producer：`playwright-manual-inputs`；
- agent producer：`production-browser-use-executor`；
- executor：`rpa_agent.host.browser_use_agent.execute_browser_use_instruction`；
- agent factory：`browser_use.Agent`；
- tools boundary：`RecordingBrowserUseTools.act`；
- Browser-use version gate：`0.13.2`；
- 浏览器上下文：Playwright 与 Browser-use 复用同一个 CDP BrowserContext、登录态和 Page。

## Results

首次完成证据：仓库内副本 [EV-029-live-replay.json](EV-029-live-replay.json)；原始运行位置 `RpaClaw/backend/.tmp/task13-agent-live-evidence/live-replay.json`。

- `evidence_kind=live-playwright-hidden-oracle`；
- `passed=true`；
- `compile_count=1`；
- artifact hash：`fb82ee52afc035aa16f994c851eb0a812f4127e50718493e1eddbc033d91325d`；
- 22 Candidate、22 accepted CoreTrace、Build Readiness `ready=true`；
- 23 次 Agent model invocation、23 次实际 Tools Action、`blocked=0`；
- `wait/done` 显式进入 non-SOP 分类；
- 观测并登记 main Page、随机 URL popup Page 与 iframe；
- Replay A：同一 artifact，22/22 step succeeded，订单号 `PO-2026-05017`，Oracle `passed=true`、`record_count=1`、`mismatches=[]`；
- Replay B：同一 artifact，22/22 step succeeded，订单号 `PO-2026-06042`，Oracle `passed=true`、`record_count=1`、`mismatches=[]`。

为排除偶然成功，又从新创建会话连续完整重跑一次：仓库内副本 [EV-029-live-replay-repeat.json](EV-029-live-replay-repeat.json)；原始运行位置 `RpaClaw/backend/.tmp/task13-agent-live-evidence-repeat/live-replay.json`。

- `passed=true`、`compile_count=1`；
- 新创建产物 hash：`8963ef0f8078178f3fecb0d10a515242506abf5106088e152fae0d09af443`；
- 仍为 22/22 Candidate accepted、23/23 实际 Tools Action、`blocked=0`；
- 该次创建内 Replay A/B 再次共用同一 hash，均 22/22 step succeeded 且 Oracle 通过。

两次独立创建的 hash 不要求相同，因为 trace id 等创建态身份不同；确定性要求是同一份 Timeline + SkillDefinition 编译结果固定，以及同一次编译产物在 A/B 间不变化。两项均已满足。

## Artifacts

生成目录：`RpaClaw/backend/.tmp/task13-agent-live-evidence/compiled_skill/`。

两份仓库内 JSON 是原始 Live runner 输出的等价 JSON 内容副本（仅换行规范化），不含 reset token 或 Secret；`.tmp` 原始目录还保留本次实际生成的四文件 SKILL。

- 四个必需文件齐全；
- 22 条 CoreTrace 分别生成 `step_001` 至 `step_022`，一条 Trace 对应一个步骤函数；
- 订单提取步骤显式生成 `inputs={'input.order_no': ctx.inputs.require('order_no')}`，运行时 Agent 后端只读取该 binding，不从 Replay profile 或录制夹具侧读；
- A/B 共用同一 artifact hash，未重新录制或重新编译；
- 静态扫描未发现两组订单号、随机任务 URL、Token、`index_ordinal`、`.first()` 或 `.nth()`；
- 新生产目录的依赖护栏拒绝旧 `backend.rpa`、旧 Trace、旧 Compiler 和旧 Timeline import；
- Compiler 仅消费依赖闭合 Timeline 与 SkillDefinition，测试覆盖错误动作整体拒绝、无部分发布、无 LLM 编译调用。

## Checks

```text
cd E:\RPA-Agent
python tests/contracts/validate_upstream_model_schema.py
  SUMMARY: passed=36 failed=0 total=36
python tests/contracts/validate_data_asset_schema.py
  SUMMARY: passed=7 failed=0 total=7
python tests/contracts/validate_skill_contract_schemas.py
  SUMMARY: passed=11 failed=0 total=11
python tests/contracts/validate_golden_skill_sample.py
  SUMMARY: passed=13 failed=0 total=13

cd RpaClaw/backend
python -m pytest tests/rpa_agent tests/contracts -q
  473 passed, 1 skipped

cd RpaClaw/frontend
npm.cmd test -- --run <10 个新 RPA Agent 目标测试文件>
  32 passed
npm.cmd run build
  pass

cd rpa-eval-app
python -m pytest backend/test_acceptance_e2e.py evals/test_runner.py -q
  36 passed, 11 subtests passed

cd rpa-eval-app/frontend
npm.cmd test -- --run
  9 passed
npm.cmd run build
  pass

git diff --check
  pass（仅 CRLF 转换 warning）
```

RpaClaw 前端全量 Vitest 在并行压力运行时曾出现 `SkillDetailPage.test.ts` 的 1 个超时和 1 个 mock 次数波动；该文件不在新 RPA Agent 改动范围，立即单文件复跑为 2/2 passed。这里不把全量前端宣称为全绿；本 Goal 的目标测试 32/32 与生产构建均通过。

作为非门禁对照，旧 `backend/rpa` 全量测试结果为 `1833 passed, 1 skipped, 3 failed`。三项失败分别是旧 deterministic CLI 读取缺失 live model 配置、旧 governed bootstrap asset 无 eligible capture、旧 stateful SOP governed bootstrap asset 无 eligible capture。旧目录按 Goal 约束保持只读；这三项不属于明确要求继续通过的四组既有契约，也没有被新生产链路导入或绕过。

## Failure Ledger

真实 Live E2E 在收敛过程中暴露并保留了以下失败记录：

1. eval reset token 与运行服务不一致，后端返回 403；重启到当前 E2E 配置后恢复。
2. 初版 fixture 使用 `index_ordinal` 辅助选择；删除该路径并为业务 option 增加可访问名称，最终只按业务语义唯一定位。
3. 确认点击发生副作用后按钮消失，确定性 target 后验变为非唯一；动作没有丢失，按既定边界降级为 Agent Action。
4. Replay step 13 的 Agent `value` binding 未被默认后端处理；补齐现有 AgentExecutor 输入契约后通过。
5. Replay step 22 最初在 popup Page 而不是 iframe 中读取 status；改为按稳定 FramePath 唯一解析 iframe 后读取。
6. description 测试源码曾包含损坏码点，且 Replay B 的 status 出现异步可见竞态；改为正确 Unicode 并局部等待 status visible。
7. 初版订单提取 Agent 步骤没有 `order_no` 输入 binding，运行夹具存在 profile 侧读风险；扩展既有 `extract_variable.input_refs`，最终生成显式 `skill_input` binding，未知、重复、非法或非 scalar ref 均形成 failed Candidate 且不提交输出。

上述失败均没有通过最近步骤、固定时间窗口、固定行号、`.first()`、录制值回退或静默跳过来掩盖；最终由两次连续完整 Live pass 覆盖。

## Limitations

- 本 Evidence 不评价外部 LLM 供应商的语义质量或稳定性；测试通过受控 model 保证 Harness 可断言、可复现。
- 不覆盖 Goal 明确排除的阶段二数据处理、通知、运行期自愈、断点续跑、多 popup 并发和全部 action.kind。
- eval-app 审查记录有两个非阻断 P2：并发重复提交可能返回一次 500、部分结构性业务字段的请求 Schema 校验偏宽；隐藏 Oracle 仍逐字段比较且只接受一条记录，因此两项不会造成当前 E2E 假通过。

## Notes

AgentMentor 全仓严格知识检查会被仓库内 2026-07-18 以前的旧 ADR、Evidence 与 Feature 模板缺段以及缺失的 `docs/features/INDEX.md` 阻断；该检查报告 599 个既有错误。EV-029 本身已使用当前 Evidence 必需章节，未为关闭本 Goal 扩张修复历史文档。F026 的完成状态只由本 Evidence 中列明的可执行验收决定。

## Conclusion

在本 Goal 明确边界内，首个阶段一纵向能力闭环已完成。完成结论来自真实浏览器链路、同一产物 A/B、隐藏 Oracle、静态产物审计和契约回归的联合证据，不从 Golden JSON 或单元测试单独推导。
