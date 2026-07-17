---
id: EV-027
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
created: 2026-07-17
updated: 2026-07-17
evidence_level: exhaustive
---

# EV-027：首个 RPA Agent 浏览器 E2E 的 eval-app 测评环境

## Supports Claim

本证据只支持以下有限完成声明：首个 RPA Agent E2E 所需的 eval-app 测评环境已经准备好。

它不证明 CoreTrace、录制/对话采集、编译、SKILL 生成或回放链路已经实现，也不证明“RPA Agent 首个 E2E 已经通过”。

## Verification Scope

- `case_a`、`case_b` 两套可重置且互相隔离的 Fixture Profile。
- 系统 A 的多条件后端查询、同名行内按钮和随机验收任务 URL。
- `task_id + token` 匹配校验、非法 token 拒绝和重复保存拒绝策略。
- 系统 B 宿主页的非业务 iframe、延迟业务 iframe，以及业务 iframe 内的完整验收表单。
- 后端真实保存、受 reset token 保护的 Oracle 精确断言。
- 旧默认 reset、旧鉴权、旧 eval client 和旧 Runner 边界不回归。
- 前端 TypeScript 检查、生产构建和真实浏览器交互。

## Checks

```powershell
Set-Location rpa-eval-app\backend
python -m unittest discover -s . -p 'test*.py' -v
```

结果：`13 tests`，全部通过。

```powershell
Set-Location rpa-eval-app\evals
python -m unittest discover -s . -p 'test*.py' -v
```

结果：`28 tests`，全部通过。

```powershell
Set-Location rpa-eval-app\frontend
npm.cmd run build
```

结果：`vue-tsc -b` 与 Vite 生产构建通过，共转换 `1691 modules`；仅有构建产物大于 500 kB 的提示。

```powershell
python -c "import pathlib, yaml; yaml.safe_load(pathlib.Path('rpa-eval-app/evals/contracts/rpa_agent_first_browser_e2e.yaml').read_text(encoding='utf-8')); print('contract-ok')"
git diff --check
```

结果：场景契约解析成功；diff 检查通过。Git 仅提示该 Windows worktree 后续可能进行 LF/CRLF 转换。

## Results

### Profile A

- reset 后结果表包含 3 条可见干扰记录，目标订单 `PO-2026-05017` 位于第一行。
- 实际操作了业务类型自定义下拉、日期范围、供应商和订单编号过滤；目标订单可被精确筛出。
- 点击目标行同名“发起验收”入口后，后端生成运行时随机任务；验收宿主页 URL 含随机 `task_id` 与 token。
- 宿主页初始只有非业务 iframe，约 900ms 后出现 `title="验收登记表单"`、`name="acceptance-form"` 的业务 iframe。
- 在业务 iframe 中填写并保存 CNY 验收记录；DOM 确认弹窗与成功状态出现。
- Oracle 返回订单、供应商、合同、金额 `128600.50`、币种 `CNY`、日期、备注“自动创建”、确认状态和关联 task_id，全部与预期一致。

### Profile B

- reset 后结果表包含 3 条可见干扰记录，目标订单 `PO-2026-06042` 位于第三行。
- 实际通过业务类型、日期范围和供应商条件查询，未使用固定行号作为目标识别依据。
- 生成的 task_id/token 与 Profile A 不同；错误 token 携带合法登录态访问仍返回 `403`。
- 真实浏览器确认了非业务 iframe 先出现、业务 iframe 延迟出现且可由稳定 title/name 定位；审查后的最新契约进一步通过后端红绿测试确认 B 加载 2 个非业务 iframe、业务 frame ordinal 为 2，与 A 不同。
- 在业务 iframe 中填写并保存 USD 验收记录；DOM 确认弹窗与成功状态出现。
- Oracle 返回金额 `10150.75`、币种 `USD` 及其余字段，全部与预期一致。

## Independent Review

独立审查复跑了后端、eval client 和前端构建，并检查了原生 `<a target="_blank">` 启动页链路、登录态复用、随机任务创建、token 校验、重复保存和 Oracle 保护。审查指出业务 iframe 原先在 A/B 中序位固定；修复后新增后端红绿测试锁定 A 的非业务 frame 数为 1、B 为 2，前端按任务契约渲染，再由 TypeScript 与生产构建验证。两个独立子会话均能初始化浏览器控制运行时，但都没有可选择的实际浏览器实例，因此不能额外录制一次“最新代码点击后枚举新标签页与变序 frame”的独立证据。

## Acceptance Mapping

| 验收项 | 证据 | 状态 |
| --- | --- | --- |
| Profile A/B 可重置、目标行位置不同、数据隔离 | 后端测试与真实浏览器结果 | pass |
| 多条件查询由后端真实过滤 | API 测试与真实浏览器查询 | pass |
| task/token 随机且必须匹配 | 后端测试、浏览器运行时 URL、非法 token `403` | pass |
| 多 iframe、延迟业务 iframe、跨 Profile 变更 ordinal、稳定 title/name | Profile A/B 浏览器结果、后端 ordinal 测试与前端构建 | pass |
| 真实保存、重复保存确定拒绝 | 后端测试、真实浏览器保存、Oracle | pass |
| Oracle 受 reset token 保护且字段完整 | 后端测试与 Profile A/B Oracle | pass |
| 旧 reset、旧鉴权、旧 Runner 边界不回归 | 后端/evals 全量测试、契约位于 `evals/contracts` | pass |
| 当前原生入口点击后的新标签枚举 | 源码/API 独立审查；独立浏览器不可用 | limited |

## Artifacts

- 实现说明：`rpa-eval-app/IMPLEMENTATION_FIRST_BROWSER_E2E.md`
- 场景契约：`rpa-eval-app/evals/contracts/rpa_agent_first_browser_e2e.yaml`
- 后端测试：`rpa-eval-app/backend/test_first_browser_e2e.py`
- eval client 测试：`rpa-eval-app/evals/test_eval_app_client.py`
- Feature：`docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md`

## Limitations

- 本次没有连接真实 LLM 或外部网络。
- 没有新增前端自动化测试框架；前端证据由构建、真实浏览器操作和后端 Oracle 共同形成。
- 主会话的应用内浏览器工具不能枚举点击产生的 popup，两个独立审查会话又没有可选择的浏览器实例；当前原生 `target="_blank"` 入口的最后一跳以源码/API 审查为补充证据。
- 跨 Profile frame ordinal 变更是在真实浏览器 A/B 表单验证后按独立审查意见补强的；它有失败先行的后端契约测试和最新前端构建证据，但没有新增一轮浏览器截图/枚举证据。
- CoreTrace、录制器、Browser-use Adapter、编译器、SKILL 生成器和 RPA Agent 前端均不在本次范围内。

## Notes

严格知识校验器能够识别本 Evidence 和 F026，但仓库中大量历史 ADR、Evidence、Feature 尚未迁移到当前模板，且不存在 `docs/features/INDEX.md`；因此全库 strict/index 校验仍被这些既有文档问题阻塞。本次没有借机批量改写无关历史文档。
