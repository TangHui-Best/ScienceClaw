---
id: EV-042
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F032-rpa-agent-next-architecture.md
created: 2026-08-02
---

# EV-042：RPA Agent Next S5 Docker 组合根

## Scope

当 `RPA_AGENT_NEXT_RUNTIME_MODE=docker` 显式启用时，RPA Agent Next 可通过既有端侧 Docker Runtime 创建和销毁 session runtime，并从该 runtime 的 CDP 建立新的 BrowserHost context；默认配置仍 fail-closed。

验证范围：vNext Docker adapter 的 ownership、health、release、CDP 解析和 Host 创建边界；Next 默认组合根只在显式 docker mode 启用；未破坏 S0–S4 和既有 RPA 测试。

## Commands

```text
cd RpaClaw/backend
python -m pytest tests/rpa_agent_next/test_s5_docker_runtime_composition.py -q --basetemp .pytest-tmp-s5-rerun3-20260802
python -m pytest tests/rpa_agent_next -q --basetemp .pytest-tmp-s5-next-full-20260802
python -m pytest tests/rpa_agent -q --basetemp .pytest-tmp-s5-rpa-full-20260802
cd ..
RPA_AGENT_NEXT_RUNTIME_MODE=docker python -c "from backend.route.rpa_agent_next import rpa_agent_next_default_services as services; assert type(services.runtime_provider).__name__ == 'DockerRuntimeProvider'; assert type(services.host_factory).__name__ == 'DockerBrowserHostFactory'; print('docker-next-composition-imports')"
docker version --format '{{.Server.Version}}'
docker image inspect rpaclaw-sandbox:local --format '{{.Id}}'
docker network inspect rpaclaw_default --format '{{.Id}}'
docker compose -f docker-compose.yml -f docker-compose-edge-runtime.yml config
docker compose -f docker-compose.yml -f docker-compose-edge-runtime.yml up -d --build backend
docker compose -f docker-compose.yml -f docker-compose-edge-runtime.yml exec -T backend python backend/scripts/smoke_rpa_agent_next_docker.py
git -C E:\RPA-Agent\browser-use rev-parse HEAD
Get-Content E:\RPA-Agent\browser-use\pyproject.toml | Select-Object -First 38
```

## Results

Pass（deterministic）：S5 3 passed；Next 49 passed；既有 RPA 500 passed、2 skipped；显式 docker mode 可从真实应用 import 并构造 Docker provider/host factory。三份 Compose 文件均已将默认网络和 `DOCKER_RUNTIME_NETWORK` 收敛为 `rpaclaw_default`；`docker-compose-edge-runtime.yml` 只在显式端侧模式下启用 Next Docker route 并挂载 Docker socket。

Pass（live Docker）：Docker daemon 为 29.1.3，`rpaclaw_default` 已由 Compose 创建，基准 sandbox 健康。`docker compose ... build backend` 成功从仓库内 `vendor/sciclaw-browser-use` 构建并安装 `browser-use-0.13.2+sciclaw.1`；容器内实际读取到该分发版本并可 `import backend.main`。`smoke_rpa_agent_next_docker.py` 成功创建临时 session container，完成 HTTP readiness、CDP 解析、Playwright CDP 连接、新建 context/page，并在结束后释放 browser context 与 session container（`RPA_AGENT_NEXT_DOCKER_SMOKE=passed`、`RPA_AGENT_NEXT_DOCKER_RELEASE=passed`）。真实 AIO 返回的 CDP 路径为 `/cdp/devtools/browser/...`，已作为受限的反向代理路径显式兼容；无 Docker HEALTHCHECK 的 runtime 在通过创建期 HTTP readiness probe 后会保持 ready，不再被一次刷新错误降级为 `running`。backend image 原本因 PyPI 缺少 `browser-use==0.13.2` 失败；对 PyPI 0.13.1/0.13.3/0.13.7 的小版本升级试验虽通过 129 个宿主边界回归，但完整 resolver 均被其 `anthropic==0.76.0` 与项目 `deepagents → langchain-anthropic` 的 `anthropic>=0.78` 冲突阻断，故已撤回。审计固定的 0.13.2 源码提交 `2454d3e2551705232333c906ded8fc31ab0fc9f2` 的 `pyproject.toml` 后，确认它同样强制 `anthropic==0.76.0` 和 `python-dotenv==1.2.2`；因此 Git URL 只会重现同一 resolver 失败，未写入 requirements。用户已确认实际模型均为 OpenAI-compatible，故当前交付使用受控兼容制品和 Next 专属适配层；不以独立 Browser-use runtime 作为 F032 第一阶段替代。

## AgentMentor Validation

执行 `python C:\Users\HUAWEI\.codex\plugins\cache\personal\agentmentor\0.2.0+codex.20260604093000\skills\using-agentmentor\scripts\knowledge_check.py --root E:\RPA-Agent\ScienceClaw-rpa-agent-next --docs-path docs --strict`。检查正确识别出本 Evidence 及 F032 的旧章节名问题，已在本次修正；剩余失败均为本次范围外的历史文档债务（ADR-005 至 ADR-008、EV-025 至 EV-041、F025、LL-003 至 LL-004）。

## Artifacts

- `RpaClaw/backend/runtime/rpa_agent_next_docker_provider.py`
- `RpaClaw/backend/rpa_agent/platform/docker_browser_host.py`
- `RpaClaw/backend/route/rpa_agent_next.py`
- `RpaClaw/backend/tests/rpa_agent_next/test_s5_docker_runtime_composition.py`
- `docker-compose-edge-runtime.yml`
- `RpaClaw/backend/scripts/smoke_rpa_agent_next_docker.py`
- `RpaClaw/backend/vendor/sciclaw-browser-use/NOTICE.md`
- `RpaClaw/backend/rpa_agent/host/next_browser_use_runtime.py`

## Notes

本 Evidence 不证明 AIO 云端 runtime，也不证明 Browser-use 自然语言任务成功。没有 LLM 时，Browser-use 只能验证受控包、宿主附着、CDP/Playwright 生命周期及错误边界；app-first E2E 评测、Harness capture 持久化和五条能力线的删除证据仍未完成。固定 Git commit 与公开 PyPI 0.13.x 已排除：它们都保留不可共存的依赖锁。当前已决路径是经依赖重基线验证的受控 fork/wheel/私有索引，仅覆盖 OpenAI-compatible Next 运行面；独立 Browser-use runtime 仅在未来另立架构决策后讨论。
