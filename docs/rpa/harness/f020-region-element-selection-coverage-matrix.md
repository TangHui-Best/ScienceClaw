# F020 区域与元素选择 Harness 覆盖矩阵

日期：2026-05-30
范围：F020 RPA Harness Region and Element Selection Simulation
关联：F020 / EV-020 / F019 / EV-019

## 目的

这份矩阵回答一个边界问题：当前 Harness v1.1 对“区域选择”和“元素选择”到底能证明什么，不能证明什么。

核心判断：

```text
Harness coverage proves observable, replayable, reviewable evidence boundaries.
It does not prove global RPA Agent correctness.
```

因此矩阵只记录可运行、可断言、可审查的能力增量；真实资产进入 blocking baseline 仍然需要人工确认 expected signals 与 sensitivity。

## 覆盖矩阵

| 能力场景 | 当前覆盖级别 | 证据来源 | 不证明什么 | 下一步 / 残余风险 |
| --- | --- | --- | --- | --- |
| 自由文本区域提取 | unit-test + controlled fixture | EV-020；`test_user_input_replay_reports_controlled_region_and_picked_element_acquisitions`；`test_full_live_profile_reports_controlled_drag_and_picked_element_acquisitions` | 不证明所有自由文本区域都能被 planner 正确理解 | 继续用真实 capture asset 扩充样本，但不得自动 promotion |
| 带 section/container anchor 的区域提取 | unit-test + existing region context path | F011；EV-020；`RecordingRuntimeAgent` region scope compact path | 不证明 anchor 缺失时一定能确定性编译 | 缺 anchor 的场景保留 runtime-AI fallback，不把现场文本硬编码进 Skill |
| 点选元素 acquisition | unit-test + controlled fixture | EV-020；`acquisition=picked_element` 在 user-input replay、full-live profile、expected signals 中保留 | 不证明需要新的 `element_context` | 继续坚持元素点选是 region acquisition，不新建后端主链路 |
| 区域内动作：点击列表第一行名称 | controlled fixture | EV-020；F020.2 controlled picked-element fixture | 不证明真实站点列表排序、虚拟滚动、动态加载都稳定 | 真实资产只能进入 captured/candidate-lite，人工确认后再考虑 candidate |
| 点击列表第一行名称触发下载 | F019 controlled download + F020 composition | F019；EV-019；F020 只引用 `controlled_download` side-effect lane | 不证明下载能力属于 F020，也不证明 live URL 下载稳定 | 下载副作用继续归 F019；F020 只验证区域/元素选择事实能与下载 side effect 组合 |
| expected signals 保存 region acquisition | unit-test | EV-020；`test_region_scoped_trace_expected_signals_preserve_selected_region_semantics` | 不证明自动生成的 expected signals 已经人工正确审查 | 人工 review 前不得作为 blocking baseline |
| captured asset review 可审查 region acquisition | unit-test + review packet behavior | EV-020；`test_review_packet_surfaces_region_acquisition_without_promoting_asset` | 不证明 `runtime_status=success` 等于业务正确 | Review Packet 只呈现 recorded facts；promotion 仍是人工治理动作 |
| full-live planner 接收 region acquisition | controlled fixture | EV-020；`snapshot.region_scope.acquisition` 到达 planner payload | 不证明模型一定会按 region 正确操作 | 失败时先看 raw/compact snapshot 与 planner payload，不直接补经验规则 |
| post-capture / Skill replay 链路 | controlled fixture + existing F019/F017 path | EV-020；F017/F019 runner；full-live `post_capture.scenario_count` | 不证明生成 Skill 已覆盖所有泛化边界 | 若 Skill 硬编码现场值，归 TraceSkillCompiler/generalization 跟进，不在 F020 扩张 |
| runtime-AI fallback | observable boundary | F017；EV-020；full-live profile | 不证明 fallback 一定成功，只证明 Harness 能观察该路径 | 对缺 anchor 的区域提取保留 runtime-AI，不用全局非空校验替代诊断 |
| iframe 内元素点选 | future / not covered | v1.1 risk TODO V11-RD-007 | F020 当前不证明 iframe frame mapping、frame_rect 或 frame_path 正确 | 独立 iframe Feature / scenario 后再做，不混入 F020 |

## Promotion 边界

- `captured`：记录事实，不能作为通过。
- `candidate-lite`：非阻塞观察层，可以用于诊断和报告，不污染 blocking baseline。
- `candidate` / `golden`：必须人工确认 expected signals 与 sensitivity 后才允许进入 blocking baseline。

F020 允许产生或审查 captured / candidate-lite region-selection asset，但不得由 Agent 自动升级为 candidate / golden。

## 与 F019 的关系

F019 负责 controlled download side effect。F020 可以组合引用 F019 的下载信号，但不重新定义下载 replay、下载路由、下载文件校验或 Skill 下载输出 contract。

换句话说：

```text
F019 answers: did the download side effect happen in a controlled, verifiable way?
F020 answers: did the selected region / picked element evidence survive Harness simulation boundaries?
```

## 当前结论

F020.1-F020.4 完成后，Harness v1.1 对区域选择与元素选择的覆盖从“字段可能存在”推进到“受控 fixture 可回放、full-live 可传递、Review Packet 可审查、覆盖边界可恢复”。

剩余风险不是 Harness v2 问题，而是后续资产治理与真实场景扩充问题。
