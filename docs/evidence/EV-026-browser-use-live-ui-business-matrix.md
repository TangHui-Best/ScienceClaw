---
id: EV-026
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F025-browser-use-recording-operator-poc.md
created: 2026-07-05
updated: 2026-07-05
evidence_level: live_ui_e2e
---

# EV-026: Browser-use 真实业务矩阵 Live UI E2E

## 2026-07-05 终态复测更新

本次复测的最终结论已经从早期“录制链路失败”推进为：

- 通过 ScienceClaw RecorderPage 的真实 live UI，自然语言逐步输入业务语义指令，browser-use 已完成采购验收矩阵录制，得到 14 条有效业务 Trace。
- 覆盖场景包括：登录后页面操作、iframe 内操作、表格搜索/筛选/行内按钮、弹窗/抽屉/下拉树、文件上传/下载、分页提取、多标签页、日期控件、富文本和复杂组件。
- 录制最终检查步骤返回 `ALL_SCENARIOS_PASS`。
- 原始 browser-use 语义回放在第 5 条审批弹窗步骤失败，根因不是页面能力，而是回放时再次调用 browser-use/LLM 造成不稳定；随后所有可用模型均返回 `insufficient_quota`。
- 已将 browser-use Trace 编译策略改为优先使用录制期 `signals.browser_use.actions/action_results` 生成确定性 Playwright 动作回放；动作证据不足时才回退到 browser-use 语义执行。
- 使用前 14 条业务 Trace 生成的确定性 SKILL：`.tmp/rpa-live-ui-deterministic-browser-use-skill-first14.py`。
- 真实 live UI 回放结果：`.tmp/rpa-live-ui-deterministic-skill-first14-direct-result.json`，`success=true`，最后输出包含 `ALL_SCENARIOS_PASS`。
- 本轮相关自动化测试：`123 passed`。

注意：后端当前运行进程如果未被 reload/restart，可能仍使用旧的编译器代码；代码层修复已经落盘，后续通过正常后端启动或 reload 后，`/generate` 将使用新的确定性 browser-use Trace 编译逻辑。

## Supports Claim

本证据支持一个负向验收结论：F025 当前 browser-use 录制入口已经能进入真实 Recorder UI 主链路，但尚未满足业务矩阵 POC 的完成标准。

本次验收覆盖 ScienceClaw 真实录制页、真实后端、local Playwright 录制浏览器、browser-use CDP 复用、OpenAI-compatible Qwen 模型配置、自然语言录制入口和 session trace timeline。测试页面本身可被 Playwright 直控完成，但通过 ScienceClaw 录制页的 browser-use 自然语言入口执行时，当前集成链路没有完成业务矩阵。

2026-07-05 纠正复测进一步发现：在真实业务话术逐步输入、中文编码已验证无乱码的情况下，前 3 个步骤可以完成并写入 browser-use trace；但从第 4 步开始模型接口返回 `insufficient_quota`，ScienceClaw 仍把失败的 browser-use history 记录成 accepted trace，且 diagnostics 为 0。这说明当前最大风险已经从“无法生成 trace”升级为“失败会被包装成成功 trace”，会直接污染后续 Skill 编译输入。

## Verification Scope

- ScienceClaw 前端：`http://127.0.0.1:5177/rpa/recorder`
- ScienceClaw 后端：`http://127.0.0.1:9798`
- eval 页面：`http://127.0.0.1:5185/rpa-live-e2e.html`
- eval 页面源码：`rpa-eval-app/frontend/public/rpa-live-e2e.html`
- 模型配置：`model_name=qwen3.6-max-preview`
- 录制模式：`RPA_RECORDING_OPERATOR=browser_use`
- 存储/浏览器模式：`STORAGE_BACKEND=local`

覆盖的业务矩阵：

- 登录后页面操作
- iframe 内操作
- 表格搜索、筛选、点击行内按钮
- 弹窗、抽屉、下拉树
- 文件上传、下载
- 分页数据提取
- 多标签页
- 日期控件
- 富文本、复杂组件

页面自校验目标为所有状态均显示 `PASS`，最终摘要显示 `ALL_SCENARIOS_PASS`。

## Checks

