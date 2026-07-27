# F020 区域与元素选择 Harness 交接记录

日期：2026-05-30
工作区：`E:\Work-Project\OtherWork\ScienceClaw`
当前目标：把 F020 剩余三个切片依次交给新会话执行，避免依赖旧会话长上下文。

## 交接结论

F020 不需要升级为 Harness v2。当前问题仍属于 Harness v1.1 的能力补齐：让区域选择与元素选择从 capture、user-input replay、full-live profile、expected signals、post-capture asset、Skill replay 形成可模拟、可断言、可审查的闭环。

F020 第一切片已经完成并通过本地验证。剩余三个切片建议按顺序推进：

1. F020.2：补 controlled asset / fixture，把拖拽区域与点选元素跑进 Harness runner。
2. F020.3：录制真实 region / element selection asset，并按资产审查流程保持 `candidate-lite` 或 `captured`，不得自动升级为 blocking baseline。
3. F020.4：补覆盖矩阵，把区域提取、锚定提取、元素点选动作、F019 下载副作用组合、runtime-AI fallback 的覆盖状态说清楚。

## 必读锚点

- Feature：`docs/features/F020-rpa-harness-region-element-selection-simulation.md`
- Evidence：`docs/evidence/EV-020-rpa-harness-region-element-selection-simulation.md`
- 下载副作用 Feature：`docs/features/F019-rpa-harness-controlled-download-side-effects.md`
- 下载副作用 Evidence：`docs/evidence/EV-019-rpa-harness-controlled-download-side-effects.md`
- 风险待办：`docs/rpa/harness/v1.1-region-selection-download-risk-todo.md`
- 资产录制与审查流程：`docs/rpa/harness/资产录制与审查最小流程.md`
- Backlog：`docs/BACKLOG.md`

新会话开始后先读上述文件，再运行 `git status --short`。当前工作树包含大量与 F020 无关的 dirty state，不要为了“清爽”恢复或删除它们。

## 已完成：F020.1

已完成能力：

- `user_input_replay` 能保留顶层 `region_context`、`region_scope`、`signals.region_selection`。
- `full_live_profile` 能把 replay event 中的 region evidence 送进 runtime planner payload。
- 点选元素不引入新的 `element_context` 主路径，只作为 `region_context.acquisition = picked_element`。
- `expected_signals` 与 `compiler_signals.must_preserve_region_context` 保留 `acquisition`。

涉及文件：

- `RpaClaw/backend/rpa/harness/user_input_replay.py`
- `RpaClaw/backend/rpa/harness/full_live_profile.py`
- `RpaClaw/backend/rpa/harness/expected_signals.py`
- `RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py`
- `RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py`
- `RpaClaw/backend/tests/test_rpa_harness_expected_signals.py`
- `docs/features/F020-rpa-harness-region-element-selection-simulation.md`
- `docs/evidence/EV-020-rpa-harness-region-element-selection-simulation.md`

已验证：

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py `
  RpaClaw/backend/tests/test_rpa_harness_expected_signals.py `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py
```

结果：`43 passed in 25.92s`。

Harness 结构检查：

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py `
  --root E:\Work-Project\OtherWork\ScienceClaw `
  --docs-path docs `
  --strict
