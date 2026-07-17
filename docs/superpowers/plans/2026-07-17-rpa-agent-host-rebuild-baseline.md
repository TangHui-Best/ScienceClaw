# [已失效] RPA Agent ScienceClaw 宿主重构基线 Implementation Plan

> 文档状态：已失效，禁止执行（2026-07-17）。
>
> 替代入口：[首个阶段一 E2E 验收场景设计基线](../specs/2026-07-17-RPA-Agent首个阶段一E2E验收场景设计基线.md)。
>
> 失效原因：本计划先从空领域目录、契约搬运和测试护栏出发，没有先用真实业务 E2E 反推共享变量、编译链路和工程边界。用户评审后确定改为“验收场景 -> 最小契约 -> 编译链路 -> eval 测评设计 -> 实施计划”。本文保留为历史记录，其中的测试隔离和依赖护栏任务可被未来场景驱动计划重新吸收，但不能按原顺序执行。

> 以下正文保留原计划内容，仅用于审计当时的任务拆分和被否决顺序，不构成执行指令。

**Goal:** 完成 F026 的增量 0，在不实现 CoreTrace 业务逻辑的前提下，建立新领域目录、正式契约入口、离线测试隔离、旧领域依赖护栏和可重复验证证据。

**Architecture:** ScienceClaw 继续作为宿主，新的生产领域从 `RpaClaw/backend/rpa_agent/` 开始；已确认的 CoreTrace 与创建态上游模型作为仓库内机器契约。旧 `backend/rpa` 仅供阅读，边界由 AST 依赖测试而不是人工约定保证。

**Tech Stack:** Python 3.11+、pytest、JSON Schema Draft 2020-12、jsonschema/referencing、FastAPI、Playwright、AgentMentor 文档与知识校验。

---

## 文件结构与职责

| 路径 | 职责 |
| --- | --- |
| `RpaClaw/backend/rpa_agent/__init__.py` | 新领域包入口，不承载兼容代码 |
| `RpaClaw/backend/rpa_agent/README.md` | 说明领域边界、允许依赖和当前非能力 |
| `RpaClaw/backend/tests/test_rpa_agent_architecture_boundary.py` | 自动阻止新包导入旧 `backend.rpa` 领域实现 |
| `RpaClaw/backend/tests/contracts/` | 保存创建态上游契约测试向量和验证入口 |
| `docs/rpa-agent/contracts/` | ScienceClaw 仓库内的正式数据模型与 JSON Schema 副本 |
| `docs/rpa-agent/README.md` | 新旧 RPA 文档权威顺序和导航入口 |
| `docs/DESIGN_STATUS.md` | 标记新链路当前权威规格和旧链路适用范围 |
| `docs/project/agent-architecture-onboarding.md` | 告诉接手者如何选择新旧链路入口 |
| `docs/evidence/EV-027-rpa-agent-host-rebuild-baseline.md` | 记录增量 0 的命令、结果、局限和下一步门槛 |

### Task 1: 修复 Route 单测对本地 Browser-use 配置的依赖

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_route_trace.py:804`
- Test: `RpaClaw/backend/tests/test_rpa_route_trace.py`

- [ ] **Step 1: 把现有测试改成确定性复现配置泄漏**

在 `test_chat_agent_done_reports_run_trace_count_not_session_total` 中，`FakeRecordingRuntimeAgent` 定义后、现有 monkeypatch 前加入：

```python
    class UnexpectedBrowserUseOperator:
        def __init__(self, *args, **kwargs):
            raise AssertionError("route test must not construct the configured live operator")

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_recording_operator", "browser_use")
    monkeypatch.setattr(
        ROUTE_MODULE,
        "BrowserUseRecordingOperator",
        UnexpectedBrowserUseOperator,
    )