1. 启动 ScienceClaw 后端、前端和 eval 静态页面服务。
2. 打开真实 RecorderPage：`http://127.0.0.1:5177/rpa/recorder`。
3. 通过 RPA session API 导航当前录制浏览器到 eval 页面。
4. 通过 RecorderPage 右侧自然语言输入框提交完整业务矩阵指令。
5. 轮询 `/api/v1/rpa/session/{session_id}`，等待新增 accepted trace 或 diagnostic。
6. 用分组自然语言指令重复验证第一组业务能力。
7. 读取后端 browser-use 日志，确认失败阶段和失败原因。

## Results

### 纠正复测：真实业务话术逐步输入

针对前一次 UI 截图中自然语言输入显示为 `????` 且任务长时间不结束的问题，重新编写 UTF-8 Python live UI 脚本，避免 PowerShell stdin/here-string 导致中文乱码。脚本在每次提交前读取 RecorderPage textarea，并断言输入值与原始中文指令完全一致。

- Session：`8a931a2a-2eaf-4ca0-8e20-cb5410763135`
- 脚本：`.tmp/run_business_live_ui_e2e.py`
- 结果文件：`.tmp/rpa-live-ui-business-utterances-result-v2.json`
- 中文输入验证：13/13 条 `composer_verified=true`
- 会话结果：`trace_count=14`，`diagnostic_count=0`
- 业务验收结论：失败

实际输入的业务话术：

1. `帮我登录采购验收系统，账号是 buyer，密码是 rpa-2026。`
2. `刷新一下工作台指标。`
3. `在页面里的供应商确认表单中填写验收码 IFRAME-OK，然后确认。`
4. `帮我查询供应商 SUP-2026-002，只看待补充状态的记录，并打开这条记录的详情。`
5. `审批通过这个申请，审批意见填写 agree。`
6. `把采购分类选择为软件服务。`
7. `上传验收附件。`
8. `下载验收报表。`
9. `翻到下一页，并提取当前页的关键数据。`
10. `打开二级验收页面，完成多标签页验收，然后回到主页面。`
11. `把交付日期设置为 2026-07-20 并确认。`
12. `在备注里加粗填写 RPA note，并选择智能验收流程，然后保存。`
13. `检查这次采购验收流程是否都完成了。`

Trace/action 复核：

| 步骤 | 结果 | browser-use evidence |
| --- | --- | --- |
| 登录 | 通过 | `7 actions`，`done=1`，`success=1`，页面标题 `RPA Live E2E Matrix 1/13` |
| 刷新工作台指标 | 通过 | `3 actions`，`done=1`，`success=1` |
| 页面内供应商确认表单 | 通过 | `4 actions`，`done=1`，`success=1`，包含 `iframe PASS` |
| 表格搜索筛选详情 | 失败 | `3 actions`，`errors=6`，`done=0`，`success=0`，页面标题回到 `0/13` |
| 审批弹窗 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 抽屉树 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 上传 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 下载 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 分页提取 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 多标签页 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 日期控件 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 富文本/复杂组件 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |
| 最终检查 | 失败 | `1 action`，`errors=6`，`done=0`，`success=0` |

第 4 步及之后的 browser-use `action_results` 中出现：

```text
Error code: 403 ... type: insufficient_quota, code: insufficient_quota
```

但 ScienceClaw session 仍显示 `diagnostic_count=0`，并持续新增 `source=browser_use`、`trace_type=ai_operation` 的 trace。这是本次复测发现的关键缺陷：`BrowserUseRecordingOperator` 或上层接纳逻辑没有把 browser-use 的错误 history 转为诊断/失败状态，反而生成了可被下游 Skill 编译消费的失败 trace。

### 页面自检

先用 Playwright 直控 eval 页面完成全矩阵，确认测试页面不是阻塞源。

结果：通过。

关键输出：

```json
{
  "summary": "ALL_SCENARIOS_PASS",
  "badges": [
    "登录: PASS",
    "登录后页面: PASS",
    "iframe: PASS",
    "表格: PASS",
    "弹窗: PASS",
    "抽屉树: PASS",
    "上传: PASS",
    "下载: PASS",
    "分页提取: PASS",
    "多标签页: PASS",
    "日期: PASS",
    "富文本: PASS",
    "复杂组件: PASS"
  ]
}
```

### 单条完整自然语言指令

通过 RecorderPage 真实 UI 启动录制会话，导航到 eval 页面后，提交一条完整业务矩阵自然语言指令。

