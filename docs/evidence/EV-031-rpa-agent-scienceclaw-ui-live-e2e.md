---
id: EV-031
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
created: 2026-07-19
---

# EV-031：RPA Agent ScienceClaw 录制 UI 与真实 Live E2E

## Supports Claim

本证据支撑 F026.3：新版 RPA Agent 在保留 ScienceClaw 录制交互壳层的前提下，能够在 Windows 本地非 Docker 模式使用真实 Qwen 模型和真实 browser-use 完成 GitHub Trending 录制、配置、编译、回放与保存闭环。

## Verification Scope

覆盖 Recorder 的流程导航、左侧步骤时间线、中部实时浏览器、右侧 AI 对话与模型选择；覆盖停止录制后的双栏 Configure；覆盖模型结果回显、停止期间投影竞态、四文件产物本地导入、真实回放和保存。未验证 Docker/VNC 模式，也未把一次 GitHub 结果外推为所有网站和所有模型的语义稳定性。

## Checks

```text
# 前端定向回归
cd RpaClaw/frontend
npm.cmd run test -- --run src/api/rpaAgent.test.ts src/pages/rpa/RecorderPage.test.ts src/pages/rpa/ConfigurePage.test.ts src/components/rpa/RpaStepTimeline.test.ts

# 前端生产构建
cd RpaClaw/frontend
npm.cmd run build

# 后端录制、停止投影、本地生成包加载和路由回归
$env:PYTHONPATH='RpaClaw'
.\.venv\Scripts\python.exe -m pytest RpaClaw\backend\tests\rpa_agent\test_browser_use_host.py RpaClaw\backend\tests\rpa_agent\test_route.py::test_agent_instruction_preserves_selected_model_id_for_host_executor RpaClaw\backend\tests\rpa_agent\test_route.py::test_stop_draft_is_derived_from_exact_timeline_binding_locations RpaClaw\backend\tests\rpa_agent\test_default_host_services.py -q --basetemp=E:\RPA-Agent\ScienceClaw\.pytest-tmp-f0263-final2

# 本地服务（非 Docker）
$env:PYTHONPATH='RpaClaw'
$env:DS_MODEL='qwen3.7-plus-2026-05-26'
python -m uvicorn backend.main:app --app-dir .\RpaClaw --host 127.0.0.1 --port 12001
npm.cmd run dev -- --host 127.0.0.1 --port 5177

# Live UI 指令
打开 GitHub Trending 页面
打开和skill最相关的项目
获取star数
```

## Results

- Pass：前端 4 个测试文件、14 条测试全部通过；其中包括 ScienceClaw 三栏壳层、模型选择、对话结果、停止期间投影竞态和 Configure 双栏契约。
- Pass：后端 28 条测试通过，1 条按环境条件跳过；停止响应携带服务端最终步骤投影，生成包在官方 `backend.main` 本地启动方式下保持 `SkillRunResult` 类型一致。
- Pass：Vite 生产构建完成，5323 个模块成功转换。仅出现仓库既有的重复 CSS key、CSS 语法和大 chunk 告警。
- Pass：真实 browser-use 日志明确记录 `provider=openai`、`model=qwen3.7-plus-2026-05-26`，不是测试替身或 scripted model。
- Pass：Live UI 从 GitHub Trending 选择 `ibelick/ui-skills`，随后在助手对话区返回精确实时结果 `5,239 stars`；模型自然语言结果与本次记录步骤数同时显示。
- Pass：录制停止后进入原有双栏 Configure；在加载最新停止投影实现后的独立干净会话中，Configure 显示 1 条实际导航步骤，不再因轮询/停止竞态变成 0 步。
- Pass：生成四文件产物的 Artifact hash 为 `d38fcbf50e8d83edfa198cd6749baba2ec9687e99a42247252596fe581ccb21a`，UI 回放显示 `运行结果：succeeded`。
- Pass：`POST /api/v1/rpa-agent/sessions/rca_1fbc8b34e0eb10d347b37fe0/save` 返回 `200 OK`，Skill 保存到 `Skills/skill_1fbc8b34e0eb10d347b37fe0/`。

## Artifacts

- [F026 Feature 与 F026.3 Patch History](../features/F026-rpa-agent-scienceclaw-host-rebuild.md)
- [LL-003 宿主 UI 契约回归保护](../lessons/LL-003-rpa-host-ui-regression-contract-e2e.md)
- `RpaClaw/backend/.rpa-agent-artifacts/rca_1fbc8b34e0eb10d347b37fe0/`
- `Skills/skill_1fbc8b34e0eb10d347b37fe0/`
- `.codex-f0263-backend-final.out.log`
- `.codex-f0263-backend-final.err.log`
- `.codex-f0263-backend-latest.out.log`
- `.codex-f0263-backend-latest.err.log`

## Limitations

- GitHub Trending 与 Star 数是实时外部状态，后续复跑数值变化不代表回归。
- browser-use 内置 judge 曾因点击动作返回 `semantic_target_not_unique` 而给出失败判断；实际浏览器 URL 已进入 `https://github.com/ibelick/ui-skills`，后一条独立真实指令也从该页面读取到精确 Star 数。该现象说明模型内部 judge/语义证据仍有可提升空间，但不否定本次 UI、浏览器状态和录制闭环证据。
- 本证据按用户要求不覆盖 Docker 模式；不证明完整 DataAsset、分页循环、阶段二处理或任意网站泛化能力。
- 未用全仓 `vue-tsc --noEmit` 作为完成门槛；仓库存在与本次文件无关的既有类型错误，本次以定向测试和成功生产构建为准。

## Notes

本轮恢复的是 ScienceClaw 产品交互壳层，底层仍只调用新版 `/api/v1/rpa-agent`、Candidate/CoreTrace 投影和新 Compiler；没有恢复旧 Trace、旧 Compiler 或双轨兼容层。真实模型首次调用可能超过通用 HTTP 30 秒，因此 Agent 指令使用独立 180 秒超时，而普通 API 仍保留原通用超时。
