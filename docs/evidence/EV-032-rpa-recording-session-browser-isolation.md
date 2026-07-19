---
id: EV-032
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
created: 2026-07-19
---

# EV-032：RPA 录制会话浏览器隔离

## Supports Claim

本证据支撑 F026.4：新版 RPA Agent 把录制会话作为 Playwright BrowserContext 与 Page 的所有权边界。退出录制、停止录制和重新录制都会释放旧会话资源；后续录制在同一中立 Chromium/CDP 宿主进程内创建全新的 BrowserContext 与 Page，不继承旧会话的 Cookie、Storage、URL、页面或历史状态。

## Verification Scope

覆盖隔离 Context 创建、Preview Registry 注册与释放、停止录制即时释放、退出录制废弃接口、Recorder 卸载清理、连续两次真实本地 Chromium 会话、真实本地 UI 的“退出后再次录制”和“停止后重新录制”两条路径。未覆盖 Docker/VNC 部署，也未重复验证 LLM/browser-use 语义执行质量；后者仍由 EV-031 支撑。

## Checks

```text
# 后端会话生命周期与宿主回归
$env:PYTHONPATH='RpaClaw'
.\.venv\Scripts\python.exe -m pytest RpaClaw\backend\tests\rpa_agent\test_browser_use_host.py RpaClaw\backend\tests\rpa_agent\test_route.py -q --basetemp=E:\RPA-Agent\ScienceClaw\.pytest-tmp-f0264-final
Result: 76 passed

# 真实本地 Chromium：同一 CDP 下连续创建两个录制会话
$env:PYTHONPATH='RpaClaw'
$env:RPA_AGENT_LOCAL_LIVE='1'
.\.venv\Scripts\python.exe -m pytest RpaClaw\backend\tests\rpa_agent\test_local_host_live.py -q -s --basetemp=E:\RPA-Agent\ScienceClaw\.pytest-tmp-f0264-live
Result: 1 passed

# 前端 API、Recorder、Configure 与 Timeline 回归
cd RpaClaw/frontend
npm.cmd run test -- --run src/api/rpaAgent.test.ts src/pages/rpa/RecorderPage.test.ts src/pages/rpa/ConfigurePage.test.ts src/components/rpa/RpaStepTimeline.test.ts
Result: 4 files / 15 tests passed

# 前端生产构建
cd RpaClaw/frontend
npm.cmd run build
Result: pass, 5313 modules transformed

# 本地非 Docker UI
backend: http://127.0.0.1:12002
frontend: http://127.0.0.1:5178
路径一：录制 rca_310fb4b1ad880a16e5b67d24 -> 返回首页 -> DELETE 200 -> 新录制 rca_4243c01a5c6a2609f128b11a
路径二：录制 rca_bdd8f1cb05301d6da6797d71 -> stop 200 -> Configure -> 重新录制 rca_481336314700265a0db91d55 -> 返回首页 -> DELETE 200
```

## Results

- Pass：`isolated_context=True` 强制每次录制调用 `browser.new_context()`；即使 Preview Registry 已有旧 Page，也不会走复用分支。
- Pass：真实 Chromium 验证两个会话使用相同 CDP URL，但 BrowserContext 与 Page 身份均不同；第一个 Page 在停止后已关闭，第二个 Context 查询 `https://isolation.test` 时不包含旧会话写入的 `old_recording` Cookie。
- Pass：停止录制在形成最终创建态投影后立即释放浏览器端口，配置、编译所需的已结算创建态数据仍保留。
- Pass：退出录制调用 `DELETE /api/v1/rpa-agent/sessions/{session_id}`，SessionStore 删除会话并幂等释放监听器、Context 与 Preview Registry。
- Pass：真实 UI 两条路径均产生不同的 `rca_*` 会话，旧会话的 stop/delete 在新会话创建前返回 200。
- Pass：本次独立验收服务只使用 12002/5178，未停止或重启用户已有的 12001 后端；验收结束后仅关闭本次启动的进程。

## Artifacts

- [F026.4 Patch History](../features/F026-rpa-agent-scienceclaw-host-rebuild.md)
- [LL-003 宿主产品契约保护](../lessons/LL-003-rpa-host-ui-regression-contract-e2e.md)
- `RpaClaw/backend/tests/rpa_agent/test_local_host_live.py`
- `.codex-f0264-backend.out.log`
- `.codex-f0264-backend.err.log`

## Limitations

- 本证据证明本地非 Docker 模式的会话隔离与资源释放，不证明容器 runtime 的真实部署状态。
- 底层 Chromium 进程仍可由中立本地 CDP 宿主共享；隔离边界是每录制会话独占的 BrowserContext/Page。强制每次重启 Chromium 进程不会增加 Cookie/Storage 隔离保证，反而会破坏宿主资源复用，因此未采用。
- 本轮没有再次调用真实 LLM；浏览器与 LLM 的真实录制、编译、回放和保存闭环沿用 EV-031，不应把本证据外推为模型语义质量验证。

## Notes

根因由两个缺口共同构成：宿主租约默认选择第一个已有 BrowserContext/Page，停止录制只解除监听而不关闭宿主端口；Recorder 离开页面也没有通知后端废弃会话。修复同时上移到 Context 创建不变量和会话释放 API，避免依赖前端刷新或用户操作顺序兜底。