```

保留现有这一行以证明它无法隔离 operator factory：

```python
    monkeypatch.setattr(ROUTE_MODULE, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
```

- [ ] **Step 2: 运行单测并确认失败发生在错误 operator 被构造**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest -q RpaClaw/backend/tests/test_rpa_route_trace.py::test_chat_agent_done_reports_run_trace_count_not_session_total
```

Expected: FAIL，包含 `route test must not construct the configured live operator`；不得访问网络。

- [ ] **Step 3: 在测试中替换真正的依赖边界**

删除 `UnexpectedBrowserUseOperator`、对应 Browser-use monkeypatch 和 `RecordingRuntimeAgent` monkeypatch，只保留配置被强制设为 Browser-use，并加入：

```python
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_recording_operator", "browser_use")
    monkeypatch.setattr(
        ROUTE_MODULE,
        "_build_recording_operator",
        lambda _model_config: FakeRecordingRuntimeAgent(),
    )
```

这样测试替换的是 Route 实际调用的 factory，而不是 factory 内部某个可能不会被选择的实现类。

- [ ] **Step 4: 验证目标测试和 Route 文件全量测试**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest -q RpaClaw/backend/tests/test_rpa_route_trace.py
```

Expected: PASS，且输出中没有真实 LLM 请求或 `insufficient_quota`。

- [ ] **Step 5: 提交离线隔离修复**

```powershell
git add RpaClaw/backend/tests/test_rpa_route_trace.py
git commit -m "test: isolate recording operator selection"
```

### Task 2: 把已确认数据模型导入 ScienceClaw 并接入契约验证

**Files:**
- Create: `docs/rpa-agent/contracts/RPA Agent Core Trace v0.1 数据模型设计.md`
- Create: `docs/rpa-agent/contracts/RPA Agent Core Trace v0.1 JSON Schema.json`
- Create: `docs/rpa-agent/contracts/RPA Agent TraceCandidate 与 BrowserFact v0.1 数据模型设计.md`
- Create: `docs/rpa-agent/contracts/RPA Agent SettlementResult v0.1 数据模型设计.md`
- Create: `docs/rpa-agent/contracts/RPA Agent创建态上游模型 v0.1 JSON Schema.json`
- Create: `docs/rpa-agent/contracts/RPA Agent创建态上游模型 v0.1 契约测试设计.md`
- Create: `RpaClaw/backend/tests/contracts/upstream_model_schema_cases.json`
- Create: `RpaClaw/backend/tests/contracts/validate_upstream_model_schema.py`
- Create: `RpaClaw/backend/tests/contracts/test_rpa_agent_contract_artifacts.py`

- [ ] **Step 1: 复制六份已确认契约材料和两份契约测试资产**

从 `E:\RPA-Agent` 根设计目录执行机械复制；内容必须逐字一致，不在导入时重新解释 Schema：

```powershell
New-Item -ItemType Directory -Force docs/rpa-agent/contracts | Out-Null
New-Item -ItemType Directory -Force RpaClaw/backend/tests/contracts | Out-Null
Copy-Item -LiteralPath 'E:\RPA-Agent\docs\design\RPA Agent Core Trace v0.1 数据模型设计.md' -Destination 'docs\rpa-agent\contracts\RPA Agent Core Trace v0.1 数据模型设计.md'
Copy-Item -LiteralPath 'E:\RPA-Agent\docs\design\RPA Agent Core Trace v0.1 JSON Schema.json' -Destination 'docs\rpa-agent\contracts\RPA Agent Core Trace v0.1 JSON Schema.json'
Copy-Item -LiteralPath 'E:\RPA-Agent\docs\design\RPA Agent TraceCandidate 与 BrowserFact v0.1 数据模型设计.md' -Destination 'docs\rpa-agent\contracts\RPA Agent TraceCandidate 与 BrowserFact v0.1 数据模型设计.md'
Copy-Item -LiteralPath 'E:\RPA-Agent\docs\design\RPA Agent SettlementResult v0.1 数据模型设计.md' -Destination 'docs\rpa-agent\contracts\RPA Agent SettlementResult v0.1 数据模型设计.md'
Copy-Item -LiteralPath 'E:\RPA-Agent\docs\design\RPA Agent创建态上游模型 v0.1 JSON Schema.json' -Destination 'docs\rpa-agent\contracts\RPA Agent创建态上游模型 v0.1 JSON Schema.json'
Copy-Item -LiteralPath 'E:\RPA-Agent\docs\design\RPA Agent创建态上游模型 v0.1 契约测试设计.md' -Destination 'docs\rpa-agent\contracts\RPA Agent创建态上游模型 v0.1 契约测试设计.md'
Copy-Item -LiteralPath 'E:\RPA-Agent\tests\contracts\upstream_model_schema_cases.json' -Destination 'RpaClaw\backend\tests\contracts\upstream_model_schema_cases.json'
Copy-Item -LiteralPath 'E:\RPA-Agent\tests\contracts\validate_upstream_model_schema.py' -Destination 'RpaClaw\backend\tests\contracts\validate_upstream_model_schema.py'
```

- [ ] **Step 2: 先写会因仓库内路径不匹配而失败的 pytest 包装测试**

创建 `RpaClaw/backend/tests/contracts/test_rpa_agent_contract_artifacts.py`：

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATOR_PATH = Path(__file__).with_name("validate_upstream_model_schema.py")


def test_rpa_agent_contract_artifacts_validate() -> None:
    spec = importlib.util.spec_from_file_location(
        "rpa_agent_contract_validator",
        VALIDATOR_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.PROJECT_ROOT == REPO_ROOT
    assert module.main() == 0
```

- [ ] **Step 3: 运行测试并确认复制脚本仍指向旧外部目录**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest -q RpaClaw/backend/tests/contracts/test_rpa_agent_contract_artifacts.py
```

Expected: FAIL，原因是 `PROJECT_ROOT` 或 `DESIGN_DIR` 未指向 ScienceClaw 仓库内 `docs/rpa-agent/contracts`。

- [ ] **Step 4: 修改复制后的验证器路径，不修改验证语义**

把 `validate_upstream_model_schema.py` 顶部常量替换为：

```python
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DESIGN_DIR = PROJECT_ROOT / "docs" / "rpa-agent" / "contracts"
UPSTREAM_SCHEMA_PATH = DESIGN_DIR / "RPA Agent创建态上游模型 v0.1 JSON Schema.json"
CORE_TRACE_SCHEMA_PATH = DESIGN_DIR / "RPA Agent Core Trace v0.1 JSON Schema.json"
CASES_PATH = Path(__file__).with_name("upstream_model_schema_cases.json")
UPSTREAM_SCHEMA_ID = (
    "https://rpa-agent.local/schemas/skill-creation-upstream-v0.1.json"
)
```

- [ ] **Step 5: 验证 Schema 自身、锚点引用和全部正反例**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest -q RpaClaw/backend/tests/contracts/test_rpa_agent_contract_artifacts.py
python RpaClaw/backend/tests/contracts/validate_upstream_model_schema.py
```

Expected: pytest PASS；验证器最后输出 `failed=0`，总用例数与导入的 cases 文件一致。

- [ ] **Step 6: 提交契约入口**

```powershell
git add docs/rpa-agent/contracts RpaClaw/backend/tests/contracts
git commit -m "docs: import rpa agent data contracts"
```

### Task 3: 建立 `backend/rpa_agent` 最小包和旧领域依赖护栏

**Files:**
- Create: `RpaClaw/backend/tests/test_rpa_agent_architecture_boundary.py`
- Create: `RpaClaw/backend/rpa_agent/__init__.py`
- Create: `RpaClaw/backend/rpa_agent/README.md`

- [ ] **Step 1: 先写包存在性和 import 边界测试**

创建 `RpaClaw/backend/tests/test_rpa_agent_architecture_boundary.py`：

```python
from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "rpa_agent"
FORBIDDEN_MODULE = "backend.rpa"


def _forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            if module == FORBIDDEN_MODULE or module.startswith(f"{FORBIDDEN_MODULE}."):
                violations.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno} -> {module}")
    return violations


def test_rpa_agent_package_exists() -> None:
    assert (PACKAGE_ROOT / "__init__.py").is_file()


def test_rpa_agent_does_not_import_legacy_rpa_domain() -> None:
    python_files = sorted(PACKAGE_ROOT.rglob("*.py"))
    assert python_files, "rpa_agent package must contain Python source"
    violations = [item for path in python_files for item in _forbidden_imports(path)]
    assert violations == []
```

- [ ] **Step 2: 运行测试并确认新领域包尚不存在**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest -q RpaClaw/backend/tests/test_rpa_agent_architecture_boundary.py
```

Expected: FAIL at `test_rpa_agent_package_exists`。

- [ ] **Step 3: 创建最小包，不复制旧实现**

创建 `RpaClaw/backend/rpa_agent/__init__.py`：

```python
"""RPA Agent greenfield domain package.

The package starts empty on purpose. Domain capabilities are added only through
contract-backed vertical slices; legacy ``backend.rpa`` objects are not imported.
"""
```

创建 `RpaClaw/backend/rpa_agent/README.md`：

```markdown
# RPA Agent 新领域核心

本目录承载 F026 定义的新 RPA Agent 创建态、CoreTrace、编译和运行边界。

允许依赖 ScienceClaw 的通用浏览器、认证、模型、文件和 Skill 宿主接口；禁止导入 `backend.rpa` 中的旧 Trace、Manager、Session 和 Compiler。需要复用的底层机制必须以新接口移植，并由契约测试证明。

当前仅建立领域边界，不代表 CoreTrace 业务能力已经实现。进入业务实现前先阅读 `docs/decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md` 和 F026。
```

- [ ] **Step 4: 验证边界测试**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest -q RpaClaw/backend/tests/test_rpa_agent_architecture_boundary.py
```

Expected: `2 passed`。

- [ ] **Step 5: 用反向探针证明护栏有效，然后立即撤销探针**

临时在 `__init__.py` 末尾加入 `from backend.rpa.models import RPAAcceptedTrace`，运行同一测试，Expected: `test_rpa_agent_does_not_import_legacy_rpa_domain` FAIL 并指出文件、行号和模块。随后删除该临时 import，再运行，Expected: `2 passed`。临时探针不得进入提交。

- [ ] **Step 6: 提交新领域边界**

```powershell
git add RpaClaw/backend/rpa_agent RpaClaw/backend/tests/test_rpa_agent_architecture_boundary.py
git commit -m "chore: establish rpa agent domain boundary"
```

### Task 4: 更新仓库内的新旧架构导航

**Files:**
- Create: `docs/rpa-agent/README.md`
- Modify: `docs/DESIGN_STATUS.md`
- Modify: `docs/project/agent-architecture-onboarding.md`

- [ ] **Step 1: 创建新链路导航入口**

创建 `docs/rpa-agent/README.md`：

```markdown
# RPA Agent 新链路文档入口

## 权威顺序

1. `docs/decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md`
2. `docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md`
3. `docs/superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md`
4. `docs/rpa-agent/contracts/` 中的 v0.1 数据模型与 JSON Schema
5. `RpaClaw/backend/rpa_agent/` 源码和测试

## 新旧边界

新 RPA Agent 使用 `TraceCandidate / BrowserFact -> SettlementResult -> CoreTrace -> Compiler -> Skill`。旧 `RpaClaw/backend/rpa/` 和 F025 只提供技术穿刺经验，不是新领域实现基线；不得为兼容旧数据而改变 CoreTrace 契约。

## 当前状态

F026 处于 active。增量 0 只建立契约、离线验证和架构护栏；CoreTrace 业务实现从后续首个纵向切片开始。
```

- [ ] **Step 2: 在设计状态页顶部新增当前权威项**

在 `docs/DESIGN_STATUS.md` 的 `## Current Or Implemented` 前插入：

```markdown
## Current RPA Agent Rebuild

- `docs/decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md`
  - 新 RPA Agent 的当前项目级决策：复用 ScienceClaw 宿主，在 `backend/rpa_agent` 绿地重建领域核心。
- `docs/superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md`
  - 已确认的宿主边界、非兼容原则、切换门槛和增量路线。
- `docs/rpa-agent/contracts/`
  - CoreTrace 与创建态上游模型的 v0.1 规格和机器契约。

旧 `backend/rpa` 相关设计仍适用于 ScienceClaw 现有旧链路，但不得作为 F026 新链路的数据模型或 Compiler 权威来源。
```

- [ ] **Step 3: 在接手导航开头加入分流规则**

在 `docs/project/agent-architecture-onboarding.md` 开头说明段之后插入：

```markdown
> RPA 分流：修改现有 ScienceClaw 旧录制链路时继续按本文的 accepted trace 路径定位；开发 F026 新 RPA Agent 时，先读 `docs/rpa-agent/README.md` 和 ADR-006，只在 `backend/rpa_agent` 建立新领域能力。两条路径在切换前共存，但不做数据模型兼容或双写。
```

- [ ] **Step 4: 检查导航链接和禁用含糊状态词**

Run:

```powershell
rg -n "ADR-006|F026|backend/rpa_agent|docs/rpa-agent/contracts" docs/DESIGN_STATUS.md docs/project/agent-architecture-onboarding.md docs/rpa-agent/README.md
rg -n "T[B]D|T[O]DO|F[I]XME" docs/rpa-agent docs/DESIGN_STATUS.md docs/project/agent-architecture-onboarding.md
```

Expected: 第一条命令在三个入口文件均有命中；第二条命令无输出。

- [ ] **Step 5: 提交导航更新**

```powershell
git add docs/rpa-agent/README.md docs/DESIGN_STATUS.md docs/project/agent-architecture-onboarding.md
git commit -m "docs: route rpa agent rebuild architecture"
```

### Task 5: 形成增量 0 的可重复验证证据

**Files:**
- Create: `docs/evidence/EV-027-rpa-agent-host-rebuild-baseline.md`
- Modify: `docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md`

- [ ] **Step 1: 运行目标验证矩阵**

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q RpaClaw/backend/tests/test_rpa_agent_architecture_boundary.py RpaClaw/backend/tests/contracts/test_rpa_agent_contract_artifacts.py RpaClaw/backend/tests/test_rpa_route_trace.py
python RpaClaw/backend/tests/contracts/validate_upstream_model_schema.py
$knowledgeOutput = & python 'C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py' --root . --docs-path docs --strict 2>&1
$currentErrors = $knowledgeOutput | Select-String 'ADR-006-rpa-agent-scienceclaw-host-greenfield-core|F026-rpa-agent-scienceclaw-host-rebuild'
if ($currentErrors) { $currentErrors; exit 1 }
Write-Output 'F026 and ADR-006 have no strict knowledge-check errors; legacy repository debt remains separately visible.'
git diff --check
```

Expected: 所有 pytest 通过；Schema 验证 `failed=0`；F026/ADR-006 定向知识校验退出码为 0；`git diff --check` 无输出。ScienceClaw 现存旧知识文档不符合当前 AgentMentor 模板，全仓 strict 结果作为既有文档债务记录，不作为 F026 增量 0 的伪失败或顺手重写范围。

- [ ] **Step 2: 创建 Evidence，记录实际结果而非预期结果**

创建 `docs/evidence/EV-027-rpa-agent-host-rebuild-baseline.md`，使用以下完整结构，并把命令输出中的实际测试数量写入 Results：

```markdown
---
id: EV-027
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
created: 2026-07-17
updated: 2026-07-17
evidence_level: automated_contract
---

# EV-027：RPA Agent 宿主重构增量 0 基线

## Supports Claim

本证据仅证明 F026 已具备仓库内正式契约入口、新领域空包、旧领域 import 护栏和离线可重复验证；不证明 CoreTrace 采集、结算、编译或回放已经实现。

## Verification Scope

- Route operator factory 的离线隔离
- CoreTrace 与创建态上游 JSON Schema 自检和正反例
- `backend/rpa_agent` 包存在性与旧领域 import 禁止规则
- ADR、Feature、规格和 Evidence 的知识结构

## Commands

记录 Task 5 Step 1 中五组实际执行命令。

## Results

记录每组命令的实际通过数量、Schema passed/failed/total、知识校验结果和 diff 检查结果。

## Limitations

- 尚未实现 TraceCandidate、BrowserFact、SettlementResult 或 CoreTrace Python 模型。
- 尚未接入 Recorder UI、Browser-use、Compiler 或 Playwright 回放。
- 尚未定义 DataAsset v0.1。

## Next Gate

只有在本 Evidence 的全部自动检查通过后，才设计并实施“单一人工动作 -> CoreTrace -> Playwright 回放”的首个纵向切片。
```

“记录”不是保留占位文字：执行时必须把命令和结果原样摘要写入相应小节，Evidence 中不得留下 `记录` 二字。

- [ ] **Step 3: 更新 F026 的增量 0 验收状态**

仅将有 EV-027 直接支持的 Acceptance Criteria 勾选为 `[x]`，并在 Acceptance Map 对应行把 Evidence 改为 `EV-027`、Status 改为 `pass`。首个纵向切片和后续业务矩阵继续保持 pending。

- [ ] **Step 4: 重新运行知识校验和工作树检查**

Run:

```powershell
$knowledgeOutput = & python 'C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py' --root . --docs-path docs --strict 2>&1
$currentErrors = $knowledgeOutput | Select-String 'ADR-006-rpa-agent-scienceclaw-host-greenfield-core|F026-rpa-agent-scienceclaw-host-rebuild'
if ($currentErrors) { $currentErrors; exit 1 }
Write-Output 'F026 and ADR-006 have no strict knowledge-check errors; legacy repository debt remains separately visible.'
git diff --check
git status --short
```

Expected: F026/ADR-006 定向知识校验和 diff 检查通过；状态只包含本计划预期的 Evidence 与 F026 更新。

- [ ] **Step 5: 提交增量 0 Evidence**

```powershell
git add docs/evidence/EV-027-rpa-agent-host-rebuild-baseline.md docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
git commit -m "docs: verify rpa agent host rebuild baseline"
```

## 自检结果

- 规格覆盖：本计划覆盖隔离分支之后的契约导入、测试隔离、领域目录、依赖护栏、文档导航和 Evidence；明确不覆盖 CoreTrace 业务实现、DataAsset 和 UI 切换。
- 文件职责：新领域包、契约、测试、导航和证据分别存放，未把兼容代码塞入新包。
- 类型一致性：本增量不定义 Python 领域类型；Schema 的名称和路径与已确认的 v0.1 文件一致。
- 规则治理：本计划不修改 `AGENTS.md`。若要把 ADR-006 的边界提升为仓库级强制规则，必须另行获得用户明确授权并通过 project-rules gate。
