# AIO Native Runtime Provider 本地验证说明

## 背景

原有 `aio_fixed` / `aio` 路线假设 AIO 沙箱内运行 RpaClaw Runtime Adapter 服务，Host Backend 通过 adapter semantic API 访问浏览器、文件、脚本执行和诊断能力。实际验证 `agent-infra/sandbox` 后，AIO 原生 API 已能直接提供 `/v1/browser/info`、CDP、VNC、文件与代码执行等能力。因此本地验证 RPA 录制主链路时，可以先走更短路径：Host Backend 直接连接固定原生 AIO 沙箱，不要求沙箱内启动 Runtime Adapter。

该模式用于验证“现有技能录制产品链路能否把执行面从本机 browser 切换到 AIO browser”，不是验证真实内网 AIO create/status/delete 生命周期。

## 使用方式

先启动一个本机 AIO sandbox，例如：

```powershell
docker run -d --security-opt seccomp=unconfined --name aio-native-manual -p 18090:8080 enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
```

然后启动 Host Backend 时配置：

```powershell
$env:STORAGE_BACKEND = "local"
$env:RUNTIME_MODE = "aio_native"
$env:AIO_BASE_URL = "http://127.0.0.1:18090"
$env:AIO_RUNTIME_SANDBOX_ID = "aio-native-manual"
```

`AIO_BASE_URL` 也可以写作 `AIO_NATIVE_BASE_URL`。`RUNTIME_MODE=aio_native` 会优先于 `STORAGE_BACKEND=local`，使 RPA CDP connector 连接 AIO sandbox，而不是启动本机 Chromium。

## 当前实现边界

`AioNativeRuntimeProvider` 返回固定 `SessionRuntimeRecord`：

- `namespace=aio-native`
- `rest_base_url` / `route_base_url` 指向 `AIO_BASE_URL`
- `sandbox_id` 来自 `AIO_RUNTIME_SANDBOX_ID`，未配置时使用本地默认值
- `refresh_runtime()` 调用 `{AIO_BASE_URL}/v1/browser/info`
- `browser_view_url` 从 AIO 返回的 `vnc_url` 归一化为 Host 可访问地址
- metadata 仅记录 `runtime_contract=aio_native`、`browser_info_ok`、`cdp_url_available` 等非敏感诊断

该 provider 不创建、不销毁 AIO sandbox，也不调用 adapter `/health`。

如果配置了真实内网生命周期 API，`AioNativeRuntimeProvider` 会从本地固定沙箱模式切换为真实 lifecycle 模式：

```powershell
$env:RUNTIME_MODE = "aio_native"
$env:AIO_NATIVE_CREATE_URL = "http://apigw-beta.huawei.com/api/livefunction/sandboxes"
$env:AIO_NATIVE_STATUS_URL_TEMPLATE = "http://apigw-beta.huawei.com/api/livefunction/sandboxes/{sandbox_id}"
$env:AIO_NATIVE_DELETE_URL_TEMPLATE = "http://apigw-beta.huawei.com/api/livefunction/sandboxes/{sandbox_id}"
$env:AIO_NATIVE_REFRESH_URL_TEMPLATE = "http://apigw-beta.huawei.com/api/livefunction/sandboxes/refresh/{sandbox_id}"
$env:AIO_NATIVE_HW_ID = "com.huawei.pass.roma.event"
$env:AIO_NATIVE_APPKEY = "<configured-appkey>"
$env:AIO_NATIVE_TEMPLATE_ID = "lf-6eff9409b0d85f3d3e079501e975e28c"
$env:AIO_NATIVE_CREATE_TIMEOUT_SECONDS = "600"
$env:AIO_NATIVE_REFRESH_DURATION_SECONDS = "300"
$env:AIO_BASE_URL = "http://apigw-beta.huawei.com/api/rpa-sandbox"
```

默认生命周期路径为：

- create: `POST /api/livefunction/sandboxes`
- status: `GET /api/livefunction/sandboxes/{sandbox_id}`
- refresh: `POST /api/livefunction/sandboxes/refresh/{sandbox_id}`
- delete: `DELETE /api/livefunction/sandboxes/{sandbox_id}`

也可以继续使用 `AIO_NATIVE_API_BASE_URL` + path/template 形式；如果配置了 `AIO_NATIVE_CREATE_URL` 等完整 URL，provider 会优先使用完整 URL。

真实 lifecycle 模式下，create payload 包含 AIO 模板和沙箱超时时间：

```json
{"templateId": "lf-6eff9409b0d85f3d3e079501e975e28c", "timeout": 600}
```

Host 会把 AIO 返回的 `data.sandboxId`、`data.templateId`、`data.status`、`data.cpu`、`data.memory`、`data.timeout`、`data.startAt`、`data.endAt` 映射到 `SessionRuntimeRecord` 和脱敏 metadata。`running` 映射为 `ready`，`stopped/error/404` 映射为 `missing`。

生命周期 API 会发送 `X-HW-ID` / `X-HW-APPKEY`。沙箱内部 API 会继续发送这两个 header，并额外发送 `x-livefunction-sandbox-id={sandboxId}`；该 `sandboxId` 来自 create/status 响应，只保存非敏感 ID，不把 `X-HW-APPKEY` 写入 runtime metadata。

`AIO_BASE_URL` / `AIO_NATIVE_BASE_URL` 指向沙箱内部 API 前缀，例如 `http://apigw-beta.huawei.com/api/rpa-sandbox`。如果内网后续暴露的是包含 `{sandbox_id}` 的 route 模板，也可以把 `{sandbox_id}` 写入该 URL。低层 URL 拼接应留在 provider/CDP connector 层，不要散落到 RPA recorder、Skill compiler 或前端。

## 待产品级验证

该模式接入后，优先验证：

1. 手动点击/输入是否经现有 recorder bridge 生成 accepted trace。
2. `framenavigated`、下载、新标签页、iframe 归因是否与本机 CDP 模式一致。
3. 自然语言操作是否能在 AIO page 上完成 snapshot、planner、executor、repair 和 accepted trace。
4. 区域选择的前端画布坐标、后端 `element-bounds`、`region/analyze` 与 region-scoped natural language 是否对齐。
5. trace 编译后的 Skill 是否能在 AIO browser 上回放。

如果这些产品能力都成立，内网优先适配 AIO 原生 API；Runtime Adapter 保留为原生 API 缺口出现时的第二阶段方案。