- Session：`17a44a76-a9d0-40d6-a9d4-4693b069c290`
- 结果：失败
- ScienceClaw session：
  - `trace_count=1`
  - `diagnostic_count=1`
  - 仅包含手工导航 trace
  - browser-use 诊断：`browser-use reported task failure.`

browser-use 后端日志显示：只完成登录；登录后在寻找 `Refresh dashboard metrics` 时陷入滚动方向循环，耗尽 `35` 步预算。过程中还出现了无效 action schema，例如 `evaluate.script`、`search_page.query`，与当前 browser-use 动作模型要求不匹配。

### 分组自然语言指令

为贴近短期“单步指令验证能力”的使用方式，又启动一个新的 RecorderPage live UI 会话，将矩阵拆成三组自然语言指令。

- Session：`20b34853-b5b3-4b89-b06b-8b8e4860b329`
- 第一组：登录、刷新指标、iframe、表格搜索筛选、行内详情
- 结果：失败
- ScienceClaw session：
  - `trace_count=1`
  - `diagnostic_count=1`
  - 仅包含手工导航 trace
  - browser-use 诊断：`browser-use reported task failure.`

后端日志显示：第一组仍只完成登录，随后在刷新指标按钮定位上陷入滚动方向循环，未进入 iframe 和表格操作。因此第二组、第三组没有继续执行。

## Limitations

当前链路没有满足这次业务矩阵 POC 的两个核心目标：

- 录制时完成业务操作：失败，纠正复测只稳定完成登录、刷新指标和页面内供应商确认表单。
- 生成可回放 Skill 所需 Trace：失败，虽然生成了 browser-use trace，但第 4 步之后包含 LLM quota 错误且无 `done/success`，不应被视为可编译的有效业务 trace。

Skill 编译和回放没有继续执行，因为当前 trace timeline 已被失败 trace 污染，继续编译只会验证错误输入的后续表现，不能证明业务可回放能力。

## Notes

1. browser-use 在该页面上存在滚动方向/视口恢复问题。目标位于当前视口上方时，多次执行向下滚动，无法回到目标区域。
2. 当前模型输出过 browser-use 不接受的动作 schema，例如 `search_page.query` 和 `evaluate.script`，而当前动作模型要求 `search_page.pattern`、`evaluate.code`。
3. ScienceClaw 适配器在 browser-use 失败时只写入一句诊断，未把 browser-use 的 action history、final result、失败步骤摘要写入 `RPATraceDiagnostic.raw`，导致前端和 session API 侧缺少足够的失败证据。
4. 系统模型实际 `model_name` 已是 `qwen3.6-max-preview`，但本地模型展示名曾显示为 `DeepSeek V3.2`，容易造成验收误判。已修正展示名/供应商。
5. 纠正复测显示，模型 quota/error 场景比普通 browser-use task failure 更危险：错误被保存在 `signals.browser_use.action_results`，但没有提升为 session diagnostic，也没有阻止 accepted trace 生成。

## Artifacts

- 完整单条指令结果：`.tmp/rpa-live-ui-matrix-result-3.json`
- 分组指令结果：`.tmp/rpa-live-ui-batch-result.json`
- 纠正复测脚本：`.tmp/run_business_live_ui_e2e.py`
- 纠正复测结果：`.tmp/rpa-live-ui-business-utterances-result-v2.json`
- 后端日志：`.codex-live-backend-9798.err.log`
- 静态 eval 服务日志：`.codex-eval-static-5185.out.log`

下一步建议：

优先不要继续扩大业务代码，而是补强 F025 的 Harness：

- 将 browser-use 失败 history 写入 `RPATraceDiagnostic.raw`。
- 当 browser-use `action_results` 含 error、无 `is_done/success`，或只有初始 navigate 时，禁止生成 accepted trace。
- 增加最小 live UI 断言脚本，固定验证“产生 browser-use accepted trace”与“页面最终 PASS 状态”两个结果。
- 针对滚动方向循环增加复现用例，判断是 browser-use 动作模型、页面可访问性、还是当前 prompt/模型 schema 对齐问题。
- 再分别验证 `qwen3.6-max-preview` 与 `qwen3.6-35b-a3b` 的 browser-use action schema 合规率。
