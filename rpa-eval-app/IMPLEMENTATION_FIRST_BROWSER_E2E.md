# 首个 RPA Agent 浏览器 E2E 测评环境实现说明

## 范围

本实现只建设 `rpa-eval-app` 的可控业务环境，不包含 CoreTrace、录制器、Browser-use Adapter、编译器、SKILL 生成器或 RPA Agent 前端，也不接入旧 `evals/cases` Runner。

## 页面入口

- 系统 A 采购订单综合查询：`http://localhost:5175/system-a/orders`
- 系统 B 验收宿主页：系统 A 通过原生新标签链接打开同源 launch 页，launch 页复用登录态创建任务后替换为 `/system-b/acceptance/{task_id}?token={token}`
- 系统 B iframe 表单：宿主页延迟加载 `/system-b/acceptance-frame/{task_id}?token={token}`

系统 B 宿主页先加载非业务 iframe，再延迟约 900ms 加载业务 iframe。`case_a` 有 1 个非业务 iframe，业务 frame ordinal 为 1；`case_b` 有 2 个非业务 iframe，业务 frame ordinal 为 2，固定 `frames[1]` 不能跨 Profile 工作。业务 iframe 的稳定身份是 `title="验收登记表单"` 和 `name="acceptance-form"`。

## API 入口

业务 API 均复用现有 Bearer 登录态：

- `GET /api/acceptance/orders`：按 `business_type`、`date_from`、`date_to`、`supplier_name`、`order_no` 组合过滤。
- `POST /api/acceptance/orders/{order_no}/tasks`：创建随机 `task_id`、随机 token 和宿主页地址。
- `GET /api/acceptance/tasks/{task_id}?token=...`：校验 task/token 后返回任务和源订单。
- `POST /api/acceptance/tasks/{task_id}/records?token=...`：创建真实验收登记。一个 task 只允许保存一次，重复保存返回 HTTP 409。

## Fixture Profile

重置请求继续使用 `X-RPA-Eval-Reset-Token`：

```powershell
$headers = @{ "X-RPA-Eval-Reset-Token" = $env:RPA_EVAL_RESET_TOKEN }
Invoke-RestMethod -Method POST -Uri "http://localhost:8085/api/eval/reset?profile=case_a" -Headers $headers
Invoke-RestMethod -Method POST -Uri "http://localhost:8085/api/eval/reset?profile=case_b" -Headers $headers
```

不传 `profile` 时执行原有默认重置。未知 Profile 返回 HTTP 400，且在校验失败前不会重建数据库。

- `case_a`：目标 `PO-2026-05017`，在宽查询结果第一行，金额 `128600.50 CNY`。
- `case_b`：目标 `PO-2026-06042`，在宽查询结果第三行，金额 `10150.75 USD`。

两套 Profile 都包含三条同业务类型、日期范围和供应商的订单，使查询后同时存在三个同名“发起验收”按钮。订单编号精确过滤仍由后端执行；场景契约的宽查询刻意不填订单编号，以保留行上下文和同名按钮抗硬编码条件。

`EvalAppClient.reset(reset_token, profile=None)` 支持同一 Profile 参数；旧 Runner 不传参数，行为不变。

## Oracle

Oracle 只供测评 Harness 使用，页面代码不调用：

```powershell
Invoke-RestMethod `
  -Method GET `
  -Uri "http://localhost:8085/api/eval/oracle/acceptance?task_id=<runtime-task-id>" `
  -Headers $headers
```

接口返回订单编号、供应商、合同编号、Decimal 金额、币种、日期、备注、确认状态、关联 task_id 和创建时间。缺失或错误 reset token 会被拒绝。

## 启动与测试

后端：

```powershell
cd rpa-eval-app/backend
$env:RPA_EVAL_RESET_TOKEN = "your-reset-token"
python -m uvicorn main:app --host 127.0.0.1 --port 8085
```

前端：

```powershell
cd rpa-eval-app/frontend
npm.cmd ci
npm.cmd run dev
```

自动化验证：

```powershell
cd rpa-eval-app/backend
python -m unittest discover -s . -p "test*.py" -v

cd ../evals
python -m unittest discover -s . -p "test*.py" -v

cd ../frontend
npm.cmd run build
```

## 场景契约

完整契约位于 `evals/contracts/rpa_agent_first_browser_e2e.yaml`。它不会被旧 Runner 的 `--all` 收集。

## 已验证内容

- Profile A/B 与默认 reset、后端组合过滤、目标行顺序。
- task/token 每次随机、合法匹配和非法 token 拒绝。
- A/B 的业务 iframe ordinal 不同，且业务 iframe 只能通过稳定 title/name 跨 Profile 定位。
- 真实验收记录保存、HTTP 409 重复策略、受保护 Oracle 和 Profile 数据隔离。
- TypeScript 检查、生产构建，以及 Profile A/B 的真实浏览器流程。

## 尚未覆盖

- 没有执行 RPA Agent 录制、CoreTrace、编译、SKILL 生成或回放。
- 没有引入跨域 iframe、原生浏览器弹窗、文件上传下载或 DataAsset。
- 项目当前没有前端自动化测试框架；前端证据由严格构建和真实浏览器验证组成。