```

结果：`Scanned 229 markdown file(s). Checked 44 knowledge artifact(s). Errors: 0. Warnings: 0.`

## 剩余切片

### F020.2 Controlled Asset / Fixture

目标：

- 构造或固化一个 controlled HTML / asset，覆盖拖拽区域选择与点选元素两种 acquisition。
- 让该资产至少跑通 user-input replay、full-live profile、expected signals；能接入 post-capture / Skill replay 的部分优先接入。
- 如果场景包含“区域内点击列表第一行名称触发下载”，只引用 F019 的 `controlled_download` side-effect lane，不在 F020 重写下载模拟能力。

验收：

- controlled fixture 中的 region facts 在 runner 输出中可见，包括 `region_context`、`region_scope`、`acquisition`。
- 点选元素仍然被表达为通用 region acquisition，不新增 `element_context`。
- 下载副作用若出现，必须走 F019 现有 contract，并在 F020 Evidence 中标注为组合验证。

不做：

- 不接 iframe。
- 不开 Harness v2。
- 不把下载动作归并进 F020。

### F020.3 Real Capture Asset

目标：

- 录制一份真实区域选择 / 元素选择资产，用来证明 capture 环节本身也能留下可审查证据。
- 生成或更新 Review Packet，记录人为期望、expected signals、sensitivity 状态。

验收：

- asset 中能看到 region / element acquisition 的 recorded facts。
- `review.md` 或 triage report 明确写出人工验收预期。
- 未经人工确认 expected signals 和 sensitivity 前，资产只能保持 `captured` / `candidate-lite`，不得进入 `candidate` 或 `golden`。

不做：

- 不把 `runtime_status=success` 当成资产通过。
- 不手改 governance JSON 绕过审查。
- 不为单一站点补 Harness 经验规则。

### F020.4 Coverage Matrix

目标：

- 增补一张 F020 / Harness v1.1 覆盖矩阵，说明哪些能力已由测试、controlled asset、真实 asset、F019 组合覆盖，哪些仍是 future work。

建议矩阵维度：

- 自由文本区域提取。
- 带 section/container anchor 的区域提取。
- 点选元素 acquisition。
- 区域内动作，例如点击列表第一行名称。
- 下载副作用，引用 F019。
- runtime-AI fallback。
- iframe 内元素点选，明确标为 future feature，不属于 F020 当前切片。

验收：

- 矩阵链接 F020 / EV020 / F019 / EV019。
- 每个能力格子都有证据来源或残余风险。
- Backlog 更新下一步状态。

## 强约束

- 不要开启 Harness v2；当前仍是 v1.1 补齐。
- 不要新增 `element_context` 后端主链路；元素选择是 `region_context` 的 acquisition。
- 不要把 F019 与 F020 合并；F019 负责 controlled download side effect，F020 负责 region / element selection simulation。
- 不要混入 iframe 修复；iframe 是单独专题。
- 不要自动 promotion 真实资产；promotion 是人工治理动作。
- 不要恢复或清理与 F020 无关的 dirty state，尤其是已有的 `data/rpa_harness_assets_bootstrap/**` 删除和大量临时文件。

## 当前工作树提醒

已知 F020 相关 dirty 文件包括：

- `RpaClaw/backend/rpa/harness/expected_signals.py`
- `RpaClaw/backend/rpa/harness/full_live_profile.py`
- `RpaClaw/backend/rpa/harness/user_input_replay.py`
- `RpaClaw/backend/tests/test_rpa_harness_expected_signals.py`
- `RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py`
- `RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py`
- `docs/BACKLOG.md`
- `docs/features/F020-rpa-harness-region-element-selection-simulation.md`
- `docs/evidence/EV-020-rpa-harness-region-element-selection-simulation.md`
- `docs/rpa/harness/v1.1-region-selection-download-risk-todo.md`
- 本文件

已知非 F020 相关 dirty state：

- `data/rpa_harness_assets_bootstrap/**` 有大量 tracked deletion。
- `tmp-*`、`.pytest-*`、`Skills/**`、`data/**` 下有大量 untracked 文件。
- `git status` 可能出现若干 permission denied warning；不要把这些 warning 误判成 F020 failure。

## 新会话推荐启动顺序

1. 读取本 handoff、F020、EV020、F019、EV019、资产录制与审查流程。
2. 运行 `git status --short`，只关注本切片需要触碰的文件。
3. 从 F020.2 开始，先写 RED test 或 controlled fixture 验证失败，再实现。
4. 每完成一个切片，更新 F020 / EV020 / Backlog，并运行相关 pytest、`knowledge_check.py --strict`、`git diff --check`。
5. F020.3 涉及真实资产时，严格按资产审查流程记录 expected signals 和 sensitivity；没有人工确认就只做 `candidate-lite` 或 `captured`。

## Closeout

Closeout verdict: pass
Completion claim allowed: yes, limited to handoff readiness.

Entry Gate: pass. 本 handoff 面向已存在的 F020 active Feature 和 EV020 Evidence，不开启新 Feature。
Vision Anchor: pass. 仍坚持 Harness v1.1 补齐，元素点选作为 region acquisition，不引入 `element_context`。
Evidence: standard. 交接文档记录已完成切片、剩余切片、验证命令、风险边界和 dirty worktree 状态。
Feature: F020 active，第一切片已实现；F020.2/F020.3/F020.4 待顺序执行。
ADR: not triggered. 沿用既有 Trace-first / asset-driven Harness 决策。
Lesson: not triggered. 当前是交接，不是新事故复盘。
Check: pass. `knowledge_check.py --strict` 扫描 230 个 Markdown 文件、检查 44 个 Harness artifact，0 errors / 0 warnings；`git diff --check` 仅出现 `docs/BACKLOG.md` 的 CRLF 提示。
